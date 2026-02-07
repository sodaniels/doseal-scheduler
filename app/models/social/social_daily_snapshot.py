# app/models/social/social_daily_snapshot.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING

from ...extensions.db import db as db_ext


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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_oid(x: Any) -> Any:
    try:
        if isinstance(x, ObjectId):
            return x
        if isinstance(x, str) and ObjectId.is_valid(x):
            return ObjectId(x)
    except Exception:
        pass
    return x


def _num(v: Any) -> float:
    try:
        if v is None:
            return 0.0
        if isinstance(v, bool):
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            vv = v.strip()
            if not vv:
                return 0.0
            return float(vv)
    except Exception:
        return 0.0
    return 0.0


def _normalize_data(data: Dict[str, Any]) -> Dict[str, float]:
    out = {}
    for k in CANON_KEYS:
        out[k] = _num((data or {}).get(k))
    return out


class SocialDailySnapshot:
    """
    Collection design (recommended):
      {
        _id,
        business_id: ObjectId,
        user__id: ObjectId,
        platform: "facebook"|"instagram"|...,
        destination_id: "12345",
        date_ymd: "2026-02-07",
        data: { followers, new_followers, posts, impressions, engagements, likes, comments, shares, reactions },
        created_at,
        updated_at
      }

    Unique index:
      (business_id, user__id, platform, destination_id, date_ymd)
    """

    collection_name = "social_daily_snapshots"

    @classmethod
    def col(cls):
        return db_ext.get_collection(cls.collection_name)

    @classmethod
    def ensure_indexes(cls):
        c = cls.col()
        # Unique per-day snapshot per destination
        c.create_index(
            [
                ("business_id", ASCENDING),
                ("user__id", ASCENDING),
                ("platform", ASCENDING),
                ("destination_id", ASCENDING),
                ("date_ymd", ASCENDING),
            ],
            unique=True,
            name="uniq_daily_snapshot",
        )
        # For range queries
        c.create_index(
            [
                ("business_id", ASCENDING),
                ("user__id", ASCENDING),
                ("platform", ASCENDING),
                ("destination_id", ASCENDING),
                ("date_ymd", DESCENDING),
            ],
            name="idx_daily_snapshot_range",
        )

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
        meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Upsert a day snapshot.
        """
        c = cls.col()

        bid = _as_oid(business_id)
        uid = _as_oid(user__id)

        doc_data = _normalize_data(data or {})
        now = _utcnow()

        q = {
            "business_id": bid,
            "user__id": uid,
            "platform": (platform or "").strip().lower(),
            "destination_id": str(destination_id or "").strip(),
            "date_ymd": str(date_ymd or "").strip(),
        }

        upd = {
            "$set": {
                **q,
                "data": doc_data,
                "meta": meta or {},
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        }

        res = c.update_one(q, upd, upsert=True)

        return {
            "matched": res.matched_count,
            "modified": res.modified_count,
            "upserted_id": str(res.upserted_id) if res.upserted_id else None,
        }

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
    ) -> List[Dict[str, Any]]:
        """
        Returns list of snapshots in [since, until], ascending by date.
        """
        c = cls.col()
        bid = _as_oid(business_id)
        uid = _as_oid(user__id)

        q = {
            "business_id": bid,
            "user__id": uid,
            "platform": (platform or "").strip().lower(),
            "destination_id": str(destination_id or "").strip(),
            "date_ymd": {"$gte": since_ymd, "$lte": until_ymd},
        }

        items = list(c.find(q).sort("date_ymd", ASCENDING))

        # normalize ids for callers
        for x in items:
            x["_id"] = str(x["_id"])
            x["business_id"] = str(x["business_id"])
            x["user__id"] = str(x["user__id"])
        return items

    @classmethod
    def latest(
        cls,
        *,
        business_id: str,
        user__id: str,
        platform: str,
        destination_id: str,
    ) -> Optional[Dict[str, Any]]:
        c = cls.col()
        bid = _as_oid(business_id)
        uid = _as_oid(user__id)

        q = {
            "business_id": bid,
            "user__id": uid,
            "platform": (platform or "").strip().lower(),
            "destination_id": str(destination_id or "").strip(),
        }
        doc = c.find_one(q, sort=[("date_ymd", DESCENDING)])
        if not doc:
            return None

        doc["_id"] = str(doc["_id"])
        doc["business_id"] = str(doc["business_id"])
        doc["user__id"] = str(doc["user__id"])
        return doc