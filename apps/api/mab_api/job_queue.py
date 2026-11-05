"""Pengiriman job ke antrean RQ."""
from __future__ import annotations

PROCESS_CLAIM = "mab_pipeline.tasks.process_claim"
DELIVER_WEBHOOK = "mab_pipeline.tasks.deliver_webhook"
WEBHOOK_RETRY_INTERVALS = [10, 60]   # detik antar percobaan ulang (total 3 percobaan)


class RQJobQueue:
    def __init__(self, redis_url: str | None = None, queue_name: str = "claims", connection=None):
        from redis import Redis
        from rq import Queue

        conn = connection if connection is not None else Redis.from_url(redis_url)
        self.queue = Queue(queue_name, connection=conn)

    def enqueue_process_claim(self, claim_id: str) -> str:
        job = self.queue.enqueue(PROCESS_CLAIM, claim_id, job_timeout=900, result_ttl=86400)
        return job.id

    def enqueue_webhook(self, delivery_id: str) -> str:
        from rq import Retry

        job = self.queue.enqueue(DELIVER_WEBHOOK, delivery_id, job_timeout=60, result_ttl=86400,
                                 retry=Retry(max=len(WEBHOOK_RETRY_INTERVALS), interval=WEBHOOK_RETRY_INTERVALS))
        return job.id
