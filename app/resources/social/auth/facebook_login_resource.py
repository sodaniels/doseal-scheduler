# app/routes/auth/facebook_login_resource.py

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
from ....extensions.redis_conn import redis_client
from ....extensions.db import db

# models
from ....models.business_model import Business, Client
from ....models.user_model import User
from ....models.admin.subscription_model import Subscription
from ....models.notifications.notification_settings import NotificationSettings

# services
from ....services.seeders.social_role_seeder import SocialRoleSeeder


blp_facebook_login = Blueprint("facebook_login", __name__)


# =========================================
# CONSTANTS
# =========================================
FACEBOOK_API_VERSION = "v20.0"
FACEBOOK_GRAPH_URL = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}"

# Scopes for login only (minimal - just authentication)
FACEBOOK_LOGIN_SCOPES = [
    "email",
    "public_profile",
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "read_insights",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_insights",
]

# Additional scopes if ads access is needed
FACEBOOK_ADS_SCOPES = [
    "ads_management",
    "ads_read",
    "business_management",
]


# =========================================
# HELPER: Check if user has active subscription
# =========================================
def _has_active_subscription(business_id: str, log_tag: str) -> bool:
    """
    Check if the business has an active subscription using Subscription model.
    
    Returns True if subscription status is Active or Trial.
    """
    try:
        # Use the Subscription model's get_active_by_business method
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
    
    Returns normalized subscription data or None.
    """
    try:
        # Use the Subscription model's get_active_by_business method
        # This returns a normalized dict with decrypted fields
        active_sub = Subscription.get_active_by_business(business_id)
        
        if active_sub:
            return {
                "subscription_id": active_sub.get("_id"),
                "status": active_sub.get("status"),  # Already decrypted by model
                "package_id": active_sub.get("package_id"),
                "billing_period": active_sub.get("billing_period"),  # Already decrypted
                "currency": active_sub.get("currency"),  # Already decrypted
                "price_paid": active_sub.get("price_paid"),  # Already decrypted to float
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
    Useful for showing subscription history or expired status.
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
# HELPER: Exchange code for token
# =========================================
def _exchange_code_for_token(code: str, redirect_uri: str, log_tag: str) -> dict:
    """Exchange authorization code for access token."""
    import requests
    
    app_id = os.getenv("META_APP_ID") or os.getenv("FACEBOOK_APP_ID")
    app_secret = os.getenv("META_APP_SECRET") or os.getenv("FACEBOOK_APP_SECRET")
    
    if not app_id or not app_secret:
        raise ValueError("META_APP_ID and META_APP_SECRET must be set")
    
    token_url = f"{FACEBOOK_GRAPH_URL}/oauth/access_token"
    params = {
        "client_id": app_id,
        "client_secret": app_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    
    response = requests.get(token_url, params=params, timeout=30)
    
    if response.status_code != 200:
        Log.error(f"{log_tag} Token exchange failed: {response.text}")
        raise ValueError(f"Token exchange failed: {response.text}")
    
    token_data = response.json()
    short_lived_token = token_data.get("access_token")
    
    if not short_lived_token:
        raise ValueError("No access_token in response")
    
    # Exchange for long-lived token
    ll_params = {
        "grant_type": "fb_exchange_token",
        "client_id": app_id,
        "client_secret": app_secret,
        "fb_exchange_token": short_lived_token,
    }
    
    ll_response = requests.get(token_url, params=ll_params, timeout=30)
    
    if ll_response.status_code == 200:
        ll_data = ll_response.json()
        return {
            "access_token": ll_data.get("access_token", short_lived_token),
            "expires_in": ll_data.get("expires_in", 5184000),
            "token_type": "bearer",
        }
    else:
        Log.info(f"{log_tag} Long-lived token exchange failed, using short-lived")
        return {
            "access_token": short_lived_token,
            "expires_in": token_data.get("expires_in", 3600),
            "token_type": "bearer",
        }


# =========================================
# HELPER: Get Facebook user profile
# =========================================
def _get_facebook_user_profile(access_token: str, log_tag: str) -> dict:
    """Get user profile from Facebook."""
    import requests
    
    response = requests.get(
        f"{FACEBOOK_GRAPH_URL}/me",
        params={
            "access_token": access_token,
            "fields": "id,name,email,first_name,last_name,picture.width(200).height(200)",
        },
        timeout=30,
    )
    
    if response.status_code != 200:
        Log.error(f"{log_tag} Failed to get user profile: {response.text}")
        raise ValueError(f"Failed to get user profile: {response.text}")
    
    data = response.json()
    
    return {
        "facebook_user_id": data.get("id"),
        "email": data.get("email"),
        "name": data.get("name"),
        "first_name": data.get("first_name"),
        "last_name": data.get("last_name"),
        "profile_picture": data.get("picture", {}).get("data", {}).get("url"),
    }


# =========================================
# HELPER: Create Business and User
# =========================================
def _create_account_from_facebook(
    profile: dict,
    log_tag: str,
) -> Tuple[dict, dict]:
    """
    Create a new business and user account from Facebook profile.
    
    This mirrors your existing registration flow:
    1. Create Business
    2. Create User
    3. Seed NotificationSettings
    4. Seed SocialRoles
    5. Create Client
    
    NOTE: Pages are NOT connected here. User must:
    1. Subscribe to a package
    2. Then connect pages via /social/oauth/facebook/start
    
    Returns: (business_doc, user_doc)
    """
    
    email = profile.get("email")
    name = profile.get("name") or f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
    first_name = profile.get("first_name") or (name.split(" ")[0] if name else "")
    last_name = profile.get("last_name") or (name.split(" ", 1)[1] if " " in name else "")
    
    if not name:
        name = email.split("@")[0] if email else "User"
    
    # Generate a random password (user can set it later)
    random_password = secrets.token_urlsafe(16)
    hashed_password = bcrypt.hashpw(
        random_password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")
    
    # Generate tenant_id and client_id
    tenant_id = str(ObjectId())
    client_id_plain = generate_client_id()
    
    # Account status - NOT subscribed yet
    account_status = [
        {
            "account_created": {
                "created_at": str(datetime.utcnow()),
                "status": True,
            },
        },
        {
            "business_email_verified": {
                "status": True,  # Verified via Facebook
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
    Log.info(f"{log_tag} Creating business for {email}")
    
    business_col = db.get_collection("businesses")
    
    business_doc = {
        "tenant_id": encrypt_data(tenant_id),
        "business_name": encrypt_data(name),
        "first_name": encrypt_data(first_name),
        "last_name": encrypt_data(last_name),
        "email": encrypt_data(email),
        "hashed_email": hash_data(email),
        "password": hashed_password,
        "client_id": encrypt_data(client_id_plain),
        "client_id_hashed": hash_data(client_id_plain),
        "status": encrypt_data("Active"),
        "hashed_status": hash_data("Active"),
        "account_status": encrypt_data(account_status),
        "account_type": encrypt_data(account_type),
        "image": profile.get("profile_picture"),
        "facebook_user_id": profile.get("facebook_user_id"),
        "social_login_provider": "facebook",
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    
    business_result = business_col.insert_one(business_doc)
    business_id = business_result.inserted_id
    Log.info(f"{log_tag} Business created: {business_id}")
    
    # =========================================
    # 2. CREATE USER
    # =========================================
    Log.info(f"{log_tag} Creating user for {email}")
    
    user_col = db.get_collection("users")
    
    user_doc = {
        "business_id": business_id,
        "tenant_id": encrypt_data(tenant_id),
        "fullname": encrypt_data(name),
        "hashed_fullname": hash_data(name),
        "email": encrypt_data(email),
        "email_hashed": hash_data(email),
        "phone_number": None,
        "password": hashed_password,
        "client_id": encrypt_data(client_id_plain),
        "client_id_hashed": hash_data(client_id_plain),
        "status": encrypt_data("Active"),
        "account_type": encrypt_data(account_type),
        "email_verified": "verified",
        "facebook_user_id": profile.get("facebook_user_id"),
        "social_login_provider": "facebook",
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
            admin_email=email,
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
        f"fb_login_state:{state}",
        ttl_seconds,
        json.dumps(data),
    )


def _consume_login_state(state: str) -> Optional[dict]:
    """Retrieve and delete OAuth state from Redis."""
    key = f"fb_login_state:{state}"
    raw = redis_client.get(key)
    if not raw:
        return None
    redis_client.delete(key)
    try:
        return json.loads(raw)
    except:
        return None


# =========================================
# INITIATE FACEBOOK LOGIN
# =========================================
@blp_facebook_login.route("/auth/facebook/business/login", methods=["GET"])
class FacebookLoginStartResource(MethodView):
    """
    Initiate Facebook Login OAuth flow.
    
    This is for AUTHENTICATION ONLY - not for connecting pages.
    Pages should be connected via /social/oauth/facebook/start AFTER subscription.
    
    Query params:
    - return_url: Where to redirect after auth (default: FRONTEND_URL)
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_login_resource.py][FacebookLoginStartResource][get][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Initiating Facebook login")
        
        try:
            app_id = os.getenv("META_APP_ID") or os.getenv("FACEBOOK_APP_ID")
            redirect_uri = os.getenv("FACEBOOK_LOGIN_REDIRECT_URI") or os.getenv("FACEBOOK_REDIRECT_URI")
            
            if not app_id or not redirect_uri:
                Log.error(f"{log_tag} Missing META_APP_ID or FACEBOOK_LOGIN_REDIRECT_URI")
                return jsonify({
                    "success": False,
                    "message": "Server OAuth configuration missing",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            
            return_url = request.args.get("return_url", os.getenv("FRONTEND_URL", "/"))
            
            # Generate state for CSRF protection
            state = secrets.token_urlsafe(24)
            
            # Store state in Redis
            _store_login_state(state, {
                "return_url": return_url,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            
            # Build authorization URL - ONLY login scopes (no page permissions)
            params = {
                "client_id": app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "response_type": "code",
                "scope": ",".join(FACEBOOK_LOGIN_SCOPES),
            }
            
            auth_url = f"https://www.facebook.com/{FACEBOOK_API_VERSION}/dialog/oauth?" + urlencode(params)
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Redirecting to Facebook in {duration:.2f}s")
            
            return redirect(auth_url)
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to initiate Facebook login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# FACEBOOK LOGIN CALLBACK
# =========================================
@blp_facebook_login.route("/auth/facebook/business/callback", methods=["GET"])
class FacebookLoginCallbackResource(MethodView):
    """
    Handle Facebook Login OAuth callback.
    
    This endpoint ONLY handles authentication:
    1. Exchanges code for access token
    2. Gets user profile from Facebook
    3. Creates account OR logs in existing user
    4. Returns JWT tokens
    
    NOTE: Pages are NOT connected here. After login:
    - If no subscription: User should be redirected to pricing
    - If has subscription: User can connect pages via /social/oauth/facebook/start
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_login_resource.py][FacebookLoginCallbackResource][get][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Processing Facebook login callback")
        
        # Get parameters
        code = request.args.get("code")
        state = request.args.get("state")
        error = request.args.get("error")
        error_description = request.args.get("error_description")
        
        # Handle errors from Facebook
        if error:
            Log.info(f"{log_tag} Facebook returned error: {error_description}")
            return jsonify({
                "success": False,
                "message": f"Facebook authentication failed: {error_description}",
                "code": "FACEBOOK_ERROR",
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
            # Verify state
            state_data = _consume_login_state(state)
            
            if not state_data:
                Log.info(f"{log_tag} Invalid or expired state")
                return jsonify({
                    "success": False,
                    "message": "Invalid or expired state. Please try again.",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            return_url = state_data.get("return_url", "/")
            
            # Get redirect URI
            redirect_uri = os.getenv("FACEBOOK_LOGIN_REDIRECT_URI") or os.getenv("FACEBOOK_REDIRECT_URI")
            
            # =========================================
            # 1. EXCHANGE CODE FOR TOKEN
            # =========================================
            Log.info(f"{log_tag} Exchanging code for token...")
            
            token_start = time.time()
            token_data = _exchange_code_for_token(code, redirect_uri, log_tag)
            access_token = token_data["access_token"]
            token_duration = time.time() - token_start
            
            Log.info(f"{log_tag} Token exchange completed in {token_duration:.2f}s")
            
            # =========================================
            # 2. GET USER PROFILE
            # =========================================
            Log.info(f"{log_tag} Getting user profile...")
            
            profile_start = time.time()
            profile = _get_facebook_user_profile(access_token, log_tag)
            profile_duration = time.time() - profile_start
            
            Log.info(f"{log_tag} Profile fetch completed in {profile_duration:.2f}s")
            
            facebook_user_id = profile.get("facebook_user_id")
            email = profile.get("email")
            
            Log.info(f"{log_tag} Got profile: facebook_user_id={facebook_user_id}, email={email}")
            
            if not email:
                Log.info(f"{log_tag} Email not provided by Facebook")
                return jsonify({
                    "success": False,
                    "message": "Email is required but Facebook did not provide it. Please update your Facebook privacy settings to share your email, or use a different login method.",
                    "code": "EMAIL_REQUIRED",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # =========================================
            # 3. CHECK IF USER EXISTS
            # =========================================
            user_col = db.get_collection("users")
            existing_user = user_col.find_one({"facebook_user_id": facebook_user_id})
            
            if existing_user:
                # =========================================
                # EXISTING USER (by Facebook ID) - LOG THEM IN
                # =========================================
                Log.info(f"{log_tag} Existing user found by facebook_user_id, logging in")
                
                business = Business.get_business_by_id(str(existing_user["business_id"]))
                
                if not business:
                    Log.error(f"{log_tag} Business not found for existing user")
                    return jsonify({
                        "success": False,
                        "message": "Account not found. Please contact support.",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
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
            
            # Check by email
            existing_business = Business.get_business_by_email(email)
            
            if existing_business:
                # =========================================
                # EXISTING USER (by email) - Link Facebook and LOG THEM IN
                # =========================================
                Log.info(f"{log_tag} Existing business found by email, linking Facebook account")
                
                existing_user = User.get_user_by_email(email)
                
                if not existing_user:
                    Log.error(f"{log_tag} User not found for existing business")
                    return jsonify({
                        "success": False,
                        "message": "Account configuration error. Please contact support.",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
                # Link Facebook user ID to existing account
                user_col.update_one(
                    {"_id": existing_user["_id"]},
                    {"$set": {
                        "facebook_user_id": facebook_user_id,
                        "social_login_provider": "facebook",
                        "updated_at": datetime.utcnow(),
                    }}
                )
                
                business_col = db.get_collection("businesses")
                business_col.update_one(
                    {"_id": ObjectId(existing_business["_id"])},
                    {"$set": {
                        "facebook_user_id": facebook_user_id,
                        "social_login_provider": "facebook",
                        "updated_at": datetime.utcnow(),
                    }}
                )
                
                # Refresh user doc to get updated fields
                existing_user = user_col.find_one({"_id": existing_user["_id"]})
                
                # Get account_type for token generation
                account_type = decrypt_data(existing_user.get("account_type")) if existing_user.get("account_type") else SYSTEM_USERS["BUSINESS_OWNER"]
                
                duration = time.time() - start_time
                Log.info(f"{log_tag} Login with Facebook link successful in {duration:.2f}s")
                
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
            Log.info(f"{log_tag} Creating new account from Facebook profile")
            
            business_doc, user_doc = _create_account_from_facebook(
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
                "message": "Failed to complete Facebook login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# SET PASSWORD (for Facebook users)
# =========================================
@blp_facebook_login.route("/auth/set-password", methods=["POST"])
class SetPasswordResource(MethodView):
    """
    Set a password for users who signed up via Facebook Login.
    
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
            log_tag = f"[facebook_login_resource.py][SetPasswordResource][{client_ip}][{user__id}]"
            
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
# CHECK ACCOUNT STATUS (login methods + subscription)
# =========================================
@blp_facebook_login.route("/auth/account-status", methods=["GET"])
class AccountStatusResource(MethodView):
    """
    Get account status including login methods and subscription status.
    
    Uses the Subscription model to check subscription status.
    
    Returns:
    {
        "success": true,
        "data": {
            "login_methods": {
                "email_password": true,
                "facebook": true,
                "registered_via": "facebook",
                "can_set_password": true
            },
            "subscription": {
                "has_active_subscription": true,
                "subscription_id": "...",
                "status": "Active",  // or "Trial"
                "package_id": "...",
                "billing_period": "monthly",
                "currency": "USD",
                "price_paid": 29.99,
                "start_date": "2025-01-01T00:00:00",
                "end_date": "2025-02-01T00:00:00",
                "trial_end_date": null,
                "auto_renew": true,
                "term_number": 1
            },
            "can_connect_social_accounts": true
        }
    }
    """
    
    def get(self):
        from ....resources.doseal.admin.admin_business_resource import token_required
        
        @token_required
        def _get():
            user = g.get("current_user", {}) or {}
            business_id = str(user.get("business_id", ""))
            user__id = str(user.get("_id", ""))
            
            client_ip = request.remote_addr
            log_tag = f"[facebook_login_resource.py][AccountStatusResource][{client_ip}][{business_id}]"
            
            # Get full user document
            user_doc = User.get_by_id(user__id, business_id)
            
            if not user_doc:
                return jsonify({
                    "success": False,
                    "message": "User not found",
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            # =========================================
            # LOGIN METHODS
            # =========================================
            has_facebook = bool(user_doc.get("facebook_user_id"))
            social_provider = user_doc.get("social_login_provider")
            has_password = bool(user_doc.get("password"))
            registered_via_social = social_provider in ["facebook", "google", "apple"]
            
            # =========================================
            # SUBSCRIPTION STATUS (using Subscription model)
            # =========================================
            has_subscription = _has_active_subscription(business_id, log_tag)
            subscription_details = _get_subscription_details(business_id, log_tag)
            
            # If no active subscription, get latest to show status
            latest_subscription = None
            if not has_subscription:
                latest_subscription = _get_latest_subscription(business_id, log_tag)
            
            # Build subscription response
            subscription_response = {
                "has_active_subscription": has_subscription,
            }
            
             # =========================================
            #BUSINESS DETAILS
            # =========================================
            account_status = None
            business = Business.get_business_by_id(business_id)
            if business:
                account_status = decrypt_data(business.get("account_status"))
            
            if subscription_details:
                subscription_response.update(subscription_details)
            elif latest_subscription:
                # Show latest subscription info even if not active
                subscription_response["latest_subscription"] = latest_subscription
            
            return jsonify({
                "success": True,
                "data": {
                    "login_methods": {
                        "email_password": has_password,
                        "facebook": has_facebook,
                        "registered_via": social_provider or "email",
                        "can_set_password": registered_via_social,
                    },
                    "subscription": subscription_response,
                    "can_connect_social_accounts": has_subscription,
                    "account": account_status
                },
            }), HTTP_STATUS_CODES["OK"]
        
        return _get()


# =========================================
# CHECK LOGIN METHODS (backward compatibility)
# =========================================
@blp_facebook_login.route("/auth/login-methods", methods=["GET"])
class LoginMethodsResource(MethodView):
    """
    Get available login methods for the current user.
    
    Uses the Subscription model to check subscription status.
    
    Returns:
    {
        "success": true,
        "data": {
            "email_password": true,
            "facebook": true,
            "registered_via": "facebook",
            "can_set_password": true,
            "has_subscription": true,
            "subscription_status": "Active",
            "can_connect_social_accounts": true
        }
    }
    """
    
    def get(self):
        from ....resources.doseal.admin.admin_business_resource import token_required
        
        @token_required
        def _get():
            user = g.get("current_user", {}) or {}
            business_id = str(user.get("business_id", ""))
            user__id = str(user.get("_id", ""))
            
            client_ip = request.remote_addr
            log_tag = f"[facebook_login_resource.py][LoginMethodsResource][{client_ip}][{business_id}]"
            
            user_doc = User.get_by_id(user__id, business_id)
            
            if not user_doc:
                return jsonify({
                    "success": False,
                    "message": "User not found",
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            # Login methods
            has_facebook = bool(user_doc.get("facebook_user_id"))
            social_provider = user_doc.get("social_login_provider")
            has_password = bool(user_doc.get("password"))
            registered_via_social = social_provider in ["facebook", "google", "apple"]
            
            # Subscription check using Subscription model
            has_subscription = _has_active_subscription(business_id, log_tag)
            subscription_details = _get_subscription_details(business_id, log_tag)
            subscription_status = subscription_details.get("status") if subscription_details else None
            
            return jsonify({
                "success": True,
                "data": {
                    "email_password": has_password,
                    "facebook": has_facebook,
                    "registered_via": social_provider or "email",
                    "can_set_password": registered_via_social,
                    "has_subscription": has_subscription,
                    "subscription_status": subscription_status,
                    "can_connect_social_accounts": has_subscription,
                },
            }), HTTP_STATUS_CODES["OK"]
        
        return _get()