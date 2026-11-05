"""Aturan underwriting (YAML berversi): muat, validasi, dan terapkan ke data calon peserta.

Aturan memakai ekspresi kondisi yang sama dengan aturan klinis (rules/engine.py), dengan
kelompok field applicant/vital/lab/history/doctor. Hasil penerapan: temuan dengan bukti,
total debit, kelas risiko, loading premi, pengecualian, dan DRAF rekomendasi.
Mesin aturan tidak pernah memutuskan sendiri: selain "terima standar" wajib ditandatangani dokter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mab_pipeline.rules.engine import (CompiledExpression, ExpressionError, MissingData, compile_expression, evaluate,
                                       message_fields, render_message)
from mab_pipeline.rules.loader import RuleValidationError

UW_GROUPS = ("applicant", "vital", "lab", "history", "doctor")
DEFAULT_UW_RULES = Path(__file__).resolve().parents[3] / "rules" / "aturan_underwriting_demo.yaml"
_REQUIRED_KEYS = ("id", "nama", "kondisi", "kode_alasan", "pesan")


@dataclass(frozen=True)
class UwRule:
    id: str
    name: str
    condition: CompiledExpression
    reason_code: str
    message: str
    debit: int = 0
    exclusion: str | None = None
    decision: str | None = None   # "tunda" | "tolak"
    note: bool = False
    reference: str | None = None

    @property
    def kind(self) -> str:
        if self.decision:
            return self.decision
        if self.exclusion and self.debit:
            return "debit_pengecualian"
        if self.exclusion:
            return "pengecualian"
        if self.debit:
            return "debit"
        return "catatan"


@dataclass(frozen=True)
class RiskClass:
    code: str
    name: str
    max_debit: int


@dataclass(frozen=True)
class UwRuleset:
    version: str
    status: str
    dictionary: dict[str, dict]
    required_docs: tuple[str, ...]
    required_fields: tuple[str, ...]
    classes: tuple[RiskClass, ...]
    decline_debit: int
    loading_per_debit: float
    rules: tuple[UwRule, ...]

    def class_name(self, code: str) -> str:
        names = {c.code: c.name for c in self.classes} | {"POSTPONE": "Ditunda", "DECLINE": "Usulan tolak"}
        return names.get(code, code)


def load_uw_rules(path: str | Path | None = None) -> UwRuleset:
    raw = yaml.safe_load(Path(path or DEFAULT_UW_RULES).read_text(encoding="utf-8"))
    errors: list[str] = []
    dictionary = raw.get("kamus_data") or {}
    for key in ("version", "kamus_data", "kelas_risiko", "aturan", "batas_debit_tolak"):
        if key not in raw:
            errors.append(f"kunci '{key}' tidak ada")
    rules: list[UwRule] = []
    seen: set[str] = set()
    for i, r in enumerate(raw.get("aturan") or []):
        where = f"aturan #{i + 1} ({r.get('id', '?')})"
        missing = [k for k in _REQUIRED_KEYS if k not in r]
        if missing:
            errors.append(f"{where}: kunci {', '.join(missing)} tidak ada")
            continue
        if r["id"] in seen:
            errors.append(f"{where}: id ganda")
        seen.add(r["id"])
        try:
            cond = compile_expression(r["kondisi"], UW_GROUPS)
        except ExpressionError as exc:
            errors.append(f"{where}: {exc}")
            continue
        for f in (*cond.fields, *message_fields(r["pesan"])):
            if f not in dictionary:
                errors.append(f"{where}: field '{f}' tidak ada di kamus_data")
        decision = r.get("keputusan")
        if decision not in (None, "tunda", "tolak"):
            errors.append(f"{where}: keputusan harus 'tunda' atau 'tolak'")
        debit = int(r.get("debit") or 0)
        if debit < 0:
            errors.append(f"{where}: debit tidak boleh negatif")
        if not (debit or r.get("pengecualian") or decision or r.get("catatan")):
            errors.append(f"{where}: butuh salah satu dari debit, pengecualian, keputusan, atau catatan")
        rules.append(UwRule(r["id"], r["nama"], cond, r["kode_alasan"], " ".join(str(r["pesan"]).split()), debit,
                            r.get("pengecualian"), decision, bool(r.get("catatan")), r.get("referensi")))
    classes = tuple(RiskClass(c["kode"], c["nama"], int(c["debit_maks"])) for c in raw.get("kelas_risiko") or [])
    if classes and [c.max_debit for c in classes] != sorted(c.max_debit for c in classes):
        errors.append("kelas_risiko harus urut menurut debit_maks")
    if classes and classes[0].max_debit != 0:
        errors.append("kelas risiko pertama harus kelas standar (debit_maks 0)")
    for f in raw.get("field_wajib") or []:
        if f not in dictionary:
            errors.append(f"field_wajib '{f}' tidak ada di kamus_data")
    if errors:
        raise RuleValidationError(errors)
    return UwRuleset(
        version=str(raw["version"]), status=str(raw.get("status", "")), dictionary=dictionary,
        required_docs=tuple(raw.get("dokumen_wajib") or ()), required_fields=tuple(raw.get("field_wajib") or ()),
        classes=classes, decline_debit=int(raw["batas_debit_tolak"]),
        loading_per_debit=float(raw.get("loading_per_debit", 1)), rules=tuple(rules),
    )


class UwData:
    """Adaptor nilai field untuk evaluator ekspresi (butuh get_field)."""

    def __init__(self, fields: dict[str, dict]):
        self.fields = fields

    def get_field(self, path: str) -> Any:
        rec = self.fields.get(path)
        return rec.get("value") if rec else None


@dataclass
class UwOutcome:
    findings: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    missing_docs: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    debit_total: int = 0
    risk_class: str = "STANDARD"
    loading_pct: int = 0
    exclusions: list[dict] = field(default_factory=list)
    recommendation: str = "ACCEPT_STANDARD"
    needs_doctor: bool = False
    doctor_reasons: list[str] = field(default_factory=list)


def apply_rules(ruleset: UwRuleset, fields: dict[str, dict], documents_present: set[str]) -> UwOutcome:
    data = UwData(fields)
    out = UwOutcome()
    for rule in ruleset.rules:
        try:
            hit = evaluate(rule.condition, data)
        except MissingData as exc:
            out.skipped.append({"rule_id": rule.id, "name": rule.name, "missing": exc.fields})
            continue
        if not hit:
            continue
        line_ids = list(dict.fromkeys(i for f in rule.condition.fields for i in (fields.get(f) or {}).get("line_ids", [])
                                      if data.get_field(f) is not None))
        out.findings.append({
            "rule_id": rule.id, "name": rule.name, "reason_code": rule.reason_code, "kind": rule.kind,
            "debit": rule.debit, "exclusion": rule.exclusion, "decision": rule.decision, "note": rule.note,
            "message": render_message(rule.message, data), "fields": list(rule.condition.fields),
            "line_ids": line_ids, "reference": rule.reference,
        })
    out.debit_total = sum(f["debit"] for f in out.findings)
    out.exclusions = [{"reason_code": f["reason_code"], "text": f["exclusion"], "rule_id": f["rule_id"]}
                      for f in out.findings if f["exclusion"]]
    out.missing_docs = [d for d in ruleset.required_docs if d not in documents_present]
    out.missing_fields = [f for f in ruleset.required_fields if data.get_field(f) is None]

    if out.debit_total > ruleset.decline_debit:
        out.findings.append({
            "rule_id": "UW-DEBIT-MAX", "name": "Total debit melebihi batas", "reason_code": "DEBIT_OVER_LIMIT",
            "kind": "tolak", "debit": 0, "exclusion": None, "decision": "tolak", "note": False,
            "message": f"Total debit {out.debit_total} melebihi batas {ruleset.decline_debit} yang masih bisa diterima.",
            "fields": [], "line_ids": list(dict.fromkeys(i for f in out.findings if f["debit"] for i in f["line_ids"])),
            "reference": "batas_debit_tolak",
        })
    decline = any(f["decision"] == "tolak" for f in out.findings)
    if (out.missing_docs or out.missing_fields) and not decline:
        # Data wajib kurang: jangan simpulkan standar atau loading yang mungkin terlalu rendah.
        missing = [*(f"dokumen {d}" for d in out.missing_docs), *out.missing_fields]
        out.findings.append({
            "rule_id": "UW-DATA-01", "name": "Data wajib belum lengkap", "reason_code": "INCOMPLETE_DATA",
            "kind": "tunda", "debit": 0, "exclusion": None, "decision": "tunda", "note": False,
            "message": "Tunda sampai data lengkap. Belum ada atau tidak terbaca: " + ", ".join(missing) + ".",
            "fields": list(out.missing_fields), "line_ids": [], "reference": "dokumen_wajib / field_wajib",
        })
    postpone = any(f["decision"] == "tunda" for f in out.findings)
    if decline:
        out.recommendation, out.risk_class, out.loading_pct = "DECLINE", "DECLINE", 0
    elif postpone:
        out.recommendation, out.risk_class, out.loading_pct = "POSTPONE", "POSTPONE", 0
    else:
        out.risk_class = next(c.code for c in ruleset.classes if out.debit_total <= c.max_debit)
        out.loading_pct = int(round(out.debit_total * ruleset.loading_per_debit))
        out.recommendation = "ACCEPT_CONDITIONAL" if (out.debit_total or out.exclusions) else "ACCEPT_STANDARD"

    reasons = []
    if out.recommendation != "ACCEPT_STANDARD":
        reasons.append("Rekomendasi selain terima standar wajib ditandatangani dokter")
    if out.missing_docs:
        reasons.append("Dokumen wajib belum lengkap: " + ", ".join(out.missing_docs))
    if out.missing_fields:
        reasons.append("Data wajib tidak terbaca: " + ", ".join(out.missing_fields))
    if out.skipped:
        reasons.append(f"{len(out.skipped)} aturan tidak bisa dinilai karena data kosong")
    if any(f["note"] for f in out.findings):
        reasons.append("Ada catatan yang perlu ditelaah dokter")
    out.doctor_reasons = reasons
    out.needs_doctor = bool(reasons)
    return out
