# app/services/social/providers/linkedin_provider.py
#
# LinkedIn provider for unified analytics
#
# LinkedIn API v2:
# - Organization info: follower counts, vanity name
# - Organization statistics: follower gains, page views
# - Share statistics: impressions, clicks, engagement, comments, shares
# - Posts (shares): UGC posts with engagement metrics
#
# Key limitations:
# - Requires Community Management API approval for organization analytics
# - Requires Marketing Developer Platform for full analytics
# - Rate limits: 100 requests per day per member per app (basic)
# - Some endpoints require r_organization_admin scope
#
# Required Products/Scopes:
# - Community Management API: r_organization_social, w_organization_social
# - Marketing Developer Platform: r_organization_admin (for full analytics)
# - Basic: r_liteprofile, r_emailaddress (personal profiles only)

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


def _to_epoch_ms(dt: datetime) -> int:
    """Convert datetime to milliseconds since epoch (LinkedIn uses ms)."""
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _from_epoch_ms(ms: int) -> str:
    """Convert milliseconds since epoch to YYYY-MM-DD."""
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


# LinkedIn API
LINKEDIN_API_BASE = "https://api.linkedin.com/v2"
LINKEDIN_REST_BASE = "https://api.linkedin.com/rest"  # Newer REST API

# Version header for REST API
LINKEDIN_VERSION = "202401"  # Use recent stable version


# -------------------------------------------------------------------
# LinkedIn API Scopes Reference
# -------------------------------------------------------------------
# Basic (OpenID Connect):
#   - openid, profile, email
#   - Only for personal profile data
#
# Community Management API:
#   - r_organization_social: Read org posts
#   - w_organization_social: Write org posts
#   - rw_organization_admin: Manage org (requires approval)
#
# Marketing Developer Platform:
#   - r_organization_admin: Full org analytics
#   - r_ads, r_ads_reporting: Ads data
#
# Organization Analytics Endpoints:
#   - /organizationalEntityFollowerStatistics: Follower stats
#   - /organizationalEntityShareStatistics: Share stats (impressions, clicks)
#   - /networkSizes: Follower count
#   - /ugcPosts: Organization posts


class LinkedInProvider(SocialProviderBase):
    platform = "linkedin"

    def __init__(self):
        self.api_base = LINKEDIN_API_BASE
        self.rest_base = LINKEDIN_REST_BASE

    def _auth_headers(self, access_token: str, use_rest: bool = False) -> Dict[str, str]:
        """Build authorization headers for LinkedIn API."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        
        if use_rest:
            headers["LinkedIn-Version"] = LINKEDIN_VERSION
        
        return headers

    def _request_get(
        self,
        url: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Make GET request to LinkedIn API."""
        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            text = r.text or ""
            
            try:
                js = r.json() if text else {}
            except Exception:
                js = {}
            
            if r.status_code >= 400:
                return {
                    "success": False,
                    "status_code": r.status_code,
                    "error": js,
                    "raw": text,
                }
            
            return {"success": True, "data": js}
        except requests.exceptions.Timeout:
            return {"success": False, "error": {"message": "Request timeout"}}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": {"message": str(e)}}

    def _parse_linkedin_error(self, error: Dict[str, Any]) -> Dict[str, Any]:
        """Parse LinkedIn API error response."""
        if isinstance(error, dict):
            return {
                "code": error.get("status") or error.get("code"),
                "message": error.get("message") or error.get("error_description") or str(error),
                "service_error_code": error.get("serviceErrorCode"),
            }
        return {"message": str(error)}

    def _is_scope_error(self, error: Dict[str, Any], status_code: int) -> bool:
        """Check if error is scope/permission related."""
        if status_code in [401, 403]:
            return True
        
        message = str(error.get("message", "")).lower()
        service_code = error.get("service_error_code") or error.get("serviceErrorCode")
        
        return (
            "scope" in message or
            "permission" in message or
            "access_denied" in message or
            "not authorized" in message or
            service_code in [100, 65600]  # LinkedIn permission error codes
        )

    def _is_auth_error(self, error: Dict[str, Any], status_code: int) -> bool:
        """Check if error is authentication related (token expired)."""
        if status_code == 401:
            message = str(error.get("message", "")).lower()
            return "expired" in message or "invalid" in message or "token" in message
        return False

    def _get_organization_info(
        self,
        org_id: str,
        access_token: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch LinkedIn organization info.
        
        Endpoint: GET /organizations/{id}
        Required scope: r_organization_social or r_organization_admin
        """
        url = f"{self.api_base}/organizations/{org_id}"
        
        result = self._request_get(
            url=url,
            headers=self._auth_headers(access_token),
            params={
                "projection": "(id,localizedName,vanityName,logoV2,localizedDescription,localizedWebsite)",
            },
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} LI org info error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        
        return {
            "success": True,
            "id": data.get("id"),
            "name": data.get("localizedName"),
            "vanity_name": data.get("vanityName"),
            "description": data.get("localizedDescription"),
            "website": data.get("localizedWebsite"),
            "logo": data.get("logoV2"),
        }

    def _get_follower_count(
        self,
        org_urn: str,
        access_token: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch organization follower count.
        
        Endpoint: GET /networkSizes/{entity}?edgeType=CompanyFollowedByMember
        Required scope: r_organization_social
        """
        # URL encode the URN
        encoded_urn = requests.utils.quote(org_urn, safe="")
        url = f"{self.api_base}/networkSizes/{encoded_urn}"
        
        result = self._request_get(
            url=url,
            headers=self._auth_headers(access_token),
            params={
                "edgeType": "CompanyFollowedByMember",
            },
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} LI follower count error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        
        return {
            "success": True,
            "follower_count": data.get("firstDegreeSize", 0),
        }

    def _get_follower_statistics(
        self,
        org_urn: str,
        access_token: str,
        since_ymd: str,
        until_ymd: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch organization follower statistics (gains/losses over time).
        
        Endpoint: GET /organizationalEntityFollowerStatistics
        Required scope: r_organization_admin (Marketing Developer Platform)
        """
        url = f"{self.api_base}/organizationalEntityFollowerStatistics"
        
        since_ms = _to_epoch_ms(_parse_ymd(since_ymd))
        until_ms = _to_epoch_ms(_parse_ymd(until_ymd) + timedelta(days=1))
        
        result = self._request_get(
            url=url,
            headers=self._auth_headers(access_token),
            params={
                "q": "organizationalEntity",
                "organizationalEntity": org_urn,
                "timeIntervals.timeGranularityType": "DAY",
                "timeIntervals.timeRange.start": since_ms,
                "timeIntervals.timeRange.end": until_ms,
            },
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} LI follower stats error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        elements = data.get("elements", [])
        
        # Parse time series
        timeline = []
        for elem in elements:
            time_range = elem.get("timeRange", {})
            start_ms = time_range.get("start")
            
            if start_ms:
                date_str = _from_epoch_ms(start_ms)
                follower_gains = elem.get("followerGains", {})
                
                timeline.append({
                    "date": date_str,
                    "organic_gains": follower_gains.get("organicFollowerGain", 0),
                    "paid_gains": follower_gains.get("paidFollowerGain", 0),
                    "total_gains": (
                        follower_gains.get("organicFollowerGain", 0) +
                        follower_gains.get("paidFollowerGain", 0)
                    ),
                })
        
        return {
            "success": True,
            "timeline": timeline,
        }

    def _get_share_statistics(
        self,
        org_urn: str,
        access_token: str,
        since_ymd: str,
        until_ymd: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch organization share statistics (impressions, clicks, engagement).
        
        Endpoint: GET /organizationalEntityShareStatistics
        Required scope: r_organization_admin (Marketing Developer Platform)
        """
        url = f"{self.api_base}/organizationalEntityShareStatistics"
        
        since_ms = _to_epoch_ms(_parse_ymd(since_ymd))
        until_ms = _to_epoch_ms(_parse_ymd(until_ymd) + timedelta(days=1))
        
        result = self._request_get(
            url=url,
            headers=self._auth_headers(access_token),
            params={
                "q": "organizationalEntity",
                "organizationalEntity": org_urn,
                "timeIntervals.timeGranularityType": "DAY",
                "timeIntervals.timeRange.start": since_ms,
                "timeIntervals.timeRange.end": until_ms,
            },
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} LI share stats error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        elements = data.get("elements", [])
        
        # Parse time series
        timeline = []
        for elem in elements:
            time_range = elem.get("timeRange", {})
            start_ms = time_range.get("start")
            total_stats = elem.get("totalShareStatistics", {})
            
            if start_ms:
                date_str = _from_epoch_ms(start_ms)
                
                timeline.append({
                    "date": date_str,
                    "impressions": total_stats.get("impressionCount", 0),
                    "unique_impressions": total_stats.get("uniqueImpressionsCount", 0),
                    "clicks": total_stats.get("clickCount", 0),
                    "likes": total_stats.get("likeCount", 0),
                    "comments": total_stats.get("commentCount", 0),
                    "shares": total_stats.get("shareCount", 0),
                    "engagement": total_stats.get("engagement", 0),
                    "share_count": total_stats.get("shareMentionsCount", 0),
                })
        
        return {
            "success": True,
            "timeline": timeline,
        }

    def _get_organization_posts(
        self,
        org_urn: str,
        access_token: str,
        limit: int = 50,
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        Fetch organization posts (UGC posts).
        
        Endpoint: GET /ugcPosts
        Required scope: r_organization_social
        """
        url = f"{self.api_base}/ugcPosts"
        
        result = self._request_get(
            url=url,
            headers=self._auth_headers(access_token),
            params={
                "q": "authors",
                "authors": f"List({org_urn})",
                "count": min(limit, 100),
            },
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} LI posts error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        elements = data.get("elements", [])
        
        posts = []
        for post in elements:
            created = post.get("created", {})
            created_time = created.get("time")
            
            # Get text content
            specific_content = post.get("specificContent", {})
            share_content = specific_content.get("com.linkedin.ugc.ShareContent", {})
            share_commentary = share_content.get("shareCommentary", {})
            text = share_commentary.get("text", "")
            
            posts.append({
                "id": post.get("id"),
                "urn": f"urn:li:ugcPost:{post.get('id')}",
                "created_time": _from_epoch_ms(created_time) if created_time else None,
                "text": text,
                "visibility": post.get("visibility", {}).get("com.linkedin.ugc.MemberNetworkVisibility"),
                "lifecycle_state": post.get("lifecycleState"),
            })
        
        return {
            "success": True,
            "posts": posts,
            "paging": data.get("paging", {}),
        }

    def _get_post_statistics(
        self,
        org_urn: str,
        share_urns: List[str],
        access_token: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch statistics for specific posts.
        
        Endpoint: GET /organizationalEntityShareStatistics
        Required scope: r_organization_admin
        """
        if not share_urns:
            return {"success": True, "stats": {}}
        
        url = f"{self.api_base}/organizationalEntityShareStatistics"
        
        # Format shares list
        shares_param = ",".join([requests.utils.quote(urn, safe="") for urn in share_urns[:20]])
        
        result = self._request_get(
            url=url,
            headers=self._auth_headers(access_token),
            params={
                "q": "organizationalEntity",
                "organizationalEntity": org_urn,
                "shares": f"List({shares_param})",
            },
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} LI post stats error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        elements = data.get("elements", [])
        
        stats = {}
        for elem in elements:
            share_urn = elem.get("share")
            total_stats = elem.get("totalShareStatistics", {})
            
            if share_urn:
                stats[share_urn] = {
                    "impressions": total_stats.get("impressionCount", 0),
                    "unique_impressions": total_stats.get("uniqueImpressionsCount", 0),
                    "clicks": total_stats.get("clickCount", 0),
                    "likes": total_stats.get("likeCount", 0),
                    "comments": total_stats.get("commentCount", 0),
                    "shares": total_stats.get("shareCount", 0),
                    "engagement": total_stats.get("engagement", 0),
                }
        
        return {
            "success": True,
            "stats": stats,
        }

    def _try_basic_profile(
        self,
        access_token: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Try to fetch basic profile info (for personal accounts).
        
        This works with basic OpenID Connect scopes.
        """
        url = f"{self.api_base}/me"
        
        result = self._request_get(
            url=url,
            headers=self._auth_headers(access_token),
            params={
                "projection": "(id,localizedFirstName,localizedLastName,vanityName)",
            },
        )
        
        if not result.get("success"):
            return result
        
        data = result.get("data", {})
        
        return {
            "success": True,
            "type": "personal",
            "id": data.get("id"),
            "name": f"{data.get('localizedFirstName', '')} {data.get('localizedLastName', '')}".strip(),
            "vanity_name": data.get("vanityName"),
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
        Fetch LinkedIn metrics for a date range.
        
        Strategy:
        1. Get organization info
        2. Get follower count (networkSizes)
        3. Try to get follower statistics (requires Marketing Developer Platform)
        4. Try to get share statistics (requires Marketing Developer Platform)
        5. Get organization posts
        6. Persist to snapshot store
        7. Fallback to snapshots if API fails
        
        Note: Full analytics require Marketing Developer Platform approval.
        Without it, only basic organization info and follower count are available.
        """
        log_tag = "[linkedin_provider.py][LinkedInProvider][fetch_range]"

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="linkedin",
            destination_id=destination_id,
        )
        
        if not acct:
            return ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=None,
                totals={},
                timeline=[],
                debug={"error": "LI_NOT_CONNECTED"},
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
                debug={"fallback": True, "live_error": "LI_TOKEN_MISSING"},
            )

        try:
            # Build organization URN
            org_urn = f"urn:li:organization:{destination_id}"
            
            # Initialize totals
            totals = {
                "followers": 0,
                "new_followers": 0,
                "posts": 0,
                "impressions": 0,
                "unique_impressions": 0,
                "engagements": 0,
                "clicks": 0,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "reactions": 0,
            }
            
            timeline_map: Dict[str, Dict[str, Any]] = {}
            
            # Track what we successfully fetched
            fetch_status = {
                "org_info": False,
                "follower_count": False,
                "follower_stats": False,
                "share_stats": False,
                "posts": False,
            }
            
            scope_warnings: List[str] = []

            # -----------------------------------------
            # 1. Get organization info
            # -----------------------------------------
            org_info = self._get_organization_info(
                org_id=destination_id,
                access_token=access_token,
                log_tag=log_tag,
            )
            
            org_name = destination_name
            if org_info.get("success"):
                fetch_status["org_info"] = True
                org_name = org_info.get("name") or destination_name
            else:
                error = org_info.get("error", {})
                status_code = org_info.get("status_code", 0)
                
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
                        debug={"fallback": True, "live_error": "LI_TOKEN_EXPIRED"},
                    )
                
                if self._is_scope_error(error, status_code):
                    scope_warnings.append("Organization info requires r_organization_social scope")

            # -----------------------------------------
            # 2. Get follower count
            # -----------------------------------------
            follower_resp = self._get_follower_count(
                org_urn=org_urn,
                access_token=access_token,
                log_tag=log_tag,
            )
            
            if follower_resp.get("success"):
                fetch_status["follower_count"] = True
                totals["followers"] = int(follower_resp.get("follower_count", 0))
            else:
                error = follower_resp.get("error", {})
                status_code = follower_resp.get("status_code", 0)
                
                if self._is_scope_error(error, status_code):
                    scope_warnings.append("Follower count requires r_organization_social scope")

            # -----------------------------------------
            # 3. Get follower statistics (time series)
            # -----------------------------------------
            follower_stats = self._get_follower_statistics(
                org_urn=org_urn,
                access_token=access_token,
                since_ymd=since_ymd,
                until_ymd=until_ymd,
                log_tag=log_tag,
            )
            
            if follower_stats.get("success"):
                fetch_status["follower_stats"] = True
                
                for day in follower_stats.get("timeline", []):
                    date_str = day.get("date")
                    if not date_str:
                        continue
                    
                    pt = timeline_map.setdefault(
                        date_str,
                        self._empty_timeline_point(date_str),
                    )
                    
                    gains = int(day.get("total_gains", 0) or 0)
                    pt["new_followers"] += gains
                    totals["new_followers"] += gains
            else:
                error = follower_stats.get("error", {})
                status_code = follower_stats.get("status_code", 0)
                
                if self._is_scope_error(error, status_code):
                    scope_warnings.append("Follower statistics require Marketing Developer Platform (r_organization_admin)")

            # -----------------------------------------
            # 4. Get share statistics (time series)
            # -----------------------------------------
            share_stats = self._get_share_statistics(
                org_urn=org_urn,
                access_token=access_token,
                since_ymd=since_ymd,
                until_ymd=until_ymd,
                log_tag=log_tag,
            )
            
            if share_stats.get("success"):
                fetch_status["share_stats"] = True
                
                for day in share_stats.get("timeline", []):
                    date_str = day.get("date")
                    if not date_str:
                        continue
                    
                    pt = timeline_map.setdefault(
                        date_str,
                        self._empty_timeline_point(date_str),
                    )
                    
                    impressions = int(day.get("impressions", 0) or 0)
                    unique_impressions = int(day.get("unique_impressions", 0) or 0)
                    clicks = int(day.get("clicks", 0) or 0)
                    likes = int(day.get("likes", 0) or 0)
                    comments = int(day.get("comments", 0) or 0)
                    shares = int(day.get("shares", 0) or 0)
                    
                    pt["impressions"] += impressions
                    pt["unique_impressions"] += unique_impressions
                    pt["clicks"] += clicks
                    pt["likes"] += likes
                    pt["comments"] += comments
                    pt["shares"] += shares
                    pt["engagements"] += likes + comments + shares + clicks
                    pt["reactions"] += likes
                    
                    totals["impressions"] += impressions
                    totals["unique_impressions"] += unique_impressions
                    totals["clicks"] += clicks
                    totals["likes"] += likes
                    totals["comments"] += comments
                    totals["shares"] += shares
                    totals["engagements"] += likes + comments + shares + clicks
                    totals["reactions"] += likes
            else:
                error = share_stats.get("error", {})
                status_code = share_stats.get("status_code", 0)
                
                if self._is_scope_error(error, status_code):
                    scope_warnings.append("Share statistics require Marketing Developer Platform (r_organization_admin)")

            # -----------------------------------------
            # 5. Get organization posts
            # -----------------------------------------
            posts_resp = self._get_organization_posts(
                org_urn=org_urn,
                access_token=access_token,
                limit=50,
                log_tag=log_tag,
            )
            
            if posts_resp.get("success"):
                fetch_status["posts"] = True
                posts = posts_resp.get("posts", [])
                
                # Filter posts by date range
                since_dt = _parse_ymd(since_ymd)
                until_dt = _parse_ymd(until_ymd) + timedelta(days=1)
                
                filtered_posts = []
                for post in posts:
                    created = post.get("created_time")
                    if created:
                        try:
                            post_dt = _parse_ymd(created)
                            if since_dt <= post_dt < until_dt:
                                filtered_posts.append(post)
                        except Exception:
                            filtered_posts.append(post)
                    else:
                        filtered_posts.append(post)
                
                totals["posts"] = len(filtered_posts)
                
                # Add posts to timeline
                for post in filtered_posts:
                    date_str = post.get("created_time")
                    if date_str and date_str in timeline_map:
                        timeline_map[date_str]["posts"] += 1
            else:
                error = posts_resp.get("error", {})
                status_code = posts_resp.get("status_code", 0)
                
                if self._is_scope_error(error, status_code):
                    scope_warnings.append("Organization posts require r_organization_social scope")

            # Sort timeline
            timeline = [timeline_map[k] for k in sorted(timeline_map.keys())]

            # Build debug info
            debug_info = {
                "fetch_status": fetch_status,
                "org_urn": org_urn,
            }
            
            if scope_warnings:
                debug_info["scope_warnings"] = scope_warnings
                debug_info["hint"] = (
                    "For full analytics, your LinkedIn app needs Marketing Developer Platform approval. "
                    "Without it, only basic organization info and follower count are available."
                )
                debug_info["required_products"] = {
                    "basic": "Community Management API (r_organization_social, w_organization_social)",
                    "full_analytics": "Marketing Developer Platform (r_organization_admin)",
                }

            # Build result
            live_res = ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=org_name,
                totals=totals,
                timeline=timeline,
                debug=debug_info if scope_warnings or not all(fetch_status.values()) else None,
            )

            # -----------------------------------------
            # 6. Persist to snapshot store
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
                    meta={"source": "live", "provider": "linkedin"},
                )

                # Ensure today's record has followers
                if totals["followers"] > 0:
                    SnapshotStore.write_from_provider_result(
                        business_id=business_id,
                        user__id=user__id,
                        platform=self.platform,
                        destination_id=destination_id,
                        result=ProviderResult(
                            platform=self.platform,
                            destination_id=destination_id,
                            destination_name=org_name,
                            totals={"followers": totals["followers"]},
                            timeline=[],
                            debug=None,
                        ),
                        prefer_write_each_day=False,
                        write_only_today_if_no_timeline=True,
                        today_ymd=_today_ymd(),
                        meta={"source": "live_followers_only", "provider": "linkedin"},
                    )
            except Exception as pe:
                Log.info(f"{log_tag} snapshot_persist_failed: {pe}")

            return live_res

        except Exception as e:
            Log.info(f"{log_tag} live_fetch_failed: {e}")

            # -----------------------------------------
            # 7. Fallback to local snapshots
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
            "impressions": 0,
            "unique_impressions": 0,
            "engagements": 0,
            "clicks": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "reactions": 0,
        }

## Summary of LinkedIn Provider

### API Endpoints Used

# | Endpoint | Purpose | Required Scope |
# |----------|---------|----------------|
# | `/organizations/{id}` | Organization info | `r_organization_social` |
# | `/networkSizes/{urn}` | Follower count | `r_organization_social` |
# | `/organizationalEntityFollowerStatistics` | Follower gains/losses | `r_organization_admin` |
# | `/organizationalEntityShareStatistics` | Share stats (impressions, clicks) | `r_organization_admin` |
# | `/ugcPosts` | Organization posts | `r_organization_social` |

# ### What You Get

# | Metric | Source | Scope Required |
# |--------|--------|----------------|
# | `followers` | networkSizes | `r_organization_social` |
# | `new_followers` | followerStatistics | `r_organization_admin` |
# | `posts` | ugcPosts | `r_organization_social` |
# | `impressions` | shareStatistics | `r_organization_admin` |
# | `unique_impressions` | shareStatistics | `r_organization_admin` |
# | `clicks` | shareStatistics | `r_organization_admin` |
# | `likes` | shareStatistics | `r_organization_admin` |
# | `comments` | shareStatistics | `r_organization_admin` |
# | `shares` | shareStatistics | `r_organization_admin` |
# | `engagements` | Calculated | `r_organization_admin` |

