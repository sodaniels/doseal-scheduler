
# app/extensions/queue.py

from __future__ import annotations

import os
from typing import Optional, Dict, Any

from rq import Queue
from rq_scheduler import Scheduler

from .redis_conn import redis_client


# -------------------------------------------------------------------
# Queue names
# -------------------------------------------------------------------

PUBLISH_QUEUE_NAME = (os.getenv("RQ_PUBLISH_QUEUE") or "publish").strip() or "publish"
DEFAULT_QUEUE_NAME = (os.getenv("RQ_DEFAULT_QUEUE") or PUBLISH_QUEUE_NAME).strip() or PUBLISH_QUEUE_NAME


# -------------------------------------------------------------------
# RQ defaults (can be overridden per enqueue)
# -------------------------------------------------------------------

RQ_DEFAULT_TIMEOUT = int(os.getenv("RQ_DEFAULT_TIMEOUT", "180"))          # seconds
RQ_DEFAULT_RESULT_TTL = int(os.getenv("RQ_DEFAULT_RESULT_TTL", "300"))    # seconds
RQ_DEFAULT_FAILURE_TTL = int(os.getenv("RQ_DEFAULT_FAILURE_TTL", "86400"))# seconds
RQ_DEFAULT_TTL = int(os.getenv("RQ_DEFAULT_TTL", "600"))                  # seconds (job ttl)


# -------------------------------------------------------------------
# Base queues
# -------------------------------------------------------------------

publish_queue = Queue(
    PUBLISH_QUEUE_NAME,
    connection=redis_client,
    default_timeout=RQ_DEFAULT_TIMEOUT,
)

default_queue = Queue(
    DEFAULT_QUEUE_NAME,
    connection=redis_client,
    default_timeout=RQ_DEFAULT_TIMEOUT,
)


# -------------------------------------------------------------------
# Scheduler
# -------------------------------------------------------------------
# This scheduler stores scheduled jobs in Redis and later moves them into the queue.
scheduler = Scheduler(queue=publish_queue, connection=redis_client)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def ping_redis(timeout_seconds: int = 2) -> bool:
    """
    Quick health check for Redis.
    Useful at startup and before scheduling critical jobs.
    """
    try:
        # redis-py supports socket_timeout per command if configured on client,
        # but we keep it simple: just ping.
        return bool(redis_client.ping())
    except Exception:
        return False


def normalise_queue_name(name: Optional[str]) -> str:
    """
    Make queue naming safe and predictable.
    """
    n = (name or "").strip()
    if not n:
        return DEFAULT_QUEUE_NAME
    return n


def get_queue(name: str = None) -> Queue:
    """
    Get an RQ queue by name.

    - If name is None/empty -> DEFAULT_QUEUE_NAME
    - If name == PUBLISH_QUEUE_NAME -> publish_queue shortcut
    - If name == DEFAULT_QUEUE_NAME -> default_queue shortcut
    - Else returns a new Queue(name, connection=redis_client)
    """
    qn = normalise_queue_name(name)

    if qn == PUBLISH_QUEUE_NAME:
        return publish_queue

    if qn == DEFAULT_QUEUE_NAME:
        return default_queue

    return Queue(qn, connection=redis_client, default_timeout=RQ_DEFAULT_TIMEOUT)


def get_scheduler(queue_name: str = None) -> Scheduler:
    """
    If you want to schedule jobs into a queue other than publish_queue.
    """
    q = get_queue(queue_name)
    return Scheduler(queue=q, connection=redis_client)


def enqueue(
    func: str,
    *args: Any,
    queue_name: str = None,
    job_timeout: Optional[int] = None,
    result_ttl: Optional[int] = None,
    failure_ttl: Optional[int] = None,
    ttl: Optional[int] = None,
    **kwargs: Any,
):
    """
    Convenience enqueue wrapper with consistent defaults.

    Example:
      enqueue(
        "app.services.social.jobs.publish_scheduled_post",
        post_id, business_id,
        queue_name="publish",
        job_timeout=180,
      )
    """
    q = get_queue(queue_name)

    return q.enqueue(
        func,
        *args,
        **kwargs,
        job_timeout=job_timeout or RQ_DEFAULT_TIMEOUT,
        result_ttl=result_ttl if result_ttl is not None else RQ_DEFAULT_RESULT_TTL,
        failure_ttl=failure_ttl if failure_ttl is not None else RQ_DEFAULT_FAILURE_TTL,
        ttl=ttl if ttl is not None else RQ_DEFAULT_TTL,
    )


def get_rq_defaults() -> Dict[str, Any]:
    """
    Handy for debugging your RQ config on an endpoint.
    """
    return {
        "PUBLISH_QUEUE_NAME": PUBLISH_QUEUE_NAME,
        "DEFAULT_QUEUE_NAME": DEFAULT_QUEUE_NAME,
        "RQ_DEFAULT_TIMEOUT": RQ_DEFAULT_TIMEOUT,
        "RQ_DEFAULT_RESULT_TTL": RQ_DEFAULT_RESULT_TTL,
        "RQ_DEFAULT_FAILURE_TTL": RQ_DEFAULT_FAILURE_TTL,
        "RQ_DEFAULT_TTL": RQ_DEFAULT_TTL,
        "redis_ok": ping_redis(),
    }
    
    
    
# # app/extensions/queue.py

# import os
# from rq import Queue
# from rq_scheduler import Scheduler

# from .redis_conn import redis_client

# PUBLISH_QUEUE_NAME = os.getenv("RQ_PUBLISH_QUEUE", "publish")

# publish_queue = Queue(PUBLISH_QUEUE_NAME, connection=redis_client)

# # This scheduler stores scheduled jobs in Redis and later moves them into `publish_queue`
# scheduler = Scheduler(queue=publish_queue, connection=redis_client)

# def get_queue(name: str = None) -> Queue:
#     if not name or name == PUBLISH_QUEUE_NAME:
#         return publish_queue

#     return Queue(name, connection=redis_client)