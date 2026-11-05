"""Tenant (asuransi): tampilan, pengaturan triase/aturan/SLA, dan akun layanan (API key)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mab_api import audit
from mab_api.access import tenant_ids
from mab_api.api_schemas import (
    ApiClientCreate,
    ApiClientCreated,
    ApiClientOut,
    ApiScopeOut,
    IntegrationJobOut,
    WebhookDeliveryOut,
    BrandingOut,
    TenantCreate,
    TenantOut,
    TenantSettingsIn,
)
from mab_api.db import get_db
from mab_api.deps import get_current_user, get_queue, require_perm
from mab_api.models import ApiClient, Claim, Insurer, IntegrationJob, Policy, TenantSettings, User, WebhookDelivery
from mab_api.rbac import Perm
from mab_api.ruleset import active_benefit_ruleset, active_ruleset
from mab_api.security import generate_api_key
from mab_api.tenancy import all_rule_ids, apply_tenant, tenant_config
from mab_api.webhooks import dispatch
from mab_pipeline.schemas import TriageStatus

router = APIRouter(prefix="/tenants", tags=["tenant"])

API_SCOPES = {
    "claims:read": "Baca status klaim, rekomendasi yang sudah dirilis, dan ClaimResponse FHIR",
    "claims:write": "Kirim klaim + dokumen (multipart) atau Bundle FHIR R4",
    "policies:write": "Kirim atau perbarui data polis peserta",
}

tenant_admin = require_perm(Perm.TENANT_ADMIN)


def _default_threshold(status_: TriageStatus) -> int | None:
    for sr in active_ruleset().triage.status_rules:
        if sr.status == status_ and sr.min_score is not None:
            return sr.min_score
    return None


def _tenant_out(db: Session, insurer: Insurer) -> TenantOut:
    cfg = tenant_config(db, insurer.id)
    row = db.get(TenantSettings, insurer.id)
    return TenantOut(
        insurer_id=insurer.id, code=insurer.code, name=insurer.name,
        display_name=cfg.display_name, logo_data_url=cfg.logo_data_url, primary_color=cfg.primary_color,
        triage_red_min_score=cfg.triage_red_min_score, triage_yellow_min_score=cfg.triage_yellow_min_score,
        disabled_rules=list(cfg.disabled_rules), sla_gp_hours=cfg.sla_gp_hours,
        sla_specialist_hours=cfg.sla_specialist_hours, auto_assign=cfg.auto_assign, version=cfg.version,
        updated_at=row.updated_at if row else None,
        default_red_min_score=_default_threshold(TriageStatus.RED),
        default_yellow_min_score=_default_threshold(TriageStatus.YELLOW),
        effective_ruleset_version=apply_tenant(active_ruleset(), cfg).version,
        claim_count=db.scalar(select(func.count()).select_from(Claim).where(Claim.insurer_id == insurer.id)) or 0,
        webhook_url=cfg.webhook_url,
        webhook_secret_set=bool(cfg.webhook_secret),
        policy_count=db.scalar(select(func.count()).select_from(Policy).where(Policy.insurer_id == insurer.id)) or 0,
    )


def _get_insurer(db: Session, insurer_id: str) -> Insurer:
    insurer = db.get(Insurer, insurer_id)
    if insurer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant tidak ditemukan")
    return insurer


@router.get("/current", response_model=BrandingOut | None)
def current_branding(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> BrandingOut | None:
    """Tampilan tenant pengguna (logo, nama) untuk header portal. Kosong untuk pengguna platform MAB."""
    if user.insurer_id is None:
        return None
    insurer = db.get(Insurer, user.insurer_id)
    if insurer is None:
        return None
    cfg = tenant_config(db, insurer.id)
    return BrandingOut(insurer_id=insurer.id, code=insurer.code, name=insurer.name, display_name=cfg.display_name,
                       logo_data_url=cfg.logo_data_url, primary_color=cfg.primary_color)


@router.get("", response_model=list[TenantOut])
def list_tenants(db: Session = Depends(get_db), user: User = Depends(require_perm(Perm.TENANT_VIEW))) -> list[TenantOut]:
    """Admin melihat semua tenant; peran lain hanya tenant yang dilayaninya."""
    allowed = tenant_ids(db, user)
    q = select(Insurer).order_by(Insurer.code)
    if allowed is not None:
        q = q.where(Insurer.id.in_(allowed))
    return [_tenant_out(db, i) for i in db.scalars(q)]


@router.post("", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
def create_tenant(body: TenantCreate, request: Request, db: Session = Depends(get_db),
                  user: User = Depends(tenant_admin)) -> TenantOut:
    insurer = Insurer(code=body.code, name=body.name.strip())
    db.add(insurer)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"Kode tenant {body.code} sudah dipakai")
    audit.record(db, "TENANT_CREATED", user_id=user.id, user_role=user.role, request=request,
                 detail={"insurer_id": insurer.id, "code": insurer.code})
    db.commit()
    return _tenant_out(db, insurer)


def _settings_snapshot(row: TenantSettings | None) -> dict:
    if row is None:
        return {}
    logo = row.logo_data_url
    return {
        "display_name": row.display_name,
        "logo_sha256": hashlib.sha256(logo.encode()).hexdigest()[:16] if logo else None,
        "primary_color": row.primary_color,
        "triage_red_min_score": row.triage_red_min_score,
        "triage_yellow_min_score": row.triage_yellow_min_score,
        "disabled_rules": list(row.disabled_rules or []),
        "sla_gp_hours": row.sla_gp_hours,
        "sla_specialist_hours": row.sla_specialist_hours,
        "auto_assign": row.auto_assign,
        "webhook_url": row.webhook_url,
        "webhook_secret_set": bool(row.webhook_secret),
        "version": row.version,
    }


@router.put("/{insurer_id}/settings", response_model=TenantOut)
def update_settings(insurer_id: str, body: TenantSettingsIn, request: Request, db: Session = Depends(get_db),
                    user: User = Depends(tenant_admin)) -> TenantOut:
    """Simpan pengaturan tenant. Berlaku untuk klaim yang diproses SETELAH disimpan; versi naik satu."""
    insurer = _get_insurer(db, insurer_id)
    unknown = sorted(set(body.disabled_rules) - all_rule_ids(active_ruleset(), active_benefit_ruleset()))
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Aturan tidak dikenal: {', '.join(unknown)}")
    red = body.triage_red_min_score if body.triage_red_min_score is not None else _default_threshold(TriageStatus.RED)
    yellow = body.triage_yellow_min_score if body.triage_yellow_min_score is not None else _default_threshold(TriageStatus.YELLOW)
    if red is not None and yellow is not None and red <= yellow:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Ambang merah ({red}) harus lebih besar dari ambang kuning ({yellow})")

    row = db.get(TenantSettings, insurer.id)
    before = _settings_snapshot(row)
    if row is None:
        row = TenantSettings(insurer_id=insurer.id, version=0)
        db.add(row)
    for key, value in body.model_dump(exclude={"webhook_secret"}).items():
        setattr(row, key, value)
    if body.webhook_secret is not None:  # None = rahasia lama dipertahankan, "" = dihapus
        row.webhook_secret = body.webhook_secret or None
    row.version = (row.version or 0) + 1
    row.updated_by_id = user.id
    row.updated_at = datetime.now(timezone.utc)
    db.flush()
    audit.record(db, "TENANT_SETTINGS_UPDATED", user_id=user.id, user_role=user.role, request=request,
                 detail={"insurer_id": insurer.id, "before": before, "after": _settings_snapshot(row)})
    db.commit()
    return _tenant_out(db, insurer)


# ----------------------------------------------------------------------------- akun layanan


@router.get("/api-scopes", response_model=list[ApiScopeOut])
def api_scopes(_: User = Depends(require_perm(Perm.TENANT_VIEW))) -> list[ApiScopeOut]:
    return [ApiScopeOut(scope=k, description=v) for k, v in API_SCOPES.items()]


@router.get("/{insurer_id}/api-clients", response_model=list[ApiClientOut])
def list_api_clients(insurer_id: str, db: Session = Depends(get_db), _: User = Depends(tenant_admin)) -> list[ApiClient]:
    _get_insurer(db, insurer_id)
    return list(db.scalars(select(ApiClient).where(ApiClient.insurer_id == insurer_id).order_by(ApiClient.created_at)))


@router.post("/{insurer_id}/api-clients", response_model=ApiClientCreated, status_code=status.HTTP_201_CREATED)
def create_api_client(insurer_id: str, body: ApiClientCreate, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(tenant_admin)) -> ApiClientCreated:
    """Buat akun layanan. Kunci API hanya ditampilkan di respons ini; yang disimpan hanya hash-nya."""
    _get_insurer(db, insurer_id)
    scopes = sorted(set(body.scopes))
    unknown = [s for s in scopes if s not in API_SCOPES]
    if unknown or not scopes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            f"Cakupan tidak dikenal: {', '.join(unknown) or '(kosong)'}. Pilihan: {', '.join(API_SCOPES)}")
    key, prefix, key_hash = generate_api_key()
    client = ApiClient(insurer_id=insurer_id, name=body.name.strip(), key_prefix=prefix, key_hash=key_hash,
                       scopes=scopes, created_by_id=user.id)
    db.add(client)
    db.flush()
    audit.record(db, "API_CLIENT_CREATED", user_id=user.id, user_role=user.role, request=request,
                 detail={"api_client_id": client.id, "insurer_id": insurer_id, "key_prefix": prefix, "scopes": scopes})
    db.commit()
    return ApiClientCreated(**ApiClientOut.model_validate(client).model_dump(), api_key=key)


@router.post("/{insurer_id}/api-clients/{client_id}/revoke", response_model=ApiClientOut)
def revoke_api_client(insurer_id: str, client_id: str, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(tenant_admin)) -> ApiClient:
    client = db.get(ApiClient, client_id)
    if client is None or client.insurer_id != insurer_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Akun layanan tidak ditemukan")
    if client.is_active:
        client.is_active = False
        client.revoked_at = datetime.now(timezone.utc)
        audit.record(db, "API_CLIENT_REVOKED", user_id=user.id, user_role=user.role, request=request,
                     detail={"api_client_id": client.id, "insurer_id": insurer_id, "key_prefix": client.key_prefix})
        db.commit()
    return client


# ----------------------------------------------------------------------------- riwayat integrasi & webhook


def _viewable_tenant(db: Session, user: User, insurer_id: str) -> Insurer:
    insurer = _get_insurer(db, insurer_id)
    allowed = tenant_ids(db, user)
    if allowed is not None and insurer_id not in allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant tidak ditemukan")
    return insurer


@router.get("/{insurer_id}/integration-jobs", response_model=list[IntegrationJobOut])
def integration_jobs(insurer_id: str, limit: int = 50, db: Session = Depends(get_db),
                     user: User = Depends(require_perm(Perm.TENANT_VIEW))) -> list[IntegrationJob]:
    """Riwayat data masuk: API, FHIR, SFTP, impor polis."""
    _viewable_tenant(db, user, insurer_id)
    q = select(IntegrationJob).where(IntegrationJob.insurer_id == insurer_id)
    return list(db.scalars(q.order_by(IntegrationJob.created_at.desc()).limit(min(max(limit, 1), 200))))


@router.get("/{insurer_id}/webhook-deliveries", response_model=list[WebhookDeliveryOut])
def webhook_deliveries(insurer_id: str, limit: int = 50, db: Session = Depends(get_db),
                       user: User = Depends(require_perm(Perm.TENANT_VIEW))) -> list[WebhookDelivery]:
    _viewable_tenant(db, user, insurer_id)
    q = select(WebhookDelivery).where(WebhookDelivery.insurer_id == insurer_id)
    return list(db.scalars(q.order_by(WebhookDelivery.created_at.desc()).limit(min(max(limit, 1), 200))))


@router.post("/{insurer_id}/webhook-deliveries/{delivery_id}/resend", response_model=WebhookDeliveryOut)
def resend_webhook(insurer_id: str, delivery_id: str, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(tenant_admin), queue=Depends(get_queue)) -> WebhookDelivery:
    """Kirim ulang webhook (mis. setelah sistem asuransi pulih). Isi payload sama; URL memakai pengaturan terbaru."""
    delivery = db.get(WebhookDelivery, delivery_id)
    if delivery is None or delivery.insurer_id != insurer_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pengiriman tidak ditemukan")
    cfg = tenant_config(db, insurer_id)
    if not cfg.webhook_url:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tenant belum punya URL webhook")
    delivery.url = cfg.webhook_url
    delivery.status, delivery.attempts, delivery.last_error, delivery.last_status_code = "PENDING", 0, None, None
    delivery.delivered_at = None
    audit.record(db, "WEBHOOK_RESEND", user_id=user.id, user_role=user.role, request=request, claim_id=delivery.claim_id,
                 detail={"delivery_id": delivery.id, "event": delivery.event, "insurer_id": insurer_id})
    db.commit()
    dispatch(queue, [delivery])
    db.refresh(delivery)
    return delivery
