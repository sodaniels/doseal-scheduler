# app/services/social/facebook_ads_service.py

import json
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from ...utils.logger import Log


class FacebookAdsService:
    """
    Service for managing Facebook Ads via Marketing API.
    
    Flow for boosting a post:
    1. Create Campaign (objective: OUTCOME_ENGAGEMENT)
    2. Create Ad Set (targeting, budget, schedule)
    3. Create Ad Creative (linked to existing post)
    4. Create Ad (links campaign, adset, creative)
    """
    
    API_VERSION = "v20.0"
    BASE_URL = f"https://graph.facebook.com/{API_VERSION}"
    
    def __init__(self, access_token: str, ad_account_id: str = None):
        """
        Initialize the Facebook Ads Service.
        
        Args:
            access_token: User's Facebook access token with ads permissions
            ad_account_id: Ad account ID (optional for some methods like get_user_ad_accounts)
        """
        self.access_token = access_token
        self.ad_account_id = None
        
        # ✅ Only process if ad_account_id is provided
        if ad_account_id:
            # Ensure ad_account_id has "act_" prefix
            if not str(ad_account_id).startswith("act_"):
                self.ad_account_id = f"act_{ad_account_id}"
            else:
                self.ad_account_id = ad_account_id
    
    def _require_ad_account(self):
        """Raise error if ad_account_id is not set."""
        if not self.ad_account_id:
            raise ValueError("ad_account_id is required for this operation. Initialize the service with an ad_account_id.")
    
    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict] = None,
        data: Optional[Dict] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """Make a request to the Facebook Marketing API."""
        
        url = f"{self.BASE_URL}/{endpoint}"
        
        params = params or {}
        params["access_token"] = self.access_token
        
        log_tag = f"[FacebookAdsService][_request][{method}][{endpoint}]"
        
        try:
            if method == "GET":
                response = requests.get(url, params=params, timeout=timeout)
            elif method == "POST":
                response = requests.post(url, params=params, data=data, timeout=timeout)
            elif method == "DELETE":
                response = requests.delete(url, params=params, timeout=timeout)
            else:
                return {"success": False, "error": f"Unsupported method: {method}"}
            
            result = response.json()
            
            if "error" in result:
                Log.error(f"{log_tag} API error: {result['error']}")
                return {
                    "success": False,
                    "error": result["error"],
                    "error_message": result["error"].get("message", "Unknown error"),
                    "error_code": result["error"].get("code"),
                    "error_subcode": result["error"].get("error_subcode"),
                }
            
            return {"success": True, "data": result}
        
        except requests.Timeout:
            Log.error(f"{log_tag} Request timeout")
            return {"success": False, "error": "Request timeout"}
        
        except Exception as e:
            Log.error(f"{log_tag} Request failed: {e}")
            return {"success": False, "error": str(e)}

    # =========================================
    # AD ACCOUNT MANAGEMENT
    # =========================================
    
    def get_user_ad_accounts(self, user_id: str = "me") -> Dict[str, Any]:
        """
        Get all ad accounts the user has access to.
        
        NOTE: Does NOT require ad_account_id to be set.
        """
        return self._request(
            "GET",
            f"{user_id}/adaccounts",
            params={
                "fields": "id,name,account_id,currency,timezone_name,"
                          "account_status,business,amount_spent,balance,spend_cap"
            }
        )
    
    def get_ad_account_info(self) -> Dict[str, Any]:
        """Get details of the current ad account."""
        self._require_ad_account()  # ✅ Validate
        return self._request(
            "GET",
            self.ad_account_id,
            params={
                "fields": "id,name,account_id,currency,timezone_name,"
                          "account_status,amount_spent,balance,spend_cap,"
                          "funding_source_details,business"
            }
        )
    
    def get_ad_account_pages(self) -> Dict[str, Any]:
        """Get pages associated with the ad account."""
        self._require_ad_account()  # ✅ Validate
        return self._request(
            "GET",
            f"{self.ad_account_id}/promote_pages",
            params={"fields": "id,name,category,picture"}
        )

    # =========================================
    # CAMPAIGN MANAGEMENT
    # =========================================
    def create_campaign(
        self,
        name: str,
        objective: str = "OUTCOME_ENGAGEMENT",
        status: str = "PAUSED",
        special_ad_categories: List[str] = None,
        is_adset_budget_sharing_enabled: bool = False,  # ✅ Add this parameter
    ) -> Dict[str, Any]:
        """
        Create an ad campaign.
        
        Objectives (ODAX):
        - OUTCOME_AWARENESS
        - OUTCOME_TRAFFIC
        - OUTCOME_ENGAGEMENT
        - OUTCOME_LEADS
        - OUTCOME_SALES
        - OUTCOME_APP_PROMOTION
        
        Args:
            name: Campaign name
            objective: Campaign objective
            status: ACTIVE or PAUSED
            special_ad_categories: List of special categories (HOUSING, EMPLOYMENT, CREDIT, etc.)
            is_adset_budget_sharing_enabled: Allow ad sets to share 20% budget for optimization
        """
        self._require_ad_account()
        
        data = {
            "name": name,
            "objective": objective,
            "status": status,
            "special_ad_categories": json.dumps(special_ad_categories or []),
            "is_adset_budget_sharing_enabled": str(is_adset_budget_sharing_enabled).lower(),  # ✅ Add this
        }
        
        return self._request("POST", f"{self.ad_account_id}/campaigns", data=data)
   
    def update_campaign(self, campaign_id: str, updates: Dict) -> Dict[str, Any]:
        """Update a campaign."""
        return self._request("POST", campaign_id, data=updates)
    
    def update_campaign_status(self, campaign_id: str, status: str) -> Dict[str, Any]:
        """Update campaign status (ACTIVE, PAUSED, DELETED)."""
        return self._request("POST", campaign_id, data={"status": status})

    # =========================================
    # AD SET MANAGEMENT
    # =========================================
    def create_adset(
        self,
        campaign_id: str,
        name: str,
        targeting: Dict[str, Any],
        budget_amount: int,
        budget_type: str = "daily",
        optimization_goal: str = "POST_ENGAGEMENT",
        billing_event: str = "IMPRESSIONS",
        bid_strategy: str = "LOWEST_COST_WITHOUT_CAP",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        status: str = "PAUSED",
    ) -> Dict[str, Any]:
        """
        Create an ad set with targeting and budget.
        """
        self._require_ad_account()
        
        # ✅ Ensure targeting has targeting_automation
        if "targeting_automation" not in targeting:
            targeting["targeting_automation"] = {
                "advantage_audience": 0  # Default to manual targeting
            }
        
        data = {
            "campaign_id": campaign_id,
            "name": name,
            "targeting": json.dumps(targeting),
            "optimization_goal": optimization_goal,
            "billing_event": billing_event,
            "bid_strategy": bid_strategy,
            "status": status,
        }
        
        # Budget
        if budget_type == "daily":
            data["daily_budget"] = budget_amount
        else:
            data["lifetime_budget"] = budget_amount
            if not end_time:
                raise ValueError("end_time is required for lifetime budget")
        
        # Schedule
        if start_time:
            # ✅ Use Unix timestamp format (Facebook prefers this)
            data["start_time"] = int(start_time.timestamp())
        if end_time:
            data["end_time"] = int(end_time.timestamp())
        
        return self._request("POST", f"{self.ad_account_id}/adsets", data=data)
    

    def update_adset_status(self, adset_id: str, status: str) -> Dict[str, Any]:
        """Update ad set status."""
        return self._request("POST", adset_id, data={"status": status})
    
    def search_interests(self, query: str, limit: int = 20) -> Dict[str, Any]:
        """Search for interest targeting options."""
        return self._request(
            "GET",
            "search",
            params={
                "type": "adinterest",
                "q": query,
                "limit": limit,
            }
        )
    
    def search_behaviors(self, query: str, limit: int = 20) -> Dict[str, Any]:
        """Search for behavior targeting options."""
        return self._request(
            "GET",
            "search",
            params={
                "type": "adTargetingCategory",
                "class": "behaviors",
                "q": query,
                "limit": limit,
            }
        )
    
    def get_targeting_browse(self) -> Dict[str, Any]:
        """Get available targeting categories."""
        self._require_ad_account()  # ✅ Validate
        return self._request("GET", f"{self.ad_account_id}/targetingbrowse")

    # =========================================
    # AD CREATIVE MANAGEMENT
    # =========================================
    
    def create_creative_from_post(
        self,
        name: str,
        page_id: str,
        post_id: str,
    ) -> Dict[str, Any]:
        """
        Create an ad creative from an existing page post.
        
        This is used for "boosting" an existing post.
        
        Args:
            name: Creative name
            page_id: Facebook Page ID
            post_id: Post ID to promote (format: page_id_post_id or just post_id)
        """
        self._require_ad_account()  # ✅ Validate
        
        # Ensure full post ID format
        if "_" not in str(post_id):
            full_post_id = f"{page_id}_{post_id}"
        else:
            full_post_id = post_id
        
        data = {
            "name": name,
            "object_story_id": full_post_id,
        }
        
        return self._request("POST", f"{self.ad_account_id}/adcreatives", data=data)
    
    def create_creative_with_link(
        self,
        name: str,
        page_id: str,
        message: str,
        link: str,
        image_hash: str = None,
        image_url: str = None,
        headline: str = None,
        description: str = None,
        call_to_action_type: str = "LEARN_MORE",
    ) -> Dict[str, Any]:
        """
        Create an ad creative with a link (new ad, not from existing post).
        
        Call to Action Types:
        - LEARN_MORE, SHOP_NOW, SIGN_UP, BOOK_NOW, CONTACT_US, DOWNLOAD,
        - GET_QUOTE, APPLY_NOW, SUBSCRIBE, GET_OFFER, etc.
        """
        self._require_ad_account()  # ✅ Validate
        
        link_data = {
            "link": link,
            "message": message,
        }
        
        if image_hash:
            link_data["image_hash"] = image_hash
        elif image_url:
            link_data["picture"] = image_url
        
        if headline:
            link_data["name"] = headline
        if description:
            link_data["description"] = description
        
        link_data["call_to_action"] = {
            "type": call_to_action_type,
            "value": {"link": link}
        }
        
        object_story_spec = {
            "page_id": page_id,
            "link_data": link_data,
        }
        
        data = {
            "name": name,
            "object_story_spec": json.dumps(object_story_spec),
        }
        
        return self._request("POST", f"{self.ad_account_id}/adcreatives", data=data)
    
    def upload_image(self, image_url: str = None, image_bytes: bytes = None) -> Dict[str, Any]:
        """
        Upload an image to the ad account.
        
        Returns image hash to use in creatives.
        """
        self._require_ad_account()  # ✅ Validate
        
        data = {}
        if image_url:
            data["url"] = image_url
        # For bytes, would need multipart upload (more complex)
        
        return self._request("POST", f"{self.ad_account_id}/adimages", data=data)

    # =========================================
    # AD MANAGEMENT
    # =========================================
    
    def create_ad(
        self,
        name: str,
        adset_id: str,
        creative_id: str,
        status: str = "PAUSED",
    ) -> Dict[str, Any]:
        """
        Create an ad linking an ad set and creative.
        """
        self._require_ad_account()  # ✅ Validate
        
        data = {
            "name": name,
            "adset_id": adset_id,
            "creative": json.dumps({"creative_id": creative_id}),
            "status": status,
        }
        
        return self._request("POST", f"{self.ad_account_id}/ads", data=data)
    
    def get_ads(self, adset_id: str = None, limit: int = 50) -> Dict[str, Any]:
        """Get all ads, optionally filtered by ad set."""
        self._require_ad_account()  # ✅ Validate
        
        params = {
            "fields": "id,name,status,creative{id,object_story_id},adset_id,created_time",
            "limit": limit,
        }
        if adset_id:
            params["filtering"] = json.dumps([{
                "field": "adset.id",
                "operator": "EQUAL",
                "value": adset_id,
            }])
        
        return self._request("GET", f"{self.ad_account_id}/ads", params=params)
    
    def update_ad_status(self, ad_id: str, status: str) -> Dict[str, Any]:
        """Update ad status (ACTIVE, PAUSED, DELETED)."""
        return self._request("POST", ad_id, data={"status": status})

    # =========================================
    # INSIGHTS / REPORTING
    # =========================================
    
    def get_campaign_insights(
        self,
        campaign_id: str,
        date_preset: str = "last_7d",
        fields: str = None,
    ) -> Dict[str, Any]:
        """
        Get performance insights for a campaign.
        
        Date presets: today, yesterday, this_week, last_week, this_month,
                      last_month, last_7d, last_14d, last_30d, last_90d
        """
        if not fields:
            fields = "impressions,reach,clicks,spend,cpc,cpm,ctr,actions,cost_per_action_type"
        
        params = {
            "fields": fields,
            "date_preset": date_preset,
        }
        return self._request("GET", f"{campaign_id}/insights", params=params)
    
    def get_adset_insights(
        self,
        adset_id: str,
        date_preset: str = "last_7d",
    ) -> Dict[str, Any]:
        """Get performance insights for an ad set."""
        params = {
            "fields": "impressions,reach,clicks,spend,cpc,cpm,ctr,actions",
            "date_preset": date_preset,
        }
        return self._request("GET", f"{adset_id}/insights", params=params)
    
    def get_ad_insights(
        self,
        ad_id: str,
        date_preset: str = "last_7d",
    ) -> Dict[str, Any]:
        """Get performance insights for an ad."""
        params = {
            "fields": "impressions,reach,clicks,spend,cpc,cpm,ctr,actions",
            "date_preset": date_preset,
        }
        return self._request("GET", f"{ad_id}/insights", params=params)

    
    # =========================================
    # ESTIMATE REACH
    # =========================================
    
    def estimate_reach(self, targeting: Dict[str, Any]) -> Dict[str, Any]:
        """
        Estimate the reach for given targeting criteria.
        
        Returns estimated daily reach and other metrics.
        """
        self._require_ad_account()  # ✅ Validate
        
        return self._request(
            "GET",
            f"{self.ad_account_id}/reachestimate",
            params={
                "targeting_spec": json.dumps(targeting),
                "optimize_for": "POST_ENGAGEMENT",
            }
        )


    # =========================================
    # CAMPAIGN MANAGEMENT
    # =========================================

    def create_campaign(
        self,
        name: str,
        objective: str = "OUTCOME_ENGAGEMENT",
        status: str = "PAUSED",
        special_ad_categories: List[str] = None,
        is_adset_budget_sharing_enabled: bool = False,
        daily_budget: int = None,
        lifetime_budget: int = None,
    ) -> Dict[str, Any]:
        """
        Create an ad campaign.
        
        Objectives (ODAX):
        - OUTCOME_AWARENESS
        - OUTCOME_TRAFFIC
        - OUTCOME_ENGAGEMENT
        - OUTCOME_LEADS
        - OUTCOME_SALES
        - OUTCOME_APP_PROMOTION
        
        Args:
            name: Campaign name
            objective: Campaign objective
            status: ACTIVE or PAUSED
            special_ad_categories: List of special categories (HOUSING, EMPLOYMENT, CREDIT, etc.)
            is_adset_budget_sharing_enabled: Allow ad sets to share 20% budget for optimization
            daily_budget: Campaign daily budget in cents (for CBO - Campaign Budget Optimization)
            lifetime_budget: Campaign lifetime budget in cents (for CBO)
        """
        self._require_ad_account()
        
        data = {
            "name": name,
            "objective": objective,
            "status": status,
            "special_ad_categories": json.dumps(special_ad_categories or []),
            "is_adset_budget_sharing_enabled": str(is_adset_budget_sharing_enabled).lower(),
        }
        
        # Campaign Budget Optimization (CBO) - budget at campaign level
        if daily_budget:
            data["daily_budget"] = daily_budget
        if lifetime_budget:
            data["lifetime_budget"] = lifetime_budget
        
        return self._request("POST", f"{self.ad_account_id}/campaigns", data=data)


    # =========================================
    # BOOST POST (SIMPLIFIED FLOW)
    # =========================================

    def boost_post(
        self,
        page_id: str,
        post_id: str,
        budget_amount: int,
        duration_days: int = 7,
        targeting: Dict[str, Any] = None,
        optimization_goal: str = "POST_ENGAGEMENT",
        campaign_name: str = None,
        is_adset_budget_sharing_enabled: bool = False,
        advantage_audience: bool = False, 
    ) -> Dict[str, Any]:
        """
        Simplified method to boost an existing page post.
        """
        self._require_ad_account()
        
        log_tag = "[FacebookAdsService][boost_post]"
        
        # Default targeting if none provided
        if not targeting:
            targeting = self.build_targeting(
                countries=["US"],
                age_min=18,
                age_max=65,
            )
        else:
            # ✅ Ensure targeting_automation is set even if targeting was provided
            if "targeting_automation" not in targeting:
                targeting["targeting_automation"] = {
                    "advantage_audience": 1 if advantage_audience else 0
                }
            
        # Calculate dates
        start_time = datetime.now(timezone.utc)
        end_time = start_time + timedelta(days=duration_days)
        
        # Generate names
        short_id = str(post_id)[-8:]
        campaign_name = campaign_name or f"Boost Post {short_id}"
        
        result = {
            "success": False,
            "campaign_id": None,
            "adset_id": None,
            "creative_id": None,
            "ad_id": None,
            "errors": [],
        }
        
        try:
            # 1. Create Campaign
            Log.info(f"{log_tag} Creating campaign...")
            campaign_result = self.create_campaign(
                name=campaign_name,
                objective="OUTCOME_ENGAGEMENT",
                status="PAUSED",
                is_adset_budget_sharing_enabled=is_adset_budget_sharing_enabled,
            )
            
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
            
            # 2. Create Ad Set
            Log.info(f"{log_tag} Creating ad set...")
            Log.info(f"{log_tag} Targeting: {targeting}")  # ✅ Debug log
            
            adset_result = self.create_adset(
                campaign_id=campaign_id,
                name=f"Boost AdSet {short_id}",
                targeting=targeting,
                budget_amount=budget_amount,
                budget_type="lifetime",
                optimization_goal=optimization_goal,
                billing_event="IMPRESSIONS",
                start_time=start_time,
                end_time=end_time,
                status="PAUSED",
            )
            
            if not adset_result.get("success"):
                result["errors"].append({
                    "step": "adset",
                    "error": adset_result.get("error_message", adset_result.get("error")),
                    "details": adset_result.get("error"),
                })
                # ✅ Cleanup: try to delete campaign, but don't fail if it doesn't work
                self._cleanup_campaign(campaign_id)
                return result
            
            adset_id = adset_result["data"]["id"]
            result["adset_id"] = adset_id
            Log.info(f"{log_tag} Ad Set created: {adset_id}")
            
            # 3. Create Creative from existing post
            Log.info(f"{log_tag} Creating creative from post...")
            creative_result = self.create_creative_from_post(
                name=f"Boost Creative {short_id}",
                page_id=page_id,
                post_id=post_id,
            )
            
            if not creative_result.get("success"):
                result["errors"].append({
                    "step": "creative",
                    "error": creative_result.get("error_message", creative_result.get("error")),
                    "details": creative_result.get("error"),
                })
                self._cleanup_campaign(campaign_id)
                return result
            
            creative_id = creative_result["data"]["id"]
            result["creative_id"] = creative_id
            Log.info(f"{log_tag} Creative created: {creative_id}")
            
            # 4. Create Ad
            Log.info(f"{log_tag} Creating ad...")
            ad_result = self.create_ad(
                name=f"Boost Ad {short_id}",
                adset_id=adset_id,
                creative_id=creative_id,
                status="PAUSED",
            )
            
            if not ad_result.get("success"):
                result["errors"].append({
                    "step": "ad",
                    "error": ad_result.get("error_message", ad_result.get("error")),
                    "details": ad_result.get("error"),
                })
                self._cleanup_campaign(campaign_id)
                return result
            
            ad_id = ad_result["data"]["id"]
            result["ad_id"] = ad_id
            Log.info(f"{log_tag} Ad created: {ad_id}")
            
            # 5. Activate the campaign
            Log.info(f"{log_tag} Activating campaign...")
            activate_result = self.update_campaign_status(campaign_id, "ACTIVE")
            
            if not activate_result.get("success"):
                result["errors"].append({
                    "step": "activate",
                    "error": activate_result.get("error_message", activate_result.get("error")),
                    "warning": "Campaign created but failed to activate. Please activate manually.",
                })
                # Don't delete - let user activate manually
                # Still mark as success since campaign was created
            
            result["success"] = True
            Log.info(f"{log_tag} Post boosted successfully!")
            
            return result
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            result["errors"].append({
                "step": "unknown",
                "error": str(e),
            })
            return result

    # =========================================
    # TARGETING HELPERS
    # =========================================
    def build_targeting(
        self,
        countries: List[str] = None,
        regions: List[Dict] = None,
        cities: List[Dict] = None,
        age_min: int = 18,
        age_max: int = 65,
        genders: List[int] = None,
        interests: List[Dict] = None,
        behaviors: List[Dict] = None,
        custom_audiences: List[str] = None,
        excluded_custom_audiences: List[str] = None,
        locales: List[int] = None,
        publisher_platforms: List[str] = None,
        facebook_positions: List[str] = None,
        instagram_positions: List[str] = None,
        advantage_audience: bool = False,  # ✅ NEW: Advantage+ audience
    ) -> Dict[str, Any]:
        """
        Build a targeting spec for ad sets.
        
        Args:
            countries: List of country codes ["US", "GB", "GH"]
            regions: List of region objects [{"key": "3847"}]
            cities: List of city objects [{"key": "2430536", "radius": 10, "distance_unit": "mile"}]
            age_min: Minimum age (13-65)
            age_max: Maximum age (13-65)
            genders: [1] for male, [2] for female, None for all
            interests: List of interest objects [{"id": "123", "name": "Technology"}]
            behaviors: List of behavior objects
            custom_audiences: List of custom audience IDs
            excluded_custom_audiences: Audiences to exclude
            locales: Language locale IDs
            publisher_platforms: ["facebook", "instagram", "audience_network", "messenger"]
            facebook_positions: ["feed", "right_hand_column", "instant_article", etc.]
            instagram_positions: ["stream", "story", "explore", "reels"]
            advantage_audience: Enable Advantage+ audience (Meta's AI targeting)
        """
        targeting = {
            "age_min": age_min,
            "age_max": age_max,
        }
        
        # Geo targeting (required - must have at least countries)
        geo_locations = {}
        if countries:
            geo_locations["countries"] = countries
        if regions:
            geo_locations["regions"] = regions
        if cities:
            geo_locations["cities"] = cities
        
        # Default to broad targeting if no geo specified
        if not geo_locations:
            geo_locations["countries"] = ["US"]
        
        targeting["geo_locations"] = geo_locations
        
        # Demographics
        if genders:
            targeting["genders"] = genders
        
        # Interests and behaviors - only add if valid
        flexible_spec = []
        
        if interests:
            valid_interests = [
                i for i in interests 
                if isinstance(i, dict) 
                and i.get("id") 
                and str(i.get("id")).isdigit()
                and len(str(i.get("id"))) > 5
            ]
            if valid_interests:
                flexible_spec.append({"interests": valid_interests})
        
        if behaviors:
            valid_behaviors = [
                b for b in behaviors 
                if isinstance(b, dict) 
                and b.get("id") 
                and str(b.get("id")).isdigit()
            ]
            if valid_behaviors:
                flexible_spec.append({"behaviors": valid_behaviors})
        
        if flexible_spec:
            targeting["flexible_spec"] = flexible_spec
        
        # Custom audiences
        if custom_audiences:
            targeting["custom_audiences"] = [{"id": ca_id} for ca_id in custom_audiences]
        if excluded_custom_audiences:
            targeting["excluded_custom_audiences"] = [{"id": ca_id} for ca_id in excluded_custom_audiences]
        
        # Language
        if locales:
            targeting["locales"] = locales
        
        # Placement
        if publisher_platforms:
            targeting["publisher_platforms"] = publisher_platforms
        if facebook_positions:
            targeting["facebook_positions"] = facebook_positions
        if instagram_positions:
            targeting["instagram_positions"] = instagram_positions
        
        # ✅ NEW: Advantage+ Audience (Meta's AI-powered targeting)
        # 0 = disabled (use manual targeting)
        # 1 = enabled (Meta expands your audience using AI)
        targeting["targeting_automation"] = {
            "advantage_audience": 1 if advantage_audience else 0
        }
        
        return targeting
    
    def _cleanup_campaign(self, campaign_id: str):
        """
        Try to delete a campaign during error cleanup.
        Logs but doesn't raise on failure.
        """
        log_tag = "[FacebookAdsService][_cleanup_campaign]"
        try:
            Log.info(f"{log_tag} Cleaning up campaign {campaign_id}...")
            delete_result = self.update_campaign_status(campaign_id, "DELETED")
            if delete_result.get("success"):
                Log.info(f"{log_tag} Campaign {campaign_id} deleted successfully")
            else:
                Log.info(f"{log_tag} Failed to delete campaign {campaign_id}: {delete_result.get('error')}")
        except Exception as e:
            Log.info(f"{log_tag} Exception during cleanup (ignored): {e}")


    def _normalize_ad_account_id(ad_account_id: str) -> str:
        """
        Ensure ad account ID is numeric (no act_ prefix).
        Used ONLY for reach estimate endpoint.
        """
        if not ad_account_id:
            return ad_account_id
        return ad_account_id.replace("act_", "", 1)

    # --------------------------------------------------
    # ✅ REACH ESTIMATE
    # --------------------------------------------------
    def get_reach_estimate(self, targeting: dict):
        """
        Calls:
        GET /act_<AD_ACCOUNT_ID>/reachestimate
        """

        params = {
            "targeting_spec": json.dumps(targeting),
        }

        return self._request(
            "GET",
            f"act_{self.ad_account_id}/reachestimate",
            params=params,
        )


    # =========================================
    # FACEBOOK ADS SERVICE — REACH ESTIMATE
    # =========================================
    def get_reach_estimate(self, targeting: dict) -> dict:
        """
        Calls:
        GET /act_<AD_ACCOUNT_ID>/reachestimate
        """

        try:
            # Facebook REQUIRED params for reach estimate
            params = {
                "targeting_spec": json.dumps(targeting),
                "objective": "POST_ENGAGEMENT",
                "optimization_goal": "POST_ENGAGEMENT",
                "billing_event": "IMPRESSIONS",
            }

            endpoint = f"/{self.ad_account_id}/reachestimate"

            resp = self._request(
                method="GET",
                endpoint=endpoint,
                params=params,
            )

            data = resp.get("data", [{}])[0] if isinstance(resp.get("data"), list) else {}

            return {
                "success": True,
                "data": {
                    "users_lower_bound": data.get("users_lower_bound"),
                    "users_upper_bound": data.get("users_upper_bound"),
                },
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }

