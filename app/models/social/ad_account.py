# app/models/social/ad_account.py

from datetime import datetime, timezone
from bson import ObjectId
from typing import Dict, Any, List, Optional

from ..base_model import BaseModel
from ...extensions import db as db_ext
from ...utils.crypt import encrypt_data, decrypt_data
from ...utils.logger import Log


class AdAccount(BaseModel):
    """
    Stores connected Facebook Ad Accounts for a business.
    
    One business can have multiple ad accounts.
    Each ad account can be linked to one or more pages for boosting.
    """
    
    collection_name = "social_ad_accounts"
    
    STATUS_ACTIVE = "active"
    STATUS_DISABLED = "disabled"
    STATUS_PENDING_REVIEW = "pending_review"
    STATUS_DISCONNECTED = "disconnected"
    
    # Facebook Ad Account Status Codes
    FB_ACCOUNT_STATUS = {
        1: "ACTIVE",
        2: "DISABLED",
        3: "UNSETTLED",
        7: "PENDING_RISK_REVIEW",
        8: "PENDING_SETTLEMENT",
        9: "IN_GRACE_PERIOD",
        100: "PENDING_CLOSURE",
        101: "CLOSED",
        201: "ANY_ACTIVE",
        202: "ANY_CLOSED",
    }

    def __init__(
        self,
        business_id,
        user__id,
        ad_account_id,
        ad_account_name=None,
        currency="USD",
        timezone_name=None,
        fb_account_status=None,
        page_id=None,
        page_name=None,
        business_manager_id=None,
        access_token_plain=None,
        status=None,
        meta=None,
        **kwargs,
    ):
        super().__init__(business_id=business_id, user__id=user__id, **kwargs)
        
        self.ad_account_id = ad_account_id  # e.g., "act_123456789"
        self.ad_account_name = ad_account_name
        self.currency = currency
        self.timezone_name = timezone_name
        self.fb_account_status = fb_account_status
        
        self.page_id = page_id
        self.page_name = page_name
        self.business_manager_id = business_manager_id
        
        self.access_token = encrypt_data(access_token_plain) if access_token_plain else None
        
        self.status = status or self.STATUS_ACTIVE
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
            "timezone_name": self.timezone_name,
            "fb_account_status": self.fb_account_status,
            "page_id": self.page_id,
            "page_name": self.page_name,
            "business_manager_id": self.business_manager_id,
            "access_token": self.access_token,
            "status": self.status,
            "meta": self.meta,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def _oid_str(cls, doc):
        if not doc:
            return None
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        if "business_id" in doc:
            doc["business_id"] = str(doc["business_id"])
        if "user__id" in doc:
            doc["user__id"] = str(doc["user__id"])
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
            "timezone_name": data.get("timezone_name"),
            "fb_account_status": data.get("fb_account_status"),
            "page_id": data.get("page_id"),
            "page_name": data.get("page_name"),
            "business_manager_id": data.get("business_manager_id"),
            "access_token": encrypt_data(data["access_token"]) if data.get("access_token") else None,
            "status": data.get("status", cls.STATUS_ACTIVE),
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
        return cls._oid_str(doc)

    @classmethod
    def get_by_ad_account_id(cls, business_id: str, ad_account_id: str) -> Optional[dict]:
        col = db_ext.get_collection(cls.collection_name)
        
        # Ensure ad_account_id has "act_" prefix
        if not ad_account_id.startswith("act_"):
            ad_account_id = f"act_{ad_account_id}"
        
        doc = col.find_one({
            "business_id": ObjectId(str(business_id)),
            "ad_account_id": ad_account_id,
        })
        if doc:
            doc["access_token_plain"] = decrypt_data(doc.get("access_token")) if doc.get("access_token") else None
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
            doc.pop("access_token", None)  # Don't expose token in list
        
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
        col.create_index([("business_id", 1), ("page_id", 1)])
        return True


class AdCampaign(BaseModel):
    """
    Stores ad campaigns created through the platform.
    
    Can be linked to a scheduled post (for boosting) or standalone.
    """
    
    collection_name = "social_ad_campaigns"
    
    # Campaign Status
    STATUS_DRAFT = "draft"
    STATUS_PENDING = "pending"
    STATUS_ACTIVE = "active"
    STATUS_PAUSED = "paused"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_DELETED = "deleted"
    
    # Campaign Objectives (ODAX)
    OBJECTIVE_AWARENESS = "OUTCOME_AWARENESS"
    OBJECTIVE_TRAFFIC = "OUTCOME_TRAFFIC"
    OBJECTIVE_ENGAGEMENT = "OUTCOME_ENGAGEMENT"
    OBJECTIVE_LEADS = "OUTCOME_LEADS"
    OBJECTIVE_SALES = "OUTCOME_SALES"
    OBJECTIVE_APP_PROMOTION = "OUTCOME_APP_PROMOTION"
    
    # Budget Types
    BUDGET_DAILY = "daily"
    BUDGET_LIFETIME = "lifetime"

    def __init__(
        self,
        business_id,
        user__id,
        ad_account_id,
        page_id,
        campaign_name=None,
        objective=None,
        budget_type=None,
        budget_amount=None,
        currency="USD",
        start_time=None,
        end_time=None,
        targeting=None,
        scheduled_post_id=None,
        post_id=None,
        fb_campaign_id=None,
        fb_adset_id=None,
        fb_ad_id=None,
        fb_creative_id=None,
        status=None,
        error=None,
        results=None,
        meta=None,
        **kwargs,
    ):
        super().__init__(business_id=business_id, user__id=user__id, **kwargs)
        
        self.ad_account_id = ad_account_id
        self.page_id = page_id
        
        self.campaign_name = campaign_name
        self.objective = objective or self.OBJECTIVE_ENGAGEMENT
        
        self.budget_type = budget_type or self.BUDGET_DAILY
        self.budget_amount = budget_amount  # in cents
        self.currency = currency
        
        self.start_time = start_time
        self.end_time = end_time
        
        self.targeting = targeting or {}
        
        # Link to scheduled post (if boosting)
        self.scheduled_post_id = scheduled_post_id
        self.post_id = post_id  # Facebook post ID to boost
        
        # Facebook IDs (populated after creation)
        self.fb_campaign_id = fb_campaign_id
        self.fb_adset_id = fb_adset_id
        self.fb_ad_id = fb_ad_id
        self.fb_creative_id = fb_creative_id
        
        self.status = status or self.STATUS_DRAFT
        self.error = error
        
        # Performance results
        self.results = results or {
            "impressions": 0,
            "reach": 0,
            "clicks": 0,
            "spend": 0,
            "cpc": 0,
            "cpm": 0,
            "ctr": 0,
            "actions": [],
        }
        
        self.meta = meta or {}
        
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self):
        return {
            "business_id": self.business_id,
            "user__id": self.user__id,
            "ad_account_id": self.ad_account_id,
            "page_id": self.page_id,
            "campaign_name": self.campaign_name,
            "objective": self.objective,
            "budget_type": self.budget_type,
            "budget_amount": self.budget_amount,
            "currency": self.currency,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "targeting": self.targeting,
            "scheduled_post_id": self.scheduled_post_id,
            "post_id": self.post_id,
            "fb_campaign_id": self.fb_campaign_id,
            "fb_adset_id": self.fb_adset_id,
            "fb_ad_id": self.fb_ad_id,
            "fb_creative_id": self.fb_creative_id,
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
        for key in ["_id", "business_id", "user__id", "scheduled_post_id"]:
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
        return None

    # -------------------- CRUD --------------------

    @classmethod
    def create(cls, data: dict) -> dict:
        col = db_ext.get_collection(cls.collection_name)
        
        doc = {
            "business_id": ObjectId(str(data["business_id"])),
            "user__id": ObjectId(str(data["user__id"])),
            "ad_account_id": data["ad_account_id"],
            "page_id": data["page_id"],
            "campaign_name": data.get("campaign_name"),
            "objective": data.get("objective", cls.OBJECTIVE_ENGAGEMENT),
            "budget_type": data.get("budget_type", cls.BUDGET_DAILY),
            "budget_amount": data.get("budget_amount"),
            "currency": data.get("currency", "USD"),
            "start_time": cls._parse_dt(data.get("start_time")),
            "end_time": cls._parse_dt(data.get("end_time")),
            "targeting": data.get("targeting", {}),
            "scheduled_post_id": ObjectId(str(data["scheduled_post_id"])) if data.get("scheduled_post_id") else None,
            "post_id": data.get("post_id"),
            "fb_campaign_id": data.get("fb_campaign_id"),
            "fb_adset_id": data.get("fb_adset_id"),
            "fb_ad_id": data.get("fb_ad_id"),
            "fb_creative_id": data.get("fb_creative_id"),
            "status": data.get("status", cls.STATUS_DRAFT),
            "error": data.get("error"),
            "results": data.get("results", {
                "impressions": 0, "reach": 0, "clicks": 0,
                "spend": 0, "cpc": 0, "cpm": 0, "ctr": 0, "actions": [],
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
    def get_by_scheduled_post(cls, scheduled_post_id: str, business_id: str) -> Optional[dict]:
        col = db_ext.get_collection(cls.collection_name)
        doc = col.find_one({
            "scheduled_post_id": ObjectId(str(scheduled_post_id)),
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
    def update_status(
        cls,
        campaign_id: str,
        business_id: str,
        status: str,
        error: str = None,
    ) -> bool:
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
        col.create_index([("business_id", 1), ("scheduled_post_id", 1)])
        col.create_index([("business_id", 1), ("ad_account_id", 1)])
        col.create_index([("fb_campaign_id", 1)])
        return True