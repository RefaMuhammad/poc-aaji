"""Portal faskes, portal peserta, kotak masuk, dan ringkasan TPA (U4).

Faskes dan peserta hanya melihat klaimnya sendiri (cakupan di `access.visible_claims_query`) dan
hanya informasi yang sudah final: status dalam bahasa awam, linimasa, permintaan dokumen, dan
penjelasan keputusan setelah asuransi memutuskan. Draf AI, skor risiko, dan field hasil baca
tidak pernah ditampilkan di portal ini.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mab_api import disputes as dispute_mod
from mab_api import doc_requests
from mab_api.access import get_visible_claim, tenant_ids, visible_claims_query
from mab_api.api_schemas import (
    DocumentOut,
    NotificationOut,
    PortalClaimDetail,
    PortalClaimItem,
    TimelineEvent,
    TpaTenantSummary,
    UploadResult,
)
from mab_api.db import get_db
from mab_api.deps import get_current_user, get_queue, get_storage, require_perm
from mab_api.models import Claim, ClaimStatus, Insurer, Notification, Recommendation, RecommendationCode, \
    RecommendationState, Role, TenantSettings, User
from mab_api.notify import doc_label
from mab_api.rbac import Perm, has_perm
from mab_api.routers.claims import _current_recommendation, _latest_decision, outcome_summary

router = APIRouter(tags=["portal"])

can_portal = require_perm(Perm.PORTAL_VIEW)
can_upload = require_perm(Perm.FACILITY_UPLOAD)
can_tpa = require_perm(Perm.TPA_OVERVIEW)

_STATUS_LABEL = {
    ClaimStatus.RECEIVED.value: "Diterima",
    ClaimStatus.QUEUED.value: "Sedang diperiksa",
    ClaimStatus.PROCESSING.value: "Sedang diperiksa",
    ClaimStatus.FAILED.value: "Sedang diperiksa",          # kegagalan teknis tidak dibebankan ke faskes/peserta
    ClaimStatus.AWAITING_DOCTOR.value: "Ditelaah dokter",
    ClaimStatus.AWAITING_DECISION.value: "Menunggu keputusan asuransi",
    ClaimStatus.PENDING_DOCUMENTS.value: "Menunggu dokumen dari rumah sakit",
    ClaimStatus.COMPLETED.value: "Selesai",
}


def status_label(claim: Claim, user: User, dispute=None) -> str:
    if dispute is not None:
        return "Banding sedang ditelaah ulang" if dispute.status == dispute_mod.IN_REVIEW else "Banding menunggu putusan ulang asuransi"
    if claim.status == ClaimStatus.PENDING_DOCUMENTS.value and user.role == Role.FACILITY_OFFICER.value:
        return "Menunggu dokumen dari Anda"
    return _STATUS_LABEL.get(claim.status, claim.status)


def _insurer_names(db: Session) -> dict[str, str]:
    display = {t.insurer_id: t.display_name for t in db.scalars(select(TenantSettings)) if t.display_name}
    return {i.id: display.get(i.id, i.name) for i in db.scalars(select(Insurer))}


def _outcome(claim: Claim) -> tuple[Recommendation | None, str | None]:
    """Rekomendasi final yang sudah diputuskan asuransi, dan ringkasannya. (None, None) bila belum selesai."""
    rec = _current_recommendation(claim)
    dec = _latest_decision(claim)
    if claim.status != ClaimStatus.COMPLETED.value or rec is None or dec is None:
        return None, None
    return rec, outcome_summary(rec, dec.decision)


def _item(db: Session, claim: Claim, user: User, names: dict[str, str]) -> PortalClaimItem:
    req = doc_requests.open_request_for(db, claim)
    _, outcome = _outcome(claim)
    dispute = dispute_mod.open_dispute_for(db, claim)
    blocked = dispute_mod.eligibility(db, claim)
    can_file = has_perm(user.role, Perm.DISPUTE_FILE)
    return PortalClaimItem(
        id=claim.id, claim_number=claim.claim_number, member_id=claim.member_id, patient_name=claim.patient_name,
        hospital_name=claim.hospital_name, insurer_name=names.get(claim.insurer_id),
        admission_date=claim.admission_date, discharge_date=claim.discharge_date, billed_amount=claim.billed_amount,
        status=claim.status, status_label=status_label(claim, user, dispute),
        open_request=doc_requests.to_out(req, claim) if req else None, outcome=outcome, updated_at=claim.updated_at,
        open_dispute=dispute_mod.to_out(dispute, db) if dispute else None,
        can_dispute=can_file and blocked is None, dispute_blocked_reason=blocked if can_file else None,
    )


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def timeline(db: Session, claim: Claim) -> list[TimelineEvent]:
    requests = doc_requests.requests_for(db, claim)
    late = {d for q in requests for d in (q.document_ids or [])}
    first = len([d for d in claim.documents if d.id not in late])
    ev: list[TimelineEvent] = [TimelineEvent(at=claim.created_at, title="Klaim diterima", detail=f"{first} dokumen")]
    for r in claim.recommendations:
        if r.dispute_id:
            continue  # telaah banding tampil sebagai peristiwa banding di bawah
        if r.state == RecommendationState.DRAFT.value:
            ev.append(TimelineEvent(at=r.created_at, title="Dokumen selesai diperiksa sistem",
                                    detail="Pemeriksaan ulang setelah dokumen susulan" if r.version > 1 else None))
        else:
            who = r.signed_by.full_name if r.signed_by else "dokter"
            ev.append(TimelineEvent(at=r.signed_at or r.created_at, title="Ditelaah dan ditandatangani dokter",
                                    detail=who))
    for q in requests:
        docs = ", ".join(doc_label(d) for d in q.doc_types or [])
        ev.append(TimelineEvent(at=q.created_at, title="Asuransi meminta dokumen susulan", detail=docs))
        if q.fulfilled_at:
            ev.append(TimelineEvent(at=q.fulfilled_at, title="Dokumen susulan diterima",
                                    detail=q.fulfilled_by.full_name if q.fulfilled_by else None))
        if q.status == doc_requests.CANCELLED:
            ev.append(TimelineEvent(at=q.created_at, title="Permintaan dokumen dibatalkan asuransi"))
    for disp in dispute_mod.disputes_for(db, claim):
        who = "faskes" if disp.raised_by_role == Role.FACILITY_OFFICER.value else "peserta"
        ev.append(TimelineEvent(at=disp.created_at, title=f"Banding diajukan {who}",
                                detail=dispute_mod.CATEGORY_LABEL.get(disp.category)))
        if disp.reviewed_at:
            ev.append(TimelineEvent(at=disp.reviewed_at, title="Banding ditelaah ulang dokter lain",
                                    detail=f"{disp.reviewer.full_name if disp.reviewer else ''} · "
                                           f"{dispute_mod.OUTCOME_LABEL.get(disp.review_outcome or '', '')}"))
        if disp.status == dispute_mod.WITHDRAWN and disp.resolved_at:
            ev.append(TimelineEvent(at=disp.resolved_at, title="Banding ditarik"))
        if disp.status == dispute_mod.RESOLVED and disp.resolved_at:
            ev.append(TimelineEvent(at=disp.resolved_at, title="Banding selesai",
                                    detail=f"keputusan awal {dispute_mod.OUTCOME_LABEL.get(disp.outcome or '', '')}"))
    for d in claim.decisions:
        rec = next((r for r in claim.recommendations if r.id == d.recommendation_id), None)
        if rec is not None and rec.recommendation == RecommendationCode.PEND.value and d.decision == "AGREE":
            continue  # "tunda" sudah tampil sebagai permintaan dokumen
        ev.append(TimelineEvent(at=d.decided_at, title="Asuransi mencatat keputusan",
                                detail=outcome_summary(rec, d.decision) if rec else d.decision))
    return sorted(ev, key=lambda e: _aware(e.at))


def explanation(claim: Claim, db: Session | None = None) -> str | None:
    rec, outcome = _outcome(claim)
    dispute = dispute_mod.open_dispute_for(db, claim) if db is not None else None
    if dispute is not None:
        return ("Banding Anda sedang ditelaah ulang oleh dokter yang berbeda dari penelaah awal. Setelah itu "
                "asuransi memutus ulang klaim ini. Target penyelesaian: " + dispute.due_at.strftime("%d-%m-%Y") + ".")
    if rec is None:
        if claim.status == ClaimStatus.PENDING_DOCUMENTS.value:
            return "Klaim ditunda sementara sampai dokumen yang diminta asuransi diterima, lalu diperiksa ulang."
        return None
    dec = _latest_decision(claim)
    parts = [f"Hasil klaim: {outcome}."]
    if rec.dispute_id and db is not None:
        from mab_api.models import Dispute

        disp = db.get(Dispute, rec.dispute_id)
        if disp is not None and disp.outcome:
            parts.append(f"Hasil banding: keputusan awal {dispute_mod.OUTCOME_LABEL[disp.outcome]}."
                         + (f" Catatan dokter penelaah banding: {disp.review_notes}" if disp.review_notes else ""))
    if dec.decision == "DIFFER" and dec.reason:
        parts.append(f"Alasan asuransi: {dec.reason}")
    if rec.recommendation == RecommendationCode.PAY_FULL.value and rec.state != RecommendationState.SIGNED.value:
        parts.append("Dokumen klaim lengkap dan sesuai, tidak ada temuan yang perlu ditelaah dokter.")
    elif rec.explanation_text:
        parts.append(rec.explanation_text)
    # rec.next_action ditujukan ke asuransi, tidak ditampilkan ke faskes / peserta
    return "\n\n".join(parts)


# ----------------------------------------------------------------------------- portal faskes / peserta


@router.get("/portal/claims", response_model=list[PortalClaimItem])
def portal_claims(db: Session = Depends(get_db), user: User = Depends(can_portal)) -> list[PortalClaimItem]:
    names = _insurer_names(db)
    rows = db.scalars(visible_claims_query(user, db).order_by(Claim.updated_at.desc()).limit(500))
    items = [_item(db, c, user, names) for c in rows]
    # klaim yang menunggu tindakan faskes di atas
    return sorted(items, key=lambda i: i.open_request is None)


@router.get("/portal/claims/{claim_id}", response_model=PortalClaimDetail)
def portal_claim(claim_id: str, db: Session = Depends(get_db), user: User = Depends(can_portal)) -> PortalClaimDetail:
    claim = get_visible_claim(db, user, claim_id)
    base = _item(db, claim, user, _insurer_names(db))
    rec, _ = _outcome(claim)
    dec = _latest_decision(claim)
    return PortalClaimDetail(
        **base.model_dump(),
        documents=[DocumentOut.model_validate(d) for d in claim.documents],
        timeline=timeline(db, claim),
        explanation=explanation(claim, db),
        recommended_amount=rec.recommended_amount if rec else None,
        decision=dec.decision if rec and dec else None,
        reviewer=rec.signed_by.full_name if rec and rec.signed_by else None,
        document_requests=[doc_requests.to_out(r, claim) for r in doc_requests.requests_for(db, claim)],
        disputes=[dispute_mod.to_out(d, db) for d in dispute_mod.disputes_for(db, claim)],
    )


@router.post("/portal/claims/{claim_id}/documents", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
def portal_upload(
    claim_id: str,
    request: Request,
    files: list[UploadFile] = File(...),
    doc_types: list[str] | None = Form(default=None, description="Jenis tiap file, urutan sama dengan files"),
    note: str | None = Form(default=None, max_length=2000),
    db: Session = Depends(get_db),
    user: User = Depends(can_upload),
    storage=Depends(get_storage),
    queue=Depends(get_queue),
) -> UploadResult:
    """Faskes mengunggah dokumen susulan. Bila semua dokumen yang diminta lengkap, klaim diproses ulang."""
    claim = get_visible_claim(db, user, claim_id)
    docs, _, job_id = doc_requests.upload_late(db, storage, queue, claim, user, files, doc_types, note, request=request)
    return UploadResult(documents=[DocumentOut.model_validate(d) for d in docs], job_id=job_id, status=claim.status)


# ----------------------------------------------------------------------------- kotak masuk (semua peran)


@router.get("/notifications", response_model=list[NotificationOut])
def my_notifications(unread: bool = False, db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)) -> list[Notification]:
    q = select(Notification).where(Notification.user_id == user.id)
    if unread:
        q = q.where(Notification.read_at.is_(None))
    return list(db.scalars(q.order_by(Notification.created_at.desc()).limit(200)))


@router.get("/notifications/unread-count")
def unread_count(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, int]:
    n = db.scalar(select(func.count()).select_from(Notification)
                  .where(Notification.user_id == user.id, Notification.read_at.is_(None)))
    return {"unread": int(n or 0)}


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(notification_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Notification:
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notifikasi tidak ditemukan")
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
        db.commit()
    return n


@router.post("/notifications/read-all")
def mark_all_read(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, int]:
    rows = list(db.scalars(select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))))
    now = datetime.now(timezone.utc)
    for n in rows:
        n.read_at = now
    db.commit()
    return {"updated": len(rows)}


# ----------------------------------------------------------------------------- TPA


@router.get("/tpa/summary", response_model=list[TpaTenantSummary])
def tpa_summary(db: Session = Depends(get_db), user: User = Depends(can_tpa)) -> list[TpaTenantSummary]:
    """Ringkasan antrean per asuransi yang dilayani: TPA bekerja untuk beberapa asuransi sekaligus."""
    allowed = tenant_ids(db, user)
    names = _insurer_names(db)
    ids = sorted(allowed if allowed is not None else names.keys(), key=lambda i: names.get(i, i))
    out = []
    for insurer_id in ids:
        counts = dict(db.execute(select(Claim.status, func.count()).where(Claim.insurer_id == insurer_id)
                                 .group_by(Claim.status)).all())
        overdue = 0
        pending = db.scalars(select(Claim).where(Claim.insurer_id == insurer_id,
                                                 Claim.status == ClaimStatus.PENDING_DOCUMENTS.value))
        for c in pending:
            req = doc_requests.open_request_for(db, c)
            if req is not None and doc_requests.to_out(req, c).overdue:
                overdue += 1
        out.append(TpaTenantSummary(
            insurer_id=insurer_id, insurer_name=names.get(insurer_id, insurer_id), total=sum(counts.values()),
            by_status=counts, awaiting_decision=counts.get(ClaimStatus.AWAITING_DECISION.value, 0),
            pending_documents=counts.get(ClaimStatus.PENDING_DOCUMENTS.value, 0), overdue_requests=overdue,
        ))
    return out
