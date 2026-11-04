"""Pra-pemrosesan gambar halaman pindaian sebelum OCR: kontras, denoise, deskew."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps

MAX_SKEW_DEG = 4.0
SKEW_STEP_DEG = 0.25


def estimate_skew(gray: Image.Image) -> float:
    """Perkirakan sudut miring (derajat) dengan profil proyeksi horizontal.

    Teks yang lurus menghasilkan profil baris yang paling "tajam" (varian
    selisih antarbaris paling besar). Dicoba pada gambar yang diperkecil.
    """
    small = gray.copy()
    small.thumbnail((800, 800))
    arr = np.asarray(small, dtype=np.uint8)
    ink = Image.fromarray(((arr < 160) * 255).astype(np.uint8))
    best_angle, best_score = 0.0, -1.0
    angle = -MAX_SKEW_DEG
    while angle <= MAX_SKEW_DEG + 1e-9:
        rotated = np.asarray(ink.rotate(angle, resample=Image.NEAREST, fillcolor=0), dtype=np.float32)
        profile = rotated.sum(axis=1)
        score = float(np.square(np.diff(profile)).sum())
        if score > best_score:
            best_angle, best_score = angle, score
        angle += SKEW_STEP_DEG
    return round(best_angle, 2)


def preprocess(image: Image.Image) -> tuple[Image.Image, float]:
    """Kembalikan (gambar RGB siap OCR, sudut koreksi yang dipakai)."""
    gray = ImageOps.grayscale(image)
    gray = gray.filter(ImageFilter.MedianFilter(3))       # buang noise bintik
    gray = ImageOps.autocontrast(gray, cutoff=1)          # perbaiki kontras pudar
    angle = estimate_skew(gray)
    if angle:
        gray = gray.rotate(angle, resample=Image.BICUBIC, expand=False, fillcolor=255)
    return gray.convert("RGB"), angle
