"""Fixture bersama untuk tes API: SQLite di memori, storage memori, antrean RQ di fakeredis."""
from __future__ import annotations

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from mab_api.db import Base, make_session_factory
from mab_api.job_queue import RQJobQueue
from mab_api.main import create_app
from mab_api.models import Insurer, Role, User
from mab_api.security import hash_secret
from mab_api.storage import MemoryStorage

PASSWORD = "rahasia-uji"


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def storage():
    return MemoryStorage()


@pytest.fixture
def job_queue():
    return RQJobQueue(queue_name="claims", connection=fakeredis.FakeRedis())


@pytest.fixture
def users(session_factory):
    """Dua asuransi; satu akun per peran di asuransi A, plus staf asuransi B."""
    with session_factory() as db:
        a = Insurer(code="A", name="Asuransi A (rekaan)")
        b = Insurer(code="B", name="Asuransi B (rekaan)")
        db.add_all([a, b])
        db.flush()
        spec = [
            ("staf", Role.INSURER_STAFF, a.id, None),
            ("manajer", Role.INSURER_MANAGER, a.id, None),
            ("dokter_umum", Role.DOCTOR_GP, None, None),
            ("spesialis", Role.DOCTOR_SPECIALIST, None, "Penyakit Dalam"),
            ("admin", Role.ADMIN, None, None),
            ("staf_b", Role.INSURER_STAFF, b.id, None),
        ]
        out = {}
        for key, role, insurer_id, specialty in spec:
            u = User(
                email=f"{key}@uji.test",
                full_name=f"Pengguna {key}",
                role=role.value,
                insurer_id=insurer_id,
                specialty=specialty,
                password_hash=hash_secret(PASSWORD),
            )
            db.add(u)
            db.flush()
            out[key] = u.id
        db.commit()
        return out


@pytest.fixture
def client(session_factory, storage, job_queue, users):
    app = create_app(session_factory=session_factory, storage=storage, job_queue=job_queue)
    return TestClient(app)


@pytest.fixture
def login(client):
    cache: dict[str, dict] = {}

    def _login(key: str) -> dict:
        if key not in cache:
            r = client.post("/auth/login", json={"email": f"{key}@uji.test", "password": PASSWORD})
            assert r.status_code == 200, r.text
            cache[key] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return cache[key]

    return _login
