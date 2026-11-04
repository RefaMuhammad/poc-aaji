"""Struktur dokumen hasil baca: halaman dan baris teks dengan lokasi."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

DOC_TYPES = ("resume_medis", "hasil_laboratorium", "cppt", "rincian_tagihan", "laporan_operasi", "resep", "unknown")


@dataclass
class TextLine:
    id: str                 # unik dalam satu klaim, mis. "D2-P1-L14"
    document_id: str
    page: int               # mulai 1
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 dalam proporsi halaman (0-1)
    confidence: float = 1.0  # 1.0 untuk teks digital, skor OCR untuk pindaian


@dataclass
class PageContent:
    page: int
    mode: str               # "digital" | "ocr" | "ocr_unavailable"
    lines: list[TextLine] = field(default_factory=list)


@dataclass
class LoadedDocument:
    document_id: str
    filename: str
    pages: list[PageContent]
    doc_type: str = "unknown"
    prefix: str = "D1"      # awalan id baris

    @property
    def lines(self) -> list[TextLine]:
        return [line for p in self.pages for line in p.lines]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    def numbered_text(self) -> str:
        """Teks bernomor untuk prompt LLM: '[D1-P1-L3] isi baris'."""
        return "\n".join(f"[{line.id}] {line.text}" for line in self.lines)

    def to_json(self) -> dict:
        return {"document_id": self.document_id, "filename": self.filename, "doc_type": self.doc_type,
                "pages": [{"page": p.page, "mode": p.mode, "lines": [asdict(l) for l in p.lines]} for p in self.pages]}
