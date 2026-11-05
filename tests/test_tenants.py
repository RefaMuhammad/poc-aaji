"""Tes U1: pengaturan tenant (ambang triase, aturan aktif), akun layanan + API key, penugasan dokter dan SLA."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mab_api.assignment import sla_state
from mab_api.models import Assignment, AuditLog, Recommendation, User
from mab_api.security import hash_secret
from mab_api.tenancy import TenantConfig
from mab_pipeline.ocr.engine import NullOCREngine
from mab_pipeline.tasks import process_claim
from tests.test_reasoning import _create_and_upload, mock_llm, ruleset  # noqa: F401  (fixture)

PIN = "135790"
SETTINGS = {"display_name": None, "logo_data_url": None, "primary_color": None, "triage_red_min_score": None,
            "triage_yellow_min_score": None, "disabled_rules": [], "sla_gp_hours": 24, "sla_specialist_hours": 48,
            "auto_assign": True}
LOGO = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0naHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmcnLz4="


@pytest.fixture
def run(client, login, session_factory, storage, mock_llm, ruleset):  # noqa: F811
    def _run(claim_id: str, staff: str = "staf", member: str = "PST-1") -> str:
        claim = _create_and_upload(client, login(staff), claim_id, member=member)
        process_claim(claim["id"], session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine(),
                      ruleset=ruleset)
        return claim["id"]
    return _run


def _put(client, login, insurer_id, **changes):
    return client.put(f"/tenants/{insurer_id}/settings", json={**SETTINGS, **changes}, headers=login("admin"))


def _rec(session_factory, claim_id) -> Recommendation:
    with session_factory() as db:
        return db.scalar(select(Recommendation).where(Recommendation.claim_id == claim_id, Recommendation.is_current))


# ----------------------------------------------------------------------------- pengaturan tenant


def test_two_tenants_side_by_side_with_different_branding_and_thresholds(client, login, users, run, session_factory):
    a, b = users["insurer_a"], users["insurer_b"]
    assert _put(client, login, a, display_name="Asuransi A", primary_color="#0f766e").status_code == 200
    r = _put(client, login, b, display_name="Asuransi B", logo_data_url=LOGO, triage_red_min_score=20)
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1 and body["default_red_min_score"] == 40 and body["default_yellow_min_score"] == 10
    assert body["effective_ruleset_version"].endswith("+B.v1")

    # header portal: masing-masing melihat tenant-nya
    assert client.get("/tenants/current", headers=login("staf")).json()["display_name"] == "Asuransi A"
    brand_b = client.get("/tenants/current", headers=login("staf_b")).json()
    assert brand_b["display_name"] == "Asuransi B" and brand_b["logo_data_url"] == LOGO
    assert client.get("/tenants/current", headers=login("dokter_umum")).json() is None
    # staf hanya melihat pengaturan tenant sendiri
    assert [t["code"] for t in client.get("/tenants", headers=login("staf")).json()] == ["A"]
    assert [t["code"] for t in client.get("/tenants", headers=login("tpa")).json()] == ["A", "B"]

    # klaim yang sama (skor 30, temuan MEDIUM + LOW): kuning di A, merah di B karena ambang merah B = 20
    in_a = run("SYN-DEN-09", "staf")
    in_b = run("SYN-DEN-09", "staf_b")
    rec_a, rec_b = _rec(session_factory, in_a), _rec(session_factory, in_b)
    assert (rec_a.triage_status, rec_a.risk_score) == ("YELLOW", 30)
    assert (rec_b.triage_status, rec_b.risk_score) == ("RED", 30)
    assert rec_a.ruleset_version == "rules-2026.11-demo"
    assert rec_b.ruleset_version == "rules-2026.11-demo+B.v1"
    with session_factory() as db:
        log = db.scalars(select(AuditLog).where(AuditLog.claim_id == in_b, AuditLog.action == "PIPELINE_COMPLETED")).one()
        assert log.detail["tenant_overrides"]["triage_red_min_score"] == 20


def test_disabled_rule_is_not_evaluated_for_that_tenant(client, login, users, run, session_factory):
    assert _put(client, login, users["insurer_b"], disabled_rules=["GEA-03"]).status_code == 200
    in_a, in_b = run("SYN-GEA-07", "staf"), run("SYN-GEA-07", "staf_b")
    assert _rec(session_factory, in_a).triage_status == "YELLOW"
    rec_b = _rec(session_factory, in_b)
    assert rec_b.triage_status == "GREEN" and rec_b.recommendation == "PAY_FULL"


def test_settings_validation_and_audit(client, login, users, session_factory):
    a = users["insurer_a"]
    assert _put(client, login, a, disabled_rules=["TIDAK-ADA"]).status_code == 422
    r = _put(client, login, a, triage_red_min_score=10, triage_yellow_min_score=15)
    assert r.status_code == 422 and "lebih besar" in r.json()["detail"]
    assert _put(client, login, a, triage_yellow_min_score=40).status_code == 422  # >= ambang merah bawaan 40
    assert _put(client, login, a, logo_data_url="data:text/html;base64,AAAA").status_code == 422
    assert _put(client, login, a, primary_color="merah").status_code == 422
    assert _put(client, login, a, sla_gp_hours=0).status_code == 422
    # hanya admin yang boleh mengubah
    for key in ("staf", "manajer", "tpa", "auditor"):
        assert client.put(f"/tenants/{a}/settings", json=SETTINGS, headers=login(key)).status_code == 403, key

    assert _put(client, login, a, sla_gp_hours=8).json()["version"] == 1
    assert _put(client, login, a, sla_gp_hours=12, logo_data_url=LOGO).json()["version"] == 2
    with session_factory() as db:
        logs = db.scalars(select(AuditLog).where(AuditLog.action == "TENANT_SETTINGS_UPDATED").order_by(AuditLog.id)).all()
        assert [log.detail["after"]["sla_gp_hours"] for log in logs] == [8, 12]
        assert logs[1].detail["before"]["sla_gp_hours"] == 8
        assert logs[1].detail["after"]["logo_sha256"] and "logo_data_url" not in logs[1].detail["after"]


def test_admin_creates_tenant(client, login):
    r = client.post("/tenants", json={"code": "NUSA", "name": "Asuransi Nusantara (rekaan)"}, headers=login("admin"))
    assert r.status_code == 201 and r.json()["version"] == 0 and r.json()["sla_gp_hours"] == 24
    assert client.post("/tenants", json={"code": "NUSA", "name": "Duplikat"}, headers=login("admin")).status_code == 409


# ----------------------------------------------------------------------------- API key


def test_api_key_lifecycle_and_tenant_isolation(client, login, users, run):
    a = users["insurer_a"]
    in_a = run("SYN-GEA-02", "staf")           # hijau, bayar penuh: sudah dirilis ke asuransi
    red = run("SYN-TIF-06", "staf", "PST-2")   # merah: draf menunggu dokter
    run("SYN-GEA-02", "staf_b")                # klaim tenant B

    assert client.post(f"/tenants/{a}/api-clients", json={"name": "Core A"}, headers=login("staf")).status_code == 403
    assert client.post(f"/tenants/{a}/api-clients", json={"name": "Core A", "scopes": ["claims:delete"]},
                       headers=login("admin")).status_code == 422
    created = client.post(f"/tenants/{a}/api-clients", json={"name": "Core A"}, headers=login("admin")).json()
    key = created["api_key"]
    assert key.startswith(f"mab_{created['key_prefix']}_")
    listed = client.get(f"/tenants/{a}/api-clients", headers=login("admin")).json()
    assert len(listed) == 1 and "api_key" not in listed[0]  # kunci tidak pernah ditampilkan lagi

    h = {"X-API-Key": key}
    assert client.get("/integrations/v1/whoami", headers=h).json()["tenant_code"] == "A"
    rows = client.get("/integrations/v1/claims", headers=h).json()
    assert {r["claim_number"] for r in rows} == {"SYN-GEA-02", "SYN-TIF-06"}  # tanpa klaim tenant B
    green = client.get("/integrations/v1/claims/SYN-GEA-02", headers=h).json()
    assert green["recommendation"] == "PAY_FULL" and green["ruleset_version"]
    draft = client.get("/integrations/v1/claims/SYN-TIF-06", headers=h).json()
    assert draft["status"] == "AWAITING_DOCTOR" and draft["recommendation"] is None  # draf tidak bocor
    assert in_a and red

    # kunci salah / tanpa kunci / dicabut
    assert client.get("/integrations/v1/claims", headers={"X-API-Key": key[:-2] + "xx"}).status_code == 401
    assert client.get("/integrations/v1/claims").status_code == 401
    assert client.get("/integrations/v1/claims", headers={"Authorization": login("staf")["Authorization"]}).status_code == 401
    assert client.post(f"/tenants/{a}/api-clients/{created['id']}/revoke", headers=login("admin")).json()["is_active"] is False
    assert client.get("/integrations/v1/whoami", headers=h).status_code == 401
    # kunci tenant A tidak bisa dicabut lewat tenant B
    assert client.post(f"/tenants/{users['insurer_b']}/api-clients/{created['id']}/revoke",
                       headers=login("admin")).status_code == 404


# ----------------------------------------------------------------------------- penugasan & SLA


@pytest.fixture
def doctors(session_factory, users):
    """PIN untuk dokter yang ada + satu dokter umum kedua."""
    with session_factory() as db:
        for key in ("dokter_umum", "spesialis"):
            db.get(User, users[key]).pin_hash = hash_secret(PIN)
        gp2 = User(email="dokter_umum2@uji.test", full_name="Pengguna dokter umum 2", role="doctor_gp",
                   password_hash=hash_secret("rahasia-uji"), pin_hash=hash_secret(PIN))
        db.add(gp2)
        db.commit()
        return {"gp2": gp2.id}


def _active(session_factory, claim_id):
    with session_factory() as db:
        return db.scalars(select(Assignment).where(Assignment.claim_id == claim_id, Assignment.status == "ACTIVE")).all()


def test_auto_assign_balances_load_and_sets_sla(client, login, users, run, doctors, session_factory):
    _put(client, login, users["insurer_a"], sla_gp_hours=6)
    first, second = run("SYN-GEA-07", member="PST-1"), run("SYN-DEN-09", member="PST-2")
    a1, a2 = _active(session_factory, first), _active(session_factory, second)
    assert len(a1) == len(a2) == 1 and a1[0].method == a2[0].method == "AUTO"
    assert {a1[0].doctor_id, a2[0].doctor_id} == {users["dokter_umum"], doctors["gp2"]}  # beban dibagi rata
    rec = _rec(session_factory, first)
    assert abs((a1[0].due_at - rec.created_at).total_seconds() - 6 * 3600) < 5

    # antrean menampilkan SLA; dokter hanya melihat kasus yang ditugaskan kepadanya
    mine = client.get("/review/queue", headers=login("dokter_umum")).json()
    assert len(mine) == 1 and mine[0]["assigned_to_me"] and mine[0]["sla_hours"] == 6
    assert mine[0]["sla_state"] == "ON_TRACK" and mine[0]["insurer_name"] == "Asuransi A (rekaan)"
    red = run("SYN-TIF-06", member="PST-3")
    assert _active(session_factory, red)[0].doctor_id == users["spesialis"]
    assert _active(session_factory, red)[0].level == "SPECIALIST"


def test_release_escalate_sign_close_assignments(client, login, users, run, doctors, session_factory):
    claim = run("SYN-GEA-07")
    owner = _active(session_factory, claim)[0].doctor_id
    owner_key = "dokter_umum" if owner == users["dokter_umum"] else None
    if owner_key is None:  # ditugaskan ke dokter umum kedua: pindahkan supaya tes memakai akun yang bisa login
        r = client.post(f"/admin/claims/{claim}/assign", json={"doctor_id": users["dokter_umum"]}, headers=login("admin"))
        assert r.status_code == 200 and r.json()["method"] == "MANUAL"
    gp = login("dokter_umum")
    assert client.post(f"/review/{claim}/start", headers=gp).status_code == 201
    # lepas: pindah ke dokter umum lain, bukan kembali ke yang melepas
    assert client.post(f"/review/{claim}/release", headers=gp).status_code == 204
    assert _active(session_factory, claim)[0].doctor_id == doctors["gp2"]
    assert client.get(f"/review/{claim}", headers=gp).status_code == 404

    # admin memindahkan kembali; eskalasi -> otomatis ke spesialis
    assert client.post(f"/admin/claims/{claim}/assign", json={"doctor_id": users["spesialis"]},
                       headers=login("admin")).status_code == 422  # kasus kuning untuk dokter umum
    assert client.post(f"/admin/claims/{claim}/assign", json={"doctor_id": users["dokter_umum"]},
                       headers=login("staf")).status_code == 403
    assert client.post(f"/admin/claims/{claim}/assign", json={"doctor_id": users["dokter_umum"]},
                       headers=login("admin")).status_code == 200
    assert client.post(f"/review/{claim}/start", headers=gp).status_code == 201
    assert client.post(f"/review/{claim}/escalate", json={"notes": "Mohon pendapat spesialis"}, headers=gp).status_code == 200
    active = _active(session_factory, claim)
    assert len(active) == 1 and active[0].doctor_id == users["spesialis"] and active[0].level == "SPECIALIST"

    sp = login("spesialis")
    assert client.post(f"/review/{claim}/start", headers=sp).status_code == 201
    ws = client.get(f"/review/{claim}", headers=sp).json()
    body = {**ws["suggestion"], "pin": PIN}
    assert client.post(f"/review/{claim}/sign", json=body, headers=sp).status_code == 200
    assert _active(session_factory, claim) == []
    with session_factory() as db:
        statuses = [a.status for a in db.scalars(select(Assignment).where(Assignment.claim_id == claim)
                                                 .order_by(Assignment.assigned_at))]
    assert statuses[-2:] == ["ESCALATED", "COMPLETED"] and "RELEASED" in statuses
    done = client.get("/review/queue?done=true", headers=sp).json()
    assert done[0]["sla_met"] is True and done[0]["sla_state"] is None


def test_shared_queue_when_auto_assign_is_off(client, login, users, run, doctors, session_factory):
    _put(client, login, users["insurer_a"], auto_assign=False)
    claim = run("SYN-GEA-07")
    assert _active(session_factory, claim) == []
    # dua dokter umum sama-sama melihat kasus di antrean bersama
    item = client.get("/review/queue", headers=login("dokter_umum")).json()[0]
    assert item["id"] == claim and item["assigned_to"] is None
    assert client.post(f"/review/{claim}/start", headers=login("dokter_umum")).status_code == 201
    a = _active(session_factory, claim)
    assert len(a) == 1 and a[0].method == "CLAIMED" and a[0].doctor_id == users["dokter_umum"]


def test_sla_states():
    cfg = TenantConfig(insurer_id="x", code="X", name="X", sla_gp_hours=24)
    now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
    assert sla_state(now + timedelta(hours=10), "GP", cfg, now) == "ON_TRACK"
    assert sla_state(now + timedelta(hours=6), "GP", cfg, now) == "AT_RISK"     # sisa <= 25% dari 24 jam
    assert sla_state(now - timedelta(minutes=1), "GP", cfg, now) == "OVERDUE"


def test_overdue_cases_are_listed_first(client, login, users, run, doctors, session_factory):
    _put(client, login, users["insurer_a"], auto_assign=False)
    late, fresh = run("SYN-GEA-07", member="PST-1"), run("SYN-DEN-09", member="PST-2")  # DEN-09 skornya lebih tinggi
    with session_factory() as db:
        rec = db.scalar(select(Recommendation).where(Recommendation.claim_id == late, Recommendation.is_current))
        rec.created_at = datetime.now(timezone.utc) - timedelta(hours=30)
        db.commit()
    q = client.get("/review/queue", headers=login("dokter_umum")).json()
    assert [i["id"] for i in q] == [late, fresh] and q[0]["sla_state"] == "OVERDUE"
