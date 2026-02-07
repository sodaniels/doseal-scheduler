# app/models/social/social_publish_attempt.py
from datetime import datetime
from bson.objectid import ObjectId
from ..base_model import BaseModel

class SocialPublishAttempt(BaseModel):
    collection_name = "social_publish_attempts"

    STATUS_SUCCESS = "Success"
    STATUS_FAILED = "Failed"

    def __init__(
        self,
        business_id,
        user__id,
        scheduled_post_id,
        platform,
        destination_id,
        status,
        provider_post_id=None,
        request_payload=None,
        response_payload=None,
        error_message=None,
        **kwargs
    ):
        super().__init__(business_id=business_id, user__id=user__id, **kwargs)
        self.business_id = ObjectId(business_id)
        self.user__id = ObjectId(user__id)
        self.scheduled_post_id = ObjectId(scheduled_post_id)

        self.platform = platform
        self.destination_id = destination_id
        self.status = status
        self.provider_post_id = provider_post_id
        self.request_payload = request_payload or {}
        self.response_payload = response_payload or {}
        self.error_message = error_message

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        return {
            "business_id": self.business_id,
            "user__id": self.user__id,
            "scheduled_post_id": self.scheduled_post_id,
            "platform": self.platform,
            "destination_id": self.destination_id,
            "status": self.status,
            "provider_post_id": self.provider_post_id,
            "request_payload": self.request_payload,
            "response_payload": self.response_payload,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }