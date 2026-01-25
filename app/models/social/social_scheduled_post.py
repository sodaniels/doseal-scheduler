# app/models/social_scheduled_post.py
from datetime import datetime
from bson.objectid import ObjectId
from ..base_model import BaseModel
from ...extensions.db import db

class SocialScheduledPost(BaseModel):
    collection_name = "social_scheduled_posts"

    STATUS_PENDING = "Pending"
    STATUS_PROCESSING = "Processing"
    STATUS_PUBLISHED = "Published"
    STATUS_FAILED = "Failed"
    STATUS_PARTIAL = "Partial"
    STATUS_CANCELLED = "Cancelled"

    def __init__(
        self,
        business_id,
        user__id,
        text=None,
        media=None,          # [{"type":"image|video", "url": "...", "path": "..."}]
        link=None,
        platforms=None,      # [{"platform":"meta","destination_id":"...","destination_type":"page"}]
        scheduled_for=None,  # utc datetime string or datetime
        timezone="Europe/London",
        status=None,
        metadata=None,
        **kwargs
    ):
        super().__init__(business_id=business_id, user__id=user__id, **kwargs)
        self.business_id = ObjectId(business_id)
        self.user__id = ObjectId(user__id)

        self.text = text
        self.link = link
        self.media = media or []
        self.platforms = platforms or []
        self.scheduled_for = scheduled_for
        self.timezone = timezone

        self.status = status or self.STATUS_PENDING
        self.metadata = metadata or {}

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        return {
            "business_id": self.business_id,
            "user__id": self.user__id,
            "text": self.text,
            "link": self.link,
            "media": self.media,
            "platforms": self.platforms,
            "scheduled_for": self.scheduled_for,
            "timezone": self.timezone,
            "status": self.status,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }