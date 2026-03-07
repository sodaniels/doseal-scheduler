# app/resources/social/tiktok_ads_resource.py

import json
import os
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
from ....services.social.ads.tiktok_ads_service import TikTokAdsService, TikTokAdsError

# schemas
from ....schemas.social.social_schema import (
    AccountConnectionSchema, TikTokAdAccountConnectSchema, TikTokBoostVideoSchema,
)


blp_tiktok_ads = Blueprint("tiktok_ads", __name__)


def _update_campaign_status(campaign_id: str, tiktok_status: str, local_status: str):
    """Helper to update campaign status on TikTok and locally."""
    user = g.get("current_user", {}) or {}
    business_id = str(user.get("business_id", ""))

    log_tag = f"[tiktok_ads_resource.py][UpdateCampaignStatus][{campaign_id}]"

    campaign = AdCampaign.get_by_id(campaign_id, business_id)
    if not campaign:
        Log.info(f"{log_tag} Campaign not found. campaign_id={campaign_id}")
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
            "message": "Campaign not found",
        }), HTTP_STATUS_CODES["NOT_FOUND"]

    if not campaign.get("tiktok_campaign_id"):
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
            "message": "Campaign not synced with TikTok",
        }), HTTP_STATUS_CODES["BAD_REQUEST"]

    ad_account = AdAccount.get_by_ad_account_id(business_id, campaign["ad_account_id"])
    if not ad_account or not ad_account.get("access_token_plain"):
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
            "message": "Ad account not found or token missing",
        }), HTTP_STATUS_CODES["BAD_REQUEST"]

    try:
        service = TikTokAdsService(
            ad_account["access_token_plain"],
            campaign["ad_account_id"],
        )
        service.update_campaign_status([campaign["tiktok_campaign_id"]], tiktok_status)
        AdCampaign.update_status(campaign_id, business_id, local_status)

        return jsonify({
            "success": True,
            "message": f"Campaign {tiktok_status.lower()} successfully",
        }), HTTP_STATUS_CODES["OK"]

    except TikTokAdsError as e:
        Log.error(f"{log_tag} TikTokAdsError: {e}")
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
# LIST USER'S AD ACCOUNTS (from TikTok)
# =========================================
@blp_tiktok_ads.route("/social/tiktok/ad-accounts/available", methods=["GET"])
class TikTokAdAccountsAvailableResource(MethodView):
    @token_required
    @blp_tiktok_ads.arguments(AccountConnectionSchema, location="query")
    @blp_tiktok_ads.response(200, AccountConnectionSchema)
    def get(self, item_data):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "tiktok_ads_resource.py",
            "TikTokAdAccountsAvailableResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        tiktok_account = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="tiktok",
            destination_id=item_data.get("destination_id"),
        )

        if not tiktok_account:
            return jsonify({
                "success": False,
                "message": "TikTok account not found.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        Log.info(f"tiktok_account: {tiktok_account}")

        access_token = tiktok_account.get("access_token_plain")
        if not access_token:
            return jsonify({
                "success": False,
                "message": "TikTok access token not found. Please reconnect your TikTok account.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        app_id = os.environ.get("TIKTOK_CLIENT_KEY", "").strip()
        app_secret = os.environ.get("TIKTOK_CLIENT_SECRET", "").strip()
        if not app_id or not app_secret:
            return jsonify({
                "success": False,
                "message": "TikTok Ads API not configured. Contact support.",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        try:
            start_time = time.time()

            service = TikTokAdsService(access_token)
            result = service.get_accessible_accounts(app_id=app_id, secret=app_secret)

            end_time = time.time()
            duration = end_time - start_time

            Log.info(f"{log_tag}[{client_ip}] Fetching TikTok ad accounts completed in {duration:.2f} seconds")

            raw_list = result.get("data", {}).get("list", [])

            formatted = []
            for acc in raw_list:
                formatted.append({
                    "advertiser_id": str(acc.get("advertiser_id", "")),
                    "advertiser_name": acc.get("advertiser_name"),
                    "email": acc.get("email"),
                    "currency": acc.get("currency"),
                    "status": acc.get("advertiser_account_status"),
                    "timezone": acc.get("timezone"),
                    "industry": acc.get("industry"),
                })

            return jsonify({
                "success": True,
                "data": formatted,
            }), HTTP_STATUS_CODES["OK"]

        except TikTokAdsError as e:
            Log.error(f"{log_tag} TikTokAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch TikTok ad accounts",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch ad accounts",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# CONNECT AD ACCOUNT
# =========================================
@blp_tiktok_ads.route("/social/tiktok/ad-accounts/connect", methods=["POST"])
class TikTokAdAccountConnectResource(MethodView):
    """
    Connect a TikTok Advertiser Account to the business.
    """
    @token_required
    @blp_tiktok_ads.arguments(TikTokAdAccountConnectSchema, location="form")
    @blp_tiktok_ads.response(200, TikTokAdAccountConnectSchema)
    def post(self, body):
        client_ip = request.remote_addr

        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "tiktok_ads_resource.py",
            "TikTokAdAccountConnectResource",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        advertiser_id = body.get("advertiser_id")

        if not advertiser_id:
            Log.info(f"{log_tag} advertiser_id is required")
            return jsonify({
                "success": False,
                "message": "advertiser_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Get TikTok access token from SocialAccount
        tiktok_accounts = SocialAccount.list_destinations(business_id, user__id, "tiktok")

        if not tiktok_accounts:
            Log.info(f"{log_tag} No TikTok account connected.")
            return jsonify({
                "success": False,
                "message": "No TikTok account connected.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        tiktok_account = SocialAccount.get_destination(
            business_id, user__id, "tiktok",
            tiktok_accounts[0].get("destination_id"),
        )

        if not tiktok_account or not tiktok_account.get("access_token_plain"):
            Log.info(f"{log_tag} TikTok access token not found.")
            return jsonify({
                "success": False,
                "message": "TikTok access token not found.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        access_token = tiktok_account["access_token_plain"]

        # Check if already connected
        existing = AdAccount.get_by_ad_account_id(business_id, advertiser_id)
        if existing:
            Log.info(f"{log_tag} This ad account is already connected.")
            return jsonify({
                "success": False,
                "message": "This ad account is already connected.",
                "code": "ALREADY_CONNECTED",
            }), HTTP_STATUS_CODES["CONFLICT"]

        # Verify ad account access
        try:
            service = TikTokAdsService(access_token, advertiser_id)
            info_resp = service.get_advertiser_info()

            info_list = info_resp.get("data", {}).get("list", [])
            ad_account_info = info_list[0] if info_list else {}

            if not ad_account_info:
                Log.info(f"{log_tag} Cannot access ad account: {info_resp}")
                return jsonify({
                    "success": False,
                    "message": "Cannot access this ad account. Make sure you have the correct permissions.",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            start_time = time.time()

            # Save to database
            ad_account = AdAccount.create({
                "business_id": business_id,
                "user__id": user__id,
                "platform": "tiktok",
                "ad_account_id": str(ad_account_info.get("advertiser_id", advertiser_id)),
                "ad_account_name": ad_account_info.get("advertiser_name"),
                "currency": ad_account_info.get("currency"),
                "timezone_name": ad_account_info.get("timezone"),
                "access_token": access_token,
                "meta": {
                    "status": ad_account_info.get("status"),
                    "industry": ad_account_info.get("industry"),
                    "tiktok_user_id": tiktok_account.get("platform_user_id"),
                    "tiktok_username": tiktok_account.get("platform_username"),
                },
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

        except TikTokAdsError as e:
            Log.error(f"{log_tag} TikTokAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Cannot access this ad account. Check your permissions.",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to connect ad account",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# LIST CONNECTED AD ACCOUNTS
# =========================================
@blp_tiktok_ads.route("/social/tiktok/ad-accounts", methods=["GET"])
class TikTokAdAccountsResource(MethodView):
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
            "tiktok_ads_resource.py",
            "TikTokAdAccountsResource",
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
            ad_accounts = AdAccount.list_by_business(business_id, platform="tiktok")

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
# BOOST VIDEO (SPARK ADS)
# =========================================
@blp_tiktok_ads.route("/social/tiktok/boost-video", methods=["POST"])
class TikTokBoostVideoResource(MethodView):

    @token_required
    @blp_tiktok_ads.arguments(TikTokBoostVideoSchema, location="json")
    def post(self, body):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "tiktok_ads_resource.py",
            "TikTokBoostVideoResource",
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
            advertiser_id = body["advertiser_id"]
            spark_ad_auth_code = body["spark_ad_auth_code"]
            daily_budget_usd = body["daily_budget_usd"]
            duration_days = body["duration_days"]
            targeting_input = body.get("targeting", {})
            scheduled_post_id = body.get("scheduled_post_id")
            auto_activate = body.get("auto_activate", False)

            Log.info(
                f"{log_tag} Params advertiser_id={advertiser_id} "
                f"budget=${daily_budget_usd}/day duration={duration_days}d "
                f"objective={body.get('objective', 'VIDEO_VIEWS')}"
            )

            # -------------------------------------------------
            # Resolve access token
            # -------------------------------------------------
            ad_account = AdAccount.get_by_ad_account_id(business_id, advertiser_id)
            if not ad_account or not ad_account.get("access_token_plain"):
                Log.warning(f"{log_tag} Missing ad account or token")
                return jsonify({
                    "success": False,
                    "message": "Ad account not connected or token missing",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            access_token = ad_account["access_token_plain"]
            currency = ad_account.get("currency", "USD")

            service = TikTokAdsService(access_token, advertiser_id)

            # -------------------------------------------------
            # Build targeting
            # -------------------------------------------------
            targeting = service.build_targeting(
                locations=targeting_input.get("locations"),
                languages=targeting_input.get("languages"),
                gender=targeting_input.get("gender"),
                age_groups=targeting_input.get("age_groups"),
                interest_category_ids=targeting_input.get("interest_category_ids"),
                interest_keyword_ids=targeting_input.get("interest_keyword_ids"),
                custom_audience_ids=targeting_input.get("custom_audience_ids"),
                excluded_audience_ids=targeting_input.get("excluded_audience_ids"),
                device_type=targeting_input.get("device_type"),
                network_types=targeting_input.get("network_types"),
                household_income=targeting_input.get("household_income"),
                spending_power=targeting_input.get("spending_power"),
            ) if targeting_input else service.build_targeting()

            Log.info(f"{log_tag} Targeting built successfully")

            # -------------------------------------------------
            # Boost video
            # -------------------------------------------------
            Log.info(f"{log_tag} Sending boost request to TikTok")

            tk_start = time.time()
            result = service.boost_video(
                spark_ad_auth_code=spark_ad_auth_code,
                daily_budget=daily_budget_usd,
                duration_days=duration_days,
                objective=body.get("objective", "VIDEO_VIEWS"),
                optimization_goal=body.get("optimization_goal", "VIDEO_VIEW"),
                placements=body.get("placements"),
                bid_type=body.get("bid_type", "BID_TYPE_NO_BID"),
                bid=body.get("bid_usd"),
                billing_event=body.get("billing_event", "CPM"),
                call_to_action=body.get("call_to_action", "WATCH_NOW"),
                landing_page_url=body.get("landing_page_url"),
                targeting=targeting,
                campaign_name=body.get("campaign_name"),
                auto_activate=auto_activate,
            )
            tk_duration = time.time() - tk_start

            Log.info(f"{log_tag} TikTok boost completed in {tk_duration:.2f}s")

            if not result.get("success"):
                errors = result.get("errors", [])
                error_messages = [e.get("error", str(e)) for e in errors]
                user_msg = errors[0].get("error", "Failed to boost video") if errors else "Failed to boost video"

                Log.info(f"{log_tag} error_messages: {error_messages}")
                Log.info(f"{log_tag} Boost failed: {errors}")
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                    "message": user_msg,
                    "message_to_show": user_msg,
                    "error": errors,
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            # -------------------------------------------------
            # Persist campaign
            # -------------------------------------------------
            campaign = AdCampaign.create({
                "business_id": business_id,
                "user__id": user__id,
                "platform": "tiktok",
                "ad_account_id": advertiser_id,
                "campaign_name": body.get("campaign_name") or f"Boost Video {spark_ad_auth_code[-8:]}",
                "objective": body.get("objective", "VIDEO_VIEWS"),
                "budget_type": AdCampaign.BUDGET_DAILY,
                "budget_amount": daily_budget_usd,
                "currency": currency,
                "start_time": datetime.now(timezone.utc),
                "end_time": datetime.now(timezone.utc) + timedelta(days=duration_days),
                "targeting": targeting,
                "scheduled_post_id": scheduled_post_id,
                "tiktok_spark_post_id": result.get("spark_post_id"),
                "tiktok_campaign_id": result.get("campaign_id"),
                "tiktok_ad_group_id": result.get("ad_group_id"),
                "tiktok_ad_id": result.get("ad_id"),
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
                    "tiktok_campaign_id": result.get("campaign_id"),
                    "tiktok_ad_group_id": result.get("ad_group_id"),
                    "tiktok_ad_id": result.get("ad_id"),
                    "tiktok_spark_post_id": result.get("spark_post_id"),
                    "budget": f"{currency} {daily_budget_usd:.2f}/day",
                    "duration_days": duration_days,
                },
            }), HTTP_STATUS_CODES["CREATED"]

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
@blp_tiktok_ads.route("/social/tiktok/campaigns", methods=["GET"])
class TikTokCampaignsResource(MethodView):

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "tiktok_ads_resource.py",
            "TikTokCampaignsResource",
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
                platform="tiktok",
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
                    "total_count": result["total"],
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
@blp_tiktok_ads.route("/social/tiktok/campaigns/<campaign_id>/insights", methods=["GET"])
class TikTokCampaignInsightsResource(MethodView):
    @token_required
    def get(self, campaign_id):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))

        log_tag = make_log_tag(
            "tiktok_ads_resource.py",
            "TikTokCampaignInsightsResource",
            "get",
            client_ip,
            user.get("_id"),
            user.get("account_type"),
            business_id,
            business_id,
        )

        start_time = time.time()
        Log.info(f"{log_tag} Fetching insights for campaign={campaign_id}")

        try:
            days = int(request.args.get("days", 7))
            now = datetime.now(timezone.utc)
            start_date = request.args.get("start_date") or (now - timedelta(days=days)).strftime("%Y-%m-%d")
            end_date = request.args.get("end_date") or now.strftime("%Y-%m-%d")

            campaign = AdCampaign.get_by_id(campaign_id, business_id)
            if not campaign:
                Log.info(f"{log_tag} Campaign not found. campaign={campaign_id}")
                return jsonify({"success": False, "message": "Campaign not found"}), HTTP_STATUS_CODES["NOT_FOUND"]

            if not campaign.get("tiktok_campaign_id"):
                return jsonify({
                    "success": False,
                    "message": "Campaign not synced with TikTok",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            ad_account = AdAccount.get_by_ad_account_id(business_id, campaign["ad_account_id"])
            if not ad_account or not ad_account.get("access_token_plain"):
                return jsonify({
                    "success": False,
                    "message": "Ad account not found or token missing",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            service = TikTokAdsService(
                ad_account["access_token_plain"],
                campaign["ad_account_id"],
            )

            result = service.get_campaign_stats(
                campaign_id=campaign["tiktok_campaign_id"],
                start_date=start_date,
                end_date=end_date,
            )

            duration = time.time() - start_time
            Log.info(f"{log_tag} Insights fetched in {duration:.2f}s")

            report_data = result.get("data", {}).get("list", [])
            metrics = report_data[0].get("metrics", {}) if report_data else {}

            return jsonify({
                "success": True,
                "data": {
                    "campaign_id": campaign_id,
                    "tiktok_campaign_id": campaign.get("tiktok_campaign_id"),
                    "period": {"start": start_date, "end": end_date},
                    "metrics": {
                        "spend": float(metrics.get("spend", 0)),
                        "impressions": int(metrics.get("impressions", 0)),
                        "clicks": int(metrics.get("clicks", 0)),
                        "ctr": float(metrics.get("ctr", 0)),
                        "cpc": float(metrics.get("cpc", 0)),
                        "cpm": float(metrics.get("cpm", 0)),
                        "reach": int(metrics.get("reach", 0)),
                        "video_play_actions": int(metrics.get("video_play_actions", 0)),
                        "video_watched_6s": int(metrics.get("video_watched_6s", 0)),
                        "video_views_p100": int(metrics.get("video_views_p100", 0)),
                        "likes": int(metrics.get("likes", 0)),
                        "comments": int(metrics.get("comments", 0)),
                        "shares": int(metrics.get("shares", 0)),
                        "follows": int(metrics.get("follows", 0)),
                        "profile_visits": int(metrics.get("profile_visits", 0)),
                    },
                },
            }), HTTP_STATUS_CODES["OK"]

        except TikTokAdsError as e:
            Log.error(f"{log_tag} TikTokAdsError: {e}")
            return jsonify({
                "success": False,
                "message": f"TikTok API error: {str(e)}",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

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
@blp_tiktok_ads.route("/social/tiktok/campaigns/<campaign_id>/pause", methods=["POST"])
class TikTokCampaignPauseResource(MethodView):
    """Pause a campaign."""

    @token_required
    def post(self, campaign_id: str):
        return _update_campaign_status(campaign_id, "DISABLE", AdCampaign.STATUS_PAUSED)


# =========================================
# RESUME CAMPAIGN
# =========================================
@blp_tiktok_ads.route("/social/tiktok/campaigns/<campaign_id>/resume", methods=["POST"])
class TikTokCampaignResumeResource(MethodView):
    """Resume a paused campaign."""

    @token_required
    def post(self, campaign_id: str):
        return _update_campaign_status(campaign_id, "ENABLE", AdCampaign.STATUS_ACTIVE)


# =========================================
# SPARK AD AUTHORIZE (pre-validate)
# =========================================
@blp_tiktok_ads.route("/social/tiktok/spark-ad/authorize", methods=["POST"])
class TikTokSparkAdAuthorizeResource(MethodView):
    """
    Authorize an existing organic TikTok post as a Spark Ad.
    Useful for pre-validating an auth code before calling boost-video.
    """

    @token_required
    def post(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "tiktok_ads_resource.py",
            "TikTokSparkAdAuthorizeResource",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        body = request.get_json(silent=True) or {}
        advertiser_id = body.get("advertiser_id", "").strip()
        auth_code = body.get("spark_ad_auth_code", "").strip()

        if not advertiser_id:
            return jsonify({"success": False, "message": "advertiser_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]
        if not auth_code:
            return jsonify({"success": False, "message": "spark_ad_auth_code is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        ad_account = AdAccount.get_by_ad_account_id(business_id, advertiser_id)
        if not ad_account or not ad_account.get("access_token_plain"):
            return jsonify({
                "success": False,
                "message": "Ad account not found or token missing",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        try:
            service = TikTokAdsService(ad_account["access_token_plain"], advertiser_id)
            resp = service.authorize_spark_ad_post(auth_code)

            data_out = resp.get("data", {})
            post_id = data_out.get("item_id") or data_out.get("tiktok_item_id")

            return jsonify({
                "success": True,
                "message": "Spark Ad post authorized successfully",
                "data": {
                    "spark_post_id": post_id,
                    "raw": data_out,
                },
            }), HTTP_STATUS_CODES["OK"]

        except TikTokAdsError as e:
            Log.error(f"{log_tag} TikTokAdsError: {e}")
            return jsonify({
                "success": False,
                "message": f"Failed to authorize Spark Ad post: {str(e)}",
                "tiktok_code": e.code,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to authorize Spark Ad post",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# SEARCH INTERESTS
# =========================================
@blp_tiktok_ads.route("/social/tiktok/targeting/interests", methods=["GET"])
class TikTokTargetingInterestsResource(MethodView):
    """Get available TikTok interest categories for targeting."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "tiktok_ads_resource.py",
            "TikTokTargetingInterestsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        tk_start = time.time()
        Log.info(f"{log_tag} Fetching targeting interests")

        version = int(request.args.get("version", 2))
        language = request.args.get("language", "en")

        ad_accounts = AdAccount.list_by_business(business_id, platform="tiktok")
        if not ad_accounts:
            return jsonify({
                "success": False,
                "message": "No TikTok ad account connected",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        ad_account = AdAccount.get_by_id(ad_accounts[0]["_id"], business_id)
        if not ad_account or not ad_account.get("access_token_plain"):
            return jsonify({
                "success": False,
                "message": "Ad account token not found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            service = TikTokAdsService(
                ad_account["access_token_plain"],
                ad_account["ad_account_id"],
            )

            result = service.get_interest_categories(version=version, language=language)

            tk_duration = time.time() - tk_start
            Log.info(f"{log_tag} TikTok interest categories fetched in {tk_duration:.2f}s")

            categories = result.get("data", {}).get("interest_categories", [])

            return jsonify({
                "success": True,
                "data": [
                    {
                        "id": str(c.get("id", "")),
                        "name": c.get("label"),
                        "parent_id": c.get("parent_id"),
                        "level": c.get("level"),
                        "children": c.get("children", []),
                    }
                    for c in categories
                ],
            }), HTTP_STATUS_CODES["OK"]

        except TikTokAdsError as e:
            Log.error(f"{log_tag} TikTokAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch interest categories",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            return jsonify({
                "success": False,
                "message": "Failed to fetch interest categories",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# INTEREST KEYWORD SEARCH
# =========================================
@blp_tiktok_ads.route("/social/tiktok/targeting/interest-keywords", methods=["GET"])
class TikTokTargetingInterestKeywordsResource(MethodView):
    """Search TikTok interest keywords for targeting."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "tiktok_ads_resource.py",
            "TikTokTargetingInterestKeywordsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        query = request.args.get("q", "").strip()
        if not query or len(query) < 2:
            return jsonify({
                "success": False,
                "message": "Query must be at least 2 characters",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        language = request.args.get("language", "en")

        ad_accounts = AdAccount.list_by_business(business_id, platform="tiktok")
        if not ad_accounts:
            return jsonify({
                "success": False,
                "message": "No TikTok ad account connected",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        ad_account = AdAccount.get_by_id(ad_accounts[0]["_id"], business_id)
        if not ad_account or not ad_account.get("access_token_plain"):
            return jsonify({
                "success": False,
                "message": "Ad account token not found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            service = TikTokAdsService(
                ad_account["access_token_plain"],
                ad_account["ad_account_id"],
            )

            result = service.get_interest_keywords(keyword=query, language=language)

            keywords = result.get("data", {}).get("keywords", [])

            return jsonify({
                "success": True,
                "data": [
                    {
                        "id": str(k.get("keyword_id", "")),
                        "name": k.get("keyword"),
                        "audience_size": k.get("audience_size"),
                    }
                    for k in keywords
                ],
            }), HTTP_STATUS_CODES["OK"]

        except TikTokAdsError as e:
            Log.error(f"{log_tag} TikTokAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to search interest keywords",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            return jsonify({
                "success": False,
                "message": "Failed to search interest keywords",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# GEO LOCATIONS
# =========================================
@blp_tiktok_ads.route("/social/tiktok/targeting/locations", methods=["GET"])
class TikTokTargetingLocationsResource(MethodView):
    """Search geo locations for targeting."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "tiktok_ads_resource.py",
            "TikTokTargetingLocationsResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        q = request.args.get("q", "").strip() or None
        level = request.args.get("level", "COUNTRY").strip().upper()

        valid_levels = {"COUNTRY", "PROVINCE", "CITY", "DMA", "DISTRICT"}
        if level not in valid_levels:
            return jsonify({
                "success": False,
                "message": f"level must be one of: {', '.join(valid_levels)}",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        ad_accounts = AdAccount.list_by_business(business_id, platform="tiktok")
        if not ad_accounts:
            return jsonify({
                "success": False,
                "message": "No TikTok ad account connected",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        ad_account = AdAccount.get_by_id(ad_accounts[0]["_id"], business_id)
        if not ad_account or not ad_account.get("access_token_plain"):
            return jsonify({
                "success": False,
                "message": "Ad account token not found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            service = TikTokAdsService(
                ad_account["access_token_plain"],
                ad_account["ad_account_id"],
            )

            result = service.get_geo_locations(level=level, keyword=q)

            locations = result.get("data", {}).get("locations", [])

            return jsonify({
                "success": True,
                "data": [
                    {
                        "id": str(loc.get("location_id", "")),
                        "name": loc.get("local_name") or loc.get("name"),
                        "level": loc.get("level"),
                        "parent_id": loc.get("parent_id"),
                    }
                    for loc in locations
                ],
            }), HTTP_STATUS_CODES["OK"]

        except TikTokAdsError as e:
            Log.error(f"{log_tag} TikTokAdsError: {e}")
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
# REACH ESTIMATE
# =========================================
@blp_tiktok_ads.route("/social/tiktok/reach-estimate", methods=["GET"])
class TikTokReachEstimateResource(MethodView):
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
            "tiktok_ads_resource.py",
            "TikTokReachEstimateResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        start_time = time.time()
        Log.info(f"{log_tag} Reach estimate request started")

        advertiser_id = request.args.get("advertiser_id")
        campaign_id = request.args.get("campaign_id")
        targeting_raw = request.args.get("targeting")
        objective = request.args.get("objective", "VIDEO_VIEWS")

        if not advertiser_id:
            return jsonify({
                "success": False,
                "message": "advertiser_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Parse targeting JSON
        try:
            targeting = json.loads(targeting_raw) if targeting_raw else {}
        except Exception:
            return jsonify({
                "success": False,
                "message": "Invalid targeting JSON",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        ad_account = AdAccount.get_by_ad_account_id(business_id, advertiser_id)
        if not ad_account or not ad_account.get("access_token_plain"):
            return jsonify({
                "success": False,
                "message": "Ad account not found or token missing",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            service = TikTokAdsService(
                ad_account["access_token_plain"],
                advertiser_id,
            )

            if not targeting:
                targeting = service.build_targeting()

            result = service.get_reach_estimate(
                campaign_id=campaign_id,
                targeting=targeting,
                objective=objective,
            )

            duration = time.time() - start_time
            Log.info(f"{log_tag} Reach estimate completed in {duration:.2f}s")

            if not result.get("success"):
                Log.error(f"{log_tag} Reach estimate failed: {result.get('error')}")
                return jsonify(result), HTTP_STATUS_CODES["BAD_REQUEST"]

            return jsonify({
                "success": True,
                "data": result.get("data", {}),
            }), HTTP_STATUS_CODES["OK"]

        except TikTokAdsError as e:
            Log.error(f"{log_tag} TikTokAdsError: {e}")
            return jsonify({
                "success": False,
                "message": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to estimate reach",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# CUSTOM AUDIENCES
# =========================================
@blp_tiktok_ads.route("/social/tiktok/audiences", methods=["GET"])
class TikTokAudiencesResource(MethodView):
    """
    List custom audiences for retargeting.
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}

        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "tiktok_ads_resource.py",
            "TikTokAudiencesResource",
            "get",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        advertiser_id = request.args.get("advertiser_id")
        if not advertiser_id:
            return jsonify({
                "success": False,
                "message": "advertiser_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 20))
        except (ValueError, TypeError):
            page, per_page = 1, 20

        ad_account = AdAccount.get_by_ad_account_id(business_id, advertiser_id)
        if not ad_account or not ad_account.get("access_token_plain"):
            return jsonify({
                "success": False,
                "message": "Ad account not found or token missing",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            service = TikTokAdsService(
                ad_account["access_token_plain"],
                advertiser_id,
            )

            result = service.get_custom_audiences(page=page, page_size=per_page)

            audience_list = result.get("data", {}).get("list", [])

            return jsonify({
                "success": True,
                "data": [
                    {
                        "audience_id": str(a.get("audience_id", "")),
                        "name": a.get("name"),
                        "type": a.get("audience_type"),
                        "size": a.get("audience_size"),
                        "status": a.get("status"),
                        "create_time": a.get("create_time"),
                    }
                    for a in audience_list
                ],
            }), HTTP_STATUS_CODES["OK"]

        except TikTokAdsError as e:
            Log.error(f"{log_tag} TikTokAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch audiences",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            return jsonify({
                "success": False,
                "message": "Failed to fetch audiences",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
