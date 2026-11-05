"""Buat ZIP unggah massal untuk demo (DATA REKAAN): manifest.xlsx + satu folder per klaim.

Bawaan: SYN-DEN-09 (klaim baru) dan SYN-DEN-01 (sudah diunggah seed), supaya hasil unggah
massal menunjukkan satu klaim diterima dan satu ditolak "Nomor klaim ... sudah ada".

Pemakaian (di container api; folder data/ terpasang ke ./data di laptop):
    docker compose exec api python infra/scripts/make_demo_zip.py
    docker compose exec api python infra/scripts/make_demo_zip.py SYN-DEN-09
Hasil: data/demo_upload/unggah_massal_demo.zip
"""
from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from pathlib import Path

from openpyxl import Workbook

DATA = Path(os.environ.get("SEED_DATA_DIR", Path(__file__).resolve().parents[2] / "data" / "synthetic_output"))
OUT = DATA.parent / "demo_upload" / "unggah_massal_demo.zip"
DEFAULT = ["SYN-DEN-09", "SYN-DEN-01"]
COLUMNS = ["folder", "nomor_klaim", "nomor_polis", "id_peserta", "nama_peserta", "nama_rs",
           "tanggal_masuk", "tanggal_keluar", "nilai_tagihan"]


def manifest_row(case: dict) -> list:
    p = case["patient"]
    return [case["claim_id"], case["claim_id"], p["policy_no"], p["member_id"], p["name"],
            case["hospital"]["name"], case["admission_date"], case["discharge_date"], int(case["billing_total"])]


def build(claims: list[str], out: Path = OUT) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "klaim"
    ws.append(COLUMNS)
    buf = io.BytesIO()
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for claim in claims:
            folder = DATA / claim
            if not (folder / "case.json").exists():
                sys.exit(f"Data {claim} tidak ada di {DATA}. Jalankan `docker compose run --rm synthetic` dulu.")
            ws.append(manifest_row(json.loads((folder / "case.json").read_text(encoding="utf-8"))))
            for pdf in sorted(folder.glob("*.pdf")):
                zf.write(pdf, f"{claim}/{pdf.name}")
        wb.save(buf)
        zf.writestr("manifest.xlsx", buf.getvalue())
    return out


if __name__ == "__main__":
    path = build(sys.argv[1:] or DEFAULT)
    print(f"ZIP dibuat: {path}")
    print("Unggah lewat Unggah klaim > Unggah massal (ZIP). File ada di folder data/demo_upload/ di laptop.")
