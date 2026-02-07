# app/models/notifications/notification_settings.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId
from pymongo import ReturnDocument

from ..base_model import BaseModel
from ...extensions import db as db_ext
from ...utils.logger import Log

from ...services.notifications.notification_config import build_default_settings


class NotificationSettings(BaseModel):
    """
    Collection: notification_settings

    One doc per (business_id, user__id).
    """
    collection_name = "notification_settings"

    @staticmethod
    def _utc_now():
        return datetime.now(timezone.utc)

    @classmethod
    def ensure_indexes(cls) -> bool:
        col = db_ext.get_collection(cls.collection_name)
        col.create_index([("business_id", 1), ("user__id", 1)], unique=True)
        col.create_index([("updated_at", -1)])
        return True

    @classmethod
    def get_or_create_defaults(cls, *, business_id: str, user__id: str) -> Dict[str, Any]:
        col = db_ext.get_collection(cls.collection_name)

        q = {"business_id": ObjectId(str(business_id)), "user__id": ObjectId(str(user__id))}
        doc = col.find_one(q)
        if doc:
            doc["_id"] = str(doc["_id"])
            doc["business_id"] = str(doc["business_id"])
            doc["user__id"] = str(doc["user__id"])
            # safety: ensure channels exist
            doc.setdefault("channels", build_default_settings())
            return doc

        now = cls._utc_now()
        new_doc = {
            "business_id": ObjectId(str(business_id)),
            "user__id": ObjectId(str(user__id)),
            "channels": build_default_settings(),
            "created_at": now,
            "updated_at": now,
        }
        res = col.insert_one(new_doc)
        new_doc["_id"] = str(res.inserted_id)
        new_doc["business_id"] = str(new_doc["business_id"])
        new_doc["user__id"] = str(new_doc["user__id"])
        return new_doc

    @classmethod
    def patch_settings(
        cls,
        *,
        business_id: str,
        user__id: str,
        patch: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        patch shape:
          {
            "channels": {
              "email": {"item_key": true/false, ...},
              "in_app": {"item_key": true/false, ...}
            }
          }

        Only fields provided are updated (partial patch).
        """
        log_tag = "[notification_settings.py][patch_settings]"
        col = db_ext.get_collection(cls.collection_name)

        # ensure doc exists first
        _ = cls.get_or_create_defaults(business_id=business_id, user__id=user__id)

        updates: Dict[str, Any] = {}
        channels = (patch or {}).get("channels") or {}

        for channel_key in ("email", "in_app"):
            ch_patch = channels.get(channel_key)
            if not isinstance(ch_patch, dict):
                continue

            for item_key, enabled in ch_patch.items():
                # store only booleans
                if not isinstance(enabled, bool):
                    continue
                updates[f"channels.{channel_key}.{item_key}"] = enabled

        if not updates:
            # nothing to change; return current doc
            return cls.get_or_create_defaults(business_id=business_id, user__id=user__id)

        updates["updated_at"] = cls._utc_now()

        q = {"business_id": ObjectId(str(business_id)), "user__id": ObjectId(str(user__id))}
        doc = col.find_one_and_update(
            q,
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )

        if not doc:
            Log.info(f"{log_tag} update failed unexpectedly. business_id={business_id} user__id={user__id}")
            return cls.get_or_create_defaults(business_id=business_id, user__id=user__id)

        doc["_id"] = str(doc["_id"])
        doc["business_id"] = str(doc["business_id"])
        doc["user__id"] = str(doc["user__id"])
        return doc