# app/services/social/providers/linkedin_provider.py

from __future__ import annotations

from .base import ProviderResult, SocialProviderBase
from ....models.social.social_account import SocialAccount


class LinkedInProvider(SocialProviderBase):
    platform = "linkedin"

    def fetch_range(
        self,
        *,
        business_id: str,
        user__id: str,
        destination_id: str,
        since_ymd: str,
        until_ymd: str,
    ) -> ProviderResult:
        
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform="linkedin",
            destination_id=destination_id,
        )
        if not acct:
            return ProviderResult(self.platform, destination_id, None, {}, [], {"error": "LI_NOT_CONNECTED"})

        # Without Community Management / Marketing Developer Platform approvals,
        # you will get "scope not authorized" or "ACCESS_DENIED".
        return ProviderResult(
            platform=self.platform,
            destination_id=destination_id,
            destination_name=acct.get("destination_name"),
            totals={
                "followers": 0,
                "new_followers": 0,
                "posts": 0,
                "impressions": 0,
                "engagements": 0,
                "likes": 0,
                "comments": 0,
                "shares": 0,
                "reactions": 0,
            },
            timeline=[],
            debug={
                "warning": "LinkedIn org analytics requires approved products/scopes. Your app currently only has OpenID Connect.",
                "hint": "Create a separate LinkedIn app to request Community Management API if dashboard says it must be the only product.",
            },
        )