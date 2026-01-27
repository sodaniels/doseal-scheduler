# app/resources/social/oauth_tiktok_resource.py

from __future__ import annotations

import os
import json
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

import requests
from flask.views import MethodView
from flask import request, jsonify, redirect, g
from flask_smorest import Blueprint

from ...utils.logger import Log
from ...utils.redis import get_redis, set_redis_with_expiry, remove_redis
from ...constants.service_code import HTTP_STATUS_CODES
from ..doseal.admin.admin_business_resource import token_required

from ...models.social.social_account import SocialAccount

# Reuse your shared helpers (same pattern as fb/ig/x)
from ...utils.schedule_helper import (
    _safe_json_load,
    _store_state,
    _consume_state,
    _store_selection,
    _load_selection,
    _delete_selection,
    _redirect_to_frontend,
)

blp_tiktok_oauth = Blueprint("tiktok_oauth", __name__)

# -------------------------------------------------------------------
# TikTok config + endpoints
# -------------------------------------------------------------------
TIKTOK_AUTH_URL = os.getenv("TIKTOK_AUTH_URL", "https://www.tiktok.com/v2/auth/authorize/")
TIKTOK_TOKEN_URL = os.getenv("TIKTOK_TOKEN_URL", "https://open.tiktokapis.com/v2/oauth/token/")
TIKTOK_USER_INFO_URL = os.getenv("TIKTOK_USER_INFO_URL", "https://open.tiktokapis.com/v2/user/info/")

# Scopes you already enabled in dashboard + shown on consent screen
DEFAULT_TIKTOK_SCOPES = "user.info.basic,video.upload,video.publish"


def _require_tiktok_env(log_tag: str):
    client_key = os.getenv("TIKTOK_CLIENT_KEY") or os.getenv("TIKTOK_CLIENT_ID")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
    redirect_uri = os.getenv("TIKTOK_REDIRECT_URI")
    if not client_key:
        Log.info(f"{log_tag} ENV missing: TIKTOK_CLIENT_KEY (or TIKTOK_CLIENT_ID)")
    if not client_secret:
        Log.info(f"{log_tag} ENV missing: TIKTOK_CLIENT_SECRET")
    if not redirect_uri:
        Log.info(f"{log_tag} ENV missing: TIKTOK_REDIRECT_URI")
    return client_key, client_secret, redirect_uri


def _tiktok_exchange_code_for_token(*, code: str, redirect_uri: str, log_tag: str) -> dict:
    """
    TikTok OAuth 2.0 token exchange.
    Endpoint: https://open.tiktokapis.com/v2/oauth/token/
    """
    client_key, client_secret, _ = _require_tiktok_env(log_tag)
    if not client_key or not client_secret:
        raise Exception("TikTok OAuth env missing (client_key/client_secret)")

    payload = {
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }

    r = requests.post(TIKTOK_TOKEN_URL, data=payload, timeout=30)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}

    # TikTok often uses 200 even for some errors; check fields too
    if r.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
        raise Exception(f"TikTok token exchange failed: {data}")

    # Expected keys include:
    # access_token, expires_in, open_id, refresh_token, refresh_expires_in, scope, token_type
    if not data.get("access_token"):
        raise Exception(f"TikTok token exchange missing access_token: {data}")

    return data


def _tiktok_get_user_info(*, access_token: str, log_tag: str) -> dict:
    """
    ✅ Correct TikTok user info (v2):
      GET https://open.tiktokapis.com/v2/user/info/?fields=...
      Authorization: Bearer <access_token>
    """
    if not access_token:
        raise Exception("Missing TikTok access_token")

    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"fields": "open_id,union_id,avatar_url,display_name"}

    r = requests.get(TIKTOK_USER_INFO_URL, headers=headers, params=params, timeout=30)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}

    # 1) HTTP failure
    if r.status_code >= HTTP_STATUS_CODES["BAD_REQUEST"]:
        raise Exception(f"TikTok user info HTTP error: {data}")

    # 2) TikTok logical failure: error.code != ok
    err = (data.get("error") or {}) if isinstance(data, dict) else {}
    code = err.get("code")

    # TikTok success commonly returns code="ok"
    if code not in (None, "ok", 0, "0"):
        raise Exception(f"TikTok user info failed: {data}")

    return data


# -------------------------------------------------------------------
# TikTok: START
# -------------------------------------------------------------------
@blp_tiktok_oauth.route("/social/oauth/tiktok/start", methods=["GET"])
class TikTokOauthStartResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_tiktok_resource.py][TikTokOauthStartResource][get][{client_ip}]"

        client_key, _, redirect_uri = _require_tiktok_env(log_tag)
        if not client_key or not redirect_uri:
            return jsonify({"success": False, "message": "TikTok OAuth env missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        user = g.get("current_user", {}) or {}
        owner = {"business_id": str(user.get("business_id")), "user__id": str(user.get("_id"))}
        if not owner["business_id"] or not owner["user__id"]:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        state = secrets.token_urlsafe(24)
        _store_state(owner, state, "tk", ttl_seconds=600)

        # You can override scopes via env if you want
        scope = (os.getenv("TIKTOK_SCOPES") or DEFAULT_TIKTOK_SCOPES).strip()

        params = {
            "client_key": client_key,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "state": state,
        }

        url = TIKTOK_AUTH_URL + "?" + urlencode(params)
        Log.info(f"{log_tag} Redirecting to TikTok OAuth consent screen")
        return redirect(url)


# -------------------------------------------------------------------
# TikTok: CALLBACK
# -------------------------------------------------------------------
@blp_tiktok_oauth.route("/social/oauth/tiktok/callback", methods=["GET"])
class TikTokOauthCallbackResource(MethodView):
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_tiktok_resource.py][TikTokOauthCallbackResource][get][{client_ip}]"

        error = request.args.get("error")
        if error:
            return jsonify({
                "success": False,
                "message": "OAuth authorization failed",
                "error": error,
                "error_description": request.args.get("error_description"),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        code = request.args.get("code")
        state = request.args.get("state")
        if not code or not state:
            return jsonify({"success": False, "message": "Missing code/state"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        state_doc = _consume_state(state, "tk")
        owner = (state_doc or {}).get("owner") or {}
        if not owner.get("business_id") or not owner.get("user__id"):
            return jsonify({"success": False, "message": "Invalid/expired OAuth state"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        _, _, redirect_uri = _require_tiktok_env(log_tag)
        if not redirect_uri:
            return jsonify({"success": False, "message": "TIKTOK_REDIRECT_URI missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        try:
            token_data = _tiktok_exchange_code_for_token(code=code, redirect_uri=redirect_uri, log_tag=log_tag)
            access_token = token_data["access_token"]

            # ✅ IMPORTANT: use v2 user-info endpoint + Bearer header + fields param
            user_info = _tiktok_get_user_info(access_token=access_token, log_tag=log_tag)

            selection_key = secrets.token_urlsafe(24)
            _store_selection(
                provider="tk",
                selection_key=selection_key,
                payload={
                    "owner": owner,
                    "token_data": token_data,
                    "user_info": user_info,  # safe for UI (no tokens needed in accounts endpoint)
                },
                ttl_seconds=300,
            )

            return _redirect_to_frontend("/connect/tiktok", selection_key)

        except Exception as e:
            Log.info(f"{log_tag} TikTok OAuth failed: {e}")
            return jsonify({"success": False, "message": "TikTok OAuth failed"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# TikTok: LIST ACCOUNTS (from redis selection_key)
# -------------------------------------------------------------------
@blp_tiktok_oauth.route("/social/tiktok/accounts", methods=["GET"])
class TikTokAccountsResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_tiktok_resource.py][TikTokAccountsResource][get][{client_ip}]"

        selection_key = request.args.get("selection_key")
        if not selection_key:
            return jsonify({"success": False, "message": "selection_key is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        raw = get_redis(f"tk_select:{selection_key}")
        if not raw:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["NOT_FOUND"]

        doc = _safe_json_load(raw, default={}) or {}
        owner = doc.get("owner") or {}
        token_data = doc.get("token_data") or {}
        user_info = doc.get("user_info") or {}

        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            Log.info(f"{log_tag} Owner mismatch: current_user != selection owner")
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        open_id = token_data.get("open_id")
        ui = (user_info.get("data") or {}).get("user") or {}
        display_name = ui.get("display_name")
        avatar_url = ui.get("avatar_url")

        safe_accounts = [
            {
                "platform": "tiktok",
                "destination_type": "tiktok_user",
                "destination_id": open_id,
                "username": display_name,
                "avatar_url": avatar_url,
            }
        ]

        return jsonify({"success": True, "data": {"accounts": safe_accounts}}), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# TikTok: CONNECT ACCOUNT (finalize into social_accounts)
# -------------------------------------------------------------------
@blp_tiktok_oauth.route("/social/tiktok/connect-account", methods=["POST"])
class TikTokConnectAccountResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_tiktok_resource.py][TikTokConnectAccountResource][post][{client_ip}]"

        body = request.get_json(silent=True) or {}
        selection_key = body.get("selection_key")
        destination_id = body.get("destination_id")  # optional open_id for extra safety

        if not selection_key:
            return jsonify({"success": False, "message": "selection_key is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        raw = get_redis(f"tk_select:{selection_key}")
        if not raw:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["NOT_FOUND"]

        doc = _safe_json_load(raw, default={}) or {}
        owner = doc.get("owner") or {}
        token_data = doc.get("token_data") or {}
        user_info = doc.get("user_info") or {}

        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            Log.info(f"{log_tag} Owner mismatch: current_user != selection owner")
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        expires_in = int(token_data.get("expires_in") or 0)
        refresh_expires_in = int(token_data.get("refresh_expires_in") or 0)
        open_id = str(token_data.get("open_id") or "")

        ui = (user_info.get("data") or {}).get("user") or {}
        display_name = ui.get("display_name")
        avatar_url = ui.get("avatar_url")

        if not access_token or not refresh_token or not open_id:
            return jsonify({
                "success": False,
                "message": "Invalid OAuth selection (missing token data). Please reconnect."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        if destination_id and str(destination_id) != open_id:
            return jsonify({"success": False, "message": "destination_id mismatch for this selection_key"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        token_expires_at = (datetime.utcnow() + timedelta(seconds=expires_in)) if expires_in > 0 else None

        try:
            SocialAccount.upsert_destination(
                business_id=owner["business_id"],
                user__id=owner["user__id"],
                platform="tiktok",
                destination_id=open_id,
                destination_type="tiktok_user",
                destination_name=display_name or open_id,

                access_token_plain=access_token,
                refresh_token_plain=refresh_token,
                token_expires_at=token_expires_at.isoformat() if token_expires_at else None,

                scopes=(token_data.get("scope") or "").split(",") if token_data.get("scope") else [],
                platform_user_id=open_id,
                platform_username=display_name,

                meta={
                    "open_id": open_id,
                    "display_name": display_name,
                    "avatar_url": avatar_url,
                    "refresh_expires_in": refresh_expires_in,
                    "token_type": token_data.get("token_type"),
                },
            )

            try:
                remove_redis(f"tk_select:{selection_key}")
            except Exception:
                pass

            return jsonify({"success": True, "message": "TikTok account connected successfully"}), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert: {e}")
            return jsonify({"success": False, "message": "Failed to connect TikTok account"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# TikTok: WEBHOOKS (separate from OAuth callback)
# IMPORTANT:
# - Keep this URL DIFFERENT from the OAuth redirect URL.
# - Implement signature verification later if you enable it in TikTok settings.
# -------------------------------------------------------------------
@blp_tiktok_oauth.route("/social/webhooks/tiktok", methods=["GET", "POST"])
class TikTokWebhooksResource(MethodView):
    def get(self):
        """
        Some platforms do GET verification. If TikTok sends a challenge param, echo it.
        Safe default: return 200 always.
        """
        client_ip = request.remote_addr
        log_tag = f"[oauth_tiktok_resource.py][TikTokWebhooksResource][get][{client_ip}]"

        # If your TikTok webhook verification uses a query param, echo it.
        # (Exact scheme can vary depending on product; adjust once you confirm TikTok's challenge format.)
        challenge = request.args.get("challenge") or request.args.get("hub.challenge")
        if challenge:
            Log.info(f"{log_tag} webhook challenge received")
            return jsonify({"challenge": challenge}), HTTP_STATUS_CODES["OK"]

        return jsonify({"success": True}), HTTP_STATUS_CODES["OK"]

    def post(self):
        """
        Receive webhook events. Store/process asynchronously.
        """
        client_ip = request.remote_addr
        log_tag = f"[oauth_tiktok_resource.py][TikTokWebhooksResource][post][{client_ip}]"

        payload = request.get_json(silent=True) or {}
        Log.info(f"{log_tag} webhook payload: {payload}")

        # TODO: push to queue / DB for processing
        return jsonify({"success": True}), HTTP_STATUS_CODES["OK"]