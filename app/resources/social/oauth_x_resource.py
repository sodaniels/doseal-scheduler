# app/resources/social/oauth_tiktok_resource.py

import os
import json
import secrets
from urllib.parse import urlencode

import requests
from flask.views import MethodView
from flask import request, jsonify, redirect, g
from flask_smorest import Blueprint

from ...utils.logger import Log
from ...utils.redis import get_redis, set_redis_with_expiry, remove_redis
from ...utils.json_response import prepared_response
from ...constants.service_code import HTTP_STATUS_CODES, SYSTEM_USERS
from ..doseal.admin.admin_business_resource import token_required

from ...models.social.social_account import SocialAccount
from ...services.social.adapters.x_adapter import XAdapter
from ...utils.plan.quota_enforcer import QuotaEnforcer, PlanLimitError
from ...utils.social.pre_process_checks import PreProcessCheck
from ...utils.schedule_helper import (
    _safe_json_load, _require_env, _exchange_code_for_token, _store_state, _consume_state,
    _store_selection, _load_selection, _delete_selection, _redirect_to_frontend, _require_x_env
)
from ...utils.helpers import make_log_tag
from ...utils.social.token_utils import (
    is_token_expired,
    is_token_expiring_soon,
)


blp_x_oauth = Blueprint("x_oauth", __name__)


# -------------------------------------------------------------------
# X: START (OAuth 1.0a)
# -------------------------------------------------------------------
@blp_x_oauth.route("/social/oauth/x/start", methods=["GET"])
class XOauthStartResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        
        body = request.get_json(silent=True) or {}
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        admin_id = str(user_info.get("admin_id"))
        account_type = user_info.get("account_type")

        # Optional business override
        form_business_id = body.get("business_id")
        target_business_id = form_business_id if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id else auth_business_id

        log_tag = make_log_tag(
            "oauth_x_resource.py",
            "XOauthStartResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
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

        consumer_key, consumer_secret, callback_url = _require_x_env(log_tag)
        if not consumer_key or not consumer_secret or not callback_url:
            return jsonify({"success": False, "message": "X OAuth env missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        user = g.get("current_user", {}) or {}
        owner = {"business_id": str(user.get("business_id")), "user__id": str(user.get("_id"))}
        if not owner["business_id"] or not owner["user__id"]:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # ✅ Create state
        state = secrets.token_urlsafe(24)

        # ✅ IMPORTANT: embed state into callback_url so callback ALWAYS gets it
        joiner = "&" if "?" in callback_url else "?"
        callback_url_with_state = f"{callback_url}{joiner}{urlencode({'state': state})}"

        try:
            # 1) request token
            oauth_token, oauth_token_secret = XAdapter.get_request_token(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                callback_url=callback_url_with_state,  # ✅ contains state
            )

            # 2) Store by state
            # key: x_oauth_state:<state>
            set_redis_with_expiry(
                f"x_oauth_state:{state}",
                600,
                json.dumps({
                    "owner": owner,
                    "oauth_token": oauth_token,
                    "oauth_token_secret": oauth_token_secret,
                }),
            )

            # 3) ALSO store by oauth_token (fallback / debugging)
            set_redis_with_expiry(
                f"x_oauth_token:{oauth_token}",
                600,
                json.dumps({
                    "owner": owner,
                    "state": state,
                    "oauth_token": oauth_token,
                    "oauth_token_secret": oauth_token_secret,
                }),
            )

            Log.info(f"{log_tag} stored state_key=x_oauth_state:{state} token_key=x_oauth_token:{oauth_token}")

            return redirect(XAdapter.build_authorize_url(oauth_token))

        except Exception as e:
            Log.info(f"{log_tag} Failed to start X OAuth: {e}")
            return jsonify({"success": False, "message": "Could not start X OAuth"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# X: CALLBACK (OAuth 1.0a)
# -------------------------------------------------------------------
@blp_x_oauth.route("/social/oauth/x/callback", methods=["GET"])
class XOauthCallbackResource(MethodView):
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_x.py][XOauthCallbackResource][get][{client_ip}]"

        denied = request.args.get("denied")
        if denied:
            return jsonify({"success": False, "message": "User denied authorization"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        oauth_token = request.args.get("oauth_token")
        oauth_verifier = request.args.get("oauth_verifier")
        state = request.args.get("state")  # ✅ should now be present because callback_url includes it

        Log.info(f"{log_tag} args={dict(request.args)}")

        if not oauth_token or not oauth_verifier:
            return jsonify({"success": False, "message": "Missing oauth_token/oauth_verifier"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        doc = {}

        # 1) preferred lookup by state
        if state:
            raw = get_redis(f"x_oauth_state:{state}")
            doc = _safe_json_load(raw, default={}) if raw else {}

        # 2) fallback by oauth_token
        if not doc:
            raw = get_redis(f"x_oauth_token:{oauth_token}")
            doc = _safe_json_load(raw, default={}) if raw else {}

        if not doc:
            Log.info(f"{log_tag} cache-miss state={state} oauth_token={oauth_token}")
            return jsonify({"success": False, "message": "OAuth state expired. Retry connect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        owner = doc.get("owner") or {}
        tmp_token = doc.get("oauth_token")
        tmp_secret = doc.get("oauth_token_secret")

        if not owner.get("business_id") or not owner.get("user__id") or not tmp_token or not tmp_secret:
            return jsonify({"success": False, "message": "Invalid OAuth cache"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        consumer_key, consumer_secret, _ = _require_x_env(log_tag)
        if not consumer_key or not consumer_secret:
            return jsonify({"success": False, "message": "X OAuth env missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        try:
            token_data = XAdapter.exchange_access_token(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                oauth_token=tmp_token,
                oauth_token_secret=tmp_secret,
                oauth_verifier=oauth_verifier,
            )

            selection_key = secrets.token_urlsafe(24)
            _store_selection(
                provider="x",
                selection_key=selection_key,
                payload={"owner": owner, "token_data": token_data},
                ttl_seconds=300,
            )

            # cleanup
            try:
                if state:
                    remove_redis(f"x_oauth_state:{state}")
                remove_redis(f"x_oauth_token:{oauth_token}")
            except Exception:
                pass

            return _redirect_to_frontend("/connect/x", selection_key)

        except Exception as e:
            Log.info(f"{log_tag} X OAuth failed: {e}")
            return jsonify({"success": False, "message": "X OAuth failed"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# -------------------------------------------------------------------
# X: LIST ACCOUNTS (from redis selection_key)
# -------------------------------------------------------------------
@blp_x_oauth.route("/social/x/accounts", methods=["GET"])
class XAccountsResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_x.py][XAccountsResource][get][{client_ip}]"

        selection_key = request.args.get("selection_key")
        if not selection_key:
            return jsonify(
                {"success": False, "message": "selection_key is required"}
            ), HTTP_STATUS_CODES["BAD_REQUEST"]

        # key: x_select:<selection_key>
        raw = get_redis(f"x_select:{selection_key}")
        if not raw:
            return jsonify(
                {"success": False, "message": "Selection expired. Please reconnect."}
            ), HTTP_STATUS_CODES["NOT_FOUND"]

        doc = _safe_json_load(raw, default={}) or {}

        owner = doc.get("owner") or {}
        token_data = doc.get("token_data") or {}

        # Ensure logged-in user matches owner
        user = g.get("current_user", {}) or {}
        if (
            str(user.get("business_id")) != str(owner.get("business_id"))
            or str(user.get("_id")) != str(owner.get("user__id"))
        ):
            Log.info(f"{log_tag} Owner mismatch: current_user != selection owner")
            return jsonify(
                {"success": False, "message": "Not allowed for this selection_key"}
            ), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # ----------------------------
        # SAFE RESPONSE ONLY
        # ----------------------------
        safe_accounts = [
            {
                "platform": "x",
                "destination_type": "user",
                "destination_id": token_data.get("user_id"),
                "username": token_data.get("screen_name"),
            }
        ]

        return jsonify(
            {"success": True, "data": {"accounts": safe_accounts}}
        ), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# X: CONNECT ACCOUNT (finalize into social_accounts)
#   - If destination already exists and token not expired/expiring soon => block (already connected)
#   - If exists but expired/expiring soon => allow reconnect WITHOUT consuming quota
#   - If not exists => consume quota then create
#
# NOTE (X OAuth 1.0a):
# - oauth_token/oauth_token_secret typically don't have an expiry timestamp you can rely on.
# - So token_expires_at is usually None.
# - In that case, we treat reconnect as "refresh/overwrite for same account" => no quota.
# - If you later add a health-check endpoint for X and you detect 401, you can mark token invalid.
# -------------------------------------------------------------------
@blp_x_oauth.route("/social/x/connect-account", methods=["POST"])
class XConnectAccountResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr

        body = request.get_json(silent=True) or {}
        selection_key = body.get("selection_key")

        # Optional: allow client to pass destination_id (user_id) for extra safety
        destination_id = body.get("destination_id")  # X user_id

        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")

        # Optional business override for system roles
        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = str(form_business_id)
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "oauth_x_resource.py",
            "XConnectAccountResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        if not selection_key:
            return jsonify({
                "success": False,
                "message": "selection_key is required"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # key: x_select:<selection_key>
        raw = get_redis(f"x_select:{selection_key}")
        if not raw:
            return jsonify({
                "success": False,
                "message": "Selection expired. Please reconnect."
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        doc = _safe_json_load(raw, default={}) or {}
        owner = doc.get("owner") or {}
        token_data = doc.get("token_data") or {}

        # Ensure logged-in user matches selection owner
        user = g.get("current_user", {}) or {}
        if (
            str(user.get("business_id")) != str(owner.get("business_id"))
            or str(user.get("_id")) != str(owner.get("user__id"))
        ):
            Log.info(f"{log_tag} Owner mismatch: current_user != selection owner")
            return jsonify({
                "success": False,
                "message": "Not allowed for this selection_key"
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # token_data should contain: oauth_token, oauth_token_secret, user_id, screen_name
        oauth_token = token_data.get("oauth_token")
        oauth_token_secret = token_data.get("oauth_token_secret")
        user_id = str(token_data.get("user_id") or "")
        screen_name = token_data.get("screen_name")

        if not oauth_token or not oauth_token_secret or not user_id:
            return jsonify({
                "success": False,
                "message": "Invalid OAuth selection (missing token data). Please reconnect."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Optional: validate client-provided destination_id matches
        if destination_id and str(destination_id) != user_id:
            return jsonify({
                "success": False,
                "message": "destination_id mismatch for this selection_key"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # ------------------------------------------------------------
        # ✅ NEW: check if this destination already exists
        # ------------------------------------------------------------
        try:
            existing = SocialAccount.get_destination(
                owner["business_id"],
                owner["user__id"],
                "x",
                user_id,
            )
        except Exception:
            existing = None

        enforcer = QuotaEnforcer(target_business_id)

        consume_quota = True
        if existing:
            # X OAuth 1.0a typically has no expiry timestamp.
            # If you stored token_expires_at and you can check it, use helpers.
            # Otherwise treat as overwrite (token refresh) => no quota.
            try:
                if not is_token_expired(existing):
                    if is_token_expiring_soon(existing, minutes=10):
                        consume_quota = False
                        Log.info(f"{log_tag} X token expiring soon; allowing reconnect without consuming quota")
                    else:
                        return jsonify({
                            "success": False,
                            "message": "This X account is already connected.",
                            "code": "ALREADY_CONNECTED",
                        }), HTTP_STATUS_CODES["CONFLICT"]
                else:
                    consume_quota = False
                    Log.info(f"{log_tag} X token expired; allowing reconnect without consuming quota")
            except Exception:
                consume_quota = False
                Log.info(f"{log_tag} Could not determine X token expiry; allowing overwrite without consuming quota")

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
                platform="x",
                destination_id=user_id,
                destination_type="user",
                destination_name=screen_name or user_id,

                # For X OAuth 1.0a, store BOTH token + secret.
                # If your schema only has access_token_plain, store token there and put secret in refresh_token_plain.
                access_token_plain=oauth_token,
                refresh_token_plain=oauth_token_secret,

                # If you ever store expires_at, keep it; else None
                token_expires_at=(
                    existing.get("token_expires_at")
                    if isinstance(existing, dict)
                    else None
                ),

                # Scopes are not always available in OAuth 1.0a; keep minimal
                scopes=(existing.get("scopes") if isinstance(existing, dict) and existing.get("scopes") else ["tweet.write", "tweet.read"]),

                platform_user_id=user_id,
                platform_username=screen_name,

                meta={
                    "user_id": user_id,
                    "screen_name": screen_name,
                    "oauth_version": "1.0a",
                },
            )

            # one-time use
            try:
                remove_redis(f"x_select:{selection_key}")
            except Exception:
                pass

            return jsonify({
                "success": True,
                "message": "X account connected successfully"
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert: {e}")
            if consume_quota:
                enforcer.release(counter_name="social_accounts", qty=1, period="billing")
            return jsonify({
                "success": False,
                "message": "Failed to connect X account"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]