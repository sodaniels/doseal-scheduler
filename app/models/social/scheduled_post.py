from datetime import datetime, timezone
from bson import ObjectId
from pymongo import ReturnDocument

from ..base_model import BaseModel
from ...extensions import db as db_ext


class ScheduledPost(BaseModel):
    collection_name = "scheduled_posts"

    STATUS_DRAFT = "draft"
    STATUS_SCHEDULED = "scheduled"
    STATUS_ENQUEUED = "enqueued"        # <--- NEW (important)
    STATUS_PUBLISHING = "publishing"
    STATUS_PUBLISHED = "published"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"

    def __init__(
        self,
        business_id,
        user__id,
        content,
        scheduled_at_utc,
        destinations,
        platform="multi",
        status=None,
        provider_results=None,
        error=None,
        created_by=None,
        **kwargs
    ):
        super().__init__(business_id=business_id, user__id=user__id, created_by=created_by, **kwargs)

        self.platform = platform  # "facebook" or "multi"

        # {"text": "...", "link": "...", "media": {...optional...}}
        self.content = content or {}

        # Always store UTC datetime
        self.scheduled_at_utc = scheduled_at_utc

        # [{"platform":"facebook","destination_type":"page","destination_id":"123"}]
        self.destinations = destinations or []

        self.status = status or self.STATUS_SCHEDULED
        self.provider_results = provider_results or []
        self.error = error

        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self):
        return {
            "business_id": self.business_id,
            "user__id": self.user__id,
            "platform": self.platform,

            "content": self.content,
            "scheduled_at_utc": self.scheduled_at_utc,
            "destinations": self.destinations,

            "status": self.status,
            "provider_results": self.provider_results,
            "error": self.error,

            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    # -------------------------
    # Helpers
    # -------------------------

    @staticmethod
    def _parse_dt(value):
        if not value:
            return None
        if isinstance(value, datetime):
            # ensure tz-aware UTC
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if isinstance(value, str):
            # allow "Z"
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        return None

    @staticmethod
    def _oid_str(doc):
        if not doc:
            return None
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        if "business_id" in doc:
            doc["business_id"] = str(doc["business_id"])
        if "user__id" in doc:
            doc["user__id"] = str(doc["user__id"])
        return doc

    # -------------------------
    # CRUD
    # -------------------------

    @classmethod
    def create(cls, doc: dict):
        """
        Insert a scheduled post document into MongoDB.
        Expects doc to include:
          business_id, user__id, content, scheduled_at_utc, destinations
        """
        col = db_ext.get_collection(cls.collection_name)
        insert_doc = dict(doc or {})

        if not insert_doc.get("business_id") or not insert_doc.get("user__id"):
            raise ValueError("business_id and user__id are required")

        insert_doc["business_id"] = ObjectId(str(insert_doc["business_id"]))
        insert_doc["user__id"] = ObjectId(str(insert_doc["user__id"]))

        # normalize scheduled time
        insert_doc["scheduled_at_utc"] = cls._parse_dt(insert_doc.get("scheduled_at_utc"))
        if not insert_doc["scheduled_at_utc"]:
            raise ValueError("scheduled_at_utc is required and must be ISO string or datetime")

        insert_doc.setdefault("platform", "multi")
        insert_doc.setdefault("content", {})
        insert_doc.setdefault("destinations", [])
        insert_doc.setdefault("status", cls.STATUS_SCHEDULED)

        now = datetime.now(timezone.utc)
        insert_doc.setdefault("provider_results", [])
        insert_doc.setdefault("error", None)
        insert_doc.setdefault("created_at", now)
        insert_doc.setdefault("updated_at", now)

        res = col.insert_one(insert_doc)
        insert_doc["_id"] = res.inserted_id

        return cls._oid_str(insert_doc)

    @classmethod
    def get_by_id(cls, post_id: str, business_id: str):
        col = db_ext.get_collection(cls.collection_name)
        doc = col.find_one({
            "_id": ObjectId(str(post_id)),
            "business_id": ObjectId(str(business_id)),
        })
        return cls._oid_str(doc)

    @classmethod
    def get_due_posts(cls, limit=50):
        """Fetch scheduled posts that are due now (UTC)."""
        col = db_ext.get_collection(cls.collection_name)
        now = datetime.now(timezone.utc)
        return list(col.find({
            "status": cls.STATUS_SCHEDULED,
            "scheduled_at_utc": {"$lte": now},
        }).sort("scheduled_at_utc", 1).limit(limit))

    # -------------------------
    # Atomic scheduler support
    # -------------------------

    @classmethod
    def claim_due_posts(cls, limit=50):
        """
        IMPORTANT (scales well):
        Atomically move due posts from scheduled -> enqueued
        so only ONE scheduler process can enqueue them.
        """
        col = db_ext.get_collection(cls.collection_name)
        now = datetime.now(timezone.utc)

        claimed = []
        for _ in range(limit):
            doc = col.find_one_and_update(
                {
                    "status": cls.STATUS_SCHEDULED,
                    "scheduled_at_utc": {"$lte": now},
                },
                {
                    "$set": {
                        "status": cls.STATUS_ENQUEUED,
                        "updated_at": now,
                    }
                },
                sort=[("scheduled_at_utc", 1)],
                return_document=ReturnDocument.AFTER,
            )
            if not doc:
                break
            claimed.append(cls._oid_str(doc))
        return claimed

    # -------------------------
    # Status updates
    # -------------------------

    @classmethod
    def update_status(cls, post_id, business_id, status, **extra):
        col = db_ext.get_collection(cls.collection_name)
        extra = extra or {}
        extra["status"] = status
        extra["updated_at"] = datetime.now(timezone.utc)

        res = col.update_one(
            {"_id": ObjectId(str(post_id)), "business_id": ObjectId(str(business_id))},
            {"$set": extra}
        )
        return res.modified_count > 0

    @classmethod
    def ensure_indexes(cls):
        col = db_ext.get_collection(cls.collection_name)

        # scheduler reads
        col.create_index([("status", 1), ("scheduled_at_utc", 1)])

        # listing per tenant/user
        col.create_index([("business_id", 1), ("user__id", 1), ("created_at", -1)])

        # optional: faster multi-destination queries later
        col.create_index([("business_id", 1), ("status", 1), ("scheduled_at_utc", 1)])
        return True