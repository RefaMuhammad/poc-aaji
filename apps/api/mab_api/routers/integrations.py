"""API integrasi untuk sistem asuransi/TPA, memakai kunci API akun layanan (header X-API-Key).

Cakupan kunci:
- claims:read    baca status klaim dan rekomendasi yang sudah dirilis (U1), ClaimResponse FHIR
- claims:write   kirim klaim + dokumen (multipart) atau Bundle FHIR R4 (U2)
- policies:write kirim/perbarui data polis peserta (U2)
Setiap panggilan tercatat di log audit. Hasil proses dikirim lewat webhook (lihat webhooks.py).
"""
from __future__ import annotations

import hmac
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from mab_api import audit
from mab_api.access import tenant_ids
from mab_api.api_schemas import (
    ClaimCreate,
    IntegrationClaimOut,
    IntegrationSubmitOut,
    IntegrationWhoAmI,
    PolicyImportOut,
    PolicyIn,
)
from mab_api.batch import DuplicateClaim, create_claim, queue_claim
from mab_api.config import get_settings
from mab_api.db import get_db
from mab_api.deps import get_queue, get_storage, require_perm
from mab_api.documents import InvalidFile, validate_file
from mab_api.fhir import FhirError, claim_response, parse_bundle
from mab_api.models import ApiClient, AuditLog, Claim, ClaimSource, Insurer, IntegrationJob, User
from mab_api.policies import upsert_policies
from mab_api.rbac import Perm
from mab_api.tenancy import tenant_config
from mab_api.webhooks import verify
from mab_api.webhooks import claim_status
from mab_api.security import hash_api_key, split_api_key

router = APIRouter(prefix="/integrations/v1", tags=["integrasi"])


def api_client(scope: str | None):
    def dependency(request: Request, x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)) -> ApiClient:
        invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Kunci API tidak valid atau sudah dicabut",
                                headers={"WWW-Authenticate": "ApiKey"})
        prefix = split_api_key(x_api_key or "")
        if prefix is None:
            raise invalid
        client = db.scalar(select(ApiClient).where(ApiClient.key_prefix == prefix))
        if client is None or not client.is_active or not hmac.compare_digest(client.key_hash, hash_api_key(x_api_key)):
            raise invalid
        if scope is not None and scope not in (client.scopes or []):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Kunci API tidak punya cakupan {scope}")
        client.last_used_at = datetime.now(timezone.utc)
        audit.record(db, "INTEGRATION_ACCESS", request=request, user_role="api_client",
                     detail={"api_client_id": client.id, "insurer_id": client.insurer_id, "scope": scope})
        db.commit()
        return client

    return dependency


def _claim_out(c: Claim) -> IntegrationClaimOut:
    return IntegrationClaimOut(**claim_status(c))


@router.get("/whoami", response_model=IntegrationWhoAmI)
def whoami(db: Session = Depends(get_db), client: ApiClient = Depends(api_client(None))) -> IntegrationWhoAmI:
    insurer = db.get(Insurer, client.insurer_id)
    return IntegrationWhoAmI(client=client.name, tenant_code=insurer.code, scopes=list(client.scopes))


@router.get("/claims", response_model=list[IntegrationClaimOut])
def list_claims(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    client: ApiClient = Depends(api_client("claims:read")),
) -> list[IntegrationClaimOut]:
    """Klaim milik tenant kunci API ini saja."""
    q = select(Claim).where(Claim.insurer_id == client.insurer_id)
    if status_filter:
        q = q.where(Claim.status == status_filter)
    return [_claim_out(c) for c in db.scalars(q.order_by(Claim.created_at.desc()).limit(limit).offset(offset))]


@router.get("/claims/{claim_number}", response_model=IntegrationClaimOut)
def get_claim(claim_number: str, db: Session = Depends(get_db),
              client: ApiClient = Depends(api_client("claims:read"))) -> IntegrationClaimOut:
    claim = db.scalar(select(Claim).where(Claim.insurer_id == client.insurer_id, Claim.claim_number == claim_number))
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Klaim tidak ditemukan")
    return _claim_out(claim)


# ----------------------------------------------------------------------------- U2: data masuk


def _job(db: Session, client: ApiClient, channel: str, reference: str | None, status_: str, summary: dict) -> IntegrationJob:
    job = IntegrationJob(insurer_id=client.insurer_id, channel=channel, reference=(reference or "")[:255] or None,
                         status=status_, summary=summary, api_client_id=client.id)
    db.add(job)
    db.flush()
    return job


def _submit(db: Session, storage, queue, client: ApiClient, body: ClaimCreate, files: list, source: ClaimSource,
            reference: str | None, extra: dict | None = None, primary_icd10: str | None = None) -> IntegrationSubmitOut:
    try:
        claim = create_claim(db, storage, client.insurer_id, body, files, source=source, api_client_id=client.id)
    except DuplicateClaim as exc:
        db.rollback()
        _job(db, client, source.value, reference or body.claim_number, "FAILED", {"error": str(exc), **(extra or {})})
        db.commit()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if primary_icd10:
        claim.primary_icd10 = primary_icd10[:16]  # petunjuk awal; diganti hasil baca resume medis
    _job(db, client, source.value, reference or body.claim_number, "SUCCESS",
         {"claim_id": claim.id, "claim_number": claim.claim_number, "documents": len(files), **(extra or {})})
    db.commit()
    job_id = queue_claim(claim, queue)
    db.commit()
    return IntegrationSubmitOut(claim_number=claim.claim_number, claim_id=claim.id, status=claim.status, source=source.value,
                                documents=len(files), job_id=job_id)


@router.post("/claims", response_model=IntegrationSubmitOut, status_code=status.HTTP_202_ACCEPTED)
def submit_claim(
    metadata: str = Form(..., description='JSON: {"claim_number", "policy_number", "member_id", "patient_name", '
                                          '"hospital_name", "admission_date", "discharge_date", "billed_amount"}'),
    files: list[UploadFile] = File(..., description="Dokumen klaim (PDF/JPG/PNG)"),
    db: Session = Depends(get_db),
    storage=Depends(get_storage),
    queue=Depends(get_queue),
    client: ApiClient = Depends(api_client("claims:write")),
) -> IntegrationSubmitOut:
    """Kirim satu klaim beserta dokumennya. Klaim langsung masuk antrean proses; hasilnya dikirim lewat
    webhook `claim.recommendation_released` atau dibaca dengan GET /integrations/v1/claims/{nomor}."""
    try:
        body = ClaimCreate.model_validate_json(metadata)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "metadata tidak valid: " + "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()))
    if body.insurer_id and body.insurer_id != client.insurer_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Kunci API hanya untuk tenant pemiliknya")
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    try:
        valid = [validate_file(f.filename or "dokumen", f.file.read(max_bytes + 1)) for f in files]
    except InvalidFile as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return _submit(db, storage, queue, client, body, valid, ClaimSource.API, body.claim_number)


@router.post("/fhir", response_model=IntegrationSubmitOut, status_code=status.HTTP_202_ACCEPTED)
def submit_fhir_bundle(
    bundle: dict = Body(..., description="FHIR R4 Bundle: Patient, Coverage, Encounter, Claim, Observation, DocumentReference"),
    db: Session = Depends(get_db),
    storage=Depends(get_storage),
    queue=Depends(get_queue),
    client: ApiClient = Depends(api_client("claims:write")),
) -> IntegrationSubmitOut:
    """Kirim klaim sebagai FHIR R4 Bundle. Dokumen dibawa di DocumentReference.content.attachment.data (base64)."""
    try:
        mapped = parse_bundle(bundle)
    except FhirError as exc:
        _job(db, client, "FHIR", str(bundle.get("id") or "")[:255] if isinstance(bundle, dict) else None, "FAILED", {"error": str(exc)})
        db.commit()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    return _submit(db, storage, queue, client, mapped.claim, mapped.files, ClaimSource.FHIR,
                   mapped.bundle_id or mapped.claim.claim_number, {"resources": mapped.counts}, mapped.primary_icd10)


@router.get("/fhir/ClaimResponse/{claim_number}")
def fhir_claim_response(claim_number: str, db: Session = Depends(get_db),
                        client: ApiClient = Depends(api_client("claims:read"))) -> JSONResponse:
    """ClaimResponse FHIR R4 untuk klaim tenant ini. Rekomendasi hanya terisi bila sudah dirilis."""
    claim = db.scalar(select(Claim).where(Claim.insurer_id == client.insurer_id, Claim.claim_number == claim_number))
    if claim is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Klaim tidak ditemukan")
    cfg = tenant_config(db, client.insurer_id)
    return JSONResponse(claim_response(claim, cfg.display_name or cfg.name or ""), media_type="application/fhir+json")


@router.put("/policies", response_model=PolicyImportOut)
def put_policies(
    policies: list[PolicyIn],
    db: Session = Depends(get_db),
    client: ApiClient = Depends(api_client("policies:write")),
) -> PolicyImportOut:
    """Tambah atau perbarui polis peserta (kolom sama dengan file impor). Plan benefit harus sudah terdaftar."""
    if len(policies) > 5000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Maksimal 5000 polis per panggilan")
    rows = [p.model_dump(mode="json") for p in policies]
    result = upsert_policies(db, client.insurer_id, rows, source="API")
    job = _job(db, client, "POLICY_API", f"{len(rows)} polis", result.status, result.summary())
    db.commit()
    return PolicyImportOut(job_id=job.id, status=result.status, created=result.created, updated=result.updated,
                           errors=result.errors[:50])


# ----------------------------------------------------------------------------- penerima webhook demo

demo_router = APIRouter(prefix="/integrations/demo-sink", tags=["integrasi"])


async def _raw_body(request: Request) -> bytes:
    return await request.body()


@demo_router.post("/{tenant_code}", include_in_schema=True)
def demo_sink(tenant_code: str, request: Request, body: bytes = Depends(_raw_body), db: Session = Depends(get_db)) -> dict:
    """Penerima webhook untuk DEMO saja: berperan sebagai "sistem inti asuransi" rekaan.
    Memeriksa tanda tangan HMAC dengan rahasia tenant lalu mencatat isinya di log audit."""
    if not get_settings().demo_mode:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tidak tersedia")
    insurer = db.scalar(select(Insurer).where(Insurer.code == tenant_code))
    if insurer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant tidak ditemukan")
    cfg = tenant_config(db, insurer.id)
    signature = request.headers.get("X-MAB-Signature")
    valid = verify(cfg.webhook_secret, body, signature) if cfg.webhook_secret else None
    if valid is False:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Tanda tangan webhook tidak cocok")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body bukan JSON")
    audit.record(db, "WEBHOOK_DEMO_RECEIVED", request=request, user_role="demo_sink", detail={
        "insurer_id": insurer.id, "event": request.headers.get("X-MAB-Event"),
        "delivery_id": request.headers.get("X-MAB-Delivery"), "signature_valid": valid, "payload": payload,
    })
    db.commit()
    return {"received": True, "signature_valid": valid}


@demo_router.get("")
def demo_sink_log(limit: int = Query(default=30, ge=1, le=200), db: Session = Depends(get_db),
                  user: User = Depends(require_perm(Perm.TENANT_VIEW))) -> list[dict]:
    """Webhook terakhir yang diterima penerima demo (sesuai tenant yang boleh dilihat pengguna)."""
    allowed = tenant_ids(db, user)
    rows = db.scalars(select(AuditLog).where(AuditLog.action == "WEBHOOK_DEMO_RECEIVED")
                      .order_by(AuditLog.occurred_at.desc()).limit(500))
    out = []
    for r in rows:
        d = r.detail or {}
        if allowed is not None and d.get("insurer_id") not in allowed:
            continue
        out.append({"received_at": r.occurred_at, **d})
        if len(out) >= limit:
            break
    return out
