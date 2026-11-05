"""Webhook keluar ke sistem asuransi (U2).

Peristiwa:
- claim.recommendation_released : rekomendasi boleh dilihat asuransi (bayar penuh, atau sudah ditandatangani dokter)
- claim.decision_recorded       : asuransi mencatat keputusan
- claim.processing_failed       : pipeline gagal memproses klaim
- claim.documents_requested     : U4, asuransi menunda klaim dan meminta dokumen susulan ke faskes
- claim.dispute_filed           : U5, faskes/peserta mengajukan banding atas keputusan
- claim.dispute_resolved        : U5, asuransi memutus ulang klaim hasil banding

Payload hanya berisi rekomendasi yang SUDAH dirilis (draf yang menunggu dokter tidak pernah dikirim).
Setiap pengiriman ditandatangani HMAC-SHA256 atas body mentah dengan rahasia webhook tenant:
    X-MAB-Signature: sha256=<hex>
    X-MAB-Event: <nama peristiwa>
    X-MAB-Delivery: <id pengiriman>
Pengiriman berjalan di worker (RQ) dengan percobaan ulang; riwayatnya di tabel webhook_deliveries.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.orm import Session

from mab_api.models import Claim, Insurer, RecommendationCode, RecommendationState, WebhookDelivery

log = logging.getLogger(__name__)

EVENTS = ("claim.recommendation_released", "claim.decision_recorded", "claim.processing_failed",
          "claim.documents_requested", "claim.dispute_filed", "claim.dispute_resolved")
LABEL = "Data rekaan untuk demonstrasi"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def released(rec) -> bool:
    return rec.recommendation == RecommendationCode.PAY_FULL.value or rec.state == RecommendationState.SIGNED.value


def current_decision(c: Claim):
    """Keputusan asuransi atas rekomendasi yang berlaku sekarang.

    Setelah dokumen susulan (U4) klaim diproses ulang dan mendapat rekomendasi baru; keputusan
    "tunda" atas rekomendasi lama tidak lagi berlaku sebagai keputusan klaim.
    """
    rec = next((r for r in reversed(c.recommendations) if r.is_current), None)
    if rec is None:
        return None
    return next((d for d in reversed(c.decisions) if d.recommendation_id == rec.id), None)


def claim_status(c: Claim) -> dict:
    """Status klaim untuk sistem asuransi (dipakai API integrasi dan webhook)."""
    rec = next((r for r in reversed(c.recommendations) if r.is_current), None)
    ok = rec is not None and released(rec)
    dec = current_decision(c)
    return {
        "claim_number": c.claim_number,
        "status": c.status,
        "source": c.source,
        "billed_amount": c.billed_amount,
        "updated_at": c.updated_at,
        "triage_status": rec.triage_status if ok else None,
        "recommendation": rec.recommendation if ok else None,
        "recommended_amount": rec.recommended_amount if ok else None,
        "reason_codes": sorted({f.reason_code for f in rec.findings}) if ok else [],
        "signed_by": rec.signed_by.full_name if ok and rec.signed_by else None,
        "signed_at": rec.signed_at if ok else None,
        "ruleset_version": rec.ruleset_version if ok else None,
        "benefit_ruleset_version": rec.benefit_ruleset_version if ok else None,
        "model_version": rec.model_version if ok else None,
        "decision": dec.decision if dec else None,
        "processing_error": c.processing_error if c.status == "FAILED" else None,
    }


def sign(secret: str | None, body: bytes) -> str | None:
    if not secret:
        return None
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, signature: str | None) -> bool:
    expected = sign(secret, body)
    return bool(signature and expected and hmac.compare_digest(expected, signature))


def queue_event(db: Session, claim: Claim, event: str) -> WebhookDelivery | None:
    """Catat satu pengiriman (PENDING) bila tenant punya URL webhook. Kirim setelah commit lewat `dispatch`."""
    from mab_api.tenancy import tenant_config

    assert event in EVENTS, event
    cfg = tenant_config(db, claim.insurer_id)
    if not cfg.webhook_url:
        return None
    db.flush()
    db.refresh(claim)
    insurer = db.get(Insurer, claim.insurer_id)
    delivery = WebhookDelivery(insurer_id=claim.insurer_id, event=event, claim_id=claim.id, url=cfg.webhook_url)
    db.add(delivery)
    db.flush()
    delivery.payload = json.loads(json.dumps({
        "event": event,
        "delivery_id": delivery.id,
        "occurred_at": _now(),
        "tenant": insurer.code if insurer else None,
        "claim": claim_status(claim),
        "label": LABEL,
    }, default=str))
    return delivery


def dispatch(queue, deliveries: list[WebhookDelivery | None]) -> None:
    """Masukkan pengiriman ke antrean. Panggil SETELAH commit supaya worker menemukan barisnya."""
    for d in deliveries:
        if d is None:
            continue
        try:
            queue.enqueue_webhook(d.id)
        except Exception:  # antrean mati tidak boleh menggagalkan aksi pengguna; bisa dikirim ulang dari halaman tenant
            log.exception("Gagal memasukkan webhook %s ke antrean", d.id)


class WebhookError(RuntimeError):
    pass


def deliver(db: Session, delivery: WebhookDelivery, post: Callable | None = None, *, timeout: float = 5.0,
            max_attempts: int = 3) -> bool:
    """Satu percobaan kirim. Gagal + masih ada jatah -> WebhookError (RQ mencoba lagi); jatah habis -> FAILED."""
    from mab_api.tenancy import tenant_config

    if delivery.status == "DELIVERED":
        return True
    cfg = tenant_config(db, delivery.insurer_id)
    body = json.dumps(delivery.payload, ensure_ascii=False, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "MAB-POC-Webhook/1.0",
               "X-MAB-Event": delivery.event, "X-MAB-Delivery": delivery.id}
    signature = sign(cfg.webhook_secret, body)
    if signature:
        headers["X-MAB-Signature"] = signature
    if post is None:
        import httpx

        def post(url, content, headers):  # noqa: E306
            return httpx.post(url, content=content, headers=headers, timeout=timeout)

    delivery.attempts = (delivery.attempts or 0) + 1
    error = None
    try:
        resp = post(delivery.url, content=body, headers=headers)
        delivery.last_status_code = resp.status_code
        if 200 <= resp.status_code < 300:
            delivery.status, delivery.delivered_at, delivery.last_error = "DELIVERED", _now(), None
            db.commit()
            return True
        error = f"HTTP {resp.status_code}"
    except Exception as exc:  # jaringan, DNS, timeout
        error = f"{type(exc).__name__}: {exc}"[:500]
    delivery.last_error = error
    delivery.status = "FAILED" if delivery.attempts >= max_attempts else "PENDING"
    db.commit()
    if delivery.status == "PENDING":
        raise WebhookError(error)
    return False
