# app/resources/social/tiktok_insights.py
#
# TikTok analytics using STORED SocialAccount token
#
# TikTok API versions:
# - TikTok API v2 (https://open.tiktokapis.com/v2)
# - TikTok for Business API (for advanced analytics)
#
# What you can get:
# - User info: display_name, follower_count, following_count, likes_count, video_count
# - Video list: with basic metrics
# - Video insights: views, likes, comments, shares
#
# Key limitations:
# - Requires proper OAuth scopes: user.info.basic, user.info.stats, video.list
# - Advanced metrics (watch time, reach) require TikTok for Business API
# - Video insights may have up to 2-day delay
# - Rate limits vary by endpoint and access level

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import g, jsonify, request
from flask.views import MethodView
from flask_smorest import Blueprint

from ....constants.service_code import HTTP_STATUS_CODES
from ....models.social.social_account import SocialAccount
from ....utils.logger import Log
from ...doseal.admin.admin_business_resource import token_required


# -------------------------------------------------------------------
# Blueprint
# -------------------------------------------------------------------

blp_tiktok_insights = Blueprint(
    "tiktok_insights",
    __name__,
)

# TikTok API base URLs
TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"
TIKTOK_BUSINESS_API_BASE = "https://business-api.tiktok.com/open_api/v1.3"

# Platform identifier
PLATFORM_ID = "tiktok"


# -------------------------------------------------------------------
# Valid Metrics Reference
# -------------------------------------------------------------------
# User Info (from /user/info/):
#   - open_id
#   - union_id
#   - display_name
#   - avatar_url
#   - follower_count      (requires user.info.stats scope)
#   - following_count     (requires user.info.stats scope)
#   - likes_count         (requires user.info.stats scope)
#   - video_count         (requires user.info.stats scope)
#   - bio_description
#   - profile_deep_link
#   - is_verified
#
# Video Info (from /video/list/):
#   - id
#   - title
#   - cover_image_url
#   - share_url
#   - create_time
#   - duration
#   - like_count
#   - comment_count
#   - share_count
#   - view_count
#
# Required OAuth Scopes:
#   - user.info.basic   : Basic profile info
#   - user.info.stats   : Follower/following/likes counts
#   - video.list        : List and query videos

# Default fields for user info
DEFAULT_USER_FIELDS = [
    "open_id",
    "union_id",
    "display_name",
    "avatar_url",
    "avatar_url_100",
    "avatar_large_url",
    "follower_count",
    "following_count",
    "likes_count",
    "video_count",
    "bio_description",
    "profile_deep_link",
    "is_verified",
]

# Default fields for video list
DEFAULT_VIDEO_FIELDS = [
    "id",
    "title",
    "video_description",
    "cover_image_url",
    "share_url",
    "embed_link",
    "create_time",
    "duration",
    "like_count",
    "comment_count",
    "share_count",
    "view_count",
]


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _pick(d: Dict[str, Any], *keys, default=None):
    """Safely pick first available key from dict."""
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d:
            return d.get(k)
    return default


def _parse_ymd(s: Optional[str]) -> Optional[datetime]:
    """Parse YYYY-MM-DD string to datetime."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


def _fmt_ymd(dt: datetime) -> str:
    """Format datetime to YYYY-MM-DD string."""
    return dt.strftime("%Y-%m-%d")


def _get_date_range_last_n_days(n: int = 30) -> Tuple[str, str]:
    """Get since/until for last N days."""
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=n)
    return _fmt_ymd(since), _fmt_ymd(until)


def _auth_headers(access_token: str) -> Dict[str, str]:
    """Build authorization headers for TikTok API."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _parse_tiktok_error(response_json: Dict[str, Any]) -> Dict[str, Any]:
    """Parse TikTok API error response."""
    error = response_json.get("error", {})
    return {
        "code": error.get("code") or response_json.get("code"),
        "message": error.get("message") or response_json.get("message") or "Unknown error",
        "log_id": error.get("log_id") or response_json.get("log_id"),
    }


def _is_auth_error(error: Dict[str, Any], status_code: int) -> bool:
    """Check if error is authentication related (token expired/invalid)."""
    code = error.get("code")
    # Only these are actual token expiration/invalid errors
    return code in [
        "access_token_invalid",
        "access_token_expired",
        "token_expired",
        "invalid_access_token",
    ]


def _is_permission_error(error: Dict[str, Any], status_code: int) -> bool:
    """Check if error is permission/scope related."""
    code = error.get("code")
    # scope_not_authorized comes with 401 but is a permission issue
    return code in [
        "scope_not_authorized",
        "permission_denied",
        "insufficient_permissions",
        "scope_permission_missed",
    ]


def _is_rate_limit_error(error: Dict[str, Any], status_code: int) -> bool:
    """Check if error is rate limit related."""
    if status_code == 429:
        return True
    code = error.get("code")
    return code in ["rate_limit_exceeded", "too_many_requests"]


# -------------------------------------------------------------------
# API Request Helpers
# -------------------------------------------------------------------

def _request_get(
    *,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Tuple[int, Dict[str, Any], str]:
    """Make GET request and return (status, json, raw_text)."""
    try:
        r = requests.get(url, headers=headers, params=params, timeout=timeout)
        text = r.text or ""
        try:
            js = r.json() if text else {}
        except Exception:
            js = {}
        return r.status_code, js, text
    except requests.exceptions.Timeout:
        return 408, {"error": {"code": "timeout", "message": "Request timeout"}}, ""
    except requests.exceptions.RequestException as e:
        return 500, {"error": {"code": "request_error", "message": str(e)}}, ""


def _request_post(
    *,
    url: str,
    headers: Dict[str, str],
    json_data: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Tuple[int, Dict[str, Any], str]:
    """Make POST request and return (status, json, raw_text)."""
    try:
        r = requests.post(url, headers=headers, json=json_data, timeout=timeout)
        text = r.text or ""
        try:
            js = r.json() if text else {}
        except Exception:
            js = {}
        return r.status_code, js, text
    except requests.exceptions.Timeout:
        return 408, {"error": {"code": "timeout", "message": "Request timeout"}}, ""
    except requests.exceptions.RequestException as e:
        return 500, {"error": {"code": "request_error", "message": str(e)}}, ""


# -------------------------------------------------------------------
# User Info
# -------------------------------------------------------------------

def _get_tiktok_user_info(
    *,
    access_token: str,
    fields: Optional[List[str]] = None,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Fetch TikTok user info.
    
    Required scopes:
      - user.info.basic: For display_name, avatar, bio
      - user.info.stats: For follower_count, following_count, likes_count, video_count
    """
    url = f"{TIKTOK_API_BASE}/user/info/"
    
    request_fields = fields or DEFAULT_USER_FIELDS
    
    # TikTok v2 API uses query params for fields
    params = {
        "fields": ",".join(request_fields),
    }
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    # Check for API-level error
    error_code = js.get("error", {}).get("code")
    if status >= 400 or error_code:
        Log.info(f"{log_tag} TikTok user info error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_tiktok_error(js),
        }
    
    data = js.get("data", {}).get("user", {})
    
    return {
        "success": True,
        "open_id": data.get("open_id"),
        "union_id": data.get("union_id"),
        "display_name": data.get("display_name"),
        "avatar_url": data.get("avatar_url") or data.get("avatar_url_100") or data.get("avatar_large_url"),
        "bio_description": data.get("bio_description"),
        "profile_deep_link": data.get("profile_deep_link"),
        "is_verified": data.get("is_verified"),
        "follower_count": data.get("follower_count"),
        "following_count": data.get("following_count"),
        "likes_count": data.get("likes_count"),
        "video_count": data.get("video_count"),
        "raw": data,
    }


# -------------------------------------------------------------------
# Video List
# -------------------------------------------------------------------

def _get_user_videos(
    *,
    access_token: str,
    max_count: int = 20,
    cursor: Optional[int] = None,
    fields: Optional[List[str]] = None,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Fetch list of user's videos.
    
    Required scope: video.list
    
    Note: TikTok API v2 uses POST for video list endpoint.
    """
    url = f"{TIKTOK_API_BASE}/video/list/"
    
    request_fields = fields or DEFAULT_VIDEO_FIELDS
    
    params = {
        "fields": ",".join(request_fields),
    }
    
    json_data = {
        "max_count": min(max_count, 20),  # TikTok max is 20 per request
    }
    
    if cursor:
        json_data["cursor"] = cursor
    
    status, js, raw = _request_post(
        url=url,
        headers=_auth_headers(access_token),
        json_data=json_data,
        timeout=30,
    )
    
    # Check for API-level error
    error_code = js.get("error", {}).get("code")
    if status >= 400 or error_code:
        Log.info(f"{log_tag} TikTok video list error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_tiktok_error(js),
        }
    
    data = js.get("data", {})
    videos_raw = data.get("videos", [])
    
    # Normalize videos
    videos = []
    for v in videos_raw:
        videos.append({
            "id": v.get("id"),
            "title": v.get("title"),
            "video_description": v.get("video_description"),
            "cover_image_url": v.get("cover_image_url"),
            "share_url": v.get("share_url"),
            "embed_link": v.get("embed_link"),
            "create_time": v.get("create_time"),
            "duration": v.get("duration"),
            "metrics": {
                "view_count": v.get("view_count"),
                "like_count": v.get("like_count"),
                "comment_count": v.get("comment_count"),
                "share_count": v.get("share_count"),
            },
            "raw": v,
        })
    
    return {
        "success": True,
        "videos": videos,
        "cursor": data.get("cursor"),
        "has_more": data.get("has_more", False),
    }


# -------------------------------------------------------------------
# Video Query (by IDs)
# -------------------------------------------------------------------

def _query_videos(
    *,
    access_token: str,
    video_ids: List[str],
    fields: Optional[List[str]] = None,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Query specific videos by ID.
    
    Required scope: video.list
    """
    url = f"{TIKTOK_API_BASE}/video/query/"
    
    request_fields = fields or DEFAULT_VIDEO_FIELDS
    
    params = {
        "fields": ",".join(request_fields),
    }
    
    json_data = {
        "filters": {
            "video_ids": video_ids[:20],  # Max 20 per request
        }
    }
    
    status, js, raw = _request_post(
        url=url,
        headers=_auth_headers(access_token),
        json_data=json_data,
        timeout=30,
    )
    
    error_code = js.get("error", {}).get("code")
    if status >= 400 or error_code:
        Log.info(f"{log_tag} TikTok video query error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_tiktok_error(js),
        }
    
    data = js.get("data", {})
    videos_raw = data.get("videos", [])
    
    videos = []
    for v in videos_raw:
        videos.append({
            "id": v.get("id"),
            "title": v.get("title"),
            "video_description": v.get("video_description"),
            "cover_image_url": v.get("cover_image_url"),
            "share_url": v.get("share_url"),
            "embed_link": v.get("embed_link"),
            "create_time": v.get("create_time"),
            "duration": v.get("duration"),
            "metrics": {
                "view_count": v.get("view_count"),
                "like_count": v.get("like_count"),
                "comment_count": v.get("comment_count"),
                "share_count": v.get("share_count"),
            },
        })
    
    return {
        "success": True,
        "videos": videos,
    }


# -------------------------------------------------------------------
# Calculate Account Summary
# -------------------------------------------------------------------

def _calculate_video_summaries(videos: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate summary statistics from video list."""
    if not videos:
        return {
            "total_videos": 0,
            "total_views": 0,
            "total_likes": 0,
            "total_comments": 0,
            "total_shares": 0,
            "average_views": 0,
            "average_likes": 0,
            "average_engagement_rate": 0,
        }
    
    total_views = 0
    total_likes = 0
    total_comments = 0
    total_shares = 0
    
    for v in videos:
        metrics = v.get("metrics", {})
        total_views += metrics.get("view_count") or 0
        total_likes += metrics.get("like_count") or 0
        total_comments += metrics.get("comment_count") or 0
        total_shares += metrics.get("share_count") or 0
    
    count = len(videos)
    avg_views = round(total_views / count, 2) if count > 0 else 0
    avg_likes = round(total_likes / count, 2) if count > 0 else 0
    
    # Engagement rate = (likes + comments + shares) / views * 100
    total_engagement = total_likes + total_comments + total_shares
    engagement_rate = round((total_engagement / total_views) * 100, 2) if total_views > 0 else 0
    
    return {
        "total_videos": count,
        "total_views": total_views,
        "total_likes": total_likes,
        "total_comments": total_comments,
        "total_shares": total_shares,
        "average_views": avg_views,
        "average_likes": avg_likes,
        "average_engagement_rate": engagement_rate,
    }


# -------------------------------------------------------------------
# TikTok: ACCOUNT INSIGHTS (Main Endpoint)
# -------------------------------------------------------------------

@blp_tiktok_insights.route("/social/tiktok/account-insights", methods=["GET"])
class TikTokAccountInsightsResource(MethodView):
    """
    TikTok account analytics using stored SocialAccount token.

    Query params:
      - destination_id (required): TikTok Open ID
      - include_videos: "true" to include recent video stats (default: true)
      - video_count: Number of recent videos to analyze (default: 20, max: 100)
      - debug: "true" to include debug info
      
    Returns:
      - User info (display_name, avatar, bio)
      - Follower/following/likes counts
      - Recent video performance summary
      
    Required OAuth scopes:
      - user.info.basic (for profile info)
      - user.info.stats (for follower counts)
      - video.list (for video list)
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[tiktok_insights][account][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Parse query parameters
        tiktok_user_id = (request.args.get("destination_id") or "").strip()
        include_videos = (request.args.get("include_videos") or "true").lower() != "false"
        debug_mode = (request.args.get("debug") or "").lower() == "true"
        
        try:
            video_count = min(max(int(request.args.get("video_count", 20)), 1), 100)
        except ValueError:
            video_count = 20

        if not tiktok_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=tiktok_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "TT_NOT_CONNECTED",
                "message": "TikTok account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "TT_TOKEN_MISSING",
                "message": "Reconnect TikTok - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch user info
        user_info = _get_tiktok_user_info(
            access_token=access_token,
            log_tag=log_tag,
        )

        if not user_info.get("success"):
            error = user_info.get("error", {})
            status_code = user_info.get("status_code", 400)
            
            # Check permission error FIRST (scope_not_authorized comes with 401)
            if _is_permission_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "TT_PERMISSION_DENIED",
                    "message": "Missing required scopes. Please reconnect TikTok with proper permissions.",
                    "error": error,
                    "required_scopes": [
                        "user.info.basic",
                        "user.info.stats",
                        "video.list",
                    ],
                    "help": "Update your OAuth scope parameter to include: user.info.basic,user.info.stats,video.list",
                }), HTTP_STATUS_CODES["FORBIDDEN"]
            
            # Then check auth error
            if _is_auth_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "TT_TOKEN_EXPIRED",
                    "message": "TikTok access token has expired. Please reconnect.",
                    "error": error,
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            if _is_rate_limit_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "TT_RATE_LIMITED",
                    "message": "Rate limit exceeded. Please try again later.",
                    "error": error,
                }), HTTP_STATUS_CODES["TOO_MANY_REQUESTS"]
            
            return jsonify({
                "success": False,
                "code": "TT_USER_INFO_ERROR",
                "message": error.get("message") or "Failed to fetch user info",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch videos if requested
        video_summary = None
        videos = []
        video_error = None
        
        if include_videos:
            all_videos = []
            cursor = None
            remaining = video_count
            
            # Paginate through videos
            while remaining > 0:
                fetch_count = min(remaining, 20)
                
                videos_resp = _get_user_videos(
                    access_token=access_token,
                    max_count=fetch_count,
                    cursor=cursor,
                    log_tag=log_tag,
                )
                
                if not videos_resp.get("success"):
                    video_error = videos_resp.get("error")
                    break
                
                batch_videos = videos_resp.get("videos", [])
                all_videos.extend(batch_videos)
                
                remaining -= len(batch_videos)
                cursor = videos_resp.get("cursor")
                
                if not videos_resp.get("has_more") or not cursor:
                    break
            
            # Remove raw data for cleaner response
            videos = []
            for v in all_videos:
                v_clean = {k: val for k, val in v.items() if k != "raw"}
                videos.append(v_clean)
            
            video_summary = _calculate_video_summaries(all_videos)

        # Build response
        result = {
            "platform": PLATFORM_ID,
            "destination_id": tiktok_user_id,
            
            "account_info": {
                "open_id": user_info.get("open_id"),
                "display_name": user_info.get("display_name"),
                "avatar_url": user_info.get("avatar_url"),
                "bio_description": user_info.get("bio_description"),
                "profile_deep_link": user_info.get("profile_deep_link"),
                "is_verified": user_info.get("is_verified"),
            },
            
            "public_metrics": {
                "follower_count": user_info.get("follower_count"),
                "following_count": user_info.get("following_count"),
                "likes_count": user_info.get("likes_count"),
                "video_count": user_info.get("video_count"),
            },
            
            "video_summary": video_summary,
            "video_error": video_error,
        }
        
        if debug_mode:
            result["debug"] = {
                "videos_fetched": len(videos),
                "required_scopes": [
                    "user.info.basic",
                    "user.info.stats",
                    "video.list",
                ],
                "note": "Detailed video insights (watch time, reach) require TikTok for Business API access.",
            }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# TikTok: VIDEO LIST
# -------------------------------------------------------------------

@blp_tiktok_insights.route("/social/tiktok/video-list", methods=["GET"])
class TikTokVideoListResource(MethodView):
    """
    List videos for a TikTok account.

    Query params:
      - destination_id (required): TikTok Open ID
      - limit: Number of videos (default: 20, max: 20 per page)
      - cursor: Pagination cursor from previous response
      
    Returns:
      - List of videos with basic metrics
      - Pagination cursor for next page
      
    Required scope: video.list
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[tiktok_insights][video_list][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        tiktok_user_id = (request.args.get("destination_id") or "").strip()
        if not tiktok_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Parse limit and cursor
        try:
            limit = min(max(int(request.args.get("limit", 20)), 1), 20)
        except ValueError:
            limit = 20
        
        cursor_str = (request.args.get("cursor") or "").strip()
        cursor = None
        if cursor_str:
            try:
                cursor = int(cursor_str)
            except ValueError:
                cursor = None

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=tiktok_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "TT_NOT_CONNECTED",
                "message": "TikTok account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "TT_TOKEN_MISSING",
                "message": "Reconnect TikTok - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch videos
        videos_resp = _get_user_videos(
            access_token=access_token,
            max_count=limit,
            cursor=cursor,
            log_tag=log_tag,
        )

        if not videos_resp.get("success"):
            error = videos_resp.get("error", {})
            status_code = videos_resp.get("status_code", 400)
            
            # Check permission error FIRST
            if _is_permission_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "TT_PERMISSION_DENIED",
                    "message": "Missing video.list scope. Please reconnect with proper permissions.",
                    "error": error,
                    "required_scopes": ["video.list"],
                }), HTTP_STATUS_CODES["FORBIDDEN"]
            
            if _is_auth_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "TT_TOKEN_EXPIRED",
                    "message": "TikTok access token has expired. Please reconnect.",
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            return jsonify({
                "success": False,
                "code": "TT_VIDEO_LIST_ERROR",
                "message": error.get("message") or "Failed to fetch videos",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Remove raw data
        videos = []
        for v in videos_resp.get("videos", []):
            v_clean = {k: val for k, val in v.items() if k != "raw"}
            videos.append(v_clean)

        result = {
            "platform": PLATFORM_ID,
            "destination_id": tiktok_user_id,
            "count": len(videos),
            "limit": limit,
            "videos": videos,
            "pagination": {
                "cursor": videos_resp.get("cursor"),
                "has_more": videos_resp.get("has_more", False),
            },
        }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# TikTok: VIDEO INSIGHTS
# -------------------------------------------------------------------

@blp_tiktok_insights.route("/social/tiktok/video-insights", methods=["GET"])
class TikTokVideoInsightsResource(MethodView):
    """
    Video analytics for a specific TikTok video.

    Query params:
      - destination_id (required): TikTok Open ID
      - video_id (required): TikTok Video ID
      - debug: "true" to include debug info
      
    Returns:
      - Video metrics: views, likes, comments, shares
      - Video info: title, cover image, duration
      
    Required scope: video.list
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[tiktok_insights][video][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        tiktok_user_id = (request.args.get("destination_id") or "").strip()
        video_id = (request.args.get("video_id") or "").strip()
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        if not tiktok_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        if not video_id:
            return jsonify({
                "success": False,
                "message": "video_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=tiktok_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "TT_NOT_CONNECTED",
                "message": "TikTok account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "TT_TOKEN_MISSING",
                "message": "Reconnect TikTok - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Query the specific video
        videos_resp = _query_videos(
            access_token=access_token,
            video_ids=[video_id],
            log_tag=log_tag,
        )

        if not videos_resp.get("success"):
            error = videos_resp.get("error", {})
            status_code = videos_resp.get("status_code", 400)
            
            if _is_permission_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "TT_PERMISSION_DENIED",
                    "message": "Missing video.list scope. Please reconnect with proper permissions.",
                    "error": error,
                }), HTTP_STATUS_CODES["FORBIDDEN"]
            
            return jsonify({
                "success": False,
                "code": "TT_VIDEO_INSIGHTS_ERROR",
                "message": error.get("message") or "Failed to fetch video insights",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        videos = videos_resp.get("videos", [])
        
        if not videos:
            return jsonify({
                "success": False,
                "code": "TT_VIDEO_NOT_FOUND",
                "message": "Video not found or not accessible",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        video = videos[0]

        result = {
            "platform": PLATFORM_ID,
            "destination_id": tiktok_user_id,
            "video_id": video_id,
            "video": {
                "id": video.get("id"),
                "title": video.get("title"),
                "video_description": video.get("video_description"),
                "cover_image_url": video.get("cover_image_url"),
                "share_url": video.get("share_url"),
                "embed_link": video.get("embed_link"),
                "create_time": video.get("create_time"),
                "duration": video.get("duration"),
            },
            "metrics": video.get("metrics"),
        }

        if debug_mode:
            result["debug"] = {
                "note": "Basic metrics available via video.list scope. For watch time and reach metrics, TikTok for Business API access is required.",
                "available_basic_metrics": [
                    "view_count",
                    "like_count",
                    "comment_count",
                    "share_count",
                ],
                "business_api_metrics": [
                    "reach",
                    "average_watch_time",
                    "full_video_watched_rate",
                    "impressions",
                ],
            }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# TikTok: VIDEO DETAILS
# -------------------------------------------------------------------

@blp_tiktok_insights.route("/social/tiktok/video-details", methods=["GET"])
class TikTokVideoDetailsResource(MethodView):
    """
    Get detailed information for a specific TikTok video.

    Query params:
      - destination_id (required): TikTok Open ID
      - video_id (required): TikTok Video ID
      
    Returns full video data including title, description, cover, and metrics.
    
    Required scope: video.list
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[tiktok_insights][video_details][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        tiktok_user_id = (request.args.get("destination_id") or "").strip()
        video_id = (request.args.get("video_id") or "").strip()

        if not tiktok_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        if not video_id:
            return jsonify({
                "success": False,
                "message": "video_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=tiktok_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "TT_NOT_CONNECTED",
                "message": "TikTok account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "TT_TOKEN_MISSING",
                "message": "Reconnect TikTok - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Query the specific video with all fields
        all_fields = [
            "id",
            "title",
            "video_description",
            "cover_image_url",
            "share_url",
            "embed_html",
            "embed_link",
            "create_time",
            "duration",
            "height",
            "width",
            "like_count",
            "comment_count",
            "share_count",
            "view_count",
        ]
        
        videos_resp = _query_videos(
            access_token=access_token,
            video_ids=[video_id],
            fields=all_fields,
            log_tag=log_tag,
        )

        if not videos_resp.get("success"):
            error = videos_resp.get("error", {})
            status_code = videos_resp.get("status_code", 400)
            
            if _is_permission_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "TT_PERMISSION_DENIED",
                    "message": "Missing video.list scope. Please reconnect with proper permissions.",
                    "error": error,
                }), HTTP_STATUS_CODES["FORBIDDEN"]
            
            return jsonify({
                "success": False,
                "code": "TT_VIDEO_DETAILS_ERROR",
                "message": error.get("message") or "Failed to fetch video details",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        videos = videos_resp.get("videos", [])
        
        if not videos:
            return jsonify({
                "success": False,
                "code": "TT_VIDEO_NOT_FOUND",
                "message": "Video not found or not accessible",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        video = videos[0]

        result = {
            "platform": PLATFORM_ID,
            "video": video,
        }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# TikTok: DISCOVER METRICS (Diagnostic)
# -------------------------------------------------------------------

@blp_tiktok_insights.route("/social/tiktok/discover-metrics", methods=["GET"])
class TikTokDiscoverMetricsResource(MethodView):
    """
    Diagnostic endpoint to test what your token can access.

    Query params:
      - destination_id (required): TikTok Open ID
      
    Returns:
      - User info availability
      - Video list availability
      - Scope assessment
      - Recommendations for missing scopes
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[tiktok_insights][discover][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        tiktok_user_id = (request.args.get("destination_id") or "").strip()
        if not tiktok_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=tiktok_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "TT_NOT_CONNECTED",
                "message": "TikTok account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "TT_TOKEN_MISSING",
                "message": "Reconnect TikTok - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Test user info (basic)
        user_info_basic = _get_tiktok_user_info(
            access_token=access_token,
            fields=["open_id", "display_name", "avatar_url", "bio_description"],
            log_tag=log_tag,
        )

        # Test user info (stats)
        user_info_stats = _get_tiktok_user_info(
            access_token=access_token,
            fields=["follower_count", "following_count", "likes_count", "video_count"],
            log_tag=log_tag,
        )

        # Test video list
        videos_resp = _get_user_videos(
            access_token=access_token,
            max_count=5,
            log_tag=log_tag,
        )

        # Assess access level
        has_user_basic = user_info_basic.get("success", False)
        has_user_stats = user_info_stats.get("success", False) and user_info_stats.get("follower_count") is not None
        has_video_list = videos_resp.get("success", False)

        scopes_available = []
        scopes_missing = []
        
        if has_user_basic:
            scopes_available.append("user.info.basic")
        else:
            scopes_missing.append("user.info.basic")
            
        if has_user_stats:
            scopes_available.append("user.info.stats")
        else:
            scopes_missing.append("user.info.stats")
            
        if has_video_list:
            scopes_available.append("video.list")
        else:
            scopes_missing.append("video.list")

        access_level = "none"
        if has_user_basic:
            access_level = "basic"
        if has_user_basic and has_user_stats:
            access_level = "standard"
        if has_user_basic and has_user_stats and has_video_list:
            access_level = "full"

        return jsonify({
            "success": True,
            "data": {
                "platform": PLATFORM_ID,
                "destination_id": tiktok_user_id,
                
                "probes": {
                    "user_info_basic": {
                        "success": has_user_basic,
                        "display_name": user_info_basic.get("display_name") if has_user_basic else None,
                        "error": user_info_basic.get("error") if not has_user_basic else None,
                    },
                    "user_info_stats": {
                        "success": has_user_stats,
                        "follower_count": user_info_stats.get("follower_count") if has_user_stats else None,
                        "video_count": user_info_stats.get("video_count") if has_user_stats else None,
                        "error": user_info_stats.get("error") if not has_user_stats else None,
                    },
                    "video_list": {
                        "success": has_video_list,
                        "count": len(videos_resp.get("videos", [])) if has_video_list else 0,
                        "sample_video_id": videos_resp.get("videos", [{}])[0].get("id") if has_video_list and videos_resp.get("videos") else None,
                        "error": videos_resp.get("error") if not has_video_list else None,
                    },
                },
                
                "access_level": access_level,
                "scopes_available": scopes_available,
                "scopes_missing": scopes_missing,
                
                "recommendation": (
                    "Full access available! All required scopes are authorized." 
                    if access_level == "full"
                    else f"Missing scopes: {', '.join(scopes_missing)}. Update your OAuth scope parameter and have the user reconnect."
                ),
                
                "oauth_scope_string": "user.info.basic,user.info.stats,video.list",
                
                "notes": [
                    "TikTok API v2 uses OAuth 2.0 with specific scopes.",
                    "Each scope must be explicitly authorized by the user.",
                    "Basic metrics: view_count, like_count, comment_count, share_count.",
                    "Advanced metrics (watch time, reach) require TikTok for Business API.",
                    "Video insights may have up to 2-day delay.",
                    "Rate limits vary by endpoint and access level.",
                ],
                
                "required_scopes": {
                    "basic": ["user.info.basic"],
                    "standard": ["user.info.basic", "user.info.stats"],
                    "full": ["user.info.basic", "user.info.stats", "video.list"],
                    "posting": ["video.upload", "video.publish"],
                },
            },
        }), HTTP_STATUS_CODES["OK"]