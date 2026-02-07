# app/services/social/providers/pinterest_provider.py

from __future__ import annotations

from typing import Optional

from .base import ProviderResult, SocialProviderBase
from ....models.social.social_account import SocialAccount
from ....models.social.social_daily_snapshot import SocialDailySnapshot


class PinterestProvider(SocialProviderBase):
    platform = "pinterest"

    def fetch_range(
        self,
        *,
        business_id: str,
        user__id: str,
        destination_id: str,   # usually board_id or account_id depending on your storage
        since_ymd: str,
        until_ymd: str,
    ) -> ProviderResult:
        
        acct = SocialAccount.get_destination(
            business_id=business_id,
            user__id=user__id,
            platform=self.platform,
            destination_id=destination_id,
        )
        if not acct:
            return ProviderResult(self.platform, destination_id, None, {}, [], {"error": "PIN_NOT_CONNECTED"})

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return ProviderResult(self.platform, destination_id, acct.get("destination_name"), {}, [], {"error": "PIN_TOKEN_MISSING"})

        snaps = SocialDailySnapshot.get_range(
            business_id=business_id,
            user__id=user__id,
            platform=self.platform,
            destination_id=destination_id,
            since_ymd=since_ymd,
            until_ymd=until_ymd,
        )

        totals = {
            "followers": 0,
            "new_followers": 0,
            "posts": 0,          # pins created (snapshot computed)
            "impressions": 0,    # impressions from analytics (if you store it)
            "engagements": 0,    # clicks+saves+closeups etc. (store as engagements)
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "reactions": 0,
        }

        timeline = []
        prev_followers: Optional[int] = None

        for s in snaps:
            date = s.get("date")
            data = s.get("data") or {}

            followers = int(data.get("followers") or 0)
            new_followers = 0 if prev_followers is None else max(0, followers - prev_followers)
            prev_followers = followers

            engagements = int(data.get("engagements") or 0)

            pt = {
                "date": date,
                "followers": followers,
                "new_followers": new_followers,
                "posts": int(data.get("posts") or 0),
                "impressions": int(data.get("impressions") or 0),
                "engagements": engagements,
            }
            timeline.append(pt)

            totals["followers"] = followers
            totals["new_followers"] += new_followers
            totals["posts"] += pt["posts"]
            totals["impressions"] += pt["impressions"]
            totals["engagements"] += engagements

        return ProviderResult(
            platform=self.platform,
            destination_id=destination_id,
            destination_name=acct.get("destination_name"),
            totals=totals,
            timeline=timeline,
            debug={"note": "Pinterest analytics computed from snapshots. Store daily impressions/engagements if available."},
        )