# app/models/admin/discount_model.py

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from bson import ObjectId

from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.logger import Log


class Discount(BaseModel):
    """
    Discount / Coupon code model.

    Supports:
      - Percentage discounts (e.g. 20% off)
      - Fixed amount discounts (e.g. $10 off)
      - Usage limits (total uses + per-business uses)
      - Expiry dates
      - Tier restrictions (only valid for certain package tiers)
      - Billing period restrictions (only for monthly or annually)
      - Minimum price threshold
      - First-time subscriber only
      - Duration: once (first payment only), repeating (N months), forever

    Only SYSTEM_OWNER can create/manage discount codes.
    """

    collection_name = "discounts"
    _subscription_exempt = True
    _permission_exempt = True
    _permission_module = "billing"

    # ── Discount types ──
    TYPE_PERCENTAGE = "percentage"
    TYPE_FIXED = "fixed"
    TYPES = [TYPE_PERCENTAGE, TYPE_FIXED]

    # ── Duration (how long the discount applies for recurring) ──
    DURATION_ONCE = "once"              # First payment only
    DURATION_REPEATING = "repeating"    # N billing cycles
    DURATION_FOREVER = "forever"        # Every renewal
    DURATIONS = [DURATION_ONCE, DURATION_REPEATING, DURATION_FOREVER]

    # ── Status ──
    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_EXPIRED = "Expired"
    STATUS_EXHAUSTED = "Exhausted"      # Max uses reached
    STATUSES = [STATUS_ACTIVE, STATUS_INACTIVE, STATUS_EXPIRED, STATUS_EXHAUSTED]

    FIELDS_TO_DECRYPT = ["code", "description", "created_by_name"]

    def __init__(
        self,
        code: str,
        discount_type: str,
        value: float,
        # Limits
        max_uses: Optional[int] = None,
        max_uses_per_business: int = 1,
        times_used: int = 0,
        # Validity
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        # Restrictions
        applicable_tiers: Optional[List[str]] = None,
        applicable_billing_periods: Optional[List[str]] = None,
        minimum_amount: float = 0,
        first_time_only: bool = False,
        # Duration for recurring
        duration: str = DURATION_ONCE,
        duration_months: Optional[int] = None,
        # Metadata
        description: Optional[str] = None,
        created_by_name: Optional[str] = None,
        status: str = STATUS_ACTIVE,
        # Internal
        user_id=None,
        user__id=None,
        business_id=None,
        **kwargs,
    ):
        super().__init__(
            user__id=user__id, user_id=user_id, business_id=business_id, **kwargs,
        )

        # business_id on discount = None (system-level, not tied to a church)
        self.business_id = ObjectId(business_id) if business_id else None

        # ── Code (encrypted + hashed for lookup) ──
        clean_code = code.strip().upper()
        self.code = encrypt_data(clean_code)
        self.hashed_code = hash_data(clean_code)

        # ── Type & value ──
        self.discount_type = discount_type
        self.value = float(value)

        # ── Usage limits ──
        self.max_uses = int(max_uses) if max_uses is not None else None
        self.max_uses_per_business = int(max_uses_per_business)
        self.times_used = int(times_used)

        # ── Validity dates ──
        self.start_date = start_date or datetime.utcnow()
        self.end_date = end_date

        # ── Restrictions ──
        self.applicable_tiers = applicable_tiers or []        # Empty = all tiers
        self.applicable_billing_periods = applicable_billing_periods or []  # Empty = all periods
        self.minimum_amount = float(minimum_amount)
        self.first_time_only = bool(first_time_only)

        # ── Duration ──
        self.duration = duration
        if duration_months is not None:
            self.duration_months = int(duration_months)

        # ── Metadata ──
        if description:
            self.description = encrypt_data(description)
        if created_by_name:
            self.created_by_name = encrypt_data(created_by_name)

        self.status = status
        self.hashed_status = hash_data(status.strip())

        # ── Redemption log ──
        self.redemptions = []

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        doc = {
            "business_id": self.business_id,
            "code": self.code,
            "hashed_code": self.hashed_code,
            "discount_type": self.discount_type,
            "value": self.value,
            "max_uses": self.max_uses,
            "max_uses_per_business": self.max_uses_per_business,
            "times_used": self.times_used,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "applicable_tiers": self.applicable_tiers,
            "applicable_billing_periods": self.applicable_billing_periods,
            "minimum_amount": self.minimum_amount,
            "first_time_only": self.first_time_only,
            "duration": self.duration,
            "duration_months": getattr(self, "duration_months", None),
            "description": getattr(self, "description", None),
            "created_by_name": getattr(self, "created_by_name", None),
            "status": self.status,
            "hashed_status": self.hashed_status,
            "redemptions": self.redemptions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return {k: v for k, v in doc.items() if v is not None}

    @staticmethod
    def _safe_decrypt(value):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        try:
            return decrypt_data(value)
        except Exception:
            return value

    @classmethod
    def _normalise(cls, doc):
        if not doc:
            return None

        for f in ["_id", "business_id"]:
            if doc.get(f):
                doc[f] = str(doc[f])

        for f in cls.FIELDS_TO_DECRYPT:
            if f in doc:
                doc[f] = cls._safe_decrypt(doc[f])

        doc.pop("hashed_code", None)
        doc.pop("hashed_status", None)

        # Compute display fields
        if doc.get("discount_type") == cls.TYPE_PERCENTAGE:
            doc["display_value"] = f"{doc.get('value', 0)}%"
        else:
            doc["display_value"] = f"${doc.get('value', 0):.2f}"

        # Check if expired
        end_date = doc.get("end_date")
        if end_date:
            if isinstance(end_date, str):
                try:
                    end_date = datetime.fromisoformat(end_date)
                except Exception:
                    pass
            if isinstance(end_date, datetime):
                doc["is_expired"] = datetime.utcnow() > end_date
            else:
                doc["is_expired"] = False
        else:
            doc["is_expired"] = False

        # Check if exhausted
        max_uses = doc.get("max_uses")
        times_used = doc.get("times_used", 0)
        doc["is_exhausted"] = max_uses is not None and times_used >= max_uses

        # Usage display
        if max_uses is not None:
            doc["usage_display"] = f"{times_used}/{max_uses}"
        else:
            doc["usage_display"] = f"{times_used}/∞"

        return doc

    # ═══════════════════════════════════════════════════════════════
    # QUERIES
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def get_by_id(cls, discount_id):
        try:
            c = db.get_collection(cls.collection_name)
            doc = c.find_one({"_id": ObjectId(discount_id)})
            return cls._normalise(doc)
        except Exception as e:
            Log.error(f"[Discount.get_by_id] {e}")
            return None

    @classmethod
    def get_by_code(cls, code):
        """Look up a discount by its code (case-insensitive)."""
        try:
            clean = code.strip().upper()
            c = db.get_collection(cls.collection_name)
            doc = c.find_one({"hashed_code": hash_data(clean)})
            return cls._normalise(doc)
        except Exception as e:
            Log.error(f"[Discount.get_by_code] {e}")
            return None

    @classmethod
    def get_all(cls, status=None, page=1, per_page=50):
        """Get all discount codes (admin view)."""
        try:
            c = db.get_collection(cls.collection_name)
            q = {}
            if status:
                q["hashed_status"] = hash_data(status.strip())

            total = c.count_documents(q)
            cursor = c.find(q).sort("created_at", -1).skip((page - 1) * per_page).limit(per_page)
            discounts = [cls._normalise(d) for d in cursor]
            total_pages = (total + per_page - 1) // per_page

            return {
                "discounts": discounts,
                "total_count": total,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"[Discount.get_all] {e}")
            return {"discounts": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    # ═══════════════════════════════════════════════════════════════
    # VALIDATION & APPLICATION
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def validate_code(cls, code, business_id, package_tier, billing_period, original_amount):
        """
        Validate a discount code and return the discount details if valid.

        Args:
            code: The discount code entered by the user
            business_id: The business trying to use the code
            package_tier: The tier of the package being subscribed to
            billing_period: "monthly" or "annually"
            original_amount: The original price before discount

        Returns:
            (is_valid: bool, discount_or_error: dict/str)
        """
        log_tag = f"[Discount.validate_code][{code}]"
        try:
            discount = cls.get_by_code(code)

            if not discount:
                return False, "Invalid discount code."

            # ── Status check ──
            status = discount.get("status", "")
            if status != cls.STATUS_ACTIVE:
                return False, f"This discount code is {status.lower()}."

            # ── Expiry check ──
            if discount.get("is_expired"):
                return False, "This discount code has expired."

            # ── Start date check ──
            start_date = discount.get("start_date")
            if start_date:
                if isinstance(start_date, str):
                    start_date = datetime.fromisoformat(start_date)
                if isinstance(start_date, datetime) and datetime.utcnow() < start_date:
                    return False, "This discount code is not yet active."

            # ── Exhausted check ──
            if discount.get("is_exhausted"):
                return False, "This discount code has been fully redeemed."

            # ── Tier restriction ──
            applicable_tiers = discount.get("applicable_tiers", [])
            if applicable_tiers and package_tier not in applicable_tiers:
                return False, f"This code is not valid for the {package_tier} plan."

            # ── Billing period restriction ──
            applicable_periods = discount.get("applicable_billing_periods", [])
            if applicable_periods and billing_period not in applicable_periods:
                period_label = "monthly" if billing_period == "monthly" else "annual"
                return False, f"This code is not valid for {period_label} billing."

            # ── Minimum amount ──
            min_amount = discount.get("minimum_amount", 0)
            if original_amount < min_amount:
                return False, f"This code requires a minimum purchase of ${min_amount:.2f}."

            # ── Per-business usage limit ──
            max_per_biz = discount.get("max_uses_per_business", 1)
            redemptions = discount.get("redemptions", [])
            biz_uses = sum(1 for r in redemptions if str(r.get("business_id")) == str(business_id))
            if biz_uses >= max_per_biz:
                return False, "Your organisation has already used this discount code."

            # ── First-time only ──
            if discount.get("first_time_only"):
                from ..admin.subscription_model import Subscription
                existing = Subscription.get_latest_by_business(str(business_id))
                if existing:
                    existing_status = (existing.get("status") or "").upper()
                    if existing_status not in ("", "TRIAL", "TRIALEXPIRED"):
                        return False, "This code is only valid for first-time subscribers."

            # ── Calculate discounted amount ──
            discount_type = discount.get("discount_type")
            value = discount.get("value", 0)

            if discount_type == cls.TYPE_PERCENTAGE:
                discount_amount = round(original_amount * (value / 100), 2)
            else:
                discount_amount = min(value, original_amount)

            final_amount = round(max(0, original_amount - discount_amount), 2)

            Log.info(f"{log_tag} valid: {discount_type} {value} → ${original_amount} - ${discount_amount} = ${final_amount}")

            return True, {
                "discount_id": discount.get("_id"),
                "code": discount.get("code"),
                "discount_type": discount_type,
                "discount_value": value,
                "display_value": discount.get("display_value"),
                "original_amount": original_amount,
                "discount_amount": discount_amount,
                "final_amount": final_amount,
                "duration": discount.get("duration", cls.DURATION_ONCE),
                "duration_months": discount.get("duration_months"),
            }

        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return False, "Unable to validate discount code. Please try again."

    @classmethod
    def apply_discount(cls, original_amount, discount_info):
        """
        Calculate the final amount after applying a validated discount.

        Args:
            original_amount: Price before discount
            discount_info: The dict returned by validate_code on success

        Returns:
            final_amount (float)
        """
        if not discount_info:
            return original_amount

        discount_type = discount_info.get("discount_type")
        value = discount_info.get("discount_value", 0)

        if discount_type == cls.TYPE_PERCENTAGE:
            discount_amount = round(original_amount * (value / 100), 2)
        else:
            discount_amount = min(value, original_amount)

        return round(max(0, original_amount - discount_amount), 2)

    @classmethod
    def record_redemption(cls, discount_id, business_id, user_id=None, amount_saved=0, subscription_id=None):
        """Record a successful use of a discount code."""
        log_tag = f"[Discount.record_redemption][{discount_id}]"
        try:
            c = db.get_collection(cls.collection_name)

            redemption = {
                "business_id": str(business_id),
                "user_id": str(user_id) if user_id else None,
                "subscription_id": str(subscription_id) if subscription_id else None,
                "amount_saved": amount_saved,
                "redeemed_at": datetime.utcnow(),
            }
            redemption = {k: v for k, v in redemption.items() if v is not None}

            result = c.find_one_and_update(
                {"_id": ObjectId(discount_id)},
                {
                    "$inc": {"times_used": 1},
                    "$push": {"redemptions": redemption},
                    "$set": {"updated_at": datetime.utcnow()},
                },
                return_document=True,
            )

            if not result:
                Log.error(f"{log_tag} discount not found")
                return False

            # Auto-exhaust if max_uses reached
            max_uses = result.get("max_uses")
            times_used = result.get("times_used", 0)
            if max_uses is not None and times_used >= max_uses:
                c.update_one(
                    {"_id": ObjectId(discount_id)},
                    {"$set": {
                        "status": cls.STATUS_EXHAUSTED,
                        "hashed_status": hash_data(cls.STATUS_EXHAUSTED),
                        "updated_at": datetime.utcnow(),
                    }},
                )
                Log.info(f"{log_tag} auto-exhausted after {times_used} uses")

            Log.info(f"{log_tag} redemption recorded: business={business_id}, saved=${amount_saved}")
            return True

        except Exception as e:
            Log.error(f"{log_tag} {e}")
            return False

    # ═══════════════════════════════════════════════════════════════
    # ADMIN MANAGEMENT
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def update_discount(cls, discount_id, **updates):
        """Update a discount code (SYSTEM_OWNER only — enforced at resource level)."""
        try:
            c = db.get_collection(cls.collection_name)
            updates["updated_at"] = datetime.utcnow()

            # Encrypt fields if present
            if "code" in updates and updates["code"]:
                clean = updates["code"].strip().upper()
                updates["code"] = encrypt_data(clean)
                updates["hashed_code"] = hash_data(clean)

            if "description" in updates and updates["description"]:
                updates["description"] = encrypt_data(updates["description"])

            if "status" in updates and updates["status"]:
                updates["hashed_status"] = hash_data(updates["status"].strip())

            updates = {k: v for k, v in updates.items() if v is not None}

            result = c.update_one({"_id": ObjectId(discount_id)}, {"$set": updates})
            return result.modified_count > 0
        except Exception as e:
            Log.error(f"[Discount.update_discount] {e}")
            return False

    @classmethod
    def deactivate(cls, discount_id):
        """Deactivate a discount code."""
        return cls.update_discount(discount_id, status=cls.STATUS_INACTIVE)

    @classmethod
    def get_redemption_stats(cls, discount_id):
        """Get usage statistics for a discount code."""
        try:
            discount = cls.get_by_id(discount_id)
            if not discount:
                return None

            redemptions = discount.get("redemptions", [])
            total_saved = sum(r.get("amount_saved", 0) for r in redemptions)
            unique_businesses = len(set(r.get("business_id") for r in redemptions))

            return {
                "discount_id": discount_id,
                "code": discount.get("code"),
                "times_used": discount.get("times_used", 0),
                "max_uses": discount.get("max_uses"),
                "unique_businesses": unique_businesses,
                "total_amount_discounted": round(total_saved, 2),
                "status": discount.get("status"),
                "is_exhausted": discount.get("is_exhausted"),
                "is_expired": discount.get("is_expired"),
                "recent_redemptions": redemptions[-10:] if redemptions else [],
            }
        except Exception as e:
            Log.error(f"[Discount.get_redemption_stats] {e}")
            return None

    @classmethod
    def expire_outdated(cls):
        """Batch-expire discounts past their end_date. Run from a daily cron."""
        try:
            c = db.get_collection(cls.collection_name)
            now = datetime.utcnow()
            result = c.update_many(
                {
                    "hashed_status": hash_data(cls.STATUS_ACTIVE),
                    "end_date": {"$lt": now, "$ne": None},
                },
                {"$set": {
                    "status": cls.STATUS_EXPIRED,
                    "hashed_status": hash_data(cls.STATUS_EXPIRED),
                    "updated_at": now,
                }},
            )
            if result.modified_count > 0:
                Log.info(f"[Discount.expire_outdated] expired {result.modified_count} discount(s)")
            return result.modified_count
        except Exception as e:
            Log.error(f"[Discount.expire_outdated] {e}")
            return 0

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("hashed_code", 1)], unique=True)
            c.create_index([("hashed_status", 1), ("created_at", -1)])
            c.create_index([("end_date", 1)])
            Log.info("[Discount.create_indexes] Indexes created")
            return True
        except Exception as e:
            Log.error(f"[Discount.create_indexes] {e}")
            return False
