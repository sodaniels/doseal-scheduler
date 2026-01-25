# app/models/social_connected_account.py
from datetime import datetime
from bson.objectid import ObjectId
from ..base_model import BaseModel
from ...utils.crypt import encrypt_data, decrypt_data
from ...extensions.db import db

class SocialConnectedAccount(BaseModel):
    collection_name = "social_connected_accounts"

    STATUS_ACTIVE = "Active"
    STATUS_REVOKED = "Revoked"
    STATUS_EXPIRED = "Expired"
    STATUS_ERROR = "Error"

    def __init__(
        self,
        business_id,
        user__id,
        platform,                 # "meta", "x", "linkedin", "pinterest", "youtube", "tiktok"
        provider_user_id=None,    # ID returned by platform
        display_name=None,
        access_token=None,
        refresh_token=None,
        expires_at=None,          # datetime or iso string
        scopes=None,              # list[str]
        destinations=None,        # list of pages/boards/channels available
        status=None,
        metadata=None,
        **kwargs
    ):
        super().__init__(business_id=business_id, user__id=user__id, **kwargs)
        self.business_id = ObjectId(business_id)
        self.user__id = ObjectId(user__id)

        self.platform = platform
        self.provider_user_id = provider_user_id
        self.display_name = display_name

        # Encrypt tokens at rest
        self.encrypted_access_token = encrypt_data(access_token) if access_token else None
        self.encrypted_refresh_token = encrypt_data(refresh_token) if refresh_token else None

        self.expires_at = expires_at
        self.scopes = scopes or []
        self.destinations = destinations or []
        self.status = status or self.STATUS_ACTIVE
        self.metadata = metadata or {}

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        return {
            "business_id": self.business_id,
            "user__id": self.user__id,
            "platform": self.platform,
            "provider_user_id": self.provider_user_id,
            "display_name": self.display_name,
            "encrypted_access_token": self.encrypted_access_token,
            "encrypted_refresh_token": self.encrypted_refresh_token,
            "expires_at": self.expires_at,
            "scopes": self.scopes,
            "destinations": self.destinations,
            "status": self.status,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def decrypt_token(doc: dict):
        if not doc:
            return None
        if doc.get("encrypted_access_token"):
            doc["access_token"] = decrypt_data(doc["encrypted_access_token"])
        if doc.get("encrypted_refresh_token"):
            doc["refresh_token"] = decrypt_data(doc["encrypted_refresh_token"])
        return doc

    @classmethod
    def get_active_by_user(cls, business_id, user__id, platform=None):
        q = {"business_id": ObjectId(business_id), "user__id": ObjectId(user__id), "status": cls.STATUS_ACTIVE}
        if platform:
            q["platform"] = platform
        return list(db.get_collection(cls.collection_name).find(q))