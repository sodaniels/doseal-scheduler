# app/resources/social//social_login_resource.py

import os
import time
import secrets
import jwt
from datetime import datetime, timezone, timedelta
from flask_smorest import Blueprint
from flask import request, jsonify, redirect, session, g
from flask.views import MethodView
from bson import ObjectId
from typing import Tuple

from ...constants.service_code import HTTP_STATUS_CODES, SYSTEM_USERS
from ...utils.logger import Log
from ...utils.helpers import make_log_tag
from ...utils.generators import generate_client_id, generate_client_secret

from ...models.business_model import Business, Client, Token
from ...models.user_model import User
from ...models.social.social_auth import SocialAuth
from ...services.auth.social_auth_service import SocialAuthService

from ...extensions.redis_conn import redis_client

blp_social_login = Blueprint("social_login", __name__)


# =========================================
# HELPER: Generate JWT Token
# =========================================
def _generate_auth_tokens(user: dict, business: dict) -> dict:
    """Generate JWT access and refresh tokens."""
    secret = os.getenv("JWT_SECRET_KEY", "your-secret-key")
    
    now = datetime.now(timezone.utc)
    
    access_payload = {
        "user_id": str(user["_id"]),
        "business_id": str(business["_id"]),
        "email": user.get("email_plain") or user.get("email"),
        "account_type": user.get("account_type"),
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
        "expires_in": 86400,  # 24 hours
        "token_type": "Bearer",
    }


# =========================================
# HELPER: Create Business and User from Social Profile
# =========================================
def _create_account_from_social(
    provider: str,
    profile: dict,
    access_token: str,
    refresh_token: str = None,
    token_expires_at: datetime = None,
    log_tag: str = "",
) -> Tuple[dict, dict, dict]:
    """
    Create a new business and user account from social profile.
    
    Returns: (business, user, social_auth)
    """
    import bcrypt
    
    email = profile.get("email")
    name = profile.get("name") or f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()
    first_name = profile.get("first_name") or name.split(" ")[0]
    last_name = profile.get("last_name") or (name.split(" ", 1)[1] if " " in name else "")
    
    # Generate a random password (user can set it later or use social login)
    random_password = secrets.token_urlsafe(16)
    hashed_password = bcrypt.hashpw(
        random_password.encode("utf-8"),
        bcrypt.gensalt()
    ).decode("utf-8")
    
    # Create business
    tenant_id = str(ObjectId())
    client_id = generate_client_id()
    
    account_status = [
        {"account_created": {"created_at": str(datetime.utcnow()), "status": True}},
        {"business_email_verified": {"status": True}},  # Email verified via social
        {"subscribed_to_package": {"status": False}},
    ]
    
    from ...extensions.db import db
    from ...utils.crypt import encrypt_data, hash_data
    
    # Create business document
    business_col = db.get_collection("businesses")
    
    business_doc = {
        "tenant_id": encrypt_data(tenant_id),
        "business_name": encrypt_data(name or email.split("@")[0]),
        "first_name": encrypt_data(first_name),
        "last_name": encrypt_data(last_name),
        "email": encrypt_data(email),
        "hashed_email": hash_data(email),
        "password": hashed_password,
        "client_id": encrypt_data(client_id),
        "client_id_hashed": hash_data(client_id),
        "status": encrypt_data("Active"),
        "hashed_status": hash_data("Active"),
        "account_status": encrypt_data(str(account_status)),
        "account_type": encrypt_data(SYSTEM_USERS["BUSINESS_OWNER"]),
        "image": profile.get("profile_picture"),
        "social_login_provider": provider,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    
    business_result = business_col.insert_one(business_doc)
    business_id = business_result.inserted_id
    
    Log.info(f"{log_tag} Business created: {business_id}")
    
    # Create user
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
        "client_id": encrypt_data(client_id),
        "client_id_hashed": hash_data(client_id),
        "status": encrypt_data("Active"),
        "account_type": encrypt_data(SYSTEM_USERS["BUSINESS_OWNER"]),
        "email_verified": "verified",
        "social_login_provider": provider,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    
    user_result = user_col.insert_one(user_doc)
    user_id = user_result.inserted_id
    
    Log.info(f"{log_tag} User created: {user_id}")
    
    # Update business with user_id
    business_col.update_one(
        {"_id": business_id},
        {"$set": {"user_id": user_id}}
    )
    
    # Create client
    client_secret = generate_client_secret()
    Client.create_client(client_id, client_secret)
    
    # Create social auth connection
    social_auth = SocialAuth.create({
        "business_id": str(business_id),
        "user__id": str(user_id),
        "provider": provider,
        "provider_user_id": profile.get("provider_user_id"),
        "email": email,
        "name": name,
        "profile_picture": profile.get("profile_picture"),
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expires_at": token_expires_at,
        "connection_type": SocialAuth.TYPE_LOGIN,
        "is_primary": True,
        "profile_data": profile.get("raw_profile", {}),
    })
    
    Log.info(f"{log_tag} Social auth created: {social_auth['_id']}")
    
    # Return with decrypted values for response
    return (
        {
            "_id": str(business_id),
            "business_name": name,
            "email": email,
        },
        {
            "_id": str(user_id),
            "fullname": name,
            "email": email,
            "account_type": SYSTEM_USERS["BUSINESS_OWNER"],
        },
        social_auth,
    )


# =========================================
# INITIATE SOCIAL LOGIN
# =========================================
@blp_social_login.route("/auth/social/<provider>/login", methods=["GET"])
class SocialLoginInitiateResource(MethodView):
    """
    Initiate social login OAuth flow.
    
    Redirects user to the provider's authorization page.
    """
    
    def get(self, provider: str):
        client_ip = request.remote_addr
        log_tag = f"[social_login_resource.py][Initiate][{provider}][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Initiating social login")
        
        # Validate provider
        provider = provider.lower()
        if provider not in SocialAuth.SUPPORTED_PROVIDERS:
            return jsonify({
                "success": False,
                "message": f"Unsupported provider: {provider}",
                "supported_providers": SocialAuth.SUPPORTED_PROVIDERS,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            service = SocialAuthService(provider)
            
            # Generate state for CSRF protection
            state = service.generate_state()
            
            # Get optional parameters
            return_url = request.args.get("return_url", os.getenv("FRONTEND_URL", "/"))
            scopes = request.args.getlist("scope")
            action = request.args.get("action", "login")  # login or link
            
            # Store state in Redis (5 minutes TTL)
            state_data = {
                "provider": provider,
                "return_url": return_url,
                "action": action,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            
            # If linking to existing account, store user info
            if action == "link":
                user_id = request.args.get("user_id")
                business_id = request.args.get("business_id")
                if user_id and business_id:
                    state_data["user_id"] = user_id
                    state_data["business_id"] = business_id
            
            redis_client.setex(
                f"social_auth_state:{state}",
                300,  # 5 minutes
                str(state_data),
            )
            
            # Generate authorization URL
            auth_url = service.get_authorization_url(
                state=state,
                scopes=scopes if scopes else None,
            )
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Redirecting to {provider} in {duration:.2f}s")
            
            return redirect(auth_url)
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to initiate social login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# SOCIAL LOGIN CALLBACK
# =========================================
@blp_social_login.route("/auth/social/<provider>/callback", methods=["GET", "POST"])
class SocialLoginCallbackResource(MethodView):
    """
    Handle OAuth callback from social provider.
    
    - Exchanges code for tokens
    - Gets user profile
    - Creates account or logs in existing user
    - Returns JWT tokens
    """
    
    def get(self, provider: str):
        return self._handle_callback(provider)
    
    def post(self, provider: str):
        # Apple sends POST with form data
        return self._handle_callback(provider)
    
    def _handle_callback(self, provider: str):
        client_ip = request.remote_addr
        log_tag = f"[social_login_resource.py][Callback][{provider}][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Processing callback")
        
        provider = provider.lower()
        
        # Get parameters (from query or form for Apple)
        code = request.args.get("code") or request.form.get("code")
        state = request.args.get("state") or request.form.get("state")
        error = request.args.get("error") or request.form.get("error")
        
        # Handle errors from provider
        if error:
            error_description = request.args.get("error_description", error)
            Log.info(f"{log_tag} Provider returned error: {error_description}")
            
            return jsonify({
                "success": False,
                "message": f"Authentication failed: {error_description}",
                "code": "PROVIDER_ERROR",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if not code:
            return jsonify({
                "success": False,
                "message": "Authorization code missing",
                "code": "MISSING_CODE",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if not state:
            return jsonify({
                "success": False,
                "message": "State parameter missing",
                "code": "MISSING_STATE",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            # Verify state from Redis
            state_key = f"social_auth_state:{state}"
            state_data_str = redis_client.get(state_key)
            
            if not state_data_str:
                Log.info(f"{log_tag} Invalid or expired state")
                return jsonify({
                    "success": False,
                    "message": "Invalid or expired state. Please try again.",
                    "code": "INVALID_STATE",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # Delete state (one-time use)
            redis_client.delete(state_key)
            
            state_data = eval(state_data_str)  # Safe since we stored it
            return_url = state_data.get("return_url", "/")
            action = state_data.get("action", "login")
            
            # Exchange code for tokens
            service = SocialAuthService(provider)
            
            token_start = time.time()
            token_result = service.exchange_code(code)
            token_duration = time.time() - token_start
            
            Log.info(f"{log_tag} Token exchange completed in {token_duration:.2f}s")
            
            if not token_result.get("success"):
                return jsonify({
                    "success": False,
                    "message": "Failed to exchange authorization code",
                    "error": token_result.get("error"),
                    "code": "TOKEN_EXCHANGE_FAILED",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            access_token = token_result["access_token"]
            refresh_token = token_result.get("refresh_token")
            expires_in = token_result.get("expires_in")
            
            token_expires_at = None
            if expires_in:
                token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
            
            # Get user profile
            profile_start = time.time()
            profile_result = service.get_user_info(access_token)
            profile_duration = time.time() - profile_start
            
            Log.info(f"{log_tag} Profile fetch completed in {profile_duration:.2f}s")
            
            if not profile_result.get("success"):
                return jsonify({
                    "success": False,
                    "message": "Failed to get user profile",
                    "error": profile_result.get("error"),
                    "code": "PROFILE_FETCH_FAILED",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            provider_user_id = profile_result.get("provider_user_id")
            email = profile_result.get("email")
            
            Log.info(f"{log_tag} Got profile: provider_user_id={provider_user_id}, email={email}")
            
            # =========================================
            # CHECK IF USER EXISTS
            # =========================================
            
            # First, check by social auth (provider + provider_user_id)
            existing_social = SocialAuth.get_by_provider_user_id(provider, provider_user_id)
            
            if existing_social and existing_social.get("user__id"):
                # User exists with this social account - LOG THEM IN
                Log.info(f"{log_tag} Existing social auth found, logging in")
                
                user = User.get_by_id(existing_social["user__id"], existing_social["business_id"])
                business = Business.get_business_by_id(existing_social["business_id"])
                
                if not user or not business:
                    Log.error(f"{log_tag} User or business not found for existing social auth")
                    return jsonify({
                        "success": False,
                        "message": "Account not found. Please contact support.",
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
                # Update tokens
                SocialAuth.update_tokens(
                    existing_social["_id"],
                    access_token,
                    refresh_token,
                    token_expires_at,
                )
                
                # Update last used
                SocialAuth.update_last_used(existing_social["_id"])
                
                # Generate JWT tokens
                tokens = _generate_auth_tokens(user, business)
                
                duration = time.time() - start_time
                Log.info(f"{log_tag} Login successful in {duration:.2f}s")
                
                # Redirect with tokens or return JSON
                if "application/json" in request.headers.get("Accept", ""):
                    return jsonify({
                        "success": True,
                        "message": "Login successful",
                        "data": {
                            "user": {
                                "_id": str(user["_id"]),
                                "email": email,
                                "fullname": profile_result.get("name"),
                            },
                            "business": {
                                "_id": str(business["_id"]),
                            },
                            "tokens": tokens,
                            "is_new_user": False,
                        },
                    }), HTTP_STATUS_CODES["OK"]
                else:
                    # Redirect to frontend with token
                    redirect_url = f"{return_url}?access_token={tokens['access_token']}&is_new=false"
                    return redirect(redirect_url)
            
            # Check if user exists by email (in business table)
            if email:
                existing_business = Business.get_business_by_email(email)
                
                if existing_business:
                    # User exists with this email - LINK social account
                    Log.info(f"{log_tag} Existing business found by email, linking social account")
                    
                    user = User.get_user_by_email(email)
                    
                    if not user:
                        Log.error(f"{log_tag} User not found for existing business")
                        return jsonify({
                            "success": False,
                            "message": "Account configuration error. Please contact support.",
                        }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                    
                    # Create social auth connection
                    social_auth = SocialAuth.create({
                        "business_id": str(existing_business["_id"]),
                        "user__id": str(user["_id"]),
                        "provider": provider,
                        "provider_user_id": provider_user_id,
                        "email": email,
                        "name": profile_result.get("name"),
                        "profile_picture": profile_result.get("profile_picture"),
                        "access_token": access_token,
                        "refresh_token": refresh_token,
                        "token_expires_at": token_expires_at,
                        "connection_type": SocialAuth.TYPE_LOGIN,
                        "is_primary": False,
                        "profile_data": profile_result.get("raw_profile", {}),
                    })
                    
                    Log.info(f"{log_tag} Social auth linked: {social_auth['_id']}")
                    
                    # Generate JWT tokens
                    tokens = _generate_auth_tokens(user, existing_business)
                    
                    duration = time.time() - start_time
                    Log.info(f"{log_tag} Login with linked account successful in {duration:.2f}s")
                    
                    if "application/json" in request.headers.get("Accept", ""):
                        return jsonify({
                            "success": True,
                            "message": "Login successful. Social account linked.",
                            "data": {
                                "user": {
                                    "_id": str(user["_id"]),
                                    "email": email,
                                },
                                "tokens": tokens,
                                "is_new_user": False,
                                "social_linked": True,
                            },
                        }), HTTP_STATUS_CODES["OK"]
                    else:
                        redirect_url = f"{return_url}?access_token={tokens['access_token']}&is_new=false&linked=true"
                        return redirect(redirect_url)
            
            # =========================================
            # CREATE NEW ACCOUNT
            # =========================================
            if not email:
                Log.info(f"{log_tag} Email not provided by {provider}")
                return jsonify({
                    "success": False,
                    "message": f"Email is required but {provider} did not provide it. Please try a different login method or update your {provider} settings.",
                    "code": "EMAIL_REQUIRED",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            Log.info(f"{log_tag} Creating new account from social profile")
            
            business, user, social_auth = _create_account_from_social(
                provider=provider,
                profile=profile_result,
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=token_expires_at,
                log_tag=log_tag,
            )
            
            # Generate JWT tokens
            tokens = _generate_auth_tokens(user, business)
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} New account created and logged in, in {duration:.2f}s")
            
            if "application/json" in request.headers.get("Accept", ""):
                return jsonify({
                    "success": True,
                    "message": "Account created successfully",
                    "data": {
                        "user": user,
                        "business": business,
                        "tokens": tokens,
                        "is_new_user": True,
                    },
                }), HTTP_STATUS_CODES["CREATED"]
            else:
                redirect_url = f"{return_url}?access_token={tokens['access_token']}&is_new=true"
                return redirect(redirect_url)
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to complete social login",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST CONNECTED SOCIAL ACCOUNTS
# =========================================
@blp_social_login.route("/auth/social/connections", methods=["GET"])
class SocialConnectionsResource(MethodView):
    """
    List social accounts connected to the user's account.
    """
    
    def get(self):
        from ..doseal.admin.admin_business_resource import token_required
        
        @token_required
        def _get():
            user = g.get("current_user", {}) or {}
            business_id = str(user.get("business_id", ""))
            user__id = str(user.get("_id", ""))
            
            connections = SocialAuth.get_by_user(business_id, user__id)
            
            # Format for response
            formatted = []
            for conn in connections:
                formatted.append({
                    "_id": conn["_id"],
                    "provider": conn["provider"],
                    "email": conn.get("email"),
                    "name": conn.get("name"),
                    "profile_picture": conn.get("profile_picture"),
                    "connection_type": conn.get("connection_type"),
                    "is_primary": conn.get("is_primary", False),
                    "last_used_at": conn.get("last_used_at"),
                    "created_at": conn.get("created_at"),
                })
            
            return jsonify({
                "success": True,
                "data": formatted,
            }), HTTP_STATUS_CODES["OK"]
        
        return _get()


# =========================================
# UNLINK SOCIAL ACCOUNT
# =========================================
@blp_social_login.route("/auth/social/connections/<connection_id>/unlink", methods=["DELETE"])
class SocialUnlinkResource(MethodView):
    """
    Unlink a social account from the user's account.
    """
    
    def delete(self, connection_id: str):
        from ..doseal.admin.admin_business_resource import token_required
        
        @token_required
        def _delete():
            user = g.get("current_user", {}) or {}
            business_id = str(user.get("business_id", ""))
            user__id = str(user.get("_id", ""))
            
            # Check if this is the only login method
            connections = SocialAuth.get_login_connections(business_id, user__id)
            
            # Get user to check if they have a password
            user_doc = User.get_by_id(user__id, business_id)
            has_password = bool(user_doc and user_doc.get("password"))
            
            # If this is the only login method and no password, prevent unlinking
            if len(connections) <= 1 and not has_password:
                return jsonify({
                    "success": False,
                    "message": "Cannot unlink the only login method. Please set a password first or connect another social account.",
                    "code": "LAST_LOGIN_METHOD",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # Unlink
            result = SocialAuth.unlink(connection_id, business_id, user__id)
            
            if not result:
                return jsonify({
                    "success": False,
                    "message": "Social connection not found",
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            return jsonify({
                "success": True,
                "message": "Social account unlinked successfully",
            }), HTTP_STATUS_CODES["OK"]
        
        return _delete()