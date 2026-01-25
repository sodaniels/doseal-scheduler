import os
from redis import Redis
from rq import Queue
from rq_scheduler import Scheduler

def get_redis():
    return Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))

redis_conn = get_redis()
queue = Queue("social_publish", connection=redis_conn, default_timeout=900)
scheduler = Scheduler(queue=queue, connection=redis_conn)