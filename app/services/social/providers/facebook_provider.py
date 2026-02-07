# app/services/social/providers/facebook_provider.py
#
# Facebook provider for unified analytics
#
# Facebook Graph API v21.0:
# - Page info: followers_count, fan_count
# - Page insights: page_daily_follows_unique, page_posts_impressions, page_post_engagements
# - Post list with engagement metrics
#
# Key limitations:
# - Many page metrics deprecated Nov 2025 (New Pages Experience)
# - Max 93 days per insights request
# - Rate limits apply (~200 calls/hour per page)
#
# Working metrics (Feb 2025):
# - page_daily_follows_unique (new followers per day)
# - page_posts_impressions (post impressions)
# - page_post_engagements (total engagements)
# - page_video_views (video views)

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

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


def _to_unix_timestamp(dt: datetime) -> int:
    """Convert datetime to Unix timestamp."""
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


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


# Facebook Graph API
GRAPH_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


# -------------------------------------------------------------------
# Working Facebook Metrics (Feb 2025 - Post Nov 2025 Deprecation)
# -------------------------------------------------------------------
# Page fields (/{page-id}?fields=...):
#   ✅ followers_count - current followers
#   ✅ fan_count - page likes
#   ✅ name, username, link, picture, category
#
# Page insights (/{page-id}/insights) - WORKING:
#   ✅ page_daily_follows_unique - new followers per day
#   ✅ page_daily_unfollows_unique - unfollows per day
#   ✅ page_posts_impressions - post impressions
#   ✅ page_post_engagements - total engagements
#   ✅ page_video_views - video views
#
# Page insights - DEPRECATED (Nov 2025):
#   ❌ page_impressions - use page_posts_impressions instead
#   ❌ page_fans - use followers_count from fields
#   ❌ page_engaged_users - deprecated
#   ❌ page_views_total - use page_views_logged_in_total
#
# Post fields (/{page-id}/posts?fields=...):
#   ✅ reactions.summary(true) - total reactions
#   ✅ comments.summary(true) - total comments
#   ✅ shares - share count

# Working page-level metrics
WORKING_PAGE_METRICS = [
    "page_daily_follows_unique",
    "page_daily_unfollows_unique",
    "page_posts_impressions",
    "page_post_engagements",
    "page_video_views",
]

# Deprecated metrics (do not use)
DEPRECATED_METRICS = [
    "page_impressions",
    "page_fans",
    "page_fan_adds",
    "page_engaged_users",
    "page_views_total",
]


class FacebookProvider(SocialProviderBase):
    platform = "facebook"

    def __init__(self, *, graph_version: str = "v21.0"):
        self.graph_version = graph_version
        self.base_url = f"https://graph.facebook.com/{graph_version}"

    def _request_get(
        self,
        endpoint: str,
        params: Dict[str, Any],
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Make GET request to Facebook Graph API."""
        url = f"{self.base_url}/{endpoint}"
        try:
            r = requests.get(url, params=params, timeout=timeout)
            js = r.json() if r.text else {}
            
            if r.status_code >= 400 or "error" in js:
                return {
                    "success": False,
                    "status_code": r.status_code,
                    "error": js.get("error", {}),
                }
            
            return {"success": True, "data": js}
        except Exception as e:
            return {"success": False, "error": {"message": str(e)}}

    def _get_page_info(
        self,
        page_id: str,
        access_token: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch Facebook page info using fields endpoint.
        
        These fields are reliable and not deprecated.
        """
        result = self._request_get(
            page_id,
            params={
                "fields": "id,name,username,followers_count,fan_count,link,picture,category,about,website",
                "access_token": access_token,
            },
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} FB page info error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        
        return {
            "success": True,
            "id": data.get("id"),
            "name": data.get("name"),
            "username": data.get("username"),
            "followers_count": data.get("followers_count", 0),
            "fan_count": data.get("fan_count", 0),
            "link": data.get("link"),
            "picture": data.get("picture", {}).get("data", {}).get("url") if isinstance(data.get("picture"), dict) else None,
            "category": data.get("category"),
            "about": data.get("about"),
            "website": data.get("website"),
        }

    def _fetch_page_insights_metric(
        self,
        page_id: str,
        access_token: str,
        metric: str,
        period: str,
        since: str,
        until: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch a single page insight metric.
        
        Fetching metrics individually allows better error handling
        when some metrics are deprecated or unavailable.
        """
        since_dt = _parse_ymd(since)
        until_dt = _parse_ymd(until)
        
        result = self._request_get(
            f"{page_id}/insights",
            params={
                "metric": metric,
                "period": period,
                "since": _to_unix_timestamp(since_dt),
                "until": _to_unix_timestamp(until_dt + timedelta(days=1)),
                "access_token": access_token,
            },
        )
        
        if not result.get("success"):
            error = result.get("error", {})
            error_msg = error.get("message", "") if isinstance(error, dict) else str(error)
            
            # Check if metric is invalid/deprecated
            if "invalid" in error_msg.lower() or result.get("status_code") == 100:
                Log.info(f"{log_tag} Metric '{metric}' is invalid or deprecated")
                return {"success": False, "deprecated": True, "error": error}
            
            Log.info(f"{log_tag} FB insights error for {metric}: {error}")
            return result
        
        data = result.get("data", {}).get("data", [])
        
        # Extract time series
        series = []
        for item in data:
            if item.get("name") == metric:
                for v in item.get("values", []):
                    series.append({
                        "end_time": v.get("end_time"),
                        "value": v.get("value"),
                    })
                break
        
        return {
            "success": True,
            "metric": metric,
            "series": series,
        }

    def _fetch_page_insights(
        self,
        page_id: str,
        access_token: str,
        metrics: List[str],
        period: str,
        since: str,
        until: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch multiple page insight metrics.
        
        Fetches each metric individually for better error handling.
        """
        all_metrics: Dict[str, List[Dict]] = {}
        valid_metrics: List[str] = []
        invalid_metrics: List[str] = []
        
        for metric in metrics:
            result = self._fetch_page_insights_metric(
                page_id=page_id,
                access_token=access_token,
                metric=metric,
                period=period,
                since=since,
                until=until,
                log_tag=log_tag,
            )
            
            if result.get("success"):
                series = result.get("series", [])
                if series:
                    all_metrics[metric] = series
                    valid_metrics.append(metric)
                else:
                    invalid_metrics.append(metric)
            else:
                invalid_metrics.append(metric)
        
        return {
            "success": len(valid_metrics) > 0,
            "valid_metrics": valid_metrics,
            "invalid_metrics": invalid_metrics,
            "metrics": all_metrics,
        }

    def _get_page_posts(
        self,
        page_id: str,
        access_token: str,
        limit: int = 100,
        since: Optional[str] = None,
        until: Optional[str] = None,
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        Fetch page posts with engagement metrics.
        
        This provides likes, comments, shares data.
        """
        params = {
            "fields": "id,message,created_time,permalink_url,shares,reactions.summary(true),comments.summary(true)",
            "limit": min(limit, 100),
            "access_token": access_token,
        }
        
        if since:
            since_dt = _parse_ymd(since)
            params["since"] = _to_unix_timestamp(since_dt)
        if until:
            until_dt = _parse_ymd(until)
            params["until"] = _to_unix_timestamp(until_dt + timedelta(days=1))
        
        result = self._request_get(f"{page_id}/posts", params=params)
        
        if not result.get("success"):
            Log.info(f"{log_tag} FB posts list error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        post_list = data.get("data", [])
        
        # Normalize posts
        posts = []
        for post in post_list:
            reactions_count = 0
            comments_count = 0
            shares_count = 0
            
            if "reactions" in post and isinstance(post["reactions"], dict):
                reactions_count = post["reactions"].get("summary", {}).get("total_count", 0)
            
            if "comments" in post and isinstance(post["comments"], dict):
                comments_count = post["comments"].get("summary", {}).get("total_count", 0)
            
            if "shares" in post and isinstance(post["shares"], dict):
                shares_count = post["shares"].get("count", 0)
            
            posts.append({
                "id": post.get("id"),
                "message": post.get("message"),
                "created_time": post.get("created_time"),
                "permalink_url": post.get("permalink_url"),
                "reactions_count": reactions_count,
                "comments_count": comments_count,
                "shares_count": shares_count,
            })
        
        return {
            "success": True,
            "posts": posts,
        }

    def fetch_range(
        self,
        *,
        business_id: str,
        user__id: str,
        destination_id: str,
        since_ymd: str,
        until_ymd: str,
    ) -> ProviderResult:
        """
        Fetch Facebook metrics for a date range.
        
        Strategy:
        1. Get page info (followers_count, fan_count) - always works
        2. Get page insights (working metrics only, chunked by 93 days)
        3. Get posts for engagement aggregation (likes, comments, shares)
        4. Persist to snapshot store
        5. Fallback to snapshots if live fetch fails
        """
        log_tag = "[facebook_provider.py][FacebookProvider][fetch_range]"

        # Load stored SocialAccount
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
            # Token missing -> fallback to local snapshots
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
            # Initialize totals
            totals = {
                "followers": 0,
                "new_followers": 0,
                "unfollows": 0,
                "posts": 0,
                "impressions": 0,
                "engagements": 0,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "reactions": 0,
                "video_views": 0,
            }

            timeline_map: Dict[str, Dict[str, Any]] = {}

            # -----------------------------------------
            # 1. Get page info (always works)
            # -----------------------------------------
            page_info = self._get_page_info(
                page_id=destination_id,
                access_token=access_token,
                log_tag=log_tag,
            )

            if not page_info.get("success"):
                error = page_info.get("error", {})
                error_code = error.get("code") if isinstance(error, dict) else None
                
                # Check for token expiry
                if error_code == 190:
                    Log.info(f"{log_tag} Token expired, falling back to snapshots")
                    return SnapshotStore.read_range_as_provider_result(
                        business_id=business_id,
                        user__id=user__id,
                        platform=self.platform,
                        destination_id=destination_id,
                        since_ymd=since_ymd,
                        until_ymd=until_ymd,
                        destination_name=destination_name,
                        debug={"fallback": True, "live_error": "FB_TOKEN_EXPIRED"},
                    )
                
                # Permission error - still try to proceed with what we can get
                Log.info(f"{log_tag} Page info error: {error}, continuing...")

            followers_count = page_info.get("followers_count", 0) if page_info.get("success") else 0
            fan_count = page_info.get("fan_count", 0) if page_info.get("success") else 0
            page_name = page_info.get("name") if page_info.get("success") else destination_name
            
            totals["followers"] = int(followers_count or fan_count or 0)

            # -----------------------------------------
            # 2. Get page insights (chunked by 93 days)
            # -----------------------------------------
            # Only use working metrics
            metrics_to_fetch = [
                "page_daily_follows_unique",
                "page_daily_unfollows_unique",
                "page_posts_impressions",
                "page_post_engagements",
                "page_video_views",
            ]

            for chunk_since, chunk_until in _daterange_chunks(since_ymd, until_ymd, max_days=93):
                insights = self._fetch_page_insights(
                    page_id=destination_id,
                    access_token=access_token,
                    metrics=metrics_to_fetch,
                    period="day",
                    since=chunk_since,
                    until=chunk_until,
                    log_tag=log_tag,
                )

                if not insights.get("success"):
                    Log.info(f"{log_tag} Insights fetch failed for chunk {chunk_since} to {chunk_until}")
                    continue

                # Process metrics
                metric_series = insights.get("metrics", {})
                
                for metric_name, series in metric_series.items():
                    for row in series or []:
                        end_time = (row.get("end_time") or "")[:10]
                        if not end_time:
                            continue

                        # Initialize timeline point
                        pt = timeline_map.setdefault(
                            end_time,
                            {
                                "date": end_time,
                                "followers": None,
                                "new_followers": 0,
                                "unfollows": 0,
                                "posts": 0,
                                "impressions": 0,
                                "engagements": 0,
                                "likes": 0,
                                "comments": 0,
                                "shares": 0,
                                "reactions": 0,
                                "video_views": 0,
                            },
                        )

                        val = int(row.get("value") or 0)

                        if metric_name == "page_daily_follows_unique":
                            pt["new_followers"] += val
                        elif metric_name == "page_daily_unfollows_unique":
                            pt["unfollows"] += val
                        elif metric_name == "page_posts_impressions":
                            pt["impressions"] += val
                        elif metric_name == "page_post_engagements":
                            pt["engagements"] += val
                        elif metric_name == "page_video_views":
                            pt["video_views"] += val

            # -----------------------------------------
            # 3. Get posts for engagement breakdown
            # -----------------------------------------
            posts_resp = self._get_page_posts(
                page_id=destination_id,
                access_token=access_token,
                limit=100,
                since=since_ymd,
                until=until_ymd,
                log_tag=log_tag,
            )

            if posts_resp.get("success"):
                posts = posts_resp.get("posts", [])
                totals["posts"] = len(posts)

                for post in posts:
                    reactions = int(post.get("reactions_count", 0) or 0)
                    comments = int(post.get("comments_count", 0) or 0)
                    shares = int(post.get("shares_count", 0) or 0)

                    totals["reactions"] += reactions
                    totals["likes"] += reactions  # Facebook reactions include likes
                    totals["comments"] += comments
                    totals["shares"] += shares

                    # Add to timeline by date
                    created_time = post.get("created_time", "")
                    date_str = created_time[:10] if created_time else None
                    
                    if date_str and date_str in timeline_map:
                        timeline_map[date_str]["posts"] += 1
                        timeline_map[date_str]["reactions"] += reactions
                        timeline_map[date_str]["likes"] += reactions
                        timeline_map[date_str]["comments"] += comments
                        timeline_map[date_str]["shares"] += shares

            # -----------------------------------------
            # 4. Aggregate totals from timeline
            # -----------------------------------------
            for d in timeline_map.values():
                totals["new_followers"] += int(d.get("new_followers") or 0)
                totals["unfollows"] += int(d.get("unfollows") or 0)
                totals["impressions"] += int(d.get("impressions") or 0)
                totals["engagements"] += int(d.get("engagements") or 0)
                totals["video_views"] += int(d.get("video_views") or 0)

            # Sort timeline
            timeline = [timeline_map[k] for k in sorted(timeline_map.keys())]

            # Build result
            live_res = ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=destination_name or page_name,
                totals=totals,
                timeline=timeline,
                debug={
                    "page_info": {
                        "name": page_name,
                        "followers_count": followers_count,
                        "fan_count": fan_count,
                    },
                    "insights_fetched": len(timeline_map),
                    "posts_fetched": totals.get("posts", 0),
                    "metrics_used": metrics_to_fetch,
                },
            )

            # -----------------------------------------
            # 5. Persist to snapshot store
            # -----------------------------------------
            try:
                # Write timeline days
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

                # Ensure today's record has current followers count
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

            # -----------------------------------------
            # 6. Fallback to local snapshots
            # -----------------------------------------
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