import os
from rq import Queue
from rq_scheduler import Scheduler

from .redis_conn import redis_client

PUBLISH_QUEUE_NAME = os.getenv("RQ_PUBLISH_QUEUE", "publish")

publish_queue = Queue(PUBLISH_QUEUE_NAME, connection=redis_client)

# This scheduler stores scheduled jobs in Redis and later moves them into `publish_queue`
scheduler = Scheduler(queue=publish_queue, connection=redis_client)