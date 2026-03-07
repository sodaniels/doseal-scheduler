# app/services/social/x_ads_service.py

import json
import time
import requests
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from requests_oauthlib import OAuth1

from ....utils.logger import Log


class XAdsError(Exception):
    """
    Raised when the X Ads API returns a non-2xx response.
    Mirrors the structure of FacebookAdsService error handling.

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


class XAdsService:
    """
    Service for managing X (Twitter) Ads via the X Ads API v12.

    Flow for boosting a tweet:
    1. Create Campaign  (objective: ENGAGEMENTS)
    2. Create Line Item (targeting, bid, placements)
    3. Add Targeting Criteria to the line item
    4. Create Promoted Tweet (links existing tweet → line item)
    5. Activate campaign

    X Ads API hierarchy:
        Account → Funding Instrument → Campaign → Line Item → Promoted Tweet

    Auth: OAuth 1.0a
        consumer_key / consumer_secret      — your app credentials
        access_token / access_token_secret  — user-level credentials

    Note: All request bodies are form-encoded — NOT JSON.
          Budget values are in *local micro* units (1 USD = 1_000_000 micro).
    """

    API_VERSION = "12"
    BASE_URL = f"https://ads-api.x.com/{API_VERSION}"

    # Valid campaign objectives (v12)
    VALID_OBJECTIVES = {
        "ENGAGEMENTS",
        "WEBSITE_CLICKS",
        "APP_INSTALLS",
        "VIDEO_VIEWS",
        "FOLLOWERS",
        "APP_ENGAGEMENTS",
        "AWARENESS",
        "REACH",
        "PREROLL_VIEWS",
    }

    # Valid placements
    VALID_PLACEMENTS = {
        "ALL_ON_TWITTER",
        "PUBLISHER_NETWORK",
        "TWITTER_PROFILE",
        "TWITTER_SEARCH",
        "TWITTER_TIMELINE",
        "TAP_BANNER",
        "TAP_FULL",
        "TAP_FULL_LANDSCAPE",
        "TAP_NATIVE",
    }

    # Valid bid types
    VALID_BID_TYPES = {"AUTO", "MAX", "TARGET"}

    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        access_token: str,
        access_token_secret: str,
        account_id: str = None,
    ):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret
        self.account_id = account_id

        self._auth = OAuth1(
            self.consumer_key,
            client_secret=self.consumer_secret,
            resource_owner_key=self.access_token,
            resource_owner_secret=self.access_token_secret,
        )

    def _require_account(self):
        if not self.account_id:
            raise ValueError(
                "account_id is required for this operation. "
                "Initialize the service with an account_id."
            )

    # =========================================
    # INTERNAL HTTP
    # =========================================

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Make an OAuth 1.0a authenticated request to the X Ads API.

        Bodies are form-encoded (not JSON) — X Ads API requirement.
        Returns a normalised dict: {"success": bool, "data": ..., "error": ...}
        """
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        log_tag = f"[XAdsService][_request][{method}][{endpoint}]"

        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                auth=self._auth,
                params=params,
                data=data,       # form-encoded
                timeout=timeout,
            )

            try:
                result = response.json()
            except ValueError:
                result = {}

            if not response.ok:
                errors = result.get("errors", [])
                if not errors and "error" in result:
                    errors = [{"message": result["error"]}]
                error_message = errors[0].get("message", "Unknown error") if errors else "Unknown error"
                Log.error(f"{log_tag} API error {response.status_code}: {errors}")
                raise XAdsError(
                    f"X Ads API error {response.status_code} on {method.upper()} {url}",
                    errors=errors,
                    status_code=response.status_code,
                )

            return {"success": True, "data": result.get("data", result)}

        except XAdsError:
            raise  # re-raise as-is

        except requests.Timeout:
            Log.error(f"{log_tag} Request timeout")
            raise XAdsError("Request timeout", errors=[{"message": "Request timeout"}])

        except Exception as e:
            Log.error(f"{log_tag} Request failed: {e}")
            raise XAdsError(str(e), errors=[{"message": str(e)}])

    def _get(self, endpoint: str, params: Dict = None) -> Dict:
        return self._request("GET", endpoint, params=params)

    def _post(self, endpoint: str, data: Dict = None) -> Dict:
        return self._request("POST", endpoint, data=data)

    def _put(self, endpoint: str, data: Dict = None) -> Dict:
        return self._request("PUT", endpoint, data=data)

    def _delete(self, endpoint: str) -> Dict:
        return self._request("DELETE", endpoint)

    # =========================================
    # ACCOUNT MANAGEMENT
    # =========================================

    def get_account(self) -> Dict[str, Any]:
        """Get details of the current ads account."""
        self._require_account()
        resp = self._get(f"accounts/{self.account_id}")
        return resp.get("data", {}) if resp.get("success") else {}

    def get_all_accounts(self) -> Dict[str, Any]:
        """
        List all ads accounts accessible to the authenticated user.
        Does NOT require account_id — useful for the connect flow.
        """
        return self._get("accounts")

    def get_funding_instruments(self) -> Dict[str, Any]:
        """
        List funding instruments (payment methods) on the account.
        Use the returned `id` as `funding_instrument_id` when creating campaigns.
        """
        self._require_account()
        return self._get(f"accounts/{self.account_id}/funding_instruments")

    # =========================================
    # CAMPAIGN MANAGEMENT
    # =========================================

    def create_campaign(
        self,
        name: str,
        funding_instrument_id: str,
        objective: str = "ENGAGEMENTS",
        daily_budget_amount_local_micro: int = None,
        total_budget_amount_local_micro: int = None,
        start_time: datetime = None,
        end_time: datetime = None,
        entity_status: str = "PAUSED",
    ) -> Dict[str, Any]:
        """
        Create an ad campaign.

        Budgets are in local micro units: 1 USD = 1_000_000 micro.
        e.g. $10/day → daily_budget_amount_local_micro = 10_000_000

        Valid objectives:
            ENGAGEMENTS, WEBSITE_CLICKS, APP_INSTALLS, VIDEO_VIEWS,
            FOLLOWERS, APP_ENGAGEMENTS, AWARENESS, REACH, PREROLL_VIEWS
        """
        self._require_account()

        if objective not in self.VALID_OBJECTIVES:
            raise ValueError(
                f"Invalid objective '{objective}'. "
                f"Choose from: {self.VALID_OBJECTIVES}"
            )

        data: Dict[str, Any] = {
            "name": name,
            "funding_instrument_id": funding_instrument_id,
            "objective": objective,
            "entity_status": entity_status,
        }

        if daily_budget_amount_local_micro is not None:
            data["daily_budget_amount_local_micro"] = daily_budget_amount_local_micro
        if total_budget_amount_local_micro is not None:
            data["total_budget_amount_local_micro"] = total_budget_amount_local_micro
        if start_time:
            data["start_time"] = start_time.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        if end_time:
            data["end_time"] = end_time.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        return self._post(f"accounts/{self.account_id}/campaigns", data=data)

    def update_campaign(
        self,
        campaign_id: str,
        entity_status: str = None,
        name: str = None,
        daily_budget_amount_local_micro: int = None,
        end_time: datetime = None,
    ) -> Dict[str, Any]:
        """Update a campaign. Pass only the fields you want to change."""
        self._require_account()
        data: Dict[str, Any] = {}
        if entity_status:
            data["entity_status"] = entity_status
        if name:
            data["name"] = name
        if daily_budget_amount_local_micro is not None:
            data["daily_budget_amount_local_micro"] = daily_budget_amount_local_micro
        if end_time:
            data["end_time"] = end_time.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        return self._put(
            f"accounts/{self.account_id}/campaigns/{campaign_id}", data=data
        )

    def update_campaign_status(self, campaign_id: str, entity_status: str) -> Dict[str, Any]:
        """Update campaign status: ACTIVE | PAUSED | DELETED."""
        return self.update_campaign(campaign_id, entity_status=entity_status)

    def delete_campaign(self, campaign_id: str) -> Dict[str, Any]:
        """Delete a campaign."""
        self._require_account()
        return self._delete(f"accounts/{self.account_id}/campaigns/{campaign_id}")

    def get_campaigns(self) -> Dict[str, Any]:
        """List all campaigns on the account."""
        self._require_account()
        return self._get(f"accounts/{self.account_id}/campaigns")

    def get_campaign(self, campaign_id: str) -> Dict[str, Any]:
        """Get a single campaign by ID."""
        self._require_account()
        return self._get(f"accounts/{self.account_id}/campaigns/{campaign_id}")

    # =========================================
    # LINE ITEM MANAGEMENT (AD GROUPS)
    # =========================================

    def create_line_item(
        self,
        campaign_id: str,
        name: str = "Untitled",
        objective: str = "ENGAGEMENTS",
        placements: List[str] = None,
        bid_amount_local_micro: int = None,
        bid_type: str = "AUTO",
        charge_by: str = "ENGAGEMENT",
        product_type: str = "PROMOTED_TWEETS",
        entity_status: str = "PAUSED",
        advertiser_domain: str = None,
    ) -> Dict[str, Any]:
        """
        Create a line item (ad group) under a campaign.

        charge_by options:
            ENGAGEMENT | IMPRESSION | APP_CLICK | LINK_CLICK | FOLLOW | VIDEO_VIEW

        bid_amount_local_micro is ignored when bid_type="AUTO".
        """
        self._require_account()

        if placements is None:
            placements = ["ALL_ON_TWITTER"]

        invalid = set(placements) - self.VALID_PLACEMENTS
        if invalid:
            raise ValueError(f"Invalid placements: {invalid}")

        if bid_type not in self.VALID_BID_TYPES:
            raise ValueError(
                f"Invalid bid_type '{bid_type}'. Choose from: {self.VALID_BID_TYPES}"
            )

        data: Dict[str, Any] = {
            "campaign_id": campaign_id,
            "name": name,
            "objective": objective,
            "placements": placements,
            "bid_type": bid_type,
            "charge_by": charge_by,
            "product_type": product_type,
            "entity_status": entity_status,
        }

        if bid_type != "AUTO" and bid_amount_local_micro is not None:
            data["bid_amount_local_micro"] = bid_amount_local_micro
        if advertiser_domain:
            data["advertiser_domain"] = advertiser_domain

        return self._post(f"accounts/{self.account_id}/line_items", data=data)

    def update_line_item(
        self,
        line_item_id: str,
        entity_status: str = None,
        bid_amount_local_micro: int = None,
    ) -> Dict[str, Any]:
        """Update a line item."""
        self._require_account()
        data: Dict[str, Any] = {}
        if entity_status:
            data["entity_status"] = entity_status
        if bid_amount_local_micro is not None:
            data["bid_amount_local_micro"] = bid_amount_local_micro
        return self._put(
            f"accounts/{self.account_id}/line_items/{line_item_id}", data=data
        )

    def update_line_item_status(self, line_item_id: str, entity_status: str) -> Dict[str, Any]:
        """Update line item status: ACTIVE | PAUSED | DELETED."""
        return self.update_line_item(line_item_id, entity_status=entity_status)

    def delete_line_item(self, line_item_id: str) -> Dict[str, Any]:
        """Delete a line item."""
        self._require_account()
        return self._delete(f"accounts/{self.account_id}/line_items/{line_item_id}")

    def get_line_items(self, campaign_id: str = None) -> Dict[str, Any]:
        """List line items, optionally filtered by campaign."""
        self._require_account()
        params = {}
        if campaign_id:
            params["campaign_id"] = campaign_id
        return self._get(f"accounts/{self.account_id}/line_items", params=params)

    # =========================================
    # TARGETING CRITERIA
    # =========================================

    def add_targeting_criterion(
        self,
        line_item_id: str,
        targeting_type: str,
        targeting_value: str,
        tailored_audience_expansion: bool = False,
        tailored_audience_type: str = None,
    ) -> Dict[str, Any]:
        """
        Add a targeting criterion to a line item.

        Common targeting_type values:
            LOCATION          – targeting_value: WOEID (e.g. "23424977" for US)
            LANGUAGE          – targeting_value: BCP-47 code (e.g. "en")
            GENDER            – targeting_value: "1" (male) | "2" (female)
            AGE               – targeting_value: "AGE_18_TO_24" | "AGE_25_TO_34" | etc.
            INTEREST          – targeting_value: interest ID from search_interests()
            KEYWORD           – targeting_value: keyword string
            EXACT_KEYWORD     – targeting_value: keyword
            BROAD_KEYWORD     – targeting_value: keyword
            PHRASE_KEYWORD    – targeting_value: phrase
            NEGATIVE_KEYWORD  – targeting_value: keyword to exclude
            FOLLOWER_OF_USER  – targeting_value: Twitter user ID
            SIMILAR_TO_FOLLOWERS_OF_USER – targeting_value: Twitter user ID
            PLATFORM          – targeting_value: "0" desktop | "1" mobile | "2" tablet
            TAILORED_AUDIENCE – targeting_value: audience ID
        """
        self._require_account()

        data: Dict[str, Any] = {
            "line_item_id": line_item_id,
            "targeting_type": targeting_type,
            "targeting_value": targeting_value,
        }
        if tailored_audience_expansion:
            data["tailored_audience_expansion"] = "true"
        if tailored_audience_type:
            data["tailored_audience_type"] = tailored_audience_type

        return self._post(f"accounts/{self.account_id}/targeting_criteria", data=data)

    def add_targeting_criteria_batch(
        self,
        line_item_id: str,
        criteria: List[Dict[str, str]],
    ) -> List[Dict[str, Any]]:
        """
        Add multiple targeting criteria to a line item.

        criteria format:
            [
                {"targeting_type": "LOCATION", "targeting_value": "23424977"},
                {"targeting_type": "LANGUAGE", "targeting_value": "en"},
                {"targeting_type": "GENDER",   "targeting_value": "2"},
            ]
        """
        results = []
        for criterion in criteria:
            result = self.add_targeting_criterion(
                line_item_id=line_item_id,
                targeting_type=criterion["targeting_type"],
                targeting_value=criterion["targeting_value"],
                tailored_audience_expansion=criterion.get(
                    "tailored_audience_expansion", False
                ),
                tailored_audience_type=criterion.get("tailored_audience_type"),
            )
            results.append(result)
        return results

    def delete_targeting_criterion(self, targeting_criterion_id: str) -> Dict[str, Any]:
        """Delete a targeting criterion."""
        self._require_account()
        return self._delete(
            f"accounts/{self.account_id}/targeting_criteria/{targeting_criterion_id}"
        )

    def get_targeting_criteria(self, line_item_id: str) -> Dict[str, Any]:
        """List all targeting criteria for a line item."""
        self._require_account()
        return self._get(
            f"accounts/{self.account_id}/targeting_criteria",
            params={"line_item_id": line_item_id},
        )

    # =========================================
    # TARGETING HELPERS
    # =========================================

    def build_targeting(
        self,
        locations: List[str] = None,           # WOEIDs — use search_locations()
        languages: List[str] = None,            # BCP-47 e.g. ["en", "fr"]
        genders: List[str] = None,              # ["1"] male, ["2"] female, None = all
        age_buckets: List[str] = None,          # ["AGE_18_TO_24", "AGE_25_TO_34", ...]
        interests: List[str] = None,            # interest IDs from search_interests()
        keywords: List[str] = None,             # broad keyword strings
        follower_of_users: List[str] = None,    # Twitter user IDs to target their followers
        platforms: List[str] = None,            # ["0"] desktop | ["1"] mobile | ["2"] tablet
        tailored_audience_ids: List[str] = None,
    ) -> List[Dict[str, str]]:
        """
        Build a flat list of targeting criteria dicts ready for add_targeting_criteria_batch().

        Use search_locations() to find valid WOEIDs.
        Use search_interests() to find valid interest IDs.

        genders: ["1"] = male only, ["2"] = female only, omit for all genders

        Returns:
            [{"targeting_type": "LOCATION", "targeting_value": "23424977"}, ...]
        """
        criteria: List[Dict[str, str]] = []

        for woeid in (locations or ["23424977"]):   # default: United States
            criteria.append({"targeting_type": "LOCATION", "targeting_value": str(woeid)})

        for lang in (languages or ["en"]):
            criteria.append({"targeting_type": "LANGUAGE", "targeting_value": lang})

        for gender in (genders or []):
            criteria.append({"targeting_type": "GENDER", "targeting_value": str(gender)})

        for age in (age_buckets or []):
            criteria.append({"targeting_type": "AGE", "targeting_value": age})

        for interest_id in (interests or []):
            criteria.append({"targeting_type": "INTEREST", "targeting_value": str(interest_id)})

        for keyword in (keywords or []):
            criteria.append({"targeting_type": "BROAD_KEYWORD", "targeting_value": keyword})

        for user_id in (follower_of_users or []):
            criteria.append(
                {"targeting_type": "FOLLOWER_OF_USER", "targeting_value": str(user_id)}
            )

        for platform in (platforms or []):
            criteria.append({"targeting_type": "PLATFORM", "targeting_value": str(platform)})

        for audience_id in (tailored_audience_ids or []):
            criteria.append(
                {"targeting_type": "TAILORED_AUDIENCE", "targeting_value": str(audience_id)}
            )

        return criteria

    # =========================================
    # PROMOTED TWEETS (CREATIVES)
    # =========================================

    def create_promoted_tweet(
        self,
        line_item_id: str,
        tweet_id: str,
    ) -> Dict[str, Any]:
        """
        Associate a published or promoted-only tweet with a line item.
        tweet_id must be a numeric tweet ID string.
        The API returns a list; we normalise and return the first element.
        """
        self._require_account()
        data = {
            "line_item_id": line_item_id,
            "tweet_ids": tweet_id,
        }
        resp = self._post(f"accounts/{self.account_id}/promoted_tweets", data=data)
        if resp.get("success"):
            items = resp.get("data", [])
            resp["data"] = items[0] if isinstance(items, list) and items else items
        return resp

    def delete_promoted_tweet(self, promoted_tweet_id: str) -> Dict[str, Any]:
        """Remove a promoted tweet association from a line item."""
        self._require_account()
        return self._delete(
            f"accounts/{self.account_id}/promoted_tweets/{promoted_tweet_id}"
        )

    def get_promoted_tweets(self, line_item_id: str = None) -> Dict[str, Any]:
        """List promoted tweets, optionally filtered by line item."""
        self._require_account()
        params = {}
        if line_item_id:
            params["line_item_id"] = line_item_id
        return self._get(f"accounts/{self.account_id}/promoted_tweets", params=params)

    def create_promoted_only_tweet(
        self,
        text: str,
        as_user_id: str = None,
        media_ids: List[str] = None,
        card_uri: str = None,
    ) -> Dict[str, Any]:
        """
        Create a nullcasted (promoted-only) tweet.
        Does NOT appear on the user's public timeline.
        Use the returned `id` in create_promoted_tweet().
        """
        self._require_account()
        data: Dict[str, Any] = {
            "status": text,
            "nullcast": "true",
        }
        if as_user_id:
            data["as_user_id"] = as_user_id
        if media_ids:
            data["media_ids"] = ",".join(media_ids)
        if card_uri:
            data["card_uri"] = card_uri

        return self._post(f"accounts/{self.account_id}/tweet", data=data)

    # =========================================
    # TARGETING DISCOVERY
    # =========================================

    def search_interests(self, query: str = None, limit: int = 20) -> Dict[str, Any]:
        """
        Search available interest targeting categories.
        Use the returned `id` in build_targeting(interests=[...]).
        """
        self._require_account()
        params: Dict[str, Any] = {"count": limit}
        if query:
            params["q"] = query
        return self._get(
            f"accounts/{self.account_id}/targeting_criteria/interests",
            params=params,
        )

    def search_locations(self, query: str, location_type: str = None) -> Dict[str, Any]:
        """
        Search locations for targeting. Returns WOEIDs.
        location_type: CITY | REGION | COUNTRY | METRO
        """
        self._require_account()
        params = {"q": query}
        if location_type:
            params["location_type"] = location_type
        return self._get(
            f"accounts/{self.account_id}/targeting_criteria/locations",
            params=params,
        )

    def get_languages(self) -> Dict[str, Any]:
        """List all supported language targeting options."""
        self._require_account()
        return self._get(
            f"accounts/{self.account_id}/targeting_criteria/languages"
        )

    def get_devices(self) -> Dict[str, Any]:
        """List supported device targeting options."""
        self._require_account()
        return self._get(
            f"accounts/{self.account_id}/targeting_criteria/devices"
        )

    def search_behaviors(self, query: str) -> Dict[str, Any]:
        """Search behavior targeting options."""
        self._require_account()
        return self._get(
            f"accounts/{self.account_id}/targeting_criteria/behaviors",
            params={"q": query},
        )

    # =========================================
    # TAILORED AUDIENCES
    # =========================================

    def get_tailored_audiences(self) -> Dict[str, Any]:
        """List all tailored audiences on the account."""
        self._require_account()
        return self._get(f"accounts/{self.account_id}/tailored_audiences")

    def create_tailored_audience(
        self, name: str, list_type: str = "EMAIL"
    ) -> Dict[str, Any]:
        """
        Create a tailored audience.
        list_type: EMAIL | TWITTER_ID | DEVICE_ID | PHONE_NUMBER
        """
        self._require_account()
        return self._post(
            f"accounts/{self.account_id}/tailored_audiences",
            data={"name": name, "list_type": list_type},
        )

    # =========================================
    # REACH ESTIMATE
    # =========================================

    def get_reach_estimate(
        self,
        targeting_criteria: List[Dict[str, str]],
        objective: str = "ENGAGEMENTS",
        bid_amount_local_micro: int = None,
    ) -> Dict[str, Any]:
        """
        Estimate audience size for a given set of targeting criteria.

        targeting_criteria format (same as build_targeting() output):
            [{"targeting_type": "LOCATION", "targeting_value": "23424977"}, ...]
        """
        self._require_account()
        try:
            data: Dict[str, Any] = {
                "objective": objective,
                "targeting_criteria": json.dumps(targeting_criteria),
            }
            if bid_amount_local_micro:
                data["bid_amount_local_micro"] = bid_amount_local_micro

            resp = self._post(f"accounts/{self.account_id}/reach_estimate", data=data)

            if not resp.get("success"):
                return {"success": False, "error": resp.get("error")}

            raw = resp.get("data", {})
            return {
                "success": True,
                "data": {
                    "audience_size": raw.get("audience_size"),
                    "bid": raw.get("bid"),
                    "budget": raw.get("budget"),
                },
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # =========================================
    # INSIGHTS / REPORTING
    # =========================================

    def get_campaign_stats(
        self,
        campaign_ids: List[str],
        start_time: datetime = None,
        end_time: datetime = None,
        granularity: str = "DAY",
        metric_groups: List[str] = None,
        placement: str = "ALL_ON_TWITTER",
    ) -> Dict[str, Any]:
        """
        Fetch synchronous performance stats for one or more campaigns.

        granularity: HOUR | DAY | TOTAL
        metric_groups: ["ENGAGEMENT", "BILLING", "VIDEO", "MEDIA", "WEB_CONVERSION"]
        """
        self._require_account()

        if metric_groups is None:
            metric_groups = ["ENGAGEMENT", "BILLING"]

        params: Dict[str, Any] = {
            "entity": "CAMPAIGN",
            "entity_ids": ",".join(campaign_ids),
            "granularity": granularity,
            "metric_groups": ",".join(metric_groups),
            "placement": placement,
        }
        if start_time:
            params["start_time"] = start_time.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        if end_time:
            params["end_time"] = end_time.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        return self._get(f"stats/accounts/{self.account_id}", params=params)

    def get_line_item_stats(
        self,
        line_item_ids: List[str],
        start_time: datetime = None,
        end_time: datetime = None,
        granularity: str = "DAY",
        metric_groups: List[str] = None,
        placement: str = "ALL_ON_TWITTER",
    ) -> Dict[str, Any]:
        """Fetch synchronous stats for one or more line items."""
        self._require_account()

        if metric_groups is None:
            metric_groups = ["ENGAGEMENT", "BILLING"]

        params: Dict[str, Any] = {
            "entity": "LINE_ITEM",
            "entity_ids": ",".join(line_item_ids),
            "granularity": granularity,
            "metric_groups": ",".join(metric_groups),
            "placement": placement,
        }
        if start_time:
            params["start_time"] = start_time.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        if end_time:
            params["end_time"] = end_time.astimezone(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )

        return self._get(f"stats/accounts/{self.account_id}", params=params)

    def get_promoted_tweet_stats(
        self,
        promoted_tweet_ids: List[str],
        granularity: str = "DAY",
        metric_groups: List[str] = None,
    ) -> Dict[str, Any]:
        """Fetch stats for specific promoted tweet entities."""
        self._require_account()

        if metric_groups is None:
            metric_groups = ["ENGAGEMENT", "BILLING"]

        params: Dict[str, Any] = {
            "entity": "PROMOTED_TWEET",
            "entity_ids": ",".join(promoted_tweet_ids),
            "granularity": granularity,
            "metric_groups": ",".join(metric_groups),
            "placement": "ALL_ON_TWITTER",
        }
        return self._get(f"stats/accounts/{self.account_id}", params=params)

    # =========================================
    # BOOST TWEET (SIMPLIFIED FLOW)
    # =========================================

    def boost_tweet(
        self,
        tweet_id: str,
        funding_instrument_id: str,
        daily_budget_usd: float,
        duration_days: int = 7,
        targeting: List[Dict[str, str]] = None,
        objective: str = "ENGAGEMENTS",
        placements: List[str] = None,
        bid_type: str = "AUTO",
        bid_amount_usd: float = None,
        campaign_name: str = None,
        auto_activate: bool = False,
    ) -> Dict[str, Any]:
        """
        Boost an existing published tweet.

        Creates:
            Campaign → Line Item → Targeting Criteria → Promoted Tweet → Activates

        Args:
            tweet_id              : numeric tweet ID string to promote
            funding_instrument_id : from get_funding_instruments()
            daily_budget_usd      : e.g. 10.0 for $10/day
            duration_days         : how long to run the boost (sets end_time)
            targeting             : list from build_targeting(). None defaults to US + English.
            objective             : ENGAGEMENTS (default) | REACH | AWARENESS | etc.
            placements            : defaults to ["ALL_ON_TWITTER"]
            bid_type              : AUTO (default) | MAX | TARGET
            bid_amount_usd        : required for MAX / TARGET bid types
            campaign_name         : optional override for campaign display name
            auto_activate         : if True, sets entities to ACTIVE immediately
        """
        self._require_account()
        log_tag = "[XAdsService][boost_tweet]"

        if placements is None:
            placements = ["ALL_ON_TWITTER"]

        if targeting is None:
            targeting = self.build_targeting()  # US + English defaults

        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(days=duration_days)
        short_id = str(tweet_id)[-8:]
        campaign_name = campaign_name or f"Boost Tweet {short_id}"
        entity_status = "ACTIVE" if auto_activate else "PAUSED"

        result = {
            "success": False,
            "campaign_id": None,
            "line_item_id": None,
            "promoted_tweet_id": None,
            "errors": [],
        }

        try:
            # 1. Create Campaign
            Log.info(f"{log_tag} Creating campaign...")
            t = time.time()
            campaign_result = self.create_campaign(
                name=campaign_name,
                funding_instrument_id=funding_instrument_id,
                objective=objective,
                daily_budget_amount_local_micro=self.usd_to_micro(daily_budget_usd),
                start_time=start_time,
                end_time=end_time,
                entity_status=entity_status,
            )
            Log.info(f"{log_tag} Campaign API call completed in {time.time() - t:.2f}s")

            if not campaign_result.get("success"):
                result["errors"].append({
                    "step": "campaign",
                    "error": campaign_result.get("error_message", campaign_result.get("error")),
                    "details": campaign_result.get("error"),
                })
                return result

            campaign_id = campaign_result["data"]["id"]
            result["campaign_id"] = campaign_id
            Log.info(f"{log_tag} Campaign created: {campaign_id}")

            # 2. Create Line Item
            Log.info(f"{log_tag} Creating line item...")
            t = time.time()
            bid_micro = self.usd_to_micro(bid_amount_usd) if bid_amount_usd else None
            line_item_result = self.create_line_item(
                campaign_id=campaign_id,
                name=f"Boost Line Item {short_id}",
                objective=objective,
                placements=placements,
                bid_amount_local_micro=bid_micro,
                bid_type=bid_type,
                entity_status=entity_status,
            )
            Log.info(f"{log_tag} Line Item API call completed in {time.time() - t:.2f}s")

            if not line_item_result.get("success"):
                result["errors"].append({
                    "step": "line_item",
                    "error": line_item_result.get("error_message", line_item_result.get("error")),
                    "details": line_item_result.get("error"),
                })
                self._cleanup_campaign(campaign_id)
                return result

            line_item_id = line_item_result["data"]["id"]
            result["line_item_id"] = line_item_id
            Log.info(f"{log_tag} Line Item created: {line_item_id}")

            # 3. Add Targeting Criteria
            if targeting:
                Log.info(f"{log_tag} Adding {len(targeting)} targeting criteria...")
                t = time.time()
                self.add_targeting_criteria_batch(line_item_id, targeting)
                Log.info(f"{log_tag} Targeting completed in {time.time() - t:.2f}s")

            # 4. Associate Tweet as Promoted Tweet
            Log.info(f"{log_tag} Creating promoted tweet for tweet_id={tweet_id}...")
            t = time.time()
            promoted_result = self.create_promoted_tweet(
                line_item_id=line_item_id,
                tweet_id=tweet_id,
            )
            Log.info(f"{log_tag} Promoted Tweet API call completed in {time.time() - t:.2f}s")

            if not promoted_result.get("success"):
                result["errors"].append({
                    "step": "promoted_tweet",
                    "error": promoted_result.get("error_message", promoted_result.get("error")),
                    "details": promoted_result.get("error"),
                })
                self._cleanup_campaign(campaign_id)
                return result

            promoted_tweet_id = promoted_result["data"].get("id")
            result["promoted_tweet_id"] = promoted_tweet_id
            Log.info(f"{log_tag} Promoted Tweet created: {promoted_tweet_id}")

            # 5. Activate (campaign was created PAUSED — activate it now)
            if not auto_activate:
                Log.info(f"{log_tag} Activating campaign...")
                t = time.time()
                activate_result = self.update_campaign_status(campaign_id, "ACTIVE")
                Log.info(f"{log_tag} Activate API call completed in {time.time() - t:.2f}s")

                if not activate_result.get("success"):
                    result["errors"].append({
                        "step": "activate",
                        "error": activate_result.get("error_message", activate_result.get("error")),
                        "warning": "Campaign created but failed to activate. Please activate manually.",
                    })

            result["success"] = True
            Log.info(f"{log_tag} Tweet boosted successfully!")
            return result

        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            result["errors"].append({"step": "unknown", "error": str(e)})
            return result

    # =========================================
    # CARDS (EXPANDED CREATIVES)
    # =========================================

    def create_website_card(
        self,
        name: str,
        website_url: str,
        website_title: str,
        image_media_id: str = None,
    ) -> Dict[str, Any]:
        """Create a website card creative."""
        self._require_account()
        data: Dict[str, Any] = {
            "name": name,
            "website_url": website_url,
            "website_title": website_title,
        }
        if image_media_id:
            data["image_media_id"] = image_media_id
        return self._post(f"accounts/{self.account_id}/cards/website", data=data)

    def create_app_download_card(
        self,
        name: str,
        app_country_code: str,
        iphone_app_id: str = None,
        ipad_app_id: str = None,
        googleplay_app_id: str = None,
        call_to_action: str = "INSTALL",
        custom_icon_media_id: str = None,
        custom_app_description: str = None,
    ) -> Dict[str, Any]:
        """Create an app download card creative."""
        self._require_account()
        data: Dict[str, Any] = {
            "name": name,
            "app_country_code": app_country_code,
            "call_to_action": call_to_action,
        }
        if iphone_app_id:
            data["iphone_app_id"] = iphone_app_id
        if ipad_app_id:
            data["ipad_app_id"] = ipad_app_id
        if googleplay_app_id:
            data["googleplay_app_id"] = googleplay_app_id
        if custom_icon_media_id:
            data["custom_icon_media_id"] = custom_icon_media_id
        if custom_app_description:
            data["custom_app_description"] = custom_app_description
        return self._post(f"accounts/{self.account_id}/cards/app_download", data=data)

    # =========================================
    # INTERNAL HELPERS
    # =========================================

    def _cleanup_campaign(self, campaign_id: str):
        """
        Try to delete a campaign during error rollback.
        Logs but does not raise — mirrors FacebookAdsService._cleanup_campaign().
        """
        log_tag = "[XAdsService][_cleanup_campaign]"
        try:
            Log.info(f"{log_tag} Cleaning up campaign {campaign_id}...")
            delete_result = self.update_campaign_status(campaign_id, "DELETED")
            if delete_result.get("success"):
                Log.info(f"{log_tag} Campaign {campaign_id} deleted successfully")
            else:
                Log.warning(
                    f"{log_tag} Failed to delete campaign {campaign_id}: "
                    f"{delete_result.get('error')}"
                )
        except Exception as e:
            Log.warning(f"{log_tag} Exception during cleanup (ignored): {e}")

    @staticmethod
    def usd_to_micro(usd: float) -> int:
        """Convert a USD float to local micro units. e.g. 10.0 → 10_000_000"""
        return int(usd * 1_000_000)

    @staticmethod
    def micro_to_usd(micro: int) -> float:
        """Convert local micro units back to USD. e.g. 10_000_000 → 10.0"""
        return micro / 1_000_000

    @staticmethod
    def _normalize_account_id(account_id: str) -> str:
        """Strip any accidental whitespace from the account ID."""
        return (account_id or "").strip()
