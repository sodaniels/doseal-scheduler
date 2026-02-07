# app/services/social/snapshot_store.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# from ...models.social.social_daily_snapshot import SocialDailySnapshot, CANON_KEYS
from ...models.social.social_daily_snapshot import SocialDailySnapshot, CANON_KEYS


def _f(v: Any) -> float:
    try:
        if v is None:
            return 0.0
        if isinstance(v, bool):
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.strip():
            return float(v.strip())
    except Exception:
        return 0.0
    return 0.0


def _zero() -> Dict[str, float]:
    return {k: 0.0 for k in CANON_KEYS}


@dataclass
class ProviderResult:
    platform: str
    destination_id: str
    destination_name: Optional[str]
    totals: Dict[str, Any]
    timeline: List[Dict[str, Any]]
    debug: Optional[Dict[str, Any]] = None


class SnapshotStore:
    """
    A small service layer that:
      - writes day snapshots from a ProviderResult timeline
      - reads snapshots and returns ProviderResult-like data (for fallback)
    """

    @staticmethod
    def ensure_indexes():
        SocialDailySnapshot.ensure_indexes()

    @staticmethod
    def write_from_provider_result(
        *,
        business_id: str,
        user__id: str,
        platform: str,
        destination_id: str,
        result: ProviderResult,
        prefer_write_each_day: bool = True,
        write_only_today_if_no_timeline: bool = True,
        today_ymd: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Persist snapshots based on provider timeline.

        - If provider returns daily timeline points -> upsert each day.
        - If provider has no timeline and write_only_today_if_no_timeline=True,
          upsert a "today" record with totals (followers, etc).
        """
        writes = 0
        platform = (platform or "").lower().strip()

        tl = result.timeline or []

        if prefer_write_each_day and tl:
            for pt in tl:
                date = (pt.get("date") or "").strip()
                if not date:
                    continue

                day_data = {
                    "followers": pt.get("followers") or 0,
                    "new_followers": pt.get("new_followers") or 0,
                    "posts": pt.get("posts") or 0,
                    "impressions": pt.get("impressions") or 0,
                    "engagements": pt.get("engagements") or 0,
                    # optional:
                    "likes": pt.get("likes") or 0,
                    "comments": pt.get("comments") or 0,
                    "shares": pt.get("shares") or 0,
                    "reactions": pt.get("reactions") or 0,
                }

                SocialDailySnapshot.upsert_snapshot(
                    business_id=business_id,
                    user__id=user__id,
                    platform=platform,
                    destination_id=destination_id,
                    date_ymd=date,
                    data=day_data,
                    meta=meta,
                )
                writes += 1

            return {"writes": writes, "mode": "timeline_days"}

        if write_only_today_if_no_timeline:
            if not today_ymd:
                # lazy import to avoid circular issues
                from datetime import datetime, timezone
                today_ymd = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            totals = result.totals or {}
            SocialDailySnapshot.upsert_snapshot(
                business_id=business_id,
                user__id=user__id,
                platform=platform,
                destination_id=destination_id,
                date_ymd=today_ymd,
                data=totals,
                meta=meta,
            )
            writes += 1
            return {"writes": writes, "mode": "today_totals"}

        return {"writes": 0, "mode": "skip"}

    @staticmethod
    def read_range_as_provider_result(
        *,
        business_id: str,
        user__id: str,
        platform: str,
        destination_id: str,
        since_ymd: str,
        until_ymd: str,
        destination_name: Optional[str] = None,
        debug: Optional[Dict[str, Any]] = None,
    ) -> ProviderResult:
        """
        Read snapshots from DB and shape them into ProviderResult so your Aggregator can merge it.
        """
        platform = (platform or "").lower().strip()

        rows = SocialDailySnapshot.get_range(
            business_id=business_id,
            user__id=user__id,
            platform=platform,
            destination_id=destination_id,
            since_ymd=since_ymd,
            until_ymd=until_ymd,
        )

        totals = _zero()
        timeline: List[Dict[str, Any]] = []

        for r in rows:
            date = r.get("date_ymd")
            data = r.get("data") or {}

            pt = {
                "date": date,
                # followers is stored as a snapshot value (not a delta)
                "followers": int(_f(data.get("followers"))),
                "new_followers": int(_f(data.get("new_followers"))),
                "posts": int(_f(data.get("posts"))),
                "impressions": int(_f(data.get("impressions"))),
                "engagements": int(_f(data.get("engagements"))),
                "likes": int(_f(data.get("likes"))),
                "comments": int(_f(data.get("comments"))),
                "shares": int(_f(data.get("shares"))),
                "reactions": int(_f(data.get("reactions"))),
            }
            timeline.append(pt)

            # totals: sum of daily series for delta-type metrics
            totals["new_followers"] += _f(data.get("new_followers"))
            totals["posts"] += _f(data.get("posts"))
            totals["impressions"] += _f(data.get("impressions"))
            totals["engagements"] += _f(data.get("engagements"))
            totals["likes"] += _f(data.get("likes"))
            totals["comments"] += _f(data.get("comments"))
            totals["shares"] += _f(data.get("shares"))
            totals["reactions"] += _f(data.get("reactions"))

        # followers total for a range is ambiguous; we use latest follower snapshot inside range
        if timeline:
            totals["followers"] = float(timeline[-1].get("followers") or 0)
        else:
            totals["followers"] = 0.0

        return ProviderResult(
            platform=platform,
            destination_id=destination_id,
            destination_name=destination_name,
            totals=totals,
            timeline=timeline,
            debug=debug,
        )