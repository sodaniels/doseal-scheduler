# app/services/social/jobs_snapshot.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ...utils.logger import Log
from ...models.social.social_account import SocialAccount
from ...models.social.social_daily_snapshot import SocialDailySnapshot
from .appctx import run_in_app_context


# -----------------------------
# Date helpers
# -----------------------------
def _today_ymd() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _yesterday_ymd() -> str:
    dt = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    dt = dt - timedelta(days=1)  # noqa
    return dt.strftime("%Y-%m-%d")


# (avoid top-level timedelta import if your lint is strict)
from datetime import timedelta  # noqa: E402


# -----------------------------
# Token helpers
# -----------------------------
def _get_access_token(acct: dict) -> Optional[str]:
    """
    Normalize token field name differences across your codebase.
    """
    return (
        acct.get("access_token_plain")
        or acct.get("access_token")
        or (acct.get("meta") or {}).get("access_token")
    )


def _get_refresh_token(acct: dict) -> Optional[str]:
    return (
        acct.get("refresh_token_plain")
        or acct.get("refresh_token")
        or (acct.get("meta") or {}).get("refresh_token")
    )


# -----------------------------
# Snapshot shape
# -----------------------------
def _empty_snapshot() -> Dict[str, Any]:
    return {
        "followers": 0,
        "posts": 0,
        "impressions": 0,
        "engagements": 0,
        "likes": 0,
        "comments": 0,
        "shares": 0,
        "reactions": 0,
        # you can extend later:
        # "views": 0,
        # "clicks": 0,
    }


def _ensure_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        if isinstance(v, bool):
            return default
        if isinstance(v, (int, float)):
            return int(v)
        if isinstance(v, str) and v.strip().isdigit():
            return int(v.strip())
        return default
    except Exception:
        return default


# -----------------------------
# Facebook collector (REAL)
# -----------------------------
def _collect_facebook_page_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    """
    Uses your existing internal Facebook insights helpers.

    Requires:
      from ...resources.social.insights.facebook_insights_resource import
        _get_facebook_page_info, _fetch_page_insights
    """
    data = _empty_snapshot()

    destination_id = str(acct.get("destination_id") or "").strip()  # page_id
    access_token = _get_access_token(acct)

    if not destination_id:
        data["_error"] = "Missing destination_id (page_id)"
        return data
    if not access_token:
        data["_error"] = "Missing facebook access token"
        return data

    # lazy import to avoid circular imports
    from ...resources.social.insights.facebook_insights_resource import (  # type: ignore
        _get_facebook_page_info,
        _fetch_page_insights,
    )

    # 1) Page info (followers/fans)
    page_info = _get_facebook_page_info(
        page_id=destination_id,
        access_token=access_token,
        log_tag=log_tag,
    )

    # page_info structure depends on your implementation; we try common keys
    # Typical keys: followers_count, fan_count, name
    followers = (
        page_info.get("followers_count")
        or page_info.get("fan_count")
        or ((page_info.get("raw") or {}).get("followers_count"))
        or ((page_info.get("raw") or {}).get("fan_count"))
        or 0
    )

    data["followers"] = _ensure_int(followers)

    # 2) Insights: daily page metrics
    # Use LAST 1 day range (today only) OR last 2 days (safer because FB can lag).
    since = _today_ymd()
    until = _today_ymd()

    # Choose metrics that are stable in Graph:
    # - page_impressions
    # - page_engaged_users
    # - page_post_engagements (sometimes)
    # - page_fans / page_follows (varies)
    metrics = [
        "page_impressions",
        "page_engaged_users",
        "page_post_engagements",
    ]

    insights = _fetch_page_insights(
        page_id=destination_id,
        access_token=access_token,
        metrics=metrics,
        period="day",
        since=since,
        until=until,
        log_tag=log_tag,
    )

    # insights structure depends on your helper; we handle common shapes:
    # Expected: {"metrics": {metric_name: [{"end_time":..., "value":...}, ...]}}
    metrics_obj = insights.get("metrics") or {}
    impressions_series = metrics_obj.get("page_impressions") or []
    engaged_series = metrics_obj.get("page_engaged_users") or []
    post_eng_series = metrics_obj.get("page_post_engagements") or []

    def _last_value(series: list) -> int:
        if not series:
            return 0
        last = series[-1] if isinstance(series, list) else {}
        return _ensure_int((last or {}).get("value"))

    data["impressions"] = _last_value(impressions_series)
    engaged = _last_value(engaged_series)
    post_eng = _last_value(post_eng_series)

    # Treat engagements as the best available sum
    data["engagements"] = max(engaged, post_eng)

    # If you later fetch reactions/comments/shares from post list aggregation,
    # store them too. For now keep as 0.
    return data


# -----------------------------
# Instagram collector (SAFE STUB)
# -----------------------------
def _collect_instagram_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    """
    If you already have instagram_insights.py (account info + insights),
    you can wire it in similarly. For now, safe snapshot from stored meta if any.
    """
    data = _empty_snapshot()

    meta = acct.get("meta") or {}
    data["followers"] = _ensure_int(meta.get("followers_count") or meta.get("followers") or 0)
    data["posts"] = _ensure_int(meta.get("media_count") or meta.get("posts") or 0)

    # impressions/engagements should come from insights endpoint or snapshot service
    return data


# -----------------------------
# X collector (SAFE STUB)
# -----------------------------
def _collect_x_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    data = _empty_snapshot()
    meta = acct.get("meta") or {}
    data["followers"] = _ensure_int(meta.get("followers_count") or 0)
    data["posts"] = _ensure_int(meta.get("tweet_count") or 0)
    return data


# -----------------------------
# TikTok collector (SAFE STUB)
# -----------------------------
def _collect_tiktok_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    data = _empty_snapshot()
    meta = acct.get("meta") or {}
    data["followers"] = _ensure_int(meta.get("follower_count") or meta.get("followers") or 0)
    data["posts"] = _ensure_int(meta.get("video_count") or meta.get("videos") or 0)
    return data


# -----------------------------
# YouTube collector (SAFE STUB)
# -----------------------------
def _collect_youtube_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    data = _empty_snapshot()
    meta = acct.get("meta") or {}
    data["followers"] = _ensure_int(meta.get("subscribers") or meta.get("subscriberCount") or 0)
    data["posts"] = _ensure_int(meta.get("videoCount") or meta.get("videos") or 0)
    # impressions/views should come from YouTube Analytics API later
    return data


# -----------------------------
# Pinterest collector (SAFE STUB)
# -----------------------------
def _collect_pinterest_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    data = _empty_snapshot()
    meta = acct.get("meta") or {}
    data["followers"] = _ensure_int(meta.get("followers") or 0)
    data["posts"] = _ensure_int(meta.get("pins") or meta.get("posts") or 0)
    return data


# -----------------------------
# Threads collector (SAFE STUB)
# -----------------------------
def _collect_threads_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    data = _empty_snapshot()
    meta = acct.get("meta") or {}
    data["followers"] = _ensure_int(meta.get("followers") or 0)
    data["posts"] = _ensure_int(meta.get("posts") or 0)
    return data


# -----------------------------
# Router
# -----------------------------
def _collect_one_snapshot(acct: dict) -> Dict[str, Any]:
    log_tag = "[jobs_snapshot.py][_collect_one_snapshot]"

    platform = (acct.get("platform") or "").strip().lower()
    destination_id = str(acct.get("destination_id") or "").strip()

    if not platform or not destination_id:
        d = _empty_snapshot()
        d["_error"] = "Missing platform or destination_id"
        return d

    try:
        if platform == "facebook":
            return _collect_facebook_page_snapshot(acct, log_tag)

        if platform == "instagram":
            return _collect_instagram_snapshot(acct, log_tag)

        if platform in ("x", "twitter"):
            return _collect_x_snapshot(acct, log_tag)

        if platform == "tiktok":
            return _collect_tiktok_snapshot(acct, log_tag)

        if platform == "youtube":
            return _collect_youtube_snapshot(acct, log_tag)

        if platform == "pinterest":
            return _collect_pinterest_snapshot(acct, log_tag)

        if platform == "threads":
            return _collect_threads_snapshot(acct, log_tag)

        # Not implemented yet:
        d = _empty_snapshot()
        d["_error"] = f"Unsupported platform for snapshots: {platform}"
        return d

    except Exception as e:
        Log.info(f"{log_tag} platform={platform} destination_id={destination_id} err={e}")
        d = _empty_snapshot()
        d["_error"] = str(e)
        return d


# -----------------------------
# Runner: by business_id (YOUR request)
# -----------------------------
def _run_snapshot_daily_for_business(business_id: str):
    log_tag = "[jobs_snapshot][daily_for_business]"
    date = _today_ymd()

    accounts = SocialAccount.get_all_by_business_id(business_id) or []
    Log.info(f"{log_tag} business_id={business_id} accounts={len(accounts)} date={date}")

    for acct in accounts:
        try:
            # normalize ids
            user__id = str(acct.get("user__id") or "")
            platform = (acct.get("platform") or "").strip().lower()
            destination_id = str(acct.get("destination_id") or "")

            if not user__id or not platform or not destination_id:
                Log.info(f"{log_tag} skip invalid acct: platform={platform} destination_id={destination_id}")
                continue

            # if you store connection flag, skip disconnected
            if acct.get("is_connected") is False:
                continue

            data = _collect_one_snapshot(acct)

            SocialDailySnapshot.upsert_snapshot(
                business_id=business_id,
                user__id=user__id,
                platform=platform,
                destination_id=destination_id,
                date_ymd=date,
                data=data,
            )

        except Exception as e:
            Log.info(f"{log_tag} failed acct={acct.get('platform')}:{acct.get('destination_id')} err={e}")


def snapshot_daily_for_business(business_id: str):
    """
    RQ entrypoint:
      q.enqueue("app.services.social.jobs_snapshot.snapshot_daily_for_business", business_id)
    """
    return run_in_app_context(_run_snapshot_daily_for_business, business_id)


# -----------------------------
# Runner: ALL businesses (optional, if you implement a business list)
# -----------------------------
def _run_snapshot_daily_all():
    """
    Optional: if you have a Business model, iterate businesses.
    If you don’t, just schedule per business_id.
    """
    log_tag = "[jobs_snapshot][daily_all]"
    date = _today_ymd()

    # Implement this in your own codebase:
    # business_ids = Business.get_all_ids()
    business_ids: List[str] = []

    Log.info(f"{log_tag} business_count={len(business_ids)} date={date}")

    for bid in business_ids:
        try:
            _run_snapshot_daily_for_business(bid)
        except Exception as e:
            Log.info(f"{log_tag} failed business_id={bid} err={e}")


def snapshot_daily():
    """
    Optional entrypoint if you implement business listing.
    """
    return run_in_app_context(_run_snapshot_daily_all)