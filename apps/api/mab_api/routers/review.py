"""Ruang kerja dokter: antrean, telaah, koreksi field, eskalasi, tanda tangan dengan PIN.

Aturan alur (PRD):
- Klaim kuning ditelaah dokter umum, yang boleh mengeskalasi ke spesialis.
- Klaim merah (dan hasil eskalasi) ditelaah dokter spesialis sebidang.
- Rekomendasi selain bayar penuh baru terlihat oleh asuransi setelah ditandatangani dokter.
- Setiap telaah mencatat waktu mulai/selesai dan apakah dokter setuju dengan draf AI.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from mab_api import audit
from mab_api.access import get_visible_claim, visible_claims_query
from mab_api.assignment import (
    auto_assign,
    claim_reviews,
    close_active,
    active_assignment,
    assign,
    routing,
    sla_due,
    sla_state,
)
from mab_api.api_schemas import (
    ClaimDetail,
    ClaimOut,
    DocumentOut,
    EscalateRequest,
    FieldCorrection,
    FieldHistoryOut,
    QueueItem,
    RecommendationOut,
    ReviewFieldOut,
    ReviewOut,
    SignRequest,
    Suggestion,
    Workspace,
)
from mab_api.db import get_db
from mab_api.deps import get_queue, require_roles
from mab_api.webhooks import dispatch, queue_event
from mab_api.documents import missing_documents
from mab_api.models import (
    AssignmentStatus,
    AuditLog,
    Claim,
    Insurer,
    ClaimStatus,
    ExtractedField,
    Finding,
    Recommendation,
    RecommendationCode,
    RecommendationState,
    Review,
    Role,
    User,
)
from mab_api.routers.claims import _current_recommendation, _latest_decision, build_recommendation_view
from mab_api.ruleset import active_ruleset
from mab_api.security import verify_secret
from mab_api.tenancy import tenant_config

router = APIRouter(prefix="/review", tags=["dokter"])

doctor_only = require_roles(Role.DOCTOR_GP, Role.DOCTOR_SPECIALIST)
doctor_or_admin = require_roles(Role.DOCTOR_GP, Role.DOCTOR_SPECIALIST, Role.ADMIN)

GP, SPECIALIST = "GP", "SPECIALIST"
APPROVE, MODIFY, ESCALATE = "APPROVE", "MODIFY", "ESCALATE"
FIELD_CORRECTED = "FIELD_CORRECTED"

DEFAULT_NEXT_ACTION = {
    "PAY_FULL": "Asuransi dapat mencatat keputusan bayar penuh.",
    "PAY_PARTIAL": "Asuransi dapat membayar sebesar nilai rekomendasi; item yang dikoreksi tercantum di rekomendasi.",
    "PEND": "Minta klarifikasi ke DPJP / rumah sakit sesuai temuan, lalu ajukan ulang untuk telaah.",
    "NOT_COVERED": "Sampaikan ke peserta dan rumah sakit bahwa klaim tidak dijamin sesuai penjelasan.",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:  # SQLite menyimpan tanpa zona waktu
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ----------------------------------------------------------------------------- bantuan


def _reviews(db: Session, claim: Claim) -> list[Review]:
    return claim_reviews(db, claim)


def _open_review(reviews: list[Review], doctor: User) -> Review | None:
    return next((r for r in reviews if r.doctor_id == doctor.id and r.finished_at is None), None)


def _routing(claim: Claim, rec: Recommendation | None, reviews: list[Review]) -> tuple[str, str | None, bool, str | None]:
    return routing(claim, rec, reviews)


def _blocked_reason(user: User, claim: Claim, rec: Recommendation | None, level: str, specialty: str | None) -> str | None:
    """None bila dokter ini boleh menelaah klaim; selain itu alasannya."""
    if claim.status != ClaimStatus.AWAITING_DOCTOR.value or rec is None or rec.state != RecommendationState.DRAFT.value:
        return "Klaim tidak sedang menunggu telaah dokter"
    if claim.assigned_doctor_id and claim.assigned_doctor_id != user.id:
        return "Klaim sedang ditelaah dokter lain"
    if user.role == Role.DOCTOR_GP.value and level == SPECIALIST:
        return "Kasus ini untuk dokter spesialis"
    if user.role == Role.DOCTOR_SPECIALIST.value:
        if level == GP:
            return "Kasus kuning ditelaah dokter umum terlebih dulu"
        if specialty and user.specialty and specialty != user.specialty:
            return f"Kasus ini untuk spesialis {specialty}"
    if user.role not in (Role.DOCTOR_GP.value, Role.DOCTOR_SPECIALIST.value):
        return "Hanya dokter yang dapat menelaah"
    return None


FINAL_LABEL = {"PAY_FULL": "bayar penuh", "PAY_PARTIAL": "bayar sebagian", "PEND": "tunda, menunggu klarifikasi / dokumen",
               "NOT_COVERED": "tidak dijamin"}


def final_explanation(draft_text: str | None, code: str, amount: int | None) -> str:
    """Penjelasan final dari draf AI: kalimat 'ini draf' dibuang, keputusan dokter ditambahkan."""
    lines = []
    for line in (draft_text or "").splitlines():
        if line.startswith("Ini draf dari sistem") or line.startswith("Usulan koreksi tagihan untuk ditinjau dokter"):
            continue
        if line.startswith("Sistem menemukan") and "perlu ditelaah dokter" in line:
            line = "Hasil telaah dokter atas klaim ini:"
        lines.append(line)
    verdict = f"Rekomendasi dokter: {FINAL_LABEL[code]}"
    if code == "PAY_PARTIAL" and amount is not None:
        verdict += ", dibayar Rp" + f"{amount:,}".replace(",", ".")
    lines.append(verdict + ".")
    return "\n".join(lines)


def suggest_final(rec: Recommendation) -> Suggestion:
    """Usulan rekomendasi final dari draf AI. Draf tidak pernah mengusulkan 'tidak dijamin'."""
    if rec.recommendation in (RecommendationCode.PAY_FULL.value, RecommendationCode.PEND.value,
                              RecommendationCode.PAY_PARTIAL.value, RecommendationCode.NOT_COVERED.value):
        return Suggestion(recommendation=rec.recommendation, recommended_amount=rec.recommended_amount)
    if rec.line_adjustments:
        return Suggestion(recommendation=RecommendationCode.PAY_PARTIAL.value, recommended_amount=rec.recommended_amount)
    # Ada temuan klinis tanpa koreksi nilai: usulannya klarifikasi dulu, bukan menolak.
    return Suggestion(recommendation=RecommendationCode.PEND.value, recommended_amount=None)


def _review_out(r: Review, names: dict[str, User]) -> ReviewOut:
    doc = names.get(r.doctor_id)
    started, finished = _aware(r.started_at), _aware(r.finished_at)
    return ReviewOut(
        id=r.id,
        doctor=doc.full_name if doc else r.doctor_id,
        doctor_specialty=doc.specialty if doc else None,
        action=r.action,
        reason_code=r.reason_code,
        agrees_with_ai=r.agrees_with_ai,
        escalated_specialty=r.escalated_specialty,
        notes=r.notes,
        started_at=started,
        finished_at=finished,
        duration_seconds=int((finished - started).total_seconds()) if finished else None,
    )


def _users(db: Session, ids: set[str | None]) -> dict[str, User]:
    ids = {i for i in ids if i}
    return {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def _require_open_review(db: Session, claim: Claim, user: User) -> tuple[Review, Recommendation]:
    rec = _current_recommendation(claim)
    reviews = _reviews(db, claim)
    review = _open_review(reviews, user)
    if review is None or rec is None or review.recommendation_id != rec.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Mulai telaah klaim ini terlebih dulu")
    if claim.status != ClaimStatus.AWAITING_DOCTOR.value or rec.state != RecommendationState.DRAFT.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Klaim tidak sedang menunggu telaah dokter")
    return review, rec


# ----------------------------------------------------------------------------- antrean


@router.get("/queue", response_model=list[QueueItem])
def queue(
    icd: str | None = Query(default=None, description="Filter awalan kode ICD-10, mis. A91"),
    done: bool = Query(default=False, description="true: klaim yang sudah saya tandatangani"),
    db: Session = Depends(get_db),
    user: User = Depends(doctor_only),
) -> list[QueueItem]:
    """Antrean kasus untuk dokter ini: yang lewat SLA dulu, lalu skor risiko tertinggi, lalu yang paling lama menunggu."""
    q = visible_claims_query(user, db)
    if done:
        q = q.where(Claim.status != ClaimStatus.AWAITING_DOCTOR.value)
    else:
        q = q.where(Claim.status == ClaimStatus.AWAITING_DOCTOR.value)
    if icd:
        q = q.where(Claim.primary_icd10.startswith(icd.strip().upper()))
    claims = list(db.scalars(q))
    assigned = _users(db, {c.assigned_doctor_id for c in claims})
    insurers = {i.id: i for i in db.scalars(select(Insurer))}
    configs: dict[str, object] = {}
    now = _now()
    items: list[QueueItem] = []
    for c in claims:
        rec = _current_recommendation(c)
        if rec is None:
            continue
        if done and rec.signed_by_id != user.id:
            continue
        reviews = _reviews(db, c)
        level, specialty, escalated, dx_name = _routing(c, rec, reviews)
        if not done and _blocked_reason(user, c, rec, level, specialty) is not None:
            continue
        doctor = assigned.get(c.assigned_doctor_id or "")
        cfg = configs.setdefault(c.insurer_id, tenant_config(db, c.insurer_id))
        due = sla_due(rec, reviews, level, cfg)
        signed_at = _aware(rec.signed_at)
        insurer = insurers.get(c.insurer_id)
        items.append(QueueItem(
            id=c.id, claim_number=c.claim_number, hospital_name=c.hospital_name, admission_date=c.admission_date,
            discharge_date=c.discharge_date, billed_amount=c.billed_amount, primary_icd10=c.primary_icd10,
            diagnosis_name=dx_name, status=c.status, triage_status=rec.triage_status, risk_score=rec.risk_score,
            findings=len(rec.findings), level=level, specialty=specialty, escalated=escalated,
            assigned_to=doctor.full_name if doctor else None, assigned_to_me=c.assigned_doctor_id == user.id,
            waiting_since=_aware(rec.created_at),
            signed_by=rec.signed_by.full_name if rec.signed_by else None, signed_at=signed_at,
            insurer_name=(cfg.display_name or (insurer.name if insurer else None)),
            sla_hours=cfg.sla_hours(level), sla_due_at=due,
            sla_state=None if done else sla_state(due, level, cfg, now),
            sla_met=(signed_at <= due) if done and signed_at else None,
        ))
    if done:
        items.sort(key=lambda i: i.signed_at or i.waiting_since, reverse=True)
    else:
        # yang sudah lewat SLA paling atas, lalu skor risiko tertinggi, lalu yang paling lama menunggu
        items.sort(key=lambda i: (i.sla_state != "OVERDUE", -(i.risk_score or 0), i.waiting_since))
    return items


# ----------------------------------------------------------------------------- layar telaah


@router.get("/{claim_id}", response_model=Workspace)
def workspace(claim_id: str, db: Session = Depends(get_db), user: User = Depends(doctor_or_admin)) -> Workspace:
    claim = get_visible_claim(db, user, claim_id)
    rec = _current_recommendation(claim)
    reviews = _reviews(db, claim)
    level, specialty, escalated, dx_name = _routing(claim, rec, reviews)
    blocked = _blocked_reason(user, claim, rec, level, specialty)
    mine = _open_review(reviews, user)

    fields = list(db.scalars(select(ExtractedField).where(ExtractedField.claim_id == claim.id).order_by(ExtractedField.field_path)))
    history_rows = list(db.scalars(
        select(AuditLog).where(AuditLog.claim_id == claim.id, AuditLog.action == FIELD_CORRECTED).order_by(AuditLog.occurred_at)
    ))
    names = _users(db, {r.doctor_id for r in reviews} | {f.corrected_by_id for f in fields}
                   | {h.user_id for h in history_rows} | {claim.assigned_doctor_id})
    kamus = active_ruleset().data_dictionary
    dec = _latest_decision(claim)
    detail = ClaimDetail(
        **ClaimOut.model_validate(claim).model_dump(),
        documents=[DocumentOut.model_validate(d) for d in claim.documents],
        missing_documents=missing_documents(claim),
        triage_status=rec.triage_status if rec else None,
        recommendation_available=rec is not None,
        awaiting_doctor=rec is not None and rec.state == RecommendationState.DRAFT.value
        and rec.recommendation != RecommendationCode.PAY_FULL.value,
        decision=dec.decision if dec else None,
    )
    assigned = names.get(claim.assigned_doctor_id or "")
    return Workspace(
        claim=detail,
        level=level,
        specialty=specialty,
        diagnosis_name=dx_name,
        escalated=escalated,
        assigned_to=assigned.full_name if assigned else None,
        can_start=blocked is None and user.role != Role.ADMIN.value,
        blocked_reason=blocked,
        my_review=_review_out(mine, names) if mine else None,
        reviews=[_review_out(r, names) for r in reviews],
        draft=build_recommendation_view(claim, rec) if rec else None,
        suggestion=suggest_final(rec) if rec and rec.state == RecommendationState.DRAFT.value else None,
        fields=[
            ReviewFieldOut(
                id=f.id, field_path=f.field_path, label=(kamus.get(f.field_path) or {}).get("ket"),
                kind=(kamus.get(f.field_path) or {}).get("tipe"), value=f.value, source=f.source,
                confidence=f.confidence, status=f.status, evidence=f.evidence or [],
                corrected_value=f.corrected_value, corrected=f.corrected_at is not None,
                corrected_by=names[f.corrected_by_id].full_name if f.corrected_by_id in names else None,
                corrected_at=_aware(f.corrected_at),
            )
            for f in fields
        ],
        field_history=[
            FieldHistoryOut(
                field_path=h.detail.get("field_path", ""), old=h.detail.get("old"), new=h.detail.get("new"),
                note=h.detail.get("note"), by=names[h.user_id].full_name if h.user_id in names else None,
                at=_aware(h.occurred_at),
            )
            for h in history_rows
        ],
        reason_codes=active_ruleset().reason_codes,
    )


@router.post("/{claim_id}/start", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def start_review(claim_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(doctor_only)) -> ReviewOut:
    """Ambil kasus: klaim dikunci untuk dokter ini dan waktu telaah mulai dihitung."""
    claim = get_visible_claim(db, user, claim_id)
    rec = _current_recommendation(claim)
    reviews = _reviews(db, claim)
    mine = _open_review(reviews, user)
    if mine is not None and rec is not None and mine.recommendation_id == rec.id:
        return _review_out(mine, _users(db, {user.id}))
    level, specialty, _, _ = _routing(claim, rec, reviews)
    blocked = _blocked_reason(user, claim, rec, level, specialty)
    if blocked:
        code = status.HTTP_403_FORBIDDEN if "untuk" in blocked or "terlebih" in blocked else status.HTTP_409_CONFLICT
        raise HTTPException(code, blocked)
    review = Review(claim_id=claim.id, recommendation_id=rec.id, doctor_id=user.id, started_at=_now())
    db.add(review)
    current = active_assignment(db, claim)
    if current is None or current.doctor_id != user.id:
        # kasus diambil dari antrean bersama (tanpa penugasan otomatis)
        if current is not None:
            close_active(db, claim, AssignmentStatus.CANCELLED)
        assign(db, claim, rec, user, level=level, specialty=specialty,
               due=sla_due(rec, reviews, level, tenant_config(db, claim.insurer_id)), method="CLAIMED",
               actor=user, request=request)
    claim.assigned_doctor_id = user.id
    db.flush()
    audit.record(db, "REVIEW_STARTED", user_id=user.id, user_role=user.role, claim_id=claim.id,
                 detail={"review_id": review.id, "level": level}, request=request)
    db.commit()
    return _review_out(review, {user.id: user})


@router.post("/{claim_id}/release", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def release_review(claim_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(doctor_only)) -> Response:
    """Lepas kasus tanpa keputusan (kembali ke antrean)."""
    claim = get_visible_claim(db, user, claim_id)
    review, _ = _require_open_review(db, claim, user)
    review.finished_at = _now()
    review.action = "RELEASED"
    claim.assigned_doctor_id = None
    close_active(db, claim, AssignmentStatus.RELEASED)
    audit.record(db, "REVIEW_RELEASED", user_id=user.id, user_role=user.role, claim_id=claim.id,
                 detail={"review_id": review.id}, request=request)
    db.flush()
    auto_assign(db, claim, exclude={user.id}, request=request)  # ke dokter lain bila ada; bila tidak, antrean bersama
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{claim_id}/fields/{field_id}", response_model=ReviewFieldOut)
def correct_field(
    claim_id: str, field_id: str, body: FieldCorrection, request: Request,
    db: Session = Depends(get_db), user: User = Depends(doctor_only),
) -> ReviewFieldOut:
    """Koreksi nilai field hasil ekstraksi. Nilai asli tetap disimpan; setiap perubahan tercatat."""
    claim = get_visible_claim(db, user, claim_id)
    _require_open_review(db, claim, user)
    field = db.get(ExtractedField, field_id)
    if field is None or field.claim_id != claim.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Field tidak ditemukan")
    old = field.corrected_value if field.corrected_at is not None else field.value
    field.corrected_value = body.value
    field.corrected_by_id = user.id
    field.corrected_at = _now()
    note = (body.note or "").strip() or None
    audit.record(db, FIELD_CORRECTED, user_id=user.id, user_role=user.role, claim_id=claim.id,
                 detail={"field_id": field.id, "field_path": field.field_path, "old": old, "new": body.value, "note": note},
                 request=request)
    db.commit()
    kamus = active_ruleset().data_dictionary.get(field.field_path) or {}
    return ReviewFieldOut(
        id=field.id, field_path=field.field_path, label=kamus.get("ket"), kind=kamus.get("tipe"), value=field.value,
        source=field.source, confidence=field.confidence, status=field.status, evidence=field.evidence or [],
        corrected_value=field.corrected_value, corrected=True, corrected_by=user.full_name, corrected_at=_aware(field.corrected_at),
    )


@router.post("/{claim_id}/escalate", response_model=ReviewOut)
def escalate(claim_id: str, body: EscalateRequest, request: Request, db: Session = Depends(get_db),
             user: User = Depends(require_roles(Role.DOCTOR_GP))) -> ReviewOut:
    """Dokter umum meneruskan kasus ke dokter spesialis."""
    claim = get_visible_claim(db, user, claim_id)
    review, rec = _require_open_review(db, claim, user)
    _, specialty, _, _ = _routing(claim, rec, _reviews(db, claim))
    review.action = ESCALATE
    review.escalated_specialty = (body.specialty or "").strip() or specialty
    review.notes = body.notes.strip()
    review.finished_at = _now()
    claim.assigned_doctor_id = None
    close_active(db, claim, AssignmentStatus.ESCALATED)
    audit.record(db, "REVIEW_ESCALATED", user_id=user.id, user_role=user.role, claim_id=claim.id,
                 detail={"review_id": review.id, "specialty": review.escalated_specialty}, request=request)
    db.flush()
    auto_assign(db, claim, request=request)
    db.commit()
    return _review_out(review, {user.id: user})


@router.post("/{claim_id}/sign", response_model=RecommendationOut)
def sign(claim_id: str, body: SignRequest, request: Request, db: Session = Depends(get_db),
         user: User = Depends(doctor_only), queue=Depends(get_queue)) -> RecommendationOut:
    """Tetapkan dan tandatangani rekomendasi final (konfirmasi PIN).

    Draf AI disimpan sebagai versi lama; rekomendasi final menjadi versi baru berstatus SIGNED.
    """
    claim = get_visible_claim(db, user, claim_id)
    review, rec = _require_open_review(db, claim, user)

    if not user.pin_hash:
        raise HTTPException(status.HTTP_409_CONFLICT, "PIN tanda tangan Anda belum diatur. Hubungi admin.")
    if not verify_secret(body.pin, user.pin_hash):
        audit.record(db, "SIGN_PIN_FAILED", user_id=user.id, user_role=user.role, claim_id=claim.id, request=request)
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "PIN salah")

    adjustments = list(rec.line_adjustments or [])
    kept_idx = list(range(len(adjustments))) if body.kept_adjustments is None else sorted(set(body.kept_adjustments))
    if any(i < 0 or i >= len(adjustments) for i in kept_idx):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indeks koreksi item tidak valid")

    code = body.recommendation
    billed = rec.billed_amount
    if code == "PAY_FULL":
        amount, kept = billed, []
    elif code == "NOT_COVERED":
        amount, kept = 0, []
    elif code == "PEND":
        amount, kept = None, []
    else:  # PAY_PARTIAL
        kept = [adjustments[i] for i in kept_idx]
        amount = body.recommended_amount
        if amount is None:
            amount = max(billed - sum(int(a.get("amount", 0)) for a in kept), 0)
        if amount >= billed:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nilai bayar sebagian harus lebih kecil dari nilai tagihan")

    suggestion = suggest_final(rec)
    agrees = (
        code == suggestion.recommendation
        and amount == suggestion.recommended_amount
        and (code != "PAY_PARTIAL" or kept_idx == list(range(len(adjustments))))
    )
    reason_code = (body.reason_code or "").strip() or None
    reason_codes = active_ruleset().reason_codes
    if not agrees and not reason_code:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kode alasan wajib diisi bila mengubah draf AI")
    if reason_code and reason_code not in reason_codes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Kode alasan '{reason_code}' tidak dikenal")

    now = _now()
    signed = Recommendation(
        claim_id=claim.id,
        version=max(r.version for r in claim.recommendations) + 1,
        is_current=True,
        state=RecommendationState.SIGNED.value,
        triage_status=rec.triage_status,
        risk_score=rec.risk_score,
        recommendation=code,
        billed_amount=billed,
        recommended_amount=amount,
        line_adjustments=kept,
        guideline_refs=list(rec.guideline_refs or []),
        next_action=(body.next_action or "").strip() or DEFAULT_NEXT_ACTION[code],
        explanation_text=(body.explanation_text or "").strip() or final_explanation(rec.explanation_text, code, amount),
        quality_flags=list(rec.quality_flags or []),
        model_version=rec.model_version,
        prompt_version=rec.prompt_version,
        ruleset_version=rec.ruleset_version,
        benefit_ruleset_version=rec.benefit_ruleset_version,
        signed_by_id=user.id,
        signed_at=now,
    )
    rec.is_current = False
    db.add(signed)
    db.flush()
    for f in rec.findings:
        db.add(Finding(claim_id=claim.id, recommendation_id=signed.id, rule_id=f.rule_id, reason_code=f.reason_code,
                       severity=f.severity, source=f.source, text=f.text, evidence=list(f.evidence or []),
                       guideline_refs=list(f.guideline_refs or [])))

    review.action = APPROVE if agrees else MODIFY
    review.agrees_with_ai = agrees
    review.reason_code = reason_code
    review.notes = (body.notes or "").strip() or None
    review.finished_at = now
    claim.status = ClaimStatus.AWAITING_DECISION.value
    close_active(db, claim, AssignmentStatus.COMPLETED, now)
    started = _aware(review.started_at)
    audit.record(db, "RECOMMENDATION_SIGNED", user_id=user.id, user_role=user.role, claim_id=claim.id, request=request,
                 detail={"recommendation_id": signed.id, "version": signed.version, "recommendation": code,
                         "recommended_amount": amount, "agrees_with_ai": agrees, "reason_code": reason_code,
                         "review_seconds": int((now - started).total_seconds())})
    hook = queue_event(db, claim, "claim.recommendation_released")
    db.commit()
    dispatch(queue, [hook])
    db.refresh(claim)
    db.refresh(signed)
    return build_recommendation_view(claim, signed)
