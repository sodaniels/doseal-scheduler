# app/routes/auth/facebook_business_login_resource.py

import os
import time
from datetime import datetime, timezone, timedelta
from flask_smorest import Blueprint
from flask import request, jsonify, redirect, g
from flask.views import MethodView

from ...constants.service_code import HTTP_STATUS_CODES
from ...utils.logger import Log
from ...utils.helpers import make_log_tag
from ...extensions.redis_conn import redis_client

from ...models.social.social_account import SocialAccount
from ...services.auth.facebook_business_auth_service import FacebookBusinessAuthService


blp_facebook_business = Blueprint("facebook_business", __name__)


# =========================================
# INITIATE FACEBOOK BUSINESS LOGIN
# =========================================
@blp_facebook_business.route("/auth/facebook/business/login", methods=["GET"])
class FacebookBusinessLoginResource(MethodView):
    """
    Initiate Facebook Business Login OAuth flow.
    
    Query params:
    - return_url: Where to redirect after auth
    - include_ads: Include ads permissions (true/false)
    - config_id: Facebook Login Configuration ID (optional)
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[facebook_business_login_resource.py][FacebookBusinessLogin][get][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Initiating Facebook Business login")
        
        try:
            service = FacebookBusinessAuthService()
            
            # Generate state
            state = service.generate_state()
            
            # Get parameters
            return_url = request.args.get("return_url", os.getenv("FRONTEND_BASE_URL", "/"))
            include_ads = request.args.get("include_ads", "false").lower() == "true"
            config_id = request.args.get("config_id")
            
            # Store state in Redis
            state_data = {
                "return_url": return_url,
                "include_ads": include_ads,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            
            # Add user info if authenticated (for linking)
            if hasattr(g, "current_user") and g.current_user:
                state_data["business_id"] = str(g.current_user.get("business_id", ""))
                state_data["user__id"] = str(g.current_user.get("_id", ""))
            
            redis_client.setex(
                f"fb_business_state:{state}",
                300,  # 5 minutes
                str(state_data),
            )
            
            # Generate authorization URL
            if include_ads:
                auth_url = service.get_authorization_url_with_ads(
                    state=state,
                    config_id=config_id,
                )
            else:
                auth_url = service.get_authorization_url(
                    state=state,
                    config_id=config_id,
                )
            
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
# FACEBOOK BUSINESS CALLBACK
# =========================================
@blp_facebook_business.route("/auth/facebook/business/callback", methods=["GET"])
class FacebookBusinessCallbackResource(MethodView):
    """
    Handle Facebook Business OAuth callback.
    
    - Exchanges code for tokens
    - Gets long-lived token
    - Fetches user's Pages and Instagram accounts
    - Stores for selection
    """
    
    def get(self):
        client_ip = request.remote_addr
        log_tag = f"[FacebookBusinessLogin][Callback][{client_ip}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Processing callback")
        
        # Get parameters
        code = request.args.get("code")
        state = request.args.get("state")
        error = request.args.get("error")
        error_description = request.args.get("error_description")
        
        # Handle errors
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
            state_key = f"fb_business_state:{state}"
            state_data_str = redis_client.get(state_key)
            
            if not state_data_str:
                Log.info(f"{log_tag} Invalid or expired state")
                return jsonify({
                    "success": False,
                    "message": "Invalid or expired state. Please try again.",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            redis_client.delete(state_key)
            state_data = eval(state_data_str)
            return_url = state_data.get("return_url", "/")
            
            service = FacebookBusinessAuthService()
            
            # =========================================
            # EXCHANGE CODE FOR TOKEN
            # =========================================
            Log.info(f"{log_tag} Exchanging code for token...")
            
            token_start = time.time()
            token_result = service.exchange_code(code)
            token_duration = time.time() - token_start
            
            Log.info(f"{log_tag} Token exchange completed in {token_duration:.2f}s")
            
            if not token_result.get("success"):
                return jsonify({
                    "success": False,
                    "message": "Failed to exchange code for token",
                    "error": token_result.get("error"),
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            short_lived_token = token_result["access_token"]
            
            # =========================================
            # GET LONG-LIVED TOKEN
            # =========================================
            Log.info(f"{log_tag} Exchanging for long-lived token...")
            
            ll_start = time.time()
            ll_result = service.get_long_lived_token(short_lived_token)
            ll_duration = time.time() - ll_start
            
            Log.info(f"{log_tag} Long-lived token exchange completed in {ll_duration:.2f}s")
            
            if not ll_result.get("success"):
                # Fallback to short-lived token
                Log.info(f"{log_tag} Long-lived token failed, using short-lived")
                user_access_token = short_lived_token
                token_expires_in = token_result.get("expires_in", 3600)
            else:
                user_access_token = ll_result["access_token"]
                token_expires_in = ll_result.get("expires_in", 5184000)  # ~60 days
            
            # =========================================
            # GET USER INFO
            # =========================================
            user_result = service.get_user_info(user_access_token)
            
            if not user_result.get("success"):
                Log.error(f"{log_tag} Failed to get user info: {user_result.get('error')}")
                return jsonify({
                    "success": False,
                    "message": "Failed to get user information",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # =========================================
            # GET PAGES & INSTAGRAM ACCOUNTS
            # =========================================
            Log.info(f"{log_tag} Fetching Pages and Instagram accounts...")
            
            pages_start = time.time()
            pages_result = service.get_user_pages(user_access_token)
            pages_duration = time.time() - pages_start
            
            Log.info(f"{log_tag} Pages fetch completed in {pages_duration:.2f}s")
            
            if not pages_result.get("success"):
                return jsonify({
                    "success": False,
                    "message": "Failed to fetch Pages. Make sure you have the required permissions.",
                    "error": pages_result.get("error"),
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            pages = pages_result.get("pages", [])
            
            if not pages:
                return jsonify({
                    "success": False,
                    "message": "No Facebook Pages found. You need at least one Page to continue.",
                    "code": "NO_PAGES",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # =========================================
            # GET AD ACCOUNTS (if ads permissions were requested)
            # =========================================
            ad_accounts = []
            if state_data.get("include_ads"):
                Log.info(f"{log_tag} Fetching Ad accounts...")
                
                ads_start = time.time()
                ads_result = service.get_user_ad_accounts(user_access_token)
                ads_duration = time.time() - ads_start
                
                Log.info(f"{log_tag} Ad accounts fetch completed in {ads_duration:.2f}s")
                
                if ads_result.get("success"):
                    ad_accounts = ads_result.get("ad_accounts", [])
            
            # =========================================
            # GET GRANTED SCOPES
            # =========================================
            scopes_result = service.get_granted_scopes(user_access_token)
            granted_scopes = scopes_result.get("granted", []) if scopes_result.get("success") else []
            
            # =========================================
            # STORE FOR SELECTION
            # =========================================
            selection_key = f"fb_selection:{state}"
            
            selection_data = {
                "user": user_result,
                "user_access_token": user_access_token,
                "token_expires_in": token_expires_in,
                "pages": pages,
                "ad_accounts": ad_accounts,
                "granted_scopes": granted_scopes,
                "business_id": state_data.get("business_id"),
                "user__id": state_data.get("user__id"),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            
            redis_client.setex(
                selection_key,
                600,  # 10 minutes
                str(selection_data),
            )
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Callback completed in {duration:.2f}s found={len(pages)} pages")
            
            # Return data for frontend to show selection UI
            return jsonify({
                "success": True,
                "message": "Authentication successful. Please select accounts to connect.",
                "data": {
                    "selection_key": state,
                    "user": {
                        "id": user_result.get("user_id"),
                        "name": user_result.get("name"),
                        "email": user_result.get("email"),
                        "profile_picture": user_result.get("profile_picture"),
                    },
                    "pages": [
                        {
                            "page_id": p["page_id"],
                            "page_name": p["page_name"],
                            "category": p["category"],
                            "picture": p["picture"],
                            "instagram": p["instagram"],
                        }
                        for p in pages
                    ],
                    "ad_accounts": [
                        {
                            "id": a["id"],
                            "account_id": a["account_id"],
                            "name": a["name"],
                            "currency": a["currency"],
                            "account_status": a["account_status"],
                        }
                        for a in ad_accounts
                    ],
                    "granted_scopes": granted_scopes,
                },
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to complete Facebook authentication",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# CONNECT SELECTED PAGES/ACCOUNTS
# =========================================
@blp_facebook_business.route("/auth/facebook/business/connect", methods=["POST"])
class FacebookBusinessConnectResource(MethodView):
    """
    Connect selected Facebook Pages and Instagram accounts.
    
    Body:
    {
        "selection_key": "...",
        "pages": ["page_id_1", "page_id_2"],
        "ad_accounts": ["act_123456789"],
        "business_id": "...",  // If not in state
        "user__id": "..."      // If not in state
    }
    """
    
    def post(self):
        from ..doseal.admin.admin_business_resource import token_required
        
        @token_required
        def _connect():
            client_ip = request.remote_addr
            user = g.get("current_user", {}) or {}
            
            business_id = str(user.get("business_id", ""))
            user__id = str(user.get("_id", ""))
            
            log_tag = f"[FacebookBusinessLogin][Connect][{client_ip}]"
            
            start_time = time.time()
            Log.info(f"{log_tag} Connecting Facebook accounts")
            
            body = request.get_json(silent=True) or {}
            
            selection_key = body.get("selection_key")
            page_ids = body.get("pages", [])
            ad_account_ids = body.get("ad_accounts", [])
            
            if not selection_key:
                return jsonify({
                    "success": False,
                    "message": "selection_key is required",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            if not page_ids and not ad_account_ids:
                return jsonify({
                    "success": False,
                    "message": "Please select at least one Page or Ad Account",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            try:
                # Get selection data from Redis
                redis_key = f"fb_selection:{selection_key}"
                selection_data_str = redis_client.get(redis_key)
                
                if not selection_data_str:
                    return jsonify({
                        "success": False,
                        "message": "Selection expired. Please authenticate again.",
                    }), HTTP_STATUS_CODES["BAD_REQUEST"]
                
                selection_data = eval(selection_data_str)
                
                user_access_token = selection_data["user_access_token"]
                all_pages = selection_data["pages"]
                all_ad_accounts = selection_data["ad_accounts"]
                granted_scopes = selection_data.get("granted_scopes", [])
                
                service = FacebookBusinessAuthService()
                
                connected = {
                    "pages": [],
                    "instagram": [],
                    "ad_accounts": [],
                }
                
                # =========================================
                # CONNECT SELECTED PAGES
                # =========================================
                for page in all_pages:
                    if page["page_id"] in page_ids:
                        Log.info(f"{log_tag} Connecting page: {page['page_id']} - {page['page_name']}")
                        
                        # Get long-lived page token
                        page_token_result = service.get_page_long_lived_token(
                            user_access_token,
                            page["page_id"],
                        )
                        
                        if not page_token_result.get("success"):
                            Log.error(f"{log_tag} Failed to get page token: {page_token_result.get('error')}")
                            continue
                        
                        page_access_token = page_token_result["page_access_token"]
                        
                        # Save Facebook Page
                        fb_account = SocialAccount.upsert_destination(
                            business_id=business_id,
                            user__id=user__id,
                            platform="facebook",
                            destination_id=page["page_id"],
                            destination_name=page["page_name"],
                            platform_username=page["page_name"],
                            access_token=page_access_token,
                            scopes=granted_scopes,
                            meta={
                                "page_id": page["page_id"],
                                "category": page["category"],
                                "picture": page["picture"],
                                "tasks": page.get("tasks", []),
                                "user_access_token": user_access_token,  # For ads API
                            },
                        )
                        
                        connected["pages"].append({
                            "page_id": page["page_id"],
                            "page_name": page["page_name"],
                        })
                        
                        # =========================================
                        # CONNECT INSTAGRAM (if linked)
                        # =========================================
                        if page.get("instagram") and page["instagram"].get("instagram_id"):
                            ig = page["instagram"]
                            
                            Log.info(f"{log_tag} Connecting Instagram: {ig['instagram_id']} - {ig['username']}")
                            
                            ig_account = SocialAccount.upsert_destination(
                                business_id=business_id,
                                user__id=user__id,
                                platform="instagram",
                                destination_id=ig["instagram_id"],
                                destination_name=ig["username"],
                                platform_username=ig["username"],
                                access_token=page_access_token,  # Use page token for Instagram
                                scopes=granted_scopes,
                                meta={
                                    "instagram_id": ig["instagram_id"],
                                    "page_id": page["page_id"],
                                    "page_name": page["page_name"],
                                    "profile_picture": ig["profile_picture"],
                                    "followers_count": ig["followers_count"],
                                    "user_access_token": user_access_token,
                                },
                            )
                            
                            connected["instagram"].append({
                                "instagram_id": ig["instagram_id"],
                                "username": ig["username"],
                            })
                
                # =========================================
                # CONNECT SELECTED AD ACCOUNTS
                # =========================================
                if ad_account_ids:
                    from app.models.social.ad_account import AdAccount
                    
                    for ad_account in all_ad_accounts:
                        if ad_account["id"] in ad_account_ids:
                            Log.info(f"{log_tag} Connecting ad account: {ad_account['id']} - {ad_account['name']}")
                            
                            # Check if already exists
                            existing = AdAccount.get_by_ad_account_id(business_id, ad_account["id"])
                            
                            if not existing:
                                AdAccount.create({
                                    "business_id": business_id,
                                    "user__id": user__id,
                                    "ad_account_id": ad_account["id"],
                                    "ad_account_name": ad_account["name"],
                                    "currency": ad_account.get("currency", "USD"),
                                    "timezone_name": ad_account.get("timezone_name"),
                                    "fb_account_status": ad_account.get("account_status"),
                                    "access_token": user_access_token,  # User token for ads
                                })
                            else:
                                # Update token
                                AdAccount.update(existing["_id"], business_id, {
                                    "access_token": user_access_token,
                                })
                            
                            connected["ad_accounts"].append({
                                "ad_account_id": ad_account["id"],
                                "name": ad_account["name"],
                            })
                
                # Clean up Redis
                redis_client.delete(redis_key)
                
                duration = time.time() - start_time
                Log.info(
                    f"{log_tag} Connection completed in {duration:.2f}s "
                    f"pages={len(connected['pages'])} "
                    f"instagram={len(connected['instagram'])} "
                    f"ad_accounts={len(connected['ad_accounts'])}"
                )
                
                return jsonify({
                    "success": True,
                    "message": "Accounts connected successfully",
                    "data": {
                        "connected": connected,
                    },
                }), HTTP_STATUS_CODES["CREATED"]
            
            except Exception as e:
                duration = time.time() - start_time
                Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
                
                return jsonify({
                    "success": False,
                    "message": "Failed to connect accounts",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        
        return _connect()