"""Endpoint klaim: buat, unggah dokumen (satuan & ZIP), status, rekomendasi, keputusan, ekspor."""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mab_api.access import get_visible_claim, visible_claims_query
from mab_api.api_schemas import (
    BatchResult,
    BatchRowResult,
    BulkAgreeRequest,
    BulkAgreeResult,
    ClaimCreate,
    ClaimDetail,
    ClaimOut,
    ClaimStatusOut,
    DecisionCreate,
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
from mab_api.deps import get_current_user, get_queue, get_storage, require_roles
from mab_api.documents import InvalidFile, missing_documents, store_document, validate_file
from mab_api.models import (
    INSURER_ROLES,
    Claim,
    ClaimStatus,
    DecisionCode,
    ExtractedField,
    InsurerDecision,
    Recommendation,
    RecommendationCode,
    RecommendationState,
    Role,
    User,
)

router = APIRouter(prefix="/claims", tags=["klaim"])

insurer_only = require_roles(Role.INSURER_STAFF, Role.INSURER_MANAGER)


# ----------------------------------------------------------------------------- bantuan


def _current_recommendation(claim: Claim) -> Recommendation | None:
    return next((r for r in reversed(claim.recommendations) if r.is_current), None)


def _released_to_insurer(rec: Recommendation) -> bool:
    """Prinsip produk: selain bayar penuh, rekomendasi wajib ditandatangani dokter dulu."""
    return rec.recommendation == RecommendationCode.PAY_FULL.value or rec.state == RecommendationState.SIGNED.value


def _latest_decision(claim: Claim) -> InsurerDecision | None:
    return claim.decisions[-1] if claim.decisions else None


def _queue_claim(claim: Claim, queue) -> str:
    job_id = queue.enqueue_process_claim(claim.id)
    claim.status = ClaimStatus.QUEUED.value
    claim.processing_error = None
    return job_id


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
        insurer_decision=InsurerDecisionOut(
            decision=decision.decision,
            reason=decision.reason,
            decided_by=decision.decided_by.full_name,
            decided_at=decision.decided_at,
        )
        if decision
        else None,
    )


def _record_decision(db: Session, claim: Claim, rec: Recommendation, user: User, decision: str, reason: str | None) -> None:
    db.add(InsurerDecision(claim_id=claim.id, recommendation_id=rec.id, decision=decision, reason=reason, decided_by_id=user.id))
    claim.status = ClaimStatus.COMPLETED.value


# ----------------------------------------------------------------------------- buat & lihat


@router.post("", response_model=ClaimOut, status_code=status.HTTP_201_CREATED)
def create_claim(body: ClaimCreate, db: Session = Depends(get_db), user: User = Depends(insurer_only)) -> Claim:
    claim = Claim(insurer_id=user.insurer_id, created_by_id=user.id, **body.model_dump())
    db.add(claim)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, f"Nomor klaim {body.claim_number} sudah ada")
    return claim


@router.get("", response_model=list[ClaimOut])
def list_claims(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Claim]:
    q = visible_claims_query(user)
    if status_filter:
        q = q.where(Claim.status == status_filter)
    return list(db.scalars(q.order_by(Claim.created_at.desc()).limit(limit).offset(offset)))


# --- ekspor & keputusan massal didefinisikan sebelum /{claim_id} -------------------------------

EXPORT_COLUMNS = [
    "nomor_klaim", "nomor_polis", "id_peserta", "nama_rs", "tanggal_masuk", "tanggal_keluar",
    "nilai_tagihan", "status_klaim", "status_triase", "skor_risiko", "rekomendasi", "nilai_rekomendasi",
    "kode_alasan", "dokter_penelaah", "waktu_tanda_tangan", "versi_aturan", "versi_model",
    "keputusan_asuransi", "alasan_keputusan", "diputuskan_oleh", "waktu_keputusan",
]


@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), user: User = Depends(insurer_only)) -> StreamingResponse:
    claims = list(db.scalars(visible_claims_query(user).order_by(Claim.created_at)))
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
def bulk_agree_green(body: BulkAgreeRequest, db: Session = Depends(get_db), user: User = Depends(insurer_only)) -> BulkAgreeResult:
    """Setujui massal klaim hijau (PAY_FULL) yang belum diputuskan."""
    agreed, skipped = [], []
    for claim_id in dict.fromkeys(body.claim_ids):
        claim = db.scalar(visible_claims_query(user).where(Claim.id == claim_id))
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
    db.commit()
    return BulkAgreeResult(agreed=agreed, skipped=skipped)


# --- unggah massal ZIP --------------------------------------------------------------------

MANIFEST_COLUMNS = {
    "folder": "folder",
    "nomor_klaim": "claim_number",
    "nomor_polis": "policy_number",
    "id_peserta": "member_id",
    "nama_peserta": "patient_name",
    "nama_rs": "hospital_name",
    "tanggal_masuk": "admission_date",
    "tanggal_keluar": "discharge_date",
    "nilai_tagihan": "billed_amount",
}


def _parse_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"format tanggal tidak dikenal: {text}")


def _read_manifest(data: bytes) -> list[dict]:
    from openpyxl import load_workbook

    ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("manifest kosong")
    header = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    missing = [c for c in MANIFEST_COLUMNS if c not in header and c != "nama_peserta"]
    if missing:
        raise ValueError(f"kolom manifest tidak ada: {', '.join(missing)}")
    out = []
    for values in rows[1:]:
        if values is None or all(v in (None, "") for v in values):
            continue
        out.append({MANIFEST_COLUMNS[h]: v for h, v in zip(header, values) if h in MANIFEST_COLUMNS})
    return out


@router.post("/batch", response_model=BatchResult)
def upload_batch(
    file: UploadFile = File(..., description="ZIP berisi manifest.xlsx dan satu folder per klaim"),
    db: Session = Depends(get_db),
    user: User = Depends(insurer_only),
    storage=Depends(get_storage),
    queue=Depends(get_queue),
) -> BatchResult:
    settings = get_settings()
    raw = file.file.read(settings.max_zip_mb * 1024 * 1024 + 1)
    if len(raw) > settings.max_zip_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"ZIP melebihi {settings.max_zip_mb} MB")
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File bukan ZIP yang valid")

    # Hanya baca entri; tidak ada yang diekstrak ke disk. Abaikan path aneh (zip-slip).
    entries = {
        info.filename.replace("\\", "/").strip("/"): info
        for info in zf.infolist()
        if not info.is_dir() and ".." not in info.filename and not info.filename.startswith(("/", "__MACOSX"))
    }
    manifest_name = next((n for n in entries if n.split("/")[-1].lower() in ("manifest.xlsx",)), None)
    if manifest_name is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "manifest.xlsx tidak ditemukan di dalam ZIP")
    prefix = manifest_name.rsplit("/", 1)[0] + "/" if "/" in manifest_name else ""
    try:
        rows = _read_manifest(zf.read(entries[manifest_name]))
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Manifest tidak bisa dibaca: {exc}")

    results: list[BatchRowResult] = []
    created_claims: list[Claim] = []
    for i, row in enumerate(rows, start=2):  # baris 1 = header
        folder = str(row.get("folder") or "").strip().strip("/")
        claim_number = str(row.get("claim_number") or "").strip() or None
        result = BatchRowResult(row=i, folder=folder or None, claim_number=claim_number, ok=False)
        results.append(result)
        try:
            body = ClaimCreate(
                claim_number=claim_number or "",
                policy_number=str(row.get("policy_number") or "").strip(),
                member_id=str(row.get("member_id") or "").strip(),
                patient_name=(str(row["patient_name"]).strip() if row.get("patient_name") else None),
                hospital_name=str(row.get("hospital_name") or "").strip(),
                admission_date=_parse_date(row.get("admission_date")),
                discharge_date=_parse_date(row.get("discharge_date")),
                billed_amount=int(float(row.get("billed_amount") or 0)),
            )
        except (ValidationError, ValueError, TypeError) as exc:
            msg = "; ".join(e["msg"] for e in exc.errors()) if isinstance(exc, ValidationError) else str(exc)
            result.reason = f"Data manifest tidak valid: {msg}"
            continue
        if not folder:
            result.reason = "Kolom folder kosong"
            continue
        files = [n for n in entries if n.startswith(f"{prefix}{folder}/")]
        if not files:
            result.reason = f"Folder {folder} tidak ada di ZIP atau kosong"
            continue
        try:
            valid = [validate_file(n.split("/")[-1], zf.read(entries[n])) for n in sorted(files)]
        except InvalidFile as exc:
            result.reason = str(exc)
            continue

        savepoint = db.begin_nested()
        try:
            claim = Claim(insurer_id=user.insurer_id, created_by_id=user.id, **body.model_dump())
            db.add(claim)
            db.flush()
            for f in valid:
                store_document(db, storage, claim, user, f)
            savepoint.commit()
        except IntegrityError:
            savepoint.rollback()
            result.reason = f"Nomor klaim {claim_number} sudah ada"
            continue
        except HTTPException as exc:
            savepoint.rollback()
            result.reason = str(exc.detail)
            continue
        result.ok, result.claim_id, result.documents = True, claim.id, len(valid)
        created_claims.append(claim)

    db.commit()
    for claim in created_claims:
        _queue_claim(claim, queue)
    db.commit()
    ok = sum(r.ok for r in results)
    return BatchResult(created=ok, failed=len(results) - ok, rows=results)


# --- per klaim -----------------------------------------------------------------------------


@router.get("/{claim_id}", response_model=ClaimDetail)
def get_claim(claim_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ClaimDetail:
    claim = get_visible_claim(db, user, claim_id)
    rec = _current_recommendation(claim)
    show_triage = rec is not None and (Role(user.role) not in INSURER_ROLES or _released_to_insurer(rec))
    return ClaimDetail(
        **ClaimOut.model_validate(claim).model_dump(),
        documents=[DocumentOut.model_validate(d) for d in claim.documents],
        missing_documents=missing_documents(claim),
        triage_status=rec.triage_status if show_triage else None,
    )


@router.get("/{claim_id}/status", response_model=ClaimStatusOut)
def get_claim_status(claim_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> ClaimStatusOut:
    claim = get_visible_claim(db, user, claim_id)
    return ClaimStatusOut(id=claim.id, status=claim.status, processing_error=claim.processing_error, updated_at=claim.updated_at)


@router.get("/{claim_id}/fields", response_model=list[ExtractedFieldOut])
def get_extracted_fields(claim_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[ExtractedFieldOut]:
    """Field hasil baca dokumen beserta bukti (dokumen, halaman, bbox, kutipan)."""
    claim = get_visible_claim(db, user, claim_id)
    rows = db.scalars(select(ExtractedField).where(ExtractedField.claim_id == claim.id).order_by(ExtractedField.field_path))
    return [ExtractedFieldOut.model_validate(r) for r in rows]


@router.post("/{claim_id}/documents", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
def upload_documents(
    claim_id: str,
    files: list[UploadFile] = File(...),
    submit: bool = Query(default=True, description="Kirim klaim ke antrean proses setelah unggah"),
    db: Session = Depends(get_db),
    user: User = Depends(insurer_only),
    storage=Depends(get_storage),
    queue=Depends(get_queue),
) -> UploadResult:
    claim = get_visible_claim(db, user, claim_id)
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
def get_recommendation(claim_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> RecommendationOut:
    claim = get_visible_claim(db, user, claim_id)
    rec = _current_recommendation(claim)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rekomendasi belum tersedia")
    if Role(user.role) in INSURER_ROLES and not _released_to_insurer(rec):
        raise HTTPException(status.HTTP_409_CONFLICT, "Rekomendasi menunggu telaah dan tanda tangan dokter")
    return build_recommendation_view(claim, rec)


@router.post("/{claim_id}/decision", response_model=RecommendationOut, status_code=status.HTTP_201_CREATED)
def record_decision(
    claim_id: str, body: DecisionCreate, db: Session = Depends(get_db), user: User = Depends(insurer_only)
) -> RecommendationOut:
    claim = get_visible_claim(db, user, claim_id)
    rec = _current_recommendation(claim)
    if rec is None or not _released_to_insurer(rec):
        raise HTTPException(status.HTTP_409_CONFLICT, "Belum ada rekomendasi final untuk diputuskan")
    if _latest_decision(claim) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Keputusan untuk klaim ini sudah dicatat")
    _record_decision(db, claim, rec, user, body.decision, (body.reason or "").strip() or None)
    db.commit()
    db.refresh(claim)
    return build_recommendation_view(claim, rec)
