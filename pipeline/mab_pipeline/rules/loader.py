"""Memuat dan memvalidasi file aturan klinis (YAML).

Validasi yang dilakukan:
  - setiap aturan punya id, nama, kondisi, kode_alasan, keparahan, pesan, butuh_ai
  - id aturan unik
  - kondisi adalah ekspresi aman (lihat engine.py)
  - setiap field di kondisi dan di pesan ada di kamus data
  - kode_alasan ada di daftar kode_alasan, keparahan ada di bobot_keparahan
  - aturan_status triase valid dan diakhiri baris default
Semua kesalahan dikumpulkan dan dilaporkan sekaligus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mab_pipeline.rules.engine import CompiledExpression, ExpressionError, compile_expression, message_fields
from mab_pipeline.schemas import InitialRecommendation, Severity, TriageStatus

REQUIRED_RULE_KEYS = ("id", "nama", "kondisi", "kode_alasan", "keparahan", "pesan", "butuh_ai")
_STATUS_CRITERIA = ("ada_kode_alasan", "ada_keparahan", "skor_min")


class RuleValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("File aturan tidak valid:\n- " + "\n- ".join(errors))


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    condition: CompiledExpression
    reason_code: str
    severity: Severity
    message: str
    needs_ai: bool
    reference: str | None = None


@dataclass(frozen=True)
class DiagnosisRules:
    id: str
    name: str
    icd10: tuple[str, ...]
    rules: tuple[Rule, ...]
    specialty: str | None = None  # spesialisasi penelaah kasus merah / eskalasi


@dataclass(frozen=True)
class StatusRule:
    status: TriageStatus
    initial_recommendation: InitialRecommendation
    any_reason_codes: tuple[str, ...] = ()
    any_severities: tuple[Severity, ...] = ()
    min_score: int | None = None
    description: str = ""

    @property
    def is_default(self) -> bool:
        return not self.any_reason_codes and not self.any_severities and self.min_score is None


@dataclass(frozen=True)
class TriageConfig:
    severity_weights: dict[Severity, int]
    status_rules: tuple[StatusRule, ...]
    max_score: int = 100
    required_inpatient_docs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleSet:
    version: str
    data_dictionary: dict[str, dict[str, Any]]
    reason_codes: dict[str, str]
    general_rules: tuple[Rule, ...]
    diagnoses: tuple[DiagnosisRules, ...]
    triage: TriageConfig
    raw: dict[str, Any] = field(repr=False, default_factory=dict)

    def match_diagnosis(self, icd10: str | None) -> DiagnosisRules | None:
        for dx in self.diagnoses:
            if icd10 in dx.icd10:
                return dx
        return None


def load_rules(path: str | Path) -> RuleSet:
    with open(path, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    return parse_rules(doc)


def parse_rules(doc: Any) -> RuleSet:
    errors: list[str] = []
    if not isinstance(doc, dict):
        raise RuleValidationError(["isi file bukan mapping YAML"])

    for key in ("version", "kamus_data", "kode_alasan", "triase", "aturan_umum", "diagnosis"):
        if key not in doc:
            errors.append(f"bagian '{key}' tidak ada")
    if errors:
        raise RuleValidationError(errors)

    kamus: dict[str, dict[str, Any]] = doc["kamus_data"] or {}
    reason_codes: dict[str, str] = doc["kode_alasan"] or {}
    triage_doc = doc["triase"] or {}
    weights_doc = triage_doc.get("bobot_keparahan") or {}

    severity_weights: dict[Severity, int] = {}
    for sev, weight in weights_doc.items():
        try:
            severity_weights[Severity(sev)] = int(weight)
        except ValueError:
            errors.append(f"triase.bobot_keparahan: keparahan '{sev}' tidak dikenal")
    for sev in Severity:
        if sev not in severity_weights:
            errors.append(f"triase.bobot_keparahan: bobot untuk {sev.value} tidak ada")

    seen_ids: set[str] = set()

    def build_rule(raw: Any, where: str) -> Rule | None:
        if not isinstance(raw, dict):
            errors.append(f"{where}: aturan harus berupa mapping")
            return None
        rule_id = raw.get("id", "<tanpa id>")
        label = f"{where} {rule_id}"
        missing = [k for k in REQUIRED_RULE_KEYS if k not in raw]
        if missing:
            errors.append(f"{label}: kunci wajib tidak ada: {', '.join(missing)}")
            return None
        if rule_id in seen_ids:
            errors.append(f"{label}: id aturan duplikat")
        seen_ids.add(rule_id)

        ok = True
        try:
            condition = compile_expression(raw["kondisi"])
        except ExpressionError as exc:
            errors.append(f"{label}: kondisi tidak valid: {exc}")
            return None
        for f in condition.fields:
            if f not in kamus:
                errors.append(f"{label}: field '{f}' di kondisi tidak ada di kamus data")
                ok = False
        for f in message_fields(str(raw["pesan"])):
            if f not in kamus:
                errors.append(f"{label}: field '{f}' di pesan tidak ada di kamus data")
                ok = False
        if raw["kode_alasan"] not in reason_codes:
            errors.append(f"{label}: kode_alasan '{raw['kode_alasan']}' tidak terdaftar")
            ok = False
        try:
            severity = Severity(raw["keparahan"])
        except ValueError:
            errors.append(f"{label}: keparahan '{raw['keparahan']}' tidak dikenal")
            return None
        if not isinstance(raw["butuh_ai"], bool):
            errors.append(f"{label}: butuh_ai harus true/false")
            ok = False
        if not ok:
            return None
        return Rule(
            id=str(rule_id),
            name=str(raw["nama"]),
            condition=condition,
            reason_code=raw["kode_alasan"],
            severity=severity,
            message=" ".join(str(raw["pesan"]).split()),
            needs_ai=raw["butuh_ai"],
            reference=raw.get("rujukan"),
        )

    general_rules = [r for raw in doc["aturan_umum"] or [] if (r := build_rule(raw, "aturan_umum"))]

    diagnoses: list[DiagnosisRules] = []
    for raw_dx in doc["diagnosis"] or []:
        dx_id = raw_dx.get("id", "<tanpa id>") if isinstance(raw_dx, dict) else "<tidak valid>"
        if not isinstance(raw_dx, dict) or not raw_dx.get("icd10"):
            errors.append(f"diagnosis {dx_id}: wajib punya id dan daftar icd10")
            continue
        rules = [r for raw in raw_dx.get("aturan") or [] if (r := build_rule(raw, f"diagnosis {dx_id}:"))]
        diagnoses.append(
            DiagnosisRules(
                id=str(dx_id),
                name=str(raw_dx.get("nama", dx_id)),
                icd10=tuple(str(code) for code in raw_dx["icd10"]),
                rules=tuple(rules),
                specialty=str(raw_dx["spesialisasi"]) if raw_dx.get("spesialisasi") else None,
            )
        )

    status_rules = _parse_status_rules(triage_doc.get("aturan_status") or [], reason_codes, errors)

    if errors:
        raise RuleValidationError(errors)

    return RuleSet(
        version=str(doc["version"]),
        data_dictionary=kamus,
        reason_codes=reason_codes,
        general_rules=tuple(general_rules),
        diagnoses=tuple(diagnoses),
        triage=TriageConfig(
            severity_weights=severity_weights,
            status_rules=tuple(status_rules),
            max_score=int(triage_doc.get("skor_maksimum", 100)),
            required_inpatient_docs=tuple(triage_doc.get("dokumen_wajib_rawat_inap") or ()),
        ),
        raw=doc,
    )


def _parse_status_rules(raw_rules: list[Any], reason_codes: dict[str, str], errors: list[str]) -> list[StatusRule]:
    result: list[StatusRule] = []
    if not raw_rules:
        errors.append("triase.aturan_status kosong")
        return result
    for i, raw in enumerate(raw_rules):
        where = f"triase.aturan_status[{i}]"
        if not isinstance(raw, dict):
            errors.append(f"{where}: harus berupa mapping")
            continue
        try:
            status = TriageStatus(raw.get("status"))
            rec = InitialRecommendation(raw.get("rekomendasi_awal"))
        except ValueError:
            errors.append(f"{where}: status atau rekomendasi_awal tidak dikenal")
            continue
        codes = tuple(raw.get("ada_kode_alasan") or ())
        for code in codes:
            if code not in reason_codes:
                errors.append(f"{where}: kode_alasan '{code}' tidak terdaftar")
        try:
            severities = tuple(Severity(s) for s in raw.get("ada_keparahan") or ())
        except ValueError:
            errors.append(f"{where}: keparahan tidak dikenal")
            continue
        min_score = raw.get("skor_min")
        result.append(
            StatusRule(
                status=status,
                initial_recommendation=rec,
                any_reason_codes=codes,
                any_severities=severities,
                min_score=int(min_score) if min_score is not None else None,
                description=str(raw.get("jika", "")),
            )
        )
    if result:
        defaults = [i for i, r in enumerate(result) if r.is_default]
        if defaults != [len(result) - 1]:
            errors.append("triase.aturan_status: harus ada tepat satu baris default (tanpa syarat) di urutan terakhir")
    return result
