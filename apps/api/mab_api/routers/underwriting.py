"""U7: underwriting medis. Antrean, pengajuan, ruang kerja, tanda tangan dokter, keputusan underwriter, PDF."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from mab_api import audit
from mab_api.access import resolve_target_tenant
from mab_api.config import get_settings
from mab_api.db import get_db
from mab_api.deps import get_queue, get_storage, require_perm
from mab_api.documents import InvalidFile, validate_file
from mab_api.models import UwApplication, UwDecision, UwReview, UwStatus, User
from mab_api.rbac import Perm, has_perm
from mab_api.security import verify_secret
from mab_api.underwriting import (LABEL, NON_STANDARD, current_review, current_terms, final_premium,
                                  get_visible_application, latest_assessment, next_application_number,
                                  recommendation_pdf, store_uw_document, uw_ruleset, visible_applications_query)
from mab_pipeline.underwriting.constants import (LAB_TESTS, QUESTIONS, RECOMMENDATION_LABELS, RECOMMENDATIONS,
                                                 UW_DOC_LABELS)

router = APIRouter(prefix="/underwriting", tags=["underwriting (U7)"])
can_view = require_perm(Perm.UW_VIEW)
can_submit = require_perm(Perm.UW_SUBMIT)
can_decide = require_perm(Perm.UW_DECIDE)
can_sign = require_perm(Perm.UW_SIGN)

Recommendation = Literal["ACCEPT_STANDARD", "ACCEPT_CONDITIONAL", "POSTPONE", "DECLINE"]


def _summary(app: UwApplication) -> dict:
    a, rev = latest_assessment(app), current_review(app)
    terms = current_terms(app)
    d = app.decisions[-1] if app.decisions else None
    return {
        "id": app.id, "application_number": app.application_number, "status": app.status,
        "insurer_id": app.insurer_id, "insurer_name": app.insurer.name, "spaj_number": app.spaj_number,
        "applicant_name": app.applicant_name, "applicant_sex": app.applicant_sex,
        "applicant_birth_date": app.applicant_birth_date, "product_name": app.product_name,
        "sum_assured": app.sum_assured, "base_premium": app.base_premium, "created_at": app.created_at,
        "updated_at": app.updated_at, "documents": len(app.documents), "processing_error": app.processing_error,
        "recommendation": terms["recommendation"], "risk_class": terms["risk_class"],
        "loading_pct": terms["loading_pct"], "terms_source": terms["source"],
        "needs_doctor": a.needs_doctor if a else None, "signed_by": rev.doctor.full_name if rev else None,
        "decision": d.decision if d else None, "findings": len(a.findings) if a else 0,
    }


def _labels() -> dict:
    rs = uw_ruleset()
    classes = [{"code": c.code, "name": c.name, "max_debit": c.max_debit} for c in rs.classes]
    classes += [{"code": "POSTPONE", "name": rs.class_name("POSTPONE")}, {"code": "DECLINE", "name": rs.class_name("DECLINE")}]
    return {"recommendations": RECOMMENDATION_LABELS, "doc_types": UW_DOC_LABELS, "classes": classes,
            "fields": {k: v.get("ket") for k, v in rs.dictionary.items()},
            "questions": {f"history.{n}" if n != "smoker" else "applicant.smoker": t for _, n, t in QUESTIONS},
            "lab_tests": {f"lab.{c}": label for c, label, _, _ in LAB_TESTS}}


@router.get("/applications")
def list_applications(status_: str | None = Query(None, alias="status"), q: str | None = None,
                      db: Session = Depends(get_db), user: User = Depends(can_view)) -> dict:
    base = visible_applications_query(user)
    counts: dict[str, int] = {}
    apps = list(db.scalars(base.order_by(UwApplication.created_at.desc())))
    for a in apps:
        counts[a.status] = counts.get(a.status, 0) + 1
    if status_:
        apps = [a for a in apps if a.status in status_.split(",")]
    if q:
        needle = q.lower()
        apps = [a for a in apps if needle in " ".join(filter(None, [a.application_number, a.spaj_number,
                                                                    a.applicant_name])).lower()]
    return {"items": [_summary(a) for a in apps], "counts": counts, "label": LABEL,
            "can_submit": has_perm(user.role, Perm.UW_SUBMIT), "can_sign": has_perm(user.role, Perm.UW_SIGN),
            "can_decide": has_perm(user.role, Perm.UW_DECIDE), "rules_version": uw_ruleset().version,
            "labels": _labels()}


@router.post("/applications", status_code=status.HTTP_201_CREATED)
def submit_application(request: Request, files: list[UploadFile] = File(...), insurer_id: str | None = Form(None),
                       db: Session = Depends(get_db), user: User = Depends(can_submit), storage=Depends(get_storage),
                       queue=Depends(get_queue)) -> dict:
    """Ajukan calon peserta: unggah SPAJ, kuesioner kesehatan, hasil MCU, lab, dan surat dokter (PDF/JPG/PNG)."""
    target = resolve_target_tenant(db, user, insurer_id)
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    try:
        valid = [validate_file(f.filename or "dokumen", f.file.read(max_bytes + 1)) for f in files]
    except InvalidFile as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    app = UwApplication(application_number=next_application_number(db), insurer_id=target, submitted_by_id=user.id,
                        status=UwStatus.QUEUED.value)
    db.add(app)
    db.flush()
    for f in valid:
        store_uw_document(db, storage, app, user, f)
    audit.record(db, "UW_SUBMITTED", user_id=user.id, user_role=user.role, request=request,
                 detail={"application_id": app.id, "application_number": app.application_number, "documents": len(valid)})
    db.commit()
    job_id = queue.enqueue_process_underwriting(app.id)
    db.refresh(app)
    return _summary(app) | {"job_id": job_id}


@router.get("/applications/{application_id}")
def get_application(application_id: str, db: Session = Depends(get_db), user: User = Depends(can_view)) -> dict:
    app = get_visible_application(db, user, application_id)
    a, rev = latest_assessment(app), current_review(app)
    terms = current_terms(app)
    can_sign = has_perm(user.role, Perm.UW_SIGN) and app.status == UwStatus.AWAITING_DOCTOR.value
    can_decide = has_perm(user.role, Perm.UW_DECIDE) and app.status == UwStatus.AWAITING_UNDERWRITER.value
    # Keputusan yang boleh dipilih underwriter: rekomendasi bertanda tangan dokter, atau terima standar.
    allowed = []
    if can_decide:
        allowed = ["ACCEPT_STANDARD"] + ([terms["recommendation"]] if terms["recommendation"] in NON_STANDARD and rev else [])
    return {
        **_summary(app), "label": LABEL, "labels": _labels(),
        "documents_list": [{"id": d.id, "filename": d.filename, "doc_type": d.doc_type, "content_type": d.content_type,
                            "page_count": d.page_count, "sha256": d.sha256, "created_at": d.created_at}
                           for d in app.documents],
        "assessment": None if a is None else {
            "id": a.id, "version": a.version, "fields": a.fields, "profile": a.profile, "findings": a.findings,
            "skipped": a.skipped, "evidence": a.evidence, "missing_docs": a.missing_docs, "missing_fields": a.missing_fields,
            "debit_total": a.debit_total, "risk_class": a.risk_class, "loading_pct": a.loading_pct,
            "exclusions": a.exclusions, "recommendation": a.recommendation, "needs_doctor": a.needs_doctor,
            "doctor_reasons": a.doctor_reasons, "rules_version": a.rules_version, "model_version": a.model_version,
            "prompt_version": a.prompt_version, "ocr_engine": a.ocr_engine, "warnings": a.warnings,
            "created_at": a.created_at},
        "review": None if rev is None else {
            "id": rev.id, "doctor": rev.doctor.full_name, "action": rev.action, "recommendation": rev.recommendation,
            "risk_class": rev.risk_class, "loading_pct": rev.loading_pct, "exclusions": rev.exclusions,
            "notes": rev.notes, "signed_at": rev.signed_at},
        "decision_detail": None if not app.decisions else {
            "decision": app.decisions[-1].decision, "risk_class": app.decisions[-1].risk_class,
            "loading_pct": app.decisions[-1].loading_pct, "exclusions": app.decisions[-1].exclusions,
            "final_premium": app.decisions[-1].final_premium, "notes": app.decisions[-1].notes,
            "decided_by": app.decisions[-1].decided_by.full_name, "decided_at": app.decisions[-1].decided_at},
        "terms": terms,
        "premium_preview": final_premium(app, terms["recommendation"] or "", terms["loading_pct"]),
        "can_sign": can_sign, "can_decide": can_decide, "allowed_decisions": allowed,
    }


@router.get("/applications/{application_id}/documents/{document_id}")
def get_document_file(application_id: str, document_id: str, request: Request, db: Session = Depends(get_db),
                      user: User = Depends(can_view), storage=Depends(get_storage)) -> Response:
    app = get_visible_application(db, user, application_id)
    doc = next((d for d in app.documents if d.id == document_id), None)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dokumen tidak ditemukan")
    audit.record(db, "UW_DOCUMENT_VIEWED", user_id=user.id, user_role=user.role, request=request,
                 detail={"application_id": app.id, "document_id": doc.id, "filename": doc.filename})
    db.commit()
    return Response(storage.get(doc.storage_key), media_type=doc.content_type,
                    headers={"Content-Disposition": f'inline; filename="{doc.filename}"'})


class SignIn(BaseModel):
    action: Literal["AGREE", "MODIFY"]
    recommendation: Recommendation | None = None
    risk_class: str | None = None
    loading_pct: int | None = Field(default=None, ge=0, le=300)
    exclusions: list[str] | None = None
    notes: str | None = Field(default=None, max_length=4000)
    pin: str


@router.post("/applications/{application_id}/sign")
def sign(application_id: str, body: SignIn, request: Request, db: Session = Depends(get_db),
         user: User = Depends(can_sign)) -> dict:
    """Dokter menelaah draf sistem lalu menandatangani rekomendasi (setujui atau ubah), dengan PIN."""
    app = get_visible_application(db, user, application_id)
    a = latest_assessment(app)
    if app.status != UwStatus.AWAITING_DOCTOR.value or a is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Pengajuan ini tidak sedang menunggu telaah dokter")
    if not user.pin_hash:
        raise HTTPException(status.HTTP_409_CONFLICT, "PIN tanda tangan Anda belum diatur. Hubungi admin.")
    if not verify_secret(body.pin, user.pin_hash):
        audit.record(db, "UW_SIGN_PIN_FAILED", user_id=user.id, user_role=user.role, request=request,
                     detail={"application_id": app.id})
        db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "PIN salah")
    notes = (body.notes or "").strip() or None
    if body.action == "AGREE":
        rec, cls, loading = a.recommendation, a.risk_class, a.loading_pct
        exclusions = [e["text"] for e in a.exclusions or []]
        if a.missing_docs or a.missing_fields:
            if not notes:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    "Data wajib belum lengkap. Tuliskan pertimbangan Anda di catatan.")
    else:
        if not notes:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tuliskan alasan perubahan di catatan")
        if body.recommendation is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pilih rekomendasi")
        rec = body.recommendation
        exclusions = [e.strip() for e in body.exclusions or [] if e.strip()]
        loading = body.loading_pct or 0
        class_codes = {c.code for c in uw_ruleset().classes}
        if rec in ("POSTPONE", "DECLINE"):
            cls, loading, exclusions = rec, 0, []
        elif rec == "ACCEPT_STANDARD":
            cls, loading, exclusions = "STANDARD", 0, []
        else:
            cls = body.risk_class or ""
            if cls not in class_codes:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kelas risiko tidak dikenal")
            if not loading and not exclusions:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                    "Terima dengan syarat butuh loading premi atau pengecualian")
    rev = UwReview(application_id=app.id, assessment_id=a.id, doctor_id=user.id, action=body.action,
                   recommendation=rec, risk_class=cls, loading_pct=loading, exclusions=exclusions, notes=notes)
    db.add(rev)
    app.reviews.append(rev)
    app.status = UwStatus.AWAITING_UNDERWRITER.value
    db.flush()
    audit.record(db, "UW_SIGNED", user_id=user.id, user_role=user.role, request=request, detail={
        "application_id": app.id, "application_number": app.application_number, "assessment_id": a.id,
        "action": body.action, "draft": a.recommendation, "recommendation": rec, "risk_class": cls,
        "loading_pct": loading, "exclusions": exclusions})
    db.commit()
    return get_application(app.id, db, user)


class DecideIn(BaseModel):
    decision: Recommendation
    notes: str | None = Field(default=None, max_length=4000)


@router.post("/applications/{application_id}/decision")
def decide(application_id: str, body: DecideIn, request: Request, db: Session = Depends(get_db),
           user: User = Depends(can_decide)) -> dict:
    """Keputusan underwriter. Selain terima standar wajib sama dengan rekomendasi yang ditandatangani dokter."""
    app = get_visible_application(db, user, application_id)
    if app.status != UwStatus.AWAITING_UNDERWRITER.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Pengajuan ini belum siap diputuskan atau sudah diputuskan")
    rev, terms = current_review(app), current_terms(app)
    notes = (body.notes or "").strip() or None
    if body.decision in NON_STANDARD:
        if rev is None or rev.recommendation != body.decision:
            raise HTTPException(status.HTTP_409_CONFLICT, "Keputusan selain terima standar wajib sama dengan rekomendasi "
                                                          "yang ditandatangani dokter")
        cls, loading, exclusions = rev.risk_class, rev.loading_pct, list(rev.exclusions or [])
    else:
        if terms["recommendation"] != "ACCEPT_STANDARD" and not notes:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Rekomendasi dokter bukan terima standar. Tuliskan alasan menerima standar di catatan.")
        cls, loading, exclusions = "STANDARD", 0, []
    d = UwDecision(application_id=app.id, review_id=rev.id if rev else None, decision=body.decision, risk_class=cls,
                   loading_pct=loading, exclusions=exclusions, final_premium=final_premium(app, body.decision, loading),
                   notes=notes, decided_by_id=user.id)
    db.add(d)
    app.decisions.append(d)
    app.status = UwStatus.DECIDED.value
    db.flush()
    audit.record(db, "UW_DECIDED", user_id=user.id, user_role=user.role, request=request, detail={
        "application_id": app.id, "application_number": app.application_number, "decision": body.decision,
        "risk_class": cls, "loading_pct": loading, "final_premium": d.final_premium,
        "review_id": rev.id if rev else None, "follows": terms["source"]})
    db.commit()
    return get_application(app.id, db, user)


@router.get("/applications/{application_id}/pdf")
def get_pdf(application_id: str, request: Request, db: Session = Depends(get_db), user: User = Depends(can_view)) -> Response:
    app = get_visible_application(db, user, application_id)
    if latest_assessment(app) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Pengajuan belum diproses")
    pdf = recommendation_pdf(app, uw_ruleset().class_name)
    audit.record(db, "UW_PDF_DOWNLOADED", user_id=user.id, user_role=user.role, request=request,
                 detail={"application_id": app.id, "application_number": app.application_number})
    db.commit()
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="underwriting_{app.application_number}.pdf"'})


@router.get("/rules")
def get_rules(user: User = Depends(can_view)) -> dict:
    """Aturan underwriting yang berlaku (versi, kelas risiko, aturan)."""
    rs = uw_ruleset()
    return {"version": rs.version, "status": rs.status, "decline_debit": rs.decline_debit,
            "loading_per_debit": rs.loading_per_debit, "required_docs": list(rs.required_docs),
            "required_fields": list(rs.required_fields),
            "classes": [{"code": c.code, "name": c.name, "max_debit": c.max_debit} for c in rs.classes],
            "rules": [{"id": r.id, "name": r.name, "condition": r.condition.source, "kind": r.kind, "debit": r.debit,
                       "exclusion": r.exclusion, "decision": r.decision, "reason_code": r.reason_code,
                       "reference": r.reference} for r in rs.rules], "recommendations": list(RECOMMENDATIONS)}
