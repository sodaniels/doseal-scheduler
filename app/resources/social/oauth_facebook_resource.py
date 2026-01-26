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


blp_meta_oauth = Blueprint("meta_oauth", __name__)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _safe_json_load(raw, default=None):
    if default is None:
        default = {}
    try:
        if raw is None:
            return default
        if isinstance(raw, (dict, list)):
            return raw
        return json.loads(raw)
    except Exception:
        return default


def _require_env(key: str, log_tag: str):
    val = os.getenv(key)
    if not val:
        Log.info(f"{log_tag} ENV missing: {key}")
    return val


def _exchange_code_for_token(*, code: str, redirect_uri: str, log_tag: str) -> dict:
    """
    Exchange OAuth code for Meta user access token.
    """
    meta_app_id = _require_env("META_APP_ID", log_tag)
    meta_app_secret = _require_env("META_APP_SECRET", log_tag)
    if not meta_app_id or not meta_app_secret:
        raise Exception("META_APP_ID or META_APP_SECRET not set")

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

    resp = requests.get(token_url, params=payload, timeout=30)
    data = resp.json()
    if resp.status_code != HTTP_STATUS_CODES["OK"]:
        raise Exception(f"Token exchange failed: {data}")
    if not data.get("access_token"):
        raise Exception(f"Token exchange missing access_token: {data}")

    return data


def _store_state(owner: dict, state: str, provider: str, ttl_seconds: int = 600):
    """
    Store state in redis:
      key: <provider>_oauth_state:<state>
      val: {"owner": {"business_id": "...", "user__id": "..."}}
    """
    key = f"{provider}_oauth_state:{state}"
    set_redis_with_expiry(key, ttl_seconds, json.dumps({"owner": owner}))


def _consume_state(state: str, provider: str) -> dict:
    """
    Validate and one-time consume state.
    Returns: {"owner": {...}}
    """
    key = f"{provider}_oauth_state:{state}"
    raw = get_redis(key)
    if not raw:
        return {}
    remove_redis(key)
    return _safe_json_load(raw, default={})


def _store_selection(*, provider: str, selection_key: str, payload: dict, ttl_seconds: int = 300):
    """
    Stores selection payload in redis:
      key: <provider>_select:<selection_key>
      val: payload JSON
    """
    key = f"{provider}_select:{selection_key}"
    set_redis_with_expiry(key, ttl_seconds, json.dumps(payload))


def _load_selection(provider: str, selection_key: str) -> dict:
    key = f"{provider}_select:{selection_key}"
    raw = get_redis(key)
    return _safe_json_load(raw, default={}) if raw else {}


def _delete_selection(provider: str, selection_key: str):
    key = f"{provider}_select:{selection_key}"
    try:
        remove_redis(key)
    except Exception:
        pass


def _redirect_to_frontend(path: str, selection_key: str):
    """
    Redirects to your frontend page with selection_key
    Example:
      /connect/facebook?selection_key=...
      /connect/instagram?selection_key=...
    """
    frontend_url = os.getenv("FRONT_END_BASE_URL")
    if not frontend_url:
        # if no frontend configured, return JSON (useful for Postman testing)
        return jsonify({
            "success": True,
            "message": "FRONT_END_BASE_URL not set; returning selection_key for testing",
            "selection_key": selection_key,
        }), HTTP_STATUS_CODES["OK"]

    return redirect(f"{frontend_url}{path}?selection_key={selection_key}")


# -------------------------------------------------------------------
# FACEBOOK: START
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/oauth/facebook/start", methods=["GET"])
class FacebookOauthStartResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_facebook_resource.py][FacebookOauthStartResource][get][{client_ip}]"

        redirect_uri = _require_env("FACEBOOK_REDIRECT_URI", log_tag)
        meta_app_id = _require_env("META_APP_ID", log_tag)
        if not redirect_uri or not meta_app_id:
            return jsonify({"success": False, "message": "Server OAuth config missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # Bind oauth flow to logged-in user
        user = g.get("current_user", {}) or {}
        owner = {"business_id": str(user.get("business_id")), "user__id": str(user.get("_id"))}
        if not owner["business_id"] or not owner["user__id"]:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        state = secrets.token_urlsafe(24)
        _store_state(owner, state, "fb", ttl_seconds=600)

        params = {
            "client_id": meta_app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            # Page posting scopes
            "scope": "pages_show_list,pages_read_engagement,pages_manage_posts",
        }

        url = "https://www.facebook.com/v20.0/dialog/oauth?" + urlencode(params)
        Log.info(f"{log_tag} Redirecting to Meta OAuth consent screen")
        return redirect(url)


# -------------------------------------------------------------------
# FACEBOOK: CALLBACK
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/oauth/facebook/callback", methods=["GET"])
class FacebookOauthCallbackResource(MethodView):
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_facebook_resource.py][FacebookOauthCallbackResource][get][{client_ip}]"

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
            return jsonify({"success": False, "message": "Missing code/state"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        state_doc = _consume_state(state, "fb")
        owner = (state_doc or {}).get("owner") or {}
        if not owner.get("business_id") or not owner.get("user__id"):
            return jsonify({"success": False, "message": "Invalid/expired OAuth state"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        redirect_uri = _require_env("FACEBOOK_REDIRECT_URI", log_tag)
        if not redirect_uri:
            return jsonify({"success": False, "message": "FACEBOOK_REDIRECT_URI missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        try:
            token_data = _exchange_code_for_token(code=code, redirect_uri=redirect_uri, log_tag=log_tag)
            user_access_token = token_data["access_token"]

            # Fetch pages
            pages = FacebookAdapter.list_pages(user_access_token)

            selection_key = secrets.token_urlsafe(24)
            _store_selection(
                provider="fb",
                selection_key=selection_key,
                payload={"owner": owner, "pages": pages},
                ttl_seconds=300,
            )

            # redirect to frontend selection page
            return _redirect_to_frontend("/connect/facebook", selection_key)

        except Exception as e:
            Log.info(f"{log_tag} Failed: {e}")
            return jsonify({"success": False, "message": "Could not fetch facebook pages"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# FACEBOOK: CONNECT PAGE (finalize into social_accounts)
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/facebook/connect-page", methods=["POST"])
class FacebookConnectPageResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_facebook_resource.py][FacebookConnectPageResource][post][{client_ip}]"

        body = request.get_json(silent=True) or {}
        selection_key = body.get("selection_key")
        page_id = body.get("page_id")

        if not selection_key or not page_id:
            return jsonify({"success": False, "message": "selection_key and page_id are required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("fb", selection_key)
        if not sel:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        owner = sel.get("owner") or {}
        pages = sel.get("pages") or []

        # enforce ownership
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        selected = next((p for p in pages if str(p.get("id")) == str(page_id)), None)
        if not selected:
            return jsonify({"success": False, "message": "Invalid page_id for this selection_key"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        page_access_token = selected.get("access_token")
        if not page_access_token:
            return jsonify({"success": False, "message": "Page token missing. Reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            SocialAccount.upsert_destination(
                business_id=owner["business_id"],
                user__id=owner["user__id"],
                platform="facebook",
                destination_id=str(page_id),
                destination_type="page",
                destination_name=selected.get("name"),
                access_token_plain=page_access_token,
                refresh_token_plain=None,
                token_expires_at=None,
                scopes=["pages_show_list", "pages_read_engagement", "pages_manage_posts"],
                platform_user_id=str(page_id),
                platform_username=selected.get("name"),
                meta={
                    "page_id": str(page_id),
                    "category": selected.get("category"),
                    "tasks": selected.get("tasks", []),
                },
            )

            # one-time use
            _delete_selection("fb", selection_key)

            return jsonify({"success": True, "message": "Facebook Page connected successfully"}), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert: {e}")
            return jsonify({"success": False, "message": "Failed to connect page"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# INSTAGRAM: START
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/oauth/instagram/start", methods=["GET"])
class InstagramOauthStartResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_facebook_resource.py][InstagramOauthStartResource][get][{client_ip}]"

        redirect_uri = _require_env("INSTAGRAM_REDIRECT_URI", log_tag)
        meta_app_id = _require_env("META_APP_ID", log_tag)
        if not redirect_uri or not meta_app_id:
            return jsonify({"success": False, "message": "Server OAuth config missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        user = g.get("current_user", {}) or {}
        owner = {"business_id": str(user.get("business_id")), "user__id": str(user.get("_id"))}
        if not owner["business_id"] or not owner["user__id"]:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        state = secrets.token_urlsafe(24)
        _store_state(owner, state, "ig", ttl_seconds=600)

        params = {
            "client_id": meta_app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            # IG Graph publishing requires page-linked IG business/creator.
            # These scopes are typical:
            "scope": "pages_show_list,pages_read_engagement,instagram_basic,instagram_content_publish",
        }

        url = "https://www.facebook.com/v20.0/dialog/oauth?" + urlencode(params)
        Log.info(f"{log_tag} Redirecting to Meta OAuth consent screen")
        return redirect(url)


# -------------------------------------------------------------------
# INSTAGRAM: CALLBACK
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/oauth/instagram/callback", methods=["GET"])
class InstagramOauthCallbackResource(MethodView):
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_facebook_resource.py][InstagramOauthCallbackResource][get][{client_ip}]"

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
            return jsonify({"success": False, "message": "Missing code/state"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        state_doc = _consume_state(state, "ig")
        owner = (state_doc or {}).get("owner") or {}
        if not owner.get("business_id") or not owner.get("user__id"):
            return jsonify({"success": False, "message": "Invalid/expired OAuth state"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        redirect_uri = _require_env("INSTAGRAM_REDIRECT_URI", log_tag)
        if not redirect_uri:
            return jsonify({"success": False, "message": "INSTAGRAM_REDIRECT_URI missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        try:
            token_data = _exchange_code_for_token(code=code, redirect_uri=redirect_uri, log_tag=log_tag)
            user_access_token = token_data["access_token"]

            # Fetch IG accounts list (page-linked IG biz/creator), including page_access_token
            accounts = InstagramAdapter.list_connected_instagram_accounts(user_access_token)

            if not accounts:
                return jsonify({
                    "success": False,
                    "message": "No Instagram Business/Creator accounts found (must be linked to a Facebook Page)."
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            selection_key = secrets.token_urlsafe(24)
            _store_selection(
                provider="ig",
                selection_key=selection_key,
                payload={"owner": owner, "accounts": accounts},
                ttl_seconds=300,
            )

            return _redirect_to_frontend("/connect/instagram", selection_key)

        except Exception as e:
            Log.info(f"{log_tag} Failed: {e}")
            return jsonify({"success": False, "message": "Could not fetch instagram accounts"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# INSTAGRAM: CONNECT ACCOUNT (finalize into social_accounts)
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/instagram/connect-account", methods=["POST"])
class InstagramConnectAccountResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_facebook_resource.py][InstagramConnectAccountResource][post][{client_ip}]"

        body = request.get_json(silent=True) or {}
        selection_key = body.get("selection_key")
        ig_user_id = body.get("ig_user_id")  # chosen account id

        if not selection_key or not ig_user_id:
            return jsonify({"success": False, "message": "selection_key and ig_user_id are required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("ig", selection_key)
        if not sel:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        owner = sel.get("owner") or {}
        accounts = sel.get("accounts") or []

        # enforce ownership
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        selected = next((a for a in accounts if str(a.get("ig_user_id")) == str(ig_user_id)), None)
        if not selected:
            return jsonify({"success": False, "message": "Invalid ig_user_id for this selection_key"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        page_access_token = selected.get("page_access_token")
        if not page_access_token:
            return jsonify({"success": False, "message": "Missing page_access_token. Reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            SocialAccount.upsert_destination(
                business_id=owner["business_id"],
                user__id=owner["user__id"],
                platform="instagram",
                destination_id=str(selected["ig_user_id"]),
                destination_type="ig_user",
                destination_name=selected.get("ig_username") or selected.get("page_name"),
                access_token_plain=page_access_token,  # used for IG publishing
                refresh_token_plain=None,
                token_expires_at=None,
                scopes=["instagram_basic", "instagram_content_publish", "pages_show_list", "pages_read_engagement"],
                platform_user_id=str(selected["ig_user_id"]),
                platform_username=selected.get("ig_username"),
                meta={
                    "ig_user_id": str(selected["ig_user_id"]),
                    "ig_username": selected.get("ig_username"),
                    "page_id": str(selected.get("page_id")),
                    "page_name": selected.get("page_name"),
                },
            )

            _delete_selection("ig", selection_key)

            return jsonify({"success": True, "message": "Instagram account connected successfully"}), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert: {e}")
            return jsonify({"success": False, "message": "Failed to connect instagram"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


@blp_meta_oauth.route("/social/instagram/accounts", methods=["GET"])
class InstagramAccountsResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_meta.py][InstagramAccountsResource][get][{client_ip}]"

        selection_key = request.args.get("selection_key")
        if not selection_key:
            return jsonify({"success": False, "message": "selection_key is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # ✅ Match the naming used in the combined implementation:
        # key: ig_select:<selection_key>
        raw = get_redis(f"ig_select:{selection_key}")
        if not raw:
            return jsonify(
                {"success": False, "message": "Selection expired. Please reconnect."}
            ), HTTP_STATUS_CODES["NOT_FOUND"]

        doc = _safe_json_load(raw, default={}) or {}
        owner = doc.get("owner") or {}
        accounts = doc.get("accounts") or []

        # Ensure logged-in user matches selection owner
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            Log.info(f"{log_tag} Owner mismatch: current_user != selection owner")
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Return safe data only (never return tokens)
        safe_accounts = []
        for a in accounts:
            safe_accounts.append({
                "ig_user_id": a.get("ig_user_id"),
                "ig_username": a.get("ig_username"),

                # helpful context for UI
                "page_id": a.get("page_id"),
                "page_name": a.get("page_name"),
            })

        return jsonify({"success": True, "data": {"accounts": safe_accounts}}), HTTP_STATUS_CODES["OK"]



