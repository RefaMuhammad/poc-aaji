"""Reset data demo dari portal: gerbang akses, kunci, pengosongan data, dan status seed (DATA REKAAN)."""
from __future__ import annotations

import sys

import fakeredis
from sqlalchemy import func, select

from mab_api import demo_reset
from mab_api.job_queue import RQJobQueue
from mab_api.models import AuditLog, Insurer, User
from mab_api.storage import MemoryStorage


def test_only_admin_can_start_reset(client, login):
    calls = []
    client.app.state.demo_reset_launcher = lambda: calls.append(1)
    for key in ("staf", "manajer", "dokter_umum", "auditor_ojk", "tpa"):
        assert client.post("/demo/reset", headers=login(key)).status_code == 403, key
    assert client.post("/demo/reset").status_code == 401
    r = client.post("/demo/reset", headers=login("admin"))
    assert r.status_code == 202 and r.json()["state"] == "running" and calls == [1]
    # reset kedua ditolak selama yang pertama berjalan
    assert client.post("/demo/reset", headers=login("admin")).status_code == 409
    assert calls == [1]


def test_status_is_public_and_hides_log_unless_failed(client, job_queue):
    r = client.get("/demo/reset")
    assert r.status_code == 200 and r.json() == {"enabled": True, "state": "idle", **{
        k: None for k in ("step", "step_no", "steps_total", "started_at", "finished_at", "message")}}
    demo_reset.try_start(job_queue.connection)
    demo_reset._write_status(job_queue.connection, log_tail=["baris log"])
    assert "log_tail" not in client.get("/demo/reset").json()
    demo_reset._write_status(job_queue.connection, state="failed")
    assert client.get("/demo/reset").json()["log_tail"] == ["baris log"]


def test_reset_disabled_outside_demo_mode(monkeypatch, client, login):
    from mab_api import config

    monkeypatch.setenv("DEMO_MODE", "false")
    config.get_settings.cache_clear()
    try:
        assert client.get("/demo/reset").json() == {"enabled": False, "state": "idle"}
        assert client.post("/demo/reset", headers=login("admin")).status_code == 404
    finally:
        config.get_settings.cache_clear()


def test_reset_never_enabled_with_real_data():
    from mab_api.config import Settings

    assert not demo_reset.enabled(Settings(_env_file=None, demo_mode=True, real_data_enabled=True))
    assert demo_reset.enabled(Settings(_env_file=None))


def test_run_wipes_everything_and_tracks_seed_steps(session_factory, users, tmp_path):
    engine = session_factory.kw["bind"]
    with session_factory() as db:
        db.add(AuditLog(action="LOGIN", detail={}))
        db.commit()
    storage = MemoryStorage()
    storage.put("dokumen/a.pdf", b"%PDF", "application/pdf")
    redis = fakeredis.FakeRedis()
    q = RQJobQueue(queue_name="claims", connection=redis, underwriting_queue="underwriting")
    q.enqueue_process_claim("c1")
    q.enqueue_process_underwriting("u1")
    redis.set("mab:fail:login:staf@uji.test", 5)
    sftp = tmp_path / "sftp"
    (sftp / "PELITA" / "keluar").mkdir(parents=True)
    (sftp / "PELITA" / "keluar" / "status_klaim.csv").write_text("lama")
    data = tmp_path / "synthetic_output"
    (data / "SYN-DEN-01").mkdir(parents=True)
    (data / "SYN-DEN-01" / "case.json").write_text("{}")
    seed = [sys.executable, "-c", "print('1. Akun demo'); print('  12 akun baru'); print('3. Unggah klaim sintetis')"]

    assert demo_reset.try_start(redis)
    result = demo_reset.run(engine=engine, storage=storage, redis=redis, queue_names=q.queue_names,
                            sftp_root=sftp, seed_cmd=seed, seed_data_dir=data)

    assert result["state"] == "done" and result["finished_at"]
    with session_factory() as db:
        for model in (User, Insurer, AuditLog):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert storage.objects == {}
    assert q.queue.count == 0 and q.underwriting.count == 0
    assert not redis.exists("mab:fail:login:staf@uji.test")
    assert not (sftp / "PELITA" / "keluar" / "status_klaim.csv").exists()
    assert not redis.exists(demo_reset.LOCK_KEY)        # kunci dilepas, reset bisa diulang


def test_seed_failure_is_reported_with_log(session_factory, users, tmp_path):
    redis = fakeredis.FakeRedis()
    data = tmp_path / "synthetic_output"
    (data / "SYN-DEN-01").mkdir(parents=True)
    (data / "SYN-DEN-01" / "case.json").write_text("{}")
    seed = [sys.executable, "-c", "print('4. Menunggu worker memproses'); raise SystemExit('Worker belum selesai')"]
    demo_reset.try_start(redis)
    result = demo_reset.run(engine=session_factory.kw["bind"], storage=MemoryStorage(), redis=redis, queue_names=[],
                            sftp_root=tmp_path / "sftp", seed_cmd=seed, seed_data_dir=data)
    assert result["state"] == "failed" and result["step"] == "Menunggu worker memproses"
    assert "Worker belum selesai" in result["log_tail"]
    assert not redis.exists(demo_reset.LOCK_KEY)


def test_missing_synthetic_data_deletes_nothing(session_factory, users, tmp_path):
    redis = fakeredis.FakeRedis()
    demo_reset.try_start(redis)
    result = demo_reset.run(engine=session_factory.kw["bind"], storage=MemoryStorage(), redis=redis, queue_names=[],
                            sftp_root=tmp_path, seed_cmd=[sys.executable, "-c", "pass"], seed_data_dir=tmp_path / "kosong")
    assert result["state"] == "failed" and "Tidak ada data yang dihapus" in result["message"]
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) > 0
