# app/models/package.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId

from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.crypt import (
    encrypt_data, decrypt_data, hash_data
)
from ...utils.logger import Log


class Package(BaseModel):
    """
    Subscription package/plan model (Social Media Management SaaS - Hootsuite-style).

    Key goals:
      ✅ No null/None fields saved to MongoDB
      ✅ Safe decrypt (never crash if a field is not encrypted / legacy data)
      ✅ Searchable tiers/status via hashed fields (encryption is non-deterministic)
      ✅ Supports Enterprise/custom pricing (price=None)
      ✅ Supports nested "limits" from API payloads via normalize_payload()

    Notes:
      - We store encrypted fields for privacy.
      - We store hashed fields for querying (because encrypt_data() is non-deterministic).
    """

    collection_name = "packages"

    # -------------------------
    # Package Tiers
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
    # Price Model
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
    # Fields to decrypt (ENCRYPTED fields only)
    # -------------------------
    FIELDS_TO_DECRYPT = [
        "name",
        "description",
        "tier",
        "billing_period",
        "currency",
        "status",
        "price",
        "setup_fee",
        "price_model",
    ]

    # -------------------------
    # Limits keys accepted (PLAIN fields)
    # -------------------------
    LIMIT_KEYS = {
        "max_users",
        "max_social_accounts",
        "bulk_schedule_limit",
        "competitor_tracking",
        "history_search_days",
    }

    def __init__(
        self,
        name: str,
        tier: str,
        billing_period: str,
        price: Optional[float],
        currency: str = "GBP",

        # Pricing model
        price_model: str = PRICE_MODEL_PER_USER,

        # Social limits
        max_users: Optional[int] = None,
        max_social_accounts: Optional[int] = None,
        bulk_schedule_limit: Optional[int] = None,
        competitor_tracking: Optional[int] = None,
        history_search_days: Optional[int] = None,

        # Feature flags
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

        # -------------------------
        # Core fields (ENCRYPTED + HASHED)
        # -------------------------
        if name:
            self.name = encrypt_data(name)
            self.hashed_name = hash_data(name)

        if description:
            self.description = encrypt_data(description)

        if tier:
            self.tier = encrypt_data(tier)
            self.hashed_tier = hash_data(tier)

        if billing_period:
            self.billing_period = encrypt_data(billing_period)
            self.hashed_billing_period = hash_data(billing_period)

        if currency:
            self.currency = encrypt_data(currency)

        if price_model:
            self.price_model = encrypt_data(price_model)

        if status:
            self.status = encrypt_data(status)
            self.hashed_status = hash_data(status)

        # -------------------------
        # Pricing (ENCRYPTED)
        # Enterprise/custom can be price=None
        # -------------------------
        if price is not None:
            self.price = encrypt_data(str(price))

        # setup_fee always stored (encrypted) as string
        self.setup_fee = encrypt_data(str(setup_fee if setup_fee is not None else 0.0))

        # -------------------------
        # Limits (PLAIN for query speed)
        # -------------------------
        if max_users is not None:
            self.max_users = int(max_users)

        if max_social_accounts is not None:
            self.max_social_accounts = int(max_social_accounts)

        if bulk_schedule_limit is not None:
            self.bulk_schedule_limit = int(bulk_schedule_limit)

        if competitor_tracking is not None:
            self.competitor_tracking = int(competitor_tracking)

        if history_search_days is not None:
            self.history_search_days = int(history_search_days)

        # -------------------------
        # Features (PLAIN JSON)
        # -------------------------
        self.features = features or self._default_features_for_tier(tier)

        # -------------------------
        # Trial + display (PLAIN)
        # -------------------------
        if trial_days is not None:
            self.trial_days = int(trial_days)

        self.is_popular = bool(is_popular)
        self.display_order = int(display_order)

        # -------------------------
        # Timestamps
        # -------------------------
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    # -----------------------------
    # Defaults per tier
    # -----------------------------
    @classmethod
    def _default_features_for_tier(cls, tier: str) -> Dict[str, Any]:
        t = (tier or "").strip().lower()

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

    # -----------------------------
    # Payload Normalizer (IMPORTANT)
    # -----------------------------
    @classmethod
    def normalize_payload(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Accepts API payloads that may contain:
          - limits: {...}
        Flattens them into top-level fields and removes None values.

        This prevents:
          ✅ "limits" being stored as an unexpected dict
          ✅ None fields being stored as null in MongoDB
        """
        if not payload:
            return {}

        payload = dict(payload)  # copy

        limits = payload.pop("limits", None) or {}
        if isinstance(limits, dict):
            for k, v in limits.items():
                if k in cls.LIMIT_KEYS and v is not None:
                    payload[k] = v

        # Remove None values at top-level
        payload = {k: v for k, v in payload.items() if v is not None}
        return payload

    # -----------------------------
    # No-null Mongo insert doc
    # -----------------------------
    def to_dict(self) -> Dict[str, Any]:
        doc: Dict[str, Any] = {
            "business_id": self.business_id,

            "name": getattr(self, "name", None),
            "hashed_name": getattr(self, "hashed_name", None),

            "description": getattr(self, "description", None),

            "tier": getattr(self, "tier", None),
            "hashed_tier": getattr(self, "hashed_tier", None),

            "billing_period": getattr(self, "billing_period", None),
            "hashed_billing_period": getattr(self, "hashed_billing_period", None),

            "price_model": getattr(self, "price_model", None),

            "price": getattr(self, "price", None),
            "currency": getattr(self, "currency", None),
            "setup_fee": getattr(self, "setup_fee", None),

            # limits
            "max_users": getattr(self, "max_users", None),
            "max_social_accounts": getattr(self, "max_social_accounts", None),
            "bulk_schedule_limit": getattr(self, "bulk_schedule_limit", None),
            "competitor_tracking": getattr(self, "competitor_tracking", None),
            "history_search_days": getattr(self, "history_search_days", None),

            "features": getattr(self, "features", None),

            "trial_days": getattr(self, "trial_days", None),
            "is_popular": getattr(self, "is_popular", None),
            "display_order": getattr(self, "display_order", None),

            "status": getattr(self, "status", None),
            "hashed_status": getattr(self, "hashed_status", None),

            "created_at": getattr(self, "created_at", None),
            "updated_at": getattr(self, "updated_at", None),
        }

        # ✅ Remove None so Mongo doesn't store nulls
        return {k: v for k, v in doc.items() if v is not None}

    # ---------------- INTERNAL HELPER ---------------- #
    @staticmethod
    def _safe_decrypt(value: Any) -> Any:
        """
        Decrypt only strings.
        If decrypt fails (legacy/plaintext/corrupt), return original.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        try:
            return decrypt_data(value)
        except Exception:
            return value

    @classmethod
    def _normalise_package_doc(cls, package: dict) -> Optional[dict]:
        if not package:
            return None

        if package.get("_id") is not None:
            package["_id"] = str(package["_id"])

        if package.get("business_id") is not None:
            package["business_id"] = str(package["business_id"])

        # Decrypt encrypted fields safely
        for field in cls.FIELDS_TO_DECRYPT:
            if field in package:
                package[field] = cls._safe_decrypt(package[field])

        # Convert numeric fields back
        if package.get("price") is not None:
            try:
                package["price"] = float(package["price"])
            except Exception:
                package["price"] = None

        if package.get("setup_fee") is not None:
            try:
                package["setup_fee"] = float(package["setup_fee"])
            except Exception:
                package["setup_fee"] = 0.0

        # remove internal hashes
        package.pop("hashed_name", None)
        package.pop("hashed_status", None)
        package.pop("hashed_tier", None)
        package.pop("hashed_billing_period", None)

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
        """
        ✅ Correct query using hashed_tier (NOT encrypt_data(tier)).
        """
        log_tag = f"[package.py][Package][get_by_tier][{tier}]"
        try:
            collection = db.get_collection(cls.collection_name)
            query = {
                "hashed_tier": hash_data(tier),
                "hashed_status": hash_data(cls.STATUS_ACTIVE),
            }
            packages = list(collection.find(query).sort("display_order", 1))
            return [cls._normalise_package_doc(p) for p in packages]
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return []

    @classmethod
    def update(cls, package_id, business_id, **updates):
        """
        Update fields. Removes None values so you don't store nulls.
        Encrypts sensitive fields and hashes searchable fields.
        """
        updates = dict(updates or {})
        updates["updated_at"] = datetime.utcnow()

        # remove None values (so no nulls)
        updates = {k: v for k, v in updates.items() if v is not None}

        # allow "limits" in updates too
        updates = cls.normalize_payload(updates)

        # Encrypt + hash plaintext fields
        if "name" in updates and updates["name"]:
            original_name = updates["name"]
            updates["name"] = encrypt_data(original_name)
            updates["hashed_name"] = hash_data(original_name)

        if "description" in updates:
            updates["description"] = encrypt_data(updates["description"]) if updates["description"] else None

        if "tier" in updates and updates["tier"]:
            original_tier = updates["tier"]
            updates["tier"] = encrypt_data(original_tier)
            updates["hashed_tier"] = hash_data(original_tier)

        if "billing_period" in updates and updates["billing_period"]:
            bp = updates["billing_period"]
            updates["billing_period"] = encrypt_data(bp)
            updates["hashed_billing_period"] = hash_data(bp)

        if "currency" in updates and updates["currency"]:
            updates["currency"] = encrypt_data(updates["currency"])

        if "price_model" in updates and updates["price_model"]:
            updates["price_model"] = encrypt_data(updates["price_model"])

        if "status" in updates and updates["status"]:
            plain_status = updates["status"]
            updates["status"] = encrypt_data(plain_status)
            updates["hashed_status"] = hash_data(plain_status)

        if "price" in updates:
            updates["price"] = encrypt_data(str(updates["price"])) if updates["price"] is not None else None

        if "setup_fee" in updates and updates["setup_fee"] is not None:
            updates["setup_fee"] = encrypt_data(str(updates["setup_fee"]))

        # Remove any None after encrypt decisions
        updates = {k: v for k, v in updates.items() if v is not None}

        return super().update(package_id, business_id, **updates)

    @classmethod
    def create_indexes(cls):
        log_tag = f"[package.py][Package][create_indexes]"
        try:
            collection = db.get_collection(cls.collection_name)

            collection.create_index([("hashed_status", 1), ("display_order", 1)])
            collection.create_index([("hashed_tier", 1), ("hashed_status", 1)])
            collection.create_index([("hashed_name", 1)])
            collection.create_index([("is_popular", 1)])
            collection.create_index([("max_social_accounts", 1)])
            collection.create_index([("max_users", 1)])

            Log.info(f"{log_tag} Indexes created successfully")
            return True

        except Exception as e:
            Log.error(f"{log_tag} Error creating indexes: {str(e)}")
            return False