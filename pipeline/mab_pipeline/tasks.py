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
    return S3Storage.from_settings(s)


def _default_ruleset():
    from mab_api.config import get_settings
    from mab_pipeline.rules import load_rules

    return load_rules(get_settings().rules_path)


def _default_job_queue():
    from mab_api.config import get_settings
    from mab_api.job_queue import RQJobQueue

    s = get_settings()
    return RQJobQueue.from_settings(s)


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


def _record_for_fraud(db, claim, facts) -> None:
    """U3: klaim yang sudah dibaca masuk data analitik fraud (DPJP, jumlah pemeriksaan lab).
    Hanya mengisi data analitik; analisis fraud dijalankan terpisah dan tidak mengubah klaim."""
    from mab_api.fraud import upsert_platform_record

    doctor = facts.resume.attending_doctor.value if facts.resume is not None else None
    panels = None
    if facts.labs is not None:
        panels = len({(r.date, r.time) for r in facts.labs.results}) or None
    upsert_platform_record(db, claim, doctor=doctor, lab_panels=panels, icd10=claim.primary_icd10)


def _assign_preferred(db, claim, doctor_id) -> bool:
    """U4: tugaskan ke dokter yang menandatangani rekomendasi sebelum dokumen diminta, bila masih berhak."""
    from mab_api.assignment import assign, claim_reviews, current_recommendation, eligible_doctors, routing, sla_due
    from mab_api.tenancy import tenant_config

    rec = current_recommendation(claim)
    if not doctor_id or rec is None or claim.assigned_doctor_id:
        return False
    reviews = claim_reviews(db, claim)
    level, specialty, _, _ = routing(claim, rec, reviews)
    doctor = next((d for d in eligible_doctors(db, level, specialty) if d.id == doctor_id), None)
    if doctor is None:
        return False
    assign(db, claim, rec, doctor, level=level, specialty=specialty,
           due=sla_due(rec, reviews, level, tenant_config(db, claim.insurer_id)), method="AUTO")
    return True


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
            _record_for_fraud(db, claim, read.facts)

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

            # U4: klaim yang dokumen susulannya baru dilengkapi selalu kembali ke dokter
            from mab_api.doc_requests import requires_doctor_after_documents

            after_docs, preferred_doctor = requires_doctor_after_documents(db, claim)
            claim.status = (ClaimStatus.AWAITING_DECISION
                            if draft.recommendation == RecommendationCode.PAY_FULL.value and not after_docs
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
                "after_late_documents": after_docs,
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
            if not (after_docs and _assign_preferred(db, claim, preferred_doctor)):
                auto_assign(db, claim)
            from mab_api.webhooks import queue_event

            # bayar penuh langsung dirilis ke asuransi; selain itu webhook menunggu tanda tangan dokter
            hook = None
            if claim.status == ClaimStatus.AWAITING_DECISION.value:
                from mab_api.notify import recommendation_released

                hook = queue_event(db, claim, "claim.recommendation_released")
                recommendation_released(db, claim)
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


def process_underwriting(application_id: str, session_factory=None, storage=None, llm=None, ocr=None,
                         ruleset=None) -> str:
    """U7: baca dokumen pengajuan, terapkan aturan underwriting, simpan draf rekomendasi.

    Hasil: AWAITING_UNDERWRITER (terima standar dengan data lengkap) atau AWAITING_DOCTOR
    (bersyarat, tunda, usul tolak, atau data kurang: wajib ditelaah dan ditandatangani dokter).
    """
    from mab_api.audit import record
    from mab_api.db import make_session_factory
    from mab_api.models import UwApplication, UwStatus
    from mab_api.underwriting import apply_result, uw_ruleset
    from mab_pipeline.llm.client import get_llm_client
    from mab_pipeline.ocr.engine import get_ocr_engine
    from mab_pipeline.underwriting.pipeline import InputDocument, assess_application

    session_factory = session_factory or make_session_factory()
    with session_factory() as db:
        app = db.get(UwApplication, application_id)
        if app is None:
            log.warning("Pengajuan underwriting %s tidak ditemukan", application_id)
            return "missing"
        app.status = UwStatus.PROCESSING.value
        app.processing_error = None
        db.commit()
        try:
            storage = storage or _default_storage()
            llm = llm or get_llm_client()
            ocr = ocr or get_ocr_engine()
            ruleset = ruleset or uw_ruleset()
            if not app.documents:
                raise ValueError("Pengajuan belum punya dokumen")
            inputs = [InputDocument(d.id, d.filename, d.content_type, storage.get(d.storage_key), d.doc_type)
                      for d in app.documents]
            result = assess_application(inputs, llm, ocr, ruleset)
            a = apply_result(db, app, result, getattr(ocr, "name", type(ocr).__name__))
            db.flush()
            record(db, "UW_PROCESSED", detail={
                "application_id": app.id, "application_number": app.application_number, "assessment_id": a.id,
                "recommendation": a.recommendation, "risk_class": a.risk_class, "loading_pct": a.loading_pct,
                "needs_doctor": a.needs_doctor, "rules_version": a.rules_version, "model_version": a.model_version,
                "prompt_version": a.prompt_version, "ocr_engine": a.ocr_engine})
            db.commit()
            log.info("Underwriting %s: %s / %s", app.application_number, a.risk_class, a.recommendation)
            return app.status
        except Exception as exc:
            log.exception("Pipeline underwriting gagal untuk %s", application_id)
            db.rollback()
            app = db.get(UwApplication, application_id)
            app.status = UwStatus.FAILED.value
            app.processing_error = f"{type(exc).__name__}: {exc}"[:1000]
            record(db, "UW_FAILED", detail={"application_id": app.id, "error": app.processing_error})
            db.commit()
            return app.status
