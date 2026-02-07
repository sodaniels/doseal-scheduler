# app/services/social/jobs_snapshot.py
#
# Daily social snapshots (followers / posts / impressions / engagements etc.)
#
# Key design:
# - ONE consistent snapshot shape across platforms
# - Iterate CONNECTED social accounts (not businesses) so you always write data
# - Provide an optional per-business runner (uses SocialAccount.get_all_by_business_id)
#
# NOTE:
# - Facebook collector wires into your existing internal helpers:
#     _get_facebook_page_info, _fetch_page_insights
# - Other platforms are safe stubs for now (use acct.meta if you stored counts)
#
# RQ entrypoints:
#   - app.services.social.jobs_snapshot.snapshot_daily
#   - app.services.social.jobs_snapshot.snapshot_daily_for_business

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

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
    dt = dt - timedelta(days=1)
    return dt.strftime("%Y-%m-%d")


# -----------------------------
# Token helpers
# -----------------------------
def _get_access_token(acct: dict) -> Optional[str]:
    """
    Normalize token field differences across your codebase.
    Prefers *_plain but falls back to other common keys.
    """
    meta = acct.get("meta") or {}
    return (
        acct.get("access_token_plain")
        or acct.get("access_token")
        or meta.get("access_token")
        or meta.get("token")
    )


def _get_refresh_token(acct: dict) -> Optional[str]:
    meta = acct.get("meta") or {}
    return (
        acct.get("refresh_token_plain")
        or acct.get("refresh_token")
        or meta.get("refresh_token")
    )


# -----------------------------
# Snapshot shape & parsing
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
        # extra debug keys you may add per platform:
        # "_raw": None,
        # "_error": None,
    }


def _ensure_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        if isinstance(v, bool):
            return default
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            return int(v)
        if isinstance(v, str):
            s = v.strip()
            if s.isdigit():
                return int(s)
            # try float-like strings
            try:
                return int(float(s))
            except Exception:
                return default
        return default
    except Exception:
        return default


def _last_series_value(series: Any) -> int:
    """
    Series is usually: [{"end_time": "...", "value": 123}, ...]
    """
    if not isinstance(series, list) or not series:
        return 0
    last = series[-1] or {}
    if isinstance(last, dict):
        return _ensure_int(last.get("value"), 0)
    return 0


def _is_connected(acct: dict) -> bool:
    """
    Best-effort 'connected' check:
    - if is_connected is explicitly False => not connected
    - must have destination_id + access token
    """
    if acct.get("is_connected") is False:
        return False
    destination_id = str(acct.get("destination_id") or "").strip()
    if not destination_id:
        return False
    if not _get_access_token(acct):
        return False
    return True


# -----------------------------
# Facebook collector (REAL)
# -----------------------------
def _collect_facebook_page_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    """
    Uses your existing internal Facebook insights helpers.

    Requires your module:
      app/resources/social/insights/facebook_insights_resource.py
        - _get_facebook_page_info(page_id, access_token, log_tag)
        - _fetch_page_insights(page_id, access_token, metrics, period, since, until, log_tag)
    """
    data = _empty_snapshot()

    page_id = str(acct.get("destination_id") or "").strip()
    access_token = _get_access_token(acct)

    if not page_id:
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

    # 1) page info (followers/fans)
    page_info = _get_facebook_page_info(
        page_id=page_id,
        access_token=access_token,
        log_tag=log_tag,
    )

    raw = page_info.get("raw") if isinstance(page_info, dict) else {}
    followers = (
        (page_info.get("followers_count") if isinstance(page_info, dict) else None)
        or (page_info.get("fan_count") if isinstance(page_info, dict) else None)
        or (raw.get("followers_count") if isinstance(raw, dict) else None)
        or (raw.get("fan_count") if isinstance(raw, dict) else None)
        or 0
    )
    data["followers"] = _ensure_int(followers, 0)

    # 2) insights (use last 2 days to avoid FB lag; take last value)
    since = _yesterday_ymd()
    until = _today_ymd()

    metrics = [
        "page_impressions",
        "page_engaged_users",
        "page_post_engagements",
    ]

    insights = _fetch_page_insights(
        page_id=page_id,
        access_token=access_token,
        metrics=metrics,
        period="day",
        since=since,
        until=until,
        log_tag=log_tag,
    )

    metrics_obj = insights.get("metrics") if isinstance(insights, dict) else {}
    impressions_series = (metrics_obj or {}).get("page_impressions") or []
    engaged_series = (metrics_obj or {}).get("page_engaged_users") or []
    post_eng_series = (metrics_obj or {}).get("page_post_engagements") or []

    data["impressions"] = _last_series_value(impressions_series)
    engaged = _last_series_value(engaged_series)
    post_eng = _last_series_value(post_eng_series)
    data["engagements"] = max(engaged, post_eng)

    return data


# -----------------------------
# Instagram collector (SAFE STUB)
# -----------------------------
def _collect_instagram_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    data = _empty_snapshot()
    meta = acct.get("meta") or {}

    # If you stored these in meta during connect, they show up here.
    data["followers"] = _ensure_int(meta.get("followers_count") or meta.get("followers"), 0)
    data["posts"] = _ensure_int(meta.get("media_count") or meta.get("posts"), 0)

    # impressions/engagements should come from your instagram_insights service later
    return data


# -----------------------------
# X collector (SAFE STUB)
# -----------------------------
def _collect_x_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    data = _empty_snapshot()
    meta = acct.get("meta") or {}
    data["followers"] = _ensure_int(meta.get("followers_count"), 0)
    data["posts"] = _ensure_int(meta.get("tweet_count"), 0)
    return data


# -----------------------------
# TikTok collector (SAFE STUB)
# -----------------------------
def _collect_tiktok_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    data = _empty_snapshot()
    meta = acct.get("meta") or {}
    data["followers"] = _ensure_int(meta.get("follower_count") or meta.get("followers"), 0)
    data["posts"] = _ensure_int(meta.get("video_count") or meta.get("videos"), 0)
    return data


# -----------------------------
# YouTube collector (SAFE STUB)
# -----------------------------
def _collect_youtube_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    data = _empty_snapshot()
    meta = acct.get("meta") or {}
    data["followers"] = _ensure_int(meta.get("subscribers") or meta.get("subscriberCount"), 0)
    data["posts"] = _ensure_int(meta.get("videoCount") or meta.get("videos"), 0)
    return data


# -----------------------------
# Pinterest collector (SAFE STUB)
# -----------------------------
def _collect_pinterest_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    data = _empty_snapshot()
    meta = acct.get("meta") or {}
    data["followers"] = _ensure_int(meta.get("followers"), 0)
    data["posts"] = _ensure_int(meta.get("pins") or meta.get("posts"), 0)
    return data


# -----------------------------
# Threads collector (SAFE STUB)
# -----------------------------
def _collect_threads_snapshot(acct: dict, log_tag: str) -> Dict[str, Any]:
    data = _empty_snapshot()
    meta = acct.get("meta") or {}
    data["followers"] = _ensure_int(meta.get("followers"), 0)
    data["posts"] = _ensure_int(meta.get("posts"), 0)
    return data


# -----------------------------
# Router
# -----------------------------
def _collect_one_snapshot(acct: dict) -> Dict[str, Any]:
    log_tag = "[jobs_snapshot][_collect_one_snapshot]"
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

        d = _empty_snapshot()
        d["_error"] = f"Unsupported platform for snapshots: {platform}"
        return d

    except Exception as e:
        Log.info(f"{log_tag} platform={platform} destination_id={destination_id} err={e}")
        d = _empty_snapshot()
        d["_error"] = str(e)
        return d


# -----------------------------
# Runner: for ONE business_id
# -----------------------------
def _run_snapshot_daily_for_business(business_id: str):
    log_tag = "[jobs_snapshot][daily_for_business]"
    date = _today_ymd()

    Log.info(f"{log_tag} running_file={__file__} business_id={business_id} date={date}")

    accounts = SocialAccount.get_all_by_business_id(business_id) or []
    connected = [a for a in accounts if _is_connected(a)]

    Log.info(f"{log_tag} business_id={business_id} accounts={len(accounts)} connected={len(connected)} date={date}")

    wrote = 0

    for acct in connected:
        try:
            user__id = str(acct.get("user__id") or "")
            platform = (acct.get("platform") or "").strip().lower()
            destination_id = str(acct.get("destination_id") or "").strip()

            if not user__id or not platform or not destination_id:
                Log.info(f"{log_tag} skip invalid acct: platform={platform} destination_id={destination_id}")
                continue

            snap = _collect_one_snapshot(acct)

            SocialDailySnapshot.upsert_snapshot(
                business_id=business_id,
                user__id=user__id,
                platform=platform,
                destination_id=destination_id,
                date_ymd=date,
                data=snap,
            )
            wrote += 1

        except Exception as e:
            Log.info(f"{log_tag} failed acct={acct.get('platform')}:{acct.get('destination_id')} err={e}")

    Log.info(f"{log_tag} business_id={business_id} wrote_snapshots={wrote} date={date}")


def snapshot_daily_for_business(business_id: str):
    """
    RQ entrypoint:
      enqueue("app.services.social.jobs_snapshot.snapshot_daily_for_business", business_id, queue_name="publish")
    """
    return run_in_app_context(_run_snapshot_daily_for_business, business_id)


# -----------------------------
# Runner: ALL connected accounts (RECOMMENDED)
# -----------------------------
def _run_snapshot_daily_all():
    """
    Iterates all connected SocialAccounts and writes snapshots.
    This avoids the "business_count=0" trap entirely.
    """
    log_tag = "[jobs_snapshot][daily_all]"
    date = _today_ymd()

    Log.info(f"{log_tag} running_file={__file__} date={date}")

    # You must implement this in SocialAccount (or alias it):
    # - list_all_connected() should return ALL accounts with valid tokens
    accounts = SocialAccount.list_all_connected() or []
    Log.info(f"{log_tag} connected_accounts={len(accounts)} date={date}")

    wrote = 0

    for acct in accounts:
        try:
            business_id = str(acct.get("business_id") or "")
            user__id = str(acct.get("user__id") or "")
            platform = (acct.get("platform") or "").strip().lower()
            destination_id = str(acct.get("destination_id") or "").strip()

            if not business_id or not user__id or not platform or not destination_id:
                continue

            snap = _collect_one_snapshot(acct)

            SocialDailySnapshot.upsert_snapshot(
                business_id=business_id,
                user__id=user__id,
                platform=platform,
                destination_id=destination_id,
                date_ymd=date,
                data=snap,
            )
            wrote += 1

        except Exception as e:
            Log.info(f"{log_tag} failed acct={acct.get('platform')}:{acct.get('destination_id')} err={e}")

    Log.info(f"{log_tag} wrote_snapshots={wrote} date={date}")


def snapshot_daily():
    """
    RQ entrypoint (recommended):
      enqueue("app.services.social.jobs_snapshot.snapshot_daily", queue_name="publish")
    """
    return run_in_app_context(_run_snapshot_daily_all)