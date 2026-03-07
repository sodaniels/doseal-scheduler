# app/routes/social/x_ads_resource.py

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
from ....utils.schedule_helper import _require_x_env

from ....models.social.social_account import SocialAccount
from ....models.social.ad_account import AdAccount, AdCampaign
from ....services.social.ads.x_ads_service import XAdsService, XAdsError


blp_x_ads = Blueprint("x_ads", __name__)


# ===========================================================================
# SCHEMAS
# ===========================================================================

class AccountConnectionSchema(ma.Schema):
    """Used for endpoints that need a destination_id query param."""
    destination_id = ma.fields.Str(required=False, load_default=None)


class XAdAccountConnectSchema(ma.Schema):
    """Body for POST /social/x/ad-accounts/connect"""
    ad_account_id = ma.fields.Str(
        required=True,
        metadata={"description": "X ads account ID (base-36, e.g. '18ce54d4x5t')"},
    )


class XTargetingCriterionSchema(ma.Schema):
    """
    A single targeting criterion for X ads.

    targeting_type examples:
        LOCATION, LANGUAGE, GENDER, AGE, INTEREST, KEYWORD,
        BROAD_KEYWORD, EXACT_KEYWORD, PHRASE_KEYWORD, NEGATIVE_KEYWORD,
        FOLLOWER_OF_USER, SIMILAR_TO_FOLLOWERS_OF_USER,
        PLATFORM, TAILORED_AUDIENCE
    """
    targeting_type = ma.fields.Str(required=True)
    targeting_value = ma.fields.Str(required=True)
    tailored_audience_expansion = ma.fields.Bool(load_default=False)
    tailored_audience_type = ma.fields.Str(load_default=None)


class XBoostTweetSchema(ma.Schema):
    """Body for POST /social/x/boost-tweet"""

    # Required
    ad_account_id = ma.fields.Str(
        required=True,
        metadata={"description": "Connected X ads account ID"},
    )
    tweet_id = ma.fields.Str(
        required=True,
        metadata={"description": "Numeric tweet ID of the tweet to boost"},
    )
    funding_instrument_id = ma.fields.Str(
        required=True,
        metadata={"description": "Funding instrument ID from GET /funding-instruments"},
    )
    daily_budget_usd = ma.fields.Float(
        required=True,
        metadata={"description": "Daily budget in USD, e.g. 10.0 for $10/day"},
    )
    duration_days = ma.fields.Int(
        required=True,
        metadata={"description": "Number of days to run the boost"},
    )

    # Optional campaign config
    objective = ma.fields.Str(
        load_default="ENGAGEMENTS",
        metadata={
            "description": (
                "Campaign objective. One of: ENGAGEMENTS, WEBSITE_CLICKS, "
                "APP_INSTALLS, VIDEO_VIEWS, FOLLOWERS, APP_ENGAGEMENTS, "
                "AWARENESS, REACH, PREROLL_VIEWS"
            )
        },
    )
    placements = ma.fields.List(
        ma.fields.Str(),
        load_default=["ALL_ON_TWITTER"],
        metadata={"description": "Ad placements. Default: ['ALL_ON_TWITTER']"},
    )
    bid_type = ma.fields.Str(
        load_default="AUTO",
        metadata={"description": "Bid type: AUTO (default) | MAX | TARGET"},
    )
    bid_amount_usd = ma.fields.Float(
        load_default=None,
        metadata={"description": "Bid amount in USD. Required for MAX or TARGET bid_type"},
    )

    # Targeting — list of criteria objects
    targeting = ma.fields.List(
        ma.fields.Nested(XTargetingCriterionSchema),
        load_default=[],
        metadata={
            "description": (
                "Targeting criteria. Each item must have targeting_type and targeting_value. "
                "Use GET /targeting/locations and GET /targeting/interests to find valid values. "
                "Defaults to US + English if empty."
            )
        },
    )

    # Optional extras
    scheduled_post_id = ma.fields.Str(
        load_default=None,
        metadata={"description": "Optional: link to a Schedulefy scheduled post"},
    )
    auto_activate = ma.fields.Bool(
        load_default=False,
        metadata={
            "description": (
                "If true, campaign is set to ACTIVE immediately. "
                "If false (default), campaign is created PAUSED."
            )
        },
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

    @ma.validates("bid_type")
    def validate_bid_type(self, value):
        valid = {"AUTO", "MAX", "TARGET"}
        if value not in valid:
            raise ma.ValidationError(f"bid_type must be one of: {valid}")

    @ma.validates("objective")
    def validate_objective(self, value):
        valid = {
            "ENGAGEMENTS", "WEBSITE_CLICKS", "APP_INSTALLS", "VIDEO_VIEWS",
            "FOLLOWERS", "APP_ENGAGEMENTS", "AWARENESS", "REACH", "PREROLL_VIEWS",
        }
        if value not in valid:
            raise ma.ValidationError(f"objective must be one of: {valid}")

    @ma.validates_schema
    def validate_bid_amount(self, data, **kwargs):
        if data.get("bid_type") in ("MAX", "TARGET") and not data.get("bid_amount_usd"):
            raise ma.ValidationError(
                "bid_amount_usd is required when bid_type is MAX or TARGET"
            )


# ===========================================================================
# HELPERS
# ===========================================================================

def _get_x_service_for_campaign(campaign_id: str, business_id: str):
    """
    Resolve AdAccount + XAdsService for a given campaign.
    Returns (service, campaign, ad_account) or raises ValueError with a message.
    """
    campaign = AdCampaign.get_by_id(campaign_id, business_id)
    if not campaign:
        raise ValueError("Campaign not found")

    if not campaign.get("x_campaign_id"):
        raise ValueError("Campaign not synced with X")

    ad_account = AdAccount.get_by_ad_account_id(business_id, campaign["ad_account_id"])
    if not ad_account or not ad_account.get("access_token_plain"):
        raise ValueError("Ad account not found or credentials missing")

    service = _build_service(ad_account)
    return service, campaign, ad_account


def _build_service(ad_account: dict) -> XAdsService:
    """
    Build an XAdsService from a stored AdAccount document.

    OAuth 1.0a credential layout (matches SocialAccount/AdAccount doc):
        consumer_key / consumer_secret   -- app-level env vars via _require_x_env()
        access_token                     -- stored as access_token_plain
        access_token_secret              -- stored as refresh_token_plain
                                           (X OAuth 1.0a has no refresh token;
                                            we reuse this field for the token secret)
    """
    log_tag = "[x_ads_resource.py][_build_service]"
    consumer_key, consumer_secret, _ = _require_x_env(log_tag)
    return XAdsService(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        access_token=ad_account.get("access_token_plain"),
        access_token_secret=ad_account.get("refresh_token_plain"),
        account_id=ad_account.get("ad_account_id"),
    )


def _update_campaign_status(campaign_id: str, x_status: str, local_status: str):
    """Pause or resume a campaign on X and update the local record."""
    user = g.get("current_user", {}) or {}
    business_id = str(user.get("business_id", ""))
    log_tag = f"[x_ads_resource.py][UpdateCampaignStatus][{campaign_id}]"

    try:
        service, campaign, _ = _get_x_service_for_campaign(campaign_id, business_id)
    except ValueError as e:
        return jsonify({
            "success": False,
            "message": str(e),
        }), HTTP_STATUS_CODES["BAD_REQUEST"]

    try:
        service.update_campaign_status(campaign["x_campaign_id"], x_status)
        AdCampaign.update_status(campaign_id, business_id, local_status)

        return jsonify({
            "success": True,
            "message": f"Campaign {x_status.lower()} successfully",
        }), HTTP_STATUS_CODES["OK"]

    except XAdsError as e:
        Log.error(f"{log_tag} XAdsError: {e}")
        return jsonify({
            "success": False,
            "message": str(e),
        }), HTTP_STATUS_CODES["BAD_REQUEST"]

    except Exception as e:
        Log.error(f"{log_tag} Exception: {e}")
        return jsonify({
            "success": False,
            "message": "Failed to update campaign status",
        }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


def _get_first_ad_account(business_id: str):
    """
    Convenience: fetch the first connected X ad account for targeting discovery
    endpoints that don't take an explicit ad_account_id.
    Returns (ad_account, error_response_tuple | None).
    """
    ad_accounts = AdAccount.list_by_business(business_id)
    if not ad_accounts:
        return None, (
            jsonify({"success": False, "message": "No X ad account connected"}),
            HTTP_STATUS_CODES["BAD_REQUEST"],
        )

    ad_account = AdAccount.get_by_id(ad_accounts[0]["_id"], business_id)
    if not ad_account:
        return None, (
            jsonify({"success": False, "message": "Ad account not found"}),
            HTTP_STATUS_CODES["BAD_REQUEST"],
        )

    return ad_account, None


# ===========================================================================
# LIST AVAILABLE X AD ACCOUNTS
# ===========================================================================

@blp_x_ads.route("/social/x/ad-accounts/available", methods=["GET"])
class XAdAccountsAvailableResource(MethodView):
    """
    List X ad accounts visible to the authenticated user.
    Reads OAuth 1.0a credentials stored in the SocialAccount meta field.
    """

    @token_required
    @blp_x_ads.arguments(AccountConnectionSchema, location="query")
    def get(self, item_data):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "x_ads_resource.py", "XAdAccountsAvailableResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        x_account = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="x",
            destination_id=item_data.get("destination_id"),
        )

        if not x_account:
            return jsonify({
                "success": False,
                "message": "X account not found.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # OAuth 1.0a credentials:
        #   consumer_key/secret  -- app-level env vars via _require_x_env()
        #   access_token         -- access_token_plain on the SocialAccount doc
        #   access_token_secret  -- refresh_token_plain (reused field; OAuth 1.0a has no refresh token)
        consumer_key, consumer_secret, _ = _require_x_env(log_tag)
        if not consumer_key or not consumer_secret:
            return jsonify({
                "success": False,
                "message": "X Ads app credentials not configured. Contact support.",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        access_token = x_account.get("access_token_plain")
        access_token_secret = x_account.get("refresh_token_plain")

        if not access_token or not access_token_secret:
            return jsonify({
                "success": False,
                "message": "X OAuth credentials missing. Please reconnect your X account.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            start_time = time.time()

            # No account_id needed — just list all accounts on the token
            service = XAdsService(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                access_token=access_token,
                access_token_secret=access_token_secret,
                account_id="",
            )

            resp = service.get_all_accounts()
            accounts_raw = resp.get("data", [])
            if isinstance(accounts_raw, dict):
                accounts_raw = [accounts_raw]

            duration = time.time() - start_time
            Log.info(f"{log_tag} Fetched {len(accounts_raw)} X ad accounts in {duration:.2f}s")

            formatted = [
                {
                    "ad_account_id": acc.get("id"),
                    "name": acc.get("name"),
                    "timezone": acc.get("timezone"),
                    "currency": acc.get("currency"),
                    "approval_status": acc.get("approval_status"),
                    "industry_type": acc.get("industry_type"),
                }
                for acc in accounts_raw
            ]

            return jsonify({
                "success": True,
                "data": formatted,
            }), HTTP_STATUS_CODES["OK"]

        except XAdsError as e:
            Log.error(f"{log_tag} XAdsError: {e}")
            error_msg = str(e)
            if "401" in error_msg or "auth" in error_msg.lower():
                return jsonify({
                    "success": False,
                    "message": "Authentication failed. Please reconnect your X account.",
                    "code": "AUTH_FAILED",
                }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            return jsonify({
                "success": False,
                "message": "Failed to fetch X ad accounts",
                "error": error_msg,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch X ad accounts",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# CONNECT AD ACCOUNT
# ===========================================================================

@blp_x_ads.route("/social/x/ad-accounts/connect", methods=["POST"])
class XAdAccountConnectResource(MethodView):
    """Connect an X ad account to the business."""

    @token_required
    @blp_x_ads.arguments(XAdAccountConnectSchema, location="form")
    def post(self, body):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "x_ads_resource.py", "XAdAccountConnectResource", "post",
            client_ip, user__id, account_type, business_id, business_id,
        )

        ad_account_id = body.get("ad_account_id")
        if not ad_account_id:
            return jsonify({
                "success": False,
                "message": "ad_account_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Fetch X social account for OAuth credentials
        x_accounts = SocialAccount.list_destinations(business_id, user__id, "x")
        if not x_accounts:
            return jsonify({
                "success": False,
                "message": "No X account connected.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        x_account = SocialAccount.get_destination(
            business_id, user__id, "x",
            x_accounts[0].get("destination_id"),
        )

        # OAuth 1.0a credentials from the SocialAccount doc
        consumer_key, consumer_secret, _ = _require_x_env(log_tag)
        if not consumer_key or not consumer_secret:
            return jsonify({
                "success": False,
                "message": "X Ads app credentials not configured. Contact support.",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

        access_token = (x_account or {}).get("access_token_plain")
        access_token_secret = (x_account or {}).get("refresh_token_plain")

        if not access_token or not access_token_secret:
            return jsonify({
                "success": False,
                "message": "X OAuth credentials not found. Please reconnect your X account.",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        # Check already connected
        existing = AdAccount.get_by_ad_account_id(business_id, ad_account_id)
        if existing:
            return jsonify({
                "success": False,
                "message": "This X ad account is already connected.",
                "code": "ALREADY_CONNECTED",
            }), HTTP_STATUS_CODES["CONFLICT"]

        try:
            service = XAdsService(
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                access_token=access_token,
                access_token_secret=access_token_secret,
                account_id=ad_account_id,
            )

            account_info = service.get_account()
            if not account_info:
                return jsonify({
                    "success": False,
                    "message": "Cannot access this X ad account.",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            start_time = time.time()

            ad_account = AdAccount.create({
                "business_id": business_id,
                "user__id": user__id,
                "platform": "x",
                "ad_account_id": account_info.get("id"),
                "ad_account_name": account_info.get("name"),
                "currency": account_info.get("currency"),
                "timezone_name": account_info.get("timezone"),
                "approval_status": account_info.get("approval_status"),
                # Store user OAuth 1.0a tokens as access_token_plain / refresh_token_plain
                # consumer_key / consumer_secret are app-level env vars, not stored per-user
                "access_token": ad_account_id,  # placeholder; actual token stored below
                "access_token_plain": access_token,
                "refresh_token_plain": access_token_secret,
                "meta": {
                    "oauth_version": "1.0a",
                    "user_id": (x_account or {}).get("platform_user_id"),
                    "screen_name": (x_account or {}).get("platform_username"),
                },
            })

            Log.info(f"{log_tag} X ad account connected in {time.time() - start_time:.2f}s")

            return jsonify({
                "success": True,
                "message": "X ad account connected successfully",
                "data": {
                    "_id": ad_account["_id"],
                    "ad_account_id": ad_account["ad_account_id"],
                    "ad_account_name": ad_account["ad_account_name"],
                    "currency": ad_account["currency"],
                },
            }), HTTP_STATUS_CODES["CREATED"]

        except XAdsError as e:
            Log.error(f"{log_tag} XAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Cannot access this X ad account. Check your permissions.",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to connect X ad account",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# LIST CONNECTED AD ACCOUNTS
# ===========================================================================

@blp_x_ads.route("/social/x/ad-accounts", methods=["GET"])
class XAdAccountsResource(MethodView):
    """List X ad accounts connected to this business."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "x_ads_resource.py", "XAdAccountsResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        start_time = time.time()
        Log.info(f"{log_tag} Fetching connected X ad accounts")

        try:
            ad_accounts = AdAccount.list_by_business(business_id, platform="x")
            Log.info(
                f"{log_tag} Retrieved {len(ad_accounts)} accounts "
                f"in {time.time() - start_time:.2f}s"
            )
            return jsonify({"success": True, "data": ad_accounts}), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to retrieve X ad accounts",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# FUNDING INSTRUMENTS
# ===========================================================================

@blp_x_ads.route("/social/x/ad-accounts/<ad_account_id>/funding-instruments", methods=["GET"])
class XFundingInstrumentsResource(MethodView):
    """
    List funding instruments (payment methods) for an X ad account.
    The frontend needs a funding_instrument_id before it can call boost-tweet.
    """

    @token_required
    def get(self, ad_account_id):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "x_ads_resource.py", "XFundingInstrumentsResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        ad_account = AdAccount.get_by_ad_account_id(business_id, ad_account_id)
        if not ad_account:
            return jsonify({
                "success": False,
                "message": "Ad account not found",
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        try:
            start_time = time.time()
            service = _build_service(ad_account)
            resp = service.get_funding_instruments()

            raw = resp.get("data", [])
            if isinstance(raw, dict):
                raw = [raw]

            Log.info(
                f"{log_tag} Fetched {len(raw)} funding instruments "
                f"in {time.time() - start_time:.2f}s"
            )

            formatted = [
                {
                    "id": fi.get("id"),
                    "description": fi.get("description"),
                    "type": fi.get("type"),
                    "currency": fi.get("currency"),
                    "credit_limit_local_micro": fi.get("credit_limit_local_micro"),
                    "funded_amount_local_micro": fi.get("funded_amount_local_micro"),
                    "cancelled": fi.get("cancelled", False),
                }
                for fi in raw
                if not fi.get("cancelled") and not fi.get("deleted")
            ]

            return jsonify({"success": True, "data": formatted}), HTTP_STATUS_CODES["OK"]

        except XAdsError as e:
            Log.error(f"{log_tag} XAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch funding instruments",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to fetch funding instruments",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# BOOST TWEET
# ===========================================================================

@blp_x_ads.route("/social/x/boost-tweet", methods=["POST"])
class XBoostTweetResource(MethodView):
    """
    Boost (promote) an existing tweet.

    Flow:
        1. Create campaign
        2. Create line item (ad group) with targeting
        3. Associate tweet as promoted tweet
        4. Persist AdCampaign locally
    """

    @token_required
    @blp_x_ads.arguments(XBoostTweetSchema, location="json")
    def post(self, body):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "x_ads_resource.py", "XBoostTweetResource", "post",
            client_ip, user__id, account_type, business_id, business_id,
        )

        start_time = time.time()
        Log.info(f"{log_tag} Boost tweet request received")

        try:
            ad_account_id = body["ad_account_id"]
            tweet_id = body["tweet_id"]
            funding_instrument_id = body["funding_instrument_id"]
            daily_budget_usd = body["daily_budget_usd"]
            duration_days = body["duration_days"]
            objective = body.get("objective", "ENGAGEMENTS")
            placements = body.get("placements", ["ALL_ON_TWITTER"])
            bid_type = body.get("bid_type", "AUTO")
            bid_amount_usd = body.get("bid_amount_usd")
            targeting_input = body.get("targeting", [])
            scheduled_post_id = body.get("scheduled_post_id")
            auto_activate = body.get("auto_activate", False)

            Log.info(
                f"{log_tag} tweet_id={tweet_id} budget=${daily_budget_usd}/day "
                f"duration={duration_days}d objective={objective}"
            )

            # -------------------------------------------------
            # Resolve ad account + credentials
            # -------------------------------------------------
            ad_account = AdAccount.get_by_ad_account_id(business_id, ad_account_id)
            if not ad_account:
                return jsonify({
                    "success": False,
                    "message": "Ad account not connected",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]

            service = _build_service(ad_account)
            currency = ad_account.get("currency", "USD")

            # -------------------------------------------------
            # Boost
            # -------------------------------------------------
            x_start = time.time()

            result = service.boost_tweet(
                tweet_id=tweet_id,
                funding_instrument_id=funding_instrument_id,
                campaign_name=f"Boost Tweet {tweet_id[-8:]}",
                daily_budget_usd=daily_budget_usd,
                objective=objective,
                placements=placements,
                bid_type=bid_type,
                bid_amount_usd=bid_amount_usd,
                targeting=targeting_input or None,
                auto_activate=auto_activate,
            )

            x_duration = time.time() - x_start
            Log.info(f"{log_tag} X boost completed in {x_duration:.2f}s")

            if not result.get("success"):
                errors = result.get("errors", [])
                error_messages = [e.get("error", str(e)) for e in errors]
                user_msg = errors[0].get("error", "Failed to boost tweet") if errors else "Failed to boost tweet"

                Log.info(f"{log_tag} Boost failed errors={error_messages}")
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
            now = datetime.now(timezone.utc)
            campaign = AdCampaign.create({
                "business_id": business_id,
                "user__id": user__id,
                "platform": "x",
                "ad_account_id": ad_account_id,
                "campaign_name": f"Boost Tweet {tweet_id[-8:]}",
                "objective": objective,
                "budget_type": AdCampaign.BUDGET_DAILY,
                "budget_amount": daily_budget_usd,
                "currency": currency,
                "start_time": now,
                "end_time": now + timedelta(days=duration_days),
                "targeting": targeting_input,
                "scheduled_post_id": scheduled_post_id,
                "tweet_id": tweet_id,
                "x_campaign_id": result.get("campaign_id"),
                "x_line_item_id": result.get("line_item_id"),
                "x_promoted_tweet_id": result.get("promoted_tweet_id"),
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
                    "x_campaign_id": result.get("campaign_id"),
                    "x_line_item_id": result.get("line_item_id"),
                    "x_promoted_tweet_id": result.get("promoted_tweet_id"),
                    "budget": f"{currency} {daily_budget_usd:.2f}/day",
                    "duration_days": duration_days,
                    "entity_status": "ACTIVE" if auto_activate else "PAUSED",
                },
            }), HTTP_STATUS_CODES["CREATED"]

        except XAdsError as e:
            Log.error(f"{log_tag} XAdsError: {e}")
            errors = e.errors or []
            user_msg = errors[0].get("message", str(e)) if errors else str(e)
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                "message": user_msg,
                "message_to_show": user_msg,
                "error": errors,
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except ValueError as e:
            # e.g. invalid objective or placement from service validation
            return jsonify({
                "success": False,
                "message": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception after {time.time() - start_time:.2f}s err={e}")
            return jsonify({
                "success": False,
                "message": "Failed to boost tweet",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# LIST CAMPAIGNS
# ===========================================================================

@blp_x_ads.route("/social/x/campaigns", methods=["GET"])
class XCampaignsResource(MethodView):
    """List locally persisted X campaigns for this business."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "x_ads_resource.py", "XCampaignsResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        start_time = time.time()
        Log.info(f"{log_tag} Fetching X campaigns")

        try:
            page = int(request.args.get("page", 1))
            per_page = int(request.args.get("per_page", 20))
            status = request.args.get("status")

            result = AdCampaign.list_by_business(
                business_id=business_id,
                platform="x",
                status=status,
                page=page,
                per_page=per_page,
            )

            Log.info(f"{log_tag} Retrieved campaigns in {time.time() - start_time:.2f}s")

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
                "message": "Failed to fetch X campaigns",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# GET CAMPAIGN STATS
# ===========================================================================

@blp_x_ads.route("/social/x/campaigns/<campaign_id>/stats", methods=["GET"])
class XCampaignStatsResource(MethodView):
    """Fetch live engagement stats for a campaign from the X Ads API."""

    @token_required
    def get(self, campaign_id):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))

        log_tag = make_log_tag(
            "x_ads_resource.py", "XCampaignStatsResource", "get",
            client_ip, user.get("_id"), user.get("account_type"),
            business_id, business_id,
        )

        start_time = time.time()
        Log.info(f"{log_tag} Fetching stats for campaign={campaign_id}")

        granularity = request.args.get("granularity", "DAY")   # HOUR | DAY | TOTAL
        metric_groups = request.args.get("metric_groups", "ENGAGEMENT,BILLING").split(",")

        try:
            service, campaign, _ = _get_x_service_for_campaign(campaign_id, business_id)
        except ValueError as e:
            return jsonify({"success": False, "message": str(e)}), HTTP_STATUS_CODES["NOT_FOUND"]

        try:
            data = service.get_campaign_stats(
                campaign_ids=[campaign["x_campaign_id"]],
                granularity=granularity,
                metric_groups=metric_groups,
            )

            Log.info(f"{log_tag} Stats fetched in {time.time() - start_time:.2f}s")

            return jsonify({"success": True, "data": data}), HTTP_STATUS_CODES["OK"]

        except XAdsError as e:
            Log.error(f"{log_tag} XAdsError: {e}")
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
# PAUSE CAMPAIGN
# ===========================================================================

@blp_x_ads.route("/social/x/campaigns/<campaign_id>/pause", methods=["POST"])
class XCampaignPauseResource(MethodView):
    """Pause an active X campaign."""

    @token_required
    def post(self, campaign_id):
        return _update_campaign_status(campaign_id, "PAUSED", AdCampaign.STATUS_PAUSED)


# ===========================================================================
# RESUME CAMPAIGN
# ===========================================================================

@blp_x_ads.route("/social/x/campaigns/<campaign_id>/resume", methods=["POST"])
class XCampaignResumeResource(MethodView):
    """Resume a paused X campaign."""

    @token_required
    def post(self, campaign_id):
        return _update_campaign_status(campaign_id, "ACTIVE", AdCampaign.STATUS_ACTIVE)


# ===========================================================================
# SEARCH TARGETING — INTERESTS
# ===========================================================================

@blp_x_ads.route("/social/x/targeting/interests", methods=["GET"])
class XTargetingInterestsResource(MethodView):
    """Search X interest targeting categories."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "x_ads_resource.py", "XTargetingInterestsResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        query = request.args.get("q", "")
        if not query or len(query) < 2:
            return jsonify({
                "success": False,
                "message": "Query must be at least 2 characters",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        ad_account, err = _get_first_ad_account(business_id)
        if err:
            return err

        try:
            start_time = time.time()
            service = _build_service(ad_account)
            resp = service.search_interests(query)

            raw = resp.get("data", [])
            if isinstance(raw, dict):
                raw = [raw]

            Log.info(
                f"{log_tag} Fetched {len(raw)} interests in {time.time() - start_time:.2f}s"
            )

            return jsonify({
                "success": True,
                "data": [{"id": i.get("id"), "name": i.get("name")} for i in raw],
            }), HTTP_STATUS_CODES["OK"]

        except XAdsError as e:
            Log.error(f"{log_tag} XAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to search interests",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to search interests",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# SEARCH TARGETING — LOCATIONS
# ===========================================================================

@blp_x_ads.route("/social/x/targeting/locations", methods=["GET"])
class XTargetingLocationsResource(MethodView):
    """Search location WOEIDs for X targeting."""

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "x_ads_resource.py", "XTargetingLocationsResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        query = request.args.get("q", "")
        location_type = request.args.get("location_type")  # CITY | REGION | COUNTRY | METRO

        if not query or len(query) < 2:
            return jsonify({
                "success": False,
                "message": "Query must be at least 2 characters",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        ad_account, err = _get_first_ad_account(business_id)
        if err:
            return err

        try:
            start_time = time.time()
            service = _build_service(ad_account)
            resp = service.search_locations(query, location_type=location_type)

            raw = resp.get("data", [])
            if isinstance(raw, dict):
                raw = [raw]

            Log.info(
                f"{log_tag} Fetched {len(raw)} locations in {time.time() - start_time:.2f}s"
            )

            return jsonify({
                "success": True,
                "data": [
                    {
                        "woeid": loc.get("targeting_value"),
                        "name": loc.get("name"),
                        "location_type": loc.get("location_type"),
                        "country_code": loc.get("country_code"),
                    }
                    for loc in raw
                ],
            }), HTTP_STATUS_CODES["OK"]

        except XAdsError as e:
            Log.error(f"{log_tag} XAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to search locations",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to search locations",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# ===========================================================================
# REACH ESTIMATE
# ===========================================================================

@blp_x_ads.route("/social/x/reach-estimate", methods=["GET"])
class XReachEstimateResource(MethodView):
    """
    Estimate audience size before spending.

    Query params:
        ad_account_id  : required
        targeting      : JSON-encoded list of {targeting_type, targeting_value}
        objective      : optional (default ENGAGEMENTS)
    """

    @token_required
    def get(self):
        client_ip = request.remote_addr
        user = g.get("current_user", {}) or {}
        business_id = str(user.get("business_id", ""))
        user__id = str(user.get("_id", ""))
        account_type = user.get("account_type")

        log_tag = make_log_tag(
            "x_ads_resource.py", "XReachEstimateResource", "get",
            client_ip, user__id, account_type, business_id, business_id,
        )

        start_time = time.time()

        ad_account_id = request.args.get("ad_account_id")
        targeting_raw = request.args.get("targeting")
        objective = request.args.get("objective", "ENGAGEMENTS")

        if not ad_account_id:
            return jsonify({
                "success": False,
                "message": "ad_account_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            targeting = json.loads(targeting_raw) if targeting_raw else []
        except Exception:
            return jsonify({
                "success": False,
                "message": "Invalid targeting JSON",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        ad_account = AdAccount.get_by_ad_account_id(business_id, ad_account_id)
        if not ad_account:
            return jsonify({
                "success": False,
                "message": "Ad account not found",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        try:
            service = _build_service(ad_account)
            estimate = service.get_reach_estimate(
                targeting_criteria=targeting,
                objective=objective,
            )

            Log.info(f"{log_tag} Reach estimate completed in {time.time() - start_time:.2f}s")

            if not estimate.get("success"):
                Log.error(f"{log_tag} Reach estimate failed: {estimate.get('error')}")
                return jsonify(estimate), HTTP_STATUS_CODES["BAD_REQUEST"]

            return jsonify({
                "success": True,
                "data": {
                    "audience_size": estimate["data"].get("audience_size"),
                    "bid": estimate["data"].get("bid"),
                    "budget": estimate["data"].get("budget"),
                },
            }), HTTP_STATUS_CODES["OK"]

        except XAdsError as e:
            Log.error(f"{log_tag} XAdsError: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to estimate reach",
                "error": str(e),
            }), HTTP_STATUS_CODES["BAD_REQUEST"]

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return jsonify({
                "success": False,
                "message": "Failed to estimate reach",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
