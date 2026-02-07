# app/services/social/providers/youtube_provider.py

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import ProviderResult, SocialProviderBase
from ....models.social.social_account import SocialAccount
from ....models.social.social_daily_snapshot import SocialDailySnapshot


class YouTubeProvider(SocialProviderBase):
    platform = "youtube"

    def fetch_range(
        self,
        *,
        business_id: str,
        user__id: str,
        destination_id: str,   # channel_id
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
            return ProviderResult(self.platform, destination_id, None, {}, [], {"error": "YT_NOT_CONNECTED"})

        access_token = acct.get("access_token_plain") or acct.get("access_token")
        if not access_token:
            return ProviderResult(self.platform, destination_id, acct.get("destination_name"), {}, [], {"error": "YT_TOKEN_MISSING"})

        snaps = SocialDailySnapshot.get_range(
            business_id=business_id,
            user__id=user__id,
            platform=self.platform,
            destination_id=destination_id,
            since_ymd=since_ymd,
            until_ymd=until_ymd,
        )

        totals = {
            "followers": 0,        # for YouTube: subscribers
            "new_followers": 0,    # new subscribers (computed from snapshots)
            "posts": 0,            # videos published (or uploads)
            "impressions": 0,      # requires Analytics API; otherwise snapshots
            "engagements": 0,      # likes+comments+shares (shares often not available)
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "reactions": 0,
        }

        timeline = []
        prev_subs: Optional[int] = None

        for s in snaps:
            date = s.get("date")
            data = s.get("data") or {}

            subs = int(data.get("followers") or data.get("subscribers") or 0)
            new_subs = 0 if prev_subs is None else max(0, subs - prev_subs)
            prev_subs = subs

            likes = int(data.get("likes") or 0)
            comments = int(data.get("comments") or 0)
            engagements = int(data.get("engagements") or (likes + comments) or 0)

            pt = {
                "date": date,
                "followers": subs,
                "new_followers": new_subs,
                "posts": int(data.get("posts") or data.get("videos") or 0),
                "impressions": int(data.get("impressions") or 0),
                "engagements": engagements,
            }
            timeline.append(pt)

            totals["followers"] = subs
            totals["new_followers"] += new_subs
            totals["posts"] += pt["posts"]
            totals["impressions"] += pt["impressions"]
            totals["likes"] += likes
            totals["comments"] += comments
            totals["engagements"] += engagements

        return ProviderResult(
            platform=self.platform,
            destination_id=destination_id,
            destination_name=acct.get("destination_name"),
            totals=totals,
            timeline=timeline,
            debug={
                "note": "YouTube timeline is snapshot-based. Use YouTube Analytics API if you want real impressions/views per day."
            },
        )