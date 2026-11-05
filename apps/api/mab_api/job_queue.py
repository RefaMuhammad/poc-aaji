"""Pengiriman job ke antrean RQ."""
from __future__ import annotations

PROCESS_CLAIM = "mab_pipeline.tasks.process_claim"
DELIVER_WEBHOOK = "mab_pipeline.tasks.deliver_webhook"
PROCESS_UNDERWRITING = "mab_pipeline.tasks.process_underwriting"
WEBHOOK_RETRY_INTERVALS = [10, 60]   # detik antar percobaan ulang (total 3 percobaan)


class RQJobQueue:
    """Klaim, underwriting, dan webhook bisa memakai antrean berbeda supaya worker bisa dipisah per beban (U8).

    Tanpa nama antrean khusus, semua job masuk ke `queue_name` (perilaku sebelum U8, dipakai tes).
    """

    def __init__(self, redis_url: str | None = None, queue_name: str = "claims", connection=None,
                 underwriting_queue: str | None = None, webhook_queue: str | None = None):
        from redis import Redis
        from rq import Queue

        conn = connection if connection is not None else Redis.from_url(redis_url)
        self.connection = conn
        self.queue = Queue(queue_name, connection=conn)
        self.underwriting = Queue(underwriting_queue, connection=conn) if underwriting_queue else self.queue
        self.webhooks = Queue(webhook_queue, connection=conn) if webhook_queue else self.queue

    @classmethod
    def from_settings(cls, settings) -> "RQJobQueue":
        return cls(settings.redis_url, settings.rq_queue, underwriting_queue=settings.rq_queue_underwriting,
                   webhook_queue=settings.rq_queue_webhooks)

    @property
    def queue_names(self) -> list[str]:
        return list(dict.fromkeys(q.name for q in (self.queue, self.underwriting, self.webhooks)))

    def enqueue_process_claim(self, claim_id: str) -> str:
        job = self.queue.enqueue(PROCESS_CLAIM, claim_id, job_timeout=900, result_ttl=86400)
        return job.id

    def enqueue_process_underwriting(self, application_id: str) -> str:
        job = self.underwriting.enqueue(PROCESS_UNDERWRITING, application_id, job_timeout=900, result_ttl=86400)
        return job.id

    def enqueue_webhook(self, delivery_id: str) -> str:
        from rq import Retry

        job = self.webhooks.enqueue(DELIVER_WEBHOOK, delivery_id, job_timeout=60, result_ttl=86400,
                                 retry=Retry(max=len(WEBHOOK_RETRY_INTERVALS), interval=WEBHOOK_RETRY_INTERVALS))
        return job.id
