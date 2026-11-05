"""Pengawas folder SFTP (U2): klaim batch dari sistem asuransi/TPA lewat folder.

Struktur per tenant (nama folder = kode tenant, mis. data/sftp/PELITA):
    masuk/      asuransi menaruh ZIP (manifest.xlsx + satu folder per klaim, sama dengan unggah massal portal)
    keluar/     hasil_<nama zip>.csv (baris diterima/ditolak) dan status_klaim.csv (status semua klaim SFTP)
    diproses/   ZIP yang sudah diproses
    gagal/      ZIP yang tidak bisa dibaca sama sekali, beserta <nama>.error.txt

ZIP baru diproses setelah ukurannya tidak berubah selama `STABLE_SECONDS` (unggahan selesai).
status_klaim.csv hanya memuat rekomendasi yang SUDAH dirilis ke asuransi.

Jalankan:  python -m mab_pipeline.sftp_watcher          (terus-menerus)
           python -m mab_pipeline.sftp_watcher --once   (satu putaran, untuk uji/demo)
"""
from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("mab.sftp")

SUBDIRS = ("masuk", "keluar", "diproses", "gagal")
STABLE_SECONDS = 3.0
STATUS_COLUMNS = ("nomor_klaim", "status", "triase", "rekomendasi", "nilai_tagihan", "nilai_disarankan", "kode_alasan",
                  "ditandatangani_oleh", "keputusan", "diperbarui", "label")
RESULT_COLUMNS = ("baris", "folder", "nomor_klaim", "diterima", "jumlah_dokumen", "alasan", "claim_id")


def ensure_dirs(tenant_dir: Path) -> None:
    for sub in SUBDIRS:
        d = tenant_dir / sub
        d.mkdir(parents=True, exist_ok=True)
        try:  # pengguna SFTP (uid lain) harus bisa menulis ke masuk/ dan membaca keluar/
            os.chmod(d, 0o777)
        except PermissionError:
            pass


def _stable(path: Path, seen: dict[Path, tuple[int, float]], now: float) -> bool:
    size = path.stat().st_size
    prev = seen.get(path)
    if prev is None or prev[0] != size:
        seen[path] = (size, now)
        return False
    return now - prev[1] >= STABLE_SECONDS


def _csv_bytes(columns, rows) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(columns)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def _write_if_changed(path: Path, data: bytes) -> None:
    if path.exists() and path.read_bytes() == data:
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def process_zip(db, storage, queue, insurer, zip_path: Path, tenant_dir: Path) -> dict:
    from mab_api.batch import BatchError, import_zip, queue_claim
    from mab_api.models import ClaimSource, IntegrationJob

    name = zip_path.name
    try:
        result = import_zip(db, storage, insurer.id, zip_path.read_bytes(), source=ClaimSource.SFTP)
    except BatchError as exc:
        db.rollback()
        db.add(IntegrationJob(insurer_id=insurer.id, channel="SFTP", reference=name, status="FAILED", summary={"error": str(exc)}))
        db.commit()
        target = tenant_dir / "gagal" / f"{_stamp()}_{name}"
        shutil.move(str(zip_path), target)
        target.with_suffix(".error.txt").write_text(f"{name}: {exc}\n", encoding="utf-8")
        log.warning("SFTP %s/%s gagal: %s", insurer.code, name, exc)
        return {"file": name, "status": "FAILED", "error": str(exc)}

    status = "SUCCESS" if result.failed == 0 else ("PARTIAL" if result.created else "FAILED")
    db.add(IntegrationJob(insurer_id=insurer.id, channel="SFTP", reference=name, status=status, summary={
        "created": result.created, "failed": result.failed,
        "rows": [r.model_dump() for r in result.rows][:200],
    }))
    db.commit()
    for claim in result.claims:
        queue_claim(claim, queue)
    db.commit()
    rows = [(r.row, r.folder or "", r.claim_number or "", "ya" if r.ok else "tidak", r.documents, r.reason or "", r.claim_id or "")
            for r in result.rows]
    _write_if_changed(tenant_dir / "keluar" / f"hasil_{zip_path.stem}.csv", _csv_bytes(RESULT_COLUMNS, rows))
    shutil.move(str(zip_path), tenant_dir / "diproses" / f"{_stamp()}_{name}")
    log.info("SFTP %s/%s: %d klaim diterima, %d ditolak", insurer.code, name, result.created, result.failed)
    return {"file": name, "status": status, "created": result.created, "failed": result.failed}


def write_status(db, insurer, tenant_dir: Path) -> None:
    from sqlalchemy import select

    from mab_api.models import Claim, ClaimSource
    from mab_api.webhooks import LABEL, claim_status

    claims = db.scalars(select(Claim).where(Claim.insurer_id == insurer.id, Claim.source == ClaimSource.SFTP.value)
                        .order_by(Claim.claim_number))
    rows = []
    for c in claims:
        s = claim_status(c)
        rows.append((s["claim_number"], s["status"], s["triage_status"] or "", s["recommendation"] or "", s["billed_amount"],
                     "" if s["recommended_amount"] is None else s["recommended_amount"], " ".join(s["reason_codes"]),
                     s["signed_by"] or "", s["decision"] or "", s["updated_at"].isoformat() if s["updated_at"] else "", LABEL))
    _write_if_changed(tenant_dir / "keluar" / "status_klaim.csv", _csv_bytes(STATUS_COLUMNS, rows))


def scan_once(session_factory, storage, queue, root: Path, seen: dict | None = None, wait_stable: bool = True) -> list[dict]:
    """Satu putaran: proses ZIP baru di setiap folder tenant, lalu perbarui status_klaim.csv."""
    from sqlalchemy import select

    from mab_api.models import Insurer

    seen = {} if seen is None else seen
    out: list[dict] = []
    now = time.monotonic()
    with session_factory() as db:
        for insurer in db.scalars(select(Insurer).order_by(Insurer.code)):
            tenant_dir = root / insurer.code
            ensure_dirs(tenant_dir)
            for zip_path in sorted((tenant_dir / "masuk").glob("*.zip")) + sorted((tenant_dir / "masuk").glob("*.ZIP")):
                if wait_stable and not _stable(zip_path, seen, now):
                    continue
                seen.pop(zip_path, None)
                out.append({"tenant": insurer.code, **process_zip(db, storage, queue, insurer, zip_path, tenant_dir)})
            write_status(db, insurer, tenant_dir)
    return out


def main() -> None:
    from mab_api.config import get_settings
    from mab_api.db import make_session_factory
    from mab_api.job_queue import RQJobQueue
    from mab_api.storage import S3Storage

    parser = argparse.ArgumentParser(description="Pengawas folder SFTP klaim batch")
    parser.add_argument("--once", action="store_true", help="satu putaran saja (tanpa menunggu unggahan stabil)")
    parser.add_argument("--interval", type=float, default=10.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    s = get_settings()
    root = Path(s.sftp_root)
    session_factory = make_session_factory()
    storage = S3Storage(s.s3_endpoint_url, s.s3_bucket, s.minio_root_user, s.minio_root_password)
    queue = RQJobQueue(s.redis_url, s.rq_queue)
    log.info("Mengawasi %s setiap %.0f detik", root, args.interval)
    if args.once:
        print(scan_once(session_factory, storage, queue, root, wait_stable=False))
        return
    seen: dict = {}
    while True:
        try:
            scan_once(session_factory, storage, queue, root, seen)
        except Exception:  # satu putaran gagal (mis. database restart) tidak boleh menghentikan pengawas
            log.exception("Putaran SFTP gagal")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
