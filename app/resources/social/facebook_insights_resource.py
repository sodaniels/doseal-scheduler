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
    "meta_impression",
    __name__,
)

# Use v21.0 - stable version
GRAPH_VERSION = "v21.0"


# -------------------------------------------------------------------
# Valid Metrics (Updated Feb 2025 - Post Nov 2025 Deprecation)
# -------------------------------------------------------------------
# IMPORTANT: Many metrics were deprecated Nov 15, 2025
# - page_impressions -> replaced by "views" metrics
# - page_fans -> deprecated, use followers_count from page fields
# - page_engaged_users -> may be deprecated
#
# The metrics below are confirmed working with New Pages Experience

# Metrics that should work with New Pages Experience (as of 2025)
VALID_PAGE_METRICS_V21 = {
    # Post engagement - these tend to work
    "page_post_engagements",
    
    # Actions
    "page_total_actions",
    "page_cta_clicks_logged_in_total",
    "page_cta_clicks_logged_in_unique",
    "page_call_phone_clicks_logged_in_unique",
    "page_get_directions_clicks_logged_in_unique", 
    "page_website_clicks_logged_in_unique",
    
    # Follows (replacement for deprecated page_fans)
    "page_daily_follows",
    "page_daily_follows_unique",
    "page_daily_unfollows",
    "page_daily_unfollows_unique",
    
    # Video metrics
    "page_video_views",
    "page_video_views_paid",
    "page_video_views_organic",
    "page_video_views_unique",
    "page_video_complete_views_30s",
    "page_video_complete_views_30s_unique",
    
    # Posts impressions (may still work)
    "page_posts_impressions",
    "page_posts_impressions_unique",
    "page_posts_impressions_paid",
    "page_posts_impressions_organic",
    
    # Views metrics (NEW - replacement for impressions)
    "page_views_total",  # Note: may be deprecated in some versions
    "page_views_logged_in_total",
    "page_views_logged_in_unique",
    
    # Content interactions
    "page_content_activity",
    "page_content_activity_by_action_type",
}

# Default metrics to try - start with most likely to work
DEFAULT_METRICS = [
    "page_post_engagements",
    "page_daily_follows_unique", 
    "page_video_views",
]

# Fallback metrics if primary ones fail
FALLBACK_METRICS = [
    "page_total_actions",
    "page_cta_clicks_logged_in_total",
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
    """Convert datetime to Unix timestamp for Facebook API."""
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def _split_date_range_93_days(
    since: Optional[str],
    until: Optional[str],
) -> List[Dict[str, Optional[str]]]:
    """
    Facebook Insights allows <=93 days between since/until.
    This splits into safe chunks automatically.
    """
    if not since or not until:
        return [{"since": since, "until": until}]

    start = _parse_ymd(since)
    end = _parse_ymd(until)

    if not start or not end or start > end:
        return [{"since": since, "until": until}]

    chunks: List[Dict[str, str]] = []
    cur = start

    while cur <= end:
        # Facebook allows max 93 days, use 90 for safety margin
        chunk_end = min(cur + timedelta(days=90), end)
        chunks.append({
            "since": _fmt_ymd(cur),
            "until": _fmt_ymd(chunk_end),
        })
        cur = chunk_end + timedelta(days=1)

    return chunks


# -------------------------------
# Error parsing
# -------------------------------

def _parse_fb_error(response_json: Dict[str, Any]) -> Dict[str, Any]:
    """Parse Facebook API error response for better error messages."""
    error = response_json.get("error", {})
    return {
        "message": error.get("message", "Unknown error"),
        "type": error.get("type", "Unknown"),
        "code": error.get("code"),
        "error_subcode": error.get("error_subcode"),
        "fbtrace_id": error.get("fbtrace_id"),
    }


def _is_permission_error(error: Dict[str, Any]) -> bool:
    """Check if error is permission-related."""
    code = error.get("code")
    message = str(error.get("message", "")).lower()
    
    # Common permission error codes
    if code in [10, 100, 190, 200, 210, 230, 270, 275]:
        return True
    
    # Check message for permission-related keywords
    permission_keywords = ["permission", "access", "authorized", "token", "scope"]
    return any(kw in message for kw in permission_keywords)


def _is_invalid_metric_error(error: Dict[str, Any]) -> bool:
    """Check if error is about invalid metric."""
    code = error.get("code")
    message = str(error.get("message", "")).lower()
    
    return code == 100 and "valid insights metric" in message


# -------------------------------
# Token validation
# -------------------------------

def _debug_token(access_token: str, log_tag: str) -> Dict[str, Any]:
    """
    Debug token to check permissions and validity.
    Returns token info including scopes.
    """
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
# Insights parsing
# -------------------------------

def _series_from_insights_payload(
    payload: Dict[str, Any], 
    metric_name: str
) -> List[Dict[str, Any]]:
    """Extract time series data for a specific metric from API response."""
    data = (payload or {}).get("data") or []
    
    # Handle case where metric might have period suffix
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
    """Merge chunked responses into one timeline, removing duplicates."""
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
# Page counts (fields endpoint)
# -------------------------------

def _get_page_counts(
    *, 
    page_id: str, 
    access_token: str, 
    log_tag: str
) -> Dict[str, Any]:
    """
    Fetch basic page metrics using fields endpoint.
    This uses the Page API, not Insights API, so should work with basic permissions.
    """
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}"

    # Request multiple fields - followers_count is the primary metric now
    params = {
        "fields": "id,name,followers_count,fan_count,category,about,link",
        "access_token": access_token,
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        
        if r.status_code >= 400:
            Log.info(f"{log_tag} page fields error: {r.status_code} {r.text}")
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
            "fan_count": data.get("fan_count"),
            "followers_count": data.get("followers_count"),
            "category": data.get("category"),
            "link": data.get("link"),
            "raw": data,
        }
        
    except requests.exceptions.Timeout:
        Log.error(f"{log_tag} page fields timeout")
        return {
            "success": False,
            "status_code": 408,
            "error": {"message": "Request timeout"},
        }
    except requests.exceptions.RequestException as e:
        Log.error(f"{log_tag} page fields request error: {e}")
        return {
            "success": False,
            "status_code": 500,
            "error": {"message": str(e)},
        }


# -------------------------------
# Discover valid metrics
# -------------------------------

def _discover_valid_metrics(
    *,
    page_id: str,
    access_token: str,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Try to discover which metrics work for this page/token combination.
    This helps diagnose permission issues.
    """
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/insights"
    
    # Try metrics one by one to see which work
    test_metrics = [
        "page_post_engagements",
        "page_daily_follows_unique",
        "page_video_views",
        "page_total_actions",
        "page_fans",  # Likely deprecated
        "page_impressions",  # Likely deprecated  
        "page_engaged_users",  # Likely deprecated
    ]
    
    working = []
    not_working = []
    
    for metric in test_metrics:
        params = {
            "metric": metric,
            "period": "day",
            "access_token": access_token,
        }
        
        try:
            r = requests.get(url, params=params, timeout=15)
            
            if r.status_code == 200:
                data = r.json()
                if data.get("data"):
                    working.append(metric)
                else:
                    not_working.append({"metric": metric, "reason": "empty_data"})
            else:
                error_data = r.json() if r.text else {}
                not_working.append({
                    "metric": metric, 
                    "reason": "error",
                    "error": _parse_fb_error(error_data),
                })
        except Exception as e:
            not_working.append({"metric": metric, "reason": str(e)})
    
    return {
        "working_metrics": working,
        "failed_metrics": not_working,
    }


# -------------------------------
# Chunked metric fetching
# -------------------------------

def _fetch_single_metric_chunked(
    *,
    page_id: str,
    access_token: str,
    metric: str,
    period: str,
    chunks: List[Dict[str, Optional[str]]],
    log_tag: str,
) -> Tuple[bool, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Fetch a single metric across all date chunks.
    Returns: (success, series_data, errors)
    """
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{page_id}/insights"
    parts: List[List[Dict[str, Any]]] = []
    errors: List[Dict[str, Any]] = []
    
    for ch in chunks:
        params = {
            "metric": metric,
            "period": period,
            "access_token": access_token,
        }

        # Use Unix timestamps for since/until (more reliable)
        if ch.get("since"):
            since_dt = _parse_ymd(ch["since"])
            if since_dt:
                params["since"] = _to_unix_timestamp(since_dt)
                
        if ch.get("until"):
            until_dt = _parse_ymd(ch["until"])
            if until_dt:
                # Add one day to until to include the end date
                params["until"] = _to_unix_timestamp(until_dt + timedelta(days=1))

        try:
            r = requests.get(url, params=params, timeout=30)

            if r.status_code >= 400:
                error_data = r.json() if r.text else {}
                parsed_error = _parse_fb_error(error_data)
                
                errors.append({
                    "metric": metric,
                    "status_code": r.status_code,
                    "error": parsed_error,
                    "since": ch.get("since"),
                    "until": ch.get("until"),
                })
                
                # Check for specific error types that mean we should stop
                if _is_invalid_metric_error(parsed_error):
                    # Metric is invalid/deprecated - no point continuing
                    Log.info(f"{log_tag} Metric '{metric}' is invalid or deprecated")
                    break
                elif parsed_error.get("code") == 190:
                    # Token expired/invalid
                    Log.warning(f"{log_tag} Token invalid")
                    break
                    
                continue

            payload = r.json() or {}
            series = _series_from_insights_payload(payload, metric)
            
            if series:
                parts.append(series)
                
        except requests.exceptions.Timeout:
            errors.append({
                "metric": metric,
                "status_code": 408,
                "error": {"message": "Request timeout"},
                "since": ch.get("since"),
                "until": ch.get("until"),
            })
        except requests.exceptions.RequestException as e:
            errors.append({
                "metric": metric,
                "status_code": 500,
                "error": {"message": str(e)},
                "since": ch.get("since"),
                "until": ch.get("until"),
            })

    if parts:
        merged = _merge_series(parts)
        return True, merged, errors
    
    return False, [], errors


def _probe_insights_metrics_chunked(
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
    Fetch multiple metrics with automatic date chunking.
    """
    chunks = _split_date_range_93_days(since, until)

    valid_metrics: List[str] = []
    invalid_metrics: List[Dict[str, Any]] = []
    merged_metrics: Dict[str, List[Dict[str, Any]]] = {}
    deprecated_metrics: List[str] = []

    # De-duplicate and clean metrics
    seen = set()
    uniq_metrics: List[str] = []
    for m in metrics:
        m2 = (m or "").strip()
        if not m2 or m2 in seen:
            continue
        seen.add(m2)
        uniq_metrics.append(m2)

    for metric in uniq_metrics:
        success, series, errors = _fetch_single_metric_chunked(
            page_id=page_id,
            access_token=access_token,
            metric=metric,
            period=period,
            chunks=chunks,
            log_tag=log_tag,
        )
        
        if success and series:
            merged_metrics[metric] = series
            valid_metrics.append(metric)
        
        if errors:
            # Check if this is a deprecated metric error
            for err in errors:
                if _is_invalid_metric_error(err.get("error", {})):
                    deprecated_metrics.append(metric)
                    break
            invalid_metrics.extend(errors)

    return {
        "chunks": chunks,
        "valid_metrics": valid_metrics,
        "invalid_metrics": invalid_metrics,
        "deprecated_metrics": list(set(deprecated_metrics)),
        "metrics": merged_metrics,
    }


# -------------------------------------------------------------------
# FACEBOOK PAGE OVERVIEW — STORED TOKEN
# -------------------------------------------------------------------

@blp_meta_impression.route("/social/facebook/page-impressions", methods=["GET"])
class FacebookPageOverviewStoredTokenResource(MethodView):
    """
    Page analytics using stored SocialAccount token.

    Query params:
      - destination_id (required): Facebook Page ID
      - since (YYYY-MM-DD): Start date for insights
      - until (YYYY-MM-DD): End date for insights
      - period: day | week | days_28 | month (default: day)
      - metrics: comma-separated list of metrics (optional)
      - debug: if "true", includes token debug info
      
    IMPORTANT: As of Nov 2025, many metrics are deprecated:
      - page_impressions -> DEPRECATED (use page_views or posts_impressions)
      - page_fans -> DEPRECATED (use followers_count from page fields)
      - page_engaged_users -> DEPRECATED
      
    Working metrics (2025):
      - page_post_engagements: Total engagements on posts
      - page_daily_follows_unique: New followers per day  
      - page_video_views: Video views
      - page_total_actions: Total actions on page
      
    Required token permissions:
      - read_insights
      - pages_read_engagement
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_insights][overview][{client_ip}]"

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
        valid_periods = {"day", "week", "days_28", "month", "lifetime"}
        if period not in valid_periods:
            return jsonify({
                "success": False,
                "message": f"Invalid period. Must be one of: {', '.join(valid_periods)}",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Validate date format if provided
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
            
            # Check if read_insights permission is present
            scopes = token_info.get("scopes", [])
            if "read_insights" not in scopes:
                Log.warning(f"{log_tag} Token missing read_insights permission")

        # Parse requested metrics or use defaults
        metrics_qs = (request.args.get("metrics") or "").strip()
        requested_metrics = (
            [m.strip() for m in metrics_qs.split(",") if m.strip()]
            if metrics_qs
            else DEFAULT_METRICS.copy()
        )

        # --------------------------------------------------
        # Fetch counts (basic page info - doesn't need insights permission)
        # --------------------------------------------------

        counts = _get_page_counts(
            page_id=page_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        # Check for token errors early
        if not counts.get("success"):
            error = counts.get("error", {})
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
                    "message": "Missing permissions. Token needs: read_insights, pages_read_engagement",
                    "debug": token_info if debug_mode else None,
                }), HTTP_STATUS_CODES["FORBIDDEN"]

        # --------------------------------------------------
        # Fetch insights (chunked for date ranges > 93 days)
        # --------------------------------------------------

        insights = _probe_insights_metrics_chunked(
            page_id=page_id,
            access_token=access_token,
            metrics=requested_metrics,
            period=period,
            since=since,
            until=until,
            log_tag=log_tag,
        )

        # Check if ALL metrics failed with invalid metric error
        deprecated_metrics = insights.get("deprecated_metrics", [])
        if deprecated_metrics and not insights.get("valid_metrics"):
            # All metrics are deprecated/invalid
            return jsonify({
                "success": False,
                "code": "FB_METRICS_DEPRECATED",
                "message": (
                    f"All requested metrics are deprecated or invalid. "
                    f"Deprecated: {deprecated_metrics}. "
                    f"Try: page_post_engagements, page_daily_follows_unique, page_video_views"
                ),
                "suggested_metrics": DEFAULT_METRICS,
                "counts": {
                    "followers_count": _pick(counts, "followers_count"),
                    "fan_count": _pick(counts, "fan_count"),
                    "name": _pick(counts, "name"),
                },
                "debug": token_info if debug_mode else None,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Build response
        result = {
            "platform": "facebook",
            "graph_version": GRAPH_VERSION,
            "destination_id": page_id,
            "destination_name": acct.get("destination_name") or _pick(counts, "name"),
            "period": period,
            "since": since,
            "until": until,
            "requested_metrics": requested_metrics,

            "counts": {
                "followers_count": _pick(counts, "followers_count"),
                "fan_count": _pick(counts, "fan_count"),
                "name": _pick(counts, "name"),
                "category": _pick(counts, "category"),
                "fields_error": None if counts.get("success") else counts.get("error"),
            },

            "chunks": insights.get("chunks"),
            "valid_metrics": insights.get("valid_metrics"),
            "invalid_metrics": insights.get("invalid_metrics"),
            "deprecated_metrics": insights.get("deprecated_metrics"),
            "metrics": insights.get("metrics"),
        }
        
        # Add debug info if requested
        if debug_mode:
            result["debug"] = {
                "token_info": token_info,
                "available_metrics": list(VALID_PAGE_METRICS_V21),
            }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]




