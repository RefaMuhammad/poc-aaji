"""Klaim masuk lewat berkas: ZIP + manifest (portal, SFTP) dan klaim tunggal dari integrasi (API, FHIR).

Dipakai bersama router klaim (unggah ZIP di portal), router integrasi, dan pengawas folder SFTP,
supaya validasi file, manifest, dan nomor klaim ganda sama persis di semua kanal.
"""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mab_api.api_schemas import BatchRowResult, ClaimCreate
from mab_api.documents import InvalidFile, ValidFile, store_document, validate_file
from mab_api.models import Claim, ClaimSource, ClaimStatus, User

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


class BatchError(ValueError):
    """ZIP atau manifest tidak bisa dipakai sama sekali."""


class DuplicateClaim(ValueError):
    pass


def parse_date(value) -> date | None:
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


def read_manifest(data: bytes) -> list[dict]:
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


def queue_claim(claim: Claim, queue) -> str:
    job_id = queue.enqueue_process_claim(claim.id)
    claim.status = ClaimStatus.QUEUED.value
    claim.processing_error = None
    return job_id


def create_claim(db: Session, storage, insurer_id: str, body: ClaimCreate, files: list[ValidFile], *,
                 source: ClaimSource, user: User | None = None, api_client_id: str | None = None) -> Claim:
    """Buat klaim + simpan dokumennya dalam satu savepoint. Nomor klaim ganda -> DuplicateClaim."""
    savepoint = db.begin_nested()
    try:
        claim = Claim(insurer_id=insurer_id, created_by_id=user.id if user else None, source=source.value,
                      api_client_id=api_client_id, **body.model_dump(exclude={"insurer_id"}))
        db.add(claim)
        db.flush()
        for f in files:
            store_document(db, storage, claim, user, f)
        savepoint.commit()
    except IntegrityError:
        savepoint.rollback()
        raise DuplicateClaim(f"Nomor klaim {body.claim_number} sudah ada")
    except HTTPException:
        savepoint.rollback()
        raise
    return claim


@dataclass
class ZipImport:
    rows: list[BatchRowResult] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)

    @property
    def created(self) -> int:
        return sum(r.ok for r in self.rows)

    @property
    def failed(self) -> int:
        return len(self.rows) - self.created


def import_zip(db: Session, storage, insurer_id: str, raw: bytes, *, source: ClaimSource,
               user: User | None = None, api_client_id: str | None = None) -> ZipImport:
    """Buat klaim dari ZIP berisi manifest.xlsx + satu folder per klaim. Baris yang salah dilewati.
    Belum commit dan belum masuk antrean; pemanggil yang melakukannya."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        raise BatchError("File bukan ZIP yang valid")

    # Hanya baca entri; tidak ada yang diekstrak ke disk. Abaikan path aneh (zip-slip).
    entries = {
        info.filename.replace("\\", "/").strip("/"): info
        for info in zf.infolist()
        if not info.is_dir() and ".." not in info.filename and not info.filename.startswith(("/", "__MACOSX"))
    }
    manifest_name = next((n for n in entries if n.split("/")[-1].lower() in ("manifest.xlsx",)), None)
    if manifest_name is None:
        raise BatchError("manifest.xlsx tidak ditemukan di dalam ZIP")
    prefix = manifest_name.rsplit("/", 1)[0] + "/" if "/" in manifest_name else ""
    try:
        rows = read_manifest(zf.read(entries[manifest_name]))
    except Exception as exc:
        raise BatchError(f"Manifest tidak bisa dibaca: {exc}")

    out = ZipImport()
    for i, row in enumerate(rows, start=2):  # baris 1 = header
        folder = str(row.get("folder") or "").strip().strip("/")
        claim_number = str(row.get("claim_number") or "").strip() or None
        result = BatchRowResult(row=i, folder=folder or None, claim_number=claim_number, ok=False)
        out.rows.append(result)
        try:
            body = ClaimCreate(
                claim_number=claim_number or "",
                policy_number=str(row.get("policy_number") or "").strip(),
                member_id=str(row.get("member_id") or "").strip(),
                patient_name=(str(row["patient_name"]).strip() if row.get("patient_name") else None),
                hospital_name=str(row.get("hospital_name") or "").strip(),
                admission_date=parse_date(row.get("admission_date")),
                discharge_date=parse_date(row.get("discharge_date")),
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
        try:
            claim = create_claim(db, storage, insurer_id, body, valid, source=source, user=user, api_client_id=api_client_id)
        except DuplicateClaim as exc:
            result.reason = str(exc)
            continue
        except HTTPException as exc:
            result.reason = str(exc.detail)
            continue
        result.ok, result.claim_id, result.documents = True, claim.id, len(valid)
        out.claims.append(claim)
    return out
