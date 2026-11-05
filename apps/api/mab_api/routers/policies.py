"""Polis peserta dan plan benefit (U2). Data dari sistem inti asuransi: impor CSV/XLSX atau API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from mab_api import audit
from mab_api.access import tenant_ids
from mab_api.api_schemas import BenefitPlanIn, BenefitPlanOut, PolicyImportOut, PolicyOut
from mab_api.db import get_db
from mab_api.deps import require_perm
from mab_api.models import BenefitPlan, Insurer, IntegrationJob, Policy, User
from mab_api.policies import POLICY_COLUMNS, read_rows, upsert_policies
from mab_api.rbac import Perm

router = APIRouter(prefix="/policies", tags=["polis"])

can_view = require_perm(Perm.POLICY_VIEW)
can_manage = require_perm(Perm.POLICY_MANAGE)
MAX_IMPORT_BYTES = 10 * 1024 * 1024


def target_tenant(db: Session, user: User, requested: str | None) -> str:
    """Tenant yang dikelola. Admin dan TPA memilih lewat insurer_id; staf asuransi memakai tenantnya."""
    allowed = tenant_ids(db, user)
    if allowed is None:
        if not requested or db.get(Insurer, requested) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pilih asuransi (insurer_id)")
        return requested
    if requested:
        if requested not in allowed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant tidak ditemukan")
        return requested
    if user.insurer_id and user.insurer_id in allowed:
        return user.insurer_id
    if len(allowed) == 1:
        return next(iter(allowed))
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pilih asuransi (insurer_id)")


def policy_out(p: Policy) -> PolicyOut:
    plan = p.plan
    remaining = max(plan.annual_limit - (p.limit_used or 0), 0) if plan.annual_limit is not None else None
    return PolicyOut(
        id=p.id, insurer_id=p.insurer_id, policy_number=p.policy_number, member_id=p.member_id, member_name=p.member_name,
        plan_code=plan.code, plan_name=plan.name, room_class=plan.room_class, room_rate_limit=plan.room_rate_limit,
        annual_limit=plan.annual_limit, waiting_period_days=plan.waiting_period_days or 0,
        excluded_icd10=list(plan.excluded_icd10 or []), start_date=p.start_date, end_date=p.end_date, status=p.status,
        limit_used=p.limit_used or 0, limit_remaining=remaining, source=p.source, updated_at=p.updated_at,
    )


@router.get("/plans", response_model=list[BenefitPlanOut])
def list_plans(insurer_id: str | None = None, db: Session = Depends(get_db), user: User = Depends(can_view)):
    tenant = target_tenant(db, user, insurer_id)
    counts = dict(db.execute(select(Policy.plan_id, func.count()).where(Policy.insurer_id == tenant).group_by(Policy.plan_id)).all())
    plans = db.scalars(select(BenefitPlan).where(BenefitPlan.insurer_id == tenant).order_by(BenefitPlan.code))
    return [BenefitPlanOut.model_validate(p).model_copy(update={"policy_count": counts.get(p.id, 0)}) for p in plans]


@router.put("/plans", response_model=BenefitPlanOut)
def upsert_plan(body: BenefitPlanIn, request: Request, db: Session = Depends(get_db), user: User = Depends(can_manage)):
    """Tambah atau ubah plan benefit (berdasarkan kode). Berlaku untuk klaim yang diproses setelahnya."""
    tenant = target_tenant(db, user, body.insurer_id)
    plan = db.scalar(select(BenefitPlan).where(BenefitPlan.insurer_id == tenant, BenefitPlan.code == body.code))
    before = BenefitPlanOut.model_validate(plan).model_dump() if plan else None
    if plan is None:
        plan = BenefitPlan(insurer_id=tenant, code=body.code)
        db.add(plan)
    for key in ("name", "room_class", "room_rate_limit", "annual_limit", "waiting_period_days", "excluded_icd10"):
        setattr(plan, key, getattr(body, key))
    db.flush()
    after = BenefitPlanOut.model_validate(plan)
    audit.record(db, "BENEFIT_PLAN_SAVED", user_id=user.id, user_role=user.role, request=request,
                 detail={"insurer_id": tenant, "code": plan.code, "before": before, "after": after.model_dump()})
    db.commit()
    return after


@router.get("", response_model=list[PolicyOut])
def list_policies(
    insurer_id: str | None = None,
    q: str | None = Query(default=None, max_length=64, description="Cari nomor polis, id atau nama peserta"),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(can_view),
):
    tenant = target_tenant(db, user, insurer_id)
    query = select(Policy).where(Policy.insurer_id == tenant)
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Policy.policy_number.ilike(like), Policy.member_id.ilike(like), Policy.member_name.ilike(like)))
    rows = db.scalars(query.order_by(Policy.policy_number, Policy.member_id).limit(limit))
    return [policy_out(p) for p in rows]


@router.get("/template.csv")
def template(_: User = Depends(can_view)) -> Response:
    body = ",".join(POLICY_COLUMNS) + "\nPOL-REKAAN-001,PST-REKAAN-001,Peserta Rekaan,SILVER,2026-01-01,2026-12-31,ACTIVE,0\n"
    return Response(body, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="template_polis.csv"'})


@router.post("/import", response_model=PolicyImportOut)
async def import_policies(
    request: Request,
    file: UploadFile = File(...),
    insurer_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(can_manage),
):
    """Impor polis dari CSV/XLSX. Kolom: nomor_polis, id_peserta, nama_peserta, kode_plan, tanggal_mulai,
    tanggal_akhir, status, limit_terpakai. Baris yang salah dilewati dan dilaporkan."""
    tenant = target_tenant(db, user, insurer_id)
    name = file.filename or "polis.csv"
    if not name.lower().endswith((".csv", ".xlsx", ".xlsm")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File harus CSV atau XLSX")
    data = await file.read()
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File maksimal 10 MB")
    try:
        rows = read_rows(name, data)
    except Exception as exc:  # file rusak / bukan CSV-XLSX yang valid
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"File tidak bisa dibaca: {type(exc).__name__}")
    result = upsert_policies(db, tenant, rows)
    job = IntegrationJob(insurer_id=tenant, channel="POLICY_IMPORT", reference=name[:255], status=result.status,
                         summary=result.summary(), user_id=user.id)
    db.add(job)
    db.flush()
    audit.record(db, "POLICIES_IMPORTED", user_id=user.id, user_role=user.role, request=request,
                 detail={"insurer_id": tenant, "job_id": job.id, "file": name, **result.summary()})
    db.commit()
    return PolicyImportOut(job_id=job.id, status=result.status, created=result.created, updated=result.updated,
                           errors=result.errors[:50])
