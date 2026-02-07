# app/resources/social/pinterest_insights_resource.py
#
# Pinterest analytics using STORED SocialAccount token
#
# Pinterest API v5:
# - User account analytics
# - Pin analytics
# - Board analytics
# - Audience insights (Business accounts)
#
# What you can get:
# - Account metrics: followers, following, pins count
# - Pin metrics: impressions, saves, clicks, comments
# - Board metrics: followers, pins count
# - Audience demographics (Business accounts only)
#
# Key limitations:
# - Analytics require Pinterest Business account
# - Some metrics require ads:read scope
# - Data may have 24-48 hour delay
# - Rate limits: 1000 requests per minute

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

blp_pinterest_insights = Blueprint(
    "pinterest_insights",
    __name__,
)

# Pinterest API v5
API_VERSION = "v5"
PINTEREST_API_BASE = f"https://api.pinterest.com/{API_VERSION}"

# Platform identifier
PLATFORM_ID = "pinterest"


# -------------------------------------------------------------------
# Valid Metrics Reference (Pinterest API v5)
# -------------------------------------------------------------------
# User Account Analytics (GET /user_account/analytics):
#   - IMPRESSION: Number of times pins were shown
#   - PIN_CLICK: Number of clicks on pins
#   - OUTBOUND_CLICK: Clicks to external URLs
#   - SAVE: Number of saves
#   - SAVE_RATE: Save rate percentage
#   - ENGAGEMENT: Total engagement
#   - ENGAGEMENT_RATE: Engagement rate
#   - TOTAL_AUDIENCE: Total audience size
#   - MONTHLY_ENGAGED_AUDIENCE: Monthly engaged audience
#
# Pin Analytics (GET /pins/{pin_id}/analytics):
#   - IMPRESSION: Times pin was shown
#   - OUTBOUND_CLICK: Clicks to destination URL
#   - PIN_CLICK: Clicks on pin
#   - SAVE: Number of saves
#   - SAVE_RATE: Save rate
#   - TOTAL_COMMENTS: Total comments
#   - TOTAL_REACTIONS: Total reactions
#
# Required Scopes:
#   - user_accounts:read: Basic account info
#   - pins:read: Read pins
#   - boards:read: Read boards
#   - user_accounts:analytics:read: Account analytics (Business)
#   - pins:read_analytics: Pin analytics (Business)

# Valid account-level metrics
VALID_ACCOUNT_METRICS = {
    "IMPRESSION",
    "PIN_CLICK",
    "OUTBOUND_CLICK",
    "SAVE",
    "SAVE_RATE",
    "ENGAGEMENT",
    "ENGAGEMENT_RATE",
    "TOTAL_AUDIENCE",
    "MONTHLY_ENGAGED_AUDIENCE",
    "TOTAL_ENGAGED_AUDIENCE",
}

# Valid pin-level metrics
VALID_PIN_METRICS = {
    "IMPRESSION",
    "OUTBOUND_CLICK",
    "PIN_CLICK",
    "SAVE",
    "SAVE_RATE",
    "TOTAL_COMMENTS",
    "TOTAL_REACTIONS",
}

# Deprecated/invalid metrics
DEPRECATED_METRICS = {
    # Add any deprecated metrics here as Pinterest API evolves
}

# Default account metrics
DEFAULT_ACCOUNT_METRICS = [
    "IMPRESSION",
    "SAVE",
    "PIN_CLICK",
    "OUTBOUND_CLICK",
]

# Default pin metrics
DEFAULT_PIN_METRICS = [
    "IMPRESSION",
    "SAVE",
    "PIN_CLICK",
    "OUTBOUND_CLICK",
]

# Valid date granularities
VALID_GRANULARITIES = {"DAY", "WEEK", "MONTH"}

# Valid split by dimensions
VALID_SPLIT_BY = {
    "NO_SPLIT",
    "APP_TYPE",
    "OWNED_CONTENT",
    "PIN_FORMAT",
    "SOURCE",
}


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


def _get_date_range_last_n_days(n: int = 30) -> Tuple[str, str]:
    """Get since/until for last N days."""
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=n)
    return _fmt_ymd(since), _fmt_ymd(until)


# -------------------------------
# Auth headers
# -------------------------------

def _auth_headers(access_token: str) -> Dict[str, str]:
    """Build authorization headers for Pinterest API."""
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# -------------------------------
# Error parsing
# -------------------------------

def _parse_pinterest_error(response_json: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Pinterest API error response."""
    # Pinterest error format varies
    if "code" in response_json:
        return {
            "code": response_json.get("code"),
            "message": response_json.get("message", "Unknown error"),
        }
    
    # Alternative error format
    return {
        "code": response_json.get("error_code") or response_json.get("status"),
        "message": response_json.get("error") or response_json.get("message") or "Unknown error",
        "details": response_json.get("details"),
    }


def _is_auth_error(error: Dict[str, Any], status_code: int) -> bool:
    """Check if error is authentication related."""
    if status_code == 401:
        return True
    code = error.get("code")
    return code in [1, 2, 3]  # Pinterest auth error codes


def _is_permission_error(error: Dict[str, Any], status_code: int) -> bool:
    """Check if error is permission related."""
    if status_code == 403:
        return True
    code = error.get("code")
    message = str(error.get("message", "")).lower()
    return code in [7, 8] or "permission" in message or "scope" in message


def _is_rate_limit_error(error: Dict[str, Any], status_code: int) -> bool:
    """Check if error is rate limit related."""
    if status_code == 429:
        return True
    code = error.get("code")
    return code == 29


def _is_not_found_error(error: Dict[str, Any], status_code: int) -> bool:
    """Check if error is not found."""
    return status_code == 404


# -------------------------------
# API request helper
# -------------------------------

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
        return 408, {"code": "timeout", "message": "Request timeout"}, ""
    except requests.exceptions.RequestException as e:
        return 500, {"code": "request_error", "message": str(e)}, ""


# -------------------------------
# User account info
# -------------------------------

def _get_pinterest_user_info(
    *,
    access_token: str,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Fetch Pinterest user account info.
    
    Returns:
        - username
        - account_type (BUSINESS or PERSONAL)
        - profile_image
        - website_url
        - follower_count
        - following_count
        - pin_count
        - board_count
    """
    url = f"{PINTEREST_API_BASE}/user_account"
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params={},
        timeout=30,
    )
    
    if status >= 400:
        Log.info(f"{log_tag} Pinterest user info error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_pinterest_error(js),
        }
    
    return {
        "success": True,
        "id": js.get("id"),
        "username": js.get("username"),
        "account_type": js.get("account_type"),  # BUSINESS or PERSONAL
        "profile_image": js.get("profile_image"),
        "website_url": js.get("website_url"),
        "business_name": js.get("business_name"),
        "follower_count": js.get("follower_count"),
        "following_count": js.get("following_count"),
        "pin_count": js.get("pin_count"),
        "monthly_views": js.get("monthly_views"),
        "raw": js,
    }


# -------------------------------
# Account analytics
# -------------------------------

def _fetch_account_analytics(
    *,
    access_token: str,
    start_date: str,
    end_date: str,
    metrics: List[str],
    granularity: str = "DAY",
    split_by: str = "NO_SPLIT",
    log_tag: str,
) -> Dict[str, Any]:
    """
    Fetch Pinterest account-level analytics.
    
    Requires:
        - Business account
        - user_accounts:analytics:read scope
    """
    url = f"{PINTEREST_API_BASE}/user_account/analytics"
    
    # Validate metrics
    valid_metrics = [m for m in metrics if m.upper() in VALID_ACCOUNT_METRICS]
    invalid_metrics = [m for m in metrics if m.upper() not in VALID_ACCOUNT_METRICS]
    
    if not valid_metrics:
        return {
            "success": False,
            "error": {
                "code": "invalid_metrics",
                "message": f"No valid metrics provided. Valid metrics: {', '.join(VALID_ACCOUNT_METRICS)}",
            },
            "invalid_metrics": invalid_metrics,
        }
    
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "metric_types": ",".join([m.upper() for m in valid_metrics]),
        "granularity": granularity.upper(),
        "split_by": split_by.upper(),
    }
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    if status >= 400:
        Log.info(f"{log_tag} Pinterest account analytics error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_pinterest_error(js),
            "valid_metrics": valid_metrics,
            "invalid_metrics": invalid_metrics,
        }
    
    # Parse response
    # Pinterest returns data in format: {"all": {"daily_metrics": [...]}}
    all_data = js.get("all", {})
    daily_metrics = all_data.get("daily_metrics", [])
    summary_metrics = all_data.get("summary_metrics", {})
    
    # Build time series for each metric
    metrics_data = {}
    for metric in valid_metrics:
        metric_upper = metric.upper()
        series = []
        
        for day_data in daily_metrics:
            date = day_data.get("date")
            data_status = day_data.get("data_status")
            metrics_values = day_data.get("metrics", {})
            
            value = metrics_values.get(metric_upper)
            
            series.append({
                "date": date,
                "value": value,
                "data_status": data_status,
            })
        
        metrics_data[metric_upper] = {
            "series": series,
            "summary": summary_metrics.get(metric_upper),
        }
    
    return {
        "success": True,
        "valid_metrics": valid_metrics,
        "invalid_metrics": invalid_metrics,
        "metrics": metrics_data,
        "summary_metrics": summary_metrics,
        "raw": js,
    }


# -------------------------------
# Pin analytics
# -------------------------------

def _fetch_pin_analytics(
    *,
    pin_id: str,
    access_token: str,
    start_date: str,
    end_date: str,
    metrics: List[str],
    log_tag: str,
) -> Dict[str, Any]:
    """
    Fetch analytics for a specific pin.
    
    Requires:
        - Business account
        - pins:read_analytics scope
    """
    url = f"{PINTEREST_API_BASE}/pins/{pin_id}/analytics"
    
    # Validate metrics
    valid_metrics = [m for m in metrics if m.upper() in VALID_PIN_METRICS]
    invalid_metrics = [m for m in metrics if m.upper() not in VALID_PIN_METRICS]
    
    if not valid_metrics:
        return {
            "success": False,
            "error": {
                "code": "invalid_metrics",
                "message": f"No valid metrics provided. Valid metrics: {', '.join(VALID_PIN_METRICS)}",
            },
            "invalid_metrics": invalid_metrics,
        }
    
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "metric_types": ",".join([m.upper() for m in valid_metrics]),
        "app_types": "ALL",
    }
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    if status >= 400:
        Log.info(f"{log_tag} Pinterest pin analytics error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_pinterest_error(js),
        }
    
    # Parse response
    all_data = js.get("all", {})
    daily_metrics = all_data.get("daily_metrics", [])
    lifetime_metrics = all_data.get("lifetime_metrics", {})
    summary_metrics = all_data.get("summary_metrics", {})
    
    # Build time series for each metric
    metrics_data = {}
    for metric in valid_metrics:
        metric_upper = metric.upper()
        series = []
        
        for day_data in daily_metrics:
            date = day_data.get("date")
            metrics_values = day_data.get("metrics", {})
            value = metrics_values.get(metric_upper)
            
            series.append({
                "date": date,
                "value": value,
            })
        
        metrics_data[metric_upper] = {
            "series": series,
            "lifetime": lifetime_metrics.get(metric_upper),
            "summary": summary_metrics.get(metric_upper),
        }
    
    return {
        "success": True,
        "valid_metrics": valid_metrics,
        "invalid_metrics": invalid_metrics,
        "metrics": metrics_data,
        "lifetime_metrics": lifetime_metrics,
        "summary_metrics": summary_metrics,
    }


# -------------------------------
# Get pins list
# -------------------------------

def _get_user_pins(
    *,
    access_token: str,
    bookmark: Optional[str] = None,
    page_size: int = 25,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Get list of user's pins.
    
    Requires:
        - pins:read scope
    """
    url = f"{PINTEREST_API_BASE}/pins"
    
    params = {
        "page_size": min(page_size, 250),  # Pinterest max is 250
    }
    
    if bookmark:
        params["bookmark"] = bookmark
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    if status >= 400:
        Log.info(f"{log_tag} Pinterest pins list error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_pinterest_error(js),
        }
    
    items = js.get("items", [])
    
    # Normalize pins
    pins = []
    for pin in items:
        pins.append({
            "id": pin.get("id"),
            "created_at": pin.get("created_at"),
            "title": pin.get("title"),
            "description": pin.get("description"),
            "link": pin.get("link"),
            "dominant_color": pin.get("dominant_color"),
            "alt_text": pin.get("alt_text"),
            "board_id": pin.get("board_id"),
            "board_section_id": pin.get("board_section_id"),
            "media": pin.get("media"),
            "pin_metrics": pin.get("pin_metrics"),
            "raw": pin,
        })
    
    return {
        "success": True,
        "pins": pins,
        "bookmark": js.get("bookmark"),
        "has_more": bool(js.get("bookmark")),
    }


# -------------------------------
# Get pin details
# -------------------------------

def _get_pin_details(
    *,
    pin_id: str,
    access_token: str,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Get details for a specific pin.
    """
    url = f"{PINTEREST_API_BASE}/pins/{pin_id}"
    
    params = {
        "pin_metrics": "true",
    }
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    if status >= 400:
        Log.info(f"{log_tag} Pinterest pin details error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_pinterest_error(js),
        }
    
    return {
        "success": True,
        "pin": {
            "id": js.get("id"),
            "created_at": js.get("created_at"),
            "title": js.get("title"),
            "description": js.get("description"),
            "link": js.get("link"),
            "dominant_color": js.get("dominant_color"),
            "alt_text": js.get("alt_text"),
            "board_id": js.get("board_id"),
            "board_section_id": js.get("board_section_id"),
            "board_owner": js.get("board_owner"),
            "media": js.get("media"),
            "pin_metrics": js.get("pin_metrics"),
        },
        "raw": js,
    }


# -------------------------------
# Get boards list
# -------------------------------

def _get_user_boards(
    *,
    access_token: str,
    bookmark: Optional[str] = None,
    page_size: int = 25,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Get list of user's boards.
    
    Requires:
        - boards:read scope
    """
    url = f"{PINTEREST_API_BASE}/boards"
    
    params = {
        "page_size": min(page_size, 250),
    }
    
    if bookmark:
        params["bookmark"] = bookmark
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    if status >= 400:
        Log.info(f"{log_tag} Pinterest boards list error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_pinterest_error(js),
        }
    
    items = js.get("items", [])
    
    # Normalize boards
    boards = []
    for board in items:
        boards.append({
            "id": board.get("id"),
            "name": board.get("name"),
            "description": board.get("description"),
            "created_at": board.get("created_at"),
            "follower_count": board.get("follower_count"),
            "pin_count": board.get("pin_count"),
            "collaborator_count": board.get("collaborator_count"),
            "privacy": board.get("privacy"),
            "media": board.get("media"),
        })
    
    return {
        "success": True,
        "boards": boards,
        "bookmark": js.get("bookmark"),
        "has_more": bool(js.get("bookmark")),
    }


# -------------------------------
# Get board analytics
# -------------------------------

def _fetch_board_analytics(
    *,
    board_id: str,
    access_token: str,
    start_date: str,
    end_date: str,
    metrics: List[str],
    log_tag: str,
) -> Dict[str, Any]:
    """
    Fetch analytics for a specific board.
    """
    # Board analytics use similar endpoint pattern
    url = f"{PINTEREST_API_BASE}/boards/{board_id}/analytics"
    
    valid_metrics = [m for m in metrics if m.upper() in VALID_ACCOUNT_METRICS]
    
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "metric_types": ",".join([m.upper() for m in valid_metrics]),
    }
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    if status >= 400:
        Log.info(f"{log_tag} Pinterest board analytics error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_pinterest_error(js),
        }
    
    return {
        "success": True,
        "metrics": js,
    }


# -------------------------------
# Calculate summaries
# -------------------------------

def _calculate_metric_summary(metric_data: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate summary statistics for a metric."""
    series = metric_data.get("series", [])
    
    if not series:
        return {
            "total": metric_data.get("summary") or metric_data.get("lifetime") or 0,
            "average": 0,
            "min": 0,
            "max": 0,
            "count": 0,
        }
    
    values = []
    for item in series:
        v = item.get("value")
        if v is not None and isinstance(v, (int, float)):
            values.append(v)
    
    if not values:
        return {
            "total": metric_data.get("summary") or 0,
            "average": 0,
            "min": 0,
            "max": 0,
            "count": 0,
        }
    
    return {
        "total": sum(values),
        "average": round(sum(values) / len(values), 2),
        "min": min(values),
        "max": max(values),
        "count": len(values),
    }


# -------------------------------------------------------------------
# PINTEREST ACCOUNT INSIGHTS — Main Endpoint
# -------------------------------------------------------------------

@blp_pinterest_insights.route("/social/pinterest/account-insights", methods=["GET"])
class PinterestAccountInsightsResource(MethodView):
    """
    Pinterest account-level analytics using stored SocialAccount token.

    Query params:
      - destination_id (required): Pinterest User ID
      - since (YYYY-MM-DD): Start date (default: 30 days ago)
      - until (YYYY-MM-DD): End date (default: today)
      - metrics: comma-separated list of metrics (optional)
      - granularity: DAY | WEEK | MONTH (default: DAY)
      - debug: if "true", includes token debug info
      
    Available metrics:
      - IMPRESSION: Number of times pins were shown
      - PIN_CLICK: Clicks on pins
      - OUTBOUND_CLICK: Clicks to external URLs
      - SAVE: Number of saves
      - SAVE_RATE: Save rate percentage
      - ENGAGEMENT: Total engagement
      - ENGAGEMENT_RATE: Engagement rate
      
    Required scopes:
      - user_accounts:read (basic info)
      - user_accounts:analytics:read (analytics - Business accounts)
      
    Note: Analytics require a Pinterest Business account.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[pinterest_insights_resource.py][PinterestAccountInsightsResource][get][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Parse query parameters
        pinterest_user_id = (request.args.get("destination_id") or "").strip()
        since = (request.args.get("since") or "").strip() or None
        until = (request.args.get("until") or "").strip() or None
        granularity = (request.args.get("granularity") or "DAY").upper().strip()
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        # Validate required parameters
        if not pinterest_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Validate granularity
        if granularity not in VALID_GRANULARITIES:
            return jsonify({
                "success": False,
                "message": f"Invalid granularity. Must be one of: {', '.join(VALID_GRANULARITIES)}",
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
            requested_metrics = [m.strip().upper() for m in metrics_qs.split(",") if m.strip()]
        else:
            requested_metrics = DEFAULT_ACCOUNT_METRICS.copy()

        # --------------------------------------------------
        # Load stored SocialAccount
        # --------------------------------------------------

        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=pinterest_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "PIN_NOT_CONNECTED",
                "message": "Pinterest account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "PIN_TOKEN_MISSING",
                "message": "Reconnect Pinterest - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # --------------------------------------------------
        # Fetch user info
        # --------------------------------------------------

        user_info = _get_pinterest_user_info(
            access_token=access_token,
            log_tag=log_tag,
        )

        if not user_info.get("success"):
            error = user_info.get("error", {})
            status_code = user_info.get("status_code", 400)
            
            if _is_auth_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "PIN_TOKEN_EXPIRED",
                    "message": "Pinterest access token has expired. Please reconnect.",
                    "error": error,
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            if _is_permission_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "PIN_PERMISSION_DENIED",
                    "message": "Missing required scopes. Ensure user_accounts:read is authorized.",
                    "error": error,
                }), HTTP_STATUS_CODES["FORBIDDEN"]

        # Check if business account (required for analytics)
        account_type = user_info.get("account_type", "").upper()
        is_business = account_type == "BUSINESS"

        # --------------------------------------------------
        # Fetch account analytics (Business accounts only)
        # --------------------------------------------------

        analytics_data = None
        analytics_error = None
        summaries = {}

        if is_business:
            analytics = _fetch_account_analytics(
                access_token=access_token,
                start_date=since,
                end_date=until,
                metrics=requested_metrics,
                granularity=granularity,
                log_tag=log_tag,
            )

            if analytics.get("success"):
                analytics_data = analytics.get("metrics")
                
                # Calculate summaries
                for metric_name, metric_data in analytics_data.items():
                    summaries[metric_name] = _calculate_metric_summary(metric_data)
            else:
                analytics_error = analytics.get("error")
                
                # Check if it's a permission error
                if _is_permission_error(analytics_error, analytics.get("status_code", 400)):
                    analytics_error["note"] = "Analytics require user_accounts:analytics:read scope"
        else:
            analytics_error = {
                "code": "not_business_account",
                "message": "Analytics require a Pinterest Business account. Current account type: " + account_type,
            }

        # Build response
        result = {
            "platform": PLATFORM_ID,
            "destination_id": pinterest_user_id,
            "since": since,
            "until": until,
            "granularity": granularity,
            "requested_metrics": requested_metrics,

            "account_info": {
                "id": user_info.get("id"),
                "username": user_info.get("username"),
                "account_type": user_info.get("account_type"),
                "business_name": user_info.get("business_name"),
                "profile_image": user_info.get("profile_image"),
                "website_url": user_info.get("website_url"),
            },

            "public_metrics": {
                "follower_count": user_info.get("follower_count"),
                "following_count": user_info.get("following_count"),
                "pin_count": user_info.get("pin_count"),
                "monthly_views": user_info.get("monthly_views"),
            },

            "summaries": summaries,
            "metrics": analytics_data,
            "analytics_error": analytics_error,
            "is_business_account": is_business,
        }

        if debug_mode:
            result["debug"] = {
                "available_metrics": sorted(list(VALID_ACCOUNT_METRICS)),
                "valid_granularities": sorted(list(VALID_GRANULARITIES)),
                "required_scopes": [
                    "user_accounts:read",
                    "user_accounts:analytics:read (Business accounts)",
                ],
                "note": "Analytics require Pinterest Business account and user_accounts:analytics:read scope",
            }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# PINTEREST PIN INSIGHTS — Get insights for a specific pin
# -------------------------------------------------------------------

@blp_pinterest_insights.route("/social/pinterest/pin-insights", methods=["GET"])
class PinterestPinInsightsResource(MethodView):
    """
    Pinterest pin-level analytics for a specific pin.

    Query params:
      - destination_id (required): Pinterest User ID
      - pin_id (required): Pinterest Pin ID
      - since (YYYY-MM-DD): Start date
      - until (YYYY-MM-DD): End date
      - metrics: comma-separated list of metrics (optional)
      - debug: if "true", includes debug info
      
    Available metrics:
      - IMPRESSION: Times pin was shown
      - PIN_CLICK: Clicks on pin
      - OUTBOUND_CLICK: Clicks to destination URL
      - SAVE: Number of saves
      - TOTAL_COMMENTS: Total comments
      - TOTAL_REACTIONS: Total reactions
      
    Required scopes:
      - pins:read
      - pins:read_analytics (Business accounts)
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[pinterest_insights_resource.py][PinterestPinInsightsResource][get][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Parse query parameters
        pinterest_user_id = (request.args.get("destination_id") or "").strip()
        pin_id = (request.args.get("pin_id") or "").strip()
        since = (request.args.get("since") or "").strip() or None
        until = (request.args.get("until") or "").strip() or None
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        if not pinterest_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        if not pin_id:
            return jsonify({
                "success": False,
                "message": "pin_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Default date range
        if not since or not until:
            since, until = _get_date_range_last_n_days(30)

        # Parse metrics
        metrics_qs = (request.args.get("metrics") or "").strip()
        if metrics_qs:
            requested_metrics = [m.strip().upper() for m in metrics_qs.split(",") if m.strip()]
        else:
            requested_metrics = DEFAULT_PIN_METRICS.copy()

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=pinterest_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "PIN_NOT_CONNECTED",
                "message": "Pinterest account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "PIN_TOKEN_MISSING",
                "message": "Reconnect Pinterest - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch pin analytics
        analytics = _fetch_pin_analytics(
            pin_id=pin_id,
            access_token=access_token,
            start_date=since,
            end_date=until,
            metrics=requested_metrics,
            log_tag=log_tag,
        )

        if not analytics.get("success"):
            error = analytics.get("error", {})
            status_code = analytics.get("status_code", 400)
            
            if _is_auth_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "PIN_TOKEN_EXPIRED",
                    "message": "Pinterest access token has expired. Please reconnect.",
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            if _is_permission_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "PIN_PERMISSION_DENIED",
                    "message": "Missing pins:read_analytics scope. Pin analytics require Business account.",
                    "error": error,
                }), HTTP_STATUS_CODES["FORBIDDEN"]
            
            if _is_not_found_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "PIN_NOT_FOUND",
                    "message": f"Pin not found: {pin_id}",
                    "error": error,
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            return jsonify({
                "success": False,
                "code": "PIN_ANALYTICS_ERROR",
                "message": error.get("message") or "Failed to fetch pin analytics",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Calculate summaries
        summaries = {}
        for metric_name, metric_data in analytics.get("metrics", {}).items():
            summaries[metric_name] = _calculate_metric_summary(metric_data)

        result = {
            "platform": PLATFORM_ID,
            "destination_id": pinterest_user_id,
            "pin_id": pin_id,
            "since": since,
            "until": until,
            "requested_metrics": requested_metrics,
            "valid_metrics": analytics.get("valid_metrics"),
            "invalid_metrics": analytics.get("invalid_metrics"),
            "summaries": summaries,
            "lifetime_metrics": analytics.get("lifetime_metrics"),
            "metrics": analytics.get("metrics"),
        }

        if debug_mode:
            result["debug"] = {
                "available_metrics": sorted(list(VALID_PIN_METRICS)),
                "required_scopes": ["pins:read", "pins:read_analytics"],
            }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# PINTEREST PIN LIST — Get all pins
# -------------------------------------------------------------------

@blp_pinterest_insights.route("/social/pinterest/pin-list", methods=["GET"])
class PinterestPinListResource(MethodView):
    """
    Get list of pins for a Pinterest account.

    Query params:
      - destination_id (required): Pinterest User ID
      - limit: Number of pins to return (default: 25, max: 250)
      - bookmark: Pagination cursor
      
    Required scope: pins:read
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[pinterest_insights][pin_list][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Parse query parameters
        pinterest_user_id = (request.args.get("destination_id") or "").strip()
        bookmark = (request.args.get("bookmark") or "").strip() or None
        
        try:
            limit = min(max(int(request.args.get("limit", 25)), 1), 250)
        except ValueError:
            limit = 25

        if not pinterest_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=pinterest_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "PIN_NOT_CONNECTED",
                "message": "Pinterest account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "PIN_TOKEN_MISSING",
                "message": "Reconnect Pinterest - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch pins
        pins_resp = _get_user_pins(
            access_token=access_token,
            bookmark=bookmark,
            page_size=limit,
            log_tag=log_tag,
        )

        if not pins_resp.get("success"):
            error = pins_resp.get("error", {})
            status_code = pins_resp.get("status_code", 400)
            
            if _is_auth_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "PIN_TOKEN_EXPIRED",
                    "message": "Pinterest access token has expired. Please reconnect.",
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            if _is_permission_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "PIN_PERMISSION_DENIED",
                    "message": "Missing pins:read scope.",
                }), HTTP_STATUS_CODES["FORBIDDEN"]
            
            return jsonify({
                "success": False,
                "code": "PIN_LIST_ERROR",
                "message": error.get("message") or "Failed to fetch pins",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Remove raw data
        pins = []
        for pin in pins_resp.get("pins", []):
            pin_clean = {k: v for k, v in pin.items() if k != "raw"}
            pins.append(pin_clean)

        result = {
            "platform": PLATFORM_ID,
            "destination_id": pinterest_user_id,
            "count": len(pins),
            "limit": limit,
            "pins": pins,
            "pagination": {
                "bookmark": pins_resp.get("bookmark"),
                "has_more": pins_resp.get("has_more", False),
            },
        }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# PINTEREST PIN DETAILS — Get details for a specific pin
# -------------------------------------------------------------------

@blp_pinterest_insights.route("/social/pinterest/pin-details", methods=["GET"])
class PinterestPinDetailsResource(MethodView):
    """
    Get detailed information for a specific Pinterest pin.

    Query params:
      - destination_id (required): Pinterest User ID
      - pin_id (required): Pinterest Pin ID
      
    Required scope: pins:read
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[pinterest_insights_resource.py][PinterestPinDetailsResource][get][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        pinterest_user_id = (request.args.get("destination_id") or "").strip()
        pin_id = (request.args.get("pin_id") or "").strip()

        if not pinterest_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        if not pin_id:
            return jsonify({
                "success": False,
                "message": "pin_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=pinterest_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "PIN_NOT_CONNECTED",
                "message": "Pinterest account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "PIN_TOKEN_MISSING",
                "message": "Reconnect Pinterest - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch pin details
        pin_resp = _get_pin_details(
            pin_id=pin_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        if not pin_resp.get("success"):
            error = pin_resp.get("error", {})
            status_code = pin_resp.get("status_code", 400)
            
            if _is_not_found_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "PIN_NOT_FOUND",
                    "message": f"Pin not found: {pin_id}",
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            return jsonify({
                "success": False,
                "code": "PIN_DETAILS_ERROR",
                "message": error.get("message") or "Failed to fetch pin details",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        result = {
            "platform": PLATFORM_ID,
            "pin": pin_resp.get("pin"),
        }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# PINTEREST BOARDS LIST — Get all boards
# -------------------------------------------------------------------

@blp_pinterest_insights.route("/social/pinterest/board-list", methods=["GET"])
class PinterestBoardListResource(MethodView):
    """
    Get list of boards for a Pinterest account.

    Query params:
      - destination_id (required): Pinterest User ID
      - limit: Number of boards to return (default: 25, max: 250)
      - bookmark: Pagination cursor
      
    Required scope: boards:read
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[pinterest_insights][board_list][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        pinterest_user_id = (request.args.get("destination_id") or "").strip()
        bookmark = (request.args.get("bookmark") or "").strip() or None
        
        try:
            limit = min(max(int(request.args.get("limit", 25)), 1), 250)
        except ValueError:
            limit = 25

        if not pinterest_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=pinterest_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "PIN_NOT_CONNECTED",
                "message": "Pinterest account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "PIN_TOKEN_MISSING",
                "message": "Reconnect Pinterest - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch boards
        boards_resp = _get_user_boards(
            access_token=access_token,
            bookmark=bookmark,
            page_size=limit,
            log_tag=log_tag,
        )

        if not boards_resp.get("success"):
            error = boards_resp.get("error", {})
            
            return jsonify({
                "success": False,
                "code": "PIN_BOARD_LIST_ERROR",
                "message": error.get("message") or "Failed to fetch boards",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        result = {
            "platform": PLATFORM_ID,
            "destination_id": pinterest_user_id,
            "count": len(boards_resp.get("boards", [])),
            "limit": limit,
            "boards": boards_resp.get("boards", []),
            "pagination": {
                "bookmark": boards_resp.get("bookmark"),
                "has_more": boards_resp.get("has_more", False),
            },
        }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# PINTEREST DISCOVER METRICS — Test which metrics work
# -------------------------------------------------------------------

@blp_pinterest_insights.route("/social/pinterest/discover-metrics", methods=["GET"])
class PinterestDiscoverMetricsResource(MethodView):
    """
    Diagnostic endpoint to test Pinterest API access.
    
    Query params:
      - destination_id (required): Pinterest User ID
      
    Tests:
      - User account info
      - Account analytics availability
      - Pins list
      - Boards list
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[pinterest_insights][discover][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        pinterest_user_id = (request.args.get("destination_id") or "").strip()
        
        if not pinterest_user_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=pinterest_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "PIN_NOT_CONNECTED",
                "message": "Pinterest account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "PIN_TOKEN_MISSING",
                "message": "Reconnect Pinterest - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Test 1: User info
        user_info = _get_pinterest_user_info(
            access_token=access_token,
            log_tag=log_tag,
        )

        user_probe = {
            "success": user_info.get("success", False),
            "username": user_info.get("username") if user_info.get("success") else None,
            "account_type": user_info.get("account_type") if user_info.get("success") else None,
            "follower_count": user_info.get("follower_count") if user_info.get("success") else None,
            "error": user_info.get("error") if not user_info.get("success") else None,
        }

        is_business = user_info.get("account_type", "").upper() == "BUSINESS"

        # Test 2: Account analytics (only for Business)
        analytics_probe = None
        if is_business:
            since, until = _get_date_range_last_n_days(7)
            analytics = _fetch_account_analytics(
                access_token=access_token,
                start_date=since,
                end_date=until,
                metrics=["IMPRESSION", "SAVE"],
                log_tag=log_tag,
            )
            
            analytics_probe = {
                "success": analytics.get("success", False),
                "has_data": bool(analytics.get("metrics")),
                "error": analytics.get("error") if not analytics.get("success") else None,
            }
        else:
            analytics_probe = {
                "success": False,
                "error": {
                    "code": "not_business",
                    "message": "Analytics require Business account",
                },
            }

        # Test 3: Pins list
        pins_resp = _get_user_pins(
            access_token=access_token,
            page_size=5,
            log_tag=log_tag,
        )

        pins_probe = {
            "success": pins_resp.get("success", False),
            "count": len(pins_resp.get("pins", [])) if pins_resp.get("success") else 0,
            "sample_pin_id": pins_resp.get("pins", [{}])[0].get("id") if pins_resp.get("success") and pins_resp.get("pins") else None,
            "error": pins_resp.get("error") if not pins_resp.get("success") else None,
        }

        # Test 4: Boards list
        boards_resp = _get_user_boards(
            access_token=access_token,
            page_size=5,
            log_tag=log_tag,
        )

        boards_probe = {
            "success": boards_resp.get("success", False),
            "count": len(boards_resp.get("boards", [])) if boards_resp.get("success") else 0,
            "error": boards_resp.get("error") if not boards_resp.get("success") else None,
        }

        # Determine access level
        has_basic = user_probe.get("success", False)
        has_pins = pins_probe.get("success", False)
        has_boards = boards_probe.get("success", False)
        has_analytics = analytics_probe.get("success", False) if analytics_probe else False

        scopes_detected = []
        if has_basic:
            scopes_detected.append("user_accounts:read")
        if has_pins:
            scopes_detected.append("pins:read")
        if has_boards:
            scopes_detected.append("boards:read")
        if has_analytics:
            scopes_detected.append("user_accounts:analytics:read")

        access_level = "none"
        if has_basic:
            access_level = "basic"
        if has_basic and has_pins and has_boards:
            access_level = "standard"
        if has_analytics:
            access_level = "full"

        return jsonify({
            "success": True,
            "data": {
                "platform": PLATFORM_ID,
                "destination_id": pinterest_user_id,
                
                "probes": {
                    "user_info": user_probe,
                    "account_analytics": analytics_probe,
                    "pins_list": pins_probe,
                    "boards_list": boards_probe,
                },
                
                "is_business_account": is_business,
                "access_level": access_level,
                "scopes_detected": scopes_detected,
                
                "recommendation": (
                    "Full analytics access available!" if access_level == "full"
                    else "Standard access. Convert to Business account for analytics."
                    if access_level == "standard" and not is_business
                    else "Standard access. Add user_accounts:analytics:read scope for analytics."
                    if access_level == "standard"
                    else "Basic access only. Check OAuth scopes."
                    if access_level == "basic"
                    else "No access. Check token validity."
                ),
                
                "notes": [
                    "Pinterest analytics require a Business account.",
                    "To convert: Go to Pinterest settings → Account settings → Convert to Business.",
                    "Rate limit: 1000 requests per minute.",
                    "Analytics data may have 24-48 hour delay.",
                ],
                
                "required_scopes": {
                    "basic": ["user_accounts:read"],
                    "standard": ["user_accounts:read", "pins:read", "boards:read"],
                    "full": [
                        "user_accounts:read",
                        "pins:read",
                        "boards:read",
                        "user_accounts:analytics:read",
                        "pins:read_analytics",
                    ],
                },
                
                "available_account_metrics": sorted(list(VALID_ACCOUNT_METRICS)),
                "available_pin_metrics": sorted(list(VALID_PIN_METRICS)),
            },
        }), HTTP_STATUS_CODES["OK"]