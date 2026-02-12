# app/routes/auth/youtube_login_resource.py

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


blp_youtube_login = Blueprint("youtube_login", __name__)


# =========================================
# CONSTANTS
# =========================================
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# Google OAuth 2.0 scopes for login (using Google account, not YouTube specific)
# These are minimal scopes for authentication
YOUTUBE_LOGIN_SCOPES = [
    "openid",
    "email",
    "profile",
]

# Additional scopes for YouTube access (used when connecting YouTube channel, not for login)
YOUTUBE_CHANNEL_SCOPES = [
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
]


# =========================================
# HELPER: Exchange code for token
# =========================================
def _exchange_code_for_token(code: str, redirect_uri: str, log_tag: str) -> dict:
    """
    Exchange authorization code for access token using Google OAuth 2.0.
    """
    import requests
    
    client_id = os.getenv("YOUTUBE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET")
    
    if not client_id or not client_secret:
        raise ValueError("YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set")
    
    token_data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
    }
    
    response = requests.post(
        GOOGLE_TOKEN_URL,
        data=token_data,
        headers=headers,
        timeout=30,
    )
    
    if response.status_code != 200:
        Log.error(f"{log_tag} Token exchange failed: {response.text}")
        raise ValueError(f"Token exchange failed: {response.text}")
    
    token_response = response.json()
    access_token = token_response.get("access_token")
    
    if not access_token:
        raise ValueError("No access_token in response")
    
    return {
        "access_token": access_token,
        "expires_in": token_response.get("expires_in", 3600),
        "refresh_token": token_response.get("refresh_token"),
        "scope": token_response.get("scope"),
        "token_type": token_response.get("token_type", "Bearer"),
        "id_token": token_response.get("id_token"),
    }


# =========================================
# HELPER: Get Google user profile
# =========================================
def _get_google_user_profile(access_token: str, log_tag: str) -> dict:
    """
    Get user profile from Google using the userinfo endpoint.
    
    This endpoint provides: sub (Google ID), name, given_name, family_name, 
    picture, email, email_verified, locale.
    """
    import requests
    
    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    
    response = requests.get(
        GOOGLE_USERINFO_URL,
        headers=headers,
        timeout=30,
    )
    
    if response.status_code != 200:
        Log.error(f"{log_tag} Failed to get Google user profile: {response.text}")
        raise ValueError(f"Failed to get user profile: {response.text}")
    
    data = response.json()
    
    return {
        "google_user_id": data.get("sub"),  # Google's unique identifier
        "email": data.get("email"),
        "email_verified": data.get("email_verified", False),
        "name": data.get("name"),
        "first_name": data.get("given_name"),
        "last_name": data.get("family_name"),
        "profile_picture": data.get("picture"),
        "locale": data.get("locale"),
    }


# =========================================
# HELPER: Get YouTube channels (optional enrichment)
# =========================================
def _get_youtube_channels(access_token: str, log_tag: str) -> list:
    """
    Get YouTube channels for the authenticated user.
    
    This is optional enrichment - only works if youtube.readonly scope was requested.
    For login-only flow, this may return empty list.
    """
    import requests
    
    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    
    try:
        response = requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={
                "part": "snippet,contentDetails,statistics",
                "mine": "true",
            },
            headers=headers,
            timeout=30,
        )
        
        if response.status_code != 200:
            Log.info(f"{log_tag} Could not fetch YouTube channels: {response.text}")
            return []
        
        data = response.json()
        items = data.get("items", [])
        
        channels = []
        for item in items:
            snippet = item.get("snippet", {})
            channels.append({
                "channel_id": item.get("id"),
                "title": snippet.get("title"),
                "description": snippet.get("description"),
                "custom_url": snippet.get("customUrl"),
                "thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url"),
                "subscriber_count": item.get("statistics", {}).get("subscriberCount"),
            })
        
        return channels
        
    except Exception as e:
        Log.info(f"{log_tag} Error fetching YouTube channels: {e}")
        return []


# =========================================
# HELPER: Create Business and User
# =========================================
def _create_account_from_youtube(
    profile: dict,
    youtube_channels: list,
    log_tag: str,
) -> Tuple[ObjectId, dict]:
    """
    Create a new business and user account from Google/YouTube profile.
    
    This mirrors your existing registration flow:
    1. Create Business
    2. Create User
    3. Seed NotificationSettings
    4. Seed SocialRoles
    5. Create Client
    
    NOTE: YouTube channels are NOT connected here. User must:
    1. Subscribe to a package
    2. Then connect YouTube via /social/oauth/youtube/start
    
    Returns: (business_id, user_doc)
    """
    
    email = profile.get("email")
    name = profile.get("name") or f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
    first_name = profile.get("first_name") or (name.split(" ")[0] if name else "")
    last_name = profile.get("last_name") or (name.split(" ", 1)[1] if " " in name else "")
    
    # If we have YouTube channels, use the first one's info as fallback
    if not name and youtube_channels:
        name = youtube_channels[0].get("title")
    
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
    
    # Get primary YouTube channel info if available
    primary_youtube_channel_id = None
    primary_youtube_channel_title = None
    if youtube_channels:
        primary_youtube_channel_id = youtube_channels[0].get("channel_id")
        primary_youtube_channel_title = youtube_channels[0].get("title")
    
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
                "created_at": str(datetime.utcnow()),
                "status": profile.get("email_verified", True),  # Google verifies emails
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
        "google_user_id": profile.get("google_user_id"),
        "youtube_channel_id": primary_youtube_channel_id,
        "youtube_channel_title": primary_youtube_channel_title,
        "social_login_provider": "youtube",
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
        "email_verified": "verified" if profile.get("email_verified", True) else "pending",
        "google_user_id": profile.get("google_user_id"),
        "youtube_channel_id": primary_youtube_channel_id,
        "youtube_channel_title": primary_youtube_channel_title,
        "social_login_provider": "youtube",
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
        f"youtube_login_state:{state}",
        ttl_seconds,
        json.dumps(data),
    )


def _consume_login_state(state: str) -> Optional[dict]:
    """Retrieve and delete OAuth state from Redis."""
    key = f"youtube_login_state:{state}"
    raw = redis_client.get(key)
    if not raw:
        return None
    redis_client.delete(key)
    try:
        return json.loads(raw)
    except:
        return None


# =========================================
# INITIATE YOUTUBE/GOOGLE LOGIN
# =========================================
@blp_youtube_login.route("/auth/youtube/business/login", methods=["GET"])
class YouTubeLoginStartResource(MethodView):
    """
    Initiate YouTube/Google Login OAuth 2.0 flow.
    
    This uses Google OAuth since YouTube is owned by Google.
    This is for AUTHENTICATION ONLY - not for connecting YouTube channels.
    
    After login, users must:
    1. Subscribe to a package
    2. Connect YouTube channels via /social/oauth/youtube/start
    
    Query params:
    - return_url: Where to redirect after auth (default: FRONTEND_URL)
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[youtube_login_resource.py][YouTubeLoginStartResource][get][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Initiating YouTube/Google login")
        
        try:
            client_id = os.getenv("YOUTUBE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID")
            redirect_uri = os.getenv("YOUTUBE_LOGIN_CALLBACK_URL") or os.getenv("GOOGLE_LOGIN_CALLBACK_URL")
            
            if not client_id or not redirect_uri:
                Log.error(f"{log_tag} Missing YOUTUBE_CLIENT_ID or YOUTUBE_LOGIN_CALLBACK_URL")
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
            
            # Build authorization URL
            params = {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(YOUTUBE_LOGIN_SCOPES),
                "state": state,
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
            }
            
            auth_url = f"{GOOGLE_AUTH_URL}?" + urlencode(params)
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Redirecting to Google OAuth in {duration:.2f}s")
            
            return redirect(auth_url)
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to initiate YouTube login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# YOUTUBE/GOOGLE LOGIN CALLBACK
# =========================================
@blp_youtube_login.route("/auth/youtube/business/callback", methods=["GET"])
class YouTubeLoginCallbackResource(MethodView):
    """
    Handle YouTube/Google Login OAuth 2.0 callback.
    
    This endpoint ONLY handles authentication:
    1. Exchanges code for access token
    2. Gets user profile from Google
    3. Optionally gets YouTube channels (for info only)
    4. Creates account OR logs in existing user
    5. Returns JWT tokens
    
    NOTE: YouTube channels are NOT connected here. After login:
    - If no subscription: User should be redirected to pricing
    - If has subscription: User can connect YouTube via /social/oauth/youtube/start
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[youtube_login_resource.py][YouTubeLoginCallbackResource][get][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Processing YouTube/Google login callback")
        
        # Get parameters
        code = request.args.get("code")
        state = request.args.get("state")
        error = request.args.get("error")
        error_description = request.args.get("error_description")
        
        # Handle errors from Google
        if error:
            Log.info(f"{log_tag} Google returned error: {error} - {error_description}")
            return jsonify({
                "success": False,
                "message": f"Google authentication failed: {error_description or error}",
                "code": "GOOGLE_ERROR",
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
            redirect_uri = os.getenv("YOUTUBE_LOGIN_CALLBACK_URL") or os.getenv("GOOGLE_LOGIN_CALLBACK_URL")
            
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
            profile = _get_google_user_profile(access_token, log_tag)
            profile_duration = time.time() - profile_start
            
            Log.info(f"{log_tag} Profile fetch completed in {profile_duration:.2f}s")
            
            google_user_id = profile.get("google_user_id")
            email = profile.get("email")
            
            Log.info(f"{log_tag} Got profile: google_user_id={google_user_id}, email={email}")
            
            # =========================================
            # 3. GET YOUTUBE CHANNELS (optional)
            # =========================================
            Log.info(f"{log_tag} Getting YouTube channels (optional)...")
            
            yt_start = time.time()
            youtube_channels = _get_youtube_channels(access_token, log_tag)
            yt_duration = time.time() - yt_start
            
            Log.info(f"{log_tag} Found {len(youtube_channels)} YouTube channels in {yt_duration:.2f}s")
            
            # Google should always provide email
            if not email:
                Log.info(f"{log_tag} Email not provided by Google")
                return jsonify({
                    "success": False,
                    "message": "Email is required but Google did not provide it. Please check your Google privacy settings.",
                    "code": "EMAIL_REQUIRED",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # =========================================
            # 4. CHECK IF USER EXISTS
            # =========================================
            user_col = db.get_collection("users")
            
            # First check by Google user ID
            existing_user = user_col.find_one({"google_user_id": google_user_id})
            
            if existing_user:
                # =========================================
                # EXISTING USER (by Google ID) - LOG THEM IN
                # =========================================
                Log.info(f"{log_tag} Existing user found by google_user_id, logging in")
                
                business = Business.get_business_by_id(str(existing_user["business_id"]))
                
                if not business:
                    Log.error(f"{log_tag} Business not found for existing user")
                    return jsonify({
                        "success": False,
                        "message": "Account not found. Please contact support.",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
                # Update YouTube channel info if we have new data
                update_fields = {
                    "updated_at": datetime.utcnow(),
                }
                
                if youtube_channels and not existing_user.get("youtube_channel_id"):
                    update_fields["youtube_channel_id"] = youtube_channels[0].get("channel_id")
                    update_fields["youtube_channel_title"] = youtube_channels[0].get("title")
                
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
                # EXISTING USER (by email) - Link Google and LOG THEM IN
                # =========================================
                Log.info(f"{log_tag} Existing business found by email, linking Google account")
                
                existing_user = User.get_user_by_email(email)
                
                if not existing_user:
                    Log.error(f"{log_tag} User not found for existing business")
                    return jsonify({
                        "success": False,
                        "message": "Account configuration error. Please contact support.",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
                # Link Google/YouTube IDs to existing account
                update_fields = {
                    "google_user_id": google_user_id,
                    "social_login_provider": "youtube",
                    "updated_at": datetime.utcnow(),
                }
                
                if youtube_channels:
                    update_fields["youtube_channel_id"] = youtube_channels[0].get("channel_id")
                    update_fields["youtube_channel_title"] = youtube_channels[0].get("title")
                
                user_col.update_one(
                    {"_id": existing_user["_id"]},
                    {"$set": update_fields}
                )
                
                business_col = db.get_collection("businesses")
                business_update = {
                    "google_user_id": google_user_id,
                    "social_login_provider": "youtube",
                    "updated_at": datetime.utcnow(),
                }
                
                if youtube_channels:
                    business_update["youtube_channel_id"] = youtube_channels[0].get("channel_id")
                    business_update["youtube_channel_title"] = youtube_channels[0].get("title")
                
                business_col.update_one(
                    {"_id": ObjectId(existing_business["_id"])},
                    {"$set": business_update}
                )
                
                # Refresh user doc to get updated fields
                existing_user = user_col.find_one({"_id": existing_user["_id"]})
                
                # Get account_type for token generation
                account_type = decrypt_data(existing_user.get("account_type")) if existing_user.get("account_type") else SYSTEM_USERS["BUSINESS_OWNER"]
                
                duration = time.time() - start_time
                Log.info(f"{log_tag} Login with Google link successful in {duration:.2f}s")
                
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
            Log.info(f"{log_tag} Creating new account from YouTube/Google profile")
            
            business_id, user_doc = _create_account_from_youtube(
                profile=profile,
                youtube_channels=youtube_channels,
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
                "message": "Failed to complete YouTube login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]