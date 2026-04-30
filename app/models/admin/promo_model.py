# app/models/admin/promo_model.py

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from bson import ObjectId

from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.logger import Log


# ═══════════════════════════════════════════════════════════════
# PROMO CODE
# ═══════════════════════════════════════════════════════════════

class PromoCode(BaseModel):
    """
    Promo/referral code assigned to admins (sales agents).

    Flow:
      1. SYSTEM_OWNER creates an admin → promo code auto-generated
      2. Admin shares code with churches
      3. Church registers with promo code
      4. On first successful payment → commission credited to admin wallet
    """

    collection_name = "promo_codes"
    _subscription_exempt = True
    _permission_exempt = True

    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_REVOKED = "Revoked"
    STATUSES = [STATUS_ACTIVE, STATUS_INACTIVE, STATUS_REVOKED]

    # Commission types
    COMMISSION_PERCENTAGE = "percentage"
    COMMISSION_FIXED = "fixed"
    COMMISSION_TYPES = [COMMISSION_PERCENTAGE, COMMISSION_FIXED]

    FIELDS_TO_DECRYPT = ["admin_name", "admin_email"]

    def __init__(
        self,
        code: str,
        admin_id: str,
        admin_name: Optional[str] = None,
        admin_email: Optional[str] = None,
        # Commission config
        commission_type: str = COMMISSION_PERCENTAGE,
        commission_value: float = 10.0,
        commission_duration_months: Optional[int] = None,
        # Limits
        max_uses: Optional[int] = None,
        times_used: int = 0,
        # Validity
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        updated_by: Optional[str] = None,
        # Restrictions
        applicable_tiers: Optional[List[str]] = None,
        # Metadata
        description: Optional[str] = None,
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

        self.business_id = ObjectId(business_id) if business_id else None

        # Code (encrypted + hashed)
        clean_code = code.strip().upper()
        self.code = encrypt_data(clean_code)
        self.hashed_code = hash_data(clean_code)

        # Admin link
        self.admin_id = ObjectId(admin_id)
        if admin_name:
            self.admin_name = encrypt_data(admin_name)
        if admin_email:
            self.admin_email = encrypt_data(admin_email)
            self.hashed_admin_email = hash_data(admin_email.strip().lower())

        # Commission
        self.commission_type = commission_type
        self.commission_value = float(commission_value)
        self.commission_duration_months = int(commission_duration_months) if commission_duration_months else None

        # Limits
        self.max_uses = int(max_uses) if max_uses is not None else None
        self.times_used = int(times_used)

        # Validity
        self.start_date = start_date or datetime.utcnow()
        self.end_date = end_date

        # Restrictions
        self.applicable_tiers = applicable_tiers or []

        # Metadata
        if description:
            self.description = encrypt_data(description)
        self.status = status
        self.hashed_status = hash_data(status.strip())
        
        self.updated_by = ObjectId(updated_by) if updated_by else None

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        doc = {
            "business_id": self.business_id,
            "code": self.code,
            "hashed_code": self.hashed_code,
            "admin_id": self.admin_id,
            "admin_name": getattr(self, "admin_name", None),
            "admin_email": getattr(self, "admin_email", None),
            "hashed_admin_email": getattr(self, "hashed_admin_email", None),
            "commission_type": self.commission_type,
            "commission_value": self.commission_value,
            "commission_duration_months": self.commission_duration_months,
            "max_uses": self.max_uses,
            "times_used": self.times_used,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "applicable_tiers": self.applicable_tiers,
            "description": getattr(self, "description", None),
            "status": self.status,
            "hashed_status": self.hashed_status,
            "updated_by": ObjectId(self.updated_by) if self.updated_by else None,
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
        from ...utils.helpers import stringify_object_ids
        if not doc:
            return None
        for f in ["_id", "business_id", "admin_id"]:
            if doc.get(f):
                doc[f] = str(doc[f])
        for f in cls.FIELDS_TO_DECRYPT:
            if f in doc:
                doc[f] = cls._safe_decrypt(doc[f])
        if doc.get("description"):
            doc["description"] = cls._safe_decrypt(doc["description"])
        if doc.get("code"):
            doc["code"] = cls._safe_decrypt(doc["code"])
        doc.pop("hashed_code", None)
        doc.pop("hashed_status", None)
        doc.pop("hashed_admin_email", None)

        # Computed fields
        max_uses = doc.get("max_uses")
        times_used = doc.get("times_used", 0)
        doc["is_exhausted"] = max_uses is not None and times_used >= max_uses
        doc["usage_display"] = f"{times_used}/{max_uses}" if max_uses else f"{times_used}/∞"

        if doc.get("commission_type") == cls.COMMISSION_PERCENTAGE:
            doc["commission_display"] = f"{doc.get('commission_value', 0)}%"
        else:
            doc["commission_display"] = f"${doc.get('commission_value', 0):.2f}"

        end_date = doc.get("end_date")
        if end_date and isinstance(end_date, datetime):
            doc["is_expired"] = datetime.utcnow() > end_date
        else:
            doc["is_expired"] = False

        doc = stringify_object_ids(doc)
        return doc

    # ── Queries ──

    @classmethod
    def get_by_id(cls, promo_id):
        try:
            c = db.get_collection(cls.collection_name)
            return cls._normalise(c.find_one({"_id": ObjectId(promo_id)}))
        except Exception as e:
            Log.error(f"[PromoCode.get_by_id] {e}")
            return None

    @classmethod
    def get_by_code(cls, code):
        try:
            clean = code.strip().upper()
            c = db.get_collection(cls.collection_name)
            return cls._normalise(c.find_one({"hashed_code": hash_data(clean)}))
        except Exception as e:
            Log.error(f"[PromoCode.get_by_code] {e}")
            return None

    @classmethod
    def get_by_admin(cls, admin_id, status=None):
        try:
            c = db.get_collection(cls.collection_name)
            q = {"admin_id": ObjectId(admin_id)}
            if status:
                q["hashed_status"] = hash_data(status.strip())
            cursor = c.find(q).sort("created_at", -1)
            return [cls._normalise(d) for d in cursor]
        except Exception as e:
            Log.error(f"[PromoCode.get_by_admin] {e}")
            return []

    @classmethod
    def get_all(cls, status=None, page=1, per_page=50):
        try:
            c = db.get_collection(cls.collection_name)
            q = {}
            if status:
                q["hashed_status"] = hash_data(status.strip())
            total = c.count_documents(q)
            cursor = c.find(q).sort("created_at", -1).skip((page - 1) * per_page).limit(per_page)
            return {
                "promo_codes": [cls._normalise(d) for d in cursor],
                "total_count": total,
                "total_pages": (total + per_page - 1) // per_page,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"[PromoCode.get_all] {e}")
            return {"promo_codes": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    # ── Validation ──

    @classmethod
    def validate_code(cls, code):
        """Validate a promo code for registration. Returns (is_valid, promo_or_error)."""
        try:
            promo = cls.get_by_code(code)
            if not promo:
                return False, "Invalid promo code."
            if promo.get("status") != cls.STATUS_ACTIVE:
                return False, f"This promo code is {(promo.get('status') or '').lower()}."
            if promo.get("is_expired"):
                return False, "This promo code has expired."
            if promo.get("is_exhausted"):
                return False, "This promo code has been fully used."

            start_date = promo.get("start_date")
            if start_date and isinstance(start_date, datetime) and datetime.utcnow() < start_date:
                return False, "This promo code is not yet active."

            return True, promo
        except Exception as e:
            Log.error(f"[PromoCode.validate_code] {e}")
            return False, "Unable to validate promo code."

    @classmethod
    def increment_usage(cls, promo_id):
        """Increment times_used. Auto-exhaust if max reached."""
        try:
            c = db.get_collection(cls.collection_name)
            result = c.find_one_and_update(
                {"_id": ObjectId(promo_id)},
                {"$inc": {"times_used": 1}, "$set": {"updated_at": datetime.utcnow()}},
                return_document=True,
            )
            if result:
                max_uses = result.get("max_uses")
                if max_uses is not None and result.get("times_used", 0) >= max_uses:
                    c.update_one(
                        {"_id": ObjectId(promo_id)},
                        {"$set": {"status": cls.STATUS_INACTIVE, "hashed_status": hash_data(cls.STATUS_INACTIVE)}},
                    )
            return True
        except Exception as e:
            Log.error(f"[PromoCode.increment_usage] {e}")
            return False

    @classmethod
    def generate_unique_code(cls, prefix="REF", length=6):
        """Generate a unique promo code like REF-A3X9K2."""
        import random, string
        for _ in range(10):
            chars = "".join(random.choices(string.ascii_uppercase + string.digits, k=length))
            code = f"{prefix}-{chars}"
            if not cls.get_by_code(code):
                return code
        return f"{prefix}-{random.randint(100000, 999999)}"

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("hashed_code", 1)], unique=True)
            c.create_index([("admin_id", 1), ("hashed_status", 1)])
            c.create_index([("hashed_status", 1), ("created_at", -1)])
            return True
        except Exception as e:
            Log.error(f"[PromoCode.create_indexes] {e}")
            return False


# ═══════════════════════════════════════════════════════════════
# REFERRAL (tracks which business used which promo code)
# ═══════════════════════════════════════════════════════════════

class Referral(BaseModel):
    """
    Tracks a business registration that used a promo code.
    Links the referred business to the referring admin.
    """

    collection_name = "referrals"
    _subscription_exempt = True
    _permission_exempt = True

    STATUS_REGISTERED = "Registered"
    STATUS_SUBSCRIBED = "Subscribed"
    STATUS_CHURNED = "Churned"
    STATUSES = [STATUS_REGISTERED, STATUS_SUBSCRIBED, STATUS_CHURNED]

    def __init__(
        self,
        promo_code_id: str,
        promo_code: str,
        admin_id: str,
        referred_business_id: str,
        referred_business_name: Optional[str] = None,
        referred_by_email: Optional[str] = None,
        # Commission config (copied from promo at time of registration)
        commission_type: str = "percentage",
        commission_value: float = 10.0,
        commission_duration_months: Optional[int] = None,
        # Tracking
        status: str = STATUS_REGISTERED,
        total_commission_earned: float = 0.0,
        total_payments_tracked: int = 0,
        months_tracked: int = 0,
        # Internal
        user_id=None,
        user__id=None,
        business_id=None,
        **kwargs,
    ):
        super().__init__(
            user__id=user__id, user_id=user_id, business_id=business_id, **kwargs,
        )

        self.business_id = ObjectId(business_id) if business_id else None
        self.promo_code_id = ObjectId(promo_code_id)
        self.promo_code = promo_code.strip().upper()
        self.admin_id = ObjectId(admin_id)
        self.referred_business_id = ObjectId(referred_business_id)

        if referred_business_name:
            self.referred_business_name = encrypt_data(referred_business_name)
        if referred_by_email:
            self.referred_by_email = encrypt_data(referred_by_email)

        self.commission_type = commission_type
        self.commission_value = float(commission_value)
        self.commission_duration_months = int(commission_duration_months) if commission_duration_months else None

        self.status = status
        self.hashed_status = hash_data(status.strip())
        self.total_commission_earned = float(total_commission_earned)
        self.total_payments_tracked = int(total_payments_tracked)
        self.months_tracked = int(months_tracked)

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        doc = {
            "business_id": self.business_id,
            "promo_code_id": self.promo_code_id,
            "promo_code": self.promo_code,
            "admin_id": self.admin_id,
            "referred_business_id": self.referred_business_id,
            "referred_business_name": getattr(self, "referred_business_name", None),
            "referred_by_email": getattr(self, "referred_by_email", None),
            "commission_type": self.commission_type,
            "commission_value": self.commission_value,
            "commission_duration_months": self.commission_duration_months,
            "status": self.status,
            "hashed_status": self.hashed_status,
            "total_commission_earned": self.total_commission_earned,
            "total_payments_tracked": self.total_payments_tracked,
            "months_tracked": self.months_tracked,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return {k: v for k, v in doc.items() if v is not None}

    @classmethod
    def _normalise(cls, doc):
        if not doc:
            return None
        for f in ["_id", "business_id", "promo_code_id", "admin_id", "referred_business_id"]:
            if doc.get(f):
                doc[f] = str(doc[f])
        for f in ["referred_business_name", "referred_by_email"]:
            if doc.get(f):
                try:
                    doc[f] = decrypt_data(doc[f])
                except Exception:
                    pass
        doc.pop("hashed_status", None)
        return doc

    @classmethod
    def get_by_business(cls, referred_business_id):
        try:
            c = db.get_collection(cls.collection_name)
            doc = c.find_one({"referred_business_id": ObjectId(referred_business_id)})
            return cls._normalise(doc)
        except Exception as e:
            Log.error(f"[Referral.get_by_business] {e}")
            return None

    @classmethod
    def get_by_admin(cls, admin_id, page=1, per_page=50):
        try:
            c = db.get_collection(cls.collection_name)
            q = {"admin_id": ObjectId(admin_id)}
            total = c.count_documents(q)
            cursor = c.find(q).sort("created_at", -1).skip((page - 1) * per_page).limit(per_page)
            return {
                "referrals": [cls._normalise(d) for d in cursor],
                "total_count": total,
                "total_pages": (total + per_page - 1) // per_page,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"[Referral.get_by_admin] {e}")
            return {"referrals": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("referred_business_id", 1)], unique=True)
            c.create_index([("admin_id", 1), ("created_at", -1)])
            c.create_index([("promo_code_id", 1)])
            return True
        except Exception as e:
            Log.error(f"[Referral.create_indexes] {e}")
            return False


# ═══════════════════════════════════════════════════════════════
# COMMISSION WALLET (admin earnings)
# ═══════════════════════════════════════════════════════════════

class CommissionWallet(BaseModel):
    """
    Tracks an admin's total commission earnings from referrals.
    One wallet per admin. Ledger entries stored in CommissionLedger.
    """

    collection_name = "commission_wallets"
    _subscription_exempt = True
    _permission_exempt = True

    def __init__(
        self,
        admin_id: str,
        admin_name: Optional[str] = None,
        admin_email: Optional[str] = None,
        total_earned: float = 0.0,
        total_paid_out: float = 0.0,
        pending_balance: float = 0.0,
        currency: str = "USD",
        # Internal
        user_id=None,
        user__id=None,
        business_id=None,
        **kwargs,
    ):
        super().__init__(
            user__id=user__id, user_id=user_id, business_id=business_id, **kwargs,
        )

        self.business_id = ObjectId(business_id) if business_id else None
        self.admin_id = ObjectId(admin_id)

        if admin_name:
            self.admin_name = encrypt_data(admin_name)
        if admin_email:
            self.admin_email = encrypt_data(admin_email)
            self.hashed_admin_email = hash_data(admin_email.strip().lower())

        self.total_earned = float(total_earned)
        self.total_paid_out = float(total_paid_out)
        self.pending_balance = float(pending_balance)
        self.currency = currency

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        doc = {
            "business_id": self.business_id,
            "admin_id": self.admin_id,
            "admin_name": getattr(self, "admin_name", None),
            "admin_email": getattr(self, "admin_email", None),
            "hashed_admin_email": getattr(self, "hashed_admin_email", None),
            "total_earned": self.total_earned,
            "total_paid_out": self.total_paid_out,
            "pending_balance": self.pending_balance,
            "currency": self.currency,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return {k: v for k, v in doc.items() if v is not None}

    @classmethod
    def _normalise(cls, doc):
        if not doc:
            return None
        for f in ["_id", "business_id", "admin_id"]:
            if doc.get(f):
                doc[f] = str(doc[f])
        for f in ["admin_name", "admin_email"]:
            if doc.get(f):
                try:
                    doc[f] = decrypt_data(doc[f])
                except Exception:
                    pass
        doc.pop("hashed_admin_email", None)
        doc["available_balance"] = round(doc.get("total_earned", 0) - doc.get("total_paid_out", 0), 2)
        return doc

    @classmethod
    def get_or_create(cls, admin_id, admin_name=None, admin_email=None):
        """Get existing wallet or create new one."""
        try:
            c = db.get_collection(cls.collection_name)
            doc = c.find_one({"admin_id": ObjectId(admin_id)})
            if doc:
                return cls._normalise(doc)

            wallet = cls(
                admin_id=admin_id,
                admin_name=admin_name,
                admin_email=admin_email,
            )
            wallet_id = wallet.save(processing_callback=True)
            if wallet_id:
                return cls._normalise(c.find_one({"_id": ObjectId(wallet_id)}))
            return None
        except Exception as e:
            Log.error(f"[CommissionWallet.get_or_create] {e}")
            return None

    @classmethod
    def get_by_admin(cls, admin_id):
        try:
            c = db.get_collection(cls.collection_name)
            return cls._normalise(c.find_one({"admin_id": ObjectId(admin_id)}))
        except Exception as e:
            Log.error(f"[CommissionWallet.get_by_admin] {e}")
            return None

    @classmethod
    def credit(cls, admin_id, amount, admin_name=None, admin_email=None):
        """Add commission to wallet balance."""
        try:
            c = db.get_collection(cls.collection_name)
            result = c.find_one_and_update(
                {"admin_id": ObjectId(admin_id)},
                {
                    "$inc": {"total_earned": round(amount, 2), "pending_balance": round(amount, 2)},
                    "$set": {"updated_at": datetime.utcnow()},
                },
                upsert=False,
                return_document=True,
            )
            if not result:
                cls.get_or_create(admin_id, admin_name, admin_email)
                c.find_one_and_update(
                    {"admin_id": ObjectId(admin_id)},
                    {
                        "$inc": {"total_earned": round(amount, 2), "pending_balance": round(amount, 2)},
                        "$set": {"updated_at": datetime.utcnow()},
                    },
                )
            Log.info(f"[CommissionWallet.credit] admin={admin_id} amount={amount}")
            return True
        except Exception as e:
            Log.error(f"[CommissionWallet.credit] {e}")
            return False

    @classmethod
    def record_payout(cls, admin_id, amount):
        """Record a payout to the admin."""
        try:
            c = db.get_collection(cls.collection_name)
            c.update_one(
                {"admin_id": ObjectId(admin_id)},
                {
                    "$inc": {"total_paid_out": round(amount, 2), "pending_balance": -round(amount, 2)},
                    "$set": {"updated_at": datetime.utcnow()},
                },
            )
            return True
        except Exception as e:
            Log.error(f"[CommissionWallet.record_payout] {e}")
            return False

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("admin_id", 1)], unique=True)
            return True
        except Exception as e:
            Log.error(f"[CommissionWallet.create_indexes] {e}")
            return False


# ═══════════════════════════════════════════════════════════════
# COMMISSION LEDGER (individual commission entries)
# ═══════════════════════════════════════════════════════════════

class CommissionLedger(BaseModel):
    """
    Individual commission transaction entries.
    Each successful payment from a referred business creates one entry.
    """

    collection_name = "commission_ledger"
    _subscription_exempt = True
    _permission_exempt = True

    TYPE_COMMISSION = "commission"
    TYPE_PAYOUT = "payout"
    TYPE_ADJUSTMENT = "adjustment"
    TYPES = [TYPE_COMMISSION, TYPE_PAYOUT, TYPE_ADJUSTMENT]

    def __init__(
        self,
        admin_id: str,
        entry_type: str,
        amount: float,
        currency: str = "USD",
        # Commission details
        referral_id: Optional[str] = None,
        referred_business_id: Optional[str] = None,
        payment_reference: Optional[str] = None,
        payment_amount: Optional[float] = None,
        commission_type: Optional[str] = None,
        commission_value: Optional[float] = None,
        plan_name: Optional[str] = None,
        billing_period: Optional[str] = None,
        month_number: Optional[int] = None,
        # Payout details
        payout_method: Optional[str] = None,
        payout_reference: Optional[str] = None,
        # Notes
        description: Optional[str] = None,
        # Internal
        user_id=None,
        user__id=None,
        business_id=None,
        **kwargs,
    ):
        super().__init__(
            user__id=user__id, user_id=user_id, business_id=business_id, **kwargs,
        )

        self.business_id = ObjectId(business_id) if business_id else None
        self.admin_id = ObjectId(admin_id)
        self.entry_type = entry_type
        self.amount = round(float(amount), 2)
        self.currency = currency

        if referral_id:
            self.referral_id = ObjectId(referral_id)
        if referred_business_id:
            self.referred_business_id = ObjectId(referred_business_id)
        if payment_reference:
            self.payment_reference = payment_reference
        if payment_amount is not None:
            self.payment_amount = float(payment_amount)
        if commission_type:
            self.commission_type = commission_type
        if commission_value is not None:
            self.commission_value = float(commission_value)
        if plan_name:
            self.plan_name = plan_name
        if billing_period:
            self.billing_period = billing_period
        if month_number is not None:
            self.month_number = int(month_number)
        if payout_method:
            self.payout_method = payout_method
        if payout_reference:
            self.payout_reference = payout_reference
        if description:
            self.description = description

        self.created_at = datetime.utcnow()

    def to_dict(self):
        doc = {k: v for k, v in self.__dict__.items() if v is not None}
        return doc

    @classmethod
    def _normalise(cls, doc):
        if not doc:
            return None
        for f in ["_id", "business_id", "admin_id", "referral_id", "referred_business_id"]:
            if doc.get(f):
                doc[f] = str(doc[f])
        return doc

    @classmethod
    def get_by_admin(cls, admin_id, entry_type=None, page=1, per_page=50):
        try:
            c = db.get_collection(cls.collection_name)
            q = {"admin_id": ObjectId(admin_id)}
            if entry_type:
                q["entry_type"] = entry_type
            total = c.count_documents(q)
            cursor = c.find(q).sort("created_at", -1).skip((page - 1) * per_page).limit(per_page)
            return {
                "entries": [cls._normalise(d) for d in cursor],
                "total_count": total,
                "total_pages": (total + per_page - 1) // per_page,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"[CommissionLedger.get_by_admin] {e}")
            return {"entries": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("admin_id", 1), ("created_at", -1)])
            c.create_index([("referral_id", 1)])
            c.create_index([("referred_business_id", 1)])
            c.create_index([("entry_type", 1), ("created_at", -1)])
            return True
        except Exception as e:
            Log.error(f"[CommissionLedger.create_indexes] {e}")
            return False


# ═══════════════════════════════════════════════════════════════
# COMMISSION SERVICE (orchestrates the flow)
# ═══════════════════════════════════════════════════════════════

class CommissionService:
    """
    Orchestrates promo code validation, referral tracking, and commission crediting.

    Call points:
      1. register_referral()     → during business registration (if promo_code provided)
      2. process_commission()    → after successful subscription payment (webhook/callback)
    """

    @staticmethod
    def register_referral(promo_code_str, referred_business_id, referred_business_name=None, referred_email=None):
        """
        Register a referral when a business signs up with a promo code.
        Called during business registration.

        Returns: (success, referral_doc_or_error)
        """
        log_tag = f"[CommissionService.register_referral][{promo_code_str}]"
        try:
            is_valid, result = PromoCode.validate_code(promo_code_str)
            if not is_valid:
                return False, result

            promo = result

            # Check if this business is already referred
            existing = Referral.get_by_business(str(referred_business_id))
            if existing:
                Log.info(f"{log_tag} Business already referred: {referred_business_id}")
                return True, existing

            # Create referral
            referral = Referral(
                promo_code_id=promo["_id"],
                promo_code=promo["code"],
                admin_id=promo["admin_id"],
                referred_business_id=str(referred_business_id),
                referred_business_name=referred_business_name,
                referred_by_email=referred_email,
                commission_type=promo.get("commission_type", "percentage"),
                commission_value=promo.get("commission_value", 10.0),
                commission_duration_months=promo.get("commission_duration_months"),
                status=Referral.STATUS_REGISTERED,
            )
            ref_id = referral.save(processing_callback=True)

            if ref_id:
                PromoCode.increment_usage(promo["_id"])
                Log.info(f"{log_tag} Referral registered: {ref_id}, admin={promo['admin_id']}")
                return True, Referral._normalise(db.get_collection(Referral.collection_name).find_one({"_id": ObjectId(ref_id)}))

            return False, "Failed to create referral record."
        except Exception as e:
            Log.error(f"{log_tag} {e}")
            return False, str(e)

    @staticmethod
    def process_commission(referred_business_id, payment_amount, payment_reference, currency="USD", plan_name=None, billing_period=None):
        """
        Calculate and credit commission after a successful payment from a referred business.
        Called from webhook after subscription payment succeeds.

        Returns: (commission_credited, amount)
        """
        log_tag = f"[CommissionService.process_commission][business={referred_business_id}]"
        try:
            referral = Referral.get_by_business(str(referred_business_id))
            if not referral:
                return False, 0

            # Check if commission duration has been exceeded
            duration_months = referral.get("commission_duration_months")
            months_tracked = referral.get("months_tracked", 0)
            if duration_months is not None and months_tracked >= duration_months:
                Log.info(f"{log_tag} Commission duration expired ({months_tracked}/{duration_months} months)")
                return False, 0

            # Calculate commission
            commission_type = referral.get("commission_type", "percentage")
            commission_value = referral.get("commission_value", 0)

            if commission_type == "percentage":
                commission_amount = round(payment_amount * (commission_value / 100), 2)
            else:
                commission_amount = min(commission_value, payment_amount)

            if commission_amount <= 0:
                return False, 0

            admin_id = referral.get("admin_id")
            referral_id = referral.get("_id")

            # Create ledger entry
            entry = CommissionLedger(
                admin_id=admin_id,
                entry_type=CommissionLedger.TYPE_COMMISSION,
                amount=commission_amount,
                currency=currency,
                referral_id=referral_id,
                referred_business_id=str(referred_business_id),
                payment_reference=payment_reference,
                payment_amount=payment_amount,
                commission_type=commission_type,
                commission_value=commission_value,
                plan_name=plan_name,
                billing_period=billing_period,
                month_number=months_tracked + 1,
                description=f"Commission from {plan_name or 'subscription'} payment ({billing_period or 'monthly'})",
            )
            entry.save(processing_callback=True)

            # Credit wallet
            CommissionWallet.credit(admin_id, commission_amount)

            # Update referral tracking
            c = db.get_collection(Referral.collection_name)
            c.update_one(
                {"_id": ObjectId(referral_id)},
                {
                    "$inc": {
                        "total_commission_earned": commission_amount,
                        "total_payments_tracked": 1,
                        "months_tracked": 1,
                    },
                    "$set": {
                        "status": Referral.STATUS_SUBSCRIBED,
                        "hashed_status": hash_data(Referral.STATUS_SUBSCRIBED),
                        "updated_at": datetime.utcnow(),
                    },
                },
            )

            Log.info(f"{log_tag} Commission credited: ${commission_amount} to admin={admin_id} (month {months_tracked + 1})")
            return True, commission_amount

        except Exception as e:
            Log.error(f"{log_tag} {e}")
            return False, 0

    @staticmethod
    def get_admin_dashboard(admin_id):
        """Get commission dashboard data for an admin."""
        try:
            wallet = CommissionWallet.get_or_create(admin_id)
            referrals = Referral.get_by_admin(admin_id, page=1, per_page=100)
            promo_codes = PromoCode.get_by_admin(admin_id)
            recent_entries = CommissionLedger.get_by_admin(admin_id, page=1, per_page=20)

            active_referrals = sum(1 for r in referrals.get("referrals", []) if r.get("status") == Referral.STATUS_SUBSCRIBED)

            return {
                "wallet": wallet,
                "summary": {
                    "total_earned": wallet.get("total_earned", 0) if wallet else 0,
                    "total_paid_out": wallet.get("total_paid_out", 0) if wallet else 0,
                    "available_balance": wallet.get("available_balance", 0) if wallet else 0,
                    "total_referrals": referrals.get("total_count", 0),
                    "active_referrals": active_referrals,
                    "promo_codes": len(promo_codes),
                },
                "promo_codes": promo_codes,
                "recent_referrals": referrals.get("referrals", [])[:10],
                "recent_commissions": recent_entries.get("entries", []),
            }
        except Exception as e:
            Log.error(f"[CommissionService.get_admin_dashboard] {e}")
            return {"wallet": None, "summary": {}, "promo_codes": [], "recent_referrals": [], "recent_commissions": []}
