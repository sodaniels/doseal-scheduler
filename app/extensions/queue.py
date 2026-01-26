from rq import Queue
from rq_scheduler import Scheduler
from datetime import timedelta

from .redis_conn import redis_client

publish_queue = Queue("publish", connection=redis_client)
scheduler = Scheduler(queue=publish_queue, connection=redis_client)