"""Tes U7: underwriting medis. Pipeline dan aturan atas kasus sintetis (DATA REKAAN), lalu alur API:
underwriter mengajukan, sistem membuat draf, dokter menandatangani, underwriter memutuskan.
Jaminan utama: tidak ada calon peserta yang ditolak (atau diterima bersyarat / ditunda) tanpa tanda tangan dokter."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from mab_api.models import AuditLog, User, UwApplication
from mab_api.security import hash_secret
from mab_pipeline.llm.mock import MockLLMClient
from mab_pipeline.ocr.engine import NullOCREngine
from mab_pipeline.rules.loader import RuleValidationError
from mab_pipeline.tasks import process_underwriting
from mab_pipeline.underwriting.pipeline import InputDocument, assess_application, guess_uw_doc_type
from mab_pipeline.underwriting.rules import apply_rules, load_uw_rules

FIXTURES = Path(__file__).parent / "fixtures" / "underwriting_sintetis"
CASES = FIXTURES / "underwriting"
PIN = "246810"


@pytest.fixture
def uw_llm():
    return MockLLMClient(fixtures_dir=FIXTURES)


@pytest.fixture
def uw_rules():
    return load_uw_rules()


def _inputs(case: str) -> list[InputDocument]:
    return [InputDocument(p.stem, p.name, "application/pdf", p.read_bytes(), guess_uw_doc_type(p.name))
            for p in sorted((CASES / case).glob("*.pdf"))]


# ----------------------------------------------------------------------------- pipeline & aturan


@pytest.mark.parametrize("case,cls,rec,loading,exclusions", [
    ("UW-01", "STANDARD", "ACCEPT_STANDARD", 0, []),
    ("UW-22", "DECLINE", "DECLINE", 0, []),
    ("UW-26", "SUB1", "ACCEPT_CONDITIONAL", 25, ["HBSAG_POSITIVE"]),
    ("UW-29", "POSTPONE", "POSTPONE", 0, []),
])
def test_pipeline_matches_answer_key_with_evidence(case, cls, rec, loading, exclusions, uw_llm, uw_rules):
    r = assess_application(_inputs(case), uw_llm, NullOCREngine(), uw_rules)
    o = r.outcome
    assert (o.risk_class, o.recommendation, o.loading_pct) == (cls, rec, loading)
    assert sorted(e["reason_code"] for e in o.exclusions) == exclusions
    assert o.needs_doctor == (rec != "ACCEPT_STANDARD")
    assert not o.missing_docs and not o.missing_fields and not o.skipped
    # setiap temuan menunjuk baris dokumen yang benar-benar ada
    evidence = r.evidence()
    for f in o.findings:
        assert f["line_ids"] and all(i in evidence for i in f["line_ids"]), f
    assert r.fields["vital.bmi"]["source"] == "hitung" and r.fields["vital.bmi"]["line_ids"]


def test_missing_document_never_concludes_standard(uw_llm, uw_rules):
    inputs = [i for i in _inputs("UW-01") if i.doc_type_hint != "hasil_lab_uw"]
    o = assess_application(inputs, uw_llm, NullOCREngine(), uw_rules).outcome
    assert o.missing_docs == ["hasil_lab_uw"]
    assert o.recommendation == "POSTPONE" and o.needs_doctor
    assert any(f["reason_code"] == "INCOMPLETE_DATA" for f in o.findings)


def test_rules_aggregate_debits_classes_and_decline_threshold(uw_rules):
    base = {"applicant.age": 40, "vital.bmi": 22.0, "vital.systolic": 120, "vital.diastolic": 80,
            "lab.fasting_glucose": 90, "lab.total_cholesterol": 180, "lab.sgpt": 20, "lab.creatinine": 0.9,
            "lab.hba1c": 5.2, "doctor.letter": False}
    docs = set(uw_rules.required_docs)

    def run(**over):
        fields = {k: {"value": v, "line_ids": ["L1"]} for k, v in (base | {k.replace("__", "."): v for k, v in over.items()}).items()}
        return apply_rules(uw_rules, fields, docs)

    assert run().recommendation == "ACCEPT_STANDARD"
    o = run(vital__bmi=36.0, lab__hba1c=7.0, applicant__smoker=True)       # 50 + 50 + 25
    assert (o.debit_total, o.risk_class, o.loading_pct, o.recommendation) == (125, "SUB4", 125, "ACCEPT_CONDITIONAL")
    o = run(vital__bmi=41.0, lab__hba1c=8.5)                                # 100 + 100 > 150
    assert (o.risk_class, o.recommendation) == ("DECLINE", "DECLINE")
    o = run(lab__hba1c=10.5)                                                # aturan usul tolak
    assert o.recommendation == "DECLINE" and o.needs_doctor
    o = run(history__asthma=True)                                           # pengecualian tanpa debit
    assert (o.risk_class, o.recommendation, o.loading_pct) == ("STANDARD", "ACCEPT_CONDITIONAL", 0)
    o = run(vital__systolic=None)                                           # data wajib tidak terbaca
    assert o.recommendation == "POSTPONE" and "vital.systolic" in o.missing_fields


def test_rule_file_validation_reports_errors(tmp_path):
    bad = tmp_path / "uw.yaml"
    bad.write_text("""
version: x
batas_debit_tolak: 150
kamus_data: {lab.hba1c: {tipe: angka}}
kelas_risiko: [{kode: STANDARD, nama: Standar, debit_maks: 0}]
aturan:
  - {id: A, nama: a, kondisi: "lab.unknown > 1", kode_alasan: X, pesan: p, debit: 25}
  - {id: B, nama: b, kondisi: "__import__('os')", kode_alasan: X, pesan: p, debit: 25}
  - {id: C, nama: c, kondisi: "lab.hba1c > 1", kode_alasan: X, pesan: p}
""", encoding="utf-8")
    with pytest.raises(RuleValidationError) as exc:
        load_uw_rules(bad)
    text = str(exc.value)
    assert "lab.unknown" in text and "B" in text and "butuh salah satu" in text


# ----------------------------------------------------------------------------- API


@pytest.fixture
def uw(client, login, session_factory, storage, uw_llm, uw_rules, users):
    with session_factory() as db:
        for key in ("dokter_umum", "spesialis"):
            db.get(User, users[key]).pin_hash = hash_secret(PIN)
        db.commit()

    def submit(case: str) -> dict:
        files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in sorted((CASES / case).glob("*.pdf"))]
        r = client.post("/underwriting/applications", files=files, headers=login("underwriter"))
        assert r.status_code == 201, r.text
        app_id = r.json()["id"]
        process_underwriting(app_id, session_factory=session_factory, storage=storage, llm=uw_llm,
                             ocr=NullOCREngine(), ruleset=uw_rules)
        return client.get(f"/underwriting/applications/{app_id}", headers=login("underwriter")).json()

    return submit


def test_standard_case_goes_straight_to_underwriter(client, login, uw):
    app = uw("UW-01")
    assert app["status"] == "AWAITING_UNDERWRITER" and app["recommendation"] == "ACCEPT_STANDARD"
    assert app["applicant_name"] and app["spaj_number"] == "SPAJ-2026-0001"
    assert app["allowed_decisions"] == ["ACCEPT_STANDARD"]
    assert app["assessment"]["rules_version"] and app["assessment"]["model_version"] == "mock-llm-1"
    r = client.post(f"/underwriting/applications/{app['id']}/decision", json={"decision": "ACCEPT_STANDARD"},
                    headers=login("underwriter"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "DECIDED" and d["decision_detail"]["final_premium"] == app["base_premium"]


def test_no_decline_without_doctor_signature(client, login, uw, session_factory):
    app = uw("UW-22")
    assert app["status"] == "AWAITING_DOCTOR" and app["recommendation"] == "DECLINE"
    assert app["terms"]["source"] == "system"
    uwh = login("underwriter")
    # underwriter tidak bisa memutus selama belum ditandatangani dokter
    r = client.post(f"/underwriting/applications/{app['id']}/decision", json={"decision": "DECLINE"}, headers=uwh)
    assert r.status_code == 409
    # underwriter tidak bisa menandatangani; dokter wajib PIN yang benar
    assert client.post(f"/underwriting/applications/{app['id']}/sign", json={"action": "AGREE", "pin": PIN},
                       headers=uwh).status_code == 403
    doc = login("spesialis")
    assert client.post(f"/underwriting/applications/{app['id']}/sign", json={"action": "AGREE", "pin": "000000"},
                       headers=doc).status_code == 403
    queue = client.get("/underwriting/applications", headers=doc).json()
    assert [a["id"] for a in queue["items"]] == [app["id"]]
    r = client.post(f"/underwriting/applications/{app['id']}/sign", json={"action": "AGREE", "pin": PIN}, headers=doc)
    assert r.status_code == 200, r.text
    signed = client.get(f"/underwriting/applications/{app['id']}", headers=uwh).json()
    assert signed["status"] == "AWAITING_UNDERWRITER" and signed["review"]["doctor"] == "Pengguna spesialis"
    assert signed["allowed_decisions"] == ["ACCEPT_STANDARD", "DECLINE"]
    r = client.post(f"/underwriting/applications/{app['id']}/decision", json={"decision": "DECLINE"}, headers=uwh)
    assert r.status_code == 200 and r.json()["decision_detail"]["final_premium"] is None
    with session_factory() as db:
        actions = [a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]
        assert {"UW_SUBMITTED", "UW_PROCESSED", "UW_SIGN_PIN_FAILED", "UW_SIGNED", "UW_DECIDED"} <= set(actions)
        # setiap pengajuan yang ditolak punya tanda tangan dokter dengan rekomendasi tolak
        for a in db.scalars(select(UwApplication)):
            for d in a.decisions:
                if d.decision != "ACCEPT_STANDARD":
                    rev = next(r for r in a.reviews if r.id == d.review_id)
                    assert rev.recommendation == d.decision


def test_decision_must_match_signed_recommendation(client, login, uw):
    app = uw("UW-26")
    assert app["recommendation"] == "ACCEPT_CONDITIONAL" and app["status"] == "AWAITING_DOCTOR"
    doc = login("dokter_umum")
    # mengubah draf wajib dengan catatan
    body = {"action": "MODIFY", "recommendation": "POSTPONE", "pin": PIN}
    assert client.post(f"/underwriting/applications/{app['id']}/sign", json=body, headers=doc).status_code == 422
    body["notes"] = "Minta hasil HBV DNA dan USG hati dulu."
    assert client.post(f"/underwriting/applications/{app['id']}/sign", json=body, headers=doc).status_code == 200
    uwh = login("underwriter")
    for decision in ("DECLINE", "ACCEPT_CONDITIONAL"):
        r = client.post(f"/underwriting/applications/{app['id']}/decision", json={"decision": decision}, headers=uwh)
        assert r.status_code == 409, decision
    # terima standar (lebih menguntungkan calon peserta) boleh, tetapi wajib beralasan
    r = client.post(f"/underwriting/applications/{app['id']}/decision", json={"decision": "ACCEPT_STANDARD"}, headers=uwh)
    assert r.status_code == 422
    r = client.post(f"/underwriting/applications/{app['id']}/decision", json={"decision": "POSTPONE"}, headers=uwh)
    assert r.status_code == 200 and r.json()["decision_detail"]["decision"] == "POSTPONE"
    pdf = client.get(f"/underwriting/applications/{app['id']}/pdf", headers=uwh)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_underwriting_access_by_role(client, login, uw):
    app = uw("UW-29")
    for key in ("staf", "manajer", "faskes", "peserta", "tpa"):
        assert client.get("/underwriting/applications", headers=login(key)).status_code == 403, key
    assert client.get(f"/underwriting/applications/{app['id']}", headers=login("auditor")).status_code == 200
    assert client.get(f"/underwriting/applications/{app['id']}", headers=login("admin")).status_code == 200
    # dokter tidak bisa mengajukan; underwriter tidak melihat data klaim
    files = [("files", ("spaj.pdf", (CASES / "UW-29" / "spaj.pdf").read_bytes(), "application/pdf"))]
    assert client.post("/underwriting/applications", files=files, headers=login("dokter_umum")).status_code == 403
    assert client.get("/claims", headers=login("underwriter")).status_code == 403
    assert client.get("/underwriting/rules", headers=login("underwriter")).json()["version"]
