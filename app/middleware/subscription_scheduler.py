# utils/subscription_scheduler.py

from datetime import datetime
from ..utils.redis import (
    get_redis, set_redis_with_expiry, remove_redis, set_redis
)

from ..services.pos.subscription_service import SubscriptionService
from ..utils.logger import Log

REDIS_KEY = "subscription:scheduler:last_run"
RUN_INTERVAL_SECONDS = 300  # 5 minutes (safe)


def run_scheduled_subscription_activation():
    """
    Run scheduled subscription activation at most once per interval.
    """
    now = int(datetime.utcnow().timestamp())

    last_run = get_redis(REDIS_KEY)
    if last_run and (now - int(last_run)) < RUN_INTERVAL_SECONDS:
        return  # ⛔ skip — recently executed

    try:
        Log.info("[SubscriptionScheduler] Running scheduled activation")
        SubscriptionService.activate_due_scheduled_subscriptions()
        set_redis(REDIS_KEY, now)
    except Exception as e:
        Log.error(f"[SubscriptionScheduler] Error: {e}", exc_info=True)