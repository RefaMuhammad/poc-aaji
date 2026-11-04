"""Pengiriman job ke antrean RQ."""
from __future__ import annotations

PROCESS_CLAIM = "mab_pipeline.tasks.process_claim"


class RQJobQueue:
    def __init__(self, redis_url: str | None = None, queue_name: str = "claims", connection=None):
        from redis import Redis
        from rq import Queue

        conn = connection if connection is not None else Redis.from_url(redis_url)
        self.queue = Queue(queue_name, connection=conn)

    def enqueue_process_claim(self, claim_id: str) -> str:
        job = self.queue.enqueue(PROCESS_CLAIM, claim_id, job_timeout=900, result_ttl=86400)
        return job.id
