# app/services/social/pinterest_ads_service.py

import json
import time
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from ...utils.logger import Log


class PinterestAdsService:
    """
    Service for managing Pinterest Ads via Pinterest Marketing API.
    
    Pinterest Ads Structure:
    - Ad Account → Campaign → Ad Group → Ad (Pin Promotion)
    
    Flow for promoting a pin:
    1. Create Campaign (objective: AWARENESS, CONSIDERATION, CONVERSIONS, etc.)
    2. Create Ad Group (targeting, budget, schedule)
    3. Create Ad (promote existing pin or create new promoted pin)
    """
    
    API_VERSION = "v5"
    BASE_URL = f"https://api.pinterest.com/{API_VERSION}"
    
    # Campaign Objectives
    OBJECTIVE_AWARENESS = "AWARENESS"
    OBJECTIVE_CONSIDERATION = "CONSIDERATION"
    OBJECTIVE_VIDEO_VIEW = "VIDEO_VIEW"
    OBJECTIVE_WEB_CONVERSION = "WEB_CONVERSION"
    OBJECTIVE_CATALOG_SALES = "CATALOG_SALES"
    OBJECTIVE_SHOPPING = "SHOPPING"
    
    # Ad Group Optimization Goals
    OPTIMIZATION_IMPRESSION = "IMPRESSION"
    OPTIMIZATION_CLICKTHROUGH = "CLICKTHROUGH"
    OPTIMIZATION_OUTBOUND_CLICK = "OUTBOUND_CLICK"
    OPTIMIZATION_VIDEO_VIEW = "VIDEO_V_50_MRC"
    OPTIMIZATION_ENGAGEMENT = "ENGAGEMENT"
    
    # Placement Types
    PLACEMENT_ALL = "ALL"
    PLACEMENT_BROWSE = "BROWSE"
    PLACEMENT_SEARCH = "SEARCH"
    
    # Status
    STATUS_ACTIVE = "ACTIVE"
    STATUS_PAUSED = "PAUSED"
    STATUS_ARCHIVED = "ARCHIVED"
    
    # Billing Types
    BILLING_CPC = "CPC"
    BILLING_CPM = "CPM"
    BILLING_CPV = "CPV"
    
    def __init__(self, access_token: str, ad_account_id: str = None):
        """
        Initialize the Pinterest Ads Service.
        
        Args:
            access_token: Pinterest OAuth access token
            ad_account_id: Pinterest Ad Account ID (optional for some methods)
        """
        self.access_token = access_token
        self.ad_account_id = ad_account_id
    
    def _require_ad_account(self):
        """Raise error if ad_account_id is not set."""
        if not self.ad_account_id:
            raise ValueError("ad_account_id is required for this operation")
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        json_data: Optional[Dict] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Make a request to the Pinterest API."""
        
        url = f"{self.BASE_URL}/{endpoint}"
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        
        log_tag = f"[PinterestAdsService][_request][{method}][{endpoint}]"
        
        try:
            start_time = time.time()
            
            if method == "GET":
                response = requests.get(url, headers=headers, params=params, timeout=timeout)
            elif method == "POST":
                response = requests.post(url, headers=headers, params=params, json=json_data or data, timeout=timeout)
            elif method == "PATCH":
                response = requests.patch(url, headers=headers, params=params, json=json_data or data, timeout=timeout)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers, params=params, timeout=timeout)
            else:
                return {"success": False, "error": f"Unsupported method: {method}"}
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} API call completed in {duration:.2f}s status={response.status_code}")
            
            # Handle empty responses
            if response.status_code == 204:
                return {"success": True, "data": {}}
            
            try:
                result = response.json()
            except json.JSONDecodeError:
                result = {"raw_response": response.text}
            
            # Pinterest error format
            if response.status_code >= 400:
                error_message = result.get("message", result.get("error", "Unknown error"))
                error_code = result.get("code", response.status_code)
                
                Log.error(f"{log_tag} API error: {result}")
                
                return {
                    "success": False,
                    "error": result,
                    "error_message": error_message,
                    "error_code": error_code,
                    "status_code": response.status_code,
                }
            
            return {"success": True, "data": result}
        
        except requests.Timeout:
            Log.error(f"{log_tag} Request timeout")
            return {"success": False, "error": "Request timeout"}
        
        except Exception as e:
            Log.error(f"{log_tag} Request failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================
    # USER & AD ACCOUNT MANAGEMENT
    # =========================================
    
    def get_user_account(self) -> Dict[str, Any]:
        """Get the authenticated user's account info."""
        return self._request("GET", "user_account")
    
    def get_user_ad_accounts(self, bookmark: str = None) -> Dict[str, Any]:
        """
        Get all ad accounts the user has access to.
        
        Returns list of ad accounts with:
        - id, name, owner, country, currency, permissions, etc.
        """
        params = {}
        if bookmark:
            params["bookmark"] = bookmark
        
        return self._request("GET", "ad_accounts", params=params)
    
    def get_ad_account_info(self) -> Dict[str, Any]:
        """Get details of the current ad account."""
        self._require_ad_account()
        return self._request("GET", f"ad_accounts/{self.ad_account_id}")
    
    def get_ad_account_analytics(
        self,
        start_date: str,
        end_date: str,
        granularity: str = "DAY",
        columns: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Get analytics for the ad account.
        
        Args:
            start_date: YYYY-MM-DD format
            end_date: YYYY-MM-DD format
            granularity: DAY, HOUR, WEEK, MONTH, TOTAL
            columns: Metrics to retrieve
        """
        self._require_ad_account()
        
        if not columns:
            columns = [
                "IMPRESSION", "CLICKTHROUGH", "SPEND_IN_MICRO_DOLLAR",
                "CTR", "CPC_IN_MICRO_DOLLAR", "CPM_IN_MICRO_DOLLAR",
                "ENGAGEMENT", "SAVE", "PIN_CLICK"
            ]
        
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "granularity": granularity,
            "columns": ",".join(columns),
        }
        
        return self._request("GET", f"ad_accounts/{self.ad_account_id}/analytics", params=params)

    # =========================================
    # CAMPAIGN MANAGEMENT
    # =========================================
    
    def create_campaign(
        self,
        name: str,
        objective_type: str = "AWARENESS",
        status: str = "PAUSED",
        daily_spend_cap: int = None,
        lifetime_spend_cap: int = None,
        start_time: int = None,
        end_time: int = None,
        tracking_urls: Dict = None,
    ) -> Dict[str, Any]:
        """
        Create an ad campaign.
        
        Args:
            name: Campaign name
            objective_type: AWARENESS, CONSIDERATION, VIDEO_VIEW, WEB_CONVERSION, CATALOG_SALES, SHOPPING
            status: ACTIVE or PAUSED
            daily_spend_cap: Daily budget in micro currency (1000000 = $1.00)
            lifetime_spend_cap: Lifetime budget in micro currency
            start_time: Unix timestamp
            end_time: Unix timestamp
            tracking_urls: UTM parameters
        """
        self._require_ad_account()
        
        log_tag = "[PinterestAdsService][create_campaign]"
        
        data = {
            "ad_account_id": self.ad_account_id,
            "name": name,
            "objective_type": objective_type,
            "status": status,
        }
        
        if daily_spend_cap:
            data["daily_spend_cap"] = daily_spend_cap
        if lifetime_spend_cap:
            data["lifetime_spend_cap"] = lifetime_spend_cap
        if start_time:
            data["start_time"] = start_time
        if end_time:
            data["end_time"] = end_time
        if tracking_urls:
            data["tracking_urls"] = tracking_urls
        
        Log.info(f"{log_tag} Creating campaign: {name}")
        
        return self._request("POST", f"ad_accounts/{self.ad_account_id}/campaigns", json_data=data)
    
    def get_campaigns(
        self,
        campaign_ids: List[str] = None,
        status: str = None,
        bookmark: str = None,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        """Get campaigns for the ad account."""
        self._require_ad_account()
        
        params = {"page_size": page_size}
        if campaign_ids:
            params["campaign_ids"] = ",".join(campaign_ids)
        if status:
            params["entity_statuses"] = status
        if bookmark:
            params["bookmark"] = bookmark
        
        return self._request("GET", f"ad_accounts/{self.ad_account_id}/campaigns", params=params)
    
    def update_campaign(self, campaign_id: str, updates: Dict) -> Dict[str, Any]:
        """Update a campaign."""
        self._require_ad_account()
        
        data = {"id": campaign_id, **updates}
        
        return self._request(
            "PATCH",
            f"ad_accounts/{self.ad_account_id}/campaigns",
            json_data=[data]  # Pinterest expects array
        )
    
    def update_campaign_status(self, campaign_id: str, status: str) -> Dict[str, Any]:
        """Update campaign status (ACTIVE, PAUSED, ARCHIVED)."""
        return self.update_campaign(campaign_id, {"status": status})

    # =========================================
    # AD GROUP MANAGEMENT
    # =========================================
    
    def create_ad_group(
        self,
        campaign_id: str,
        name: str,
        budget_in_micro_currency: int,
        budget_type: str = "DAILY",
        bid_in_micro_currency: int = None,
        optimization_goal_metadata: Dict = None,
        billing_event: str = "IMPRESSION",
        placement_group: str = "ALL",
        targeting_spec: Dict = None,
        start_time: int = None,
        end_time: int = None,
        status: str = "PAUSED",
        auto_targeting_enabled: bool = True,
    ) -> Dict[str, Any]:
        """
        Create an ad group.
        
        Args:
            campaign_id: Parent campaign ID
            name: Ad group name
            budget_in_micro_currency: Budget in micro currency (1000000 = $1.00)
            budget_type: DAILY or LIFETIME
            bid_in_micro_currency: Bid amount in micro currency
            optimization_goal_metadata: Optimization settings
            billing_event: IMPRESSION, CLICKTHROUGH, VIDEO_V_50_MRC
            placement_group: ALL, BROWSE, SEARCH
            targeting_spec: Targeting specification
            start_time: Unix timestamp
            end_time: Unix timestamp (required for LIFETIME budget)
            status: ACTIVE or PAUSED
            auto_targeting_enabled: Let Pinterest expand targeting
        """
        self._require_ad_account()
        
        log_tag = "[PinterestAdsService][create_ad_group]"
        
        data = {
            "ad_account_id": self.ad_account_id,
            "campaign_id": campaign_id,
            "name": name,
            "status": status,
            "budget_in_micro_currency": budget_in_micro_currency,
            "budget_type": budget_type,
            "billable_event": billing_event,
            "placement_group": placement_group,
            "auto_targeting_enabled": auto_targeting_enabled,
        }
        
        if bid_in_micro_currency:
            data["bid_in_micro_currency"] = bid_in_micro_currency
        
        if optimization_goal_metadata:
            data["optimization_goal_metadata"] = optimization_goal_metadata
        
        if targeting_spec:
            data["targeting_spec"] = targeting_spec
        
        if start_time:
            data["start_time"] = start_time
        if end_time:
            data["end_time"] = end_time
        
        Log.info(f"{log_tag} Creating ad group: {name} for campaign: {campaign_id}")
        
        return self._request("POST", f"ad_accounts/{self.ad_account_id}/ad_groups", json_data=data)
    
    def get_ad_groups(
        self,
        campaign_ids: List[str] = None,
        ad_group_ids: List[str] = None,
        status: str = None,
        bookmark: str = None,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        """Get ad groups for the ad account."""
        self._require_ad_account()
        
        params = {"page_size": page_size}
        if campaign_ids:
            params["campaign_ids"] = ",".join(campaign_ids)
        if ad_group_ids:
            params["ad_group_ids"] = ",".join(ad_group_ids)
        if status:
            params["entity_statuses"] = status
        if bookmark:
            params["bookmark"] = bookmark
        
        return self._request("GET", f"ad_accounts/{self.ad_account_id}/ad_groups", params=params)
    
    def update_ad_group(self, ad_group_id: str, updates: Dict) -> Dict[str, Any]:
        """Update an ad group."""
        self._require_ad_account()
        
        data = {"id": ad_group_id, **updates}
        
        return self._request(
            "PATCH",
            f"ad_accounts/{self.ad_account_id}/ad_groups",
            json_data=[data]
        )
    
    def update_ad_group_status(self, ad_group_id: str, status: str) -> Dict[str, Any]:
        """Update ad group status."""
        return self.update_ad_group(ad_group_id, {"status": status})

    # =========================================
    # TARGETING HELPERS
    # =========================================
    
    def build_targeting_spec(
        self,
        # Location
        geo_locations: List[str] = None,  # Country codes: ["US", "GB"]
        regions: List[str] = None,  # Region IDs
        
        # Demographics
        age_bucket: List[str] = None,  # ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
        genders: List[str] = None,  # ["male", "female", "unknown"]
        
        # Interests
        interest_ids: List[str] = None,  # Pinterest interest IDs
        
        # Keywords
        keywords: List[str] = None,  # Search keywords
        
        # Audiences
        audience_include: List[str] = None,  # Audience IDs to include
        audience_exclude: List[str] = None,  # Audience IDs to exclude
        
        # Devices
        device_types: List[str] = None,  # ["MOBILE", "TABLET", "WEB"]
        
        # Language
        locales: List[str] = None,  # ["en-US", "es-ES"]
    ) -> Dict[str, Any]:
        """
        Build a targeting spec for ad groups.
        
        Pinterest targeting is additive (AND between categories, OR within categories).
        """
        targeting_spec = {}
        
        # Geo targeting
        if geo_locations:
            targeting_spec["GEO"] = geo_locations
        if regions:
            targeting_spec["REGION"] = regions
        
        # Demographics
        if age_bucket:
            targeting_spec["AGE_BUCKET"] = age_bucket
        if genders:
            targeting_spec["GENDER"] = genders
        
        # Interests
        if interest_ids:
            targeting_spec["INTEREST"] = interest_ids
        
        # Keywords
        if keywords:
            targeting_spec["KEYWORD"] = keywords
        
        # Audiences
        if audience_include:
            targeting_spec["AUDIENCE_INCLUDE"] = audience_include
        if audience_exclude:
            targeting_spec["AUDIENCE_EXCLUDE"] = audience_exclude
        
        # Devices
        if device_types:
            targeting_spec["TARGETING_STRATEGY"] = device_types
        
        # Locales
        if locales:
            targeting_spec["LOCALE"] = locales
        
        return targeting_spec
    
    def search_interests(self, query: str, limit: int = 25) -> Dict[str, Any]:
        """Search for interest targeting options."""
        self._require_ad_account()
        
        return self._request(
            "GET",
            f"ad_accounts/{self.ad_account_id}/targeting_analytics",
            params={
                "targeting_types": "INTEREST",
                "query": query,
                "page_size": limit,
            }
        )
    
    def get_targeting_options(self, targeting_type: str) -> Dict[str, Any]:
        """
        Get available targeting options.
        
        targeting_type: APPTYPE, GENDER, LOCALE, AGE_BUCKET, LOCATION, GEO, INTEREST, KEYWORD, AUDIENCE_INCLUDE, AUDIENCE_EXCLUDE
        """
        self._require_ad_account()
        
        return self._request(
            "GET",
            f"ad_accounts/{self.ad_account_id}/targeting_analytics",
            params={"targeting_types": targeting_type}
        )

    # =========================================
    # AD (PIN PROMOTION) MANAGEMENT
    # =========================================
    
    def create_ad(
        self,
        ad_group_id: str,
        creative_type: str,
        pin_id: str = None,
        name: str = None,
        status: str = "PAUSED",
        destination_url: str = None,
        tracking_urls: Dict = None,
        carousel_android_deep_links: List[str] = None,
        carousel_ios_deep_links: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Create an ad (promoted pin).
        
        Args:
            ad_group_id: Parent ad group ID
            creative_type: REGULAR (image), VIDEO, SHOPPING, CAROUSEL, MAX_VIDEO, SHOP_THE_PIN, COLLECTION, IDEA
            pin_id: Existing pin ID to promote
            name: Ad name
            status: ACTIVE or PAUSED
            destination_url: Click-through URL
            tracking_urls: UTM parameters
        """
        self._require_ad_account()
        
        log_tag = "[PinterestAdsService][create_ad]"
        
        data = {
            "ad_account_id": self.ad_account_id,
            "ad_group_id": ad_group_id,
            "creative_type": creative_type,
            "status": status,
        }
        
        if pin_id:
            data["pin_id"] = pin_id
        if name:
            data["name"] = name
        if destination_url:
            data["destination_url"] = destination_url
        if tracking_urls:
            data["tracking_urls"] = tracking_urls
        if carousel_android_deep_links:
            data["carousel_android_deep_links"] = carousel_android_deep_links
        if carousel_ios_deep_links:
            data["carousel_ios_deep_links"] = carousel_ios_deep_links
        
        Log.info(f"{log_tag} Creating ad for pin: {pin_id} in ad_group: {ad_group_id}")
        
        return self._request("POST", f"ad_accounts/{self.ad_account_id}/ads", json_data=data)
    
    def get_ads(
        self,
        ad_group_ids: List[str] = None,
        campaign_ids: List[str] = None,
        ad_ids: List[str] = None,
        status: str = None,
        bookmark: str = None,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        """Get ads for the ad account."""
        self._require_ad_account()
        
        params = {"page_size": page_size}
        if ad_group_ids:
            params["ad_group_ids"] = ",".join(ad_group_ids)
        if campaign_ids:
            params["campaign_ids"] = ",".join(campaign_ids)
        if ad_ids:
            params["ad_ids"] = ",".join(ad_ids)
        if status:
            params["entity_statuses"] = status
        if bookmark:
            params["bookmark"] = bookmark
        
        return self._request("GET", f"ad_accounts/{self.ad_account_id}/ads", params=params)
    
    def update_ad(self, ad_id: str, updates: Dict) -> Dict[str, Any]:
        """Update an ad."""
        self._require_ad_account()
        
        data = {"id": ad_id, **updates}
        
        return self._request(
            "PATCH",
            f"ad_accounts/{self.ad_account_id}/ads",
            json_data=[data]
        )
    
    def update_ad_status(self, ad_id: str, status: str) -> Dict[str, Any]:
        """Update ad status."""
        return self.update_ad(ad_id, {"status": status})

    # =========================================
    # PIN MANAGEMENT
    # =========================================
    
    def get_pins(
        self,
        bookmark: str = None,
        page_size: int = 25,
        pin_filter: str = None,
    ) -> Dict[str, Any]:
        """
        Get pins for the authenticated user.
        
        pin_filter: exclude_repins, exclude_videos
        """
        params = {"page_size": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        if pin_filter:
            params["pin_filter"] = pin_filter
        
        return self._request("GET", "pins", params=params)
    
    def get_pin(self, pin_id: str) -> Dict[str, Any]:
        """Get a specific pin."""
        return self._request("GET", f"pins/{pin_id}")
    
    def get_pin_analytics(
        self,
        pin_id: str,
        start_date: str,
        end_date: str,
        metric_types: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Get analytics for a specific pin.
        
        Args:
            pin_id: Pin ID
            start_date: YYYY-MM-DD format
            end_date: YYYY-MM-DD format
            metric_types: IMPRESSION, SAVE, PIN_CLICK, OUTBOUND_CLICK, VIDEO_MRC_VIEW, VIDEO_V50_WATCH_TIME, QUARTILE_95_PERCENT_VIEW
        """
        if not metric_types:
            metric_types = ["IMPRESSION", "SAVE", "PIN_CLICK", "OUTBOUND_CLICK"]
        
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "metric_types": ",".join(metric_types),
            "app_types": "ALL",
            "split_field": "NO_SPLIT",
        }
        
        return self._request("GET", f"pins/{pin_id}/analytics", params=params)

    # =========================================
    # BOARDS MANAGEMENT
    # =========================================
    
    def get_boards(self, bookmark: str = None, page_size: int = 25) -> Dict[str, Any]:
        """Get boards for the authenticated user."""
        params = {"page_size": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        
        return self._request("GET", "boards", params=params)
    
    def get_board_pins(
        self,
        board_id: str,
        bookmark: str = None,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        """Get pins from a specific board."""
        params = {"page_size": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        
        return self._request("GET", f"boards/{board_id}/pins", params=params)

    # =========================================
    # INSIGHTS / ANALYTICS
    # =========================================
    
    def get_campaign_analytics(
        self,
        campaign_ids: List[str],
        start_date: str,
        end_date: str,
        granularity: str = "DAY",
        columns: List[str] = None,
    ) -> Dict[str, Any]:
        """Get analytics for campaigns."""
        self._require_ad_account()
        
        if not columns:
            columns = [
                "IMPRESSION", "CLICKTHROUGH", "SPEND_IN_MICRO_DOLLAR",
                "CTR", "CPC_IN_MICRO_DOLLAR", "CPM_IN_MICRO_DOLLAR",
                "ENGAGEMENT", "SAVE", "PIN_CLICK"
            ]
        
        params = {
            "campaign_ids": ",".join(campaign_ids),
            "start_date": start_date,
            "end_date": end_date,
            "granularity": granularity,
            "columns": ",".join(columns),
        }
        
        return self._request(
            "GET",
            f"ad_accounts/{self.ad_account_id}/campaigns/analytics",
            params=params
        )
    
    def get_ad_group_analytics(
        self,
        ad_group_ids: List[str],
        start_date: str,
        end_date: str,
        granularity: str = "DAY",
        columns: List[str] = None,
    ) -> Dict[str, Any]:
        """Get analytics for ad groups."""
        self._require_ad_account()
        
        if not columns:
            columns = [
                "IMPRESSION", "CLICKTHROUGH", "SPEND_IN_MICRO_DOLLAR",
                "CTR", "CPC_IN_MICRO_DOLLAR", "CPM_IN_MICRO_DOLLAR",
                "ENGAGEMENT", "SAVE", "PIN_CLICK"
            ]
        
        params = {
            "ad_group_ids": ",".join(ad_group_ids),
            "start_date": start_date,
            "end_date": end_date,
            "granularity": granularity,
            "columns": ",".join(columns),
        }
        
        return self._request(
            "GET",
            f"ad_accounts/{self.ad_account_id}/ad_groups/analytics",
            params=params
        )
    
    def get_ad_analytics(
        self,
        ad_ids: List[str],
        start_date: str,
        end_date: str,
        granularity: str = "DAY",
        columns: List[str] = None,
    ) -> Dict[str, Any]:
        """Get analytics for ads."""
        self._require_ad_account()
        
        if not columns:
            columns = [
                "IMPRESSION", "CLICKTHROUGH", "SPEND_IN_MICRO_DOLLAR",
                "CTR", "CPC_IN_MICRO_DOLLAR", "CPM_IN_MICRO_DOLLAR",
                "ENGAGEMENT", "SAVE", "PIN_CLICK"
            ]
        
        params = {
            "ad_ids": ",".join(ad_ids),
            "start_date": start_date,
            "end_date": end_date,
            "granularity": granularity,
            "columns": ",".join(columns),
        }
        
        return self._request(
            "GET",
            f"ad_accounts/{self.ad_account_id}/ads/analytics",
            params=params
        )

    # =========================================
    # PROMOTE PIN (SIMPLIFIED FLOW)
    # =========================================
    
    def promote_pin(
        self,
        pin_id: str,
        budget_amount: int,
        duration_days: int = 7,
        objective_type: str = "AWARENESS",
        targeting_spec: Dict = None,
        bid_amount: int = None,
        destination_url: str = None,
        campaign_name: str = None,
        auto_targeting_enabled: bool = True,
    ) -> Dict[str, Any]:
        """
        Simplified method to promote an existing pin.
        
        Creates Campaign → Ad Group → Ad in one flow.
        
        Args:
            pin_id: Pinterest Pin ID to promote
            budget_amount: Total budget in cents (e.g., 1000 = $10.00)
            duration_days: How many days to run the ad
            objective_type: AWARENESS, CONSIDERATION, VIDEO_VIEW, WEB_CONVERSION
            targeting_spec: Targeting specification (None = broad targeting)
            bid_amount: Bid in cents (None = auto bid)
            destination_url: Override click URL
            campaign_name: Optional campaign name
            auto_targeting_enabled: Let Pinterest expand targeting
        
        Returns:
            Dict with success, campaign_id, ad_group_id, ad_id, errors
        """
        self._require_ad_account()
        
        log_tag = "[PinterestAdsService][promote_pin]"
        
        # Convert cents to micro currency (1 cent = 10000 micro)
        budget_micro = budget_amount * 10000
        bid_micro = bid_amount * 10000 if bid_amount else None
        
        # Default targeting if none provided
        if not targeting_spec:
            targeting_spec = self.build_targeting_spec(
                geo_locations=["US"],
                age_bucket=["25-34", "35-44", "45-54"],
            )
        
        # Calculate dates
        start_time = int(datetime.now(timezone.utc).timestamp())
        end_time = int((datetime.now(timezone.utc) + timedelta(days=duration_days)).timestamp())
        
        # Generate names
        short_id = str(pin_id)[-8:]
        campaign_name = campaign_name or f"Promote Pin {short_id}"
        
        result = {
            "success": False,
            "campaign_id": None,
            "ad_group_id": None,
            "ad_id": None,
            "errors": [],
        }
        
        try:
            # 1. Create Campaign
            Log.info(f"{log_tag} Creating campaign...")
            campaign_start = time.time()
            
            campaign_result = self.create_campaign(
                name=campaign_name,
                objective_type=objective_type,
                status="PAUSED",
                lifetime_spend_cap=budget_micro,
                start_time=start_time,
                end_time=end_time,
            )
            
            campaign_duration = time.time() - campaign_start
            Log.info(f"{log_tag} Campaign API call completed in {campaign_duration:.2f}s")
            
            if not campaign_result.get("success"):
                result["errors"].append({
                    "step": "campaign",
                    "error": campaign_result.get("error_message", campaign_result.get("error")),
                    "details": campaign_result.get("error"),
                })
                return result
            
            campaign_id = campaign_result["data"].get("id")
            result["campaign_id"] = campaign_id
            Log.info(f"{log_tag} Campaign created: {campaign_id}")
            
            # 2. Create Ad Group
            Log.info(f"{log_tag} Creating ad group...")
            ad_group_start = time.time()
            
            # Determine billing event based on objective
            billing_event = "IMPRESSION"
            if objective_type in ["CONSIDERATION", "WEB_CONVERSION"]:
                billing_event = "CLICKTHROUGH"
            
            ad_group_result = self.create_ad_group(
                campaign_id=campaign_id,
                name=f"AdGroup {short_id}",
                budget_in_micro_currency=budget_micro,
                budget_type="LIFETIME",
                bid_in_micro_currency=bid_micro,
                billing_event=billing_event,
                placement_group="ALL",
                targeting_spec=targeting_spec,
                start_time=start_time,
                end_time=end_time,
                status="PAUSED",
                auto_targeting_enabled=auto_targeting_enabled,
            )
            
            ad_group_duration = time.time() - ad_group_start
            Log.info(f"{log_tag} Ad Group API call completed in {ad_group_duration:.2f}s")
            
            if not ad_group_result.get("success"):
                result["errors"].append({
                    "step": "ad_group",
                    "error": ad_group_result.get("error_message", ad_group_result.get("error")),
                    "details": ad_group_result.get("error"),
                })
                # Cleanup: archive campaign
                self._cleanup_campaign(campaign_id)
                return result
            
            ad_group_id = ad_group_result["data"].get("id")
            result["ad_group_id"] = ad_group_id
            Log.info(f"{log_tag} Ad Group created: {ad_group_id}")
            
            # 3. Get pin info to determine creative type
            Log.info(f"{log_tag} Getting pin info...")
            pin_info = self.get_pin(pin_id)
            
            creative_type = "REGULAR"
            if pin_info.get("success"):
                pin_data = pin_info.get("data", {})
                media_type = pin_data.get("media", {}).get("media_type", "")
                if media_type == "video":
                    creative_type = "VIDEO"
                elif pin_data.get("is_idea_pin"):
                    creative_type = "IDEA"
            
            # 4. Create Ad (Promoted Pin)
            Log.info(f"{log_tag} Creating ad for pin: {pin_id}...")
            ad_start = time.time()
            
            ad_result = self.create_ad(
                ad_group_id=ad_group_id,
                creative_type=creative_type,
                pin_id=pin_id,
                name=f"Promoted Pin {short_id}",
                status="PAUSED",
                destination_url=destination_url,
            )
            
            ad_duration = time.time() - ad_start
            Log.info(f"{log_tag} Ad API call completed in {ad_duration:.2f}s")
            
            if not ad_result.get("success"):
                result["errors"].append({
                    "step": "ad",
                    "error": ad_result.get("error_message", ad_result.get("error")),
                    "details": ad_result.get("error"),
                })
                self._cleanup_campaign(campaign_id)
                return result
            
            ad_id = ad_result["data"].get("id")
            result["ad_id"] = ad_id
            Log.info(f"{log_tag} Ad created: {ad_id}")
            
            # 5. Activate the campaign
            Log.info(f"{log_tag} Activating campaign...")
            activate_start = time.time()
            
            # Activate ad, ad group, then campaign
            self.update_ad_status(ad_id, "ACTIVE")
            self.update_ad_group_status(ad_group_id, "ACTIVE")
            activate_result = self.update_campaign_status(campaign_id, "ACTIVE")
            
            activate_duration = time.time() - activate_start
            Log.info(f"{log_tag} Activation completed in {activate_duration:.2f}s")
            
            if not activate_result.get("success"):
                result["errors"].append({
                    "step": "activate",
                    "error": activate_result.get("error_message", activate_result.get("error")),
                    "warning": "Campaign created but failed to activate. Please activate manually.",
                })
            
            result["success"] = True
            Log.info(f"{log_tag} Pin promoted successfully!")
            
            return result
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            result["errors"].append({
                "step": "unknown",
                "error": str(e),
            })
            return result
    
    def _cleanup_campaign(self, campaign_id: str):
        """
        Try to archive a campaign during error cleanup.
        """
        log_tag = "[PinterestAdsService][_cleanup_campaign]"
        try:
            Log.info(f"{log_tag} Cleaning up campaign {campaign_id}...")
            archive_result = self.update_campaign_status(campaign_id, "ARCHIVED")
            if archive_result.get("success"):
                Log.info(f"{log_tag} Campaign {campaign_id} archived successfully")
            else:
                Log.info(f"{log_tag} Failed to archive campaign {campaign_id}: {archive_result.get('error')}")
        except Exception as e:
            Log.info(f"{log_tag} Exception during cleanup (ignored): {e}")

    # =========================================
    # AUDIENCES
    # =========================================
    
    def get_audiences(
        self,
        bookmark: str = None,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        """Get audiences for the ad account."""
        self._require_ad_account()
        
        params = {"page_size": page_size}
        if bookmark:
            params["bookmark"] = bookmark
        
        return self._request("GET", f"ad_accounts/{self.ad_account_id}/audiences", params=params)
    
    def create_audience(
        self,
        name: str,
        audience_type: str,
        description: str = None,
        rule: Dict = None,
    ) -> Dict[str, Any]:
        """
        Create a custom audience.
        
        audience_type: CUSTOMER_LIST, VISITOR, ENGAGEMENT, ACTALIKE
        """
        self._require_ad_account()
        
        data = {
            "ad_account_id": self.ad_account_id,
            "name": name,
            "audience_type": audience_type,
        }
        
        if description:
            data["description"] = description
        if rule:
            data["rule"] = rule
        
        return self._request("POST", f"ad_accounts/{self.ad_account_id}/audiences", json_data=data)