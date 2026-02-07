from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId

from ...extensions.db import db as db_ext


class SocialDashboardSummary:
    """
    Materialized dashboard summary (cache) per:
      business_id + user__id + since_ymd + until_ymd

    Collection: social_dashboard_summaries
    """
    collection_name = "social_dashboard_summaries"

    @classmethod
    def upsert_summary(
        cls,
        *,
        business_id: str,
        user__id: str,
        since_ymd: str,
        until_ymd: str,
        data: Dict[str, Any],
        source: str,  # "live" | "snapshot" | "mixed"
        meta: Optional[Dict[str, Any]] = None,
    ):
        now = datetime.now(timezone.utc)
        col = db_ext.get_collection(cls.collection_name)

        filt = {
            "business_id": ObjectId(business_id),
            "user__id": ObjectId(user__id),
            "since_ymd": since_ymd,
            "until_ymd": until_ymd,
        }

        update = {
            "$set": {
                # The full payload you return to the UI
                "data": data or {},
                "source": source,
                "meta": meta or {},
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
        }

        return col.update_one(filt, update, upsert=True)

    @classmethod
    def get_summary(
        cls,
        *,
        business_id: str,
        user__id: str,
        since_ymd: str,
        until_ymd: str,
    ) -> Optional[Dict[str, Any]]:
        col = db_ext.get_collection(cls.collection_name)
        doc = col.find_one(
            {
                "business_id": ObjectId(business_id),
                "user__id": ObjectId(user__id),
                "since_ymd": since_ymd,
                "until_ymd": until_ymd,
            }
        )
        if not doc:
            return None

        # normalize ids for API output if you need
        doc["_id"] = str(doc["_id"])
        doc["business_id"] = str(doc["business_id"])
        doc["user__id"] = str(doc["user__id"])
        return doc