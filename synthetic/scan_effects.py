"""Ubah PDF digital menjadi PDF hasil "pindaian" (gambar) untuk klaim terpilih.

Efek: miring 1-3 derajat, blur ringan, noise, kontras sedikit turun, dan
stempel "DITERIMA". Klaim terpilih ditandai "scanned": true di case.json
(dipilih acak dengan seed, sekitar 40%).

Pemakaian: python -m synthetic.scan_effects [folder_output]
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from synthetic.generate_cases import DEFAULT_OUTPUT

DPI = 150


def _stamp(img: Image.Image, rng: random.Random) -> None:
    draw = ImageDraw.Draw(img)
    w, h = img.size
    # di area tanda tangan (kanan bawah) supaya tidak menutup identitas pasien
    x, y = int(w * rng.uniform(0.08, 0.3)), int(h * rng.uniform(0.80, 0.86))
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    draw.rounded_rectangle([x, y, x + 300, y + 90], radius=12, outline=(170, 30, 60), width=5)
    draw.text((x + 22, y + 8), "DITERIMA", fill=(170, 30, 60), font=font)
    draw.text((x + 22, y + 50), "Bag. Klaim (rekaan)", fill=(170, 30, 60), font=font.font_variant(size=20) if hasattr(font, "font_variant") else font)


def scan_page(img: Image.Image, rng: random.Random) -> Image.Image:
    img = img.convert("RGB")
    _stamp(img, rng)
    angle = rng.uniform(1, 3) * rng.choice([-1, 1])
    img = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(245, 245, 240))
    img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.4, 0.9)))
    arr = np.asarray(img).astype(np.int16)
    noise = np.random.default_rng(rng.randint(0, 2**31)).normal(0, rng.uniform(6, 12), arr.shape[:2])[..., None]
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.8, 0.92))
    return img.convert("L")


def scan_pdf(pdf_path: Path, rng: random.Random) -> None:
    doc = pdfium.PdfDocument(str(pdf_path))
    pages = [scan_page(doc[i].render(scale=DPI / 72).to_pil(), rng) for i in range(len(doc))]
    doc.close()
    pages[0].save(pdf_path, save_all=True, append_images=pages[1:], resolution=DPI)


def main(out_dir: Path = DEFAULT_OUTPUT) -> None:
    count = 0
    for case_file in sorted(out_dir.glob("*/case.json")):
        case = json.loads(case_file.read_text(encoding="utf-8"))
        marker = case_file.parent / ".pindaian_selesai"
        if not case.get("scanned") or marker.exists():
            continue  # tidak dipilih, atau sudah dipindai (hindari efek ganda saat dijalankan ulang)
        rng = random.Random(f"scan-{case['claim_id']}")
        for doc_type in case["documents"]:
            scan_pdf(case_file.parent / f"{doc_type}.pdf", rng)
        marker.write_text("1", encoding="utf-8")
        count += 1
    print(f"Efek pindaian diterapkan pada {count} klaim")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT)
