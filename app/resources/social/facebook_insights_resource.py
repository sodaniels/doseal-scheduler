# app/resources/social/facebook_insights.py

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import g, jsonify, request
from flask.views import MethodView
from flask_smorest import Blueprint

from ...constants.service_code import HTTP_STATUS_CODES
from ...models.social.social_account import SocialAccount
from ...utils.logger import Log
from ..doseal.admin.admin_business_resource import token_required


# -------------------------------------------------------------------
# Blueprint
# -------------------------------------------------------------------

blp_meta_impression = Blueprint(
    "facebook_insights",
    __name__,
)

# Use v21.0 - stable version
GRAPH_VERSION = "v21.0"


# -------------------------------------------------------------------
# Valid Metrics (Updated Feb 2025 - Post Nov 2025 Deprecation)
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


def _is_invalid_metric_error(error: Dict[str, Any]) -> bool:
    """Check if error is about invalid metric."""
    code = error.get("code")
    message = str(error.get("message", "")).lower()
    return code == 100 and ("invalid" in message or "metric" in message)


def _is_permission_error(error: Dict[str, Any]) -> bool:
    """Check if error is about missing permissions."""
    code = error.get("code")
    return code in [10, 200, 210]


# -------------------------------
# Token validation
# -------------------------------

def _debug_token(access_token: str, log_tag: str) -> Dict[str, Any]:
    """Debug token to check permissions and validity."""
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/debug_token"
    params = {
        "input_token": access_token,
        "access_token": access_token,
    }
    
    try:
        r = requests.get(url, params=params, timeout=15)
        
        if r.status_code >= 400:
            return {
                "valid": False,
                "error": "Token debug request failed",
                "status_code": r.status_code,
            }
        
        data = r.json().get("data", {})
        
        return {
            "valid": data.get("is_valid", False),
            "app_id": data.get("app_id"),
            "type": data.get("type"),
            "expires_at": data.get("expires_at"),
            "data_access_expires_at": data.get("data_access_expires_at"),
            "scopes": data.get("scopes", []),
            "granular_scopes": data.get("granular_scopes", []),
        }
        
    except Exception as e:
        Log.error(f"{log_tag} Token debug error: {e}")
        return {
            "valid": False,
            "error": str(e),
        }


# -------------------------------
# Page info
# -------------------------------

def _get_facebook_page_info(
    *, 
    page_id: str, 
    access_token: str, 
    log_tag: str
) -> Dict[str, Any]:
    """
    Fetch basic Facebook page info using fields endpoint.
    """
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}"

    params = {
        "fields": "id,name,username,followers_count,fan_count,link,picture,category,about,website",
        "access_token": access_token,
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        
        if r.status_code >= 400:
            Log.info(f"{log_tag} FB page info error: {r.status_code} {r.text}")
            error_data = r.json() if r.text else {}
            return {
                "success": False,
                "status_code": r.status_code,
                "error": _parse_fb_error(error_data),
            }

        data = r.json() or {}

        return {
            "success": True,
            "id": data.get("id"),
            "name": data.get("name"),
            "username": data.get("username"),
            "followers_count": data.get("followers_count"),
            "fan_count": data.get("fan_count"),
            "link": data.get("link"),
            "picture": data.get("picture", {}).get("data", {}).get("url") if isinstance(data.get("picture"), dict) else None,
            "category": data.get("category"),
            "about": data.get("about"),
            "website": data.get("website"),
            "raw": data,
        }
        
    except requests.exceptions.Timeout:
        Log.error(f"{log_tag} FB page info timeout")
        return {
            "success": False,
            "status_code": 408,
            "error": {"message": "Request timeout"},
        }
    except requests.exceptions.RequestException as e:
        Log.error(f"{log_tag} FB page info request error: {e}")
        return {
            "success": False,
            "status_code": 500,
            "error": {"message": str(e)},
        }


# -------------------------------
# Insights parsing
# -------------------------------

def _series_from_insights_payload(
    payload: Dict[str, Any], 
    metric_name: str
) -> List[Dict[str, Any]]:
    """Extract time series data for a specific metric from API response."""
    data = (payload or {}).get("data") or []
    
    item = None
    for x in data:
        name = x.get("name", "")
        if name == metric_name or name.startswith(f"{metric_name}/"):
            item = x
            break
    
    if not item:
        return []
    
    values = item.get("values") or []
    out: List[Dict[str, Any]] = []
    
    for v in values or []:
        out.append({
            "end_time": v.get("end_time"),
            "value": v.get("value"),
        })

    return out


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
    """
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/insights"
    
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
    
    # Fetch metrics individually for better error handling
    for metric in uniq_metrics:
        params = {
            "metric": metric,
            "period": period,
            "access_token": access_token,
        }
        
        # Add date range
        if since and until:
            since_dt = _parse_ymd(since)
            until_dt = _parse_ymd(until)
            if since_dt:
                params["since"] = _to_unix_timestamp(since_dt)
            if until_dt:
                params["until"] = _to_unix_timestamp(until_dt + timedelta(days=1))
        
        try:
            r = requests.get(url, params=params, timeout=30)
            
            if r.status_code >= 400:
                error_data = r.json() if r.text else {}
                parsed_error = _parse_fb_error(error_data)
                
                invalid_metrics.append({
                    "metric": metric,
                    "status_code": r.status_code,
                    "error": parsed_error,
                })
                
                if _is_invalid_metric_error(parsed_error):
                    deprecated_found.append(metric)
                    Log.info(f"{log_tag} Metric '{metric}' is invalid or deprecated")
                elif _is_permission_error(parsed_error):
                    permission_errors.append(metric)
                    Log.info(f"{log_tag} Metric '{metric}' requires additional permissions")
                    
                continue
            
            payload = r.json() or {}
            series = _series_from_insights_payload(payload, metric)
            
            if series:
                all_metrics[metric] = series
                valid_metrics.append(metric)
            else:
                invalid_metrics.append({
                    "metric": metric,
                    "status_code": 200,
                    "error": {"message": "No data returned"},
                })
                
        except requests.exceptions.Timeout:
            invalid_metrics.append({
                "metric": metric,
                "status_code": 408,
                "error": {"message": "Request timeout"},
            })
        except requests.exceptions.RequestException as e:
            invalid_metrics.append({
                "metric": metric,
                "status_code": 500,
                "error": {"message": str(e)},
            })
    
    return {
        "valid_metrics": valid_metrics,
        "invalid_metrics": invalid_metrics,
        "deprecated_metrics": list(set(deprecated_found)),
        "permission_errors": list(set(permission_errors)),
        "metrics": all_metrics,
    }


# -------------------------------
# Summary calculations
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
            return {"type": "breakdown", "count": len(series)}
    
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
        log_tag = f"[facebook_insights][page][{client_ip}]"

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
        valid_periods = {"day", "week", "days_28", "lifetime"}
        if period not in valid_periods:
            return jsonify({
                "success": False,
                "message": f"Invalid period. Must be one of: {', '.join(valid_periods)}",
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

        # Default to last 30 days if no dates provided
        if not since or not until:
            since, until = _get_date_range_last_n_days(30)

        # --------------------------------------------------
        # Load stored SocialAccount
        # --------------------------------------------------

        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="facebook",
            destination_id=page_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "FB_NOT_CONNECTED",
                "message": "Facebook page not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain")
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

        # Parse requested metrics or use defaults
        metrics_qs = (request.args.get("metrics") or "").strip()
        
        if metrics_qs:
            requested_metrics = [m.strip() for m in metrics_qs.split(",") if m.strip()]
        else:
            requested_metrics = DEFAULT_PAGE_METRICS.copy()

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
            error_code = error.get("code")
            
            if error_code == 190:
                return jsonify({
                    "success": False,
                    "code": "FB_TOKEN_EXPIRED",
                    "message": "Facebook access token has expired. Please reconnect.",
                    "debug": token_info if debug_mode else None,
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            elif error_code in [10, 200, 210]:
                return jsonify({
                    "success": False,
                    "code": "FB_PERMISSION_DENIED",
                    "message": "Missing permissions. Token needs: pages_read_engagement, read_insights",
                    "debug": token_info if debug_mode else None,
                }), HTTP_STATUS_CODES["FORBIDDEN"]

        # --------------------------------------------------
        # Fetch insights
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
                "message": (
                    f"Missing permission 'read_insights'. "
                    f"Please reconnect Facebook with updated permissions."
                ),
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
                "message": (
                    f"All requested metrics are invalid. "
                    f"Invalid metrics: {deprecated_found}. "
                    f"Use these instead: {DEFAULT_PAGE_METRICS}"
                ),
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
            "platform": "facebook",
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
        
        # Add debug info if requested
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
      - debug: if "true", includes token debug info
      
    Working metrics (Feb 2025):
      - post_impressions: Times post was shown
      - post_impressions_unique: Unique accounts reached
      - post_engaged_users: Users who engaged
      - post_clicks: Total clicks
      - post_reactions_by_type_total: Reactions breakdown
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_insights][post][{client_ip}]"

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

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="facebook",
            destination_id=page_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "FB_NOT_CONNECTED",
                "message": "Facebook page not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "FB_TOKEN_MISSING",
                "message": "Reconnect Facebook - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Parse requested metrics or use defaults
        metrics_qs = (request.args.get("metrics") or "").strip()
        requested_metrics = (
            [m.strip() for m in metrics_qs.split(",") if m.strip()]
            if metrics_qs
            else DEFAULT_POST_METRICS.copy()
        )

        # Fetch post insights
        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{post_id}/insights"
        params = {
            "metric": ",".join(requested_metrics),
            "access_token": access_token,
        }

        try:
            r = requests.get(url, params=params, timeout=30)
            
            if r.status_code >= 400:
                error_data = r.json() if r.text else {}
                parsed_error = _parse_fb_error(error_data)
                
                return jsonify({
                    "success": False,
                    "code": "FB_POST_INSIGHTS_ERROR",
                    "message": parsed_error.get("message", "Failed to fetch post insights"),
                    "error": parsed_error,
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            payload = r.json() or {}
            data = payload.get("data", [])
            
            # Parse metrics from response
            metrics_data = {}
            for item in data:
                name = item.get("name")
                values = item.get("values", [])
                if values:
                    metrics_data[name] = values[0].get("value")
            
            result = {
                "platform": "facebook",
                "graph_version": GRAPH_VERSION,
                "post_id": post_id,
                "requested_metrics": requested_metrics,
                "metrics": metrics_data,
            }
            
            if debug_mode:
                result["debug"] = {
                    "available_post_metrics": sorted(list(VALID_POST_METRICS)),
                }
            
            return jsonify({
                "success": True,
                "data": result,
            }), HTTP_STATUS_CODES["OK"]
            
        except requests.exceptions.RequestException as e:
            Log.error(f"{log_tag} Post insights error: {e}")
            return jsonify({
                "success": False,
                "message": f"Request failed: {str(e)}",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


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
      - fields: Comma-separated fields (optional, has defaults)
      
    Default fields returned:
      - id, message, created_time, updated_time
      - permalink_url, full_picture
      - shares, reactions.summary(true), comments.summary(true)
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_insights][post_list][{client_ip}]"

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
        limit = request.args.get("limit", "25").strip()
        after_cursor = (request.args.get("after") or "").strip() or None
        before_cursor = (request.args.get("before") or "").strip() or None
        fields_qs = (request.args.get("fields") or "").strip()

        # Validate required parameters
        if not page_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Validate and cap limit
        try:
            limit = min(int(limit), 100)
            if limit < 1:
                limit = 25
        except ValueError:
            limit = 25

        # Default fields if not specified
        default_fields = [
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
        
        if fields_qs:
            fields = [f.strip() for f in fields_qs.split(",") if f.strip()]
        else:
            fields = default_fields

        # --------------------------------------------------
        # Load stored SocialAccount
        # --------------------------------------------------

        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="facebook",
            destination_id=page_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "FB_NOT_CONNECTED",
                "message": "Facebook page not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "FB_TOKEN_MISSING",
                "message": "Reconnect Facebook - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # --------------------------------------------------
        # Fetch post list from Facebook API
        # --------------------------------------------------

        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/posts"
        params = {
            "fields": ",".join(fields),
            "limit": limit,
            "access_token": access_token,
        }
        
        # Add pagination cursors if provided
        if after_cursor:
            params["after"] = after_cursor
        if before_cursor:
            params["before"] = before_cursor

        try:
            r = requests.get(url, params=params, timeout=30)
            
            if r.status_code >= 400:
                error_data = r.json() if r.text else {}
                parsed_error = _parse_fb_error(error_data)
                
                error_code = parsed_error.get("code")
                
                if error_code == 190:
                    return jsonify({
                        "success": False,
                        "code": "FB_TOKEN_EXPIRED",
                        "message": "Facebook access token has expired. Please reconnect.",
                    }), HTTP_STATUS_CODES["UNAUTHORIZED"]
                elif error_code in [10, 200, 210]:
                    return jsonify({
                        "success": False,
                        "code": "FB_PERMISSION_DENIED",
                        "message": "Missing permissions. Token needs: pages_read_engagement",
                    }), HTTP_STATUS_CODES["FORBIDDEN"]
                
                return jsonify({
                    "success": False,
                    "code": "FB_POST_LIST_ERROR",
                    "message": parsed_error.get("message", "Failed to fetch post list"),
                    "error": parsed_error,
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            payload = r.json() or {}
            post_list = payload.get("data", [])
            paging = payload.get("paging", {})
            
            # Process posts to flatten nested data
            processed_posts = []
            for post in post_list:
                processed = {**post}
                
                # Flatten reactions summary
                if "reactions" in processed and isinstance(processed["reactions"], dict):
                    processed["reactions_count"] = processed["reactions"].get("summary", {}).get("total_count", 0)
                    del processed["reactions"]
                
                # Flatten comments summary
                if "comments" in processed and isinstance(processed["comments"], dict):
                    processed["comments_count"] = processed["comments"].get("summary", {}).get("total_count", 0)
                    del processed["comments"]
                
                # Flatten shares
                if "shares" in processed and isinstance(processed["shares"], dict):
                    processed["shares_count"] = processed["shares"].get("count", 0)
                    del processed["shares"]
                
                processed_posts.append(processed)
            
            # Extract pagination info
            cursors = paging.get("cursors", {})
            pagination = {
                "has_next": "next" in paging,
                "has_previous": "previous" in paging,
                "after": cursors.get("after"),
                "before": cursors.get("before"),
            }
            
            # Build response
            result = {
                "platform": "facebook",
                "graph_version": GRAPH_VERSION,
                "destination_id": page_id,
                "count": len(processed_posts),
                "limit": limit,
                "posts": processed_posts,
                "pagination": pagination,
            }
            
            return jsonify({
                "success": True,
                "data": result,
            }), HTTP_STATUS_CODES["OK"]
            
        except requests.exceptions.Timeout:
            Log.error(f"{log_tag} Post list timeout")
            return jsonify({
                "success": False,
                "message": "Request timeout",
            }), HTTP_STATUS_CODES["GATEWAY_TIMEOUT"]
        except requests.exceptions.RequestException as e:
            Log.error(f"{log_tag} Post list error: {e}")
            return jsonify({
                "success": False,
                "message": f"Request failed: {str(e)}",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


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
      - fields: Comma-separated fields (optional, has defaults)
      
    Returns full post details including attachments.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_insights][post_details][{client_ip}]"

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
        fields_qs = (request.args.get("fields") or "").strip()

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

        # Default fields
        default_fields = [
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
        
        if fields_qs:
            fields = [f.strip() for f in fields_qs.split(",") if f.strip()]
        else:
            fields = default_fields

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="facebook",
            destination_id=page_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "FB_NOT_CONNECTED",
                "message": "Facebook page not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "FB_TOKEN_MISSING",
                "message": "Reconnect Facebook - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch post details
        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{post_id}"
        params = {
            "fields": ",".join(fields),
            "access_token": access_token,
        }

        try:
            r = requests.get(url, params=params, timeout=30)
            
            if r.status_code >= 400:
                error_data = r.json() if r.text else {}
                parsed_error = _parse_fb_error(error_data)
                
                return jsonify({
                    "success": False,
                    "code": "FB_POST_DETAILS_ERROR",
                    "message": parsed_error.get("message", "Failed to fetch post details"),
                    "error": parsed_error,
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            post_data = r.json() or {}
            
            # Flatten nested data
            if "reactions" in post_data and isinstance(post_data["reactions"], dict):
                post_data["reactions_count"] = post_data["reactions"].get("summary", {}).get("total_count", 0)
                del post_data["reactions"]
            
            if "comments" in post_data and isinstance(post_data["comments"], dict):
                post_data["comments_count"] = post_data["comments"].get("summary", {}).get("total_count", 0)
                del post_data["comments"]
            
            if "shares" in post_data and isinstance(post_data["shares"], dict):
                post_data["shares_count"] = post_data["shares"].get("count", 0)
                del post_data["shares"]
            
            # Process attachments
            if "attachments" in post_data and "data" in post_data["attachments"]:
                post_data["attachments"] = post_data["attachments"]["data"]
            
            result = {
                "platform": "facebook",
                "graph_version": GRAPH_VERSION,
                "post": post_data,
            }
            
            return jsonify({
                "success": True,
                "data": result,
            }), HTTP_STATUS_CODES["OK"]
            
        except requests.exceptions.RequestException as e:
            Log.error(f"{log_tag} Post details error: {e}")
            return jsonify({
                "success": False,
                "message": f"Request failed: {str(e)}",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# FACEBOOK DISCOVER METRICS — Test which metrics work
# -------------------------------------------------------------------

@blp_meta_impression.route("/social/facebook/discover-metrics", methods=["GET"])
class FacebookDiscoverMetricsResource(MethodView):
    """
    Test endpoint to discover which Facebook metrics work with current token.
    
    Query params:
      - destination_id (required): Facebook Page ID
      
    This will test all known metrics and return which ones work.
    Useful for debugging permission issues.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_insights][discover][{client_ip}]"

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
            platform="facebook",
            destination_id=page_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "FB_NOT_CONNECTED",
                "message": "Facebook page not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "FB_TOKEN_MISSING",
                "message": "Reconnect Facebook - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Debug token first
        token_info = _debug_token(access_token, log_tag)
        
        # Get page info
        page_info = _get_facebook_page_info(
            page_id=page_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        # Test metrics (including deprecated ones to confirm status)
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
        
        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/insights"
        since, until = _get_date_range_last_n_days(7)
        since_ts = _to_unix_timestamp(_parse_ymd(since))
        until_ts = _to_unix_timestamp(_parse_ymd(until) + timedelta(days=1))
        
        working_metrics = []
        failed_metrics = []
        
        for metric in test_metrics:
            params = {
                "metric": metric,
                "period": "day",
                "since": since_ts,
                "until": until_ts,
                "access_token": access_token,
            }
            
            try:
                r = requests.get(url, params=params, timeout=15)
                
                if r.status_code < 400:
                    payload = r.json() or {}
                    data = payload.get("data", [])
                    if data:
                        working_metrics.append({
                            "metric": metric,
                            "has_data": True,
                            "sample_count": len(data[0].get("values", [])) if data else 0,
                        })
                    else:
                        working_metrics.append({
                            "metric": metric,
                            "has_data": False,
                            "note": "Metric valid but no data returned",
                        })
                else:
                    error_data = r.json() if r.text else {}
                    parsed_error = _parse_fb_error(error_data)
                    failed_metrics.append({
                        "metric": metric,
                        "status_code": r.status_code,
                        "error": parsed_error.get("message"),
                        "error_code": parsed_error.get("code"),
                    })
                    
            except Exception as e:
                failed_metrics.append({
                    "metric": metric,
                    "error": str(e),
                })

        return jsonify({
            "success": True,
            "data": {
                "destination_id": page_id,
                "page_name": _pick(page_info, "name"),
                "followers_count": _pick(page_info, "followers_count"),
                "token_info": {
                    "valid": token_info.get("valid"),
                    "scopes": token_info.get("scopes", []),
                    "has_insights_permission": "read_insights" in token_info.get("scopes", []),
                },
                "working_metrics": working_metrics,
                "failed_metrics": failed_metrics,
                "recommendation": (
                    "All core metrics working!" if len(working_metrics) >= 4 
                    else "Reconnect Facebook with 'read_insights' permission"
                ),
            },
        }), HTTP_STATUS_CODES["OK"]
        
