# app/utils/church/api_rate_limiter.py

import time
from ...extensions.db import db
from ...utils.logger import Log
from bson import ObjectId


class ApiRateLimitError(Exception):
    def __init__(self, limit_type, limit, reset_at=None):
        self.limit_type = limit_type
        self.limit = limit
        self.reset_at = reset_at
        self.message = f"API rate limit exceeded. Max {limit} requests per {limit_type}."
        self.meta = {
            "limit_type": limit_type,
            "limit": limit,
            "reset_at": reset_at,
            "action_required": "slow_down",
        }
        super().__init__(self.message)


def check_api_rate_limit(business_id):
    """
    Check both per-minute and per-day API rate limits.
    Uses MongoDB counters with TTL (or Redis if available).

    Call this at the top of any API-facing endpoint or in middleware.
    """
    try:
        from ...utils.feature_gate import get_business_package

        package = get_business_package(business_id)
        if not package:
            return True  # No package = let subscription check handle it

        max_per_day = package.get("max_api_requests_per_day", 0)
        max_per_minute = package.get("api_rate_limit_per_minute", 0)

        # -1 = unlimited
        if max_per_day == -1 and max_per_minute == -1:
            return True

        c = db.get_collection("api_rate_limits")
        now = time.time()
        today = time.strftime("%Y-%m-%d")
        current_minute = time.strftime("%Y-%m-%d-%H-%M")

        bid = str(business_id)

        # ── Per-day check ──
        if max_per_day != -1 and max_per_day > 0:
            day_key = f"{bid}:{today}"
            day_doc = c.find_one({"_id": day_key})

            if day_doc and day_doc.get("count", 0) >= max_per_day:
                raise ApiRateLimitError("day", max_per_day, reset_at=f"{today}T23:59:59Z")

            c.update_one(
                {"_id": day_key},
                {
                    "$inc": {"count": 1},
                    "$setOnInsert": {"created_at": now, "type": "day"},
                },
                upsert=True,
            )

        # ── Per-minute check ──
        if max_per_minute != -1 and max_per_minute > 0:
            min_key = f"{bid}:{current_minute}"
            min_doc = c.find_one({"_id": min_key})

            if min_doc and min_doc.get("count", 0) >= max_per_minute:
                raise ApiRateLimitError("minute", max_per_minute)

            c.update_one(
                {"_id": min_key},
                {
                    "$inc": {"count": 1},
                    "$setOnInsert": {"created_at": now, "type": "minute"},
                },
                upsert=True,
            )

        return True

    except ApiRateLimitError:
        raise
    except Exception as e:
        Log.error(f"[check_api_rate_limit] {e}")
        return True  # Fail open


def get_api_usage(business_id):
    """Get current API usage for dashboard display."""
    try:
        from ...utils.feature_gate import get_business_package

        c = db.get_collection("api_rate_limits")
        bid = str(business_id)
        today = time.strftime("%Y-%m-%d")

        day_doc = c.find_one({"_id": f"{bid}:{today}"})
        used_today = day_doc.get("count", 0) if day_doc else 0

        package = get_business_package(business_id)
        max_per_day = package.get("max_api_requests_per_day", 0) if package else 0
        max_per_minute = package.get("api_rate_limit_per_minute", 0) if package else 0

        if max_per_day == -1:
            remaining = "Unlimited"
            pct = 0
        elif max_per_day > 0:
            remaining = max(0, max_per_day - used_today)
            pct = round((used_today / max_per_day) * 100, 1)
        else:
            remaining = 0
            pct = 100

        return {
            "used_today": used_today,
            "daily_limit": "Unlimited" if max_per_day == -1 else max_per_day,
            "remaining": remaining,
            "pct": pct,
            "per_minute_limit": "Unlimited" if max_per_minute == -1 else max_per_minute,
        }
    except Exception as e:
        Log.error(f"[get_api_usage] {e}")
        return {"used_today": 0, "daily_limit": 0, "remaining": 0, "pct": 0}


def create_rate_limit_indexes():
    """Create TTL index to auto-clean old rate limit docs."""
    try:
        c = db.get_collection("api_rate_limits")
        # Auto-delete after 48 hours (day counters need to survive midnight)
        c.create_index("created_at", expireAfterSeconds=172800)
        return True
    except Exception as e:
        Log.error(f"[create_rate_limit_indexes] {e}")
        return False