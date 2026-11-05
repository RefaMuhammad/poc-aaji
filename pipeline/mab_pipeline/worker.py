"""Titik masuk worker RQ: python -m mab_pipeline.worker

RQ_QUEUES memilih antrean yang didengar (dipisah koma). Bawaan: semua antrean, sehingga satu worker
cukup untuk dev. Di Kubernetes, worker dipisah per antrean (klaim, underwriting, webhook) supaya
beban berat satu modul tidak menahan modul lain.
"""
import logging
import os
import sys

from redis import Redis
from rq import Queue, Worker


def main() -> None:
    from mab_api.config import get_settings
    from mab_api.observability import setup_logging

    s = get_settings()
    setup_logging(s.log_format, s.log_level)
    problems = s.readiness_problems()
    if problems:
        for p in problems:
            logging.error("Konfigurasi belum aman untuk %s: %s", s.environment, p)
        sys.exit(1)
    default = ",".join(dict.fromkeys([s.rq_queue, s.rq_queue_underwriting, s.rq_queue_webhooks]))
    names = [n.strip() for n in os.environ.get("RQ_QUEUES", default).split(",") if n.strip()]
    conn = Redis.from_url(s.redis_url)
    logging.info("Worker mendengarkan antrean: %s", ", ".join(names))
    worker = Worker([Queue(n, connection=conn) for n in names], connection=conn)
    worker.work()


if __name__ == "__main__":
    main()
