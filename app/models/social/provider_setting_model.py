from __future__ import annotations

from datetime import datetime
from bson import ObjectId

from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.logger import Log


class ProviderSetting(BaseModel):
    """
    Stores default integration provider choices for a business or branch.
    """

    collection_name = "business_provider_settings"
    _permission_module = "integrations"

    SUPPORTED_KEYS = [
        "default_payment_provider",
        "default_sms_provider",
        "default_email_provider",
        "default_whatsapp_provider",
    ]

    def __init__(
        self,
        business_id,
        branch_id=None,
        default_payment_provider=None,
        default_sms_provider=None,
        default_email_provider=None,
        default_whatsapp_provider=None,
        user_id=None,
        user__id=None,
        **kwargs,
    ):
        super().__init__(user__id=user__id, user_id=user_id, business_id=business_id, **kwargs)

        self.business_id = ObjectId(business_id) if business_id else None
        self.branch_id = ObjectId(branch_id) if branch_id else None

        self.default_payment_provider = default_payment_provider
        self.default_sms_provider = default_sms_provider
        self.default_email_provider = default_email_provider
        self.default_whatsapp_provider = default_whatsapp_provider

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        doc = {
            "business_id": self.business_id,
            "branch_id": self.branch_id,
            "default_payment_provider": getattr(self, "default_payment_provider", None),
            "default_sms_provider": getattr(self, "default_sms_provider", None),
            "default_email_provider": getattr(self, "default_email_provider", None),
            "default_whatsapp_provider": getattr(self, "default_whatsapp_provider", None),
            "created_at": getattr(self, "created_at", None),
            "updated_at": getattr(self, "updated_at", None),
        }
        return {k: v for k, v in doc.items() if v is not None}

    @classmethod
    def _normalise(cls, doc):
        if not doc:
            return None

        if doc.get("_id"):
            doc["_id"] = str(doc["_id"])
        if doc.get("business_id"):
            doc["business_id"] = str(doc["business_id"])
        if doc.get("branch_id"):
            doc["branch_id"] = str(doc["branch_id"])

        return doc

    @classmethod
    def get_for_business(cls, business_id, branch_id=None, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)

            # 1. Branch-specific settings (if branch_id provided)
            if branch_id:
                branch_doc = c.find_one({
                    "business_id": ObjectId(business_id),
                    "branch_id": ObjectId(branch_id),
                })
                if branch_doc:
                    return cls._normalise(branch_doc)

            # 2. Business-level settings (no branch)
            biz_doc = c.find_one({
                "business_id": ObjectId(business_id),
                "branch_id": {"$in": [None, ""]},
            })
            if not biz_doc:
                biz_doc = c.find_one({
                    "business_id": ObjectId(business_id),
                    "branch_id": {"$exists": False},
                })

            if biz_doc:
                return cls._normalise(biz_doc)

            # 3. Fallback: any setting for this business (first available)
            any_doc = c.find_one(
                {"business_id": ObjectId(business_id)},
                sort=[("updated_at", -1)],
            )
            return cls._normalise(any_doc)

        except Exception as e:
            Log.error(f"[ProviderSetting.get_for_business] {e}")
            return None
    
    @classmethod
    def upsert_for_business(cls, business_id, branch_id=None, processing_callback=False, **updates):
        cls._enforce_permission("update", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)

            safe_updates = {
                k: v for k, v in updates.items()
                if k in cls.SUPPORTED_KEYS and v is not None
            }
            safe_updates["updated_at"] = datetime.utcnow()

            query = {"business_id": ObjectId(business_id)}
            if branch_id:
                query["branch_id"] = ObjectId(branch_id)
            else:
                query["branch_id"] = {"$exists": False}

            set_on_insert = {
                "business_id": ObjectId(business_id),
                "created_at": datetime.utcnow(),
            }
            if branch_id:
                set_on_insert["branch_id"] = ObjectId(branch_id)

            c.update_one(
                query,
                {
                    "$set": safe_updates,
                    "$setOnInsert": set_on_insert,
                },
                upsert=True,
            )

            return cls.get_for_business(business_id, branch_id=branch_id, processing_callback=True)
        except Exception as e:
            Log.error(f"[ProviderSetting.upsert_for_business] {e}")
            return None

    @classmethod
    def clear_defaults(cls, business_id, branch_id=None, keys=None, processing_callback=False):
        cls._enforce_permission("update", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)

            keys = keys or []
            unset_doc = {k: "" for k in keys if k in cls.SUPPORTED_KEYS}
            if not unset_doc:
                return cls.get_for_business(business_id, branch_id=branch_id, processing_callback=True)

            query = {"business_id": ObjectId(business_id)}
            if branch_id:
                query["branch_id"] = ObjectId(branch_id)
            else:
                query["branch_id"] = {"$exists": False}

            c.update_one(
                query,
                {
                    "$unset": unset_doc,
                    "$set": {"updated_at": datetime.utcnow()},
                },
            )

            return cls.get_for_business(business_id, branch_id=branch_id, processing_callback=True)
        except Exception as e:
            Log.error(f"[ProviderSetting.clear_defaults] {e}")
            return None

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("business_id", 1), ("branch_id", 1)], unique=True)
            return True
        except Exception as e:
            Log.error(f"[ProviderSetting.create_indexes] {e}")
            return False