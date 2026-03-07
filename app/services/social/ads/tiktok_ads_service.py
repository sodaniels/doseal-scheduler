# app/services/social/ads/tiktok_ads_service.py

import json
import time
import requests
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ....utils.logger import Log


class TikTokAdsError(Exception):
    """
    Raised when the TikTok Marketing API returns a non-success response.

    Attributes:
        code        : TikTok error code (int)
        errors      : list of error dicts
        status_code : HTTP status code
    """

    def __init__(self, message: str, code: int = None, errors: list = None, status_code: int = None):
        super().__init__(message)
        self.code = code
        self.errors = errors or []
        self.status_code = status_code

    def __str__(self):
        base = super().__str__()
        if self.code:
            return f"{base} | TikTok code: {self.code}"
        return base


class TikTokAdsService:
    """
    Service for managing TikTok Ads via the TikTok Marketing API v1.3.

    Flow for boosting a video (Spark Ads):
        1. Authorize existing organic post as Spark Ad
        2. Create Campaign          (objective)
        3. Create Ad Group          (targeting, budget, bid, placement, schedule)
        4. Create Ad                (links Spark Ad post to ad group)

    TikTok API hierarchy:
        Advertiser Account → Campaign → Ad Group → Ad

    Auth:
        access_token  — long-lived OAuth 2.0 token from TikTok for Business
        advertiser_id — TikTok ad account ID (passed per-request, not in URL)

    Budget:
        TikTok uses whole currency units (e.g. 10.0 = $10.00 USD).
        Minimum daily budget is $20 USD per ad group.
        Minimum lifetime budget is $20 USD.

    Spark Ads:
        To boost an existing organic TikTok video, the post owner must
        generate a "Spark Ad authorization code" from TikTok Creator Studio.
        This code is passed to create_spark_ad_post() which returns a post_id
        usable as the creative in an ad.

    Base URL: https://business-api.tiktok.com/open_api/v1.3/
    """

    BASE_URL = "https://business-api.tiktok.com/open_api/v1.3"

    # Valid campaign objectives
    VALID_OBJECTIVES = {
        "REACH",
        "TRAFFIC",
        "APP_PROMOTION",
        "LEAD_GENERATION",
        "ENGAGEMENT",
        "VIDEO_VIEWS",
        "CONVERSIONS",
        "CATALOG_SALES",
        "COMMUNITY_INTERACTION",
    }

    # Valid placement types
    VALID_PLACEMENTS = {
        "PLACEMENT_TIKTOK",
        "PLACEMENT_PANGLE",
        "PLACEMENT_TOPVIEW",
    }

    # Valid bid strategies
    VALID_BID_STRATEGIES = {
        "BID_TYPE_NO_BID",       # Lowest cost (auto)
        "BID_TYPE_CUSTOM_BID",   # Manual bid
        "BID_TYPE_MAX_CONVERSIONS",
    }

    # Valid optimization goals (per objective)
    VALID_OPTIMIZATION_GOALS = {
        "CLICK",
        "REACH",
        "SHOW",
        "VIDEO_VIEW",
        "LEAD",
        "APP_INSTALL",
        "CONVERT",
        "ENGAGED_VIEW",
    }

    def __init__(self, access_token: str, advertiser_id: str = None):
        self.access_token = access_token
        self.advertiser_id = str(advertiser_id) if advertiser_id else None

    def _require_account(self):
        if not self.advertiser_id:
            raise ValueError(
                "advertiser_id is required for this operation. "
                "Initialize the service with an advertiser_id."
            )

    def _headers(self) -> Dict[str, str]:
        return {
            "Access-Token": self.access_token,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_body: Optional[Dict] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Make an authenticated request to the TikTok Marketing API.

        TikTok Marketing API response shape:
        {
            "code": 0,          # 0 = success, non-zero = error
            "message": "OK",
            "data": { ... }
        }

        All errors are surfaced as TikTokAdsError.
        """
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        log_tag = f"[TikTokAdsService][_request][{method}][{endpoint}]"

        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                headers=self._headers(),
                params=params,
                json=json_body,
                timeout=timeout,
            )

            try:
                result = response.json()
            except Exception:
                result = {"message": response.text}

            # TikTok returns HTTP 200 for most errors — check the code field
            tiktok_code = result.get("code", -1)
            message = result.get("message", "Unknown error")

            if not response.ok or tiktok_code != 0:
                Log.error(f"{log_tag} API error code={tiktok_code} message={message} http={response.status_code}")
                raise TikTokAdsError(
                    f"TikTok API error on {method.upper()} {url}: {message}",
                    code=tiktok_code,
                    errors=[{"code": tiktok_code, "message": message}],
                    status_code=response.status_code,
                )

            return {"success": True, "data": result.get("data", {})}

        except TikTokAdsError:
            raise

        except requests.Timeout:
            Log.error(f"{log_tag} Request timeout")
            raise TikTokAdsError("Request timeout", errors=[{"message": "Request timeout"}])

        except Exception as e:
            Log.error(f"{log_tag} Request failed: {e}")
            raise TikTokAdsError(str(e), errors=[{"message": str(e)}])

    def _get(self, endpoint: str, params: Dict = None) -> Dict:
        return self._request("GET", endpoint, params=params)

    def _post(self, endpoint: str, body: Dict = None) -> Dict:
        return self._request("POST", endpoint, json_body=body)

    # =========================================
    # AD ACCOUNTS
    # =========================================

    def get_advertiser_info(self) -> Dict[str, Any]:
        """
        Get info about the current advertiser account.
        Returns name, currency, timezone, status, industry.
        """
        self._require_account()
        return self._get(
            "advertiser/info/",
            params={
                "advertiser_id": self.advertiser_id,
                "fields": json.dumps([
                    "advertiser_id", "advertiser_name", "currency",
                    "timezone", "status", "industry",
                ]),
            },
        )

    def get_accessible_accounts(self, app_id: str, secret: str) -> Dict[str, Any]:
        """
        List all advertiser accounts accessible via this app.
        Used during the account discovery / connect flow.

        GET /open_api/v1.3/oauth2/advertiser/get/

        NOTE: This endpoint requires app_id, secret, AND access_token all
        as query params — the Access-Token header alone is NOT sufficient.
        access_token here is the Marketing API access token, NOT the
        Content API token from the TikTok Creator / posting OAuth flow.

        These are two separate tokens from two separate TikTok app registrations:
          - Content API  → open.tiktokapis.com  (client_key / client_secret)
          - Marketing API → business-api.tiktok.com (app_id / secret)
        """
        return self._get(
            "oauth2/advertiser/get/",
            params={
                "app_id": app_id,
                "secret": secret,
                "access_token": self.access_token,
            },
        )

    # =========================================
    # CAMPAIGNS
    # =========================================

    def create_campaign(
        self,
        name: str,
        objective: str = "VIDEO_VIEWS",
        budget_mode: str = "BUDGET_MODE_INFINITE",
        budget: float = None,
        status: str = "CAMPAIGN_STATUS_ENABLE",
        special_industries: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a campaign.

        objective:
            REACH, TRAFFIC, APP_PROMOTION, LEAD_GENERATION,
            ENGAGEMENT, VIDEO_VIEWS, CONVERSIONS, CATALOG_SALES,
            COMMUNITY_INTERACTION

        budget_mode:
            BUDGET_MODE_INFINITE   — no campaign-level budget cap (use ad group budget)
            BUDGET_MODE_DAY        — daily campaign budget
            BUDGET_MODE_TOTAL      — lifetime campaign budget

        status:
            CAMPAIGN_STATUS_ENABLE | CAMPAIGN_STATUS_DISABLE
        """
        self._require_account()

        body: Dict[str, Any] = {
            "advertiser_id": self.advertiser_id,
            "campaign_name": name,
            "objective_type": objective,
            "budget_mode": budget_mode,
            "operation_status": status,
            "special_industries": special_industries or [],
        }

        if budget and budget_mode != "BUDGET_MODE_INFINITE":
            body["budget"] = budget

        return self._post("campaign/create/", body=body)

    def update_campaign(self, campaign_id: str, updates: Dict) -> Dict[str, Any]:
        """Update a campaign."""
        self._require_account()
        body = {"advertiser_id": self.advertiser_id, "campaign_id": campaign_id, **updates}
        return self._post("campaign/update/", body=body)

    def update_campaign_status(self, campaign_ids: List[str], status: str) -> Dict[str, Any]:
        """
        Update status for one or more campaigns.
        status: ENABLE | DISABLE | DELETE
        """
        self._require_account()
        return self._post("campaign/status/update/", body={
            "advertiser_id": self.advertiser_id,
            "campaign_ids": campaign_ids,
            "operation_status": status,
        })

    def get_campaigns(
        self,
        campaign_ids: List[str] = None,
        status: str = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """List campaigns for this advertiser."""
        self._require_account()

        body: Dict[str, Any] = {
            "advertiser_id": self.advertiser_id,
            "page": page,
            "page_size": page_size,
            "fields": [
                "campaign_id", "campaign_name", "objective_type",
                "budget", "budget_mode", "operation_status",
                "create_time", "modify_time",
            ],
        }
        if campaign_ids:
            body["filtering"] = {"campaign_ids": campaign_ids}
        if status:
            body.setdefault("filtering", {})["primary_status"] = status

        return self._post("campaign/get/", body=body)

    # =========================================
    # AD GROUPS
    # =========================================

    def create_ad_group(
        self,
        campaign_id: str,
        name: str,
        placements: List[str] = None,
        budget_mode: str = "BUDGET_MODE_DAY",
        budget: float = 20.0,
        schedule_type: str = "SCHEDULE_FROM_NOW",
        start_time: str = None,
        end_time: str = None,
        optimization_goal: str = "VIDEO_VIEW",
        bid_type: str = "BID_TYPE_NO_BID",
        bid: float = None,
        billing_event: str = "CPM",
        targeting: Dict[str, Any] = None,
        status: str = "AD_STATUS_ENABLE",
    ) -> Dict[str, Any]:
        """
        Create an ad group (TikTok equivalent of Facebook Ad Set / X Line Item).

        budget_mode:
            BUDGET_MODE_DAY   — daily budget (min $20 USD)
            BUDGET_MODE_TOTAL — lifetime budget

        schedule_type:
            SCHEDULE_FROM_NOW — start immediately, end at end_time or run indefinitely
            SCHEDULE_START_END — explicit start and end time

        start_time / end_time: UTC timestamp strings "2025-01-01 00:00:00"

        optimization_goal:
            CLICK, REACH, SHOW, VIDEO_VIEW, LEAD, APP_INSTALL, CONVERT, ENGAGED_VIEW

        bid_type:
            BID_TYPE_NO_BID        — lowest cost / auto bid
            BID_TYPE_CUSTOM_BID    — manual bid amount required
            BID_TYPE_MAX_CONVERSIONS

        billing_event: CPM | CPC | CPV | OCPM

        targeting: from build_targeting()
        """
        self._require_account()

        body: Dict[str, Any] = {
            "advertiser_id": self.advertiser_id,
            "campaign_id": campaign_id,
            "adgroup_name": name,
            "placement_type": "PLACEMENT_TYPE_NORMAL",
            "placements": placements or ["PLACEMENT_TIKTOK"],
            "budget_mode": budget_mode,
            "budget": budget,
            "schedule_type": schedule_type,
            "optimization_goal": optimization_goal,
            "bid_type": bid_type,
            "billing_event": billing_event,
            "operation_status": status,
        }

        if bid and bid_type == "BID_TYPE_CUSTOM_BID":
            body["bid_price"] = bid

        if schedule_type == "SCHEDULE_START_END":
            if start_time:
                body["schedule_start_time"] = start_time
            if end_time:
                body["schedule_end_time"] = end_time
        elif end_time:
            body["schedule_end_time"] = end_time

        if targeting:
            body.update(targeting)

        return self._post("adgroup/create/", body=body)

    def update_ad_group(self, ad_group_id: str, updates: Dict) -> Dict[str, Any]:
        """Update an ad group."""
        self._require_account()
        body = {"advertiser_id": self.advertiser_id, "adgroup_id": ad_group_id, **updates}
        return self._post("adgroup/update/", body=body)

    def update_ad_group_status(self, ad_group_ids: List[str], status: str) -> Dict[str, Any]:
        """
        Update status for one or more ad groups.
        status: ENABLE | DISABLE | DELETE
        """
        self._require_account()
        return self._post("adgroup/status/update/", body={
            "advertiser_id": self.advertiser_id,
            "adgroup_ids": ad_group_ids,
            "operation_status": status,
        })

    def get_ad_groups(
        self,
        campaign_ids: List[str] = None,
        ad_group_ids: List[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """List ad groups."""
        self._require_account()

        body: Dict[str, Any] = {
            "advertiser_id": self.advertiser_id,
            "page": page,
            "page_size": page_size,
            "fields": [
                "adgroup_id", "adgroup_name", "campaign_id",
                "budget", "budget_mode", "operation_status",
                "optimization_goal", "bid_type", "bid_price",
                "schedule_start_time", "schedule_end_time",
                "create_time", "modify_time",
            ],
        }

        filtering = {}
        if campaign_ids:
            filtering["campaign_ids"] = campaign_ids
        if ad_group_ids:
            filtering["adgroup_ids"] = ad_group_ids
        if filtering:
            body["filtering"] = filtering

        return self._post("adgroup/get/", body=body)

    # =========================================
    # ADS (CREATIVES)
    # =========================================

    def create_spark_ad(
        self,
        ad_group_id: str,
        name: str,
        spark_ad_post_id: str,
        call_to_action: str = "WATCH_NOW",
        status: str = "AD_STATUS_ENABLE",
    ) -> Dict[str, Any]:
        """
        Create a Spark Ad using an existing organic TikTok post.

        spark_ad_post_id: obtained from authorize_spark_ad_post()
            — this is NOT the raw video ID, it's the authorized post ID.

        call_to_action:
            WATCH_NOW, LEARN_MORE, SHOP_NOW, SIGN_UP, DOWNLOAD,
            BOOK_NOW, CONTACT_US, APPLY_NOW, ORDER_NOW, GET_QUOTE,
            SUBSCRIBE, VISIT_STORE, INTERESTED, PLAY_GAME, DOWNLOAD_NOW
        """
        self._require_account()

        body = {
            "advertiser_id": self.advertiser_id,
            "adgroup_id": ad_group_id,
            "ads": [{
                "ad_name": name,
                "ad_format": "SINGLE_VIDEO",
                "tiktok_item_id": spark_ad_post_id,
                "ad_type": "SPARK_ADS",
                "call_to_action": call_to_action,
                "operation_status": status,
            }],
        }

        return self._post("ad/create/", body=body)

    def create_video_ad(
        self,
        ad_group_id: str,
        name: str,
        video_id: str,
        identity_id: str,
        identity_type: str = "CUSTOMIZED_USER",
        ad_text: str = "",
        call_to_action: str = "WATCH_NOW",
        landing_page_url: str = None,
        display_name: str = None,
        avatar_icon_web_uri: str = None,
        status: str = "AD_STATUS_ENABLE",
    ) -> Dict[str, Any]:
        """
        Create a standard in-feed video ad (non-Spark).

        video_id: from upload_video()
        identity_id: TikTok Business identity ID
        identity_type: CUSTOMIZED_USER | AUTH_CODE | TT_USER
        """
        self._require_account()

        ad_payload: Dict[str, Any] = {
            "ad_name": name,
            "ad_format": "SINGLE_VIDEO",
            "ad_type": "NORMAL_ADS",
            "video_id": video_id,
            "identity_id": identity_id,
            "identity_type": identity_type,
            "ad_text": ad_text,
            "call_to_action": call_to_action,
            "operation_status": status,
        }

        if landing_page_url:
            ad_payload["landing_page_url"] = landing_page_url
        if display_name:
            ad_payload["display_name"] = display_name
        if avatar_icon_web_uri:
            ad_payload["avatar_icon_web_uri"] = avatar_icon_web_uri

        body = {
            "advertiser_id": self.advertiser_id,
            "adgroup_id": ad_group_id,
            "ads": [ad_payload],
        }

        return self._post("ad/create/", body=body)

    def update_ad_status(self, ad_ids: List[str], status: str) -> Dict[str, Any]:
        """
        Update status for one or more ads.
        status: ENABLE | DISABLE | DELETE
        """
        self._require_account()
        return self._post("ad/status/update/", body={
            "advertiser_id": self.advertiser_id,
            "ad_ids": ad_ids,
            "operation_status": status,
        })

    def get_ads(
        self,
        campaign_ids: List[str] = None,
        ad_group_ids: List[str] = None,
        ad_ids: List[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """List ads."""
        self._require_account()

        body: Dict[str, Any] = {
            "advertiser_id": self.advertiser_id,
            "page": page,
            "page_size": page_size,
            "fields": [
                "ad_id", "ad_name", "adgroup_id", "campaign_id",
                "ad_type", "operation_status", "call_to_action",
                "create_time", "modify_time",
            ],
        }

        filtering = {}
        if campaign_ids:
            filtering["campaign_ids"] = campaign_ids
        if ad_group_ids:
            filtering["adgroup_ids"] = ad_group_ids
        if ad_ids:
            filtering["ad_ids"] = ad_ids
        if filtering:
            body["filtering"] = filtering

        return self._post("ad/get/", body=body)

    # =========================================
    # SPARK ADS AUTHORIZATION
    # =========================================

    def authorize_spark_ad_post(
        self,
        auth_code: str,
    ) -> Dict[str, Any]:
        """
        Authorize an existing organic TikTok post as a Spark Ad.

        auth_code: generated by the post owner in TikTok Creator Studio or
                   TikTok app → Settings → Creator Tools → Ad Authorization.
                   Valid for 30 days.

        Returns a post_id (tiktok_item_id) usable in create_spark_ad().
        """
        self._require_account()
        return self._post("tt_video/authorize/", body={
            "advertiser_id": self.advertiser_id,
            "auth_code": auth_code,
        })

    def get_spark_ad_posts(self, post_ids: List[str] = None) -> Dict[str, Any]:
        """List authorized Spark Ad posts for this advertiser."""
        self._require_account()
        body: Dict[str, Any] = {"advertiser_id": self.advertiser_id}
        if post_ids:
            body["item_ids"] = post_ids
        return self._post("tt_video/get/", body=body)

    # =========================================
    # VIDEO UPLOAD
    # =========================================

    def upload_video_by_url(
        self,
        video_url: str,
        video_name: str = None,
    ) -> Dict[str, Any]:
        """
        Upload a video to TikTok ad library by URL.
        Returns video_id usable in create_video_ad().
        """
        self._require_account()
        body: Dict[str, Any] = {
            "advertiser_id": self.advertiser_id,
            "video_url": video_url,
        }
        if video_name:
            body["video_name"] = video_name
        return self._post("file/video/ad/upload/", body=body)

    # =========================================
    # ANALYTICS / REPORTING
    # =========================================

    def get_report(
        self,
        report_type: str = "BASIC",
        dimensions: List[str] = None,
        metrics: List[str] = None,
        start_date: str = None,
        end_date: str = None,
        filters: List[Dict] = None,
        data_level: str = "AUCTION_AD",
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """
        Get campaign performance report.

        report_type: BASIC | AUDIENCE | PLAYABLE_MATERIAL | CATALOG

        data_level:
            AUCTION_ADVERTISER — advertiser-level
            AUCTION_CAMPAIGN   — campaign-level
            AUCTION_ADGROUP    — ad group-level
            AUCTION_AD         — ad-level

        dimensions: ["ad_id", "stat_time_day"] for ad-level daily breakdown
                    ["campaign_id"] for campaign-level totals

        Common metrics:
            spend, impressions, clicks, ctr, cpc, cpm,
            video_play_actions, video_watched_2s, video_watched_6s,
            video_views_p25, video_views_p50, video_views_p75, video_views_p100,
            reach, frequency, likes, comments, shares, follows,
            profile_visits, profile_visits_rate,
            conversion, cost_per_conversion, conversion_rate

        date format: "2025-01-01"
        """
        self._require_account()

        now = datetime.now(timezone.utc)
        if not start_date:
            start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = now.strftime("%Y-%m-%d")

        if not dimensions:
            dimensions = ["ad_id"]

        if not metrics:
            metrics = [
                "spend", "impressions", "clicks", "ctr", "cpc", "cpm",
                "video_play_actions", "video_watched_6s",
                "video_views_p100", "reach", "likes", "comments", "shares",
                "follows", "profile_visits",
            ]

        body: Dict[str, Any] = {
            "advertiser_id": self.advertiser_id,
            "report_type": report_type,
            "data_level": data_level,
            "dimensions": dimensions,
            "metrics": metrics,
            "start_date": start_date,
            "end_date": end_date,
            "page": page,
            "page_size": page_size,
        }

        if filters:
            body["filtering"] = filters

        return self._post("report/integrated/get/", body=body)

    def get_campaign_stats(
        self,
        campaign_id: str,
        start_date: str = None,
        end_date: str = None,
    ) -> Dict[str, Any]:
        """Convenience wrapper: stats for a single campaign."""
        return self.get_report(
            data_level="AUCTION_CAMPAIGN",
            dimensions=["campaign_id"],
            filters=[{"field_name": "campaign_id", "filter_type": "IN", "filter_value": f'["{campaign_id}"]'}],
            start_date=start_date,
            end_date=end_date,
        )

    def get_ad_group_stats(
        self,
        ad_group_id: str,
        start_date: str = None,
        end_date: str = None,
    ) -> Dict[str, Any]:
        """Convenience wrapper: stats for a single ad group."""
        return self.get_report(
            data_level="AUCTION_ADGROUP",
            dimensions=["adgroup_id"],
            filters=[{"field_name": "adgroup_id", "filter_type": "IN", "filter_value": f'["{ad_group_id}"]'}],
            start_date=start_date,
            end_date=end_date,
        )

    # =========================================
    # TARGETING DISCOVERY
    # =========================================

    def get_interest_categories(
        self,
        version: int = 2,
        placements: List[str] = None,
        language: str = "en",
    ) -> Dict[str, Any]:
        """
        Get all available interest categories for targeting.
        Returns a nested category tree with ids usable in build_targeting().
        """
        self._require_account()
        return self._get("tools/interest_category/", params={
            "advertiser_id": self.advertiser_id,
            "version": version,
            "placements": json.dumps(placements or ["PLACEMENT_TIKTOK"]),
            "special_industries": json.dumps([]),
            "language": language,
        })

    def get_interest_keywords(
        self,
        keyword: str,
        language: str = "en",
    ) -> Dict[str, Any]:
        """
        Search interest keywords for keyword-based targeting.
        Returns keyword IDs and reach estimates.
        """
        self._require_account()
        return self._post("tools/interest_keyword/recommend/", body={
            "advertiser_id": self.advertiser_id,
            "keywords": [keyword],
            "language": language,
        })

    def get_geo_locations(
        self,
        level: str = "COUNTRY",
        language: str = "en",
        keyword: str = None,
    ) -> Dict[str, Any]:
        """
        Get available geo targeting locations.

        level: COUNTRY | PROVINCE | CITY | DMA | DISTRICT

        Returns location IDs usable in build_targeting() locations param.
        """
        self._require_account()
        params: Dict[str, Any] = {
            "advertiser_id": self.advertiser_id,
            "placements": json.dumps(["PLACEMENT_TIKTOK"]),
            "level": level,
            "language": language,
        }
        if keyword:
            params["keyword"] = keyword
        return self._get("tools/region/", params=params)

    def get_languages(self) -> Dict[str, Any]:
        """Get all supported targeting languages."""
        self._require_account()
        return self._get("tools/language/", params={"advertiser_id": self.advertiser_id})

    def get_reach_estimate(
        self,
        campaign_id: str,
        ad_group_id: str = None,
        targeting: Dict[str, Any] = None,
        objective: str = "VIDEO_VIEWS",
        placements: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Get audience reach estimate for a targeting configuration.
        Returns an estimated audience size range.
        """
        self._require_account()
        try:
            body: Dict[str, Any] = {
                "advertiser_id": self.advertiser_id,
                "campaign_id": campaign_id,
                "objective_type": objective,
                "placements": placements or ["PLACEMENT_TIKTOK"],
            }
            if targeting:
                body.update(targeting)
            if ad_group_id:
                body["adgroup_id"] = ad_group_id

            resp = self._post("tools/reach_estimate/", body=body)
            data = resp.get("data", {})
            return {
                "success": True,
                "data": {
                    "reach_estimate": data.get("reach_estimate"),
                    "lower_bound": data.get("reach_lower"),
                    "upper_bound": data.get("reach_upper"),
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================
    # AUDIENCE MANAGEMENT
    # =========================================

    def get_custom_audiences(self, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """List custom audiences for retargeting."""
        self._require_account()
        return self._post("dmp/custom_audience/list/", body={
            "advertiser_id": self.advertiser_id,
            "page": page,
            "page_size": page_size,
        })

    # =========================================
    # TARGETING BUILDER
    # =========================================

    def build_targeting(
        self,
        locations: List[str] = None,           # geo location IDs from get_geo_locations()
        languages: List[str] = None,            # language IDs from get_languages()
        gender: str = None,                     # "GENDER_MALE" | "GENDER_FEMALE" | None (all)
        age_groups: List[str] = None,           # ["AGE_18_24", "AGE_25_34", ...]
        interest_category_ids: List[str] = None,
        interest_keyword_ids: List[str] = None,
        custom_audience_ids: List[str] = None,
        excluded_audience_ids: List[str] = None,
        device_type: List[str] = None,          # ["ANDROID", "IOS"]
        device_price_ranges: List[Dict] = None, # [{"min": 0, "max": 300}]
        network_types: List[str] = None,        # ["WIFI", "4G", "3G"]
        os_versions: List[str] = None,
        household_income: List[str] = None,     # ["TOP_6_PERCENT", ...]
        spending_power: str = None,             # "HIGH" | "MEDIUM" | "LOW"
    ) -> Dict[str, Any]:
        """
        Build a targeting dict for create_ad_group().

        TikTok targeting is passed as flat fields on the ad group body
        (not nested like Facebook). This returns a dict you can spread
        directly into the create_ad_group() body via body.update(targeting).

        age_groups:
            AGE_13_17, AGE_18_24, AGE_25_34, AGE_35_44,
            AGE_45_54, AGE_55_100 (or AGE_55_PLUS)

        device_type: ["ANDROID"] | ["IOS"] | ["ANDROID", "IOS"] (both)

        network_types: ["WIFI"] | ["4G"] | ["3G"] | any combination

        household_income:
            TOP_6_PERCENT, TOP_11_PERCENT, TOP_25_PERCENT (US only)
        """
        targeting: Dict[str, Any] = {}

        # Locations — required; default to US
        targeting["location_ids"] = locations or ["US"]

        if languages:
            targeting["languages"] = languages

        if gender:
            targeting["gender"] = gender

        if age_groups:
            targeting["age_groups"] = age_groups

        if interest_category_ids:
            targeting["interest_category_ids"] = interest_category_ids

        if interest_keyword_ids:
            targeting["interest_keyword_ids"] = interest_keyword_ids

        if custom_audience_ids:
            targeting["audience_ids"] = custom_audience_ids

        if excluded_audience_ids:
            targeting["excluded_audience_ids"] = excluded_audience_ids

        if device_type:
            targeting["device_type"] = device_type

        if device_price_ranges:
            targeting["device_price_ranges"] = device_price_ranges

        if network_types:
            targeting["network_types"] = network_types

        if os_versions:
            targeting["os_versions"] = os_versions

        if household_income:
            targeting["household_income"] = household_income

        if spending_power:
            targeting["spending_power"] = spending_power

        return targeting

    # =========================================
    # CLEANUP HELPER
    # =========================================

    def _cleanup_campaign(self, campaign_id: str):
        """Delete a campaign on boost failure. Best-effort."""
        try:
            self.update_campaign_status([campaign_id], "DELETE")
            Log.info(f"[TikTokAdsService][_cleanup] deleted campaign {campaign_id}")
        except Exception as e:
            Log.error(f"[TikTokAdsService][_cleanup] failed to delete campaign {campaign_id}: {e}")

    # =========================================
    # BOOST VIDEO — SPARK ADS FLOW
    # =========================================

    def boost_video(
        self,
        spark_ad_auth_code: str,
        daily_budget: float,
        duration_days: int = 7,
        objective: str = "VIDEO_VIEWS",
        optimization_goal: str = "VIDEO_VIEW",
        placements: List[str] = None,
        bid_type: str = "BID_TYPE_NO_BID",
        bid: float = None,
        billing_event: str = "CPM",
        call_to_action: str = "WATCH_NOW",
        landing_page_url: str = None,
        targeting: Dict[str, Any] = None,
        campaign_name: str = None,
        auto_activate: bool = False,
    ) -> Dict[str, Any]:
        """
        Boost an existing organic TikTok video using Spark Ads.

        Creates: Campaign → Ad Group (with targeting + budget) → Ad (Spark)

        Args:
            spark_ad_auth_code : Authorization code from TikTok Creator Studio.
                                 The post owner generates this via:
                                 TikTok app → Me → Settings → Creator Tools → Ad Authorization
                                 Valid for 30 days.
            daily_budget       : Daily budget in USD (minimum $20.00)
            duration_days      : How many days to run. Sets end time on ad group.
            objective          : VIDEO_VIEWS (default) | REACH | ENGAGEMENT | TRAFFIC
            optimization_goal  : VIDEO_VIEW | CLICK | REACH | SHOW
            placements         : ["PLACEMENT_TIKTOK"] by default
            bid_type           : BID_TYPE_NO_BID (auto) | BID_TYPE_CUSTOM_BID
            bid                : Required for BID_TYPE_CUSTOM_BID
            billing_event      : CPM | CPV | CPC
            call_to_action     : WATCH_NOW | LEARN_MORE | SHOP_NOW | etc.
            landing_page_url   : Required for TRAFFIC objective
            targeting          : From build_targeting(). None = US default.
            campaign_name      : Override. Auto-generated if None.
            auto_activate      : If True, creates as ENABLE immediately. Default: DISABLE.

        Returns:
            {
                "success": bool,
                "spark_post_id": str | None,
                "campaign_id": str | None,
                "ad_group_id": str | None,
                "ad_id": str | None,
                "errors": [{"step": str, "error": str}]
            }
        """
        self._require_account()
        log_tag = "[TikTokAdsService][boost_video]"

        if not targeting:
            targeting = self.build_targeting()  # defaults to US

        initial_status_campaign = "CAMPAIGN_STATUS_ENABLE" if auto_activate else "CAMPAIGN_STATUS_DISABLE"
        initial_status_adgroup = "AD_STATUS_ENABLE" if auto_activate else "AD_STATUS_DISABLE"

        now = datetime.now(timezone.utc)
        end_time = now + timedelta(days=duration_days)
        end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")

        campaign_name = campaign_name or f"Boost Video {now.strftime('%Y%m%d%H%M%S')}"

        result: Dict[str, Any] = {
            "success": False,
            "spark_post_id": None,
            "campaign_id": None,
            "ad_group_id": None,
            "ad_id": None,
            "errors": [],
        }

        try:
            # --------------------------------------------------
            # 1. Authorize Spark Ad post
            # --------------------------------------------------
            Log.info(f"{log_tag} Authorizing Spark Ad post...")
            spark_resp = self.authorize_spark_ad_post(spark_ad_auth_code)
            spark_post_id = spark_resp.get("data", {}).get("item_id") or spark_resp.get("data", {}).get("tiktok_item_id")

            if not spark_post_id:
                result["errors"].append({"step": "spark_authorize", "error": "No post ID returned from Spark Ad authorization"})
                return result

            result["spark_post_id"] = spark_post_id
            Log.info(f"{log_tag} Spark post authorized: {spark_post_id}")

            # --------------------------------------------------
            # 2. Create Campaign
            # --------------------------------------------------
            Log.info(f"{log_tag} Creating campaign...")
            campaign_resp = self.create_campaign(
                name=campaign_name,
                objective=objective,
                budget_mode="BUDGET_MODE_INFINITE",
                status=initial_status_campaign,
            )

            campaign_id = str(campaign_resp.get("data", {}).get("campaign_id", ""))
            if not campaign_id:
                result["errors"].append({"step": "campaign", "error": "No campaign ID returned"})
                return result

            result["campaign_id"] = campaign_id
            Log.info(f"{log_tag} Campaign created: {campaign_id}")

            # --------------------------------------------------
            # 3. Create Ad Group
            # --------------------------------------------------
            Log.info(f"{log_tag} Creating ad group...")
            ad_group_resp = self.create_ad_group(
                campaign_id=campaign_id,
                name=f"{campaign_name} Ad Group",
                placements=placements or ["PLACEMENT_TIKTOK"],
                budget_mode="BUDGET_MODE_DAY",
                budget=daily_budget,
                schedule_type="SCHEDULE_FROM_NOW",
                end_time=end_time_str,
                optimization_goal=optimization_goal,
                bid_type=bid_type,
                bid=bid,
                billing_event=billing_event,
                targeting=targeting,
                status=initial_status_adgroup,
            )

            ad_group_id = str(ad_group_resp.get("data", {}).get("adgroup_id", ""))
            if not ad_group_id:
                result["errors"].append({"step": "ad_group", "error": "No ad group ID returned"})
                self._cleanup_campaign(campaign_id)
                return result

            result["ad_group_id"] = ad_group_id
            Log.info(f"{log_tag} Ad group created: {ad_group_id}")

            # --------------------------------------------------
            # 4. Create Spark Ad
            # --------------------------------------------------
            Log.info(f"{log_tag} Creating Spark Ad...")
            ad_resp = self.create_spark_ad(
                ad_group_id=ad_group_id,
                name=f"{campaign_name} Ad",
                spark_ad_post_id=spark_post_id,
                call_to_action=call_to_action,
                status=initial_status_adgroup,
            )

            ad_ids = ad_resp.get("data", {}).get("ad_ids") or []
            ad_id = str(ad_ids[0]) if ad_ids else ""

            if not ad_id:
                result["errors"].append({"step": "ad", "error": "No ad ID returned"})
                self._cleanup_campaign(campaign_id)
                return result

            result["ad_id"] = ad_id
            Log.info(f"{log_tag} Spark Ad created: {ad_id}")

            result["success"] = True
            Log.info(f"{log_tag} Video boosted successfully!")
            return result

        except TikTokAdsError as e:
            Log.error(f"{log_tag} TikTokAdsError: {e}")
            result["errors"].append({"step": "unknown", "error": str(e)})
            return result

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            result["errors"].append({"step": "unknown", "error": str(e)})
            return result
