# app/routes/social/instagram_ads_resource.py

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
from ....utils.json_response import prepared_response

from ....models.social.social_account import SocialAccount
from ....models.social.ad_account import AdAccount, AdCampaign
from ....services.social.facebook_ads_service import FacebookAdsService

# Schemas
from ....schemas.social.social_schema import (
    InstagramBoostPostSchema,
    InstagramMediaListSchema,
)


blp_instagram_ads = Blueprint("instagram_ads", __name__)


# =========================================
# HELPER: Get Instagram Account from Page
# =========================================
def _get_instagram_account_for_page(
    business_id: str,
    user__id: str,
    page_id: str,
    log_tag: str,
) -> dict:
    """
    Get Instagram Business Account linked to a Facebook Page.
    
    Returns:
        {
            "success": True/False,
            "instagram_account_id": "....",
            "instagram_username": "....",
            "access_token": "....",
            "error": "...."
        }
    """
    result = {
        "success": False,
        "instagram_account_id": None,
        "instagram_username": None,
        "access_token": None,
        "error": None,
    }
    
    # First try to get from Instagram social account directly
    ig_accounts = SocialAccount.list_destinations(business_id, user__id, "instagram")
    
    for ig_acc in ig_accounts:
        ig_full = SocialAccount.get_destination(
            business_id, user__id, "instagram", ig_acc.get("destination_id")
        )
        if ig_full:
            meta = ig_full.get("meta", {}) or {}
            # Check if this IG account is linked to the specified page
            if meta.get("page_id") == page_id or not page_id:
                result["success"] = True
                result["instagram_account_id"] = ig_full.get("destination_id") or meta.get("ig_user_id")
                result["instagram_username"] = ig_full.get("platform_username") or meta.get("ig_username")
                result["access_token"] = ig_full.get("access_token_plain")
                Log.info(f"{log_tag} Found Instagram account from social_accounts: {result['instagram_account_id']}")
                return result
    
    # Fallback: Get from Facebook page connection
    fb_account = SocialAccount.find_destination(business_id, "facebook", page_id)
    if not fb_account:
        result["error"] = "Facebook page not found"
        return result
    
    fb_full = SocialAccount.get_destination(
        business_id,
        fb_account.get("user__id") or user__id,
        "facebook",
        page_id,
    )
    
    if not fb_full:
        result["error"] = "Facebook page details not found"
        return result
    
    meta = fb_full.get("meta", {}) or {}
    access_token = meta.get("user_access_token") or fb_full.get("access_token_plain")
    
    if not access_token:
        result["error"] = "Access token not found"
        return result
    
    # Query Facebook API for linked Instagram account
    try:
        service = FacebookAdsService(access_token)
        ig_result = service.get_instagram_account_from_page(page_id)
        
        if not ig_result.get("success"):
            result["error"] = f"Failed to get Instagram account: {ig_result.get('error_message', ig_result.get('error'))}"
            return result
        
        ig_data = ig_result.get("data", {}).get("instagram_business_account", {})
        
        if not ig_data.get("id"):
            result["error"] = "No Instagram Business Account linked to this Facebook Page"
            return result
        
        result["success"] = True
        result["instagram_account_id"] = ig_data.get("id")
        result["instagram_username"] = ig_data.get("username")
        result["access_token"] = access_token
        
        Log.info(f"{log_tag} Found Instagram account from FB API: {result['instagram_account_id']}")
        return result
        
    except Exception as e:
        result["error"] = str(e)
        return result


# =========================================
# GET INSTAGRAM ACCOUNT FOR AD ACCOUNT
# =========================================
@blp_instagram_ads.route("/social/instagram/ad-account-info", methods=["GET"])
class InstagramAdAccountInfoResource(MethodView):
    """
    Get Instagram Business Account linked to a Facebook Page for ads.
    """
    
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "instagram_ads_resource.py",
            "InstagramAdAccountInfoResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Getting Instagram account info for ads")
        
        page_id = request.args.get("page_id")
        
        if not page_id:
            return jsonify({
                "success": False,
                "message": "page_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            ig_info = _get_instagram_account_for_page(
                business_id, user__id, page_id, log_tag
            )
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Instagram account info retrieved in {duration:.2f}s")
            
            if not ig_info.get("success"):
                return jsonify({
                    "success": False,
                    "message": ig_info.get("error", "Failed to get Instagram account"),
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            return jsonify({
                "success": True,
                "data": {
                    "instagram_account_id": ig_info.get("instagram_account_id"),
                    "instagram_username": ig_info.get("instagram_username"),
                    "page_id": page_id,
                },
            }), HTTP_STATUS_CODES["OK"]
            
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to get Instagram account info",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST INSTAGRAM MEDIA (for boost selection)
# =========================================
@blp_instagram_ads.route("/social/instagram/media", methods=["GET"])
class InstagramMediaListResource(MethodView):
    """
    List recent Instagram posts that can be boosted.
    """
    
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "instagram_ads_resource.py",
            "InstagramMediaListResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Fetching Instagram media list")
        
        page_id = request.args.get("page_id")
        instagram_account_id = request.args.get("instagram_account_id")
        limit = int(request.args.get("limit", 25))
        
        if not page_id and not instagram_account_id:
            return jsonify({
                "success": False,
                "message": "page_id or instagram_account_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            # Get Instagram account info if not provided
            if not instagram_account_id:
                ig_info = _get_instagram_account_for_page(
                    business_id, user__id, page_id, log_tag
                )
                
                if not ig_info.get("success"):
                    return jsonify({
                        "success": False,
                        "message": ig_info.get("error", "Failed to get Instagram account"),
                    }), HTTP_STATUS_CODES["BAD_REQUEST"]
                
                instagram_account_id = ig_info.get("instagram_account_id")
                access_token = ig_info.get("access_token")
            else:
                # Get access token from ad account or social account
                ad_accounts = AdAccount.list_by_business(business_id)
                access_token = None
                
                if ad_accounts:
                    ad_account = AdAccount.get_by_id(ad_accounts[0]["_id"], business_id)
                    access_token = ad_account.get("access_token_plain") if ad_account else None
                
                if not access_token:
                    ig_info = _get_instagram_account_for_page(
                        business_id, user__id, page_id or "", log_tag
                    )
                    access_token = ig_info.get("access_token")
            
            if not access_token:
                return jsonify({
                    "success": False,
                    "message": "Access token not found. Please reconnect your account.",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # Fetch media from Instagram
            service = FacebookAdsService(access_token)
            
            api_start = time.time()
            media_result = service.get_instagram_media(instagram_account_id, limit=limit)
            api_duration = time.time() - api_start
            
            Log.info(f"{log_tag} Instagram media API call completed in {api_duration:.2f}s")
            
            if not media_result.get("success"):
                return jsonify({
                    "success": False,
                    "message": "Failed to fetch Instagram media",
                    "error": media_result.get("error_message", media_result.get("error")),
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            media_items = media_result.get("data", {}).get("data", [])
            
            # Format response
            formatted_media = []
            for item in media_items:
                formatted_media.append({
                    "media_id": item.get("id"),
                    "caption": item.get("caption", "")[:100] + "...." if len(item.get("caption", "")) > 100 else item.get("caption", ""),
                    "full_caption": item.get("caption"),
                    "media_type": item.get("media_type"),  # IMAGE, VIDEO, CAROUSEL_ALBUM
                    "media_url": item.get("media_url"),
                    "thumbnail_url": item.get("thumbnail_url"),
                    "permalink": item.get("permalink"),
                    "timestamp": item.get("timestamp"),
                    "like_count": item.get("like_count"),
                    "comments_count": item.get("comments_count"),
                    "can_boost": item.get("media_type") in ["IMAGE", "VIDEO"],  # CAROUSEL_ALBUM may not be boostable
                })
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Retrieved {len(formatted_media)} media items in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "data": {
                    "instagram_account_id": instagram_account_id,
                    "media": formatted_media,
                    "count": len(formatted_media),
                },
            }), HTTP_STATUS_CODES["OK"]
            
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to fetch Instagram media",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# BOOST INSTAGRAM POST
# =========================================
@blp_instagram_ads.route("/social/instagram/boost-post", methods=["POST"])
class InstagramBoostPostResource(MethodView):
    """
    Boost an existing Instagram post.
    
    Body:
    {
        "ad_account_id": "act_123456789",
        "page_id": "758138094536716",
        "instagram_account_id": "17841400000000000",  // Optional, will be fetched from page
        "media_id": "17900000000000000",
        "budget_amount": 1000,  // in cents ($10.00)
        "duration_days": 7,
        "targeting": {
            "countries": ["US", "GB"],
            "age_min": 18,
            "age_max": 45,
            "genders": [1, 2]
        },
        "advantage_audience": false
    }
    """
    
    @token_required
    @blp_instagram_ads.arguments(InstagramBoostPostSchema, location="json")
    @blp_instagram_ads.response(200, InstagramBoostPostSchema)  
    def post(self, body):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "instagram_ads_resource.py",
            "InstagramBoostPostResource",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Instagram boost post request received")
        
        # Extract parameters
        ad_account_id = body.get("ad_account_id")
        page_id = body.get("page_id")
        instagram_account_id = body.get("instagram_account_id")
        media_id = body.get("media_id")
        budget_amount = body.get("budget_amount", 500)
        duration_days = body.get("duration_days", 7)
        targeting_input = body.get("targeting", {})
        scheduled_post_id = body.get("scheduled_post_id")
        is_adset_budget_sharing_enabled = body.get("is_adset_budget_sharing_enabled", False)
        advantage_audience = body.get("advantage_audience", False)
        
        Log.info(
            f"{log_tag} Params: media_id={media_id} "
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
        
        if not page_id:
            return jsonify({
                "success": False,
                "message": "page_id is required (Facebook Page linked to Instagram)",
                "code": "MISSING_PAGE_ID",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if not media_id:
            return jsonify({
                "success": False,
                "message": "media_id is required (Instagram post to boost)",
                "code": "MISSING_MEDIA_ID",
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
        
        try:
            # =========================================
            # GET AD ACCOUNT & ACCESS TOKEN
            # =========================================
            ad_account = AdAccount.get_by_ad_account_id(business_id, ad_account_id)
            
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
            # GET INSTAGRAM ACCOUNT ID (if not provided)
            # =========================================
            if not instagram_account_id:
                Log.info(f"{log_tag} Instagram account ID not provided, fetching from page....")
                
                ig_fetch_start = time.time()
                ig_info = _get_instagram_account_for_page(
                    business_id, user__id, page_id, log_tag
                )
                ig_fetch_duration = time.time() - ig_fetch_start
                
                Log.info(f"{log_tag} Instagram account fetch completed in {ig_fetch_duration:.2f}s")
                
                if not ig_info.get("success"):
                    return jsonify({
                        "success": False,
                        "message": ig_info.get("error", "Failed to get Instagram account"),
                        "code": "NO_INSTAGRAM_ACCOUNT",
                    }), HTTP_STATUS_CODES["BAD_REQUEST"]
                
                instagram_account_id = ig_info.get("instagram_account_id")
            
            Log.info(f"{log_tag} Using Instagram account: {instagram_account_id}")
            
            # =========================================
            # BUILD TARGETING
            # =========================================
            service = FacebookAdsService(access_token, ad_account_id)
            
            # Filter valid interests
            interests_input = targeting_input.get("interests", [])
            valid_interests = None
            
            if interests_input:
                valid_interests = [
                    i for i in interests_input
                    if isinstance(i, dict)
                    and i.get("id")
                    and str(i.get("id")).isdigit()
                    and len(str(i.get("id"))) > 5
                ]
                if not valid_interests:
                    valid_interests = None
                    Log.info(f"{log_tag} No valid interests provided, using broad targeting")
            
            targeting = service.build_targeting(
                countries=targeting_input.get("countries") or ["US"],
                age_min=targeting_input.get("age_min", 18),
                age_max=targeting_input.get("age_max", 65),
                genders=targeting_input.get("genders"),
                interests=valid_interests,
                behaviors=targeting_input.get("behaviors"),
                locales=targeting_input.get("locales"),
                advantage_audience=advantage_audience,
                # Instagram-specific placements
                publisher_platforms=["instagram"],
                instagram_positions=targeting_input.get("instagram_positions") or ["stream", "story", "explore", "reels"],
            )
            
            Log.info(f"{log_tag} Targeting built: {json.dumps(targeting, indent=2)}")
            
            # =========================================
            # BOOST THE INSTAGRAM POST
            # =========================================
            Log.info(f"{log_tag} Sending Instagram boost request to Facebook....")
            
            fb_start = time.time()
            
            result = service.boost_instagram_post(
                instagram_account_id=instagram_account_id,
                page_id=page_id,
                media_id=media_id,
                budget_amount=budget_amount,
                duration_days=duration_days,
                targeting=targeting,
                is_adset_budget_sharing_enabled=is_adset_budget_sharing_enabled,
                advantage_audience=advantage_audience,
            )
            
            fb_duration = time.time() - fb_start
            Log.info(f"{log_tag} Facebook boost completed in {fb_duration:.2f}s")
            
            if not result.get("success"):
                errors = result.get("errors", [])
                error_messages = [e.get("error", str(e)) for e in errors]
                
                # Extract user-friendly error message
                sweet_error = "Failed to boost Instagram post"
                if errors and errors[0].get("details"):
                    details = errors[0].get("details", {})
                    if isinstance(details, dict):
                        sweet_error = details.get("error_user_msg", sweet_error)
                
                Log.info(f"{log_tag} error_messages: {error_messages}")
                Log.info(f"{log_tag} Boost failed: {errors}")
                
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
            campaign = AdCampaign.create({
                "business_id": business_id,
                "user__id": user__id,
                "ad_account_id": ad_account_id,
                "page_id": page_id,
                "campaign_name": f"Boost IG Post {media_id[-8:]}",
                "objective": AdCampaign.OBJECTIVE_ENGAGEMENT,
                "budget_type": AdCampaign.BUDGET_LIFETIME,
                "budget_amount": budget_amount,
                "currency": currency,
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc) + timedelta(days=duration_days),
                "targeting": targeting,
                "scheduled_post_id": scheduled_post_id,
                "post_id": media_id,  # Instagram media ID
                "fb_campaign_id": result.get("campaign_id"),
                "fb_adset_id": result.get("adset_id"),
                "fb_creative_id": result.get("creative_id"),
                "fb_ad_id": result.get("ad_id"),
                "status": AdCampaign.STATUS_ACTIVE,
                "meta": {
                    "platform": "instagram",
                    "instagram_account_id": instagram_account_id,
                    "media_id": media_id,
                    "is_adset_budget_sharing_enabled": is_adset_budget_sharing_enabled,
                    "advantage_audience": advantage_audience,
                },
            })
            
            total_duration = time.time() - start_time
            Log.info(
                f"{log_tag} Instagram boost successful campaign={campaign['_id']} "
                f"fb_campaign={result.get('campaign_id')} in {total_duration:.2f}s"
            )
            
            return jsonify({
                "success": True,
                "message": "Instagram post boosted successfully!",
                "data": {
                    "_id": campaign["_id"],
                    "fb_campaign_id": result.get("campaign_id"),
                    "fb_adset_id": result.get("adset_id"),
                    "fb_creative_id": result.get("creative_id"),
                    "fb_ad_id": result.get("ad_id"),
                    "instagram_account_id": instagram_account_id,
                    "media_id": media_id,
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
                "message": "Failed to boost Instagram post",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST INSTAGRAM CAMPAIGNS
# =========================================
@blp_instagram_ads.route("/social/instagram/campaigns", methods=["GET"])
class InstagramCampaignsResource(MethodView):
    """
    List Instagram ad campaigns for the business.
    """
    
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")
        
        log_tag = make_log_tag(
            "instagram_ads_resource.py",
            "InstagramCampaignsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Fetching Instagram campaigns")
        
        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 20))
            status = request.args.get("status")
            
            # Get all campaigns and filter by platform=instagram
            result = AdCampaign.list_by_business(
                business_id=business_id,
                status=status,
                page=1,
                per_page=1000,  # Get all, then filter
            )
            
            # Filter for Instagram campaigns
            instagram_campaigns = [
                c for c in result["items"]
                if (c.get("meta", {}) or {}).get("platform") == "instagram"
            ]
            
            # Manual pagination
            total_count = len(instagram_campaigns)
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            paginated = instagram_campaigns[start_idx:end_idx]
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Retrieved {len(paginated)} Instagram campaigns in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "data": paginated,
                "pagination": {
                    "total_count": total_count,
                    "total_pages": (total_count + per_page - 1) // per_page,
                    "current_page": page,
                    "per_page": per_page,
                },
            }), HTTP_STATUS_CODES["OK"]
            
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Failed after {duration:.2f}s: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to fetch Instagram campaigns",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# PAUSE INSTAGRAM CAMPAIGN
# =========================================
@blp_instagram_ads.route("/social/instagram/campaigns/<campaign_id>/pause", methods=["POST"])
class InstagramCampaignPauseResource(MethodView):
    """Pause an Instagram campaign."""
    
    @token_required
    def post(self, campaign_id: str):
        return _update_instagram_campaign_status(campaign_id, "PAUSED", AdCampaign.STATUS_PAUSED)


# =========================================
# RESUME INSTAGRAM CAMPAIGN
# =========================================
@blp_instagram_ads.route("/social/instagram/campaigns/<campaign_id>/resume", methods=["POST"])
class InstagramCampaignResumeResource(MethodView):
    """Resume a paused Instagram campaign."""
    
    @token_required
    def post(self, campaign_id: str):
        return _update_instagram_campaign_status(campaign_id, "ACTIVE", AdCampaign.STATUS_ACTIVE)


def _update_instagram_campaign_status(campaign_id: str, fb_status: str, local_status: str):
    """Helper to update Instagram campaign status."""
    client_ip = request.remote_addr
    user = g.get("current_user", {}) or {}
    business_id = str(user.get("business_id", ""))
    
    log_tag = f"[instagram_ads_resource.py][UpdateCampaignStatus][{campaign_id}]"
    
    start_time = time.time()
    Log.info(f"{log_tag} Updating campaign status to {fb_status}")
    
    campaign = AdCampaign.get_by_id(campaign_id, business_id)
    if not campaign:
        Log.info(f"{log_tag} Campaign not found")
        return jsonify({
            "success": False,
            "message": "Campaign not found",
        }), HTTP_STATUS_CODES["NOT_FOUND"]
    
    if not campaign.get("fb_campaign_id"):
        return jsonify({
            "success": False,
            "message": "Campaign not synced with Facebook",
        }), HTTP_STATUS_CODES["BAD_REQUEST"]
    
    ad_account = AdAccount.get_by_ad_account_id(business_id, campaign["ad_account_id"])
    if not ad_account or not ad_account.get("access_token_plain"):
        return jsonify({
            "success": False,
            "message": "Ad account not found or token missing",
        }), HTTP_STATUS_CODES["BAD_REQUEST"]
    
    try:
        service = FacebookAdsService(
            ad_account["access_token_plain"],
            campaign["ad_account_id"]
        )
        
        api_start = time.time()
        result = service.update_campaign_status(campaign["fb_campaign_id"], fb_status)
        api_duration = time.time() - api_start
        
        Log.info(f"{log_tag} Facebook API call completed in {api_duration:.2f}s")
        
        if not result.get("success"):
            return jsonify({
                "success": False,
                "message": "Failed to update campaign status",
                "error": result.get("error_message", result.get("error")),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        # Update local status
        AdCampaign.update_status(campaign_id, business_id, local_status)
        
        duration = time.time() - start_time
        Log.info(f"{log_tag} Campaign status updated to {fb_status} in {duration:.2f}s")
        
        return jsonify({
            "success": True,
            "message": f"Campaign {fb_status.lower()} successfully",
        }), HTTP_STATUS_CODES["OK"]
        
    except Exception as e:
        duration = time.time() - start_time
        Log.error(f"{log_tag} Exception after {duration:.2f}s: {e}")
        
        return jsonify({
            "success": False,
            "message": "Failed to update campaign status",
        }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]