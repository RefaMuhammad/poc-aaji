"""Manajemen sengketa / banding (U5).

1. Faskes atau peserta mengajukan banding atas keputusan klaim yang tidak dibayar penuh, dengan alasan
   dan (opsional) dokumen pendukung, paling lambat `WINDOW_DAYS` hari setelah keputusan (`file_dispute`).
2. Rekomendasi yang dibanding disalin menjadi draf telaah ulang (`dispute_id`). Penandatangan rekomendasi
   itu dicatat sebagai `excluded_reviewer_id`: ia TIDAK boleh menelaah bandingnya sendiri. Banding selalu
   masuk antrean dokter spesialis (lihat `assignment.routing`).
3. Dokter lain menelaah dan menandatangani. Hasil telaah ulang dibandingkan dengan rekomendasi lama
   (`outcome_of`): UPHELD (dikuatkan), MODIFIED (diubah), OVERTURNED (dibatalkan, dibayar penuh).
4. Asuransi memutus ulang atas rekomendasi baru; sengketa RESOLVED.
Setiap langkah tercatat di log audit (DISPUTE_FILED, DISPUTE_REVIEWED, DISPUTE_RESOLVED, DISPUTE_WITHDRAWN).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from mab_api import audit, notify
from mab_api.models import (
    AssignmentStatus,
    Claim,
    ClaimStatus,
    DecisionCode,
    Dispute,
    Finding,
    Recommendation,
    RecommendationCode,
    RecommendationState,
    Role,
    User,
)

WINDOW_DAYS = 30   # batas waktu mengajukan banding sejak keputusan
SLA_DAYS = 14      # batas waktu penyelesaian banding (telaah ulang + putusan ulang)

IN_REVIEW, AWAITING_DECISION, RESOLVED, WITHDRAWN = "IN_REVIEW", "AWAITING_DECISION", "RESOLVED", "WITHDRAWN"
OPEN_STATUSES = (IN_REVIEW, AWAITING_DECISION)
UPHELD, MODIFIED, OVERTURNED = "UPHELD", "MODIFIED", "OVERTURNED"

CATEGORY_LABEL = {
    "CLINICAL": "Penilaian medis",
    "COVERAGE": "Penjaminan / polis",
    "BILLING": "Nilai pembayaran",
    "OTHER": "Lainnya",
}
OUTCOME_LABEL = {UPHELD: "dikuatkan", MODIFIED: "diubah", OVERTURNED: "dibatalkan"}
FILER_ROLES = (Role.FACILITY_OFFICER.value, Role.MEMBER.value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _current(claim: Claim) -> Recommendation | None:
    return next((r for r in reversed(claim.recommendations) if r.is_current), None)


def disputes_for(db: Session, claim: Claim) -> list[Dispute]:
    return list(db.scalars(select(Dispute).where(Dispute.claim_id == claim.id).order_by(Dispute.created_at)))


def open_dispute_for(db: Session, claim: Claim) -> Dispute | None:
    return db.scalar(select(Dispute).where(Dispute.claim_id == claim.id, Dispute.status.in_(OPEN_STATUSES)))


def eligibility(db: Session, claim: Claim) -> str | None:
    """None bila klaim boleh dibanding sekarang; selain itu alasannya (untuk ditampilkan di portal)."""
    from mab_api.webhooks import current_decision

    if open_dispute_for(db, claim) is not None:
        return "Banding untuk klaim ini sedang berjalan"
    rec, dec = _current(claim), current_decision(claim)
    if claim.status != ClaimStatus.COMPLETED.value or rec is None or dec is None:
        return "Banding bisa diajukan setelah asuransi memutuskan klaim"
    if rec.dispute_id or db.scalar(select(Dispute.id).where(Dispute.decision_id == dec.id, Dispute.status != WITHDRAWN)):
        return "Banding atas klaim ini sudah diputus; banding hanya satu tingkat"
    if rec.recommendation == RecommendationCode.PAY_FULL.value and dec.decision == DecisionCode.AGREE.value:
        return "Klaim sudah dibayar penuh"
    if _aware(dec.decided_at) + timedelta(days=WINDOW_DAYS) < _now():
        return f"Batas waktu banding ({WINDOW_DAYS} hari sejak keputusan) sudah lewat"
    return None


def file_dispute(db: Session, storage, claim: Claim, user: User, *, category: str, reason: str, files: list,
                 doc_types: list[str] | None, request=None) -> Dispute:
    """Ajukan banding. `files` adalah ValidFile yang sudah divalidasi."""
    from mab_api.assignment import auto_assign, close_active
    from mab_api.doc_requests import KNOWN_DOC_TYPES
    from mab_api.documents import store_document
    from mab_api.webhooks import current_decision

    blocked = eligibility(db, claim)
    if blocked:
        raise HTTPException(status.HTTP_409_CONFLICT, blocked)
    if category not in CATEGORY_LABEL:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Kategori banding tidak dikenal")
    reason = (reason or "").strip()
    if len(reason) < 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Tuliskan alasan banding (minimal 10 karakter)")
    declared = list(doc_types or [])
    if declared and len(declared) != len(files):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Jumlah jenis dokumen harus sama dengan jumlah file")

    old, dec = _current(claim), current_decision(claim)
    docs = []
    for i, f in enumerate(files):
        doc = store_document(db, storage, claim, user, f)
        kind = (declared[i] if declared else "").strip()
        if kind:
            if kind not in KNOWN_DOC_TYPES:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Jenis dokumen tidak dikenal: {kind}")
            doc.doc_type = kind
        docs.append(doc)

    d = Dispute(claim_id=claim.id, insurer_id=claim.insurer_id, decision_id=dec.id, disputed_recommendation_id=old.id,
                original_reviewer_id=old.signed_by_id, raised_by_id=user.id, raised_by_role=user.role,
                category=category, reason=reason[:4000], document_ids=[x.id for x in docs], status=IN_REVIEW,
                due_at=_now() + timedelta(days=SLA_DAYS))
    db.add(d)
    db.flush()

    # Draf telaah ulang: salinan rekomendasi yang dibanding, ditandai sengketa. Ini keputusan dokter
    # sebelumnya, bukan draf AI baru; dokter penelaah banding yang menetapkan hasil akhirnya.
    flag = {"code": "DISPUTE", "message": f"Banding {CATEGORY_LABEL[category].lower()} dari "
                                          f"{'faskes' if user.role == Role.FACILITY_OFFICER.value else 'peserta'}: {reason[:300]}"}
    draft = Recommendation(
        claim_id=claim.id, version=max(r.version for r in claim.recommendations) + 1, is_current=True,
        state=RecommendationState.DRAFT.value, triage_status=old.triage_status, risk_score=old.risk_score,
        recommendation=old.recommendation, billed_amount=old.billed_amount, recommended_amount=old.recommended_amount,
        line_adjustments=list(old.line_adjustments or []), guideline_refs=list(old.guideline_refs or []),
        next_action=None, explanation_text=old.explanation_text, quality_flags=[flag] + list(old.quality_flags or []),
        model_version=old.model_version, prompt_version=old.prompt_version, ruleset_version=old.ruleset_version,
        benefit_ruleset_version=old.benefit_ruleset_version, dispute_id=d.id, excluded_reviewer_id=old.signed_by_id,
    )
    old.is_current = False
    db.add(draft)
    db.flush()
    for f in old.findings:
        db.add(Finding(claim_id=claim.id, recommendation_id=draft.id, rule_id=f.rule_id, reason_code=f.reason_code,
                       severity=f.severity, source=f.source, text=f.text, evidence=list(f.evidence or []),
                       guideline_refs=list(f.guideline_refs or [])))
    d.review_recommendation_id = draft.id
    claim.status = ClaimStatus.AWAITING_DOCTOR.value
    close_active(db, claim, AssignmentStatus.CANCELLED)
    claim.assigned_doctor_id = None
    audit.record(db, "DISPUTE_FILED", user_id=user.id, user_role=user.role, claim_id=claim.id, request=request,
                 detail={"dispute_id": d.id, "category": category, "decision_id": dec.id,
                         "disputed_recommendation_id": old.id, "excluded_reviewer_id": old.signed_by_id,
                         "documents": [x.id for x in docs]})
    db.flush()
    db.refresh(claim)
    auto_assign(db, claim, request=request)
    notify.dispute_filed(db, claim, d, user)
    return d


def outcome_of(old: Recommendation, new: Recommendation) -> str:
    if new.recommendation == old.recommendation and new.recommended_amount == old.recommended_amount:
        return UPHELD
    if new.recommendation == RecommendationCode.PAY_FULL.value:
        return OVERTURNED
    return MODIFIED


def on_signed(db: Session, claim: Claim, signed: Recommendation, doctor: User, notes: str | None, request=None) -> None:
    """Dipanggil `review.sign` untuk draf telaah ulang: catat hasil telaah dokter."""
    d = db.get(Dispute, signed.dispute_id)
    if d is None or d.status != IN_REVIEW:
        return
    old = db.get(Recommendation, d.disputed_recommendation_id)
    d.status = AWAITING_DECISION
    d.reviewer_id = doctor.id
    d.reviewed_at = _now()
    d.review_outcome = outcome_of(old, signed)
    d.review_notes = notes
    d.new_recommendation_id = signed.id
    audit.record(db, "DISPUTE_REVIEWED", user_id=doctor.id, user_role=doctor.role, claim_id=claim.id, request=request,
                 detail={"dispute_id": d.id, "review_outcome": d.review_outcome, "recommendation_id": signed.id,
                         "from": [old.recommendation, old.recommended_amount],
                         "to": [signed.recommendation, signed.recommended_amount]})
    notify.dispute_reviewed(db, claim, d)


def on_decided(db: Session, claim: Claim, rec: Recommendation, decision, user: User) -> None:
    """Dipanggil saat asuransi mencatat keputusan atas rekomendasi hasil banding."""
    d = db.get(Dispute, rec.dispute_id)
    if d is None or d.status != AWAITING_DECISION:
        return
    d.status = RESOLVED
    d.outcome = d.review_outcome
    d.final_decision_id = decision.id
    d.resolved_at = _now()
    d.resolved_by_id = user.id
    audit.record(db, "DISPUTE_RESOLVED", user_id=user.id, user_role=user.role, claim_id=claim.id,
                 detail={"dispute_id": d.id, "outcome": d.outcome, "decision": decision.decision,
                         "decision_id": decision.id, "on_time": _aware(d.resolved_at) <= _aware(d.due_at)})
    notify.dispute_resolved(db, claim, d, decision.decision)


def withdraw(db: Session, claim: Claim, user: User, request=None) -> Dispute:
    """Pengaju menarik banding sebelum dokter menandatangani: rekomendasi dan keputusan lama berlaku lagi."""
    from mab_api.assignment import close_active

    d = open_dispute_for(db, claim)
    if d is None or d.raised_by_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Banding tidak ditemukan")
    if d.status != IN_REVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, "Banding sudah ditelaah dokter dan tidak bisa ditarik")
    draft = db.get(Recommendation, d.review_recommendation_id)
    old = db.get(Recommendation, d.disputed_recommendation_id)
    if draft is not None:
        draft.is_current = False
    old.is_current = True
    d.status = WITHDRAWN
    d.resolved_at = _now()
    claim.status = ClaimStatus.COMPLETED.value
    close_active(db, claim, AssignmentStatus.CANCELLED)
    claim.assigned_doctor_id = None
    audit.record(db, "DISPUTE_WITHDRAWN", user_id=user.id, user_role=user.role, claim_id=claim.id, request=request,
                 detail={"dispute_id": d.id})
    return d


def to_out(d: Dispute, db: Session):
    from mab_api.api_schemas import DisputeOut

    names = {u.id: u for u in db.scalars(select(User).where(User.id.in_(
        [i for i in (d.raised_by_id, d.reviewer_id, d.resolved_by_id, d.original_reviewer_id) if i])))}
    old = db.get(Recommendation, d.disputed_recommendation_id)
    new = db.get(Recommendation, d.new_recommendation_id) if d.new_recommendation_id else None
    open_ = d.status in OPEN_STATUSES
    return DisputeOut(
        id=d.id, claim_id=d.claim_id, status=d.status, category=d.category, category_label=CATEGORY_LABEL[d.category],
        reason=d.reason, raised_by=names[d.raised_by_id].full_name if d.raised_by_id in names else "",
        raised_by_role=d.raised_by_role, created_at=d.created_at, due_at=d.due_at,
        overdue=open_ and _aware(d.due_at) < _now(),
        document_ids=list(d.document_ids or []),
        original_reviewer=names[d.original_reviewer_id].full_name if d.original_reviewer_id in names else None,
        reviewer=names[d.reviewer_id].full_name if d.reviewer_id in names else None,
        reviewed_at=d.reviewed_at, review_outcome=d.review_outcome, review_notes=d.review_notes,
        disputed_recommendation=old.recommendation if old else None,
        disputed_amount=old.recommended_amount if old else None,
        new_recommendation=new.recommendation if new else None,
        new_amount=new.recommended_amount if new else None,
        outcome=d.outcome, outcome_label=OUTCOME_LABEL.get(d.outcome or d.review_outcome or ""),
        resolved_at=d.resolved_at,
        resolved_by=names[d.resolved_by_id].full_name if d.resolved_by_id in names else None,
    )
