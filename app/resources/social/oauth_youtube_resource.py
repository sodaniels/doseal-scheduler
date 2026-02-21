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
from ...utils.plan.quota_enforcer import QuotaEnforcer, PlanLimitError
from ...utils.social.pre_process_checks import PreProcessCheck
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
from ...utils.social.token_utils import (
    is_token_expired,
    is_token_expiring_soon,
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
        admin_id = str(user_info.get("admin_id"))
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
        
        ##################### PRE TRANSACTION CHECKS #########################
        pre_check = PreProcessCheck(
            business_id=target_business_id,
            account_type=account_type,
            admin_id=admin_id
        )
        initial_check_result = pre_check.initial_processs_checks()
        if initial_check_result is not None:
            return initial_check_result
        ##################### PRE TRANSACTION CHECKS #########################


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
        
        user_info = g.get("current_user", {}) or {}
        auth_business_id = str(user_info.get("business_id"))
        admin_id = str(user_info.get("admin_id"))
        account_type = user_info.get("account_type")
        
        ##################### PRE TRANSACTION CHECKS #########################
        pre_check = PreProcessCheck(
            business_id=auth_business_id,
            account_type=account_type,
            admin_id=admin_id
        )
        initial_check_result = pre_check.initial_processs_checks()
        if initial_check_result is not None:
            return initial_check_result
        ##################### PRE TRANSACTION CHECKS #########################

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
#   - If channel already exists and token not expired/expiring soon => block (already connected)
#   - If exists but expired/expiring soon => allow reconnect WITHOUT consuming quota
#   - If not exists => consume quota then create
#
# NOTE:
# - Google OAuth access tokens expire quickly; refresh_token is what matters.
# - If you store token_expires_at, your helpers can behave accurately.
# - If token_expires_at is None, we treat it as "unknown" and:
#     * if destination exists => allow overwrite without quota (safe for refresh flow),
#       OR you can choose to block if refresh_token exists and you want stricter UX.
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
        admin_id = str(user_info.get("admin_id"))
        account_type = user_info.get("account_type")
        
        ##################### PRE TRANSACTION CHECKS #########################
        pre_check = PreProcessCheck(
            business_id=auth_business_id,
            account_type=account_type,
            admin_id=admin_id
        )
        initial_check_result = pre_check.initial_processs_checks()
        if initial_check_result is not None:
            return initial_check_result
        ##################### PRE TRANSACTION CHECKS #########################


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
            return jsonify({
                "success": False,
                "message": "selection_key and channel_id are required"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("yt", selection_key)
        if not sel:
            return jsonify({
                "success": False,
                "message": "Selection expired. Please reconnect."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        owner = sel.get("owner") or {}
        token_data = sel.get("token_data") or {}
        channels = sel.get("channels") or []

        # Ensure logged-in user matches selection owner
        user = g.get("current_user", {}) or {}
        if (
            str(user.get("business_id")) != str(owner.get("business_id"))
            or str(user.get("_id")) != str(owner.get("user__id"))
        ):
            return jsonify({
                "success": False,
                "message": "Not allowed for this selection_key"
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        selected = next((c for c in channels if str(c.get("channel_id")) == str(channel_id)), None)
        if not selected:
            return jsonify({
                "success": False,
                "message": "Invalid channel_id for this selection_key"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")  # may be None
        token_expires_at = token_data.get("token_expires_at")  # optional if you stored it
        scopes = token_data.get("scopes") or token_data.get("scope") or []

        if not access_token:
            return jsonify({
                "success": False,
                "message": "Missing access_token. Reconnect."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # ------------------------------------------------------------
        # ✅ NEW: check if this destination already exists
        # ------------------------------------------------------------
        channel_id = str(channel_id or "").strip()
        if not channel_id:
            return jsonify({
                "success": False,
                "message": "channel_id is required"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            existing = SocialAccount.get_destination(
                owner["business_id"],
                owner["user__id"],
                "youtube",
                channel_id,
            )
        except Exception:
            existing = None

        # ---- PLAN ENFORCER ----
        enforcer = QuotaEnforcer(target_business_id)

        consume_quota = True
        if existing:
            # If token not expired => block; if expiring soon/expired => allow refresh (no quota)
            # If token_expires_at is None, expiry helpers may treat as "unknown" and raise.
            # In that case we allow overwrite without quota (safe for refresh flow).
            try:
                if not is_token_expired(existing):
                    if is_token_expiring_soon(existing, minutes=10):
                        consume_quota = False
                        Log.info(f"{log_tag} YT token expiring soon; allowing OAuth reconnect without consuming quota")
                    else:
                        return jsonify({
                            "success": False,
                            "message": "This YouTube channel is already connected.",
                            "code": "ALREADY_CONNECTED",
                        }), HTTP_STATUS_CODES["CONFLICT"]
                else:
                    consume_quota = False
                    Log.info(f"{log_tag} YT token expired; allowing OAuth reconnect without consuming quota")
            except Exception:
                consume_quota = False
                Log.info(f"{log_tag} Could not determine YT token expiry; allowing overwrite without consuming quota")

        # ------------------------------------------------------------
        # ✅ Only reserve quota when creating a NEW destination
        # ------------------------------------------------------------
        if consume_quota:
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
                destination_id=channel_id,
                destination_type="channel",
                destination_name=selected.get("title") or channel_id,

                access_token_plain=access_token,
                refresh_token_plain=refresh_token or (existing.get("refresh_token_plain") if isinstance(existing, dict) else None),

                # Prefer new token_expires_at from token_data; otherwise keep existing
                token_expires_at=(
                    token_expires_at
                    or (existing.get("token_expires_at") if isinstance(existing, dict) else None)
                    or None
                ),

                # Prefer selection scopes; else keep existing; else defaults
                scopes=(
                    scopes
                    if isinstance(scopes, list) and scopes
                    else (
                        existing.get("scopes")
                        if isinstance(existing, dict) and existing.get("scopes")
                        else [
                            "https://www.googleapis.com/auth/youtube.upload",
                            "https://www.googleapis.com/auth/youtube.readonly",
                        ]
                    )
                ),

                platform_user_id=channel_id,
                platform_username=selected.get("title"),

                meta={
                    "channel_id": channel_id,
                    "title": selected.get("title"),
                    "custom_url": selected.get("custom_url"),
                    "thumb": selected.get("thumb"),
                },
            )

            _delete_selection("yt", selection_key)

            return jsonify({
                "success": True,
                "message": "YouTube channel connected successfully"
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert: {e}")
            if consume_quota:
                enforcer.release(counter_name="social_accounts", qty=1, period="billing")
            return jsonify({
                "success": False,
                "message": "Failed to connect YouTube channel"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]













