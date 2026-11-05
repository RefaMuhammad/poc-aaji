"""Jalankan migrasi database dengan kunci, aman bila beberapa pod API start bersamaan (U8).

python -m mab_api.migrate   (initContainer API di Helm chart)
Pod pertama yang mendapat kunci menjalankan `alembic upgrade head`; pod lain menunggu lalu mendapati
skema sudah terbaru.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from mab_api.config import get_settings
from mab_api.observability import setup_logging

LOCK_ID = 7_270_008   # kunci advisory PostgreSQL khusus migrasi


def main() -> int:
    s = get_settings()
    setup_logging(s.log_format, s.log_level)
    log = logging.getLogger("mab_api.migrate")
    problems = s.readiness_problems()
    if problems:
        for p in problems:
            log.error("Konfigurasi belum aman untuk %s: %s", s.environment, p)
        return 1

    from alembic import command
    from alembic.config import Config

    ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    engine = create_engine(s.database_url, pool_pre_ping=True)
    with engine.connect() as conn:
        if conn.dialect.name == "postgresql":
            log.info("Menunggu kunci migrasi")
            conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
        try:
            log.info("alembic upgrade head")
            command.upgrade(Config(str(ini)), "head")
        finally:
            if conn.dialect.name == "postgresql":
                conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
    log.info("Migrasi selesai")
    return 0


if __name__ == "__main__":
    sys.exit(main())
