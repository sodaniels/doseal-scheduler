# app/services/social/providers/instagram_provider.py

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from .base import ProviderResult, SocialProviderBase
from ....models.social.social_account import SocialAccount


def _parse_ymd(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def _fmt_ymd(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


class InstagramProvider(SocialProviderBase):
    platform = "instagram"

    def __init__(self, *, graph_version: str = "v21.0"):
        self.graph_version = graph_version

    def fetch_range(
        self,
        *,
        business_id: str,
        user__id: str,
        destination_id: str,
        since_ymd: str,
        until_ymd: str,
    ) -> ProviderResult:
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="instagram",
            destination_id=destination_id,
        )
        if not acct:
            return ProviderResult(self.platform, destination_id, None, {}, [], {"error": "IG_NOT_CONNECTED"})

        access_token = acct.get("access_token_plain") or  acct.get("access_token")
        if not access_token:
            return ProviderResult(self.platform, destination_id, acct.get("destination_name"), {}, [], {"error": "IG_TOKEN_MISSING"})

        # Import internal helper methods (no HTTP)
        from ....resources.social.insights.instagram_insights_resource import (
            _get_instagram_account_info,
            _fetch_account_insights,
        )

        account_info = _get_instagram_account_info(
            ig_user_id=destination_id,
            access_token=access_token,
            log_tag="[instagram_provider.py][InstagramProvider]",
        )

        followers_now = (account_info.get("followers_count") or 0) if account_info.get("success") else 0

        # Canonical totals
        totals = {
            "followers": int(followers_now or 0),
            "new_followers": 0,      # IG follower_count is a time-series metric but may be limited
            "posts": 0,
            "impressions": 0,
            "engagements": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "reactions": 0,
        }

        # Use the metrics you confirmed: impressions, reach, follower_count (30 days only)
        metrics = ["impressions", "follower_count"]

        insights = _fetch_account_insights(
            ig_user_id=destination_id,
            access_token=access_token,
            metrics=metrics,
            period="day",
            since=since_ymd,
            until=until_ymd,
            log_tag="[InstagramProvider]",
        )

        timeline_map: Dict[str, Dict[str, Any]] = {}

        metric_series = insights.get("metrics", {}) or {}
        for metric_name, series in metric_series.items():
            for row in series or []:
                end_time = (row.get("end_time") or "")[:10]
                if not end_time:
                    continue
                pt = timeline_map.setdefault(
                    end_time,
                    {"date": end_time, "followers": None, "new_followers": 0, "posts": 0, "impressions": 0, "engagements": 0},
                )
                val = row.get("value") or 0
                if metric_name == "impressions":
                    pt["impressions"] += int(val or 0)
                elif metric_name == "follower_count":
                    # IG returns “net new followers” per day (but only recent window)
                    pt["new_followers"] += int(val or 0)

        for d in timeline_map.values():
            totals["impressions"] += int(d.get("impressions") or 0)
            totals["new_followers"] += int(d.get("new_followers") or 0)

        timeline = [timeline_map[k] for k in sorted(timeline_map.keys())]

        return ProviderResult(
            platform=self.platform,
            destination_id=destination_id,
            destination_name=acct.get("destination_name") or account_info.get("username"),
            totals=totals,
            timeline=timeline,
            debug=None,
        )