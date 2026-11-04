import copy
import json
from pathlib import Path

import pytest
import yaml

from mab_pipeline.rules import RuleValidationError, load_rules, parse_rules, run_rules
from mab_pipeline.rules.engine import ExpressionError, compile_expression, evaluate, MissingData
from mab_pipeline.schemas import ClaimData

ROOT = Path(__file__).resolve().parents[1]
RULES_FILE = ROOT / "rules" / "aturan_klinis_demo.yaml"
CLAIMS_FILE = ROOT / "tests" / "fixtures" / "contoh_klaim_uji.json"

EXPECTED = {
    "DEMO-DEN-01": ("RED", "DOCTOR_REVIEW"),
    "DEMO-DEN-02": ("GREEN", "PAY_FULL"),
    "DEMO-TIF-01": ("RED", "DOCTOR_REVIEW"),
    "DEMO-TIF-02": ("GREEN", "PAY_FULL"),
    "DEMO-GEA-01": ("RED", "DOCTOR_REVIEW"),
    "DEMO-GEA-02": ("GREEN", "PAY_FULL"),
    "DEMO-GEN-01": ("YELLOW", "PEND"),
}


@pytest.fixture(scope="module")
def raw_doc():
    return yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ruleset():
    return load_rules(RULES_FILE)


@pytest.fixture(scope="module")
def claims():
    data = json.loads(CLAIMS_FILE.read_text(encoding="utf-8"))
    return {c["claim_id"]: ClaimData.model_validate(c) for c in data}


# --- File aturan dan kamus data -------------------------------------------------


def test_rules_file_loads_with_19_rules(ruleset):
    total = len(ruleset.general_rules) + sum(len(dx.rules) for dx in ruleset.diagnoses)
    assert ruleset.version == "rules-2026.11-demo"
    assert total == 19


def test_schema_matches_data_dictionary(ruleset):
    assert ClaimData.field_paths() == set(ruleset.data_dictionary)


def test_claim_with_field_outside_dictionary_is_rejected():
    with pytest.raises(ValueError):
        ClaimData.model_validate({"lab": {"platelet_minimum": 90000}})


# --- 7 skenario uji ------------------------------------------------------------------


@pytest.mark.parametrize("claim_id", sorted(EXPECTED))
def test_scenarios_produce_expected_triage(ruleset, claims, claim_id):
    result = run_rules(ruleset, claims[claim_id])
    assert (result.triage_status.value, result.initial_recommendation.value) == EXPECTED[claim_id]
    assert result.ruleset_version == "rules-2026.11-demo"


def test_den01_findings_and_message(ruleset, claims):
    result = run_rules(ruleset, claims["DEMO-DEN-01"])
    assert [f.rule_id for f in result.findings] == ["GEN-02", "DEN-01", "DEN-03", "DEN-04"]
    assert result.risk_score == 100
    den01 = next(f for f in result.findings if f.rule_id == "DEN-01")
    assert "120.000" in den01.message
    assert "lab.platelet_min" in den01.fields_used


def test_green_claims_have_no_findings(ruleset, claims):
    for claim_id, (status, _) in EXPECTED.items():
        if status == "GREEN":
            assert run_rules(ruleset, claims[claim_id]).findings == []


# --- Data kosong tidak membuat crash ---------------------------------------------------


def test_empty_claim_does_not_crash_and_reports_skipped(ruleset):
    result = run_rules(ruleset, ClaimData.model_validate({"dx": {"primary": "A91"}}))
    skipped = {s.rule_id: s.missing_fields for s in result.skipped_rules}
    assert "GEN-01" in skipped and skipped["GEN-01"] == ["history.overlapping_claims"]
    assert "docs.missing" in skipped["GEN-03"]


def test_unknown_diagnosis_runs_only_general_rules(ruleset):
    claim = ClaimData.model_validate({"dx": {"primary": "J18.9"}, "bill": {"duplicate_items": 2}})
    result = run_rules(ruleset, claim)
    assert result.matched_diagnosis is None
    assert [f.rule_id for f in result.findings] == ["GEN-02"]


# --- Ambang di YAML mengubah hasil tanpa mengubah kode ----------------------------------


def test_changing_red_threshold_in_yaml_changes_result(raw_doc, claims):
    # GEA-01 punya 3 temuan MEDIUM (skor 60): merah karena skor >= 40.
    doc = copy.deepcopy(raw_doc)
    doc["triase"]["aturan_status"][1]["skor_min"] = 80
    result = run_rules(parse_rules(doc), claims["DEMO-GEA-01"])
    assert result.triage_status.value == "YELLOW"


def test_changing_severity_weight_in_yaml_changes_result(raw_doc, claims):
    doc = copy.deepcopy(raw_doc)
    doc["triase"]["bobot_keparahan"]["MEDIUM"] = 5
    result = run_rules(parse_rules(doc), claims["DEMO-GEA-01"])
    assert result.risk_score == 15
    assert result.triage_status.value == "YELLOW"


def test_changing_rule_threshold_in_yaml_changes_result(raw_doc, claims):
    # TIF-03 terpicu karena seftriakson 7 hari > 5. Naikkan ambang ke 7.
    doc = copy.deepcopy(raw_doc)
    tif = next(dx for dx in doc["diagnosis"] if dx["id"] == "tifoid")
    rule = next(r for r in tif["aturan"] if r["id"] == "TIF-03")
    rule["kondisi"] = rule["kondisi"].replace("> 5", "> 7")
    result = run_rules(parse_rules(doc), claims["DEMO-TIF-01"])
    assert "TIF-03" not in [f.rule_id for f in result.findings]


# --- YAML rusak -------------------------------------------------------------------------


def _first_rule(doc):
    return doc["aturan_umum"][0]


@pytest.mark.parametrize(
    "mutate, expected_text",
    [
        (lambda d: _first_rule(d).pop("kode_alasan"), "kunci wajib tidak ada"),
        (lambda d: _first_rule(d).update(kondisi="history.tidak_ada > 0"), "tidak ada di kamus data"),
        (lambda d: _first_rule(d).update(pesan="Nilai {lab.salah_ketik}"), "di pesan tidak ada di kamus data"),
        (lambda d: _first_rule(d).update(kode_alasan="KODE_BARU"), "tidak terdaftar"),
        (lambda d: _first_rule(d).update(keparahan="SEDANG"), "keparahan 'SEDANG' tidak dikenal"),
        (lambda d: _first_rule(d).update(kondisi="history.overlapping_claims >"), "sintaks tidak valid"),
        (lambda d: d["aturan_umum"][1].update(id="GEN-01"), "id aturan duplikat"),
        (lambda d: d["triase"]["aturan_status"].pop(), "baris default"),
        (lambda d: d["triase"]["bobot_keparahan"].pop("LOW"), "bobot untuk LOW"),
        (lambda d: d.pop("kamus_data"), "'kamus_data' tidak ada"),
    ],
)
def test_broken_yaml_is_rejected(raw_doc, mutate, expected_text):
    doc = copy.deepcopy(raw_doc)
    mutate(doc)
    with pytest.raises(RuleValidationError) as exc:
        parse_rules(doc)
    assert expected_text in str(exc.value)


def test_multiple_errors_are_reported_together(raw_doc):
    doc = copy.deepcopy(raw_doc)
    doc["aturan_umum"][0]["kode_alasan"] = "X"
    doc["aturan_umum"][1]["keparahan"] = "Y"
    with pytest.raises(RuleValidationError) as exc:
        parse_rules(doc)
    assert len(exc.value.errors) == 2


# --- Ekspresi berbahaya ditolak ----------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('echo hai')",
        "().__class__.__bases__",
        "lab.platelet_min.__class__",
        "open('/etc/passwd')",
        "(lambda: 1)()",
        "lab.platelet_min if True else 0",
        "dx.secondary[0] == 'A01.0'",
        "[x for x in dx.secondary]",
        "os.path",
        "platelet_min > 1",
        "lab.platelet_min + 1 > 2",
    ],
)
def test_unsafe_expressions_are_rejected(expr):
    with pytest.raises(ExpressionError):
        compile_expression(expr)


def test_expression_semantics_follow_python():
    claim = ClaimData.model_validate({"lab": {"platelet_min": 90000}, "clin": {"plasma_leakage": None}})
    assert evaluate(compile_expression("lab.platelet_min < 100000 and not clin.plasma_leakage"), claim)
    assert evaluate(compile_expression("lab.dengue_ns1 is None or lab.dengue_ns1 != 'pos'"), claim)
    assert not evaluate(compile_expression("lab.platelet_min in (1, 2)"), claim)
    with pytest.raises(MissingData):
        evaluate(compile_expression("lab.hct_rise_pct >= 20"), claim)
