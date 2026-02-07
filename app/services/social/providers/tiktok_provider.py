# app/services/social/providers/tiktok_provider.py
#
# TikTok provider for unified analytics
#
# TikTok API v2:
# - User info: follower_count, following_count, likes_count, video_count
# - Video list: with engagement metrics (views, likes, comments, shares)
# - Video queries: search user's videos
#
# Key limitations:
# - Time-series analytics require TikTok Business API (separate approval)
# - Basic API provides current counts and per-video metrics
# - Videos endpoint uses POST not GET
# - Rate limits: 100 requests per minute per user
#
# Required Scopes:
# - user.info.basic: Basic user info
# - user.info.profile: Profile info
# - user.info.stats: Stats (followers, likes)
# - video.list: List user's videos

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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


def _from_unix_timestamp(ts: int) -> str:
    """Convert Unix timestamp to YYYY-MM-DD."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


# TikTok API v2
TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"


# -------------------------------------------------------------------
# TikTok API Reference
# -------------------------------------------------------------------
# User Info (POST /user/info/):
#   Fields: open_id, union_id, avatar_url, display_name, bio_description,
#           profile_deep_link, is_verified, follower_count, following_count,
#           likes_count, video_count
#
# Video List (POST /video/list/):
#   Fields: id, title, video_description, duration, cover_image_url,
#           embed_link, create_time, share_url
#   Metrics: view_count, like_count, comment_count, share_count
#
# Video Query (POST /video/query/):
#   Query specific videos by IDs
#
# Required Scopes:
#   - user.info.basic: Basic profile
#   - user.info.profile: Full profile
#   - user.info.stats: Follower/like counts
#   - video.list: List videos


class TikTokProvider(SocialProviderBase):
    platform = "tiktok"

    def __init__(self):
        self.api_base = TIKTOK_API_BASE

    def _auth_headers(self, access_token: str) -> Dict[str, str]:
        """Build authorization headers for TikTok API."""
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def _request_post(
        self,
        endpoint: str,
        headers: Dict[str, str],
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Make POST request to TikTok API (TikTok uses POST for most endpoints)."""
        url = f"{self.api_base}/{endpoint}"
        try:
            r = requests.post(
                url,
                headers=headers,
                json=json_body or {},
                params=params,
                timeout=timeout,
            )
            text = r.text or ""
            
            try:
                js = r.json() if text else {}
            except Exception:
                js = {}
            
            # TikTok returns error in response body even with 200 status
            error_data = js.get("error", {})
            if error_data and error_data.get("code") != "ok":
                return {
                    "success": False,
                    "status_code": r.status_code,
                    "error": error_data,
                    "raw": text,
                }
            
            if r.status_code >= 400:
                return {
                    "success": False,
                    "status_code": r.status_code,
                    "error": js.get("error", js),
                    "raw": text,
                }
            
            return {"success": True, "data": js.get("data", {})}
        except requests.exceptions.Timeout:
            return {"success": False, "error": {"code": "timeout", "message": "Request timeout"}}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": {"code": "request_error", "message": str(e)}}

    def _parse_tiktok_error(self, error: Dict[str, Any]) -> Dict[str, Any]:
        """Parse TikTok API error response."""
        if isinstance(error, dict):
            return {
                "code": error.get("code"),
                "message": error.get("message") or error.get("log_id") or str(error),
                "log_id": error.get("log_id"),
            }
        return {"message": str(error)}

    def _is_auth_error(self, error: Dict[str, Any], status_code: int) -> bool:
        """Check if error is authentication related (token expired)."""
        if status_code == 401:
            return True
        code = error.get("code", "")
        return code in ["access_token_invalid", "access_token_expired", "invalid_token"]

    def _is_scope_error(self, error: Dict[str, Any], status_code: int) -> bool:
        """Check if error is scope/permission related."""
        if status_code == 403:
            return True
        code = error.get("code", "")
        message = str(error.get("message", "")).lower()
        return (
            code in ["scope_not_authorized", "permission_denied"] or
            "scope" in message or
            "permission" in message
        )

    def _is_rate_limit_error(self, error: Dict[str, Any], status_code: int) -> bool:
        """Check if error is rate limit related."""
        if status_code == 429:
            return True
        code = error.get("code", "")
        return code in ["rate_limit_exceeded", "too_many_requests"]

    def _get_user_info(
        self,
        access_token: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch TikTok user info.
        
        Endpoint: POST /user/info/
        Required scopes: user.info.basic, user.info.profile, user.info.stats
        """
        # TikTok requires fields parameter in query string
        fields = [
            "open_id",
            "union_id",
            "avatar_url",
            "avatar_url_100",
            "display_name",
            "bio_description",
            "profile_deep_link",
            "is_verified",
            "follower_count",
            "following_count",
            "likes_count",
            "video_count",
        ]
        
        result = self._request_post(
            endpoint="user/info/",
            headers=self._auth_headers(access_token),
            params={"fields": ",".join(fields)},
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} TikTok user info error: {result.get('error')}")
            return result
        
        data = result.get("data", {}).get("user", {})
        
        return {
            "success": True,
            "open_id": data.get("open_id"),
            "union_id": data.get("union_id"),
            "display_name": data.get("display_name"),
            "avatar_url": data.get("avatar_url") or data.get("avatar_url_100"),
            "bio_description": data.get("bio_description"),
            "profile_deep_link": data.get("profile_deep_link"),
            "is_verified": data.get("is_verified", False),
            "follower_count": data.get("follower_count", 0),
            "following_count": data.get("following_count", 0),
            "likes_count": data.get("likes_count", 0),
            "video_count": data.get("video_count", 0),
        }

    def _get_video_list(
        self,
        access_token: str,
        max_count: int = 20,
        cursor: Optional[int] = None,
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        Fetch user's videos.
        
        Endpoint: POST /video/list/
        Required scope: video.list
        """
        fields = [
            "id",
            "title",
            "video_description",
            "duration",
            "cover_image_url",
            "embed_link",
            "embed_html",
            "create_time",
            "share_url",
            "view_count",
            "like_count",
            "comment_count",
            "share_count",
        ]
        
        body = {
            "max_count": min(max_count, 20),  # TikTok max is 20 per request
        }
        
        if cursor:
            body["cursor"] = cursor
        
        result = self._request_post(
            endpoint="video/list/",
            headers=self._auth_headers(access_token),
            json_body=body,
            params={"fields": ",".join(fields)},
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} TikTok video list error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        videos_raw = data.get("videos", [])
        
        videos = []
        for video in videos_raw:
            create_time = video.get("create_time")
            created_date = _from_unix_timestamp(create_time) if create_time else None
            
            videos.append({
                "id": video.get("id"),
                "title": video.get("title"),
                "description": video.get("video_description"),
                "duration": video.get("duration"),
                "cover_image_url": video.get("cover_image_url"),
                "share_url": video.get("share_url"),
                "embed_link": video.get("embed_link"),
                "create_time": create_time,
                "created_date": created_date,
                "view_count": video.get("view_count", 0),
                "like_count": video.get("like_count", 0),
                "comment_count": video.get("comment_count", 0),
                "share_count": video.get("share_count", 0),
            })
        
        return {
            "success": True,
            "videos": videos,
            "cursor": data.get("cursor"),
            "has_more": data.get("has_more", False),
        }

    def _get_all_videos(
        self,
        access_token: str,
        limit: int = 100,
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        Fetch all user's videos with pagination.
        
        TikTok limits to 20 videos per request, so we paginate.
        """
        all_videos = []
        cursor = None
        pages_fetched = 0
        max_pages = (limit // 20) + 1
        
        while pages_fetched < max_pages:
            result = self._get_video_list(
                access_token=access_token,
                max_count=20,
                cursor=cursor,
                log_tag=log_tag,
            )
            
            if not result.get("success"):
                # Return what we have so far
                if all_videos:
                    return {
                        "success": True,
                        "videos": all_videos,
                        "partial": True,
                        "error": result.get("error"),
                    }
                return result
            
            videos = result.get("videos", [])
            all_videos.extend(videos)
            
            if not result.get("has_more") or not result.get("cursor"):
                break
            
            cursor = result.get("cursor")
            pages_fetched += 1
            
            if len(all_videos) >= limit:
                break
        
        return {
            "success": True,
            "videos": all_videos[:limit],
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
        Fetch TikTok metrics for a date range.
        
        Strategy:
        1. Get user info (followers, following, likes, video count) - always works
        2. Get video list with engagement metrics
        3. Filter videos by date range
        4. Aggregate video metrics (views, likes, comments, shares)
        5. Persist to snapshot store
        6. Fallback to snapshots if API fails
        
        Note: TikTok doesn't provide time-series analytics via basic API.
        For time-series, you need TikTok Business API (separate approval).
        We aggregate from video-level metrics instead.
        """
        log_tag = "[tiktok_provider.py][TikTokProvider][fetch_range]"

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=self.platform,
            destination_id=destination_id,
        )
        
        if not acct:
            return ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=None,
                totals={},
                timeline=[],
                debug={"error": "TT_NOT_CONNECTED"},
            )

        destination_name = acct.get("destination_name")
        access_token = acct.get("access_token_plain") or acct.get("access_token")
        
        if not access_token:
            # Token missing -> fallback to snapshots
            return SnapshotStore.read_range_as_provider_result(
                business_id=business_id,
                user__id=user__id,
                platform=self.platform,
                destination_id=destination_id,
                since_ymd=since_ymd,
                until_ymd=until_ymd,
                destination_name=destination_name,
                debug={"fallback": True, "live_error": "TT_TOKEN_MISSING"},
            )

        try:
            # Initialize totals
            totals = {
                "followers": 0,
                "following": 0,
                "new_followers": 0,
                "posts": 0,  # videos
                "impressions": 0,  # video views
                "views": 0,
                "engagements": 0,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "reactions": 0,
                "total_likes": 0,  # account-level likes received
            }
            
            timeline_map: Dict[str, Dict[str, Any]] = {}
            
            # Track what we successfully fetched
            fetch_status = {
                "user_info": False,
                "video_list": False,
            }
            
            scope_warnings: List[str] = []

            # -----------------------------------------
            # 1. Get user info (always works with basic scopes)
            # -----------------------------------------
            user_info = self._get_user_info(
                access_token=access_token,
                log_tag=log_tag,
            )
            
            display_name = destination_name
            if user_info.get("success"):
                fetch_status["user_info"] = True
                display_name = user_info.get("display_name") or destination_name
                
                totals["followers"] = int(user_info.get("follower_count", 0) or 0)
                totals["following"] = int(user_info.get("following_count", 0) or 0)
                totals["total_likes"] = int(user_info.get("likes_count", 0) or 0)
            else:
                error = user_info.get("error", {})
                status_code = user_info.get("status_code", 0)
                
                if self._is_auth_error(error, status_code):
                    Log.info(f"{log_tag} Token expired, falling back to snapshots")
                    return SnapshotStore.read_range_as_provider_result(
                        business_id=business_id,
                        user__id=user__id,
                        platform=self.platform,
                        destination_id=destination_id,
                        since_ymd=since_ymd,
                        until_ymd=until_ymd,
                        destination_name=destination_name,
                        debug={"fallback": True, "live_error": "TT_TOKEN_EXPIRED"},
                    )
                
                if self._is_scope_error(error, status_code):
                    scope_warnings.append("User info requires user.info.basic, user.info.stats scopes")

            # -----------------------------------------
            # 2. Get video list with metrics
            # -----------------------------------------
            videos_resp = self._get_all_videos(
                access_token=access_token,
                limit=100,
                log_tag=log_tag,
            )
            
            if videos_resp.get("success"):
                fetch_status["video_list"] = True
                videos = videos_resp.get("videos", [])
                
                # Filter videos by date range
                since_dt = _parse_ymd(since_ymd)
                until_dt = _parse_ymd(until_ymd) + timedelta(days=1)
                
                filtered_videos = []
                for video in videos:
                    created_date = video.get("created_date")
                    if created_date:
                        try:
                            video_dt = _parse_ymd(created_date)
                            if since_dt <= video_dt < until_dt:
                                filtered_videos.append(video)
                        except Exception:
                            # Include if can't parse date
                            filtered_videos.append(video)
                    else:
                        # Include if no date
                        filtered_videos.append(video)
                
                totals["posts"] = len(filtered_videos)
                
                # Aggregate video metrics
                for video in filtered_videos:
                    views = int(video.get("view_count", 0) or 0)
                    likes = int(video.get("like_count", 0) or 0)
                    comments = int(video.get("comment_count", 0) or 0)
                    shares = int(video.get("share_count", 0) or 0)
                    
                    totals["views"] += views
                    totals["impressions"] += views  # Views = impressions for TikTok
                    totals["likes"] += likes
                    totals["comments"] += comments
                    totals["shares"] += shares
                    totals["engagements"] += likes + comments + shares
                    totals["reactions"] += likes
                    
                    # Add to timeline by date
                    created_date = video.get("created_date")
                    if created_date:
                        pt = timeline_map.setdefault(
                            created_date,
                            self._empty_timeline_point(created_date),
                        )
                        
                        pt["posts"] += 1
                        pt["views"] += views
                        pt["impressions"] += views
                        pt["likes"] += likes
                        pt["comments"] += comments
                        pt["shares"] += shares
                        pt["engagements"] += likes + comments + shares
                        pt["reactions"] += likes
            else:
                error = videos_resp.get("error", {})
                status_code = videos_resp.get("status_code", 0)
                
                if self._is_scope_error(error, status_code):
                    scope_warnings.append("Video list requires video.list scope")
                elif self._is_rate_limit_error(error, status_code):
                    scope_warnings.append("Rate limit exceeded. Try again later.")

            # Sort timeline
            timeline = [timeline_map[k] for k in sorted(timeline_map.keys())]

            # Build debug info
            debug_info = {
                "fetch_status": fetch_status,
                "videos_fetched": len(videos_resp.get("videos", [])) if videos_resp.get("success") else 0,
                "videos_in_range": totals.get("posts", 0),
            }
            
            if scope_warnings:
                debug_info["scope_warnings"] = scope_warnings
                debug_info["hint"] = (
                    "TikTok basic API provides current counts and per-video metrics. "
                    "For time-series analytics, you need TikTok Business API (separate approval)."
                )
                debug_info["required_scopes"] = {
                    "basic": ["user.info.basic", "user.info.profile", "user.info.stats"],
                    "videos": ["video.list"],
                }
            
            # Note about time-series
            debug_info["note"] = (
                "TikTok does not provide time-series follower data via basic API. "
                "New followers are calculated from daily snapshots. "
                "Video metrics are aggregated from individual videos."
            )

            # Build result
            live_res = ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=destination_name or display_name,
                totals=totals,
                timeline=timeline,
                debug=debug_info,
            )

            # -----------------------------------------
            # 3. Persist to snapshot store
            # -----------------------------------------
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
                    meta={"source": "live", "provider": "tiktok"},
                )

                # Ensure today's record has followers (important for daily tracking)
                if totals["followers"] > 0:
                    SnapshotStore.write_from_provider_result(
                        business_id=business_id,
                        user__id=user__id,
                        platform=self.platform,
                        destination_id=destination_id,
                        result=ProviderResult(
                            platform=self.platform,
                            destination_id=destination_id,
                            destination_name=live_res.destination_name,
                            totals={
                                "followers": totals["followers"],
                                "following": totals["following"],
                                "total_likes": totals["total_likes"],
                            },
                            timeline=[],
                            debug=None,
                        ),
                        prefer_write_each_day=False,
                        write_only_today_if_no_timeline=True,
                        today_ymd=_today_ymd(),
                        meta={"source": "live_followers_only", "provider": "tiktok"},
                    )
            except Exception as pe:
                Log.info(f"{log_tag} snapshot_persist_failed: {pe}")

            return live_res

        except Exception as e:
            Log.info(f"{log_tag} live_fetch_failed: {e}")

            # -----------------------------------------
            # 4. Fallback to local snapshots
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

    def _empty_timeline_point(self, date_str: str) -> Dict[str, Any]:
        """Create empty timeline point structure."""
        return {
            "date": date_str,
            "followers": None,
            "new_followers": 0,
            "posts": 0,
            "views": 0,
            "impressions": 0,
            "engagements": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "reactions": 0,
        }

## Summary of TikTok Provider

### API Endpoints Used

# | Endpoint | Method | Purpose | Required Scope |
# |----------|--------|---------|----------------|
# | `/user/info/` | POST | User info (followers, likes, video count) | `user.info.basic`, `user.info.stats` |
# | `/video/list/` | POST | List user's videos with metrics | `video.list` |

# ### What You Get

# | Metric | Source | Scope Required |
# |--------|--------|----------------|
# | `followers` | user/info | `user.info.stats` |
# | `following` | user/info | `user.info.stats` |
# | `total_likes` | user/info (account-level) | `user.info.stats` |
# | `posts` (videos) | video/list | `video.list` |
# | `views` | video/list (aggregated) | `video.list` |
# | `impressions` | video/list (= views) | `video.list` |
# | `likes` | video/list (aggregated) | `video.list` |
# | `comments` | video/list (aggregated) | `video.list` |
# | `shares` | video/list (aggregated) | `video.list` |
# | `engagements` | Calculated (likes+comments+shares) | `video.list` |

