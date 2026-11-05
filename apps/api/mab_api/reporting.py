"""U6: penampil log audit, jejak keputusan klaim, dan laporan bulanan kepatuhan (POJK 36/2025).

Laporan dibangun dari data platform untuk satu periode (bulan kalender, UTC) dan satu cakupan
(satu tenant, atau seluruh platform). Isinya dibekukan di tabel `reports` supaya laporan yang sudah
dikirim tidak berubah bila data berubah. Membuat ulang laporan yang sama menaikkan `revision`.

Templat `pojk36-draf-1` adalah DRAF. POJK 36/2025 tidak memuat format laporan berkala ke OJK
(lihat docs/u6-audit-pelaporan.md); bagian laporan disusun dari kewajiban yang bisa dibuktikan
platform (Telaah Utilisasi, Dewan Penasihat Medis, kapabilitas digital) dan wajib dicocokkan dengan
format yang diminta OJK / klien sebelum dipakai.
"""
from __future__ import annotations

import io
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from mab_api import disputes as dispute_mod
from mab_api.access import tenant_ids, visible_claims_query
from mab_api.models import (
    Assignment,
    AuditLog,
    Claim,
    Dispute,
    Document,
    DocumentRequest,
    FraudReview,
    FraudRun,
    FraudSignal,
    Insurer,
    RecommendationState,
    Report,
    Review,
    Role,
    User,
)

KIND = "POJK36_MONTHLY"
TEMPLATE_VERSION = "pojk36-draf-1"
DATA_LABEL = "Data rekaan untuk demonstrasi"
TEMPLATE_NOTE = (
    "Templat draf. POJK 36/2025 tidak menetapkan format laporan berkala ke OJK; bagian laporan ini disusun "
    "dari kewajiban yang bisa dibuktikan platform dan wajib dicocokkan dengan format yang diminta OJK atau klien."
)

REC_LABEL = {"PAY_FULL": "Bayar penuh", "PAY_PARTIAL": "Bayar sebagian", "PEND": "Tunda",
             "NOT_COVERED": "Tidak dijamin", "DOCTOR_REVIEW": "Menunggu telaah dokter"}
SOURCE_LABEL = {"PORTAL": "Portal (satu klaim)", "BATCH": "Portal (ZIP)", "API": "REST API",
                "SFTP": "SFTP", "FHIR": "FHIR"}
ROLE_LABEL = {r.value: r.value for r in Role} | {
    "insurer_staff": "Staf klaim", "insurer_manager": "Manajer klaim", "tpa_operator": "Operator TPA",
    "doctor_gp": "Dokter umum", "doctor_specialist": "Dokter spesialis", "auditor": "Auditor",
    "facility_officer": "Petugas faskes", "member": "Peserta", "underwriter": "Underwriter", "admin": "Admin",
}

REVIEW_ACTION_LABEL = {"APPROVE": "menyetujui draf", "MODIFY": "mengubah draf", "ESCALATE": "eskalasi ke spesialis"}

# ----------------------------------------------------------------------------- label aksi audit

ACTION_LABEL = {
    "LOGIN": "Masuk", "LOGIN_FAILED": "Gagal masuk", "DEMO_SWITCH": "Ganti peran (mode demo)",
    "DOCUMENT_ACCESS": "Membuka dokumen",
    "PIPELINE_COMPLETED": "Sistem selesai membaca dan menilai dokumen",
    "PIPELINE_FAILED": "Sistem gagal memproses klaim",
    "CASE_ASSIGNED": "Kasus ditugaskan ke dokter",
    "REVIEW_STARTED": "Dokter mulai menelaah", "REVIEW_ESCALATED": "Dokter mengeskalasi ke spesialis",
    "REVIEW_RELEASED": "Dokter melepas kasus", "FIELD_CORRECTED": "Dokter mengoreksi hasil baca",
    "SIGN_PIN_FAILED": "PIN tanda tangan salah", "RECOMMENDATION_SIGNED": "Dokter menandatangani rekomendasi",
    "DOCUMENTS_REQUESTED": "Asuransi meminta dokumen susulan",
    "LATE_DOCUMENTS_UPLOADED": "Dokumen susulan diunggah",
    "DOCUMENT_REQUEST_FULFILLED": "Permintaan dokumen terpenuhi",
    "DOCUMENT_REQUEST_CANCELLED": "Permintaan dokumen dibatalkan",
    "DISPUTE_FILED": "Banding diajukan", "DISPUTE_REVIEWED": "Banding ditelaah ulang",
    "DISPUTE_RESOLVED": "Banding diputus", "DISPUTE_WITHDRAWN": "Banding ditarik",
    "TENANT_CREATED": "Tenant dibuat", "TENANT_SETTINGS_UPDATED": "Pengaturan tenant diubah",
    "API_CLIENT_CREATED": "API key dibuat", "API_CLIENT_REVOKED": "API key dicabut",
    "INTEGRATION_ACCESS": "Akses integrasi", "POLICIES_IMPORTED": "Polis diimpor",
    "BENEFIT_PLAN_SAVED": "Plan benefit disimpan", "WEBHOOK_RESEND": "Webhook dikirim ulang",
    "WEBHOOK_DEMO_RECEIVED": "Webhook demo diterima",
    "FRAUD_HISTORY_IMPORTED": "Riwayat klaim fraud diimpor", "FRAUD_ANALYSIS_RUN": "Analisis fraud dijalankan",
    "FRAUD_SIGNAL_REVIEWED": "Sinyal fraud ditelaah",
    "REPORT_GENERATED": "Laporan dibuat", "REPORT_DOWNLOADED": "Laporan diunduh",
    "AUDIT_LOG_EXPORTED": "Log audit diekspor",
    "AUDIT_TRACE_EXPORTED": "Jejak keputusan diekspor",
    # U7: underwriting medis
    "UW_SUBMITTED": "Pengajuan underwriting diterima", "UW_PROCESSED": "Draf underwriting dibuat sistem",
    "UW_FAILED": "Proses underwriting gagal", "UW_SIGNED": "Dokter menandatangani rekomendasi underwriting",
    "UW_SIGN_PIN_FAILED": "PIN tanda tangan underwriting salah", "UW_DECIDED": "Underwriter memutuskan pengajuan",
    "UW_PDF_DOWNLOADED": "PDF rekomendasi underwriting diunduh", "UW_DOCUMENT_VIEWED": "Dokumen underwriting dibuka",
}

# Aksi tulis yang dicatat middleware sebagai "METHOD /path": dipetakan ke label yang terbaca.
_UUID = r"[0-9a-f-]{36}"
_ROUTE_LABEL: list[tuple[str, str]] = [
    (rf"^POST /claims/{_UUID}/decision$", "Asuransi mencatat keputusan"),
    (r"^POST /claims/decisions/bulk-agree$", "Asuransi menyetujui klaim secara massal"),
    (rf"^POST /claims/{_UUID}/documents$", "Dokumen klaim diunggah"),
    (r"^POST /claims/batch$", "Unggah klaim (ZIP)"),
    (r"^POST /claims$", "Klaim dibuat"),
    (rf"^POST /claims/{_UUID}/reprocess$", "Klaim diproses ulang"),
    (rf"^POST /claims/{_UUID}/document-requests(/cancel)?$", "Permintaan dokumen susulan"),
    (rf"^POST /review/{_UUID}/sign$", "Tanda tangan rekomendasi"),
    (rf"^POST /review/{_UUID}/start$", "Mulai telaah"),
    (rf"^POST /review/{_UUID}/escalate$", "Eskalasi telaah"),
    (rf"^POST /portal/claims/{_UUID}/documents$", "Faskes mengunggah dokumen susulan"),
    (rf"^POST /portal/claims/{_UUID}/disputes(/withdraw)?$", "Banding (portal)"),
    (r"^POST /reports$", "Laporan dibuat"),
    (r"^POST /underwriting/applications$", "Pengajuan underwriting diunggah"),
    (rf"^POST /underwriting/applications/{_UUID}/sign$", "Tanda tangan rekomendasi underwriting"),
    (rf"^POST /underwriting/applications/{_UUID}/decision$", "Keputusan underwriting"),
]


def action_label(action: str) -> str:
    if action in ACTION_LABEL:
        return ACTION_LABEL[action]
    for pattern, label in _ROUTE_LABEL:
        if re.match(pattern, action):
            return label
    return action


def action_group(action: str) -> str:
    """Kelompok aksi untuk filter penampil audit."""
    if action.startswith(("LOGIN", "DEMO_SWITCH")):
        return "AUTH"
    if action == "DOCUMENT_ACCESS":
        return "ACCESS"
    if action.startswith("UW_") or "/underwriting" in action:
        return "UNDERWRITING"
    if action.startswith(("PIPELINE_",)):
        return "SYSTEM"
    if action.startswith(("REVIEW_", "RECOMMENDATION_", "SIGN_", "CASE_", "FIELD_")) or "/review/" in action:
        return "REVIEW"
    if "/decision" in action:
        return "DECISION"
    if action.startswith(("DOCUMENT_REQUEST", "DOCUMENTS_REQUESTED", "LATE_DOCUMENTS")) or "document-requests" in action:
        return "DOCUMENTS"
    if action.startswith("DISPUTE_") or "/disputes" in action:
        return "DISPUTE"
    if action.startswith("FRAUD_"):
        return "FRAUD"
    if action.startswith("REPORT_") or action.startswith("AUDIT_") or "/reports" in action:
        return "REPORT"
    if action.startswith(("TENANT_", "API_CLIENT", "POLICIES_", "BENEFIT_", "WEBHOOK_", "INTEGRATION_")):
        return "ADMIN"
    return "OTHER"


ACTION_GROUPS = {
    "AUTH": "Masuk / keluar", "ACCESS": "Akses dokumen", "SYSTEM": "Proses sistem", "REVIEW": "Telaah dokter",
    "DECISION": "Keputusan asuransi", "DOCUMENTS": "Dokumen susulan", "DISPUTE": "Banding",
    "FRAUD": "Fraud", "REPORT": "Laporan & audit", "ADMIN": "Pengaturan & integrasi",
    "UNDERWRITING": "Underwriting", "OTHER": "Lainnya",
}


def _utc(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------------------- penampil log audit

def audit_scope(db: Session, user: User):
    """Kondisi baris log audit yang boleh dilihat pengguna. None = semua (admin, auditor platform)."""
    tenants = tenant_ids(db, user)
    if tenants is None:
        return None
    claim_ids = select(visible_claims_query(user, db).subquery().c.id)
    tenant_users = select(User.id).where(User.insurer_id.in_(tenants)) if tenants else select(User.id).where(False)
    return or_(AuditLog.claim_id.in_(claim_ids), AuditLog.user_id.in_(tenant_users))


def query_audit(db: Session, user: User, *, claim_id: str | None = None, claim_number: str | None = None,
                user_query: str | None = None, action: str | None = None, group: str | None = None,
                date_from: datetime | None = None, date_to: datetime | None = None,
                limit: int = 100, offset: int = 0) -> tuple[int, list[AuditLog]]:
    q = select(AuditLog)
    scope = audit_scope(db, user)
    if scope is not None:
        q = q.where(scope)
    if claim_id:
        q = q.where(AuditLog.claim_id == claim_id)
    if claim_number:
        ids = select(visible_claims_query(user, db).where(Claim.claim_number.ilike(f"%{claim_number.strip()}%"))
                     .subquery().c.id)
        q = q.where(AuditLog.claim_id.in_(ids))
    if user_query:
        term = f"%{user_query.strip()}%"
        uids = select(User.id).where(or_(User.email.ilike(term), User.full_name.ilike(term)))
        q = q.where(AuditLog.user_id.in_(uids))
    if action:
        q = q.where(AuditLog.action.ilike(f"%{action.strip()}%"))
    if date_from:
        q = q.where(AuditLog.occurred_at >= date_from)
    if date_to:
        q = q.where(AuditLog.occurred_at < date_to)
    rows = list(db.scalars(q.order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())))
    if group:
        rows = [r for r in rows if action_group(r.action) == group]
    return len(rows), rows[offset:offset + limit]


def describe_rows(db: Session, rows: list[AuditLog]) -> list[dict]:
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r.user_id for r in rows if r.user_id})))}
    claims = {c.id: c for c in db.scalars(select(Claim).where(Claim.id.in_({r.claim_id for r in rows if r.claim_id})))}
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_({r.document_id for r in rows if r.document_id})))}
    out = []
    for r in rows:
        u, c, d = users.get(r.user_id), claims.get(r.claim_id), docs.get(r.document_id)
        out.append({
            "id": r.id, "occurred_at": r.occurred_at, "action": r.action, "label": action_label(r.action),
            "group": action_group(r.action), "user_id": r.user_id,
            "user_name": u.full_name if u else ("Sistem" if r.user_id is None else None),
            "user_email": u.email if u else None, "user_role": r.user_role,
            "claim_id": r.claim_id, "claim_number": c.claim_number if c else None,
            "document_id": r.document_id, "document_name": d.filename if d else None,
            "method": r.method, "path": r.path, "status_code": r.status_code, "ip_address": r.ip_address,
            "detail": r.detail or {},
        })
    return out


# ----------------------------------------------------------------------------- jejak keputusan satu klaim

STAGES = ["Penerimaan", "Pemrosesan sistem", "Telaah dokter", "Keputusan asuransi", "Dokumen susulan", "Banding",
          "Akses & lainnya"]


def _name(users: dict[str, User], uid: str | None, fallback: str = "Sistem") -> str:
    u = users.get(uid or "")
    return f"{u.full_name} ({ROLE_LABEL.get(u.role, u.role)})" if u else fallback


def _rp(n: int | None) -> str:
    return "-" if n is None else "Rp" + f"{n:,}".replace(",", ".")


def claim_trace(db: Session, claim: Claim) -> dict:
    """Jejak lengkap satu klaim dari unggah sampai keputusan akhir, untuk auditor.

    Disusun dari entitas (dokumen, rekomendasi berversi, penugasan, telaah, keputusan, permintaan dokumen,
    banding) dan dicocokkan dengan log audit. `chain` merangkum mata rantai keputusan akhir.
    """
    recs = sorted(claim.recommendations, key=lambda r: r.version)
    reviews = list(db.scalars(select(Review).where(Review.claim_id == claim.id).order_by(Review.started_at)))
    assignments = list(db.scalars(select(Assignment).where(Assignment.claim_id == claim.id).order_by(Assignment.assigned_at)))
    requests = list(db.scalars(select(DocumentRequest).where(DocumentRequest.claim_id == claim.id).order_by(DocumentRequest.created_at)))
    disputes = list(db.scalars(select(Dispute).where(Dispute.claim_id == claim.id).order_by(Dispute.created_at)))
    logs = list(db.scalars(select(AuditLog).where(AuditLog.claim_id == claim.id).order_by(AuditLog.occurred_at, AuditLog.id)))
    uids = {claim.created_by_id, *(d.uploaded_by_id for d in claim.documents), *(r.signed_by_id for r in recs),
            *(r.doctor_id for r in reviews), *(a.doctor_id for a in assignments), *(a.assigned_by_id for a in assignments),
            *(d.decided_by_id for d in claim.decisions), *(q.requested_by_id for q in requests),
            *(q.fulfilled_by_id for q in requests), *(d.raised_by_id for d in disputes),
            *(d.reviewer_id for d in disputes), *(d.resolved_by_id for d in disputes), *(r.user_id for r in logs)}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_({i for i in uids if i})))}
    insurer = db.get(Insurer, claim.insurer_id)
    rec_by_id = {r.id: r for r in recs}

    steps: list[dict] = []

    def add(at, stage, title, actor=None, detail=None, ref=None):
        steps.append({"at": at, "stage": stage, "title": title, "actor": actor, "detail": detail, "ref": ref})

    who = _name(users, claim.created_by_id, f"Integrasi {SOURCE_LABEL.get(claim.source, claim.source)}")
    add(claim.created_at, "Penerimaan", "Klaim diterima", who,
        f"Kanal {SOURCE_LABEL.get(claim.source, claim.source)} · tagihan {_rp(claim.billed_amount)}")
    late = {i for q in requests for i in (q.document_ids or [])} | {i for d in disputes for i in (d.document_ids or [])}
    for d in claim.documents:
        stage = "Penerimaan" if d.id not in late else ("Banding" if any(d.id in (x.document_ids or []) for x in disputes)
                                                         else "Dokumen susulan")
        add(d.created_at, stage, f"Dokumen diunggah: {d.filename}", _name(users, d.uploaded_by_id, "Integrasi"),
            f"{d.doc_type} · {d.page_count or '?'} hal. · SHA-256 {d.sha256[:16]}…", d.id)
    for r in recs:
        if r.state == RecommendationState.DRAFT.value:
            add(r.created_at, "Pemrosesan sistem", f"Draf rekomendasi v{r.version}: {REC_LABEL.get(r.recommendation, r.recommendation)}",
                "Sistem", f"Triase {r.triage_status}, skor {r.risk_score} · {len(r.findings)} temuan · model {r.model_version}, "
                f"prompt {r.prompt_version}, aturan {r.ruleset_version}"
                + (f", benefit {r.benefit_ruleset_version}" if r.benefit_ruleset_version else "")
                + (" · draf telaah banding" if r.dispute_id else ""), r.id)
        else:
            add(r.signed_at or r.created_at, "Telaah dokter",
                f"Rekomendasi v{r.version} ditandatangani: {REC_LABEL.get(r.recommendation, r.recommendation)} {_rp(r.recommended_amount)}",
                _name(users, r.signed_by_id, "dokter"), "rekomendasi banding" if r.dispute_id else None, r.id)
    for a in assignments:
        add(a.assigned_at, "Telaah dokter", f"Ditugaskan ke {_name(users, a.doctor_id, 'dokter')}",
            _name(users, a.assigned_by_id, "Sistem (otomatis)"),
            f"Level {a.level}{' · ' + a.specialty if a.specialty else ''} · cara {a.method} · batas SLA "
            f"{_utc(a.due_at):%d-%m-%Y %H:%M} UTC · status {a.status}")
    for rv in reviews:
        if rv.finished_at:
            agree = {True: "sama dengan draf AI", False: "mengubah draf AI", None: "telaah banding"}[rv.agrees_with_ai]
            add(rv.finished_at, "Telaah dokter", f"Telaah selesai: {REVIEW_ACTION_LABEL.get(rv.action or '', rv.action or '-')}",
                _name(users, rv.doctor_id, "dokter"),
                f"{agree}{' · kode ' + rv.reason_code if rv.reason_code else ''}"
                f"{' · ' + rv.notes if rv.notes else ''} · durasi "
                f"{round((_utc(rv.finished_at) - _utc(rv.started_at)).total_seconds() / 60, 1)} menit")
    for dec in claim.decisions:
        rec = rec_by_id.get(dec.recommendation_id)
        add(dec.decided_at, "Keputusan asuransi",
            f"Keputusan asuransi: {'setuju' if dec.decision == 'AGREE' else 'berbeda'} dengan rekomendasi v{rec.version if rec else '?'}",
            _name(users, dec.decided_by_id), dec.reason)
    for q in requests:
        add(q.created_at, "Dokumen susulan", f"Dokumen susulan diminta: {', '.join(q.doc_types or [])}",
            _name(users, q.requested_by_id), q.message)
        if q.fulfilled_at:
            add(q.fulfilled_at, "Dokumen susulan", "Permintaan dokumen terpenuhi", _name(users, q.fulfilled_by_id), q.response_note)
    for d in disputes:
        add(d.created_at, "Banding", f"Banding diajukan ({dispute_mod.CATEGORY_LABEL.get(d.category, d.category)})",
            _name(users, d.raised_by_id), d.reason)
        if d.reviewed_at:
            add(d.reviewed_at, "Banding", f"Banding ditelaah ulang: {dispute_mod.OUTCOME_LABEL.get(d.review_outcome or '', '-')}",
                _name(users, d.reviewer_id), f"Penelaah awal dikecualikan: {_name(users, d.original_reviewer_id, '-')}")
        if d.resolved_at:
            add(d.resolved_at, "Banding", "Banding ditarik" if d.status == dispute_mod.WITHDRAWN else
                f"Banding diputus: keputusan awal {dispute_mod.OUTCOME_LABEL.get(d.outcome or '', '-')}",
                _name(users, d.resolved_by_id or d.raised_by_id))
    access = [r for r in logs if r.action == "DOCUMENT_ACCESS"]
    for r in access:
        add(r.occurred_at, "Akses & lainnya", "Dokumen dibuka", _name(users, r.user_id, "-"), r.path)
    steps.sort(key=lambda s: _utc(s["at"]))

    # Mata rantai keputusan akhir: keputusan -> rekomendasi -> penanda tangan -> draf sistem -> dokumen
    chain: list[str] = []
    final = max(claim.decisions, key=lambda d: _utc(d.decided_at)) if claim.decisions else None
    if final is not None:
        rec = rec_by_id.get(final.recommendation_id)
        chain.append(f"Keputusan akhir: {'setuju' if final.decision == 'AGREE' else 'berbeda'} oleh "
                     f"{_name(users, final.decided_by_id)} pada {_utc(final.decided_at):%d-%m-%Y %H:%M} UTC"
                     + (f". Alasan: {final.reason}" if final.reason else ""))
        if rec is not None:
            chain.append(f"Atas rekomendasi v{rec.version} ({rec.state}): {REC_LABEL.get(rec.recommendation, rec.recommendation)} "
                         f"{_rp(rec.recommended_amount)} dari tagihan {_rp(rec.billed_amount)}")
            if rec.signed_by_id:
                rv = next((x for x in reversed(reviews) if x.recommendation_id in {rec.id} | {r.id for r in recs}
                           and x.doctor_id == rec.signed_by_id and x.finished_at), None)
                chain.append(f"Ditandatangani {_name(users, rec.signed_by_id)} pada {_utc(rec.signed_at):%d-%m-%Y %H:%M} UTC"
                             + (f", kode alasan {rv.reason_code}" if rv and rv.reason_code else "")
                             + (", sama dengan draf AI" if rv and rv.agrees_with_ai else ""))
            else:
                chain.append("Bayar penuh tanpa tanda tangan dokter (hijau, dirilis langsung sesuai aturan)")
            drafts = [r for r in recs if r.state == RecommendationState.DRAFT.value and r.version < rec.version] or \
                     [r for r in recs if r.state == RecommendationState.DRAFT.value]
            if drafts:
                d = drafts[-1]
                chain.append(f"Berdasarkan draf sistem v{d.version}: triase {d.triage_status} skor {d.risk_score}, "
                             f"{len(d.findings)} temuan, model {d.model_version}, prompt {d.prompt_version}, aturan {d.ruleset_version}")
            if rec.dispute_id:
                disp = next((x for x in disputes if x.id == rec.dispute_id), None)
                if disp:
                    chain.append(f"Hasil banding ({dispute_mod.CATEGORY_LABEL.get(disp.category)}) yang diajukan "
                                 f"{_name(users, disp.raised_by_id)}; penelaah awal {_name(users, disp.original_reviewer_id, '-')} dikecualikan")
        chain.append(f"Dokumen sumber: {len(claim.documents)} file, sidik SHA-256 tercatat per file")
    else:
        chain.append("Klaim belum diputuskan asuransi.")

    return {
        "claim": {"id": claim.id, "claim_number": claim.claim_number, "insurer_name": insurer.name if insurer else None,
                  "hospital_name": claim.hospital_name, "member_id": claim.member_id, "status": claim.status,
                  "source": claim.source, "billed_amount": claim.billed_amount, "created_at": claim.created_at},
        "chain": chain,
        "steps": steps,
        "documents": [{"id": d.id, "filename": d.filename, "doc_type": d.doc_type, "sha256": d.sha256,
                       "size_bytes": d.size_bytes, "created_at": d.created_at} for d in claim.documents],
        "audit": describe_rows(db, logs),
        "stages": STAGES,
        "generated_at": _now(),
        "label": DATA_LABEL,
    }


# ----------------------------------------------------------------------------- laporan bulanan

def parse_period(period: str) -> tuple[datetime, datetime]:
    m = re.fullmatch(r"(\d{4})-(\d{2})", period or "")
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError("Periode harus berformat YYYY-MM")
    y, mo = int(m.group(1)), int(m.group(2))
    start = datetime(y, mo, 1, tzinfo=timezone.utc)
    end = datetime(y + (mo == 12), 1 if mo == 12 else mo + 1, 1, tzinfo=timezone.utc)
    return start, end


def previous_period(now: datetime) -> str:
    first = now.astimezone(timezone.utc).replace(day=1)
    prev = first - timedelta(days=1)
    return f"{prev.year:04d}-{prev.month:02d}"


def _in(dt, start, end) -> bool:
    dt = _utc(dt)
    return dt is not None and start <= dt < end


def _pct(a: int, b: int) -> float | None:
    return round(100 * a / b, 1) if b else None


def _avg(xs: list[float], digits: int = 1) -> float | None:
    return round(sum(xs) / len(xs), digits) if xs else None


def _row(label: str, value, unit: str | None = None, note: str | None = None) -> dict:
    return {"label": label, "value": value, "unit": unit, "note": note}


def build_report_data(db: Session, insurer: Insurer | None, period: str, *, now: datetime | None = None) -> dict:
    """Hitung isi laporan bulanan untuk satu tenant (atau seluruh platform bila `insurer` None)."""
    start, end = parse_period(period)
    now = now or _now()
    q = select(Claim)
    if insurer is not None:
        q = q.where(Claim.insurer_id == insurer.id)
    claims = list(db.scalars(q))
    ids = [c.id for c in claims]
    received = [c for c in claims if _in(c.created_at, start, end)]

    # --- B. Layanan klaim
    decisions = [d for c in claims for d in c.decisions if _in(d.decided_at, start, end)]
    decided_claims = {d.claim_id for d in decisions}
    by_rec, by_source = Counter(), Counter(c.source for c in received)
    first_rec_hours, decide_days = [], []
    billed = approved = 0
    rec_by_id = {r.id: r for c in claims for r in c.recommendations}
    for c in received:
        drafts = [r for r in c.recommendations if r.version == 1]
        if drafts:
            first_rec_hours.append((_utc(drafts[0].created_at) - _utc(c.created_at)).total_seconds() / 3600)
    for c in claims:
        if c.id not in decided_claims:
            continue
        final = max((d for d in c.decisions if _in(d.decided_at, start, end)), key=lambda d: _utc(d.decided_at))
        rec = rec_by_id.get(final.recommendation_id)
        decide_days.append((_utc(final.decided_at) - _utc(c.created_at)).total_seconds() / 86400)
        if rec is not None:
            by_rec[rec.recommendation] += 1
            billed += rec.billed_amount or 0
            approved += rec.recommended_amount or 0
    agree = sum(1 for d in decisions if d.decision == "AGREE")
    status_now = Counter(c.status for c in claims)
    service = {
        "id": "B", "title": "Layanan klaim",
        "basis": "Gambaran layanan klaim periode ini (indikator umum, bukan pasal tertentu)",
        "rows": [
            _row("Klaim diterima", len(received), "klaim"),
            _row("Klaim diputus asuransi", len(decided_claims), "klaim"),
            _row("Keputusan sama dengan rekomendasi", f"{agree} dari {len(decisions)}",
                 note=f"{_pct(agree, len(decisions))}%" if decisions else None),
            _row("Rata-rata klaim diterima sampai rekomendasi awal", _avg(first_rec_hours, 2), "jam"),
            _row("Rata-rata klaim diterima sampai keputusan", _avg(decide_days, 1), "hari"),
            _row("Nilai tagihan klaim yang diputus", billed, "rupiah"),
            _row("Nilai yang direkomendasikan dibayar", approved, "rupiah"),
            _row("Selisih (koreksi)", max(billed - approved, 0), "rupiah"),
            _row("Posisi akhir: menunggu dokter / keputusan / dokumen",
                 f"{status_now['AWAITING_DOCTOR']} / {status_now['AWAITING_DECISION']} / {status_now['PENDING_DOCUMENTS']}",
                 note="posisi saat laporan dibuat"),
        ],
        "tables": [
            {"title": "Klaim diterima per kanal", "columns": ["Kanal", "Klaim"],
             "rows": [[SOURCE_LABEL.get(k, k), v] for k, v in by_source.most_common()]},
            {"title": "Hasil rekomendasi klaim yang diputus", "columns": ["Rekomendasi", "Klaim"],
             "rows": [[REC_LABEL.get(k, k), v] for k, v in by_rec.most_common()]},
        ],
    }

    # --- C. Telaah Utilisasi (Pasal 29-30)
    signed = [r for c in claims for r in c.recommendations
              if r.state == RecommendationState.SIGNED.value and _in(r.signed_at, start, end)]
    reviews = list(db.scalars(select(Review).where(Review.claim_id.in_(ids)))) if ids else []
    done = [r for r in reviews if _in(r.finished_at, start, end)]
    with_ai = [r for r in done if r.agrees_with_ai is not None]
    escalations = [r for r in done if r.action == "ESCALATE"]
    durations = [(_utc(r.finished_at) - _utc(r.started_at)).total_seconds() / 60 for r in done if r.action != "ESCALATE"]
    assigns = list(db.scalars(select(Assignment).where(Assignment.claim_id.in_(ids)))) if ids else []
    closed = [a for a in assigns if a.status == "COMPLETED" and _in(a.closed_at, start, end)]
    on_time = sum(1 for a in closed if _utc(a.closed_at) <= _utc(a.due_at))
    findings = Counter(f.reason_code for r in signed for f in r.findings)
    reason_codes = Counter(r.reason_code for r in done if r.reason_code)
    green_full = sum(1 for c in received for r in c.recommendations
                     if r.version == 1 and r.recommendation == "PAY_FULL")
    ur = {
        "id": "C", "title": "Telaah Utilisasi",
        "basis": "Pasal 29-30 POJK 36/2025: wajib melakukan Telaah Utilisasi oleh dokter dan ahli asuransi kesehatan",
        "rows": [
            _row("Klaim baru dinilai sistem", len(received), "klaim"),
            _row("Hijau, bayar penuh tanpa telaah dokter", green_full, "klaim",
                 note="dirilis langsung sesuai aturan; tetap bisa diaudit"),
            _row("Rekomendasi ditandatangani dokter", len(signed), "rekomendasi"),
            _row("Dokter sama dengan draf AI", f"{sum(1 for r in with_ai if r.agrees_with_ai)} dari {len(with_ai)}",
                 note=f"{_pct(sum(1 for r in with_ai if r.agrees_with_ai), len(with_ai))}%" if with_ai else None),
            _row("Eskalasi dokter umum ke spesialis", len(escalations), "kasus"),
            _row("Telaah selesai dalam SLA", f"{on_time} dari {len(closed)}",
                 note=f"{_pct(on_time, len(closed))}%" if closed else None),
            _row("Rata-rata durasi telaah", _avg(durations, 1), "menit"),
        ],
        "tables": [
            {"title": "Temuan pada rekomendasi yang ditandatangani", "columns": ["Kode alasan", "Jumlah"],
             "rows": [[k, v] for k, v in findings.most_common(10)]},
            {"title": "Kode alasan perubahan oleh dokter", "columns": ["Kode alasan", "Jumlah"],
             "rows": [[k, v] for k, v in reason_codes.most_common(10)]},
        ],
    }

    # --- D. Dewan Penasihat Medis (Pasal 8-9)
    doctors = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r.doctor_id for r in done})))} if done else {}
    per_doc: dict[str, list[Review]] = defaultdict(list)
    for r in done:
        per_doc[r.doctor_id].append(r)
    doc_rows = []
    for uid, rs in sorted(per_doc.items(), key=lambda kv: -len(kv[1])):
        u = doctors.get(uid)
        signs = [r for r in rs if r.action != "ESCALATE"]
        ai = [r for r in rs if r.agrees_with_ai is not None]
        doc_rows.append([u.full_name if u else uid, ROLE_LABEL.get(u.role, u.role) if u else "-",
                         (u.specialty if u and u.specialty else "-"), len(signs), sum(1 for r in rs if r.action == "ESCALATE"),
                         _avg([(_utc(r.finished_at) - _utc(r.started_at)).total_seconds() / 60 for r in signs], 1),
                         f"{_pct(sum(1 for r in ai if r.agrees_with_ai), len(ai))}%" if ai else "-"])
    specialties = Counter((doctors[u].specialty or "Dokter umum") for u in per_doc if u in doctors)
    dpm = {
        "id": "D", "title": "Dewan Penasihat Medis (panel dokter MAB)",
        "basis": "Pasal 8-9 POJK 36/2025: DPM memberi nasihat untuk pelaksanaan Telaah Utilisasi",
        "rows": [
            _row("Dokter panel aktif dalam periode", len(per_doc), "dokter"),
            _row("Bidang", ", ".join(f"{k} ({v})" for k, v in specialties.most_common()) or "-"),
            _row("Telaah ulang banding oleh dokter berbeda", sum(1 for r in done if r.agrees_with_ai is None and r.action != "ESCALATE"),
                 "kasus"),
        ],
        "tables": [{"title": "Aktivitas per dokter",
                    "columns": ["Dokter", "Peran", "Spesialisasi", "Tanda tangan", "Eskalasi", "Rata-rata menit", "Sama dengan AI"],
                    "rows": doc_rows}],
    }

    # --- E. Fraud
    insurer_ids = [insurer.id] if insurer is not None else [i.id for i in db.scalars(select(Insurer))]
    sig_rows, total_signals, reviewed_status = [], 0, Counter()
    runs = []
    for iid in insurer_ids:
        run = db.scalar(select(FraudRun).where(FraudRun.insurer_id == iid).order_by(FraudRun.created_at.desc()).limit(1))
        if run is None:
            continue
        runs.append(run)
        sigs = list(db.scalars(select(FraudSignal).where(FraudSignal.run_id == run.id)))
        total_signals += len(sigs)
        rv = {(r.rule_id, r.entity_key): r for r in db.scalars(select(FraudReview).where(FraudReview.insurer_id == iid))}
        by_rule = Counter((s.rule_id, s.reason_code) for s in sigs)
        for s in sigs:
            r = rv.get((s.rule_id, s.entity_key))
            reviewed_status[r.status if r else "BELUM_DITELAAH"] += 1
        for (rule, code), n in by_rule.most_common():
            sig_rows.append([rule, code, n])
    reviews_in_period = list(db.scalars(select(FraudReview).where(FraudReview.insurer_id.in_(insurer_ids)))) if insurer_ids else []
    fraud = {
        "id": "E", "title": "Pengendalian fraud",
        "basis": "Sinyal fraud dari analisis terakhir; sinyal tidak mengubah rekomendasi atau keputusan klaim",
        "rows": [
            _row("Analisis terakhir", ", ".join(f"{_utc(r.created_at):%d-%m-%Y}" for r in runs) or "belum ada"),
            _row("Sinyal fraud aktif", total_signals, "sinyal"),
            _row("Ditelaah investigator dalam periode",
                 sum(1 for r in reviews_in_period if _in(r.reviewed_at, start, end)), "sinyal"),
            _row("Status telaah: dikonfirmasi / diselidiki / ditolak / belum",
                 f"{reviewed_status['CONFIRMED']} / {reviewed_status['INVESTIGATING']} / {reviewed_status['DISMISSED']} / "
                 f"{reviewed_status['BELUM_DITELAAH']}"),
        ],
        "tables": [{"title": "Sinyal per aturan", "columns": ["Aturan", "Kode", "Sinyal"], "rows": sig_rows}],
    }

    # --- F. Sengketa / banding
    disputes = list(db.scalars(select(Dispute).where(Dispute.claim_id.in_(ids)))) if ids else []
    filed = [d for d in disputes if _in(d.created_at, start, end)]
    resolved = [d for d in disputes if d.status == dispute_mod.RESOLVED and _in(d.resolved_at, start, end)]
    outcomes = Counter(d.outcome for d in resolved)
    open_now = [d for d in disputes if d.status in dispute_mod.OPEN_STATUSES]
    dispute = {
        "id": "F", "title": "Sengketa dan banding",
        "basis": "Penanganan keberatan faskes dan peserta (perlindungan konsumen, Pasal 47 POJK 36/2025)",
        "rows": [
            _row("Banding diajukan", len(filed), "banding"),
            _row("Banding diputus", len(resolved), "banding"),
            _row("Diputus dalam SLA 14 hari",
                 f"{sum(1 for d in resolved if _utc(d.resolved_at) <= _utc(d.due_at))} dari {len(resolved)}"),
            _row("Keputusan berubah (diubah + dibatalkan)",
                 f"{outcomes[dispute_mod.MODIFIED] + outcomes[dispute_mod.OVERTURNED]} dari {len(resolved)}",
                 note=f"{_pct(outcomes[dispute_mod.MODIFIED] + outcomes[dispute_mod.OVERTURNED], len(resolved))}%" if resolved else None),
            _row("Banding terbuka saat laporan dibuat", len(open_now), "banding",
                 note=f"{sum(1 for d in open_now if _utc(d.due_at) < now)} lewat SLA"),
            _row("Ditarik pengaju", sum(1 for d in disputes if d.status == dispute_mod.WITHDRAWN and _in(d.resolved_at, start, end)),
                 "banding"),
        ],
        "tables": [
            {"title": "Hasil banding", "columns": ["Hasil", "Banding"],
             "rows": [[dispute_mod.OUTCOME_LABEL[k], outcomes[k]] for k in
                      (dispute_mod.UPHELD, dispute_mod.MODIFIED, dispute_mod.OVERTURNED)]},
            {"title": "Kategori banding diajukan", "columns": ["Kategori", "Banding"],
             "rows": [[v, sum(1 for d in filed if d.category == k)] for k, v in dispute_mod.CATEGORY_LABEL.items()]},
        ],
    }

    # --- G. Kapabilitas digital dan data
    log_q = select(func.count(AuditLog.id)).where(AuditLog.occurred_at >= start, AuditLog.occurred_at < end)
    access_q = log_q.where(AuditLog.action == "DOCUMENT_ACCESS")
    if insurer is not None:
        log_q = log_q.where(AuditLog.claim_id.in_(ids)) if ids else log_q.where(False)
        access_q = access_q.where(AuditLog.claim_id.in_(ids)) if ids else access_q.where(False)
    integrated = sum(v for k, v in by_source.items() if k in ("API", "SFTP", "FHIR"))
    requests = list(db.scalars(select(DocumentRequest).where(DocumentRequest.claim_id.in_(ids)))) if ids else []
    digital = {
        "id": "G", "title": "Kapabilitas digital dan pengelolaan data",
        "basis": "Pasal 5 ayat (1) huruf b dan Pasal 7 POJK 36/2025: sistem informasi memadai, kerahasiaan dan retensi data",
        "rows": [
            _row("Klaim masuk lewat integrasi (API, SFTP, FHIR)", f"{integrated} dari {len(received)}",
                 note=f"{_pct(integrated, len(received))}%" if received else None),
            _row("Dokumen susulan diminta lewat sistem", sum(1 for r in requests if _in(r.created_at, start, end)), "permintaan"),
            _row("Entri log audit klaim dalam periode", db.scalar(log_q) or 0, "entri"),
            _row("Akses dokumen tercatat", db.scalar(access_q) or 0, "akses"),
            _row("Log audit tidak dapat diubah", "Ya", note="trigger PostgreSQL menolak UPDATE dan DELETE"),
            _row("Retensi data", "Belum diterapkan di POC",
                 note="POJK 36/2025 menyebut basis data disimpan paling singkat 10 tahun setelah polis berakhir"),
        ],
        "tables": [],
    }

    # --- H. Di luar cakupan platform
    outside = {
        "id": "H", "title": "Diisi asuransi (di luar data platform)",
        "basis": "Kewajiban POJK 36/2025 yang datanya tidak ada di platform MAB",
        "rows": [
            _row("Pembagian risiko (co-payment 5%, maks. Rp300.000 rawat jalan / Rp3.000.000 rawat inap)", "-",
                 note="Pasal 24"),
            _row("Peninjauan ulang premi paling banyak 1 kali setahun", "-", note="Pasal 21-23"),
            _row("Koordinasi manfaat dengan BPJS Kesehatan (KAPJ)", "-", note="Pasal 42-43"),
            _row("Penyedia DPM dan TPA (kerja sama tertulis)", "-", note="Pasal 8 ayat (2), Pasal 33"),
        ],
        "tables": [],
    }

    partial = now < end
    ident = {
        "id": "A", "title": "Identitas laporan", "basis": None,
        "rows": [
            _row("Perusahaan", insurer.name if insurer else "Seluruh tenant platform MAB"),
            _row("Periode", f"{start:%d-%m-%Y} s.d. {(end - timedelta(days=1)):%d-%m-%Y}",
                 note="periode berjalan, angka belum final" if partial else None),
            _row("Versi templat", TEMPLATE_VERSION),
            _row("Sumber data", "Platform MAB (klaim, rekomendasi berversi, telaah dokter, keputusan, log audit)"),
            _row("Keterangan", DATA_LABEL),
        ],
        "tables": [],
    }
    return {
        "title": "Laporan bulanan kepatuhan POJK 36/2025",
        "period": period, "insurer_name": insurer.name if insurer else None,
        "template_version": TEMPLATE_VERSION, "template_note": TEMPLATE_NOTE, "label": DATA_LABEL,
        "partial": partial, "computed_at": now.isoformat(),
        "sections": [ident, service, ur, dpm, fraud, dispute, digital, outside],
    }


def generate_report(db: Session, insurer: Insurer | None, period: str, *, trigger: str,
                    user: User | None = None, now: datetime | None = None) -> Report:
    now = now or _now()
    data = build_report_data(db, insurer, period, now=now)
    key = insurer.id if insurer else "ALL"
    rep = db.scalar(select(Report).where(Report.kind == KIND, Report.period == period, Report.scope_key == key))
    if rep is None:
        rep = Report(kind=KIND, period=period, insurer_id=insurer.id if insurer else None, scope_key=key, revision=1)
        db.add(rep)
    else:
        rep.revision += 1
    rep.template_version = TEMPLATE_VERSION
    rep.trigger = trigger
    rep.partial = data["partial"]
    rep.data = data
    rep.generated_by_id = user.id if user else None
    rep.generated_at = now
    db.flush()
    return rep


def run_schedule(db: Session, *, now: datetime | None = None) -> list[Report]:
    """Penjadwal: buat laporan bulan lalu untuk setiap tenant dan untuk seluruh platform bila belum ada.

    Aman dipanggil berulang (mis. tiap jam): laporan yang sudah ada tidak dibuat ulang.
    """
    from mab_api.audit import record

    now = now or _now()
    period = previous_period(now)
    made = []
    scopes: list[Insurer | None] = [*db.scalars(select(Insurer).order_by(Insurer.code)), None]
    for ins in scopes:
        key = ins.id if ins else "ALL"
        if db.scalar(select(Report.id).where(Report.kind == KIND, Report.period == period, Report.scope_key == key)):
            continue
        rep = generate_report(db, ins, period, trigger="SCHEDULED", now=now)
        record(db, "REPORT_GENERATED", detail={"report_id": rep.id, "period": period, "scope": key, "trigger": "SCHEDULED"})
        made.append(rep)
    return made


# ----------------------------------------------------------------------------- ekspor

def _fmt(v, unit: str | None) -> str:
    if v is None:
        return "-"
    if unit == "rupiah" and isinstance(v, (int, float)):
        return _rp(int(v))
    if isinstance(v, float):
        s = f"{v:,.2f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{s} {unit}" if unit else s
    return f"{v} {unit}" if unit and unit != "rupiah" else str(v)


def report_xlsx(rep: Report) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    data = rep.data
    wb = Workbook()
    ws = wb.active
    ws.title = "Laporan"
    bold, head = Font(bold=True), PatternFill("solid", fgColor="E2E8F0")
    ws.append([data["title"]])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"{data.get('insurer_name') or 'Seluruh tenant'} · periode {data['period']} · revisi {rep.revision} · "
               f"dibuat {_utc(rep.generated_at):%d-%m-%Y %H:%M} UTC ({'otomatis' if rep.trigger == 'SCHEDULED' else 'manual'})"])
    ws.append([data["label"].upper()])
    ws["A3"].font = Font(bold=True, color="B00000")
    ws.append([data["template_note"]])
    ws.append([])
    for sec in data["sections"]:
        ws.append([f"{sec['id']}. {sec['title']}"])
        ws.cell(ws.max_row, 1).font = Font(bold=True, size=12)
        if sec.get("basis"):
            ws.append([f"Dasar: {sec['basis']}"])
            ws.cell(ws.max_row, 1).font = Font(italic=True, color="475569")
        for r in sec["rows"]:
            ws.append([r["label"], _fmt(r["value"], r.get("unit")), r.get("note") or ""])
        for t in sec.get("tables") or []:
            ws.append([])
            ws.append([t["title"]])
            ws.cell(ws.max_row, 1).font = bold
            ws.append(t["columns"])
            for c in range(1, len(t["columns"]) + 1):
                ws.cell(ws.max_row, c).font = bold
                ws.cell(ws.max_row, c).fill = head
            for row in t["rows"] or [["(tidak ada)"]]:
                ws.append(list(row))
        ws.append([])
    ws.column_dimensions["A"].width = 62
    ws.column_dimensions["B"].width = 30
    ws.column_dimensions["C"].width = 48
    for col in "DEFG":
        ws.column_dimensions[col].width = 16
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pdf():
    from fpdf import FPDF

    from mab_api.rendering import FONT_DIRS

    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    font = next((d for d in FONT_DIRS if (d / "DejaVuSans.ttf").exists()), None)
    if font:
        pdf.add_font("dv", "", str(font / "DejaVuSans.ttf"))
        pdf.add_font("dv", "B", str(font / "DejaVuSans-Bold.ttf"))
        family, clean = "dv", (lambda s: s)
    else:
        family = "helvetica"

        def clean(s: str) -> str:
            return (s.replace("–", "-").replace("—", "-").replace("…", "...")
                    .encode("latin-1", "replace").decode("latin-1"))

    def text(s: str, size: int = 10, style: str = "", gap: float = 1.2, color=(30, 41, 59)) -> None:
        pdf.set_font(family, style, size)
        pdf.set_text_color(*color)
        pdf.multi_cell(pdf.epw, size * 0.5, clean(str(s)), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(gap)

    def table(columns: list[str], rows: list[list], size: int = 8, widths: tuple | None = None) -> None:
        pdf.set_font(family, "", size)
        pdf.set_text_color(30, 41, 59)
        with pdf.table(text_align="LEFT", line_height=size * 0.55, first_row_as_headings=True, col_widths=widths) as t:
            r = t.row()
            for c in columns:
                r.cell(clean(str(c)))
            for row in rows or [["(tidak ada)"] + [""] * (len(columns) - 1)]:
                r = t.row()
                for v in row:
                    r.cell(clean("-" if v is None else str(v)))
        pdf.ln(2)

    return pdf, text, table


def report_pdf(rep: Report) -> bytes:
    data = rep.data
    pdf, text, table = _pdf()
    text(f"{data['label'].upper()} - bukan laporan resmi", 8, "B", color=(176, 0, 0))
    text(data["title"], 15, "B", 1)
    text(f"{data.get('insurer_name') or 'Seluruh tenant platform'} · periode {data['period']} · revisi {rep.revision} · "
         f"dibuat {_utc(rep.generated_at):%d-%m-%Y %H:%M} UTC ({'otomatis' if rep.trigger == 'SCHEDULED' else 'manual'})",
         9, color=(71, 85, 105))
    text(data["template_note"], 8, color=(146, 64, 14), gap=3)
    for sec in data["sections"]:
        text(f"{sec['id']}. {sec['title']}", 12, "B", 0.5)
        if sec.get("basis"):
            text(f"Dasar: {sec['basis']}", 8, color=(71, 85, 105))
        table(["Indikator", "Nilai", "Catatan"],
              [[r["label"], _fmt(r["value"], r.get("unit")), r.get("note") or ""] for r in sec["rows"]])
        for t in sec.get("tables") or []:
            text(t["title"], 9, "B", 0.5)
            table(t["columns"], t["rows"])
        pdf.ln(2)
    return bytes(pdf.output())


def trace_pdf(trace: dict) -> bytes:
    c = trace["claim"]
    pdf, text, table = _pdf()
    text(f"{trace['label'].upper()} - bukan dokumen klaim sungguhan", 8, "B", color=(176, 0, 0))
    text(f"Jejak keputusan klaim {c['claim_number']}", 15, "B", 1)
    text(f"{c.get('insurer_name') or '-'} · {c['hospital_name']} · peserta {c['member_id']} · status {c['status']} · "
         f"dibuat {_utc(trace['generated_at']):%d-%m-%Y %H:%M} UTC", 9, color=(71, 85, 105), gap=3)
    text("Mata rantai keputusan", 12, "B", 0.5)
    for i, line in enumerate(trace["chain"], 1):
        text(f"{i}. {line}", 9, gap=0.6)
    pdf.ln(2)
    text("Linimasa", 12, "B", 0.5)
    table(["Waktu (UTC)", "Tahap", "Kejadian", "Pelaku", "Rincian"],
          [[f"{_utc(s['at']):%d-%m-%Y %H:%M:%S}", s["stage"], s["title"], s.get("actor") or "", s.get("detail") or ""]
           for s in trace["steps"]], size=7)
    text("Dokumen sumber", 12, "B", 0.5)
    table(["File", "Jenis", "SHA-256"], [[d["filename"], d["doc_type"], d["sha256"]] for d in trace["documents"]], size=7)
    text(f"Log audit klaim ({len(trace['audit'])} entri)", 12, "B", 0.5)
    table(["Waktu (UTC)", "Aksi", "Pengguna", "Status"],
          [[f"{_utc(a['occurred_at']):%d-%m-%Y %H:%M:%S}", a["label"], a.get("user_name") or "-", a.get("status_code") or ""]
           for a in trace["audit"]], size=7)
    return bytes(pdf.output())
