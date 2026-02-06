# app/resources/social/oauth_linkedin_resource.py

import os
import json
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

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
from ...utils.json_response import prepared_response
from ...utils.plan.quota_enforcer import QuotaEnforcer, PlanLimitError
from ...utils.social.pre_process_checks import PreProcessCheck
from ...models.social.social_account import SocialAccount
from ...utils.schedule_helper import (
    _safe_json_load,
    _store_selection,
    _redirect_to_frontend,
)
from ...utils.helpers import make_log_tag
from ...utils.social.token_utils import (
    is_token_expired,
    is_token_expiring_soon,
)


blp_linkedin_oauth = Blueprint("linkedin_oauth", __name__)


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def _require_linkedin_env(log_tag: str):
    """
    Required env vars:
      LINKEDIN_CLIENT_ID
      LINKEDIN_CLIENT_SECRET
      LINKEDIN_CALLBACK_URL  (must match exactly in LinkedIn app)
      FRONTEND_URL           (optional, only used by _redirect_to_frontend in your helper)
    Optional:
      LINKEDIN_SCOPES        (default below)
    """
    client_id = os.getenv("LINKEDIN_CLIENT_ID")
    client_secret = os.getenv("LINKEDIN_CLIENT_SECRET")
    callback_url = os.getenv("LINKEDIN_CALLBACK_URL")

    if not client_id or not client_secret or not callback_url:
        Log.info(f"{log_tag} Missing LinkedIn env vars")
        return None, None, None

    return client_id, client_secret, callback_url


def _linkedin_headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _linkedin_scopes() -> str:
    """
    Default scopes (safe baseline):
      - openid profile email  -> userinfo endpoint
    For posting as member:
      - w_member_social
    For pages/orgs:
      - depends on your LinkedIn product access. Often requires additional approval.
    """
    return os.getenv("LINKEDIN_SCOPES", "openid profile email") #w_member_social r_liteprofile r_emailaddress w_member_social r_organization_social rw_organization_admin w_organization_social


def _linkedin_auth_url() -> str:
    return "https://www.linkedin.com/oauth/v2/authorization"


def _linkedin_token_url() -> str:
    return "https://www.linkedin.com/oauth/v2/accessToken"


def _fetch_linkedin_userinfo(access_token: str, log_tag: str) -> dict:
    """
    Uses the OIDC userinfo endpoint.
    Returns something like:
      { "sub": "...", "name": "...", "given_name": "...", "family_name": "...", "email": "...", ... }
    """
    url = "https://api.linkedin.com/v2/userinfo"
    resp = requests.get(url, headers=_linkedin_headers(access_token), timeout=30)
    if resp.status_code >= 400:
        Log.info(f"{log_tag} userinfo failed: {resp.status_code} {resp.text}")
        return {}
    try:
        return resp.json()
    except Exception:
        return {}


def _fetch_linkedin_admin_organizations(
    access_token: str,
    log_tag: str,
    limit: int = 50
) -> list:
    """
    List LinkedIn organizations/pages where the user has an admin role.

    IMPORTANT:
    - Many LinkedIn apps are NOT approved for org APIs. In that case LinkedIn returns 403:
      {"code":"ACCESS_DENIED","message":"Not enough permissions ... organizationAcls ..."}
      We treat that as a normal situation and return [].

    Steps:
      1) GET /v2/organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED&count=...
      2) Parse organization URNs -> extract org IDs
      3) For each org ID, GET /v2/organizations/{id} to retrieve the name

    Returns:
      [
        {"id": "12345", "name": "My Company"},
        ...
      ]
    """

    def _safe_json(resp: requests.Response) -> dict:
        try:
            return resp.json() or {}
        except Exception:
            return {}

    def _extract_org_id(org_value) -> str | None:
        """
        org can be:
          - "urn:li:organization:12345"
          - {"urn": "urn:li:organization:12345"}  (rare)
          - {"id": "12345"} (rare)
        """
        if not org_value:
            return None

        if isinstance(org_value, str):
            if "urn:li:organization:" in org_value:
                return org_value.split(":")[-1].strip() or None
            # sometimes already an ID
            if org_value.strip().isdigit():
                return org_value.strip()
            return None

        if isinstance(org_value, dict):
            urn = org_value.get("urn") or org_value.get("organization") or org_value.get("value")
            if isinstance(urn, str) and "urn:li:organization:" in urn:
                return urn.split(":")[-1].strip() or None
            _id = org_value.get("id")
            if _id is not None:
                return str(_id).strip() or None

        return None

    if not access_token:
        Log.info(f"{log_tag} missing access_token; cannot fetch organizations")
        return []

    # safety bounds
    try:
        limit = int(limit)
    except Exception:
        limit = 50
    limit = max(1, min(limit, 100))

    acls_url = (
        "https://api.linkedin.com/v2/organizationAcls?"
        + urlencode(
            {
                "q": "roleAssignee",
                "role": "ADMINISTRATOR",
                "state": "APPROVED",
                "count": str(limit),
            }
        )
    )

    try:
        resp = requests.get(acls_url, headers=_linkedin_headers(access_token), timeout=30)
    except Exception as e:
        Log.info(f"{log_tag} organizationAcls request error: {e}")
        return []

    # ✅ Most common "not approved" case
    if resp.status_code == 403:
        Log.info(f"{log_tag} organizationAcls not permitted (403). Returning empty organizations list.")
        return []

    # Token invalid/expired etc.
    if resp.status_code in (401,):
        Log.info(f"{log_tag} organizationAcls unauthorized (401). Token may be invalid/expired.")
        return []

    # Other errors
    if resp.status_code >= 400:
        Log.info(f"{log_tag} organizationAcls failed: {resp.status_code} {resp.text}")
        return []

    payload = _safe_json(resp)
    elements = payload.get("elements") or []

    # Collect unique org IDs
    org_ids: list[str] = []
    seen = set()

    for el in elements:
        if not isinstance(el, dict):
            continue

        org_value = el.get("organization")
        org_id = _extract_org_id(org_value)
        if not org_id:
            continue

        if org_id not in seen:
            seen.add(org_id)
            org_ids.append(org_id)

        if len(org_ids) >= limit:
            break

    if not org_ids:
        return []

    orgs: list[dict] = []

    for org_id in org_ids[:limit]:
        org_url = f"https://api.linkedin.com/v2/organizations/{org_id}"

        try:
            org_resp = requests.get(org_url, headers=_linkedin_headers(access_token), timeout=30)
        except Exception as e:
            Log.info(f"{log_tag} organizations/{org_id} request error: {e}")
            continue

        if org_resp.status_code == 403:
            # Not permitted to fetch org details (still treat as normal)
            Log.info(f"{log_tag} organizations/{org_id} not permitted (403). Skipping.")
            continue

        if org_resp.status_code >= 400:
            continue

        org_doc = _safe_json(org_resp)

        name = (
            org_doc.get("localizedName")
            or (org_doc.get("name") if isinstance(org_doc.get("name"), str) else None)
            or org_id
        )

        orgs.append({"id": str(org_id), "name": name})

    return orgs

# -------------------------------------------------------------------
# LinkedIn: START (OAuth2 Authorization Code)
# -------------------------------------------------------------------
@blp_linkedin_oauth.route("/social/oauth/linkedin/start", methods=["GET"])
class LinkedInOauthStartResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        account_type = user_info.get("account_type")
        auth_business_id = str(user_info.get("business_id"))
        target_business_id = str(user_info.get("business_id"))
        admin_id = str(user_info.get("admin_id"))
        
        log_tag = make_log_tag(
            "oauth_linkedin_resource.py",
            "LinkedInOauthStartResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )

        client_id, client_secret, callback_url = _require_linkedin_env(log_tag)
        if not client_id or not client_secret or not callback_url:
            return jsonify({"success": False, "message": "LinkedIn OAuth env missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        owner = {"business_id": str(user_info.get("business_id")), "user__id": str(user_info.get("_id"))}
        if not owner["business_id"] or not owner["user__id"]:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]
        
        #####################PRE TRANSACTION CHECKS#########################
        
        # 1. check pre transaction requirements for agents
        pre_check = PreProcessCheck(business_id=target_business_id, account_type=account_type, admin_id=admin_id)
        initial_check_result = pre_check.initial_processs_checks()
        
        if initial_check_result is not None:
            return initial_check_result
        #####################PRE TRANSACTION CHECKS#########################

        # state stored in Redis
        state = secrets.token_urlsafe(24)

        # Cache owner against state (10 mins)
        set_redis_with_expiry(
            f"linkedin_oauth_state:{state}",
            600,
            json.dumps({"owner": owner}),
        )

        scopes = _linkedin_scopes()

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": callback_url,
            "state": state,
            "scope": scopes,
        }

        auth_url = f"{_linkedin_auth_url()}?{urlencode(params)}"
        Log.info(f"{log_tag} redirecting to LinkedIn auth, state_key=linkedin_oauth_state:{state}")

        return redirect(auth_url)


# -------------------------------------------------------------------
# LinkedIn: CALLBACK (OAuth2 Authorization Code)
# -------------------------------------------------------------------
@blp_linkedin_oauth.route("/social/oauth/linkedin/callback", methods=["GET"])
class LinkedInOauthCallbackResource(MethodView):
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[oauth_linkedin_resource.py][LinkedInOauthCallbackResource][get][{client_ip}]"

        error = request.args.get("error")
        if error:
            desc = request.args.get("error_description") or "Authorization failed"
            Log.info(f"{log_tag} user denied/failed: error={error} desc={desc}")
            return jsonify({"success": False, "message": desc}), HTTP_STATUS_CODES["BAD_REQUEST"]

        code = request.args.get("code")
        state = request.args.get("state")

        Log.info(f"{log_tag} args={dict(request.args)}")

        if not code or not state:
            return jsonify({"success": False, "message": "Missing code/state"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        raw = get_redis(f"linkedin_oauth_state:{state}")
        doc = _safe_json_load(raw, default={}) if raw else {}
        if not doc:
            return jsonify({"success": False, "message": "OAuth state expired. Retry connect."}), HTTP_STATUS_CODES["BAD_REQUEST"]

        owner = doc.get("owner") or {}
        if not owner.get("business_id") or not owner.get("user__id"):
            return jsonify({"success": False, "message": "Invalid OAuth cache"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        client_id, client_secret, callback_url = _require_linkedin_env(log_tag)
        if not client_id or not client_secret or not callback_url:
            return jsonify({"success": False, "message": "LinkedIn OAuth env missing"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        # Exchange code -> token
        try:
            token_resp = requests.post(
                _linkedin_token_url(),
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": callback_url,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                timeout=30,
            )

            if token_resp.status_code >= 400:
                Log.info(f"{log_tag} token exchange failed: {token_resp.status_code} {token_resp.text}")
                return jsonify({"success": False, "message": "LinkedIn token exchange failed"}), HTTP_STATUS_CODES["BAD_REQUEST"]

            token_data = token_resp.json() if token_resp.text else {}
            access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in")  # seconds

            if not access_token:
                return jsonify({"success": False, "message": "Missing access_token from LinkedIn"}), HTTP_STATUS_CODES["BAD_REQUEST"]

            token_expires_at = None
            if expires_in:
                try:
                    token_expires_at = (datetime.utcnow() + timedelta(seconds=int(expires_in))).isoformat()
                except Exception:
                    token_expires_at = None

            # Fetch destinations (profile + pages if available)
            userinfo = _fetch_linkedin_userinfo(access_token, log_tag)
            orgs = _fetch_linkedin_admin_organizations(access_token, log_tag)

            selection_key = secrets.token_urlsafe(24)

            _store_selection(
                provider="linkedin",
                selection_key=selection_key,
                payload={
                    "owner": owner,
                    "token_data": {
                        "access_token": access_token,
                        "expires_in": expires_in,
                        "token_expires_at": token_expires_at,
                        # LinkedIn usually doesn't return refresh_token in this flow
                        "refresh_token": token_data.get("refresh_token"),
                        "scope": token_data.get("scope"),
                    },
                    "destinations": {
                        "profile": userinfo,
                        "organizations": orgs,
                    },
                },
                ttl_seconds=300,
            )

            # cleanup state
            try:
                remove_redis(f"linkedin_oauth_state:{state}")
            except Exception:
                pass

            # Frontend route you handle (similar to /connect/x)
            return _redirect_to_frontend("/connect/linkedin", selection_key)

        except Exception as e:
            Log.info(f"{log_tag} LinkedIn OAuth failed: {e}")
            return jsonify({"success": False, "message": "LinkedIn OAuth failed"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------------------------------
# LinkedIn: LIST ACCOUNTS (from redis selection_key)
# -------------------------------------------------------------------
@blp_linkedin_oauth.route("/social/linkedin/accounts", methods=["GET"])
class LinkedInAccountsResource(MethodView):
    @token_required
    def get(self):
        client_ip = request.remote_addr
        
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        account_type = user_info.get("account_type")
        auth_business_id = str(user_info.get("business_id"))
        target_business_id = str(user_info.get("business_id"))
        admin_id = str(user_info.get("admin_id"))
        
        log_tag = make_log_tag(
            "oauth_linkedin_resource.py",
            "LinkedInAccountsResource",
            "post",
            client_ip,
            auth_user__id,
            account_type,
            auth_business_id,
            target_business_id
        )
        
        #####################PRE TRANSACTION CHECKS#########################
        
        # 1. check pre transaction requirements for agents
        pre_check = PreProcessCheck(business_id=target_business_id, account_type=account_type, admin_id=admin_id)
        initial_check_result = pre_check.initial_processs_checks()
        
        if initial_check_result is not None:
            return initial_check_result
        #####################PRE TRANSACTION CHECKS#########################

        selection_key = request.args.get("selection_key")
        if not selection_key:
            return jsonify({"success": False, "message": "selection_key is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        raw = get_redis(f"linkedin_select:{selection_key}")
        if not raw:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["NOT_FOUND"]

        doc = _safe_json_load(raw, default={}) or {}
        owner = doc.get("owner") or {}
        destinations = doc.get("destinations") or {}
        profile = destinations.get("profile") or {}
        orgs = destinations.get("organizations") or []

        # Ensure logged-in user matches owner
        user = g.get("current_user", {}) or {}
        if (
            str(user.get("business_id")) != str(owner.get("business_id"))
            or str(user.get("_id")) != str(owner.get("user__id"))
        ):
            Log.info(f"{log_tag} Owner mismatch: current_user != selection owner")
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        # Build safe account list for UI selection
        safe_accounts = []

        # Member profile destination
        # userinfo.sub is typically the LinkedIn member id (OIDC subject)
        member_id = profile.get("sub") or ""
        member_name = profile.get("name") or profile.get("given_name") or "LinkedIn Member"

        if member_id:
            safe_accounts.append(
                {
                    "platform": "linkedin",
                    "destination_type": "member",
                    "destination_id": member_id,
                    "destination_name": member_name,
                }
            )

        # Organizations/pages destination
        for org in orgs:
            safe_accounts.append(
                {
                    "platform": "linkedin",
                    "destination_type": "organization",
                    "destination_id": org.get("id"),
                    "destination_name": org.get("name") or org.get("id"),
                }
            )

        return jsonify({"success": True, "data": {"accounts": safe_accounts}}), HTTP_STATUS_CODES["OK"]


# -------------------------------------------------------------------
# LinkedIn: CONNECT ACCOUNT (finalize into social_accounts)
# -------------------------------------------------------------------
@blp_linkedin_oauth.route("/social/linkedin/connect-account", methods=["POST"])
class LinkedInConnectAccountResource(MethodView):
    @token_required
    def post(self):
        client_ip = request.remote_addr

        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        account_type = user_info.get("account_type")
        auth_business_id = str(user_info.get("business_id"))
        admin_id = str(user_info.get("admin_id"))

        # Optional business_id override for SYSTEM_OWNER / SUPER_ADMIN
        body = request.get_json(silent=True) or {}
        form_business_id = body.get("business_id")
        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
            target_business_id = str(form_business_id)
        else:
            target_business_id = auth_business_id

        log_tag = make_log_tag(
            "oauth_linkedin_resource.py",
            "LinkedInConnectAccountResource",
            "post",
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

        selection_key = body.get("selection_key")
        destination_id = body.get("destination_id")
        destination_type = body.get("destination_type")  # "member" or "organization"

        if not selection_key:
            return jsonify({"success": False, "message": "selection_key is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]
        if not destination_id or not destination_type:
            return jsonify({"success": False, "message": "destination_id and destination_type are required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        raw = get_redis(f"linkedin_select:{selection_key}")
        if not raw:
            return jsonify({"success": False, "message": "Selection expired. Please reconnect."}), HTTP_STATUS_CODES["NOT_FOUND"]

        doc = _safe_json_load(raw, default={}) or {}
        owner = doc.get("owner") or {}
        token_data = doc.get("token_data") or {}
        destinations = doc.get("destinations") or {}

        # Ensure logged-in user matches selection owner
        user = g.get("current_user", {}) or {}
        if (
            str(user.get("business_id")) != str(owner.get("business_id"))
            or str(user.get("_id")) != str(owner.get("user__id"))
        ):
            Log.info(f"{log_tag} Owner mismatch: current_user != selection owner")
            return jsonify({"success": False, "message": "Not allowed for this selection_key"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        token_expires_at = token_data.get("token_expires_at")
        scopes = (token_data.get("scope") or token_data.get("scopes") or "").split()

        if not access_token:
            return jsonify({
                "success": False,
                "message": "Invalid OAuth selection (missing token data). Please reconnect."
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Validate destination exists in selection (extra safety)
        allowed = False
        destination_name = None

        if destination_type == "member":
            profile = (destinations.get("profile") or {})
            if str(profile.get("sub")) == str(destination_id):
                allowed = True
                destination_name = profile.get("name") or "LinkedIn Member"

        elif destination_type == "organization":
            orgs = destinations.get("organizations") or []
            for org in orgs:
                if str(org.get("id")) == str(destination_id):
                    allowed = True
                    destination_name = org.get("name") or org.get("id")
                    break

        if not allowed:
            return jsonify({
                "success": False,
                "message": "destination_id not found for this selection_key"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # ------------------------------------------------------------
        # ✅ NEW: check if this destination already exists
        #   - if exists and token NOT expired/expiring soon => block (already connected)
        #   - if exists but expired/expiring soon => allow reconnect WITHOUT consuming quota
        #   - if not exists => consume quota then create
        # ------------------------------------------------------------
        destination_id = str(destination_id)

        try:
            existing = SocialAccount.get_destination(
                owner["business_id"],
                owner["user__id"],
                "linkedin",
                destination_id,
            )
        except Exception:
            existing = None

        enforcer = QuotaEnforcer(target_business_id)

        consume_quota = True
        if existing:
            try:
                if not is_token_expired(existing):
                    if is_token_expiring_soon(existing, minutes=10):
                        consume_quota = False
                        Log.info(f"{log_tag} LinkedIn token expiring soon; allowing OAuth reconnect without consuming quota")
                    else:
                        return jsonify({
                            "success": False,
                            "message": "This LinkedIn account is already connected.",
                            "code": "ALREADY_CONNECTED",
                        }), HTTP_STATUS_CODES["CONFLICT"]
                else:
                    consume_quota = False
                    Log.info(f"{log_tag} LinkedIn token expired; allowing OAuth reconnect without consuming quota")
            except Exception:
                consume_quota = False
                Log.info(f"{log_tag} Could not determine token expiry; allowing overwrite without consuming quota")

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
                platform="linkedin",
                destination_id=destination_id,
                destination_type=destination_type,
                destination_name=destination_name or destination_id,

                access_token_plain=access_token,
                refresh_token_plain=refresh_token,
                token_expires_at=token_expires_at,

                scopes=scopes or ["openid", "profile", "email"],

                platform_user_id=destination_id,
                platform_username=None,

                meta={
                    "destination_type": destination_type,
                    "token_scope": token_data.get("scope"),
                },
            )

            # one-time use selection
            try:
                remove_redis(f"linkedin_select:{selection_key}")
            except Exception:
                pass

            return jsonify({
                "success": True,
                "message": "LinkedIn account connected successfully"
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} Failed to upsert LinkedIn destination: {e}")
            if consume_quota:
                enforcer.release(counter_name="social_accounts", qty=1, period="billing")
            return jsonify({
                "success": False,
                "message": "Failed to connect LinkedIn account"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]













