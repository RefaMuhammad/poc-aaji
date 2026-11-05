"""Alur underwriting satu pengajuan, tanpa database:
ingest -> OCR -> klasifikasi -> ekstraksi LLM -> field data -> aturan YAML -> draf rekomendasi.

Dipakai job worker (mab_pipeline.tasks.process_underwriting) dan evaluasi akurasi
(evaluation/underwriting_eval.py).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from mab_pipeline.documents import LoadedDocument
from mab_pipeline.extraction.llm_extractor import ExtractionOutcome, sanitize_evidence
from mab_pipeline.ingest.doc_classifier import HEAD_LINES, normalize
from mab_pipeline.ingest.pdf_loader import load_document
from mab_pipeline.llm.client import LLMClient, parse_json
from mab_pipeline.ocr.engine import OcrEngine
from mab_pipeline.pipeline import InputDocument
from mab_pipeline.underwriting.constants import QUESTION_FIELDS, UW_DOC_TYPES, UW_TITLE_KEYWORDS
from mab_pipeline.underwriting.facts import UW_EXTRACT_MODELS
from mab_pipeline.underwriting.rules import UwOutcome, UwRuleset, apply_rules

log = logging.getLogger(__name__)

UW_PROMPT_VERSION = "uw_extract_v1"
PROMPTS_DIR = Path(__file__).with_name("prompts")
# Urutan ekstraksi: SPAJ dulu supaya nomor SPAJ bisa dipakai sebagai petunjuk dokumen lain
_ORDER = {t: i for i, t in enumerate(("spaj", "kuesioner_kesehatan", "hasil_mcu", "hasil_lab_uw", "surat_dokter"))}

__all__ = ["InputDocument", "UwResult", "assess_application"]


@lru_cache
def _prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


# ----------------------------------------------------------------------------- klasifikasi


def classify_uw(doc: LoadedDocument, llm: LLMClient | None = None, hint: str | None = None) -> tuple[str, str]:
    head = normalize(" ".join(line.text for line in doc.lines[:HEAD_LINES]))
    hits = [t for t, words in UW_TITLE_KEYWORDS.items() if any(w in head for w in words)]
    if hits:
        return min(hits, key=lambda t: min(head.find(w) for w in UW_TITLE_KEYWORDS[t] if w in head)), "keyword"
    if llm is not None and doc.lines:
        raw = llm.complete_json(_prompt("classify_uw_v1"), "Awal dokumen:\n" + "\n".join(l.text for l in doc.lines[:40]),
                                task="uw_classify", context={"lines": [{"id": l.id, "text": l.text} for l in doc.lines[:40]]})
        try:
            found = parse_json(raw).get("doc_type", "unknown")
        except (ValueError, AttributeError):
            found = "unknown"
        if found in UW_DOC_TYPES and found != "unknown":
            return found, "llm"
    if hint in UW_DOC_TYPES and hint != "unknown":
        return hint, "filename"
    return "unknown", "none"


def guess_uw_doc_type(filename: str) -> str:
    name = filename.lower()
    for key, doc_type in (("spaj", "spaj"), ("kuesioner", "kuesioner_kesehatan"), ("mcu", "hasil_mcu"),
                          ("lab", "hasil_lab_uw"), ("surat", "surat_dokter"), ("dokter", "surat_dokter")):
        if key in name:
            return doc_type
    return "unknown"


# ----------------------------------------------------------------------------- ekstraksi


def extract_uw_document(llm: LLMClient, doc: LoadedDocument, hint: str | None = None) -> ExtractionOutcome:
    model = UW_EXTRACT_MODELS.get(doc.doc_type)
    if model is None:
        return ExtractionOutcome(doc.document_id, doc.doc_type, "skipped")
    if not doc.lines:
        return ExtractionOutcome(doc.document_id, doc.doc_type, "failed", warnings=["dokumen tidak punya teks yang terbaca"])
    system = _prompt("_common_uw_v1") + "\n\n" + _prompt(f"extract_{doc.doc_type}_v1")
    user = f"Dokumen ({doc.doc_type}):\n{doc.numbered_text()}"
    context = {"spaj_hint": hint, "lines": [{"id": l.id, "text": l.text} for l in doc.lines]}
    error = ""
    for attempt in (1, 2):
        prompt = user if not error else f"{user}\n\nJawaban Anda sebelumnya tidak valid:\n{error}\nPerbaiki dan kirim ulang JSON lengkap."
        raw = llm.complete_json(system, prompt, task=f"uw_extract:{doc.doc_type}", context=context)
        try:
            facts = model.model_validate(parse_json(raw))
        except (ValidationError, json.JSONDecodeError, ValueError) as exc:
            error = str(exc)[:2000]
            log.warning("Ekstraksi underwriting %s (%s) tidak valid, percobaan %s", doc.document_id, doc.doc_type, attempt)
            continue
        warnings = sanitize_evidence(facts, {l.id for l in doc.lines})
        return ExtractionOutcome(doc.document_id, doc.doc_type, "ok" if attempt == 1 else "retried", facts, warnings, attempt)
    return ExtractionOutcome(doc.document_id, doc.doc_type, "failed", warnings=[f"jawaban LLM tidak valid 2 kali: {error[:300]}"], attempts=2)


# ----------------------------------------------------------------------------- field data


def _f(value: Any, line_ids: list[str] | None = None, source: str = "dokumen") -> dict:
    return {"value": value, "line_ids": list(dict.fromkeys(line_ids or [])), "source": source}


def _first(outcomes: list[ExtractionOutcome], doc_type: str) -> BaseModel | None:
    return next((o.facts for o in outcomes if o.doc_type == doc_type and o.facts is not None), None)


def _age(birth: date, on: date) -> int:
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def build_fields(outcomes: list[ExtractionOutcome], documents_present: set[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    """(field kamus data untuk aturan, profil pengajuan untuk tampilan)."""
    fields: dict[str, dict] = {}
    profile: dict[str, dict] = {}
    spaj = _first(outcomes, "spaj")
    if spaj is not None:
        for name in ("spaj_number", "applicant_name", "sex", "birth_date", "occupation", "product", "sum_assured",
                     "base_premium", "spaj_date"):
            fact = getattr(spaj, name)
            value = fact.value.isoformat() if isinstance(fact.value, date) else fact.value
            profile[name] = _f(value, fact.source_line_ids)
        fields["applicant.sex"] = _f(spaj.sex.value, spaj.sex.source_line_ids)
        if spaj.birth_date.value and spaj.spaj_date.value:
            fields["applicant.age"] = _f(_age(spaj.birth_date.value, spaj.spaj_date.value),
                                         spaj.birth_date.source_line_ids + spaj.spaj_date.source_line_ids, "hitung")

    q = _first(outcomes, "kuesioner_kesehatan")
    if q is not None:
        for ans in q.answers:
            name = QUESTION_FIELDS[ans.code]
            path = "applicant.smoker" if name == "smoker" else f"history.{name}"
            if path not in fields or fields[path]["value"] is None:
                fields[path] = _f(ans.value, ans.source_line_ids)
                if ans.detail:
                    fields[path]["detail"] = ans.detail

    mcu = _first(outcomes, "hasil_mcu")
    if mcu is not None:
        for name in ("height_cm", "weight_kg", "systolic", "diastolic", "ecg"):
            fact = getattr(mcu, name)
            fields[f"vital.{name}"] = _f(fact.value, fact.source_line_ids)
        h, w = mcu.height_cm.value, mcu.weight_kg.value
        if h and w:
            fields["vital.bmi"] = _f(round(w / (h / 100) ** 2, 1), mcu.height_cm.source_line_ids + mcu.weight_kg.source_line_ids, "hitung")
        if mcu.exam_date.value:
            profile["exam_date"] = _f(mcu.exam_date.value.isoformat(), mcu.exam_date.source_line_ids)

    lab = _first(outcomes, "hasil_lab_uw")
    if lab is not None:
        for r in lab.results:
            if r.test == "other" or f"lab.{r.test}" in fields:
                continue
            value = r.value
            if r.test in ("hbsag", "urine_protein") and isinstance(value, str):
                value = value.strip().lower()
                if r.test == "hbsag":
                    value = "pos" if value in ("pos", "positif", "reaktif") else "neg" if value in ("neg", "negatif", "non-reaktif") else value
            elif isinstance(value, str):
                try:
                    value = float(value.replace(",", "."))
                except ValueError:
                    value = None
            fields[f"lab.{r.test}"] = _f(value, r.source_line_ids)

    letter = _first(outcomes, "surat_dokter")
    letter_present = "surat_dokter" in documents_present
    fields["doctor.letter"] = _f(letter_present, [], "hitung")
    if letter is not None:
        fields["doctor.controlled"] = _f(letter.controlled.value, letter.controlled.source_line_ids)
        for name in ("diagnosis", "since_year", "treatment", "doctor"):
            fact = getattr(letter, name)
            profile[f"letter_{name}"] = _f(fact.value, fact.source_line_ids)
    return fields, profile


# ----------------------------------------------------------------------------- hasil


@dataclass
class UwResult:
    documents: list[LoadedDocument]
    classification: dict[str, str]
    outcomes: list[ExtractionOutcome]
    fields: dict[str, dict]
    profile: dict[str, dict]
    outcome: UwOutcome
    rules_version: str
    model_version: str
    prompt_version: str = UW_PROMPT_VERSION
    warnings: list[str] = field(default_factory=list)

    def line_index(self) -> dict[str, dict]:
        """id baris -> {document_id, doc_type, page, text, bbox} untuk bukti."""
        return {l.id: {"document_id": d.document_id, "doc_type": d.doc_type, "page": l.page, "text": l.text,
                       "bbox": list(l.bbox)}
                for d in self.documents for l in d.lines}

    def evidence(self) -> dict[str, dict]:
        """Hanya baris yang dirujuk field atau temuan (disimpan bersama hasil penilaian)."""
        wanted = {i for rec in (*self.fields.values(), *self.profile.values()) for i in rec.get("line_ids", [])}
        wanted |= {i for f in self.outcome.findings for i in f["line_ids"]}
        index = self.line_index()
        return {i: index[i] for i in sorted(wanted) if i in index}


def assess_application(inputs: list[InputDocument], llm: LLMClient, ocr: OcrEngine, ruleset: UwRuleset) -> UwResult:
    documents: list[LoadedDocument] = []
    methods: dict[str, str] = {}
    warnings: list[str] = []
    for n, item in enumerate(inputs, start=1):
        try:
            doc = load_document(item.document_id, item.data, item.content_type, item.filename, ocr=ocr, prefix=f"D{n}")
        except Exception as exc:  # file rusak tidak boleh menghentikan pengajuan
            log.exception("Gagal membaca %s", item.filename)
            warnings.append(f"{item.filename}: tidak bisa dibaca ({type(exc).__name__})")
            continue
        if any(p.mode == "ocr_unavailable" for p in doc.pages):
            warnings.append(f"{item.filename}: halaman pindaian tidak dibaca karena OCR tidak tersedia")
        doc.doc_type, methods[doc.document_id] = classify_uw(doc, llm, item.doc_type_hint)
        documents.append(doc)
    if inputs and not documents:
        raise ValueError("Tidak ada dokumen yang bisa dibuka: " + "; ".join(warnings))

    outcomes: list[ExtractionOutcome] = []
    hint = None
    for doc in sorted(documents, key=lambda d: _ORDER.get(d.doc_type, 99)):
        o = extract_uw_document(llm, doc, hint)
        if doc.doc_type == "spaj" and o.facts is not None and hint is None:
            hint = o.facts.spaj_number.value
        outcomes.append(o)
        warnings += [f"{o.doc_type} ({o.document_id[:8]}): {w}" for w in o.warnings]
    present = {d.doc_type for d in documents if d.doc_type != "unknown"}
    fields, profile = build_fields(outcomes, present)
    letter_doc = next((d for d in documents if d.doc_type == "surat_dokter" and d.lines), None)
    if letter_doc is not None:  # bukti "ada surat dokter" = baris judul surat
        title = next((l for l in letter_doc.lines[:HEAD_LINES] if "surat keterangan" in normalize(l.text)), letter_doc.lines[0])
        fields["doctor.letter"]["line_ids"] = [title.id]
    outcome = apply_rules(ruleset, fields, present)
    return UwResult(documents, methods, outcomes, fields, profile, outcome, ruleset.version,
                    getattr(llm, "model_version", "unknown"), warnings=warnings)
