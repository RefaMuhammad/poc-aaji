"""Tes U1: matriks hak akses per peran dan isolasi data antar tenant / antar peran."""
from __future__ import annotations

import pytest

from mab_api.models import Role
from mab_api.rbac import ROLE_PERMS, Perm
from mab_pipeline.ocr.engine import NullOCREngine
from mab_pipeline.tasks import process_claim
from tests.test_reasoning import _create_and_upload, mock_llm, ruleset  # noqa: F401  (fixture)

ALL_KEYS = ["staf", "manajer", "tpa", "dokter_umum", "spesialis", "auditor", "auditor_ojk", "faskes", "peserta",
            "underwriter", "admin"]


def test_every_role_has_a_row_in_the_matrix():
    assert set(ROLE_PERMS) == set(Role)


@pytest.fixture
def claims(client, login, session_factory, storage, mock_llm, ruleset):  # noqa: F811
    """Klaim tifoid (merah, menunggu dokter) dan gastroenteritis (hijau) di asuransi A, satu klaim hijau di B."""
    red = _create_and_upload(client, login("staf"), "SYN-TIF-06")
    green = _create_and_upload(client, login("staf"), "SYN-GEA-02", member="PST-LAIN")
    other = _create_and_upload(client, login("staf_b"), "SYN-GEA-02", member="PST-B")
    for c in (red, green, other):
        process_claim(c["id"], session_factory=session_factory, storage=storage, llm=mock_llm, ocr=NullOCREngine(),
                      ruleset=ruleset)
    return {"red": red["id"], "green": green["id"], "other": other["id"]}


# Endpoint -> izin yang dibutuhkan. Status kode diharapkan: 403 bila peran tidak punya izin.
ENDPOINTS = [
    ("GET", "/claims", Perm.CLAIM_LIST),
    ("GET", "/claims/export.csv", Perm.CLAIM_EXPORT),
    ("GET", "/dashboard", Perm.DASHBOARD),
    ("GET", "/review/queue", Perm.REVIEW),
    ("GET", "/admin/ruleset", Perm.RULESET_VIEW),
    ("GET", "/tenants", Perm.TENANT_VIEW),
    ("GET", "/users", Perm.USER_ADMIN),
    ("POST", "/tenants", Perm.TENANT_ADMIN),
    ("POST", "/claims", Perm.CLAIM_SUBMIT),
    ("POST", "/claims/decisions/bulk-agree", Perm.CLAIM_DECIDE),
]


@pytest.mark.parametrize("key", ALL_KEYS)
def test_role_matrix_is_enforced_on_endpoints(client, login, users, key):
    headers = login(key)
    role = Role(client.get("/auth/me", headers=headers).json()["role"])
    for method, path, perm in ENDPOINTS:
        if method == "GET":
            r = client.get(path, headers=headers)
        else:
            r = client.post(path, json={}, headers=headers)
        allowed = perm in ROLE_PERMS[role]
        if allowed:
            assert r.status_code != 403, f"{key} seharusnya boleh {method} {path}: {r.status_code} {r.text}"
        else:
            assert r.status_code == 403, f"{key} seharusnya ditolak {method} {path}: {r.status_code}"


def _ids(client, headers):
    return {c["id"] for c in client.get("/claims", headers=headers).json()}


def test_claim_visibility_per_role_and_tenant(client, login, claims):
    red, green, other = claims["red"], claims["green"], claims["other"]
    assert _ids(client, login("staf")) == {red, green}
    assert _ids(client, login("manajer")) == {red, green}
    assert _ids(client, login("staf_b")) == {other}
    assert _ids(client, login("tpa")) == {red, green, other}           # melayani A dan B
    assert _ids(client, login("auditor")) == {red, green}              # auditor tenant A
    assert _ids(client, login("auditor_ojk")) == {red, green, other}   # auditor platform
    assert _ids(client, login("faskes")) == {red, green, other}        # semua klaim dari RS-nya, lintas asuransi
    assert _ids(client, login("peserta")) == {red}                     # hanya klaim atas nomor pesertanya
    assert _ids(client, login("admin")) == {red, green, other}
    assert client.get("/claims", headers=login("underwriter")).status_code == 403

    # tenant lain: 404, bukan 403, supaya keberadaan klaim tidak bocor
    for key in ("staf_b", "auditor"):
        target = red if key == "staf_b" else other
        assert client.get(f"/claims/{target}", headers=login(key)).status_code == 404
    assert client.get(f"/claims/{other}", headers=login("peserta")).status_code == 404


def test_drafts_and_internal_details_stay_hidden(client, login, claims):
    red = claims["red"]
    # draf merah belum ditandatangani: hanya dokter/admin yang melihat
    for key in ("staf", "tpa", "auditor", "auditor_ojk"):
        assert client.get(f"/claims/{red}/recommendation", headers=login(key)).status_code == 409, key
        row = next(c for c in client.get("/claims", headers=login(key)).json() if c["id"] == red)
        assert row["triage_status"] is None and row["recommendation"] is None, key
    assert client.get(f"/claims/{red}/recommendation", headers=login("admin")).status_code == 200
    # faskes & peserta: hanya status; rekomendasi, field, dan dokumen ditolak
    for key in ("faskes", "peserta"):
        h = login(key)
        assert client.get(f"/claims/{red}", headers=h).status_code == 200
        assert client.get(f"/claims/{red}/status", headers=h).status_code == 200
        for path in ("recommendation", "fields", "recommendation.pdf"):
            assert client.get(f"/claims/{red}/{path}", headers=h).status_code == 403, (key, path)
        doc = client.get(f"/claims/{red}", headers=login("staf")).json()["documents"][0]["id"]
        assert client.get(f"/documents/{doc}/download", headers=h).status_code == 403
    green = claims["green"]
    row = next(c for c in client.get("/claims", headers=login("faskes")).json() if c["id"] == green)
    assert row["recommendation"] is None and row["triage_status"] is None


def test_tpa_creates_claims_only_for_its_tenants(client, login, users, session_factory):
    body = {"claim_number": "TPA-1", "policy_number": "P", "member_id": "M", "hospital_name": "RS rekaan",
            "admission_date": "2026-10-01", "discharge_date": "2026-10-03", "billed_amount": 1_000_000}
    h = login("tpa")
    # harus memilih asuransi karena melayani dua
    assert client.post("/claims", json=body, headers=h).status_code == 422
    r = client.post("/claims", json={**body, "insurer_id": users["insurer_b"]}, headers=h)
    assert r.status_code == 201 and r.json()["insurer_id"] == users["insurer_b"]
    # staf asuransi A tidak bisa membuat klaim untuk asuransi B
    r = client.post("/claims", json={**body, "claim_number": "X-2", "insurer_id": users["insurer_b"]}, headers=login("staf"))
    assert r.status_code == 403
    assert client.post("/claims", json={**body, "claim_number": "X-3"}, headers=login("staf")).json()["insurer_id"] == users["insurer_a"]


def test_read_only_roles_cannot_write(client, login, claims):
    green = claims["green"]
    for key in ("auditor", "auditor_ojk", "faskes", "peserta", "underwriter"):
        h = login(key)
        assert client.post(f"/claims/{green}/decision", json={"decision": "AGREE"}, headers=h).status_code == 403, key
        assert client.post(f"/claims/{green}/documents", files=[("files", ("a.pdf", b"%PDF-1.4", "application/pdf"))],
                           headers=h).status_code == 403, key
