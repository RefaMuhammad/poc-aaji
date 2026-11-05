"""Endpoint klaim: buat, unggah dokumen (satuan & ZIP), status, rekomendasi, keputusan, ekspor."""
from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mab_api.access import get_visible_claim, resolve_target_tenant, visible_claims_query
from mab_api.api_schemas import (
    BatchResult,
    BulkAgreeRequest,
    BulkAgreeResult,
    ClaimCreate,
    ClaimDetail,
    ClaimListItem,
    ClaimOut,
    ClaimStatusOut,
    DecisionCreate,
    DocumentRequestCreate,
    DocumentRequestOut,
    DocumentOut,
    EvidenceOut,
    ExtractedFieldOut,
    FindingOut,
    InsurerDecisionOut,
    RecommendationOut,
    ReviewerOut,
    UploadResult,
)
from mab_api.config import get_settings
from mab_api.db import get_db
from mab_api.deps import get_queue, get_storage, require_perm
from mab_api.rendering import recommendation_pdf
from mab_api.documents import InvalidFile, missing_documents, store_document, validate_file
from mab_api.models import (
    Claim,
    ClaimSource,
    ClaimStatus,
    DecisionCode,
    ExtractedField,
    Insurer,
    InsurerDecision,
    Recommendation,
    RecommendationCode,
    RecommendationState,
    TenantSettings,
    User,
)
from mab_api.rbac import Perm, can_see_draft, has_perm
from mab_api.webhooks import current_decision, dispatch, queue_event
from mab_api.batch import BatchError, import_zip, queue_claim
from mab_api.routers.policies import policy_out
from mab_api import doc_requests, notify

router = APIRouter(prefix="/claims", tags=["klaim"])

can_list = require_perm(Perm.CLAIM_LIST)
can_detail = require_perm(Perm.CLAIM_DETAIL)
can_submit = require_perm(Perm.CLAIM_SUBMIT)
can_decide = require_perm(Perm.CLAIM_DECIDE)
can_export = require_perm(Perm.CLAIM_EXPORT)


# ----------------------------------------------------------------------------- bantuan


def _current_recommendation(claim: Claim) -> Recommendation | None:
    return next((r for r in reversed(claim.recommendations) if r.is_current), None)


def _released_to_insurer(rec: Recommendation) -> bool:
    """Prinsip produk: selain bayar penuh, rekomendasi wajib ditandatangani dokter dulu."""
    return rec.recommendation == RecommendationCode.PAY_FULL.value or rec.state == RecommendationState.SIGNED.value


def _latest_decision(claim: Claim) -> InsurerDecision | None:
    """Keputusan atas rekomendasi yang berlaku (keputusan lama hilang saat klaim diproses ulang, U4)."""
    return current_decision(claim)


_queue_claim = queue_claim


def build_recommendation_view(claim: Claim, rec: Recommendation) -> RecommendationOut:
    decision = _latest_decision(claim)
    reviewer = None
    if rec.signed_by is not None and rec.signed_at is not None:
        reviewer = ReviewerOut(name=rec.signed_by.full_name, specialty=rec.signed_by.specialty, signed_at=rec.signed_at)
    return RecommendationOut(
        claim_id=claim.id,
        claim_number=claim.claim_number,
        triage_status=rec.triage_status,
        risk_score=rec.risk_score,
        recommendation=rec.recommendation,
        state=rec.state,
        billed_amount=rec.billed_amount,
        recommended_amount=rec.recommended_amount,
        line_adjustments=rec.line_adjustments or [],
        findings=[
            FindingOut(
                code=f.reason_code,
                severity=f.severity,
                source=f.source,
                text=f.text,
                rule_id=f.rule_id,
                evidence=[EvidenceOut(**e) for e in (f.evidence or [])],
                guideline_refs=f.guideline_refs or [],
            )
            for f in rec.findings
        ],
        guideline_refs=rec.guideline_refs or [],
        next_action=rec.next_action,
        reviewer=reviewer,
        explanation_text=rec.explanation_text,
        quality_flags=rec.quality_flags or [],
        model_version=rec.model_version,
        prompt_version=rec.prompt_version,
        ruleset_version=rec.ruleset_version,
        benefit_ruleset_version=rec.benefit_ruleset_version,
        insurer_decision=InsurerDecisionOut(
            decision=decision.decision,
            reason=decision.reason,
            decided_by=decision.decided_by.full_name,
            decided_at=decision.decided_at,
        )
        if decision
        else None,
    )


OUTCOME_LABEL = {"PAY_FULL": "dibayar penuh", "PAY_PARTIAL": "dibayar sebagian", "PEND": "ditunda",
                 "NOT_COVERED": "tidak dijamin"}


def outcome_summary(rec: Recommendation, decision: str) -> str:
    """Ringkasan hasil untuk peserta dan faskes (keputusan asuransi atas rekomendasi)."""
    if decision == DecisionCode.DIFFER.value:
        return "asuransi memutuskan berbeda dari rekomendasi medis; lihat alasan di portal"
    text = OUTCOME_LABEL.get(rec.recommendation, rec.recommendation)
    if rec.recommendation == "PAY_PARTIAL" and rec.recommended_amount is not None:
        text += ", Rp" + f"{rec.recommended_amount:,}".replace(",", ".")
    return text


def _record_decision(db: Session, claim: Claim, rec: Recommendation, user: User, decision: str, reason: str | None) -> None:
    db.add(InsurerDecision(claim_id=claim.id, recommendation_id=rec.id, decision=decision, reason=reason, decided_by_id=user.id))
    claim.status = ClaimStatus.COMPLETED.value
    notify.decision_recorded(db, claim, outcome_summary(rec, decision))


# ----------------------------------------------------------------------------- buat & lihat


@router.post("", response_model=ClaimOut, status_code=status.HTTP_201_CREATED)
def create_claim(body: ClaimCreate, db: Session = Depends(get_db), user: User = Depends(can_submit)) -> Claim:
    """Staf asuransi membuat klaim untuk asuransinya; operator TPA memilih asuransi lewat `insurer_id`."""
    insurer_id = resolve_target_tenant(db, user, body.insurer_id)
    claim = Claim(insurer_id=insurer_id, created_by_id=user.id, source=ClaimSource.PORTAL.value,
                  **body.model_dump(exclude={"insurer_id"}))
    db.add(claim)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"Nomor klaim {body.claim_number} sudah ada")
    return claim


def _visible_rec(claim: Claim, user: User) -> Recommendation | None:
    """Rekomendasi yang boleh dilihat: draf hanya untuk dokter/admin; peran tanpa akses detail tidak melihatnya."""
    rec = _current_recommendation(claim)
    if rec is None or not has_perm(user.role, Perm.CLAIM_DETAIL):
        return None
    if not can_see_draft(user.role) and not _released_to_insurer(rec):
        return None
    return rec


@router.get("", response_model=list[ClaimListItem])
def list_claims(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    triage: str | None = Query(default=None, description="GREEN / YELLOW / RED"),
    insurer_id: str | None = Query(default=None, description="Operator TPA: saring per asuransi"),
    user: User = Depends(can_list),
) -> list[ClaimListItem]:
    q = visible_claims_query(user, db)
    if insurer_id:
        q = q.where(Claim.insurer_id == insurer_id)
    if status_filter:
        q = q.where(Claim.status == status_filter)
    out = []
    display = {t.insurer_id: t.display_name for t in db.scalars(select(TenantSettings)) if t.display_name}
    insurer_names = {i.id: display.get(i.id, i.name) for i in db.scalars(select(Insurer))}
    for c in db.scalars(q.order_by(Claim.created_at.desc()).limit(limit).offset(offset)):
        rec = _visible_rec(c, user)
        if triage and (rec is None or rec.triage_status != triage):
            continue
        dec = _latest_decision(c)
        out.append(ClaimListItem(
            **ClaimOut.model_validate(c).model_dump(),
            triage_status=rec.triage_status if rec else None,
            risk_score=rec.risk_score if rec else None,
            recommendation=rec.recommendation if rec else None,
            decision=dec.decision if dec else None,
            insurer_name=insurer_names.get(c.insurer_id),
        ))
    return out


# --- ekspor & keputusan massal didefinisikan sebelum /{claim_id} -------------------------------

EXPORT_COLUMNS = [
    "nomor_klaim", "nomor_polis", "id_peserta", "nama_rs", "tanggal_masuk", "tanggal_keluar",
    "nilai_tagihan", "status_klaim", "status_triase", "skor_risiko", "rekomendasi", "nilai_rekomendasi",
    "kode_alasan", "dokter_penelaah", "waktu_tanda_tangan", "versi_aturan", "versi_model",
    "keputusan_asuransi", "alasan_keputusan", "diputuskan_oleh", "waktu_keputusan",
]


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), user: User = Depends(can_export)) -> StreamingResponse:
    claims = list(db.scalars(visible_claims_query(user, db).order_by(Claim.created_at)))
    buf = io.StringIO()
    buf.write("﻿")  # BOM supaya Excel membaca UTF-8
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    for c in claims:
        rec = _current_recommendation(c)
        visible = rec is not None and _released_to_insurer(rec)
        dec = _latest_decision(c)
        writer.writerow(
            [
                c.claim_number, c.policy_number, c.member_id, c.hospital_name, c.admission_date.isoformat(),
                c.discharge_date.isoformat(), c.billed_amount, c.status,
                rec.triage_status if visible else "", rec.risk_score if visible else "",
                rec.recommendation if visible else "", (rec.recommended_amount if visible and rec.recommended_amount is not None else ""),
                ";".join(sorted({f.reason_code for f in rec.findings})) if visible else "",
                rec.signed_by.full_name if visible and rec.signed_by else "",
                rec.signed_at.isoformat() if visible and rec.signed_at else "",
                rec.ruleset_version if visible else "", rec.model_version if visible else "",
                dec.decision if dec else "", dec.reason or "" if dec else "",
                dec.decided_by.full_name if dec else "", dec.decided_at.isoformat() if dec else "",
            ]
        )
    filename = f"ekspor_klaim_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/decisions/bulk-agree", response_model=BulkAgreeResult)
def bulk_agree_green(body: BulkAgreeRequest, db: Session = Depends(get_db), user: User = Depends(can_decide),
                     queue=Depends(get_queue)) -> BulkAgreeResult:
    """Setujui massal klaim hijau (PAY_FULL) yang belum diputuskan."""
    agreed, skipped, hooks = [], [], []
    for claim_id in dict.fromkeys(body.claim_ids):
        claim = db.scalar(visible_claims_query(user, db).where(Claim.id == claim_id))
        rec = _current_recommendation(claim) if claim else None
        if claim is None:
            skipped.append({"claim_id": claim_id, "reason": "Klaim tidak ditemukan"})
        elif rec is None or rec.triage_status != "GREEN" or rec.recommendation != RecommendationCode.PAY_FULL.value:
            skipped.append({"claim_id": claim_id, "reason": "Hanya klaim hijau dengan rekomendasi bayar penuh"})
        elif _latest_decision(claim) is not None:
            skipped.append({"claim_id": claim_id, "reason": "Sudah ada keputusan"})
        else:
            _record_decision(db, claim, rec, user, DecisionCode.AGREE.value, None)
            agreed.append(claim_id)
            hooks.append(queue_event(db, claim, "claim.decision_recorded"))
    db.commit()
    dispatch(queue, hooks)
    return BulkAgreeResult(agreed=agreed, skipped=skipped)


# --- unggah massal ZIP --------------------------------------------------------------------


@router.post("/batch", response_model=BatchResult)
def upload_batch(
    file: UploadFile = File(..., description="ZIP berisi manifest.xlsx dan satu folder per klaim"),
    insurer_id: str | None = Query(default=None, description="Wajib untuk operator TPA: asuransi pemilik klaim"),
    db: Session = Depends(get_db),
    user: User = Depends(can_submit),
    storage=Depends(get_storage),
    queue=Depends(get_queue),
) -> BatchResult:
    settings = get_settings()
    target_insurer = resolve_target_tenant(db, user, insurer_id)
    raw = file.file.read(settings.max_zip_mb * 1024 * 1024 + 1)
    if len(raw) > settings.max_zip_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"ZIP melebihi {settings.max_zip_mb} MB")
    try:
        result = import_zip(db, storage, target_insurer, raw, source=ClaimSource.BATCH, user=user)
    except BatchError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    db.commit()
    for claim in result.claims:
        _queue_claim(claim, queue)
    db.commit()
    return BatchResult(created=result.created, failed=result.failed, rows=result.rows)


# --- per klaim -----------------------------------------------------------------------------


@router.get("/{claim_id}", response_model=ClaimDetail)
def get_claim(claim_id: str, db: Session = Depends(get_db), user: User = Depends(can_list)) -> ClaimDetail:
    claim = get_visible_claim(db, user, claim_id)
    current = _current_recommendation(claim)
    rec = _visible_rec(claim, user)
    dec = _latest_decision(claim)
    return ClaimDetail(
        **ClaimOut.model_validate(claim).model_dump(),
        documents=[DocumentOut.model_validate(d) for d in claim.documents],
        missing_documents=missing_documents(claim),
        triage_status=rec.triage_status if rec else None,
        recommendation_available=rec is not None,
        awaiting_doctor=current is not None and not _released_to_insurer(current),
        decision=dec.decision if dec else None,
        policy=policy_out(claim.policy) if claim.policy is not None and has_perm(user.role, Perm.CLAIM_DETAIL) else None,
        document_requests=[doc_requests.to_out(r, claim) for r in doc_requests.requests_for(db, claim)],
    )


@router.get("/{claim_id}/status", response_model=ClaimStatusOut)
def get_claim_status(claim_id: str, db: Session = Depends(get_db), user: User = Depends(can_list)) -> ClaimStatusOut:
    claim = get_visible_claim(db, user, claim_id)
    return ClaimStatusOut(id=claim.id, status=claim.status, processing_error=claim.processing_error, updated_at=claim.updated_at)


@router.get("/{claim_id}/fields", response_model=list[ExtractedFieldOut])
def get_extracted_fields(claim_id: str, db: Session = Depends(get_db), user: User = Depends(can_detail)) -> list[ExtractedFieldOut]:
    """Field hasil baca dokumen beserta bukti (dokumen, halaman, bbox, kutipan)."""
    claim = get_visible_claim(db, user, claim_id)
    rows = db.scalars(select(ExtractedField).where(ExtractedField.claim_id == claim.id).order_by(ExtractedField.field_path))
    return [ExtractedFieldOut.model_validate(r) for r in rows]


@router.post("/{claim_id}/documents", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
def upload_documents(
    claim_id: str,
    files: list[UploadFile] = File(...),
    submit: bool = Query(default=True, description="Kirim klaim ke antrean proses setelah unggah"),
    request: Request = None,
    doc_types: list[str] | None = Form(default=None, description="U4: jenis tiap file dokumen susulan (urutan sama)"),
    db: Session = Depends(get_db),
    user: User = Depends(can_submit),
    storage=Depends(get_storage),
    queue=Depends(get_queue),
) -> UploadResult:
    claim = get_visible_claim(db, user, claim_id)
    if claim.status == ClaimStatus.PENDING_DOCUMENTS.value:
        # U4: asuransi mengunggah sendiri dokumen susulan yang diminta
        docs, _, job_id = doc_requests.upload_late(db, storage, queue, claim, user, files, doc_types, None, request=request)
        return UploadResult(documents=[DocumentOut.model_validate(d) for d in docs], job_id=job_id, status=claim.status)
    if claim.status not in (ClaimStatus.RECEIVED.value, ClaimStatus.QUEUED.value, ClaimStatus.FAILED.value):
        raise HTTPException(status.HTTP_409_CONFLICT, "Klaim sudah diproses; dokumen tidak bisa ditambah")
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    try:
        valid = [validate_file(f.filename or "dokumen", f.file.read(max_bytes + 1)) for f in files]
    except InvalidFile as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    docs = [store_document(db, storage, claim, user, f) for f in valid]
    db.commit()
    job_id = None
    if submit:
        job_id = _queue_claim(claim, queue)
        db.commit()
    return UploadResult(documents=[DocumentOut.model_validate(d) for d in docs], job_id=job_id, status=claim.status)


@router.get("/{claim_id}/recommendation", response_model=RecommendationOut)
def get_recommendation(claim_id: str, db: Session = Depends(get_db), user: User = Depends(can_detail)) -> RecommendationOut:
    claim = get_visible_claim(db, user, claim_id)
    rec = _current_recommendation(claim)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rekomendasi belum tersedia")
    if not can_see_draft(user.role) and not _released_to_insurer(rec):
        raise HTTPException(status.HTTP_409_CONFLICT, "Rekomendasi menunggu telaah dan tanda tangan dokter")
    return build_recommendation_view(claim, rec)


@router.get("/{claim_id}/recommendation.pdf")
def get_recommendation_pdf(claim_id: str, db: Session = Depends(get_db), user: User = Depends(can_detail)) -> Response:
    """Rekomendasi sebagai PDF sederhana (isi sama dengan tampilan portal)."""
    view = get_recommendation(claim_id, db, user)
    claim = get_visible_claim(db, user, claim_id)
    pdf = recommendation_pdf(view.model_dump(mode="json"), {d.id: d.filename for d in claim.documents})
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="rekomendasi_{claim.claim_number}.pdf"'})


@router.post("/{claim_id}/decision", response_model=RecommendationOut, status_code=status.HTTP_201_CREATED)
def record_decision(
    claim_id: str, body: DecisionCreate, db: Session = Depends(get_db), user: User = Depends(can_decide),
    queue=Depends(get_queue),
) -> RecommendationOut:
    claim = get_visible_claim(db, user, claim_id)
    rec = _current_recommendation(claim)
    if rec is None or not _released_to_insurer(rec):
        raise HTTPException(status.HTTP_409_CONFLICT, "Belum ada rekomendasi final untuk diputuskan")
    if _latest_decision(claim) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Keputusan untuk klaim ini sudah dicatat")
    if claim.status == ClaimStatus.PENDING_DOCUMENTS.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Klaim menunggu dokumen susulan dari faskes")
    reason = (body.reason or "").strip() or None
    wants_docs = bool(body.doc_types) or bool(missing_documents(claim))
    if rec.recommendation == RecommendationCode.PEND.value and body.decision == DecisionCode.AGREE.value and wants_docs:
        # U4: setuju menunda = minta dokumen ke faskes; klaim belum selesai.
        # Tunda untuk klarifikasi tanpa dokumen yang kurang tetap dicatat sebagai keputusan biasa.
        doc_requests.open_request(db, claim, rec, user, doc_types=body.doc_types, message=body.message or reason)
        db.add(InsurerDecision(claim_id=claim.id, recommendation_id=rec.id, decision=body.decision, reason=reason,
                               decided_by_id=user.id))
        hook = queue_event(db, claim, "claim.documents_requested")
    else:
        _record_decision(db, claim, rec, user, body.decision, reason)
        hook = queue_event(db, claim, "claim.decision_recorded")
    db.commit()
    dispatch(queue, [hook])
    db.refresh(claim)
    return build_recommendation_view(claim, rec)


# --- U4: permintaan dokumen susulan ------------------------------------------------------


@router.get("/{claim_id}/document-requests", response_model=list[DocumentRequestOut])
def list_document_requests(claim_id: str, db: Session = Depends(get_db), user: User = Depends(can_list)) -> list[DocumentRequestOut]:
    claim = get_visible_claim(db, user, claim_id)
    return [doc_requests.to_out(r, claim) for r in doc_requests.requests_for(db, claim)]


@router.post("/{claim_id}/document-requests", response_model=DocumentRequestOut, status_code=status.HTTP_201_CREATED)
def create_document_request(claim_id: str, body: DocumentRequestCreate, request: Request, db: Session = Depends(get_db),
                            user: User = Depends(can_decide), queue=Depends(get_queue)) -> DocumentRequestOut:
    """Tunda klaim dan minta dokumen susulan ke faskes (tanpa mencatat keputusan)."""
    claim = get_visible_claim(db, user, claim_id)
    rec = _current_recommendation(claim)
    if rec is None or not _released_to_insurer(rec):
        raise HTTPException(status.HTTP_409_CONFLICT, "Belum ada rekomendasi final untuk klaim ini")
    if _latest_decision(claim) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Keputusan untuk klaim ini sudah dicatat")
    req = doc_requests.open_request(db, claim, rec, user, doc_types=body.doc_types, message=body.message,
                                    due_days=body.due_days, request=request)
    hook = queue_event(db, claim, "claim.documents_requested")
    db.commit()
    dispatch(queue, [hook])
    db.refresh(req)
    return doc_requests.to_out(req, claim)


@router.post("/{claim_id}/document-requests/cancel", response_model=DocumentRequestOut)
def cancel_document_request(claim_id: str, request: Request, db: Session = Depends(get_db),
                            user: User = Depends(can_decide)) -> DocumentRequestOut:
    claim = get_visible_claim(db, user, claim_id)
    if _latest_decision(claim) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Permintaan ini bagian dari keputusan tunda; tidak bisa dibatalkan")
    req = doc_requests.cancel_request(db, claim, user, request=request)
    db.commit()
    db.refresh(req)
    return doc_requests.to_out(req, claim)
