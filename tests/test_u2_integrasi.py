"""Tes U2: aturan benefit polis, impor polis, API klaim masuk, FHIR, webhook, dan SFTP (semua data rekaan)."""
from __future__ import annotations

import copy
import datetime as dt
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook
from sqlalchemy import select

from mab_api.models import Claim, IntegrationJob, Recommendation, WebhookDelivery
from mab_api.webhooks import WebhookError, verify
from mab_pipeline.benefit import (
    PolicyInfo,
    benefit_adjustments,
    build_facts,
    load_benefit_rules,
    parse_benefit_rules,
    run_benefit_rules,
)
from mab_pipeline.extraction.facts import BillingItem
from mab_pipeline.ocr.engine import NullOCREngine
from mab_pipeline.rules import RuleValidationError
from mab_pipeline.tasks import deliver_webhook, process_claim
from tests.test_reasoning import FIXTURES, _create_and_upload, mock_llm, ruleset  # noqa: F401  (fixture)
from tests.test_tenants import SETTINGS

ROOT = Path(__file__).resolve().parents[1]
BENEFIT_FILE = ROOT / "rules" / "aturan_benefit_demo.yaml"
DOC_TYPES = ["resume_medis", "hasil_laboratorium", "cppt", "rincian_tagihan"]
SECRET = "rahasia-webhook-uji-1234"
sys.path.insert(0, str(ROOT / "infra" / "scripts"))


def _case(claim_id: str) -> dict:
    return json.loads((FIXTURES / claim_id / "case.json").read_text(encoding="utf-8"))


def _room_days(claim_id: str) -> int:
    return sum(b["qty"] for b in _case(claim_id)["billing"] if "kamar" in b["name"].lower())


@pytest.fixture
def run(client, login, session_factory, storage, mock_llm, ruleset, job_queue):  # noqa: F811
    def _run(claim_id: str, staff: str = "staf", member: str = "PST-1") -> str:
        claim = _create_and_upload(client, login(staff), claim_id, member=member)
        process_claim(claim["id"], session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine(),
                      ruleset=ruleset, job_queue=job_queue)
        return claim["id"]
    return _run


def _rec(session_factory, claim_id) -> Recommendation:
    with session_factory() as db:
        rec = db.scalar(select(Recommendation).where(Recommendation.claim_id == claim_id, Recommendation.is_current))
        _ = [f.evidence for f in rec.findings]
        db.expunge_all()
        return rec


def _plan(client, login, insurer_id, code, **kw):
    body = {"insurer_id": insurer_id, "code": code, "name": f"Plan {code}", "room_class": "Kelas 1",
            "room_rate_limit": 500_000, "annual_limit": 100_000_000, "waiting_period_days": 30, "excluded_icd10": [], **kw}
    r = client.put("/policies/plans", json=body, headers=login("admin"))
    assert r.status_code == 200, r.text
    return r.json()


def _import(client, headers, rows: list[str], insurer_id=None):
    csv_text = "nomor_polis,id_peserta,nama_peserta,kode_plan,tanggal_mulai,tanggal_akhir,status,limit_terpakai\n" + "\n".join(rows)
    data = {"insurer_id": insurer_id} if insurer_id else {}
    return client.post("/policies/import", files={"file": ("polis.csv", csv_text.encode(), "text/csv")}, data=data,
                       headers=headers)


# ----------------------------------------------------------------------------- aturan benefit (tanpa database)


def test_benefit_rules_file_is_valid_and_only_allows_policy_fields():
    rs = load_benefit_rules(BENEFIT_FILE)
    assert rs.version == "benefit-2026.11-demo"
    assert rs.rule_ids == {"BEN-00", "BEN-01", "BEN-02", "BEN-03", "BEN-04", "BEN-05"}
    doc = yaml.safe_load(BENEFIT_FILE.read_text(encoding="utf-8"))
    bad = copy.deepcopy(doc)
    bad["aturan"][0]["kondisi"] = "lab.platelet_min < 100000"  # field klinis tidak boleh di aturan benefit
    with pytest.raises(RuleValidationError):
        parse_benefit_rules(bad)
    bad = copy.deepcopy(doc)
    bad["aturan"][0]["kode_alasan"] = "TIDAK_ADA"
    with pytest.raises(RuleValidationError):
        parse_benefit_rules(bad)


def test_benefit_facts_findings_and_adjustments():
    rs = load_benefit_rules(BENEFIT_FILE)
    policy = PolicyInfo("POL-1", "PST-1", "SILVER", "Silver", dt.date(2026, 3, 1), dt.date(2027, 2, 28), room_class="Kelas 2",
                        room_rate_limit=300_000, annual_limit=10_000_000, limit_used=8_000_000, waiting_period_days=30,
                        excluded_icd10=("O", "A01"))
    items = [BillingItem(name="Kamar rawat inap kelas 1", qty=3, unit_price=450_000, source_line_ids=["L1"])]
    evidence = {"L1": [{"doc": "d1", "page": 1, "quote": "Kamar rawat inap kelas 1 3 x 450.000"}]}
    facts = build_facts(policy, dt.date(2026, 3, 10), ["A01.0"], 5_000_000, items, evidence)
    result = run_benefit_rules(rs, facts)
    assert [f.rule_id for f in result.findings] == ["BEN-02", "BEN-03", "BEN-04", "BEN-05"]
    msg = {f.rule_id: f.message for f in result.findings}
    assert "9 hari" in msg["BEN-02"] and "A01.0" in msg["BEN-03"]
    assert "Kelas 1 Rp450.000/hari" in msg["BEN-05"] and "Kelas 2 maksimal Rp300.000/hari" in msg["BEN-05"]
    # bukti: data polis, dan baris kamar di rincian tagihan
    assert facts.evidence["policy.excluded_dx"][0]["policy_number"] == "POL-1"
    assert facts.evidence["benefit.room_rate_billed"][0]["page"] == 1
    adj = benefit_adjustments(result, items, 5_000_000)
    assert [(a["reason_code"], a["amount"]) for a in adj] == [("ROOM_CLASS_EXCEEDED", 450_000), ("LIMIT_EXCEEDED", 2_550_000)]

    # polis aktif, di luar masa tunggu, tanpa pengecualian: tidak ada temuan
    ok = PolicyInfo("POL-2", "PST-2", "GOLD", "Gold", dt.date(2025, 1, 1), dt.date(2026, 12, 31), room_rate_limit=500_000,
                    annual_limit=100_000_000)
    assert run_benefit_rules(rs, build_facts(ok, dt.date(2026, 3, 10), ["A90"], 5_000_000, items, {})).findings == []
    # polis kedaluwarsa
    lapsed = run_benefit_rules(rs, build_facts(ok, dt.date(2027, 1, 5), ["A90"], 1, items, {}))
    assert [f.rule_id for f in lapsed.findings] == ["BEN-01"]
    # polis tidak ditemukan: hanya BEN-00, sisanya tidak bisa dinilai
    missing = run_benefit_rules(rs, build_facts(None, dt.date(2026, 3, 10), ["A90"], 1, items, {}))
    assert [f.rule_id for f in missing.findings] == ["BEN-00"]


# ----------------------------------------------------------------------------- polis


def test_policy_import_plans_and_access(client, login, users):
    a = users["insurer_a"]
    _plan(client, login, a, "SILVER")
    assert client.put("/policies/plans", json={"code": "GOLD", "name": "Plan Gold", "excluded_icd10": ["o", "z30"]},
                      headers=login("staf")).json()["excluded_icd10"] == ["O", "Z30"]
    bad_icd = client.put("/policies/plans", json={"code": "X1", "name": "Plan X", "excluded_icd10": ["12;drop"]}, headers=login("staf"))
    assert bad_icd.status_code == 422

    r = _import(client, login("staf"), ["POL-1,PST-1,Peserta Satu,SILVER,2026-01-01,2026-12-31,ACTIVE,0",
                                         "POL-2,PST-2,Peserta Dua,GOLD,01/01/2026,31/12/2026,ACTIVE,1.500.000",
                                         "POL-3,PST-3,Peserta Tiga,PLATINUM,2026-01-01,2026-12-31,ACTIVE,0"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["created"], body["updated"]) == ("PARTIAL", 2, 0)
    assert "PLATINUM" in body["errors"][0]
    again = _import(client, login("staf"), ["POL-1,PST-1,Peserta Satu,SILVER,2026-01-01,2026-12-31,LAPSED,250000"]).json()
    assert (again["created"], again["updated"]) == (0, 1)

    policies = {p["policy_number"]: p for p in client.get("/policies", headers=login("staf")).json()}
    assert policies["POL-1"]["status"] == "LAPSED" and policies["POL-1"]["limit_remaining"] == 100_000_000 - 250_000
    assert policies["POL-2"]["limit_used"] == 1_500_000
    assert [p["policy_number"] for p in client.get("/policies?q=Dua", headers=login("staf")).json()] == ["POL-2"]
    plans = {p["code"]: p["policy_count"] for p in client.get("/policies/plans", headers=login("staf")).json()}
    assert plans == {"GOLD": 1, "SILVER": 1}

    # cakupan: tenant lain 404, auditor hanya baca, peran lain ditolak
    assert client.get(f"/policies?insurer_id={a}", headers=login("staf_b")).status_code == 404
    assert client.get("/policies", headers=login("staf_b")).json() == []
    assert len(client.get("/policies", headers=login("auditor")).json()) == 2
    assert _import(client, login("auditor"), []).status_code == 403
    for role in ("faskes", "peserta", "dokter_umum", "underwriter"):
        assert client.get("/policies", headers=login(role)).status_code == 403
    assert client.get("/policies", headers=login("admin")).status_code == 422  # admin wajib memilih tenant
    jobs = client.get(f"/tenants/{a}/integration-jobs", headers=login("staf")).json()
    assert [j["channel"] for j in jobs] == ["POLICY_IMPORT", "POLICY_IMPORT"]
    assert client.get(f"/tenants/{a}/integration-jobs", headers=login("staf_b")).status_code == 404


def test_benefit_findings_enter_triage_and_adjust_amount(client, login, users, run, session_factory):
    a = users["insurer_a"]
    _plan(client, login, a, "K2", room_class="Kelas 2", room_rate_limit=300_000, annual_limit=10_000_000)
    _plan(client, login, a, "K1", excluded_icd10=["A90"])
    assert _import(client, login("staf"), ["POL-1,PST-1,Peserta Satu,K2,2025-01-01,2026-12-31,ACTIVE,9000000",
                                            "POL-2,PST-2,Peserta Dua,K1,2025-01-01,2026-12-31,ACTIVE,0"]).json()["created"] == 2

    # SYN-GEA-02 hijau secara klinis; polis PST-1: kamar di atas hak (LOW) + melebihi sisa limit (MEDIUM) -> kuning
    claim = run("SYN-GEA-02", member="PST-1")
    rec = _rec(session_factory, claim)
    assert rec.benefit_ruleset_version == "benefit-2026.11-demo"
    assert sorted(f.rule_id for f in rec.findings) == ["BEN-04", "BEN-05"]
    assert (rec.triage_status, rec.risk_score, rec.recommendation) == ("YELLOW", 30, "DOCTOR_REVIEW")
    room = next(f for f in rec.findings if f.rule_id == "BEN-05")
    assert any(e.get("policy_number") == "POL-1" for e in room.evidence) and any(e.get("page") for e in room.evidence)
    billed = _case("SYN-GEA-02")["billing_total"]
    room_adj = (450_000 - 300_000) * _room_days("SYN-GEA-02")
    adj: dict[str, int] = {}
    for item in rec.line_adjustments:
        adj[item["reason_code"]] = adj.get(item["reason_code"], 0) + item["amount"]
    assert adj["ROOM_CLASS_EXCEEDED"] == room_adj
    assert adj["LIMIT_EXCEEDED"] == billed - room_adj - 1_000_000
    assert rec.recommended_amount == 1_000_000
    with session_factory() as db:
        c = db.get(Claim, claim)
        assert c.policy is not None and c.policy.policy_number == "POL-1"
    detail = client.get(f"/claims/{claim}", headers=login("staf")).json()
    assert detail["policy"]["plan_code"] == "K2" and detail["source"] == "PORTAL"
    fields = {f["field_path"]: f for f in client.get(f"/claims/{claim}/fields", headers=login("staf")).json()}
    assert fields["policy.number"]["value"] == "POL-1" and fields["policy.number"]["source"] == "polis"

    # diagnosis dikecualikan (A90 pada SYN-DEN-09) -> HIGH -> merah
    rec2 = _rec(session_factory, run("SYN-DEN-09", member="PST-2"))
    assert "BEN-03" in [f.rule_id for f in rec2.findings] and rec2.triage_status == "RED"
    # peserta tanpa polis -> BEN-00
    rec3 = _rec(session_factory, run("SYN-GEA-07", member="PST-TIDAK-ADA"))
    assert "BEN-00" in [f.rule_id for f in rec3.findings]

    # tenant tanpa data polis: aturan benefit tidak dijalankan
    rec_b = _rec(session_factory, run("SYN-GEA-02", "staf_b"))
    assert rec_b.benefit_ruleset_version is None and rec_b.triage_status == "GREEN"

    # aturan benefit bisa dimatikan per tenant
    assert client.put(f"/tenants/{a}/settings", json={**SETTINGS, "disabled_rules": ["BEN-00"]},
                      headers=login("admin")).status_code == 200
    unknown = client.put(f"/tenants/{a}/settings", json={**SETTINGS, "disabled_rules": ["BEN-99"]}, headers=login("admin"))
    assert unknown.status_code == 422


# ----------------------------------------------------------------------------- API masuk + webhook


def _key(client, login, insurer_id, scopes):
    r = client.post(f"/tenants/{insurer_id}/api-clients", json={"name": "Core uji", "scopes": scopes}, headers=login("admin"))
    assert r.status_code == 201, r.text
    return {"X-API-Key": r.json()["api_key"]}


def _metadata(claim_id: str, member="PST-1", number=None) -> str:
    case = _case(claim_id)
    return json.dumps({"claim_number": number or claim_id, "policy_number": "POL-1", "member_id": member,
                       "hospital_name": "RS rekaan", "admission_date": case["admission_date"],
                       "discharge_date": case["discharge_date"], "billed_amount": case["billing_total"]})


def _files(claim_id):
    return [("files", (f"{t}.pdf", (FIXTURES / claim_id / f"{t}.pdf").read_bytes(), "application/pdf")) for t in DOC_TYPES]


class FakePost:
    def __init__(self, codes=(200,)):
        self.codes = list(codes)
        self.calls: list[tuple[str, bytes, dict]] = []

    def __call__(self, url, content, headers):
        self.calls.append((url, content, headers))
        code = self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]
        return type("Resp", (), {"status_code": code})()


def test_api_inbound_claim_and_signed_webhooks(client, login, users, session_factory, storage, job_queue, mock_llm, ruleset):  # noqa: F811
    a = users["insurer_a"]
    r = client.put(f"/tenants/{a}/settings", json={**SETTINGS, "webhook_url": "http://sistem-inti.test/hook",
                                                   "webhook_secret": SECRET}, headers=login("admin"))
    assert r.status_code == 200 and r.json()["webhook_secret_set"] and "webhook_secret" not in r.json()
    # rahasia tidak terhapus saat pengaturan lain disimpan tanpa field rahasia
    assert client.put(f"/tenants/{a}/settings", json={**SETTINGS, "webhook_url": "http://sistem-inti.test/hook"},
                      headers=login("admin")).json()["webhook_secret_set"]

    read_only = _key(client, login, a, ["claims:read"])
    key = _key(client, login, a, ["claims:read", "claims:write"])
    assert client.get("/integrations/v1/whoami", headers=key).json()["scopes"] == ["claims:read", "claims:write"]
    assert client.post("/integrations/v1/claims", data={"metadata": _metadata("SYN-GEA-02")}, files=_files("SYN-GEA-02"),
                       headers=read_only).status_code == 403
    bad = client.post("/integrations/v1/claims", data={"metadata": "{}"}, files=_files("SYN-GEA-02"), headers=key)
    assert bad.status_code == 422 and "claim_number" in bad.json()["detail"]

    r = client.post("/integrations/v1/claims", data={"metadata": _metadata("SYN-GEA-02")}, files=_files("SYN-GEA-02"), headers=key)
    assert r.status_code == 202, r.text
    sent = r.json()
    assert (sent["status"], sent["source"], sent["documents"]) == ("QUEUED", "API", 4)
    dup = client.post("/integrations/v1/claims", data={"metadata": _metadata("SYN-GEA-02")}, files=_files("SYN-GEA-02"), headers=key)
    assert dup.status_code == 409
    jobs = client.get(f"/tenants/{a}/integration-jobs", headers=login("staf")).json()
    assert [(j["channel"], j["status"]) for j in jobs] == [("API", "FAILED"), ("API", "SUCCESS")]
    with session_factory() as db:
        claim = db.get(Claim, sent["claim_id"])
        assert claim.created_by_id is None and claim.api_client_id is not None
        assert all(d.uploaded_by_id is None for d in claim.documents)

    # bayar penuh -> dirilis -> webhook bertanda tangan
    before = len(job_queue.queue.jobs)
    assert process_claim(sent["claim_id"], session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine(),
                         ruleset=ruleset, job_queue=job_queue) == "AWAITING_DECISION"
    assert len(job_queue.queue.jobs) == before + 1
    with session_factory() as db:
        delivery = db.scalars(select(WebhookDelivery)).one()
        assert (delivery.event, delivery.status) == ("claim.recommendation_released", "PENDING")
        delivery_id = delivery.id
    post = FakePost([200])
    assert deliver_webhook(delivery_id, session_factory=session_factory, post=post) == "DELIVERED"
    url, body, headers = post.calls[0]
    assert url == "http://sistem-inti.test/hook" and headers["X-MAB-Event"] == "claim.recommendation_released"
    assert verify(SECRET, body, headers["X-MAB-Signature"]) and not verify("rahasia-lain-1234567", body, headers["X-MAB-Signature"])
    payload = json.loads(body)
    assert payload["claim"]["claim_number"] == "SYN-GEA-02" and payload["claim"]["recommendation"] == "PAY_FULL"
    assert payload["claim"]["source"] == "API" and payload["label"] == "Data rekaan untuk demonstrasi"
    status = client.get("/integrations/v1/claims/SYN-GEA-02", headers=key).json()
    assert status["recommendation"] == "PAY_FULL" and status["source"] == "API"

    # keputusan asuransi -> webhook kedua; kegagalan dicoba ulang lalu FAILED, bisa dikirim ulang
    assert client.post(f"/claims/{sent['claim_id']}/decision", json={"decision": "AGREE"}, headers=login("staf")).status_code == 201
    with session_factory() as db:
        second = db.scalars(select(WebhookDelivery).where(WebhookDelivery.event == "claim.decision_recorded")).one().id
    failing = FakePost([500])
    for attempt in (1, 2):
        with pytest.raises(WebhookError):
            deliver_webhook(second, session_factory=session_factory, post=failing)
    assert deliver_webhook(second, session_factory=session_factory, post=failing) == "FAILED"
    rows = client.get(f"/tenants/{a}/webhook-deliveries", headers=login("staf")).json()
    assert {(d["event"], d["status"]) for d in rows} == {("claim.recommendation_released", "DELIVERED"),
                                                          ("claim.decision_recorded", "FAILED")}
    assert client.post(f"/tenants/{a}/webhook-deliveries/{second}/resend", headers=login("staf")).status_code == 403
    resent = client.post(f"/tenants/{a}/webhook-deliveries/{second}/resend", headers=login("admin")).json()
    assert (resent["status"], resent["attempts"]) == ("PENDING", 0)

    # draf yang menunggu dokter tidak dikirim lewat webhook
    r = client.post("/integrations/v1/claims", data={"metadata": _metadata("SYN-TIF-06", "PST-2")}, files=_files("SYN-TIF-06"),
                    headers=key)
    assert process_claim(r.json()["claim_id"], session_factory=session_factory, storage=storage, llm=mock_llm,
                         ocr=NullOCREngine(), ruleset=ruleset, job_queue=job_queue) == "AWAITING_DOCTOR"
    with session_factory() as db:
        assert db.scalars(select(WebhookDelivery)).all().__len__() == 2


def test_policies_via_api_key(client, login, users):
    a = users["insurer_a"]
    _plan(client, login, a, "SILVER")
    key = _key(client, login, a, ["policies:write"])
    body = [{"nomor_polis": "POL-9", "id_peserta": "PST-9", "kode_plan": "SILVER", "tanggal_mulai": "2026-01-01",
             "tanggal_akhir": "2026-12-31"}]
    r = client.put("/integrations/v1/policies", json=body, headers=key)
    assert r.status_code == 200 and r.json()["created"] == 1
    assert client.get("/integrations/v1/claims", headers=key).status_code == 403  # tidak punya claims:read
    p = client.get("/policies", headers=login("staf")).json()[0]
    assert (p["policy_number"], p["source"]) == ("POL-9", "API")


# ----------------------------------------------------------------------------- FHIR


def test_fhir_bundle_in_and_claim_response_out(client, login, users, session_factory, storage, job_queue, mock_llm, ruleset):  # noqa: F811
    from make_fhir_bundle import build_bundle

    a = users["insurer_a"]
    key = _key(client, login, a, ["claims:read", "claims:write"])
    bundle = build_bundle(FIXTURES / "SYN-GEA-02")

    broken = copy.deepcopy(bundle)
    broken["entry"] = [e for e in broken["entry"] if e["resource"]["resourceType"] != "Coverage"]
    r = client.post("/integrations/v1/fhir", json=broken, headers=key)
    assert r.status_code == 422 and "Coverage" in r.json()["detail"]
    invalid = copy.deepcopy(bundle)
    invalid["entry"][0]["resource"]["birthDate"] = "bukan-tanggal"
    assert client.post("/integrations/v1/fhir", json=invalid, headers=key).status_code == 422

    r = client.post("/integrations/v1/fhir", json=bundle, headers=key)
    assert r.status_code == 202, r.text
    sent = r.json()
    assert (sent["source"], sent["documents"]) == ("FHIR", 4)
    case = _case("SYN-GEA-02")
    with session_factory() as db:
        claim = db.get(Claim, sent["claim_id"])
        assert claim.member_id == case["patient"]["member_id"] and claim.policy_number == case["patient"]["policy_no"]
        assert claim.billed_amount == case["billing_total"] and claim.primary_icd10 == case["icd10"]
        job = db.scalars(select(IntegrationJob).where(IntegrationJob.status == "SUCCESS")).one()
        assert job.channel == "FHIR" and job.summary["resources"]["DocumentReference"] == 4

    queued = client.get("/integrations/v1/fhir/ClaimResponse/SYN-GEA-02", headers=key)
    assert queued.headers["content-type"].startswith("application/fhir+json")
    assert queued.json()["outcome"] == "queued" and len(queued.json()["total"]) == 1
    process_claim(sent["claim_id"], session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine(),
                  ruleset=ruleset, job_queue=job_queue)
    done = client.get("/integrations/v1/fhir/ClaimResponse/SYN-GEA-02", headers=key).json()
    assert done["resourceType"] == "ClaimResponse" and done["outcome"] == "complete"
    assert {t["category"]["coding"][0]["code"]: t["amount"]["value"] for t in done["total"]} == {
        "submitted": case["billing_total"], "benefit": case["billing_total"]}
    assert client.get("/integrations/v1/fhir/ClaimResponse/SYN-GEA-02",
                      headers=_key(client, login, users["insurer_b"], ["claims:read"])).status_code == 404


# ----------------------------------------------------------------------------- SFTP


def _zip(claim_id: str, number: str) -> bytes:
    case = _case(claim_id)
    wb = Workbook()
    ws = wb.active
    ws.append(["folder", "nomor_klaim", "nomor_polis", "id_peserta", "nama_peserta", "nama_rs", "tanggal_masuk",
               "tanggal_keluar", "nilai_tagihan"])
    ws.append([claim_id, number, "POL-1", "PST-1", "Peserta rekaan", "RS rekaan", case["admission_date"],
               case["discharge_date"], case["billing_total"]])
    ws.append(["TIDAK-ADA", "Z-404", "POL-2", "PST-2", "Peserta rekaan", "RS rekaan", "2026-03-02", "2026-03-04", 1000])
    xbuf, zbuf = io.BytesIO(), io.BytesIO()
    wb.save(xbuf)
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("manifest.xlsx", xbuf.getvalue())
        for t in DOC_TYPES:
            z.writestr(f"{claim_id}/{t}.pdf", (FIXTURES / claim_id / f"{t}.pdf").read_bytes())
    return zbuf.getvalue()


def test_sftp_folder_in_and_out(tmp_path, client, login, users, session_factory, storage, job_queue, mock_llm, ruleset):  # noqa: F811
    from mab_pipeline.sftp_watcher import scan_once

    masuk = tmp_path / "A" / "masuk"
    masuk.mkdir(parents=True)
    (masuk / "kiriman1.zip").write_bytes(_zip("SYN-GEA-02", "SYN-GEA-02"))
    (masuk / "rusak.zip").write_bytes(b"bukan zip")
    result = {r["file"]: r for r in scan_once(session_factory, storage, job_queue, tmp_path, wait_stable=False)}
    assert result["kiriman1.zip"]["status"] == "PARTIAL" and result["kiriman1.zip"]["created"] == 1
    assert result["rusak.zip"]["status"] == "FAILED"
    assert not list(masuk.iterdir())
    assert len(list((tmp_path / "A" / "diproses").glob("*_kiriman1.zip"))) == 1
    assert len(list((tmp_path / "A" / "gagal").glob("*.error.txt"))) == 1
    for sub in ("masuk", "keluar", "diproses", "gagal"):
        assert (tmp_path / "B" / sub).is_dir()  # folder tenant lain dibuat juga

    hasil = (tmp_path / "A" / "keluar" / "hasil_kiriman1.csv").read_text(encoding="utf-8-sig").splitlines()
    assert hasil[0].startswith("baris,folder,nomor_klaim,diterima") and ",ya," in hasil[1] and "tidak ada di ZIP" in hasil[2]
    with session_factory() as db:
        claim = db.scalar(select(Claim).where(Claim.claim_number == "SYN-GEA-02"))
        assert (claim.source, claim.status) == ("SFTP", "QUEUED")
        claim_id = claim.id
    status_csv = (tmp_path / "A" / "keluar" / "status_klaim.csv").read_text(encoding="utf-8-sig").splitlines()
    assert status_csv[1].startswith("SYN-GEA-02,QUEUED,,,")

    process_claim(claim_id, session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine(),
                  ruleset=ruleset, job_queue=job_queue)
    scan_once(session_factory, storage, job_queue, tmp_path, wait_stable=False)
    status_csv = (tmp_path / "A" / "keluar" / "status_klaim.csv").read_text(encoding="utf-8-sig").splitlines()
    assert status_csv[1].startswith("SYN-GEA-02,AWAITING_DECISION,GREEN,PAY_FULL,")
    jobs = client.get(f"/tenants/{users['insurer_a']}/integration-jobs", headers=login("staf")).json()
    assert sorted(j["status"] for j in jobs if j["channel"] == "SFTP") == ["FAILED", "PARTIAL"]


# ----------------------------------------------------------------------------- penerima webhook demo


def test_demo_sink_checks_signature(client, login, users):
    from mab_api.webhooks import sign

    a = users["insurer_a"]
    client.put(f"/tenants/{a}/settings", json={**SETTINGS, "webhook_url": "http://api:8000/integrations/demo-sink/A",
                                               "webhook_secret": SECRET}, headers=login("admin"))
    body = json.dumps({"event": "claim.decision_recorded", "claim": {"claim_number": "X-1"}}).encode()
    assert client.post("/integrations/demo-sink/A", content=body, headers={"X-MAB-Signature": "sha256=salah"}).status_code == 401
    ok = client.post("/integrations/demo-sink/A", content=body,
                     headers={"X-MAB-Signature": sign(SECRET, body), "X-MAB-Event": "claim.decision_recorded"})
    assert ok.status_code == 200 and ok.json()["signature_valid"] is True
    log = client.get("/integrations/demo-sink", headers=login("staf")).json()
    assert log[0]["event"] == "claim.decision_recorded" and log[0]["payload"]["claim"]["claim_number"] == "X-1"
    assert client.get("/integrations/demo-sink", headers=login("staf_b")).json() == []


def test_benefit_rules_run_without_billing_document(client, login, users, session_factory, storage, mock_llm, ruleset):  # noqa: F811
    """Klaim tanpa rincian tagihan (dokumen tidak lengkap) tetap diproses; aturan kamar tidak bisa dinilai."""
    _plan(client, login, users["insurer_a"], "K1")
    _import(client, login("staf"), ["POL-1,PST-1,Peserta Satu,K1,2025-01-01,2026-12-31,ACTIVE,0"])
    case = _case("SYN-GEA-07")
    body = {"claim_number": "SYN-GEA-07", "policy_number": "POL-1", "member_id": "PST-1", "hospital_name": "RS rekaan",
            "admission_date": case["admission_date"], "discharge_date": case["discharge_date"], "billed_amount": case["billing_total"]}
    claim = client.post("/claims", json=body, headers=login("staf")).json()
    files = [("files", (f"{t}.pdf", (FIXTURES / "SYN-GEA-07" / f"{t}.pdf").read_bytes(), "application/pdf"))
             for t in ("resume_medis", "hasil_laboratorium")]
    assert client.post(f"/claims/{claim['id']}/documents", files=files, headers=login("staf")).status_code == 201
    status = process_claim(claim["id"], session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine(),
                           ruleset=ruleset)
    assert status == "AWAITING_DOCTOR"
    rec = _rec(session_factory, claim["id"])
    assert rec.benefit_ruleset_version == "benefit-2026.11-demo"
    assert not any(f.rule_id.startswith("BEN-") for f in rec.findings)
