# app/services/social/enqueuer.py

import os
import time

from app import create_social_app as create_app
from ...extensions.queue import get_queue  # <-- you should have this helper; see below
from ...models.social.scheduled_post import ScheduledPost
from ...utils.logger import Log


def enqueue_due_posts(poll_seconds: int = 5, limit: int = 50):
    """
    Hootsuite-style:
      - claim due posts (scheduled -> enqueued) atomically
      - push publish jobs into Redis queue
      - workers consume and publish
    """
    app = create_app()
    q = get_queue("publish")

    with app.app_context():
        Log.info("[enqueuer][start] polling due posts...")

        while True:
            try:
                claimed = ScheduledPost.claim_due_posts(limit=limit)
                if claimed:
                    Log.info(f"[enqueuer] claimed={len(claimed)}")

                for post in claimed:
                    post_id = post["_id"]
                    business_id = post["business_id"]

                    # enqueue publish job
                    q.enqueue(
                        "app.services.social.jobs.publish_scheduled_post",
                        post_id,
                        business_id,
                        job_timeout=180,     # adjust as needed
                        result_ttl=300,
                        failure_ttl=86400,
                    )

                time.sleep(poll_seconds)

            except Exception as e:
                Log.info(f"[enqueuer][error] {e}")
                time.sleep(5)