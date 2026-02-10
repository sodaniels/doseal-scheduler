# app/models/social/pinterest_ad_account.py

from datetime import datetime, timezone
from bson import ObjectId
from typing import Dict, Any, List, Optional

from ..base_model import BaseModel
from ...extensions import db as db_ext
from ...utils.crypt import encrypt_data, decrypt_data
from ...utils.logger import Log


class PinterestAdAccount(BaseModel):
    """
    Stores connected Pinterest Ad Accounts for a business.
    """
    
    collection_name = "pinterest_ad_accounts"
    
    STATUS_ACTIVE = "active"
    STATUS_DISABLED = "disabled"
    STATUS_DISCONNECTED = "disconnected"

    def __init__(
        self,
        business_id,
        user__id,
        ad_account_id,
        ad_account_name=None,
        currency="USD",
        country=None,
        owner_username=None,
        access_token_plain=None,
        refresh_token_plain=None,
        token_expires_at=None,
        status=None,
        permissions=None,
        meta=None,
        **kwargs,
    ):
        super().__init__(business_id=business_id, user__id=user__id, **kwargs)
        
        self.ad_account_id = ad_account_id
        self.ad_account_name = ad_account_name
        self.currency = currency
        self.country = country
        self.owner_username = owner_username
        
        self.access_token = encrypt_data(access_token_plain) if access_token_plain else None
        self.refresh_token = encrypt_data(refresh_token_plain) if refresh_token_plain else None
        self.token_expires_at = token_expires_at
        
        self.status = status or self.STATUS_ACTIVE
        self.permissions = permissions or []
        self.meta = meta or {}
        
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self):
        return {
            "business_id": self.business_id,
            "user__id": self.user__id,
            "ad_account_id": self.ad_account_id,
            "ad_account_name": self.ad_account_name,
            "currency": self.currency,
            "country": self.country,
            "owner_username": self.owner_username,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_expires_at": self.token_expires_at,
            "status": self.status,
            "permissions": self.permissions,
            "meta": self.meta,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def _oid_str(cls, doc):
        if not doc:
            return None
        for key in ["_id", "business_id", "user__id"]:
            if key in doc and doc[key]:
                doc[key] = str(doc[key])
        return doc

    # -------------------- CRUD --------------------

    @classmethod
    def create(cls, data: dict) -> dict:
        col = db_ext.get_collection(cls.collection_name)
        
        doc = {
            "business_id": ObjectId(str(data["business_id"])),
            "user__id": ObjectId(str(data["user__id"])),
            "ad_account_id": data["ad_account_id"],
            "ad_account_name": data.get("ad_account_name"),
            "currency": data.get("currency", "USD"),
            "country": data.get("country"),
            "owner_username": data.get("owner_username"),
            "access_token": encrypt_data(data["access_token"]) if data.get("access_token") else None,
            "refresh_token": encrypt_data(data["refresh_token"]) if data.get("refresh_token") else None,
            "token_expires_at": data.get("token_expires_at"),
            "status": data.get("status", cls.STATUS_ACTIVE),
            "permissions": data.get("permissions", []),
            "meta": data.get("meta", {}),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        
        result = col.insert_one(doc)
        doc["_id"] = result.inserted_id
        return cls._oid_str(doc)

    @classmethod
    def get_by_id(cls, account_id: str, business_id: str) -> Optional[dict]:
        col = db_ext.get_collection(cls.collection_name)
        doc = col.find_one({
            "_id": ObjectId(str(account_id)),
            "business_id": ObjectId(str(business_id)),
        })
        if doc:
            doc["access_token_plain"] = decrypt_data(doc.get("access_token")) if doc.get("access_token") else None
            doc["refresh_token_plain"] = decrypt_data(doc.get("refresh_token")) if doc.get("refresh_token") else None
        return cls._oid_str(doc)

    @classmethod
    def get_by_ad_account_id(cls, business_id: str, ad_account_id: str) -> Optional[dict]:
        col = db_ext.get_collection(cls.collection_name)
        doc = col.find_one({
            "business_id": ObjectId(str(business_id)),
            "ad_account_id": ad_account_id,
        })
        if doc:
            doc["access_token_plain"] = decrypt_data(doc.get("access_token")) if doc.get("access_token") else None
            doc["refresh_token_plain"] = decrypt_data(doc.get("refresh_token")) if doc.get("refresh_token") else None
        return cls._oid_str(doc)

    @classmethod
    def list_by_business(cls, business_id: str, status: str = None) -> List[dict]:
        col = db_ext.get_collection(cls.collection_name)
        
        query = {"business_id": ObjectId(str(business_id))}
        if status:
            query["status"] = status
        
        items = list(col.find(query).sort("created_at", -1))
        
        for doc in items:
            cls._oid_str(doc)
            doc.pop("access_token", None)
            doc.pop("refresh_token", None)
        
        return items

    @classmethod
    def update(cls, account_id: str, business_id: str, updates: dict) -> bool:
        col = db_ext.get_collection(cls.collection_name)
        
        updates = dict(updates)
        updates.pop("_id", None)
        updates.pop("business_id", None)
        updates.pop("user__id", None)
        updates.pop("created_at", None)
        
        if updates.get("access_token"):
            updates["access_token"] = encrypt_data(updates["access_token"])
        if updates.get("refresh_token"):
            updates["refresh_token"] = encrypt_data(updates["refresh_token"])
        
        updates["updated_at"] = datetime.now(timezone.utc)
        
        result = col.update_one(
            {
                "_id": ObjectId(str(account_id)),
                "business_id": ObjectId(str(business_id)),
            },
            {"$set": updates}
        )
        return result.modified_count > 0

    @classmethod
    def delete(cls, account_id: str, business_id: str) -> bool:
        col = db_ext.get_collection(cls.collection_name)
        result = col.delete_one({
            "_id": ObjectId(str(account_id)),
            "business_id": ObjectId(str(business_id)),
        })
        return result.deleted_count > 0

    @classmethod
    def ensure_indexes(cls):
        col = db_ext.get_collection(cls.collection_name)
        col.create_index([("business_id", 1), ("ad_account_id", 1)], unique=True)
        col.create_index([("business_id", 1), ("status", 1)])
        return True


class PinterestAdCampaign(BaseModel):
    """
    Stores Pinterest ad campaigns created through the platform.
    """
    
    collection_name = "pinterest_ad_campaigns"
    
    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_ARCHIVED = "archived"
    
    OBJECTIVE_AWARENESS = "AWARENESS"
    OBJECTIVE_CONSIDERATION = "CONSIDERATION"
    OBJECTIVE_VIDEO_VIEW = "VIDEO_VIEW"
    OBJECTIVE_CONVERSIONS = "WEB_CONVERSION"
    
    BUDGET_DAILY = "DAILY"
    BUDGET_LIFETIME = "LIFETIME"

    def __init__(
        self,
        business_id,
        user__id,
        ad_account_id,
        campaign_name=None,
        objective=None,
        budget_type=None,
        budget_amount=None,
        currency="USD",
        start_time=None,
        end_time=None,
        targeting_spec=None,
        pin_id=None,
        destination_url=None,
        pinterest_campaign_id=None,
        pinterest_ad_group_id=None,
        pinterest_ad_id=None,
        status=None,
        error=None,
        results=None,
        meta=None,
        **kwargs,
    ):
        super().__init__(business_id=business_id, user__id=user__id, **kwargs)
        
        self.ad_account_id = ad_account_id
        self.campaign_name = campaign_name
        self.objective = objective or self.OBJECTIVE_AWARENESS
        
        self.budget_type = budget_type or self.BUDGET_LIFETIME
        self.budget_amount = budget_amount  # in cents
        self.currency = currency
        
        self.start_time = start_time
        self.end_time = end_time
        
        self.targeting_spec = targeting_spec or {}
        
        self.pin_id = pin_id
        self.destination_url = destination_url
        
        # Pinterest IDs
        self.pinterest_campaign_id = pinterest_campaign_id
        self.pinterest_ad_group_id = pinterest_ad_group_id
        self.pinterest_ad_id = pinterest_ad_id
        
        self.status = status or self.STATUS_DRAFT
        self.error = error
        
        self.results = results or {
            "impressions": 0,
            "clicks": 0,
            "saves": 0,
            "spend_micro": 0,
            "ctr": 0,
            "cpc_micro": 0,
            "cpm_micro": 0,
        }
        
        self.meta = meta or {}
        
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self):
        return {
            "business_id": self.business_id,
            "user__id": self.user__id,
            "ad_account_id": self.ad_account_id,
            "campaign_name": self.campaign_name,
            "objective": self.objective,
            "budget_type": self.budget_type,
            "budget_amount": self.budget_amount,
            "currency": self.currency,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "targeting_spec": self.targeting_spec,
            "pin_id": self.pin_id,
            "destination_url": self.destination_url,
            "pinterest_campaign_id": self.pinterest_campaign_id,
            "pinterest_ad_group_id": self.pinterest_ad_group_id,
            "pinterest_ad_id": self.pinterest_ad_id,
            "status": self.status,
            "error": self.error,
            "results": self.results,
            "meta": self.meta,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def _oid_str(cls, doc):
        if not doc:
            return None
        for key in ["_id", "business_id", "user__id"]:
            if key in doc and doc[key]:
                doc[key] = str(doc[key])
        return doc

    @classmethod
    def _parse_dt(cls, value):
        if not value:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return None

    @classmethod
    def create(cls, data: dict) -> dict:
        col = db_ext.get_collection(cls.collection_name)
        
        doc = {
            "business_id": ObjectId(str(data["business_id"])),
            "user__id": ObjectId(str(data["user__id"])),
            "ad_account_id": data["ad_account_id"],
            "campaign_name": data.get("campaign_name"),
            "objective": data.get("objective", cls.OBJECTIVE_AWARENESS),
            "budget_type": data.get("budget_type", cls.BUDGET_LIFETIME),
            "budget_amount": data.get("budget_amount"),
            "currency": data.get("currency", "USD"),
            "start_time": cls._parse_dt(data.get("start_time")),
            "end_time": cls._parse_dt(data.get("end_time")),
            "targeting_spec": data.get("targeting_spec", {}),
            "pin_id": data.get("pin_id"),
            "destination_url": data.get("destination_url"),
            "pinterest_campaign_id": data.get("pinterest_campaign_id"),
            "pinterest_ad_group_id": data.get("pinterest_ad_group_id"),
            "pinterest_ad_id": data.get("pinterest_ad_id"),
            "status": data.get("status", cls.STATUS_DRAFT),
            "error": data.get("error"),
            "results": data.get("results", {
                "impressions": 0, "clicks": 0, "saves": 0,
                "spend_micro": 0, "ctr": 0, "cpc_micro": 0, "cpm_micro": 0,
            }),
            "meta": data.get("meta", {}),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        
        result = col.insert_one(doc)
        doc["_id"] = result.inserted_id
        return cls._oid_str(doc)

    @classmethod
    def get_by_id(cls, campaign_id: str, business_id: str) -> Optional[dict]:
        col = db_ext.get_collection(cls.collection_name)
        doc = col.find_one({
            "_id": ObjectId(str(campaign_id)),
            "business_id": ObjectId(str(business_id)),
        })
        return cls._oid_str(doc)

    @classmethod
    def list_by_business(
        cls,
        business_id: str,
        status: str = None,
        page: int = 1,
        per_page: int = 20,
    ) -> Dict[str, Any]:
        col = db_ext.get_collection(cls.collection_name)
        
        query = {"business_id": ObjectId(str(business_id))}
        if status:
            query["status"] = status
        
        total_count = col.count_documents(query)
        
        skip = (page - 1) * per_page
        items = list(
            col.find(query)
            .sort("created_at", -1)
            .skip(skip)
            .limit(per_page)
        )
        
        for doc in items:
            cls._oid_str(doc)
        
        return {
            "items": items,
            "total_count": total_count,
            "total_pages": (total_count + per_page - 1) // per_page,
            "current_page": page,
            "per_page": per_page,
        }

    @classmethod
    def update(cls, campaign_id: str, business_id: str, updates: dict) -> bool:
        col = db_ext.get_collection(cls.collection_name)
        
        updates = dict(updates)
        updates.pop("_id", None)
        updates.pop("business_id", None)
        updates.pop("user__id", None)
        updates.pop("created_at", None)
        
        updates["updated_at"] = datetime.now(timezone.utc)
        
        result = col.update_one(
            {
                "_id": ObjectId(str(campaign_id)),
                "business_id": ObjectId(str(business_id)),
            },
            {"$set": updates}
        )
        return result.modified_count > 0

    @classmethod
    def update_status(cls, campaign_id: str, business_id: str, status: str, error: str = None) -> bool:
        updates = {"status": status}
        if error is not None:
            updates["error"] = error
        return cls.update(campaign_id, business_id, updates)

    @classmethod
    def update_results(cls, campaign_id: str, business_id: str, results: dict) -> bool:
        return cls.update(campaign_id, business_id, {"results": results})

    @classmethod
    def ensure_indexes(cls):
        col = db_ext.get_collection(cls.collection_name)
        col.create_index([("business_id", 1), ("status", 1), ("created_at", -1)])
        col.create_index([("business_id", 1), ("ad_account_id", 1)])
        col.create_index([("pinterest_campaign_id", 1)])
        return True