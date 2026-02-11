# app/routes/auth/instagram_login_resource.py

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


blp_instagram_login = Blueprint("instagram_login", __name__)


# =========================================
# CONSTANTS
# =========================================
# Instagram uses Facebook's OAuth but with Instagram-specific endpoints
INSTAGRAM_API_VERSION = "v20.0"
FACEBOOK_GRAPH_URL = f"https://graph.facebook.com/{INSTAGRAM_API_VERSION}"

# Instagram Basic Display API scopes (for personal accounts)
# Note: For Instagram Business/Creator accounts, you need to use Facebook Login
# and request instagram_basic, instagram_content_publish, etc.

# Scopes for Instagram login via Facebook OAuth
# This allows login + future Instagram business account connection
INSTAGRAM_LOGIN_SCOPES = [
    "email",
    "public_profile",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_insights",
    "pages_show_list",
    "pages_read_engagement",
]

# Additional scopes if ads access is needed
INSTAGRAM_ADS_SCOPES = [
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
# HELPER: Exchange code for token (via Facebook OAuth)
# =========================================
def _exchange_code_for_token(code: str, redirect_uri: str, log_tag: str) -> dict:
    """
    Exchange authorization code for access token.
    Instagram Business/Creator accounts use Facebook's OAuth system.
    """
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
# HELPER: Get user profile from Facebook (includes Instagram info)
# =========================================
def _get_user_profile(access_token: str, log_tag: str) -> dict:
    """
    Get user profile from Facebook.
    For Instagram login, we still use Facebook's /me endpoint
    since Instagram Business accounts are linked to Facebook.
    """
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
# HELPER: Get Instagram Business Accounts
# =========================================
def _get_instagram_accounts(access_token: str, log_tag: str) -> list:
    """
    Get Instagram Business/Creator accounts linked to Facebook Pages.
    
    Instagram Business accounts must be linked to a Facebook Page.
    This fetches all pages and their linked Instagram accounts.
    """
    import requests
    
    # First, get all Facebook Pages the user manages
    response = requests.get(
        f"{FACEBOOK_GRAPH_URL}/me/accounts",
        params={
            "access_token": access_token,
            "fields": "id,name,instagram_business_account{id,username,profile_picture_url,followers_count,name}",
        },
        timeout=30,
    )
    
    if response.status_code != 200:
        Log.info(f"{log_tag} Failed to get pages/Instagram accounts: {response.text}")
        return []
    
    data = response.json()
    pages = data.get("data", [])
    
    instagram_accounts = []
    for page in pages:
        ig_account = page.get("instagram_business_account")
        if ig_account:
            instagram_accounts.append({
                "instagram_id": ig_account.get("id"),
                "username": ig_account.get("username"),
                "name": ig_account.get("name"),
                "profile_picture": ig_account.get("profile_picture_url"),
                "followers_count": ig_account.get("followers_count"),
                "linked_page_id": page.get("id"),
                "linked_page_name": page.get("name"),
            })
    
    return instagram_accounts


# =========================================
# HELPER: Create Business and User
# =========================================
def _create_account_from_instagram(
    profile: dict,
    instagram_accounts: list,
    log_tag: str,
) -> Tuple[ObjectId, dict]:
    """
    Create a new business and user account from Instagram/Facebook profile.
    
    This mirrors your existing registration flow:
    1. Create Business
    2. Create User
    3. Seed NotificationSettings
    4. Seed SocialRoles
    5. Create Client
    
    NOTE: Instagram accounts are NOT connected here. User must:
    1. Subscribe to a package
    2. Then connect Instagram via /social/oauth/instagram/start
    
    Returns: (business_id, user_doc)
    """
    
    email = profile.get("email")
    name = profile.get("name") or f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
    first_name = profile.get("first_name") or (name.split(" ")[0] if name else "")
    last_name = profile.get("last_name") or (name.split(" ", 1)[1] if " " in name else "")
    
    # If we have Instagram accounts, use the first one's info as fallback
    if not name and instagram_accounts:
        name = instagram_accounts[0].get("name") or instagram_accounts[0].get("username")
    
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
                "status": True,  # Verified via Instagram/Facebook
            }
        },
        {
            "subscribed_to_package": {
                "status": False,  # NOT subscribed - needs to choose package
            }
        }
    ]
    
    account_type = SYSTEM_USERS["BUSINESS_OWNER"]
    
    # Get profile picture - prefer Instagram if available
    profile_picture = profile.get("profile_picture")
    if instagram_accounts and instagram_accounts[0].get("profile_picture"):
        profile_picture = instagram_accounts[0].get("profile_picture")
    
    # Get primary Instagram username for reference
    primary_instagram_username = None
    primary_instagram_id = None
    if instagram_accounts:
        primary_instagram_username = instagram_accounts[0].get("username")
        primary_instagram_id = instagram_accounts[0].get("instagram_id")
    
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
        "image": profile_picture,
        "facebook_user_id": profile.get("facebook_user_id"),
        "instagram_user_id": primary_instagram_id,
        "instagram_username": primary_instagram_username,
        "social_login_provider": "instagram",
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
        "instagram_user_id": primary_instagram_id,
        "instagram_username": primary_instagram_username,
        "social_login_provider": "instagram",
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
        f"ig_login_state:{state}",
        ttl_seconds,
        json.dumps(data),
    )


def _consume_login_state(state: str) -> Optional[dict]:
    """Retrieve and delete OAuth state from Redis."""
    key = f"ig_login_state:{state}"
    raw = redis_client.get(key)
    if not raw:
        return None
    redis_client.delete(key)
    try:
        return json.loads(raw)
    except:
        return None


# =========================================
# INITIATE INSTAGRAM LOGIN
# =========================================
@blp_instagram_login.route("/auth/instagram/business/login", methods=["GET"])
class InstagramLoginStartResource(MethodView):
    """
    Initiate Instagram Login OAuth flow.
    
    Instagram Business/Creator accounts use Facebook's OAuth system.
    This is for AUTHENTICATION ONLY - not for connecting Instagram accounts.
    
    After login, users must:
    1. Subscribe to a package
    2. Connect Instagram accounts via /social/oauth/instagram/start
    
    Query params:
    - return_url: Where to redirect after auth (default: FRONTEND_URL)
    - include_ads: Include ads management scopes (true/false)
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[instagram_login_resource.py][InstagramLoginStartResource][get][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Initiating Instagram login")
        
        try:
            app_id = os.getenv("META_APP_ID") or os.getenv("FACEBOOK_APP_ID")
            redirect_uri = os.getenv("INSTAGRAM_LOGIN_REDIRECT_URI") or os.getenv("INSTAGRAM_REDIRECT_URI")
            
            if not app_id or not redirect_uri:
                Log.error(f"{log_tag} Missing META_APP_ID or INSTAGRAM_LOGIN_REDIRECT_URI")
                return jsonify({
                    "success": False,
                    "message": "Server OAuth configuration missing",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            
            return_url = request.args.get("return_url", os.getenv("FRONTEND_URL", "/"))
            include_ads = request.args.get("include_ads", "false").lower() == "true"
            
            # Generate state for CSRF protection
            state = secrets.token_urlsafe(24)
            
            # Store state in Redis
            _store_login_state(state, {
                "return_url": return_url,
                "include_ads": include_ads,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            
            # Build scopes
            scopes = INSTAGRAM_LOGIN_SCOPES.copy()
            if include_ads:
                scopes.extend(INSTAGRAM_ADS_SCOPES)
            
            # Build authorization URL (using Facebook OAuth)
            params = {
                "client_id": app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "response_type": "code",
                "scope": ",".join(scopes),
            }
            
            # Instagram Business accounts use Facebook's OAuth dialog
            auth_url = f"https://www.facebook.com/{INSTAGRAM_API_VERSION}/dialog/oauth?" + urlencode(params)
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Redirecting to Facebook/Instagram OAuth in {duration:.2f}s")
            
            return redirect(auth_url)
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to initiate Instagram login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# INSTAGRAM LOGIN CALLBACK
# =========================================
@blp_instagram_login.route("/auth/instagram/business/callback", methods=["GET"])
class InstagramLoginCallbackResource(MethodView):
    """
    Handle Instagram Login OAuth callback.
    
    This endpoint ONLY handles authentication:
    1. Exchanges code for access token
    2. Gets user profile from Facebook (Instagram uses Facebook OAuth)
    3. Gets linked Instagram Business accounts (for display/info only)
    4. Creates account OR logs in existing user
    5. Returns JWT tokens
    
    NOTE: Instagram accounts are NOT connected here. After login:
    - If no subscription: User should be redirected to pricing
    - If has subscription: User can connect Instagram via /social/oauth/instagram/start
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[instagram_login_resource.py][InstagramLoginCallbackResource][get][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Processing Instagram login callback")
        
        # Get parameters
        code = request.args.get("code")
        state = request.args.get("state")
        error = request.args.get("error")
        error_description = request.args.get("error_description")
        
        # Handle errors from Facebook/Instagram
        if error:
            Log.info(f"{log_tag} Instagram returned error: {error_description}")
            return jsonify({
                "success": False,
                "message": f"Instagram authentication failed: {error_description}",
                "code": "INSTAGRAM_ERROR",
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
            redirect_uri = os.getenv("INSTAGRAM_LOGIN_REDIRECT_URI") or os.getenv("INSTAGRAM_REDIRECT_URI")
            
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
            # 2. GET USER PROFILE (from Facebook)
            # =========================================
            Log.info(f"{log_tag} Getting user profile...")
            
            profile_start = time.time()
            profile = _get_user_profile(access_token, log_tag)
            profile_duration = time.time() - profile_start
            
            Log.info(f"{log_tag} Profile fetch completed in {profile_duration:.2f}s")
            
            facebook_user_id = profile.get("facebook_user_id")
            email = profile.get("email")
            
            Log.info(f"{log_tag} Got profile: facebook_user_id={facebook_user_id}, email={email}")
            
            # =========================================
            # 3. GET INSTAGRAM ACCOUNTS (for info only)
            # =========================================
            Log.info(f"{log_tag} Getting Instagram accounts...")
            
            ig_start = time.time()
            instagram_accounts = _get_instagram_accounts(access_token, log_tag)
            ig_duration = time.time() - ig_start
            
            Log.info(f"{log_tag} Found {len(instagram_accounts)} Instagram accounts in {ig_duration:.2f}s")
            
            # If no email from Facebook but we have Instagram, we still need email
            if not email:
                Log.info(f"{log_tag} Email not provided by Facebook/Instagram")
                return jsonify({
                    "success": False,
                    "message": "Email is required but was not provided. Please update your Facebook privacy settings to share your email, or use a different login method.",
                    "code": "EMAIL_REQUIRED",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # =========================================
            # 4. CHECK IF USER EXISTS
            # =========================================
            user_col = db.get_collection("users")
            
            # First check by Facebook user ID (since Instagram uses Facebook OAuth)
            existing_user = user_col.find_one({"facebook_user_id": facebook_user_id})
            
            # Also check by Instagram user ID if we have one
            if not existing_user and instagram_accounts:
                primary_ig_id = instagram_accounts[0].get("instagram_id")
                if primary_ig_id:
                    existing_user = user_col.find_one({"instagram_user_id": primary_ig_id})
            
            if existing_user:
                # =========================================
                # EXISTING USER - LOG THEM IN
                # =========================================
                Log.info(f"{log_tag} Existing user found, logging in")
                
                business = Business.get_business_by_id(str(existing_user["business_id"]))
                
                if not business:
                    Log.error(f"{log_tag} Business not found for existing user")
                    return jsonify({
                        "success": False,
                        "message": "Account not found. Please contact support.",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
                # Update Instagram info if we have new data
                update_fields = {
                    "updated_at": datetime.utcnow(),
                }
                
                if instagram_accounts:
                    primary_ig = instagram_accounts[0]
                    if not existing_user.get("instagram_user_id"):
                        update_fields["instagram_user_id"] = primary_ig.get("instagram_id")
                        update_fields["instagram_username"] = primary_ig.get("username")
                
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
            
            # Check by email
            existing_business = Business.get_business_by_email(email)
            
            if existing_business:
                # =========================================
                # EXISTING USER (by email) - Link Instagram and LOG THEM IN
                # =========================================
                Log.info(f"{log_tag} Existing business found by email, linking Instagram account")
                
                existing_user = User.get_user_by_email(email)
                
                if not existing_user:
                    Log.error(f"{log_tag} User not found for existing business")
                    return jsonify({
                        "success": False,
                        "message": "Account configuration error. Please contact support.",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
                # Link Facebook/Instagram IDs to existing account
                update_fields = {
                    "facebook_user_id": facebook_user_id,
                    "social_login_provider": "instagram",
                    "updated_at": datetime.utcnow(),
                }
                
                if instagram_accounts:
                    primary_ig = instagram_accounts[0]
                    update_fields["instagram_user_id"] = primary_ig.get("instagram_id")
                    update_fields["instagram_username"] = primary_ig.get("username")
                
                user_col.update_one(
                    {"_id": existing_user["_id"]},
                    {"$set": update_fields}
                )
                
                business_col = db.get_collection("businesses")
                business_update = {
                    "facebook_user_id": facebook_user_id,
                    "social_login_provider": "instagram",
                    "updated_at": datetime.utcnow(),
                }
                
                if instagram_accounts:
                    primary_ig = instagram_accounts[0]
                    business_update["instagram_user_id"] = primary_ig.get("instagram_id")
                    business_update["instagram_username"] = primary_ig.get("username")
                
                business_col.update_one(
                    {"_id": ObjectId(existing_business["_id"])},
                    {"$set": business_update}
                )
                
                # Refresh user doc to get updated fields
                existing_user = user_col.find_one({"_id": existing_user["_id"]})
                
                # Get account_type for token generation
                account_type = decrypt_data(existing_user.get("account_type")) if existing_user.get("account_type") else SYSTEM_USERS["BUSINESS_OWNER"]
                
                duration = time.time() - start_time
                Log.info(f"{log_tag} Login with Instagram link successful in {duration:.2f}s")
                
                # Return token
                return create_token_response_admin(
                    user=existing_user,
                    account_type=account_type,
                    client_ip=client_ip,
                    log_tag=log_tag,
                )
            
            # =========================================
            # 5. NEW USER - Create account
            # =========================================
            Log.info(f"{log_tag} Creating new account from Instagram profile")
            
            business_id, user_doc = _create_account_from_instagram(
                profile=profile,
                instagram_accounts=instagram_accounts,
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
                "message": "Failed to complete Instagram login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
