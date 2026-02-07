# app/resources/social/twitter_insights.py
#
# X (Twitter) analytics using STORED SocialAccount token
#
# Reliably available via X API v2:
# - Account public_metrics: followers_count, following_count, tweet_count, listed_count
# - Tweet public_metrics: like_count, reply_count, repost_count, quote_count, bookmark_count
#
# NOT reliably available on all tiers:
# - impression_count / organic_metrics / non_public_metrics (often requires higher tier)
# - follower_count time-series (X does not provide “new followers per day” natively)
#   -> store daily snapshots and compute diffs

from __future__ import annotations

import base64
import os
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

blp_twitter_insights = Blueprint(
    "twitter_insights",
    __name__,
)

# X API v2 base (docs: https://api.x.com/2/...)
X_API_BASE = "https://api.x.com/2"

# OAuth2 token endpoint (docs.x.com)
X_OAUTH2_TOKEN_URL = "https://api.x.com/2/oauth2/token"

# Your SocialAccount platform key(s)
# Use "twitter" if that's what you already stored, but we also fallback to "x".
PLATFORM_PRIMARY = "x"
PLATFORM_FALLBACK = "x"


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _pick(d: Dict[str, Any], *keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d:
            return d.get(k)
    return default


def _parse_ymd(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return None


def _fmt_ymd(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _iso8601(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _get_date_range_last_n_days(n: int = 7) -> Tuple[str, str]:
    until = datetime.now(timezone.utc)
    since = until - timedelta(days=n)
    return _fmt_ymd(since), _fmt_ymd(until)


def _auth_headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _parse_x_error(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": payload.get("title") or payload.get("error") or "Request failed",
        "detail": payload.get("detail") or payload.get("message"),
        "type": payload.get("type"),
        "status": payload.get("status"),
        "errors": payload.get("errors"),
    }


def _is_auth_error(status_code: int, err: Optional[Dict[str, Any]] = None) -> bool:
    return status_code in (401, 403)


def _request_get(
    *,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Tuple[int, Dict[str, Any], str]:
    r = requests.get(url, headers=headers, params=params, timeout=timeout)
    text = r.text or ""
    try:
        js = r.json() if text else {}
    except Exception:
        js = {}
    return r.status_code, js, text


def _request_post_form(
    *,
    url: str,
    headers: Dict[str, str],
    data: Dict[str, Any],
    timeout: int = 30,
) -> Tuple[int, Dict[str, Any], str]:
    r = requests.post(url, headers=headers, data=data, timeout=timeout)
    text = r.text or ""
    try:
        js = r.json() if text else {}
    except Exception:
        js = {}
    return r.status_code, js, text


# -------------------------------------------------------------------
# Token refresh (OAuth 2.0 refresh_token)
# -------------------------------------------------------------------

def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("utf-8")


def _refresh_access_token(
    *,
    refresh_token: str,
    log_tag: str,
) -> Dict[str, Any]:
    """
    Refresh X OAuth2 access token.

    Requires:
      - refresh_token stored (scope offline.access was granted)
      - X_CLIENT_ID set (always required for public clients; safe to send always)
      - Optional X_CLIENT_SECRET (for confidential clients: can use Basic auth)
    """
    client_id = (os.getenv("X_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("X_CLIENT_SECRET") or "").strip()

    if not client_id:
        return {
            "success": False,
            "code": "TW_REFRESH_CONFIG_MISSING",
            "message": "Missing X_CLIENT_ID env var for refresh_token flow",
        }

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if client_secret:
        headers["Authorization"] = _basic_auth_header(client_id, client_secret)

    # docs.x.com example uses: refresh_token, grant_type=refresh_token, client_id=...
    form = {
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "client_id": client_id,
    }

    try:
        status, js, raw = _request_post_form(
            url=X_OAUTH2_TOKEN_URL,
            headers=headers,
            data=form,
            timeout=30,
        )

        if status >= 400:
            Log.info(f"{log_tag} refresh_token failed: {status} {raw}")
            return {
                "success": False,
                "status_code": status,
                "error": _parse_x_error(js) or {"raw": raw},
                "code": "TW_REFRESH_FAILED",
            }

        # Expected keys: access_token, token_type, expires_in, scope, refresh_token (sometimes rotated)
        return {
            "success": True,
            "access_token": js.get("access_token"),
            "refresh_token": js.get("refresh_token") or refresh_token,
            "expires_in": js.get("expires_in"),
            "scope": js.get("scope"),
            "token_type": js.get("token_type"),
            "raw": js,
        }

    except Exception as e:
        Log.error(f"{log_tag} refresh_token exception: {e}")
        return {
            "success": False,
            "code": "TW_REFRESH_EXCEPTION",
            "message": str(e),
        }


def _persist_tokens_best_effort(
    *,
    business_id: str,
    user__id: str,
    platform: str,
    destination_id: str,
    access_token: str,
    refresh_token: Optional[str],
    expires_in: Optional[int],
    log_tag: str,
) -> None:
    """
    Best-effort persistence into your SocialAccount model.
    Adjust this to your actual model API.

    If you already have a method like SocialAccount.update_destination_tokens(...),
    plug it in here.
    """
    try:
        # ---- CHANGE THIS TO YOUR REAL UPDATE METHOD ----
        # Example (pseudo):
        # SocialAccount.update_destination_tokens(
        #     business_id=business_id,
        #     user__id=user__id,
        #     platform=platform,
        #     destination_id=destination_id,
        #     access_token_plain=access_token,
        #     refresh_token_plain=refresh_token,
        #     expires_in=expires_in,
        #     updated_at=datetime.now(timezone.utc),
        # )
        _ = business_id, user__id, platform, destination_id, access_token, refresh_token, expires_in
        return
    except Exception as e:
        Log.info(f"{log_tag} persist_tokens failed (ignored): {e}")


def _get_destination_account(
    *,
    business_id: str,
    user__id: str,
    destination_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Try your existing platform key first, then fallback.
    """
    acct = None
    try:
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_PRIMARY,
            destination_id=destination_id,
        )
    except Exception:
        acct = None

    if acct:
        return acct

    try:
        return SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=PLATFORM_FALLBACK,
            destination_id=destination_id,
        )
    except Exception:
        return None


def _get_tokens_from_acct(acct: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Normalize token field names. You said you store refresh_token.
    Prefer *_plain versions if you have them.
    """
    access_token = (
        acct.get("access_token_plain")
        or acct.get("access_token")
        or acct.get("token")
    )
    refresh_token = (
        acct.get("refresh_token_plain")
        or acct.get("refresh_token")
    )
    return access_token, refresh_token


def _ensure_valid_access_token(
    *,
    business_id: str,
    user__id: str,
    platform_used: str,
    destination_id: str,
    access_token: Optional[str],
    refresh_token: Optional[str],
    log_tag: str,
) -> Dict[str, Any]:
    """
    If access_token is missing -> fail.
    If a request returns 401/403, callers will invoke refresh.
    This helper only refreshes when explicitly asked by callers.
    """
    if not access_token:
        return {
            "success": False,
            "code": "TW_TOKEN_MISSING",
            "message": "Reconnect Twitter/X - no access token found",
        }

    # If you want proactive refresh by expiry timestamp, add it here (if you store expires_at).
    return {
        "success": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "platform_used": platform_used,
    }


def _refresh_and_retry_get(
    *,
    request_fn_name: str,
    do_request,  # callable returning (status, js, raw)
    business_id: str,
    user__id: str,
    platform_used: str,
    destination_id: str,
    refresh_token: Optional[str],
    log_tag: str,
) -> Dict[str, Any]:
    """
    Execute request once. If 401/403, refresh token (if available) and retry once.
    Returns:
      {success: True, status, js, raw, access_token_used, refreshed: bool}
      or {success: False, ...}
    """
    # First attempt
    status, js, raw, access_token_used = do_request()
    if status < 400:
        return {
            "success": True,
            "status_code": status,
            "json": js,
            "raw": raw,
            "access_token_used": access_token_used,
            "refreshed": False,
        }

    err = _parse_x_error(js) or {"raw": raw}
    if not _is_auth_error(status, err):
        return {
            "success": False,
            "status_code": status,
            "error": err,
            "code": f"{request_fn_name}_ERROR",
        }

    # Try refresh
    if not refresh_token:
        return {
            "success": False,
            "status_code": status,
            "error": err,
            "code": "TW_TOKEN_EXPIRED",
            "message": "Twitter/X access token has expired. Please reconnect (no refresh_token stored).",
        }

    refreshed = _refresh_access_token(refresh_token=refresh_token, log_tag=log_tag)
    if not refreshed.get("success"):
        return {
            "success": False,
            "status_code": status,
            "error": err,
            "refresh_error": refreshed,
            "code": "TW_TOKEN_EXPIRED",
            "message": "Twitter/X access token has expired. Please reconnect (refresh failed).",
        }

    new_access = refreshed.get("access_token")
    new_refresh = refreshed.get("refresh_token") or refresh_token

    if not new_access:
        return {
            "success": False,
            "code": "TW_REFRESH_INVALID",
            "message": "Refresh succeeded but no access_token returned.",
            "refresh_raw": refreshed.get("raw"),
        }

    # Persist best effort
    _persist_tokens_best_effort(
        business_id=business_id,
        user__id=user__id,
        platform=platform_used,
        destination_id=destination_id,
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=refreshed.get("expires_in"),
        log_tag=log_tag,
    )

    # Retry once with new token
    def do_request_retry():
        return do_request(override_access_token=new_access)

    status2, js2, raw2, access_used2 = do_request_retry()
    if status2 < 400:
        return {
            "success": True,
            "status_code": status2,
            "json": js2,
            "raw": raw2,
            "access_token_used": access_used2,
            "refreshed": True,
        }

    return {
        "success": False,
        "status_code": status2,
        "error": _parse_x_error(js2) or {"raw": raw2},
        "code": f"{request_fn_name}_ERROR",
        "message": "Request failed even after token refresh.",
        "refreshed": True,
    }


# -------------------------------------------------------------------
# X API calls
# -------------------------------------------------------------------

def _get_x_user_info(
    *,
    user_id: str,
    access_token: str,
    log_tag: str,
) -> Tuple[int, Dict[str, Any], str]:
    url = f"{X_API_BASE}/users/{user_id}"
    params = {
        "user.fields": "id,name,username,profile_image_url,created_at,verified,public_metrics,description,url,location",
    }
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    if status >= 400:
        Log.info(f"{log_tag} X user lookup error: {status} {raw}")
    return status, js, raw


def _get_x_user_tweets(
    *,
    user_id: str,
    access_token: str,
    max_results: int,
    pagination_token: Optional[str],
    start_time: Optional[str],
    end_time: Optional[str],
    fields: Optional[List[str]],
    exclude: Optional[List[str]],
    log_tag: str,
) -> Tuple[int, Dict[str, Any], str]:
    url = f"{X_API_BASE}/users/{user_id}/tweets"

    tweet_fields_default = [
        "id",
        "text",
        "created_at",
        "lang",
        "public_metrics",
        "possibly_sensitive",
        "source",
        "conversation_id",
        "reply_settings",
    ]
    tweet_fields = fields or tweet_fields_default

    params: Dict[str, Any] = {
        "max_results": max(5, min(int(max_results), 100)),
        "tweet.fields": ",".join(tweet_fields),
    }

    if pagination_token:
        params["pagination_token"] = pagination_token
    if start_time:
        params["start_time"] = start_time
    if end_time:
        params["end_time"] = end_time
    if exclude:
        params["exclude"] = ",".join(exclude)

    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    if status >= 400:
        Log.info(f"{log_tag} X user tweets error: {status} {raw}")
    return status, js, raw


def _get_x_tweet_best_effort(
    *,
    post_id: str,
    access_token: str,
    fields: List[str],
    log_tag: str,
) -> Tuple[int, Dict[str, Any], str]:
    url = f"{X_API_BASE}/tweets/{post_id}"
    params = {"tweet.fields": ",".join(fields)}
    status, js, raw = _request_get(
        url=url,
        headers=_auth_headers(access_token),
        params=params,
        timeout=30,
    )
    if status >= 400:
        Log.info(f"{log_tag} X tweet lookup error: {status} {raw}")
    return status, js, raw


def _normalize_user_info(js: Dict[str, Any]) -> Dict[str, Any]:
    data = (js or {}).get("data") or {}
    pm = data.get("public_metrics") or {}
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "username": data.get("username"),
        "profile_image_url": data.get("profile_image_url"),
        "description": data.get("description"),
        "url": data.get("url"),
        "location": data.get("location"),
        "created_at": data.get("created_at"),
        "verified": data.get("verified"),
        "public_metrics": pm,
        "followers_count": pm.get("followers_count"),
        "following_count": pm.get("following_count"),
        "tweet_count": pm.get("tweet_count"),
        "listed_count": pm.get("listed_count"),
    }


def _normalize_posts_list(js: Dict[str, Any]) -> Dict[str, Any]:
    data = (js or {}).get("data") or []
    meta = (js or {}).get("meta") or {}

    posts: List[Dict[str, Any]] = []
    for t in data:
        pm = t.get("public_metrics") or {}
        posts.append({
            "id": t.get("id"),
            "text": t.get("text"),
            "created_at": t.get("created_at"),
            "lang": t.get("lang"),
            "source": t.get("source"),
            "conversation_id": t.get("conversation_id"),
            "reply_settings": t.get("reply_settings"),
            "possibly_sensitive": t.get("possibly_sensitive"),
            "metrics": {
                "like_count": pm.get("like_count", 0),
                "reply_count": pm.get("reply_count", 0),
                "repost_count": pm.get("repost_count", pm.get("retweet_count", 0)),
                "quote_count": pm.get("quote_count", 0),
                "bookmark_count": pm.get("bookmark_count", 0),
                # Often absent unless tier allows
                "impression_count": pm.get("impression_count"),
            },
        })

    return {"posts": posts, "meta": meta}


def _normalize_tweet_metrics(js: Dict[str, Any]) -> Dict[str, Any]:
    data = (js or {}).get("data") or {}
    pm = data.get("public_metrics") or {}
    om = data.get("organic_metrics") or {}
    nm = data.get("non_public_metrics") or {}

    metrics = {
        "like_count": pm.get("like_count", 0),
        "reply_count": pm.get("reply_count", 0),
        "repost_count": pm.get("repost_count", pm.get("retweet_count", 0)),
        "quote_count": pm.get("quote_count", 0),
        "bookmark_count": pm.get("bookmark_count", 0),
    }

    impression = (
        om.get("impression_count")
        or nm.get("impression_count")
        or pm.get("impression_count")
    )
    if impression is not None:
        metrics["impression_count"] = impression

    for extra_key in ["url_link_clicks", "user_profile_clicks"]:
        val = om.get(extra_key) or nm.get(extra_key)
        if val is not None:
            metrics[extra_key] = val

    return {
        "id": data.get("id"),
        "text": data.get("text"),
        "created_at": data.get("created_at"),
        "metrics": metrics,
    }


# -------------------------------------------------------------------
# X (Twitter): ACCOUNT INSIGHTS
# -------------------------------------------------------------------

@blp_twitter_insights.route("/social/x/account-insights", methods=["GET"])
class XAccountInsightsResource(MethodView):
    """
    X account analytics using stored SocialAccount token.

    Query params:
      - destination_id (required): X User ID (numeric string)
      - debug: "true" to include debug info
      - compare_to_followers (optional int): baseline for computing follower delta
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[x_insights.py][account][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        x_user_id = (request.args.get("destination_id") or "").strip()
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        if not x_user_id:
            return jsonify({"success": False, "message": "destination_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        acct = _get_destination_account(
            business_id=business_id,
            user__id=user__id,
            destination_id=x_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "TW_NOT_CONNECTED",
                "message": "Twitter/X account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        # Which platform key did we actually use?
        platform_used = acct.get("platform") or PLATFORM_PRIMARY

        access_token, refresh_token = _get_tokens_from_acct(acct)
        ensured = _ensure_valid_access_token(
            business_id=business_id,
            user__id=user__id,
            platform_used=platform_used,
            destination_id=x_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            log_tag=log_tag,
        )
        if not ensured.get("success"):
            return jsonify({"success": False, **ensured}), HTTP_STATUS_CODES["BAD_REQUEST"]

        def do_user_lookup(override_access_token: Optional[str] = None):
            tok = override_access_token or ensured["access_token"]
            status, js, raw = _get_x_user_info(user_id=x_user_id, access_token=tok, log_tag=log_tag)
            return status, js, raw, tok

        # Request with auto-refresh on 401/403
        rr = _refresh_and_retry_get(
            request_fn_name="TW_ACCOUNT_LOOKUP",
            do_request=do_user_lookup,
            business_id=business_id,
            user__id=user__id,
            platform_used=platform_used,
            destination_id=x_user_id,
            refresh_token=ensured.get("refresh_token"),
            log_tag=log_tag,
        )
        
        Log.info(f"rr: {rr}")

        if not rr.get("success"):
            # Normalize error contract like your other endpoints
            code = rr.get("code") or "TW_ACCOUNT_LOOKUP_ERROR"
            if code == "TW_TOKEN_EXPIRED":
                return jsonify({
                    "success": False,
                    "code": "TW_TOKEN_EXPIRED",
                    "message": "Twitter/X access token has expired. Please reconnect.",
                    "error": rr.get("error"),
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]

            return jsonify({
                "success": False,
                "code": "TW_ACCOUNT_LOOKUP_ERROR",
                "message": rr.get("message") or _pick(rr.get("error", {}), "detail", "title") or "Unauthorized",
                "error": rr.get("error"),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        info = _normalize_user_info(rr["json"])
        followers_count = info.get("followers_count")

        delta_followers = None
        compare_to = (request.args.get("compare_to_followers") or "").strip()
        if compare_to:
            try:
                base = int(compare_to)
                if isinstance(followers_count, int):
                    delta_followers = followers_count - base
            except ValueError:
                delta_followers = None

        result = {
            "platform": "x",
            "destination_id": x_user_id,
            "destination_name": info.get("name") or info.get("username"),
            "account_info": {
                "id": info.get("id"),
                "name": info.get("name"),
                "username": info.get("username"),
                "profile_image_url": info.get("profile_image_url"),
                "description": info.get("description"),
                "url": info.get("url"),
                "location": info.get("location"),
                "created_at": info.get("created_at"),
                "verified": info.get("verified"),
            },
            "public_metrics": info.get("public_metrics"),
            "summaries": {
                "followers_count": followers_count,
                "following_count": info.get("following_count"),
                "tweet_count": info.get("tweet_count"),
                "listed_count": info.get("listed_count"),
                "new_followers_delta": delta_followers,
            },
        }

        if debug_mode:
            result["debug"] = {
                "refreshed": rr.get("refreshed"),
                "platform_lookup_used": platform_used,
                "note": "X API does not provide 'new followers per day' natively. Store daily snapshots and diff them.",
                "available_account_metrics": ["followers_count", "following_count", "tweet_count", "listed_count"],
            }

        return jsonify({"success": True, "data": result}), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# X (Twitter): POST LIST
# -------------------------------------------------------------------

@blp_twitter_insights.route("/social/twitter/post-list", methods=["GET"])
class TwitterPostListResource(MethodView):
    """
    List tweets for an X user.

    Query params:
      - destination_id (required): X User ID
      - limit: default 25, max 100
      - pagination_token
      - since (YYYY-MM-DD)
      - until (YYYY-MM-DD)
      - exclude: replies,retweets
      - fields: comma-separated tweet.fields
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[twitter_insights][post_list][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        x_user_id = (request.args.get("destination_id") or "").strip()
        if not x_user_id:
            return jsonify({"success": False, "message": "destination_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        limit_raw = (request.args.get("limit") or "25").strip()
        try:
            limit = min(max(int(limit_raw), 5), 100)
        except ValueError:
            limit = 25

        pagination_token = (request.args.get("pagination_token") or "").strip() or None
        since = (request.args.get("since") or "").strip() or None
        until = (request.args.get("until") or "").strip() or None
        exclude_qs = (request.args.get("exclude") or "").strip()
        fields_qs = (request.args.get("fields") or "").strip()
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        start_time = None
        end_time = None

        if since:
            dt = _parse_ymd(since)
            if not dt:
                return jsonify({"success": False, "message": "Invalid 'since' format. Use YYYY-MM-DD"}), HTTP_STATUS_CODES["BAD_REQUEST"]
            start_time = _iso8601(dt.replace(tzinfo=timezone.utc))

        if until:
            dt = _parse_ymd(until)
            if not dt:
                return jsonify({"success": False, "message": "Invalid 'until' format. Use YYYY-MM-DD"}), HTTP_STATUS_CODES["BAD_REQUEST"]
            end_time = _iso8601((dt + timedelta(days=1)).replace(tzinfo=timezone.utc))

        fields = [f.strip() for f in fields_qs.split(",") if f.strip()] if fields_qs else None
        exclude = [e.strip() for e in exclude_qs.split(",") if e.strip()] if exclude_qs else None

        acct = _get_destination_account(
            business_id=business_id,
            user__id=user__id,
            destination_id=x_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "TW_NOT_CONNECTED",
                "message": "Twitter/X account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        platform_used = acct.get("platform") or PLATFORM_PRIMARY

        access_token, refresh_token = _get_tokens_from_acct(acct)
        ensured = _ensure_valid_access_token(
            business_id=business_id,
            user__id=user__id,
            platform_used=platform_used,
            destination_id=x_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            log_tag=log_tag,
        )
        if not ensured.get("success"):
            return jsonify({"success": False, **ensured}), HTTP_STATUS_CODES["BAD_REQUEST"]

        def do_posts_list(override_access_token: Optional[str] = None):
            tok = override_access_token or ensured["access_token"]
            status, js, raw = _get_x_user_tweets(
                user_id=x_user_id,
                access_token=tok,
                max_results=limit,
                pagination_token=pagination_token,
                start_time=start_time,
                end_time=end_time,
                fields=fields,
                exclude=exclude,
                log_tag=log_tag,
            )
            return status, js, raw, tok

        rr = _refresh_and_retry_get(
            request_fn_name="TW_POST_LIST",
            do_request=do_posts_list,
            business_id=business_id,
            user__id=user__id,
            platform_used=platform_used,
            destination_id=x_user_id,
            refresh_token=ensured.get("refresh_token"),
            log_tag=log_tag,
        )

        if not rr.get("success"):
            if rr.get("code") == "TW_TOKEN_EXPIRED":
                return jsonify({
                    "success": False,
                    "code": "TW_TOKEN_EXPIRED",
                    "message": "Twitter/X access token has expired. Please reconnect.",
                    "error": rr.get("error"),
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]

            return jsonify({
                "success": False,
                "code": "TW_POST_LIST_ERROR",
                "message": rr.get("message") or _pick(rr.get("error", {}), "detail", "title") or "Failed to fetch post list",
                "error": rr.get("error"),
                "debug": {"refreshed": rr.get("refreshed")} if debug_mode else None,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        norm = _normalize_posts_list(rr["json"])
        meta = norm.get("meta") or {}

        result = {
            "platform": "x",
            "destination_id": x_user_id,
            "count": len(norm.get("posts") or []),
            "limit": limit,
            "since": since,
            "until": until,
            "posts": norm.get("posts") or [],
            "pagination": {
                "has_next": bool(meta.get("next_token")),
                "has_previous": bool(meta.get("previous_token")),
                "next_token": meta.get("next_token"),
                "previous_token": meta.get("previous_token"),
                "result_count": meta.get("result_count"),
            },
        }

        if debug_mode:
            result["debug"] = {
                "refreshed": rr.get("refreshed"),
                "platform_lookup_used": platform_used,
                "note": "Some fields/metrics may be missing depending on X API tier.",
            }

        return jsonify({"success": True, "data": result}), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# X (Twitter): POST INSIGHTS
# -------------------------------------------------------------------

@blp_twitter_insights.route("/social/twitter/post-insights", methods=["GET"])
class TwitterPostInsightsResource(MethodView):
    """
    Tweet metrics for a specific tweet.

    Query params:
      - destination_id (required): X User ID (for token lookup)
      - post_id (required): tweet id
      - debug: "true"
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[twitter_insights][post][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        x_user_id = (request.args.get("destination_id") or "").strip()
        post_id = (request.args.get("post_id") or "").strip()
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        if not x_user_id:
            return jsonify({"success": False, "message": "destination_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]
        if not post_id:
            return jsonify({"success": False, "message": "post_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        acct = _get_destination_account(
            business_id=business_id,
            user__id=user__id,
            destination_id=x_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "TW_NOT_CONNECTED",
                "message": "Twitter/X account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        platform_used = acct.get("platform") or PLATFORM_PRIMARY
        access_token, refresh_token = _get_tokens_from_acct(acct)

        ensured = _ensure_valid_access_token(
            business_id=business_id,
            user__id=user__id,
            platform_used=platform_used,
            destination_id=x_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            log_tag=log_tag,
        )
        if not ensured.get("success"):
            return jsonify({"success": False, **ensured}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Best-effort field sets for impressions/organic metrics
        field_sets = [
            ["created_at", "text", "public_metrics", "organic_metrics"],
            ["created_at", "text", "public_metrics", "non_public_metrics"],
            ["created_at", "text", "public_metrics"],
        ]

        used_fields: Optional[List[str]] = None
        last_error: Optional[Dict[str, Any]] = None

        for fields in field_sets:
            def do_tweet_lookup(override_access_token: Optional[str] = None):
                tok = override_access_token or ensured["access_token"]
                status, js, raw = _get_x_tweet_best_effort(
                    post_id=post_id,
                    access_token=tok,
                    fields=fields,
                    log_tag=log_tag,
                )
                return status, js, raw, tok

            rr = _refresh_and_retry_get(
                request_fn_name="TW_POST_INSIGHTS",
                do_request=do_tweet_lookup,
                business_id=business_id,
                user__id=user__id,
                platform_used=platform_used,
                destination_id=x_user_id,
                refresh_token=ensured.get("refresh_token"),
                log_tag=log_tag,
            )

            if rr.get("success"):
                used_fields = fields
                tweet = _normalize_tweet_metrics(rr["json"])
                return jsonify({
                    "success": True,
                    "data": {
                        "platform": "x",
                        "destination_id": x_user_id,
                        "post_id": post_id,
                        "post": tweet,
                        "debug": {
                            "used_fields": used_fields,
                            "refreshed": rr.get("refreshed"),
                            "organic_metrics_note": "impression_count/url_link_clicks/user_profile_clicks require higher X API tier.",
                        } if debug_mode else None,
                    }
                }), HTTP_STATUS_CODES["OK"]

            # If token expired, surface that immediately
            if rr.get("code") == "TW_TOKEN_EXPIRED":
                return jsonify({
                    "success": False,
                    "code": "TW_TOKEN_EXPIRED",
                    "message": "Twitter/X access token has expired. Please reconnect.",
                    "error": rr.get("error"),
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]

            last_error = rr

        return jsonify({
            "success": False,
            "code": "TW_POST_INSIGHTS_ERROR",
            "message": _pick((last_error or {}).get("error", {}), "detail", "title") or "Failed to fetch post metrics",
            "error": (last_error or {}).get("error"),
            "debug": last_error if debug_mode else None,
        }), HTTP_STATUS_CODES["BAD_REQUEST"]


# -------------------------------------------------------------------
# X (Twitter): POST DETAILS
# -------------------------------------------------------------------

@blp_twitter_insights.route("/social/twitter/post-details", methods=["GET"])
class TwitterPostDetailsResource(MethodView):
    """
    Tweet details for a specific tweet.

    Query params:
      - destination_id (required): X User ID (for token lookup)
      - post_id (required)
      - fields: comma-separated tweet.fields
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[twitter_insights][post_details][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        x_user_id = (request.args.get("destination_id") or "").strip()
        post_id = (request.args.get("post_id") or "").strip()
        fields_qs = (request.args.get("fields") or "").strip()
        debug_mode = (request.args.get("debug") or "").lower() == "true"

        if not x_user_id:
            return jsonify({"success": False, "message": "destination_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]
        if not post_id:
            return jsonify({"success": False, "message": "post_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        default_fields = [
            "id",
            "text",
            "created_at",
            "author_id",
            "conversation_id",
            "lang",
            "source",
            "public_metrics",
            "possibly_sensitive",
            "reply_settings",
            "entities",
            "attachments",
        ]
        fields = [f.strip() for f in fields_qs.split(",") if f.strip()] if fields_qs else default_fields

        acct = _get_destination_account(
            business_id=business_id,
            user__id=user__id,
            destination_id=x_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "TW_NOT_CONNECTED",
                "message": "Twitter/X account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        platform_used = acct.get("platform") or PLATFORM_PRIMARY
        access_token, refresh_token = _get_tokens_from_acct(acct)

        ensured = _ensure_valid_access_token(
            business_id=business_id,
            user__id=user__id,
            platform_used=platform_used,
            destination_id=x_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            log_tag=log_tag,
        )
        if not ensured.get("success"):
            return jsonify({"success": False, **ensured}), HTTP_STATUS_CODES["BAD_REQUEST"]

        def do_details(override_access_token: Optional[str] = None):
            tok = override_access_token or ensured["access_token"]
            url = f"{X_API_BASE}/tweets/{post_id}"
            params = {
                "tweet.fields": ",".join(fields),
                "expansions": "attachments.media_keys,author_id",
                "media.fields": "url,preview_image_url,type,duration_ms",
                "user.fields": "name,username,profile_image_url",
            }
            status, js, raw = _request_get(url=url, headers=_auth_headers(tok), params=params, timeout=30)
            if status >= 400:
                Log.info(f"{log_tag} X post details error: {status} {raw}")
            return status, js, raw, tok

        rr = _refresh_and_retry_get(
            request_fn_name="TW_POST_DETAILS",
            do_request=do_details,
            business_id=business_id,
            user__id=user__id,
            platform_used=platform_used,
            destination_id=x_user_id,
            refresh_token=ensured.get("refresh_token"),
            log_tag=log_tag,
        )

        if not rr.get("success"):
            if rr.get("code") == "TW_TOKEN_EXPIRED":
                return jsonify({
                    "success": False,
                    "code": "TW_TOKEN_EXPIRED",
                    "message": "Twitter/X access token has expired. Please reconnect.",
                    "error": rr.get("error"),
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]

            return jsonify({
                "success": False,
                "code": "TW_POST_DETAILS_ERROR",
                "message": rr.get("message") or _pick(rr.get("error", {}), "detail", "title") or "Failed to fetch post details",
                "error": rr.get("error"),
                "debug": {"refreshed": rr.get("refreshed")} if debug_mode else None,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        js = rr["json"]
        data = (js or {}).get("data") or {}
        includes = (js or {}).get("includes") or {}

        pm = data.get("public_metrics") or {}
        data["metrics"] = {
            "like_count": pm.get("like_count", 0),
            "reply_count": pm.get("reply_count", 0),
            "repost_count": pm.get("repost_count", pm.get("retweet_count", 0)),
            "quote_count": pm.get("quote_count", 0),
            "bookmark_count": pm.get("bookmark_count", 0),
        }

        if "media" in includes:
            data["media"] = includes["media"]
        if "users" in includes and includes["users"]:
            data["author"] = includes["users"][0]

        result = {
            "platform": "x",
            "post": data,
        }

        if debug_mode:
            result["debug"] = {
                "refreshed": rr.get("refreshed"),
                "platform_lookup_used": platform_used,
            }

        return jsonify({"success": True, "data": result}), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# X (Twitter): DISCOVER (diagnostic)
# -------------------------------------------------------------------

@blp_twitter_insights.route("/social/twitter/discover-metrics", methods=["GET"])
class TwitterDiscoverMetricsResource(MethodView):
    """
    Diagnostic endpoint: user lookup + posts list + optional post metrics.
    Query params:
      - destination_id (required): X User ID
      - sample_post_id (optional)
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[twitter_insights][discover][{client_ip}]"

        user = g.get("current_user") or {}
        business_id = str(user.get("business_id") or "")
        user__id = str(user.get("_id") or "")

        if not business_id or not user__id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        x_user_id = (request.args.get("destination_id") or "").strip()
        sample_post_id = (request.args.get("sample_post_id") or "").strip() or None

        if not x_user_id:
            return jsonify({"success": False, "message": "destination_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        acct = _get_destination_account(
            business_id=business_id,
            user__id=user__id,
            destination_id=x_user_id,
        )

        if not acct:
            return jsonify({
                "success": False,
                "code": "TW_NOT_CONNECTED",
                "message": "Twitter/X account not connected",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        platform_used = acct.get("platform") or PLATFORM_PRIMARY
        access_token, refresh_token = _get_tokens_from_acct(acct)

        ensured = _ensure_valid_access_token(
            business_id=business_id,
            user__id=user__id,
            platform_used=platform_used,
            destination_id=x_user_id,
            access_token=access_token,
            refresh_token=refresh_token,
            log_tag=log_tag,
        )
        if not ensured.get("success"):
            return jsonify({"success": False, **ensured}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # User lookup probe
        def do_user(override_access_token: Optional[str] = None):
            tok = override_access_token or ensured["access_token"]
            status, js, raw = _get_x_user_info(user_id=x_user_id, access_token=tok, log_tag=log_tag)
            return status, js, raw, tok

        user_rr = _refresh_and_retry_get(
            request_fn_name="TW_ACCOUNT_LOOKUP",
            do_request=do_user,
            business_id=business_id,
            user__id=user__id,
            platform_used=platform_used,
            destination_id=x_user_id,
            refresh_token=ensured.get("refresh_token"),
            log_tag=log_tag,
        )

        # Posts list probe (last 7 days)
        since, until = _get_date_range_last_n_days(7)
        start_time = _iso8601(_parse_ymd(since).replace(tzinfo=timezone.utc))
        end_time = _iso8601((_parse_ymd(until) + timedelta(days=1)).replace(tzinfo=timezone.utc))

        def do_posts(override_access_token: Optional[str] = None):
            tok = override_access_token or (user_rr.get("access_token_used") or ensured["access_token"])
            status, js, raw = _get_x_user_tweets(
                user_id=x_user_id,
                access_token=tok,
                max_results=5,
                pagination_token=None,
                start_time=start_time,
                end_time=end_time,
                fields=None,
                exclude=None,
                log_tag=log_tag,
            )
            return status, js, raw, tok

        posts_rr = _refresh_and_retry_get(
            request_fn_name="TW_POST_LIST",
            do_request=do_posts,
            business_id=business_id,
            user__id=user__id,
            platform_used=platform_used,
            destination_id=x_user_id,
            refresh_token=ensured.get("refresh_token"),
            log_tag=log_tag,
        )

        # Optional post metrics probe
        metrics_probe = None
        if sample_post_id:
            field_sets = [
                ["created_at", "text", "public_metrics", "organic_metrics"],
                ["created_at", "text", "public_metrics", "non_public_metrics"],
                ["created_at", "text", "public_metrics"],
            ]

            probe_ok = False
            probe_used = None
            probe_metrics = None
            probe_err = None

            for fs in field_sets:
                def do_post_metrics(override_access_token: Optional[str] = None):
                    tok = override_access_token or ensured["access_token"]
                    status, js, raw = _get_x_tweet_best_effort(
                        post_id=sample_post_id,
                        access_token=tok,
                        fields=fs,
                        log_tag=log_tag,
                    )
                    return status, js, raw, tok

                pr = _refresh_and_retry_get(
                    request_fn_name="TW_POST_INSIGHTS",
                    do_request=do_post_metrics,
                    business_id=business_id,
                    user__id=user__id,
                    platform_used=platform_used,
                    destination_id=x_user_id,
                    refresh_token=ensured.get("refresh_token"),
                    log_tag=log_tag,
                )
                if pr.get("success"):
                    probe_ok = True
                    probe_used = fs
                    tweet = _normalize_tweet_metrics(pr["json"])
                    probe_metrics = list((tweet.get("metrics") or {}).keys())
                    break
                probe_err = pr.get("error")

            metrics_probe = {
                "success": probe_ok,
                "used_fields": probe_used,
                "available_metrics": probe_metrics,
                "error": probe_err,
            }

        # Build response
        user_part = (
            {"success": True, **_normalize_user_info(user_rr["json"])}
            if user_rr.get("success")
            else {"success": False, "status_code": user_rr.get("status_code"), "error": user_rr.get("error")}
        )

        posts_part = (
            {"success": True, "count": len((_normalize_posts_list(posts_rr["json"]).get("posts") or []))}
            if posts_rr.get("success")
            else {"success": False, "status_code": posts_rr.get("status_code"), "error": posts_rr.get("error")}
        )

        return jsonify({
            "success": True,
            "data": {
                "platform": "x",
                "destination_id": x_user_id,
                "platform_lookup_used": platform_used,
                "user_lookup": user_part,
                "posts_list_probe": posts_part,
                "post_metrics_probe": metrics_probe,
                "refreshed_any": bool(user_rr.get("refreshed") or posts_rr.get("refreshed")),
                "notes": [
                    "Refresh tokens require offline.access scope.",
                    "X API does not provide follower_count time-series; store daily snapshots and diff them.",
                    "impression_count/url_link_clicks/user_profile_clicks require higher X API tier (organic/non_public metrics).",
                ],
            }
        }), HTTP_STATUS_CODES["OK"]