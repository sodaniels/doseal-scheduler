
# app/resources/social/linkedin_insights.py
#
# LinkedIn analytics using STORED SocialAccount token
#
# What you can get with LinkedIn API:
# - Organization (Company Page) follower statistics
# - Organization share statistics (posts)
# - Post-level engagement metrics
#
# LinkedIn API versions:
# - Marketing API (requires Marketing Developer Platform access)
# - Community Management API (for basic page management)
#
# Key limitations:
# - Most analytics require Organization Admin access
# - Some metrics require Marketing Developer Platform approval
# - Rate limits: 100 requests per day for most endpoints

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

blp_linkedin_insights = Blueprint(
    "linkedin_insights",
    __name__,
)

# LinkedIn API base URLs
LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_REST_BASE = "https://api.linkedin.com/rest"

# Platform identifier
PLATFORM_ID = "linkedin"

# API Version header (required for REST API)
LINKEDIN_VERSION = "202401"


# -------------------------------------------------------------------
# Valid Metrics Reference
# -------------------------------------------------------------------
# Organization Follower Statistics:
#   - followerCountsByAssociationType
#   - followerCountsByFunction
#   - followerCountsByGeoCountry
#   - followerCountsByIndustry
#   - followerCountsBySeniority
#   - followerCountsByStaffCountRange
#
# Organization Share Statistics (requires Marketing API):
#   - shareCount
#   - uniqueImpressionsCount
#   - clickCount
#   - likeCount
#   - commentCount
#   - shareCountOrganic
#   - engagement
#
# Post-level metrics (UGC Posts):
#   - likes
#   - comments
#   - shares
#   - impressions (requires Marketing API)
#   - clicks (requires Marketing API)


# Default metrics to request
DEFAULT_ORG_METRICS = [
    "followerCount",
]

DEFAULT_POST_METRICS = [
    "likes",
    "comments", 
    "shares",
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


def _to_unix_timestamp_ms(dt: datetime) -> int:
    """Convert datetime to Unix timestamp in milliseconds for LinkedIn API."""
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _get_date_range_last_n_days(n: int = 30) -> Tuple[str, str]:
    """Get since/until for last N days."""
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=n)
    return _fmt_ymd(since), _fmt_ymd(until)


def _auth_headers(access_token: str, use_rest_api: bool = False) -> Dict[str, str]:
    """Build authorization headers for LinkedIn API."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Restli-Protocol-Version": "2.0.0",
    }
    
    if use_rest_api:
        headers["LinkedIn-Version"] = LINKEDIN_VERSION
    
    return headers


def _parse_linkedin_error(response_json: Dict[str, Any]) -> Dict[str, Any]:
    """Parse LinkedIn API error response."""
    return {
        "message": response_json.get("message") or response_json.get("error_description") or "Unknown error",
        "status": response_json.get("status") or response_json.get("error"),
        "service_error_code": response_json.get("serviceErrorCode"),
        "code": response_json.get("code"),
    }


def _is_auth_error(error: Dict[str, Any], status_code: int) -> bool:
    """Check if error is authentication related."""
    if status_code in [401, 403]:
        return True
    service_code = error.get("service_error_code")
    return service_code in [65600, 65601, 65602]  # LinkedIn auth error codes


def _is_permission_error(error: Dict[str, Any], status_code: int) -> bool:
    """Check if error is permission related."""
    if status_code == 403:
        return True
    service_code = error.get("service_error_code")
    return service_code in [100, 65604]  # Access denied codes


def _extract_org_id(org_urn: str) -> str:
    """Extract organization ID from URN."""
    # urn:li:organization:12345 -> 12345
    if org_urn.startswith("urn:li:organization:"):
        return org_urn.replace("urn:li:organization:", "")
    return org_urn


def _make_org_urn(org_id: str) -> str:
    """Create organization URN from ID."""
    if org_id.startswith("urn:li:organization:"):
        return org_id
    return f"urn:li:organization:{org_id}"


def _extract_post_id(post_urn: str) -> str:
    """Extract post ID from URN."""
    # urn:li:share:12345 -> 12345
    # urn:li:ugcPost:12345 -> 12345
    if post_urn.startswith("urn:li:share:"):
        return post_urn.replace("urn:li:share:", "")
    if post_urn.startswith("urn:li:ugcPost:"):
        return post_urn.replace("urn:li:ugcPost:", "")
    return post_urn


# -------------------------------------------------------------------
# API Request Helper
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
        return 408, {"message": "Request timeout"}, ""
    except requests.exceptions.RequestException as e:
        return 500, {"message": str(e)}, ""


# -------------------------------------------------------------------
# Organization Info
# -------------------------------------------------------------------

def _get_linkedin_organization_info(
    *, 
    org_id: str, 
    access_token: str, 
    log_tag: str
) -> Dict[str, Any]:
    """
    Fetch LinkedIn organization (company page) info.
    """
    org_urn = _make_org_urn(org_id)
    url = f"{LINKEDIN_API_BASE}/organizations/{org_id}"
    
    params = {
        "projection": "(id,localizedName,localizedDescription,vanityName,logoV2,coverPhotoV2,staffCountRange,industries,specialties,websiteUrl,locations)",
    }
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    if status >= 400:
        Log.info(f"{log_tag} LinkedIn org info error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_linkedin_error(js) or {"raw": raw},
        }
    
    # Extract logo URL if present
    logo_url = None
    logo_v2 = js.get("logoV2", {})
    if logo_v2:
        # Try to get the largest logo
        original = logo_v2.get("original")
        cropped = logo_v2.get("cropped")
        if original:
            logo_url = original
        elif cropped:
            logo_url = cropped
    
    return {
        "success": True,
        "id": js.get("id"),
        "urn": org_urn,
        "name": js.get("localizedName"),
        "description": js.get("localizedDescription"),
        "vanity_name": js.get("vanityName"),
        "logo_url": logo_url,
        "website_url": js.get("websiteUrl"),
        "staff_count_range": js.get("staffCountRange"),
        "industries": js.get("industries"),
        "specialties": js.get("specialties"),
        "locations": js.get("locations"),
        "raw": js,
    }


# -------------------------------------------------------------------
# Organization Follower Count
# -------------------------------------------------------------------

def _get_organization_follower_count(
    *,
    org_id: str,
    access_token: str,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Get organization follower count.
    Uses the networkSizes endpoint.
    """
    org_urn = _make_org_urn(org_id)
    
    # Method 1: Try networkSizes endpoint
    url = f"{LINKEDIN_API_BASE}/networkSizes/{org_urn}"
    params = {"edgeType": "CompanyFollowedByMember"}
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    if status < 400:
        return {
            "success": True,
            "followers_count": js.get("firstDegreeSize", 0),
            "source": "networkSizes",
        }
    
    # Method 2: Try organizationalEntityFollowerStatistics
    url2 = f"{LINKEDIN_API_BASE}/organizationalEntityFollowerStatistics"
    params2 = {"q": "organizationalEntity", "organizationalEntity": org_urn}
    
    status2, js2, raw2 = _request_get(
        url=url2,
        headers=_auth_headers(access_token),
        params=params2,
        timeout=30,
    )
    
    if status2 < 400:
        elements = js2.get("elements", [])
        if elements:
            follower_counts = elements[0].get("followerCounts", {})
            organic = follower_counts.get("organicFollowerCount", 0)
            paid = follower_counts.get("paidFollowerCount", 0)
            return {
                "success": True,
                "followers_count": organic + paid,
                "organic_followers": organic,
                "paid_followers": paid,
                "source": "followerStatistics",
            }
    
    Log.info(f"{log_tag} LinkedIn follower count error: {status} {raw}")
    return {
        "success": False,
        "status_code": status,
        "error": _parse_linkedin_error(js) or {"raw": raw},
    }


# -------------------------------------------------------------------
# Organization Follower Statistics (Demographics)
# -------------------------------------------------------------------

def _get_organization_follower_statistics(
    *,
    org_id: str,
    access_token: str,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Get organization follower demographics/statistics.
    Requires Marketing Developer Platform access.
    """
    org_urn = _make_org_urn(org_id)
    url = f"{LINKEDIN_API_BASE}/organizationalEntityFollowerStatistics"
    
    params = {
        "q": "organizationalEntity",
        "organizationalEntity": org_urn,
    }
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    if status >= 400:
        Log.info(f"{log_tag} LinkedIn follower stats error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_linkedin_error(js) or {"raw": raw},
        }
    
    elements = js.get("elements", [])
    if not elements:
        return {
            "success": True,
            "data": None,
            "message": "No follower statistics available",
        }
    
    stats = elements[0]
    
    return {
        "success": True,
        "follower_counts": stats.get("followerCounts"),
        "follower_counts_by_association_type": stats.get("followerCountsByAssociationType"),
        "follower_counts_by_function": stats.get("followerCountsByFunction"),
        "follower_counts_by_geo_country": stats.get("followerCountsByGeoCountry"),
        "follower_counts_by_industry": stats.get("followerCountsByIndustry"),
        "follower_counts_by_seniority": stats.get("followerCountsBySeniority"),
        "follower_counts_by_staff_count_range": stats.get("followerCountsByStaffCountRange"),
        "raw": stats,
    }


# -------------------------------------------------------------------
# Organization Share Statistics (Page Analytics)
# -------------------------------------------------------------------

def _get_organization_share_statistics(
    *,
    org_id: str,
    access_token: str,
    since: Optional[str] = None,
    until: Optional[str] = None,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Get organization share/post statistics.
    Requires Marketing Developer Platform access.
    """
    org_urn = _make_org_urn(org_id)
    url = f"{LINKEDIN_API_BASE}/organizationalEntityShareStatistics"
    
    params = {
        "q": "organizationalEntity",
        "organizationalEntity": org_urn,
    }
    
    # Add time range if provided
    if since:
        since_dt = _parse_ymd(since)
        if since_dt:
            params["timeIntervals.timeGranularityType"] = "DAY"
            params["timeIntervals.timeRange.start"] = _to_unix_timestamp_ms(since_dt)
    
    if until:
        until_dt = _parse_ymd(until)
        if until_dt:
            params["timeIntervals.timeRange.end"] = _to_unix_timestamp_ms(until_dt + timedelta(days=1))
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    if status >= 400:
        Log.info(f"{log_tag} LinkedIn share stats error: {status} {raw}")
        return {
            "success": False,
            "status_code": status,
            "error": _parse_linkedin_error(js) or {"raw": raw},
        }
    
    elements = js.get("elements", [])
    if not elements:
        return {
            "success": True,
            "data": None,
            "message": "No share statistics available",
        }
    
    stats = elements[0]
    total_stats = stats.get("totalShareStatistics", {})
    
    return {
        "success": True,
        "total_statistics": {
            "share_count": total_stats.get("shareCount", 0),
            "unique_impressions_count": total_stats.get("uniqueImpressionsCount", 0),
            "click_count": total_stats.get("clickCount", 0),
            "like_count": total_stats.get("likeCount", 0),
            "comment_count": total_stats.get("commentCount", 0),
            "engagement": total_stats.get("engagement", 0),
            "impression_count": total_stats.get("impressionCount", 0),
        },
        "time_bound": stats.get("timeRange"),
        "raw": stats,
    }


# -------------------------------------------------------------------
# Organization Posts List
# -------------------------------------------------------------------

def _get_organization_posts(
    *,
    org_id: str,
    access_token: str,
    count: int = 25,
    start: int = 0,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Get list of posts for an organization.
    Uses the posts endpoint (ugcPosts or shares).
    """
    org_urn = _make_org_urn(org_id)
    
    # Try ugcPosts endpoint first (newer)
    url = f"{LINKEDIN_API_BASE}/ugcPosts"
    params = {
        "q": "authors",
        "authors": f"List({org_urn})",
        "count": min(count, 100),
        "start": start,
        "sortBy": "LAST_MODIFIED",
    }
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    if status >= 400:
        # Try shares endpoint as fallback
        url2 = f"{LINKEDIN_API_BASE}/shares"
        params2 = {
            "q": "owners",
            "owners": org_urn,
            "count": min(count, 100),
            "start": start,
            "sharesPerOwner": 1000,
        }
        
        status2, js2, raw2 = _request_get(
            url=url2,
            headers=_auth_headers(access_token),
            params=params2,
            timeout=30,
        )
        
        if status2 >= 400:
            Log.info(f"{log_tag} LinkedIn posts error: {status} {raw}")
            return {
                "success": False,
                "status_code": status,
                "error": _parse_linkedin_error(js) or {"raw": raw},
            }
        
        js = js2
    
    elements = js.get("elements", [])
    paging = js.get("paging", {})
    
    # Normalize posts
    posts = []
    for post in elements:
        post_id = post.get("id") or post.get("activity")
        
        # Extract text content
        specific_content = post.get("specificContent", {})
        share_content = specific_content.get("com.linkedin.ugc.ShareContent", {})
        share_commentary = share_content.get("shareCommentary", {})
        text = share_commentary.get("text", "")
        
        # Or from share format
        if not text:
            text_obj = post.get("text", {})
            text = text_obj.get("text", "") if isinstance(text_obj, dict) else str(text_obj)
        
        # Extract media
        media = []
        share_media = share_content.get("media", [])
        for m in share_media:
            media.append({
                "status": m.get("status"),
                "media_type": m.get("mediaType"),
                "original_url": m.get("originalUrl"),
                "title": m.get("title", {}).get("text") if isinstance(m.get("title"), dict) else m.get("title"),
                "description": m.get("description", {}).get("text") if isinstance(m.get("description"), dict) else m.get("description"),
            })
        
        posts.append({
            "id": post_id,
            "urn": post.get("id"),
            "text": text,
            "created_at": post.get("created", {}).get("time") or post.get("createdAt"),
            "last_modified_at": post.get("lastModified", {}).get("time") or post.get("lastModifiedAt"),
            "visibility": post.get("visibility", {}).get("com.linkedin.ugc.MemberNetworkVisibility") or post.get("distribution", {}).get("linkedInDistributionTarget"),
            "lifecycle_state": post.get("lifecycleState"),
            "media": media if media else None,
            "raw": post,
        })
    
    return {
        "success": True,
        "posts": posts,
        "count": len(posts),
        "pagination": {
            "start": paging.get("start", start),
            "count": paging.get("count", count),
            "total": paging.get("total"),
            "has_more": len(elements) >= count,
        },
    }


# -------------------------------------------------------------------
# Post Social Actions (Likes, Comments, Shares)
# -------------------------------------------------------------------

def _get_post_social_actions(
    *,
    post_urn: str,
    access_token: str,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Get social action counts for a post.
    """
    # URL encode the URN
    encoded_urn = requests.utils.quote(post_urn, safe='')
    
    # Get likes count
    likes_url = f"{LINKEDIN_API_BASE}/socialActions/{encoded_urn}/likes"
    likes_status, likes_js, _ = _request_get(
        url=likes_url,
        headers=_auth_headers(access_token),
        params={"count": 0},  # Just get count, not actual likes
        timeout=15,
    )
    
    likes_count = 0
    if likes_status < 400:
        likes_count = likes_js.get("paging", {}).get("total", 0)
    
    # Get comments count
    comments_url = f"{LINKEDIN_API_BASE}/socialActions/{encoded_urn}/comments"
    comments_status, comments_js, _ = _request_get(
        url=comments_url,
        headers=_auth_headers(access_token),
        params={"count": 0},
        timeout=15,
    )
    
    comments_count = 0
    if comments_status < 400:
        comments_count = comments_js.get("paging", {}).get("total", 0)
    
    return {
        "success": True,
        "likes_count": likes_count,
        "comments_count": comments_count,
    }


# -------------------------------------------------------------------
# Post Statistics (requires Marketing API)
# -------------------------------------------------------------------

def _get_post_statistics(
    *,
    post_urn: str,
    org_id: str,
    access_token: str,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Get detailed statistics for a specific post.
    Requires Marketing Developer Platform access.
    """
    org_urn = _make_org_urn(org_id)
    
    # Try shareStatistics endpoint
    url = f"{LINKEDIN_API_BASE}/organizationalEntityShareStatistics"
    params = {
        "q": "organizationalEntity",
        "organizationalEntity": org_urn,
        "shares": f"List({post_urn})",
    }
    
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    
    if status >= 400:
        Log.info(f"{log_tag} LinkedIn post stats error: {status} {raw}")
        
        # Fall back to social actions
        social_actions = _get_post_social_actions(
            post_urn=post_urn,
            access_token=access_token,
            log_tag=log_tag,
        )
        
        if social_actions.get("success"):
            return {
                "success": True,
                "metrics": {
                    "likes_count": social_actions.get("likes_count", 0),
                    "comments_count": social_actions.get("comments_count", 0),
                },
                "source": "socialActions",
                "note": "Limited metrics available. Marketing API access required for impressions/clicks.",
            }
        
        return {
            "success": False,
            "status_code": status,
            "error": _parse_linkedin_error(js) or {"raw": raw},
        }
    
    elements = js.get("elements", [])
    if not elements:
        return {
            "success": True,
            "metrics": {},
            "message": "No statistics available for this post",
        }
    
    stats = elements[0]
    total_stats = stats.get("totalShareStatistics", {})
    
    return {
        "success": True,
        "metrics": {
            "impression_count": total_stats.get("impressionCount", 0),
            "unique_impressions_count": total_stats.get("uniqueImpressionsCount", 0),
            "click_count": total_stats.get("clickCount", 0),
            "like_count": total_stats.get("likeCount", 0),
            "comment_count": total_stats.get("commentCount", 0),
            "share_count": total_stats.get("shareCount", 0),
            "engagement": total_stats.get("engagement", 0),
        },
        "source": "shareStatistics",
        "raw": stats,
    }


# -------------------------------------------------------------------
# LinkedIn: ORGANIZATION INSIGHTS (Main Endpoint)
# -------------------------------------------------------------------

@blp_linkedin_insights.route("/social/linkedin/page-insights", methods=["GET"])
class LinkedInPageInsightsResource(MethodView):
    """
    LinkedIn organization (company page) analytics.

    Query params:
      - destination_id (required): LinkedIn Organization ID
      - since (YYYY-MM-DD): Start date for share statistics
      - until (YYYY-MM-DD): End date for share statistics
      - include_demographics: "true" to include follower demographics
      - debug: "true" to include debug info
      
    Returns:
      - Organization info (name, description, logo)
      - Follower count
      - Share statistics (impressions, clicks, engagement)
      - Follower demographics (if requested and available)
      
    Required permissions:
      - r_organization_social (for basic stats)
      - rw_organization_admin (for full analytics)
      - Marketing Developer Platform access (for detailed metrics)
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[linkedin_insights][page][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Parse query parameters
        org_id = (request.args.get("destination_id") or "").strip()
        since = (request.args.get("since") or "").strip() or None
        until = (request.args.get("until") or "").strip() or None
        include_demographics = (request.args.get("include_demographics") or "").lower() == "true"
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        if not org_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
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

        # Default to last 30 days
        if not since or not until:
            since, until = _get_date_range_last_n_days(30)

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=org_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "LI_NOT_CONNECTED",
                "message": "LinkedIn organization not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "LI_TOKEN_MISSING",
                "message": "Reconnect LinkedIn - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch organization info
        org_info = _get_linkedin_organization_info(
            org_id=org_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        if not org_info.get("success"):
            error = org_info.get("error", {})
            status_code = org_info.get("status_code", 400)
            
            if _is_auth_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "LI_TOKEN_EXPIRED",
                    "message": "LinkedIn access token has expired. Please reconnect.",
                    "error": error,
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            if _is_permission_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "LI_PERMISSION_DENIED",
                    "message": "Missing permissions. Ensure you have organization admin access.",
                    "error": error,
                }), HTTP_STATUS_CODES["FORBIDDEN"]

        # Fetch follower count
        follower_info = _get_organization_follower_count(
            org_id=org_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        # Fetch share statistics
        share_stats = _get_organization_share_statistics(
            org_id=org_id,
            access_token=access_token,
            since=since,
            until=until,
            log_tag=log_tag,
        )

        # Optionally fetch follower demographics
        demographics = None
        if include_demographics:
            demographics = _get_organization_follower_statistics(
                org_id=org_id,
                access_token=access_token,
                log_tag=log_tag,
            )

        # Build response
        result = {
            "platform": PLATFORM_ID,
            "destination_id": org_id,
            "org_urn": _make_org_urn(org_id),
            "since": since,
            "until": until,

            "organization_info": {
                "id": org_info.get("id"),
                "name": org_info.get("name"),
                "description": org_info.get("description"),
                "vanity_name": org_info.get("vanity_name"),
                "logo_url": org_info.get("logo_url"),
                "website_url": org_info.get("website_url"),
                "staff_count_range": org_info.get("staff_count_range"),
                "info_error": None if org_info.get("success") else org_info.get("error"),
            },

            "summaries": {
                "followers_count": follower_info.get("followers_count") if follower_info.get("success") else None,
                "organic_followers": follower_info.get("organic_followers"),
                "paid_followers": follower_info.get("paid_followers"),
            },

            "share_statistics": share_stats.get("total_statistics") if share_stats.get("success") else None,
            "share_stats_error": None if share_stats.get("success") else share_stats.get("error"),
        }

        if include_demographics and demographics:
            result["demographics"] = {
                "by_function": demographics.get("follower_counts_by_function"),
                "by_country": demographics.get("follower_counts_by_geo_country"),
                "by_industry": demographics.get("follower_counts_by_industry"),
                "by_seniority": demographics.get("follower_counts_by_seniority"),
                "by_staff_count": demographics.get("follower_counts_by_staff_count_range"),
                "demographics_error": None if demographics.get("success") else demographics.get("error"),
            }

        if debug_mode:
            result["debug"] = {
                "follower_source": follower_info.get("source"),
                "note": "Full share statistics require Marketing Developer Platform access.",
                "required_permissions": [
                    "r_organization_social",
                    "rw_organization_admin",
                    "r_organization_followers (Marketing API)",
                ],
            }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# LinkedIn: POST LIST
# -------------------------------------------------------------------

@blp_linkedin_insights.route("/social/linkedin/post-list", methods=["GET"])
class LinkedInPostListResource(MethodView):
    """
    List posts for a LinkedIn organization.

    Query params:
      - destination_id (required): LinkedIn Organization ID
      - limit: Number of posts (default: 25, max: 100)
      - start: Offset for pagination (default: 0)
      
    Returns:
      - List of posts with text, created_at, media
      - Pagination info
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[linkedin_insights][post_list][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        org_id = (request.args.get("destination_id") or "").strip()
        if not org_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Parse limit and start
        try:
            limit = min(max(int(request.args.get("limit", 25)), 1), 100)
        except ValueError:
            limit = 25
            
        try:
            start = max(int(request.args.get("start", 0)), 0)
        except ValueError:
            start = 0

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=org_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "LI_NOT_CONNECTED",
                "message": "LinkedIn organization not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "LI_TOKEN_MISSING",
                "message": "Reconnect LinkedIn - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch posts
        posts_resp = _get_organization_posts(
            org_id=org_id,
            access_token=access_token,
            count=limit,
            start=start,
            log_tag=log_tag,
        )

        if not posts_resp.get("success"):
            error = posts_resp.get("error", {})
            status_code = posts_resp.get("status_code", 400)
            
            if _is_auth_error(error, status_code):
                return jsonify({
                    "success": False,
                    "code": "LI_TOKEN_EXPIRED",
                    "message": "LinkedIn access token has expired. Please reconnect.",
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            return jsonify({
                "success": False,
                "code": "LI_POST_LIST_ERROR",
                "message": error.get("message") or "Failed to fetch posts",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Remove raw data from posts for cleaner response
        posts = posts_resp.get("posts", [])
        for post in posts:
            post.pop("raw", None)

        result = {
            "platform": PLATFORM_ID,
            "destination_id": org_id,
            "count": len(posts),
            "limit": limit,
            "start": start,
            "posts": posts,
            "pagination": posts_resp.get("pagination"),
        }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# LinkedIn: POST INSIGHTS
# -------------------------------------------------------------------

@blp_linkedin_insights.route("/social/linkedin/post-insights", methods=["GET"])
class LinkedInPostInsightsResource(MethodView):
    """
    Post analytics for a specific LinkedIn post.

    Query params:
      - destination_id (required): LinkedIn Organization ID
      - post_id (required): LinkedIn Post ID or URN
      - debug: "true" to include debug info
      
    Returns:
      - Post metrics: impressions, clicks, likes, comments, shares
      
    Note: Full metrics require Marketing Developer Platform access.
    Basic metrics (likes, comments) available with standard permissions.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[linkedin_insights][post][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        org_id = (request.args.get("destination_id") or "").strip()
        post_id = (request.args.get("post_id") or "").strip()
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        if not org_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        if not post_id:
            return jsonify({
                "success": False,
                "message": "post_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Ensure post_id is a URN
        if not post_id.startswith("urn:li:"):
            # Try both share and ugcPost URN formats
            post_urn = f"urn:li:share:{post_id}"
        else:
            post_urn = post_id

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=org_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "LI_NOT_CONNECTED",
                "message": "LinkedIn organization not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "LI_TOKEN_MISSING",
                "message": "Reconnect LinkedIn - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch post statistics
        stats_resp = _get_post_statistics(
            post_urn=post_urn,
            org_id=org_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        if not stats_resp.get("success"):
            error = stats_resp.get("error", {})
            return jsonify({
                "success": False,
                "code": "LI_POST_INSIGHTS_ERROR",
                "message": error.get("message") or "Failed to fetch post metrics",
                "error": error,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        result = {
            "platform": PLATFORM_ID,
            "destination_id": org_id,
            "post_id": post_id,
            "post_urn": post_urn,
            "metrics": stats_resp.get("metrics"),
        }

        if debug_mode:
            result["debug"] = {
                "source": stats_resp.get("source"),
                "note": stats_resp.get("note"),
                "available_with_marketing_api": [
                    "impression_count",
                    "unique_impressions_count",
                    "click_count",
                    "engagement",
                ],
                "available_with_basic_api": [
                    "likes_count",
                    "comments_count",
                ],
            }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# LinkedIn: POST DETAILS
# -------------------------------------------------------------------

@blp_linkedin_insights.route("/social/linkedin/post-details", methods=["GET"])
class LinkedInPostDetailsResource(MethodView):
    """
    Get detailed information for a specific LinkedIn post.

    Query params:
      - destination_id (required): LinkedIn Organization ID
      - post_id (required): LinkedIn Post ID or URN
      
    Returns full post data including text, media, and basic engagement.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[linkedin_insights][post_details][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        org_id = (request.args.get("destination_id") or "").strip()
        post_id = (request.args.get("post_id") or "").strip()

        if not org_id:
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
            destination_id=org_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "LI_NOT_CONNECTED",
                "message": "LinkedIn organization not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "LI_TOKEN_MISSING",
                "message": "Reconnect LinkedIn - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Determine if it's a URN or ID
        if post_id.startswith("urn:li:ugcPost:"):
            url = f"{LINKEDIN_API_BASE}/ugcPosts/{requests.utils.quote(post_id, safe='')}"
        elif post_id.startswith("urn:li:share:"):
            url = f"{LINKEDIN_API_BASE}/shares/{requests.utils.quote(post_id, safe='')}"
        else:
            # Try ugcPost first
            url = f"{LINKEDIN_API_BASE}/ugcPosts/urn:li:ugcPost:{post_id}"

        status, js, raw = _request_get(
            url=url,
            headers=_auth_headers(access_token),
            params={},
            timeout=30,
        )

        if status >= 400:
            # Try share endpoint
            url2 = f"{LINKEDIN_API_BASE}/shares/urn:li:share:{post_id}"
            status2, js2, raw2 = _request_get(
                url=url2,
                headers=_auth_headers(access_token),
                params={},
                timeout=30,
            )
            
            if status2 >= 400:
                error = _parse_linkedin_error(js) or {"raw": raw}
                return jsonify({
                    "success": False,
                    "code": "LI_POST_DETAILS_ERROR",
                    "message": error.get("message") or "Failed to fetch post details",
                    "error": error,
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            js = js2

        # Parse post data
        specific_content = js.get("specificContent", {})
        share_content = specific_content.get("com.linkedin.ugc.ShareContent", {})
        share_commentary = share_content.get("shareCommentary", {})
        
        text = share_commentary.get("text", "")
        if not text:
            text_obj = js.get("text", {})
            text = text_obj.get("text", "") if isinstance(text_obj, dict) else str(text_obj or "")

        # Extract media
        media = []
        share_media = share_content.get("media", [])
        for m in share_media:
            media.append({
                "status": m.get("status"),
                "media_type": m.get("mediaType"),
                "original_url": m.get("originalUrl"),
                "title": m.get("title", {}).get("text") if isinstance(m.get("title"), dict) else m.get("title"),
                "description": m.get("description", {}).get("text") if isinstance(m.get("description"), dict) else m.get("description"),
            })

        # Get social actions
        post_urn = js.get("id") or f"urn:li:share:{post_id}"
        social_actions = _get_post_social_actions(
            post_urn=post_urn,
            access_token=access_token,
            log_tag=log_tag,
        )

        post_data = {
            "id": js.get("id"),
            "text": text,
            "created_at": js.get("created", {}).get("time") or js.get("createdAt"),
            "last_modified_at": js.get("lastModified", {}).get("time") or js.get("lastModifiedAt"),
            "author": js.get("author"),
            "visibility": js.get("visibility"),
            "lifecycle_state": js.get("lifecycleState"),
            "media": media if media else None,
            "metrics": {
                "likes_count": social_actions.get("likes_count", 0),
                "comments_count": social_actions.get("comments_count", 0),
            },
        }

        result = {
            "platform": PLATFORM_ID,
            "post": post_data,
        }

        return jsonify({
            "success": True,
            "data": result,
        }), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# LinkedIn: DISCOVER METRICS (Diagnostic)
# -------------------------------------------------------------------

@blp_linkedin_insights.route("/social/linkedin/discover-metrics", methods=["GET"])
class LinkedInDiscoverMetricsResource(MethodView):
    """
    Diagnostic endpoint to test what your token can access.

    Query params:
      - destination_id (required): LinkedIn Organization ID
      
    Returns:
      - Organization lookup result
      - Follower count availability
      - Share statistics availability
      - API access level assessment
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[linkedin_insights][discover][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({
                "success": False,
                "message": "Unauthorized",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        org_id = (request.args.get("destination_id") or "").strip()
        if not org_id:
            return jsonify({
                "success": False,
                "message": "destination_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_ID,
            destination_id=org_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "LI_NOT_CONNECTED",
                "message": "LinkedIn organization not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return jsonify({
                "success": False,
                "code": "LI_TOKEN_MISSING",
                "message": "Reconnect LinkedIn - no access token found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Test organization lookup
        org_info = _get_linkedin_organization_info(
            org_id=org_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        # Test follower count
        follower_info = _get_organization_follower_count(
            org_id=org_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        # Test share statistics
        share_stats = _get_organization_share_statistics(
            org_id=org_id,
            access_token=access_token,
            since=None,
            until=None,
            log_tag=log_tag,
        )

        # Test follower demographics
        demographics = _get_organization_follower_statistics(
            org_id=org_id,
            access_token=access_token,
            log_tag=log_tag,
        )

        # Test posts list
        posts_info = _get_organization_posts(
            org_id=org_id,
            access_token=access_token,
            count=5,
            start=0,
            log_tag=log_tag,
        )

        # Assess access level
        has_basic_access = org_info.get("success", False)
        has_follower_access = follower_info.get("success", False)
        has_share_stats = share_stats.get("success", False) and share_stats.get("total_statistics")
        has_demographics = demographics.get("success", False) and demographics.get("follower_counts_by_function")
        has_posts_access = posts_info.get("success", False)

        access_level = "none"
        if has_basic_access:
            access_level = "basic"
        if has_basic_access and has_follower_access and has_posts_access:
            access_level = "standard"
        if has_share_stats or has_demographics:
            access_level = "marketing"

        return jsonify({
            "success": True,
            "data": {
                "platform": PLATFORM_ID,
                "destination_id": org_id,
                "org_urn": _make_org_urn(org_id),
                
                "probes": {
                    "organization_lookup": {
                        "success": org_info.get("success", False),
                        "name": org_info.get("name") if org_info.get("success") else None,
                        "error": org_info.get("error") if not org_info.get("success") else None,
                    },
                    "follower_count": {
                        "success": follower_info.get("success", False),
                        "count": follower_info.get("followers_count") if follower_info.get("success") else None,
                        "source": follower_info.get("source"),
                        "error": follower_info.get("error") if not follower_info.get("success") else None,
                    },
                    "share_statistics": {
                        "success": share_stats.get("success", False) and bool(share_stats.get("total_statistics")),
                        "has_data": bool(share_stats.get("total_statistics")),
                        "error": share_stats.get("error") if not share_stats.get("success") else None,
                    },
                    "follower_demographics": {
                        "success": demographics.get("success", False) and bool(demographics.get("follower_counts_by_function")),
                        "has_data": bool(demographics.get("follower_counts_by_function")),
                        "error": demographics.get("error") if not demographics.get("success") else None,
                    },
                    "posts_list": {
                        "success": posts_info.get("success", False),
                        "count": len(posts_info.get("posts", [])) if posts_info.get("success") else 0,
                        "error": posts_info.get("error") if not posts_info.get("success") else None,
                    },
                },
                
                "access_level": access_level,
                "recommendation": (
                    "Full Marketing API access available!" if access_level == "marketing"
                    else "Standard access available. Apply for Marketing Developer Platform for detailed analytics."
                    if access_level == "standard"
                    else "Basic access only. Ensure you have organization admin permissions."
                    if access_level == "basic"
                    else "No access. Check organization ID and token permissions."
                ),
                
                "notes": [
                    "LinkedIn requires organization admin access for most analytics.",
                    "Full share statistics require Marketing Developer Platform approval.",
                    "Follower demographics require Marketing Developer Platform approval.",
                    "Rate limit: ~100 requests per day for most endpoints.",
                ],
                
                "required_permissions": {
                    "basic": ["r_organization_social"],
                    "standard": ["r_organization_social", "rw_organization_admin"],
                    "marketing": [
                        "r_organization_social",
                        "rw_organization_admin",
                        "r_ads_reporting",
                        "r_organization_followers",
                    ],
                },
            },
        }), HTTP_STATUS_CODES["OK"]

# | `/social/linkedin/page-insights` | Organization/page metrics | `destination_id` |
# | `/social/linkedin/post-list` | List organization posts | `destination_id` |
# | `/social/linkedin/post-insights` | Single post metrics | `destination_id`, `post_id` |
# | `/social/linkedin/post-details` | Full post details | `destination_id`, `post_id` |
# | `/social/linkedin/discover-metrics` | Diagnostic endpoint | `destination_id` |



# # app/resources/social/linkedin_insights.py
# #
# # LinkedIn analytics using STORED SocialAccount token
# #
# # What you can reliably get with LinkedIn Marketing/Organization APIs (depending on app access + permissions):
# # - Organization info: localizedName, vanityName, logo, etc.
# # - Followers: organizationalEntityFollowerStatistics (aggregates + time buckets)
# # - Page stats: organizationPageStatistics (page views, clicks, etc. — varies by product access)
# # - Posts list: ugcPosts (org authored posts)
# # - Engagement counts: socialActions (likes/comments counts) for a given post URN (best-effort)
# #
# # Important notes:
# # - LinkedIn APIs are gated. Many endpoints require your app to be approved for Marketing/Community Management use-cases.
# # - 403 is common if your app doesn’t have access to the product or missing permissions.
# # - 401 means token expired/invalid. If you store refresh_token, you can auto-refresh (if your app supports it).
# #
# # Required env vars for refresh (if you want auto-refresh):
# #   LINKEDIN_CLIENT_ID
# #   LINKEDIN_CLIENT_SECRET
# #
# # Token permissions/scopes vary by endpoint. Common ones include:
# #   r_organization_social, rw_organization_admin, w_organization_social, r_basicprofile (legacy), etc.

# from __future__ import annotations

# from datetime import datetime, timedelta, timezone
# from typing import Any, Dict, List, Optional, Tuple
# from urllib.parse import quote

# import os
# import requests
# from flask import g, jsonify, request
# from flask.views import MethodView
# from flask_smorest import Blueprint

# from ....constants.service_code import HTTP_STATUS_CODES
# from ....models.social.social_account import SocialAccount
# from ....utils.logger import Log
# from ...doseal.admin.admin_business_resource import token_required


# # -------------------------------------------------------------------
# # Blueprint
# # -------------------------------------------------------------------

# blp_linkedin_insights = Blueprint(
#     "linkedin_insights",
#     __name__,
# )

# # LinkedIn API base (v2)
# LI_API_BASE = "https://api.linkedin.com/v2"

# # LinkedIn OAuth token endpoint
# LI_OAUTH_TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"

# # Platform identifier - keep consistent with what you store in SocialAccount.platform
# PLATFORM_ID = "linkedin"


# # -------------------------------------------------------------------
# # Helpers
# # -------------------------------------------------------------------

# def _pick(d: Dict[str, Any], *keys, default=None):
#     if not isinstance(d, dict):
#         return default
#     for k in keys:
#         if k in d:
#             return d.get(k)
#     return default


# def _parse_ymd(s: Optional[str]) -> Optional[datetime]:
#     if not s:
#         return None
#     try:
#         return datetime.strptime(s, "%Y-%m-%d")
#     except ValueError:
#         return None


# def _fmt_ymd(dt: datetime) -> str:
#     return dt.strftime("%Y-%m-%d")


# def _get_date_range_last_n_days(n: int = 30) -> Tuple[str, str]:
#     until = datetime.now(timezone.utc)
#     since = until - timedelta(days=n)
#     return _fmt_ymd(since), _fmt_ymd(until)


# def _to_ms_epoch(dt: datetime) -> int:
#     if dt.tzinfo is None:
#         dt = dt.replace(tzinfo=timezone.utc)
#     return int(dt.timestamp() * 1000)


# def _auth_headers(access_token: str) -> Dict[str, str]:
#     return {
#         "Authorization": f"Bearer {access_token}",
#         "Accept": "application/json",
#         "X-Restli-Protocol-Version": "2.0.0",
#     }


# def _parse_li_error(payload: Dict[str, Any], status_code: int, raw_text: str) -> Dict[str, Any]:
#     """
#     LinkedIn errors often look like:
#       {"message":"...","status":403,"serviceErrorCode":100,...}
#     or sometimes {"error":"invalid_token","error_description":"..."}
#     """
#     if not isinstance(payload, dict):
#         payload = {}
#     return {
#         "status": status_code,
#         "message": payload.get("message") or payload.get("error_description") or payload.get("error") or "Request failed",
#         "serviceErrorCode": payload.get("serviceErrorCode"),
#         "code": payload.get("code"),
#         "details": payload.get("details"),
#         "raw": raw_text[:2000] if raw_text else None,
#     }


# def _is_auth_error(status_code: int, err: Dict[str, Any]) -> bool:
#     return status_code in (401, 403) and (
#         "token" in str(err.get("message", "")).lower()
#         or "unauthorized" in str(err.get("message", "")).lower()
#         or status_code == 401
#     )


# def _request_get(
#     *,
#     url: str,
#     access_token: str,
#     params: Optional[Dict[str, Any]] = None,
#     timeout: int = 30,
# ) -> Tuple[int, Dict[str, Any], str]:
#     r = requests.get(url, headers=_auth_headers(access_token), params=params, timeout=timeout)
#     text = r.text or ""
#     try:
#         js = r.json() if text else {}
#     except Exception:
#         js = {}
#     return r.status_code, js, text


# def _request_get_with_refresh(
#     *,
#     url: str,
#     params: Optional[Dict[str, Any]],
#     access_token: str,
#     refresh_token: Optional[str],
#     log_tag: str,
# ) -> Tuple[int, Dict[str, Any], str, Optional[str]]:
#     """
#     GET, and if 401/403 auth-ish error, attempt refresh (if refresh_token exists) and retry once.
#     Returns: (status, json, raw_text, new_access_token_if_refreshed)
#     """
#     status, js, raw = _request_get(url=url, access_token=access_token, params=params, timeout=30)
#     if status < 400:
#         return status, js, raw, None

#     err = _parse_li_error(js or {}, status, raw)
#     if refresh_token and _is_auth_error(status, err):
#         refreshed = _refresh_access_token(refresh_token=refresh_token, log_tag=log_tag)
#         if refreshed.get("success") and refreshed.get("access_token"):
#             new_token = refreshed["access_token"]
#             status2, js2, raw2 = _request_get(url=url, access_token=new_token, params=params, timeout=30)
#             return status2, js2, raw2, new_token

#     return status, js, raw, None


# def _refresh_access_token(*, refresh_token: str, log_tag: str) -> Dict[str, Any]:
#     """
#     Refresh LinkedIn access token (only works if your LinkedIn app + token supports refresh tokens).
#     Requires env:
#       LINKEDIN_CLIENT_ID
#       LINKEDIN_CLIENT_SECRET
#     """
#     client_id = (os.getenv("LINKEDIN_CLIENT_ID") or "").strip()
#     client_secret = (os.getenv("LINKEDIN_CLIENT_SECRET") or "").strip()

#     if not client_id or not client_secret:
#         return {
#             "success": False,
#             "error": "Missing LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET in env",
#         }

#     data = {
#         "grant_type": "refresh_token",
#         "refresh_token": refresh_token,
#         "client_id": client_id,
#         "client_secret": client_secret,
#     }

#     try:
#         r = requests.post(LI_OAUTH_TOKEN_URL, data=data, timeout=30)
#         txt = r.text or ""
#         try:
#             js = r.json() if txt else {}
#         except Exception:
#             js = {}

#         if r.status_code >= 400:
#             Log.info(f"{log_tag} LinkedIn refresh failed: {r.status_code} {txt}")
#             return {
#                 "success": False,
#                 "status_code": r.status_code,
#                 "error": _parse_li_error(js or {}, r.status_code, txt),
#             }

#         return {
#             "success": True,
#             "access_token": js.get("access_token"),
#             "expires_in": js.get("expires_in"),
#             "raw": js,
#         }
#     except Exception as e:
#         Log.error(f"{log_tag} LinkedIn refresh error: {e}")
#         return {"success": False, "error": str(e)}


# def _store_new_access_token_if_possible(
#     *,
#     acct: Dict[str, Any],
#     new_access_token: str,
#     log_tag: str,
# ) -> None:
#     """
#     Best-effort: if your SocialAccount model has an updater, use it.
#     Otherwise, we just proceed without persisting.
#     """
#     try:
#         if hasattr(SocialAccount, "update_destination_token"):
#             SocialAccount.update_destination_token(
#                 _id=acct.get("_id"),
#                 access_token_plain=new_access_token,
#             )
#         elif hasattr(SocialAccount, "update_access_token"):
#             SocialAccount.update_access_token(
#                 _id=acct.get("_id"),
#                 access_token_plain=new_access_token,
#             )
#     except Exception as e:
#         Log.info(f"{log_tag} could not persist refreshed token: {e}")


# def _org_urn(org_id: str) -> str:
#     org_id = (org_id or "").strip()
#     return f"urn:li:organization:{org_id}"


# def _safe_int(x: Any, default: int = 0) -> int:
#     try:
#         if isinstance(x, bool):
#             return default
#         return int(x)
#     except Exception:
#         return default


# # -------------------------------------------------------------------
# # LinkedIn: Organization Info
# # -------------------------------------------------------------------

# def _get_linkedin_org_info(
#     *,
#     org_id: str,
#     access_token: str,
#     refresh_token: Optional[str],
#     log_tag: str,
# ) -> Dict[str, Any]:
#     """
#     GET /organizations/{id}?projection=...
#     Projection fields vary. We keep it simple.
#     """
#     url = f"{LI_API_BASE}/organizations/{org_id}"
#     params = {
#         "projection": "(id,localizedName,vanityName,localizedDescription,websiteUrl,logoV2(original~:playableStreams))"
#     }

#     status, js, raw, new_tok = _request_get_with_refresh(
#         url=url,
#         params=params,
#         access_token=access_token,
#         refresh_token=refresh_token,
#         log_tag=log_tag,
#     )

#     if status >= 400:
#         return {
#             "success": False,
#             "status_code": status,
#             "error": _parse_li_error(js or {}, status, raw),
#             "refreshed_access_token": new_tok,
#         }

#     logo = None
#     try:
#         logo = (
#             (js or {})
#             .get("logoV2", {})
#             .get("original~", {})
#             .get("elements", [{}])[0]
#             .get("identifiers", [{}])[0]
#             .get("identifier")
#         )
#     except Exception:
#         logo = None

#     return {
#         "success": True,
#         "id": js.get("id"),
#         "name": js.get("localizedName"),
#         "vanityName": js.get("vanityName"),
#         "description": js.get("localizedDescription"),
#         "websiteUrl": js.get("websiteUrl"),
#         "logo": logo,
#         "raw": js,
#         "refreshed_access_token": new_tok,
#     }


# # -------------------------------------------------------------------
# # LinkedIn: Organization Followers Statistics
# # -------------------------------------------------------------------

# def _get_org_follower_stats(
#     *,
#     org_id: str,
#     access_token: str,
#     refresh_token: Optional[str],
#     log_tag: str,
#     since: Optional[str],
#     until: Optional[str],
# ) -> Dict[str, Any]:
#     """
#     GET /organizationalEntityFollowerStatistics?q=organizationalEntity&organizationalEntity=urn:li:organization:{id}
#     Optionally you can pass timeIntervals, but many apps just read aggregates.
#     """
#     url = f"{LI_API_BASE}/organizationalEntityFollowerStatistics"
#     params: Dict[str, Any] = {
#         "q": "organizationalEntity",
#         "organizationalEntity": _org_urn(org_id),
#     }

#     # Best-effort time range: LinkedIn uses timeIntervals with ms epoch in some variants.
#     # We do not force it here because it can be picky by product access.
#     if since and until:
#         sd = _parse_ymd(since)
#         ud = _parse_ymd(until)
#         if sd and ud:
#             params["timeIntervals.timeRange.start"] = _to_ms_epoch(sd.replace(tzinfo=timezone.utc))
#             params["timeIntervals.timeRange.end"] = _to_ms_epoch((ud + timedelta(days=1)).replace(tzinfo=timezone.utc))

#     status, js, raw, new_tok = _request_get_with_refresh(
#         url=url,
#         params=params,
#         access_token=access_token,
#         refresh_token=refresh_token,
#         log_tag=log_tag,
#     )

#     if status >= 400:
#         return {
#             "success": False,
#             "status_code": status,
#             "error": _parse_li_error(js or {}, status, raw),
#             "refreshed_access_token": new_tok,
#         }

#     elements = (js or {}).get("elements") or []
#     # Try to extract a simple summary (varies by response shape)
#     total_followers = None
#     try:
#         # some responses include followerCounts in a nested structure
#         # keep it best-effort
#         for el in elements:
#             fc = el.get("followerCounts") or {}
#             if isinstance(fc, dict) and fc:
#                 # pick any numeric value
#                 for _, v in fc.items():
#                     if isinstance(v, (int, float)):
#                         total_followers = v
#                         break
#             if total_followers is not None:
#                 break
#     except Exception:
#         total_followers = None

#     return {
#         "success": True,
#         "elements": elements,
#         "summary": {
#             "total_followers_best_effort": total_followers,
#             "count": len(elements),
#         },
#         "raw": js,
#         "refreshed_access_token": new_tok,
#     }


# # -------------------------------------------------------------------
# # LinkedIn: Organization Page Statistics
# # -------------------------------------------------------------------

# def _get_org_page_stats(
#     *,
#     org_id: str,
#     access_token: str,
#     refresh_token: Optional[str],
#     log_tag: str,
#     since: Optional[str],
#     until: Optional[str],
# ) -> Dict[str, Any]:
#     """
#     GET /organizationPageStatistics?q=organization&organization=urn:li:organization:{id}
#     Time filtering can be added similarly, but can be access-sensitive.
#     """
#     url = f"{LI_API_BASE}/organizationPageStatistics"
#     params: Dict[str, Any] = {
#         "q": "organization",
#         "organization": _org_urn(org_id),
#     }

#     if since and until:
#         sd = _parse_ymd(since)
#         ud = _parse_ymd(until)
#         if sd and ud:
#             params["timeIntervals.timeRange.start"] = _to_ms_epoch(sd.replace(tzinfo=timezone.utc))
#             params["timeIntervals.timeRange.end"] = _to_ms_epoch((ud + timedelta(days=1)).replace(tzinfo=timezone.utc))

#     status, js, raw, new_tok = _request_get_with_refresh(
#         url=url,
#         params=params,
#         access_token=access_token,
#         refresh_token=refresh_token,
#         log_tag=log_tag,
#     )

#     if status >= 400:
#         return {
#             "success": False,
#             "status_code": status,
#             "error": _parse_li_error(js or {}, status, raw),
#             "refreshed_access_token": new_tok,
#         }

#     elements = (js or {}).get("elements") or []
#     return {
#         "success": True,
#         "elements": elements,
#         "summary": {
#             "count": len(elements),
#         },
#         "raw": js,
#         "refreshed_access_token": new_tok,
#     }


# # -------------------------------------------------------------------
# # LinkedIn: Posts list (UGC)
# # -------------------------------------------------------------------

# def _fetch_org_posts(
#     *,
#     org_id: str,
#     access_token: str,
#     refresh_token: Optional[str],
#     log_tag: str,
#     count: int = 25,
#     start: int = 0,
# ) -> Dict[str, Any]:
#     """
#     GET /ugcPosts?q=authors&authors=List(urn:li:organization:{id})&sortBy=LAST_MODIFIED&count=...&start=...
#     """
#     url = f"{LI_API_BASE}/ugcPosts"
#     params = {
#         "q": "authors",
#         "authors": f"List({_org_urn(org_id)})",
#         "sortBy": "LAST_MODIFIED",
#         "count": max(1, min(int(count), 50)),
#         "start": max(0, int(start)),
#     }

#     status, js, raw, new_tok = _request_get_with_refresh(
#         url=url,
#         params=params,
#         access_token=access_token,
#         refresh_token=refresh_token,
#         log_tag=log_tag,
#     )

#     if status >= 400:
#         return {
#             "success": False,
#             "status_code": status,
#             "error": _parse_li_error(js or {}, status, raw),
#             "refreshed_access_token": new_tok,
#         }

#     elements = (js or {}).get("elements") or []
#     paging = (js or {}).get("paging") or {}

#     posts: List[Dict[str, Any]] = []
#     for el in elements:
#         urn = el.get("id")  # urn:li:ugcPost:...
#         created_at = None
#         try:
#             created_at = el.get("created", {}).get("time")
#         except Exception:
#             created_at = None

#         text = None
#         try:
#             specific = el.get("specificContent", {})
#             share = specific.get("com.linkedin.ugc.ShareContent", {})
#             commentary = share.get("shareCommentary", {})
#             text = commentary.get("text")
#         except Exception:
#             text = None

#         posts.append({
#             "urn": urn,
#             "created_at_ms": created_at,
#             "lifecycleState": el.get("lifecycleState"),
#             "visibility": el.get("visibility"),
#             "text": text,
#             "raw": el,
#         })

#     return {
#         "success": True,
#         "posts": posts,
#         "paging": paging,
#         "refreshed_access_token": new_tok,
#     }


# # -------------------------------------------------------------------
# # LinkedIn: socialActions (likes/comments counts) best-effort
# # -------------------------------------------------------------------

# def _get_social_actions(
#     *,
#     post_urn: str,
#     access_token: str,
#     refresh_token: Optional[str],
#     log_tag: str,
# ) -> Dict[str, Any]:
#     """
#     GET /socialActions/{encodedUrn}
#     Example: /socialActions/urn%3Ali%3AugcPost%3A123
#     """
#     if not post_urn:
#         return {"success": False, "status_code": 400, "error": {"message": "post_urn is required"}}

#     encoded = quote(post_urn, safe="")
#     url = f"{LI_API_BASE}/socialActions/{encoded}"

#     status, js, raw, new_tok = _request_get_with_refresh(
#         url=url,
#         params=None,
#         access_token=access_token,
#         refresh_token=refresh_token,
#         log_tag=log_tag,
#     )

#     if status >= 400:
#         return {
#             "success": False,
#             "status_code": status,
#             "error": _parse_li_error(js or {}, status, raw),
#             "refreshed_access_token": new_tok,
#         }

#     # Typical fields: likesSummary.totalCount, commentsSummary.totalCount
#     likes = _safe_int(_pick(js or {}, "likesSummary", default={}).get("totalCount") if isinstance((js or {}).get("likesSummary"), dict) else None, 0)
#     comments = _safe_int(_pick(js or {}, "commentsSummary", default={}).get("totalCount") if isinstance((js or {}).get("commentsSummary"), dict) else None, 0)

#     return {
#         "success": True,
#         "metrics": {
#             "likes_count": likes,
#             "comments_count": comments,
#         },
#         "raw": js,
#         "refreshed_access_token": new_tok,
#     }


# # -------------------------------------------------------------------
# # LINKEDIN: ACCOUNT / ORG INSIGHTS — Main Endpoint
# # -------------------------------------------------------------------

# @blp_linkedin_insights.route("/social/linkedin/account-insights", methods=["GET"])
# class LinkedInAccountInsightsResource(MethodView):
#     """
#     LinkedIn Organization analytics using stored SocialAccount token.

#     Query params:
#       - destination_id (required): LinkedIn Organization ID (numeric string)
#       - since (YYYY-MM-DD) optional
#       - until (YYYY-MM-DD) optional
#       - debug: "true" includes extra diagnostics

#     Returns:
#       - Organization info
#       - Followers statistics (best effort)
#       - Page statistics (best effort)
#     """

#     @token_required
#     def get(self):
#         client_ip = request.remote_addr
#         log_tag = f"[linkedin_insights][account][{client_ip}]"

#         user = g.get("current_user") or {}
#         business_id = str(user.get("business_id") or "")
#         user__id = str(user.get("_id") or "")

#         if not business_id or not user__id:
#             return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

#         org_id = (request.args.get("destination_id") or "").strip()
#         since = (request.args.get("since") or "").strip() or None
#         until = (request.args.get("until") or "").strip() or None
#         debug_mode = (request.args.get("debug") or "").lower() == "true"

#         if not org_id:
#             return jsonify({"success": False, "message": "destination_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

#         if since and not _parse_ymd(since):
#             return jsonify({"success": False, "message": "Invalid 'since' date format. Use YYYY-MM-DD"}), HTTP_STATUS_CODES["BAD_REQUEST"]
#         if until and not _parse_ymd(until):
#             return jsonify({"success": False, "message": "Invalid 'until' date format. Use YYYY-MM-DD"}), HTTP_STATUS_CODES["BAD_REQUEST"]

#         if since and until:
#             sd = _parse_ymd(since)
#             ud = _parse_ymd(until)
#             if sd and ud and sd > ud:
#                 return jsonify({"success": False, "message": "'since' must be before 'until'"}), HTTP_STATUS_CODES["BAD_REQUEST"]

#         if not since or not until:
#             since, until = _get_date_range_last_n_days(30)

#         # Load stored SocialAccount
#         acct = SocialAccount.get_destination(
#             business_id=business_id,
#             user__id=user__id,
#             platform=PLATFORM_ID,
#             destination_id=org_id,
#         )

#         if not acct:
#             return jsonify({
#                 "success": False,
#                 "code": "LI_NOT_CONNECTED",
#                 "message": "LinkedIn organization not connected",
#             }), HTTP_STATUS_CODES["NOT_FOUND"]

#         access_token = acct.get("access_token_plain") or acct.get("access_token")
#         refresh_token = acct.get("refresh_token_plain") or acct.get("refresh_token")

#         if not access_token:
#             return jsonify({
#                 "success": False,
#                 "code": "LI_TOKEN_MISSING",
#                 "message": "Reconnect LinkedIn - no access token found",
#             }), HTTP_STATUS_CODES["BAD_REQUEST"]

#         # 1) Org info
#         org_info = _get_linkedin_org_info(
#             org_id=org_id,
#             access_token=access_token,
#             refresh_token=refresh_token,
#             log_tag=log_tag,
#         )
#         if org_info.get("refreshed_access_token"):
#             access_token = org_info["refreshed_access_token"]
#             _store_new_access_token_if_possible(acct=acct, new_access_token=access_token, log_tag=log_tag)

#         if not org_info.get("success"):
#             err = org_info.get("error") or {}
#             status = org_info.get("status_code", 400)
#             code = "LI_ORG_LOOKUP_ERROR"
#             if status in (401, 403):
#                 code = "LI_TOKEN_EXPIRED" if status == 401 else "LI_PERMISSION_DENIED"
#             return jsonify({
#                 "success": False,
#                 "code": code,
#                 "message": err.get("message") or "Failed to fetch organization info",
#                 "error": err,
#             }), HTTP_STATUS_CODES["UNAUTHORIZED"] if status == 401 else HTTP_STATUS_CODES["FORBIDDEN"] if status == 403 else HTTP_STATUS_CODES["BAD_REQUEST"]

#         # 2) Followers stats
#         follower_stats = _get_org_follower_stats(
#             org_id=org_id,
#             access_token=access_token,
#             refresh_token=refresh_token,
#             log_tag=log_tag,
#             since=since,
#             until=until,
#         )
#         if follower_stats.get("refreshed_access_token"):
#             access_token = follower_stats["refreshed_access_token"]
#             _store_new_access_token_if_possible(acct=acct, new_access_token=access_token, log_tag=log_tag)

#         # 3) Page stats
#         page_stats = _get_org_page_stats(
#             org_id=org_id,
#             access_token=access_token,
#             refresh_token=refresh_token,
#             log_tag=log_tag,
#             since=since,
#             until=until,
#         )
#         if page_stats.get("refreshed_access_token"):
#             access_token = page_stats["refreshed_access_token"]
#             _store_new_access_token_if_possible(acct=acct, new_access_token=access_token, log_tag=log_tag)

#         result = {
#             "platform": PLATFORM_ID,
#             "destination_id": org_id,
#             "destination_urn": _org_urn(org_id),
#             "since": since,
#             "until": until,

#             "org_info": {
#                 "id": org_info.get("id"),
#                 "name": org_info.get("name"),
#                 "vanityName": org_info.get("vanityName"),
#                 "logo": org_info.get("logo"),
#                 "websiteUrl": org_info.get("websiteUrl"),
#                 "description": org_info.get("description"),
#                 "info_error": None,
#             },

#             "followers_statistics": {
#                 "success": follower_stats.get("success"),
#                 "summary": follower_stats.get("summary"),
#                 "elements": follower_stats.get("elements") if follower_stats.get("success") else None,
#                 "error": follower_stats.get("error") if not follower_stats.get("success") else None,
#             },

#             "page_statistics": {
#                 "success": page_stats.get("success"),
#                 "summary": page_stats.get("summary"),
#                 "elements": page_stats.get("elements") if page_stats.get("success") else None,
#                 "error": page_stats.get("error") if not page_stats.get("success") else None,
#             },
#         }

#         if debug_mode:
#             result["debug"] = {
#                 "note": "LinkedIn analytics endpoints are gated. 403 usually means missing product access or scopes.",
#                 "stored_destination_name": acct.get("destination_name"),
#                 "has_refresh_token": bool(refresh_token),
#             }

#         return jsonify({"success": True, "data": result}), HTTP_STATUS_CODES["OK"]


# # -------------------------------------------------------------------
# # LINKEDIN: POST LIST — Organization posts
# # -------------------------------------------------------------------

# @blp_linkedin_insights.route("/social/linkedin/post-list", methods=["GET"])
# class LinkedInPostListResource(MethodView):
#     """
#     List LinkedIn organization posts (UGC).

#     Query params:
#       - destination_id (required): Organization ID
#       - limit: default 25 (max 50)
#       - start: pagination start offset
#       - debug: "true" includes paging object
#     """

#     @token_required
#     def get(self):
#         client_ip = request.remote_addr
#         log_tag = f"[linkedin_insights][post_list][{client_ip}]"

#         user = g.get("current_user") or {}
#         business_id = str(user.get("business_id") or "")
#         user__id = str(user.get("_id") or "")

#         if not business_id or not user__id:
#             return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

#         org_id = (request.args.get("destination_id") or "").strip()
#         limit_raw = (request.args.get("limit") or "25").strip()
#         start_raw = (request.args.get("start") or "0").strip()
#         debug_mode = (request.args.get("debug") or "").lower() == "true"

#         if not org_id:
#             return jsonify({"success": False, "message": "destination_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

#         try:
#             limit = max(1, min(int(limit_raw), 50))
#         except Exception:
#             limit = 25
#         try:
#             start = max(0, int(start_raw))
#         except Exception:
#             start = 0

#         acct = SocialAccount.get_destination(
#             business_id=business_id,
#             user__id=user__id,
#             platform=PLATFORM_ID,
#             destination_id=org_id,
#         )
#         if not acct:
#             return jsonify({
#                 "success": False,
#                 "code": "LI_NOT_CONNECTED",
#                 "message": "LinkedIn organization not connected",
#             }), HTTP_STATUS_CODES["NOT_FOUND"]

#         access_token = acct.get("access_token_plain") or acct.get("access_token")
#         refresh_token = acct.get("refresh_token_plain") or acct.get("refresh_token")
#         if not access_token:
#             return jsonify({
#                 "success": False,
#                 "code": "LI_TOKEN_MISSING",
#                 "message": "Reconnect LinkedIn - no access token found",
#             }), HTTP_STATUS_CODES["BAD_REQUEST"]

#         resp = _fetch_org_posts(
#             org_id=org_id,
#             access_token=access_token,
#             refresh_token=refresh_token,
#             log_tag=log_tag,
#             count=limit,
#             start=start,
#         )

#         if resp.get("refreshed_access_token"):
#             access_token = resp["refreshed_access_token"]
#             _store_new_access_token_if_possible(acct=acct, new_access_token=access_token, log_tag=log_tag)

#         if not resp.get("success"):
#             err = resp.get("error") or {}
#             status = resp.get("status_code", 400)
#             code = "LI_POST_LIST_ERROR"
#             if status == 401:
#                 code = "LI_TOKEN_EXPIRED"
#             elif status == 403:
#                 code = "LI_PERMISSION_DENIED"
#             return jsonify({
#                 "success": False,
#                 "code": code,
#                 "message": err.get("message") or "Failed to fetch post list",
#                 "error": err,
#                 "debug": {
#                     "limit": limit,
#                     "start": start,
#                 } if debug_mode else None,
#             }), HTTP_STATUS_CODES["UNAUTHORIZED"] if status == 401 else HTTP_STATUS_CODES["FORBIDDEN"] if status == 403 else HTTP_STATUS_CODES["BAD_REQUEST"]

#         result = {
#             "platform": PLATFORM_ID,
#             "destination_id": org_id,
#             "count": len(resp.get("posts") or []),
#             "limit": limit,
#             "start": start,
#             "posts": resp.get("posts") or [],
#         }

#         if debug_mode:
#             result["debug"] = {
#                 "paging": resp.get("paging"),
#                 "note": "LinkedIn uses start/count paging for some endpoints.",
#             }

#         return jsonify({"success": True, "data": result}), HTTP_STATUS_CODES["OK"]


# # -------------------------------------------------------------------
# # LINKEDIN: POST DETAILS — Fetch one UGC post by URN
# # -------------------------------------------------------------------

# @blp_linkedin_insights.route("/social/linkedin/post-details", methods=["GET"])
# class LinkedInPostDetailsResource(MethodView):
#     """
#     Get a single LinkedIn UGC post by URN.

#     Query params:
#       - destination_id (required): Organization ID (for token lookup)
#       - post_urn (required): e.g. urn:li:ugcPost:123456789
#     """

#     @token_required
#     def get(self):
#         client_ip = request.remote_addr
#         log_tag = f"[linkedin_insights][post_details][{client_ip}]"

#         user = g.get("current_user") or {}
#         business_id = str(user.get("business_id") or "")
#         user__id = str(user.get("_id") or "")

#         if not business_id or not user__id:
#             return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

#         org_id = (request.args.get("destination_id") or "").strip()
#         post_urn = (request.args.get("post_urn") or "").strip()

#         if not org_id:
#             return jsonify({"success": False, "message": "destination_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]
#         if not post_urn:
#             return jsonify({"success": False, "message": "post_urn is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

#         acct = SocialAccount.get_destination(
#             business_id=business_id,
#             user__id=user__id,
#             platform=PLATFORM_ID,
#             destination_id=org_id,
#         )
#         if not acct:
#             return jsonify({
#                 "success": False,
#                 "code": "LI_NOT_CONNECTED",
#                 "message": "LinkedIn organization not connected",
#             }), HTTP_STATUS_CODES["NOT_FOUND"]

#         access_token = acct.get("access_token_plain") or acct.get("access_token")
#         refresh_token = acct.get("refresh_token_plain") or acct.get("refresh_token")
#         if not access_token:
#             return jsonify({
#                 "success": False,
#                 "code": "LI_TOKEN_MISSING",
#                 "message": "Reconnect LinkedIn - no access token found",
#             }), HTTP_STATUS_CODES["BAD_REQUEST"]

#         # UGC post fetch: GET /ugcPosts/{encodedUrn}
#         encoded = quote(post_urn, safe="")
#         url = f"{LI_API_BASE}/ugcPosts/{encoded}"

#         status, js, raw, new_tok = _request_get_with_refresh(
#             url=url,
#             params=None,
#             access_token=access_token,
#             refresh_token=refresh_token,
#             log_tag=log_tag,
#         )

#         if new_tok:
#             _store_new_access_token_if_possible(acct=acct, new_access_token=new_tok, log_tag=log_tag)

#         if status >= 400:
#             err = _parse_li_error(js or {}, status, raw)
#             code = "LI_POST_DETAILS_ERROR"
#             if status == 401:
#                 code = "LI_TOKEN_EXPIRED"
#             elif status == 403:
#                 code = "LI_PERMISSION_DENIED"
#             return jsonify({
#                 "success": False,
#                 "code": code,
#                 "message": err.get("message") or "Failed to fetch post details",
#                 "error": err,
#             }), HTTP_STATUS_CODES["UNAUTHORIZED"] if status == 401 else HTTP_STATUS_CODES["FORBIDDEN"] if status == 403 else HTTP_STATUS_CODES["BAD_REQUEST"]

#         # Extract text best-effort
#         text = None
#         try:
#             specific = (js or {}).get("specificContent", {})
#             share = specific.get("com.linkedin.ugc.ShareContent", {})
#             commentary = share.get("shareCommentary", {})
#             text = commentary.get("text")
#         except Exception:
#             text = None

#         result = {
#             "platform": PLATFORM_ID,
#             "post_urn": post_urn,
#             "post": js,
#             "summary": {
#                 "text": text,
#                 "lifecycleState": js.get("lifecycleState"),
#                 "visibility": js.get("visibility"),
#                 "created_at_ms": _pick(js.get("created") or {}, "time"),
#                 "last_modified_ms": _pick(js.get("lastModified") or {}, "time"),
#             },
#         }

#         return jsonify({"success": True, "data": result}), HTTP_STATUS_CODES["OK"]

# # -------------------------------------------------------------------
# # LINKEDIN: POST INSIGHTS — socialActions (likes/comments counts)
# # -------------------------------------------------------------------

# @blp_linkedin_insights.route("/social/linkedin/post-insights", methods=["GET"])
# class LinkedInPostInsightsResource(MethodView):
#     """
#     LinkedIn post analytics (best-effort) using socialActions.

#     Query params:
#       - destination_id (required): Organization ID (for token lookup)
#       - post_urn (required): urn:li:ugcPost:...
#       - debug: "true" includes raw response
#     """

#     @token_required
#     def get(self):
#         client_ip = request.remote_addr
#         log_tag = f"[linkedin_insights][post_insights][{client_ip}]"

#         user = g.get("current_user") or {}
#         business_id = str(user.get("business_id") or "")
#         user__id = str(user.get("_id") or "")

#         if not business_id or not user__id:
#             return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

#         org_id = (request.args.get("destination_id") or "").strip()
#         post_urn = (request.args.get("post_urn") or "").strip()
#         debug_mode = (request.args.get("debug") or "").lower() == "true"

#         if not org_id:
#             return jsonify({"success": False, "message": "destination_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]
#         if not post_urn:
#             return jsonify({"success": False, "message": "post_urn is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

#         acct = SocialAccount.get_destination(
#             business_id=business_id,
#             user__id=user__id,
#             platform=PLATFORM_ID,
#             destination_id=org_id,
#         )
#         if not acct:
#             return jsonify({
#                 "success": False,
#                 "code": "LI_NOT_CONNECTED",
#                 "message": "LinkedIn organization not connected",
#             }), HTTP_STATUS_CODES["NOT_FOUND"]

#         access_token = acct.get("access_token_plain") or acct.get("access_token")
#         refresh_token = acct.get("refresh_token_plain") or acct.get("refresh_token")
#         if not access_token:
#             return jsonify({
#                 "success": False,
#                 "code": "LI_TOKEN_MISSING",
#                 "message": "Reconnect LinkedIn - no access token found",
#             }), HTTP_STATUS_CODES["BAD_REQUEST"]

#         actions = _get_social_actions(
#             post_urn=post_urn,
#             access_token=access_token,
#             refresh_token=refresh_token,
#             log_tag=log_tag,
#         )

#         if actions.get("refreshed_access_token"):
#             _store_new_access_token_if_possible(acct=acct, new_access_token=actions["refreshed_access_token"], log_tag=log_tag)

#         if not actions.get("success"):
#             err = actions.get("error") or {}
#             status = actions.get("status_code", 400)
#             code = "LI_POST_INSIGHTS_ERROR"
#             if status == 401:
#                 code = "LI_TOKEN_EXPIRED"
#             elif status == 403:
#                 code = "LI_PERMISSION_DENIED"
#             return jsonify({
#                 "success": False,
#                 "code": code,
#                 "message": err.get("message") or "Failed to fetch post insights",
#                 "error": err,
#                 "debug": actions if debug_mode else None,
#             }), HTTP_STATUS_CODES["UNAUTHORIZED"] if status == 401 else HTTP_STATUS_CODES["FORBIDDEN"] if status == 403 else HTTP_STATUS_CODES["BAD_REQUEST"]

#         result = {
#             "platform": PLATFORM_ID,
#             "destination_id": org_id,
#             "post_urn": post_urn,
#             "metrics": actions.get("metrics"),
#         }
#         if debug_mode:
#             result["debug"] = {"raw": actions.get("raw")}

#         return jsonify({"success": True, "data": result}), HTTP_STATUS_CODES["OK"]


# # -------------------------------------------------------------------
# # LINKEDIN: DISCOVER — diagnostic endpoint
# # -------------------------------------------------------------------

# @blp_linkedin_insights.route("/social/linkedin/discover", methods=["GET"])
# class LinkedInDiscoverResource(MethodView):
#     """
#     Diagnostic endpoint to test what your token can access.

#     Query params:
#       - destination_id (required): Organization ID
#       - sample_post_urn (optional): urn:li:ugcPost:... to test socialActions
#       - debug: "true"
#     """

#     @token_required
#     def get(self):
#         client_ip = request.remote_addr
#         log_tag = f"[linkedin_insights][discover][{client_ip}]"

#         user = g.get("current_user") or {}
#         business_id = str(user.get("business_id") or "")
#         user__id = str(user.get("_id") or "")

#         if not business_id or not user__id:
#             return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

#         org_id = (request.args.get("destination_id") or "").strip()
#         sample_post_urn = (request.args.get("sample_post_urn") or "").strip() or None
#         debug_mode = (request.args.get("debug") or "").lower() == "true"

#         if not org_id:
#             return jsonify({"success": False, "message": "destination_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

#         acct = SocialAccount.get_destination(
#             business_id=business_id,
#             user__id=user__id,
#             platform=PLATFORM_ID,
#             destination_id=org_id,
#         )
#         if not acct:
#             return jsonify({
#                 "success": False,
#                 "code": "LI_NOT_CONNECTED",
#                 "message": "LinkedIn organization not connected",
#             }), HTTP_STATUS_CODES["NOT_FOUND"]

#         access_token = acct.get("access_token_plain") or acct.get("access_token")
#         refresh_token = acct.get("refresh_token_plain") or acct.get("refresh_token")
#         if not access_token:
#             return jsonify({
#                 "success": False,
#                 "code": "LI_TOKEN_MISSING",
#                 "message": "Reconnect LinkedIn - no access token found",
#             }), HTTP_STATUS_CODES["BAD_REQUEST"]

#         since, until = _get_date_range_last_n_days(7)

#         org_info = _get_linkedin_org_info(
#             org_id=org_id,
#             access_token=access_token,
#             refresh_token=refresh_token,
#             log_tag=log_tag,
#         )
#         if org_info.get("refreshed_access_token"):
#             access_token = org_info["refreshed_access_token"]
#             _store_new_access_token_if_possible(acct=acct, new_access_token=access_token, log_tag=log_tag)

#         followers = _get_org_follower_stats(
#             org_id=org_id,
#             access_token=access_token,
#             refresh_token=refresh_token,
#             log_tag=log_tag,
#             since=since,
#             until=until,
#         )
#         if followers.get("refreshed_access_token"):
#             access_token = followers["refreshed_access_token"]
#             _store_new_access_token_if_possible(acct=acct, new_access_token=access_token, log_tag=log_tag)

#         page_stats = _get_org_page_stats(
#             org_id=org_id,
#             access_token=access_token,
#             refresh_token=refresh_token,
#             log_tag=log_tag,
#             since=since,
#             until=until,
#         )
#         if page_stats.get("refreshed_access_token"):
#             access_token = page_stats["refreshed_access_token"]
#             _store_new_access_token_if_possible(acct=acct, new_access_token=access_token, log_tag=log_tag)

#         posts = _fetch_org_posts(
#             org_id=org_id,
#             access_token=access_token,
#             refresh_token=refresh_token,
#             log_tag=log_tag,
#             count=5,
#             start=0,
#         )
#         if posts.get("refreshed_access_token"):
#             access_token = posts["refreshed_access_token"]
#             _store_new_access_token_if_possible(acct=acct, new_access_token=access_token, log_tag=log_tag)

#         social_actions_probe = None
#         if sample_post_urn:
#             social_actions_probe = _get_social_actions(
#                 post_urn=sample_post_urn,
#                 access_token=access_token,
#                 refresh_token=refresh_token,
#                 log_tag=log_tag,
#             )
#             if social_actions_probe.get("refreshed_access_token"):
#                 _store_new_access_token_if_possible(acct=acct, new_access_token=social_actions_probe["refreshed_access_token"], log_tag=log_tag)

#         result = {
#             "platform": PLATFORM_ID,
#             "destination_id": org_id,
#             "since": since,
#             "until": until,
#             "token": {
#                 "has_refresh_token": bool(refresh_token),
#                 "can_auto_refresh": bool(refresh_token) and bool(os.getenv("LINKEDIN_CLIENT_ID")) and bool(os.getenv("LINKEDIN_CLIENT_SECRET")),
#             },
#             "org_info_probe": {
#                 "success": org_info.get("success"),
#                 "name": org_info.get("name") if org_info.get("success") else None,
#                 "error": org_info.get("error") if not org_info.get("success") else None,
#                 "status_code": org_info.get("status_code") if not org_info.get("success") else 200,
#             },
#             "followers_probe": {
#                 "success": followers.get("success"),
#                 "summary": followers.get("summary") if followers.get("success") else None,
#                 "error": followers.get("error") if not followers.get("success") else None,
#                 "status_code": followers.get("status_code") if not followers.get("success") else 200,
#             },
#             "page_stats_probe": {
#                 "success": page_stats.get("success"),
#                 "summary": page_stats.get("summary") if page_stats.get("success") else None,
#                 "error": page_stats.get("error") if not page_stats.get("success") else None,
#                 "status_code": page_stats.get("status_code") if not page_stats.get("success") else 200,
#             },
#             "posts_probe": {
#                 "success": posts.get("success"),
#                 "count": len(posts.get("posts") or []) if posts.get("success") else 0,
#                 "sample_post_urn": (posts.get("posts") or [{}])[0].get("urn") if posts.get("success") and posts.get("posts") else None,
#                 "error": posts.get("error") if not posts.get("success") else None,
#                 "status_code": posts.get("status_code") if not posts.get("success") else 200,
#             },
#             "social_actions_probe": None,
#             "recommendation": (
#                 "All probes look OK (subject to data availability)."
#                 if org_info.get("success") and (followers.get("success") or page_stats.get("success") or posts.get("success"))
#                 else "If you see 403, your app likely lacks product access/scopes for LinkedIn Marketing/Org APIs."
#             ),
#             "notes": [
#                 "LinkedIn analytics endpoints are access-gated and often return 403 if your app isn’t approved.",
#                 "401 typically means token expired/invalid — refresh token can help if your app supports it.",
#                 "Follower/Page stats are not guaranteed for every app/token; use probes to see what’s available.",
#             ],
#         }

#         if sample_post_urn and social_actions_probe is not None:
#             result["social_actions_probe"] = {
#                 "success": social_actions_probe.get("success"),
#                 "metrics": social_actions_probe.get("metrics") if social_actions_probe.get("success") else None,
#                 "error": social_actions_probe.get("error") if not social_actions_probe.get("success") else None,
#                 "status_code": social_actions_probe.get("status_code") if not social_actions_probe.get("success") else 200,
#                 "raw": social_actions_probe.get("raw") if debug_mode and social_actions_probe.get("success") else None,
#             }

#         if debug_mode:
#             result["debug"] = {
#                 "stored_destination_name": acct.get("destination_name"),
#                 "hint": "If org_info works but stats fail with 403, your token/app likely lacks Marketing/Analytics product access.",
#             }

#         return jsonify({"success": True, "data": result}), HTTP_STATUS_CODES["OK"]



















































