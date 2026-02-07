# app/services/social/providers/facebook_provider.py

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from .base import ProviderResult, SocialProviderBase
from ....models.social.social_account import SocialAccount
from ....utils.logger import Log
from ....services.social.snapshot_store import SnapshotStore


def _parse_ymd(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def _fmt_ymd(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _today_ymd() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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

        destination_name = acct.get("destination_name")

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            # token missing -> fallback to local snapshots (if any)
            return SnapshotStore.read_range_as_provider_result(
                business_id=business_id,
                user__id=user__id,
                platform=self.platform,
                destination_id=destination_id,
                since_ymd=since_ymd,
                until_ymd=until_ymd,
                destination_name=destination_name,
                debug={"fallback": True, "live_error": "FB_TOKEN_MISSING"},
            )

        try:
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

            # Import internal helper methods (no HTTP)
            from ....resources.social.insights.facebook_insights_resource import (
                _get_facebook_page_info,
                _fetch_page_insights,
            )

            # 1) Page info (followers_count)
            page_info = _get_facebook_page_info(
                page_id=destination_id,
                access_token=access_token,
                log_tag=log_tag,
            )

            # Your helper may return success flag; handle both shapes safely
            followers_now = 0
            if isinstance(page_info, dict):
                if page_info.get("success") is True:
                    followers_now = int(page_info.get("followers_count") or page_info.get("fan_count") or 0)
                else:
                    # sometimes you return raw dict without success key
                    followers_now = int(page_info.get("followers_count") or page_info.get("fan_count") or 0)

            totals["followers"] = int(followers_now or 0)

            # 2) Insights time-series (chunked)
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

                metric_series = (insights or {}).get("metrics", {}) or {}
                for metric_name, series in metric_series.items():
                    for row in series or []:
                        end_time = (row.get("end_time") or "")[:10]
                        if not end_time:
                            continue

                        pt = timeline_map.setdefault(
                            end_time,
                            {
                                "date": end_time,
                                # followers in timeline is optional (we store daily followers snapshot separately)
                                "followers": None,
                                "new_followers": 0,
                                "posts": 0,
                                "impressions": 0,
                                "engagements": 0,
                                "likes": 0,
                                "comments": 0,
                                "shares": 0,
                                "reactions": 0,
                            },
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

            live_res = ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=destination_name or page_info.get("name"),
                totals=totals,
                timeline=timeline,
                debug=None,
            )

            # -------------------------
            # ✅ PERSISTENCE
            # -------------------------
            # 1) Write timeline days (new_followers, impressions, engagements)
            # 2) Also write "followers snapshot" for today (because followers_count is not a time-series)
            try:
                SnapshotStore.write_from_provider_result(
                    business_id=business_id,
                    user__id=user__id,
                    platform=self.platform,
                    destination_id=destination_id,
                    result=live_res,
                    prefer_write_each_day=True,
                    write_only_today_if_no_timeline=True,
                    today_ymd=_today_ymd(),
                    meta={"source": "live", "provider": "facebook"},
                )

                # Ensure today's record has followers (important)
                SnapshotStore.write_from_provider_result(
                    business_id=business_id,
                    user__id=user__id,
                    platform=self.platform,
                    destination_id=destination_id,
                    result=ProviderResult(
                        platform=self.platform,
                        destination_id=destination_id,
                        destination_name=live_res.destination_name,
                        totals={"followers": totals["followers"]},
                        timeline=[],
                        debug=None,
                    ),
                    prefer_write_each_day=False,
                    write_only_today_if_no_timeline=True,
                    today_ymd=_today_ymd(),
                    meta={"source": "live_followers_only", "provider": "facebook"},
                )
            except Exception as pe:
                Log.info(f"{log_tag} snapshot_persist_failed: {pe}")

            return live_res

        except Exception as e:
            Log.info(f"{log_tag} live_fetch_failed: {e}")

            # -------------------------
            # ✅ FALLBACK: read local snapshots
            # -------------------------
            return SnapshotStore.read_range_as_provider_result(
                business_id=business_id,
                user__id=user__id,
                platform=self.platform,
                destination_id=destination_id,
                since_ymd=since_ymd,
                until_ymd=until_ymd,
                destination_name=destination_name,
                debug={"fallback": True, "live_error": str(e)},
            )