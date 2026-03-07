# app/services/social/ads/linkedin_ads_service.py

import json
import time
import requests
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ....utils.logger import Log


class LinkedInAdsError(Exception):
    """
    Raised when the LinkedIn Marketing API returns a non-2xx response.

    Attributes:
        errors      : list of error dicts from the API response
        status_code : HTTP status code from the response
    """

    def __init__(self, message: str, errors: list = None, status_code: int = None):
        super().__init__(message)
        self.errors = errors or []
        self.status_code = status_code

    def __str__(self):
        base = super().__str__()
        if self.errors:
            details = "; ".join(
                e.get("message", str(e)) for e in self.errors
            )
            return f"{base} | API errors: {details}"
        return base


class LinkedInAdsService:
    """
    Service for managing LinkedIn Ads via the LinkedIn Marketing API v2.

    Flow for boosting a post (Sponsored Content):
        1. Resolve ad account URN           (urn:li:sponsoredAccount:<id>)
        2. Create Campaign Group            (container for campaigns)
        3. Create Campaign                  (budget, targeting, objective)
        4. Create Creative                  (links existing post/UGC post)
        5. Activate campaign group + campaign

    LinkedIn API hierarchy:
        Ad Account → Campaign Group → Campaign → Creative

    Auth: OAuth 2.0 Bearer token (access_token from SocialAccount)

    Budget: LinkedIn uses amounts in the account currency's minor unit
            e.g. 1000 = $10.00 USD  (same as Facebook cents convention)

    Targeting: Uses LinkedIn URNs for most facets:
        - Locations : urn:li:geo:<id>
        - Job titles: urn:li:title:<id>
        - Industries: urn:li:industry:<id>
        - Companies : urn:li:company:<id>
        - Skills    : urn:li:skill:<id>
        - Degrees   : urn:li:degree:<id>
        - Seniority : urn:li:seniority:<id>
        - Member age: ageRange facet with start/end

    Versioned API: LinkedIn requires a Linkedin-Version header for v2 endpoints.
    We use 202304 (April 2023) which is stable for Campaign Management API.
    """

    BASE_URL = "https://api.linkedin.com/v2"
    VERSIONED_URL = "https://api.linkedin.com/rest"
    API_VERSION = "202304"

    def __init__(self, access_token: str, ad_account_id: str = None):
        self.access_token = access_token
        self.ad_account_id = ad_account_id  # numeric string, e.g. "510123456"
        self.account_urn = f"urn:li:sponsoredAccount:{ad_account_id}" if ad_account_id else None

    def _require_account(self):
        if not self.ad_account_id or not self.account_urn:
            raise ValueError(
                "ad_account_id is required for this operation. "
                "Initialize the service with an ad_account_id."
            )

    def _headers(self, versioned: bool = False) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        if versioned:
            headers["LinkedIn-Version"] = self.API_VERSION
        return headers

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        json_body: Optional[Dict] = None,
        versioned: bool = False,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        base = self.VERSIONED_URL if versioned else self.BASE_URL
        url = f"{base}/{endpoint}"
        log_tag = f"[LinkedInAdsService][_request][{method}][{endpoint}]"

        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                headers=self._headers(versioned=versioned),
                params=params,
                json=json_body,
                timeout=timeout,
            )

            # 204 No Content (e.g. DELETE, status update)
            if response.status_code == 204:
                return {"success": True, "data": {}}

            try:
                result = response.json()
            except Exception:
                result = {"raw": response.text}

            if not response.ok:
                # LinkedIn error shapes vary:
                #   {"message": "...", "status": 403}
                #   {"code": "...", "message": "..."}
                #   {"errors": [...]}
                errors = result.get("errors") or []
                if not errors:
                    msg = result.get("message") or result.get("code") or str(result)
                    errors = [{"message": msg}]

                Log.error(f"{log_tag} API error {response.status_code}: {errors}")
                raise LinkedInAdsError(
                    f"LinkedIn API error {response.status_code} on {method.upper()} {url}",
                    errors=errors,
                    status_code=response.status_code,
                )

            return {"success": True, "data": result}

        except LinkedInAdsError:
            raise

        except requests.Timeout:
            Log.error(f"{log_tag} Request timeout")
            raise LinkedInAdsError("Request timeout", errors=[{"message": "Request timeout"}])

        except Exception as e:
            Log.error(f"{log_tag} Request failed: {e}")
            raise LinkedInAdsError(str(e), errors=[{"message": str(e)}])

    # =========================================
    # AD ACCOUNT
    # =========================================

    def get_ad_accounts(self) -> Dict[str, Any]:
        """
        List all ad accounts accessible to the authenticated user.
        Does NOT require ad_account_id to be set.
        """
        return self._request(
            "GET",
            "adAccounts",
            params={
                "q": "search",
                "search.type.values[0]": "BUSINESS",
                "fields": "id,name,currency,status,type,reference,notifiedOnCampaignOptimization",
            },
        )

    def get_ad_account(self) -> Dict[str, Any]:
        """Get details of the current ad account."""
        self._require_account()
        return self._request("GET", f"adAccounts/{self.ad_account_id}")

    # =========================================
    # CAMPAIGN GROUPS
    # =========================================

    def create_campaign_group(
        self,
        name: str,
        status: str = "ACTIVE",
        start_date: datetime = None,
        end_date: datetime = None,
        total_budget: int = None,
    ) -> Dict[str, Any]:
        """
        Create a campaign group (container for campaigns).
        status: ACTIVE | ARCHIVED | CANCELED | DRAFT | PAUSED | PENDING_DELETION | REMOVED
        total_budget: in minor currency units (cents). Optional.
        """
        self._require_account()

        body: Dict[str, Any] = {
            "account": self.account_urn,
            "name": name,
            "status": status,
            "runSchedule": {},
        }

        if start_date:
            body["runSchedule"]["start"] = int(start_date.timestamp() * 1000)
        else:
            body["runSchedule"]["start"] = int(datetime.now(timezone.utc).timestamp() * 1000)

        if end_date:
            body["runSchedule"]["end"] = int(end_date.timestamp() * 1000)

        if total_budget:
            body["totalBudget"] = {
                "amount": str(total_budget),
                "currencyCode": "USD",
            }

        return self._request("POST", "adCampaignGroups", json_body=body)

    def update_campaign_group_status(self, group_id: str, status: str) -> Dict[str, Any]:
        """Update campaign group status."""
        return self._request(
            "POST",
            f"adCampaignGroups/{group_id}",
            json_body={"patch": {"$set": {"status": status}}},
        )

    def delete_campaign_group(self, group_id: str) -> Dict[str, Any]:
        """Delete (archive) a campaign group."""
        return self._request(
            "POST",
            f"adCampaignGroups/{group_id}",
            json_body={"patch": {"$set": {"status": "ARCHIVED"}}},
        )

    def get_campaign_groups(self, count: int = 20) -> Dict[str, Any]:
        """List campaign groups for this ad account."""
        self._require_account()
        return self._request(
            "GET",
            "adCampaignGroups",
            params={
                "q": "search",
                "search.account.values[0]": self.account_urn,
                "count": count,
            },
        )

    # =========================================
    # CAMPAIGNS
    # =========================================

    def create_campaign(
        self,
        campaign_group_id: str,
        name: str,
        objective: str = "ENGAGEMENT",
        daily_budget: int = None,
        total_budget: int = None,
        bid_strategy: str = "AUTOMATED",
        bid_amount: int = None,
        targeting: Dict[str, Any] = None,
        start_date: datetime = None,
        end_date: datetime = None,
        status: str = "PAUSED",
        audience_expansion_enabled: bool = False,
        locale: Dict[str, str] = None,
    ) -> Dict[str, Any]:
        """
        Create a campaign.

        objective:
            BRAND_AWARENESS, ENGAGEMENT, JOB_APPLICANTS, LEAD_GENERATION,
            WEBSITE_CONVERSIONS, WEBSITE_VISITS, VIDEO_VIEWS

        bid_strategy:
            AUTOMATED     — LinkedIn manages bids (recommended)
            MAXIMUM_CPM   — max cost per 1000 impressions
            TARGET_COST_PER_CLICK — target CPC

        budget: in minor currency units (e.g. 1000 = $10.00 USD)
        """
        self._require_account()

        body: Dict[str, Any] = {
            "account": self.account_urn,
            "campaignGroup": f"urn:li:sponsoredCampaignGroup:{campaign_group_id}",
            "name": name,
            "objectiveType": objective,
            "costType": "CPM",           # CPM required for most objectives; CPC for WEBSITE_VISITS
            "type": "SPONSORED_UPDATES", # Sponsored Content
            "status": status,
            "audienceExpansionEnabled": audience_expansion_enabled,
            "locale": locale or {"country": "US", "language": "en"},
            "runSchedule": {},
        }

        if start_date:
            body["runSchedule"]["start"] = int(start_date.timestamp() * 1000)
        else:
            body["runSchedule"]["start"] = int(datetime.now(timezone.utc).timestamp() * 1000)

        if end_date:
            body["runSchedule"]["end"] = int(end_date.timestamp() * 1000)

        # Budget — daily OR total, not both
        if daily_budget:
            body["dailyBudget"] = {"amount": str(daily_budget), "currencyCode": "USD"}
        elif total_budget:
            body["totalBudget"] = {"amount": str(total_budget), "currencyCode": "USD"}

        # Bid strategy
        body["bidOptimizationMode"] = bid_strategy
        if bid_amount and bid_strategy != "AUTOMATED":
            body["unitCost"] = {"amount": str(bid_amount), "currencyCode": "USD"}

        # Targeting
        if targeting:
            body["targetingCriteria"] = targeting

        return self._request("POST", "adCampaigns", json_body=body)

    def update_campaign(self, campaign_id: str, updates: Dict) -> Dict[str, Any]:
        """Partial update a campaign via PATCH."""
        return self._request(
            "POST",
            f"adCampaigns/{campaign_id}",
            json_body={"patch": {"$set": updates}},
        )

    def update_campaign_status(self, campaign_id: str, status: str) -> Dict[str, Any]:
        """Update campaign status (ACTIVE, PAUSED, ARCHIVED, CANCELED)."""
        return self._request(
            "POST",
            f"adCampaigns/{campaign_id}",
            json_body={"patch": {"$set": {"status": status}}},
        )

    def delete_campaign(self, campaign_id: str) -> Dict[str, Any]:
        """Archive a campaign."""
        return self.update_campaign_status(campaign_id, "ARCHIVED")

    def get_campaigns(self, count: int = 20, status_filter: str = None) -> Dict[str, Any]:
        """List campaigns for this ad account."""
        self._require_account()
        params = {
            "q": "search",
            "search.account.values[0]": self.account_urn,
            "count": count,
        }
        if status_filter:
            params["search.status.values[0]"] = status_filter
        return self._request("GET", "adCampaigns", params=params)

    def get_campaign(self, campaign_id: str) -> Dict[str, Any]:
        """Get a single campaign."""
        return self._request("GET", f"adCampaigns/{campaign_id}")

    # =========================================
    # CREATIVES
    # =========================================

    def create_creative_from_ugc_post(
        self,
        campaign_id: str,
        ugc_post_urn: str,
        status: str = "ACTIVE",
    ) -> Dict[str, Any]:
        """
        Create a Sponsored Content creative from an existing UGC post.

        ugc_post_urn: urn:li:ugcPost:<id>
            — get this from the LinkedIn post URL or the post creation response.
        """
        self._require_account()

        body = {
            "account": self.account_urn,
            "campaign": f"urn:li:sponsoredCampaign:{campaign_id}",
            "reference": ugc_post_urn,
            "status": status,
            "type": "SPONSORED",
        }

        return self._request("POST", "adCreatives", json_body=body)

    def create_creative_from_share(
        self,
        campaign_id: str,
        share_urn: str,
        status: str = "ACTIVE",
    ) -> Dict[str, Any]:
        """
        Create a creative from an older Share (v1 post).
        share_urn: urn:li:share:<id>
        """
        self._require_account()

        body = {
            "account": self.account_urn,
            "campaign": f"urn:li:sponsoredCampaign:{campaign_id}",
            "reference": share_urn,
            "status": status,
            "type": "SPONSORED",
        }

        return self._request("POST", "adCreatives", json_body=body)

    def get_creatives(self, campaign_id: str, count: int = 20) -> Dict[str, Any]:
        """List creatives for a campaign."""
        return self._request(
            "GET",
            "adCreatives",
            params={
                "q": "search",
                "search.campaign.values[0]": f"urn:li:sponsoredCampaign:{campaign_id}",
                "count": count,
            },
        )

    def update_creative_status(self, creative_id: str, status: str) -> Dict[str, Any]:
        """Update creative status (ACTIVE, PAUSED, ARCHIVED, CANCELED)."""
        return self._request(
            "POST",
            f"adCreatives/{creative_id}",
            json_body={"patch": {"$set": {"status": status}}},
        )

    # =========================================
    # ANALYTICS / STATS
    # =========================================

    def get_campaign_stats(
        self,
        campaign_id: str,
        date_range_start: datetime = None,
        date_range_end: datetime = None,
        fields: List[str] = None,
        time_granularity: str = "ALL",
    ) -> Dict[str, Any]:
        """
        Get campaign analytics.

        time_granularity: ALL | DAILY | MONTHLY | YEARLY

        Common fields:
            impressions, clicks, costInLocalCurrency,
            totalEngagements, likes, comments, shares,
            follows, uniqueImpressions, approximateUniqueImpressions
        """
        if not fields:
            fields = [
                "impressions", "clicks", "costInLocalCurrency",
                "totalEngagements", "likes", "comments", "shares",
                "follows", "uniqueImpressions",
            ]

        now = datetime.now(timezone.utc)
        start = date_range_start or (now - timedelta(days=7))
        end = date_range_end or now

        params = {
            "q": "analytics",
            "pivot": "CAMPAIGN",
            "timeGranularity": time_granularity,
            "campaigns[0]": f"urn:li:sponsoredCampaign:{campaign_id}",
            "dateRange.start.year": start.year,
            "dateRange.start.month": start.month,
            "dateRange.start.day": start.day,
            "dateRange.end.year": end.year,
            "dateRange.end.month": end.month,
            "dateRange.end.day": end.day,
            "fields": ",".join(fields),
        }

        return self._request("GET", "adAnalytics", params=params)

    def get_creative_stats(
        self,
        creative_id: str,
        date_range_start: datetime = None,
        date_range_end: datetime = None,
    ) -> Dict[str, Any]:
        """Get analytics for a specific creative."""
        now = datetime.now(timezone.utc)
        start = date_range_start or (now - timedelta(days=7))
        end = date_range_end or now

        params = {
            "q": "analytics",
            "pivot": "CREATIVE",
            "timeGranularity": "ALL",
            "creatives[0]": f"urn:li:sponsoredCreative:{creative_id}",
            "dateRange.start.year": start.year,
            "dateRange.start.month": start.month,
            "dateRange.start.day": start.day,
            "dateRange.end.year": end.year,
            "dateRange.end.month": end.month,
            "dateRange.end.day": end.day,
            "fields": "impressions,clicks,costInLocalCurrency,totalEngagements",
        }

        return self._request("GET", "adAnalytics", params=params)

    # =========================================
    # TARGETING FACETS (DISCOVERY)
    # =========================================

    def search_geo_locations(self, query: str, count: int = 10) -> Dict[str, Any]:
        """
        Search for geo targeting facets (countries, regions, cities).
        Returns URNs like urn:li:geo:90009696 (United States)
        Use these URNs in build_targeting() locations param.
        """
        return self._request(
            "GET",
            "adTargetingFacets/locations",
            params={"q": "typeahead", "query": query, "count": count},
        )

    def search_job_titles(self, query: str, count: int = 10) -> Dict[str, Any]:
        """Search for job title facets. Returns urn:li:title:<id>"""
        return self._request(
            "GET",
            "adTargetingFacets/titles",
            params={"q": "typeahead", "query": query, "count": count},
        )

    def search_industries(self, query: str, count: int = 10) -> Dict[str, Any]:
        """Search for industry facets. Returns urn:li:industry:<id>"""
        return self._request(
            "GET",
            "adTargetingFacets/industries",
            params={"q": "typeahead", "query": query, "count": count},
        )

    def search_skills(self, query: str, count: int = 10) -> Dict[str, Any]:
        """Search for skill facets. Returns urn:li:skill:<id>"""
        return self._request(
            "GET",
            "adTargetingFacets/skills",
            params={"q": "typeahead", "query": query, "count": count},
        )

    def get_seniority_facets(self) -> Dict[str, Any]:
        """Get all seniority levels (static list). Returns urn:li:seniority:<id>"""
        return self._request(
            "GET",
            "adTargetingFacets/seniorities",
            params={"q": "typeahead", "query": ""},
        )

    def get_company_size_facets(self) -> Dict[str, Any]:
        """Get company size facets (static list)."""
        return self._request(
            "GET",
            "adTargetingFacets/companySizes",
            params={"q": "typeahead", "query": ""},
        )

    # =========================================
    # TARGETING HELPERS
    # =========================================

    def build_targeting(
        self,
        locations: List[str] = None,          # geo URNs e.g. ["urn:li:geo:90009696"]
        job_titles: List[str] = None,          # title URNs e.g. ["urn:li:title:100"]
        industries: List[str] = None,          # industry URNs
        skills: List[str] = None,              # skill URNs
        seniorities: List[str] = None,         # seniority URNs e.g. ["urn:li:seniority:10"]
        company_sizes: List[str] = None,       # e.g. ["B"] (2–10), ["C"] (11–50), etc.
        member_age_ranges: List[Dict] = None,  # [{"start": 25, "end": 34}]
        member_gender: str = None,             # "MALE" | "FEMALE" | None (all)
        include_audiences: List[str] = None,   # matched audience URNs
        exclude_audiences: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Build a LinkedIn targetingCriteria dict.

        LinkedIn uses include/exclude facets format:
        {
            "include": {
                "and": [
                    {"or": {"urn:li:adTargetingFacet:locations": [...urns...]}},
                    {"or": {"urn:li:adTargetingFacet:titles": [...urns...]}},
                ]
            },
            "exclude": {
                "or": {...}
            }
        }

        company_size codes: A=1, B=2-10, C=11-50, D=51-200, E=201-500,
                            F=501-1000, G=1001-5000, H=5001-10000, I=10001+
        """
        include_facets = []

        # Locations (required — default to worldwide if not provided)
        geo_urns = locations or ["urn:li:geo:90009696"]  # US default
        include_facets.append({
            "or": {"urn:li:adTargetingFacet:locations": geo_urns}
        })

        if job_titles:
            include_facets.append({
                "or": {"urn:li:adTargetingFacet:titles": job_titles}
            })

        if industries:
            include_facets.append({
                "or": {"urn:li:adTargetingFacet:industries": industries}
            })

        if skills:
            include_facets.append({
                "or": {"urn:li:adTargetingFacet:skills": skills}
            })

        if seniorities:
            include_facets.append({
                "or": {"urn:li:adTargetingFacet:seniorities": seniorities}
            })

        if company_sizes:
            include_facets.append({
                "or": {"urn:li:adTargetingFacet:staffCountRanges": company_sizes}
            })

        if member_age_ranges:
            include_facets.append({
                "or": {"urn:li:adTargetingFacet:ageRanges": [
                    {"start": r.get("start"), "end": r.get("end")}
                    for r in member_age_ranges
                ]}
            })

        if member_gender:
            include_facets.append({
                "or": {"urn:li:adTargetingFacet:genders": [member_gender]}
            })

        if include_audiences:
            include_facets.append({
                "or": {"urn:li:adTargetingFacet:matchedAudiences": include_audiences}
            })

        targeting: Dict[str, Any] = {
            "include": {"and": include_facets}
        }

        if exclude_audiences:
            targeting["exclude"] = {
                "or": {"urn:li:adTargetingFacet:matchedAudiences": exclude_audiences}
            }

        return targeting

    # =========================================
    # REACH ESTIMATE
    # =========================================

    def get_reach_estimate(self, targeting: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get estimated audience size for a targeting spec.
        Returns approximate member count range.
        """
        self._require_account()
        try:
            resp = self._request(
                "GET",
                "adTargetingEntities",
                params={
                    "q": "audienceCountWithDetails",
                    "account": self.account_urn,
                    "targetingCriteria": json.dumps(targeting),
                },
            )

            if not resp.get("success"):
                return {"success": False, "error": resp.get("error")}

            data = resp.get("data", {})
            return {
                "success": True,
                "data": {
                    "approximate_count": data.get("approximateMemberCount"),
                    "audience_count_without_exclusion": data.get("audienceCountWithoutExclusion"),
                },
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================
    # MATCHED AUDIENCES
    # =========================================

    def get_matched_audiences(self, count: int = 20) -> Dict[str, Any]:
        """List matched audiences (retargeting, contact lists, lookalikes)."""
        self._require_account()
        return self._request(
            "GET",
            "adAudienceCounts",
            params={
                "q": "search",
                "search.account.values[0]": self.account_urn,
                "count": count,
            },
        )

    # =========================================
    # ORGANIC POST LOOKUP (for Creative URN)
    # =========================================

    def get_ugc_post(self, ugc_post_id: str) -> Dict[str, Any]:
        """
        Fetch a UGC post by ID to validate it exists before creating a creative.
        ugc_post_id: numeric string from urn:li:ugcPost:<id>
        """
        return self._request("GET", f"ugcPosts/urn:li:ugcPost:{ugc_post_id}")

    def get_organization_posts(self, organization_urn: str, count: int = 10) -> Dict[str, Any]:
        """
        List recent UGC posts for an organization page.
        organization_urn: urn:li:organization:<id>
        """
        return self._request(
            "GET",
            "ugcPosts",
            params={
                "q": "authors",
                "authors[0]": organization_urn,
                "count": count,
            },
        )

    # =========================================
    # CLEANUP HELPER
    # =========================================

    def _cleanup_campaign_group(self, group_id: str):
        """Archive a campaign group on boost failure. Best-effort."""
        try:
            self.delete_campaign_group(group_id)
            Log.info(f"[LinkedInAdsService][_cleanup] archived group {group_id}")
        except Exception as e:
            Log.error(f"[LinkedInAdsService][_cleanup] failed to archive group {group_id}: {e}")

    # =========================================
    # BOOST POST (SIMPLIFIED FLOW)
    # =========================================

    def boost_post(
        self,
        post_urn: str,                         # urn:li:ugcPost:<id> or urn:li:share:<id>
        daily_budget: int,                      # minor currency units (e.g. 1000 = $10.00)
        duration_days: int = 7,
        objective: str = "ENGAGEMENT",
        targeting: Dict[str, Any] = None,
        campaign_name: str = None,
        bid_strategy: str = "AUTOMATED",
        bid_amount: int = None,
        auto_activate: bool = False,
        locale: Dict[str, str] = None,
    ) -> Dict[str, Any]:
        """
        Boost an existing LinkedIn post (Sponsored Content).

        Creates: Campaign Group → Campaign → Creative → Activates (if auto_activate)

        Args:
            post_urn      : URN of the post to boost — urn:li:ugcPost:<id>
            daily_budget  : Daily budget in minor currency units (1000 = $10.00)
            duration_days : How many days to run. Sets runSchedule.end on the campaign.
            objective     : ENGAGEMENT (default) | WEBSITE_VISITS | BRAND_AWARENESS |
                            LEAD_GENERATION | VIDEO_VIEWS
            targeting     : From build_targeting(). None defaults to US + English.
            campaign_name : Override. Defaults to "Boost Post <short_id>".
            bid_strategy  : AUTOMATED (default) | MAXIMUM_CPM | TARGET_COST_PER_CLICK
            bid_amount    : Required for non-AUTOMATED bid strategies.
            auto_activate : If True, campaign is set ACTIVE immediately. Default: PAUSED.
            locale        : {"country": "US", "language": "en"} by default.

        Returns:
            {
                "success": bool,
                "campaign_group_id": str | None,
                "campaign_id": str | None,
                "creative_id": str | None,
                "errors": [{"step": str, "error": str}]
            }
        """
        self._require_account()
        log_tag = "[LinkedInAdsService][boost_post]"

        if not targeting:
            targeting = self.build_targeting()  # defaults to US

        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(days=duration_days)

        # Derive short label from post URN
        short_id = post_urn.split(":")[-1][-8:] if post_urn else "post"
        campaign_name = campaign_name or f"Boost Post {short_id}"

        initial_status = "ACTIVE" if auto_activate else "PAUSED"

        result: Dict[str, Any] = {
            "success": False,
            "campaign_group_id": None,
            "campaign_id": None,
            "creative_id": None,
            "errors": [],
        }

        try:
            # --------------------------------------------------
            # 1. Create Campaign Group
            # --------------------------------------------------
            Log.info(f"{log_tag} Creating campaign group...")
            group_resp = self.create_campaign_group(
                name=f"{campaign_name} Group",
                status=initial_status,
                start_date=start_time,
                end_date=end_time,
            )

            group_id = str(group_resp.get("data", {}).get("id", ""))
            if not group_id:
                # LinkedIn returns the URN in the X-RestLi-Id header for POST
                # Fallback: parse from headers if present (handled by caller)
                result["errors"].append({"step": "campaign_group", "error": "No group ID returned"})
                return result

            result["campaign_group_id"] = group_id
            Log.info(f"{log_tag} Campaign group created: {group_id}")

            # --------------------------------------------------
            # 2. Create Campaign
            # --------------------------------------------------
            Log.info(f"{log_tag} Creating campaign...")
            campaign_resp = self.create_campaign(
                campaign_group_id=group_id,
                name=campaign_name,
                objective=objective,
                daily_budget=daily_budget,
                targeting=targeting,
                bid_strategy=bid_strategy,
                bid_amount=bid_amount,
                start_date=start_time,
                end_date=end_time,
                status=initial_status,
                locale=locale or {"country": "US", "language": "en"},
            )

            campaign_id = str(campaign_resp.get("data", {}).get("id", ""))
            if not campaign_id:
                result["errors"].append({"step": "campaign", "error": "No campaign ID returned"})
                self._cleanup_campaign_group(group_id)
                return result

            result["campaign_id"] = campaign_id
            Log.info(f"{log_tag} Campaign created: {campaign_id}")

            # --------------------------------------------------
            # 3. Create Creative from existing post
            # --------------------------------------------------
            Log.info(f"{log_tag} Creating creative from {post_urn}...")

            if "ugcPost" in post_urn:
                creative_resp = self.create_creative_from_ugc_post(
                    campaign_id=campaign_id,
                    ugc_post_urn=post_urn,
                    status=initial_status,
                )
            else:
                # Older share URN
                creative_resp = self.create_creative_from_share(
                    campaign_id=campaign_id,
                    share_urn=post_urn,
                    status=initial_status,
                )

            creative_id = str(creative_resp.get("data", {}).get("id", ""))
            if not creative_id:
                result["errors"].append({"step": "creative", "error": "No creative ID returned"})
                self._cleanup_campaign_group(group_id)
                return result

            result["creative_id"] = creative_id
            Log.info(f"{log_tag} Creative created: {creative_id}")

            result["success"] = True
            Log.info(f"{log_tag} Post boosted successfully!")
            return result

        except LinkedInAdsError as e:
            Log.error(f"{log_tag} LinkedInAdsError: {e}")
            result["errors"].append({"step": "unknown", "error": str(e)})
            return result

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            result["errors"].append({"step": "unknown", "error": str(e)})
            return result
