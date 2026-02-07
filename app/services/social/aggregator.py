# app/services/social/aggregator.py

from __future__ import annotations

from typing import Any, Dict, List

from .providers.base import ProviderResult
from .providers.facebook_provider import FacebookProvider
from .providers.instagram_provider import InstagramProvider
from .providers.tiktok_provider import TikTokProvider
from .providers.x_provider import XProvider
from .providers.linkedin_provider import LinkedInProvider
from .providers.threads_provider import ThreadsProvider
from .providers.youtube_provider import YouTubeProvider
from .providers.pinterest_provider import PinterestProvider

from ...models.social.social_account import SocialAccount
from ...models.social.social_dashboard_summary import SocialDashboardSummary  # ✅ NEW


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
    return {k: 0.0 for k in CANON_KEYS}


def _merge_totals(dst: Dict[str, float], src: Dict[str, Any]) -> Dict[str, float]:
    for k in CANON_KEYS:
        dst[k] = float(dst.get(k, 0) or 0) + float(src.get(k, 0) or 0)
    return dst


def _merge_timeline(all_points: Dict[str, Dict[str, Any]], platform_points: List[Dict[str, Any]]):
    for pt in platform_points or []:
        d = pt.get("date")
        if not d:
            continue

        agg = all_points.setdefault(
            d,
            {"date": d, "followers": 0, "new_followers": 0, "posts": 0, "impressions": 0, "engagements": 0},
        )

        # Followers: treat as snapshot sum when provided
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
        persist: bool = True,  # ✅ NEW: allow turning persistence off
    ) -> Dict[str, Any]:
        """
        Combines analytics across all connected accounts for this user/business,
        and (optionally) persists a cached dashboard summary for the date-range.

        Persistence target: social_dashboard_summaries
          key = (business_id, user__id, since_ymd, until_ymd)
        """
        # Pull all destinations from SocialAccount collection
        all_accounts: List[Dict[str, Any]] = []
        for platform in self.providers.keys():
            items = SocialAccount.list_destinations(business_id, user__id, platform) or []
            all_accounts.extend(items)

        by_platform_totals: Dict[str, Dict[str, float]] = {p: _zero_totals() for p in self.providers.keys()}
        totals: Dict[str, float] = _zero_totals()
        timeline_map: Dict[str, Dict[str, Any]] = {}
        errors: List[Dict[str, Any]] = []

        # Optional: track which accounts were processed
        processed = 0

        for acc in all_accounts:
            platform = (acc.get("platform") or "").strip().lower()
            destination_id = str(acc.get("destination_id") or "").strip()
            if not platform or not destination_id:
                continue

            provider = self.providers.get(platform)
            if not provider:
                continue

            processed += 1

            res: ProviderResult = provider.fetch_range(
                business_id=business_id,
                user__id=user__id,
                destination_id=destination_id,
                since_ymd=since_ymd,
                until_ymd=until_ymd,
            )

            # If provider failed, record error and skip merging
            if res.debug and res.debug.get("error"):
                errors.append(
                    {
                        "platform": platform,
                        "destination_id": destination_id,
                        "debug": res.debug,
                    }
                )
                continue

            # platform totals
            _merge_totals(by_platform_totals[platform], res.totals or {})
            # global totals
            _merge_totals(totals, res.totals or {})
            # timeline
            _merge_timeline(timeline_map, res.timeline or [])

        timeline = [timeline_map[k] for k in sorted(timeline_map.keys())]

        payload: Dict[str, Any] = {
            "range": {"since": since_ymd, "until": until_ymd},
            "totals": totals,
            "by_platform": by_platform_totals,
            "timeline": timeline,
            "errors": errors,
        }

        # ✅ Persist totals per platform + overall totals + timeline
        if persist:
            try:
                # Source label (simple): if any provider errors, mark as mixed
                source = "live" if len(errors) == 0 else "mixed"

                SocialDashboardSummary.upsert_summary(
                    business_id=business_id,
                    user__id=user__id,
                    since_ymd=since_ymd,
                    until_ymd=until_ymd,
                    data=payload,
                    source=source,
                    meta={
                        "processed_accounts": processed,
                        "error_count": len(errors),
                        "platform_count": len(self.providers),
                    },
                )
            except Exception:
                # Do not break dashboard if caching fails
                pass

        return payload