# app/resources/social/linkedin_ads_resource.py

import json
import os
import time
from datetime import datetime, timezone, timedelta

import marshmallow as ma
from flask_smorest import Blueprint
from flask import request, jsonify, g
from flask.views import MethodView

from ...doseal.admin.admin_business_resource import token_required
from ....constants.service_code import HTTP_STATUS_CODES
from ....utils.logger import Log
from ....utils.helpers import make_log_tag

from ....models.social.social_account import SocialAccount
from ....models.social.ad_account import AdAccount, AdCampaign
from ....services.social.ads.linkedin_ads_service import LinkedInAdsService, LinkedInAdsError


blp_linkedin_ads = Blueprint("linkedin_ads", __name__)


# ===========================================================================
# SCHEMAS
# ===========================================================================

class AccountConnectionSchema(ma.Schema):
    """Used for endpoints that need a destination_id query param."""
    destination_id = ma.fields.Str(required=False, load_default=None)


class LinkedInAdAccountConnectSchema(ma.Schema):
    """Body for POST /social/linkedin/ad-accounts/connect"""
    ad_account_id = ma.fields.Str(
        required=True,
        metadata={"description": "LinkedIn Ad Account ID (numeric string)"},
    )
    destination_id = ma.fields.Str(
        required=True,
        metadata={"description": "Destination ID (numeric string)"},
    )
    


class LinkedInTargetingFacetSchema(ma.Schema):
    """Single targeting facet: a URN string."""
    urn = ma.fields.Str(required=True)


class LinkedInAgeRangeSchema(ma.Schema):
    start = ma.fields.Int(required=True)
    end = ma.fields.Int(required=True)


class LinkedInTargetingSchema(ma.Schema):
    """Targeting input for boost-post."""
    locations = ma.fields.List(
        ma.fields.Str(),
        load_default=None,
        metadata={"description": "Geo URNs e.g. ['urn:li:geo:90009696'] (US). Use GET /targeting/locations?q=..."},
    )
    job_titles = ma.fields.List(
        ma.fields.Str(),
        load_default=None,
        metadata={"description": "Title URNs from GET /targeting/job-titles"},
    )
    industries = ma.fields.List(
        ma.fields.Str(),
        load_default=None,
        metadata={"description": "Industry URNs from GET /targeting/industries"},
    )
    skills = ma.fields.List(
        ma.fields.Str(),
        load_default=None,
        metadata={"description": "Skill URNs from GET /targeting/skills"},
    )
    seniorities = ma.fields.List(
        ma.fields.Str(),
        load_default=None,
        metadata={"description": "Seniority URNs e.g. urn:li:seniority:10 (Senior)"},
    )
    company_sizes = ma.fields.List(
        ma.fields.Str(),
        load_default=None,
        metadata={"description": "Company size codes: A=1, B=2-10, C=11-50, D=51-200, E=201-500, F=501-1000, G=1001-5000, H=5001-10000, I=10001+"},
    )
    member_age_ranges = ma.fields.List(
        ma.fields.Nested(LinkedInAgeRangeSchema),
        load_default=None,
        metadata={"description": "Age ranges e.g. [{\"start\": 25, \"end\": 34}]"},
    )
    member_gender = ma.fields.Str(
        load_default=None,
        metadata={"description": "MALE | FEMALE | null (all)"},
    )


class LinkedInBoostPostSchema(ma.Schema):
    """Body for POST /social/linkedin/boost-post"""

    # Required
    ad_account_id = ma.fields.Str(
        required=True,
        metadata={"description": "Connected LinkedIn ad account ID"},
    )
    post_urn = ma.fields.Str(
        required=True,
        metadata={"description": "URN of the post to boost: urn:li:ugcPost:<id> or urn:li:share:<id>"},
    )
    daily_budget_usd = ma.fields.Float(
        required=True,
        metadata={"description": "Daily budget in USD e.g. 10.0 for $10/day (minimum ~$10)"},
    )
    duration_days = ma.fields.Int(
        required=True,
        metadata={"description": "Number of days to run the boost (1-365)"},
    )

    # Optional campaign config
    objective = ma.fields.Str(
        load_default="ENGAGEMENT",
        metadata={
            "description": (
                "Campaign objective. One of: ENGAGEMENT, WEBSITE_VISITS, "
                "BRAND_AWARENESS, LEAD_GENERATION, VIDEO_VIEWS"
            )
        },
    )
    bid_strategy = ma.fields.Str(
        load_default="AUTOMATED",
        metadata={"description": "AUTOMATED (default) | MAXIMUM_CPM | TARGET_COST_PER_CLICK"},
    )
    bid_amount_usd = ma.fields.Float(
        load_default=None,
        metadata={"description": "Bid amount in USD. Required for non-AUTOMATED bid_strategy."},
    )
    locale_country = ma.fields.Str(
        load_default="US",
        metadata={"description": "ISO country code for campaign locale e.g. US, GB"},
    )
    locale_language = ma.fields.Str(
        load_default="en",
        metadata={"description": "ISO language code e.g. en, fr, es"},
    )

    # Targeting
    targeting = ma.fields.Nested(
        LinkedInTargetingSchema,
        load_default=None,
        metadata={"description": "Targeting criteria. Defaults to US if omitted."},
    )

    # Optional extras
    scheduled_post_id = ma.fields.Str(
        load_default=None,
        metadata={"description": "Optional: link to a Schedulefy scheduled post"},
    )
    auto_activate = ma.fields.Bool(
        load_default=False,
        metadata={"description": "If true, campaign is set ACTIVE immediately. Default: PAUSED."},
    )

    @ma.validates("daily_budget_usd")
    def validate_budget(self, value):
        if value <= 0:
            raise ma.ValidationError("daily_budget_usd must be greater than 0")

    @ma.validates("duration_days")
    def validate_duration(self, value):
        if value < 1:
            raise ma.ValidationError("duration_days must be at least 1")
        if value > 365:
            raise ma.ValidationError("duration_days cannot exceed 365")

    @ma.validates("bid_strategy")
    def validate_bid_strategy(self, value):
        valid = {"AUTOMATED", "MAXIMUM_CPM", "TARGET_COST_PER_CLICK"}
        if value not in valid:
            raise ma.ValidationError(f"bid_strategy must be one of: {valid}")

    @ma.validates("objective")
    def validate_objective(self, value):
        valid = {
            "ENGAGEMENT", "WEBSITE_VISITS", "BRAND_AWARENESS",
            "LEAD_GENERATION", "VIDEO_VIEWS",
        }
        if value not in valid:
            raise ma.ValidationError(f"objective must be one of: {valid}")

    @ma.validates_schema
    def validate_bid_amount(self, data, **kwargs):
        if data.get("bid_strategy") != "AUTOMATED" and not data.get("bid_amount_usd"):
            raise ma.ValidationError(
                "bid_amount_usd is required when bid_strategy is not AUTOMATED"
            )


# ===========================================================================
# HELPERS
# ===========================================================================

def _usd_to_minor(usd: float) -> int:
    """Convert USD float to minor currency units (cents). e.g. 10.0 → 1000"""
    return int(round(usd * 100))


def _build_service(ad_account: dict) -> LinkedInAdsService:
    """
    Build a LinkedInAdsService from a stored AdAccount document.

    LinkedIn uses OAuth 2.0.
    access_token is stored as access_token_plain on the SocialAccount/AdAccount doc.
    """
    return LinkedInAdsService(
        access_token=ad_account.get("access_token_plain"),
        ad_account_id=ad_account.get("ad_account_id"),
    )


def _build_service_from_social_account(social_account: dict, ad_account_id: str = None) -> LinkedInAdsService:
    """Build a LinkedInAdsService directly from a SocialAccount (for account discovery)."""
    return LinkedInAdsService(
        access_token=social_account.get("access_token_plain"),
        ad_account_id=ad_account_id,
    )


def _get_linkedin_service_for_campaign(campaign_id: str, business_id: str):
    """
    Resolve AdAccount + LinkedInAdsService for a given campaign.
    Returns (service, campaign, ad_account) or raises ValueError.
    """
    campaign = AdCampaign.get_by_id(campaign_id, business_id)
    if not campaign:
        raise ValueError("Campaign not found")

    if not campaign.get("linkedin_campaign_id"):
        raise ValueError("Campaign not synced with LinkedIn")

    ad_account = AdAccount.get_by_ad_account_id(business_id, campaign["ad_account_id"])
    if not ad_account or not ad_account.get("access_token_plain"):
        raise ValueError("Ad account not found or credentials missing")

    service = _build_service(ad_account)
    return service, campaign, ad_account


def _update_campaign_status(campaign_id: str, li_status: str, local_status: str):
    """Pause or resume a LinkedIn campaign and update the local record."""
    user = g.get("current_user", {}) or {}
    business_id = str(user.get("business_id", ""))

    try:
        service, campaign, _ = _get_linkedin_service_for_campaign(campaign_id, business_id)
        service.update_campaign_status(campaign["linkedin_campaign_id"], li_status)
        AdCampaign.update_status(campaign_id, business_id, local_status)
        return jsonify({
            "success": True,
            "message": f"Campaign {li_status.lower()} successfully",
        }), HTTP_STATUS_CODES["OK"]

    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), HTTP_STATUS_CODES["NOT_FOUND"]

    except LinkedInAdsError as e:
        return jsonify({
            "success": False,
            "message": f"LinkedIn API error: {str(e)}",
        }), HTTP_STATUS_CODES["BAD_REQUEST"]

    except Exception:
        return jsonify({
            "success": False,
            "message": "Failed to update campaign status",
        }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# LIST AVAILABLE LINKEDIN AD ACCOUNTS
# ===========================================================================

@blp_linkedin_ads.route("/social/linkedin/ad-accounts/available", methods=["GET"])
class LinkedInAdAccountsAvailableResource(MethodView):
    """
    List LinkedIn ad accounts visible to the authenticated user's access token.
    Reads the SocialAccount access_token_plain for the connected LinkedIn account.
    """

    @token_required
    @blp_linkedin_ads.arguments(AccountConnectionSchema, location="query")
    def get(self, item_data):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "linkedin_ads_resource.py", "LinkedInAdAccountsAvailableResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        linkedin_account = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="linkedin",
            destination_id=item_data.get("destination_id"),
        )

        if not linkedin_account:
            return jsonify({
                "success": False,
                "message": "LinkedIn account not connected. Please connect your LinkedIn account first.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        access_token = linkedin_account.get("access_token_plain")
        if not access_token:
            return jsonify({
                "success": False,
                "message": "LinkedIn access token missing. Please reconnect your LinkedIn account.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            start_time = time.time()
            service = LinkedInAdsService(access_token=access_token)
            resp = service.get_ad_accounts()

            raw = resp.get("data", {})
            elements = raw.get("elements", [])

            Log.info(
                f"{log_tag} Fetched {len(elements)} LinkedIn ad accounts "
                f"in {time.time() - start_time:.2f}s"
            )

            formatted = [
                {
                    "id": str(acc.get("id", "")),
                    "name": acc.get("name"),
                    "currency": acc.get("currency"),
                    "status": acc.get("status"),
                    "type": acc.get("type"),
                }
                for acc in elements
                if acc.get("status") != "CANCELED"
            ]

            return jsonify({"success": True, "data": formatted}), HTTP_STATUS_CODES["OK"]

        except LinkedInAdsError as e:
            Log.error(f"{log_tag} LinkedInAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch LinkedIn ad accounts",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch LinkedIn ad accounts",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# CONNECT AD ACCOUNT
# ===========================================================================

@blp_linkedin_ads.route("/social/linkedin/ad-accounts/connect", methods=["POST"])
class LinkedInAdAccountConnectResource(MethodView):
    """
    Connect a LinkedIn ad account to this business.
    Verifies the account is accessible, then stores it in AdAccount.
    """

    @token_required
    @blp_linkedin_ads.arguments(LinkedInAdAccountConnectSchema, location="json")
    def post(self, body):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "linkedin_ads_resource.py", "LinkedInAdAccountConnectResource", "post",
            client_ip, user__id, account_type, business_id, business_id,
        )

        ad_account_id = body.get("ad_account_id", "").strip()
        destination_id = body.get("destination_id", "").strip()

        linkedin_account = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            destination_id=destination_id,
            platform="linkedin",
        )

        if not linkedin_account:
            return jsonify({
                "success": False,
                "message": "LinkedIn account not connected. Please connect your LinkedIn account first.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        access_token = linkedin_account.get("access_token_plain")
        if not access_token:
            return jsonify({
                "success": False,
                "message": "LinkedIn access token missing. Please reconnect your LinkedIn account.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Check already connected
        existing = AdAccount.get_by_ad_account_id(business_id, ad_account_id)
        if existing:
            return jsonify({
                "success": False,
                "message": "This LinkedIn ad account is already connected.",
                "code": "ALREADY_CONNECTED",
            }), HTTP_STATUS_CODES["CONFLICT"]

        try:
            service = LinkedInAdsService(
                access_token=access_token,
                ad_account_id=ad_account_id,
            )

            account_info_resp = service.get_ad_account()
            account_info = account_info_resp.get("data", {})

            if not account_info:
                return jsonify({
                    "success": False,
                    "message": "Cannot access this LinkedIn ad account. Check your permissions.",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            start_time = time.time()

            ad_account = AdAccount.create({
                "business_id": business_id,
                "user__id": user__id,
                "platform": "linkedin",
                "ad_account_id": str(account_info.get("id", ad_account_id)),
                "ad_account_name": account_info.get("name"),
                "currency": account_info.get("currency", "USD"),
                # Store access token for API calls
                "access_token_plain": access_token,
                "refresh_token_plain": linkedin_account.get("refresh_token_plain"),
                "token_expires_at": linkedin_account.get("token_expires_at"),
                "meta": {
                    "account_type": account_info.get("type"),
                    "status": account_info.get("status"),
                    "linkedin_user_id": linkedin_account.get("platform_user_id"),
                },
            })

            Log.info(f"{log_tag} LinkedIn ad account connected in {time.time() - start_time:.2f}s")

            return jsonify({
                "success": True,
                "message": "LinkedIn ad account connected successfully",
                "data": {
                    "_id": str(ad_account.get("_id", "")),
                    "ad_account_id": ad_account.get("ad_account_id"),
                    "ad_account_name": ad_account.get("ad_account_name"),
                    "currency": ad_account.get("currency"),
                },
            }), HTTP_STATUS_CODES["CREATED"]

        except LinkedInAdsError as e:
            Log.error(f"{log_tag} LinkedInAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Cannot access this LinkedIn ad account. Check your permissions.",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to connect LinkedIn ad account",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# LIST CONNECTED AD ACCOUNTS
# ===========================================================================

@blp_linkedin_ads.route("/social/linkedin/ad-accounts", methods=["GET"])
class LinkedInAdAccountsResource(MethodView):
    """List LinkedIn ad accounts connected to this business."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "linkedin_ads_resource.py", "LinkedInAdAccountsResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        try:
            start_time = time.time()
            ad_accounts = AdAccount.list_by_business(business_id, platform="linkedin")
            Log.info(
                f"{log_tag} Retrieved {len(ad_accounts)} accounts "
                f"in {time.time() - start_time:.2f}s"
            )
            return jsonify({"success": True, "data": ad_accounts}), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to retrieve LinkedIn ad accounts",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# BOOST POST
# ===========================================================================

@blp_linkedin_ads.route("/social/linkedin/boost-post", methods=["POST"])
class LinkedInBoostPostResource(MethodView):
    """
    Boost (promote) an existing LinkedIn post as Sponsored Content.

    Flow:
        1. Create campaign group
        2. Create campaign (objective, budget, targeting)
        3. Create creative (links existing post URN)
        4. Persist AdCampaign locally
    """

    @token_required
    @blp_linkedin_ads.arguments(LinkedInBoostPostSchema, location="json")
    def post(self, body):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "linkedin_ads_resource.py", "LinkedInBoostPostResource", "post",
            client_ip, user__id, account_type, business_id, business_id,
        )

        ad_account_id = body.get("ad_account_id")
        post_urn = body.get("post_urn")
        daily_budget_usd = body.get("daily_budget_usd")
        duration_days = body.get("duration_days")
        objective = body.get("objective", "ENGAGEMENT")
        bid_strategy = body.get("bid_strategy", "AUTOMATED")
        bid_amount_usd = body.get("bid_amount_usd")
        targeting_input = body.get("targeting")
        auto_activate = body.get("auto_activate", False)
        scheduled_post_id = body.get("scheduled_post_id")
        locale_country = body.get("locale_country", "US")
        locale_language = body.get("locale_language", "en")

        Log.info(
            f"{log_tag} Boost request: ad_account={ad_account_id} "
            f"post_urn={post_urn} budget=${daily_budget_usd}/day "
            f"duration={duration_days}d objective={objective}"
        )

        # Resolve ad account
        ad_account = AdAccount.get_by_ad_account_id(business_id, ad_account_id)
        if not ad_account:
            return jsonify({
                "success": False,
                "message": "Ad account not connected",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        service = _build_service(ad_account)

        # Build targeting
        targeting = None
        if targeting_input:
            targeting = service.build_targeting(
                locations=targeting_input.get("locations"),
                job_titles=targeting_input.get("job_titles"),
                industries=targeting_input.get("industries"),
                skills=targeting_input.get("skills"),
                seniorities=targeting_input.get("seniorities"),
                company_sizes=targeting_input.get("company_sizes"),
                member_age_ranges=targeting_input.get("member_age_ranges"),
                member_gender=targeting_input.get("member_gender"),
            )

        # Convert USD to minor units
        daily_budget_minor = _usd_to_minor(daily_budget_usd)
        bid_amount_minor = _usd_to_minor(bid_amount_usd) if bid_amount_usd else None

        try:
            li_start = time.time()

            result = service.boost_post(
                post_urn=post_urn,
                daily_budget=daily_budget_minor,
                duration_days=duration_days,
                objective=objective,
                targeting=targeting,
                bid_strategy=bid_strategy,
                bid_amount=bid_amount_minor,
                auto_activate=auto_activate,
                locale={"country": locale_country, "language": locale_language},
            )

            li_duration = time.time() - li_start
            Log.info(f"{log_tag} LinkedIn boost completed in {li_duration:.2f}s")

            if not result.get("success"):
                errors = result.get("errors", [])
                user_msg = errors[0].get("error", "Failed to boost post") if errors else "Failed to boost post"
                Log.info(f"{log_tag} Boost failed errors={errors}")
                return jsonify({
                    "success": False,
                    "message": user_msg,
                    "error": errors,
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            # Persist campaign
            now = datetime.now(timezone.utc)
            campaign = AdCampaign.create({
                "business_id": business_id,
                "user__id": user__id,
                "platform": "linkedin",
                "ad_account_id": ad_account_id,
                "campaign_name": f"Boost Post {post_urn.split(':')[-1][-8:]}",
                "post_id": post_urn,
                "scheduled_post_id": scheduled_post_id,
                "linkedin_campaign_group_id": result.get("campaign_group_id"),
                "linkedin_campaign_id": result.get("campaign_id"),
                "linkedin_creative_id": result.get("creative_id"),
                "budget_type": AdCampaign.BUDGET_DAILY,
                "budget_amount": daily_budget_usd,
                "duration_days": duration_days,
                "objective": objective,
                "status": AdCampaign.STATUS_ACTIVE if auto_activate else AdCampaign.STATUS_PAUSED,
                "start_date": now.isoformat(),
                "end_date": (now + timedelta(days=duration_days)).isoformat(),
                "meta": {
                    "bid_strategy": bid_strategy,
                    "post_urn": post_urn,
                    "locale": {"country": locale_country, "language": locale_language},
                },
            })

            Log.info(f"{log_tag} AdCampaign persisted: {campaign.get('_id')}")

            return jsonify({
                "success": True,
                "message": "Post boosted successfully",
                "data": {
                    "campaign_id": str(campaign.get("_id", "")),
                    "linkedin_campaign_group_id": result.get("campaign_group_id"),
                    "linkedin_campaign_id": result.get("campaign_id"),
                    "linkedin_creative_id": result.get("creative_id"),
                    "status": "active" if auto_activate else "paused",
                },
            }), HTTP_STATUS_CODES["CREATED"]

        except LinkedInAdsError as e:
            Log.error(f"{log_tag} LinkedInAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "LinkedIn API error. Check your ad account permissions.",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to boost post",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# LIST CAMPAIGNS
# ===========================================================================

@blp_linkedin_ads.route("/social/linkedin/campaigns", methods=["GET"])
class LinkedInCampaignsResource(MethodView):
    """List LinkedIn campaigns for this business (local records)."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "linkedin_ads_resource.py", "LinkedInCampaignsResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 20))
            status = request.args.get("status")

            result = AdCampaign.list_by_business(
                business_id=business_id,
                platform="linkedin",
                status=status,
                page=page,
                per_page=per_page,
            )

            return jsonify({
                "success": True,
                "data": result.get("items", []),
                "total": result.get("total", 0),
                "total_pages": result.get("total_pages", 1),
                "current_page": result.get("current_page", 1),
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to retrieve LinkedIn campaigns",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# CAMPAIGN STATS
# ===========================================================================

@blp_linkedin_ads.route("/social/linkedin/campaigns/<campaign_id>/stats", methods=["GET"])
class LinkedInCampaignStatsResource(MethodView):
    """Get live LinkedIn campaign analytics."""

    @token_required
    def get(self, campaign_id):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "linkedin_ads_resource.py", "LinkedInCampaignStatsResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        try:
            service, campaign, _ = _get_linkedin_service_for_campaign(campaign_id, business_id)

            # Optional date range from query params
            days = int(request.args.get("days", 7))
            now = datetime.now(timezone.utc)
            date_range_start = now - timedelta(days=days)

            resp = service.get_campaign_stats(
                campaign_id=campaign["linkedin_campaign_id"],
                date_range_start=date_range_start,
                date_range_end=now,
            )

            elements = resp.get("data", {}).get("elements", [])
            stats = elements[0] if elements else {}

            return jsonify({
                "success": True,
                "data": {
                    "impressions": stats.get("impressions", 0),
                    "clicks": stats.get("clicks", 0),
                    "spend": stats.get("costInLocalCurrency", "0"),
                    "engagements": stats.get("totalEngagements", 0),
                    "likes": stats.get("likes", 0),
                    "comments": stats.get("comments", 0),
                    "shares": stats.get("shares", 0),
                    "follows": stats.get("follows", 0),
                    "unique_impressions": stats.get("uniqueImpressions", 0),
                },
            }), HTTP_STATUS_CODES["OK"]

        except ValueError as e:
            return jsonify({"success": False, "message": str(e)}), HTTP_STATUS_CODES["NOT_FOUND"]

        except LinkedInAdsError as e:
            Log.error(f"{log_tag} LinkedInAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch campaign stats",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch campaign stats",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# PAUSE / RESUME
# ===========================================================================

@blp_linkedin_ads.route("/social/linkedin/campaigns/<campaign_id>/pause", methods=["POST"])
class LinkedInCampaignPauseResource(MethodView):

    @token_required
    def post(self, campaign_id):
        return _update_campaign_status(campaign_id, "PAUSED", AdCampaign.STATUS_PAUSED)


@blp_linkedin_ads.route("/social/linkedin/campaigns/<campaign_id>/resume", methods=["POST"])
class LinkedInCampaignResumeResource(MethodView):

    @token_required
    def post(self, campaign_id):
        return _update_campaign_status(campaign_id, "ACTIVE", AdCampaign.STATUS_ACTIVE)


# ===========================================================================
# TARGETING DISCOVERY
# ===========================================================================

@blp_linkedin_ads.route("/social/linkedin/targeting/locations", methods=["GET"])
class LinkedInTargetingLocationsResource(MethodView):
    """Search geo location URNs. Pass q= query string."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "linkedin_ads_resource.py", "LinkedInTargetingLocationsResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        q = request.args.get("q", "").strip()
        if len(q) < 2:
            return jsonify({
                "success": False,
                "message": "q must be at least 2 characters",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            ad_accounts = AdAccount.list_by_business(business_id, platform="linkedin")
            if not ad_accounts:
                return jsonify({"success": False, "message": "No LinkedIn ad account connected"}), HTTP_STATUS_CODES["BAD_REQUEST"]

            ad_account = AdAccount.get_by_id(ad_accounts[0]["_id"], business_id)
            service = _build_service(ad_account)
            resp = service.search_geo_locations(q)

            elements = resp.get("data", {}).get("elements", [])
            return jsonify({
                "success": True,
                "data": [
                    {"urn": e.get("urn"), "name": e.get("name", {}).get("en", "")}
                    for e in elements
                ],
            }), HTTP_STATUS_CODES["OK"]

        except LinkedInAdsError as e:
            Log.error(f"{log_tag} LinkedInAdsError: {e}")
            return jsonify({"success": False, "message": str(e)}), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({"success": False, "message": "Failed to search locations"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


@blp_linkedin_ads.route("/social/linkedin/targeting/job-titles", methods=["GET"])
class LinkedInTargetingJobTitlesResource(MethodView):
    """Search job title URNs. Pass q= query string."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "linkedin_ads_resource.py", "LinkedInTargetingJobTitlesResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        q = request.args.get("q", "").strip()
        if len(q) < 2:
            return jsonify({"success": False, "message": "q must be at least 2 characters"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            ad_accounts = AdAccount.list_by_business(business_id, platform="linkedin")
            if not ad_accounts:
                return jsonify({"success": False, "message": "No LinkedIn ad account connected"}), HTTP_STATUS_CODES["BAD_REQUEST"]

            ad_account = AdAccount.get_by_id(ad_accounts[0]["_id"], business_id)
            service = _build_service(ad_account)
            resp = service.search_job_titles(q)

            elements = resp.get("data", {}).get("elements", [])
            return jsonify({
                "success": True,
                "data": [
                    {"urn": e.get("urn"), "name": e.get("name", {}).get("en", "")}
                    for e in elements
                ],
            }), HTTP_STATUS_CODES["OK"]

        except LinkedInAdsError as e:
            Log.error(f"{log_tag} LinkedInAdsError: {e}")
            return jsonify({"success": False, "message": str(e)}), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({"success": False, "message": "Failed to search job titles"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


@blp_linkedin_ads.route("/social/linkedin/targeting/industries", methods=["GET"])
class LinkedInTargetingIndustriesResource(MethodView):
    """Search industry URNs. Pass q= query string."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "linkedin_ads_resource.py", "LinkedInTargetingIndustriesResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        q = request.args.get("q", "").strip()
        if len(q) < 2:
            return jsonify({"success": False, "message": "q must be at least 2 characters"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            ad_accounts = AdAccount.list_by_business(business_id, platform="linkedin")
            if not ad_accounts:
                return jsonify({"success": False, "message": "No LinkedIn ad account connected"}), HTTP_STATUS_CODES["BAD_REQUEST"]

            ad_account = AdAccount.get_by_id(ad_accounts[0]["_id"], business_id)
            service = _build_service(ad_account)
            resp = service.search_industries(q)

            elements = resp.get("data", {}).get("elements", [])
            return jsonify({
                "success": True,
                "data": [
                    {"urn": e.get("urn"), "name": e.get("name", {}).get("en", "")}
                    for e in elements
                ],
            }), HTTP_STATUS_CODES["OK"]

        except LinkedInAdsError as e:
            Log.error(f"{log_tag} LinkedInAdsError: {e}")
            return jsonify({"success": False, "message": str(e)}), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({"success": False, "message": "Failed to search industries"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# REACH ESTIMATE
# ===========================================================================

@blp_linkedin_ads.route("/social/linkedin/reach-estimate", methods=["GET"])
class LinkedInReachEstimateResource(MethodView):
    """
    Get estimated audience size for a targeting spec.

    Query params:
        ad_account_id : required
        targeting     : JSON-encoded targeting object (from build_targeting output)
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "linkedin_ads_resource.py", "LinkedInReachEstimateResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        ad_account_id = request.args.get("ad_account_id")
        targeting_raw = request.args.get("targeting")

        if not ad_account_id:
            return jsonify({"success": False, "message": "ad_account_id is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        if not targeting_raw:
            return jsonify({"success": False, "message": "targeting is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            targeting = json.loads(targeting_raw)
        except (json.JSONDecodeError, TypeError):
            return jsonify({"success": False, "message": "targeting must be valid JSON"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            ad_account = AdAccount.get_by_ad_account_id(business_id, ad_account_id)
            if not ad_account:
                return jsonify({"success": False, "message": "Ad account not found"}), HTTP_STATUS_CODES["NOT_FOUND"]

            service = _build_service(ad_account)
            result = service.get_reach_estimate(targeting)

            return jsonify(result), HTTP_STATUS_CODES["OK"]

        except LinkedInAdsError as e:
            Log.error(f"{log_tag} LinkedInAdsError: {e}")
            return jsonify({"success": False, "message": str(e)}), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({"success": False, "message": "Failed to get reach estimate"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
