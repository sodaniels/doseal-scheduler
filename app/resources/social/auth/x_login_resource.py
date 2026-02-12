# app/routes/auth/x_login_resource.py

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
from ....utils.redis import get_redis, set_redis_with_expiry, remove_redis
from ....utils.json_response import prepared_response
from ....services.email_service import send_user_registration_email
from ....utils.generators import generate_confirm_email_token

from ....extensions.db import db

# models
from ....models.business_model import Business, Client
from ....models.user_model import User
from ....models.admin.subscription_model import Subscription
from ....models.notifications.notification_settings import NotificationSettings

# services
from ....services.seeders.social_role_seeder import SocialRoleSeeder
from ....services.social.adapters.x_adapter import XAdapter

# utils
from ....utils.schedule_helper import _safe_json_load
from ....utils.rate_limits import (
    social_login_initiator_limiter,
    social_login_callback_limiter
)

blp_x_login = Blueprint("x_login", __name__)


# =========================================
# CONSTANTS
# =========================================
X_API_VERSION = "2"

# OAuth 1.0a doesn't have scopes in the same way as OAuth 2.0
# These are the permissions requested during app setup
X_DEFAULT_SCOPES = [
    "tweet.read",
    "tweet.write",
    "users.read",
]


# =========================================
# HELPER: Get X environment variables
# =========================================
def _require_x_env(log_tag: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Get X OAuth environment variables.
    
    Returns: (consumer_key, consumer_secret, callback_url)
    """
    consumer_key = os.getenv("X_CONSUMER_KEY") or os.getenv("TWITTER_CONSUMER_KEY")
    consumer_secret = os.getenv("X_CONSUMER_SECRET") or os.getenv("TWITTER_CONSUMER_SECRET")
    callback_url = os.getenv("X_LOGIN_CALLBACK_URL") or os.getenv("X_CALLBACK_URL") or os.getenv("TWITTER_CALLBACK_URL")
    
    if not consumer_key:
        Log.error(f"{log_tag} X_CONSUMER_KEY not configured")
    if not consumer_secret:
        Log.error(f"{log_tag} X_CONSUMER_SECRET not configured")
    if not callback_url:
        Log.error(f"{log_tag} X_LOGIN_CALLBACK_URL not configured")
    
    return consumer_key, consumer_secret, callback_url


# =========================================
# HELPER: Check if user has active subscription
# =========================================
def _has_active_subscription(business_id: str, log_tag: str) -> bool:
    """
    Check if the business has an active subscription using Subscription model.
    
    Returns True if subscription status is Active or Trial.
    """
    try:
        active_sub = Subscription.get_active_by_business(business_id)
        
        if active_sub:
            status = active_sub.get("status")
            Log.info(f"{log_tag} Business {business_id} has active subscription with status: {status}")
            return True
        
        Log.info(f"{log_tag} Business {business_id} has NO active subscription")
        return False
        
    except Exception as e:
        Log.error(f"{log_tag} Error checking subscription: {e}")
        return False


# =========================================
# HELPER: Get subscription details
# =========================================
def _get_subscription_details(business_id: str, log_tag: str) -> Optional[dict]:
    """
    Get subscription details for the business using Subscription model.
    """
    try:
        active_sub = Subscription.get_active_by_business(business_id)
        
        if active_sub:
            return {
                "subscription_id": active_sub.get("_id"),
                "status": active_sub.get("status"),
                "package_id": active_sub.get("package_id"),
                "billing_period": active_sub.get("billing_period"),
                "currency": active_sub.get("currency"),
                "price_paid": active_sub.get("price_paid"),
                "start_date": active_sub.get("start_date").isoformat() if active_sub.get("start_date") else None,
                "end_date": active_sub.get("end_date").isoformat() if active_sub.get("end_date") else None,
                "trial_end_date": active_sub.get("trial_end_date").isoformat() if active_sub.get("trial_end_date") else None,
                "auto_renew": active_sub.get("auto_renew"),
                "term_number": active_sub.get("term_number"),
            }
        
        return None
        
    except Exception as e:
        Log.error(f"{log_tag} Error getting subscription details: {e}")
        return None


# =========================================
# HELPER: Get latest subscription (any status)
# =========================================
def _get_latest_subscription(business_id: str, log_tag: str) -> Optional[dict]:
    """
    Get the latest subscription for the business regardless of status.
    """
    try:
        latest_sub = Subscription.get_latest_by_business(business_id)
        
        if latest_sub:
            return {
                "subscription_id": latest_sub.get("_id"),
                "status": latest_sub.get("status"),
                "package_id": latest_sub.get("package_id"),
                "billing_period": latest_sub.get("billing_period"),
                "start_date": latest_sub.get("start_date").isoformat() if latest_sub.get("start_date") else None,
                "end_date": latest_sub.get("end_date").isoformat() if latest_sub.get("end_date") else None,
                "cancelled_at": latest_sub.get("cancelled_at").isoformat() if latest_sub.get("cancelled_at") else None,
            }
        
        return None
        
    except Exception as e:
        Log.error(f"{log_tag} Error getting latest subscription: {e}")
        return None


# =========================================
# HELPER: Get X user profile
# =========================================
def _get_x_user_profile(
    consumer_key: str,
    consumer_secret: str,
    oauth_token: str,
    oauth_token_secret: str,
    user_id: str,
    log_tag: str,
) -> dict:
    """
    Get user profile from X API.
    
    Uses OAuth 1.0a signed request to fetch user details.
    """
    import requests
    from requests_oauthlib import OAuth1
    
    try:
        auth = OAuth1(
            consumer_key,
            consumer_secret,
            oauth_token,
            oauth_token_secret,
        )
        
        # Use X API v2 to get user details
        response = requests.get(
            f"https://api.twitter.com/2/users/{user_id}",
            params={
                "user.fields": "id,name,username,profile_image_url,description,created_at,public_metrics",
            },
            auth=auth,
            timeout=30,
        )
        
        if response.status_code != 200:
            Log.error(f"{log_tag} Failed to get X user profile: {response.text}")
            # Return basic info from token exchange if API call fails
            return {
                "x_user_id": user_id,
                "username": None,
                "name": None,
                "profile_picture": None,
                "description": None,
            }
        
        data = response.json()
        user_data = data.get("data", {})
        
        return {
            "x_user_id": user_data.get("id"),
            "username": user_data.get("username"),
            "name": user_data.get("name"),
            "profile_picture": user_data.get("profile_image_url"),
            "description": user_data.get("description"),
            "followers_count": user_data.get("public_metrics", {}).get("followers_count"),
            "following_count": user_data.get("public_metrics", {}).get("following_count"),
        }
        
    except Exception as e:
        Log.error(f"{log_tag} Error fetching X user profile: {e}")
        return {
            "x_user_id": user_id,
            "username": None,
            "name": None,
            "profile_picture": None,
            "description": None,
        }


# =========================================
# HELPER: Create Business and User from X profile
# =========================================
def _create_account_from_x(
    profile: dict,
    screen_name: str,
    log_tag: str,
) -> Tuple[ObjectId, dict]:
    """
    Create a new business and user account from X profile.
    
    This mirrors your existing registration flow:
    1. Create Business
    2. Create User
    3. Seed NotificationSettings
    4. Seed SocialRoles
    5. Create Client
    
    NOTE: X accounts are NOT connected here. User must:
    1. Subscribe to a package
    2. Then connect X via /social/oauth/x/start
    
    Returns: (business_id, user_doc)
    """
    
    x_user_id = profile.get("x_user_id")
    username = profile.get("username") or screen_name
    name = profile.get("name") or username
    profile_picture = profile.get("profile_picture")
    
    # X doesn't provide email via OAuth 1.0a by default
    # We'll generate a placeholder email that user can update later
    # Or you can require email input after login
    placeholder_email = f"{username}@x.placeholder.doseal.com"
    
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
                "status": False,  # NOT verified - using placeholder email
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
    Log.info(f"{log_tag} Creating business for X user @{username}")
    
    business_col = db.get_collection("businesses")
    
    business_doc = {
        "tenant_id": encrypt_data(tenant_id),
        "business_name": encrypt_data(name),
        "first_name": encrypt_data(name.split(" ")[0] if " " in name else name),
        "last_name": encrypt_data(name.split(" ", 1)[1] if " " in name else ""),
        "email": encrypt_data(placeholder_email),
        "hashed_email": hash_data(placeholder_email),
        "password": hashed_password,
        "client_id": encrypt_data(client_id_plain),
        "client_id_hashed": hash_data(client_id_plain),
        "status": encrypt_data("Active"),
        "hashed_status": hash_data("Active"),
        "account_status": encrypt_data(account_status),
        "account_type": encrypt_data(account_type),
        "image": profile_picture,
        "x_user_id": x_user_id,
        "x_username": username,
        "social_login_provider": "x",
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
    Log.info(f"{log_tag} Creating user for X user @{username}")
    
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
        "x_user_id": x_user_id,
        "x_username": username,
        "social_login_provider": "x",
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
    set_redis_with_expiry(
        f"x_login_state:{state}",
        ttl_seconds,
        json.dumps(data),
    )


def _consume_login_state(state: str) -> Optional[dict]:
    """Retrieve and delete OAuth state from Redis."""
    key = f"x_login_state:{state}"
    raw = get_redis(key)
    if not raw:
        return None
    remove_redis(key)
    try:
        return json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode('utf-8'))
    except:
        return None


# =========================================
# INITIATE X LOGIN (OAuth 1.0a)
# =========================================
@social_login_initiator_limiter("x_login")
@blp_x_login.route("/auth/x/business/login", methods=["GET"])
class XLoginStartResource(MethodView):
    """
    Initiate X Login OAuth 1.0a flow.
    
    This is for AUTHENTICATION ONLY - not for connecting X accounts.
    
    After login, users must:
    1. Update their email (X doesn't provide email via OAuth)
    2. Subscribe to a package
    3. Connect X accounts via /social/oauth/x/start
    
    Query params:
    - return_url: Where to redirect after auth (default: FRONTEND_URL)
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[x_login_resource.py][XLoginStartResource][get][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Initiating X login")
        
        try:
            consumer_key, consumer_secret, callback_url = _require_x_env(log_tag)
            
            if not consumer_key or not consumer_secret or not callback_url:
                return jsonify({
                    "success": False,
                    "message": "X OAuth configuration missing",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            
            return_url = request.args.get("return_url", os.getenv("FRONTEND_URL", "/"))
            
            # Generate state for CSRF protection
            state = secrets.token_urlsafe(24)
            
            # Embed state into callback_url so callback always receives it
            joiner = "&" if "?" in callback_url else "?"
            callback_url_with_state = f"{callback_url}{joiner}{urlencode({'state': state})}"
            
            # Step 1: Get request token from X
            oauth_token, oauth_token_secret = XAdapter.get_request_token(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                callback_url=callback_url_with_state,
            )
            
            # Store state data in Redis (keyed by state)
            _store_login_state(state, {
                "return_url": return_url,
                "oauth_token": oauth_token,
                "oauth_token_secret": oauth_token_secret,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            
            # Also store by oauth_token as fallback
            set_redis_with_expiry(
                f"x_login_token:{oauth_token}",
                600,
                json.dumps({
                    "state": state,
                    "return_url": return_url,
                    "oauth_token": oauth_token,
                    "oauth_token_secret": oauth_token_secret,
                }),
            )
            
            Log.info(f"{log_tag} Stored state={state}, oauth_token={oauth_token[:10]}...")
            
            # Step 2: Redirect to X authorization page
            auth_url = XAdapter.build_authorize_url(oauth_token)
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Redirecting to X OAuth in {duration:.2f}s")
            
            return redirect(auth_url)
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            import traceback
            traceback.print_exc()
            
            return jsonify({
                "success": False,
                "message": "Failed to initiate X login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# X LOGIN CALLBACK (OAuth 1.0a)
# =========================================
@social_login_callback_limiter("x_login")
@blp_x_login.route("/auth/x/business/callback", methods=["GET"])
class XLoginCallbackResource(MethodView):
    """
    Handle X Login OAuth 1.0a callback.
    
    This endpoint ONLY handles authentication:
    1. Exchanges request token for access token
    2. Gets user profile from X
    3. Creates account OR logs in existing user
    4. Returns JWT tokens
    
    NOTE: X accounts are NOT connected here. After login:
    - User should update their email (X doesn't provide email)
    - If no subscription: User should be redirected to pricing
    - If has subscription: User can connect X via /social/oauth/x/start
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[x_login_resource.py][XLoginCallbackResource][get][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Processing X login callback")
        
        # Check if user denied authorization
        denied = request.args.get("denied")
        if denied:
            Log.info(f"{log_tag} User denied X authorization")
            return jsonify({
                "success": False,
                "message": "X authorization was denied",
                "code": "X_AUTH_DENIED",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        # Get OAuth parameters
        oauth_token = request.args.get("oauth_token")
        oauth_verifier = request.args.get("oauth_verifier")
        state = request.args.get("state")
        
        Log.info(f"{log_tag} Callback args: oauth_token={oauth_token[:10] if oauth_token else None}..., state={state}")
        
        if not oauth_token or not oauth_verifier:
            return jsonify({
                "success": False,
                "message": "Missing oauth_token or oauth_verifier",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            # Retrieve stored state data
            state_data = None
            
            # Try by state first (preferred)
            if state:
                state_data = _consume_login_state(state)
            
            # Fallback: try by oauth_token
            if not state_data:
                raw = get_redis(f"x_login_token:{oauth_token}")
                if raw:
                    state_data = _safe_json_load(raw, default={})
                    # Also clean up the state key if we found it via token
                    if state_data.get("state"):
                        try:
                            remove_redis(f"x_login_state:{state_data['state']}")
                        except:
                            pass
            
            if not state_data:
                Log.info(f"{log_tag} OAuth state expired or not found")
                return jsonify({
                    "success": False,
                    "message": "OAuth state expired. Please try again.",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            return_url = state_data.get("return_url", "/")
            tmp_token = state_data.get("oauth_token")
            tmp_secret = state_data.get("oauth_token_secret")
            
            if not tmp_token or not tmp_secret:
                return jsonify({
                    "success": False,
                    "message": "Invalid OAuth state data",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # Get X credentials
            consumer_key, consumer_secret, _ = _require_x_env(log_tag)
            if not consumer_key or not consumer_secret:
                return jsonify({
                    "success": False,
                    "message": "X OAuth configuration missing",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            
            # =========================================
            # 1. EXCHANGE FOR ACCESS TOKEN
            # =========================================
            Log.info(f"{log_tag} Exchanging for access token...")
            
            token_start = time.time()
            token_data = XAdapter.exchange_access_token(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                oauth_token=tmp_token,
                oauth_token_secret=tmp_secret,
                oauth_verifier=oauth_verifier,
            )
            token_duration = time.time() - token_start
            
            Log.info(f"{log_tag} Token exchange completed in {token_duration:.2f}s")
            
            # Extract token data
            access_token = token_data.get("oauth_token")
            access_token_secret = token_data.get("oauth_token_secret")
            x_user_id = str(token_data.get("user_id", ""))
            screen_name = token_data.get("screen_name", "")
            
            if not access_token or not access_token_secret or not x_user_id:
                Log.error(f"{log_tag} Invalid token data from X: {token_data}")
                return jsonify({
                    "success": False,
                    "message": "Failed to get access token from X",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            
            Log.info(f"{log_tag} Got X user: id={x_user_id}, screen_name=@{screen_name}")
            
            # =========================================
            # 2. GET USER PROFILE (optional enrichment)
            # =========================================
            Log.info(f"{log_tag} Getting X user profile...")
            
            profile_start = time.time()
            profile = _get_x_user_profile(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                oauth_token=access_token,
                oauth_token_secret=access_token_secret,
                user_id=x_user_id,
                log_tag=log_tag,
            )
            profile_duration = time.time() - profile_start
            
            Log.info(f"{log_tag} Profile fetch completed in {profile_duration:.2f}s")
            
            # Use screen_name from token exchange if profile fetch failed
            if not profile.get("username"):
                profile["username"] = screen_name
            if not profile.get("x_user_id"):
                profile["x_user_id"] = x_user_id
            
            # Clean up OAuth tokens from Redis
            try:
                remove_redis(f"x_login_token:{oauth_token}")
            except:
                pass
            
            # =========================================
            # 3. CHECK IF USER EXISTS
            # =========================================
            user_col = db.get_collection("users")
            existing_user = user_col.find_one({"x_user_id": x_user_id})
            
            if existing_user:
                # =========================================
                # EXISTING USER - LOG THEM IN
                # =========================================
                Log.info(f"{log_tag} Existing user found by x_user_id, logging in")
                
                business = Business.get_business_by_id(str(existing_user["business_id"]))
                
                if not business:
                    Log.error(f"{log_tag} Business not found for existing user")
                    return jsonify({
                        "success": False,
                        "message": "Account not found. Please contact support.",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
                # Update X info if changed
                update_fields = {
                    "updated_at": datetime.utcnow(),
                }
                
                if profile.get("username") and profile.get("username") != existing_user.get("x_username"):
                    update_fields["x_username"] = profile.get("username")
                
                if update_fields:
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
            
            # Check by X username (fallback)
            existing_user = user_col.find_one({"x_username": screen_name})
            
            if existing_user:
                # =========================================
                # EXISTING USER (by username) - Link X ID and LOG THEM IN
                # =========================================
                Log.info(f"{log_tag} Existing user found by x_username, linking X user ID")
                
                business = Business.get_business_by_id(str(existing_user["business_id"]))
                
                if not business:
                    Log.error(f"{log_tag} Business not found for existing user")
                    return jsonify({
                        "success": False,
                        "message": "Account not found. Please contact support.",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
                # Link X user ID
                user_col.update_one(
                    {"_id": existing_user["_id"]},
                    {"$set": {
                        "x_user_id": x_user_id,
                        "social_login_provider": "x",
                        "updated_at": datetime.utcnow(),
                    }}
                )
                
                business_col = db.get_collection("businesses")
                business_col.update_one(
                    {"_id": ObjectId(business["_id"])},
                    {"$set": {
                        "x_user_id": x_user_id,
                        "social_login_provider": "x",
                        "updated_at": datetime.utcnow(),
                    }}
                )
                
                # Refresh user doc
                existing_user = user_col.find_one({"_id": existing_user["_id"]})
                
                # Get account_type for token generation
                account_type = decrypt_data(existing_user.get("account_type")) if existing_user.get("account_type") else SYSTEM_USERS["BUSINESS_OWNER"]
                
                duration = time.time() - start_time
                Log.info(f"{log_tag} Login with X link successful in {duration:.2f}s")
                
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
            Log.info(f"{log_tag} Creating new account from X profile")
            
            business_id, user_doc = _create_account_from_x(
                profile=profile,
                screen_name=screen_name,
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
                "message": "Failed to complete X login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# SET PASSWORD (for X users)
# =========================================
@blp_x_login.route("/auth/x/set-password", methods=["POST"])
class XSetPasswordResource(MethodView):
    """
    Set a password for users who signed up via X Login.
    
    This allows them to also log in with email/password.
    
    Body:
    {
        "password": "newPassword123"
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
            log_tag = f"[x_login_resource.py][XSetPasswordResource][{client_ip}][{user__id}]"
            
            body = request.get_json(silent=True) or {}
            new_password = body.get("password")
            
            if not new_password:
                return jsonify({
                    "success": False,
                    "message": "Password is required",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            if len(new_password) < 8:
                return jsonify({
                    "success": False,
                    "message": "Password must be at least 8 characters",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            try:
                result = User.update_password(
                    user_id=user__id,
                    business_id=business_id,
                    new_password=new_password,
                )
                
                if result:
                    Log.info(f"{log_tag} Password set successfully")
                    return jsonify({
                        "success": True,
                        "message": "Password set successfully. You can now log in with email and password.",
                    }), HTTP_STATUS_CODES["OK"]
                else:
                    return jsonify({
                        "success": False,
                        "message": "Failed to set password",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            
            except Exception as e:
                Log.error(f"{log_tag} Error: {e}")
                return jsonify({
                    "success": False,
                    "message": "Failed to set password",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        
        return _post()


# =========================================
# UPDATE EMAIL (for X users - required since X doesn't provide email)
# =========================================
@blp_x_login.route("/auth/x/update-email", methods=["POST"])
class XUpdateEmailResource(MethodView):
    """
    Update email for users who signed up via X Login.
    
    X doesn't provide email via OAuth 1.0a, so users need to add their email
    after signing up to receive notifications and for account recovery.
    
    Body:
    {
        "email": "user@example.com"
    }
    """
    
    def post(self):
        from ....resources.doseal.admin.admin_business_resource import token_required
        from ....models.business_model import Business
        
        @token_required
        def _post():
            user = g.get("current_user", {}) or {}
            business_id = str(user.get("business_id", ""))
            user__id = str(user.get("_id", ""))
            
            client_ip = request.remote_addr
            log_tag = f"[x_login_resource.py][XUpdateEmailResource][{client_ip}][{user__id}]"
            
            body = request.get_json(silent=True) or {}
            new_email = body.get("email", "").strip().lower()
            return_url = body.get("return_url", "").strip().lower()
            
            business = Business.get_business_by_id(business_id)
            
            fullname = f"{decrypt_data(business.get("first_name"))} {decrypt_data(business.get("last_name"))}"
            
            
            if not new_email:
                Log.info(f"{log_tag} Email is required")
                return prepared_response(False, "BAD_REQUEST", "Email is required")
            
            if not return_url:
                Log.info(f"{log_tag} return_url is required")
                return prepared_response(False, "BAD_REQUEST", "Return URL is required")
            
            # Basic email validation
            import re
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_pattern, new_email):
                Log.info(f"{log_tag} Please provide a valid email address")
                return prepared_response(False, "BAD_REQUEST", "Please provide a valid email address")
            
            # Check if email is a placeholder
            if "@x.placeholder.doseal.com" in new_email:
                Log.info(f"{log_tag} Please provide a valid email address")
                return prepared_response(False, "BAD_REQUEST", "Please provide a valid email address")
            
            try:
                # Check if email is already taken
                existing_business = Business.get_business_by_email(new_email)
                if existing_business and str(existing_business.get("_id")) != business_id:
                    Log.info(f"{log_tag} This email is already associated with another account")
                    return prepared_response(False, "CONFLICT", "Please provide a valid email address")
                
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
                
                # # Update business email
                business_col = db.get_collection("businesses")
                business_col.update_one(
                    {"_id": ObjectId(business_id)},
                    {"$set": {
                        "email": encrypt_data(new_email),
                        "return_url": encrypt_data(return_url),
                        "hashed_email": hash_data(new_email),
                        "email_needs_verification": False,
                        "updated_at": datetime.utcnow(),
                    }}
                )
                
                try:
                    token = secrets.token_urlsafe(32)
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
                
                Log.info(f"{log_tag} Email updated successfully. Please check your inbox to verify your email.")
                return prepared_response(False, "OK", "Email updated successfully. Please check your inbox to verify your email.")
            
            except Exception as e:
                Log.error(f"{log_tag} Error: {e}")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to update email")
        
        return _post()

