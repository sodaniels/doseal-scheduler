# app/models/social/social_daily_snapshot.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId

from ...extensions.db import db as db_ext
from ...utils.logger import Log


class SocialDailySnapshot:
    """
    Store daily snapshots per destination (page/account) per platform.

    Why:
    - Many platforms do NOT provide follower_count time series.
    - Even when they do, you want stable local data for charts + speed.

    Unique key recommendation:
      (business_id, user__id, platform, destination_id, date)
    """

    collection_name = "social_daily_snapshots"

    @staticmethod
    def _col():
        return db_ext.get_collection(SocialDailySnapshot.collection_name)

    @classmethod
    def upsert_snapshot(
        cls,
        *,
        business_id: str,
        user__id: str,
        platform: str,
        destination_id: str,
        date_ymd: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        col = cls._col()
        now = datetime.now(timezone.utc)

        doc = {
            "business_id": ObjectId(business_id),
            "user__id": ObjectId(user__id),
            "platform": platform,
            "destination_id": destination_id,
            "date": date_ymd,  # YYYY-MM-DD
            "data": data,
            "updated_at": now,
        }

        col.update_one(
            {
                "business_id": ObjectId(business_id),
                "user__id": ObjectId(user__id),
                "platform": platform,
                "destination_id": destination_id,
                "date": date_ymd,
            },
            {"$set": doc, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )

        return {"success": True}

    @classmethod
    def get_range(
        cls,
        *,
        business_id: str,
        user__id: str,
        platform: str,
        destination_id: str,
        since_ymd: str,
        until_ymd: str,
    ):
        col = cls._col()
        cursor = col.find(
            {
                "business_id": ObjectId(business_id),
                "user__id": ObjectId(user__id),
                "platform": platform,
                "destination_id": destination_id,
                "date": {"$gte": since_ymd, "$lte": until_ymd},
            },
            {"_id": 0, "date": 1, "data": 1},
        ).sort("date", 1)

        return list(cursor)

    @classmethod
    def get_latest(
        cls,
        *,
        business_id: str,
        user__id: str,
        platform: str,
        destination_id: str,
    ) -> Optional[Dict[str, Any]]:
        col = cls._col()
        doc = col.find_one(
            {
                "business_id": ObjectId(business_id),
                "user__id": ObjectId(user__id),
                "platform": platform,
                "destination_id": destination_id,
            },
            sort=[("date", -1)],
            projection={"_id": 0, "date": 1, "data": 1},
        )
        return doc