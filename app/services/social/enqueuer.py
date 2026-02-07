
# app/services/social/enqueuer.py

from __future__ import annotations

import os
import time
from typing import Optional

from app import create_social_app as create_app
from ...extensions.queue import get_queue, enqueue, ping_redis
from ...models.social.scheduled_post import ScheduledPost
from ...utils.logger import Log


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def enqueue_due_posts(
    poll_seconds: Optional[int] = None,
    limit: Optional[int] = None,
    queue_name: Optional[str] = None,
):
    """
    Hootsuite-style:
      - claim due posts (scheduled -> enqueued) atomically
      - push publish jobs into Redis queue
      - workers consume and publish

    Env overrides:
      - ENQUEUER_POLL_SECONDS (default 5)
      - ENQUEUER_LIMIT (default 50)
      - RQ_PUBLISH_QUEUE (default "publish")  (from queu.py)
    """
    poll_seconds = poll_seconds if poll_seconds is not None else _env_int("ENQUEUER_POLL_SECONDS", 5)
    limit = limit if limit is not None else _env_int("ENQUEUER_LIMIT", 50)
    queue_name = (queue_name or os.getenv("RQ_PUBLISH_QUEUE") or "publish").strip() or "publish"

    app = create_app()
    q = get_queue(queue_name)

    with app.app_context():
        Log.info(f"[enqueuer][start] polling due posts... queue={queue_name} poll={poll_seconds}s limit={limit}")

        # Best-effort Redis health check
        if not ping_redis():
            Log.info("[enqueuer][warn] redis ping failed (will continue and retry on loop)")

        while True:
            try:
                claimed = ScheduledPost.claim_due_posts(limit=limit) or []

                if claimed:
                    Log.info(f"[enqueuer] claimed={len(claimed)}")

                for post in claimed:
                    post_id = str(post.get("_id") or "")
                    business_id = str(post.get("business_id") or "")

                    if not post_id or not business_id:
                        Log.info(f"[enqueuer][skip] invalid post payload: _id={post.get('_id')} business_id={post.get('business_id')}")
                        continue

                    # enqueue publish job (preferred wrapper: consistent defaults)
                    try:
                        job = enqueue(
                            "app.services.social.jobs.publish_scheduled_post",
                            post_id,
                            business_id,
                            queue_name=queue_name,
                            job_timeout=180,
                            result_ttl=300,
                            failure_ttl=86400,
                        )
                        Log.info(f"[enqueuer][queued] post_id={post_id} business_id={business_id} job_id={getattr(job, 'id', None)}")
                    except Exception as e:
                        # fallback to raw q.enqueue if wrapper fails for any reason
                        Log.info(f"[enqueuer][enqueue_error] post_id={post_id} err={e}")
                        q.enqueue(
                            "app.services.social.jobs.publish_scheduled_post",
                            post_id,
                            business_id,
                            job_timeout=180,
                            result_ttl=300,
                            failure_ttl=86400,
                        )

                time.sleep(max(1, int(poll_seconds)))

            except Exception as e:
                Log.info(f"[enqueuer][error] {e}")
                time.sleep(5)

# # app/services/social/enqueuer.py

# import os
# import time

# from app import create_social_app as create_app
# from ...extensions.queue import get_queue  # <-- you should have this helper; see below
# from ...models.social.scheduled_post import ScheduledPost
# from ...utils.logger import Log


# def enqueue_due_posts(poll_seconds: int = 5, limit: int = 50):
#     """
#     Hootsuite-style:
#       - claim due posts (scheduled -> enqueued) atomically
#       - push publish jobs into Redis queue
#       - workers consume and publish
#     """
#     app = create_app()
#     q = get_queue("publish")

#     with app.app_context():
#         Log.info("[enqueuer][start] polling due posts...")

#         while True:
#             try:
#                 claimed = ScheduledPost.claim_due_posts(limit=limit)
#                 if claimed:
#                     Log.info(f"[enqueuer] claimed={len(claimed)}")

#                 for post in claimed:
#                     post_id = post["_id"]
#                     business_id = post["business_id"]

#                     # enqueue publish job
#                     q.enqueue(
#                         "app.services.social.jobs.publish_scheduled_post",
#                         post_id,
#                         business_id,
#                         job_timeout=180,     # adjust as needed
#                         result_ttl=300,
#                         failure_ttl=86400,
#                     )

#                 time.sleep(poll_seconds)

#             except Exception as e:
#                 Log.info(f"[enqueuer][error] {e}")
#                 time.sleep(5)