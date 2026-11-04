"""Cek bukti: kutipan dari LLM harus benar-benar ada di teks dokumen klaim.

Kutipan dicocokkan (fuzzy, toleran terhadap salah ketik OCR dan spasi) dengan
setiap baris dan gabungan 2-3 baris berturutan dalam satu dokumen. Skor >= 0,9
dianggap ditemukan. Kutipan yang tidak ditemukan dibuang; nilai yang bergantung
padanya dianggap tidak diketahui (null), bukan "tidak ada".
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

from mab_pipeline.documents import LoadedDocument, TextLine

MATCH_THRESHOLD = 0.9
MIN_QUOTE_CHARS = 6
MAX_WINDOW_LINES = 3


@dataclass
class EvidenceMatch:
    quote: str                 # kutipan dari LLM
    score: float               # 0-1
    lines: list[TextLine]      # baris dokumen tempat kutipan ditemukan

    def to_evidence(self, field: str | None = None) -> list[dict]:
        """Satu entri bukti per halaman: {doc, page, bbox, quote, line_ids, field}."""
        out: list[dict] = []
        for line in self.lines:
            if out and out[-1]["doc"] == line.document_id and out[-1]["page"] == line.page:
                x0, y0, x1, y1 = out[-1]["bbox"]
                lx0, ly0, lx1, ly1 = line.bbox
                out[-1]["bbox"] = [min(x0, lx0), min(y0, ly0), max(x1, lx1), max(y1, ly1)]
                out[-1]["line_ids"].append(line.id)
                continue
            out.append({"doc": line.document_id, "page": line.page, "bbox": list(line.bbox), "quote": self.quote,
                        "line_ids": [line.id], "field": field})
        return out


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).lower()
    return re.sub(r"[^a-z0-9]", "", text)


class EvidenceIndex:
    """Indeks teks semua dokumen satu klaim untuk pencocokan kutipan."""

    def __init__(self, documents: list[LoadedDocument]):
        self.windows: list[tuple[str, list[TextLine]]] = []
        for doc in documents:
            lines = doc.lines
            for i in range(len(lines)):
                for size in range(1, MAX_WINDOW_LINES + 1):
                    chunk = lines[i:i + size]
                    if len(chunk) < size:
                        break
                    self.windows.append((normalize(" ".join(l.text for l in chunk)), chunk))

    def find(self, quote: str, threshold: float = MATCH_THRESHOLD) -> EvidenceMatch | None:
        target = normalize(quote or "")
        if len(target) < MIN_QUOTE_CHARS:
            return None
        best: tuple[float, int, list[TextLine]] | None = None
        cutoff = threshold * 100
        for text, lines in self.windows:
            if len(text) < len(target) * 0.9:
                continue
            score = fuzz.partial_ratio(target, text, score_cutoff=cutoff)
            # skor sama: pilih jendela terpendek (paling tepat)
            if score and (best is None or score > best[0] or (score == best[0] and len(lines) < len(best[2]))):
                best = (score, len(lines), lines)
                if score == 100 and len(lines) == 1:
                    break
        if best is None:
            return None
        return EvidenceMatch(quote=quote, score=round(best[0] / 100, 3), lines=list(best[2]))
