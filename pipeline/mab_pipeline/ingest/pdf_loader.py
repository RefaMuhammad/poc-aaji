"""Baca dokumen klaim (PDF digital, PDF pindaian, JPG/PNG) menjadi baris teks berlokasi.

- Halaman PDF yang punya lapisan teks (>= MIN_DIGITAL_CHARS karakter) dibaca dengan
  pdfplumber: teks + koordinat, keyakinan 1.0. Teks miring (watermark, stempel) dibuang.
- Halaman tanpa teks dianggap pindaian: dirender 200 DPI, dipra-proses, lalu OCR.
- Bbox disimpan dalam proporsi halaman (0-1) agar bisa disorot di penampil dokumen.
"""
from __future__ import annotations

import io
import logging

import pdfplumber
from PIL import Image

from mab_pipeline.documents import LoadedDocument, PageContent, TextLine
from mab_pipeline.ingest.image_preprocess import preprocess
from mab_pipeline.ocr.engine import NullOCREngine, OcrEngine, OcrLine

log = logging.getLogger(__name__)

RENDER_DPI = 200
MIN_DIGITAL_CHARS = 20
_ROTATION_TOLERANCE = 0.01


def _is_upright_char(obj: dict) -> bool:
    if obj.get("object_type") != "char":
        return True
    a, b, c, d, *_ = obj.get("matrix") or (1, 0, 0, 1)
    return abs(b) < _ROTATION_TOLERANCE and abs(c) < _ROTATION_TOLERANCE


def _line_id(prefix: str, page: int, n: int) -> str:
    return f"{prefix}-P{page}-L{n}"


def _digital_page(page, number: int, document_id: str, prefix: str) -> PageContent:
    clean = page.filter(_is_upright_char)
    w, h = float(page.width), float(page.height)
    lines = []
    for raw in clean.extract_text_lines(strip=True):
        text = " ".join(raw["text"].split())
        if not text:
            continue
        lines.append(
            TextLine(
                id=_line_id(prefix, number, len(lines) + 1),
                document_id=document_id,
                page=number,
                text=text,
                bbox=(round(raw["x0"] / w, 4), round(raw["top"] / h, 4), round(raw["x1"] / w, 4), round(raw["bottom"] / h, 4)),
                confidence=1.0,
            )
        )
    return PageContent(page=number, mode="digital", lines=lines)


def group_rows(boxes: list[OcrLine]) -> list[OcrLine]:
    """Gabungkan kotak OCR yang berada di baris visual yang sama, urut kiri ke kanan."""
    rows: list[list[OcrLine]] = []
    for box in sorted(boxes, key=lambda b: (b.bbox[1] + b.bbox[3]) / 2):
        cy = (box.bbox[1] + box.bbox[3]) / 2
        if rows:
            last = rows[-1]
            top = min(b.bbox[1] for b in last)
            bottom = max(b.bbox[3] for b in last)
            height = bottom - top
            if top + 0.25 * height <= cy <= bottom - 0.25 * height:
                last.append(box)
                continue
        rows.append([box])
    merged = []
    for row in rows:
        row.sort(key=lambda b: b.bbox[0])
        merged.append(
            OcrLine(
                text=" ".join(b.text.strip() for b in row if b.text.strip()),
                bbox=(min(b.bbox[0] for b in row), min(b.bbox[1] for b in row), max(b.bbox[2] for b in row), max(b.bbox[3] for b in row)),
                confidence=min(b.confidence for b in row),
            )
        )
    return [m for m in merged if m.text]


def _ocr_image(image: Image.Image, number: int, document_id: str, prefix: str, ocr: OcrEngine) -> PageContent:
    if not ocr.available():
        return PageContent(page=number, mode="ocr_unavailable", lines=[])
    clean, angle = preprocess(image)
    w, h = clean.size
    lines = []
    for row in group_rows(ocr.read(clean)):
        x0, y0, x1, y1 = row.bbox
        lines.append(
            TextLine(
                id=_line_id(prefix, number, len(lines) + 1),
                document_id=document_id,
                page=number,
                text=row.text,
                bbox=(round(x0 / w, 4), round(y0 / h, 4), round(x1 / w, 4), round(y1 / h, 4)),
                confidence=round(row.confidence, 3),
            )
        )
    log.info("OCR halaman %s: %s baris (koreksi miring %s°)", number, len(lines), angle)
    return PageContent(page=number, mode="ocr", lines=lines)


def render_pdf_pages(data: bytes, dpi: int = RENDER_DPI) -> list[Image.Image]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        return [pdf[i].render(scale=dpi / 72).to_pil() for i in range(len(pdf))]
    finally:
        pdf.close()


def load_document(
    document_id: str,
    data: bytes,
    content_type: str,
    filename: str = "",
    ocr: OcrEngine | None = None,
    prefix: str = "D1",
) -> LoadedDocument:
    ocr = ocr or NullOCREngine()
    pages: list[PageContent] = []
    if content_type == "application/pdf" or data[:5] == b"%PDF-":
        rendered: list[Image.Image] | None = None
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                chars = [c for c in page.chars if _is_upright_char(c) and c["text"].strip()]
                if len(chars) >= MIN_DIGITAL_CHARS:
                    pages.append(_digital_page(page, i, document_id, prefix))
                    continue
                if rendered is None:
                    rendered = render_pdf_pages(data)
                pages.append(_ocr_image(rendered[i - 1], i, document_id, prefix, ocr))
    else:
        image = Image.open(io.BytesIO(data))
        image.load()
        pages.append(_ocr_image(image, 1, document_id, prefix, ocr))
    return LoadedDocument(document_id=document_id, filename=filename, pages=pages, prefix=prefix)
