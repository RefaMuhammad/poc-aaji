"""U8: kesiapan operasi dan keamanan.

Batas percobaan login/PIN, header keamanan, request id, health/readiness, metrik, gerbang konfigurasi
staging/produksi dan data sungguhan, antrean terpisah, enkripsi S3, log JSON, dan skrip backup.
"""
from __future__ import annotations

import importlib.util
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fakeredis
import jwt
import pytest
from fastapi.testclient import TestClient

from mab_api.config import Settings
from mab_api.job_queue import RQJobQueue
from mab_api.main import create_app
from mab_api.observability import JsonFormatter, request_id_var
from mab_api.ratelimit import FailureLimiter
from mab_api.storage import S3Storage
from tests.conftest import PASSWORD
from tests.test_u7_underwriting import PIN, uw, uw_llm, uw_rules  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]


# ----------------------------------------------------------------------------- batas percobaan


def test_login_locked_after_repeated_failures(client):
    for _ in range(5):
        r = client.post("/auth/login", json={"email": "staf@uji.test", "password": "salah"})
        assert r.status_code == 401
    # password benar pun ditolak selama akun dikunci, dengan Retry-After
    r = client.post("/auth/login", json={"email": "staf@uji.test", "password": PASSWORD})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    # akun lain tidak ikut terkunci
    assert client.post("/auth/login", json={"email": "manajer@uji.test", "password": PASSWORD}).status_code == 200


def test_successful_login_resets_account_counter(client):
    for _ in range(4):
        client.post("/auth/login", json={"email": "staf@uji.test", "password": "salah"})
    assert client.post("/auth/login", json={"email": "staf@uji.test", "password": PASSWORD}).status_code == 200
    for _ in range(4):
        assert client.post("/auth/login", json={"email": "staf@uji.test", "password": "salah"}).status_code == 401
    assert client.post("/auth/login", json={"email": "staf@uji.test", "password": PASSWORD}).status_code == 200


def test_lockout_is_recorded_in_audit_log(client, login, session_factory):
    from sqlalchemy import select

    from mab_api.models import AuditLog

    for _ in range(6):
        client.post("/auth/login", json={"email": "dokter_umum@uji.test", "password": "salah"})
    with session_factory() as db:
        actions = [a for a in db.scalars(select(AuditLog.action))]
    assert actions.count("LOGIN_FAILED") == 5 and actions.count("LOGIN_LOCKED") == 1


def test_signature_pin_locked_after_repeated_failures(client, login, uw):  # noqa: F811
    app = uw("UW-22")
    doc = login("spesialis")
    url = f"/underwriting/applications/{app['id']}/sign"
    for _ in range(5):
        assert client.post(url, json={"action": "AGREE", "pin": "000000"}, headers=doc).status_code == 403
    # PIN benar ditolak selama terkunci: tebakan beruntun tidak bisa menemukan PIN
    r = client.post(url, json={"action": "AGREE", "pin": PIN}, headers=doc)
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_failure_limiter_window_and_reset():
    redis = fakeredis.FakeRedis()
    lim = FailureLimiter(max_failures=3, window=60, redis=redis)
    for _ in range(3):
        lim.fail("k")
    assert lim.blocked("k") and 0 < lim.retry_after("k") <= 60
    assert not lim.blocked("k", limit=10)
    lim.reset("k")
    assert not lim.blocked("k")
    # tanpa Redis: hitungan di memori
    mem = FailureLimiter(max_failures=2, window=60)
    mem.fail("x"), mem.fail("x")
    assert mem.blocked("x")


# ----------------------------------------------------------------------------- token


def test_tampered_or_expired_tokens_are_rejected(client, users):
    from mab_api.config import get_settings

    secret = get_settings().jwt_secret
    now = datetime.now(timezone.utc)
    base = {"sub": users["admin"], "role": "admin", "insurer_id": None, "iat": now}
    bad = [
        jwt.encode({**base, "exp": now + timedelta(hours=1)}, "kunci-lain-yang-bukan-milik-server-123456", algorithm="HS256"),
        jwt.encode({**base, "exp": now - timedelta(minutes=1)}, secret, algorithm="HS256"),
        jwt.encode({**base, "exp": now + timedelta(hours=1)}, None, algorithm="none"),
    ]
    for token in bad:
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


# ----------------------------------------------------------------------------- header, health, metrik


def test_security_headers_and_request_id(client):
    r = client.get("/health")
    for h in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Content-Security-Policy", "X-Request-ID"):
        assert h in r.headers, h
    assert r.headers["Cache-Control"] == "no-store"
    assert "Strict-Transport-Security" not in r.headers          # development: tanpa HSTS
    # request id dari klien dipakai bila formatnya wajar, selain itu diganti
    assert client.get("/health", headers={"X-Request-ID": "abc12345-req"}).headers["X-Request-ID"] == "abc12345-req"
    assert client.get("/health", headers={"X-Request-ID": "<script>"}).headers["X-Request-ID"] != "<script>"
    # header juga ada di respons error
    assert "X-Frame-Options" in client.get("/claims").headers


def test_readiness_checks_dependencies(client, storage):
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["checks"] == {"database": "ok", "redis": "ok", "storage": "ok"}

    def broken():
        raise ConnectionError("tidak terhubung")

    storage.ping = broken
    r = client.get("/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["storage"].startswith("gagal")
    assert client.get("/health/live").status_code == 200       # liveness tidak bergantung dependensi


def test_metrics_use_route_templates_and_queue_depth(client, login, job_queue):
    h = login("admin")
    claim_id = "00000000-0000-0000-0000-000000000000"
    client.get(f"/claims/{claim_id}", headers=h)
    job_queue.enqueue_process_claim("x")
    body = client.get("/metrics").text
    assert 'route="/claims/{claim_id}"' in body and claim_id not in body
    assert 'mab_queue_depth{queue="claims"}' in body


def test_metrics_token(monkeypatch, session_factory, storage, job_queue, users):
    from mab_api import config

    monkeypatch.setenv("METRICS_TOKEN", "token-metrik-uji")
    config.get_settings.cache_clear()
    try:
        c = TestClient(create_app(session_factory=session_factory, storage=storage, job_queue=job_queue))
        assert c.get("/metrics").status_code == 401
        assert c.get("/metrics", headers={"Authorization": "Bearer token-metrik-uji"}).status_code == 200
    finally:
        config.get_settings.cache_clear()


# ----------------------------------------------------------------------------- gerbang konfigurasi


def test_development_has_no_readiness_problems():
    assert Settings(_env_file=None).readiness_problems() == []


def test_staging_with_dev_defaults_refuses_to_start(monkeypatch, session_factory, storage, job_queue):
    s = Settings(_env_file=None, environment="staging")
    problems = " | ".join(s.readiness_problems())
    for needle in ("JWT_SECRET", "DATABASE_URL", "MINIO_ROOT_PASSWORD", "LOG_FORMAT"):
        assert needle in problems

    from mab_api import config

    monkeypatch.setenv("ENVIRONMENT", "staging")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="belum aman"):
            create_app(session_factory=session_factory, storage=storage, job_queue=job_queue)
    finally:
        config.get_settings.cache_clear()


def _safe(**kw) -> Settings:
    base = dict(
        environment="staging", jwt_secret="x" * 40, log_format="json", minio_root_password="kuat-sekali",
        database_url="postgresql+psycopg://mab:kuat@db:5432/mab?sslmode=require", cors_origins="https://mab.contoh.id",
    )
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_staging_with_safe_config_passes():
    assert _safe().readiness_problems() == []


def test_real_data_gate():
    problems = " | ".join(_safe(real_data_enabled=True).readiness_problems())
    for needle in ("production", "DEMO_MODE", "LLM_PROVIDER", "residensi", "S3_SSE"):
        assert needle in problems
    ok = _safe(environment="production", real_data_enabled=True, demo_mode=False, llm_provider="openai_compatible",
               llm_data_residency_approved=True, s3_sse="aws:kms")
    assert ok.readiness_problems() == []
    no_tls = _safe(environment="production", real_data_enabled=True, demo_mode=False, llm_provider="openai_compatible",
                   llm_data_residency_approved=True, s3_sse="aws:kms", database_url="postgresql+psycopg://mab:kuat@db/mab")
    assert any("sslmode" in p for p in no_tls.readiness_problems())


# ----------------------------------------------------------------------------- antrean dan penyimpanan


def test_jobs_go_to_separate_queues_when_configured():
    q = RQJobQueue(queue_name="claims", connection=fakeredis.FakeRedis(),
                   underwriting_queue="underwriting", webhook_queue="webhooks")
    q.enqueue_process_claim("c1")
    q.enqueue_process_underwriting("u1")
    q.enqueue_webhook("w1")
    assert (q.queue.count, q.underwriting.count, q.webhooks.count) == (1, 1, 1)
    assert q.queue_names == ["claims", "underwriting", "webhooks"]
    single = RQJobQueue(queue_name="claims", connection=fakeredis.FakeRedis())
    single.enqueue_process_underwriting("u1")
    assert single.queue.count == 1 and single.queue_names == ["claims"]


def test_s3_server_side_encryption_arguments():
    plain = S3Storage("http://minio:9000", "b", "k", "s")
    assert plain._sse_args() == {}
    sse_s3 = S3Storage("http://minio:9000", "b", "k", "s", sse="AES256")
    assert sse_s3._sse_args() == {"ServerSideEncryption": "AES256"}
    kms = S3Storage(None, "b", None, None, region="ap-southeast-3", sse="aws:kms", kms_key_id="arn:aws:kms:x")
    assert kms._sse_args() == {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": "arn:aws:kms:x"}


# ----------------------------------------------------------------------------- log


def test_json_log_line_has_request_id_and_fields():
    rec = logging.LogRecord("mab_api.request", logging.INFO, __file__, 1, "%s %s %s", ("GET", "/claims", 200), None)
    rec.route, rec.status, rec.duration_ms = "/claims", 200, 12.5
    token = request_id_var.set("req-12345678")
    try:
        line = json.loads(JsonFormatter().format(rec))
    finally:
        request_id_var.reset(token)
    assert line["request_id"] == "req-12345678" and line["route"] == "/claims" and line["msg"] == "GET /claims 200"


# ----------------------------------------------------------------------------- backup


def _backup_module():
    spec = importlib.util.spec_from_file_location("mab_backup", ROOT / "infra" / "ops" / "mab_backup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_backup_password_not_in_process_arguments():
    mod = _backup_module()
    uri, env = mod.libpq("postgresql+psycopg://mab:p%40ss@db:5432/mab?sslmode=require")
    assert uri == "postgresql://mab@db:5432/mab?sslmode=require"
    assert env["PGPASSWORD"] == "p@ss"


def test_backup_count_query_quotes_table_names():
    mod = _backup_module()
    q = mod._count_sql(["claims", 'jahat"; DROP TABLE x; --'])
    text = q.as_string(None)
    assert '"public"."claims"' in text and '"jahat""; DROP TABLE x; --"' in text
