from datetime import datetime
from bson import ObjectId

from ..base_model import BaseModel
from ...extensions import db as db_ext

# If you already have encrypt_data/decrypt_data, import them:
# from ...utils.crypt import encrypt_data, decrypt_data
# For this standalone module, we store plain tokens by default.
# Replace with encryption in production.

def _enc(v):  # replace with encrypt_data
    return v

def _dec(v):  # replace with decrypt_data
    return v

class SocialAccount(BaseModel):
    """
    One connected social account per (business_id, user__id, platform).
    meta holds required platform identifiers:
      - facebook: {"page_id": "..."}
      - instagram: {"ig_user_id": "..."}
      - threads: {"threads_user_id": "..."} (optional)
      - linkedin: {"author_urn": "urn:li:person:..."} OR org urn
      - pinterest: {"board_id": "..."}
      - youtube: {} (channel is implicit)
      - x: {} (implicit)
      - tiktok: {} (approval required)
    """
    collection_name = "social_accounts"

    def __init__(
        self,
        business_id,
        user__id,
        platform,
        access_token=None,
        refresh_token=None,
        token_expires_at=None,
        scopes=None,
        platform_user_id=None,
        platform_username=None,
        meta=None,
        **kwargs
    ):
        super().__init__(business_id=business_id, user__id=user__id, **kwargs)
        self.platform = platform

        self.access_token = _enc(access_token) if access_token else None
        self.refresh_token = _enc(refresh_token) if refresh_token else None
        self.token_expires_at = token_expires_at
        self.scopes = scopes or []

        self.platform_user_id = platform_user_id
        self.platform_username = platform_username
        self.meta = meta or {}

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        return {
            "business_id": self.business_id,
            "user__id": self.user__id,
            "platform": self.platform,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_expires_at": self.token_expires_at,
            "scopes": self.scopes,
            "platform_user_id": self.platform_user_id,
            "platform_username": self.platform_username,
            "meta": self.meta,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def get_account(cls, business_id, user__id, platform):
        col = db_ext.get_collection(cls.collection_name)
        doc = col.find_one({
            "business_id": ObjectId(business_id),
            "user__id": ObjectId(user__id),
            "platform": platform
        })
        if not doc:
            return None

        doc["_id"] = str(doc["_id"])
        doc["business_id"] = str(doc["business_id"])
        doc["user__id"] = str(doc["user__id"])

        doc["access_token_plain"] = _dec(doc.get("access_token"))
        doc["refresh_token_plain"] = _dec(doc.get("refresh_token"))
        return doc
    
    @classmethod
    def upsert_account(cls, business_id, user__id, platform, doc: dict):
        col = db_ext.get_collection(cls.collection_name)
        doc["updated_at"] = datetime.utcnow()

        res = col.update_one(
            {"business_id": ObjectId(business_id), "user__id": ObjectId(user__id), "platform": platform},
            {"$set": doc, "$setOnInsert": {"created_at": datetime.utcnow(), "platform": platform}},
            upsert=True,
        )
        return res.acknowledged