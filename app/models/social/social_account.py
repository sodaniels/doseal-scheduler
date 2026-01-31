from datetime import datetime
from bson import ObjectId

from ..base_model import BaseModel
from ...extensions import db as db_ext
from ...utils.crypt import encrypt_data, decrypt_data
from ...utils.logger import Log
from typing import List, Dict, Any, Optional


class SocialAccount(BaseModel):
    """
    One connected destination per document.

    Unique key recommendation:
      (business_id, user__id, platform, destination_id)

    Examples:
      - Facebook Page: platform="facebook", destination_type="page", destination_id="<PAGE_ID>"
      - Instagram:     platform="instagram", destination_type="ig_user", destination_id="<IG_USER_ID>"
      - LinkedIn:      platform="linkedin", destination_type="author", destination_id="<AUTHOR_URN>"
      - Pinterest:     platform="pinterest", destination_type="board", destination_id="<BOARD_ID>"
      - YouTube:       platform="youtube", destination_type="channel", destination_id="<CHANNEL_ID>"
      - X:             platform="x", destination_type="user", destination_id="<X_USER_ID>"
      - TikTok:        platform="tiktok", destination_type="user", destination_id="<OPEN_ID>"
    """

    collection_name = "social_accounts"

    def __init__(
        self,
        business_id,
        user__id,
        platform,
        destination_id,
        destination_type,
        destination_name=None,
        access_token_plain=None,
        refresh_token_plain=None,
        token_expires_at=None,   # datetime or ISO string
        scopes=None,
        platform_user_id=None,
        platform_username=None,
        meta=None,
        **kwargs,
    ):
        super().__init__(business_id=business_id, user__id=user__id, **kwargs)

        self.platform = platform

        self.destination_id = destination_id
        self.destination_type = destination_type
        self.destination_name = destination_name

        # Store encrypted tokens at rest
        self.access_token = encrypt_data(access_token_plain) if access_token_plain else None
        self.refresh_token = encrypt_data(refresh_token_plain) if refresh_token_plain else None

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

            "destination_id": self.destination_id,
            "destination_type": self.destination_type,
            "destination_name": self.destination_name,

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

    # -------------------- Queries --------------------

    @classmethod
    def get_destination(cls, business_id, user__id, platform, destination_id):
        col = db_ext.get_collection(cls.collection_name)
        doc = col.find_one({
            "business_id": ObjectId(business_id),
            "user__id": ObjectId(user__id),
            "platform": platform,
            "destination_id": destination_id,
        })
        if not doc:
            return None

        doc["_id"] = str(doc["_id"])
        doc["business_id"] = str(doc["business_id"])
        doc["user__id"] = str(doc["user__id"])

        # Decrypt on read for internal use only
        doc["access_token_plain"] = decrypt_data(doc.get("access_token")) if doc.get("access_token") else None
        doc["refresh_token_plain"] = decrypt_data(doc.get("refresh_token")) if doc.get("refresh_token") else None
        return doc

    @classmethod
    def list_destinations(cls, business_id, user__id, platform):
        col = db_ext.get_collection(cls.collection_name)
        cursor = col.find({
            "business_id": ObjectId(business_id),
            "user__id": ObjectId(user__id),
            "platform": platform,
        }).sort("created_at", -1)

        items = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            doc["business_id"] = str(doc["business_id"])
            doc["user__id"] = str(doc["user__id"])
            # DO NOT include decrypted tokens in list responses
            doc.pop("access_token", None)
            doc.pop("refresh_token", None)
            items.append(doc)
        return items

    # -------------------- Write helpers --------------------
    
    @classmethod
    def get_all_by_business_id(cls, business_id: str) -> List[Dict[str, Any]]:
        """
        Return all social accounts for a business (plain docs).
        """
        bid = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
        col = db_ext.get_collection(cls.collection_name)
        items = list(col.find({"business_id": bid}).sort("created_at", -1))

        # Normalise IDs
        for x in items:
            x["_id"] = str(x["_id"])
            x["business_id"] = str(x["business_id"])
            if x.get("user__id") is not None:
                x["user__id"] = str(x["user__id"])
        return items

    @classmethod
    def upsert_destination(
        cls,
        business_id,
        user__id,
        platform,
        destination_id,
        destination_type,
        destination_name=None,
        access_token_plain=None,
        refresh_token_plain=None,
        token_expires_at=None,
        scopes=None,
        platform_user_id=None,
        platform_username=None,
        meta=None,
    ):
        col = db_ext.get_collection(cls.collection_name)

        update_doc = {
            "platform": platform,
            "destination_id": destination_id,
            "destination_type": destination_type,
            "destination_name": destination_name,

            "token_expires_at": token_expires_at,
            "scopes": scopes or [],
            "platform_user_id": platform_user_id,
            "platform_username": platform_username,
            "meta": meta or {},

            "updated_at": datetime.utcnow(),
        }

        if access_token_plain:
            update_doc["access_token"] = encrypt_data(access_token_plain)
        if refresh_token_plain:
            update_doc["refresh_token"] = encrypt_data(refresh_token_plain)

        res = col.update_one(
            {
                "business_id": ObjectId(business_id),
                "user__id": ObjectId(user__id),
                "platform": platform,
                "destination_id": destination_id,
            },
            {
                "$set": update_doc,
                "$setOnInsert": {
                    "business_id": ObjectId(business_id),
                    "user__id": ObjectId(user__id),
                    "created_at": datetime.utcnow(),
                }
            },
            upsert=True
        )
        return res.acknowledged

    @classmethod
    def ensure_indexes(cls):
        col = db_ext.get_collection(cls.collection_name)
        col.create_index(
            [("business_id", 1), ("user__id", 1), ("platform", 1), ("destination_id", 1)],
            unique=True
        )
        col.create_index([("business_id", 1), ("user__id", 1), ("platform", 1), ("created_at", -1)])
        return True
    
    