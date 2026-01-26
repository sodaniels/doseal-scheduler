import os
import json
import secrets
import requests
from urllib.parse import urlencode

from flask.views import MethodView
from flask_smorest import Blueprint
from flask import request, redirect, jsonify, g

from ...utils.logger import Log
from ...constants.service_code import HTTP_STATUS_CODES
from ...resources.doseal.admin.admin_business_resource import token_required

from ...utils.redis import (
    get_redis,
    set_redis_with_expiry,
    remove_redis,
)

from ...models.social.social_account import SocialAccount
from ...services.social.adapters.facebook_adapter import FacebookAdapter


blp_fb_oauth = Blueprint("fb_oauth", __name__)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _safe_json_load(raw, default=None):
    try:
        return json.loads(raw) if raw else (default if default is not None else None)
    except Exception:
        return default if default is not None else None


def _require_env(key: str, log_tag: str):
    val = os.getenv(key)
    if not val:
        Log.info(f"{log_tag} {key} not set")
        return None
    return val


# -------------------------------------------------------------------
# 1) START OAuth (GET)
# Browser hits this -> redirect to Facebook dialog
# IMPORTANT: this MUST be token_required so we can tie state -> user/business.
# -------------------------------------------------------------------

@blp_fb_oauth.route("/social/oauth/facebook/start", methods=["GET"])
class FacebookOauthStartResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_facebook.py][FacebookOauthStartResource][get][{client_ip}]"

        redirect_uri = _require_env("FACEBOOK_REDIRECT_URI", log_tag)
        meta_app_id = _require_env("META_APP_ID", log_tag)
        if not redirect_uri or not meta_app_id:
            return jsonify({"success": False, "message": "Server OAuth config missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # CSRF state (and also binds this OAuth flow to this logged-in user)
        state = secrets.token_urlsafe(24)
        

        # Attach owner context so callback can upsert without needing auth header
        user = g.get("current_user", {}) or {}
        owner = {
            "business_id": str(user.get("business_id")),
            "user__id": str(user.get("_id")),
        }

        if not owner["business_id"] or not owner["user__id"]:
            Log.info(f"{log_tag} Missing business_id/user__id in current_user")
            return jsonify({"success": False, "message": "Could not identify current user for OAuth"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Store state for 10 minutes
        try:
            set_redis_with_expiry(
                f"fb_oauth_state:{state}",
                600,
                json.dumps({"owner": owner}),
            )
        except Exception as e:
            Log.info(f"{log_tag} Failed to store state in Redis: {e}")
            return jsonify({"success": False, "message": "Could not initialize OAuth flow"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # Minimal scopes for Page posting flow
        # pages_show_list -> list pages
        # pages_read_engagement -> often required for review + reading page info
        # pages_manage_posts -> publish to Page
        params = {
            "client_id": meta_app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            "scope": "pages_show_list,pages_read_engagement,pages_manage_posts",
        }

        url = "https://www.facebook.com/v20.0/dialog/oauth?" + urlencode(params)
        Log.info(f"{log_tag} Redirecting to Meta OAuth consent screen")
        return redirect(url)


# -------------------------------------------------------------------
# 2) CALLBACK (GET)
# Facebook redirects here after user approves.
# Callback exchanges code -> token, fetches pages, stores them in Redis,
# then redirects to frontend with selection_key (NO tokens leaked to frontend).
# -------------------------------------------------------------------

@blp_fb_oauth.route("/social/oauth/facebook/callback", methods=["GET"])
class FacebookOauthCallbackResource(MethodView):
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_facebook.py][FacebookOauthCallbackResource][get][{client_ip}]"

        # Handle denial
        error = request.args.get("error")
        if error:
            return jsonify({
                "success": False,
                "message": "OAuth authorization failed",
                "error": error,
                "error_reason": request.args.get("error_reason"),
                "error_description": request.args.get("error_description"),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        code = request.args.get("code")
        state = request.args.get("state")
        if not code or not state:
            Log.info(f"{log_tag} Missing code/state in callback")
            return jsonify({"success": False, "message": "Missing required OAuth parameters"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Validate state from Redis
        state_key = f"fb_oauth_state:{state}"
        state_raw = None
        try:
            state_raw = get_redis(state_key)
            if not state_raw:
                Log.info(f"{log_tag} Invalid/expired state: {state}")
                return jsonify({"success": False, "message": "Invalid or expired OAuth state"}), HTTP_STATUS_CODES["BAD_REQUEST"]
            remove_redis(state_key)  # one-time use
        except Exception as e:
            Log.info(f"{log_tag} Error validating state in Redis: {e}")
            return jsonify({"success": False, "message": "Could not validate OAuth state"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        state_doc = _safe_json_load(state_raw, default={}) or {}
        owner = (state_doc.get("owner") or {})

        if not owner.get("business_id") or not owner.get("user__id"):
            Log.info(f"{log_tag} State owner missing (business_id/user__id)")
            return jsonify({"success": False, "message": "OAuth state is missing owner info"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        redirect_uri = _require_env("FACEBOOK_REDIRECT_URI", log_tag)
        meta_app_id = _require_env("META_APP_ID", log_tag)
        meta_app_secret = _require_env("META_APP_SECRET", log_tag)
        if not redirect_uri or not meta_app_id or not meta_app_secret:
            return jsonify({"success": False, "message": "Server OAuth config missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # Exchange code for user access token
        token_url = os.getenv(
            "FACEBOOK_GRAPH_OAUTH_ACCESS_TOKEN_URL",
            "https://graph.facebook.com/v20.0/oauth/access_token"
        )
        payload = {
            "client_id": meta_app_id,
            "client_secret": meta_app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }

        try:
            resp = requests.get(token_url, params=payload, timeout=30)
            data = resp.json()
        except Exception as e:
            Log.info(f"{log_tag} Token exchange request failed: {e}")
            return jsonify({"success": False, "message": "Token exchange failed"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        if resp.status_code != HTTP_STATUS_CODES["OK"]:
            Log.info(f"{log_tag} Meta token exchange error: {data}")
            return jsonify({
                "success": False,
                "message": "Token exchange failed",
                "meta_error": data
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        user_access_token = data.get("access_token")
        if not user_access_token:
            Log.info(f"{log_tag} No access_token returned by Meta")
            return jsonify({"success": False, "message": "Meta did not return an access_token"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # Fetch pages (each page item includes page access_token)
        try:
            pages = FacebookAdapter.list_pages(user_access_token)
        except Exception as e:
            Log.info(f"{log_tag} Failed to fetch user pages: {e}")
            return jsonify({
                "success": False,
                "message": "Could not fetch user pages after OAuth"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # Create short-lived selection key
        selection_key = secrets.token_urlsafe(24)

        # Store pages + owner in Redis for 5 minutes (NO token to frontend)
        try:
            set_redis_with_expiry(
                f"fb_pages:{selection_key}",
                300,
                json.dumps({
                    "owner": owner,
                    "pages": pages,  # includes page access_token from /me/accounts
                })
            )
        except Exception as e:
            Log.info(f"{log_tag} Failed to store pages in Redis: {e}")
            return jsonify({"success": False, "message": "Could not store page selection data"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        frontend_url = os.getenv("FRONT_END_BASE_URL")
        if not frontend_url:
            # If no frontend yet, just return JSON for testing
            return jsonify({
                "success": True,
                "message": "OAuth successful. Use selection_key to list pages.",
                "selection_key": selection_key,
                "pages_count": len(pages) if isinstance(pages, list) else None
            }), HTTP_STATUS_CODES["OK"]

        return redirect(f"{frontend_url}/connect/facebook?selection_key={selection_key}")


