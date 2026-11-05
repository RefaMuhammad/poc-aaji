"""U6: penjadwal laporan bulanan.

Jalan terus sebagai layanan `report-scheduler` (docker compose). Setiap REPORT_CHECK_SECONDS (bawaan
1 jam) ia memastikan laporan bulan lalu sudah ada untuk setiap tenant dan untuk seluruh platform.
Laporan yang sudah ada tidak dibuat ulang, jadi aman bila layanan dimulai ulang kapan saja.

    python -m mab_api.report_scheduler          # jalan terus
    python -m mab_api.report_scheduler --once   # sekali jalan (mis. dari cron)
"""
from __future__ import annotations

import logging
import os
import sys
import time

from mab_api.db import make_session_factory
from mab_api.reporting import run_schedule

log = logging.getLogger("report_scheduler")


def run_once(session_factory=None) -> int:
    session_factory = session_factory or make_session_factory()
    with session_factory() as db:
        made = run_schedule(db)
        db.commit()
        for r in made:
            log.info("laporan %s %s dibuat (%s)", r.period, r.scope_key, r.id)
        return len(made)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    every = int(os.environ.get("REPORT_CHECK_SECONDS", "3600"))
    if "--once" in sys.argv:
        print(f"{run_once()} laporan dibuat")
        return
    log.info("penjadwal laporan aktif, cek tiap %s detik", every)
    while True:
        wait = every
        try:
            run_once()
        except Exception:  # noqa: BLE001 - penjadwal tidak boleh berhenti karena satu galat
            log.exception("gagal membuat laporan terjadwal; coba lagi 1 menit lagi")
            wait = min(every, 60)  # mis. migrasi database belum selesai saat layanan baru mulai
        time.sleep(wait)


if __name__ == "__main__":
    main()
