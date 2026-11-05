"""Validasi dan penyimpanan file dokumen klaim."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from mab_api.config import get_settings
from mab_api.models import Claim, Document, User

# Sama dengan triase.dokumen_wajib_rawat_inap di rules/aturan_klinis_demo.yaml (dicek oleh tes)
REQUIRED_INPATIENT_DOCS = ("resume_medis", "rincian_tagihan", "hasil_laboratorium")

_MAGIC = {
    b"%PDF-": "application/pdf",
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}

# Tebakan awal dari nama file; klasifikasi sesungguhnya oleh pipeline (M4)
_DOC_TYPE_PATTERNS = [
    ("resume_medis", re.compile(r"resume|ringkasan[_ -]?pulang|discharge", re.I)),
    ("hasil_laboratorium", re.compile(r"\blab|laboratori", re.I)),
    ("rincian_tagihan", re.compile(r"tagihan|billing|invoice|kwitansi|rincian", re.I)),
    ("cppt", re.compile(r"cppt|catatan[_ -]?perkembangan|progress", re.I)),
    ("laporan_operasi", re.compile(r"operasi|operative", re.I)),
    ("resep", re.compile(r"resep|prescription", re.I)),
]


class InvalidFile(ValueError):
    pass


@dataclass
class ValidFile:
    filename: str
    data: bytes
    content_type: str


def sniff_content_type(data: bytes) -> str | None:
    for magic, ctype in _MAGIC.items():
        if data.startswith(magic):
            return ctype
    return None


def guess_doc_type(filename: str) -> str:
    for doc_type, pattern in _DOC_TYPE_PATTERNS:
        if pattern.search(filename):
            return doc_type
    return "unknown"


def safe_filename(name: str) -> str:
    base = name.replace("\\", "/").split("/")[-1]
    return re.sub(r"[^A-Za-z0-9._ -]", "_", base)[:200] or "dokumen"


def validate_file(filename: str, data: bytes) -> ValidFile:
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    if not data:
        raise InvalidFile(f"{filename}: file kosong")
    if len(data) > max_bytes:
        raise InvalidFile(f"{filename}: ukuran melebihi {get_settings().max_upload_mb} MB")
    ctype = sniff_content_type(data)
    if ctype is None:
        raise InvalidFile(f"{filename}: hanya PDF, JPG, atau PNG yang diterima")
    return ValidFile(safe_filename(filename), data, ctype)


def store_document(db: Session, storage, claim: Claim, user: User | None, f: ValidFile) -> Document:
    """Simpan file dokumen. `user` kosong untuk dokumen dari integrasi (API, SFTP, FHIR)."""
    doc = Document(
        claim_id=claim.id,
        filename=f.filename,
        content_type=f.content_type,
        size_bytes=len(f.data),
        sha256=hashlib.sha256(f.data).hexdigest(),
        storage_key="",
        doc_type=guess_doc_type(f.filename),
        uploaded_by_id=user.id if user else None,
    )
    db.add(doc)
    db.flush()  # dapatkan id
    doc.storage_key = f"{claim.insurer_id}/{claim.id}/{doc.id}/{f.filename}"
    try:
        storage.put(doc.storage_key, f.data, f.content_type)
    except Exception as exc:  # gagal simpan file = gagalkan request, jangan tinggalkan baris yatim
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Penyimpanan file tidak tersedia: {exc}") from exc
    return doc


def missing_documents(claim: Claim) -> list[str]:
    present = {d.doc_type for d in claim.documents}
    return [d for d in REQUIRED_INPATIENT_DOCS if d not in present]
