# app/resources/social/facebook_insights_resource.py
#
# Facebook Page analytics using STORED SocialAccount token
#
# Facebook Graph API v21.0:
# - Page info and metrics
# - Page insights (time series)
# - Post list and insights
# - Video insights
#
# What you can get:
# - Page metrics: followers, fans, engagement
# - Post metrics: impressions, reach, reactions, comments, shares
# - Video metrics: views, watch time
#
# Key limitations:
# - Many metrics deprecated Nov 2025 (New Pages Experience)
# - Use followers_count from page fields instead of page_fans
# - Insights require read_insights permission
# - Rate limits apply

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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

blp_meta_impression = Blueprint(
    "facebook_insights",
    __name__,
)

# Facebook Graph API version
GRAPH_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Platform identifier
PLATFORM_ID = "facebook"


# -------------------------------------------------------------------
# Valid Metrics Reference (Updated Feb 2025 - Post Nov 2025 Deprecation)
# -------------------------------------------------------------------
# IMPORTANT: As of November 15, 2025, Meta deprecated 80+ page metrics
# as part of the "New Pages Experience" migration.
#
# CONFIRMED WORKING (Feb 2025):
# - page_post_engagements: Total engagements on posts
# - page_daily_follows_unique: New followers per day
# - page_video_views: Video views
# - page_posts_impressions: Post impressions
#
# DEPRECATED (Nov 2025):
# - page_impressions, page_fans, page_engaged_users, page_views_total

# Page-level metrics (/{page-id}/insights)
VALID_PAGE_METRICS = {
    # Engagement metrics (period: day, week, days_28)
    "page_post_engagements",           # Total engagements on page posts
    "page_daily_follows_unique",       # New followers per day
    "page_daily_unfollows_unique",     # Unfollows per day
    "page_follows",                    # Total page follows (lifetime)
    
    # Post metrics
    "page_posts_impressions",          # Impressions of page posts
    "page_posts_impressions_unique",   # Unique impressions (reach)
    "page_posts_impressions_organic",  # Organic impressions
    "page_posts_impressions_paid",     # Paid impressions
    
    # Video metrics
    "page_video_views",                # Total video views
    "page_video_views_organic",        # Organic video views
    "page_video_views_paid",           # Paid video views
    
    # Actions
    "page_total_actions",              # Total actions on page
    "page_call_phone_clicks_logged_in_unique",  # Phone clicks
    "page_website_clicks_logged_in_unique",     # Website clicks
    "page_get_directions_clicks_logged_in_unique",  # Directions clicks
    
    # Content interactions
    "page_consumptions_unique",        # Unique content consumptions
    "page_places_checkin_total",       # Check-ins
    
    # Views (logged in users only)
    "page_views_logged_in_total",      # Total page views (logged in)
    "page_views_logged_in_unique",     # Unique page views (logged in)
}

# Post-level metrics (/{post-id}/insights)
VALID_POST_METRICS = {
    "post_impressions",                # Times post was shown
    "post_impressions_unique",         # Unique accounts reached
    "post_impressions_organic",        # Organic impressions
    "post_impressions_paid",           # Paid impressions
    "post_engaged_users",              # Users who engaged
    "post_clicks",                     # Total clicks
    "post_clicks_unique",              # Unique clickers
    "post_reactions_like_total",       # Like reactions
    "post_reactions_love_total",       # Love reactions
    "post_reactions_wow_total",        # Wow reactions
    "post_reactions_haha_total",       # Haha reactions
    "post_reactions_sorry_total",      # Sad reactions
    "post_reactions_anger_total",      # Angry reactions
    "post_reactions_by_type_total",    # All reactions by type
    "post_activity_by_action_type",    # Activity breakdown
}

# Video-specific metrics
VALID_VIDEO_METRICS = {
    "total_video_views",               # Total views
    "total_video_views_unique",        # Unique viewers
    "total_video_views_organic",       # Organic views
    "total_video_views_paid",          # Paid views
    "total_video_avg_time_watched",    # Average watch time
    "total_video_complete_views",      # Complete views
    "total_video_10s_views",           # 10+ second views
    "total_video_30s_views",           # 30+ second views
}

# Deprecated metrics - DO NOT USE
DEPRECATED_METRICS = {
    "page_impressions",                # Deprecated Nov 2025
    "page_impressions_unique",         # Deprecated Nov 2025
    "page_fans",                       # Use followers_count from page fields
    "page_fan_adds",                   # Use page_daily_follows_unique
    "page_fan_removes",                # Use page_daily_unfollows_unique
    "page_engaged_users",              # Deprecated Nov 2025
    "page_views_total",                # Use page_views_logged_in_total
    "page_stories",                    # Deprecated
    "page_storytellers",               # Deprecated
}

# Default page metrics - CONFIRMED WORKING as of Feb 2025
DEFAULT_PAGE_METRICS = [
    "page_post_engagements",
    "page_posts_impressions",
    "page_daily_follows_unique",
    "page_video_views",
]

# Default post metrics
DEFAULT_POST_METRICS = [
    "post_impressions",
    "post_impressions_unique",
    "post_engaged_users",
    "post_clicks",
    "post_reactions_by_type_total",
]

# Valid periods for page insights
VALID_PERIODS = {"day", "week", "days_28", "lifetime"}


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


# -------------------------------
# Date helpers
# -------------------------------

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


def _to_unix_timestamp(dt: datetime) -> int:
    """Convert datetime to Unix timestamp for API."""
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def _get_date_range_last_n_days(n: int = 30) -> Tuple[str, str]:
    """Get since/until for last N days."""
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=n)
    return _fmt_ymd(since), _fmt_ymd(until)


# -------------------------------
# Error parsing
# -------------------------------

def _parse_fb_error(response_json: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Facebook/Graph API error response."""
    error = response_json.get("error", {})
    return {
        "message": error.get("message", "Unknown error"),
        "type": error.get("type", "Unknown"),
        "code": error.get("code"),
        "error_subcode": error.get("error_subcode"),
        "fbtrace_id": error.get("fbtrace_id"),
    }


def _is_auth_error(error: Dict[str, Any], status_code: int) -> bool:
    """Check if error is authentication related (token expired/invalid)."""
    if status_code == 401:
        return True
    code = error.get("code")
    return code == 190  # OAuth token expired/invalid


def _is_permission_error(error: Dict[str, Any], status_code: int) -> bool:
    """Check if error is permission related."""
    if status_code == 403:
        return True
    code = error.get("code")
    return code in [10, 200, 210]  # Permission errors


def _is_rate_limit_error(error: Dict[str, Any], status_code: int) -> bool:
    """Check if error is rate limit related."""
    if status_code == 429:
        return True
    code = error.get("code")
    return code in [4, 17, 32, 613]  # Rate limit codes


def _is_invalid_metric_error(error: Dict[str, Any]) -> bool:
    """Check if error is about invalid/deprecated metric."""
    code = error.get("code")
    message = str(error.get("message", "")).lower()
    return code == 100 and ("invalid" in message or "metric" in message)


# -------------------------------
# API request helper
# -------------------------------

def _request_get(
    *,
    url: str,
    params: Dict[str, Any],
    timeout: int = 30,
) -> Tuple[int, Dict[str, Any], str]:
    """Make GET request and return (status, json, raw_text)."""
    try:
        r = requests.get(url, params=params, timeout=timeout)
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


# -------------------------------
# Token debug
# -------------------------------

def _debug_token(access_token: str, log_tag: str) -> Dict[str, Any]:
    """Debug token to check permissions and validity."""
    url = f"{GRAPH_API_BASE}/debug_token"
    params = {
        "input_token": access_token,
        "access_token": access_token,
    }
    
    status, js, raw = _request_get(url=url, params=params, timeout=15)
    
    if status >= 400:
        return {
            "valid": False,
            "error": "Token debug request failed",
            "status_code": status,
        }
    
    data = js.get("data", {})
    
    return {
        "valid": data.get("is_valid", False),
        "app_id": data.get("app_id"),
        "type": data.get("type"),
        "expires_at": data.get("expires_at"),
        "data_access_expires_at": data.get("data_access_expires_at"),
        "scopes": data.get("scopes", []),
        "granular_scopes": data.get("granular_scopes", []),
    }


# -------------------------------
# Page info
# -------------------------------

def _get_facebook_page_info(
    *,
    page_id: str,
    access_token: str,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Fetch basic Facebook page info using fields endpoint.
    
    Returns:
        - id, name, username
        - followers_count, fan_count
        - link, picture, category
        - about, website
    """
    url = f"{GRAPH_API_BASE}/{page_id}"
    
    params = {
        "fields": "id,name,username,followers_count,fan_count,link,picture,category,about,website",
        "access_token": access_token,
    }
    
    status, js, raw = _request_get(url=url, params=params, timeout=30)
    
    if status >= 400:
        Log.info(f"{log_tag} FB page info error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_fb_error(js),
        }
    
    return {
        "success": True,
        "id": js.get("id"),
        "name": js.get("name"),
        "username": js.get("username"),
        "followers_count": js.get("followers_count"),
        "fan_count": js.get("fan_count"),
        "link": js.get("link"),
        "picture": js.get("picture", {}).get("data", {}).get("url") if isinstance(js.get("picture"), dict) else None,
        "category": js.get("category"),
        "about": js.get("about"),
        "website": js.get("website"),
        "raw": js,
    }


# -------------------------------
# Page insights fetching
# -------------------------------

def _fetch_page_insights(
    *,
    page_id: str,
    access_token: str,
    metrics: List[str],
    period: str,
    since: Optional[str],
    until: Optional[str],
    log_tag: str,
) -> Dict[str, Any]:
    """
    Fetch Facebook page-level insights.
    
    Fetches metrics individually for better error handling.
    """
    url = f"{GRAPH_API_BASE}/{page_id}/insights"
    
    valid_metrics: List[str] = []
    invalid_metrics: List[Dict[str, Any]] = []
    all_metrics: Dict[str, List[Dict[str, Any]]] = {}
    deprecated_found: List[str] = []
    permission_errors: List[str] = []
    
    # De-duplicate metrics
    seen = set()
    uniq_metrics = []
    for m in metrics:
        m2 = (m or "").strip()
        if m2 and m2 not in seen:
            seen.add(m2)
            uniq_metrics.append(m2)
    
    # Build date params
    date_params = {}
    if since and until:
        since_dt = _parse_ymd(since)
        until_dt = _parse_ymd(until)
        if since_dt:
            date_params["since"] = _to_unix_timestamp(since_dt)
        if until_dt:
            date_params["until"] = _to_unix_timestamp(until_dt + timedelta(days=1))
    
    # Fetch metrics individually for better error handling
    for metric in uniq_metrics:
        params = {
            "metric": metric,
            "period": period,
            "access_token": access_token,
            **date_params,
        }
        
        status, js, raw = _request_get(url=url, params=params, timeout=30)
        
        if status >= 400:
            parsed_error = _parse_fb_error(js)
            
            invalid_metrics.append({
                "metric": metric,
                "status_code": status,
                "error": parsed_error,
            })
            
            if _is_invalid_metric_error(parsed_error):
                deprecated_found.append(metric)
                Log.info(f"{log_tag} Metric '{metric}' is invalid or deprecated")
            elif _is_permission_error(parsed_error, status):
                permission_errors.append(metric)
                Log.info(f"{log_tag} Metric '{metric}' requires additional permissions")
                
            continue
        
        # Extract series data
        data = js.get("data", [])
        
        if data:
            series = []
            for item in data:
                if item.get("name") == metric:
                    for v in item.get("values", []):
                        series.append({
                            "end_time": v.get("end_time"),
                            "value": v.get("value"),
                        })
                    break
            
            if series:
                all_metrics[metric] = series
                valid_metrics.append(metric)
            else:
                invalid_metrics.append({
                    "metric": metric,
                    "status_code": 200,
                    "error": {"message": "No data returned"},
                })
        else:
            invalid_metrics.append({
                "metric": metric,
                "status_code": 200,
                "error": {"message": "Empty response"},
            })
    
    return {
        "valid_metrics": valid_metrics,
        "invalid_metrics": invalid_metrics,
        "deprecated_metrics": list(set(deprecated_found)),
        "permission_errors": list(set(permission_errors)),
        "metrics": all_metrics,
    }


# -------------------------------
# Post list fetching
# -------------------------------

def _get_page_posts(
    *,
    page_id: str,
    access_token: str,
    limit: int = 25,
    after: Optional[str] = None,
    before: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Fetch list of posts for a page.
    """
    url = f"{GRAPH_API_BASE}/{page_id}/posts"
    
    fields = [
        "id",
        "message",
        "story",
        "created_time",
        "updated_time",
        "permalink_url",
        "full_picture",
        "type",
        "status_type",
        "shares",
        "reactions.summary(true)",
        "comments.summary(true)",
    ]
    
    params = {
        "fields": ",".join(fields),
        "limit": min(limit, 100),
        "access_token": access_token,
    }
    
    if after:
        params["after"] = after
    if before:
        params["before"] = before
    if since:
        since_dt = _parse_ymd(since)
        if since_dt:
            params["since"] = _to_unix_timestamp(since_dt)
    if until:
        until_dt = _parse_ymd(until)
        if until_dt:
            params["until"] = _to_unix_timestamp(until_dt + timedelta(days=1))
    
    status, js, raw = _request_get(url=url, params=params, timeout=30)
    
    if status >= 400:
        Log.info(f"{log_tag} FB posts list error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_fb_error(js),
        }
    
    post_list = js.get("data", [])
    paging = js.get("paging", {})
    
    # Normalize posts
    posts = []
    for post in post_list:
        processed = {
            "id": post.get("id"),
            "message": post.get("message"),
            "story": post.get("story"),
            "created_time": post.get("created_time"),
            "updated_time": post.get("updated_time"),
            "permalink_url": post.get("permalink_url"),
            "full_picture": post.get("full_picture"),
            "type": post.get("type"),
            "status_type": post.get("status_type"),
        }
        
        # Flatten reactions
        if "reactions" in post and isinstance(post["reactions"], dict):
            processed["reactions_count"] = post["reactions"].get("summary", {}).get("total_count", 0)
        else:
            processed["reactions_count"] = 0
        
        # Flatten comments
        if "comments" in post and isinstance(post["comments"], dict):
            processed["comments_count"] = post["comments"].get("summary", {}).get("total_count", 0)
        else:
            processed["comments_count"] = 0
        
        # Flatten shares
        if "shares" in post and isinstance(post["shares"], dict):
            processed["shares_count"] = post["shares"].get("count", 0)
        else:
            processed["shares_count"] = 0
        
        posts.append(processed)
    
    # Extract pagination
    cursors = paging.get("cursors", {})
    pagination = {
        "has_next": "next" in paging,
        "has_previous": "previous" in paging,
        "after": cursors.get("after"),
        "before": cursors.get("before"),
    }
    
    return {
        "success": True,
        "posts": posts,
        "pagination": pagination,
    }


# -------------------------------
# Post insights fetching
# -------------------------------

def _fetch_post_insights(
    *,
    post_id: str,
    access_token: str,
    metrics: List[str],
    log_tag: str,
) -> Dict[str, Any]:
    """
    Fetch insights for a specific post.
    """
    url = f"{GRAPH_API_BASE}/{post_id}/insights"
    
    params = {
        "metric": ",".join(metrics),
        "access_token": access_token,
    }
    
    status, js, raw = _request_get(url=url, params=params, timeout=30)
    
    if status >= 400:
        Log.info(f"{log_tag} FB post insights error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_fb_error(js),
        }
    
    data = js.get("data", [])
    
    # Parse metrics
    metrics_data = {}
    for item in data:
        name = item.get("name")
        values = item.get("values", [])
        if values:
            metrics_data[name] = values[0].get("value")
    
    return {
        "success": True,
        "metrics": metrics_data,
    }


# -------------------------------
# Post details fetching
# -------------------------------

def _get_post_details(
    *,
    post_id: str,
    access_token: str,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Fetch detailed info for a specific post.
    """
    url = f"{GRAPH_API_BASE}/{post_id}"
    
    fields = [
        "id",
        "message",
        "story",
        "created_time",
        "updated_time",
        "permalink_url",
        "full_picture",
        "type",
        "status_type",
        "shares",
        "reactions.summary(true)",
        "comments.summary(true)",
        "attachments{media_type,url,title,description,media}",
    ]
    
    params = {
        "fields": ",".join(fields),
        "access_token": access_token,
    }
    
    status, js, raw = _request_get(url=url, params=params, timeout=30)
    
    if status >= 400:
        Log.info(f"{log_tag} FB post details error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_fb_error(js),
        }
    
    # Normalize post data
    post = {
        "id": js.get("id"),
        "message": js.get("message"),
        "story": js.get("story"),
        "created_time": js.get("created_time"),
        "updated_time": js.get("updated_time"),
        "permalink_url": js.get("permalink_url"),
        "full_picture": js.get("full_picture"),
        "type": js.get("type"),
        "status_type": js.get("status_type"),
    }
    
    # Flatten reactions
    if "reactions" in js and isinstance(js["reactions"], dict):
        post["reactions_count"] = js["reactions"].get("summary", {}).get("total_count", 0)
    
    # Flatten comments
    if "comments" in js and isinstance(js["comments"], dict):
        post["comments_count"] = js["comments"].get("summary", {}).get("total_count", 0)
    
    # Flatten shares
    if "shares" in js and isinstance(js["shares"], dict):
        post["shares_count"] = js["shares"].get("count", 0)
    
    # Process attachments
    if "attachments" in js and "data" in js["attachments"]:
        post["attachments"] = js["attachments"]["data"]
    
    return {
        "success": True,
        "post": post,
        "raw": js,
    }


# -------------------------------
# Calculate summaries
# -------------------------------

def _calculate_metric_summary(series: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate summary statistics for a metric series."""
    if not series:
        return {"total": 0, "average": 0, "min": 0, "max": 0, "count": 0}
    
    values = []
    for item in series:
        v = item.get("value")
        if isinstance(v, (int, float)):
            values.append(v)
        elif isinstance(v, dict):
            # Breakdown metric (like reactions by type)
            return {"type": "breakdown", "count": len(series), "latest": v}
    
    if not values:
        return {"total": 0, "average": 0, "min": 0, "max": 0, "count": 0}
    
    return {
        "total": sum(values),
        "average": round(sum(values) / len(values), 2),
        "min": min(values),
        "max": max(values),
        "count": len(values),
    }


# -------------------------------------------------------------------
# FACEBOOK PAGE INSIGHTS — Main Endpoint
# -------------------------------------------------------------------

@blp_meta_impression.route("/social/facebook/page-insights", methods=["GET"])
class FacebookPageInsightsResource(MethodView):
    """
    Facebook page-level analytics using stored SocialAccount token.

    Query params:
      - destination_id (required): Facebook Page ID
      - since (YYYY-MM-DD): Start date for insights
      - until (YYYY-MM-DD): End date for insights  
      - period: day | week | days_28 | lifetime (default: day)
      - metrics: comma-separated list of metrics (optional)
      - debug: if "true", includes token debug info
      
    CONFIRMED WORKING metrics (Feb 2025):
      - page_post_engagements: Total engagements on posts
      - page_posts_impressions: Post impressions
      - page_daily_follows_unique: New followers per day
      - page_video_views: Video views
      
    DEPRECATED (Nov 2025):
      - page_impressions, page_fans, page_engaged_users
      - Use followers_count from page fields instead of page_fans
      
    Required token permissions:
      - pages_show_list
      - pages_read_engagement
      - read_insights
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_insights_resource.py][FacebookPageInsightsResource][get][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Parse query parameters
        page_id = (request.args.get("destination_id") or "").strip()
        since = (request.args.get("since") or "").strip() or None
        until = (request.args.get("until") or "").strip() or None
        period = (request.args.get("period") or "day").lower().strip()
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        # Validate required parameters
        if not page_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Validate period
        if period not in VALID_PERIODS:
            return jsonify({
                "success": False,
                "message": f"Invalid period. Must be one of: {', '.join(VALID_PERIODS)}",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Validate date format
        if since and not _parse_ymd(since):
            return jsonify({
                "success": False,
                "message": "Invalid 'since' date format. Use YYYY-MM-DD",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        if until and not _parse_ymd(until):
            return jsonify({
                "success": False,
                "message": "Invalid 'until' date format. Use YYYY-MM-DD",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Validate date range
        if since and until:
            since_dt = _parse_ymd(since)
            until_dt = _parse_ymd(until)
            if since_dt and until_dt and since_dt > until_dt:
                return jsonify({
                    "success": False,
                    "message": "'since' date must be before 'until' date",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Default to last 30 days
        if not since or not until:
            since, until = _get_date_range_last_n_days(30)

        # Parse requested metrics
        metrics_qs = (request.args.get("metrics") or "").strip()
        if metrics_qs:
            requested_metrics = [m.strip() for m in metrics_qs.split(",") if m.strip()]
        else:
            requested_metrics = DEFAULT_PAGE_METRICS.copy()

        # --------------------------------------------------
        # Load stored SocialAccount
        # --------------------------------------------------

        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=page_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "FB_NOT_CONNECTED",
                "message": "Facebook page not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "FB_TOKEN_MISSING",
                "message": "Reconnect Facebook - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # --------------------------------------------------
        # Debug token if requested
        # --------------------------------------------------

        token_info = None
        if debug_mode:
            token_info = _debug_token(access_token, log_tag)

        # --------------------------------------------------
        # Fetch page info
        # --------------------------------------------------

        page_info = _get_facebook_page_info(
            page_id=page_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        # Check for token errors early
        if not page_info.get("success"):
            error = page_info.get("error", {})
            status_code = page_info.get("status_code", 400)
            
            if _is_auth_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "FB_TOKEN_EXPIRED",
                    "message": "Facebook access token has expired. Please reconnect.",
                    "error": error,
                    "debug": token_info if debug_mode else None,
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            if _is_permission_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "FB_PERMISSION_DENIED",
                    "message": "Missing permissions. Token needs: pages_read_engagement, read_insights",
                    "error": error,
                    "debug": token_info if debug_mode else None,
                }), HTTP_STATUS_CODES["FORBIDDEN"]

        # --------------------------------------------------
        # Fetch page insights
        # --------------------------------------------------

        insights = _fetch_page_insights(
            page_id=page_id,
            access_token=access_token,
            metrics=requested_metrics,
            period=period,
            since=since,
            until=until,
            log_tag=log_tag,
        )

        # Check if ALL metrics failed due to permissions
        permission_errors = insights.get("permission_errors", [])
        if permission_errors and not insights.get("valid_metrics"):
            return jsonify({
                "success": False,
                "code": "FB_PERMISSION_DENIED",
                "message": "Missing permission 'read_insights'. Please reconnect Facebook with updated permissions.",
                "failed_metrics": permission_errors,
                "required_permissions": [
                    "pages_show_list",
                    "pages_read_engagement",
                    "read_insights",
                ],
                "page_info": {
                    "name": _pick(page_info, "name"),
                    "followers_count": _pick(page_info, "followers_count"),
                },
                "debug": token_info if debug_mode else None,
            }), HTTP_STATUS_CODES["FORBIDDEN"]

        # Check if ALL metrics failed due to deprecation
        deprecated_found = insights.get("deprecated_metrics", [])
        if deprecated_found and not insights.get("valid_metrics"):
            return jsonify({
                "success": False,
                "code": "FB_METRICS_INVALID",
                "message": f"All requested metrics are invalid. Invalid metrics: {deprecated_found}. Use these instead: {DEFAULT_PAGE_METRICS}",
                "suggested_metrics": DEFAULT_PAGE_METRICS,
                "page_info": {
                    "name": _pick(page_info, "name"),
                    "followers_count": _pick(page_info, "followers_count"),
                },
                "debug": token_info if debug_mode else None,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Calculate summaries
        summaries = {}
        for metric_name, series in insights.get("metrics", {}).items():
            summaries[metric_name] = _calculate_metric_summary(series)

        # Build response
        result = {
            "platform": PLATFORM_ID,
            "graph_version": GRAPH_VERSION,
            "destination_id": page_id,
            "page_name": _pick(page_info, "name"),
            "period": period,
            "since": since,
            "until": until,
            "requested_metrics": requested_metrics,

            "page_info": {
                "id": _pick(page_info, "id"),
                "name": _pick(page_info, "name"),
                "username": _pick(page_info, "username"),
                "followers_count": _pick(page_info, "followers_count"),
                "fan_count": _pick(page_info, "fan_count"),
                "link": _pick(page_info, "link"),
                "picture": _pick(page_info, "picture"),
                "category": _pick(page_info, "category"),
                "info_error": None if page_info.get("success") else page_info.get("error"),
            },

            "summaries": summaries,
            "valid_metrics": insights.get("valid_metrics"),
            "invalid_metrics": insights.get("invalid_metrics"),
            "deprecated_metrics": insights.get("deprecated_metrics"),
            "permission_errors": insights.get("permission_errors"),
            "metrics": insights.get("metrics"),
        }

        if debug_mode:
            result["debug"] = {
                "token_info": token_info,
                "available_page_metrics": sorted(list(VALID_PAGE_METRICS)),
                "deprecated_metrics": sorted(list(DEPRECATED_METRICS)),
                "default_metrics": DEFAULT_PAGE_METRICS,
            }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# FACEBOOK POST LIST — Get all posts for a page
# -------------------------------------------------------------------

@blp_meta_impression.route("/social/facebook/post-list", methods=["GET"])
class FacebookPostListResource(MethodView):
    """
    Get list of posts for a Facebook page.

    Query params:
      - destination_id (required): Facebook Page ID
      - limit: Number of posts to return (default: 25, max: 100)
      - after: Pagination cursor for next page
      - before: Pagination cursor for previous page
      - since (YYYY-MM-DD): Filter posts after this date
      - until (YYYY-MM-DD): Filter posts before this date
      
    Returns:
      - List of posts with basic metrics (reactions, comments, shares)
      - Pagination cursors
      
    Required permission: pages_read_engagement
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_insights_resource.py][FacebookPostListResource][get][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Parse query parameters
        page_id = (request.args.get("destination_id") or "").strip()
        after_cursor = (request.args.get("after") or "").strip() or None
        before_cursor = (request.args.get("before") or "").strip() or None
        since = (request.args.get("since") or "").strip() or None
        until = (request.args.get("until") or "").strip() or None

        try:
            limit = min(max(int(request.args.get("limit", 25)), 1), 100)
        except ValueError:
            limit = 25

        if not page_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=page_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "FB_NOT_CONNECTED",
                "message": "Facebook page not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "FB_TOKEN_MISSING",
                "message": "Reconnect Facebook - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch posts
        posts_resp = _get_page_posts(
            page_id=page_id,
            access_token=access_token,
            limit=limit,
            after=after_cursor,
            before=before_cursor,
            since=since,
            until=until,
            log_tag=log_tag,
        )

        if not posts_resp.get("success"):
            error = posts_resp.get("error", {})
            status_code = posts_resp.get("status_code", 400)
            
            if _is_auth_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "FB_TOKEN_EXPIRED",
                    "message": "Facebook access token has expired. Please reconnect.",
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            if _is_permission_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "FB_PERMISSION_DENIED",
                    "message": "Missing permissions. Token needs: pages_read_engagement",
                }), HTTP_STATUS_CODES["FORBIDDEN"]
            
            return jsonify({
                "success": False,
                "code": "FB_POST_LIST_ERROR",
                "message": error.get("message") or "Failed to fetch post list",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        result = {
            "platform": PLATFORM_ID,
            "graph_version": GRAPH_VERSION,
            "destination_id": page_id,
            "count": len(posts_resp.get("posts", [])),
            "limit": limit,
            "posts": posts_resp.get("posts", []),
            "pagination": posts_resp.get("pagination", {}),
        }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# FACEBOOK POST INSIGHTS — Get insights for a specific post
# -------------------------------------------------------------------

@blp_meta_impression.route("/social/facebook/post-insights", methods=["GET"])
class FacebookPostInsightsResource(MethodView):
    """
    Facebook post-level analytics for a specific post.

    Query params:
      - destination_id (required): Facebook Page ID
      - post_id (required): Facebook Post ID
      - metrics: comma-separated list of metrics (optional)
      - debug: if "true", includes debug info
      
    Working metrics (Feb 2025):
      - post_impressions: Times post was shown
      - post_impressions_unique: Unique accounts reached
      - post_engaged_users: Users who engaged
      - post_clicks: Total clicks
      - post_reactions_by_type_total: Reactions breakdown
      
    Required permission: read_insights
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_insights_resource.py][FacebookPostInsightsResource][get][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Parse query parameters
        page_id = (request.args.get("destination_id") or "").strip()
        post_id = (request.args.get("post_id") or "").strip()
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        if not page_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        if not post_id:
            return jsonify({
                "success": False,
                "message": "post_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Parse metrics
        metrics_qs = (request.args.get("metrics") or "").strip()
        if metrics_qs:
            requested_metrics = [m.strip() for m in metrics_qs.split(",") if m.strip()]
        else:
            requested_metrics = DEFAULT_POST_METRICS.copy()

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=page_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "FB_NOT_CONNECTED",
                "message": "Facebook page not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "FB_TOKEN_MISSING",
                "message": "Reconnect Facebook - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch post insights
        insights = _fetch_post_insights(
            post_id=post_id,
            access_token=access_token,
            metrics=requested_metrics,
            log_tag=log_tag,
        )

        if not insights.get("success"):
            error = insights.get("error", {})
            status_code = insights.get("status_code", 400)
            
            if _is_auth_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "FB_TOKEN_EXPIRED",
                    "message": "Facebook access token has expired. Please reconnect.",
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            if _is_permission_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "FB_PERMISSION_DENIED",
                    "message": "Missing read_insights permission.",
                    "error": error,
                }), HTTP_STATUS_CODES["FORBIDDEN"]
            
            return jsonify({
                "success": False,
                "code": "FB_POST_INSIGHTS_ERROR",
                "message": error.get("message") or "Failed to fetch post insights",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        result = {
            "platform": PLATFORM_ID,
            "graph_version": GRAPH_VERSION,
            "destination_id": page_id,
            "post_id": post_id,
            "requested_metrics": requested_metrics,
            "metrics": insights.get("metrics"),
        }

        if debug_mode:
            result["debug"] = {
                "available_post_metrics": sorted(list(VALID_POST_METRICS)),
            }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# FACEBOOK POST DETAILS — Get details for a specific post
# -------------------------------------------------------------------

@blp_meta_impression.route("/social/facebook/post-details", methods=["GET"])
class FacebookPostDetailsResource(MethodView):
    """
    Get detailed information for a specific Facebook post.

    Query params:
      - destination_id (required): Facebook Page ID
      - post_id (required): Facebook Post ID
      
    Returns:
      - Full post data including message, attachments, reactions, comments, shares
      
    Required permission: pages_read_engagement
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_insights_resource.py][FacebookPostDetailsResource][get][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        page_id = (request.args.get("destination_id") or "").strip()
        post_id = (request.args.get("post_id") or "").strip()

        if not page_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        if not post_id:
            return jsonify({
                "success": False,
                "message": "post_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=page_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "FB_NOT_CONNECTED",
                "message": "Facebook page not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "FB_TOKEN_MISSING",
                "message": "Reconnect Facebook - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch post details
        post_resp = _get_post_details(
            post_id=post_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        if not post_resp.get("success"):
            error = post_resp.get("error", {})
            status_code = post_resp.get("status_code", 400)
            
            if _is_auth_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "FB_TOKEN_EXPIRED",
                    "message": "Facebook access token has expired. Please reconnect.",
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            return jsonify({
                "success": False,
                "code": "FB_POST_DETAILS_ERROR",
                "message": error.get("message") or "Failed to fetch post details",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        result = {
            "platform": PLATFORM_ID,
            "graph_version": GRAPH_VERSION,
            "post": post_resp.get("post"),
        }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# FACEBOOK DISCOVER METRICS — Diagnostic endpoint
# -------------------------------------------------------------------

@blp_meta_impression.route("/social/facebook/discover-metrics", methods=["GET"])
class FacebookDiscoverMetricsResource(MethodView):
    """
    Diagnostic endpoint to test Facebook API access.
    
    Query params:
      - destination_id (required): Facebook Page ID
      
    Tests:
      - Page info access
      - Page insights (working vs deprecated metrics)
      - Post list access
      - Token permissions
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_insights_resource.py][FacebookDiscoverMetricsResource][get][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        page_id = (request.args.get("destination_id") or "").strip()
        
        if not page_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=page_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "FB_NOT_CONNECTED",
                "message": "Facebook page not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "FB_TOKEN_MISSING",
                "message": "Reconnect Facebook - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Test 1: Debug token
        token_info = _debug_token(access_token, log_tag)
        
        token_probe = {
            "valid": token_info.get("valid", False),
            "scopes": token_info.get("scopes", []),
            "has_read_insights": "read_insights" in token_info.get("scopes", []),
            "has_pages_read_engagement": "pages_read_engagement" in token_info.get("scopes", []),
        }

        # Test 2: Page info
        page_info = _get_facebook_page_info(
            page_id=page_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        page_probe = {
            "success": page_info.get("success", False),
            "name": page_info.get("name") if page_info.get("success") else None,
            "followers_count": page_info.get("followers_count") if page_info.get("success") else None,
            "error": page_info.get("error") if not page_info.get("success") else None,
        }

        # Test 3: Test metrics (working vs deprecated)
        test_metrics = [
            # Should work
            "page_post_engagements",
            "page_posts_impressions",
            "page_daily_follows_unique",
            "page_video_views",
            # Deprecated - should fail
            "page_impressions",
            "page_fans",
            "page_engaged_users",
        ]
        
        since, until = _get_date_range_last_n_days(7)
        
        working_metrics = []
        failed_metrics = []
        
        for metric in test_metrics:
            insights = _fetch_page_insights(
                page_id=page_id,
                access_token=access_token,
                metrics=[metric],
                period="day",
                since=since,
                until=until,
                log_tag=log_tag,
            )
            
            if insights.get("valid_metrics"):
                working_metrics.append({
                    "metric": metric,
                    "has_data": bool(insights.get("metrics", {}).get(metric)),
                })
            else:
                invalid = insights.get("invalid_metrics", [{}])[0]
                failed_metrics.append({
                    "metric": metric,
                    "error": invalid.get("error", {}).get("message") if invalid else "Unknown",
                    "deprecated": metric in DEPRECATED_METRICS,
                })

        # Test 4: Posts list
        posts_resp = _get_page_posts(
            page_id=page_id,
            access_token=access_token,
            limit=5,
            log_tag=log_tag,
        )

        posts_probe = {
            "success": posts_resp.get("success", False),
            "count": len(posts_resp.get("posts", [])) if posts_resp.get("success") else 0,
            "sample_post_id": posts_resp.get("posts", [{}])[0].get("id") if posts_resp.get("success") and posts_resp.get("posts") else None,
            "error": posts_resp.get("error") if not posts_resp.get("success") else None,
        }

        # Determine access level
        has_basic = page_probe.get("success", False)
        has_posts = posts_probe.get("success", False)
        has_insights = len(working_metrics) > 0

        scopes_detected = []
        if has_basic:
            scopes_detected.append("pages_show_list")
        if has_posts:
            scopes_detected.append("pages_read_engagement")
        if has_insights:
            scopes_detected.append("read_insights")

        access_level = "none"
        if has_basic:
            access_level = "basic"
        if has_basic and has_posts:
            access_level = "standard"
        if has_basic and has_posts and has_insights:
            access_level = "full"

        return jsonify({
            "success": True,
            "data": {
                "platform": PLATFORM_ID,
                "graph_version": GRAPH_VERSION,
                "destination_id": page_id,
                
                "probes": {
                    "token": token_probe,
                    "page_info": page_probe,
                    "posts_list": posts_probe,
                    "working_metrics": working_metrics,
                    "failed_metrics": failed_metrics,
                },
                
                "access_level": access_level,
                "scopes_detected": scopes_detected,
                
                "recommendation": (
                    "Full analytics access available!" if access_level == "full"
                    else "Standard access. Add read_insights permission for page analytics."
                    if access_level == "standard"
                    else "Basic access only. Add pages_read_engagement and read_insights permissions."
                    if access_level == "basic"
                    else "No access. Check token validity and permissions."
                ),
                
                "notes": [
                    "Many page metrics were deprecated Nov 2025 (New Pages Experience).",
                    "Use followers_count from page fields instead of page_fans metric.",
                    "Working metrics: page_post_engagements, page_posts_impressions, page_daily_follows_unique, page_video_views.",
                    "Rate limits apply: ~200 calls per hour per page.",
                ],
                
                "required_permissions": {
                    "basic": ["pages_show_list"],
                    "standard": ["pages_show_list", "pages_read_engagement"],
                    "full": ["pages_show_list", "pages_read_engagement", "read_insights"],
                },
                
                "available_page_metrics": sorted(list(VALID_PAGE_METRICS)),
                "available_post_metrics": sorted(list(VALID_POST_METRICS)),
                "deprecated_metrics": sorted(list(DEPRECATED_METRICS)),
                "default_page_metrics": DEFAULT_PAGE_METRICS,
                "default_post_metrics": DEFAULT_POST_METRICS,
            },
        }), HTTP_STATUS_CODES["OK"]
