from datetime import datetime, timezone
from bson import ObjectId
from ..base_model import BaseModel
from ...extensions import db as db_ext


class ScheduledPost(BaseModel):
    collection_name = "scheduled_posts"

    STATUS_DRAFT = "draft"
    STATUS_SCHEDULED = "scheduled"
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

        # post content
        self.content = content  # {"text": "...", "link": "...", "media": {...optional...}}

        # Always store UTC
        self.scheduled_at_utc = scheduled_at_utc

        # Where to publish: list of dicts
        # Example: [{"platform":"facebook","destination_type":"page","destination_id":"123"}]
        self.destinations = destinations

        self.status = status or self.STATUS_SCHEDULED

        # results per destination
        self.provider_results = provider_results or []  # [{"platform":"facebook","destination_id":"..","provider_post_id":"..","raw":{}}]
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

    @classmethod
    def get_due_posts(cls, limit=50):
        """Fetch scheduled posts that are due now (UTC)."""
        col = db_ext.get_collection(cls.collection_name)
        now = datetime.now(timezone.utc)
        return list(col.find({
            "status": cls.STATUS_SCHEDULED,
            "scheduled_at_utc": {"$lte": now},
        }).sort("scheduled_at_utc", 1).limit(limit))

    @classmethod
    def update_status(cls, post_id, business_id, status, **extra):
        col = db_ext.get_collection(cls.collection_name)
        extra["status"] = status
        extra["updated_at"] = datetime.now(timezone.utc)
        res = col.update_one(
            {"_id": ObjectId(post_id), "business_id": ObjectId(business_id)},
            {"$set": extra}
        )
        return res.modified_count > 0

    @classmethod
    def ensure_indexes(cls):
        col = db_ext.get_collection(cls.collection_name)
        col.create_index([("status", 1), ("scheduled_at_utc", 1)])
        col.create_index([("business_id", 1), ("user__id", 1), ("created_at", -1)])
        return True