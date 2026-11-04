"""Penalaran klinis: LLM mengisi field ber-sumber 'ai' di kamus data dari resume, CPPT, lab, dan tagihan.

Setiap nilai yang menyatakan sesuatu ADA wajib membawa kutipan yang lolos cek bukti.
- nilai positif + kutipan ditemukan      -> 'verified', nilai dipakai, bukti disimpan
- nilai positif + kutipan tidak ditemukan -> 'unverified', nilai menjadi null (tidak diketahui)
- nilai "tidak ada" (false, 0, [])        -> 'absent', dipakai tanpa kutipan
- null / tidak dijawab                    -> 'unknown'
Item daftar dicek satu per satu; item tanpa bukti dibuang, dan bila semua item
terbuang nilainya null, bukan daftar kosong.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from mab_pipeline.documents import LoadedDocument
from mab_pipeline.llm.client import LLMClient, parse_json
from mab_pipeline.reasoning.evidence_check import EvidenceIndex, EvidenceMatch
from mab_pipeline.rules.loader import RuleSet

log = logging.getLogger(__name__)

PROMPT_VERSION = "clinical_v1"
PROMPT_FILE = Path(__file__).with_name("prompts") / "clinical_v1.md"
# field bertipe angka yang dijawab LLM sebagai daftar item (nilai = jumlah item terbukti)
COUNT_OF_ITEMS = {"bill.items_without_clinical_note"}
# urutan dokumen untuk prompt: narasi klinis dulu
DOC_ORDER = ("resume_medis", "cppt", "hasil_laboratorium", "rincian_tagihan")


@dataclass
class AiField:
    path: str
    value: Any = None
    status: str = "unknown"            # verified | absent | unverified | unknown
    evidence: list[dict] = field(default_factory=list)
    confidence: float | None = None
    dropped_quotes: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)     # isi daftar yang terbukti (sebelum dihitung)


@dataclass
class ReasoningResult:
    fields: dict[str, AiField]
    status: str                        # ok | retried | failed | skipped
    model_version: str
    prompt_version: str = PROMPT_VERSION
    warnings: list[str] = field(default_factory=list)

    @property
    def unverified(self) -> list[str]:
        return [p for p, f in self.fields.items() if f.status == "unverified"]


def ai_fields_for(ruleset: RuleSet, primary_dx: str | None) -> list[str]:
    """Field ai yang dipakai aturan umum + aturan diagnosis yang cocok (urutan kamus data)."""
    rules = list(ruleset.general_rules)
    dx = ruleset.match_diagnosis(primary_dx)
    if dx:
        rules += list(dx.rules)
    used = {f for r in rules for f in r.condition.fields}
    return [p for p, spec in ruleset.data_dictionary.items() if spec.get("sumber") == "ai" and p in used]


@lru_cache
def _template() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def build_prompt(ruleset: RuleSet, paths: list[str]) -> str:
    lines = []
    for p in paths:
        spec = ruleset.data_dictionary[p]
        kind = "daftar item" if p in COUNT_OF_ITEMS else spec.get("tipe", "")
        lines.append(f"- {p} ({kind}): {spec.get('ket', '')}")
    return _template().replace("{fields}", "\n".join(lines))


def documents_text(documents: list[LoadedDocument]) -> str:
    ordered = sorted(documents, key=lambda d: DOC_ORDER.index(d.doc_type) if d.doc_type in DOC_ORDER else 99)
    parts = []
    for d in ordered:
        if d.lines:
            parts.append(f"=== {d.doc_type.upper()} ({d.filename}) ===\n{d.numbered_text()}")
        else:
            parts.append(f"=== {d.doc_type.upper()} ({d.filename}) === [tidak ada teks terbaca]")
    return "\n\n".join(parts)


def _is_absent(value: Any) -> bool:
    return value is False or value == 0 or value == [] or value == ""


def _coerce(path: str, kind: str, value: Any) -> Any:
    """Sesuaikan tipe nilai dengan kamus data; ValueError bila tidak cocok."""
    if value is None:
        return None
    if kind == "ya_tidak":
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("true", "ya", "yes"):
            return True
        if str(value).lower() in ("false", "tidak", "no"):
            return False
    elif kind == "angka":
        if isinstance(value, bool):
            raise ValueError(f"{path}: harus angka")
        if isinstance(value, (int, float)):
            return int(value) if float(value).is_integer() else value
        return int(str(value).strip())
    elif kind == "teks":
        if isinstance(value, str):
            return value.strip().lower()
    raise ValueError(f"{path}: nilai {value!r} tidak sesuai tipe {kind}")


def _verify_items(path: str, raw: Any, index: EvidenceIndex) -> AiField:
    if raw is None:
        return AiField(path)
    if not isinstance(raw, list):
        raise ValueError(f"{path}: harus daftar")
    if not raw:
        return AiField(path, value=[], status="absent")
    kept, evidence, dropped, scores = [], [], [], []
    for item in raw:
        if isinstance(item, str):
            item = {"item": item, "quote": ""}
        name, quote = str(item.get("item", "")).strip(), str(item.get("quote", "") or "")
        match = index.find(quote) if name else None
        if match is None:
            dropped.append(quote or name)
            continue
        kept.append(name.lower())
        evidence += match.to_evidence(path)
        scores.append(match.score)
    if not kept:
        return AiField(path, value=None, status="unverified", dropped_quotes=dropped)
    return AiField(path, value=kept, status="verified", evidence=evidence, confidence=min(scores),
                   dropped_quotes=dropped, items=list(kept))


def _verify_scalar(path: str, value: Any, quotes: list[str], index: EvidenceIndex) -> AiField:
    if value is None:
        return AiField(path)
    matches: list[EvidenceMatch] = []
    dropped = []
    for q in quotes:
        m = index.find(q)
        (matches.append(m) if m else dropped.append(q))
    evidence = [e for m in matches for e in m.to_evidence(path)]
    if _is_absent(value):
        return AiField(path, value=value, status="absent", evidence=evidence, dropped_quotes=dropped)
    if not matches:
        return AiField(path, value=None, status="unverified", dropped_quotes=dropped or ["(tanpa kutipan)"])
    return AiField(path, value=value, status="verified", evidence=evidence,
                   confidence=min(m.score for m in matches), dropped_quotes=dropped)


def parse_answer(answer: Any, ruleset: RuleSet, paths: list[str], index: EvidenceIndex) -> dict[str, AiField]:
    if not isinstance(answer, dict) or not isinstance(answer.get("fields"), dict):
        raise ValueError("jawaban harus berbentuk {\"fields\": {...}}")
    raw_fields = answer["fields"]
    out: dict[str, AiField] = {}
    for path in paths:
        raw = raw_fields.get(path)
        if raw is None:
            out[path] = AiField(path)
            continue
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: harus objek {{value, quotes}}")
        kind = ruleset.data_dictionary[path].get("tipe")
        value = raw.get("value")
        if path in COUNT_OF_ITEMS:
            f = _verify_items(path, value, index)
            f.value = len(f.value) if isinstance(f.value, list) else f.value
            out[path] = f
        elif kind == "daftar":
            out[path] = _verify_items(path, value, index)
        else:
            quotes = raw.get("quotes") or []
            if isinstance(quotes, str):
                quotes = [quotes]
            out[path] = _verify_scalar(path, _coerce(path, kind, value), [str(q) for q in quotes], index)
    return out


def reason(
    llm: LLMClient,
    documents: list[LoadedDocument],
    ruleset: RuleSet,
    primary_dx: str | None,
    claim_number: str | None = None,
) -> ReasoningResult:
    paths = ai_fields_for(ruleset, primary_dx)
    readable = [d for d in documents if d.lines]
    if not paths:
        return ReasoningResult({}, "skipped", llm.model_version)
    if not readable:
        return ReasoningResult({p: AiField(p) for p in paths}, "failed", llm.model_version, warnings=["tidak ada dokumen yang terbaca"])
    index = EvidenceIndex(readable)
    system = build_prompt(ruleset, paths)
    user = f"Diagnosis utama yang ditagihkan: {primary_dx or 'tidak diketahui'}\n\n{documents_text(documents)}"
    context = {"claim_number": claim_number, "fields": paths,
               "lines": [{"id": l.id, "text": l.text, "doc_type": d.doc_type} for d in readable for l in d.lines]}
    error = ""
    for attempt in (1, 2):
        prompt = user if not error else f"{user}\n\nJawaban Anda sebelumnya tidak valid:\n{error}\nKirim ulang JSON lengkap."
        raw = llm.complete_json(system, prompt, task="reason", context=context)
        try:
            fields = parse_answer(parse_json(raw), ruleset, paths, index)
        except (ValueError, json.JSONDecodeError, TypeError, AttributeError) as exc:
            error = str(exc)[:1000]
            log.warning("Jawaban penalaran klinis tidak valid (percobaan %s): %s", attempt, error)
            continue
        warnings = [f"{p}: kutipan tidak ditemukan di dokumen ({'; '.join(f.dropped_quotes)[:120]}), nilai dianggap tidak diketahui"
                    for p, f in fields.items() if f.status == "unverified"]
        return ReasoningResult(fields, "ok" if attempt == 1 else "retried", llm.model_version, warnings=warnings)
    return ReasoningResult({p: AiField(p) for p in paths}, "failed", llm.model_version,
                           warnings=[f"jawaban penalaran klinis tidak valid 2 kali: {error[:200]}"])
