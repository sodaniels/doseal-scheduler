# app/services/social/providers/pinterest_provider.py
#
# Pinterest provider for unified analytics
#
# Pinterest API v5:
# - User account info: followers, following, pins count
# - Account analytics: impressions, saves, clicks, engagement
# - Pin analytics: per-pin impressions, saves, clicks
# - Board info: follower count, pin count
#
# Key limitations:
# - Analytics require Pinterest Business account
# - Some metrics require ads:read scope
# - Data may have 24-48 hour delay
# - Rate limits: 1000 requests per minute
#
# Required Scopes:
# - user_accounts:read: Basic account info
# - pins:read: Read pins
# - boards:read: Read boards
# - user_accounts:analytics:read: Account analytics (Business only)
# - pins:read_analytics: Pin analytics (Business only)

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


# Pinterest API v5
API_VERSION = "v5"
PINTEREST_API_BASE = f"https://api.pinterest.com/{API_VERSION}"


# -------------------------------------------------------------------
# Pinterest API Metrics Reference
# -------------------------------------------------------------------
# Account Analytics (GET /user_account/analytics):
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
#   - TOTAL_COMMENTS: Total comments
#   - TOTAL_REACTIONS: Total reactions

# Valid account-level metrics
VALID_ACCOUNT_METRICS = [
    "IMPRESSION",
    "PIN_CLICK",
    "OUTBOUND_CLICK",
    "SAVE",
    "ENGAGEMENT",
]

# Valid pin-level metrics
VALID_PIN_METRICS = [
    "IMPRESSION",
    "PIN_CLICK",
    "OUTBOUND_CLICK",
    "SAVE",
]


class PinterestProvider(SocialProviderBase):
    platform = "pinterest"

    def __init__(self):
        self.api_base = PINTEREST_API_BASE

    def _auth_headers(self, access_token: str) -> Dict[str, str]:
        """Build authorization headers for Pinterest API."""
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request_get(
        self,
        endpoint: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Make GET request to Pinterest API."""
        url = f"{self.api_base}/{endpoint}"
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

    def _parse_pinterest_error(self, error: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Pinterest API error response."""
        if isinstance(error, dict):
            return {
                "code": error.get("code") or error.get("error_code") or error.get("status"),
                "message": error.get("message") or error.get("error") or str(error),
                "details": error.get("details"),
            }
        return {"message": str(error)}

    def _is_auth_error(self, error: Dict[str, Any], status_code: int) -> bool:
        """Check if error is authentication related (token expired)."""
        if status_code == 401:
            return True
        code = error.get("code")
        return code in [1, 2, 3]

    def _is_scope_error(self, error: Dict[str, Any], status_code: int) -> bool:
        """Check if error is scope/permission related."""
        if status_code == 403:
            return True
        code = error.get("code")
        message = str(error.get("message", "")).lower()
        return (
            code in [7, 8] or
            "permission" in message or
            "scope" in message or
            "not authorized" in message
        )

    def _is_business_required_error(self, error: Dict[str, Any], status_code: int) -> bool:
        """Check if error is because Business account is required."""
        message = str(error.get("message", "")).lower()
        return "business" in message or status_code == 403

    def _get_user_info(
        self,
        access_token: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch Pinterest user account info.
        
        Endpoint: GET /user_account
        Required scope: user_accounts:read
        """
        result = self._request_get(
            endpoint="user_account",
            headers=self._auth_headers(access_token),
            params={},
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} Pinterest user info error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        
        return {
            "success": True,
            "id": data.get("id"),
            "username": data.get("username"),
            "account_type": data.get("account_type"),  # BUSINESS or PERSONAL
            "profile_image": data.get("profile_image"),
            "website_url": data.get("website_url"),
            "business_name": data.get("business_name"),
            "follower_count": data.get("follower_count", 0),
            "following_count": data.get("following_count", 0),
            "pin_count": data.get("pin_count", 0),
            "monthly_views": data.get("monthly_views", 0),
        }

    def _get_account_analytics(
        self,
        access_token: str,
        start_date: str,
        end_date: str,
        metrics: List[str],
        granularity: str = "DAY",
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        Fetch Pinterest account-level analytics.
        
        Endpoint: GET /user_account/analytics
        Required scope: user_accounts:analytics:read (Business only)
        """
        result = self._request_get(
            endpoint="user_account/analytics",
            headers=self._auth_headers(access_token),
            params={
                "start_date": start_date,
                "end_date": end_date,
                "metric_types": ",".join(metrics),
                "granularity": granularity,
                "split_by": "NO_SPLIT",
            },
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} Pinterest account analytics error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        
        # Parse response - Pinterest format: {"all": {"daily_metrics": [...]}}
        all_data = data.get("all", {})
        daily_metrics = all_data.get("daily_metrics", [])
        summary_metrics = all_data.get("summary_metrics", {})
        
        # Build time series
        timeline = []
        for day_data in daily_metrics:
            date = day_data.get("date")
            metrics_values = day_data.get("metrics", {})
            data_status = day_data.get("data_status")
            
            if date:
                timeline.append({
                    "date": date,
                    "metrics": metrics_values,
                    "data_status": data_status,
                })
        
        return {
            "success": True,
            "timeline": timeline,
            "summary": summary_metrics,
        }

    def _get_user_pins(
        self,
        access_token: str,
        limit: int = 100,
        bookmark: Optional[str] = None,
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        Fetch user's pins.
        
        Endpoint: GET /pins
        Required scope: pins:read
        """
        params = {
            "page_size": min(limit, 250),
        }
        
        if bookmark:
            params["bookmark"] = bookmark
        
        result = self._request_get(
            endpoint="pins",
            headers=self._auth_headers(access_token),
            params=params,
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} Pinterest pins list error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        items = data.get("items", [])
        
        pins = []
        for pin in items:
            pins.append({
                "id": pin.get("id"),
                "created_at": pin.get("created_at"),
                "title": pin.get("title"),
                "description": pin.get("description"),
                "link": pin.get("link"),
                "board_id": pin.get("board_id"),
                "media_type": pin.get("media", {}).get("media_type") if isinstance(pin.get("media"), dict) else None,
            })
        
        return {
            "success": True,
            "pins": pins,
            "bookmark": data.get("bookmark"),
            "has_more": bool(data.get("bookmark")),
        }

    def _get_pin_analytics(
        self,
        pin_id: str,
        access_token: str,
        start_date: str,
        end_date: str,
        metrics: List[str],
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        Fetch analytics for a specific pin.
        
        Endpoint: GET /pins/{pin_id}/analytics
        Required scope: pins:read_analytics (Business only)
        """
        result = self._request_get(
            endpoint=f"pins/{pin_id}/analytics",
            headers=self._auth_headers(access_token),
            params={
                "start_date": start_date,
                "end_date": end_date,
                "metric_types": ",".join(metrics),
                "app_types": "ALL",
            },
        )
        
        if not result.get("success"):
            # Pin analytics may fail for some pins - don't log as error
            return result
        
        data = result.get("data", {})
        all_data = data.get("all", {})
        
        return {
            "success": True,
            "lifetime_metrics": all_data.get("lifetime_metrics", {}),
            "summary_metrics": all_data.get("summary_metrics", {}),
        }

    def _get_boards(
        self,
        access_token: str,
        limit: int = 50,
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        Fetch user's boards.
        
        Endpoint: GET /boards
        Required scope: boards:read
        """
        result = self._request_get(
            endpoint="boards",
            headers=self._auth_headers(access_token),
            params={
                "page_size": min(limit, 250),
            },
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} Pinterest boards list error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        items = data.get("items", [])
        
        boards = []
        for board in items:
            boards.append({
                "id": board.get("id"),
                "name": board.get("name"),
                "description": board.get("description"),
                "follower_count": board.get("follower_count", 0),
                "pin_count": board.get("pin_count", 0),
                "privacy": board.get("privacy"),
            })
        
        return {
            "success": True,
            "boards": boards,
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
        Fetch Pinterest metrics for a date range.
        
        Strategy:
        1. Get user account info (followers, following, pin count) - always works
        2. Check if Business account (required for analytics)
        3. Try to get account analytics (Business only)
        4. Get pins list for engagement aggregation
        5. Optionally get pin-level analytics (Business only)
        6. Persist to snapshot store
        7. Fallback to snapshots if API fails
        """
        log_tag = "[pinterest_provider.py][PinterestProvider][fetch_range]"

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
                debug={"error": "PIN_NOT_CONNECTED"},
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
                debug={"fallback": True, "live_error": "PIN_TOKEN_MISSING"},
            )

        try:
            # Initialize totals
            totals = {
                "followers": 0,
                "following": 0,
                "new_followers": 0,
                "posts": 0,  # pins
                "impressions": 0,
                "engagements": 0,
                "saves": 0,
                "clicks": 0,
                "pin_clicks": 0,
                "outbound_clicks": 0,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "reactions": 0,
            }
            
            timeline_map: Dict[str, Dict[str, Any]] = {}
            
            # Track what we successfully fetched
            fetch_status = {
                "user_info": False,
                "account_analytics": False,
                "pins_list": False,
                "pin_analytics": False,
                "boards": False,
            }
            
            is_business = False
            scope_warnings: List[str] = []

            # -----------------------------------------
            # 1. Get user account info (always works)
            # -----------------------------------------
            user_info = self._get_user_info(
                access_token=access_token,
                log_tag=log_tag,
            )
            
            username = destination_name
            if user_info.get("success"):
                fetch_status["user_info"] = True
                username = user_info.get("username") or destination_name
                
                totals["followers"] = int(user_info.get("follower_count", 0) or 0)
                totals["following"] = int(user_info.get("following_count", 0) or 0)
                
                # Check account type
                account_type = user_info.get("account_type", "").upper()
                is_business = account_type == "BUSINESS"
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
                        debug={"fallback": True, "live_error": "PIN_TOKEN_EXPIRED"},
                    )

            # -----------------------------------------
            # 2. Get account analytics (Business only)
            # -----------------------------------------
            if is_business:
                analytics = self._get_account_analytics(
                    access_token=access_token,
                    start_date=since_ymd,
                    end_date=until_ymd,
                    metrics=VALID_ACCOUNT_METRICS,
                    granularity="DAY",
                    log_tag=log_tag,
                )
                
                if analytics.get("success"):
                    fetch_status["account_analytics"] = True
                    
                    for day in analytics.get("timeline", []):
                        date_str = day.get("date")
                        if not date_str:
                            continue
                        
                        metrics = day.get("metrics", {})
                        
                        pt = timeline_map.setdefault(
                            date_str,
                            self._empty_timeline_point(date_str),
                        )
                        
                        impressions = int(metrics.get("IMPRESSION", 0) or 0)
                        saves = int(metrics.get("SAVE", 0) or 0)
                        pin_clicks = int(metrics.get("PIN_CLICK", 0) or 0)
                        outbound_clicks = int(metrics.get("OUTBOUND_CLICK", 0) or 0)
                        engagement = int(metrics.get("ENGAGEMENT", 0) or 0)
                        
                        pt["impressions"] += impressions
                        pt["saves"] += saves
                        pt["pin_clicks"] += pin_clicks
                        pt["outbound_clicks"] += outbound_clicks
                        pt["clicks"] += pin_clicks + outbound_clicks
                        pt["engagements"] += engagement if engagement > 0 else saves + pin_clicks + outbound_clicks
                        
                        totals["impressions"] += impressions
                        totals["saves"] += saves
                        totals["pin_clicks"] += pin_clicks
                        totals["outbound_clicks"] += outbound_clicks
                        totals["clicks"] += pin_clicks + outbound_clicks
                        totals["engagements"] += engagement if engagement > 0 else saves + pin_clicks + outbound_clicks
                else:
                    error = analytics.get("error", {})
                    status_code = analytics.get("status_code", 0)
                    
                    if self._is_scope_error(error, status_code):
                        scope_warnings.append("Account analytics require user_accounts:analytics:read scope")
            else:
                scope_warnings.append("Analytics require Pinterest Business account. Current account type: PERSONAL")

            # -----------------------------------------
            # 3. Get pins list
            # -----------------------------------------
            pins_resp = self._get_user_pins(
                access_token=access_token,
                limit=100,
                log_tag=log_tag,
            )
            
            if pins_resp.get("success"):
                fetch_status["pins_list"] = True
                pins = pins_resp.get("pins", [])
                
                # Filter pins by date range
                since_dt = _parse_ymd(since_ymd)
                until_dt = _parse_ymd(until_ymd) + timedelta(days=1)
                
                filtered_pins = []
                for pin in pins:
                    created = pin.get("created_at")
                    if created:
                        try:
                            # Pinterest date format: YYYY-MM-DD or ISO format
                            pin_date_str = created[:10]
                            pin_dt = _parse_ymd(pin_date_str)
                            
                            if since_dt <= pin_dt < until_dt:
                                filtered_pins.append(pin)
                                
                                # Add to timeline
                                pt = timeline_map.setdefault(
                                    pin_date_str,
                                    self._empty_timeline_point(pin_date_str),
                                )
                                pt["posts"] += 1
                        except Exception:
                            filtered_pins.append(pin)
                    else:
                        filtered_pins.append(pin)
                
                totals["posts"] = len(filtered_pins)
                
                # -----------------------------------------
                # 4. Get pin-level analytics (Business only)
                # -----------------------------------------
                if is_business and filtered_pins:
                    pin_analytics_success = 0
                    
                    # Limit to first 20 pins to avoid rate limits
                    for pin in filtered_pins[:20]:
                        pin_id = pin.get("id")
                        if not pin_id:
                            continue
                        
                        pin_analytics = self._get_pin_analytics(
                            pin_id=pin_id,
                            access_token=access_token,
                            start_date=since_ymd,
                            end_date=until_ymd,
                            metrics=VALID_PIN_METRICS,
                            log_tag=log_tag,
                        )
                        
                        if pin_analytics.get("success"):
                            pin_analytics_success += 1
                            # Pin analytics are already included in account analytics
                            # This is just for per-pin breakdown if needed
                    
                    if pin_analytics_success > 0:
                        fetch_status["pin_analytics"] = True
            else:
                error = pins_resp.get("error", {})
                status_code = pins_resp.get("status_code", 0)
                
                if self._is_scope_error(error, status_code):
                    scope_warnings.append("Pins list requires pins:read scope")

            # -----------------------------------------
            # 5. Get boards (optional, for reference)
            # -----------------------------------------
            boards_resp = self._get_boards(
                access_token=access_token,
                limit=50,
                log_tag=log_tag,
            )
            
            if boards_resp.get("success"):
                fetch_status["boards"] = True
                # Can aggregate board follower counts if needed

            # Sort timeline
            timeline = [timeline_map[k] for k in sorted(timeline_map.keys())]

            # Calculate engagement as reactions for compatibility
            totals["reactions"] = totals["saves"]  # Saves are the main "reaction" on Pinterest
            totals["likes"] = totals["saves"]

            # Build debug info
            debug_info = {
                "fetch_status": fetch_status,
                "is_business_account": is_business,
                "account_type": user_info.get("account_type") if user_info.get("success") else "UNKNOWN",
            }
            
            if scope_warnings:
                debug_info["scope_warnings"] = scope_warnings
                debug_info["hint"] = (
                    "Full analytics require a Pinterest Business account and user_accounts:analytics:read scope. "
                    "Without these, only basic account info and pins list are available."
                )
                debug_info["required_scopes"] = {
                    "basic": ["user_accounts:read", "pins:read", "boards:read"],
                    "full_analytics": ["user_accounts:analytics:read", "pins:read_analytics"],
                }

            # Build result
            live_res = ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=destination_name or username,
                totals=totals,
                timeline=timeline,
                debug=debug_info if scope_warnings or not fetch_status.get("account_analytics") else None,
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
                    meta={"source": "live", "provider": "pinterest"},
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
                            destination_name=live_res.destination_name,
                            totals={"followers": totals["followers"]},
                            timeline=[],
                            debug=None,
                        ),
                        prefer_write_each_day=False,
                        write_only_today_if_no_timeline=True,
                        today_ymd=_today_ymd(),
                        meta={"source": "live_followers_only", "provider": "pinterest"},
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
            "engagements": 0,
            "saves": 0,
            "clicks": 0,
            "pin_clicks": 0,
            "outbound_clicks": 0,
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "reactions": 0,
        }
        
## Summary of Pinterest Provider

### API Endpoints Used

# | Endpoint | Purpose | Required Scope |
# |----------|---------|----------------|
# | `/user_account` | Account info (followers, pins count) | `user_accounts:read` |
# | `/user_account/analytics` | Account analytics (impressions, saves, clicks) | `user_accounts:analytics:read` (Business) |
# | `/pins` | List user's pins | `pins:read` |
# | `/pins/{id}/analytics` | Per-pin analytics | `pins:read_analytics` (Business) |
# | `/boards` | List user's boards | `boards:read` |

# ### What You Get

# | Metric | Source | Scope Required |
# |--------|--------|----------------|
# | `followers` | user_account | `user_accounts:read` |
# | `following` | user_account | `user_accounts:read` |
# | `posts` (pins) | pins list | `pins:read` |
# | `impressions` | account analytics | `user_accounts:analytics:read` (Business) |
# | `saves` | account analytics | `user_accounts:analytics:read` (Business) |
# | `pin_clicks` | account analytics | `user_accounts:analytics:read` (Business) |
# | `outbound_clicks` | account analytics | `user_accounts:analytics:read` (Business) |
# | `engagements` | account analytics | `user_accounts:analytics:read` (Business) |

