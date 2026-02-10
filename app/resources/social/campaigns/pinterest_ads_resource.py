# app/routes/social/pinterest_ads_resource.py

import os
import json
import time
from datetime import datetime, timezone, timedelta
from flask_smorest import Blueprint
from flask import request, jsonify, g
from flask.views import MethodView
from bson import ObjectId

from ...doseal.admin.admin_business_resource import token_required
from ....constants.service_code import HTTP_STATUS_CODES, SYSTEM_USERS
from ....utils.logger import Log
from ....utils.helpers import make_log_tag

from ....models.social.social_account import SocialAccount
from ....models.social.pinterest_ad_account import PinterestAdAccount, PinterestAdCampaign
from ....services.social.pinterest_ads_service import PinterestAdsService

from ....schemas.social.social_schema import (
    AccountConnectionSchema, PinterestAccountConnectionSchema
)


blp_pinterest_ads = Blueprint("pinterest_ads", __name__)


# =========================================
# HELPER: Get Pinterest Access Token
# =========================================
def _get_pinterest_access_token(business_id: str, user__id: str, log_tag: str) -> dict:
    """
    Get Pinterest access token from social accounts.
    
    Returns:
        {"success": True/False, "access_token": "...", "error": "..."}
    """
    result = {
        "success": False,
        "access_token": None,
        "destination_id": None,
        "error": None,
    }
    
    # Get Pinterest social accounts
    pinterest_accounts = SocialAccount.list_destinations(business_id, user__id, "pinterest")
    
    if not pinterest_accounts:
        result["error"] = "No Pinterest account connected"
        return result
    
    # Get the first one with a valid token
    for acc in pinterest_accounts:
        full_acc = SocialAccount.get_destination(
            business_id, user__id, "pinterest", acc.get("destination_id")
        )
        if full_acc and full_acc.get("access_token_plain"):
            result["success"] = True
            result["access_token"] = full_acc["access_token_plain"]
            result["destination_id"] = acc.get("destination_id")
            Log.info(f"{log_tag} Found Pinterest token for destination: {result['destination_id']}")
            return result
    
    result["error"] = "Pinterest access token not found"
    return result


# =========================================
# LIST USER'S AD ACCOUNTS (from Pinterest)
# =========================================
@blp_pinterest_ads.route("/social/pinterest/ad-accounts/available", methods=["GET"])
class PinterestAdAccountsAvailableResource(MethodView):
    """
    List all Pinterest Ad Accounts the user has access to.
    """
    
    @token_required
    @blp_pinterest_ads.arguments(AccountConnectionSchema, location="query")
    @blp_pinterest_ads.response(200, AccountConnectionSchema)
    def get(self, body):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "pinterest_ads_resource.py",
            "PinterestAdAccountsAvailableResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Fetching available Pinterest ad accounts")
        
        pi_account = SocialAccount.get_destination(
            business_id=business_id, 
            user__id=user__id, 
            platform="pinterest", 
            destination_id=body.get("destination_id"),
        )
        
        if not pi_account:
            return jsonify({
                "success": False,
                "message": "Pinterest account not found.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            # Get Pinterest access token
            token_info = _get_pinterest_access_token(business_id, user__id, log_tag)
            
            if not token_info.get("success"):
                return jsonify({
                    "success": False,
                    "message": token_info.get("error", "Pinterest access token not found"),
                    "code": "NO_PINTEREST_CONNECTED",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            access_token = token_info["access_token"]
            
            # Fetch ad accounts from Pinterest
            service = PinterestAdsService(access_token)
            
            api_start = time.time()
            result = service.get_user_ad_accounts()
            api_duration = time.time() - api_start
            
            Log.info(f"{log_tag} Pinterest API call completed in {api_duration:.2f}s")
            
            if not result.get("success"):
                error_msg = result.get("error_message", result.get("error"))
                Log.info(f"{log_tag} Failed to fetch ad accounts: {error_msg}")
                
                return jsonify({
                    "success": False,
                    "message": "Failed to fetch ad accounts from Pinterest",
                    "error": error_msg,
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            ad_accounts = result.get("data", {}).get("items", [])
            
            # Format response
            formatted = []
            for acc in ad_accounts:
                formatted.append({
                    "ad_account_id": acc.get("id"),
                    "name": acc.get("name"),
                    "currency": acc.get("currency"),
                    "country": acc.get("country"),
                    "owner_username": acc.get("owner", {}).get("username"),
                    "permissions": acc.get("permissions", []),
                    "created_time": acc.get("created_time"),
                })
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Retrieved {len(formatted)} ad accounts in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "data": formatted,
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to fetch ad accounts",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# CONNECT AD ACCOUNT
# =========================================
@blp_pinterest_ads.route("/social/pinterest/ad-accounts/connect", methods=["POST"])
class PinterestAdAccountConnectResource(MethodView):
    """
    Connect a Pinterest Ad Account to the business.
    """
    
    @token_required
    @blp_pinterest_ads.arguments(PinterestAccountConnectionSchema, location="query")
    @blp_pinterest_ads.response(200, PinterestAccountConnectionSchema)
    def post(self, body):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "pinterest_ads_resource.py",
            "PinterestAdAccountConnectResource",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Connecting Pinterest ad account")
        
        ad_account_id = body.get("ad_account_id")
        
        if not ad_account_id:
            return jsonify({
                "success": False,
                "message": "ad_account_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            # Check if already connected
            existing = PinterestAdAccount.get_by_ad_account_id(business_id, ad_account_id)
            if existing:
                return jsonify({
                    "success": False,
                    "message": "This ad account is already connected",
                    "code": "ALREADY_CONNECTED",
                }), HTTP_STATUS_CODES["CONFLICT"]
            
            # Get Pinterest access token
            pi_account = SocialAccount.get_destination(
                business_id=business_id, 
                user__id=user__id, 
                platform="pinterest", 
                destination_id=body.get("destination_id"),
            )
            
            
            if not pi_account:
                return jsonify({
                    "success": False,
                    "message": "Pinterest access token not found",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            access_token = pi_account.get("access_token")
            
            # Verify ad account access
            service = PinterestAdsService(access_token, ad_account_id)
            
            api_start = time.time()
            info_result = service.get_ad_account_info()
            api_duration = time.time() - api_start
            
            Log.info(f"{log_tag} Pinterest API call completed in {api_duration:.2f}s")
            
            if not info_result.get("success"):
                Log.info(f"{log_tag} Cannot access ad account: {info_result.get('error')}")
                return jsonify({
                    "success": False,
                    "message": "Cannot access this ad account. Make sure you have permission.",
                    "error": info_result.get("error_message", info_result.get("error")),
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            ad_account_info = info_result.get("data", {})
            
            # Save to database
            db_start = time.time()
            
            ad_account = PinterestAdAccount.create({
                "business_id": business_id,
                "user__id": user__id,
                "ad_account_id": ad_account_info.get("id"),
                "ad_account_name": ad_account_info.get("name"),
                "currency": ad_account_info.get("currency"),
                "country": ad_account_info.get("country"),
                "owner_username": ad_account_info.get("owner", {}).get("username"),
                "access_token": access_token,
                "permissions": ad_account_info.get("permissions", []),
            })
            
            db_duration = time.time() - db_start
            Log.info(f"{log_tag} Database save completed in {db_duration:.2f}s")
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Ad account connected successfully in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "message": "Pinterest ad account connected successfully",
                "data": {
                    "_id": ad_account["_id"],
                    "ad_account_id": ad_account["ad_account_id"],
                    "ad_account_name": ad_account["ad_account_name"],
                    "currency": ad_account["currency"],
                },
            }), HTTP_STATUS_CODES["CREATED"]
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to connect ad account",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST CONNECTED AD ACCOUNTS
# =========================================
@blp_pinterest_ads.route("/social/pinterest/ad-accounts", methods=["GET"])
class PinterestAdAccountsResource(MethodView):
    """
    List Pinterest ad accounts connected to this business.
    """
    
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "pinterest_ads_resource.py",
            "PinterestAdAccountsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Fetching connected Pinterest ad accounts")
        
        try:
            ad_accounts = PinterestAdAccount.list_by_business(business_id)
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Retrieved {len(ad_accounts)} ad accounts in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "data": ad_accounts,
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to fetch ad accounts",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST PINS (for promotion selection)
# =========================================
@blp_pinterest_ads.route("/social/pinterest/pins", methods=["GET"])
class PinterestPinsResource(MethodView):
    """
    List Pinterest pins that can be promoted.
    """
    
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "pinterest_ads_resource.py",
            "PinterestPinsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Fetching Pinterest pins")
        
        page_size = int(request.args.get("page_size", 25))
        bookmark = request.args.get("bookmark")
        board_id = request.args.get("board_id")
        
        try:
            # Get Pinterest access token
            token_info = _get_pinterest_access_token(business_id, user__id, log_tag)
            
            if not token_info.get("success"):
                return jsonify({
                    "success": False,
                    "message": token_info.get("error", "Pinterest access token not found"),
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            access_token = token_info["access_token"]
            service = PinterestAdsService(access_token)
            
            api_start = time.time()
            
            if board_id:
                result = service.get_board_pins(board_id, bookmark=bookmark, page_size=page_size)
            else:
                result = service.get_pins(bookmark=bookmark, page_size=page_size)
            
            api_duration = time.time() - api_start
            Log.info(f"{log_tag} Pinterest API call completed in {api_duration:.2f}s")
            
            if not result.get("success"):
                return jsonify({
                    "success": False,
                    "message": "Failed to fetch pins",
                    "error": result.get("error_message", result.get("error")),
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            pins = result.get("data", {}).get("items", [])
            next_bookmark = result.get("data", {}).get("bookmark")
            
            # Format pins
            formatted_pins = []
            for pin in pins:
                media = pin.get("media", {})
                images = media.get("images", {})
                
                formatted_pins.append({
                    "pin_id": pin.get("id"),
                    "title": pin.get("title"),
                    "description": pin.get("description"),
                    "link": pin.get("link"),
                    "media_type": media.get("media_type"),
                    "image_url": images.get("600x", {}).get("url") or images.get("400x300", {}).get("url"),
                    "created_at": pin.get("created_at"),
                    "board_id": pin.get("board_id"),
                    "can_promote": True,  # Most pins can be promoted
                })
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Retrieved {len(formatted_pins)} pins in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "data": {
                    "pins": formatted_pins,
                    "count": len(formatted_pins),
                    "bookmark": next_bookmark,
                },
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to fetch pins",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST BOARDS
# =========================================
@blp_pinterest_ads.route("/social/pinterest/boards", methods=["GET"])
class PinterestBoardsResource(MethodView):
    """
    List Pinterest boards.
    """
    
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "pinterest_ads_resource.py",
            "PinterestBoardsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Fetching Pinterest boards")
        
        try:
            token_info = _get_pinterest_access_token(business_id, user__id, log_tag)
            
            if not token_info.get("success"):
                return jsonify({
                    "success": False,
                    "message": token_info.get("error"),
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            service = PinterestAdsService(token_info["access_token"])
            
            api_start = time.time()
            result = service.get_boards()
            api_duration = time.time() - api_start
            
            Log.info(f"{log_tag} Pinterest API call completed in {api_duration:.2f}s")
            
            if not result.get("success"):
                return jsonify({
                    "success": False,
                    "message": "Failed to fetch boards",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            boards = result.get("data", {}).get("items", [])
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Retrieved {len(boards)} boards in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "data": boards,
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to fetch boards",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# PROMOTE PIN
# =========================================
@blp_pinterest_ads.route("/social/pinterest/promote-pin", methods=["POST"])
class PinterestPromotePinResource(MethodView):
    """
    Promote an existing Pinterest pin.
    
    Body:
    {
        "ad_account_id": "549755885175",
        "pin_id": "123456789012345678",
        "budget_amount": 1000,  // in cents ($10.00)
        "duration_days": 7,
        "objective": "AWARENESS",
        "targeting": {
            "geo_locations": ["US", "GB"],
            "age_bucket": ["25-34", "35-44"],
            "genders": ["female"],
            "interest_ids": ["947205316521"],
            "keywords": ["home decor", "interior design"]
        },
        "destination_url": "https://example.com/product",
        "auto_targeting_enabled": true
    }
    """
    
    @token_required
    def post(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "pinterest_ads_resource.py",
            "PinterestPromotePinResource",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Pinterest promote pin request received")
        
        body = request.get_json(silent=True) or {}
        
        # Extract parameters
        ad_account_id = body.get("ad_account_id")
        pin_id = body.get("pin_id")
        budget_amount = body.get("budget_amount", 500)  # cents
        duration_days = body.get("duration_days", 7)
        objective = body.get("objective", "AWARENESS")
        targeting_input = body.get("targeting", {})
        destination_url = body.get("destination_url")
        auto_targeting_enabled = body.get("auto_targeting_enabled", True)
        
        Log.info(
            f"{log_tag} Params: pin_id={pin_id} "
            f"budget={budget_amount} duration={duration_days}"
        )
        
        # =========================================
        # VALIDATION
        # =========================================
        if not ad_account_id:
            return jsonify({
                "success": False,
                "message": "ad_account_id is required",
                "code": "MISSING_AD_ACCOUNT_ID",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if not pin_id:
            return jsonify({
                "success": False,
                "message": "pin_id is required",
                "code": "MISSING_PIN_ID",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if budget_amount < 100:
            return jsonify({
                "success": False,
                "message": "Minimum budget is $1.00 (100 cents)",
                "code": "BUDGET_TOO_LOW",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if duration_days < 1 or duration_days > 90:
            return jsonify({
                "success": False,
                "message": "Duration must be between 1 and 90 days",
                "code": "INVALID_DURATION",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        valid_objectives = ["AWARENESS", "CONSIDERATION", "VIDEO_VIEW", "WEB_CONVERSION", "CATALOG_SALES"]
        if objective not in valid_objectives:
            return jsonify({
                "success": False,
                "message": f"Invalid objective. Must be one of: {', '.join(valid_objectives)}",
                "code": "INVALID_OBJECTIVE",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            # =========================================
            # GET AD ACCOUNT & ACCESS TOKEN
            # =========================================
            ad_account = PinterestAdAccount.get_by_ad_account_id(business_id, ad_account_id)
            
            if not ad_account or not ad_account.get("access_token_plain"):
                Log.warning(f"{log_tag} Missing ad account or token")
                return jsonify({
                    "success": False,
                    "message": "Ad account not connected or token missing",
                    "code": "NO_AD_ACCOUNT",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            access_token = ad_account["access_token_plain"]
            currency = ad_account.get("currency", "USD")
            
            # =========================================
            # BUILD TARGETING
            # =========================================
            service = PinterestAdsService(access_token, ad_account_id)
            
            targeting_spec = service.build_targeting_spec(
                geo_locations=targeting_input.get("geo_locations") or targeting_input.get("countries") or ["US"],
                age_bucket=targeting_input.get("age_bucket"),
                genders=targeting_input.get("genders"),
                interest_ids=targeting_input.get("interest_ids"),
                keywords=targeting_input.get("keywords"),
                audience_include=targeting_input.get("audience_include"),
                audience_exclude=targeting_input.get("audience_exclude"),
                locales=targeting_input.get("locales"),
            )
            
            Log.info(f"{log_tag} Targeting spec built: {json.dumps(targeting_spec, indent=2)}")
            
            # =========================================
            # PROMOTE THE PIN
            # =========================================
            Log.info(f"{log_tag} Sending promote request to Pinterest...")
            
            pinterest_start = time.time()
            
            result = service.promote_pin(
                pin_id=pin_id,
                budget_amount=budget_amount,
                duration_days=duration_days,
                objective_type=objective,
                targeting_spec=targeting_spec if targeting_spec else None,
                destination_url=destination_url,
                auto_targeting_enabled=auto_targeting_enabled,
            )
            
            pinterest_duration = time.time() - pinterest_start
            Log.info(f"{log_tag} Pinterest promote completed in {pinterest_duration:.2f}s")
            
            if not result.get("success"):
                errors = result.get("errors", [])
                error_messages = [e.get("error", str(e)) for e in errors]
                
                sweet_error = "Failed to promote pin"
                if errors and errors[0].get("details"):
                    details = errors[0].get("details", {})
                    if isinstance(details, dict):
                        sweet_error = details.get("message", sweet_error)
                
                Log.info(f"{log_tag} error_messages: {error_messages}")
                Log.info(f"{log_tag} Promote failed: {errors}")
                
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                    "message": sweet_error,
                    "message_to_show": sweet_error,
                    "error": errors,
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # =========================================
            # SAVE CAMPAIGN TO DATABASE
            # =========================================
            campaign = PinterestAdCampaign.create({
                "business_id": business_id,
                "user__id": user__id,
                "ad_account_id": ad_account_id,
                "campaign_name": f"Promote Pin {pin_id[-8:]}",
                "objective": objective,
                "budget_type": PinterestAdCampaign.BUDGET_LIFETIME,
                "budget_amount": budget_amount,
                "currency": currency,
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc) + timedelta(days=duration_days),
                "targeting_spec": targeting_spec,
                "pin_id": pin_id,
                "destination_url": destination_url,
                "pinterest_campaign_id": result.get("campaign_id"),
                "pinterest_ad_group_id": result.get("ad_group_id"),
                "pinterest_ad_id": result.get("ad_id"),
                "status": PinterestAdCampaign.STATUS_ACTIVE,
                "meta": {
                    "auto_targeting_enabled": auto_targeting_enabled,
                },
            })
            
            total_duration = time.time() - start_time
            Log.info(
                f"{log_tag} Pin promoted successfully campaign={campaign['_id']} "
                f"pinterest_campaign={result.get('campaign_id')} in {total_duration:.2f}s"
            )
            
            return jsonify({
                "success": True,
                "message": "Pin promoted successfully!",
                "data": {
                    "_id": campaign["_id"],
                    "pinterest_campaign_id": result.get("campaign_id"),
                    "pinterest_ad_group_id": result.get("ad_group_id"),
                    "pinterest_ad_id": result.get("ad_id"),
                    "pin_id": pin_id,
                    "budget": f"{currency} {budget_amount / 100:.2f}",
                    "duration_days": duration_days,
                    "status": "active",
                },
            }), HTTP_STATUS_CODES["CREATED"]
        
        except ValueError as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} ValueError after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": str(e),
                "code": "VALIDATION_ERROR",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to promote pin",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST CAMPAIGNS
# =========================================
@blp_pinterest_ads.route("/social/pinterest/campaigns", methods=["GET"])
class PinterestCampaignsResource(MethodView):
    """
    List Pinterest ad campaigns for the business.
    """
    
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "pinterest_ads_resource.py",
            "PinterestCampaignsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Fetching Pinterest campaigns")
        
        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 20))
            status = request.args.get("status")
            
            result = PinterestAdCampaign.list_by_business(
                business_id=business_id,
                status=status,
                page=page,
                per_page=per_page,
            )
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Retrieved {len(result['items'])} campaigns in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "data": result["items"],
                "pagination": {
                    "total_count": result["total_count"],
                    "total_pages": result["total_pages"],
                    "current_page": result["current_page"],
                    "per_page": result["per_page"],
                },
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to fetch campaigns",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# GET CAMPAIGN INSIGHTS
# =========================================
@blp_pinterest_ads.route("/social/pinterest/campaigns/<campaign_id>/insights", methods=["GET"])
class PinterestCampaignInsightsResource(MethodView):
    """
    Get performance insights for a Pinterest campaign.
    """
    
    @token_required
    def get(self, campaign_id: str):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        
        log_tag = f"[pinterest_ads_resource.py][CampaignInsights][{campaign_id}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Fetching campaign insights")
        
        try:
            # Date range params
            end_date = request.args.get("end_date", datetime.now().strftime("%Y-%m-%d"))
            start_date = request.args.get(
                "start_date",
                (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            )
            granularity = request.args.get("granularity", "DAY")
            
            # Get campaign
            campaign = PinterestAdCampaign.get_by_id(campaign_id, business_id)
            if not campaign:
                return jsonify({
                    "success": False,
                    "message": "Campaign not found",
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            if not campaign.get("pinterest_campaign_id"):
                return jsonify({
                    "success": False,
                    "message": "Campaign not synced with Pinterest",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # Get ad account
            ad_account = PinterestAdAccount.get_by_ad_account_id(
                business_id, campaign["ad_account_id"]
            )
            
            if not ad_account or not ad_account.get("access_token_plain"):
                return jsonify({
                    "success": False,
                    "message": "Ad account not found or token missing",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            service = PinterestAdsService(
                ad_account["access_token_plain"],
                campaign["ad_account_id"],
            )
            
            api_start = time.time()
            result = service.get_campaign_analytics(
                campaign_ids=[campaign["pinterest_campaign_id"]],
                start_date=start_date,
                end_date=end_date,
                granularity=granularity,
            )
            api_end = time.time() 
            
            
            api_duration = api_start - api_end
            Log.info(f"{log_tag} Pinterest API call completed in {api_duration:.2f}s")
            
            if not result.get("success"):
                return jsonify({
                    "success": False,
                    "message": "Failed to fetch insights",
                    "error": result.get("error_message", result.get("error")),
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            insights_data = result.get("data", [])
            
            # Update campaign results in database
            if insights_data:
                # Aggregate totals
                totals = {
                    "impressions": 0,
                    "clicks": 0,
                    "saves": 0,
                    "spend_micro": 0,
                }
                
                for row in insights_data:
                    totals["impressions"] += row.get("IMPRESSION", 0)
                    totals["clicks"] += row.get("CLICKTHROUGH", 0)
                    totals["saves"] += row.get("SAVE", 0)
                    totals["spend_micro"] += row.get("SPEND_IN_MICRO_DOLLAR", 0)
                
                # Calculate rates
                if totals["impressions"] > 0:
                    totals["ctr"] = (totals["clicks"] / totals["impressions"]) * 100
                    totals["cpm_micro"] = (totals["spend_micro"] / totals["impressions"]) * 1000
                else:
                    totals["ctr"] = 0
                    totals["cpm_micro"] = 0
                
                if totals["clicks"] > 0:
                    totals["cpc_micro"] = totals["spend_micro"] / totals["clicks"]
                else:
                    totals["cpc_micro"] = 0
                
                PinterestAdCampaign.update_results(campaign_id, business_id, totals)
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Insights fetched in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "data": {
                    "insights": insights_data,
                    "date_range": {
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    "granularity": granularity,
                },
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to fetch insights",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# PAUSE CAMPAIGN
# =========================================
@blp_pinterest_ads.route("/social/pinterest/campaigns/<campaign_id>/pause", methods=["POST"])
class PinterestCampaignPauseResource(MethodView):
    """Pause a Pinterest campaign."""
    
    @token_required
    def post(self, campaign_id: str):
        return _update_pinterest_campaign_status(campaign_id, "PAUSED", PinterestAdCampaign.STATUS_PAUSED)


# =========================================
# RESUME CAMPAIGN
# =========================================
@blp_pinterest_ads.route("/social/pinterest/campaigns/<campaign_id>/resume", methods=["POST"])
class PinterestCampaignResumeResource(MethodView):
    """Resume a paused Pinterest campaign."""
    
    @token_required
    def post(self, campaign_id: str):
        return _update_pinterest_campaign_status(campaign_id, "ACTIVE", PinterestAdCampaign.STATUS_ACTIVE)


# =========================================
# ARCHIVE CAMPAIGN
# =========================================
@blp_pinterest_ads.route("/social/pinterest/campaigns/<campaign_id>/archive", methods=["POST"])
class PinterestCampaignArchiveResource(MethodView):
    """Archive a Pinterest campaign."""
    
    @token_required
    def post(self, campaign_id: str):
        return _update_pinterest_campaign_status(campaign_id, "ARCHIVED", PinterestAdCampaign.STATUS_ARCHIVED)


def _update_pinterest_campaign_status(campaign_id: str, pinterest_status: str, local_status: str):
    """Helper to update Pinterest campaign status on Pinterest and locally."""
    client_ip = request.remote_addr
    user = g.get("current_user", {}) or {}
    business_id = str(user.get("business_id", ""))
    
    log_tag = f"[pinterest_ads_resource.py][UpdateCampaignStatus][{campaign_id}]"
    
    start_time = time.time()
    Log.info(f"{log_tag} Updating campaign status to {pinterest_status}")
    
    campaign = PinterestAdCampaign.get_by_id(campaign_id, business_id)
    if not campaign:
        Log.info(f"{log_tag} Campaign not found")
        return jsonify({
            "success": False,
            "message": "Campaign not found",
        }), HTTP_STATUS_CODES["NOT_FOUND"]
    
    if not campaign.get("pinterest_campaign_id"):
        return jsonify({
            "success": False,
            "message": "Campaign not synced with Pinterest",
        }), HTTP_STATUS_CODES["BAD_REQUEST"]
    
    ad_account = PinterestAdAccount.get_by_ad_account_id(business_id, campaign["ad_account_id"])
    if not ad_account or not ad_account.get("access_token_plain"):
        return jsonify({
            "success": False,
            "message": "Ad account not found or token missing",
        }), HTTP_STATUS_CODES["BAD_REQUEST"]
    
    try:
        service = PinterestAdsService(
            ad_account["access_token_plain"],
            campaign["ad_account_id"]
        )
        
        api_start = time.time()
        result = service.update_campaign_status(campaign["pinterest_campaign_id"], pinterest_status)
        api_duration = time.time() - api_start
        
        Log.info(f"{log_tag} Pinterest API call completed in {api_duration:.2f}s")
        
        if not result.get("success"):
            return jsonify({
                "success": False,
                "message": "Failed to update campaign status",
                "error": result.get("error_message", result.get("error")),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        # Update local status
        PinterestAdCampaign.update_status(campaign_id, business_id, local_status)
        
        duration = time.time() - start_time
        Log.info(f"{log_tag} Campaign status updated to {pinterest_status} in {duration:.2f}s")
        
        return jsonify({
            "success": True,
            "message": f"Campaign {pinterest_status.lower()} successfully",
        }), HTTP_STATUS_CODES["OK"]
    
    except Exception as e:
        duration = time.time() - start_time
        Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
        
        return jsonify({
            "success": False,
            "message": "Failed to update campaign status",
        }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# SEARCH INTERESTS (for targeting)
# =========================================
@blp_pinterest_ads.route("/social/pinterest/targeting/interests", methods=["GET"])
class PinterestTargetingInterestsResource(MethodView):
    """
    Get available interest targeting options.
    """
    
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "pinterest_ads_resource.py",
            "PinterestTargetingInterestsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Fetching Pinterest targeting interests")
        
        try:
            # Get any ad account for the request
            ad_accounts = PinterestAdAccount.list_by_business(business_id)
            if not ad_accounts:
                return jsonify({
                    "success": False,
                    "message": "No ad account connected",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            ad_account = PinterestAdAccount.get_by_id(ad_accounts[0]["_id"], business_id)
            if not ad_account or not ad_account.get("access_token_plain"):
                return jsonify({
                    "success": False,
                    "message": "Ad account token not found",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            service = PinterestAdsService(
                ad_account["access_token_plain"],
                ad_account["ad_account_id"]
            )
            
            api_start = time.time()
            result = service.get_targeting_options("INTEREST")
            api_duration = time.time() - api_start
            
            Log.info(f"{log_tag} Pinterest API call completed in {api_duration:.2f}s")
            
            if not result.get("success"):
                return jsonify({
                    "success": False,
                    "message": "Failed to fetch interests",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            interests = result.get("data", {}).get("items", [])
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Retrieved {len(interests)} interests in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "data": interests,
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to fetch interests",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# GET AUDIENCES
# =========================================
@blp_pinterest_ads.route("/social/pinterest/audiences", methods=["GET"])
class PinterestAudiencesResource(MethodView):
    """
    List custom audiences for targeting.
    """
    
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "pinterest_ads_resource.py",
            "PinterestAudiencesResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Fetching Pinterest audiences")
        
        ad_account_id = request.args.get("ad_account_id")
        
        if not ad_account_id:
            return jsonify({
                "success": False,
                "message": "ad_account_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            ad_account = PinterestAdAccount.get_by_ad_account_id(business_id, ad_account_id)
            if not ad_account or not ad_account.get("access_token_plain"):
                return jsonify({
                    "success": False,
                    "message": "Ad account not found or token missing",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            service = PinterestAdsService(
                ad_account["access_token_plain"],
                ad_account_id
            )
            
            api_start = time.time()
            result = service.get_audiences()
            api_duration = time.time() - api_start
            
            Log.info(f"{log_tag} Pinterest API call completed in {api_duration:.2f}s")
            
            if not result.get("success"):
                return jsonify({
                    "success": False,
                    "message": "Failed to fetch audiences",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            audiences = result.get("data", {}).get("items", [])
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Retrieved {len(audiences)} audiences in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "data": audiences,
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to fetch audiences",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# GET PIN ANALYTICS
# =========================================
@blp_pinterest_ads.route("/social/pinterest/pins/<pin_id>/analytics", methods=["GET"])
class PinterestPinAnalyticsResource(MethodView):
    """
    Get analytics for a specific pin.
    """
    
    @token_required
    def get(self, pin_id: str):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        
        log_tag = f"[pinterest_ads_resource.py][PinAnalytics][{pin_id}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Fetching pin analytics")
        
        try:
            # Date range params
            end_date = request.args.get("end_date", datetime.now().strftime("%Y-%m-%d"))
            start_date = request.args.get(
                "start_date",
                (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            )
            
            # Get Pinterest access token
            token_info = _get_pinterest_access_token(business_id, user__id, log_tag)
            
            if not token_info.get("success"):
                return jsonify({
                    "success": False,
                    "message": token_info.get("error"),
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            service = PinterestAdsService(token_info["access_token"])
            
            api_start = time.time()
            result = service.get_pin_analytics(
                pin_id=pin_id,
                start_date=start_date,
                end_date=end_date,
            )
            api_duration = time.time() - api_start
            
            Log.info(f"{log_tag} Pinterest API call completed in {api_duration:.2f}s")
            
            if not result.get("success"):
                return jsonify({
                    "success": False,
                    "message": "Failed to fetch pin analytics",
                    "error": result.get("error_message", result.get("error")),
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Pin analytics fetched in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "data": {
                    "pin_id": pin_id,
                    "analytics": result.get("data", {}),
                    "date_range": {
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                },
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to fetch pin analytics",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]