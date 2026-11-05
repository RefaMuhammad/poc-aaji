"""Sengketa / banding (U5): ajukan & tarik banding dari portal, daftar sengketa untuk asuransi."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from mab_api import disputes
from mab_api.access import get_visible_claim, visible_claims_query
from mab_api.api_schemas import DisputeListItem, DisputeOut
from mab_api.config import get_settings
from mab_api.db import get_db
from mab_api.deps import get_queue, get_storage, require_perm
from mab_api.documents import InvalidFile, validate_file
from mab_api.models import Claim, Dispute, Insurer, TenantSettings, User
from mab_api.rbac import Perm
from mab_api.webhooks import dispatch, queue_event

router = APIRouter(tags=["sengketa"])

can_file = require_perm(Perm.DISPUTE_FILE)
can_list = require_perm(Perm.CLAIM_LIST)
can_view = require_perm(Perm.DISPUTE_VIEW)


@router.post("/portal/claims/{claim_id}/disputes", response_model=DisputeOut, status_code=status.HTTP_201_CREATED)
def file_dispute(
    claim_id: str,
    request: Request,
    category: str = Form(..., description="CLINICAL / COVERAGE / BILLING / OTHER"),
    reason: str = Form(..., max_length=4000),
    files: list[UploadFile] | None = File(default=None),
    doc_types: list[str] | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(can_file),
    storage=Depends(get_storage),
    queue=Depends(get_queue),
) -> DisputeOut:
    """Faskes atau peserta mengajukan banding atas keputusan klaim, dengan alasan dan dokumen pendukung."""
    claim = get_visible_claim(db, user, claim_id)
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    uploads = [f for f in (files or []) if f.filename]
    try:
        valid = [validate_file(f.filename or "dokumen", f.file.read(max_bytes + 1)) for f in uploads]
    except InvalidFile as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    d = disputes.file_dispute(db, storage, claim, user, category=category, reason=reason, files=valid,
                              doc_types=[t for t in (doc_types or []) if t] or None, request=request)
    hook = queue_event(db, claim, "claim.dispute_filed")
    db.commit()
    dispatch(queue, [hook])
    return disputes.to_out(d, db)


@router.post("/portal/claims/{claim_id}/disputes/withdraw", response_model=DisputeOut)
def withdraw_dispute(claim_id: str, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(can_file)) -> DisputeOut:
    claim = get_visible_claim(db, user, claim_id)
    d = disputes.withdraw(db, claim, user, request=request)
    db.commit()
    return disputes.to_out(d, db)


@router.get("/claims/{claim_id}/disputes", response_model=list[DisputeOut])
def claim_disputes(claim_id: str, db: Session = Depends(get_db), user: User = Depends(can_list)) -> list[DisputeOut]:
    claim = get_visible_claim(db, user, claim_id)
    return [disputes.to_out(d, db) for d in disputes.disputes_for(db, claim)]


@router.get("/disputes", response_model=list[DisputeListItem])
def list_disputes(
    status_filter: str | None = Query(default=None, alias="status", description="IN_REVIEW / AWAITING_DECISION / RESOLVED / WITHDRAWN / OPEN"),
    db: Session = Depends(get_db),
    user: User = Depends(can_view),
) -> list[DisputeListItem]:
    """Sengketa dalam cakupan pengguna, terbaru dulu."""
    claim_ids = select(visible_claims_query(user, db).subquery().c.id)
    q = select(Dispute).where(Dispute.claim_id.in_(claim_ids))
    if status_filter == "OPEN":
        q = q.where(Dispute.status.in_(disputes.OPEN_STATUSES))
    elif status_filter:
        q = q.where(Dispute.status == status_filter)
    display = {t.insurer_id: t.display_name for t in db.scalars(select(TenantSettings)) if t.display_name}
    names = {i.id: display.get(i.id, i.name) for i in db.scalars(select(Insurer))}
    out = []
    for d in db.scalars(q.order_by(Dispute.created_at.desc()).limit(500)):
        claim = db.get(Claim, d.claim_id)
        out.append(DisputeListItem(**disputes.to_out(d, db).model_dump(), claim_number=claim.claim_number,
                                   hospital_name=claim.hospital_name, insurer_name=names.get(claim.insurer_id)))
    return out
