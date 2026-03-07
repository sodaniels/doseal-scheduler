# app/resources/social/youtube_ads_resource.py

import json
import time
from datetime import datetime, timezone, timedelta

from flask_smorest import Blueprint
from flask import request, jsonify, g
from flask.views import MethodView

from ...doseal.admin.admin_business_resource import token_required
from ....constants.service_code import HTTP_STATUS_CODES
from ....utils.logger import Log
from ....utils.helpers import make_log_tag

from ....models.social.social_account import SocialAccount
from ....models.social.ad_account import AdAccount, AdCampaign
from ....services.social.ads.youtube_ads_service import YouTubeAdsService, YouTubeAdsError

# schemas
from ....schemas.social.social_schema import (
    AccountConnectionSchema, YouTubeAdAccountConnectSchema, YouTubeBoostVideoSchema,
)


blp_youtube_ads = Blueprint("youtube_ads", __name__)


def _update_campaign_status(campaign_id: str, google_status: str, local_status: str):
    """Helper to update campaign status on Google Ads and locally."""
    user = g.get("current_user", {}) or {}
    business_id = str(user.get("business_id", ""))

    log_tag = f"[youtube_ads_resource.py][UpdateCampaignStatus][{campaign_id}]"

    campaign = AdCampaign.get_by_id(campaign_id, business_id)
    if not campaign:
        Log.info(f"{log_tag} Campaign not found. campaign_id={campaign_id}")
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
            "message": "Campaign not found",
        }), HTTP_STATUS_CODES["NOT_FOUND"]

    if not campaign.get("youtube_campaign_id"):
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
            "message": "Campaign not synced with Google Ads",
        }), HTTP_STATUS_CODES["BAD_REQUEST"]

    ad_account = AdAccount.get_by_ad_account_id(business_id, campaign["ad_account_id"])
    if not ad_account or not ad_account.get("access_token_plain"):
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
            "message": "Ad account not found or token missing",
        }), HTTP_STATUS_CODES["BAD_REQUEST"]

    try:
        service = YouTubeAdsService(
            access_token=ad_account["access_token_plain"],
            refresh_token=ad_account.get("refresh_token_plain"),
            customer_id=campaign["ad_account_id"],
            manager_customer_id=ad_account.get("meta", {}).get("manager_customer_id"),
        )
        service.update_campaign_status(campaign["youtube_campaign_id"], google_status)
        AdCampaign.update_status(campaign_id, business_id, local_status)

        return jsonify({
            "success": True,
            "message": f"Campaign {google_status.lower()} successfully",
        }), HTTP_STATUS_CODES["OK"]

    except YouTubeAdsError as e:
        Log.error(f"{log_tag} YouTubeAdsError: {e}")
        return jsonify({
            "success": False,
            "message": "Failed to update campaign status",
            "error": str(e),
        }), HTTP_STATUS_CODES["BAD_REQUEST"]

    except Exception as e:
        Log.error(f"{log_tag} Exception: {e}")
        return jsonify({
            "success": False,
            "message": "Failed to update campaign status",
        }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST ACCESSIBLE GOOGLE ADS ACCOUNTS
# =========================================
@blp_youtube_ads.route("/social/youtube/ad-accounts/available", methods=["GET"])
class YouTubeAdAccountsAvailableResource(MethodView):
    """
    List Google Ads customer accounts accessible via the connected YouTube/Google account.
    Reads the OAuth token from SocialAccount(platform="youtube") — the same account
    used for video posting (connected via /social/oauth/youtube/connect-channel).
    The access_token and refresh_token stored there carry the Google OAuth scopes.
    """

    @token_required
    @blp_youtube_ads.arguments(AccountConnectionSchema, location="query")
    @blp_youtube_ads.response(200, AccountConnectionSchema)
    def get(self, item_data):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "youtube_ads_resource.py",
            "YouTubeAdAccountsAvailableResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        # Read token from YouTube SocialAccount — same platform used for video posting
        youtube_account = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="youtube",
            destination_id=item_data.get("destination_id"),
        )

        if not youtube_account:
            return jsonify({
                "success": False,
                "message": "YouTube account not connected. Please connect your YouTube channel first.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        access_token = youtube_account.get("access_token_plain")
        refresh_token = youtube_account.get("refresh_token_plain")

        if not access_token:
            return jsonify({
                "success": False,
                "message": "YouTube access token not found. Please reconnect your YouTube channel.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            start_time = time.time()

            service = YouTubeAdsService(
                access_token=access_token,
                refresh_token=refresh_token,
            )
            result = service.list_accessible_customers()

            duration = time.time() - start_time
            Log.info(f"{log_tag} Fetched accessible Google Ads accounts in {duration:.2f}s")

            return jsonify({
                "success": True,
                "data": result.get("data", []),
            }), HTTP_STATUS_CODES["OK"]

        except YouTubeAdsError as e:
            Log.error(f"{log_tag} YouTubeAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch Google Ads accounts",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch Google Ads accounts",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# CONNECT AD ACCOUNT
# =========================================
@blp_youtube_ads.route("/social/youtube/ad-accounts/connect", methods=["POST"])
class YouTubeAdAccountConnectResource(MethodView):
    """
    Connect a Google Ads customer account to this business.
    Reads OAuth tokens from the connected Google SocialAccount.
    """

    @token_required
    @blp_youtube_ads.arguments(YouTubeAdAccountConnectSchema, location="form")
    @blp_youtube_ads.response(200, YouTubeAdAccountConnectSchema)
    def post(self, body):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "youtube_ads_resource.py",
            "YouTubeAdAccountConnectResource",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        customer_id = str(body.get("customer_id", "")).replace("-", "").strip()
        manager_customer_id = str(body.get("manager_customer_id", "")).replace("-", "").strip() or None

        if not customer_id:
            return jsonify({
                "success": False,
                "message": "customer_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Get YouTube OAuth tokens from SocialAccount (platform="youtube")
        # This is the same account connected via /social/oauth/youtube/connect-channel
        youtube_accounts = SocialAccount.list_destinations(business_id, user__id, "youtube")
        if not youtube_accounts:
            return jsonify({
                "success": False,
                "message": "No YouTube channel connected. Please connect your YouTube channel first.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        youtube_account = SocialAccount.get_destination(
            business_id, user__id, "youtube",
            youtube_accounts[0].get("destination_id"),
        )

        if not youtube_account or not youtube_account.get("access_token_plain"):
            return jsonify({
                "success": False,
                "message": "YouTube access token not found. Please reconnect your YouTube channel.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        access_token = youtube_account["access_token_plain"]
        refresh_token = youtube_account.get("refresh_token_plain")

        # Check already connected
        existing = AdAccount.get_by_ad_account_id(business_id, customer_id, platform="youtube")
        if existing:
            return jsonify({
                "success": False,
                "message": "This Google Ads account is already connected.",
                "code": "ALREADY_CONNECTED",
            }), HTTP_STATUS_CODES["CONFLICT"]

        try:
            service = YouTubeAdsService(
                access_token=access_token,
                refresh_token=refresh_token,
                customer_id=customer_id,
                manager_customer_id=manager_customer_id,
            )

            # Verify access and get account details
            info_resp = service.get_customer_info()
            info = info_resp.get("data", {})

            if not info:
                return jsonify({
                    "success": False,
                    "message": "Cannot access this Google Ads account. Check your permissions.",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            start_time = time.time()

            ad_account = AdAccount.create({
                "business_id": business_id,
                "user__id": user__id,
                "platform": "youtube",
                "ad_account_id": customer_id,
                "ad_account_name": info.get("name") or f"Google Ads {customer_id}",
                "currency": info.get("currency", "USD"),
                "timezone_name": info.get("timezone"),
                "access_token": access_token,
                "refresh_token": refresh_token,
                "meta": {
                    "manager_customer_id": manager_customer_id,
                    "is_manager": info.get("is_manager", False),
                    "youtube_channel_id": youtube_account.get("platform_user_id"),
                    "youtube_channel_name": youtube_account.get("platform_username"),
                    "status": info.get("status"),
                },
            })

            duration = time.time() - start_time
            Log.info(f"{log_tag} AdAccount created in {duration:.2f}s")

            return jsonify({
                "success": True,
                "message": "Google Ads account connected successfully",
                "data": {
                    "_id": ad_account["_id"],
                    "ad_account_id": ad_account["ad_account_id"],
                    "ad_account_name": ad_account["ad_account_name"],
                    "currency": ad_account["currency"],
                },
            }), HTTP_STATUS_CODES["CREATED"]

        except YouTubeAdsError as e:
            Log.error(f"{log_tag} YouTubeAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Cannot access this Google Ads account. Check your permissions.",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to connect Google Ads account",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST CONNECTED AD ACCOUNTS
# =========================================
@blp_youtube_ads.route("/social/youtube/ad-accounts", methods=["GET"])
class YouTubeAdAccountsResource(MethodView):
    """List Google Ads accounts connected to this business."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "youtube_ads_resource.py",
            "YouTubeAdAccountsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        start_time = time.time()

        try:
            ad_accounts = AdAccount.list_by_business(business_id, platform="youtube")
            duration = time.time() - start_time
            Log.info(f"{log_tag} Retrieved {len(ad_accounts)} accounts in {duration:.2f}s")

            return jsonify({
                "success": True,
                "data": ad_accounts,
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to retrieve ad accounts",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# BOOST VIDEO (DEMAND GEN)
# =========================================
@blp_youtube_ads.route("/social/youtube/boost-video", methods=["POST"])
class YouTubeBoostVideoResource(MethodView):
    """
    Boost a YouTube video using a Demand Gen campaign.

    The video must already be uploaded to YouTube. Only the 11-character
    YouTube video ID is required — no upload step needed.
    """

    @token_required
    @blp_youtube_ads.arguments(YouTubeBoostVideoSchema, location="json")
    def post(self, body):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "youtube_ads_resource.py",
            "YouTubeBoostVideoResource",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        start_time = time.time()
        Log.info(f"{log_tag} Boost video request received")

        try:
            customer_id = str(body["customer_id"]).replace("-", "")
            youtube_video_id = body["youtube_video_id"].strip()
            headline = body["headline"]
            description = body["description"]
            business_name = body["business_name"]
            final_url = body["final_url"]
            daily_budget_usd = body["daily_budget_usd"]
            duration_days = body["duration_days"]
            scheduled_post_id = body.get("scheduled_post_id")
            auto_activate = body.get("auto_activate", False)

            Log.info(
                f"{log_tag} Params customer_id={customer_id} "
                f"video={youtube_video_id} budget=${daily_budget_usd}/day "
                f"duration={duration_days}d"
            )

            # Resolve ad account + tokens
            ad_account = AdAccount.get_by_ad_account_id(business_id, customer_id, platform="youtube")
            if not ad_account or not ad_account.get("access_token_plain"):
                Log.warning(f"{log_tag} Missing ad account or token")
                return jsonify({
                    "success": False,
                    "message": "Google Ads account not connected or token missing",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            access_token = ad_account["access_token_plain"]
            refresh_token = ad_account.get("refresh_token_plain")
            manager_customer_id = ad_account.get("meta", {}).get("manager_customer_id")
            currency = ad_account.get("currency", "USD")

            service = YouTubeAdsService(
                access_token=access_token,
                refresh_token=refresh_token,
                customer_id=customer_id,
                manager_customer_id=manager_customer_id,
            )

            # Build targeting
            targeting_input = body.get("targeting", {}) or {}
            geo_ids = targeting_input.get("geo_target_ids") or ["2840"]   # default US
            lang_ids = targeting_input.get("language_ids") or ["1000"]   # default English

            gads_start = time.time()

            result = service.boost_video(
                youtube_video_id=youtube_video_id,
                headline=headline,
                description=description,
                business_name=business_name,
                final_url=final_url,
                daily_budget_usd=daily_budget_usd,
                duration_days=duration_days,
                campaign_name=body.get("campaign_name"),
                long_headline=body.get("long_headline"),
                logo_image_url=body.get("logo_image_url"),
                geo_target_ids=geo_ids,
                language_ids=lang_ids,
                bidding_strategy=body.get("bidding_strategy", "maximizeConversions"),
                target_cpa_usd=body.get("target_cpa_usd"),
                breadcrumb1=body.get("breadcrumb1"),
                breadcrumb2=body.get("breadcrumb2"),
                auto_activate=auto_activate,
            )

            gads_duration = time.time() - gads_start
            Log.info(f"{log_tag} Google Ads boost completed in {gads_duration:.2f}s")

            # Persist campaign
            campaign = AdCampaign.create({
                "business_id": business_id,
                "user__id": user__id,
                "platform": "youtube",
                "ad_account_id": customer_id,
                "campaign_name": body.get("campaign_name") or f"Boost YT {youtube_video_id}",
                "objective": "DEMAND_GEN",
                "budget_type": AdCampaign.BUDGET_DAILY,
                "budget_amount": daily_budget_usd,
                "currency": currency,
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc) + timedelta(days=duration_days),
                "targeting": {
                    "geo_target_ids": geo_ids,
                    "language_ids": lang_ids,
                },
                "scheduled_post_id": scheduled_post_id,
                "youtube_video_id": youtube_video_id,
                "youtube_campaign_id": result.get("campaign_id"),
                "youtube_budget_id": result.get("budget_id"),
                "youtube_ad_group_id": result.get("ad_group_id"),
                "youtube_ad_group_ad_id": result.get("ad_group_ad_id"),
                "youtube_video_asset_id": result.get("video_asset_id"),
                "status": AdCampaign.STATUS_ACTIVE if auto_activate else AdCampaign.STATUS_PAUSED,
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
                    "youtube_campaign_id": result.get("campaign_id"),
                    "youtube_ad_group_id": result.get("ad_group_id"),
                    "youtube_video_id": youtube_video_id,
                    "budget": f"{currency} {daily_budget_usd:.2f}/day",
                    "duration_days": duration_days,
                },
            }), HTTP_STATUS_CODES["CREATED"]

        except YouTubeAdsError as e:
            Log.error(f"{log_tag} YouTubeAdsError: {e}")
            return jsonify({
                "success": False,
                "message": str(e),
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Exception after {duration:.2f}s err={e}")
            return jsonify({
                "success": False,
                "message": "Failed to boost video",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST CAMPAIGNS
# =========================================
@blp_youtube_ads.route("/social/youtube/campaigns", methods=["GET"])
class YouTubeCampaignsResource(MethodView):
    """List Demand Gen campaigns for this business."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "youtube_ads_resource.py",
            "YouTubeCampaignsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        start_time = time.time()

        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 20))
            status = request.args.get("status")

            result = AdCampaign.list_by_business(
                business_id=business_id,
                platform="youtube",
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
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch campaigns",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# GET CAMPAIGN INSIGHTS
# =========================================
@blp_youtube_ads.route("/social/youtube/campaigns/<campaign_id>/insights", methods=["GET"])
class YouTubeCampaignInsightsResource(MethodView):

    @token_required
    def get(self, campaign_id):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))

        log_tag = make_log_tag(
            "youtube_ads_resource.py",
            "YouTubeCampaignInsightsResource",
            "get",
            client_ip,
            user.get("_id"),
            user.get("account_type"),
            business_id,
            business_id,
        )

        start_time = time.time()

        try:
            days = int(request.args.get("days", 7))
            now = datetime.now(timezone.utc)
            start_date = request.args.get("start_date") or (now - timedelta(days=days)).strftime("%Y-%m-%d")
            end_date = request.args.get("end_date") or now.strftime("%Y-%m-%d")

            campaign = AdCampaign.get_by_id(campaign_id, business_id)
            if not campaign:
                return jsonify({"success": False, "message": "Campaign not found"}), HTTP_STATUS_CODES["NOT_FOUND"]

            if not campaign.get("youtube_campaign_id"):
                return jsonify({
                    "success": False,
                    "message": "Campaign not synced with Google Ads",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            ad_account = AdAccount.get_by_ad_account_id(business_id, campaign["ad_account_id"], platform="youtube")
            if not ad_account or not ad_account.get("access_token_plain"):
                return jsonify({
                    "success": False,
                    "message": "Ad account not found or token missing",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            service = YouTubeAdsService(
                access_token=ad_account["access_token_plain"],
                refresh_token=ad_account.get("refresh_token_plain"),
                customer_id=campaign["ad_account_id"],
                manager_customer_id=ad_account.get("meta", {}).get("manager_customer_id"),
            )

            result = service.get_campaign_insights(
                campaign_id=campaign["youtube_campaign_id"],
                start_date=start_date,
                end_date=end_date,
            )

            duration = time.time() - start_time
            Log.info(f"{log_tag} Insights fetched in {duration:.2f}s")

            return jsonify({
                "success": True,
                "data": {
                    "campaign_id": campaign_id,
                    "youtube_campaign_id": campaign.get("youtube_campaign_id"),
                    "youtube_video_id": campaign.get("youtube_video_id"),
                    **result.get("data", {}),
                },
            }), HTTP_STATUS_CODES["OK"]

        except YouTubeAdsError as e:
            Log.error(f"{log_tag} YouTubeAdsError: {e}")
            return jsonify({
                "success": False,
                "message": f"Google Ads API error: {str(e)}",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch insights",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# PAUSE CAMPAIGN
# =========================================
@blp_youtube_ads.route("/social/youtube/campaigns/<campaign_id>/pause", methods=["POST"])
class YouTubeCampaignPauseResource(MethodView):
    """Pause a Demand Gen campaign."""

    @token_required
    def post(self, campaign_id: str):
        return _update_campaign_status(campaign_id, "PAUSED", AdCampaign.STATUS_PAUSED)


# =========================================
# RESUME CAMPAIGN
# =========================================
@blp_youtube_ads.route("/social/youtube/campaigns/<campaign_id>/resume", methods=["POST"])
class YouTubeCampaignResumeResource(MethodView):
    """Resume a paused Demand Gen campaign."""

    @token_required
    def post(self, campaign_id: str):
        return _update_campaign_status(campaign_id, "ENABLED", AdCampaign.STATUS_ACTIVE)


# =========================================
# GEO TARGET SEARCH
# =========================================
@blp_youtube_ads.route("/social/youtube/targeting/locations", methods=["GET"])
class YouTubeTargetingLocationsResource(MethodView):
    """
    Search Google geo target constants by name.
    Returns location IDs usable in boost-video targeting.geo_target_ids.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "youtube_ads_resource.py",
            "YouTubeTargetingLocationsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        q = request.args.get("q", "").strip()
        if not q or len(q) < 2:
            return jsonify({
                "success": False,
                "message": "Query 'q' must be at least 2 characters",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        locale = request.args.get("locale", "en")

        # Use any connected Google Ads account for this lookup
        ad_accounts = AdAccount.list_by_business(business_id, platform="youtube")
        if not ad_accounts:
            return jsonify({
                "success": False,
                "message": "No Google Ads account connected",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        ad_account = AdAccount.get_by_id(ad_accounts[0]["_id"], business_id)
        if not ad_account or not ad_account.get("access_token_plain"):
            return jsonify({
                "success": False,
                "message": "Ad account token not found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            service = YouTubeAdsService(
                access_token=ad_account["access_token_plain"],
                refresh_token=ad_account.get("refresh_token_plain"),
                customer_id=ad_account["ad_account_id"],
            )

            result = service.get_geo_targets(keyword=q, locale=locale)
            duration = time.time()
            Log.info(f"{log_tag} Geo targets fetched q={q}")

            return jsonify({
                "success": True,
                "data": result.get("data", []),
            }), HTTP_STATUS_CODES["OK"]

        except YouTubeAdsError as e:
            Log.error(f"{log_tag} YouTubeAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch locations",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            return jsonify({
                "success": False,
                "message": "Failed to fetch locations",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LANGUAGE CONSTANTS
# =========================================
@blp_youtube_ads.route("/social/youtube/targeting/languages", methods=["GET"])
class YouTubeTargetingLanguagesResource(MethodView):
    """
    List available Google Ads language targeting constants.
    Returns language IDs usable in boost-video targeting.language_ids.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "youtube_ads_resource.py",
            "YouTubeTargetingLanguagesResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        q = request.args.get("q", "").strip() or None

        ad_accounts = AdAccount.list_by_business(business_id, platform="youtube")
        if not ad_accounts:
            return jsonify({
                "success": False,
                "message": "No Google Ads account connected",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        ad_account = AdAccount.get_by_id(ad_accounts[0]["_id"], business_id)
        if not ad_account or not ad_account.get("access_token_plain"):
            return jsonify({
                "success": False,
                "message": "Ad account token not found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            service = YouTubeAdsService(
                access_token=ad_account["access_token_plain"],
                refresh_token=ad_account.get("refresh_token_plain"),
                customer_id=ad_account["ad_account_id"],
            )

            result = service.get_language_constants(keyword=q)

            return jsonify({
                "success": True,
                "data": result.get("data", []),
            }), HTTP_STATUS_CODES["OK"]

        except YouTubeAdsError as e:
            Log.error(f"{log_tag} YouTubeAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch languages",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            return jsonify({
                "success": False,
                "message": "Failed to fetch languages",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# REACH FORECAST
# =========================================
@blp_youtube_ads.route("/social/youtube/reach-forecast", methods=["GET"])
class YouTubeReachForecastResource(MethodView):
    """
    Get audience reach forecast for a Demand Gen targeting spec.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "youtube_ads_resource.py",
            "YouTubeReachForecastResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        customer_id = request.args.get("customer_id", "").replace("-", "").strip()
        daily_budget_usd = request.args.get("daily_budget_usd")
        duration_days = request.args.get("duration_days")
        geo_ids_raw = request.args.get("geo_target_ids")
        lang_ids_raw = request.args.get("language_ids")

        if not customer_id:
            return jsonify({"success": False, "message": "customer_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]
        if not daily_budget_usd or not duration_days:
            return jsonify({"success": False, "message": "daily_budget_usd and duration_days are required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            daily_budget_usd = float(daily_budget_usd)
            duration_days = int(duration_days)
            geo_ids = json.loads(geo_ids_raw) if geo_ids_raw else None
            lang_ids = json.loads(lang_ids_raw) if lang_ids_raw else None
        except Exception:
            return jsonify({"success": False, "message": "Invalid parameter format"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        ad_account = AdAccount.get_by_ad_account_id(business_id, customer_id, platform="youtube")
        if not ad_account or not ad_account.get("access_token_plain"):
            return jsonify({"success": False, "message": "Ad account not found or token missing"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            service = YouTubeAdsService(
                access_token=ad_account["access_token_plain"],
                refresh_token=ad_account.get("refresh_token_plain"),
                customer_id=customer_id,
                manager_customer_id=ad_account.get("meta", {}).get("manager_customer_id"),
            )

            result = service.get_reach_forecast(
                campaign_duration_days=duration_days,
                daily_budget_usd=daily_budget_usd,
                geo_target_ids=geo_ids,
                language_ids=lang_ids,
            )

            Log.info(f"{log_tag} Reach forecast completed")

            if not result.get("success"):
                return jsonify(result), HTTP_STATUS_CODES["BAD_REQUEST"]

            return jsonify({
                "success": True,
                "data": result.get("data", {}),
            }), HTTP_STATUS_CODES["OK"]

        except YouTubeAdsError as e:
            Log.error(f"{log_tag} YouTubeAdsError: {e}")
            return jsonify({"success": False, "message": str(e)}), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({"success": False, "message": "Failed to get reach forecast"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
