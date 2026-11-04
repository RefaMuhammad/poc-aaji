"""Job RQ. Orkestrasi pipeline lengkap dikerjakan di M4."""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def ping() -> str:
    """Job uji untuk memastikan worker menerima antrean."""
    return "pong"


def process_claim(claim_id: str, session_factory=None) -> str:
    """Proses satu klaim.

    M3: hanya menandai klaim sedang diproses. Ingest, OCR, ekstraksi, aturan,
    dan triase ditambahkan di M4 dan M5.
    """
    from mab_api.db import make_session_factory
    from mab_api.models import Claim, ClaimStatus

    session_factory = session_factory or make_session_factory()
    with session_factory() as db:
        claim = db.get(Claim, claim_id)
        if claim is None:
            log.warning("Klaim %s tidak ditemukan", claim_id)
            return "missing"
        claim.status = ClaimStatus.PROCESSING.value
        db.commit()
        log.info("Klaim %s ditandai PROCESSING (pipeline baca dokumen menyusul di M4)", claim_id)
        return claim.status
