# app/services/social/jobs_snapshot.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Any

from ...utils.logger import Log
from ...models.social.social_account import SocialAccount
from ...models.social.social_daily_snapshot import SocialDailySnapshot
from .appctx import run_in_app_context


def _today_ymd() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _collect_one_snapshot(acct: dict) -> Dict[str, Any]:
    """
    Keep it SIMPLE and consistent:
      data = { followers, posts, impressions, engagements, likes, comments }
    For platforms where API is hard/limited, store what you can.
    """
    log_tag = "[jobs_snapshot.py]"

    platform = acct.get("platform")
    destination_id = acct.get("destination_id")
    access_token = acct.get("access_token")
    
    from ...resources.social.insights.facebook_insights_resource import (
            _get_facebook_page_info,
            _fetch_page_insights,
        )

    page_info = _get_facebook_page_info(
        page_id=destination_id,
        access_token=access_token,
        log_tag=log_tag,
    )

    # default empty snapshot
    data = {
        "followers": 0,
        "posts": 0,
        "impressions": 0,
        "engagements": 0,
        "likes": 0,
        "comments": 0,
    }

    # TODO: plug in real fetchers per platform.
    # You already have working adapters for publishing.
    # For analytics, call your existing insight endpoints/services where available:
    # - Facebook page lookup + insights
    # - Instagram account info + insights
    # - TikTok user.info.stats
    # - X user public_metrics
    # - YouTube channel statistics
    # - Pinterest account/board stats (if enabled)
    #
    # Until then, snapshot stays zeros and your UI still works.

    return data


def _run_snapshot_daily():
    log_tag = "[jobs_snapshot]"
    date = _today_ymd()

    # iterate all connected accounts for all businesses/users
    # if you want to scope by business, create another job with business_id param
    accounts = SocialAccount.list_all_connected()  # implement below

    Log.info(f"{log_tag} connected_accounts={len(accounts)} date={date}")

    for acct in accounts:
        try:
            business_id = str(acct["business_id"])
            user__id = str(acct["user__id"])
            platform = acct["platform"]
            destination_id = acct["destination_id"]

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


def snapshot_daily():
    return run_in_app_context(_run_snapshot_daily)