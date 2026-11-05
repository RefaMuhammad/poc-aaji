"""Job RQ: proses satu klaim dari dokumen sampai draf rekomendasi.

M4: baca dokumen (ingest, OCR, klasifikasi, ekstraksi LLM, field turunan).
M5: penalaran klinis + cek bukti, aturan klinis, draf rekomendasi.
Hasil akhir: status AWAITING_DECISION (bayar penuh, langsung ke asuransi) atau
AWAITING_DOCTOR (selain bayar penuh wajib ditelaah dan ditandatangani dokter).
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


def ping() -> str:
    """Job uji untuk memastikan worker menerima antrean."""
    return "pong"


def _default_storage():
    from mab_api.config import get_settings
    from mab_api.storage import S3Storage

    s = get_settings()
    return S3Storage(s.s3_endpoint_url, s.s3_bucket, s.minio_root_user, s.minio_root_password)


def _default_ruleset():
    from mab_api.config import get_settings
    from mab_pipeline.rules import load_rules

    return load_rules(get_settings().rules_path)


def _default_job_queue():
    from mab_api.config import get_settings
    from mab_api.job_queue import RQJobQueue

    s = get_settings()
    return RQJobQueue(s.redis_url, s.rq_queue)


def deliver_webhook(delivery_id: str, session_factory=None, post=None) -> str:
    """Job RQ: kirim satu webhook. Gagal -> exception supaya RQ mencoba lagi (lihat job_queue.py)."""
    from mab_api.config import get_settings
    from mab_api.db import make_session_factory
    from mab_api.models import WebhookDelivery
    from mab_api.webhooks import deliver

    s = get_settings()
    with (session_factory or make_session_factory())() as db:
        delivery = db.get(WebhookDelivery, delivery_id)
        if delivery is None:
            return "missing"
        deliver(db, delivery, post, timeout=s.webhook_timeout_seconds, max_attempts=s.webhook_max_attempts)
        return delivery.status


def _send_webhooks(job_queue, deliveries) -> None:
    from mab_api.webhooks import dispatch

    deliveries = [d for d in deliveries if d is not None]
    if deliveries:
        dispatch(job_queue or _default_job_queue(), deliveries)


def _default_benefit_ruleset():
    from mab_api.ruleset import active_benefit_ruleset

    return active_benefit_ruleset()


def _overlapping_claims(db, claim) -> list[dict]:
    from sqlalchemy import select

    from mab_api.models import Claim

    others = db.scalars(
        select(Claim).where(
            Claim.insurer_id == claim.insurer_id,
            Claim.member_id == claim.member_id,
            Claim.id != claim.id,
            Claim.admission_date <= claim.discharge_date,
            Claim.discharge_date >= claim.admission_date,
        )
    )
    return [{"claim_id": o.id, "quote": f"Klaim {o.claim_number}: {o.admission_date} s.d. {o.discharge_date}"} for o in others]


def process_claim(claim_id: str, session_factory=None, storage=None, llm=None, ocr=None, ruleset=None,
                  benefit_ruleset=None, job_queue=None) -> str:
    from sqlalchemy import delete, select

    from mab_api.assignment import auto_assign, close_active
    from mab_api.audit import record
    from mab_api.db import make_session_factory
    from mab_api.models import (AssignmentStatus, Claim, ClaimStatus, ExtractedField, Finding, Recommendation,
                                RecommendationCode)
    from mab_pipeline.extraction.derived_fields import DEFAULT_REQUIRED_DOCS
    from mab_pipeline.llm.client import get_llm_client
    from mab_pipeline.ocr.engine import get_ocr_engine
    from mab_pipeline.pipeline import InputDocument, assess_claim, read_claim

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
            from mab_api.tenancy import tenant_ruleset

            # aturan dasar + penyesuaian tenant (ambang triase, aturan yang dimatikan)
            ruleset, tenant_cfg = tenant_ruleset(db, ruleset or _default_ruleset(), claim.insurer_id)
            documents = list(claim.documents)
            if not documents:
                raise ValueError("Klaim belum punya dokumen")

            # --- M4: baca dokumen ---------------------------------------------------------
            inputs = [InputDocument(d.id, d.filename, d.content_type, storage.get(d.storage_key), d.doc_type) for d in documents]
            required = ruleset.triage.required_inpatient_docs or DEFAULT_REQUIRED_DOCS
            read = read_claim(inputs, llm, ocr, claim.claim_number, tuple(required))
            by_id = {d.id: d for d in documents}
            for loaded in read.documents:
                row = by_id[loaded.document_id]
                row.doc_type = loaded.doc_type
                row.page_count = len(loaded.pages)
                storage.put(f"{row.storage_key}.pages.json", json.dumps(loaded.to_json(), ensure_ascii=False).encode(), "application/json")

            # --- U2: polis peserta untuk aturan benefit (hanya bila tenant punya data polis) ---
            from mab_api.policies import find_policy, policy_info, tenant_has_policies
            from mab_api.tenancy import apply_tenant_benefit

            benefit_rs, policy = None, None
            claim.policy_id = None
            if tenant_has_policies(db, claim.insurer_id):
                benefit_rs = apply_tenant_benefit(benefit_ruleset or _default_benefit_ruleset(), tenant_cfg)
                found = find_policy(db, claim)
                if found is not None:
                    claim.policy_id = found.id
                    policy = policy_info(found)

            # --- M5: penalaran klinis, aturan, rekomendasi -------------------------------
            assessment = assess_claim(read, ruleset, llm, claim.billed_amount, claim.claim_number, _overlapping_claims(db, claim),
                                      benefit_ruleset=benefit_rs, policy=policy, admission_date=claim.admission_date)
            draft = assessment.recommendation

            db.execute(delete(ExtractedField).where(ExtractedField.claim_id == claim.id))
            for fv in assessment.fields.values():
                db.add(ExtractedField(claim_id=claim.id, field_path=fv.path, value=fv.value, source=fv.source,
                                      confidence=fv.confidence, evidence=fv.evidence, status=fv.status))
            primary = assessment.fields["dx.primary"].value
            if primary:
                claim.primary_icd10 = str(primary)

            previous = db.scalars(select(Recommendation).where(Recommendation.claim_id == claim.id)).all()
            for old in previous:
                old.is_current = False
            rec = Recommendation(
                claim_id=claim.id,
                version=max((r.version for r in previous), default=0) + 1,
                is_current=True,
                triage_status=draft.triage_status,
                risk_score=draft.risk_score,
                recommendation=draft.recommendation,
                billed_amount=draft.billed_amount,
                recommended_amount=draft.recommended_amount,
                line_adjustments=draft.line_adjustments,
                guideline_refs=draft.guideline_refs,
                next_action=draft.next_action,
                explanation_text=draft.explanation_text,
                quality_flags=draft.quality_flags,
                model_version=assessment.model_version,
                prompt_version=assessment.prompt_version,
                ruleset_version=assessment.ruleset_version,
                benefit_ruleset_version=assessment.benefit_ruleset_version,
            )
            db.add(rec)
            db.flush()
            for f in draft.findings:
                db.add(Finding(claim_id=claim.id, recommendation_id=rec.id, rule_id=f.rule_id, reason_code=f.reason_code,
                               severity=f.severity, source=f.source, text=f.text, evidence=f.evidence,
                               guideline_refs=f.guideline_refs))

            claim.status = (ClaimStatus.AWAITING_DECISION if draft.recommendation == RecommendationCode.PAY_FULL.value
                            else ClaimStatus.AWAITING_DOCTOR).value
            # proses ulang: penugasan lama tidak berlaku lagi
            close_active(db, claim, AssignmentStatus.CANCELLED)
            claim.assigned_doctor_id = None
            record(db, "PIPELINE_COMPLETED", claim_id=claim.id, detail={
                "recommendation_id": rec.id,
                "triage_status": draft.triage_status,
                "recommendation": draft.recommendation,
                "model_version": assessment.model_version,
                "prompt_version": assessment.prompt_version,
                "ruleset_version": assessment.ruleset_version,
                "benefit": {
                    "ruleset_version": assessment.benefit_ruleset_version,
                    "policy_number": policy.policy_number if policy else None,
                    "findings": [f.rule_id for f in assessment.benefit.findings],
                    "skipped_rules": assessment.benefit.skipped,
                } if assessment.benefit else None,
                "tenant_overrides": {
                    "settings_version": tenant_cfg.version,
                    "triage_red_min_score": tenant_cfg.triage_red_min_score,
                    "triage_yellow_min_score": tenant_cfg.triage_yellow_min_score,
                    "disabled_rules": list(tenant_cfg.disabled_rules),
                } if tenant_cfg.has_rule_overrides else None,
                "ocr_engine": read.ocr_engine,
                "documents": {
                    d.document_id: {"doc_type": d.doc_type, "method": read.classification.get(d.document_id),
                                    "pages": [p.mode for p in d.pages]}
                    for d in read.documents
                },
                "extraction": {o.document_id: o.status for o in read.outcomes},
                "reasoning": assessment.reasoning.status,
                "findings": [f.rule_id for f in draft.findings],
                "dropped_findings": draft.dropped_findings,
                "skipped_rules": draft.skipped_rules,
                "quality_flags": [q["code"] for q in draft.quality_flags],
                "warnings": (read.warnings + assessment.reasoning.warnings)[:50],
            })
            db.flush()
            db.refresh(claim)
            auto_assign(db, claim)
            from mab_api.webhooks import queue_event

            # bayar penuh langsung dirilis ke asuransi; selain itu webhook menunggu tanda tangan dokter
            hook = queue_event(db, claim, "claim.recommendation_released") \
                if claim.status == ClaimStatus.AWAITING_DECISION.value else None
            db.commit()
            _send_webhooks(job_queue, [hook])
            log.info("Klaim %s: %s / %s", claim.claim_number, draft.triage_status, draft.recommendation)
            return claim.status
        except Exception as exc:
            log.exception("Pipeline gagal untuk klaim %s", claim_id)
            db.rollback()
            claim = db.get(Claim, claim_id)
            claim.status = ClaimStatus.FAILED.value
            claim.processing_error = f"{type(exc).__name__}: {exc}"[:1000]
            record(db, "PIPELINE_FAILED", claim_id=claim.id, detail={"error": claim.processing_error})
            from mab_api.webhooks import queue_event

            hook = queue_event(db, claim, "claim.processing_failed")
            db.commit()
            _send_webhooks(job_queue, [hook])
            return claim.status
