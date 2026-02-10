# app/routes/social/facebook_ads_resource.py

import os, json
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
from ....utils.json_response import prepared_response

from ....models.social.social_account import SocialAccount
from ....models.social.ad_account import AdAccount, AdCampaign
from ....services.social.facebook_ads_service import FacebookAdsService

#schemas
from ....schemas.social.social_schema import (
    AccountConnectionSchema, AddsAccountConnectionSchema, FacebookBoostPostSchema
)


blp_facebook_ads = Blueprint("facebook_ads", __name__)


def _update_campaign_status(campaign_id: str, fb_status: str, local_status: str):
    """Helper to update campaign status on Facebook and locally."""
    user = g.get("current_user", {}) or {}
    business_id = str(user.get("business_id", ""))
    
    log_tag = f"[facebook_ads_resource.py][UpdateCampaignStatus][{campaign_id}]"
    
    campaign = AdCampaign.get_by_id(campaign_id, business_id)
    if not campaign:
        Log.info(f"{log_tag} Campaign not found. campaign_id={campaign_id}")
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
            "message": "Campaign not found",
        }), HTTP_STATUS_CODES["NOT_FOUND"]
    
    if not campaign.get("fb_campaign_id"):
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
            "message": "Campaign not synced with Facebook",
        }), HTTP_STATUS_CODES["BAD_REQUEST"]
    
    ad_account = AdAccount.get_by_ad_account_id(business_id, campaign["ad_account_id"])
    if not ad_account or not ad_account.get("access_token_plain"):
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
            "message": "Ad account not found or token missing",
        }), HTTP_STATUS_CODES["BAD_REQUEST"]
    
    try:
        service = FacebookAdsService(
            ad_account["access_token_plain"],
            campaign["ad_account_id"]
        )
        
        result = service.update_campaign_status(campaign["fb_campaign_id"], fb_status)
        
        if not result.get("success"):
            return jsonify({
                "success": False,
                "message": f"Failed to update campaign status",
                "error": result.get("error_message", result.get("error")),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        # Update local status
        AdCampaign.update_status(campaign_id, business_id, local_status)
        
        return jsonify({
            "success": True,
            "message": f"Campaign {fb_status.lower()} successfully",
        }), HTTP_STATUS_CODES["OK"]
    
    except Exception as e:
        Log.error(f"{log_tag} Exception: {e}")
        return jsonify({
            "success": False,
            "message": "Failed to update campaign status",
        }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST USER'S AD ACCOUNTS (from Facebook)
# =========================================
@blp_facebook_ads.route("/social/facebook/ad-accounts/available", methods=["GET"])
class FacebookAdAccountsAvailableResource(MethodView):
    @token_required
    @blp_facebook_ads.arguments(AccountConnectionSchema, location="query")
    @blp_facebook_ads.response(200, AccountConnectionSchema)
    def get(self, item_data):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "facebook_ads_resource.py",
            "FacebookAdAccountsAvailableResource",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id
        )
        
        fb_account = SocialAccount.get_destination(
            business_id=business_id, 
            user__id=user__id, 
            platform="facebook", 
            destination_id=item_data.get("destination_id"),
        )
        
        if not fb_account:
            return jsonify({
                "success": False,
                "message": "Facebook account not found.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        # ✅ Use user_access_token from meta (for ads), fallback to page token
        meta = fb_account.get("meta", {}) or {}
        user_access_token = meta.get("user_access_token")
        
        if not user_access_token:
            # Fallback to page token (may work for some ad account operations)
            user_access_token = fb_account.get("access_token_plain")
        
        if not user_access_token:
            return jsonify({
                "success": False,
                "message": "Facebook access token not found. Please reconnect your Facebook account.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            start_time = time.time()
            
            # ✅ Create service without ad_account_id (not needed for listing)
            service = FacebookAdsService(user_access_token)
            result = service.get_user_ad_accounts()
            
            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag}[{client_ip}] Fetching ad accounts completed in {duration:.2f} seconds")
        
            
            if not result.get("success"):
                error = result.get("error", {})
                error_message = error.get("message") if isinstance(error, dict) else str(error)
                
                Log.info(f"{log_tag} Failed to fetch ad accounts: {error}")
                
                # Check for permission errors
                if "permission" in error_message.lower() or "scope" in error_message.lower():
                    return jsonify({
                        "success": False,
                        "message": "Missing ads permissions. Please reconnect your Facebook account to grant ads access.",
                        "code": "MISSING_ADS_PERMISSION",
                        "error": error_message,
                    }), HTTP_STATUS_CODES["FORBIDDEN"]
                
                return jsonify({
                    "success": False,
                    "message": "Failed to fetch ad accounts from Facebook",
                    "error": error_message,
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            ad_accounts = result.get("data", {}).get("data", [])
            
            # Format response
            formatted = []
            for acc in ad_accounts:
                formatted.append({
                    "ad_account_id": acc.get("id"),
                    "account_id": acc.get("account_id"),
                    "name": acc.get("name"),
                    "currency": acc.get("currency"),
                    "timezone": acc.get("timezone_name"),
                    "status": AdAccount.FB_ACCOUNT_STATUS.get(acc.get("account_status"), "UNKNOWN"),
                    "amount_spent": acc.get("amount_spent"),
                    "balance": acc.get("balance"),
                    "spend_cap": acc.get("spend_cap"),
                })
            
            return jsonify({
                "success": True,
                "data": formatted,
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch ad accounts",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# CONNECT AD ACCOUNT
# =========================================
@blp_facebook_ads.route("/social/facebook/ad-accounts/connect", methods=["POST"])
class FacebookAdAccountConnectResource(MethodView):
    """
    Connect a Facebook Ad Account to the business.
    """
    @token_required
    @blp_facebook_ads.arguments(AddsAccountConnectionSchema, location="form")
    @blp_facebook_ads.response(200, AddsAccountConnectionSchema)
    def post(self, body):
        client_ip = request.remote_addr
        
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "facebook_ads_resource.py",
            "FacebookAdAccountConnectResource",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id
        )
        
        ad_account_id = body.get("ad_account_id")
        page_id = body.get("page_id")  # Optional: link to specific page
        
        if not ad_account_id:
            Log.info(f"{log_tag} ad_account_id is required")
            return jsonify({
                "success": False,
                "message": "ad_account_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
            
        # Get Facebook access token
        fb_accounts = SocialAccount.list_destinations(business_id, user__id, "facebook")
        
        if not fb_accounts:
            Log.info(f"{log_tag} No Facebook account connected.")
            return jsonify({
                "success": False,
                "message": "No Facebook account connected.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        fb_account = SocialAccount.get_destination(
            business_id, user__id, "facebook",
            fb_accounts[0].get("destination_id")
        )
        
        if not fb_account or not fb_account.get("access_token_plain"):
            Log.info(f"{log_tag} Facebook access token not found.")
            return jsonify({
                "success": False,
                "message": "Facebook access token not found.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        access_token = fb_account["access_token_plain"]
        
        # Check if already connected
        existing = AdAccount.get_by_ad_account_id(business_id, ad_account_id)
        if existing:
            Log.info(f"{log_tag} This ad account is already connected.")
            return jsonify({
                "success": False,
                "message": "This ad account is already connected.",
                "code": "ALREADY_CONNECTED",
            }), HTTP_STATUS_CODES["CONFLICT"]
        
        # Verify ad account access
        try:
            service = FacebookAdsService(access_token, ad_account_id)
            info_result = service.get_ad_account_info()
            
            if not info_result.get("success"):
                Log.info(f"{log_tag} Cannot access ad account: {info_result.get('error')}")
                return jsonify({
                    "success": False,
                    "message": "Cannot access this ad account. Make sure you have admin access.",
                    "error": info_result.get("error_message", info_result.get("error")),
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            ad_account_info = info_result.get("data", {})
            
            # Get page info if provided
            page_name = None
            if page_id:
                page_account = SocialAccount.find_destination(business_id, "facebook", page_id)
                if page_account:
                    page_name = page_account.get("destination_name")
            
            
            start_time = time.time()
             
            # Save to database
            ad_account = AdAccount.create({
                "business_id": business_id,
                "user__id": user__id,
                "ad_account_id": ad_account_info.get("id"),
                "ad_account_name": ad_account_info.get("name"),
                "currency": ad_account_info.get("currency"),
                "timezone_name": ad_account_info.get("timezone_name"),
                "fb_account_status": ad_account_info.get("account_status"),
                "page_id": page_id,
                "page_name": page_name,
                "business_manager_id": ad_account_info.get("business", {}).get("id"),
                "access_token": access_token,
            })
            
            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag}[{client_ip}] Creating AdAccount completed in {duration:.2f} seconds")
        
            
            return jsonify({
                "success": True,
                "message": "Ad account connected successfully",
                "data": {
                    "_id": ad_account["_id"],
                    "ad_account_id": ad_account["ad_account_id"],
                    "ad_account_name": ad_account["ad_account_name"],
                    "currency": ad_account["currency"],
                },
            }), HTTP_STATUS_CODES["CREATED"]
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to connect ad account",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# =========================================
# LIST CONNECTED AD ACCOUNTS
# =========================================
@blp_facebook_ads.route("/social/facebook/ad-accounts", methods=["GET"])
class FacebookAdAccountsResource(MethodView):
    """
    List ad accounts connected to this business.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "facebook_ads_resource.py",
            "FacebookAdAccountsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        start_time = time.time()
        Log.info(f"{log_tag} Fetching connected ad accounts...")

        try:
            ad_accounts = AdAccount.list_by_business(business_id)

            duration = time.time() - start_time
            Log.info(f"{log_tag} Retrieved {len(ad_accounts)} ad accounts in {duration:.2f}s")

            return jsonify({
                "success": True,
                "data": ad_accounts,
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Failed after {duration:.2f}s err={e}")

            return jsonify({
                "success": False,
                "message": "Failed to retrieve ad accounts",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# =========================================
# BOOST POST
# =========================================
@blp_facebook_ads.route("/social/facebook/boost-post", methods=["POST"])
class FacebookBoostPostResource(MethodView):

    @token_required
    @blp_facebook_ads.arguments(FacebookBoostPostSchema, location="json")
    def post(self, body):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "facebook_ads_resource.py",
            "FacebookBoostPostResource",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        start_time = time.time()
        Log.info(f"{log_tag} Boost post request received")

        try:
            ad_account_id = body["ad_account_id"]
            page_id = body["page_id"]
            post_id = body["post_id"]
            budget_amount = body["budget_amount"]
            duration_days = body["duration_days"]
            targeting_input = body.get("targeting", {})
            scheduled_post_id = body.get("scheduled_post_id")
            is_adset_budget_sharing_enabled = body.get("is_adset_budget_sharing_enabled", False)

            Log.info(
                f"{log_tag} Params post_id={post_id} "
                f"budget={budget_amount} duration={duration_days}"
            )

            # -------------------------------------------------
            # Resolve access token
            # -------------------------------------------------
            ad_account = AdAccount.get_by_ad_account_id(business_id, ad_account_id)
            if not ad_account or not ad_account.get("access_token_plain"):
                Log.warning(f"{log_tag} Missing ad account or token")
                return jsonify({
                    "success": False,
                    "message": "Ad account not connected or token missing",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            access_token = ad_account["access_token_plain"]
            currency = ad_account.get("currency", "USD")

            service = FacebookAdsService(access_token, ad_account_id)

            # -------------------------------------------------
            # Build targeting
            # -------------------------------------------------
            targeting = service.build_targeting(
                countries=targeting_input.get("countries") or ["US"],
                age_min=targeting_input.get("age_min", 18),
                age_max=targeting_input.get("age_max", 65),
                genders=targeting_input.get("genders"),
                interests=targeting_input.get("interests"),
                behaviors=targeting_input.get("behaviors"),
            )

            Log.info(f"{log_tag} Targeting built successfully")

            # -------------------------------------------------
            # Boost post
            # -------------------------------------------------
            Log.info(f"{log_tag} Sending boost request to Facebook")

            fb_start = time.time()
            result = service.boost_post(
                page_id=page_id,
                post_id=post_id,
                budget_amount=budget_amount,
                duration_days=duration_days,
                targeting=targeting,
                is_adset_budget_sharing_enabled=is_adset_budget_sharing_enabled,
            )
            fb_duration = time.time() - fb_start

            Log.info(f"{log_tag} Facebook boost completed in {fb_duration:.2f}s")

            if not result.get("success"):
                errors = result.get("errors", [])
                error_messages = [e.get("error", str(e)) for e in errors]
                
                sweet_error_object = errors[0].get("details")
                
                Log.info(f"{log_tag} error_messages: {error_messages}")
                Log.info(f"{log_tag} Boost failed: {errors}")
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                    "message": sweet_error_object.get("error_user_msg"),
                    "message_to_show": sweet_error_object.get("error_user_msg"),
                    "error": errors,
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            # -------------------------------------------------
            # Persist campaign
            # -------------------------------------------------
            campaign = AdCampaign.create({
                "business_id": business_id,
                "user__id": user__id,
                "ad_account_id": ad_account_id,
                "page_id": page_id,
                "campaign_name": f"Boost Post {post_id[-8:]}",
                "objective": AdCampaign.OBJECTIVE_ENGAGEMENT,
                "budget_type": AdCampaign.BUDGET_LIFETIME,
                "budget_amount": budget_amount,
                "currency": currency,
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc) + timedelta(days=duration_days),
                "targeting": targeting,
                "scheduled_post_id": scheduled_post_id,
                "post_id": post_id,
                "fb_campaign_id": result.get("campaign_id"),
                "fb_adset_id": result.get("adset_id"),
                "fb_ad_id": result.get("ad_id"),
                "status": AdCampaign.STATUS_ACTIVE,
            })

            total_duration = time.time() - start_time
            Log.info(
                f"{log_tag} Boost successful campaign={campaign['_id']} "
                f"in {total_duration:.2f}s"
            )

            return jsonify({
                "success": True,
                "data": {
                    "_id": campaign["_id"],
                    "fb_campaign_id": result.get("campaign_id"),
                    "fb_adset_id": result.get("adset_id"),
                    "fb_ad_id": result.get("ad_id"),
                    "budget": f"{currency} {budget_amount / 100:.2f}",
                    "duration_days": duration_days,
                },
            }), HTTP_STATUS_CODES["CREATED"]

        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s err={e}")

            return jsonify({
                "success": False,
                "message": "Failed to boost post",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST CAMPAIGNS
# =========================================
@blp_facebook_ads.route("/social/facebook/campaigns", methods=["GET"])
class FacebookCampaignsResource(MethodView):

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "facebook_ads_resource.py",
            "FacebookCampaignsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        start_time = time.time()
        Log.info(f"{log_tag} Fetching campaigns")

        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 20))
            status = request.args.get("status")

            result = AdCampaign.list_by_business(
                business_id=business_id,
                status=status,
                page=page,
                per_page=per_page,
            )

            duration = time.time() - start_time
            Log.info(f"{log_tag} Retrieved campaigns in {duration:.2f}s")

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
            Log.error(f"{log_tag} Failed after {duration:.2f}s err={e}")

            return jsonify({
                "success": False,
                "message": "Failed to fetch campaigns",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# GET CAMPAIGN INSIGHTS
# =========================================
@blp_facebook_ads.route("/social/facebook/campaigns/<campaign_id>/insights", methods=["GET"])
class FacebookCampaignInsightsResource(MethodView):
    @token_required
    def get(self, campaign_id):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))

        log_tag = make_log_tag(
            "facebook_ads_resource.py",
            "FacebookCampaignInsightsResource",
            "get",
            client_ip,
            user.get("_id"),
            user.get("account_type"),
            business_id,
            business_id,
        )

        start_time = time.time()
        Log.info(f"{log_tag} Fetching insights for. campaign={campaign_id}")

        try:
            date_preset = request.args.get("date_preset", "last_7d")

            campaign = AdCampaign.get_by_id(campaign_id, business_id)
            if not campaign:
                Log.info(f"{log_tag} Campaign not found. campaign={campaign_id}")
                return jsonify({"success": False, "message": "Campaign not found"}), 404

            ad_account = AdAccount.get_by_ad_account_id(business_id, campaign["ad_account_id"])
            service = FacebookAdsService(
                ad_account["access_token_plain"],
                campaign["ad_account_id"],
            )

            result = service.get_campaign_insights(
                campaign["fb_campaign_id"],
                date_preset=date_preset,
            )

            duration = time.time() - start_time
            Log.info(f"{log_tag} Insights fetched in {duration:.2f}s")

            return jsonify({
                "success": True,
                "data": result.get("data", {}).get("data", []),
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Failed after {duration:.2f}s err={e}")

            return jsonify({
                "success": False,
                "message": "Failed to fetch insights",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# =========================================
# PAUSE CAMPAIGN
# =========================================
@blp_facebook_ads.route("/social/facebook/campaigns/<campaign_id>/pause", methods=["POST"])
class FacebookCampaignPauseResource(MethodView):
    """Pause a campaign."""
    
    @token_required
    def post(self, campaign_id: str):
        return _update_campaign_status(campaign_id, "PAUSED", AdCampaign.STATUS_PAUSED)


# =========================================
# RESUME CAMPAIGN
# =========================================
@blp_facebook_ads.route("/social/facebook/campaigns/<campaign_id>/resume", methods=["POST"])
class FacebookCampaignResumeResource(MethodView):
    """Resume a paused campaign."""
    
    @token_required
    def post(self, campaign_id: str):
        return _update_campaign_status(campaign_id, "ACTIVE", AdCampaign.STATUS_ACTIVE)

# =========================================
# SEARCH INTERESTS
# =========================================
@blp_facebook_ads.route("/social/facebook/targeting/interests", methods=["GET"])
class FacebookTargetingInterestsResource(MethodView):
    """Search for interest targeting options."""
    
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "facebook_ads_resource.py",
            "FacebookTargetingInterestsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        fb_start = time.time()
        Log.info(f"{log_tag} Fetching targeting interests")
        
        query = request.args.get("q", "")
        if not query or len(query) < 2:
            return jsonify({
                "success": False,
                "message": "Query must be at least 2 characters",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        # Get any ad account for the search
        ad_accounts = AdAccount.list_by_business(business_id)
        if not ad_accounts:
            return jsonify({
                "success": False,
                "message": "No ad account connected",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        ad_account = AdAccount.get_by_id(ad_accounts[0]["_id"], business_id)
        if not ad_account or not ad_account.get("access_token_plain"):
            return jsonify({
                "success": False,
                "message": "Ad account token not found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            service = FacebookAdsService(
                ad_account["access_token_plain"],
                ad_account["ad_account_id"]
            )
            
            result = service.search_interests(query)
            
            fb_duration = time.time() - fb_start

            Log.info(f"{log_tag} Facebook search interests in {fb_duration:.2f}s")
            
            if not result.get("success"):
                return jsonify({
                    "success": False,
                    "message": "Failed to search interests",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            interests = result.get("data", {}).get("data", [])
            
            return jsonify({
                "success": True,
                "data": [
                    {
                        "id": i.get("id"),
                        "name": i.get("name"),
                        "audience_size": i.get("audience_size"),
                        "path": i.get("path"),
                    }
                    for i in interests
                ],
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            return jsonify({
                "success": False,
                "message": "Failed to search interests",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# FACEBOOK REACH ESTIMATE
# =========================================
@blp_facebook_ads.route("/social/facebook/reach-estimate", methods=["GET"])
class FacebookReachEstimateResource(MethodView):
    """
    Estimate audience reach for a given targeting spec.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "facebook_ads_resource.py",
            "FacebookReachEstimateResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        start_time = time.time()
        Log.info(f"{log_tag} Reach estimate request started")

        ad_account_id = request.args.get("ad_account_id")
        targeting_raw = request.args.get("targeting")

        if not ad_account_id:
            return jsonify({
                "success": False,
                "message": "ad_account_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # normalize ad account id (avoid act_act_)
        if not ad_account_id.startswith("act_"):
            ad_account_id = f"act_{ad_account_id}"

        # Parse targeting JSON
        try:
            targeting = json.loads(targeting_raw) if targeting_raw else {}
        except Exception:
            return jsonify({
                "success": False,
                "message": "Invalid targeting JSON",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Get ad account
        ad_account = AdAccount.get_by_ad_account_id(business_id, ad_account_id)
        if not ad_account or not ad_account.get("access_token"):
            return jsonify({
                "success": False,
                "message": "Ad account not found or token missing",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            service = FacebookAdsService(
                ad_account["access_token"],
                ad_account_id,
            )

            result = service.get_reach_estimate(targeting)

            duration = time.time() - start_time
            Log.info(f"{log_tag} Reach estimate completed in {duration:.2f}s")

            if not result.get("success"):
                Log.error(f"{log_tag} Reach estimate failed: {result.get('error')}")
                return jsonify(result), HTTP_STATUS_CODES["BAD_REQUEST"]

            return jsonify({
                "success": True,
                "data": {
                    "users_lower_bound": result["data"].get("users_lower_bound"),
                    "users_upper_bound": result["data"].get("users_upper_bound"),
                },
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to estimate reach",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]














