# app/routes/social/oauth_whatsapp_resource.py

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
from ...services.social.adapters.whatsapp_adapter import WhatsAppAdapter

from ...utils.plan.quota_enforcer import QuotaEnforcer, PlanLimitError
from ...utils.helpers import make_log_tag

from ...utils.schedule_helper import (
    _safe_json_load, _require_env, _exchange_code_for_token,
    _store_state, _consume_state,
    _store_selection, _load_selection, _delete_selection,
    _redirect_to_frontend,
)

blp_whatsapp_oauth = Blueprint("whatsapp_oauth", __name__)


# -------------------------------------------------------------------
# WHATSAPP: START
# -------------------------------------------------------------------
@blp_whatsapp_oauth.route("/social/oauth/whatsapp/start", methods=["GET"])
class WhatsAppOauthStartResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr

        body = request.get_json(silent=True) or {}
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")

        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "oauth_whatsapp_resource.py",
            "WhatsAppOauthStartResource",
            "get",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        redirect_uri = _require_env("WHATSAPP_REDIRECT_URI", log_tag)
        meta_app_id = _require_env("META_APP_ID", log_tag)
        if not redirect_uri or not meta_app_id:
            return jsonify({"success": False, "message": "Server OAuth config missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        owner = {"business_id": str(user_info.get("business_id")), "user__id": str(user_info.get("_id"))}
        if not owner["business_id"] or not owner["user__id"]:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        state = secrets.token_urlsafe(24)
        _store_state(owner, state, "wa", ttl_seconds=600)

        params = {
            "client_id": meta_app_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "response_type": "code",

            # ✅ IMPORTANT:
            # /me/businesses usually needs business_management
            # WABA/phone usage needs whatsapp_business_management + whatsapp_business_messaging
            "scope": "business_management,whatsapp_business_management,whatsapp_business_messaging",
        }

        url = "https://www.facebook.com/v20.0/dialog/oauth?" + urlencode(params)
        Log.info(f"{log_tag} Redirecting to WhatsApp OAuth consent screen")
        return redirect(url)


# -------------------------------------------------------------------
# WHATSAPP: CALLBACK
# -------------------------------------------------------------------
@blp_whatsapp_oauth.route("/social/oauth/whatsapp/callback", methods=["GET"])
class WhatsAppOauthCallbackResource(MethodView):
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_whatsapp_resource.py][WhatsAppOauthCallbackResource][get][{client_ip}]"

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

        state_doc = _consume_state(state, "wa")
        owner = (state_doc or {}).get("owner") or {}
        if not owner.get("business_id") or not owner.get("user__id"):
            return jsonify({"success": False, "message": "Invalid/expired OAuth state"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        redirect_uri = _require_env("WHATSAPP_REDIRECT_URI", log_tag)
        if not redirect_uri:
            return jsonify({"success": False, "message": "WHATSAPP_REDIRECT_URI missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        try:
            token_data = _exchange_code_for_token(code=code, redirect_uri=redirect_uri, log_tag=log_tag)
            user_access_token = token_data["access_token"]

            # ✅ FIXED: discover via /me/businesses -> /{business_id}/owned_whatsapp_business_accounts
            wabas = WhatsAppAdapter.list_whatsapp_business_accounts(access_token=user_access_token)

            selection_key = secrets.token_urlsafe(24)
            _store_selection(
                provider="wa",
                selection_key=selection_key,
                payload={"owner": owner, "wabas": wabas, "access_token": user_access_token},
                ttl_seconds=300,
            )

            return _redirect_to_frontend("/connect/whatsapp", selection_key)

        except Exception as e:
            Log.info(f"{log_tag} Failed: {e}")
            return jsonify({"success": False, "message": "Could not fetch WhatsApp Business Accounts"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# WHATSAPP: LIST WABAs (selection screen)
# -------------------------------------------------------------------
@blp_whatsapp_oauth.route("/social/whatsapp/wabas", methods=["GET"])
class WhatsAppWabasResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_whatsapp_resource.py][WhatsAppWabasResource][get][{client_ip}]"

        selection_key = request.args.get("selection_key")
        if not selection_key:
            return jsonify({"success": False, "message": "selection_key is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("wa", selection_key)
        if not sel:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["NOT_FOUND"]

        owner = sel.get("owner") or {}
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        wabas = sel.get("wabas") or []
        safe = []
        for w in wabas:
            safe.append({
                "waba_id": w.get("id"),
                "name": w.get("name"),
                "business_id": w.get("business_id"),
                "business_name": w.get("business_name"),
            })

        return jsonify({"success": True, "data": {"wabas": safe}}), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# WHATSAPP: LIST PHONE NUMBERS UNDER A WABA
# -------------------------------------------------------------------
@blp_whatsapp_oauth.route("/social/whatsapp/phone-numbers", methods=["GET"])
class WhatsAppPhoneNumbersResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_whatsapp_resource.py][WhatsAppPhoneNumbersResource][get][{client_ip}]"

        selection_key = request.args.get("selection_key")
        waba_id = request.args.get("waba_id")
        if not selection_key or not waba_id:
            return jsonify({"success": False, "message": "selection_key and waba_id are required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("wa", selection_key)
        if not sel:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["NOT_FOUND"]

        owner = sel.get("owner") or {}
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        access_token = sel.get("access_token")
        if not access_token:
            return jsonify({"success": False, "message": "Missing access token in selection (reconnect)"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            nums = WhatsAppAdapter.list_phone_numbers(access_token=access_token, waba_id=str(waba_id))
            safe = []
            for n in nums:
                safe.append({
                    "phone_number_id": n.get("id"),
                    "display_phone_number": n.get("display_phone_number"),
                    "verified_name": n.get("verified_name"),
                    "quality_rating": n.get("quality_rating"),
                    "code_verification_status": n.get("code_verification_status"),
                    "waba_id": str(waba_id),
                })
            return jsonify({"success": True, "data": {"phone_numbers": safe}}), HTTP_STATUS_CODES["OK"]
        except Exception as e:
            Log.info(f"{log_tag} Failed: {e}")
            return jsonify({"success": False, "message": "Could not fetch phone numbers"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# WHATSAPP: CONNECT NUMBER (finalize into social_accounts)
# -------------------------------------------------------------------
@blp_whatsapp_oauth.route("/social/whatsapp/connect-number", methods=["POST"])
class WhatsAppConnectNumberResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr

        body = request.get_json(silent=True) or {}
        selection_key = body.get("selection_key")
        phone_number_id = body.get("phone_number_id")
        waba_id = body.get("waba_id")

        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        auth_business_id = str(user_info.get("business_id"))
        account_type = user_info.get("account_type")

        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = form_business_id
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "oauth_whatsapp_resource.py",
            "WhatsAppConnectNumberResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        if not selection_key or not phone_number_id:
            return jsonify({"success": False, "message": "selection_key and phone_number_id are required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        sel = _load_selection("wa", selection_key)
        if not sel:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        owner = sel.get("owner") or {}
        user = g.get("current_user", {}) or {}
        if str(user.get("business_id")) != str(owner.get("business_id")) or str(user.get("_id")) != str(owner.get("user__id")):
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        access_token = sel.get("access_token")
        if not access_token:
            return jsonify({"success": False, "message": "Missing token in selection (reconnect)"}), HTTP_STATUS_CODES["BAD_REQUEST"]

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
                platform="whatsapp",
                destination_id=str(phone_number_id),
                destination_type="phone_number",
                destination_name=str(body.get("display_phone_number") or phone_number_id),

                access_token_plain=access_token,
                refresh_token_plain=None,
                token_expires_at=None,
                scopes=["business_management", "whatsapp_business_management", "whatsapp_business_messaging"],

                platform_user_id=str(phone_number_id),
                platform_username=str(body.get("display_phone_number") or ""),

                meta={
                    "waba_id": str(waba_id or ""),
                    "display_phone_number": body.get("display_phone_number"),
                    "verified_name": body.get("verified_name"),
                    "quality_rating": body.get("quality_rating"),
                    "code_verification_status": body.get("code_verification_status"),
                },
            )

            _delete_selection("wa", selection_key)
            return jsonify({"success": True, "message": "WhatsApp number connected successfully"}), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert: {e}")
            enforcer.release(counter_name="social_accounts", qty=1, period="billing")
            return jsonify({"success": False, "message": "Failed to connect WhatsApp number"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]