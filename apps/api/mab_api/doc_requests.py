"""Alur "tunda: minta dokumen" (U4).

1. Asuransi menunda klaim yang rekomendasinya sudah dirilis dan meminta dokumen susulan
   (`open_request`). Klaim menjadi PENDING_DOCUMENTS; faskes dan peserta mendapat notifikasi.
2. Faskes (atau asuransi) mengunggah dokumen (`attach_documents`). Permintaan tetap OPEN sampai
   semua jenis dokumen yang diminta ada di klaim.
3. Setelah lengkap, permintaan FULFILLED dan klaim masuk antrean proses ulang. Pipeline membuat
   draf baru yang WAJIB ditelaah dokter (lihat `requires_doctor_after_documents`), diutamakan
   dokter yang menandatangani rekomendasi sebelumnya. Setelah ditandatangani, asuransi memutuskan.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from mab_api import audit, notify
from mab_api.documents import ValidFile, missing_documents, store_document
from mab_api.models import Claim, ClaimStatus, Document, DocumentRequest, Recommendation, User

OPEN, FULFILLED, CANCELLED = "OPEN", "FULFILLED", "CANCELLED"
DEFAULT_DUE_DAYS = 7
KNOWN_DOC_TYPES = ("resume_medis", "rincian_tagihan", "hasil_laboratorium", "cppt", "laporan_operasi", "resep")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def requests_for(db: Session, claim: Claim) -> list[DocumentRequest]:
    return list(db.scalars(select(DocumentRequest).where(DocumentRequest.claim_id == claim.id)
                           .order_by(DocumentRequest.created_at)))


def open_request_for(db: Session, claim: Claim) -> DocumentRequest | None:
    return db.scalar(select(DocumentRequest).where(DocumentRequest.claim_id == claim.id, DocumentRequest.status == OPEN))


def outstanding(req: DocumentRequest, claim: Claim) -> list[str]:
    """Jenis dokumen yang diminta tetapi belum ada di klaim."""
    present = {d.doc_type for d in claim.documents}
    return [d for d in (req.doc_types or []) if d not in present]


def open_request(db: Session, claim: Claim, rec: Recommendation, user: User, *, doc_types: list[str] | None,
                 message: str | None, due_days: int = DEFAULT_DUE_DAYS, request=None) -> DocumentRequest:
    if claim.status != ClaimStatus.AWAITING_DECISION.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Dokumen hanya bisa diminta saat klaim menunggu keputusan asuransi")
    if open_request_for(db, claim) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Masih ada permintaan dokumen yang terbuka untuk klaim ini")
    if rec.dispute_id:
        # U5: proses ulang akan membuat draf baru di luar banding; dokumen banding sudah dikirim pengaju.
        raise HTTPException(status.HTTP_409_CONFLICT, "Klaim sedang diputus ulang atas banding; dokumen tidak bisa diminta")
    types = list(dict.fromkeys(t.strip() for t in (doc_types or []) if t and t.strip())) or missing_documents(claim)
    if not types:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pilih minimal satu jenis dokumen yang diminta")
    unknown = [t for t in types if t not in KNOWN_DOC_TYPES]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Jenis dokumen tidak dikenal: {', '.join(unknown)}")
    text = (message or "").strip() or ("Mohon kirimkan " + ", ".join(notify.doc_label(t) for t in types)
                                       + " untuk melengkapi klaim.")
    due = _now() + timedelta(days=due_days)
    req = DocumentRequest(claim_id=claim.id, insurer_id=claim.insurer_id, recommendation_id=rec.id, doc_types=types,
                          message=text, status=OPEN, requested_by_id=user.id, due_at=due)
    db.add(req)
    claim.status = ClaimStatus.PENDING_DOCUMENTS.value
    db.flush()
    audit.record(db, "DOCUMENTS_REQUESTED", user_id=user.id, user_role=user.role, claim_id=claim.id, request=request,
                 detail={"request_id": req.id, "doc_types": types, "recommendation_id": rec.id, "due_at": due.isoformat()})
    notify.documents_requested(db, claim, types, text, due.strftime("%d-%m-%Y"))
    return req


def attach_documents(db: Session, storage, claim: Claim, user: User, files: list[ValidFile],
                     doc_types: list[str] | None, note: str | None, request=None) -> tuple[list[Document], DocumentRequest]:
    """Simpan dokumen susulan. Kembalikan (dokumen, permintaan); permintaan FULFILLED bila sudah lengkap."""
    req = open_request_for(db, claim)
    if req is None or claim.status != ClaimStatus.PENDING_DOCUMENTS.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tidak ada permintaan dokumen yang terbuka untuk klaim ini")
    declared = list(doc_types or [])
    if declared and len(declared) != len(files):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Jumlah jenis dokumen harus sama dengan jumlah file")
    docs = []
    for i, f in enumerate(files):
        doc = store_document(db, storage, claim, user, f)
        kind = (declared[i] if declared else "").strip()
        if kind:
            if kind not in KNOWN_DOC_TYPES:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Jenis dokumen tidak dikenal: {kind}")
            doc.doc_type = kind
        docs.append(doc)
    db.flush()
    db.refresh(claim)
    req.document_ids = list(req.document_ids or []) + [d.id for d in docs]
    if note and note.strip():
        req.response_note = note.strip()[:2000]
    audit.record(db, "LATE_DOCUMENTS_UPLOADED", user_id=user.id, user_role=user.role, claim_id=claim.id, request=request,
                 detail={"request_id": req.id, "documents": {d.id: d.doc_type for d in docs}})
    if not outstanding(req, claim):
        req.status = FULFILLED
        req.fulfilled_at = _now()
        req.fulfilled_by_id = user.id
        audit.record(db, "DOCUMENT_REQUEST_FULFILLED", user_id=user.id, user_role=user.role, claim_id=claim.id,
                     request=request, detail={"request_id": req.id})
        notify.documents_received(db, claim, list(req.doc_types or []), user)
    return docs, req


def cancel_request(db: Session, claim: Claim, user: User, request=None) -> DocumentRequest:
    """Asuransi membatalkan permintaan; klaim kembali menunggu keputusan atas rekomendasi yang sama."""
    req = open_request_for(db, claim)
    if req is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tidak ada permintaan dokumen yang terbuka")
    req.status = CANCELLED
    claim.status = ClaimStatus.AWAITING_DECISION.value
    audit.record(db, "DOCUMENT_REQUEST_CANCELLED", user_id=user.id, user_role=user.role, claim_id=claim.id,
                 request=request, detail={"request_id": req.id})
    return req


def requires_doctor_after_documents(db: Session, claim: Claim) -> tuple[bool, str | None]:
    """Dipakai pipeline saat proses ulang: (wajib telaah dokter, id dokter yang diutamakan).

    Klaim yang pernah ditunda lalu dokumennya dilengkapi selalu kembali ke dokter, walau draf baru
    bayar penuh: dokter yang menunda perlu melihat dokumen yang dimintanya sendiri.
    """
    done = [r for r in requests_for(db, claim) if r.status == FULFILLED]
    if not done:
        return False, None
    last = done[-1]
    rec = db.get(Recommendation, last.recommendation_id) if last.recommendation_id else None
    return True, rec.signed_by_id if rec is not None else None


def to_out(req: DocumentRequest, claim: Claim):
    from mab_api.api_schemas import DocumentRequestOut

    due = req.due_at if req.due_at.tzinfo else req.due_at.replace(tzinfo=timezone.utc)
    return DocumentRequestOut(
        id=req.id, claim_id=req.claim_id, status=req.status, doc_types=list(req.doc_types or []),
        outstanding=outstanding(req, claim) if req.status == OPEN else [],
        message=req.message, requested_by=req.requested_by.full_name if req.requested_by else "",
        created_at=req.created_at, due_at=req.due_at, overdue=req.status == OPEN and due < _now(),
        fulfilled_at=req.fulfilled_at, fulfilled_by=req.fulfilled_by.full_name if req.fulfilled_by else None,
        document_ids=list(req.document_ids or []), response_note=req.response_note,
    )


def upload_late(db: Session, storage, queue, claim: Claim, user: User, uploads: list, doc_types: list[str] | None,
                note: str | None, request=None):
    """Unggah dokumen susulan dari endpoint (faskes atau asuransi). Bila permintaan lengkap, klaim diproses ulang.

    Kembalikan (dokumen, permintaan, job_id atau None).
    """
    from mab_api.batch import queue_claim
    from mab_api.config import get_settings
    from mab_api.documents import InvalidFile, validate_file

    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    try:
        valid = [validate_file(f.filename or "dokumen", f.file.read(max_bytes + 1)) for f in uploads]
    except InvalidFile as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    docs, req = attach_documents(db, storage, claim, user, valid, doc_types, note, request=request)
    db.commit()
    job_id = None
    if req.status == FULFILLED:
        job_id = queue_claim(claim, queue)
        db.commit()
    return docs, req, job_id
