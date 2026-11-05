"""Fraud analytics (U3), sisi database: data analitik, run analisis, sinyal, dan telaah.

Analisisnya sendiri ada di mab_pipeline.fraud (murni, tanpa database). Modul ini:
  - mengisi data analitik dari riwayat impor (CSV/XLSX) dan dari klaim platform yang diproses
  - menjalankan analisis per tenant dan menyimpan run + sinyal
  - menggabungkan sinyal dengan hasil telaah investigator (bertahan lintas run)
Sinyal fraud tidak pernah mengubah status, rekomendasi, atau skor risiko klinis klaim.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mab_api.models import Claim, FraudClaimRecord, FraudReview, FraudRun, FraudSignal
from mab_pipeline.fraud import ClaimRecord, FraudRuleSet, RowError, analyze, record_from_row

REVIEW_STATUSES = ("INVESTIGATING", "CONFIRMED", "DISMISSED")
KEEP_RUNS = 5
MAX_IMPORT_ROWS = 50_000


@dataclass
class ImportResult:
    created: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.errors and not (self.created or self.updated):
            return "FAILED"
        return "PARTIAL" if self.errors else "SUCCESS"

    def summary(self) -> dict:
        return {"created": self.created, "updated": self.updated, "errors": self.errors[:50], "error_count": len(self.errors)}


def _columns(r: ClaimRecord) -> dict:
    return {"member_id": r.member_id, "member_name": r.member_name, "address": r.address, "bank_account": r.bank_account,
            "hospital_name": r.hospital, "doctor_name": r.doctor, "referral_from": r.referral_from, "icd10": r.icd10,
            "admission_date": r.admission_date, "discharge_date": r.discharge_date, "billed_amount": r.billed_amount,
            "lab_panels": r.lab_panels}


def import_history(db: Session, insurer_id: str, rows: list[dict]) -> ImportResult:
    """Impor riwayat klaim (kolom lihat mab_pipeline.fraud.HISTORY_COLUMNS). Upsert per nomor klaim."""
    result = ImportResult()
    if len(rows) > MAX_IMPORT_ROWS:
        result.errors.append(f"maksimal {MAX_IMPORT_ROWS} baris per impor")
        return result
    existing = {r.claim_number: r for r in db.scalars(select(FraudClaimRecord).where(FraudClaimRecord.insurer_id == insurer_id))}
    seen: set[str] = set()
    for i, row in enumerate(rows, start=2):  # baris 1 = header
        try:
            rec = record_from_row(row)
        except RowError as exc:
            result.errors.append(f"baris {i}: {exc}")
            continue
        if rec.claim_number in seen:
            result.errors.append(f"baris {i}: nomor_klaim {rec.claim_number} duplikat di file")
            continue
        seen.add(rec.claim_number)
        row_obj = existing.get(rec.claim_number)
        if row_obj is not None and row_obj.source == "PLATFORM":
            # klaim platform: lengkapi rekening/alamat/rujukan dari sistem inti, data dokumen tetap dari platform
            for key in ("member_name", "address", "bank_account", "referral_from"):
                value = getattr(rec, key)
                if value:
                    setattr(row_obj, key, value)
            result.updated += 1
            continue
        if row_obj is None:
            db.add(FraudClaimRecord(insurer_id=insurer_id, claim_number=rec.claim_number, source="HISTORY", **_columns(rec)))
            result.created += 1
        else:
            for key, value in _columns(rec).items():
                setattr(row_obj, key, value)
            result.updated += 1
    db.flush()
    return result


def upsert_platform_record(db: Session, claim: Claim, *, doctor: str | None, lab_panels: int | None,
                           icd10: str | None) -> FraudClaimRecord:
    """Klaim yang selesai diproses pipeline masuk data analitik (dipanggil dari tasks.process_claim)."""
    rec = db.scalar(select(FraudClaimRecord).where(FraudClaimRecord.insurer_id == claim.insurer_id,
                                                   FraudClaimRecord.claim_number == claim.claim_number))
    if rec is None:
        rec = FraudClaimRecord(insurer_id=claim.insurer_id, claim_number=claim.claim_number)
        db.add(rec)
    rec.claim_id = claim.id
    rec.source = "PLATFORM"
    rec.member_id = claim.member_id
    rec.member_name = rec.member_name or claim.patient_name
    rec.hospital_name = claim.hospital_name
    rec.doctor_name = doctor or rec.doctor_name
    rec.icd10 = icd10 or claim.primary_icd10 or rec.icd10
    rec.admission_date = claim.admission_date
    rec.discharge_date = claim.discharge_date
    rec.billed_amount = claim.billed_amount
    rec.lab_panels = lab_panels
    return rec


def to_record(r: FraudClaimRecord) -> ClaimRecord:
    return ClaimRecord(
        claim_number=r.claim_number, member_id=r.member_id, hospital=r.hospital_name, admission_date=r.admission_date,
        discharge_date=r.discharge_date, billed_amount=int(r.billed_amount), icd10=r.icd10, doctor=r.doctor_name,
        lab_panels=r.lab_panels, member_name=r.member_name, address=r.address, bank_account=r.bank_account,
        referral_from=r.referral_from, source=r.source,
    )


def run_analysis(db: Session, insurer_id: str, ruleset: FraudRuleSet, user_id: str | None = None) -> FraudRun:
    records = [to_record(r) for r in db.scalars(select(FraudClaimRecord).where(FraudClaimRecord.insurer_id == insurer_id))]
    report = analyze(records, ruleset)
    run = FraudRun(insurer_id=insurer_id, ruleset_version=report.ruleset_version, record_count=report.record_count,
                   signal_count=len(report.signals), entities=[dataclasses.asdict(e) for e in report.entities],
                   created_by_id=user_id)
    db.add(run)
    db.flush()
    for s in report.signals:
        db.add(FraudSignal(run_id=run.id, insurer_id=insurer_id, rule_id=s.rule_id, reason_code=s.reason_code,
                           severity=s.severity, weight=s.weight, entity_type=s.entity_type, entity_key=s.entity_key[:300],
                           entity_label=s.entity_label[:300], message=s.message, claim_numbers=s.claim_numbers,
                           evidence=s.evidence))
    # simpan beberapa run terakhir saja (sinyal lama ikut terhapus); telaah tetap ada di fraud_reviews
    old = db.scalars(select(FraudRun.id).where(FraudRun.insurer_id == insurer_id)
                     .order_by(FraudRun.created_at.desc(), FraudRun.id).offset(KEEP_RUNS)).all()
    old = [o for o in old if o != run.id]
    if old:
        db.execute(delete(FraudSignal).where(FraudSignal.run_id.in_(old)))
        db.execute(delete(FraudRun).where(FraudRun.id.in_(old)))
    db.flush()
    return run


def latest_run(db: Session, insurer_id: str) -> FraudRun | None:
    return db.scalar(select(FraudRun).where(FraudRun.insurer_id == insurer_id).order_by(FraudRun.created_at.desc()).limit(1))


def reviews_for(db: Session, insurer_id: str) -> dict[tuple[str, str], FraudReview]:
    return {(r.rule_id, r.entity_key): r for r in db.scalars(select(FraudReview).where(FraudReview.insurer_id == insurer_id))}


def signals_for_claim(db: Session, claim: Claim) -> tuple[FraudRun | None, list[FraudSignal]]:
    """Sinyal run terakhir yang menyangkut klaim ini: menyebut nomornya, atau entitasnya (RS, dokter, peserta).

    Pencocokan entitas membuat klaim baru (diproses setelah run terakhir) tetap terlihat terkait
    dengan RS atau peserta yang sudah ditandai.
    """
    run = latest_run(db, claim.insurer_id)
    if run is None:
        return None, []
    rec = db.scalar(select(FraudClaimRecord).where(FraudClaimRecord.insurer_id == claim.insurer_id,
                                                   FraudClaimRecord.claim_number == claim.claim_number))
    keys = {("HOSPITAL", claim.hospital_name), ("MEMBER", claim.member_id)}
    if rec is not None and rec.doctor_name:
        keys.add(("DOCTOR", rec.doctor_name))
    out = [s for s in db.scalars(select(FraudSignal).where(FraudSignal.run_id == run.id))
           if claim.claim_number in (s.claim_numbers or []) or (s.entity_type, s.entity_key) in keys]
    return run, out
