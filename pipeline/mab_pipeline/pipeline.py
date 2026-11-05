"""Alur baca dokumen satu klaim, tanpa database: ingest -> OCR -> klasifikasi -> ekstraksi -> field turunan.

Dipakai job worker (tasks.py) dan skrip evaluasi akurasi.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mab_pipeline.documents import LoadedDocument, TextLine
from mab_pipeline.extraction.derived_fields import DEFAULT_REQUIRED_DOCS, DerivedValue, derive
from mab_pipeline.extraction.facts import ClaimFacts
from mab_pipeline.extraction.llm_extractor import PROMPT_VERSION, ExtractionOutcome, extract_document, merge_facts
from mab_pipeline.ingest.doc_classifier import classify
from mab_pipeline.ingest.pdf_loader import load_document
from mab_pipeline.llm.client import LLMClient
from mab_pipeline.ocr.engine import OcrEngine

if TYPE_CHECKING:  # pragma: no cover
    from mab_pipeline.benefit import BenefitResult

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


# ----------------------------------------------------------------------------- M5: penilaian


@dataclass
class FieldValue:
    path: str
    value: object
    source: str                 # dokumen | hitung | ai
    evidence: list[dict] = field(default_factory=list)
    confidence: float | None = None
    status: str | None = None   # khusus ai: verified | absent | unverified | unknown


@dataclass
class Assessment:
    fields: dict[str, FieldValue]
    reasoning: "ReasoningResult"
    triage: "TriageResult"
    recommendation: "RecommendationDraft"
    model_version: str
    prompt_version: str
    ruleset_version: str
    benefit: "BenefitResult | None" = None

    @property
    def benefit_ruleset_version(self) -> str | None:
        return self.benefit.version if self.benefit else None


def line_evidence(line_ids: list[str], lines: dict[str, TextLine], field_path: str) -> tuple[list[dict], float | None]:
    out, conf = [], []
    for line_id in line_ids:
        line = lines.get(line_id)
        if line is None:
            continue
        out.append({"doc": line.document_id, "page": line.page, "bbox": list(line.bbox), "quote": line.text,
                    "line_ids": [line.id], "field": field_path})
        conf.append(line.confidence)
    return out, (round(min(conf), 3) if conf else None)


def assess_claim(
    read: ReadResult,
    ruleset,
    llm: LLMClient,
    billed_amount: int,
    claim_number: str | None = None,
    overlapping: list[dict] | None = None,
    benefit_ruleset=None,
    policy=None,
    admission_date=None,
) -> Assessment:
    """Penalaran klinis -> aturan -> rekomendasi, dari hasil baca dokumen.

    U2: bila `benefit_ruleset` diberikan, aturan benefit dinilai terhadap `policy` (PolicyInfo atau
    None = polis tidak ditemukan). Temuannya digabung dengan temuan klinis sebelum triase.
    """
    from mab_pipeline.ingest.doc_classifier import title_line
    from mab_pipeline.reasoning.clinical_reasoner import PROMPT_VERSION as REASON_PROMPT
    from mab_pipeline.reasoning.clinical_reasoner import reason
    from mab_pipeline.rules import run_rules
    from mab_pipeline.schemas import ClaimData
    from mab_pipeline.triage.recommender import build_recommendation

    lines = read.line_index()
    fields: dict[str, FieldValue] = {}
    for path, dv in read.derived.items():
        evidence, conf = line_evidence(dv.line_ids, lines, path)
        fields[path] = FieldValue(path, dv.value, dv.source, evidence, conf)
    # bukti dokumen yang diterima, untuk temuan "dokumen tidak lengkap"
    titles = [t for t in (title_line(d) for d in read.documents if d.doc_type != "unknown") if t is not None]
    fields["docs.missing"].evidence = line_evidence([t.id for t in titles], lines, "docs.missing")[0]
    overlapping = overlapping or []
    fields["history.overlapping_claims"] = FieldValue(
        "history.overlapping_claims", len(overlapping), "hitung",
        [{**o, "field": "history.overlapping_claims"} for o in overlapping])

    primary = read.derived["dx.primary"].value
    reasoning = reason(llm, read.documents, ruleset, primary, claim_number)
    ai_items: dict[str, list[str]] = {}
    for path, f in reasoning.fields.items():
        fields[path] = FieldValue(path, f.value, "ai", f.evidence, f.confidence, f.status)
        if f.items:
            ai_items[path] = f.items

    nested: dict[str, dict] = {}
    for path, fv in fields.items():
        group, name = path.split(".", 1)
        nested.setdefault(group, {})[name] = fv.value
    claim = ClaimData.model_validate({**nested, "claim_id": claim_number})
    triage = run_rules(ruleset, claim)

    benefit = None
    extra_adjustments = None
    if benefit_ruleset is not None:
        from mab_pipeline.benefit import benefit_adjustments, build_facts, run_benefit_rules

        items = read.facts.billing.items if read.facts.billing is not None else []
        billing_ev = {lid: line_evidence([lid], lines, "benefit.room_rate_billed")[0]
                      for it in items for lid in it.source_line_ids}
        dx_codes = [c for c in [primary, *(claim.dx.secondary or [])] if c]
        facts = build_facts(policy, admission_date, dx_codes, billed_amount, items, billing_ev)
        benefit = run_benefit_rules(benefit_ruleset, facts)
        triage = triage.model_copy(update={"findings": [*triage.findings, *benefit.findings]})
        for path, value in facts.values.items():
            fields[path] = FieldValue(path, value, "polis", facts.evidence.get(path, []))

        def extra_adjustments(prior: int) -> list[dict]:
            return benefit_adjustments(benefit, items, billed_amount, prior)

    quality: list[str] = []
    unreadable = [d for d in read.documents if not d.lines]
    if unreadable or any(o.status == "failed" for o in read.outcomes) or any("tidak bisa dibaca" in w for w in read.warnings):
        quality.append("DOC_UNREADABLE")
    if not primary:
        quality.append("DX_UNKNOWN")
    if reasoning.status == "failed":
        quality.append("AI_FAILED")
    if reasoning.unverified:
        quality.append("AI_UNVERIFIED")

    draft = build_recommendation(
        triage, claim, ruleset, {p: fv.evidence for p, fv in fields.items()}, billed_amount,
        billing=read.facts.billing, ai_items=ai_items, quality=quality, extra_adjustments=extra_adjustments,
    )
    return Assessment(
        fields=fields,
        reasoning=reasoning,
        triage=triage,
        recommendation=draft,
        model_version=read.model_version,
        prompt_version=f"{read.prompt_version}+{REASON_PROMPT}",
        ruleset_version=ruleset.version,
        benefit=benefit,
    )
