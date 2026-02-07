# app/services/social/providers/instagram_provider.py
#
# Instagram provider for unified analytics
#
# Instagram Graph API (via Facebook):
# - Account info: followers_count, follows_count, media_count
# - Media insights: impressions, reach, engagement, saves
# - Account insights: Limited to recent 30 days
#
# Key limitations:
# - Account-level insights limited to last 30 days
# - Many account metrics deprecated or require specific conditions
# - Media insights available for each post individually
#
# Working approach (Feb 2025):
# - Use account fields for followers_count, media_count
# - Aggregate engagement from recent media posts

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from .base import ProviderResult, SocialProviderBase
from ....models.social.social_account import SocialAccount
from ....utils.logger import Log


def _parse_ymd(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def _fmt_ymd(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


# Instagram Graph API base
GRAPH_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


# -------------------------------------------------------------------
# Working Instagram Metrics (Feb 2025)
# -------------------------------------------------------------------
# Account-level (from /user fields):
#   - followers_count
#   - follows_count
#   - media_count
#
# Account insights (/{ig-user-id}/insights) - LIMITED:
#   - reach (last 30 days, requires specific metric_type)
#   - accounts_engaged (may require Business account)
#   - NOTE: "impressions" at account level is deprecated/restricted
#
# Media insights (/{media-id}/insights) - WORKING:
#   - impressions
#   - reach
#   - engagement (for FEED posts)
#   - saved
#   - video_views (for videos)
#   - likes, comments (from media fields, not insights)


class InstagramProvider(SocialProviderBase):
    platform = "instagram"

    def __init__(self, *, graph_version: str = "v21.0"):
        self.graph_version = graph_version
        self.base_url = f"https://graph.facebook.com/{graph_version}"

    def _request_get(
        self,
        endpoint: str,
        params: Dict[str, Any],
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Make GET request to Instagram Graph API."""
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

    def _get_account_info(
        self,
        ig_user_id: str,
        access_token: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch Instagram account info using fields endpoint.
        
        These fields are reliable and not deprecated.
        """
        result = self._request_get(
            ig_user_id,
            params={
                "fields": "id,username,name,profile_picture_url,followers_count,follows_count,media_count,biography,website",
                "access_token": access_token,
            },
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} IG account info error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        
        return {
            "success": True,
            "id": data.get("id"),
            "username": data.get("username"),
            "name": data.get("name"),
            "profile_picture_url": data.get("profile_picture_url"),
            "followers_count": data.get("followers_count", 0),
            "follows_count": data.get("follows_count", 0),
            "media_count": data.get("media_count", 0),
            "biography": data.get("biography"),
            "website": data.get("website"),
        }

    def _get_recent_media(
        self,
        ig_user_id: str,
        access_token: str,
        limit: int = 50,
        since_ymd: Optional[str] = None,
        until_ymd: Optional[str] = None,
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        Fetch recent media with engagement metrics.
        
        This is more reliable than account-level insights.
        """
        result = self._request_get(
            f"{ig_user_id}/media",
            params={
                "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count",
                "limit": min(limit, 100),
                "access_token": access_token,
            },
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} IG media list error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        media_list = data.get("data", [])
        
        # Filter by date range if provided
        filtered_media = []
        since_dt = _parse_ymd(since_ymd).replace(tzinfo=timezone.utc) if since_ymd else None
        until_dt = (_parse_ymd(until_ymd) + timedelta(days=1)).replace(tzinfo=timezone.utc) if until_ymd else None
        
        for media in media_list:
            timestamp = media.get("timestamp")
            if timestamp:
                try:
                    media_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    
                    if since_dt and media_dt < since_dt:
                        continue
                    if until_dt and media_dt > until_dt:
                        continue
                except Exception:
                    pass
            
            filtered_media.append({
                "id": media.get("id"),
                "caption": media.get("caption"),
                "media_type": media.get("media_type"),
                "media_url": media.get("media_url") or media.get("thumbnail_url"),
                "permalink": media.get("permalink"),
                "timestamp": timestamp,
                "like_count": media.get("like_count", 0),
                "comments_count": media.get("comments_count", 0),
            })
        
        return {
            "success": True,
            "media": filtered_media,
        }

    def _get_media_insights(
        self,
        media_id: str,
        media_type: str,
        access_token: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch insights for a specific media item.
        
        Available metrics depend on media type:
        - IMAGE/CAROUSEL_ALBUM: impressions, reach, engagement, saved
        - VIDEO/REELS: impressions, reach, saved, video_views
        """
        # Different metrics for different media types
        if media_type in ["VIDEO", "REELS"]:
            metrics = "impressions,reach,saved,video_views"
        else:
            # IMAGE, CAROUSEL_ALBUM
            metrics = "impressions,reach,engagement,saved"
        
        result = self._request_get(
            f"{media_id}/insights",
            params={
                "metric": metrics,
                "access_token": access_token,
            },
        )
        
        if not result.get("success"):
            # Media insights may fail for some posts (e.g., promoted posts)
            # Return empty metrics instead of failing
            return {
                "success": True,
                "metrics": {},
            }
        
        data = result.get("data", {}).get("data", [])
        
        metrics_data = {}
        for item in data:
            name = item.get("name")
            values = item.get("values", [])
            if values:
                metrics_data[name] = values[0].get("value", 0)
        
        return {
            "success": True,
            "metrics": metrics_data,
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
        Fetch Instagram metrics for a date range.
        
        Strategy:
        1. Get account info (followers, media_count) - always works
        2. Get recent media in date range
        3. Aggregate engagement from media (likes, comments)
        4. Optionally get media-level insights (impressions, reach)
        """
        log_tag = "[instagram_provider.py][InstagramProvider]"
        
        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="instagram",
            destination_id=destination_id,
        )
        
        if not acct:
            return ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=None,
                totals={},
                timeline=[],
                debug={"error": "IG_NOT_CONNECTED"},
            )

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=acct.get("destination_name"),
                totals={},
                timeline=[],
                debug={"error": "IG_TOKEN_MISSING"},
            )

        # 1. Get account info (always works)
        account_info = self._get_account_info(
            ig_user_id=destination_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        if not account_info.get("success"):
            error = account_info.get("error", {})
            error_code = error.get("code") if isinstance(error, dict) else None
            
            # Check for token expiry
            if error_code == 190:
                return ProviderResult(
                    platform=self.platform,
                    destination_id=destination_id,
                    destination_name=acct.get("destination_name"),
                    totals={},
                    timeline=[],
                    debug={"error": "IG_TOKEN_EXPIRED", "details": error},
                )
            
            return ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=acct.get("destination_name"),
                totals={},
                timeline=[],
                debug={"error": "IG_ACCOUNT_INFO_ERROR", "details": error},
            )

        followers_count = account_info.get("followers_count", 0)
        media_count = account_info.get("media_count", 0)
        username = account_info.get("username")

        # Initialize totals
        totals = {
            "followers": int(followers_count or 0),
            "following": int(account_info.get("follows_count", 0)),
            "new_followers": 0,  # Can't reliably get this from IG API
            "posts": 0,
            "impressions": 0,
            "reach": 0,
            "engagements": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,  # IG doesn't expose shares
            "saves": 0,
            "reactions": 0,
        }

        # 2. Get recent media in date range
        media_resp = self._get_recent_media(
            ig_user_id=destination_id,
            access_token=access_token,
            limit=100,
            since_ymd=since_ymd,
            until_ymd=until_ymd,
            log_tag=log_tag,
        )

        timeline_map: Dict[str, Dict[str, Any]] = {}

        if media_resp.get("success"):
            media_list = media_resp.get("media", [])
            totals["posts"] = len(media_list)

            for media in media_list:
                # Extract date from timestamp
                timestamp = media.get("timestamp", "")
                date_str = timestamp[:10] if timestamp else None
                
                like_count = int(media.get("like_count", 0) or 0)
                comments_count = int(media.get("comments_count", 0) or 0)
                
                # Add to totals
                totals["likes"] += like_count
                totals["comments"] += comments_count
                totals["engagements"] += like_count + comments_count
                totals["reactions"] += like_count  # Likes are the main reaction on IG

                # 3. Try to get media-level insights (impressions, reach)
                media_id = media.get("id")
                media_type = media.get("media_type", "IMAGE")
                
                if media_id:
                    insights = self._get_media_insights(
                        media_id=media_id,
                        media_type=media_type,
                        access_token=access_token,
                        log_tag=log_tag,
                    )
                    
                    if insights.get("success"):
                        metrics = insights.get("metrics", {})
                        impressions = int(metrics.get("impressions", 0) or 0)
                        reach = int(metrics.get("reach", 0) or 0)
                        saves = int(metrics.get("saved", 0) or 0)
                        
                        totals["impressions"] += impressions
                        totals["reach"] += reach
                        totals["saves"] += saves

                # Build timeline
                if date_str:
                    pt = timeline_map.setdefault(
                        date_str,
                        {
                            "date": date_str,
                            "followers": None,
                            "new_followers": 0,
                            "posts": 0,
                            "impressions": 0,
                            "reach": 0,
                            "engagements": 0,
                            "likes": 0,
                            "comments": 0,
                            "saves": 0,
                        },
                    )
                    pt["posts"] += 1
                    pt["likes"] += like_count
                    pt["comments"] += comments_count
                    pt["engagements"] += like_count + comments_count
                    
                    if insights.get("success"):
                        metrics = insights.get("metrics", {})
                        pt["impressions"] += int(metrics.get("impressions", 0) or 0)
                        pt["reach"] += int(metrics.get("reach", 0) or 0)
                        pt["saves"] += int(metrics.get("saved", 0) or 0)

        # Sort timeline by date
        timeline = [timeline_map[k] for k in sorted(timeline_map.keys())]

        return ProviderResult(
            platform=self.platform,
            destination_id=destination_id,
            destination_name=acct.get("destination_name") or username,
            totals=totals,
            timeline=timeline,
            debug={
                "account_info": {
                    "username": username,
                    "followers_count": followers_count,
                    "media_count": media_count,
                },
                "media_fetched": len(media_resp.get("media", [])) if media_resp.get("success") else 0,
                "note": "Instagram account-level impressions metric is deprecated. Using media-level aggregation instead.",
            },
        )