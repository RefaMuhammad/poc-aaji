"""Kenali jenis dokumen: aturan kata kunci dulu, LLM sebagai cadangan."""
from __future__ import annotations

import re
import unicodedata

from mab_pipeline.documents import DOC_TYPES, LoadedDocument

# Judul khas di bagian atas dokumen. Dicek pada 15 baris pertama tiap dokumen.
TITLE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "resume_medis": ("resume medis", "ringkasan pulang", "discharge summary", "resume pasien pulang"),
    "hasil_laboratorium": ("hasil pemeriksaan laboratorium", "hasil laboratorium", "laporan hasil lab"),
    "cppt": ("cppt", "catatan perkembangan pasien", "catatan terintegrasi"),
    "rincian_tagihan": ("rincian tagihan", "rincian biaya", "kuitansi perawatan", "billing"),
    "laporan_operasi": ("laporan operasi",),
    "resep": ("resep",),
}
HEAD_LINES = 15


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9/ ]", " ", text)).strip()


def classify_by_keywords(doc: LoadedDocument) -> str | None:
    head = normalize(" ".join(line.text for line in doc.lines[:HEAD_LINES]))
    hits = [t for t, words in TITLE_KEYWORDS.items() if any(w in head for w in words)]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        # pilih kata kunci yang muncul paling awal (judul biasanya di atas)
        return min(hits, key=lambda t: min(head.find(w) for w in TITLE_KEYWORDS[t] if w in head))
    return None


def classify(doc: LoadedDocument, llm=None, hint: str | None = None) -> tuple[str, str]:
    """Kembalikan (jenis_dokumen, metode) dengan metode 'keyword' | 'llm' | 'filename' | 'none'.

    `hint` adalah tebakan dari nama file saat unggah; dipakai terakhir, mis. bila
    halaman pindaian tidak bisa dibaca.
    """
    found = classify_by_keywords(doc)
    if found:
        return found, "keyword"
    if llm is not None and doc.lines:
        from mab_pipeline.extraction.llm_extractor import classify_with_llm

        found = classify_with_llm(llm, doc)
        if found in DOC_TYPES and found != "unknown":
            return found, "llm"
    if hint in DOC_TYPES and hint != "unknown":
        return hint, "filename"
    return "unknown", "none"


def title_line(doc: LoadedDocument):
    """Baris judul dokumen (dipakai sebagai bukti bahwa dokumen jenis ini diterima)."""
    words = TITLE_KEYWORDS.get(doc.doc_type, ())
    for line in doc.lines[:HEAD_LINES]:
        if any(w in normalize(line.text) for w in words):
            return line
    return doc.lines[0] if doc.lines else None
