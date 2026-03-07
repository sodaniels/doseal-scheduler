# app/services/social/ads/youtube_ads_service.py

"""
YouTube Ads Service — Google Ads API (Demand Gen Campaigns)

IMPORTANT: YouTube Video campaigns (standard) are NOT supported by the
Google Ads API for creation or mutation. This service uses Demand Gen
campaigns, which are the official programmatic alternative and run video
ads on YouTube (including Shorts), Discover, and Gmail.

Reference: https://developers.google.com/google-ads/api/docs/demand-gen/overview

API version: v19
Base URL: https://googleads.googleapis.com/v19/

Auth:
  - OAuth 2.0 Bearer token (from Google account)
  - developer-token header (from Google Ads API Center)
  - login-customer-id header (manager account ID, if applicable)

Hierarchy:
  Customer (customer_id)
    └── CampaignBudget
    └── Campaign (DEMAND_GEN, AdvertisingChannelType)
          └── AdGroup
                └── AdGroupCriterion  (location / language targeting)
                └── Asset             (YouTube video, logo image)
                └── AdGroupAd         (DemandGenVideoResponsiveAd)

Budget: Micro-currency units. 1 USD = 1,000,000 micros.

Boost flow (boost_video):
  1. create_campaign_budget()
  2. create_campaign()         — DEMAND_GEN, maximize_conversions or target_cpa
  3. create_ad_group()
  4. add_location_criteria()   — ad-group level
  5. add_language_criteria()   — ad-group level
  6. create_youtube_video_asset()
  7. create_image_asset()      — logo (optional but recommended)
  8. create_demand_gen_video_ad()
  9. _cleanup_campaign() on any failure

Required env vars:
  GOOGLE_ADS_DEVELOPER_TOKEN   — from ads.google.com/aw/apicenter
  YOUTUBE_CLIENT_ID            — same OAuth2 client used for YouTube posting
  YOUTUBE_CLIENT_SECRET        — same OAuth2 client secret used for YouTube posting

Tokens sourced from:
  SocialAccount(platform="youtube", destination_id=channel_id)
    access_token_plain  → OAuth2 access token (short-lived, ~1h)
    refresh_token_plain → OAuth2 refresh token (long-lived, persisted from connect-channel flow)

Tokens stored per AdAccount(platform="youtube"):
  access_token_plain  → OAuth2 access token
  refresh_token_plain → OAuth2 refresh token
  meta                → {manager_customer_id, is_manager, currency, timezone}
"""

import os
import time
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from ....utils.logger import Log


API_VERSION = "v19"
BASE_URL = f"https://googleads.googleapis.com/{API_VERSION}"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class YouTubeAdsError(Exception):
    """Raised when the Google Ads API returns a non-200 response."""

    def __init__(self, message: str, errors: list = None, status_code: int = None):
        super().__init__(message)
        self.errors = errors or []
        self.status_code = status_code

    def __str__(self):
        if self.errors:
            detail = self.errors[0].get("message", "") if self.errors else ""
            return f"{super().__str__()} — {detail}" if detail else super().__str__()
        return super().__str__()


def _require_google_env():
    """Return (developer_token, client_id, client_secret) from env or raise."""
    dev_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN", "").strip()
    client_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
    if not dev_token:
        raise YouTubeAdsError("GOOGLE_ADS_DEVELOPER_TOKEN env var not set")
    if not client_id or not client_secret:
        raise YouTubeAdsError("YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET env vars not set")
    return dev_token, client_id, client_secret


class YouTubeAdsService:
    """
    Service for managing YouTube Demand Gen campaigns via the Google Ads REST API.

    Usage:
        service = YouTubeAdsService(
            access_token="ya29...",
            refresh_token="1//0g...",
            customer_id="1234567890",          # 10-digit, no hyphens
            manager_customer_id="9876543210",  # optional MCC account
        )
    """

    def __init__(
        self,
        access_token: str,
        refresh_token: str = None,
        customer_id: str = None,
        manager_customer_id: str = None,
    ):
        # Strip hyphens — Google Ads customer IDs are 10 digits, sometimes displayed as xxx-xxx-xxxx
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.customer_id = str(customer_id).replace("-", "") if customer_id else None
        self.manager_customer_id = (
            str(manager_customer_id).replace("-", "") if manager_customer_id else None
        )
        self._token_refreshed_at = None

    def _require_customer(self):
        if not self.customer_id:
            raise YouTubeAdsError(
                "customer_id is required for this operation. "
                "Initialize the service with a customer_id."
            )

    # =========================================
    # HTTP LAYER
    # =========================================

    def _headers(self) -> Dict[str, str]:
        dev_token, _, _ = _require_google_env()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
            "developer-token": dev_token,
        }
        # login-customer-id is required when authenticating through a manager account
        if self.manager_customer_id and self.manager_customer_id != self.customer_id:
            headers["login-customer-id"] = self.manager_customer_id
        return headers

    def _refresh_access_token(self) -> str:
        """
        Exchange refresh_token for a new access_token.
        Called automatically when a 401 is received.
        Returns the new access_token.
        """
        if not self.refresh_token:
            raise YouTubeAdsError("Cannot refresh token: no refresh_token available")

        _, client_id, client_secret = _require_google_env()

        resp = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }, timeout=15)

        if resp.status_code != 200:
            raise YouTubeAdsError(
                "Failed to refresh Google OAuth token",
                status_code=resp.status_code,
            )

        data = resp.json()
        self.access_token = data["access_token"]
        self._token_refreshed_at = time.time()
        return self.access_token

    def _request(
        self,
        method: str,
        url: str,
        body: Dict = None,
        params: Dict = None,
        retry_on_401: bool = True,
    ) -> Dict[str, Any]:
        response = requests.request(
            method,
            url,
            headers=self._headers(),
            json=body,
            params=params,
            timeout=30,
        )

        if response.status_code == 401 and retry_on_401 and self.refresh_token:
            self._refresh_access_token()
            return self._request(method, url, body=body, params=params, retry_on_401=False)

        if not response.ok:
            try:
                err_body = response.json()
                errors = err_body.get("error", {}).get("details", [])
                message = err_body.get("error", {}).get("message", response.text)
            except Exception:
                errors = []
                message = response.text

            raise YouTubeAdsError(message, errors=errors, status_code=response.status_code)

        if response.status_code == 204:
            return {}

        return response.json()

    def _post(self, path: str, body: Dict) -> Dict[str, Any]:
        url = f"{BASE_URL}/customers/{self.customer_id}/{path}"
        return self._request("POST", url, body=body)

    def _get(self, path: str, params: Dict = None) -> Dict[str, Any]:
        url = f"{BASE_URL}/customers/{self.customer_id}/{path}"
        return self._request("GET", url, params=params)

    def _search(self, query: str, page_token: str = None) -> Dict[str, Any]:
        """Execute a GAQL query via googleAds:search."""
        body: Dict[str, Any] = {"query": query}
        if page_token:
            body["pageToken"] = page_token
        return self._post("googleAds:search", body)

    # =========================================
    # TOKEN / ACCOUNT HELPERS
    # =========================================

    def _usd_to_micros(self, usd: float) -> int:
        """Convert USD to micro-currency units (1 USD = 1,000,000 micros)."""
        return int(round(usd * 1_000_000))

    def _campaign_resource(self, campaign_id: str) -> str:
        return f"customers/{self.customer_id}/campaigns/{campaign_id}"

    def _budget_resource(self, budget_id: str) -> str:
        return f"customers/{self.customer_id}/campaignBudgets/{budget_id}"

    def _ad_group_resource(self, ad_group_id: str) -> str:
        return f"customers/{self.customer_id}/adGroups/{ad_group_id}"

    def _asset_resource(self, asset_id: str) -> str:
        return f"customers/{self.customer_id}/assets/{asset_id}"

    def _extract_id(self, resource_name: str) -> str:
        """Extract the numeric ID from a resource name like 'customers/123/campaigns/456'."""
        return resource_name.split("/")[-1]

    # =========================================
    # ACCOUNT DISCOVERY
    # =========================================

    def list_accessible_customers(self) -> Dict[str, Any]:
        """
        List all Google Ads customer accounts accessible with the current token.
        Does NOT require customer_id — call this before connecting an account.

        Returns a list of resource names: ["customers/1234567890", ...]
        """
        url = f"{BASE_URL.rsplit('/', 1)[0]}/customers:listAccessibleCustomers"
        # No customer_id in URL for this endpoint
        dev_token, _, _ = _require_google_env()
        response = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "developer-token": dev_token,
            },
            timeout=30,
        )

        if response.status_code == 401 and self.refresh_token:
            self._refresh_access_token()
            return self.list_accessible_customers()

        if not response.ok:
            raise YouTubeAdsError(
                "Failed to list accessible customers",
                status_code=response.status_code,
            )

        data = response.json()
        resource_names = data.get("resourceNames", [])

        customers = []
        for rn in resource_names:
            cid = self._extract_id(rn)
            customers.append({"customer_id": cid, "resource_name": rn})

        return {"success": True, "data": customers}

    def get_customer_info(self) -> Dict[str, Any]:
        """
        Get details for the current customer_id: name, currency, timezone, status.
        """
        self._require_customer()
        query = """
            SELECT
                customer.id,
                customer.descriptive_name,
                customer.currency_code,
                customer.time_zone,
                customer.status,
                customer.manager
            FROM customer
            LIMIT 1
        """
        result = self._search(query)
        rows = result.get("results", [])
        if not rows:
            return {"success": True, "data": {}}

        c = rows[0].get("customer", {})
        return {
            "success": True,
            "data": {
                "customer_id": str(c.get("id", "")),
                "name": c.get("descriptiveName"),
                "currency": c.get("currencyCode"),
                "timezone": c.get("timeZone"),
                "status": c.get("status"),
                "is_manager": c.get("manager", False),
            },
        }

    # =========================================
    # CAMPAIGN BUDGET
    # =========================================

    def create_campaign_budget(
        self,
        name: str,
        amount_usd: float,
        delivery_method: str = "STANDARD",
    ) -> Dict[str, Any]:
        """
        Create a non-shared campaign budget.

        Demand Gen campaigns require a non-shared budget.
        Budget is in USD, converted internally to micros.

        delivery_method:
            STANDARD   — spreads budget evenly through the day
            ACCELERATED — spends budget as fast as possible (deprecated for most types)

        Returns the budget resource_name and ID.
        """
        self._require_customer()

        body = {
            "operations": [{
                "create": {
                    "name": name,
                    "amountMicros": str(self._usd_to_micros(amount_usd)),
                    "deliveryMethod": delivery_method,
                    "explicitlyShared": False,
                    "type": "STANDARD",
                },
            }],
        }

        result = self._post("campaignBudgets:mutate", body)
        resource_name = result.get("results", [{}])[0].get("resourceName", "")
        return {
            "success": True,
            "resource_name": resource_name,
            "budget_id": self._extract_id(resource_name),
        }

    # =========================================
    # CAMPAIGNS
    # =========================================

    def create_campaign(
        self,
        name: str,
        budget_resource_name: str,
        bidding_strategy: str = "maximizeConversions",
        target_cpa_usd: float = None,
        target_roas: float = None,
        start_date: str = None,
        end_date: str = None,
        status: str = "PAUSED",
    ) -> Dict[str, Any]:
        """
        Create a Demand Gen campaign.

        advertisingChannelType is always DEMAND_GEN.
        No advertisingChannelSubType should be set.

        bidding_strategy options:
            "maximizeConversions"   — auto bid for max conversions (default)
            "maximizeConversionValue" — auto bid for max conversion value
            "targetCpa"             — target CPA, requires target_cpa_usd
            "targetRoas"            — target ROAS, requires target_roas
            "maximizeClicks"        — max clicks

        start_date / end_date: "YYYY-MM-DD" format
        status: "PAUSED" | "ENABLED"
        """
        self._require_customer()

        campaign: Dict[str, Any] = {
            "name": name,
            "advertisingChannelType": "DEMAND_GEN",
            "campaignBudget": budget_resource_name,
            "status": status,
        }

        # Bidding strategy
        if bidding_strategy == "targetCpa" and target_cpa_usd:
            campaign["targetCpa"] = {
                "targetCpaMicros": str(self._usd_to_micros(target_cpa_usd)),
            }
        elif bidding_strategy == "targetRoas" and target_roas:
            campaign["targetRoas"] = {
                "targetRoas": target_roas,
            }
        elif bidding_strategy == "maximizeConversionValue":
            campaign["maximizeConversionValue"] = {}
        elif bidding_strategy == "maximizeClicks":
            campaign["maximizeClicks"] = {}
        else:
            # Default: maximize conversions
            campaign["maximizeConversions"] = {}

        if start_date:
            campaign["startDate"] = start_date.replace("-", "")  # YYYYMMDD format
        if end_date:
            campaign["endDate"] = end_date.replace("-", "")

        result = self._post("campaigns:mutate", {"operations": [{"create": campaign}]})
        resource_name = result.get("results", [{}])[0].get("resourceName", "")
        return {
            "success": True,
            "resource_name": resource_name,
            "campaign_id": self._extract_id(resource_name),
        }

    def update_campaign_status(self, campaign_id: str, status: str) -> Dict[str, Any]:
        """
        Update campaign status.
        status: "ENABLED" | "PAUSED" | "REMOVED"
        """
        self._require_customer()
        resource_name = self._campaign_resource(campaign_id)

        result = self._post("campaigns:mutate", {
            "operations": [{
                "update": {
                    "resourceName": resource_name,
                    "status": status,
                },
                "updateMask": "status",
            }],
        })
        return {"success": True, "data": result}

    def get_campaigns(
        self,
        status_filter: str = None,
        page_size: int = 20,
        page_token: str = None,
    ) -> Dict[str, Any]:
        """
        List Demand Gen campaigns for this customer.
        status_filter: "ENABLED" | "PAUSED" | "REMOVED" | None (all active)
        """
        self._require_customer()

        where_clauses = ["campaign.advertising_channel_type = 'DEMAND_GEN'"]
        if status_filter:
            where_clauses.append(f"campaign.status = '{status_filter}'")
        else:
            where_clauses.append("campaign.status != 'REMOVED'")

        where = " AND ".join(where_clauses)

        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                campaign.advertising_channel_type,
                campaign.bidding_strategy_type,
                campaign.start_date,
                campaign.end_date,
                campaign_budget.amount_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.cost_micros,
                metrics.conversions
            FROM campaign
            WHERE {where}
            ORDER BY campaign.id DESC
            LIMIT {page_size}
        """

        result = self._search(query, page_token=page_token)
        rows = result.get("results", [])

        campaigns = []
        for row in rows:
            c = row.get("campaign", {})
            b = row.get("campaignBudget", {})
            m = row.get("metrics", {})
            campaigns.append({
                "campaign_id": str(c.get("id", "")),
                "name": c.get("name"),
                "status": c.get("status"),
                "bidding_strategy_type": c.get("biddingStrategyType"),
                "start_date": c.get("startDate"),
                "end_date": c.get("endDate"),
                "budget_micros": b.get("amountMicros"),
                "budget_usd": int(b.get("amountMicros", 0)) / 1_000_000,
                "metrics": {
                    "impressions": int(m.get("impressions", 0)),
                    "clicks": int(m.get("clicks", 0)),
                    "cost_usd": int(m.get("costMicros", 0)) / 1_000_000,
                    "conversions": float(m.get("conversions", 0)),
                },
            })

        return {
            "success": True,
            "data": campaigns,
            "next_page_token": result.get("nextPageToken"),
        }

    # =========================================
    # AD GROUPS
    # =========================================

    def create_ad_group(
        self,
        campaign_resource_name: str,
        name: str,
        status: str = "ENABLED",
    ) -> Dict[str, Any]:
        """
        Create an ad group for a Demand Gen campaign.

        Note: Do NOT set adGroupType — Demand Gen ad groups have no type field.
        Targeting (location, language) is set at the ad group level via criteria.
        """
        self._require_customer()

        result = self._post("adGroups:mutate", {
            "operations": [{
                "create": {
                    "name": name,
                    "campaign": campaign_resource_name,
                    "status": status,
                },
            }],
        })
        resource_name = result.get("results", [{}])[0].get("resourceName", "")
        return {
            "success": True,
            "resource_name": resource_name,
            "ad_group_id": self._extract_id(resource_name),
        }

    # =========================================
    # TARGETING (AD GROUP LEVEL)
    # =========================================

    def add_location_criteria(
        self,
        ad_group_resource_name: str,
        geo_target_constant_ids: List[str],
        negative: bool = False,
    ) -> Dict[str, Any]:
        """
        Add location targeting to an ad group.

        geo_target_constant_ids: list of Google geo target constant IDs.
            Common examples:
                "2826"  → United Kingdom
                "2840"  → United States
                "2288"  → Ghana
                "2566"  → Spain
            Use get_geo_targets() to search by name.

        negative: True to exclude the locations.
        """
        self._require_customer()

        operations = []
        for geo_id in geo_target_constant_ids:
            criterion: Dict[str, Any] = {
                "adGroup": ad_group_resource_name,
                "status": "ENABLED",
                "location": {
                    "geoTargetConstant": f"geoTargetConstants/{geo_id}",
                },
            }
            if negative:
                criterion["negative"] = True
            operations.append({"create": criterion})

        result = self._post("adGroupCriteria:mutate", {"operations": operations})
        return {"success": True, "data": result}

    def add_language_criteria(
        self,
        ad_group_resource_name: str,
        language_constant_ids: List[str],
    ) -> Dict[str, Any]:
        """
        Add language targeting to an ad group.

        language_constant_ids: list of language constant IDs.
            Common examples:
                "1000" → English
                "1003" → French
                "1001" → German
                "1005" → Spanish
                "1023" → Twi
            Use get_language_constants() to search.
        """
        self._require_customer()

        operations = [
            {
                "create": {
                    "adGroup": ad_group_resource_name,
                    "status": "ENABLED",
                    "language": {
                        "languageConstant": f"languageConstants/{lang_id}",
                    },
                },
            }
            for lang_id in language_constant_ids
        ]

        result = self._post("adGroupCriteria:mutate", {"operations": operations})
        return {"success": True, "data": result}

    # =========================================
    # ASSETS
    # =========================================

    def create_youtube_video_asset(
        self,
        youtube_video_id: str,
        name: str = None,
    ) -> Dict[str, Any]:
        """
        Create a YouTube video asset from an existing YouTube video.

        youtube_video_id: the 11-character video ID from the YouTube URL.
            e.g. for https://youtu.be/dQw4w9WgXcQ → "dQw4w9WgXcQ"

        Returns asset resource_name and asset_id usable in create_demand_gen_video_ad().
        """
        self._require_customer()

        asset: Dict[str, Any] = {
            "youtubeVideoAsset": {
                "youtubeVideoId": youtube_video_id,
            },
        }
        if name:
            asset["name"] = name

        result = self._post("assets:mutate", {
            "operations": [{"create": asset}],
        })
        resource_name = result.get("results", [{}])[0].get("resourceName", "")
        return {
            "success": True,
            "resource_name": resource_name,
            "asset_id": self._extract_id(resource_name),
        }

    def create_image_asset_from_url(
        self,
        image_url: str,
        name: str = None,
    ) -> Dict[str, Any]:
        """
        Create an image asset from a public URL (for logo).

        The image is downloaded by this service and uploaded as base64.
        Minimum logo size: 128x128px. Recommended: 1200x1200px square.

        Returns asset resource_name and asset_id.
        """
        self._require_customer()

        # Download image
        img_resp = requests.get(image_url, timeout=15)
        if not img_resp.ok:
            raise YouTubeAdsError(f"Failed to download image from URL: {image_url}")

        import base64
        image_data_b64 = base64.b64encode(img_resp.content).decode("utf-8")

        asset: Dict[str, Any] = {
            "imageAsset": {
                "data": image_data_b64,
            },
        }
        if name:
            asset["name"] = name

        result = self._post("assets:mutate", {
            "operations": [{"create": asset}],
        })
        resource_name = result.get("results", [{}])[0].get("resourceName", "")
        return {
            "success": True,
            "resource_name": resource_name,
            "asset_id": self._extract_id(resource_name),
        }

    # =========================================
    # ADS
    # =========================================

    def create_demand_gen_video_ad(
        self,
        ad_group_resource_name: str,
        video_asset_resource_name: str,
        headline: str,
        description: str,
        business_name: str,
        final_url: str,
        long_headline: str = None,
        logo_asset_resource_name: str = None,
        call_to_action_asset_resource_name: str = None,
        breadcrumb1: str = None,
        breadcrumb2: str = None,
        status: str = "ENABLED",
    ) -> Dict[str, Any]:
        """
        Create a DemandGenVideoResponsiveAd and attach it to an ad group.

        This is the primary ad format for YouTube Demand Gen campaigns.
        The ad uses an existing YouTube video via its asset resource_name.

        headline:           short headline (max 30 chars)
        long_headline:      longer variant (max 90 chars)
        description:        ad description (max 90 chars)
        business_name:      your brand name (max 25 chars)
        final_url:          landing page URL
        breadcrumb1/2:      short URL display breadcrumbs (e.g. "youtube.com" / "campaign")
        """
        self._require_customer()

        demand_gen_ad: Dict[str, Any] = {
            "headlines": [{"text": headline}],
            "descriptions": [{"text": description}],
            "longHeadlines": [{"text": long_headline or headline}],
            "businessName": {"text": business_name},
            "videos": [{"asset": video_asset_resource_name}],
        }

        if logo_asset_resource_name:
            demand_gen_ad["logoImages"] = [{"asset": logo_asset_resource_name}]

        if call_to_action_asset_resource_name:
            demand_gen_ad["callToActions"] = [{"asset": call_to_action_asset_resource_name}]

        if breadcrumb1:
            demand_gen_ad["breadcrumb1"] = breadcrumb1
        if breadcrumb2:
            demand_gen_ad["breadcrumb2"] = breadcrumb2

        body = {
            "operations": [{
                "create": {
                    "adGroup": ad_group_resource_name,
                    "status": status,
                    "ad": {
                        "finalUrls": [final_url],
                        "demandGenVideoResponsiveAd": demand_gen_ad,
                    },
                },
            }],
        }

        result = self._post("adGroupAds:mutate", body)
        resource_name = result.get("results", [{}])[0].get("resourceName", "")
        return {
            "success": True,
            "resource_name": resource_name,
            "ad_group_ad_id": self._extract_id(resource_name),
        }

    # =========================================
    # CLEANUP
    # =========================================

    def _cleanup_campaign(
        self,
        campaign_id: str = None,
        budget_id: str = None,
        ad_group_id: str = None,
    ):
        """
        Best-effort cleanup of partial campaign creation on failure.
        Removes campaign, ad group, and budget (in that order).
        Silently ignores errors.
        """
        try:
            if ad_group_id:
                self._post("adGroups:mutate", {
                    "operations": [{
                        "remove": self._ad_group_resource(ad_group_id),
                    }],
                })
        except Exception:
            pass

        try:
            if campaign_id:
                self._post("campaigns:mutate", {
                    "operations": [{
                        "remove": self._campaign_resource(campaign_id),
                    }],
                })
        except Exception:
            pass

        try:
            if budget_id:
                self._post("campaignBudgets:mutate", {
                    "operations": [{
                        "remove": self._budget_resource(budget_id),
                    }],
                })
        except Exception:
            pass

    # =========================================
    # BOOST VIDEO — HIGH LEVEL
    # =========================================

    def boost_video(
        self,
        youtube_video_id: str,
        headline: str,
        description: str,
        business_name: str,
        final_url: str,
        daily_budget_usd: float,
        duration_days: int,
        campaign_name: str = None,
        long_headline: str = None,
        logo_image_url: str = None,
        geo_target_ids: List[str] = None,
        language_ids: List[str] = None,
        bidding_strategy: str = "maximizeConversions",
        target_cpa_usd: float = None,
        breadcrumb1: str = None,
        breadcrumb2: str = None,
        auto_activate: bool = False,
    ) -> Dict[str, Any]:
        """
        Full Demand Gen campaign creation flow for boosting a YouTube video.

        Steps:
          1. Create budget  (daily_budget_usd for duration_days)
          2. Create campaign (DEMAND_GEN, PAUSED or ENABLED)
          3. Create ad group
          4. Add location criteria (default: US + UK)
          5. Add language criteria (default: English)
          6. Create YouTube video asset
          7. Create logo image asset (if logo_image_url provided)
          8. Create DemandGenVideoResponsiveAd

        Returns dict with all IDs needed to persist to AdCampaign model.
        Rolls back (removes campaign + budget) on any step failure.

        youtube_video_id:   11-char YouTube video ID (e.g. "dQw4w9WgXcQ")
        geo_target_ids:     Google geo target constant IDs (default ["2840"] = US)
        language_ids:       Language constant IDs (default ["1000"] = English)
        """
        self._require_customer()

        budget_id = None
        campaign_id = None
        ad_group_id = None

        now = datetime.now(timezone.utc)
        start_date = now.strftime("%Y-%m-%d")
        end_date = (now + timedelta(days=duration_days)).strftime("%Y-%m-%d")

        campaign_status = "ENABLED" if auto_activate else "PAUSED"
        campaign_name = campaign_name or f"Boost YT {youtube_video_id} {now.strftime('%Y%m%d')}"

        # Default targeting
        geo_ids = geo_target_ids or ["2840"]       # US
        lang_ids = language_ids or ["1000"]        # English

        try:
            # Step 1: Budget
            budget_resp = self.create_campaign_budget(
                name=f"{campaign_name} Budget",
                amount_usd=daily_budget_usd,
            )
            budget_id = budget_resp["budget_id"]
            budget_resource = budget_resp["resource_name"]

            # Step 2: Campaign
            campaign_resp = self.create_campaign(
                name=campaign_name,
                budget_resource_name=budget_resource,
                bidding_strategy=bidding_strategy,
                target_cpa_usd=target_cpa_usd,
                start_date=start_date,
                end_date=end_date,
                status=campaign_status,
            )
            campaign_id = campaign_resp["campaign_id"]
            campaign_resource = campaign_resp["resource_name"]

            # Step 3: Ad group
            ad_group_resp = self.create_ad_group(
                campaign_resource_name=campaign_resource,
                name=f"{campaign_name} AdGroup",
            )
            ad_group_id = ad_group_resp["ad_group_id"]
            ad_group_resource = ad_group_resp["resource_name"]

            # Step 4: Location targeting
            self.add_location_criteria(ad_group_resource, geo_ids)

            # Step 5: Language targeting
            self.add_language_criteria(ad_group_resource, lang_ids)

            # Step 6: YouTube video asset
            video_asset_resp = self.create_youtube_video_asset(
                youtube_video_id=youtube_video_id,
                name=f"Video {youtube_video_id}",
            )
            video_asset_resource = video_asset_resp["resource_name"]

            # Step 7: Logo image asset (optional)
            logo_asset_resource = None
            if logo_image_url:
                try:
                    logo_resp = self.create_image_asset_from_url(
                        image_url=logo_image_url,
                        name=f"{business_name} Logo",
                    )
                    logo_asset_resource = logo_resp["resource_name"]
                except Exception as e:
                    Log.warning(f"[YouTubeAdsService] Logo upload failed (continuing): {e}")

            # Step 8: Demand Gen video ad
            ad_resp = self.create_demand_gen_video_ad(
                ad_group_resource_name=ad_group_resource,
                video_asset_resource_name=video_asset_resource,
                headline=headline,
                description=description,
                business_name=business_name,
                final_url=final_url,
                long_headline=long_headline,
                logo_asset_resource_name=logo_asset_resource,
                breadcrumb1=breadcrumb1,
                breadcrumb2=breadcrumb2,
                status="ENABLED" if auto_activate else "PAUSED",
            )

            return {
                "success": True,
                "budget_id": budget_id,
                "campaign_id": campaign_id,
                "ad_group_id": ad_group_id,
                "ad_group_ad_id": ad_resp.get("ad_group_ad_id"),
                "video_asset_id": video_asset_resp.get("asset_id"),
            }

        except Exception as e:
            Log.error(f"[YouTubeAdsService.boost_video] Failed: {e}. Cleaning up...")
            self._cleanup_campaign(
                campaign_id=campaign_id,
                budget_id=budget_id,
                ad_group_id=ad_group_id,
            )
            raise

    # =========================================
    # REPORTING
    # =========================================

    def get_campaign_insights(
        self,
        campaign_id: str,
        start_date: str = None,
        end_date: str = None,
    ) -> Dict[str, Any]:
        """
        Get performance metrics for a Demand Gen campaign.

        start_date / end_date: "YYYY-MM-DD" (defaults to last 7 days)
        """
        self._require_customer()

        now = datetime.now(timezone.utc)
        if not start_date:
            start_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = now.strftime("%Y-%m-%d")

        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr,
                metrics.average_cpc,
                metrics.cost_micros,
                metrics.conversions,
                metrics.conversions_value,
                metrics.video_views,
                metrics.video_view_rate,
                metrics.video_quartile_p25_rate,
                metrics.video_quartile_p50_rate,
                metrics.video_quartile_p75_rate,
                metrics.video_quartile_p100_rate,
                metrics.engagement_rate,
                metrics.engagements
            FROM campaign
            WHERE campaign.id = {campaign_id}
              AND campaign.advertising_channel_type = 'DEMAND_GEN'
              AND segments.date BETWEEN '{start_date}' AND '{end_date}'
        """

        result = self._search(query)
        rows = result.get("results", [])

        if not rows:
            return {
                "success": True,
                "data": {
                    "campaign_id": campaign_id,
                    "period": {"start": start_date, "end": end_date},
                    "metrics": {},
                },
            }

        m = rows[0].get("metrics", {})
        return {
            "success": True,
            "data": {
                "campaign_id": campaign_id,
                "period": {"start": start_date, "end": end_date},
                "metrics": {
                    "impressions": int(m.get("impressions", 0)),
                    "clicks": int(m.get("clicks", 0)),
                    "ctr": float(m.get("ctr", 0)),
                    "cost_usd": int(m.get("costMicros", 0)) / 1_000_000,
                    "average_cpc_usd": int(m.get("averageCpc", 0)) / 1_000_000,
                    "conversions": float(m.get("conversions", 0)),
                    "conversions_value": float(m.get("conversionsValue", 0)),
                    "video_views": int(m.get("videoViews", 0)),
                    "video_view_rate": float(m.get("videoViewRate", 0)),
                    "video_watched_25pct": float(m.get("videoQuartileP25Rate", 0)),
                    "video_watched_50pct": float(m.get("videoQuartileP50Rate", 0)),
                    "video_watched_75pct": float(m.get("videoQuartileP75Rate", 0)),
                    "video_watched_100pct": float(m.get("videoQuartileP100Rate", 0)),
                    "engagements": int(m.get("engagements", 0)),
                    "engagement_rate": float(m.get("engagementRate", 0)),
                },
            },
        }

    # =========================================
    # TARGETING DISCOVERY
    # =========================================

    def get_geo_targets(self, keyword: str, locale: str = "en") -> Dict[str, Any]:
        """
        Search Google geo target constants by name.
        Returns IDs usable in add_location_criteria().

        keyword: city/country name, e.g. "United Kingdom", "London", "Ghana"
        locale:  language of returned names, e.g. "en", "fr"
        """
        # geoTargetConstants is a top-level resource, not customer-scoped
        dev_token, _, _ = _require_google_env()
        url = f"{BASE_URL}/geoTargetConstants:suggest"
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "developer-token": dev_token,
                "Content-Type": "application/json",
            },
            json={"locale": locale, "query": keyword},
            timeout=15,
        )

        if not response.ok:
            raise YouTubeAdsError(
                f"Failed to search geo targets: {response.text}",
                status_code=response.status_code,
            )

        suggestions = response.json().get("geoTargetConstantSuggestions", [])
        results = []
        for s in suggestions:
            gtc = s.get("geoTargetConstant", {})
            results.append({
                "id": self._extract_id(gtc.get("resourceName", "")),
                "name": gtc.get("name"),
                "canonical_name": gtc.get("canonicalName"),
                "country_code": gtc.get("countryCode"),
                "target_type": gtc.get("targetType"),
                "status": gtc.get("status"),
            })

        return {"success": True, "data": results}

    def get_language_constants(self, keyword: str = None) -> Dict[str, Any]:
        """
        List available language targeting constants.
        Optionally filter by name keyword (e.g. "English", "French").
        """
        self._require_customer()

        where = ""
        if keyword:
            where = f"WHERE language_constant.name LIKE '%{keyword}%'"

        query = f"""
            SELECT
                language_constant.id,
                language_constant.name,
                language_constant.code,
                language_constant.targetable
            FROM language_constant
            {where}
            ORDER BY language_constant.name
            LIMIT 50
        """

        result = self._search(query)
        rows = result.get("results", [])

        return {
            "success": True,
            "data": [
                {
                    "id": str(row.get("languageConstant", {}).get("id", "")),
                    "name": row.get("languageConstant", {}).get("name"),
                    "code": row.get("languageConstant", {}).get("code"),
                    "targetable": row.get("languageConstant", {}).get("targetable"),
                }
                for row in rows
            ],
        }

    def get_reach_forecast(
        self,
        campaign_duration_days: int,
        daily_budget_usd: float,
        geo_target_ids: List[str] = None,
        language_ids: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Get audience reach forecast for a Demand Gen targeting spec.

        Uses the ReachPlanService.GenerateReachForecast endpoint.
        Returns estimated reach, impressions, and on-target reach.

        Note: This is an approximation; actual delivery depends on auction.
        """
        self._require_customer()

        geo_ids = geo_target_ids or ["2840"]  # default US
        lang_ids = language_ids or ["1000"]   # default English

        body: Dict[str, Any] = {
            "currencyCode": "USD",
            "campaignDuration": {"durationInDays": campaign_duration_days},
            "plannedProducts": [{
                "plannableProductCode": "DEMAND_GEN_AD",
                "budgetMicros": str(self._usd_to_micros(daily_budget_usd * campaign_duration_days)),
            }],
            "targeting": {
                "plannableLocationIds": geo_ids,
                "ageRanges": ["AGE_RANGE_18_24", "AGE_RANGE_25_34", "AGE_RANGE_35_44",
                              "AGE_RANGE_45_54", "AGE_RANGE_55_64", "AGE_RANGE_65_UP"],
                "genders": [{"type": "MALE"}, {"type": "FEMALE"}],
                "languages": [{"languageConstant": f"languageConstants/{lid}"} for lid in lang_ids],
            },
        }

        try:
            url = f"{BASE_URL}/customers/{self.customer_id}:generateReachForecast"
            result = self._request("POST", url, body=body)
            forecast = result.get("onTargetAudienceMetrics", {})
            reach_curve = result.get("reachCurve", {}).get("reachForecasts", [])

            top = reach_curve[-1] if reach_curve else {}
            on_target = top.get("onTargetReach", {})

            return {
                "success": True,
                "data": {
                    "targeted_reach": int(on_target.get("targetedReach", 0)),
                    "on_target_impressions": int(on_target.get("onTargetImpressions", 0)),
                    "total_reach": int(top.get("reach", 0)),
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
