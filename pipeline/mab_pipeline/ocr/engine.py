"""Mesin OCR. PaddleOCR dipakai bila terpasang (image worker); bila tidak, NullOCREngine.

Keluaran: daftar baris teks dengan bbox piksel dan skor keyakinan.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)


@dataclass
class OcrLine:
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 dalam piksel
    confidence: float


class OcrEngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def read(self, image: Image.Image) -> list[OcrLine]: ...


class NullOCREngine:
    """Dipakai bila PaddleOCR tidak terpasang. Halaman pindaian ditandai 'ocr_unavailable'."""

    name = "none"

    def available(self) -> bool:
        return False

    def read(self, image: Image.Image) -> list[OcrLine]:
        return []


class PaddleOCREngine:
    """PaddleOCR 2.x. Model dimuat sekali (lazy) per proses worker."""

    name = "paddleocr"

    def __init__(self, lang: str | None = None):
        self.lang = lang or os.getenv("OCR_LANG", "latin")
        self._ocr = None

    def available(self) -> bool:
        try:
            import paddleocr  # noqa: F401
        except ImportError:
            return False
        return True

    def _engine(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(use_angle_cls=True, lang=self.lang, show_log=False)
        return self._ocr

    def read(self, image: Image.Image) -> list[OcrLine]:
        result = self._engine().ocr(np.asarray(image.convert("RGB"))[:, :, ::-1], cls=True)
        lines: list[OcrLine] = []
        for page in result or []:
            for box, (text, score) in page or []:
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                lines.append(OcrLine(text=text, bbox=(min(xs), min(ys), max(xs), max(ys)), confidence=float(score)))
        return lines


_ENGINE: OcrEngine | None = None


def get_ocr_engine() -> OcrEngine:
    """OCR_ENGINE=paddle (bawaan) | none."""
    global _ENGINE
    if _ENGINE is None:
        choice = os.getenv("OCR_ENGINE", "paddle").lower()
        engine: OcrEngine = PaddleOCREngine() if choice == "paddle" else NullOCREngine()
        if not engine.available():
            log.warning("PaddleOCR tidak terpasang; halaman pindaian tidak bisa dibaca")
            engine = NullOCREngine()
        _ENGINE = engine
    return _ENGINE
