"""Tes M5: cek bukti, penalaran klinis, aturan + bukti, rekomendasi, job worker sampai rekomendasi."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from mab_api.models import AuditLog, Claim, Recommendation
from mab_pipeline.documents import LoadedDocument, PageContent, TextLine
from mab_pipeline.extraction.facts import BillingFacts, BillingItem
from mab_pipeline.llm.mock import MockLLMClient
from mab_pipeline.ocr.engine import NullOCREngine
from mab_pipeline.pipeline import InputDocument, assess_claim, read_claim
from mab_pipeline.reasoning.clinical_reasoner import ai_fields_for, reason
from mab_pipeline.reasoning.evidence_check import EvidenceIndex
from mab_pipeline.rules import load_rules
from mab_pipeline.schemas import ClaimData, Finding, InitialRecommendation, Severity, TriageResult, TriageStatus
from mab_pipeline.tasks import process_claim
from mab_pipeline.triage.recommender import build_recommendation
from synthetic.generate_cases import answer_key_rows

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "klaim_sintetis"
CLAIM_IDS = ["SYN-DEN-09", "SYN-TIF-06", "SYN-GEA-07", "SYN-GEA-02"]
DOC_TYPES = ["resume_medis", "hasil_laboratorium", "cppt", "rincian_tagihan"]


@pytest.fixture(scope="module")
def ruleset():
    return load_rules(ROOT / "rules" / "aturan_klinis_demo.yaml")


@pytest.fixture
def mock_llm():
    return MockLLMClient(fixtures_dir=FIXTURES)


def _case(claim_id):
    return json.loads((FIXTURES / claim_id / "case.json").read_text(encoding="utf-8"))


def _inputs(claim_id):
    return [InputDocument(f"doc-{t}", f"{t}.pdf", "application/pdf", (FIXTURES / claim_id / f"{t}.pdf").read_bytes())
            for t in DOC_TYPES]


def _doc(*texts, doc_type="cppt"):
    lines = [TextLine(f"D1-P1-L{i}", "doc1", 1, t, (0.1, 0.05 * i, 0.9, 0.05 * i + 0.03)) for i, t in enumerate(texts, 1)]
    return LoadedDocument("doc1", "cppt.pdf", [PageContent(1, "digital", lines)], doc_type=doc_type)


# --- cek bukti --------------------------------------------------------------------------


def test_quote_found_exactly_and_with_ocr_noise():
    index = EvidenceIndex([_doc("S: Demam tinggi 3 hari; muntah terus-menerus setiap diberi makan/minum", "O: TD 110/70 mmHg")])
    exact = index.find("muntah terus-menerus setiap diberi makan/minum")
    assert exact and exact.score == 1.0 and exact.lines[0].id == "D1-P1-L1"
    noisy = index.find("muntah terus menerus setiap diberi rnakan/minum")  # spasi & 'rn' hasil OCR
    assert noisy and noisy.score >= 0.9


def test_quote_spanning_two_lines_is_found():
    index = EvidenceIndex([_doc("O: Mata sangat cekung, turgor kulit kembali sangat lambat, malas minum;", "kesan dehidrasi berat; Sp.PD")])
    m = index.find("malas minum; kesan dehidrasi berat")
    assert m and [l.id for l in m.lines] == ["D1-P1-L1", "D1-P1-L2"]
    [ev] = m.to_evidence("clin.dehydration")
    assert ev["line_ids"] == ["D1-P1-L1", "D1-P1-L2"] and ev["page"] == 1 and ev["field"] == "clin.dehydration"


@pytest.mark.parametrize("quote", ["efusi pleura kanan minimal", "pasien syok dengan akral dingin", "", "nadi"])
def test_fabricated_or_too_short_quotes_are_not_found(quote):
    index = EvidenceIndex([_doc("S: Demam tinggi 3 hari, nyeri kepala", "O: TD 110/70 mmHg, nadi 96x/menit")])
    assert index.find(quote) is None


# --- penalaran klinis ---------------------------------------------------------------------


def test_ai_fields_follow_rules_of_matched_diagnosis(ruleset):
    dengue = ai_fields_for(ruleset, "A91")
    assert "clin.warning_signs" in dengue and "clin.plasma_leakage" in dengue and "clin.dehydration" not in dengue
    assert "clin.dehydration" in ai_fields_for(ruleset, "A09")
    assert ai_fields_for(ruleset, "J18.9") == ["bill.items_without_clinical_note"]


class Scripted:
    model_version = "uji"

    def __init__(self, *answers):
        self.answers = [a if isinstance(a, str) else json.dumps(a) for a in answers]
        self.prompts = []

    def complete_json(self, system, user, *, task, context):
        self.prompts.append((system, user))
        return self.answers.pop(0)


def _doc_dengue():
    return _doc("S: Demam tinggi 3 hari; nyeri perut kanan atas", "O: TD 110/70 mmHg; Lab: trombosit 95.000",
                "P: Bebas demam > 48 jam. Pasien layak pulang.")


def test_unverified_positive_value_becomes_null_not_false(ruleset):
    answer = {"fields": {
        "clin.plasma_leakage": {"value": True, "quotes": ["efusi pleura kanan minimal"]},       # tidak ada di dokumen
        "clin.shock": {"value": False, "quotes": []},                                           # tidak ada -> dipakai
        "clin.warning_signs": {"value": [{"item": "nyeri abdomen", "quote": "nyeri perut kanan atas"},
                                         {"item": "letargi", "quote": "pasien tampak letargis"}]},
        "clin.days_after_discharge_criteria": {"value": 2, "quotes": ["Pasien layak pulang"]},
        "clin.comorbidities": {"value": [{"item": "diabetes", "quote": "riwayat diabetes melitus"}]},
    }}
    result = reason(Scripted(answer), [_doc_dengue()], ruleset, "A91")
    f = result.fields
    assert f["clin.plasma_leakage"].value is None and f["clin.plasma_leakage"].status == "unverified"
    assert f["clin.shock"].value is False and f["clin.shock"].status == "absent"
    assert f["clin.warning_signs"].value == ["nyeri abdomen"]          # item tanpa bukti dibuang
    assert f["clin.warning_signs"].evidence[0]["line_ids"] == ["D1-P1-L1"]
    assert f["clin.days_after_discharge_criteria"].value == 2 and f["clin.days_after_discharge_criteria"].status == "verified"
    assert f["clin.comorbidities"].value is None                       # semua item gugur -> null, bukan []
    assert f["clin.spontaneous_bleeding"].value is None                # tidak dijawab -> tidak diketahui
    assert set(result.unverified) == {"clin.plasma_leakage", "clin.comorbidities"}
    assert any("kutipan tidak ditemukan" in w for w in result.warnings)


def test_reasoner_retries_once_then_fails(ruleset):
    ok = {"fields": {"clin.shock": {"value": False}}}
    llm = Scripted({"hasil": []}, ok)
    assert reason(llm, [_doc_dengue()], ruleset, "A91").status == "retried"
    assert "tidak valid" in llm.prompts[1][1]
    failed = reason(Scripted("bukan json", {"fields": {"clin.shock": {"value": "mungkin"}}}), [_doc_dengue()], ruleset, "A91")
    assert failed.status == "failed" and all(f.value is None for f in failed.fields.values())


def test_prompt_lists_requested_fields_and_documents(ruleset):
    llm = Scripted({"fields": {}})
    reason(llm, [_doc_dengue()], ruleset, "A91")
    system, user = llm.prompts[0]
    requested = system.split("Field yang diminta:")[1].split("Petunjuk khusus:")[0]
    assert "clin.warning_signs" in requested and "clin.dehydration" not in requested
    assert "[D1-P1-L1] S: Demam tinggi" in user and "A91" in user


def test_items_without_note_counts_only_verified_items(ruleset):
    bill = _doc("12 9 Maret 10:00 USG Abdomen 1 450.000 450.000", doc_type="rincian_tagihan")
    answer = {"fields": {"bill.items_without_clinical_note": {"value": [
        {"item": "USG Abdomen", "quote": "USG Abdomen 1 450.000"}, {"item": "Endoskopi", "quote": "Endoskopi 2.500.000"}]}}}
    f = reason(Scripted(answer), [bill], ruleset, "J18.9").fields["bill.items_without_clinical_note"]
    assert f.value == 1 and f.items == ["usg abdomen"]


# --- rekomendasi ----------------------------------------------------------------------------


def _triage(*findings, status=TriageStatus.GREEN, rec=InitialRecommendation.PAY_FULL):
    return TriageResult(claim_id="X", ruleset_version="uji", matched_diagnosis=None, triage_status=status, risk_score=0,
                        initial_recommendation=rec, findings=list(findings))


def _finding(rule_id, code, sev, fields, needs_ai=True):
    return Finding(rule_id=rule_id, rule_name=rule_id, reason_code=code, severity=sev, needs_ai_evidence=needs_ai,
                   message=f"pesan {rule_id}", fields_used=fields)


EV = {"doc": "d1", "page": 1, "bbox": [0, 0, 1, 1], "quote": "kutipan", "line_ids": ["D1-P1-L1"]}


def test_green_claim_is_pay_full(ruleset):
    d = build_recommendation(_triage(), ClaimData(), ruleset, {}, 5_000_000)
    assert (d.triage_status, d.recommendation, d.recommended_amount) == ("GREEN", "PAY_FULL", 5_000_000)
    assert "dibayar penuh" in d.explanation_text


def test_ai_finding_without_evidence_is_dropped_but_claim_not_green(ruleset):
    f = _finding("GEA-03", "DRUG_NOT_INDICATED", Severity.MEDIUM, ["tx.antibiotic_given", "clin.bloody_diarrhea"])
    d = build_recommendation(_triage(f, status=TriageStatus.YELLOW, rec=InitialRecommendation.DOCTOR_REVIEW), ClaimData(), ruleset, {}, 1000)
    assert d.findings == [] and d.dropped_findings == ["GEA-03"]
    assert d.triage_status == "YELLOW" and d.recommendation == "DOCTOR_REVIEW"
    assert [q["code"] for q in d.quality_flags] == ["FINDING_WITHOUT_EVIDENCE"]


def test_findings_carry_evidence_of_fields_used(ruleset):
    f = _finding("GEA-03", "DRUG_NOT_INDICATED", Severity.MEDIUM, ["tx.antibiotic_given", "clin.bloody_diarrhea"])
    d = build_recommendation(_triage(f, status=TriageStatus.YELLOW, rec=InitialRecommendation.DOCTOR_REVIEW),
                             ClaimData(), ruleset, {"tx.antibiotic_given": [EV]}, 1000)
    assert d.findings[0].evidence == [EV] and d.findings[0].guideline_refs


def test_unreadable_documents_never_green(ruleset):
    d = build_recommendation(_triage(), ClaimData(), ruleset, {}, 1000, quality=["DOC_UNREADABLE"])
    assert (d.triage_status, d.recommendation) == ("YELLOW", "PEND")
    assert "Minta dokumen yang bisa dibaca" in d.next_action


def test_duplicate_items_become_line_adjustments(ruleset):
    item = dict(date=date(2026, 3, 9), time="12:00", name="Pemeriksaan Darah Lengkap", qty=1, unit_price=95_000, source_line_ids=["L1"])
    billing = BillingFacts(items=[BillingItem(**item), BillingItem(**item)])
    f = _finding("GEN-02", "DUP_ITEM", Severity.MEDIUM, ["bill.duplicate_items"], needs_ai=False)
    d = build_recommendation(_triage(f, status=TriageStatus.YELLOW, rec=InitialRecommendation.DOCTOR_REVIEW),
                             ClaimData(), ruleset, {"bill.duplicate_items": [EV]}, 1_000_000, billing=billing)
    assert [a["amount"] for a in d.line_adjustments] == [95_000]
    assert d.recommended_amount == 905_000
    assert "Rp95.000" in d.explanation_text and "ditolak" not in d.explanation_text.lower()


# --- alur lengkap ---------------------------------------------------------------------------


@pytest.mark.parametrize("claim_id", CLAIM_IDS)
def test_assessment_matches_answer_key_with_traceable_evidence(claim_id, ruleset, mock_llm):
    case = _case(claim_id)
    [key] = answer_key_rows([case])
    read = read_claim(_inputs(claim_id), mock_llm, NullOCREngine(), claim_id)
    a = assess_claim(read, ruleset, mock_llm, 5_000_000, claim_id)
    d = a.recommendation
    assert (d.triage_status, d.recommendation) == (key["status_triase_harapan"], key["rekomendasi_harapan"])
    assert [f.rule_id for f in d.findings] == [r for r in key["aturan_harapan"].split(";") if r]
    for f in d.findings:
        assert any(e.get("doc") and e.get("page") and e.get("quote") for e in f.evidence), f.rule_id
    assert d.quality_flags == []
    assert a.prompt_version == "extract_v1+clinical_v1" and a.ruleset_version == ruleset.version
    # nilai klinis AI sama dengan kebenaran skenario
    for path in a.reasoning.fields:
        if path.startswith("clin."):
            assert a.fields[path].value == case["clinical"][path[5:]], path


# --- job worker -----------------------------------------------------------------------------


def _create_and_upload(client, headers, claim_id, number=None, member="PST-REKAAN-1"):
    case = _case(claim_id)
    body = {"claim_number": number or claim_id, "policy_number": "POL-DEMO-1", "member_id": member, "hospital_name": "RS rekaan",
            "admission_date": case["admission_date"], "discharge_date": case["discharge_date"], "billed_amount": case["billing_total"]}
    claim = client.post("/claims", json=body, headers=headers).json()
    files = [("files", (f"{t}.pdf", (FIXTURES / claim_id / f"{t}.pdf").read_bytes(), "application/pdf")) for t in DOC_TYPES]
    assert client.post(f"/claims/{claim['id']}/documents", files=files, headers=headers).status_code == 201
    return claim


def test_problem_claim_waits_for_doctor_and_is_hidden_from_insurer(client, login, session_factory, storage, mock_llm, ruleset):
    headers = login("staf")
    claim = _create_and_upload(client, headers, "SYN-TIF-06")
    status = process_claim(claim["id"], session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine(), ruleset=ruleset)
    assert status == "AWAITING_DOCTOR"
    # selain bayar penuh: asuransi belum boleh melihat sebelum ditandatangani dokter
    assert client.get(f"/claims/{claim['id']}/recommendation", headers=headers).status_code == 409
    rec = client.get(f"/claims/{claim['id']}/recommendation", headers=login("spesialis")).json()
    assert rec["triage_status"] == "RED" and rec["recommendation"] == "DOCTOR_REVIEW" and rec["state"] == "DRAFT"
    assert [f["rule_id"] for f in rec["findings"]] == ["TIF-01", "TIF-03"]
    assert all(f["evidence"] and f["evidence"][0]["page"] == 1 and f["evidence"][0]["quote"] for f in rec["findings"])
    assert rec["prompt_version"] == "extract_v1+clinical_v1" and rec["model_version"] == "mock-llm-1"
    assert rec["ruleset_version"] == ruleset.version

    fields = {f["field_path"]: f for f in client.get(f"/claims/{claim['id']}/fields", headers=headers).json()}
    assert fields["clin.complication_documented"]["source"] == "ai" and fields["clin.complication_documented"]["status"] == "absent"
    with session_factory() as db:
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "PIPELINE_COMPLETED"))
        assert audit.detail["findings"] == ["TIF-01", "TIF-03"] and audit.detail["ruleset_version"] == ruleset.version


def test_green_claim_goes_straight_to_insurer(client, login, session_factory, storage, mock_llm, ruleset):
    headers = login("staf")
    claim = _create_and_upload(client, headers, "SYN-GEA-02")
    assert process_claim(claim["id"], session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine(),
                         ruleset=ruleset) == "AWAITING_DECISION"
    rec = client.get(f"/claims/{claim['id']}/recommendation", headers=headers).json()
    assert rec["recommendation"] == "PAY_FULL" and rec["recommended_amount"] == rec["billed_amount"] and rec["findings"] == []
    r = client.post(f"/claims/{claim['id']}/decision", json={"decision": "AGREE"}, headers=headers)
    assert r.status_code == 201


def test_overlapping_claim_triggers_duplicate_rule_and_reprocessing_versions(client, login, session_factory, storage, mock_llm, ruleset):
    headers = login("staf")
    claim = _create_and_upload(client, headers, "SYN-GEA-02")
    _create_and_upload(client, headers, "SYN-GEA-02", number="KLM-RIWAYAT-1")
    run = lambda: process_claim(claim["id"], session_factory=session_factory, storage=storage, llm=mock_llm,  # noqa: E731
                                ocr=NullOCREngine(), ruleset=ruleset)
    assert run() == "AWAITING_DOCTOR"
    rec = client.get(f"/claims/{claim['id']}/recommendation", headers=login("spesialis")).json()
    assert rec["triage_status"] == "RED" and [f["rule_id"] for f in rec["findings"]] == ["GEN-01"]
    assert "KLM-RIWAYAT-1" in rec["findings"][0]["evidence"][0]["quote"]
    run()
    with session_factory() as db:
        recs = db.scalars(select(Recommendation).where(Recommendation.claim_id == claim["id"])).all()
        assert sorted(r.version for r in recs) == [1, 2] and [r.is_current for r in sorted(recs, key=lambda r: r.version)] == [False, True]
        assert db.get(Claim, claim["id"]).status == "AWAITING_DOCTOR"
