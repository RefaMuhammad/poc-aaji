"""Alur baca dokumen satu klaim, tanpa database: ingest -> OCR -> klasifikasi -> ekstraksi -> field turunan.

Dipakai job worker (tasks.py) dan skrip evaluasi akurasi.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from mab_pipeline.documents import LoadedDocument, TextLine
from mab_pipeline.extraction.derived_fields import DEFAULT_REQUIRED_DOCS, DerivedValue, derive
from mab_pipeline.extraction.facts import ClaimFacts
from mab_pipeline.extraction.llm_extractor import PROMPT_VERSION, ExtractionOutcome, extract_document, merge_facts
from mab_pipeline.ingest.doc_classifier import classify
from mab_pipeline.ingest.pdf_loader import load_document
from mab_pipeline.llm.client import LLMClient
from mab_pipeline.ocr.engine import OcrEngine

log = logging.getLogger(__name__)


@dataclass
class InputDocument:
    document_id: str
    filename: str
    content_type: str
    data: bytes
    doc_type_hint: str | None = None     # tebakan dari nama file saat unggah


@dataclass
class ReadResult:
    documents: list[LoadedDocument]
    classification: dict[str, str]          # document_id -> metode (keyword/llm/none)
    outcomes: list[ExtractionOutcome]
    facts: ClaimFacts
    derived: dict[str, DerivedValue]
    model_version: str
    prompt_version: str = PROMPT_VERSION
    ocr_engine: str = "none"
    warnings: list[str] = field(default_factory=list)

    def line_index(self) -> dict[str, TextLine]:
        return {line.id: line for doc in self.documents for line in doc.lines}


def read_claim(
    inputs: list[InputDocument],
    llm: LLMClient,
    ocr: OcrEngine,
    claim_number: str | None = None,
    required_docs: tuple[str, ...] = DEFAULT_REQUIRED_DOCS,
) -> ReadResult:
    documents: list[LoadedDocument] = []
    methods: dict[str, str] = {}
    warnings: list[str] = []
    for n, item in enumerate(inputs, start=1):
        try:
            doc = load_document(item.document_id, item.data, item.content_type, item.filename, ocr=ocr, prefix=f"D{n}")
        except Exception as exc:  # file rusak tidak boleh menghentikan klaim
            log.exception("Gagal membaca %s", item.filename)
            warnings.append(f"{item.filename}: tidak bisa dibaca ({type(exc).__name__})")
            continue
        if any(p.mode == "ocr_unavailable" for p in doc.pages):
            warnings.append(f"{item.filename}: halaman pindaian tidak dibaca karena OCR tidak tersedia")
        doc.doc_type, methods[doc.document_id] = classify(doc, llm, item.doc_type_hint)
        documents.append(doc)

    if inputs and not documents:
        raise ValueError("Tidak ada dokumen yang bisa dibuka: " + "; ".join(warnings))

    outcomes = [extract_document(llm, doc, claim_number) for doc in documents]
    for o in outcomes:
        warnings += [f"{o.doc_type} ({o.document_id[:8]}): {w}" for w in o.warnings]
    facts = merge_facts(outcomes, [d.doc_type for d in documents if d.doc_type != "unknown"])
    return ReadResult(
        documents=documents,
        classification=methods,
        outcomes=outcomes,
        facts=facts,
        derived=derive(facts, required_docs),
        model_version=llm.model_version,
        ocr_engine=ocr.name,
        warnings=warnings,
    )
