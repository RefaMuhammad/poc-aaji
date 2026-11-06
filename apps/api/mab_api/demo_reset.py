"""Reset data demo dari portal (DATA REKAAN): kosongkan semua data lalu isi ulang dengan seed demo.

Sama dengan `docker compose down -v` + seed, tetapi tanpa terminal: dipicu tombol di halaman admin.
Hanya berjalan bila DEMO_MODE=true dan REAL_DATA_ENABLED=false. Proses berjalan di subproses terpisah
(`python -m mab_api.demo_reset`) karena seed butuh beberapa menit dan memakai API ini sendiri lewat HTTP.

Langkah:
1. Kosongkan database (semua tabel kecuali alembic_version). TRUNCATE dipakai karena log audit punya trigger
   yang menolak DELETE baris; reset demo memang menghapus seluruh isi termasuk log audit.
2. Hapus semua objek dokumen di bucket.
3. Kosongkan antrean RQ dan kunci percobaan login/PIN di Redis.
4. Kosongkan folder SFTP demo (masuk, keluar, diproses, gagal).
5. Jalankan `infra/scripts/seed_demo.py`. Baris bernomor dari seed ("3. Unggah klaim sintetis") menjadi
   langkah yang tampil di portal.

Status disimpan di Redis supaya bisa dibaca portal walau akun admin ikut terhapus selama reset.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Engine, text

log = logging.getLogger(__name__)

STATUS_KEY = "mab:demo_reset:status"
LOCK_KEY = "mab:demo_reset:lock"
LOCK_TTL = 3 * 3600
FAIL_PREFIX = "mab:fail:"
SFTP_SUBDIRS = ("masuk", "keluar", "diproses", "gagal")
STEP_LINE = re.compile(r"^\s*(\d+)\.\s+(.+)$")
SEED_STEPS = 11  # jumlah langkah bernomor di seed_demo.py


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def enabled(settings) -> bool:
    return bool(settings.demo_mode) and not settings.real_data_enabled


def read_status(redis) -> dict:
    raw = redis.get(STATUS_KEY)
    if not raw:
        return {"state": "idle"}
    try:
        return json.loads(raw)
    except ValueError:
        return {"state": "idle"}


def _write_status(redis, **fields) -> dict:
    status = {**read_status(redis), **fields}
    redis.set(STATUS_KEY, json.dumps(status))
    return status


def try_start(redis) -> bool:
    """Ambil kunci reset. False bila reset lain masih berjalan."""
    if not redis.set(LOCK_KEY, _now(), nx=True, ex=LOCK_TTL):
        return False
    redis.set(STATUS_KEY, json.dumps({
        "state": "running", "step": "Menyiapkan reset", "step_no": 0, "steps_total": SEED_STEPS + 1,
        "started_at": _now(), "finished_at": None, "message": None, "log_tail": [],
    }))
    return True


def release(redis) -> None:
    redis.delete(LOCK_KEY)


# ----------------------------------------------------------------------------- pengosongan


def wipe_database(engine: Engine) -> int:
    """Kosongkan semua tabel aplikasi. Mengembalikan jumlah tabel."""
    from mab_api import models  # noqa: F401  (daftarkan semua tabel di metadata)
    from mab_api.db import Base

    tables = [t for t in Base.metadata.sorted_tables if t.name != "alembic_version"]
    with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            names = ", ".join(conn.dialect.identifier_preparer.quote(t.name) for t in tables)
            conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        else:  # SQLite (tes)
            for t in reversed(tables):
                conn.execute(t.delete())
    return len(tables)


def wipe_storage(storage) -> int:
    clear = getattr(storage, "clear", None)
    return clear() if clear else 0


def wipe_redis(redis, queue_names: list[str]) -> None:
    from rq import Queue

    for name in queue_names:
        q = Queue(name, connection=redis)
        for job_id in q.get_job_ids():  # tanpa Queue.empty(): itu memakai skrip Lua
            redis.delete(q.job_class.key_for(job_id))
        redis.delete(q.key)
        for registry in (q.failed_job_registry, q.finished_job_registry, q.deferred_job_registry,
                         q.scheduled_job_registry):
            for job_id in registry.get_job_ids():
                registry.remove(job_id, delete_job=True)
    keys = list(redis.scan_iter(match=FAIL_PREFIX + "*"))
    if keys:
        redis.delete(*keys)


def wipe_sftp(root: Path) -> int:
    removed = 0
    if not root.is_dir():
        return 0
    for tenant_dir in root.iterdir():
        for sub in SFTP_SUBDIRS:
            d = tenant_dir / sub
            if not d.is_dir():
                continue
            for f in d.iterdir():
                if f.is_file():
                    try:
                        f.unlink()
                        removed += 1
                    except OSError as e:
                        log.warning("Tidak bisa menghapus %s: %s", f, e)
    return removed


# ----------------------------------------------------------------------------- seed


def default_seed_command() -> list[str]:
    script = os.environ.get("SEED_SCRIPT")
    if not script:
        here = Path(__file__).resolve()
        candidates = [here.parents[1] / "infra" / "scripts" / "seed_demo.py"]   # container: /app/infra/scripts
        if len(here.parents) > 3:
            candidates.append(here.parents[3] / "infra" / "scripts" / "seed_demo.py")  # repo: apps/api/mab_api
        script = next((str(c) for c in candidates if c.is_file()), str(candidates[0]))
    return [sys.executable, "-u", script]


def run_seed(redis, cmd: list[str], env: dict | None = None) -> tuple[int, list[str]]:
    tail: deque[str] = deque(maxlen=40)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)  # noqa: S603
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        tail.append(line)
        m = STEP_LINE.match(line)
        if m:
            _write_status(redis, step=m.group(2).strip(), step_no=int(m.group(1)))
    return proc.wait(), list(tail)


def run(*, engine: Engine, storage, redis, queue_names: list[str], sftp_root: Path,
        seed_cmd: list[str] | None = None, seed_env: dict | None = None, seed_data_dir: Path | None = None) -> dict:
    """Jalankan reset penuh. Kunci harus sudah diambil dengan try_start()."""
    try:
        if seed_data_dir is not None and not any(seed_data_dir.glob("SYN-*/case.json")):
            # Cek sebelum menghapus apa pun: tanpa data sintetis, seed pasti gagal dan portal jadi kosong.
            return _write_status(redis, state="failed", finished_at=_now(),
                                 message=f"Data sintetis tidak ditemukan di {seed_data_dir}. Jalankan "
                                         "`docker compose run --rm synthetic` dulu. Tidak ada data yang dihapus.")
        _write_status(redis, step="Mengosongkan database, dokumen, dan antrean", step_no=0)
        tables = wipe_database(engine)
        objects = wipe_storage(storage)
        wipe_redis(redis, queue_names)
        files = wipe_sftp(sftp_root)
        log.info("Reset demo: %s tabel dikosongkan, %s objek dan %s file SFTP dihapus", tables, objects, files)

        code, tail = run_seed(redis, seed_cmd or default_seed_command(), env=seed_env)
        if code != 0:
            return _write_status(redis, state="failed", finished_at=_now(), log_tail=tail[-15:],
                                 message=f"Seed berhenti dengan kode {code}. Lihat log di bawah.")
        return _write_status(redis, state="done", step="Selesai", step_no=SEED_STEPS + 1, finished_at=_now(),
                             message="Data demo sudah diisi ulang. Silakan login lagi.", log_tail=[])
    except Exception as e:  # status harus selalu berakhir, supaya portal tidak menunggu selamanya
        log.exception("Reset demo gagal")
        return _write_status(redis, state="failed", finished_at=_now(), message=f"{type(e).__name__}: {e}")
    finally:
        release(redis)


def launch() -> None:
    """Mulai reset di subproses terpisah (dipanggil endpoint setelah try_start)."""
    subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "mab_api.demo_reset"],
        stdout=subprocess.DEVNULL, stderr=None, start_new_session=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )


def main() -> None:
    from redis import Redis

    from mab_api.config import get_settings
    from mab_api.db import get_engine
    from mab_api.job_queue import RQJobQueue
    from mab_api.storage import S3Storage

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    s = get_settings()
    redis = Redis.from_url(s.redis_url)
    if not enabled(s):
        _write_status(redis, state="failed", finished_at=_now(), message="Reset demo dimatikan di lingkungan ini.")
        release(redis)
        sys.exit(1)
    queue_names = RQJobQueue.from_settings(s).queue_names
    seed_data = Path(os.environ.get("SEED_DATA_DIR", Path(__file__).resolve().parents[1] / "data" / "synthetic_output"))
    sftp_root = Path(os.environ.get("SFTP_ROOT", seed_data.parent / "sftp"))
    env = {**os.environ, "SEED_API_URL": os.environ.get("SEED_API_URL", "http://localhost:8000")}
    result = run(engine=get_engine(), storage=S3Storage.from_settings(s), redis=redis, queue_names=queue_names,
                 sftp_root=sftp_root, seed_env=env, seed_data_dir=seed_data)
    sys.exit(0 if result.get("state") == "done" else 1)


if __name__ == "__main__":
    main()
