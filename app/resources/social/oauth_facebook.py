import os, json, secrets
from xmlrpc import client
from flask.views import MethodView
import requests
from urllib.parse import urlencode

from flask_smorest import Blueprint, abort

from flask import request, redirect, jsonify, g
from ...utils.logger import Log # import logging
from ...models.social.social_account import SocialAccount
from ...extensions import db as db_ext
from ...utils.redis import (
    get_redis, set_redis_with_expiry, remove_redis, set_redis
)
from ...constants.service_code import (
    HTTP_STATUS_CODES,
)
from ...resources.doseal.admin.admin_business_resource import token_required
from ...services.social.adapters.facebook_adapter import FacebookAdapter


blp_fb_oauth = Blueprint("fb_oauth", __name__)

# -------------------------------------------------------------------
# START OAuth
# -------------------------------------------------------------------

@blp_fb_oauth.route("/social/oauth/facebook/start", methods=["GET"])
class FacebookOauthResource(MethodView):
    # @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[fb_oauth.py][facebook_oauth_start][{client_ip}]"
        redirect_uri = os.getenv("FACEBOOK_REDIRECT_URI")
        meta_app_id = os.getenv("META_APP_ID")

        if not redirect_uri:
            Log.info(f"{log_tag} FACEBOOK_REDIRECT_URI not set")
            return jsonify({"success": False, "message": "FACEBOOK_REDIRECT_URI not set"}), 500

        if not meta_app_id:
            Log.info(f"{log_tag} META_APP_ID not set")
            return jsonify({"success": False, "message": "META_APP_ID not set"}), 500

        # CSRF state
        state = secrets.token_urlsafe(24)

        # Store state for 10 minutes (adjust as you like)
        try:
            set_redis_with_expiry(f"fb_oauth_state:{state}", 600, "1")
        except Exception as e:
            Log.info(f"{log_tag} Failed to store state in Redis: {e}")
            return jsonify({"success": False, "message": "Could not initialize OAuth flow"}), 500

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
    
@blp_fb_oauth.route("/social/oauth/facebook/callback", methods=["GET"])
class FacebookOauthResource(MethodView):
    # @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[fb_oauth.py][facebook_oauth_callback][{client_ip}]"
        error = request.args.get("error")
        error_reason = request.args.get("error_reason")
        error_description = request.args.get("error_description")

        if error:
            Log.info(f"{log_tag} OAuth denied/failed: {error} | {error_reason} | {error_description}")
            return jsonify({
                "success": False,
                "message": "OAuth authorization failed",
                "error": error,
                "error_reason": error_reason,
                "error_description": error_description
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        code = request.args.get("code")
        state = request.args.get("state")

        if not code or not state:
            Log.info(f"{log_tag} Missing code/state in callback")
            return jsonify({"success": False, "message": "Missing required OAuth parameters"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Validate state from Redis
        try:
            state_key = f"fb_oauth_state:{state}"
            state_exists = get_redis(state_key)  # redis client
            if not state_exists:
                Log.info(f"{log_tag} Invalid/expired state: {state}")
                return jsonify({"success": False, "message": "Invalid or expired OAuth state"}), HTTP_STATUS_CODES["BAD_REQUEST"]
            # one-time use
            remove_redis(state_key)
        except Exception as e:
            Log.info(f"{log_tag} Error validating state in Redis: {e}")
            return jsonify({"success": False, "message": "Could not validate OAuth state"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        redirect_uri = os.getenv("FACEBOOK_REDIRECT_URI")
        meta_app_id = os.getenv("META_APP_ID")
        meta_app_secret = os.getenv("META_APP_SECRET")

        if not redirect_uri:
            Log.info(f"{log_tag} FACEBOOK_REDIRECT_URI not set")
            return jsonify({"success": False, "message": "FACEBOOK_REDIRECT_URI not set"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        if not meta_app_id or not meta_app_secret:
            Log.info(f"{log_tag} META_APP_ID or META_APP_SECRET not set")
            return jsonify({"success": False, "message": "META_APP_ID or META_APP_SECRET not set"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # Exchange code for access token
        token_url = os.getenv("FACEBOOK_GRAPH_OAUTH_ACCESS_TOKEN_URL", "https://graph.facebook.com/v20.0/oauth/access_token")
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

        Log.info(f"{log_tag} OAuth successful - token exchanged")
        
        try:
            # Fetch user pages
            user_access_token = data.get("access_token")
            pages = FacebookAdapter.list_pages(user_access_token)

            # data["pages"] = pages
            
            # Create a short-lived selection key
            selection_key = secrets.token_urlsafe(24)

            # Save pages in Redis for 5 minutes
            redis_key = f"fb_pages:{selection_key}"
            set_redis_with_expiry(redis_key, 300, json.dumps(pages)) # 5 minutes expiry
            
            # Redirect to frontend (no token in URL)
            frontend_url = os.getenv("FRONT_END_BASE_URL")
            return redirect(f"{frontend_url}/connect/facebook?selection_key={selection_key}")
 
        except Exception as e:
            Log.info(f"{log_tag} Failed to fetch user pages: {e}")
            return jsonify({
                "success": False,
                "message": "Could not fetch user pages after OAuth"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
   