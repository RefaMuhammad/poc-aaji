"""Aturan benefit (U2): memeriksa klaim terhadap polis peserta.

Polis dan plan berasal dari sistem inti asuransi (impor atau API), jadi modul ini tidak
membaca database: pemanggil (tasks.py) mencari polis dan mengirim `PolicyInfo`.
Aturan ditulis di YAML terpisah (rules/aturan_benefit_demo.yaml) dengan format dan
evaluator yang sama dengan aturan klinis, tetapi memakai kelompok field policy.* dan benefit.*.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mab_pipeline.extraction.facts import BillingItem
from mab_pipeline.rules.engine import ExpressionError, MissingData, compile_expression, evaluate, message_fields, render_message
from mab_pipeline.rules.loader import Rule, RuleValidationError
from mab_pipeline.schemas import Finding, Severity

BENEFIT_GROUPS: tuple[str, ...] = ("policy", "benefit")
ADJUSTMENTS = ("kelebihan_kamar", "kelebihan_limit")
ROOM_WORDS = ("kamar",)
_ROOM_CLASS = re.compile(r"\b(vvip|vip|kelas\s*(?:[1-3]|i{1,3}))\b", re.IGNORECASE)


@dataclass(frozen=True)
class BenefitRule:
    rule: Rule
    adjustment: str | None = None


@dataclass(frozen=True)
class BenefitRuleSet:
    version: str
    data_dictionary: dict[str, dict[str, Any]]
    reason_codes: dict[str, str]
    rules: tuple[BenefitRule, ...]

    @property
    def rule_ids(self) -> set[str]:
        return {r.rule.id for r in self.rules}


def load_benefit_rules(path: str | Path) -> BenefitRuleSet:
    with open(path, encoding="utf-8") as fh:
        return parse_benefit_rules(yaml.safe_load(fh))


def parse_benefit_rules(doc: Any) -> BenefitRuleSet:
    errors: list[str] = []
    if not isinstance(doc, dict):
        raise RuleValidationError(["isi file bukan mapping YAML"])
    for key in ("version", "kamus_data", "kode_alasan", "aturan"):
        if key not in doc:
            errors.append(f"bagian '{key}' tidak ada")
    if errors:
        raise RuleValidationError(errors)
    kamus = doc["kamus_data"] or {}
    codes = doc["kode_alasan"] or {}
    for path in kamus:
        if path.split(".", 1)[0] not in BENEFIT_GROUPS:
            errors.append(f"kamus_data: field '{path}' harus diawali policy. atau benefit.")
    seen: set[str] = set()
    rules: list[BenefitRule] = []
    for raw in doc["aturan"] or []:
        if not isinstance(raw, dict):
            errors.append("aturan: setiap aturan harus berupa mapping")
            continue
        rid = str(raw.get("id", "<tanpa id>"))
        missing = [k for k in ("id", "nama", "kondisi", "kode_alasan", "keparahan", "pesan") if k not in raw]
        if missing:
            errors.append(f"aturan {rid}: kunci wajib tidak ada: {', '.join(missing)}")
            continue
        if rid in seen:
            errors.append(f"aturan {rid}: id aturan duplikat")
        seen.add(rid)
        try:
            cond = compile_expression(raw["kondisi"], BENEFIT_GROUPS)
        except ExpressionError as exc:
            errors.append(f"aturan {rid}: kondisi tidak valid: {exc}")
            continue
        for f in list(cond.fields) + message_fields(str(raw["pesan"])):
            if f not in kamus:
                errors.append(f"aturan {rid}: field '{f}' tidak ada di kamus data")
        if raw["kode_alasan"] not in codes:
            errors.append(f"aturan {rid}: kode_alasan '{raw['kode_alasan']}' tidak terdaftar")
        try:
            sev = Severity(raw["keparahan"])
        except ValueError:
            errors.append(f"aturan {rid}: keparahan '{raw['keparahan']}' tidak dikenal")
            continue
        adj = raw.get("penyesuaian")
        if adj is not None and adj not in ADJUSTMENTS:
            errors.append(f"aturan {rid}: penyesuaian '{adj}' tidak dikenal (pilihan: {', '.join(ADJUSTMENTS)})")
        rules.append(BenefitRule(
            Rule(id=rid, name=str(raw["nama"]), condition=cond, reason_code=raw["kode_alasan"], severity=sev,
                 message=" ".join(str(raw["pesan"]).split()), needs_ai=False, reference=raw.get("rujukan")),
            adj,
        ))
    if errors:
        raise RuleValidationError(errors)
    return BenefitRuleSet(str(doc["version"]), kamus, codes, tuple(rules))


# ----------------------------------------------------------------------------- fakta


@dataclass(frozen=True)
class PolicyInfo:
    """Polis peserta + plan benefitnya, sudah diambil dari database oleh pemanggil."""

    policy_number: str
    member_id: str
    plan_code: str
    plan_name: str
    start_date: dt.date
    end_date: dt.date
    status: str = "ACTIVE"
    room_class: str | None = None
    room_rate_limit: int | None = None
    annual_limit: int | None = None
    limit_used: int = 0
    waiting_period_days: int = 0
    excluded_icd10: tuple[str, ...] = ()


@dataclass
class BenefitFacts:
    values: dict[str, Any]
    evidence: dict[str, list[dict]]

    def get_field(self, path: str) -> Any:
        return self.values.get(path)


def _fmt_rp(n: int | None) -> str:
    return "-" if n is None else "Rp" + f"{n:,}".replace(",", ".")


def room_items(items: list[BillingItem]) -> list[BillingItem]:
    return [it for it in items if any(w in it.name.lower() for w in ROOM_WORDS) and it.unit_price is not None]


def room_class_of(name: str) -> str | None:
    m = _ROOM_CLASS.search(name)
    if not m:
        return None
    raw = " ".join(m.group(1).split()).lower()
    roman = {"i": "1", "ii": "2", "iii": "3"}
    if raw.startswith("kelas"):
        num = raw.split()[-1] if " " in raw else raw[5:]
        return f"Kelas {roman.get(num, num)}"
    return raw.upper()


def build_facts(
    policy: PolicyInfo | None,
    admission_date: dt.date | None,
    diagnoses: list[str],
    billed_amount: int,
    billing_items: list[BillingItem] | None = None,
    billing_evidence: dict[str, list[dict]] | None = None,
) -> BenefitFacts:
    """Hitung field policy.* dan benefit.* untuk satu klaim.

    `billing_evidence`: id baris -> bukti dokumen (untuk mengutip baris kamar di tagihan).
    """
    v: dict[str, Any] = {"policy.found": policy is not None, "benefit.billed_amount": billed_amount,
                         "policy.admission_date": admission_date.isoformat() if admission_date else None}
    ev: dict[str, list[dict]] = {}
    if policy is None:
        return BenefitFacts(v, ev)

    def cite(path: str, quote: str) -> None:
        ev.setdefault(path, []).append({"policy_number": policy.policy_number, "quote": quote, "field": path})

    v.update({
        "policy.number": policy.policy_number,
        "policy.plan_name": policy.plan_name,
        "policy.status": policy.status,
        "policy.start_date": policy.start_date.isoformat(),
        "policy.end_date": policy.end_date.isoformat(),
        "policy.waiting_period_days": policy.waiting_period_days,
    })
    period = (f"Polis {policy.policy_number} (plan {policy.plan_name}): status {policy.status}, "
              f"berlaku {policy.start_date.isoformat()} s.d. {policy.end_date.isoformat()}")
    if admission_date is not None:
        active = policy.status == "ACTIVE" and policy.start_date <= admission_date <= policy.end_date
        v["policy.active_on_admission"] = active
        v["policy.days_since_start"] = (admission_date - policy.start_date).days
        cite("policy.active_on_admission", f"{period}; tanggal masuk rawat {admission_date.isoformat()}")
        cite("policy.days_since_start", f"Polis mulai {policy.start_date.isoformat()}, masuk rawat {admission_date.isoformat()} "
                                        f"({v['policy.days_since_start']} hari); masa tunggu plan {policy.waiting_period_days} hari")
    ev["policy.status"] = ev.get("policy.active_on_admission", [])

    prefixes = tuple(p.upper() for p in policy.excluded_icd10 if p)
    excluded = [d for d in dict.fromkeys(x.upper() for x in diagnoses if x) if prefixes and d.startswith(prefixes)]
    v["policy.excluded_dx"] = excluded
    if excluded:
        cite("policy.excluded_dx", f"Pengecualian plan {policy.plan_name}: {', '.join(prefixes)}; diagnosis klaim: {', '.join(excluded)}")

    if policy.annual_limit is not None:
        remaining = max(policy.annual_limit - (policy.limit_used or 0), 0)
        v["benefit.limit_remaining"] = remaining
        cite("benefit.limit_remaining", f"Limit tahunan {_fmt_rp(policy.annual_limit)}, terpakai {_fmt_rp(policy.limit_used or 0)}, "
                                        f"sisa {_fmt_rp(remaining)}; tagihan klaim {_fmt_rp(billed_amount)}")

    rooms = room_items(billing_items or [])
    v["benefit.room_rate_limit"] = policy.room_rate_limit
    v["benefit.room_class_entitled"] = policy.room_class
    if rooms:
        top = max(rooms, key=lambda it: it.unit_price or 0)
        v["benefit.room_rate_billed"] = top.unit_price
        v["benefit.room_days_billed"] = sum(it.qty for it in rooms)
        v["benefit.room_class_billed"] = room_class_of(top.name) or top.name
        line_ev = [e for it in rooms for lid in it.source_line_ids for e in (billing_evidence or {}).get(lid, [])]
        ev["benefit.room_rate_billed"] = [{**e, "field": "benefit.room_rate_billed"} for e in line_ev]
        cite("benefit.room_rate_limit", f"Hak kamar plan {policy.plan_name}: {policy.room_class or '-'}, "
                                        f"maksimal {_fmt_rp(policy.room_rate_limit)}/hari")
    return BenefitFacts(v, ev)


# ----------------------------------------------------------------------------- penilaian


@dataclass
class BenefitResult:
    version: str
    facts: BenefitFacts
    findings: list[Finding] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    adjustment_rules: dict[str, str] = field(default_factory=dict)   # rule_id -> jenis penyesuaian


def run_benefit_rules(ruleset: BenefitRuleSet, facts: BenefitFacts) -> BenefitResult:
    result = BenefitResult(ruleset.version, facts)
    for br in ruleset.rules:
        rule = br.rule
        try:
            hit = evaluate(rule.condition, facts)  # type: ignore[arg-type]
        except MissingData as missing:
            result.skipped.append({"rule_id": rule.id, "missing_fields": list(dict.fromkeys(missing.fields))})
            continue
        if not hit:
            continue
        result.findings.append(Finding(
            rule_id=rule.id, rule_name=rule.name, reason_code=rule.reason_code, severity=rule.severity,
            needs_ai_evidence=False, message=render_message(rule.message, facts),  # type: ignore[arg-type]
            reference=rule.reference, fields_used=list(rule.condition.fields),
        ))
        if br.adjustment:
            result.adjustment_rules[rule.id] = br.adjustment
    return result


def benefit_adjustments(result: BenefitResult, billing_items: list[BillingItem] | None, billed_amount: int,
                        prior_adjustment: int = 0) -> list[dict]:
    """Usulan koreksi tagihan dari temuan benefit (dihitung setelah koreksi klinis)."""
    kinds = {result.adjustment_rules[f.rule_id]: f.reason_code for f in result.findings if f.rule_id in result.adjustment_rules}
    out: list[dict] = []
    if "kelebihan_kamar" in kinds:
        limit = result.facts.get_field("benefit.room_rate_limit")
        if limit is not None:
            for it in room_items(billing_items or []):
                if (it.unit_price or 0) > limit:
                    out.append({"item": it.name, "date": it.date.isoformat() if it.date else None, "time": it.time,
                                "qty": it.qty, "amount": (it.unit_price - limit) * it.qty,
                                "reason_code": kinds["kelebihan_kamar"],
                                "note": f"Selisih tarif kamar di atas hak plan ({_fmt_rp(limit)}/hari)",
                                "line_ids": it.source_line_ids})
    if "kelebihan_limit" in kinds:
        remaining = result.facts.get_field("benefit.limit_remaining")
        if remaining is not None:
            excess = billed_amount - prior_adjustment - sum(a["amount"] for a in out) - remaining
            if excess > 0:
                out.append({"item": "Bagian tagihan di atas sisa limit tahunan", "date": None, "time": None, "qty": 1,
                            "amount": excess, "reason_code": kinds["kelebihan_limit"],
                            "note": f"Sisa limit tahunan {_fmt_rp(remaining)}", "line_ids": []})
    return out
