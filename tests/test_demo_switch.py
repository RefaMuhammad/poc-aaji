"""Ganti peran (demo): pindah antar-akun demo tanpa password, hanya di mode demo."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "infra" / "scripts"))

from seed_users import seed as seed_users  # noqa: E402

from mab_api.config import Settings  # noqa: E402
from mab_api.routers import auth as auth_router  # noqa: E402


def _demo_login(client, email="staf@demo.test"):
    r = client.post("/auth/login", json={"email": email, "password": "pw-demo"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_switch_between_demo_accounts(client, session_factory):
    seed_users(session_factory, password="pw-demo")
    h = _demo_login(client)

    accounts = client.get("/auth/demo-accounts", headers=h).json()
    assert [a["email"] for a in accounts][:2] == ["staf@demo.test", "dokter.umum@mab.test"]

    r = client.post("/auth/demo-switch", json={"email": "dokter.umum@mab.test"}, headers=h)
    assert r.status_code == 200, r.text
    h2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/auth/me", headers=h2).json()["role"] == "doctor_gp"
    # peran tetap dipisah: dokter tidak bisa membuka dashboard
    assert client.get("/dashboard", headers=h2).status_code == 403


def test_switch_refused_outside_demo(client, session_factory, login, monkeypatch):
    seed_users(session_factory, password="pw-demo")
    # akun bukan demo tidak bisa pindah ke akun demo
    assert client.get("/auth/demo-accounts", headers=login("staf")).json() == []
    assert client.post("/auth/demo-switch", json={"email": "admin@mab.test"}, headers=login("staf")).status_code == 403
    # akun demo tidak bisa pindah ke akun non-demo
    h = _demo_login(client)
    assert client.post("/auth/demo-switch", json={"email": "admin@uji.test"}, headers=h).status_code == 403
    # mode demo mati
    monkeypatch.setattr(auth_router, "get_settings", lambda: Settings(demo_mode=False))
    assert client.post("/auth/demo-switch", json={"email": "admin@mab.test"}, headers=h).status_code == 403
    assert client.get("/auth/demo-accounts", headers=h).json() == []
