from datetime import datetime
from bson import ObjectId

from ..base_model import BaseModel
from ...extensions import db as db_ext

class ScheduledPost(BaseModel):
    collection_name = "scheduled_posts"

    STATUS_SCHEDULED = "Scheduled"
    STATUS_PROCESSING = "Processing"
    STATUS_POSTED = "Posted"
    STATUS_FAILED = "Failed"

    def __init__(
        self,
        business_id,
        user__id,
        caption,
        platforms,
        scheduled_for,
        media=None,
        link=None,
        extra=None,
        status=None,
        results=None,
        error=None,
        **kwargs
    ):
        super().__init__(business_id=business_id, user__id=user__id, **kwargs)
        self.caption = caption
        self.platforms = platforms
        self.scheduled_for = scheduled_for  # datetime (UTC)
        self.media = media or {"type": "none"}  # {"type":"image|video|none","url":"...","file_path":"..."}
        self.link = link
        self.extra = extra or {}
        self.status = status or self.STATUS_SCHEDULED
        self.results = results or {}
        self.error = error

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        return {
            "business_id": self.business_id,
            "user__id": self.user__id,
            "caption": self.caption,
            "platforms": self.platforms,
            "scheduled_for": self.scheduled_for,
            "media": self.media,
            "link": self.link,
            "extra": self.extra,
            "status": self.status,
            "results": self.results,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def get_by_id(cls, post_id, business_id):
        col = db_ext.get_collection(cls.collection_name)
        doc = col.find_one({"_id": ObjectId(post_id), "business_id": ObjectId(business_id)})
        if not doc:
            return None
        doc["_id"] = str(doc["_id"])
        doc["business_id"] = str(doc["business_id"])
        doc["user__id"] = str(doc["user__id"])
        return doc

    @classmethod
    def set_status(cls, post_id, business_id, status, results=None, error=None):
        update_doc = {"status": status, "updated_at": datetime.utcnow()}
        if results is not None:
            update_doc["results"] = results
        if error is not None:
            update_doc["error"] = error

        col = db_ext.get_collection(cls.collection_name)
        res = col.update_one(
            {"_id": ObjectId(post_id), "business_id": ObjectId(business_id)},
            {"$set": update_doc}
        )
        return res.modified_count > 0