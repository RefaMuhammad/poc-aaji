"""Job RQ: proses satu klaim.

M4: baca dokumen (ingest, OCR, klasifikasi, ekstraksi LLM, field turunan), simpan
field beserta bukti lokasinya, lalu status klaim menjadi EXTRACTED.
Penalaran klinis, aturan, dan rekomendasi ditambahkan di M5.
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)


def ping() -> str:
    """Job uji untuk memastikan worker menerima antrean."""
    return "pong"


def _default_storage():
    from mab_api.config import get_settings
    from mab_api.storage import S3Storage

    s = get_settings()
    return S3Storage(s.s3_endpoint_url, s.s3_bucket, s.minio_root_user, s.minio_root_password)


def _required_docs() -> tuple[str, ...]:
    from mab_api.config import get_settings
    from mab_pipeline.extraction.derived_fields import DEFAULT_REQUIRED_DOCS
    from mab_pipeline.rules import load_rules

    try:
        docs = load_rules(get_settings().rules_path).triage.required_inpatient_docs
    except (OSError, ValueError):
        log.warning("File aturan tidak terbaca; memakai daftar dokumen wajib bawaan")
        return DEFAULT_REQUIRED_DOCS
    return tuple(docs) or DEFAULT_REQUIRED_DOCS


def _evidence(line_ids: list[str], lines: dict) -> tuple[list[dict], float | None]:
    evidence = []
    confidences = []
    for line_id in line_ids:
        line = lines.get(line_id)
        if line is None:
            continue
        evidence.append({"document_id": line.document_id, "page": line.page, "bbox": list(line.bbox), "quote": line.text, "line_id": line.id})
        confidences.append(line.confidence)
    return evidence, (round(min(confidences), 3) if confidences else None)


def _overlapping_claims(db, claim) -> list[Any]:
    from sqlalchemy import select

    from mab_api.models import Claim

    return list(
        db.scalars(
            select(Claim).where(
                Claim.insurer_id == claim.insurer_id,
                Claim.member_id == claim.member_id,
                Claim.id != claim.id,
                Claim.admission_date <= claim.discharge_date,
                Claim.discharge_date >= claim.admission_date,
            )
        )
    )


def process_claim(claim_id: str, session_factory=None, storage=None, llm=None, ocr=None) -> str:
    from sqlalchemy import delete

    from mab_api.audit import record
    from mab_api.db import make_session_factory
    from mab_api.models import Claim, ClaimStatus, ExtractedField
    from mab_pipeline.llm.client import get_llm_client
    from mab_pipeline.ocr.engine import get_ocr_engine
    from mab_pipeline.pipeline import InputDocument, read_claim

    session_factory = session_factory or make_session_factory()
    with session_factory() as db:
        claim = db.get(Claim, claim_id)
        if claim is None:
            log.warning("Klaim %s tidak ditemukan", claim_id)
            return "missing"
        claim.status = ClaimStatus.PROCESSING.value
        claim.processing_error = None
        db.commit()

        try:
            storage = storage or _default_storage()
            llm = llm or get_llm_client()
            ocr = ocr or get_ocr_engine()
            documents = list(claim.documents)
            if not documents:
                raise ValueError("Klaim belum punya dokumen")
            inputs = [InputDocument(d.id, d.filename, d.content_type, storage.get(d.storage_key), d.doc_type) for d in documents]
            result = read_claim(inputs, llm, ocr, claim.claim_number, _required_docs())

            by_id = {d.id: d for d in documents}
            for loaded in result.documents:
                row = by_id[loaded.document_id]
                row.doc_type = loaded.doc_type
                row.page_count = len(loaded.pages)
                storage.put(f"{row.storage_key}.pages.json", json.dumps(loaded.to_json(), ensure_ascii=False).encode(), "application/json")

            lines = result.line_index()
            db.execute(delete(ExtractedField).where(ExtractedField.claim_id == claim.id))
            for path, dv in result.derived.items():
                evidence, confidence = _evidence(dv.line_ids, lines)
                db.add(ExtractedField(claim_id=claim.id, field_path=path, value=dv.value, source=dv.source,
                                      confidence=confidence, evidence=evidence))
            others = _overlapping_claims(db, claim)
            db.add(ExtractedField(
                claim_id=claim.id, field_path="history.overlapping_claims", value=len(others), source="hitung", confidence=None,
                evidence=[{"claim_id": o.id, "quote": f"Klaim {o.claim_number}: {o.admission_date} s.d. {o.discharge_date}"} for o in others],
            ))

            primary = result.derived.get("dx.primary")
            if primary and primary.value:
                claim.primary_icd10 = str(primary.value)
            claim.status = ClaimStatus.EXTRACTED.value
            record(db, "PIPELINE_EXTRACTED", claim_id=claim.id, detail={
                "model_version": result.model_version,
                "prompt_version": result.prompt_version,
                "ocr_engine": result.ocr_engine,
                "documents": {
                    d.document_id: {"doc_type": d.doc_type, "method": result.classification.get(d.document_id),
                                    "pages": [p.mode for p in d.pages]}
                    for d in result.documents
                },
                "extraction": {o.document_id: o.status for o in result.outcomes},
                "warnings": result.warnings[:50],
            })
            db.commit()
            log.info("Klaim %s: %s field terisi", claim.claim_number, len(result.derived) + 1)
            return claim.status
        except Exception as exc:
            log.exception("Pipeline gagal untuk klaim %s", claim_id)
            db.rollback()
            claim = db.get(Claim, claim_id)
            claim.status = ClaimStatus.FAILED.value
            claim.processing_error = f"{type(exc).__name__}: {exc}"[:1000]
            record(db, "PIPELINE_FAILED", claim_id=claim.id, detail={"error": claim.processing_error})
            db.commit()
            return claim.status
