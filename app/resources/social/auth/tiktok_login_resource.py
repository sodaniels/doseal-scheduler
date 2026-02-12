# app/routes/auth/tiktok_login_resource.py

import os
import time
import secrets
import bcrypt
from typing import Tuple, Optional
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from flask_smorest import Blueprint
from flask import request, jsonify, redirect, g
from flask.views import MethodView
from bson import ObjectId
import json

# helpers
from ....constants.service_code import HTTP_STATUS_CODES, SYSTEM_USERS
from ....utils.logger import Log
from ....utils.helpers import create_token_response_admin
from ....utils.json_response import prepared_response
from ....utils.generators import generate_client_id, generate_client_secret
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.generators import generate_confirm_email_token
from ....services.email_service import send_user_registration_email
from ....utils.rate_limits import (
    social_login_initiator_limiter,
    social_login_callback_limiter
)

from ....extensions.redis_conn import redis_client
from ....extensions.db import db

# models
from ....models.business_model import Business, Client
from ....models.user_model import User
from ....models.admin.subscription_model import Subscription
from ....models.notifications.notification_settings import NotificationSettings

# services
from ....services.seeders.social_role_seeder import SocialRoleSeeder


blp_tiktok_login = Blueprint("tiktok_login", __name__)


# =========================================
# CONSTANTS
# =========================================
TIKTOK_AUTH_URL = "https://www.tiktok.com/v2/auth/authorize"
TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
TIKTOK_USERINFO_URL = "https://open.tiktokapis.com/v2/user/info/"

# TikTok OAuth 2.0 scopes for login
# user.info.basic is required for authentication
TIKTOK_LOGIN_SCOPES = [
    "user.info.basic",
    "user.info.profile",
    "user.info.stats",
]

# Additional scopes for video posting (used when connecting TikTok account, not for login)
TIKTOK_POSTING_SCOPES = [
    "video.publish",
    "video.upload",
]


# =========================================
# HELPER: Generate code verifier and challenge for PKCE
# =========================================
def _generate_pkce_pair() -> Tuple[str, str]:
    """
    Generate PKCE code verifier and code challenge.
    
    TikTok requires PKCE (Proof Key for Code Exchange) for OAuth 2.0.
    
    Returns: (code_verifier, code_challenge)
    """
    import hashlib
    import base64
    
    # Generate code verifier (43-128 characters)
    code_verifier = secrets.token_urlsafe(64)[:128]
    
    # Generate code challenge using S256 method
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode('utf-8')).digest()
    ).decode('utf-8').rstrip('=')
    
    return code_verifier, code_challenge


# =========================================
# HELPER: Exchange code for token
# =========================================
def _exchange_code_for_token(code: str, code_verifier: str, redirect_uri: str, log_tag: str) -> dict:
    """
    Exchange authorization code for access token using TikTok OAuth 2.0.
    
    TikTok requires PKCE, so we need to send the code_verifier.
    """
    import requests
    
    client_key = os.getenv("TIKTOK_CLIENT_KEY") or os.getenv("TIKTOK_CLIENT_ID")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET")
    
    if not client_key or not client_secret:
        raise ValueError("TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET must be set")
    
    token_data = {
        "client_key": client_key,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }
    
    response = requests.post(
        TIKTOK_TOKEN_URL,
        data=token_data,
        headers=headers,
        timeout=30,
    )
    
    if response.status_code != 200:
        Log.error(f"{log_tag} Token exchange failed: {response.text}")
        raise ValueError(f"Token exchange failed: {response.text}")
    
    token_response = response.json()
    
    # TikTok returns data in a nested structure
    if token_response.get("error"):
        error_desc = token_response.get("error_description", token_response.get("error"))
        raise ValueError(f"Token exchange failed: {error_desc}")
    
    access_token = token_response.get("access_token")
    
    if not access_token:
        raise ValueError("No access_token in response")
    
    return {
        "access_token": access_token,
        "expires_in": token_response.get("expires_in", 86400),  # Default 24 hours
        "refresh_token": token_response.get("refresh_token"),
        "refresh_expires_in": token_response.get("refresh_expires_in"),
        "scope": token_response.get("scope"),
        "token_type": token_response.get("token_type", "Bearer"),
        "open_id": token_response.get("open_id"),  # TikTok's unique user identifier
    }


# =========================================
# HELPER: Get TikTok user profile
# =========================================
def _get_tiktok_user_profile(access_token: str, log_tag: str) -> dict:
    """
    Get user profile from TikTok using the userinfo endpoint.
    
    TikTok API v2 requires specifying which fields to return.
    """
    import requests
    
    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    
    # TikTok requires specifying fields in the query
    params = {
        "fields": "open_id,union_id,avatar_url,avatar_url_100,avatar_large_url,display_name,bio_description,profile_deep_link,is_verified,follower_count,following_count,likes_count,video_count",
    }
    
    response = requests.get(
        TIKTOK_USERINFO_URL,
        params=params,
        headers=headers,
        timeout=30,
    )
    
    if response.status_code != 200:
        Log.error(f"{log_tag} Failed to get TikTok user profile: {response.text}")
        raise ValueError(f"Failed to get user profile: {response.text}")
    
    response_data = response.json()
    
    # Check for errors
    if response_data.get("error", {}).get("code") != "ok":
        error_msg = response_data.get("error", {}).get("message", "Unknown error")
        Log.error(f"{log_tag} TikTok API error: {error_msg}")
        raise ValueError(f"TikTok API error: {error_msg}")
    
    data = response_data.get("data", {}).get("user", {})
    
    return {
        "tiktok_open_id": data.get("open_id"),
        "tiktok_union_id": data.get("union_id"),
        "display_name": data.get("display_name"),
        "username": data.get("display_name"),  # TikTok doesn't expose username via API
        "profile_picture": data.get("avatar_url") or data.get("avatar_large_url") or data.get("avatar_url_100"),
        "bio": data.get("bio_description"),
        "profile_deep_link": data.get("profile_deep_link"),
        "is_verified": data.get("is_verified", False),
        "follower_count": data.get("follower_count"),
        "following_count": data.get("following_count"),
        "likes_count": data.get("likes_count"),
        "video_count": data.get("video_count"),
    }


# =========================================
# HELPER: Create Business and User
# =========================================
def _create_account_from_tiktok(
    profile: dict,
    log_tag: str,
) -> Tuple[ObjectId, dict]:
    """
    Create a new business and user account from TikTok profile.
    
    This mirrors your existing registration flow:
    1. Create Business
    2. Create User
    3. Seed NotificationSettings
    4. Seed SocialRoles
    5. Create Client
    
    NOTE: TikTok accounts are NOT connected here. User must:
    1. Subscribe to a package
    2. Then connect TikTok via /social/oauth/tiktok/start
    
    IMPORTANT: TikTok does NOT provide email via OAuth.
    We'll generate a placeholder email that user must update later.
    
    Returns: (business_id, user_doc)
    """
    
    tiktok_open_id = profile.get("tiktok_open_id")
    display_name = profile.get("display_name") or "TikTok User"
    username = profile.get("username") or display_name
    
    # TikTok doesn't provide email via OAuth
    # Generate a placeholder email that user must update later
    placeholder_email = f"{tiktok_open_id}@tiktok.placeholder.doseal.com"
    
    # Use display name for name
    name = display_name
    first_name = name.split(" ")[0] if " " in name else name
    last_name = name.split(" ", 1)[1] if " " in name else ""
    
    # Generate a random password (user can set it later)
    random_password = secrets.token_urlsafe(16)
    hashed_password = bcrypt.hashpw(
        random_password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")
    
    # Generate tenant_id and client_id
    tenant_id = str(ObjectId())
    client_id_plain = generate_client_id()
    
    # Account status - NOT subscribed yet, email NOT verified (placeholder)
    account_status = [
        {
            "account_created": {
                "created_at": str(datetime.utcnow()),
                "status": True,
            },
        },
        {
            "business_email_verified": {
                "created_at": str(datetime.utcnow()),
                "status": False,  # NOT verified - using placeholder
            }
        },
        {
            "subscribed_to_package": {
                "status": False,  # NOT subscribed - needs to choose package
            }
        }
    ]
    
    account_type = SYSTEM_USERS["BUSINESS_OWNER"]
    
    # =========================================
    # 1. CREATE BUSINESS
    # =========================================
    Log.info(f"{log_tag} Creating business for TikTok user {display_name}")
    
    business_col = db.get_collection("businesses")
    
    business_doc = {
        "tenant_id": encrypt_data(tenant_id),
        "business_name": encrypt_data(name),
        "first_name": encrypt_data(first_name),
        "last_name": encrypt_data(last_name),
        "email": encrypt_data(placeholder_email),
        "hashed_email": hash_data(placeholder_email),
        "password": hashed_password,
        "client_id": encrypt_data(client_id_plain),
        "client_id_hashed": hash_data(client_id_plain),
        "status": encrypt_data("Active"),
        "hashed_status": hash_data("Active"),
        "account_status": encrypt_data(account_status),
        "account_type": encrypt_data(account_type),
        "image": profile.get("profile_picture"),
        "tiktok_open_id": tiktok_open_id,
        "tiktok_union_id": profile.get("tiktok_union_id"),
        "tiktok_display_name": display_name,
        "social_login_provider": "tiktok",
        "email_needs_verification": True,  # Flag to prompt user to add real email
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    
    business_result = business_col.insert_one(business_doc)
    business_id = business_result.inserted_id
    Log.info(f"{log_tag} Business created: {business_id}")
    
    # =========================================
    # 2. CREATE USER
    # =========================================
    Log.info(f"{log_tag} Creating user for TikTok user {display_name}")
    
    user_col = db.get_collection("users")
    
    user_doc = {
        "business_id": business_id,
        "tenant_id": encrypt_data(tenant_id),
        "fullname": encrypt_data(name),
        "hashed_fullname": hash_data(name),
        "email": encrypt_data(placeholder_email),
        "email_hashed": hash_data(placeholder_email),
        "phone_number": None,
        "password": hashed_password,
        "client_id": encrypt_data(client_id_plain),
        "client_id_hashed": hash_data(client_id_plain),
        "status": encrypt_data("Active"),
        "account_type": encrypt_data(account_type),
        "email_verified": "pending",  # NOT verified - using placeholder
        "tiktok_open_id": tiktok_open_id,
        "tiktok_union_id": profile.get("tiktok_union_id"),
        "tiktok_display_name": display_name,
        "social_login_provider": "tiktok",
        "email_needs_verification": True,
        "devices": [],
        "locations": [],
        "referrals": [],
        "transactions": 0,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    
    user_result = user_col.insert_one(user_doc)
    user_id = user_result.inserted_id
    user_doc["_id"] = user_id
    
    Log.info(f"{log_tag} User created: {user_id}")
    
    # =========================================
    # 3. UPDATE BUSINESS WITH USER_ID
    # =========================================
    try:
        business_col.update_one(
            {"_id": business_id},
            {"$set": {"user_id": user_id, "updated_at": datetime.utcnow()}}
        )
        Log.info(f"{log_tag} Business updated with user_id")
    except Exception as e:
        Log.error(f"{log_tag} Error updating business with user_id: {e}")
    
    # =========================================
    # 4. SEED NOTIFICATION SETTINGS
    # =========================================
    try:
        NotificationSettings.seed_for_user(
            business_id=str(business_id),
            user__id=str(user_id),
        )
        Log.info(f"{log_tag} Notification settings seeded")
    except Exception as e:
        Log.error(f"{log_tag} Error seeding notifications: {e}")
    
    # =========================================
    # 5. SEED SOCIAL ROLES
    # =========================================
    try:
        SocialRoleSeeder.seed_defaults(
            business_id=str(business_id),
            admin_user__id=str(user_id),
            admin_user_id="",
            admin_email=placeholder_email,
            admin_name=name,
        )
        Log.info(f"{log_tag} Social roles seeded")
    except Exception as e:
        Log.error(f"{log_tag} Error seeding social roles: {e}")
    
    # =========================================
    # 6. CREATE CLIENT
    # =========================================
    try:
        client_secret = generate_client_secret()
        Client.create_client(client_id_plain, client_secret)
        Log.info(f"{log_tag} Client created")
    except Exception as e:
        Log.error(f"{log_tag} Error creating client: {e}")
    
    return (business_id, user_doc)


# =========================================
# HELPER: Store/retrieve OAuth state
# =========================================
def _store_login_state(state: str, data: dict, ttl_seconds: int = 600):
    """Store OAuth state in Redis."""
    redis_client.setex(
        f"tiktok_login_state:{state}",
        ttl_seconds,
        json.dumps(data),
    )


def _consume_login_state(state: str) -> Optional[dict]:
    """Retrieve and delete OAuth state from Redis."""
    key = f"tiktok_login_state:{state}"
    raw = redis_client.get(key)
    if not raw:
        return None
    redis_client.delete(key)
    try:
        return json.loads(raw)
    except:
        return None


# =========================================
# INITIATE TIKTOK LOGIN
# =========================================
@social_login_initiator_limiter("tiktok_login")
@blp_tiktok_login.route("/auth/tiktok/business/login", methods=["GET"])
class TikTokLoginStartResource(MethodView):
    """
    Initiate TikTok Login OAuth 2.0 flow with PKCE.
    
    This is for AUTHENTICATION ONLY - not for connecting TikTok accounts.
    
    IMPORTANT: TikTok does NOT provide email via OAuth.
    Users will need to update their email after signing up.
    
    After login, users must:
    1. Update their email (TikTok doesn't provide email)
    2. Subscribe to a package
    3. Connect TikTok accounts via /social/oauth/tiktok/start
    
    Query params:
    - return_url: Where to redirect after auth (default: FRONTEND_URL)
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[tiktok_login_resource.py][TikTokLoginStartResource][get][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Initiating TikTok login")
        
        try:
            client_key = os.getenv("TIKTOK_CLIENT_KEY")
            redirect_uri = os.getenv("TIKTOK_LOGIN_CALLBACK_URL")
            
            if not client_key or not redirect_uri:
                Log.error(f"{log_tag} Missing TIKTOK_CLIENT_KEY or TIKTOK_LOGIN_CALLBACK_URL")
                return jsonify({
                    "success": False,
                    "message": "Server OAuth configuration missing",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            
            return_url = request.args.get("return_url", os.getenv("FRONTEND_URL", "/"))
            
            # Generate state for CSRF protection
            state = secrets.token_urlsafe(24)
            
            # Generate PKCE pair (TikTok requires PKCE)
            code_verifier, code_challenge = _generate_pkce_pair()
            
            # Store state and code_verifier in Redis
            _store_login_state(state, {
                "return_url": return_url,
                "code_verifier": code_verifier,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            
            # Build authorization URL
            params = {
                "client_key": client_key,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": ",".join(TIKTOK_LOGIN_SCOPES),
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
            
            auth_url = f"{TIKTOK_AUTH_URL}?" + urlencode(params)
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Redirecting to TikTok OAuth in {duration:.2f}s")
            
            return redirect(auth_url)
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to initiate TikTok login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# TIKTOK LOGIN CALLBACK
# =========================================
@social_login_callback_limiter("tiktok_login")
@blp_tiktok_login.route("/auth/tiktok/business/callback", methods=["GET"])
class TikTokLoginCallbackResource(MethodView):
    """
    Handle TikTok Login OAuth 2.0 callback.
    
    This endpoint ONLY handles authentication:
    1. Exchanges code for access token (with PKCE)
    2. Gets user profile from TikTok
    3. Creates account OR logs in existing user
    4. Returns JWT tokens
    
    NOTE: TikTok does NOT provide email. After login:
    - User should update their email
    - If no subscription: User should be redirected to pricing
    - If has subscription: User can connect TikTok via /social/oauth/tiktok/start
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[tiktok_login_resource.py][TikTokLoginCallbackResource][get][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Processing TikTok login callback")
        
        # Get parameters
        code = request.args.get("code")
        state = request.args.get("state")
        error = request.args.get("error")
        error_description = request.args.get("error_description")
        
        # Handle errors from TikTok
        if error:
            Log.info(f"{log_tag} TikTok returned error: {error} - {error_description}")
            return jsonify({
                "success": False,
                "message": f"TikTok authentication failed: {error_description or error}",
                "code": "TIKTOK_ERROR",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if not code:
            return jsonify({
                "success": False,
                "message": "Authorization code missing",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if not state:
            return jsonify({
                "success": False,
                "message": "State parameter missing",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            # Verify state and retrieve code_verifier
            state_data = _consume_login_state(state)
            
            if not state_data:
                Log.info(f"{log_tag} Invalid or expired state")
                return jsonify({
                    "success": False,
                    "message": "Invalid or expired state. Please try again.",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            return_url = state_data.get("return_url", "/")
            code_verifier = state_data.get("code_verifier")
            
            if not code_verifier:
                Log.error(f"{log_tag} Code verifier missing from state")
                return jsonify({
                    "success": False,
                    "message": "Invalid OAuth state. Please try again.",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # Get redirect URI
            redirect_uri = os.getenv("TIKTOK_LOGIN_CALLBACK_URL") or os.getenv("TIKTOK_REDIRECT_URI")
            
            # =========================================
            # 1. EXCHANGE CODE FOR TOKEN
            # =========================================
            Log.info(f"{log_tag} Exchanging code for token...")
            
            token_start = time.time()
            token_data = _exchange_code_for_token(code, code_verifier, redirect_uri, log_tag)
            access_token = token_data["access_token"]
            tiktok_open_id = token_data.get("open_id")
            token_duration = time.time() - token_start
            
            Log.info(f"{log_tag} Token exchange completed in {token_duration:.2f}s, open_id={tiktok_open_id}")
            
            # =========================================
            # 2. GET USER PROFILE
            # =========================================
            Log.info(f"{log_tag} Getting user profile...")
            
            profile_start = time.time()
            profile = _get_tiktok_user_profile(access_token, log_tag)
            profile_duration = time.time() - profile_start
            
            Log.info(f"{log_tag} Profile fetch completed in {profile_duration:.2f}s")
            
            # Use open_id from token if not in profile
            if not profile.get("tiktok_open_id") and tiktok_open_id:
                profile["tiktok_open_id"] = tiktok_open_id
            
            tiktok_open_id = profile.get("tiktok_open_id")
            display_name = profile.get("display_name")
            
            Log.info(f"{log_tag} Got profile: tiktok_open_id={tiktok_open_id}, display_name={display_name}")
            
            if not tiktok_open_id:
                Log.error(f"{log_tag} TikTok open_id not provided")
                return jsonify({
                    "success": False,
                    "message": "Failed to get TikTok user ID. Please try again.",
                    "code": "MISSING_USER_ID",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # =========================================
            # 3. CHECK IF USER EXISTS
            # =========================================
            user_col = db.get_collection("users")
            
            # First check by TikTok open_id
            existing_user = user_col.find_one({"tiktok_open_id": tiktok_open_id})
            
            # Also check by union_id if available
            if not existing_user and profile.get("tiktok_union_id"):
                existing_user = user_col.find_one({"tiktok_union_id": profile.get("tiktok_union_id")})
            
            if existing_user:
                # =========================================
                # EXISTING USER (by TikTok ID) - LOG THEM IN
                # =========================================
                Log.info(f"{log_tag} Existing user found by tiktok_open_id, logging in")
                
                business = Business.get_business_by_id(str(existing_user["business_id"]))
                
                if not business:
                    Log.error(f"{log_tag} Business not found for existing user")
                    return jsonify({
                        "success": False,
                        "message": "Account not found. Please contact support.",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
                # Update TikTok info if changed
                update_fields = {
                    "updated_at": datetime.utcnow(),
                }
                
                if profile.get("display_name") and profile.get("display_name") != existing_user.get("tiktok_display_name"):
                    update_fields["tiktok_display_name"] = profile.get("display_name")
                
                if profile.get("tiktok_union_id") and not existing_user.get("tiktok_union_id"):
                    update_fields["tiktok_union_id"] = profile.get("tiktok_union_id")
                
                user_col.update_one(
                    {"_id": existing_user["_id"]},
                    {"$set": update_fields}
                )
                
                # Get account_type for token generation
                account_type = decrypt_data(existing_user.get("account_type")) if existing_user.get("account_type") else SYSTEM_USERS["BUSINESS_OWNER"]
                
                duration = time.time() - start_time
                Log.info(f"{log_tag} Login successful in {duration:.2f}s")
                
                # Return token
                return create_token_response_admin(
                    user=existing_user,
                    account_type=account_type,
                    client_ip=client_ip,
                    log_tag=log_tag,
                )
            
            # =========================================
            # 4. NEW USER - Create account
            # =========================================
            # Note: We don't check by email because TikTok doesn't provide email
            Log.info(f"{log_tag} Creating new account from TikTok profile")
            
            business_id, user_doc = _create_account_from_tiktok(
                profile=profile,
                log_tag=log_tag,
            )
            
            # Get account_type for token generation
            account_type = SYSTEM_USERS["BUSINESS_OWNER"]
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} New account created in {duration:.2f}s")
            
            # Return token
            return create_token_response_admin(
                user=user_doc,
                account_type=account_type,
                client_ip=client_ip,
                log_tag=log_tag,
            )
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            import traceback
            traceback.print_exc()
            
            return jsonify({
                "success": False,
                "message": "Failed to complete TikTok login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# UPDATE EMAIL (for TikTok users - required since TikTok doesn't provide email)
# =========================================
@blp_tiktok_login.route("/auth/tiktok/update-email", methods=["POST"])
class TikTokUpdateEmailResource(MethodView):
    """
    Update email for users who signed up via TikTok Login.
    
    TikTok doesn't provide email via OAuth, so users need to add their email
    after signing up to receive notifications and for account recovery.
    
    Body:
    {
        "email": "user@example.com"
    }
    """
    
    def post(self):
        from ....resources.doseal.admin.admin_business_resource import token_required
        
        @token_required
        def _post():
            user = g.get("current_user", {}) or {}
            business_id = str(user.get("business_id", ""))
            user__id = str(user.get("_id", ""))
            
            client_ip = request.remote_addr
            log_tag = f"[tiktok_login_resource.py][TikTokUpdateEmailResource][{client_ip}][{user__id}]"
            
            body = request.get_json(silent=True) or {}
            new_email = body.get("email", "").strip().lower()
            return_url = body.get("return_url", "").strip().lower()
            
            if not new_email:
                return jsonify({
                    "success": False,
                    "message": "Email is required",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
                
            if not return_url:
                return jsonify({
                    "success": False,
                    "message": "Return URL is required",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
                
                
            
            # Basic email validation
            import re
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_pattern, new_email):
                return jsonify({
                    "success": False,
                    "message": "Please provide a valid email address",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # Check if email is a placeholder
            if "@tiktok.placeholder.doseal.com" in new_email:
                return jsonify({
                    "success": False,
                    "message": "Please provide a real email address",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            try:
                # Check if email is already taken
                existing_business = Business.get_business_by_email(new_email)
                if existing_business and str(existing_business.get("_id")) != business_id:
                    return jsonify({
                        "success": False,
                        "message": "This email is already associated with another account",
                    }), HTTP_STATUS_CODES["CONFLICT"]
                
                # Update user email
                user_col = db.get_collection("users")
                user_col.update_one(
                    {"_id": ObjectId(user__id)},
                    {"$set": {
                        "email": encrypt_data(new_email),
                        "email_hashed": hash_data(new_email),
                        "email_verified": "pending",  # Will need to verify
                        "email_needs_verification": False,
                        "updated_at": datetime.utcnow(),
                    }}
                )
                
                # Update business email
                business_col = db.get_collection("businesses")
                business_col.update_one(
                    {"_id": ObjectId(business_id)},
                    {"$set": {
                        "email": encrypt_data(new_email),
                        "hashed_email": hash_data(new_email),
                        "email_needs_verification": False,
                        "updated_at": datetime.utcnow(),
                    }}
                )
                
                fullname = decrypt_data(existing_business.get("first_name")) +" "+decrypt_data(existing_business.get("last_name"))
                
                Log.info(f"{log_tag} Email updated to {new_email}")
                
                try:
                    token = secrets.token_urlsafe(32) # Generates a 32-byte URL-safe token 
                    reset_url = generate_confirm_email_token(return_url, token)
    
                    update_code = User.update_auth_code(new_email, token)
                    
                    if update_code:
                        Log.info(f"{log_tag}\t reset_url: {reset_url}")
                        try:
                            result = send_user_registration_email(new_email, fullname, reset_url)
                            Log.info(f"Email sent result={result}")
                        except Exception as e:
                            Log.error(f"Email sending failed: {e}")
                            raise
                except Exception as e:
                    Log.info(f"{log_tag}\t An error occurred sending emails: {e}")
                
                return jsonify({
                    "success": True,
                    "message": "Email updated successfully. Please check your inbox to verify your email.",
                }), HTTP_STATUS_CODES["OK"]
            
            except Exception as e:
                Log.error(f"{log_tag} Error: {e}")
                return jsonify({
                    "success": False,
                    "message": "Failed to update email",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        
        return _post()














