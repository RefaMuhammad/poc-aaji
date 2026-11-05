"""U7: underwriting medis. Cakupan data, penyimpanan dokumen, hasil pipeline ke database, dan PDF rekomendasi."""
from __future__ import annotations

import hashlib
from datetime import date
from functools import lru_cache

from fastapi import HTTPException, status
from sqlalchemy import Select, false, or_, select
from sqlalchemy.orm import Session

from mab_api.documents import ValidFile
from mab_api.models import DOCTOR_ROLES, Role, User, UwApplication, UwAssessment, UwDocument, UwReview, UwStatus
from mab_pipeline.underwriting.constants import RECOMMENDATION_LABELS, UW_DOC_LABELS

LABEL = "Data rekaan untuk demonstrasi"
NON_STANDARD = ("ACCEPT_CONDITIONAL", "POSTPONE", "DECLINE")


@lru_cache
def uw_ruleset(path: str | None = None):
    from mab_api.config import get_settings
    from mab_pipeline.underwriting.rules import load_uw_rules

    return load_uw_rules(path or get_settings().resolved_underwriting_rules_path())


def visible_applications_query(user: User) -> Select:
    """Underwriter dan auditor tenant: pengajuan asuransinya. Dokter panel: yang menunggu dokter atau yang
    pernah ditelaahnya. Admin dan auditor platform: semua. Peran lain: tidak ada."""
    q = select(UwApplication)
    try:
        role = Role(user.role)
    except ValueError:
        return q.where(false())
    if role == Role.UNDERWRITER:
        return q.where(UwApplication.insurer_id == user.insurer_id) if user.insurer_id else q.where(false())
    if role == Role.AUDITOR:
        return q.where(UwApplication.insurer_id == user.insurer_id) if user.insurer_id else q
    if role in DOCTOR_ROLES:
        signed = select(UwReview.application_id).where(UwReview.doctor_id == user.id)
        return q.where(or_(UwApplication.status == UwStatus.AWAITING_DOCTOR.value, UwApplication.id.in_(signed)))
    if role == Role.ADMIN:
        return q
    return q.where(false())


def get_visible_application(db: Session, user: User, application_id: str) -> UwApplication:
    app = db.scalar(visible_applications_query(user).where(UwApplication.id == application_id))
    if app is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pengajuan tidak ditemukan")
    return app


def next_application_number(db: Session, today: date | None = None) -> str:
    year = (today or date.today()).year
    prefix = f"UWA-{year}-"
    existing = db.scalars(select(UwApplication.application_number).where(UwApplication.application_number.like(f"{prefix}%")))
    n = max((int(x.rsplit("-", 1)[1]) for x in existing if x.rsplit("-", 1)[1].isdigit()), default=0)
    return f"{prefix}{n + 1:04d}"


def store_uw_document(db: Session, storage, app: UwApplication, user: User | None, f: ValidFile) -> UwDocument:
    from mab_pipeline.underwriting.pipeline import guess_uw_doc_type

    doc = UwDocument(application_id=app.id, filename=f.filename, content_type=f.content_type, size_bytes=len(f.data),
                     sha256=hashlib.sha256(f.data).hexdigest(), storage_key="", doc_type=guess_uw_doc_type(f.filename),
                     uploaded_by_id=user.id if user else None)
    db.add(doc)
    db.flush()
    doc.storage_key = f"underwriting/{app.insurer_id}/{app.id}/{doc.id}/{f.filename}"
    try:
        storage.put(doc.storage_key, f.data, f.content_type)
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Penyimpanan file tidak tersedia: {exc}") from exc
    return doc


def latest_assessment(app: UwApplication) -> UwAssessment | None:
    return app.assessments[-1] if app.assessments else None


def current_review(app: UwApplication) -> UwReview | None:
    """Tanda tangan dokter atas penilaian terbaru (penilaian ulang membatalkan tanda tangan lama)."""
    a = latest_assessment(app)
    if a is None:
        return None
    return next((r for r in reversed(app.reviews) if r.assessment_id == a.id), None)


def current_terms(app: UwApplication) -> dict:
    """Rekomendasi yang berlaku: tanda tangan dokter bila ada, selain itu draf sistem."""
    rev, a = current_review(app), latest_assessment(app)
    if rev is not None:
        return {"source": "doctor", "recommendation": rev.recommendation, "risk_class": rev.risk_class,
                "loading_pct": rev.loading_pct, "exclusions": list(rev.exclusions or [])}
    if a is not None:
        return {"source": "system", "recommendation": a.recommendation, "risk_class": a.risk_class,
                "loading_pct": a.loading_pct, "exclusions": [e["text"] for e in a.exclusions or []]}
    return {"source": None, "recommendation": None, "risk_class": None, "loading_pct": 0, "exclusions": []}


def final_premium(app: UwApplication, decision: str, loading_pct: int) -> int | None:
    if decision not in ("ACCEPT_STANDARD", "ACCEPT_CONDITIONAL") or app.base_premium is None:
        return None
    return app.base_premium * (100 + loading_pct) // 100


def apply_result(db: Session, app: UwApplication, result, ocr_name: str) -> UwAssessment:
    """Simpan hasil pipeline sebagai penilaian baru dan isi data SPAJ ke pengajuan."""
    o = result.outcome
    by_id = {d.id: d for d in app.documents}
    for loaded in result.documents:
        row = by_id.get(loaded.document_id)
        if row is not None:
            row.doc_type, row.page_count = loaded.doc_type, len(loaded.pages)
    p = {k: v.get("value") for k, v in result.profile.items()}
    app.spaj_number = p.get("spaj_number") or app.spaj_number
    app.applicant_name = p.get("applicant_name") or app.applicant_name
    app.applicant_sex = p.get("sex") or app.applicant_sex
    if p.get("birth_date"):
        app.applicant_birth_date = date.fromisoformat(p["birth_date"])
    app.product_name = p.get("product") or app.product_name
    app.sum_assured = p.get("sum_assured") or app.sum_assured
    app.base_premium = p.get("base_premium") or app.base_premium
    a = UwAssessment(
        application_id=app.id, version=len(app.assessments) + 1, fields=result.fields, profile=result.profile,
        findings=o.findings, skipped=o.skipped, evidence=result.evidence(), missing_docs=o.missing_docs,
        missing_fields=o.missing_fields, debit_total=o.debit_total, risk_class=o.risk_class, loading_pct=o.loading_pct,
        exclusions=o.exclusions, recommendation=o.recommendation, needs_doctor=o.needs_doctor,
        doctor_reasons=o.doctor_reasons, rules_version=result.rules_version, model_version=result.model_version,
        prompt_version=result.prompt_version, ocr_engine=ocr_name, warnings=result.warnings,
    )
    db.add(a)
    app.assessments.append(a)
    app.status = (UwStatus.AWAITING_DOCTOR if o.needs_doctor else UwStatus.AWAITING_UNDERWRITER).value
    return a


# ----------------------------------------------------------------------------- PDF


def recommendation_pdf(app: UwApplication, class_name) -> bytes:
    from mab_api.reporting import _pdf

    a, rev = latest_assessment(app), current_review(app)
    terms = current_terms(app)
    decision = app.decisions[-1] if app.decisions else None
    pdf, text, table = _pdf()
    text(f"{LABEL.upper()} - bukan dokumen underwriting sungguhan", 8, "B", color=(176, 0, 0))
    text(f"Rekomendasi underwriting medis {app.application_number}", 15, "B", 1)
    text(f"{app.insurer.name} · SPAJ {app.spaj_number or '-'} · {app.applicant_name or '-'} · "
         f"{'Perempuan' if app.applicant_sex == 'P' else 'Laki-laki' if app.applicant_sex == 'L' else '-'} · "
         f"lahir {app.applicant_birth_date or '-'}", 9, color=(71, 85, 105))
    text(f"Produk {app.product_name or '-'} · UP Rp{_rp(app.sum_assured)} · premi dasar Rp{_rp(app.base_premium)}", 9,
         color=(71, 85, 105), gap=3)

    text("Rekomendasi", 12, "B", 0.5)
    rec_label = RECOMMENDATION_LABELS.get(terms["recommendation"] or "", "-")
    text(f"{rec_label} · kelas risiko {class_name(terms['risk_class'] or '-')} · loading {terms['loading_pct']}%", 11, "B", 0.8)
    for e in terms["exclusions"]:
        text(f"Pengecualian: {e}", 9, gap=0.4)
    if rev is not None:
        text(f"Ditandatangani {rev.doctor.full_name} pada {rev.signed_at:%d-%m-%Y %H:%M} UTC "
             f"({'menyetujui draf sistem' if rev.action == 'AGREE' else 'mengubah draf sistem'}).", 9, gap=0.4)
        if rev.notes:
            text(f"Catatan dokter: {rev.notes}", 9, gap=0.4)
    elif terms["recommendation"] in NON_STANDARD or (a and a.needs_doctor):
        text("DRAF SISTEM, BELUM DITANDATANGANI DOKTER. Belum boleh diputuskan.", 9, "B", color=(176, 0, 0))
    if decision is not None:
        text(f"Keputusan underwriter: {RECOMMENDATION_LABELS.get(decision.decision)} oleh {decision.decided_by.full_name} "
             f"pada {decision.decided_at:%d-%m-%Y %H:%M} UTC. Premi akhir: "
             f"{'Rp' + _rp(decision.final_premium) if decision.final_premium else '-'}.", 9, gap=0.4)
    pdf.ln(2)
    if a is not None:
        text("Temuan dan dasar aturan", 12, "B", 0.5)
        rows = [[f["rule_id"], f["name"], _kind(f), f["message"], _quotes(a, f["line_ids"])] for f in a.findings]
        if rows:
            table(["Aturan", "Nama", "Akibat", "Pesan", "Bukti dokumen"], rows, widths=(18, 32, 22, 60, 58))
        else:
            text("Tidak ada temuan. Semua aturan dinilai dan tidak ada yang terpicu.", 9)
        pdf.ln(2)
        text(f"Total debit {a.debit_total} · aturan {a.rules_version} · model {a.model_version} · prompt "
             f"{a.prompt_version} · OCR {a.ocr_engine} · penilaian v{a.version} {a.created_at:%d-%m-%Y %H:%M} UTC",
             8, color=(100, 116, 139))
        text("Debit, kelas risiko, dan loading memakai tabel contoh; pada pemakaian sungguhan memakai tabel klien.",
             8, color=(100, 116, 139))
    text("Dokumen sumber", 12, "B", 0.5)
    table(["Jenis", "File", "SHA-256"], [[UW_DOC_LABELS.get(d.doc_type, d.doc_type), d.filename, d.sha256[:32] + "…"]
                                          for d in app.documents], widths=(40, 60, 90))
    return bytes(pdf.output())


def _rp(n: int | None) -> str:
    return f"{n:,}".replace(",", ".") if n is not None else "-"


def _kind(f: dict) -> str:
    parts = []
    if f.get("decision") == "tolak":
        parts.append("usul tolak")
    if f.get("decision") == "tunda":
        parts.append("tunda")
    if f.get("debit"):
        parts.append(f"+{f['debit']}")
    if f.get("exclusion"):
        parts.append("pengecualian")
    if f.get("note"):
        parts.append("catatan")
    return ", ".join(parts) or "-"


def _quotes(a: UwAssessment, line_ids: list[str]) -> str:
    ev = a.evidence or {}
    return " | ".join(f"{UW_DOC_LABELS.get(ev[i]['doc_type'], '')}: {ev[i]['text']}" for i in line_ids if i in ev)[:300] or "-"
