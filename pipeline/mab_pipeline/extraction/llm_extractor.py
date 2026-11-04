"""Ekstraksi fakta dokumen dengan LLM.

Per dokumen: teks bernomor + prompt berversi dikirim ke LLM, jawaban JSON
divalidasi dengan Pydantic. Gagal validasi -> diulang sekali dengan pesan
kesalahannya; gagal lagi -> dokumen ditandai 'failed' dan faktanya kosong.
Id baris yang tidak ada di dokumen dibuang; nilai tanpa bukti dicatat sebagai peringatan.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ValidationError

from mab_pipeline.documents import DOC_TYPES, LoadedDocument
from mab_pipeline.extraction.facts import BillingFacts, ClaimFacts, CpptFacts, Fact, LabFacts, ResumeFacts
from mab_pipeline.llm.client import LLMClient, parse_json

log = logging.getLogger(__name__)

PROMPT_VERSION = "extract_v1"
PROMPTS_DIR = Path(__file__).with_name("prompts")

EXTRACT_MODELS: dict[str, type[BaseModel]] = {
    "resume_medis": ResumeFacts,
    "hasil_laboratorium": LabFacts,
    "rincian_tagihan": BillingFacts,
    "cppt": CpptFacts,
}


@lru_cache
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def system_prompt(doc_type: str) -> str:
    return load_prompt("_common_v1") + "\n\n" + load_prompt(f"extract_{doc_type}_v1")


@dataclass
class ExtractionOutcome:
    document_id: str
    doc_type: str
    status: str                       # ok | retried | failed | skipped
    facts: BaseModel | None = None
    warnings: list[str] = field(default_factory=list)
    attempts: int = 0


def _evidence_holders(obj: BaseModel, path: str = ""):
    """Semua objek yang punya source_line_ids (Fact, LabResult, BillingItem, ...)."""
    if hasattr(obj, "source_line_ids"):
        yield path, obj
    for name in type(obj).model_fields:
        value = getattr(obj, name)
        sub = f"{path}.{name}" if path else name
        if isinstance(value, BaseModel):
            yield from _evidence_holders(value, sub)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, BaseModel):
                    yield from _evidence_holders(item, f"{sub}[{i}]")


def sanitize_evidence(facts: BaseModel, valid_ids: set[str]) -> list[str]:
    warnings: list[str] = []
    for path, holder in _evidence_holders(facts):
        unknown = [i for i in holder.source_line_ids if i not in valid_ids]
        if unknown:
            warnings.append(f"{path}: id baris tidak dikenal dibuang ({', '.join(unknown[:3])})")
            holder.source_line_ids = [i for i in holder.source_line_ids if i in valid_ids]
        value = holder.value if isinstance(holder, Fact) else getattr(holder, "value", getattr(holder, "name", None))
        if value not in (None, [], "") and not holder.source_line_ids:
            warnings.append(f"{path}: nilai tanpa bukti lokasi")
    return warnings


def extract_document(llm: LLMClient, doc: LoadedDocument, claim_number: str | None = None) -> ExtractionOutcome:
    model = EXTRACT_MODELS.get(doc.doc_type)
    if model is None:
        return ExtractionOutcome(doc.document_id, doc.doc_type, "skipped")
    if not doc.lines:
        return ExtractionOutcome(doc.document_id, doc.doc_type, "failed", warnings=["dokumen tidak punya teks yang terbaca"])
    system = system_prompt(doc.doc_type)
    user = f"Dokumen ({doc.doc_type}):\n{doc.numbered_text()}"
    context = {"claim_number": claim_number, "lines": [{"id": l.id, "text": l.text} for l in doc.lines]}
    error = ""
    for attempt in (1, 2):
        prompt = user if not error else (
            f"{user}\n\nJawaban Anda sebelumnya tidak valid:\n{error}\nPerbaiki dan kirim ulang JSON lengkap."
        )
        raw = llm.complete_json(system, prompt, task=f"extract:{doc.doc_type}", context=context)
        try:
            facts = model.model_validate(parse_json(raw))
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            error = str(exc)[:2000]
            log.warning("Ekstraksi %s (%s) tidak valid, percobaan %s", doc.document_id, doc.doc_type, attempt)
            continue
        warnings = sanitize_evidence(facts, {l.id for l in doc.lines})
        return ExtractionOutcome(doc.document_id, doc.doc_type, "ok" if attempt == 1 else "retried", facts, warnings, attempt)
    return ExtractionOutcome(doc.document_id, doc.doc_type, "failed", warnings=[f"jawaban LLM tidak valid 2 kali: {error[:300]}"], attempts=2)


def merge_facts(outcomes: list[ExtractionOutcome], documents_present: list[str]) -> ClaimFacts:
    """Gabungkan fakta per dokumen. Jenis dokumen yang ada tapi gagal diekstrak tetap
    dianggap ada, dengan fakta kosong."""
    claim = ClaimFacts(documents_present=sorted(set(documents_present)))
    for o in outcomes:
        if o.doc_type == "resume_medis":
            if claim.resume is None:
                claim.resume = o.facts or ResumeFacts()
            elif o.facts is not None:  # resume kedua: isi yang masih kosong saja
                for name in ResumeFacts.model_fields:
                    if getattr(claim.resume, name).value in (None, []):
                        setattr(claim.resume, name, getattr(o.facts, name))
        elif o.doc_type == "hasil_laboratorium":
            claim.labs = claim.labs or LabFacts()
            claim.labs.results += o.facts.results if o.facts else []
        elif o.doc_type == "rincian_tagihan":
            claim.billing = claim.billing or BillingFacts()
            claim.billing.items += o.facts.items if o.facts else []
        elif o.doc_type == "cppt":
            claim.cppt = claim.cppt or CpptFacts()
            claim.cppt.medications += o.facts.medications if o.facts else []
    return claim


def classify_with_llm(llm: LLMClient, doc: LoadedDocument) -> str:
    head = "\n".join(l.text for l in doc.lines[:40])
    raw = llm.complete_json(
        load_prompt("classify_v1"), f"Awal dokumen:\n{head}", task="classify",
        context={"lines": [{"id": l.id, "text": l.text} for l in doc.lines[:40]]},
    )
    try:
        found = parse_json(raw).get("doc_type", "unknown")
    except (ValueError, AttributeError):
        return "unknown"
    return found if found in DOC_TYPES else "unknown"
