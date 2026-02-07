# app/services/social/providers/x_provider.py
#
# X (Twitter) provider for unified analytics
#
# X API v2:
# - User info: followers_count, following_count, tweet_count
# - User tweets: with engagement metrics (likes, replies, retweets, impressions)
# - Tweet metrics: public_metrics, non_public_metrics, organic_metrics
#
# Key limitations:
# - No time-series follower data (use daily snapshots)
# - Non-public metrics require OAuth 2.0 user context
# - Impression data requires tweet owner or elevated access
# - Rate limits vary by tier (Basic, Pro, Enterprise)
#
# Required Scopes:
# - tweet.read: Read tweets
# - users.read: Read user profile
# - offline.access: Refresh tokens (recommended)
#
# API Tiers:
# - Free: Very limited (50 tweets/month read)
# - Basic: $100/month (10K tweets/month read)
# - Pro: $5000/month (1M tweets/month read)

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


def _parse_twitter_datetime(dt_str: str) -> Optional[str]:
    """Parse Twitter datetime to YYYY-MM-DD."""
    if not dt_str:
        return None
    try:
        # Twitter format: 2024-01-15T12:30:00.000Z
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


# X (Twitter) API v2
X_API_BASE = "https://api.twitter.com/2"


# -------------------------------------------------------------------
# X API v2 Reference
# -------------------------------------------------------------------
# User by ID (GET /users/{id}):
#   Fields: id, name, username, description, profile_image_url,
#           public_metrics (followers_count, following_count, tweet_count, listed_count)
#
# User Tweets (GET /users/{id}/tweets):
#   Fields: id, text, created_at, public_metrics, non_public_metrics, organic_metrics
#   Public metrics: like_count, reply_count, retweet_count, quote_count
#   Non-public metrics: impression_count, url_link_clicks, user_profile_clicks
#   Organic metrics: impression_count, like_count, reply_count, retweet_count
#
# Rate Limits (v2):
#   - Free tier: 1 request per 15 minutes for user lookup
#   - Basic: 100 requests per 15 minutes
#   - Pro: 300 requests per 15 minutes


class XProvider(SocialProviderBase):
    platform = "x"

    def __init__(self):
        self.api_base = X_API_BASE

    def _auth_headers(self, access_token: str) -> Dict[str, str]:
        """Build authorization headers for X API."""
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def _request_get(
        self,
        endpoint: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Make GET request to X API."""
        url = f"{self.api_base}/{endpoint}"
        try:
            r = requests.get(url, headers=headers, params=params, timeout=timeout)
            text = r.text or ""
            
            try:
                js = r.json() if text else {}
            except Exception:
                js = {}
            
            # X API returns errors in response body
            if "errors" in js:
                errors = js.get("errors", [])
                return {
                    "success": False,
                    "status_code": r.status_code,
                    "error": errors[0] if errors else {"message": "Unknown error"},
                    "errors": errors,
                    "raw": text,
                }
            
            if r.status_code >= 400:
                return {
                    "success": False,
                    "status_code": r.status_code,
                    "error": js,
                    "raw": text,
                }
            
            return {"success": True, "data": js.get("data", js), "meta": js.get("meta", {}), "includes": js.get("includes", {})}
        except requests.exceptions.Timeout:
            return {"success": False, "error": {"message": "Request timeout"}}
        except requests.exceptions.RequestException as e:
            return {"success": False, "error": {"message": str(e)}}

    def _parse_x_error(self, error: Dict[str, Any]) -> Dict[str, Any]:
        """Parse X API error response."""
        if isinstance(error, dict):
            return {
                "code": error.get("code") or error.get("type"),
                "message": error.get("message") or error.get("detail") or error.get("title") or str(error),
                "type": error.get("type"),
            }
        return {"message": str(error)}

    def _is_auth_error(self, error: Dict[str, Any], status_code: int) -> bool:
        """Check if error is authentication related (token expired)."""
        if status_code == 401:
            return True
        code = error.get("code")
        error_type = error.get("type", "")
        return (
            code in [32, 89, 215] or  # Twitter error codes
            "token" in error_type.lower() or
            "unauthorized" in str(error.get("message", "")).lower()
        )

    def _is_scope_error(self, error: Dict[str, Any], status_code: int) -> bool:
        """Check if error is scope/permission related."""
        if status_code == 403:
            return True
        message = str(error.get("message", "")).lower()
        error_type = str(error.get("type", "")).lower()
        return (
            "scope" in message or
            "permission" in message or
            "forbidden" in error_type or
            "not authorized" in message
        )

    def _is_rate_limit_error(self, error: Dict[str, Any], status_code: int) -> bool:
        """Check if error is rate limit related."""
        if status_code == 429:
            return True
        code = error.get("code")
        return code == 88  # Rate limit exceeded

    def _is_not_found_error(self, error: Dict[str, Any], status_code: int) -> bool:
        """Check if error is not found."""
        if status_code == 404:
            return True
        code = error.get("code")
        return code == 34  # Page does not exist

    def _get_user_info(
        self,
        user_id: str,
        access_token: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch X user info.
        
        Endpoint: GET /users/{id}
        Required scope: users.read
        """
        user_fields = [
            "id",
            "name",
            "username",
            "description",
            "profile_image_url",
            "verified",
            "verified_type",
            "public_metrics",
            "created_at",
            "url",
            "location",
        ]
        
        result = self._request_get(
            endpoint=f"users/{user_id}",
            headers=self._auth_headers(access_token),
            params={
                "user.fields": ",".join(user_fields),
            },
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} X user info error: {result.get('error')}")
            return result
        
        data = result.get("data", {})
        public_metrics = data.get("public_metrics", {})
        
        return {
            "success": True,
            "id": data.get("id"),
            "name": data.get("name"),
            "username": data.get("username"),
            "description": data.get("description"),
            "profile_image_url": data.get("profile_image_url"),
            "verified": data.get("verified", False),
            "verified_type": data.get("verified_type"),
            "url": data.get("url"),
            "location": data.get("location"),
            "created_at": data.get("created_at"),
            "followers_count": public_metrics.get("followers_count", 0),
            "following_count": public_metrics.get("following_count", 0),
            "tweet_count": public_metrics.get("tweet_count", 0),
            "listed_count": public_metrics.get("listed_count", 0),
        }

    def _get_user_by_username(
        self,
        username: str,
        access_token: str,
        log_tag: str,
    ) -> Dict[str, Any]:
        """
        Fetch X user info by username.
        
        Endpoint: GET /users/by/username/{username}
        Required scope: users.read
        """
        user_fields = [
            "id",
            "name",
            "username",
            "description",
            "profile_image_url",
            "public_metrics",
        ]
        
        result = self._request_get(
            endpoint=f"users/by/username/{username}",
            headers=self._auth_headers(access_token),
            params={
                "user.fields": ",".join(user_fields),
            },
        )
        
        if not result.get("success"):
            return result
        
        data = result.get("data", {})
        public_metrics = data.get("public_metrics", {})
        
        return {
            "success": True,
            "id": data.get("id"),
            "name": data.get("name"),
            "username": data.get("username"),
            "followers_count": public_metrics.get("followers_count", 0),
            "following_count": public_metrics.get("following_count", 0),
            "tweet_count": public_metrics.get("tweet_count", 0),
        }

    def _get_user_tweets(
        self,
        user_id: str,
        access_token: str,
        max_results: int = 100,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        pagination_token: Optional[str] = None,
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        Fetch user's tweets.
        
        Endpoint: GET /users/{id}/tweets
        Required scope: tweet.read, users.read
        """
        tweet_fields = [
            "id",
            "text",
            "created_at",
            "public_metrics",
            "non_public_metrics",
            "organic_metrics",
            "author_id",
            "conversation_id",
            "in_reply_to_user_id",
            "referenced_tweets",
        ]
        
        params = {
            "tweet.fields": ",".join(tweet_fields),
            "max_results": min(max_results, 100),  # X max is 100
            "exclude": "retweets,replies",  # Only original tweets
        }
        
        if start_time:
            # X requires ISO 8601 format
            params["start_time"] = f"{start_time}T00:00:00Z"
        if end_time:
            params["end_time"] = f"{end_time}T23:59:59Z"
        if pagination_token:
            params["pagination_token"] = pagination_token
        
        result = self._request_get(
            endpoint=f"users/{user_id}/tweets",
            headers=self._auth_headers(access_token),
            params=params,
        )
        
        if not result.get("success"):
            Log.info(f"{log_tag} X tweets error: {result.get('error')}")
            return result
        
        data = result.get("data", [])
        meta = result.get("meta", {})
        
        # Handle empty response
        if data is None:
            data = []
        
        tweets = []
        for tweet in data:
            public_metrics = tweet.get("public_metrics", {})
            non_public_metrics = tweet.get("non_public_metrics", {})
            organic_metrics = tweet.get("organic_metrics", {})
            
            created_at = tweet.get("created_at")
            created_date = _parse_twitter_datetime(created_at)
            
            tweets.append({
                "id": tweet.get("id"),
                "text": tweet.get("text"),
                "created_at": created_at,
                "created_date": created_date,
                # Public metrics (always available)
                "like_count": public_metrics.get("like_count", 0),
                "reply_count": public_metrics.get("reply_count", 0),
                "retweet_count": public_metrics.get("retweet_count", 0),
                "quote_count": public_metrics.get("quote_count", 0),
                "bookmark_count": public_metrics.get("bookmark_count", 0),
                # Non-public metrics (owner or elevated access)
                "impression_count": non_public_metrics.get("impression_count") or organic_metrics.get("impression_count", 0),
                "url_link_clicks": non_public_metrics.get("url_link_clicks", 0),
                "user_profile_clicks": non_public_metrics.get("user_profile_clicks", 0),
            })
        
        return {
            "success": True,
            "tweets": tweets,
            "meta": {
                "result_count": meta.get("result_count", 0),
                "next_token": meta.get("next_token"),
                "previous_token": meta.get("previous_token"),
            },
        }

    def _get_all_user_tweets(
        self,
        user_id: str,
        access_token: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: int = 200,
        log_tag: str = "",
    ) -> Dict[str, Any]:
        """
        Fetch all user's tweets with pagination.
        
        X limits to 100 tweets per request.
        """
        all_tweets = []
        pagination_token = None
        pages_fetched = 0
        max_pages = (limit // 100) + 1
        
        while pages_fetched < max_pages:
            result = self._get_user_tweets(
                user_id=user_id,
                access_token=access_token,
                max_results=100,
                start_time=start_time,
                end_time=end_time,
                pagination_token=pagination_token,
                log_tag=log_tag,
            )
            
            if not result.get("success"):
                # Return what we have so far
                if all_tweets:
                    return {
                        "success": True,
                        "tweets": all_tweets,
                        "partial": True,
                        "error": result.get("error"),
                    }
                return result
            
            tweets = result.get("tweets", [])
            all_tweets.extend(tweets)
            
            meta = result.get("meta", {})
            pagination_token = meta.get("next_token")
            
            if not pagination_token or not tweets:
                break
            
            pages_fetched += 1
            
            if len(all_tweets) >= limit:
                break
        
        return {
            "success": True,
            "tweets": all_tweets[:limit],
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
        Fetch X metrics for a date range.
        
        Strategy:
        1. Get user info (followers, following, tweet count) - always works
        2. Get user tweets with engagement metrics
        3. Filter tweets by date range
        4. Aggregate tweet metrics (likes, replies, retweets, impressions)
        5. Persist to snapshot store
        6. Fallback to snapshots if API fails
        
        Note: X doesn't provide time-series follower data.
        Use daily snapshots to track follower growth.
        """
        log_tag = "[x_provider.py][XProvider][fetch_range]"

        # Load stored SocialAccount
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=self.platform,
            destination_id=destination_id,
        )
        
        if not acct:
            # Also try "twitter" platform for backwards compatibility
            acct = SocialAccount.get_destination(
                business_id=business_id,
                user__id=user__id,
                platform="twitter",
                destination_id=destination_id,
            )
        
        if not acct:
            return ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=None,
                totals={},
                timeline=[],
                debug={"error": "X_NOT_CONNECTED"},
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
                debug={"fallback": True, "live_error": "X_TOKEN_MISSING"},
            )

        try:
            # Initialize totals
            totals = {
                "followers": 0,
                "following": 0,
                "new_followers": 0,
                "posts": 0,  # tweets
                "impressions": 0,
                "engagements": 0,
                "likes": 0,
                "comments": 0,  # replies
                "shares": 0,  # retweets
                "reactions": 0,
                "retweets": 0,
                "replies": 0,
                "quotes": 0,
                "bookmarks": 0,
            }
            
            timeline_map: Dict[str, Dict[str, Any]] = {}
            
            # Track what we successfully fetched
            fetch_status = {
                "user_info": False,
                "tweets": False,
            }
            
            scope_warnings: List[str] = []

            # -----------------------------------------
            # 1. Get user info
            # -----------------------------------------
            user_info = self._get_user_info(
                user_id=destination_id,
                access_token=access_token,
                log_tag=log_tag,
            )
            
            username = destination_name
            if user_info.get("success"):
                fetch_status["user_info"] = True
                username = user_info.get("username") or user_info.get("name") or destination_name
                
                totals["followers"] = int(user_info.get("followers_count", 0) or 0)
                totals["following"] = int(user_info.get("following_count", 0) or 0)
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
                        debug={"fallback": True, "live_error": "X_TOKEN_EXPIRED"},
                    )
                
                if self._is_rate_limit_error(error, status_code):
                    scope_warnings.append("Rate limit exceeded. Try again later.")
                    # Fall back to snapshots
                    return SnapshotStore.read_range_as_provider_result(
                        business_id=business_id,
                        user__id=user__id,
                        platform=self.platform,
                        destination_id=destination_id,
                        since_ymd=since_ymd,
                        until_ymd=until_ymd,
                        destination_name=destination_name,
                        debug={"fallback": True, "live_error": "X_RATE_LIMIT"},
                    )
                
                if self._is_scope_error(error, status_code):
                    scope_warnings.append("User info requires users.read scope")

            # -----------------------------------------
            # 2. Get user tweets with metrics
            # -----------------------------------------
            tweets_resp = self._get_all_user_tweets(
                user_id=destination_id,
                access_token=access_token,
                start_time=since_ymd,
                end_time=until_ymd,
                limit=200,
                log_tag=log_tag,
            )
            
            if tweets_resp.get("success"):
                fetch_status["tweets"] = True
                tweets = tweets_resp.get("tweets", [])
                
                totals["posts"] = len(tweets)
                
                # Aggregate tweet metrics
                for tweet in tweets:
                    likes = int(tweet.get("like_count", 0) or 0)
                    replies = int(tweet.get("reply_count", 0) or 0)
                    retweets = int(tweet.get("retweet_count", 0) or 0)
                    quotes = int(tweet.get("quote_count", 0) or 0)
                    bookmarks = int(tweet.get("bookmark_count", 0) or 0)
                    impressions = int(tweet.get("impression_count", 0) or 0)
                    
                    totals["likes"] += likes
                    totals["replies"] += replies
                    totals["retweets"] += retweets
                    totals["quotes"] += quotes
                    totals["bookmarks"] += bookmarks
                    totals["impressions"] += impressions
                    
                    # Map to canonical metrics
                    totals["comments"] += replies
                    totals["shares"] += retweets + quotes
                    totals["reactions"] += likes
                    totals["engagements"] += likes + replies + retweets + quotes
                    
                    # Add to timeline by date
                    created_date = tweet.get("created_date")
                    if created_date:
                        pt = timeline_map.setdefault(
                            created_date,
                            self._empty_timeline_point(created_date),
                        )
                        
                        pt["posts"] += 1
                        pt["likes"] += likes
                        pt["replies"] += replies
                        pt["retweets"] += retweets
                        pt["quotes"] += quotes
                        pt["impressions"] += impressions
                        pt["comments"] += replies
                        pt["shares"] += retweets + quotes
                        pt["reactions"] += likes
                        pt["engagements"] += likes + replies + retweets + quotes
            else:
                error = tweets_resp.get("error", {})
                status_code = tweets_resp.get("status_code", 0)
                
                if self._is_scope_error(error, status_code):
                    scope_warnings.append("Tweets require tweet.read scope")
                elif self._is_rate_limit_error(error, status_code):
                    scope_warnings.append("Rate limit exceeded for tweets endpoint")

            # Sort timeline
            timeline = [timeline_map[k] for k in sorted(timeline_map.keys())]

            # Build debug info
            debug_info = {
                "fetch_status": fetch_status,
                "tweets_fetched": len(tweets_resp.get("tweets", [])) if tweets_resp.get("success") else 0,
            }
            
            if scope_warnings:
                debug_info["scope_warnings"] = scope_warnings
                debug_info["hint"] = (
                    "X API requires paid tier for full access. "
                    "Free tier has very limited quotas. "
                    "Non-public metrics (impressions) require tweet owner context."
                )
                debug_info["required_scopes"] = {
                    "basic": ["tweet.read", "users.read"],
                    "refresh": ["offline.access"],
                }
                debug_info["api_tiers"] = {
                    "free": "50 tweets/month read",
                    "basic": "$100/month - 10K tweets/month",
                    "pro": "$5000/month - 1M tweets/month",
                }
            
            # Note about time-series
            debug_info["note"] = (
                "X does not provide time-series follower data. "
                "New followers are calculated from daily snapshots. "
                "Tweet metrics are aggregated from individual tweets."
            )

            # Build result
            live_res = ProviderResult(
                platform=self.platform,
                destination_id=destination_id,
                destination_name=destination_name or username,
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
                    meta={"source": "live", "provider": "x"},
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
                            totals={
                                "followers": totals["followers"],
                                "following": totals["following"],
                            },
                            timeline=[],
                            debug=None,
                        ),
                        prefer_write_each_day=False,
                        write_only_today_if_no_timeline=True,
                        today_ymd=_today_ymd(),
                        meta={"source": "live_followers_only", "provider": "x"},
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
            "impressions": 0,
            "engagements": 0,
            "likes": 0,
            "comments": 0,
            "replies": 0,
            "shares": 0,
            "retweets": 0,
            "quotes": 0,
            "reactions": 0,
        }


## Summary of X (Twitter) Provider

### API Endpoints Used

# | Endpoint | Method | Purpose | Required Scope |
# |----------|--------|---------|----------------|
# | `/users/{id}` | GET | User info (followers, tweet count) | `users.read` |
# | `/users/{id}/tweets` | GET | User's tweets with metrics | `tweet.read`, `users.read` |

# ### What You Get

# | Metric | Source | Scope Required |
# |--------|--------|----------------|
# | `followers` | users/{id} | `users.read` |
# | `following` | users/{id} | `users.read` |
# | `posts` (tweets) | tweets list | `tweet.read` |
# | `likes` | tweets (aggregated) | `tweet.read` |
# | `replies` | tweets (aggregated) | `tweet.read` |
# | `retweets` | tweets (aggregated) | `tweet.read` |
# | `quotes` | tweets (aggregated) | `tweet.read` |
# | `impressions` | tweets (non-public) | Tweet owner context |
# | `engagements` | Calculated | `tweet.read` |

