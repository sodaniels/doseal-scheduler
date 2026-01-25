# app/tasks/queue.py
import os
from redis import Redis
from rq import Queue
from rq_scheduler import Scheduler

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_conn = Redis.from_url(REDIS_URL)

social_queue = Queue("social", connection=redis_conn, default_timeout=600)
social_scheduler = Scheduler(queue=social_queue, connection=redis_conn)