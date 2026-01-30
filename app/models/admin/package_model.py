# app/models/package.py

from __future__ import annotations

from datetime import datetime
from bson import ObjectId
from ...models.base_model import BaseModel
from typing import Any, Dict, Optional
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.logger import Log


class Package(BaseModel):
    """
    Subscription package/plan model (Social Media Management SaaS).

    Hootsuite-style:
      - per-user pricing (price_model = "per_user")
      - limits centered around: social accounts, scheduling, inbox, analytics, listening
      - enterprise has custom price (price=None)
    """

    collection_name = "packages"

    # -------------------------
    # Package Tiers (UPDATED)
    # -------------------------
    TIER_STANDARD = "Standard"
    TIER_ADVANCED = "Advanced"
    TIER_ENTERPRISE = "Enterprise"

    # -------------------------
    # Billing Periods
    # -------------------------
    PERIOD_MONTHLY = "monthly"
    PERIOD_QUARTERLY = "quarterly"
    PERIOD_YEARLY = "yearly"
    PERIOD_LIFETIME = "lifetime"
    PERIOD_CUSTOM = "custom"

    # -------------------------
    # Price Model (NEW)
    # -------------------------
    PRICE_MODEL_PER_USER = "per_user"
    PRICE_MODEL_FLAT = "flat"
    PRICE_MODEL_CUSTOM = "custom"

    # -------------------------
    # Status
    # -------------------------
    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_DEPRECATED = "Deprecated"

    # -------------------------
    # Fields to decrypt
    # -------------------------
    FIELDS_TO_DECRYPT = [
        "name",
        "description",
        "tier",
        "billing_period",
        "currency",
        "status",
        "price",       # encrypted string
        "setup_fee",   # encrypted string
        "price_model", # encrypted string (NEW)
    ]

    def __init__(
        self,
        name: str,
        tier: str,
        billing_period: str,
        price: Optional[float],
        currency: str = "GBP",

        # Pricing model (NEW)
        price_model: str = PRICE_MODEL_PER_USER,

        # Social limits (UPDATED)
        max_users: Optional[int] = None,                # seats/users
        max_social_accounts: Optional[int] = None,      # connected accounts
        bulk_schedule_limit: Optional[int] = None,      # e.g. 350 in Advanced
        competitor_tracking: Optional[int] = None,      # e.g. 5 / 20
        history_search_days: Optional[int] = None,      # e.g. 7 / 30

        # Feature flags (UPDATED)
        features: Optional[Dict[str, Any]] = None,

        # Fees/trial
        setup_fee: float = 0.0,
        trial_days: int = 0,

        # Metadata
        description: Optional[str] = None,
        is_popular: bool = False,
        display_order: int = 0,
        status: str = STATUS_ACTIVE,

        # Internal
        user_id=None,
        user__id=None,
        business_id=None,
        **kwargs,
    ):
        super().__init__(
            user__id=user__id,
            user_id=user_id,
            business_id=business_id,
            **kwargs,
        )

        self.business_id = ObjectId(business_id) if business_id else None

        # Core fields - ENCRYPTED
        if name:
            self.name = encrypt_data(name)
            self.hashed_name = hash_data(name)

        self.description = encrypt_data(description) if description else None
        self.tier = encrypt_data(tier) if tier else None
        self.billing_period = encrypt_data(billing_period) if billing_period else None
        self.currency = encrypt_data(currency) if currency else None

        self.price_model = encrypt_data(price_model) if price_model else None

        if status:
            self.status = encrypt_data(status)
            self.hashed_status = hash_data(status)

        # Pricing - ENCRYPTED
        # NOTE: Enterprise can be custom -> price=None
        self.price = encrypt_data(str(price)) if price is not None else None
        self.setup_fee = encrypt_data(str(setup_fee)) if setup_fee is not None else encrypt_data("0")

        # Limits - PLAIN (fast queries)
        self.max_users = int(max_users) if max_users is not None else None
        self.max_social_accounts = int(max_social_accounts) if max_social_accounts is not None else None
        self.bulk_schedule_limit = int(bulk_schedule_limit) if bulk_schedule_limit is not None else None
        self.competitor_tracking = int(competitor_tracking) if competitor_tracking is not None else None
        self.history_search_days = int(history_search_days) if history_search_days is not None else None

        # Features - PLAIN (JSON)
        self.features = features or self._default_features_for_tier(tier)

        # Trial + display - PLAIN
        self.trial_days = int(trial_days)
        self.is_popular = bool(is_popular)
        self.display_order = int(display_order)

        # Timestamps
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    # -----------------------------
    # Defaults per tier (UPDATED)
    # -----------------------------
    @classmethod
    def _default_features_for_tier(cls, tier: str) -> Dict[str, Any]:
        t = (tier or "").strip().lower()

        # baseline (Standard-ish)
        base = {
            "post_scheduling": True,
            "unlimited_scheduled_posts": True,
            "best_time_to_post_ai": True,
            "ai_caption_generator": True,
            "ai_image_generator": True,
            "content_templates": True,

            "shared_inbox": True,
            "dm_automation": True,
            "brand_monitoring": True,
            "sentiment_analysis": True,
            "competitor_benchmarking": True,
            "team_assignments": True,

            "analytics_dashboards": True,
            "custom_reports": False,
            "export_reports": False,
            "scheduled_reports": False,

            "approval_workflows": False,
            "bulk_upload": False,
            "routing_and_tagging": False,
            "auto_responses": False,
            "custom_permissions": False,

            "api_access": False,

            "sso": False,
            "enterprise_support": False,
            "dedicated_success_manager": False,
            "sla": False,

            "social_listening": False,
            "review_management": False,
            "employee_advocacy": False,
            "crm_integrations": False,
            "salesforce_integration": False,
        }

        if t == "advanced":
            base.update({
                "custom_reports": True,
                "export_reports": True,
                "scheduled_reports": True,

                "approval_workflows": True,
                "bulk_upload": True,
                "routing_and_tagging": True,
                "auto_responses": True,
                "custom_permissions": True,

                "api_access": True,
            })

        if t == "enterprise":
            base.update({
                "custom_reports": True,
                "export_reports": True,
                "scheduled_reports": True,

                "approval_workflows": True,
                "bulk_upload": True,
                "routing_and_tagging": True,
                "auto_responses": True,
                "custom_permissions": True,

                "api_access": True,

                "sso": True,
                "enterprise_support": True,
                "dedicated_success_manager": True,
                "sla": True,

                "social_listening": True,
                "review_management": True,
                "employee_advocacy": True,
                "crm_integrations": True,
                "salesforce_integration": True,
            })

        return base

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for MongoDB insertion."""
        return {
            "business_id": self.business_id,

            "name": self.name,
            "hashed_name": self.hashed_name,
            "description": self.description,

            "tier": self.tier,
            "billing_period": self.billing_period,

            "price_model": self.price_model,
            "price": self.price,
            "currency": self.currency,
            "setup_fee": self.setup_fee,

            # limits
            "max_users": self.max_users,
            "max_social_accounts": self.max_social_accounts,
            "bulk_schedule_limit": self.bulk_schedule_limit,
            "competitor_tracking": self.competitor_tracking,
            "history_search_days": self.history_search_days,

            "features": self.features,

            "trial_days": self.trial_days,
            "is_popular": self.is_popular,
            "display_order": self.display_order,

            "status": self.status,
            "hashed_status": self.hashed_status,

            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    # ---------------- INTERNAL HELPER ---------------- #
    @staticmethod
    def _normalise_package_doc(package: dict) -> Optional[dict]:
        """Normalise ObjectId fields and decrypt data."""
        if not package:
            return None

        if package.get("_id") is not None:
            package["_id"] = str(package["_id"])

        if package.get("business_id") is not None:
            package["business_id"] = str(package["business_id"])

        # Decrypt fields
        for field in Package.FIELDS_TO_DECRYPT:
            if field in package and package[field] is not None:
                package[field] = decrypt_data(package[field])

        # Convert numeric fields back
        # price may be None for Enterprise/custom
        if package.get("price") is not None:
            try:
                package["price"] = float(package["price"])
            except (ValueError, TypeError):
                package["price"] = None

        if package.get("setup_fee") is not None:
            try:
                package["setup_fee"] = float(package["setup_fee"])
            except (ValueError, TypeError):
                package["setup_fee"] = 0.0

        # Remove internal fields
        package.pop("hashed_name", None)
        package.pop("hashed_status", None)

        return package

    # ---------------- QUERIES ---------------- #
    @classmethod
    def get_by_id(cls, package_id):
        log_tag = f"[package.py][Package][get_by_id][{package_id}]"
        try:
            package_id = ObjectId(package_id) if not isinstance(package_id, ObjectId) else package_id
            collection = db.get_collection(cls.collection_name)
            package = collection.find_one({"_id": package_id})
            if not package:
                Log.error(f"{log_tag} Package not found")
                return None
            return cls._normalise_package_doc(package)
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None

    @classmethod
    def get_all_active(cls, page=None, per_page=None):
        log_tag = f"[package.py][Package][get_all_active]"
        try:
            page = int(page) if page else 1
            per_page = int(per_page) if per_page else 50

            collection = db.get_collection(cls.collection_name)
            query = {"hashed_status": hash_data(cls.STATUS_ACTIVE)}
            total_count = collection.count_documents(query)

            cursor = (
                collection.find(query)
                .sort("display_order", 1)
                .skip((page - 1) * per_page)
                .limit(per_page)
            )

            items = list(cursor)
            packages = [cls._normalise_package_doc(p) for p in items]
            total_pages = (total_count + per_page - 1) // per_page

            Log.info(f"{log_tag} Retrieved {len(packages)} packages")
            return {
                "packages": packages,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
            }

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "packages": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": int(page) if page else 1,
                "per_page": int(per_page) if per_page else 50,
            }

    @classmethod
    def get_by_tier(cls, tier: str):
        log_tag = f"[package.py][Package][get_by_tier][{tier}]"
        try:
            collection = db.get_collection(cls.collection_name)

            # NOTE: tier is encrypted so this matches your existing storage approach
            packages = list(
                collection.find({
                    "tier": encrypt_data(tier),
                    "hashed_status": hash_data(cls.STATUS_ACTIVE),
                }).sort("display_order", 1)
            )

            packages = [cls._normalise_package_doc(p) for p in packages]
            Log.info(f"{log_tag} Retrieved {len(packages)} packages")
            return packages

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return []

    @classmethod
    def update(cls, package_id, business_id, **updates):
        updates["updated_at"] = datetime.utcnow()

        # Encrypt + hash plaintext fields
        if "name" in updates and updates["name"]:
            original_name = updates["name"]
            updates["name"] = encrypt_data(original_name)
            updates["hashed_name"] = hash_data(original_name)

        if "description" in updates:
            updates["description"] = encrypt_data(updates["description"]) if updates["description"] else None

        if "tier" in updates and updates["tier"]:
            updates["tier"] = encrypt_data(updates["tier"])

        if "billing_period" in updates and updates["billing_period"]:
            updates["billing_period"] = encrypt_data(updates["billing_period"])

        if "currency" in updates and updates["currency"]:
            updates["currency"] = encrypt_data(updates["currency"])

        if "price_model" in updates and updates["price_model"]:
            updates["price_model"] = encrypt_data(updates["price_model"])

        if "status" in updates and updates["status"]:
            plain_status = updates["status"]
            updates["status"] = encrypt_data(plain_status)
            updates["hashed_status"] = hash_data(plain_status)

        if "price" in updates:
            # allow None for enterprise/custom
            updates["price"] = encrypt_data(str(updates["price"])) if updates["price"] is not None else None

        if "setup_fee" in updates and updates["setup_fee"] is not None:
            updates["setup_fee"] = encrypt_data(str(updates["setup_fee"]))

        return super().update(package_id, business_id, **updates)

    @classmethod
    def create_indexes(cls):
        log_tag = f"[package.py][Package][create_indexes]"
        try:
            collection = db.get_collection(cls.collection_name)

            # Indexes (UPDATED)
            collection.create_index([("hashed_status", 1), ("display_order", 1)])
            collection.create_index([("tier", 1)])
            collection.create_index([("is_popular", 1)])
            collection.create_index([("hashed_name", 1)])
            collection.create_index([("price", 1)])  # encrypted string; still okay for existence queries
            collection.create_index([("max_social_accounts", 1)])
            collection.create_index([("max_users", 1)])

            Log.info(f"{log_tag} Indexes created successfully")
            return True

        except Exception as e:
            Log.error(f"{log_tag} Error creating indexes: {str(e)}")
            return False




