# app/routes/social/oauth_youtube_resource.py

import os
import json
import secrets
from urllib.parse import urlencode

from flask.views import MethodView
from flask import request, jsonify, redirect, g
from flask_smorest import Blueprint

from ...utils.logger import Log
from ...utils.redis import get_redis, set_redis_with_expiry, remove_redis
from ...utils.json_response import prepared_response
from ...utils.helpers import make_log_tag
from ...constants.service_code import HTTP_STATUS_CODES, SYSTEM_USERS
from ..doseal.admin.admin_business_resource import token_required

from ...models.social.social_account import SocialAccount
from ...services.social.adapters.youtube_adapter import YouTubeAdapter
from ...utils.plan.quota_enforcer import QuotaEnforcer, PlanLimitError

from ...utils.schedule_helper import (
    _safe_json_load,
    _store_state,
    _consume_state,
    _store_selection,
    _load_selection,
    _delete_selection,
    _redirect_to_frontend,
)


blp_youtube_oauth = Blueprint("youtube_oauth", __name__)


def _require_env(name: str, log_tag: str) -> str:
    val = (os.getenv(name) or "").strip()
    if not val:
        Log.info(f"{log_tag} missing env: {name}")
    return val


def _youtube_scopes() -> str:
    # Minimal for upload + read channel identity:
    scopes = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
    ]
    return " ".join(scopes)


# -------------------------------------------------------------------
# YOUTUBE: START
# -------------------------------------------------------------------
@blp_youtube_oauth.route("/social/oauth/youtube/start", methods=["GET"])
class YouTubeOauthStartResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        body = request.get_json(silent=True) or {}

        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")

        # Optional business override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = str(form_business_id)
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "oauth_youtube_resource.py",
            "YouTubeOauthStartResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        client_id = _require_env("YOUTUBE_CLIENT_ID", log_tag)
        redirect_uri = _require_env("YOUTUBE_REDIRECT_URI", log_tag)
        if not client_id or not redirect_uri:
            return jsonify({"success": False, "message": "Server YouTube OAuth config missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        owner = {"business_id": target_business_id, "user__id": auth_user__id}
        if not owner["business_id"] or not owner["user__id"]:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        state = secrets.token_urlsafe(24)
        _store_state(owner, state, "yt", ttl_seconds=600)

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _youtube_scopes(),
            "state": state,

            # IMPORTANT for refresh_token:
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }

        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
        Log.info(f"{log_tag} redirecting to Google OAuth consent")
        return redirect(url)


# -------------------------------------------------------------------
# YOUTUBE: CALLBACK
# -------------------------------------------------------------------
@blp_youtube_oauth.route("/social/oauth/youtube/callback", methods=["GET"])
class YouTubeOauthCallbackResource(MethodView):
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_youtube_resource.py][YouTubeOauthCallbackResource][get][{client_ip}]"

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

        state_doc = _consume_state(state, "yt")
        owner = (state_doc or {}).get("owner") or {}
        if not owner.get("business_id") or not owner.get("user__id"):
            return jsonify({"success": False, "message": "Invalid/expired OAuth state"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        client_id = _require_env("YOUTUBE_CLIENT_ID", log_tag)
        client_secret = _require_env("YOUTUBE_CLIENT_SECRET", log_tag)
        redirect_uri = _require_env("YOUTUBE_REDIRECT_URI", log_tag)
        if not client_id or not client_secret or not redirect_uri:
            return jsonify({"success": False, "message": "YOUTUBE env missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        try:
            token_data = YouTubeAdapter.exchange_code_for_token(
                client_id=client_id,
                client_secret=client_secret,
                code=code,
                redirect_uri=redirect_uri,
                log_tag=log_tag,
            )

            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")  # may be None
            expires_in = token_data.get("expires_in")

            # Fetch channels (mine=true)
            channels = YouTubeAdapter.list_my_channels(
                access_token=access_token,
                log_tag=log_tag,
            )

            selection_key = secrets.token_urlsafe(24)
            _store_selection(
                provider="yt",
                selection_key=selection_key,
                payload={
                    "owner": owner,
                    "token_data": {
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "expires_in": expires_in,
                    },
                    "channels": channels,
                },
                ttl_seconds=300,
            )

            return _redirect_to_frontend("/connect/youtube", selection_key)

        except Exception as e:
            Log.info(f"{log_tag} youtube callback failed: {e}")
            return jsonify({"success": False, "message": "Could not complete YouTube OAuth"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# YOUTUBE: LIST CHANNELS (selection screen)
# -------------------------------------------------------------------
@blp_youtube_oauth.route("/social/youtube/channels", methods=["GET"])
class YouTubeChannelsResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_youtube_resource.py][YouTubeChannelsResource][get][{client_ip}]"

        selection_key = request.args.get("selection_key")
        if not selection_key:
            return jsonify({"success": False, "message": "selection_key is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("yt", selection_key)
        if not sel:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["NOT_FOUND"]

        owner = sel.get("owner") or {}
        channels = sel.get("channels") or []

        # Ensure logged-in user matches owner
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Safe response
        safe_channels = []
        for c in channels:
            safe_channels.append({
                "channel_id": c.get("channel_id"),
                "title": c.get("title"),
                "custom_url": c.get("custom_url"),
                "thumb": c.get("thumb"),
            })

        return jsonify({"success": True, "data": {"channels": safe_channels}}), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# YOUTUBE: CONNECT CHANNEL (finalize into social_accounts)
# -------------------------------------------------------------------
@blp_youtube_oauth.route("/social/youtube/connect-channel", methods=["POST"])
class YouTubeConnectChannelResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr
        body = request.get_json(silent=True) or {}

        selection_key = body.get("selection_key")
        channel_id = body.get("channel_id")

        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")

        # Optional business override
        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = str(form_business_id)
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "oauth_youtube_resource.py",
            "YouTubeConnectChannelResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        if not selection_key or not channel_id:
            return jsonify({"success": False, "message": "selection_key and channel_id are required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("yt", selection_key)
        if not sel:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        owner = sel.get("owner") or {}
        token_data = sel.get("token_data") or {}
        channels = sel.get("channels") or []

        # Ensure logged-in user matches selection owner
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        selected = next((c for c in channels if str(c.get("channel_id")) == str(channel_id)), None)
        if not selected:
            return jsonify({"success": False, "message": "Invalid channel_id for this selection_key"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")  # may be None

        if not access_token:
            return jsonify({"success": False, "message": "Missing access_token. Reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # ---- PLAN ENFORCER ----
        enforcer = QuotaEnforcer(target_business_id)
        try:
            enforcer.reserve(
                counter_name="social_accounts",
                limit_key="max_social_accounts",
                qty=1,
                period="billing",
                reason="social_accounts:create",
            )
        except PlanLimitError as e:
            Log.info(f"{log_tag} plan limit reached: {e.meta}")
            return prepared_response(False, "FORBIDDEN", e.message, errors=e.meta)

        try:
            SocialAccount.upsert_destination(
                business_id=owner["business_id"],
                user__id=owner["user__id"],
                platform="youtube",
                destination_id=str(channel_id),
                destination_type="channel",
                destination_name=selected.get("title") or str(channel_id),

                access_token_plain=access_token,
                refresh_token_plain=refresh_token,
                token_expires_at=None,
                scopes=[
                    "https://www.googleapis.com/auth/youtube.upload",
                    "https://www.googleapis.com/auth/youtube.readonly",
                ],
                platform_user_id=str(channel_id),
                platform_username=selected.get("title"),

                meta={
                    "channel_id": str(channel_id),
                    "title": selected.get("title"),
                    "custom_url": selected.get("custom_url"),
                    "thumb": selected.get("thumb"),
                },
            )

            _delete_selection("yt", selection_key)

            return jsonify({"success": True, "message": "YouTube channel connected successfully"}), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert: {e}")
            enforcer.release(counter_name="social_accounts", qty=1, period="billing")
            return jsonify({"success": False, "message": "Failed to connect YouTube channel"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]