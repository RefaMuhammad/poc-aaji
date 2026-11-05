"""Data polis dan plan benefit (U2): pencarian polis untuk klaim dan impor dari sistem inti asuransi.

Data polis TIDAK dibaca dari dokumen rumah sakit. Sumbernya file CSV/XLSX yang diunggah
asuransi/TPA atau `PUT /integrations/v1/policies`. Semua data di POC ini rekaan.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass, field

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from mab_api.models import BenefitPlan, Claim, Policy
from mab_pipeline.benefit import PolicyInfo

POLICY_STATUSES = ("ACTIVE", "LAPSED", "TERMINATED")
POLICY_COLUMNS = ("nomor_polis", "id_peserta", "nama_peserta", "kode_plan", "tanggal_mulai", "tanggal_akhir",
                  "status", "limit_terpakai")
REQUIRED_POLICY_COLUMNS = ("nomor_polis", "id_peserta", "kode_plan", "tanggal_mulai", "tanggal_akhir")


def tenant_has_policies(db: Session, insurer_id: str) -> bool:
    return bool(db.scalar(select(exists().where(Policy.insurer_id == insurer_id))))


def find_policy(db: Session, claim: Claim) -> Policy | None:
    """Polis peserta klaim: nomor polis + peserta yang sama, atau polis peserta yang
    masa berlakunya mencakup tanggal masuk, atau polis peserta yang paling baru."""
    rows = list(db.scalars(select(Policy).where(Policy.insurer_id == claim.insurer_id, Policy.member_id == claim.member_id)))
    if not rows:
        return None
    for p in rows:
        if p.policy_number == claim.policy_number:
            return p
    covering = [p for p in rows if p.start_date <= claim.admission_date <= p.end_date]
    return max(covering or rows, key=lambda p: p.start_date)


def policy_info(p: Policy) -> PolicyInfo:
    plan = p.plan
    return PolicyInfo(
        policy_number=p.policy_number, member_id=p.member_id, plan_code=plan.code, plan_name=plan.name,
        start_date=p.start_date, end_date=p.end_date, status=p.status, room_class=plan.room_class,
        room_rate_limit=plan.room_rate_limit, annual_limit=plan.annual_limit, limit_used=p.limit_used or 0,
        waiting_period_days=plan.waiting_period_days or 0, excluded_icd10=tuple(plan.excluded_icd10 or ()),
    )


# ----------------------------------------------------------------------------- impor


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


def _date(value) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"tanggal tidak dikenal: {text!r} (pakai YYYY-MM-DD)")


def _int(value) -> int:
    if value is None or str(value).strip() == "":
        return 0
    text = str(value).strip().replace(".", "").replace(",", "") if isinstance(value, str) else value
    return int(float(text))


def read_rows(filename: str, data: bytes) -> list[dict]:
    """Baris CSV (pemisah koma atau titik koma) atau XLSX (sheet pertama) sebagai dict berkunci huruf kecil."""
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook

        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).worksheets[0]
        it = ws.iter_rows(values_only=True)
        header = [str(h or "").strip().lower() for h in next(it, [])]
        return [dict(zip(header, row)) for row in it if any(v not in (None, "") for v in row)]
    text = data.decode("utf-8-sig")
    dialect = csv.Sniffer().sniff(text.splitlines()[0] if text else ",", delimiters=",;")
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    return [{(k or "").strip().lower(): v for k, v in row.items()} for row in reader if any((v or "").strip() for v in row.values())]


def upsert_policies(db: Session, insurer_id: str, rows: list[dict], source: str = "IMPORT") -> ImportResult:
    """Tambah atau perbarui polis. Baris yang salah dilewati dan dilaporkan; baris lain tetap disimpan."""
    result = ImportResult()
    if rows:
        missing = [c for c in REQUIRED_POLICY_COLUMNS if c not in rows[0]]
        if missing:
            result.errors.append(f"kolom wajib tidak ada: {', '.join(missing)}")
            return result
    plans = {p.code: p for p in db.scalars(select(BenefitPlan).where(BenefitPlan.insurer_id == insurer_id))}
    for n, row in enumerate(rows, start=2):
        try:
            number = str(row.get("nomor_polis") or "").strip()
            member = str(row.get("id_peserta") or "").strip()
            plan_code = str(row.get("kode_plan") or "").strip()
            if not number or not member:
                raise ValueError("nomor_polis dan id_peserta wajib diisi")
            plan = plans.get(plan_code)
            if plan is None:
                raise ValueError(f"kode_plan {plan_code!r} belum terdaftar")
            start, end = _date(row.get("tanggal_mulai")), _date(row.get("tanggal_akhir"))
            if end < start:
                raise ValueError("tanggal_akhir sebelum tanggal_mulai")
            status = str(row.get("status") or "ACTIVE").strip().upper()
            if status not in POLICY_STATUSES:
                raise ValueError(f"status {status!r} tidak dikenal ({'/'.join(POLICY_STATUSES)})")
            used = _int(row.get("limit_terpakai"))
        except (ValueError, TypeError) as exc:
            result.errors.append(f"baris {n}: {exc}")
            continue
        policy = db.scalar(select(Policy).where(Policy.insurer_id == insurer_id, Policy.policy_number == number,
                                                Policy.member_id == member))
        if policy is None:
            policy = Policy(insurer_id=insurer_id, policy_number=number, member_id=member)
            db.add(policy)
            result.created += 1
        else:
            result.updated += 1
        name = row.get("nama_peserta")
        policy.member_name = str(name).strip() if name else policy.member_name
        policy.plan_id = plan.id
        policy.start_date, policy.end_date = start, end
        policy.status = status
        policy.limit_used = used
        policy.source = source
        db.flush()
    return result
