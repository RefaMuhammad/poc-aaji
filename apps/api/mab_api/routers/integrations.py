"""API integrasi untuk sistem asuransi/TPA, memakai kunci API akun layanan (header X-API-Key).

U1 menyediakan endpoint baca saja (cakupan `claims:read`). Pengiriman klaim lewat API,
webhook, SFTP, dan FHIR menyusul di U2. Setiap panggilan tercatat di log audit.
"""
from __future__ import annotations

import hmac
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from mab_api import audit
from mab_api.api_schemas import IntegrationClaimOut, IntegrationWhoAmI
from mab_api.db import get_db
from mab_api.models import ApiClient, Claim, Insurer
from mab_api.routers.claims import _current_recommendation, _latest_decision, _released_to_insurer
from mab_api.security import hash_api_key, split_api_key

router = APIRouter(prefix="/integrations/v1", tags=["integrasi"])


def api_client(scope: str):
    def dependency(request: Request, x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)) -> ApiClient:
        invalid = HTTPException(status.HTTP_401_UNAUTHORIZED, "Kunci API tidak valid atau sudah dicabut",
                                headers={"WWW-Authenticate": "ApiKey"})
        prefix = split_api_key(x_api_key or "")
        if prefix is None:
            raise invalid
        client = db.scalar(select(ApiClient).where(ApiClient.key_prefix == prefix))
        if client is None or not client.is_active or not hmac.compare_digest(client.key_hash, hash_api_key(x_api_key)):
            raise invalid
        if scope not in (client.scopes or []):
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Kunci API tidak punya cakupan {scope}")
        client.last_used_at = datetime.now(timezone.utc)
        audit.record(db, "INTEGRATION_ACCESS", request=request, user_role="api_client",
                     detail={"api_client_id": client.id, "insurer_id": client.insurer_id, "scope": scope})
        db.commit()
        return client

    return dependency


def _claim_out(c: Claim) -> IntegrationClaimOut:
    rec = _current_recommendation(c)
    released = rec is not None and _released_to_insurer(rec)
    dec = _latest_decision(c)
    return IntegrationClaimOut(
        claim_number=c.claim_number, status=c.status, billed_amount=c.billed_amount, updated_at=c.updated_at,
        triage_status=rec.triage_status if released else None,
        recommendation=rec.recommendation if released else None,
        recommended_amount=rec.recommended_amount if released else None,
        reason_codes=sorted({f.reason_code for f in rec.findings}) if released else [],
        signed_by=rec.signed_by.full_name if released and rec.signed_by else None,
        signed_at=rec.signed_at if released else None,
        ruleset_version=rec.ruleset_version if released else None,
        model_version=rec.model_version if released else None,
        decision=dec.decision if dec else None,
    )


@router.get("/whoami", response_model=IntegrationWhoAmI)
def whoami(db: Session = Depends(get_db), client: ApiClient = Depends(api_client("claims:read"))) -> IntegrationWhoAmI:
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
