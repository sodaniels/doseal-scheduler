# app/services/social/providers/x_provider.py

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import ProviderResult, SocialProviderBase
from ....models.social.social_account import SocialAccount
from ....models.social.social_daily_snapshot import SocialDailySnapshot


class XProvider(SocialProviderBase):
    platform = "x"

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
            platform="x",
            destination_id=destination_id,
        )
        if not acct:
            return ProviderResult(self.platform, destination_id, None, {}, [], {"error": "TW_NOT_CONNECTED"})

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return ProviderResult(self.platform, destination_id, acct.get("destination_name"), {}, [], {"error": "TW_TOKEN_MISSING"})

        # Use snapshots for timeline (X does not provide follower time series)
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
            "posts": 0,
            "impressions": 0,
            "engagements": 0,
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

            pt = {
                "date": date,
                "followers": followers,
                "new_followers": new_followers,
                "posts": int(data.get("posts") or 0),
                "impressions": int(data.get("impressions") or 0),
                "engagements": int(data.get("engagements") or 0),
            }
            timeline.append(pt)

            totals["followers"] = followers  # last known in range
            totals["new_followers"] += new_followers
            totals["posts"] += pt["posts"]
            totals["impressions"] += pt["impressions"]
            totals["engagements"] += pt["engagements"]

        return ProviderResult(
            platform=self.platform,
            destination_id=destination_id,
            destination_name=acct.get("destination_name"),
            totals=totals,
            timeline=timeline,
            debug={"note": "X timeline computed from SocialDailySnapshot."},
        )