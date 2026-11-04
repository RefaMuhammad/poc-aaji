"""Tes generator data sintetis (M2)."""
import json
from collections import Counter

import pytest

from mab_pipeline.rules import load_rules, run_rules
from mab_pipeline.schemas import ClaimData
from synthetic.generate_cases import (
    PLASMA_LEAKAGE_WORDS,
    REQUIRED_DOCS,
    WARNING_SIGN_TEXT,
    answer_key_rows,
    generate_all,
)
from tests.test_rules import RULES_FILE


@pytest.fixture(scope="module")
def generated():
    cases, truths, cfg = generate_all()
    return cases, truths


@pytest.fixture(scope="module")
def cases(generated):
    return generated[0]


@pytest.fixture(scope="module")
def truths(generated):
    return generated[1]


def _text(case):
    """Semua teks naratif yang akan dibaca AI: CPPT + resume."""
    return json.dumps([case["cppt"], case["resume"]], ensure_ascii=False).lower()


# --- Komposisi skenario --------------------------------------------------------------


def test_thirty_scenarios_ten_per_diagnosis(cases):
    assert len(cases) == 30
    assert Counter(c["dx_group"] for c in cases) == {"dengue": 10, "tifoid": 10, "gea": 10}
    assert len({c["claim_id"] for c in cases}) == 30


def test_mix_of_normal_and_problem_claims(cases):
    for group in ("dengue", "tifoid", "gea"):
        cats = Counter(c["scenario"]["kategori"] for c in cases if c["dx_group"] == group)
        assert 5 <= cats["wajar"] <= 6, (group, cats)
    all_cats = Counter(c["scenario"]["kategori"] for c in cases)
    assert all_cats["dokumen_tidak_lengkap"] == 2
    assert all_cats["duplikat"] == 1


def test_every_problem_scenario_names_expected_rules(cases):
    for c in cases:
        if c["scenario"]["kategori"] != "wajar":
            assert c["scenario"]["harapan"]["aturan"], c["claim_id"]
            assert c["scenario"]["harapan"]["status"] != "GREEN", c["claim_id"]


def test_about_forty_percent_scanned(cases):
    assert sum(c["scanned"] for c in cases) == 12


def test_generation_is_deterministic():
    a = generate_all()[0]
    b = generate_all()[0]
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# --- Ground truth konsisten dengan aturan (kriteria selesai M2) -----------------------


def test_ground_truth_is_valid_claim_data(truths):
    for t in truths:
        ClaimData.model_validate(t)


def test_rule_engine_on_ground_truth_matches_answer_key_100_percent(cases, truths):
    ruleset = load_rules(RULES_FILE)
    key = {r["claim_id"]: r for r in answer_key_rows(cases)}
    mismatches = []
    for t in truths:
        result = run_rules(ruleset, ClaimData.model_validate(t))
        row = key[t["claim_id"]]
        got_rules = sorted(f.rule_id for f in result.findings)
        expected_rules = sorted(filter(None, row["aturan_harapan"].split(";")))
        if (
            result.triage_status.value != row["status_triase_harapan"]
            or result.initial_recommendation.value != row["rekomendasi_harapan"]
            or got_rules != expected_rules
        ):
            mismatches.append((t["claim_id"], result.triage_status.value, got_rules, row))
    assert mismatches == []


def test_no_problem_claim_would_be_green(cases, truths):
    ruleset = load_rules(RULES_FILE)
    for c, t in zip(cases, truths):
        if c["scenario"]["kategori"] != "wajar":
            assert run_rules(ruleset, ClaimData.model_validate(t)).triage_status.value != "GREEN"


# --- Dokumen konsisten dengan skenario ------------------------------------------------


def test_lab_values_match_scenario_targets(cases, truths):
    for c, t in zip(cases, truths):
        lab = c["scenario"].get("lab", {})
        if c["dx_group"] == "dengue":
            assert t["lab"]["platelet_min"] == lab["trombosit_min"]
            assert abs(t["lab"]["hct_rise_pct"] - lab["kenaikan_ht"]) <= 1
            assert t["lab"]["cbc_max_per_day"] == lab.get("cbc_maks_per_hari", 2)
        if c["dx_group"] == "tifoid":
            assert t["lab"]["widal_tests"] == len(lab.get("widal", []))


def test_no_plasma_leakage_words_without_leakage(cases):
    for c in cases:
        if c["dx_group"] == "dengue" and not c["clinical"]["plasma_leakage"]:
            text = _text(c)
            assert not any(w in text for w in PLASMA_LEAKAGE_WORDS), c["claim_id"]
        if c["dx_group"] == "dengue" and c["clinical"]["plasma_leakage"]:
            assert "efusi pleura" in _text(c), c["claim_id"]


def test_warning_signs_are_written_in_cppt(cases):
    for c in cases:
        if c["dx_group"] == "dengue":
            text = _text(c)
            for ws in c["clinical"]["warning_signs"]:
                assert WARNING_SIGN_TEXT[ws] in text, (c["claim_id"], ws)
            if not c["clinical"]["warning_signs"]:
                assert not any(v in text for v in WARNING_SIGN_TEXT.values()), c["claim_id"]


def test_dehydration_degree_is_written(cases):
    for c in cases:
        if c["dx_group"] == "gea":
            assert f"dehidrasi {c['clinical']['dehydration']}" in _text(c), c["claim_id"]


def test_complication_mentioned_only_when_documented(cases):
    for c in cases:
        if c["dx_group"] == "tifoid":
            assert ("melena" in _text(c)) == bool(c["clinical"]["complication_documented"]), c["claim_id"]


def test_discharge_ready_day_matches_days_after_criteria(cases):
    for c in cases:
        after = c["clinical"]["days_after_discharge_criteria"]
        ready = [n["day"] for n in c["cppt"] if "layak pulang" in n["P"]]
        assert ready == [c["scenario"]["lama_rawat"] - after], c["claim_id"]


def test_undocumented_billed_items_are_billed_but_not_in_cppt(cases):
    for c in cases:
        billed = {it["name"] for it in c["billing"]}
        for item in c["undocumented_billed_items"]:
            assert item in billed
            assert item.lower() not in _text(c)


def test_missing_documents(cases, truths):
    for c, t in zip(cases, truths):
        missing = c["scenario"].get("dokumen_tidak_ada", [])
        assert t["docs"]["missing"] == [d for d in REQUIRED_DOCS if d in missing]
        for d in missing:
            assert d not in c["documents"]


# --- Template ----------------------------------------------------------------------


def test_every_document_carries_synthetic_label(cases):
    from synthetic.render_pdf import render_html

    case = cases[0]
    for doc in case["documents"]:
        html = render_html(case, doc)
        assert html.count("DATA REKAAN") >= 2
        assert case["patient"]["name"] in html
