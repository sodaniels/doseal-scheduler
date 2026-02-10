# app/services/auth/facebook_business_auth_service.py

import os
import time
import secrets
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from urllib.parse import urlencode

from ...utils.logger import Log


class FacebookBusinessAuthService:
    """
    Service for Facebook Business Login (Login for Business).
    
    This flow provides access to:
    - Facebook Pages
    - Instagram Business Accounts
    - Facebook Ads / Marketing API
    - Business Manager
    
    Documentation: https://developers.facebook.com/docs/facebook-login/facebook-login-for-business
    """
    
    API_VERSION = "v20.0"
    BASE_URL = f"https://graph.facebook.com/{API_VERSION}"
    
    # OAuth endpoints
    AUTHORIZE_URL = "https://www.facebook.com/v20.0/dialog/oauth"
    TOKEN_URL = f"https://graph.facebook.com/{API_VERSION}/oauth/access_token"
    
    # Permission categories
    PERMISSIONS_PAGES = [
        "pages_show_list",
        "pages_read_engagement",
        "pages_manage_posts",
        "pages_manage_metadata",
        "pages_read_user_content",
    ]
    
    PERMISSIONS_INSTAGRAM = [
        "instagram_basic",
        "instagram_content_publish",
        "instagram_manage_comments",
        "instagram_manage_insights",
    ]
    
    PERMISSIONS_ADS = [
        "ads_management",
        "ads_read",
        "business_management",
    ]
    
    PERMISSIONS_INSIGHTS = [
        "read_insights",
    ]
    
    def __init__(self):
        self.client_id = os.getenv("FACEBOOK_APP_ID")
        self.client_secret = os.getenv("FACEBOOK_APP_SECRET")
        self.redirect_uri = os.getenv("FACEBOOK_BUSINESS_REDIRECT_URI")
    
    def generate_state(self) -> str:
        """Generate a random state for CSRF protection."""
        return secrets.token_urlsafe(32)
    
    def get_authorization_url(
        self,
        state: str,
        scopes: List[str] = None,
        config_id: str = None,
        extras: Dict[str, str] = None,
    ) -> str:
        """
        Generate the Facebook Business Login authorization URL.
        
        Args:
            state: CSRF state token
            scopes: List of permissions to request
            config_id: Facebook Login Configuration ID (for Login for Business)
            extras: Additional parameters
        
        Returns:
            Authorization URL to redirect user to
        """
        if not scopes:
            # Default: Pages + Instagram + Insights
            scopes = (
                self.PERMISSIONS_PAGES +
                self.PERMISSIONS_INSTAGRAM +
                self.PERMISSIONS_INSIGHTS
            )
        
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "response_type": "code",
            "scope": ",".join(scopes),
        }
        
        # For Login for Business, use config_id
        if config_id:
            params["config_id"] = config_id
        
        # Add extras
        if extras:
            params.update(extras)
        
        return f"{self.AUTHORIZE_URL}?{urlencode(params)}"
    
    def get_authorization_url_with_ads(
        self,
        state: str,
        config_id: str = None,
    ) -> str:
        """
        Get authorization URL with all permissions including Ads.
        """
        scopes = (
            self.PERMISSIONS_PAGES +
            self.PERMISSIONS_INSTAGRAM +
            self.PERMISSIONS_ADS +
            self.PERMISSIONS_INSIGHTS
        )
        
        return self.get_authorization_url(
            state=state,
            scopes=scopes,
            config_id=config_id,
        )
    
    def exchange_code(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access token.
        
        Returns short-lived user access token.
        """
        log_tag = "[FacebookBusinessAuthService][exchange_code]"
        
        params = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "code": code,
        }
        
        try:
            start_time = time.time()
            
            response = requests.get(self.TOKEN_URL, params=params, timeout=30)
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Token exchange completed in {duration:.2f}s status={response.status_code}")
            
            if response.status_code != 200:
                error_data = response.json()
                Log.error(f"{log_tag} Token exchange failed: {error_data}")
                return {
                    "success": False,
                    "error": error_data.get("error", {}).get("message", "Unknown error"),
                    "error_code": error_data.get("error", {}).get("code"),
                }
            
            data = response.json()
            
            return {
                "success": True,
                "access_token": data.get("access_token"),
                "token_type": data.get("token_type", "bearer"),
                "expires_in": data.get("expires_in"),
            }
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def get_long_lived_token(self, short_lived_token: str) -> Dict[str, Any]:
        """
        Exchange short-lived token for long-lived token.
        
        Short-lived: ~1-2 hours
        Long-lived: ~60 days
        """
        log_tag = "[FacebookBusinessAuthService][get_long_lived_token]"
        
        params = {
            "grant_type": "fb_exchange_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "fb_exchange_token": short_lived_token,
        }
        
        try:
            start_time = time.time()
            
            response = requests.get(self.TOKEN_URL, params=params, timeout=30)
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Long-lived token exchange completed in {duration:.2f}s")
            
            if response.status_code != 200:
                error_data = response.json()
                Log.error(f"{log_tag} Failed: {error_data}")
                return {
                    "success": False,
                    "error": error_data.get("error", {}).get("message", "Unknown error"),
                }
            
            data = response.json()
            
            return {
                "success": True,
                "access_token": data.get("access_token"),
                "token_type": data.get("token_type", "bearer"),
                "expires_in": data.get("expires_in"),  # ~5184000 (60 days)
            }
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Get the authenticated user's info.
        """
        log_tag = "[FacebookBusinessAuthService][get_user_info]"
        
        try:
            response = requests.get(
                f"{self.BASE_URL}/me",
                params={
                    "access_token": access_token,
                    "fields": "id,name,email,picture.width(200).height(200)",
                },
                timeout=30,
            )
            
            if response.status_code != 200:
                error_data = response.json()
                return {
                    "success": False,
                    "error": error_data.get("error", {}).get("message", "Unknown error"),
                }
            
            data = response.json()
            
            return {
                "success": True,
                "user_id": data.get("id"),
                "name": data.get("name"),
                "email": data.get("email"),
                "profile_picture": data.get("picture", {}).get("data", {}).get("url"),
            }
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def get_user_pages(self, access_token: str) -> Dict[str, Any]:
        """
        Get Facebook Pages the user manages.
        
        Returns pages with their page access tokens.
        """
        log_tag = "[FacebookBusinessAuthService][get_user_pages]"
        
        try:
            start_time = time.time()
            
            response = requests.get(
                f"{self.BASE_URL}/me/accounts",
                params={
                    "access_token": access_token,
                    "fields": "id,name,category,access_token,picture.width(200).height(200),instagram_business_account{id,username,profile_picture_url,followers_count},tasks",
                },
                timeout=30,
            )
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Pages fetch completed in {duration:.2f}s")
            
            if response.status_code != 200:
                error_data = response.json()
                Log.error(f"{log_tag} Failed: {error_data}")
                return {
                    "success": False,
                    "error": error_data.get("error", {}).get("message", "Unknown error"),
                }
            
            data = response.json()
            pages = data.get("data", [])
            
            # Format pages
            formatted_pages = []
            for page in pages:
                instagram = page.get("instagram_business_account", {})
                
                formatted_pages.append({
                    "page_id": page.get("id"),
                    "page_name": page.get("name"),
                    "category": page.get("category"),
                    "page_access_token": page.get("access_token"),
                    "picture": page.get("picture", {}).get("data", {}).get("url"),
                    "tasks": page.get("tasks", []),
                    "instagram": {
                        "instagram_id": instagram.get("id"),
                        "username": instagram.get("username"),
                        "profile_picture": instagram.get("profile_picture_url"),
                        "followers_count": instagram.get("followers_count"),
                    } if instagram else None,
                })
            
            return {
                "success": True,
                "pages": formatted_pages,
                "count": len(formatted_pages),
            }
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def get_user_ad_accounts(self, access_token: str) -> Dict[str, Any]:
        """
        Get Ad Accounts the user has access to.
        """
        log_tag = "[FacebookBusinessAuthService][get_user_ad_accounts]"
        
        try:
            start_time = time.time()
            
            response = requests.get(
                f"{self.BASE_URL}/me/adaccounts",
                params={
                    "access_token": access_token,
                    "fields": "id,account_id,name,currency,timezone_name,account_status,amount_spent,balance,business",
                },
                timeout=30,
            )
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Ad accounts fetch completed in {duration:.2f}s")
            
            if response.status_code != 200:
                error_data = response.json()
                Log.error(f"{log_tag} Failed: {error_data}")
                return {
                    "success": False,
                    "error": error_data.get("error", {}).get("message", "Unknown error"),
                }
            
            data = response.json()
            
            return {
                "success": True,
                "ad_accounts": data.get("data", []),
                "count": len(data.get("data", [])),
            }
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def get_user_businesses(self, access_token: str) -> Dict[str, Any]:
        """
        Get Business Manager accounts the user has access to.
        """
        log_tag = "[FacebookBusinessAuthService][get_user_businesses]"
        
        try:
            response = requests.get(
                f"{self.BASE_URL}/me/businesses",
                params={
                    "access_token": access_token,
                    "fields": "id,name,profile_picture_uri,verification_status",
                },
                timeout=30,
            )
            
            if response.status_code != 200:
                error_data = response.json()
                return {
                    "success": False,
                    "error": error_data.get("error", {}).get("message", "Unknown error"),
                }
            
            data = response.json()
            
            return {
                "success": True,
                "businesses": data.get("data", []),
                "count": len(data.get("data", [])),
            }
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def get_page_long_lived_token(
        self,
        user_access_token: str,
        page_id: str,
    ) -> Dict[str, Any]:
        """
        Get a long-lived page access token.
        
        Page tokens from long-lived user tokens are also long-lived (never expire).
        """
        log_tag = "[FacebookBusinessAuthService][get_page_long_lived_token]"
        
        try:
            # First, get the page with its token
            response = requests.get(
                f"{self.BASE_URL}/{page_id}",
                params={
                    "access_token": user_access_token,
                    "fields": "access_token,name",
                },
                timeout=30,
            )
            
            if response.status_code != 200:
                error_data = response.json()
                return {
                    "success": False,
                    "error": error_data.get("error", {}).get("message", "Unknown error"),
                }
            
            data = response.json()
            
            return {
                "success": True,
                "page_id": page_id,
                "page_name": data.get("name"),
                "page_access_token": data.get("access_token"),
                # Page tokens from long-lived user tokens don't expire
                "expires_in": None,
            }
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def debug_token(self, access_token: str) -> Dict[str, Any]:
        """
        Debug an access token to get info about it.
        """
        log_tag = "[FacebookBusinessAuthService][debug_token]"
        
        try:
            response = requests.get(
                f"{self.BASE_URL}/debug_token",
                params={
                    "input_token": access_token,
                    "access_token": f"{self.client_id}|{self.client_secret}",
                },
                timeout=30,
            )
            
            if response.status_code != 200:
                error_data = response.json()
                return {
                    "success": False,
                    "error": error_data.get("error", {}).get("message", "Unknown error"),
                }
            
            data = response.json().get("data", {})
            
            return {
                "success": True,
                "app_id": data.get("app_id"),
                "user_id": data.get("user_id"),
                "type": data.get("type"),
                "is_valid": data.get("is_valid"),
                "scopes": data.get("scopes", []),
                "expires_at": data.get("expires_at"),
                "issued_at": data.get("issued_at"),
            }
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def get_granted_scopes(self, access_token: str) -> Dict[str, Any]:
        """
        Get the permissions that were granted by the user.
        """
        log_tag = "[FacebookBusinessAuthService][get_granted_scopes]"
        
        try:
            response = requests.get(
                f"{self.BASE_URL}/me/permissions",
                params={"access_token": access_token},
                timeout=30,
            )
            
            if response.status_code != 200:
                error_data = response.json()
                return {
                    "success": False,
                    "error": error_data.get("error", {}).get("message", "Unknown error"),
                }
            
            data = response.json()
            permissions = data.get("data", [])
            
            granted = [p["permission"] for p in permissions if p.get("status") == "granted"]
            declined = [p["permission"] for p in permissions if p.get("status") == "declined"]
            
            return {
                "success": True,
                "granted": granted,
                "declined": declined,
            }
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return {"success": False, "error": str(e)}