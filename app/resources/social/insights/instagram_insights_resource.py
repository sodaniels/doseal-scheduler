# app/resources/social/instagram_insights.py

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

blp_instagram_insights = Blueprint(
    "instagram_insights",
    __name__,
)

# Use v21.0 - stable version
GRAPH_VERSION = "v21.0"


# -------------------------------------------------------------------
# Valid Metrics (Updated Feb 2025 - Post Jan 2025 Deprecation)
# -------------------------------------------------------------------
# IMPORTANT: As of January 8, 2025, Meta deprecated several metrics:
# - video_views (for non-Reels content)
# - email_contacts (time series)
# - profile_views (use views instead)
# - website_clicks
# - phone_call_clicks  
# - text_message_clicks
#
# New metrics added March 2025:
# - views (replaces impressions)
# - story_views
# - profile_views (new version)

# Account-level metrics (/{ig-user-id}/insights)
VALID_ACCOUNT_METRICS = {
    # Time series metrics (period: day, week, days_28)
    "reach",                    # Unique accounts that saw content
    "follower_count",           # Net new followers per day (last 30 days only)
    "views",                    # NEW - replaces impressions (March 2025)
    
    # Lifetime/demographic metrics (period: lifetime)
    "audience_gender_age",      # Gender and age distribution
    "audience_locale",          # Locale distribution  
    "audience_country",         # Country distribution
    "audience_city",            # City distribution
    "online_followers",         # When followers are online
}

# Media-level metrics (/{ig-media-id}/insights)
VALID_MEDIA_METRICS = {
    # All media types
    "reach",                    # Unique accounts that saw the media
    "saved",                    # Times saved
    "views",                    # NEW - replaces impressions
    "likes",                    # Like count
    "comments",                 # Comment count
    "shares",                   # Share count
    "total_interactions",       # Sum of all interactions
    
    # Video/Reel specific
    "plays",                    # Video plays
    "ig_reels_aggregated_all_plays_count",  # Reel plays
    "ig_reels_avg_watch_time",  # Average watch time
    "ig_reels_video_view_total_time",  # Total watch time
    
    # Story specific (within 24-48 hours)
    "exits",                    # Times exited story
    "replies",                  # Replies to story
    "taps_forward",             # Taps forward
    "taps_back",                # Taps back
}

# Deprecated metrics - DO NOT USE
DEPRECATED_METRICS = {
    "impressions",              # Replaced by views (March 2025)
    "video_views",              # Deprecated Jan 2025 (non-Reels)
    "email_contacts",           # Deprecated Jan 2025
    "website_clicks",           # Deprecated Jan 2025
    "phone_call_clicks",        # Deprecated Jan 2025
    "text_message_clicks",      # Deprecated Jan 2025
    "profile_views",            # Old version deprecated
    "carousel_album_impressions",  # Replaced by views
    "carousel_album_reach",     # Use reach
}

# Default account metrics - CONFIRMED WORKING as of Feb 2025
DEFAULT_ACCOUNT_METRICS = [
    "reach",
    "follower_count",
]

# Default media metrics
DEFAULT_MEDIA_METRICS = [
    "reach",
    "saved", 
    "likes",
    "comments",
    "shares",
    "total_interactions",
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

def _parse_ig_error(response_json: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Instagram/Graph API error response."""
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
# Account info
# -------------------------------

def _get_instagram_account_info(
    *, 
    ig_user_id: str, 
    access_token: str, 
    log_tag: str
) -> Dict[str, Any]:
    """
    Fetch basic Instagram account info using fields endpoint.
    """
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{ig_user_id}"

    params = {
        "fields": "id,username,name,profile_picture_url,followers_count,follows_count,media_count,biography,website",
        "access_token": access_token,
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        
        if r.status_code >= 400:
            Log.info(f"{log_tag} IG account info error: {r.status_code} {r.text}")
            error_data = r.json() if r.text else {}
            return {
                "success": False,
                "status_code": r.status_code,
                "error": _parse_ig_error(error_data),
            }

        data = r.json() or {}

        return {
            "success": True,
            "id": data.get("id"),
            "username": data.get("username"),
            "name": data.get("name"),
            "profile_picture_url": data.get("profile_picture_url"),
            "followers_count": data.get("followers_count"),
            "follows_count": data.get("follows_count"),
            "media_count": data.get("media_count"),
            "biography": data.get("biography"),
            "website": data.get("website"),
            "raw": data,
        }
        
    except requests.exceptions.Timeout:
        Log.error(f"{log_tag} IG account info timeout")
        return {
            "success": False,
            "status_code": 408,
            "error": {"message": "Request timeout"},
        }
    except requests.exceptions.RequestException as e:
        Log.error(f"{log_tag} IG account info request error: {e}")
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


def _merge_series(series_list: List[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Merge responses into one timeline, removing duplicates."""
    merged: Dict[str, Any] = {}

    for series in series_list:
        for row in series or []:
            et = row.get("end_time")
            if et:
                merged[et] = row.get("value")

    return [
        {"end_time": k, "value": merged[k]}
        for k in sorted(merged.keys())
    ]


# -------------------------------
# Account insights fetching
# -------------------------------

def _fetch_account_insights(
    *,
    ig_user_id: str,
    access_token: str,
    metrics: List[str],
    period: str,
    since: Optional[str],
    until: Optional[str],
    log_tag: str,
) -> Dict[str, Any]:
    """
    Fetch Instagram account-level insights.
    
    Note: follower_count only available for last 30 days.
    Note: Accounts with <100 followers may have limited data.
    """
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{ig_user_id}/insights"
    
    valid_metrics: List[str] = []
    invalid_metrics: List[Dict[str, Any]] = []
    all_metrics: Dict[str, List[Dict[str, Any]]] = {}
    deprecated_found: List[str] = []
    
    
    # De-duplicate metrics
    seen = set()
    uniq_metrics = []
    for m in metrics:
        m2 = (m or "").strip()
        if m2 and m2 not in seen:
            seen.add(m2)
            uniq_metrics.append(m2)
    
    # Instagram API allows multiple metrics in one call
    # But we fetch individually for better error handling
    for metric in uniq_metrics:
        params = {
            "metric": metric,
            "period": period,
            "access_token": access_token,
        }
        
        # Add date range for time-series metrics
        if period in {"day", "week", "days_28"} and since and until:
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
                parsed_error = _parse_ig_error(error_data)
                
                invalid_metrics.append({
                    "metric": metric,
                    "status_code": r.status_code,
                    "error": parsed_error,
                })
                
                if _is_invalid_metric_error(parsed_error):
                    deprecated_found.append(metric)
                    Log.info(f"{log_tag} Metric '{metric}' is invalid or deprecated")
                    
                continue
            
            payload = r.json() or {}
            series = _series_from_insights_payload(payload, metric)
            
            if series:
                all_metrics[metric] = series
                valid_metrics.append(metric)
            else:
                # Empty data - might be valid metric but no data
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
            # For demographic data, skip summary
            return {"type": "demographic", "count": len(series)}
    
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
# INSTAGRAM ACCOUNT INSIGHTS — Main Endpoint
# -------------------------------------------------------------------

@blp_instagram_insights.route("/social/instagram/account-insights", methods=["GET"])
class InstagramAccountInsightsResource(MethodView):
    """
    Instagram account-level analytics using stored SocialAccount token.

    Query params:
      - destination_id (required): Instagram Business/Creator Account ID
      - since (YYYY-MM-DD): Start date for insights
      - until (YYYY-MM-DD): End date for insights  
      - period: day | week | days_28 | lifetime (default: day)
      - metrics: comma-separated list of metrics (optional)
      - debug: if "true", includes token debug info
      
    IMPORTANT: As of Jan 2025, several metrics are deprecated:
      - impressions -> use "views" instead
      - video_views -> deprecated for non-Reels
      - website_clicks, phone_call_clicks, etc -> deprecated
      
    Working metrics (Feb 2025):
      - reach: Unique accounts that saw content
      - follower_count: Net new followers per day (last 30 days only)
      
    Lifetime metrics (period=lifetime):
      - audience_gender_age: Gender and age distribution
      - audience_country: Country distribution
      - audience_city: City distribution
      
    Required token permissions:
      - instagram_basic
      - instagram_manage_insights (or read_insights)
      - pages_read_engagement
      
    Note: Accounts with <100 followers have limited data access.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[instagram_insights][account][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Parse query parameters
        ig_user_id = (request.args.get("destination_id") or "").strip()
        since = (request.args.get("since") or "").strip() or None
        until = (request.args.get("until") or "").strip() or None
        period = (request.args.get("period") or "day").lower().strip()
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        # Validate required parameters
        if not ig_user_id:
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
            platform="instagram",
            destination_id=ig_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "IG_NOT_CONNECTED",
                "message": "Instagram account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "IG_TOKEN_MISSING",
                "message": "Reconnect Instagram - no access token found",
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
            # Use appropriate defaults based on period
            if period == "lifetime":
                requested_metrics = ["audience_gender_age", "audience_country", "audience_city"]
            else:
                requested_metrics = DEFAULT_ACCOUNT_METRICS.copy()

        # --------------------------------------------------
        # Fetch account info
        # --------------------------------------------------

        account_info = _get_instagram_account_info(
            ig_user_id=ig_user_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        # Check for token errors early
        if not account_info.get("success"):
            error = account_info.get("error", {})
            error_code = error.get("code")
            
            if error_code == 190:
                return jsonify({
                    "success": False,
                    "code": "IG_TOKEN_EXPIRED",
                    "message": "Instagram access token has expired. Please reconnect.",
                    "debug": token_info if debug_mode else None,
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            elif error_code in [10, 200, 210]:
                return jsonify({
                    "success": False,
                    "code": "IG_PERMISSION_DENIED",
                    "message": "Missing permissions. Token needs: instagram_basic, read_insights",
                    "debug": token_info if debug_mode else None,
                }), HTTP_STATUS_CODES["FORBIDDEN"]

        # --------------------------------------------------
        # Fetch insights
        # --------------------------------------------------

        insights = _fetch_account_insights(
            ig_user_id=ig_user_id,
            access_token=access_token,
            metrics=requested_metrics,
            period=period,
            since=since,
            until=until,
            log_tag=log_tag,
        )

        # Check if ALL metrics failed
        deprecated_found = insights.get("deprecated_metrics", [])
        if deprecated_found and not insights.get("valid_metrics"):
            return jsonify({
                "success": False,
                "code": "IG_METRICS_DEPRECATED",
                "message": (
                    f"All requested metrics are deprecated or invalid. "
                    f"Deprecated: {deprecated_found}. "
                    f"Use these instead: {DEFAULT_ACCOUNT_METRICS}"
                ),
                "suggested_metrics": DEFAULT_ACCOUNT_METRICS,
                "account_info": {
                    "username": _pick(account_info, "username"),
                    "followers_count": _pick(account_info, "followers_count"),
                },
                "debug": token_info if debug_mode else None,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Calculate summaries
        summaries = {}
        for metric_name, series in insights.get("metrics", {}).items():
            summaries[metric_name] = _calculate_metric_summary(series)

        # Build response
        result = {
            "platform": "instagram",
            "graph_version": GRAPH_VERSION,
            "destination_id": ig_user_id,
            "username": _pick(account_info, "username"),
            "period": period,
            "since": since,
            "until": until,
            "requested_metrics": requested_metrics,

            "account_info": {
                "id": _pick(account_info, "id"),
                "username": _pick(account_info, "username"),
                "name": _pick(account_info, "name"),
                "followers_count": _pick(account_info, "followers_count"),
                "follows_count": _pick(account_info, "follows_count"),
                "media_count": _pick(account_info, "media_count"),
                "profile_picture_url": _pick(account_info, "profile_picture_url"),
                "info_error": None if account_info.get("success") else account_info.get("error"),
            },

            "summaries": summaries,
            "valid_metrics": insights.get("valid_metrics"),
            "invalid_metrics": insights.get("invalid_metrics"),
            "deprecated_metrics": insights.get("deprecated_metrics"),
            "metrics": insights.get("metrics"),
        }
        
        # Add debug info if requested
        if debug_mode:
            result["debug"] = {
                "token_info": token_info,
                "available_account_metrics": sorted(list(VALID_ACCOUNT_METRICS)),
                "deprecated_metrics": sorted(list(DEPRECATED_METRICS)),
            }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# INSTAGRAM MEDIA INSIGHTS — Get insights for a specific post
# -------------------------------------------------------------------

@blp_instagram_insights.route("/social/instagram/media-insights", methods=["GET"])
class InstagramMediaInsightsResource(MethodView):
    """
    Instagram media-level analytics for a specific post.

    Query params:
      - destination_id (required): Instagram Business/Creator Account ID
      - media_id (required): Instagram Media ID
      - metrics: comma-separated list of metrics (optional)
      - debug: if "true", includes token debug info
      
    Working metrics (Feb 2025):
      - reach: Unique accounts that saw the media
      - saved: Times saved
      - likes: Like count
      - comments: Comment count  
      - shares: Share count
      - total_interactions: Sum of all interactions
      
    For Reels:
      - plays: Video plays
      - ig_reels_avg_watch_time: Average watch time
      
    For Stories (within 24-48 hours):
      - exits, replies, taps_forward, taps_back
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[instagram_insights][media][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Parse query parameters
        ig_user_id = (request.args.get("destination_id") or "").strip()
        media_id = (request.args.get("media_id") or "").strip()
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        if not ig_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        if not media_id:
            return jsonify({
                "success": False,
                "message": "media_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="instagram",
            destination_id=ig_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "IG_NOT_CONNECTED",
                "message": "Instagram account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "IG_TOKEN_MISSING",
                "message": "Reconnect Instagram - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Parse requested metrics or use defaults
        metrics_qs = (request.args.get("metrics") or "").strip()
        requested_metrics = (
            [m.strip() for m in metrics_qs.split(",") if m.strip()]
            if metrics_qs
            else DEFAULT_MEDIA_METRICS.copy()
        )

        # Fetch media insights
        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{media_id}/insights"
        params = {
            "metric": ",".join(requested_metrics),
            "access_token": access_token,
        }

        try:
            r = requests.get(url, params=params, timeout=30)
            
            if r.status_code >= 400:
                error_data = r.json() if r.text else {}
                parsed_error = _parse_ig_error(error_data)
                
                return jsonify({
                    "success": False,
                    "code": "IG_MEDIA_INSIGHTS_ERROR",
                    "message": parsed_error.get("message", "Failed to fetch media insights"),
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
                "platform": "instagram",
                "graph_version": GRAPH_VERSION,
                "media_id": media_id,
                "requested_metrics": requested_metrics,
                "metrics": metrics_data,
            }
            
            if debug_mode:
                result["debug"] = {
                    "available_media_metrics": sorted(list(VALID_MEDIA_METRICS)),
                }
            
            return jsonify({
                "success": True,
                "data": result,
            }), HTTP_STATUS_CODES["OK"]
            
        except requests.exceptions.RequestException as e:
            Log.error(f"{log_tag} Media insights error: {e}")
            return jsonify({
                "success": False,
                "message": f"Request failed: {str(e)}",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# INSTAGRAM MEDIA LIST — Get all media for an account
# -------------------------------------------------------------------

@blp_instagram_insights.route("/social/instagram/media-list", methods=["GET"])
class InstagramMediaListResource(MethodView):
    """
    Get list of media (posts) for an Instagram account.

    Query params:
      - destination_id (required): Instagram Business/Creator Account ID
      - limit: Number of posts to return (default: 25, max: 100)
      - after: Pagination cursor for next page
      - before: Pagination cursor for previous page
      - fields: Comma-separated fields (optional, has defaults)
      
    Default fields returned:
      - id, caption, media_type, timestamp
      - like_count, comments_count
      - permalink, media_url, thumbnail_url
      
    Media types:
      - IMAGE: Single image post
      - VIDEO: Single video post  
      - CAROUSEL_ALBUM: Multiple images/videos
      - REELS: Instagram Reel
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[instagram_insights][media_list][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Parse query parameters
        ig_user_id = (request.args.get("destination_id") or "").strip()
        limit = request.args.get("limit", "25").strip()
        after_cursor = (request.args.get("after") or "").strip() or None
        before_cursor = (request.args.get("before") or "").strip() or None
        fields_qs = (request.args.get("fields") or "").strip()

        # Validate required parameters
        if not ig_user_id:
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
            "caption",
            "media_type",
            "media_product_type",
            "timestamp",
            "like_count",
            "comments_count",
            "permalink",
            "media_url",
            "thumbnail_url",
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
            platform="instagram",
            destination_id=ig_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "IG_NOT_CONNECTED",
                "message": "Instagram account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "IG_TOKEN_MISSING",
                "message": "Reconnect Instagram - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # --------------------------------------------------
        # Fetch media list from Instagram API
        # --------------------------------------------------

        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{ig_user_id}/media"
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
                parsed_error = _parse_ig_error(error_data)
                
                error_code = parsed_error.get("code")
                
                if error_code == 190:
                    return jsonify({
                        "success": False,
                        "code": "IG_TOKEN_EXPIRED",
                        "message": "Instagram access token has expired. Please reconnect.",
                    }), HTTP_STATUS_CODES["UNAUTHORIZED"]
                elif error_code in [10, 200, 210]:
                    return jsonify({
                        "success": False,
                        "code": "IG_PERMISSION_DENIED",
                        "message": "Missing permissions. Token needs: instagram_basic",
                    }), HTTP_STATUS_CODES["FORBIDDEN"]
                
                return jsonify({
                    "success": False,
                    "code": "IG_MEDIA_LIST_ERROR",
                    "message": parsed_error.get("message", "Failed to fetch media list"),
                    "error": parsed_error,
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            payload = r.json() or {}
            media_list = payload.get("data", [])
            paging = payload.get("paging", {})
            
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
                "platform": "instagram",
                "graph_version": GRAPH_VERSION,
                "destination_id": ig_user_id,
                "count": len(media_list),
                "limit": limit,
                "media": media_list,
                "pagination": pagination,
            }
            
            return jsonify({
                "success": True,
                "data": result,
            }), HTTP_STATUS_CODES["OK"]
            
        except requests.exceptions.Timeout:
            Log.error(f"{log_tag} Media list timeout")
            return jsonify({
                "success": False,
                "message": "Request timeout",
            }), HTTP_STATUS_CODES["GATEWAY_TIMEOUT"]
        except requests.exceptions.RequestException as e:
            Log.error(f"{log_tag} Media list error: {e}")
            return jsonify({
                "success": False,
                "message": f"Request failed: {str(e)}",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# INSTAGRAM MEDIA DETAILS — Get details for a specific media
# -------------------------------------------------------------------

@blp_instagram_insights.route("/social/instagram/media-details", methods=["GET"])
class InstagramMediaDetailsResource(MethodView):
    """
    Get detailed information for a specific Instagram media item.

    Query params:
      - destination_id (required): Instagram Business/Creator Account ID
      - media_id (required): Instagram Media ID
      - fields: Comma-separated fields (optional, has defaults)
      
    Returns full media details including children for carousels.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[instagram_insights][media_details][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Parse query parameters
        ig_user_id = (request.args.get("destination_id") or "").strip()
        media_id = (request.args.get("media_id") or "").strip()
        fields_qs = (request.args.get("fields") or "").strip()

        if not ig_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        if not media_id:
            return jsonify({
                "success": False,
                "message": "media_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Default fields
        default_fields = [
            "id",
            "caption",
            "media_type",
            "media_product_type",
            "timestamp",
            "like_count",
            "comments_count",
            "permalink",
            "media_url",
            "thumbnail_url",
            "children{id,media_type,media_url,thumbnail_url}",
        ]
        
        if fields_qs:
            fields = [f.strip() for f in fields_qs.split(",") if f.strip()]
        else:
            fields = default_fields

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="instagram",
            destination_id=ig_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "IG_NOT_CONNECTED",
                "message": "Instagram account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "IG_TOKEN_MISSING",
                "message": "Reconnect Instagram - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch media details
        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{media_id}"
        params = {
            "fields": ",".join(fields),
            "access_token": access_token,
        }

        try:
            r = requests.get(url, params=params, timeout=30)
            
            if r.status_code >= 400:
                error_data = r.json() if r.text else {}
                parsed_error = _parse_ig_error(error_data)
                
                return jsonify({
                    "success": False,
                    "code": "IG_MEDIA_DETAILS_ERROR",
                    "message": parsed_error.get("message", "Failed to fetch media details"),
                    "error": parsed_error,
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            media_data = r.json() or {}
            
            # Process children if present (for carousels)
            if "children" in media_data and "data" in media_data["children"]:
                media_data["children"] = media_data["children"]["data"]
            
            result = {
                "platform": "instagram",
                "graph_version": GRAPH_VERSION,
                "media": media_data,
            }
            
            return jsonify({
                "success": True,
                "data": result,
            }), HTTP_STATUS_CODES["OK"]
            
        except requests.exceptions.RequestException as e:
            Log.error(f"{log_tag} Media details error: {e}")
            return jsonify({
                "success": False,
                "message": f"Request failed: {str(e)}",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]



