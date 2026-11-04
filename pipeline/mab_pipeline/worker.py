"""Titik masuk worker RQ: python -m mab_pipeline.worker"""
import logging
import os

from redis import Redis
from rq import Queue, Worker

logging.basicConfig(level=logging.INFO)


def main() -> None:
    redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
    queue_name = os.environ.get("RQ_QUEUE", "claims")
    conn = Redis.from_url(redis_url)
    worker = Worker([Queue(queue_name, connection=conn)], connection=conn)
    worker.work()


if __name__ == "__main__":
    main()
