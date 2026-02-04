# app/routes/social/oauth_facebook_resource.py

import os
import json
import secrets
from urllib.parse import urlencode
from ...utils.json_response import prepared_response
import requests
from flask.views import MethodView
from flask import request, jsonify, redirect, g
from flask_smorest import Blueprint

from ...utils.logger import Log
from ...utils.redis import get_redis, set_redis_with_expiry, remove_redis
from ...constants.service_code import (
    HTTP_STATUS_CODES,
    SYSTEM_USERS
)
from ..doseal.admin.admin_business_resource import token_required

from ...models.social.social_account import SocialAccount
from ...services.social.adapters.facebook_adapter import FacebookAdapter
from ...services.social.adapters.instagram_adapter import InstagramAdapter
from ...services.social.adapters.threads_adapter import ThreadsAdapter
from ...utils.plan.quota_enforcer import QuotaEnforcer, PlanLimitError
from ...utils.helpers import make_log_tag

from ...utils.social.pre_process_checks import PreProcessCheck

from ...utils.schedule_helper import (
    _safe_json_load, _require_env, _exchange_code_for_token, _store_state, _consume_state,
    _store_selection, _load_selection, _delete_selection, _redirect_to_frontend,
    _exchange_code_for_token_threads
)
from ...utils.social.token_utils import (
    is_token_expired,
    is_token_expiring_soon,
)


blp_meta_oauth = Blueprint("meta_oauth", __name__)


# -------------------------------------------------------------------
# FACEBOOK: START
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/oauth/facebook/start", methods=["GET"])
class FacebookOauthStartResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_meta.py][FacebookOauthStartResource][get][{client_ip}]"
        user_info = g.get("current_user", {}) or {}
        admin_id = str(user_info.get("admin_id"))
        business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")
        
        #####################PRE TRANSACTION CHECKS#########################
        
        # 1. check pre transaction requirements for agents
        pre_check = PreProcessCheck(business_id=business_id, account_type=account_type, admin_id=admin_id, )
        initial_check_result = pre_check.initial_processs_checks()
        
        if initial_check_result is not None:
            return initial_check_result
        #####################PRE TRANSACTION CHECKS#########################

        redirect_uri = _require_env("FACEBOOK_REDIRECT_URI", log_tag)
        meta_app_id = _require_env("META_APP_ID", log_tag)
        if not redirect_uri or not meta_app_id:
            return jsonify({"success": False, "message": "Server OAuth config missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

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
        log_tag = f"[oauth_meta.py][FacebookOauthCallbackResource][get][{client_ip}]"

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

            pages = FacebookAdapter.list_pages(user_access_token)

            selection_key = secrets.token_urlsafe(24)
            _store_selection(
                provider="fb",
                selection_key=selection_key,
                payload={"owner": owner, "pages": pages},
                ttl_seconds=300,
            )

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

        body = request.get_json(silent=True) or {}
        selection_key = body.get("selection_key")
        page_id = body.get("page_id")

        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "oauth_facebook_resource.py",
            "FacebookConnectPageResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        if not selection_key or not page_id:
            return jsonify({"success": False, "message": "selection_key and page_id are required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("fb", selection_key)
        if not sel:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        owner = sel.get("owner") or {}
        pages = sel.get("pages") or []

        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        selected = next((p for p in pages if str(p.get("id")) == str(page_id)), None)
        if not selected:
            return jsonify({"success": False, "message": "Invalid page_id for this selection_key"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        page_access_token = selected.get("access_token")
        if not page_access_token:
            return jsonify({"success": False, "message": "Page token missing. Reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # ---------------------------------------------------------
        # ✅ NEW: Prevent double-counting quota on reconnect
        #   - if already connected and token is still valid => 409
        #   - if already connected but token expired => allow refresh WITHOUT reserve
        #   - if not connected => reserve quota then create
        # ---------------------------------------------------------
        from pymongo.errors import DuplicateKeyError
        from ...utils.social.token_utils import is_token_expired, is_token_expiring_soon

        try:
            existing = SocialAccount.get_destination(
                owner["business_id"],
                owner["user__id"],
                "facebook",
                str(page_id),
            )
        except Exception:
            Log.info(f"{log_tag} Error retrieving social destination: {str(e)}")

        should_reserve_quota = False

        if existing:
            # If you have token_expires_at tracking, use it.
            # If you don't (token_expires_at is None always), then treat as "still valid"
            # and block reconnect unless frontend explicitly calls a "force_refresh" flow.
            if not is_token_expired(existing):
                # Optional: if expiring soon, you can allow refresh (no quota) instead of blocking
                if is_token_expiring_soon(existing, minutes=10):
                    Log.info(f"{log_tag} token expiring soon; refreshing token without consuming quota")
                else:
                    return jsonify({
                        "success": False,
                        "message": "This Facebook Page is already connected.",
                        "code": "ALREADY_CONNECTED",
                    }), HTTP_STATUS_CODES["CONFLICT"]
            else:
                Log.info(f"{log_tag} token expired; refreshing token without consuming quota")
        else:
            should_reserve_quota = True

        # ---- PLAN ENFORCER ----
        enforcer = QuotaEnforcer(target_business_id)

        # ✅ Reserve quota ONLY if this is a brand new connection
        if should_reserve_quota:
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
            # Upsert is fine:
            # - if existing: this updates access_token_plain and meta (refresh)
            # - if new: creates destination
            SocialAccount.upsert_destination(
                business_id=owner["business_id"],
                user__id=owner["user__id"],
                platform="facebook",
                destination_id=str(page_id),
                destination_type="page",
                destination_name=selected.get("name"),
                access_token_plain=page_access_token,
                refresh_token_plain=None,
                token_expires_at=None,  # ideally store expires_at if you can obtain it
                scopes=["pages_show_list", "pages_read_engagement", "pages_manage_posts"],
                platform_user_id=str(page_id),
                platform_username=selected.get("name"),
                meta={
                    "page_id": str(page_id),
                    "category": selected.get("category"),
                    "tasks": selected.get("tasks", []),
                },
            )

            _delete_selection("fb", selection_key)

            return jsonify({
                "success": True,
                "message": "Facebook Page connected successfully" if should_reserve_quota else "Facebook Page refreshed successfully",
            }), HTTP_STATUS_CODES["OK"]

        except DuplicateKeyError as e:
            # If it was a race and doc already exists, don't punish user
            Log.info(f"{log_tag} DuplicateKeyError (already exists): {e}")
            if should_reserve_quota:
                enforcer.release(counter_name="social_accounts", qty=1, period="billing")
            return jsonify({
                "success": True,
                "message": "Facebook Page already connected (no changes required).",
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert: {e}")
            if should_reserve_quota:
                enforcer.release(counter_name="social_accounts", qty=1, period="billing")
            return jsonify({"success": False, "message": "Failed to connect page"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# -------------------------------------------------------------------
# FACEBOOK: PAGES
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/facebook/pages", methods=["GET"])
class FacebookPagesResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        
        body = request.get_json(silent=True) or {}
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")
        
        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id
            
        log_tag = make_log_tag(
            "oauth_facebook_resource.py",
            "FacebookConnectPageResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        selection_key = request.args.get("selection_key")
        if not selection_key:
            return jsonify({"success": False, "message": "selection_key is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        raw = get_redis(f"fb_select:{selection_key}")
        
    
        if not raw:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["NOT_FOUND"]

        doc = _safe_json_load(raw, default={}) or {}
        owner = doc.get("owner") or {}
        pages = doc.get("pages") or []

        # Ensure the logged-in user matches the owner stored in Redis
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            Log.info(f"{log_tag} Owner mismatch: current_user != selection owner")
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        safe_pages = []
        for p in pages:
            safe_pages.append({
                "page_id": p.get("id"),
                "name": p.get("name"),
                "category": p.get("category"),
                "tasks": p.get("tasks", []),
            })

        return jsonify({"success": True, "data": {"pages": safe_pages}}), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# INSTAGRAM: START
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/oauth/instagram/start", methods=["GET"])
class InstagramOauthStartResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        
        body = request.get_json(silent=True) or {}
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")
        
        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id
            
        log_tag = make_log_tag(
            "oauth_facebook_resource.py",
            "FacebookConnectPageResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

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
        log_tag = f"[oauth_meta.py][InstagramOauthCallbackResource][get][{client_ip}]"

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

            accounts = InstagramAdapter.get_connected_instagram_accounts(user_access_token)

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
        log_tag = f"[oauth_meta.py][InstagramConnectAccountResource][post][{client_ip}]"

        body = request.get_json(silent=True) or {}
        selection_key = body.get("selection_key")
        ig_user_id = body.get("ig_user_id")  # chosen IG user id
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")

        if not selection_key or not ig_user_id:
            return jsonify({"success": False, "message": "selection_key and ig_user_id are required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("ig", selection_key)
        if not sel:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        owner = sel.get("owner") or {}
        accounts = sel.get("accounts") or []

        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # ✅ NEW: match adapter output (destination_id)
        selected = next((a for a in accounts if str(a.get("destination_id")) == str(ig_user_id)), None)
        if not selected:
            return jsonify({"success": False, "message": "Invalid ig_user_id for this selection_key"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        page_access_token = selected.get("page_access_token")
        if not page_access_token:
            return jsonify({"success": False, "message": "Missing page_access_token. Reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        
        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id
        
        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id
            
        log_tag = make_log_tag(
            "oauth_facebook_resource.py",
            "FacebookConnectPageResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )
        
         # ---- PLAN ENFORCER (scoped to target business) ----
        enforcer = QuotaEnforcer(target_business_id)
        
        # ✅ 2) RESERVE QUOTA ONLY WHEN WE ARE ABOUT TO CREATE
        try:
            enforcer.reserve(
                counter_name="social_accounts",
                limit_key="max_social_accounts",
                qty=1,
                period="billing",   # monthly plans => month bucket, yearly => year bucket
                reason="social_accounts:create",
            )
        except PlanLimitError as e:
            Log.info(f"{log_tag} plan limit reached: {e.meta}")
            return prepared_response(False, "FORBIDDEN", e.message, errors=e.meta)

        try:
            SocialAccount.upsert_destination(
                business_id=owner["business_id"],
                user__id=owner["user__id"],
                platform="instagram",

                # ✅ destination_id IS the IG user id
                destination_id=str(selected.get("destination_id")),
                destination_type="ig_user",
                destination_name=selected.get("username") or selected.get("page_name"),

                # ✅ page token is used to publish to IG Graph
                access_token_plain=page_access_token,

                refresh_token_plain=None,
                token_expires_at=None,

                scopes=["instagram_basic", "instagram_content_publish", "pages_show_list", "pages_read_engagement"],

                platform_user_id=str(selected.get("destination_id")),
                platform_username=selected.get("username"),

                meta={
                    "ig_user_id": str(selected.get("destination_id")),
                    "ig_username": selected.get("username"),
                    "page_id": str(selected.get("page_id")),
                    "page_name": selected.get("page_name"),
                },
            )

            _delete_selection("ig", selection_key)

            return jsonify({"success": True, "message": "Instagram account connected successfully"}), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert: {e}")
            enforcer.release(counter_name="social_accounts", qty=1, period="billing")
            Log.info(f"{log_tag} DuplicateKeyError on social_accounts insert: {e}")
            return jsonify({"success": False, "message": "Failed to connect instagram"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# INSTAGRAM: LIST ACCOUNTS (selection screen)
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/instagram/accounts", methods=["GET"])
class InstagramAccountsResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_meta.py][InstagramAccountsResource][get][{client_ip}]"

        selection_key = request.args.get("selection_key")
        if not selection_key:
            return jsonify({"success": False, "message": "selection_key is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        raw = get_redis(f"ig_select:{selection_key}")
        if not raw:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["NOT_FOUND"]

        doc = _safe_json_load(raw, default={}) or {}
        owner = doc.get("owner") or {}
        accounts = doc.get("accounts") or []

        user = g.get("current_user", {}) or {}
        if (
            str(user.get("business_id")) != str(owner.get("business_id"))
            or str(user.get("_id")) != str(owner.get("user__id"))
        ):
            Log.info(f"{log_tag} Owner mismatch: current_user != selection owner")
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        safe_accounts = []
        for a in accounts:
            safe_accounts.append({
                # ✅ map new fields to UI-friendly keys
                "ig_user_id": a.get("destination_id"),
                "ig_username": a.get("username"),
                "page_id": a.get("page_id"),
                "page_name": a.get("page_name"),
            })

        return jsonify({"success": True, "data": {"accounts": safe_accounts}}), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# THREADS: START
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/oauth/threads/start", methods=["GET"])
class ThreadsOauthStartResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_meta.py][ThreadsOauthStartResource][get][{client_ip}]"

        redirect_uri = _require_env("THREADS_REDIRECT_URI", log_tag)
        meta_app_id = _require_env("THREADS_APP_ID", log_tag)
        if not redirect_uri or not meta_app_id:
            return jsonify({"success": False, "message": "Server OAuth config missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        user = g.get("current_user", {}) or {}
        owner = {"business_id": str(user.get("business_id")), "user__id": str(user.get("_id"))}
        if not owner["business_id"] or not owner["user__id"]:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        state = secrets.token_urlsafe(24)
        _store_state(owner, state, "threads", ttl_seconds=600)

        # Threads uses Meta login. Scopes can vary based on your app approval.
        # Start with "threads_basic" and "threads_content_publish" style scopes if available.
        # If your Meta app uses different scope names, update here.
        params = {
            "client_id": meta_app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",
            "scope": "threads_basic,threads_content_publish",
        }
        
        Log.info(f"{log_tag} THREADS_APP_ID={os.getenv('THREADS_APP_ID')}")

        url = "https://www.facebook.com/v20.0/dialog/oauth?" + urlencode(params)
        Log.info(f"{log_tag} Redirecting to Threads OAuth consent screen")
        return redirect(url)


# -------------------------------------------------------------------
# THREADS: CALLBACK
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/oauth/threads/callback", methods=["GET"])
class ThreadsOauthCallbackResource(MethodView):
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_meta.py][ThreadsOauthCallbackResource][get][{client_ip}]"

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

        state_doc = _consume_state(state, "threads")
        owner = (state_doc or {}).get("owner") or {}
        if not owner.get("business_id") or not owner.get("user__id"):
            return jsonify({"success": False, "message": "Invalid/expired OAuth state"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        redirect_uri = _require_env("THREADS_REDIRECT_URI", log_tag)
        if not redirect_uri:
            return jsonify({"success": False, "message": "THREADS_REDIRECT_URI missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        try:
            # Reuse your helper to exchange code => token
            token_data = _exchange_code_for_token_threads(code=code, redirect_uri=redirect_uri, log_tag=log_tag)
            access_token = token_data.get("access_token")
            if not access_token:
                return jsonify({"success": False, "message": "Missing access_token from Threads OAuth"}), HTTP_STATUS_CODES["BAD_REQUEST"]

            # Fetch Threads user id. Graph field names can vary; safest is /me?fields=id
            me = requests.get(
                f"https://graph.facebook.com/v19.0/me",
                params={"fields": "id,name", "access_token": access_token},
                timeout=30,
            )
            me_payload = _safe_json_load(me.text, default={}) if me.text else {}
            try:
                me_payload = me.json()
            except Exception:
                pass

            threads_user_id = str(me_payload.get("id") or "")
            name = me_payload.get("name") or "Threads Account"

            if not threads_user_id:
                Log.info(f"{log_tag} Could not determine threads user id: {me_payload}")
                return jsonify({"success": False, "message": "Could not fetch Threads user id"}), HTTP_STATUS_CODES["BAD_REQUEST"]

            # Store selection (like the others)
            selection_key = secrets.token_urlsafe(24)
            _store_selection(
                provider="threads",
                selection_key=selection_key,
                payload={
                    "owner": owner,
                    "account": {
                        "platform": "threads",
                        "destination_type": "user",
                        "destination_id": threads_user_id,
                        "name": name,
                        "access_token": access_token,
                        "scopes": (token_data.get("scope") or ""),
                    },
                },
                ttl_seconds=300,
            )

            return _redirect_to_frontend("/connect/threads", selection_key)

        except Exception as e:
            Log.info(f"{log_tag} Failed: {e}")
            return jsonify({"success": False, "message": "Could not fetch Threads account"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# THREADS: ACCOUNT (selection screen)
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/threads/accounts", methods=["GET"])
class ThreadsAccountsResource(MethodView):
    @token_required
    def get(self):
        selection_key = request.args.get("selection_key")
        if not selection_key:
            return jsonify({"success": False, "message": "selection_key is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        raw = get_redis(f"threads_select:{selection_key}")
        if not raw:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["NOT_FOUND"]

        doc = _safe_json_load(raw, default={}) or {}
        owner = doc.get("owner") or {}
        account = doc.get("account") or {}

        # Ensure the logged-in user matches owner stored
        user = g.get("current_user", {}) or {}
        if (
            str(user.get("business_id")) != str(owner.get("business_id"))
            or str(user.get("_id")) != str(owner.get("user__id"))
        ):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        safe_accounts = [{
            "threads_user_id": account.get("destination_id"),
            "name": account.get("name"),
        }]

        return jsonify({"success": True, "data": {"accounts": safe_accounts}}), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# THREADS: CONNECT ACCOUNT
# -------------------------------------------------------------------
@blp_meta_oauth.route("/social/threads/connect-account", methods=["POST"])
class ThreadsConnectAccountResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr

        body = request.get_json(silent=True) or {}
        selection_key = body.get("selection_key")
        threads_user_id = body.get("threads_user_id")

        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")

        if not selection_key or not threads_user_id:
            return jsonify({"success": False, "message": "selection_key and threads_user_id are required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("threads", selection_key)
        if not sel:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        owner = sel.get("owner") or {}
        account = sel.get("account") or {}

        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        if str(account.get("destination_id")) != str(threads_user_id):
            return jsonify({"success": False, "message": "Invalid threads_user_id for this selection_key"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Optional business override for system roles
        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "oauth_facebook_resource.py",
            "ThreadsConnectAccountResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        # Plan enforcement
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
                platform="threads",
                destination_id=str(account.get("destination_id")),
                destination_type="user",
                destination_name=account.get("name") or "Threads Account",
                access_token_plain=account.get("access_token"),
                refresh_token_plain=None,
                token_expires_at=None,
                scopes=["threads_basic", "threads_content_publish"],
                platform_user_id=str(account.get("destination_id")),
                platform_username=account.get("name"),
                meta={
                    "threads_user_id": str(account.get("destination_id")),
                    "name": account.get("name"),
                },
            )

            _delete_selection("threads", selection_key)
            return jsonify({"success": True, "message": "Threads account connected successfully"}), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert: {e}")
            enforcer.release(counter_name="social_accounts", qty=1, period="billing")
            return jsonify({"success": False, "message": "Failed to connect Threads"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

























