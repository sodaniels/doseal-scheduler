# app/routes/social/oauth_pinterest_resource.py

import os
import secrets
from urllib.parse import urlencode

from flask.views import MethodView
from flask import request, jsonify, redirect, g
from flask_smorest import Blueprint

from ...utils.logger import Log
from ...utils.json_response import prepared_response
from ...constants.service_code import HTTP_STATUS_CODES, SYSTEM_USERS
from ..doseal.admin.admin_business_resource import token_required

from ...models.social.social_account import SocialAccount
from ...services.social.adapters.pinterest_adapter import PinterestAdapter

from ...utils.plan.quota_enforcer import QuotaEnforcer, PlanLimitError
from ...utils.helpers import make_log_tag

from ...utils.schedule_helper import (
    _require_env,
    _store_state, _consume_state,
    _store_selection, _load_selection, _delete_selection,
    _redirect_to_frontend,
)

blp_pinterest_oauth = Blueprint("pinterest_oauth", __name__)


def _pinterest_authorize_url(*, client_id: str, redirect_uri: str, state: str, scopes: str) -> str:
    # Pinterest authorize endpoint  [oai_citation:4‡docs.squiz.net](https://docs.squiz.net/connect/latest/components/connectors/pinterest.html?utm_source=chatgpt.com)
    base = "https://www.pinterest.com/oauth/"
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "scope": scopes,
    }
    return base + "?" + urlencode(params)


# -------------------------------------------------------------------
# PINTEREST: START
# -------------------------------------------------------------------
@blp_pinterest_oauth.route("/social/oauth/pinterest/start", methods=["GET"])
class PinterestOauthStartResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr

        body = request.get_json(silent=True) or {}
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")

        # Optional business override
        form_business_id = body.get("business_id")
        target_business_id = form_business_id if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id else auth_business_id

        log_tag = make_log_tag(
            "oauth_pinterest_resource.py",
            "PinterestOauthStartResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        redirect_uri = _require_env("PINTEREST_REDIRECT_URI", log_tag)
        client_id = _require_env("PINTEREST_CLIENT_ID", log_tag)
        if not redirect_uri or not client_id:
            return jsonify({"success": False, "message": "Server OAuth config missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        owner = {"business_id": str(user_info.get("business_id")), "user__id": str(user_info.get("_id"))}
        if not owner["business_id"] or not owner["user__id"]:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        state = secrets.token_urlsafe(24)
        _store_state(owner, state, "pi", ttl_seconds=600)

        # Scopes: adjust to your app’s access
        # Common patterns include boards:read, pins:read, pins:write, user_accounts:read
        scopes = os.getenv("PINTEREST_SCOPES", "boards:read,pins:read,pins:write,user_accounts:read")

        url = _pinterest_authorize_url(
            client_id=client_id,
            redirect_uri=redirect_uri,
            state=state,
            scopes=scopes,
        )

        Log.info(f"{log_tag} Redirecting to Pinterest OAuth consent screen")
        return redirect(url)


# -------------------------------------------------------------------
# PINTEREST: CALLBACK
# -------------------------------------------------------------------
@blp_pinterest_oauth.route("/social/oauth/pinterest/callback", methods=["GET"])
class PinterestOauthCallbackResource(MethodView):
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_pinterest_resource.py][PinterestOauthCallbackResource][get][{client_ip}]"

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

        state_doc = _consume_state(state, "pi")
        owner = (state_doc or {}).get("owner") or {}
        if not owner.get("business_id") or not owner.get("user__id"):
            return jsonify({"success": False, "message": "Invalid/expired OAuth state"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        redirect_uri = _require_env("PINTEREST_REDIRECT_URI", log_tag)
        client_id = _require_env("PINTEREST_CLIENT_ID", log_tag)
        client_secret = _require_env("PINTEREST_CLIENT_SECRET", log_tag)
        if not redirect_uri or not client_id or not client_secret:
            return jsonify({"success": False, "message": "Pinterest OAuth config missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        try:
            token_data = PinterestAdapter.exchange_code_for_token(
                client_id=client_id,
                client_secret=client_secret,
                code=code,
                redirect_uri=redirect_uri,
                log_tag=log_tag,
            )

            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")

            # Load boards for selection UI
            boards = PinterestAdapter.list_boards(access_token=access_token)

            selection_key = secrets.token_urlsafe(24)
            _store_selection(
                provider="pi",
                selection_key=selection_key,
                payload={
                    "owner": owner,
                    "boards": boards,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                },
                ttl_seconds=300,
            )

            return _redirect_to_frontend("/connect/pinterest", selection_key)

        except Exception as e:
            Log.info(f"{log_tag} Failed: {e}")
            return jsonify({"success": False, "message": "Could not fetch Pinterest boards"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# PINTEREST: LIST BOARDS (selection screen)
# -------------------------------------------------------------------
@blp_pinterest_oauth.route("/social/pinterest/boards", methods=["GET"])
class PinterestBoardsResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_pinterest_resource.py][PinterestBoardsResource][get][{client_ip}]"

        selection_key = request.args.get("selection_key")
        if not selection_key:
            return jsonify({"success": False, "message": "selection_key is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("pi", selection_key)
        if not sel:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["NOT_FOUND"]

        owner = sel.get("owner") or {}
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        boards = sel.get("boards") or []
        safe = []
        for b in boards:
            safe.append({
                "board_id": b.get("id"),
                "name": b.get("name"),
                "privacy": b.get("privacy"),
            })
        return jsonify({"success": True, "data": {"boards": safe}}), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# PINTEREST: CONNECT BOARD (finalize into social_accounts)
# -------------------------------------------------------------------
@blp_pinterest_oauth.route("/social/pinterest/connect-board", methods=["POST"])
class PinterestConnectBoardResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr
        body = request.get_json(silent=True) or {}

        selection_key = body.get("selection_key")
        board_id = body.get("board_id")

        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")

        form_business_id = body.get("business_id")
        target_business_id = form_business_id if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id else auth_business_id

        log_tag = make_log_tag(
            "oauth_pinterest_resource.py",
            "PinterestConnectBoardResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        if not selection_key or not board_id:
            return jsonify({"success": False, "message": "selection_key and board_id are required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("pi", selection_key)
        if not sel:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        owner = sel.get("owner") or {}
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        access_token = sel.get("access_token")
        refresh_token = sel.get("refresh_token")
        boards = sel.get("boards") or []
        selected = next((b for b in boards if str(b.get("id")) == str(board_id)), None)
        if not selected:
            return jsonify({"success": False, "message": "Invalid board_id for this selection_key"}), HTTP_STATUS_CODES["BAD_REQUEST"]

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
                platform="pinterest",
                destination_id=str(board_id),
                destination_type="board",
                destination_name=selected.get("name"),

                access_token_plain=access_token,
                refresh_token_plain=refresh_token,
                token_expires_at=None,
                scopes=(os.getenv("PINTEREST_SCOPES", "").split(",") if os.getenv("PINTEREST_SCOPES") else []),

                platform_user_id=str(board_id),
                platform_username=selected.get("name"),

                meta={
                    "board_id": str(board_id),
                    "privacy": selected.get("privacy"),
                },
            )

            _delete_selection("pi", selection_key)
            return jsonify({"success": True, "message": "Pinterest board connected successfully"}), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert: {e}")
            enforcer.release(counter_name="social_accounts", qty=1, period="billing")
            return jsonify({"success": False, "message": "Failed to connect Pinterest board"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]