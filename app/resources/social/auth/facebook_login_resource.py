# app/routes/auth/facebook_login_resource.py

import os
import time
import secrets
import jwt
import bcrypt
from typing import Tuple, Optional
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from flask_smorest import Blueprint
from flask import request, jsonify, redirect, g
from flask.views import MethodView
from bson import ObjectId

from ....constants.service_code import HTTP_STATUS_CODES, SYSTEM_USERS
from ....utils.logger import Log
from ....utils.generators import generate_client_id, generate_client_secret
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....extensions.redis_conn import redis_client
from ....extensions.db import db

from ....models.business_model import Business, Client
from ....models.user_model import User
from ....models.social.social_account import SocialAccount
from ....models.notifications.notification_settings import NotificationSettings
from ....services.seeders.social_role_seeder import SocialRoleSeeder

from ....services.social.adapters.facebook_adapter import FacebookAdapter


blp_facebook_login = Blueprint("facebook_login", __name__)


# =========================================
# CONSTANTS
# =========================================
FACEBOOK_API_VERSION = "v20.0"
FACEBOOK_GRAPH_URL = f"https://graph.facebook.com/{FACEBOOK_API_VERSION}"

# Scopes for login + business access
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
# HELPER: Exchange code for token
# =========================================
def _exchange_code_for_token(code: str, redirect_uri: str, log_tag: str) -> dict:
    """Exchange authorization code for access token."""
    import requests
    
    app_id = os.getenv("META_APP_ID")
    app_secret = os.getenv("META_APP_SECRET")
    
    if not app_id or not app_secret:
        raise ValueError("META_APP_ID and META_APP_SECRET must be set")
    
    # Exchange code for short-lived token
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
            "expires_in": ll_data.get("expires_in", 5184000),  # ~60 days
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
# HELPER: Get Facebook Pages
# =========================================
def _get_facebook_pages(access_token: str, log_tag: str) -> list:
    """Get Facebook Pages the user manages."""
    import requests
    
    response = requests.get(
        f"{FACEBOOK_GRAPH_URL}/me/accounts",
        params={
            "access_token": access_token,
            "fields": "id,name,category,access_token,picture.width(200).height(200),instagram_business_account{id,username,profile_picture_url,followers_count},tasks",
        },
        timeout=30,
    )
    
    if response.status_code != 200:
        Log.info(f"{log_tag} Failed to get pages: {response.text}")
        return []
    
    data = response.json()
    pages = data.get("data", [])
    
    formatted_pages = []
    for page in pages:
        instagram = page.get("instagram_business_account", {})
        
        formatted_pages.append({
            "page_id": page.get("id"),
            "page_name": page.get("name"),
            "category": page.get("category"),
            "page_access_token": page.get("access_token"),
            "picture": page.get("picture", {}).get("data", {}).get("url"),
            "tasks": page.get("tasks", []),
            "instagram": {
                "instagram_id": instagram.get("id"),
                "username": instagram.get("username"),
                "profile_picture": instagram.get("profile_picture_url"),
                "followers_count": instagram.get("followers_count"),
            } if instagram.get("id") else None,
        })
    
    return formatted_pages


# =========================================
# HELPER: Generate JWT tokens
# =========================================
def _generate_auth_tokens(user: dict, business: dict) -> dict:
    """Generate JWT access and refresh tokens."""
    secret = os.getenv("JWT_SECRET_KEY", "your-secret-key")
    
    now = datetime.now(timezone.utc)
    
    # Get email (may be encrypted)
    email = user.get("email")
    if email and "@" not in str(email):
        try:
            email = decrypt_data(email)
        except:
            pass
    
    # Get account_type (may be encrypted)
    account_type = user.get("account_type")
    if account_type:
        try:
            decrypted = decrypt_data(account_type)
            if decrypted:
                account_type = decrypted
        except:
            pass
    
    access_payload = {
        "user_id": str(user["_id"]),
        "business_id": str(business["_id"]),
        "email": email,
        "account_type": account_type,
        "iat": now,
        "exp": now + timedelta(hours=24),
        "type": "access",
    }
    
    refresh_payload = {
        "user_id": str(user["_id"]),
        "business_id": str(business["_id"]),
        "iat": now,
        "exp": now + timedelta(days=30),
        "type": "refresh",
    }
    
    access_token = jwt.encode(access_payload, secret, algorithm="HS256")
    refresh_token = jwt.encode(refresh_payload, secret, algorithm="HS256")
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": 86400,
        "token_type": "Bearer",
    }


# =========================================
# HELPER: Create Business and User (mirrors registration)
# =========================================
def _create_account_from_facebook(
    profile: dict,
    facebook_access_token: str,
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
    
    Returns: (business_dict, user_dict)
    """
    
    email = profile.get("email")
    name = profile.get("name") or f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
    first_name = profile.get("first_name") or (name.split(" ")[0] if name else "")
    last_name = profile.get("last_name") or (name.split(" ", 1)[1] if " " in name else "")
    
    if not name:
        name = email.split("@")[0] if email else "User"
    
    # Generate a random password (user can set it later or continue using Facebook login)
    random_password = secrets.token_urlsafe(16)
    hashed_password = bcrypt.hashpw(
        random_password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")
    
    # Generate tenant_id and client_id
    tenant_id = str(ObjectId())
    client_id_plain = generate_client_id()
    
    # Account status (email verified since they used Facebook login)
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
                "status": False,
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
        "account_status": encrypt_data(str(account_status)),
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
        "email_verified": "verified",  # Verified via Facebook
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
    
    # Return dictionaries for response
    return (
        {
            "_id": str(business_id),
            "business_name": name,
            "email": email,
            "client_id": client_id_plain,
        },
        {
            "_id": str(user_id),
            "business_id": str(business_id),
            "fullname": name,
            "email": email,
            "account_type": account_type,
        },
    )


# =========================================
# HELPER: Connect Facebook Pages & Instagram
# =========================================
def _connect_facebook_pages(
    business_id: str,
    user__id: str,
    user_access_token: str,
    pages: list,
    log_tag: str,
) -> dict:
    """
    Connect Facebook Pages and Instagram accounts.
    Uses your existing SocialAccount.upsert_destination pattern.
    """
    connected = {
        "pages": [],
        "instagram": [],
    }
    
    scopes = [
        "pages_show_list",
        "pages_read_engagement",
        "pages_manage_posts",
        "read_insights",
        "instagram_basic",
        "instagram_content_publish",
        "instagram_manage_insights",
    ]
    
    for page in pages:
        page_id = page.get("page_id")
        page_name = page.get("page_name")
        page_access_token = page.get("page_access_token")
        
        if not page_access_token:
            Log.info(f"{log_tag} No token for page {page_id}, skipping")
            continue
        
        Log.info(f"{log_tag} Connecting page: {page_id} - {page_name}")
        
        # Connect Facebook Page
        try:
            SocialAccount.upsert_destination(
                business_id=business_id,
                user__id=user__id,
                platform="facebook",
                destination_id=str(page_id),
                destination_type="page",
                destination_name=page_name,
                access_token_plain=page_access_token,
                refresh_token_plain=None,
                token_expires_at=None,
                scopes=scopes,
                platform_user_id=str(page_id),
                platform_username=page_name,
                meta={
                    "page_id": str(page_id),
                    "category": page.get("category"),
                    "picture": page.get("picture"),
                    "tasks": page.get("tasks", []),
                    "user_access_token": user_access_token,
                },
            )
            
            connected["pages"].append({
                "page_id": page_id,
                "page_name": page_name,
            })
            
            Log.info(f"{log_tag} Page connected: {page_id}")
        except Exception as e:
            Log.error(f"{log_tag} Failed to connect page {page_id}: {e}")
        
        # Connect Instagram if linked
        instagram = page.get("instagram")
        if instagram and instagram.get("instagram_id"):
            ig_id = instagram["instagram_id"]
            ig_username = instagram.get("username", "")
            
            Log.info(f"{log_tag} Connecting Instagram: {ig_id} - {ig_username}")
            
            try:
                SocialAccount.upsert_destination(
                    business_id=business_id,
                    user__id=user__id,
                    platform="instagram",
                    destination_id=str(ig_id),
                    destination_type="ig_user",
                    destination_name=ig_username,
                    access_token_plain=page_access_token,  # Instagram uses page token
                    refresh_token_plain=None,
                    token_expires_at=None,
                    scopes=scopes,
                    platform_user_id=str(ig_id),
                    platform_username=ig_username,
                    meta={
                        "ig_user_id": str(ig_id),
                        "ig_username": ig_username,
                        "page_id": str(page_id),
                        "page_name": page_name,
                        "profile_picture": instagram.get("profile_picture"),
                        "followers_count": instagram.get("followers_count"),
                        "user_access_token": user_access_token,
                    },
                )
                
                connected["instagram"].append({
                    "instagram_id": ig_id,
                    "username": ig_username,
                })
                
                Log.info(f"{log_tag} Instagram connected: {ig_id}")
            except Exception as e:
                Log.error(f"{log_tag} Failed to connect Instagram {ig_id}: {e}")
    
    return connected


# =========================================
# HELPER: Store/retrieve OAuth state
# =========================================
def _store_login_state(state: str, data: dict, ttl_seconds: int = 600):
    """Store OAuth state in Redis."""
    import json
    redis_client.setex(
        f"fb_login_state:{state}",
        ttl_seconds,
        json.dumps(data),
    )


def _consume_login_state(state: str) -> Optional[dict]:
    """Retrieve and delete OAuth state from Redis."""
    import json
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
    
    This allows users to:
    1. Log in with their Facebook account
    2. Automatically register if they don't have an account
    3. Connect their Facebook Pages and Instagram accounts
    
    Query params:
    - return_url: Where to redirect after auth (default: FRONTEND_URL)
    - include_ads: Include ads management scopes (true/false)
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_login_resource.py][FacebookLoginStartResource][get][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Initiating Facebook login")
        
        try:
            # Get environment variables
            app_id = os.getenv("META_APP_ID")
            redirect_uri = os.getenv("FACEBOOK_LOGIN_REDIRECT_URI")
            
            if not app_id or not redirect_uri:
                Log.error(f"{log_tag} Missing META_APP_ID or FACEBOOK_LOGIN_REDIRECT_URI")
                return jsonify({
                    "success": False,
                    "message": "Server OAuth configuration missing",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            
            # Get optional parameters
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
            scopes = FACEBOOK_LOGIN_SCOPES.copy()
            if include_ads:
                scopes.extend(FACEBOOK_ADS_SCOPES)
            
            # Build authorization URL
            params = {
                "client_id": app_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "response_type": "code",
                "scope": ",".join(scopes),
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
    
    This endpoint:
    1. Exchanges code for access token
    2. Gets user profile from Facebook
    3. Creates account OR logs in existing user
    4. Connects Facebook Pages and Instagram accounts
    5. Returns JWT tokens
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
            redirect_uri = os.getenv("FACEBOOK_LOGIN_REDIRECT_URI")
            
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
            # 3. GET FACEBOOK PAGES
            # =========================================
            Log.info(f"{log_tag} Getting Facebook pages...")
            
            pages_start = time.time()
            pages = _get_facebook_pages(access_token, log_tag)
            pages_duration = time.time() - pages_start
            
            Log.info(f"{log_tag} Found {len(pages)} pages in {pages_duration:.2f}s")
            
            # =========================================
            # 4. CHECK IF USER EXISTS
            # =========================================
            
            # First, check by Facebook user ID
            user_col = db.get_collection("users")
            existing_user = user_col.find_one({"facebook_user_id": facebook_user_id})
            
            if existing_user:
                # User exists with this Facebook account - LOG THEM IN
                Log.info(f"{log_tag} Existing user found by facebook_user_id, logging in")
                
                business = Business.get_business_by_id(str(existing_user["business_id"]))
                
                if not business:
                    Log.error(f"{log_tag} Business not found for existing user")
                    return jsonify({
                        "success": False,
                        "message": "Account not found. Please contact support.",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
                # Connect/update Facebook Pages and Instagram
                connected = {"pages": [], "instagram": []}
                if pages:
                    connected = _connect_facebook_pages(
                        business_id=str(business["_id"]),
                        user__id=str(existing_user["_id"]),
                        user_access_token=access_token,
                        pages=pages,
                        log_tag=log_tag,
                    )
                
                # Generate JWT tokens
                tokens = _generate_auth_tokens(existing_user, business)
                
                duration = time.time() - start_time
                Log.info(f"{log_tag} Login successful in {duration:.2f}s")
                
                # Return JSON or redirect
                if "application/json" in request.headers.get("Accept", ""):
                    return jsonify({
                        "success": True,
                        "message": "Login successful",
                        "data": {
                            "user": {
                                "_id": str(existing_user["_id"]),
                                "email": email,
                                "fullname": profile.get("name"),
                            },
                            "business": {
                                "_id": str(business["_id"]),
                                "business_name": business.get("business_name"),
                            },
                            "tokens": tokens,
                            "is_new_user": False,
                            "connected": connected,
                        },
                    }), HTTP_STATUS_CODES["OK"]
                else:
                    redirect_url = f"{return_url}?access_token={tokens['access_token']}&is_new=false"
                    return redirect(redirect_url)
            
            # Check by email
            existing_business = Business.get_business_by_email(email)
            
            if existing_business:
                # User exists with this email - link Facebook and log them in
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
                
                # Connect Facebook Pages and Instagram
                connected = {"pages": [], "instagram": []}
                if pages:
                    connected = _connect_facebook_pages(
                        business_id=str(existing_business["_id"]),
                        user__id=str(existing_user["_id"]),
                        user_access_token=access_token,
                        pages=pages,
                        log_tag=log_tag,
                    )
                
                # Generate JWT tokens
                tokens = _generate_auth_tokens(existing_user, existing_business)
                
                duration = time.time() - start_time
                Log.info(f"{log_tag} Login with Facebook link successful in {duration:.2f}s")
                
                if "application/json" in request.headers.get("Accept", ""):
                    return jsonify({
                        "success": True,
                        "message": "Login successful. Facebook account linked.",
                        "data": {
                            "user": {
                                "_id": str(existing_user["_id"]),
                                "email": email,
                            },
                            "business": {
                                "_id": str(existing_business["_id"]),
                            },
                            "tokens": tokens,
                            "is_new_user": False,
                            "facebook_linked": True,
                            "connected": connected,
                        },
                    }), HTTP_STATUS_CODES["OK"]
                else:
                    redirect_url = f"{return_url}?access_token={tokens['access_token']}&is_new=false&linked=true"
                    return redirect(redirect_url)
            
            # =========================================
            # 5. CREATE NEW ACCOUNT
            # =========================================
            Log.info(f"{log_tag} Creating new account from Facebook profile")
            
            business, user = _create_account_from_facebook(
                profile=profile,
                facebook_access_token=access_token,
                log_tag=log_tag,
            )
            
            # Connect Facebook Pages and Instagram
            connected = {"pages": [], "instagram": []}
            if pages:
                connected = _connect_facebook_pages(
                    business_id=business["_id"],
                    user__id=user["_id"],
                    user_access_token=access_token,
                    pages=pages,
                    log_tag=log_tag,
                )
            
            # Generate JWT tokens
            tokens = _generate_auth_tokens(user, business)
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} New account created in {duration:.2f}s")
            
            if "application/json" in request.headers.get("Accept", ""):
                return jsonify({
                    "success": True,
                    "message": "Account created successfully",
                    "data": {
                        "user": user,
                        "business": business,
                        "tokens": tokens,
                        "is_new_user": True,
                        "connected": connected,
                    },
                }), HTTP_STATUS_CODES["CREATED"]
            else:
                redirect_url = f"{return_url}?access_token={tokens['access_token']}&is_new=true"
                return redirect(redirect_url)
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            import traceback
            traceback.print_exc()
            
            return jsonify({
                "success": False,
                "message": "Failed to complete Facebook login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]