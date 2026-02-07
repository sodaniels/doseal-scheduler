# app/services/social/aggregator.py

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Optional

from .providers.base import ProviderResult
from .providers.facebook_provider import FacebookProvider
from .providers.instagram_provider import InstagramProvider
from .providers.tiktok_provider import TikTokProvider
from .providers.x_provider import XProvider
from .providers.linkedin_provider import LinkedInProvider
from ...models.social.social_account import SocialAccount
from .providers.threads_provider import ThreadsProvider
from .providers.youtube_provider import YouTubeProvider
from .providers.pinterest_provider import PinterestProvider


CANON_KEYS = [
    "followers",
    "new_followers",
    "posts",
    "impressions",
    "engagements",
    "likes",
    "comments",
    "shares",
    "reactions",
]


def _zero_totals() -> Dict[str, float]:
    return {k: 0 for k in CANON_KEYS}


def _merge_totals(dst: Dict[str, float], src: Dict[str, Any]) -> Dict[str, float]:
    for k in CANON_KEYS:
        dst[k] = float(dst.get(k, 0) or 0) + float(src.get(k, 0) or 0)
    return dst


def _merge_timeline(all_points: Dict[str, Dict[str, Any]], platform_points: List[Dict[str, Any]]):
    for pt in platform_points:
        d = pt.get("date")
        if not d:
            continue
        agg = all_points.setdefault(
            d,
            {"date": d, "followers": 0, "new_followers": 0, "posts": 0, "impressions": 0, "engagements": 0},
        )

        # followers is tricky for combined chart; we treat it as “sum of followers snapshots”
        # (best if snapshots exist per platform; otherwise only current)
        if pt.get("followers") is not None:
            agg["followers"] += int(pt.get("followers") or 0)

        agg["new_followers"] += int(pt.get("new_followers") or 0)
        agg["posts"] += int(pt.get("posts") or 0)
        agg["impressions"] += int(pt.get("impressions") or 0)
        agg["engagements"] += int(pt.get("engagements") or 0)


class SocialAggregator:
    def __init__(self):
        
        self.providers = {
            "facebook": FacebookProvider(),
            "instagram": InstagramProvider(),
            "tiktok": TikTokProvider(),
            "x": XProvider(),
            "linkedin": LinkedInProvider(),
            "threads": ThreadsProvider(),
            "youtube": YouTubeProvider(),
            "pinterest": PinterestProvider(),
        }

    def build_overview(
        self,
        *,
        business_id: str,
        user__id: str,
        since_ymd: str,
        until_ymd: str,
    ) -> Dict[str, Any]:
        """
        Combines analytics across all connected accounts for this user/business.
        """
        # Pull all destinations from SocialAccount collection
        all_accounts = []
        for platform in self.providers.keys():
            items = SocialAccount.list_destinations(business_id, user__id, platform) or []
            all_accounts.extend(items)

        by_platform_totals: Dict[str, Dict[str, float]] = {p: _zero_totals() for p in self.providers.keys()}
        totals = _zero_totals()
        timeline_map: Dict[str, Dict[str, Any]] = {}
        errors: List[Dict[str, Any]] = []

        for acc in all_accounts:
            platform = acc.get("platform")
            destination_id = acc.get("destination_id")
            if not platform or not destination_id:
                continue
            provider = self.providers.get(platform)
            if not provider:
                continue

            res: ProviderResult = provider.fetch_range(
                business_id=business_id,
                user__id=user__id,
                destination_id=destination_id,
                since_ymd=since_ymd,
                until_ymd=until_ymd,
            )

            if res.debug and res.debug.get("error"):
                errors.append({"platform": platform, "destination_id": destination_id, "debug": res.debug})
                continue

            # platform totals
            _merge_totals(by_platform_totals[platform], res.totals)
            # global totals
            _merge_totals(totals, res.totals)
            # timeline
            _merge_timeline(timeline_map, res.timeline)

        timeline = [timeline_map[k] for k in sorted(timeline_map.keys())]

        return {
            "range": {"since": since_ymd, "until": until_ymd},
            "totals": totals,
            "by_platform": by_platform_totals,
            "timeline": timeline,
            "errors": errors,
        }