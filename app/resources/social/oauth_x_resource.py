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
from ...constants.service_code import HTTP_STATUS_CODES
from ..doseal.admin.admin_business_resource import token_required

from ...models.social.social_account import SocialAccount
from ...services.social.adapters.facebook_adapter import FacebookAdapter
from ...services.social.adapters.instagram_adapter import InstagramAdapter
from ...services.social.adapters.x_adapter import XAdapter

from ...utils.schedule_helper import (
    _safe_json_load, _require_env, _exchange_code_for_token, _store_state, _consume_state,
    _store_selection, _load_selection, _delete_selection, _redirect_to_frontend, _require_x_env
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
        log_tag = f"[oauth_x.py][XOauthStartResource][get][{client_ip}]"

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
# -------------------------------------------------------------------
@blp_x_oauth.route("/social/x/connect-account", methods=["POST"])
class XConnectAccountResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_x.py][XConnectAccountResource][post][{client_ip}]"

        body = request.get_json(silent=True) or {}
        selection_key = body.get("selection_key")

        # Optional: allow client to pass destination_id (user_id) for extra safety
        destination_id = body.get("destination_id")  # X user_id

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
                token_expires_at=None,

                # Scopes are not always available in OAuth 1.0a
                scopes=["tweet.write", "tweet.read"],

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
            return jsonify({
                "success": False,
                "message": "Failed to connect X account"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

