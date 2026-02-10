# app/services/auth/social_auth_service.py

import os
import time
import secrets
import requests
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlencode

from ...utils.logger import Log


class SocialAuthService:
    """
    Service for handling OAuth flows with various social providers.
    """
    
    def __init__(self, provider: str):
        self.provider = provider.lower()
        self._load_config()
    
    def _load_config(self):
        """Load provider-specific configuration from environment."""
        provider_upper = self.provider.upper()
        
        self.client_id = os.getenv(f"{provider_upper}_CLIENT_ID")
        self.client_secret = os.getenv(f"{provider_upper}_CLIENT_SECRET")
        self.redirect_uri = os.getenv(f"{provider_upper}_REDIRECT_URI")
        
        # Provider-specific endpoints
        self.endpoints = self._get_endpoints()
    
    def _get_endpoints(self) -> Dict[str, str]:
        """Get OAuth endpoints for the provider."""
        endpoints = {
            "facebook": {
                "authorize": "https://www.facebook.com/v20.0/dialog/oauth",
                "token": "https://graph.facebook.com/v20.0/oauth/access_token",
                "userinfo": "https://graph.facebook.com/v20.0/me",
                "userinfo_fields": "id,name,email,picture.width(200).height(200)",
            },
            "google": {
                "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
                "token": "https://oauth2.googleapis.com/token",
                "userinfo": "https://www.googleapis.com/oauth2/v2/userinfo",
            },
            "apple": {
                "authorize": "https://appleid.apple.com/auth/authorize",
                "token": "https://appleid.apple.com/auth/token",
                # Apple returns user info in the ID token
            },
            "twitter": {  # X
                "authorize": "https://twitter.com/i/oauth2/authorize",
                "token": "https://api.twitter.com/2/oauth2/token",
                "userinfo": "https://api.twitter.com/2/users/me",
            },
            "linkedin": {
                "authorize": "https://www.linkedin.com/oauth/v2/authorization",
                "token": "https://www.linkedin.com/oauth/v2/accessToken",
                "userinfo": "https://api.linkedin.com/v2/userinfo",
            },
            "github": {
                "authorize": "https://github.com/login/oauth/authorize",
                "token": "https://github.com/login/oauth/access_token",
                "userinfo": "https://api.github.com/user",
                "emails": "https://api.github.com/user/emails",
            },
            "microsoft": {
                "authorize": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
                "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                "userinfo": "https://graph.microsoft.com/v1.0/me",
            },
        }
        
        return endpoints.get(self.provider, {})
    
    def get_default_scopes(self) -> list:
        """Get default scopes for the provider."""
        scopes = {
            "facebook": ["email", "public_profile"],
            "google": ["openid", "email", "profile"],
            "apple": ["name", "email"],
            "twitter": ["tweet.read", "users.read", "offline.access"],
            "linkedin": ["openid", "profile", "email"],
            "github": ["read:user", "user:email"],
            "microsoft": ["openid", "email", "profile", "User.Read"],
        }
        
        return scopes.get(self.provider, [])
    
    def generate_state(self) -> str:
        """Generate a random state for CSRF protection."""
        return secrets.token_urlsafe(32)
    
    def get_authorization_url(
        self,
        state: str,
        scopes: list = None,
        extra_params: dict = None,
    ) -> str:
        """
        Generate the authorization URL for the OAuth flow.
        
        Args:
            state: CSRF state token
            scopes: OAuth scopes (defaults to provider defaults)
            extra_params: Additional provider-specific params
        """
        if not self.endpoints.get("authorize"):
            raise ValueError(f"Unsupported provider: {self.provider}")
        
        scopes = scopes or self.get_default_scopes()
        
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "response_type": "code",
        }
        
        # Provider-specific scope formatting
        if self.provider == "facebook":
            params["scope"] = ",".join(scopes)
        elif self.provider in ["twitter", "linkedin"]:
            params["scope"] = " ".join(scopes)
        else:
            params["scope"] = " ".join(scopes)
        
        # Provider-specific params
        if self.provider == "google":
            params["access_type"] = "offline"
            params["prompt"] = "consent"
        elif self.provider == "apple":
            params["response_mode"] = "form_post"
        elif self.provider == "twitter":
            params["code_challenge"] = self._generate_pkce_challenge()
            params["code_challenge_method"] = "S256"
        
        if extra_params:
            params.update(extra_params)
        
        return f"{self.endpoints['authorize']}?{urlencode(params)}"
    
    def exchange_code(
        self,
        code: str,
        code_verifier: str = None,
    ) -> Dict[str, Any]:
        """
        Exchange authorization code for access token.
        
        Returns:
            {
                "success": bool,
                "access_token": str,
                "refresh_token": str (optional),
                "expires_in": int,
                "token_type": str,
                "error": str (on failure),
            }
        """
        log_tag = f"[SocialAuthService][{self.provider}][exchange_code]"
        
        if not self.endpoints.get("token"):
            return {"success": False, "error": f"Unsupported provider: {self.provider}"}
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        
        # PKCE for Twitter
        if self.provider == "twitter" and code_verifier:
            data["code_verifier"] = code_verifier
        
        headers = {"Accept": "application/json"}
        
        # GitHub needs special header
        if self.provider == "github":
            headers["Accept"] = "application/json"
        
        try:
            start_time = time.time()
            
            response = requests.post(
                self.endpoints["token"],
                data=data,
                headers=headers,
                timeout=30,
            )
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Token exchange completed in {duration:.2f}s status={response.status_code}")
            
            if response.status_code != 200:
                Log.error(f"{log_tag} Token exchange failed: {response.text}")
                return {
                    "success": False,
                    "error": response.json().get("error_description", response.text),
                }
            
            token_data = response.json()
            
            return {
                "success": True,
                "access_token": token_data.get("access_token"),
                "refresh_token": token_data.get("refresh_token"),
                "expires_in": token_data.get("expires_in"),
                "token_type": token_data.get("token_type", "Bearer"),
                "id_token": token_data.get("id_token"),  # For Apple/Google
            }
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def get_user_info(self, access_token: str) -> Dict[str, Any]:
        """
        Get user profile from the provider.
        
        Returns:
            {
                "success": bool,
                "provider_user_id": str,
                "email": str (optional),
                "name": str (optional),
                "first_name": str (optional),
                "last_name": str (optional),
                "profile_picture": str (optional),
                "raw_profile": dict,
                "error": str (on failure),
            }
        """
        log_tag = f"[SocialAuthService][{self.provider}][get_user_info]"
        
        try:
            start_time = time.time()
            
            headers = {"Authorization": f"Bearer {access_token}"}
            params = {}
            
            # Provider-specific handling
            if self.provider == "facebook":
                params["fields"] = self.endpoints.get("userinfo_fields", "id,name,email")
            
            response = requests.get(
                self.endpoints["userinfo"],
                headers=headers,
                params=params,
                timeout=30,
            )
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} User info fetched in {duration:.2f}s status={response.status_code}")
            
            if response.status_code != 200:
                Log.error(f"{log_tag} Failed to get user info: {response.text}")
                return {"success": False, "error": response.text}
            
            profile = response.json()
            
            # Normalize profile data
            normalized = self._normalize_profile(profile, access_token)
            normalized["success"] = True
            normalized["raw_profile"] = profile
            
            return normalized
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def _normalize_profile(self, profile: dict, access_token: str = None) -> dict:
        """Normalize profile data from different providers."""
        
        if self.provider == "facebook":
            picture = profile.get("picture", {}).get("data", {}).get("url")
            return {
                "provider_user_id": profile.get("id"),
                "email": profile.get("email"),
                "name": profile.get("name"),
                "first_name": profile.get("first_name"),
                "last_name": profile.get("last_name"),
                "profile_picture": picture,
            }
        
        elif self.provider == "google":
            return {
                "provider_user_id": profile.get("id"),
                "email": profile.get("email"),
                "name": profile.get("name"),
                "first_name": profile.get("given_name"),
                "last_name": profile.get("family_name"),
                "profile_picture": profile.get("picture"),
                "email_verified": profile.get("verified_email", False),
            }
        
        elif self.provider == "apple":
            # Apple provides user info in ID token, handled separately
            return {
                "provider_user_id": profile.get("sub"),
                "email": profile.get("email"),
                "name": profile.get("name"),
                "email_verified": profile.get("email_verified", False),
            }
        
        elif self.provider == "twitter":
            data = profile.get("data", {})
            return {
                "provider_user_id": data.get("id"),
                "name": data.get("name"),
                "username": data.get("username"),
                "profile_picture": data.get("profile_image_url"),
            }
        
        elif self.provider == "linkedin":
            return {
                "provider_user_id": profile.get("sub"),
                "email": profile.get("email"),
                "name": profile.get("name"),
                "first_name": profile.get("given_name"),
                "last_name": profile.get("family_name"),
                "profile_picture": profile.get("picture"),
                "email_verified": profile.get("email_verified", False),
            }
        
        elif self.provider == "github":
            # GitHub may not return email in profile, need separate call
            email = profile.get("email")
            if not email and access_token:
                email = self._get_github_email(access_token)
            
            name = profile.get("name") or profile.get("login")
            name_parts = name.split(" ", 1) if name else ["", ""]
            
            return {
                "provider_user_id": str(profile.get("id")),
                "email": email,
                "name": name,
                "first_name": name_parts[0],
                "last_name": name_parts[1] if len(name_parts) > 1 else "",
                "username": profile.get("login"),
                "profile_picture": profile.get("avatar_url"),
            }
        
        elif self.provider == "microsoft":
            return {
                "provider_user_id": profile.get("id"),
                "email": profile.get("mail") or profile.get("userPrincipalName"),
                "name": profile.get("displayName"),
                "first_name": profile.get("givenName"),
                "last_name": profile.get("surname"),
            }
        
        return {"provider_user_id": profile.get("id")}
    
    def _get_github_email(self, access_token: str) -> Optional[str]:
        """Get primary email from GitHub (separate endpoint)."""
        try:
            response = requests.get(
                self.endpoints.get("emails", "https://api.github.com/user/emails"),
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            
            if response.status_code == 200:
                emails = response.json()
                # Find primary email
                for email_obj in emails:
                    if email_obj.get("primary") and email_obj.get("verified"):
                        return email_obj.get("email")
                # Fallback to first verified
                for email_obj in emails:
                    if email_obj.get("verified"):
                        return email_obj.get("email")
        except Exception as e:
            Log.error(f"[SocialAuthService][github] Failed to get email: {e}")
        
        return None
    
    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh an access token."""
        log_tag = f"[SocialAuthService][{self.provider}][refresh_token]"
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        
        try:
            response = requests.post(
                self.endpoints["token"],
                data=data,
                timeout=30,
            )
            
            if response.status_code != 200:
                Log.error(f"{log_tag} Token refresh failed: {response.text}")
                return {"success": False, "error": response.text}
            
            token_data = response.json()
            
            return {
                "success": True,
                "access_token": token_data.get("access_token"),
                "refresh_token": token_data.get("refresh_token", refresh_token),
                "expires_in": token_data.get("expires_in"),
            }
        
        except Exception as e:
            Log.error(f"{log_tag} Exception: {e}")
            return {"success": False, "error": str(e)}
    
    def _generate_pkce_challenge(self) -> str:
        """Generate PKCE code challenge for Twitter/X."""
        import hashlib
        import base64
        
        code_verifier = secrets.token_urlsafe(32)
        code_challenge = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(code_challenge).decode().rstrip("=")
        
        return code_challenge