# app/services/social/providers/facebook_provider.py

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .base import ProviderResult, SocialProviderBase
from ....models.social.social_account import SocialAccount
from ....utils.logger import Log


def _parse_ymd(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def _fmt_ymd(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _daterange_chunks(since_ymd: str, until_ymd: str, max_days: int = 93):
    """
    Facebook insights throws:
      "There cannot be more than 93 days between since and until"
    So we chunk.
    """
    start = _parse_ymd(since_ymd)
    end = _parse_ymd(until_ymd)

    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=max_days - 1), end)
        yield _fmt_ymd(cur), _fmt_ymd(chunk_end)
        cur = chunk_end + timedelta(days=1)


class FacebookProvider(SocialProviderBase):
    platform = "facebook"

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
        log_tag = "[facebook_provider.py][FacebookProvider][fetch_range]"

        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="facebook",
            destination_id=destination_id,
        )
        if not acct:
            return ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=None,
                totals={},
                timeline=[],
                debug={"error": "FB_NOT_CONNECTED"},
            )

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=acct.get("destination_name"),
                totals={},
                timeline=[],
                debug={"error": "FB_TOKEN_MISSING"},
            )

        # -----
        # IMPORTANT:
        # Use your existing endpoints/functions if you already implemented:
        #   /social/facebook/page-insights
        # Here we just outline canonical mapping from your metrics.
        # -----

        # Canonical accumulators
        timeline_map: Dict[str, Dict[str, Any]] = {}
        totals = {
            "followers": 0,
            "new_followers": 0,
            "posts": 0,
            "impressions": 0,
            "engagements": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "reactions": 0,
        }

        # For FB, you can:
        # - followers: from page fields followers_count (current, not time series)
        # - new_followers: from page_daily_follows_unique (time series)
        # - impressions: page_posts_impressions (time series)
        # - engagements: page_post_engagements (time series)
        #
        # You already built these in your facebook_insights.py.

        # PSEUDO: call your internal function/service instead of HTTP.
        # If you prefer HTTP, call your own endpoint.
        from ....resources.social.insights.facebook_insights_resource import (
            _get_facebook_page_info,
            _fetch_page_insights,
        )

        page_info = _get_facebook_page_info(
            page_id=destination_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        followers_now = (page_info.get("followers_count") or 0) if page_info.get("success") else 0
        totals["followers"] = int(followers_now or 0)

        # Chunk requests (FB time range constraints)
        metrics = ["page_daily_follows_unique", "page_posts_impressions", "page_post_engagements"]
        for csince, cuntil in _daterange_chunks(since_ymd, until_ymd, max_days=93):
            insights = _fetch_page_insights(
                page_id=destination_id,
                access_token=access_token,
                metrics=metrics,
                period="day",
                since=csince,
                until=cuntil,
                log_tag=log_tag,
            )

            metric_series = insights.get("metrics", {}) or {}
            for metric_name, series in metric_series.items():
                for row in series or []:
                    # end_time is ISO; take date portion
                    end_time = (row.get("end_time") or "")[:10]
                    if not end_time:
                        continue
                    pt = timeline_map.setdefault(
                        end_time,
                        {"date": end_time, "followers": None, "new_followers": 0, "posts": 0, "impressions": 0, "engagements": 0},
                    )
                    val = row.get("value") or 0

                    if metric_name == "page_daily_follows_unique":
                        pt["new_followers"] += int(val or 0)
                    elif metric_name == "page_posts_impressions":
                        pt["impressions"] += int(val or 0)
                    elif metric_name == "page_post_engagements":
                        pt["engagements"] += int(val or 0)

        # Totals from timeline
        for d in timeline_map.values():
            totals["new_followers"] += int(d.get("new_followers") or 0)
            totals["impressions"] += int(d.get("impressions") or 0)
            totals["engagements"] += int(d.get("engagements") or 0)

        timeline = [timeline_map[k] for k in sorted(timeline_map.keys())]

        return ProviderResult(
            platform=self.platform,
            destination_id=destination_id,
            destination_name=acct.get("destination_name") or page_info.get("name"),
            totals=totals,
            timeline=timeline,
            debug=None,
        )