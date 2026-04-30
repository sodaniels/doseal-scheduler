# app/models/admin/payment_method_model.py

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, Optional
from bson import ObjectId

from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.logger import Log


class PaymentMethod(BaseModel):
    """
    Stored payment method (Paystack authorization tokens).

    When a user pays via Paystack, the response includes an `authorization` object
    with a reusable `authorization_code`. We store this encrypted so the user
    can be charged again without re-entering card details.

    Each business can have multiple payment methods. One is marked as primary
    (used for auto-renewals and subscription charges). Others are secondary
    (available as fallback or manual selection).

    Webhook-safe: All write methods use processing_callback=True or direct DB
    queries so they work without an authenticated user context (g.current_user).
    """

    collection_name = "payment_methods"
    _subscription_exempt = True  # Users must manage cards even with expired subscription

    PROVIDER_PAYSTACK = "paystack"
    PROVIDER_STRIPE = "stripe"
    PROVIDER_FLUTTERWAVE = "flutterwave"
    PROVIDERS = [PROVIDER_PAYSTACK, PROVIDER_STRIPE, PROVIDER_FLUTTERWAVE]

    CARD_TYPE_VISA = "visa"
    CARD_TYPE_MASTERCARD = "mastercard"
    CARD_TYPE_VERVE = "verve"
    CARD_TYPE_AMEX = "amex"
    CARD_TYPE_DISCOVER = "discover"
    CARD_TYPES = [CARD_TYPE_VISA, CARD_TYPE_MASTERCARD, CARD_TYPE_VERVE, CARD_TYPE_AMEX, CARD_TYPE_DISCOVER]

    STATUS_ACTIVE = "Active"
    STATUS_EXPIRED = "Expired"
    STATUS_REVOKED = "Revoked"
    STATUS_FAILED = "Failed"
    STATUSES = [STATUS_ACTIVE, STATUS_EXPIRED, STATUS_REVOKED, STATUS_FAILED]

    FIELDS_TO_DECRYPT = ["card_holder_name", "email"]

    def __init__(
        self,
        provider: str,
        # Paystack authorization fields
        authorization_code: str = None,
        card_type: str = None,
        last4: str = None,
        exp_month: str = None,
        exp_year: str = None,
        bin: str = None,
        bank: str = None,
        channel: str = None,
        signature: str = None,
        reusable: bool = True,
        country_code: str = None,
        account_name: str = None,
        # Card holder info
        card_holder_name: str = None,
        email: str = None,
        # Metadata
        label: str = None,
        is_primary: bool = False,
        status: str = STATUS_ACTIVE,
        last_charged_at: datetime = None,
        last_charge_status: str = None,
        failed_attempts: int = 0,
        # Paystack customer
        paystack_customer_id: str = None,
        paystack_customer_code: str = None,
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
        self.provider = provider

        # ── Encrypted sensitive fields ──
        if authorization_code:
            self.authorization_code = encrypt_data(authorization_code)
        if signature:
            self.signature = encrypt_data(signature)
            self.hashed_signature = hash_data(signature)  # Fast duplicate lookup
        if card_holder_name:
            self.card_holder_name = encrypt_data(card_holder_name)
        if email:
            self.email = encrypt_data(email)
            self.hashed_email = hash_data(email.strip().lower())
        if paystack_customer_id:
            self.paystack_customer_id = encrypt_data(str(paystack_customer_id))
        if paystack_customer_code:
            self.paystack_customer_code = encrypt_data(str(paystack_customer_code))

        # ── Plain fields (non-sensitive, needed for display) ──
        if card_type:
            self.card_type = card_type.lower()
        if last4:
            self.last4 = str(last4)
        if exp_month:
            self.exp_month = str(exp_month)
        if exp_year:
            self.exp_year = str(exp_year)
        if bin:
            self.bin = str(bin)
        if bank:
            self.bank = bank
        if channel:
            self.channel = channel
        if country_code:
            self.country_code = country_code
        if account_name:
            self.account_name = account_name
        if label:
            self.label = label

        self.reusable = bool(reusable)
        self.is_primary = bool(is_primary)
        self.status = status
        self.hashed_status = hash_data(status.strip())

        self.last_charged_at = last_charged_at
        self.last_charge_status = last_charge_status
        self.failed_attempts = int(failed_attempts)

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        doc = {
            "business_id": self.business_id,
            "provider": self.provider,
            "authorization_code": getattr(self, "authorization_code", None),
            "signature": getattr(self, "signature", None),
            "hashed_signature": getattr(self, "hashed_signature", None),
            "card_holder_name": getattr(self, "card_holder_name", None),
            "email": getattr(self, "email", None),
            "hashed_email": getattr(self, "hashed_email", None),
            "paystack_customer_id": getattr(self, "paystack_customer_id", None),
            "paystack_customer_code": getattr(self, "paystack_customer_code", None),
            "card_type": getattr(self, "card_type", None),
            "last4": getattr(self, "last4", None),
            "exp_month": getattr(self, "exp_month", None),
            "exp_year": getattr(self, "exp_year", None),
            "bin": getattr(self, "bin", None),
            "bank": getattr(self, "bank", None),
            "channel": getattr(self, "channel", None),
            "country_code": getattr(self, "country_code", None),
            "account_name": getattr(self, "account_name", None),
            "label": getattr(self, "label", None),
            "reusable": self.reusable,
            "is_primary": self.is_primary,
            "status": self.status,
            "hashed_status": self.hashed_status,
            "last_charged_at": self.last_charged_at,
            "last_charge_status": self.last_charge_status,
            "failed_attempts": self.failed_attempts,
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
    def _normalise(cls, doc, include_auth_code=False):
        """
        Normalise for API response.
        NEVER exposes authorization_code, signature, or paystack_customer_id
        unless include_auth_code=True (internal use only for charging).
        """
        if not doc:
            return None

        for f in ["_id", "business_id"]:
            if doc.get(f):
                doc[f] = str(doc[f])

        for f in cls.FIELDS_TO_DECRYPT:
            if f in doc:
                doc[f] = cls._safe_decrypt(doc[f])

        # Decrypt auth code for internal charging
        if include_auth_code:
            if doc.get("authorization_code"):
                doc["authorization_code"] = cls._safe_decrypt(doc["authorization_code"])
            if doc.get("paystack_customer_code"):
                doc["paystack_customer_code"] = cls._safe_decrypt(doc["paystack_customer_code"])
        else:
            doc.pop("authorization_code", None)
            doc.pop("signature", None)
            doc.pop("paystack_customer_id", None)
            doc.pop("paystack_customer_code", None)

        # Always remove internal hashes
        doc.pop("hashed_status", None)
        doc.pop("hashed_email", None)
        doc.pop("hashed_signature", None)

        # Build display label if not set
        if not doc.get("label"):
            card_type = (doc.get("card_type") or "card").upper()
            last4 = doc.get("last4", "****")
            doc["label"] = f"{card_type} •••• {last4}"

        # Expiry display + expired check
        exp_month = doc.get("exp_month")
        exp_year = doc.get("exp_year")
        if exp_month and exp_year:
            doc["expiry_display"] = f"{exp_month}/{exp_year}"
            try:
                now = datetime.utcnow()
                exp_m = int(exp_month)
                exp_y = int(exp_year)
                if exp_y < 100:
                    exp_y += 2000
                doc["is_expired"] = (exp_y < now.year or (exp_y == now.year and exp_m < now.month))
            except Exception:
                doc["is_expired"] = False
        else:
            doc["is_expired"] = False

        return doc

    # ═══════════════════════════════════════════════════════════════
    # QUERIES
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def get_by_id(cls, method_id, business_id=None, include_auth_code=False):
        try:
            c = db.get_collection(cls.collection_name)
            q = {"_id": ObjectId(method_id)}
            if business_id:
                q["business_id"] = ObjectId(business_id)
            return cls._normalise(c.find_one(q), include_auth_code=include_auth_code)
        except Exception as e:
            Log.error(f"[PaymentMethod.get_by_id] {e}")
            return None

    @classmethod
    def get_all_by_business(cls, business_id, status=None):
        """Get all payment methods for a business, primary first."""
        try:
            c = db.get_collection(cls.collection_name)
            q = {"business_id": ObjectId(business_id)}
            if status:
                q["hashed_status"] = hash_data(status.strip())
            cursor = c.find(q).sort([("is_primary", -1), ("created_at", -1)])
            return [cls._normalise(d) for d in cursor]
        except Exception as e:
            Log.error(f"[PaymentMethod.get_all_by_business] {e}")
            return []

    @classmethod
    def get_primary(cls, business_id, include_auth_code=False):
        """Get the primary payment method for a business."""
        try:
            c = db.get_collection(cls.collection_name)
            q = {
                "business_id": ObjectId(business_id),
                "is_primary": True,
                "hashed_status": hash_data(cls.STATUS_ACTIVE),
            }
            return cls._normalise(c.find_one(q), include_auth_code=include_auth_code)
        except Exception as e:
            Log.error(f"[PaymentMethod.get_primary] {e}")
            return None

    @classmethod
    def get_by_signature(cls, business_id, signature):
        """
        Check if a card (by Paystack signature) already exists to prevent duplicates.
        Uses hashed_signature for O(1) lookup instead of decrypting every card.
        """
        try:
            if not signature:
                return None
            c = db.get_collection(cls.collection_name)
            q = {
                "business_id": ObjectId(business_id),
                "hashed_signature": hash_data(signature),
            }
            doc = c.find_one(q)
            return cls._normalise(doc) if doc else None
        except Exception as e:
            Log.error(f"[PaymentMethod.get_by_signature] {e}")
            return None

    # ═══════════════════════════════════════════════════════════════
    # PRIMARY / SECONDARY MANAGEMENT
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def set_primary(cls, method_id, business_id):
        """
        Set a payment method as primary. Demotes all others to secondary.
        Returns True if successful.
        """
        try:
            c = db.get_collection(cls.collection_name)

            # Verify the method exists and is active
            method = c.find_one({
                "_id": ObjectId(method_id),
                "business_id": ObjectId(business_id),
                "hashed_status": hash_data(cls.STATUS_ACTIVE),
            })
            if not method:
                return False

            # Demote all current primary methods for this business
            c.update_many(
                {"business_id": ObjectId(business_id), "is_primary": True},
                {"$set": {"is_primary": False, "updated_at": datetime.utcnow()}},
            )

            # Promote the selected method
            result = c.update_one(
                {"_id": ObjectId(method_id), "business_id": ObjectId(business_id)},
                {"$set": {"is_primary": True, "updated_at": datetime.utcnow()}},
            )

            Log.info(f"[PaymentMethod.set_primary] method={method_id} set as primary for business={business_id}")
            return result.modified_count > 0
        except Exception as e:
            Log.error(f"[PaymentMethod.set_primary] {e}")
            return False

    @classmethod
    def _auto_promote_next_primary(cls, business_id):
        """Promote the next active card to primary when current primary is failed/revoked."""
        try:
            # Check if there's already an active primary
            existing_primary = cls.get_primary(business_id)
            if existing_primary:
                return  # Already have a primary — nothing to do

            c = db.get_collection(cls.collection_name)
            next_card = c.find_one(
                {
                    "business_id": ObjectId(business_id),
                    "hashed_status": hash_data(cls.STATUS_ACTIVE),
                    "reusable": True,
                },
                sort=[("created_at", -1)],
            )

            if next_card:
                cls.set_primary(str(next_card["_id"]), business_id)
                Log.info(f"[PaymentMethod._auto_promote_next_primary] promoted {next_card['_id']} for business={business_id}")
            else:
                Log.info(f"[PaymentMethod._auto_promote_next_primary] no active cards remaining for business={business_id}")
        except Exception as e:
            Log.error(f"[PaymentMethod._auto_promote_next_primary] {e}")

    @classmethod
    def save_from_paystack(cls, business_id, paystack_response, user_id=None, user__id=None, set_as_primary=False, label=None):
        """
        Save a payment method from a Paystack transaction/charge response.

        Webhook-safe: uses processing_callback=True on save() and handles
        None/null values from Paystack's customer object gracefully.

        Args:
            business_id: The business ID
            paystack_response: The Paystack API response data (contains authorization + customer)
            user_id, user__id: The user who made the payment (may be None in webhook context)
            set_as_primary: Whether to set this as the primary method
            label: Optional display label (e.g. "Office Card", "Pastor's Card")

        Returns:
            The created/existing PaymentMethod document or None
        """
        log_tag = f"[PaymentMethod.save_from_paystack][business={business_id}]"
        try:
            auth = paystack_response.get("authorization") or {}
            customer = paystack_response.get("customer") or {}

            if not auth:
                Log.error(f"{log_tag} No authorization in response")
                return None

            # Check if card is reusable
            if not auth.get("reusable", False):
                Log.info(f"{log_tag} Card is not reusable, skipping save")
                return None

            # Check for duplicate via hashed_signature (fast O(1) lookup)
            signature = auth.get("signature")
            if signature:
                existing = cls.get_by_signature(str(business_id), signature)
                if existing:
                    Log.info(f"{log_tag} Card already exists: {existing.get('_id')}")
                    if set_as_primary:
                        cls.set_primary(existing["_id"], str(business_id))
                    return existing

            # If no existing methods, auto-set as primary
            existing_methods = cls.get_all_by_business(str(business_id), status=cls.STATUS_ACTIVE)
            if not existing_methods:
                set_as_primary = True

            # ── Safely extract customer data (Paystack may return null for any field) ──
            first_name = customer.get("first_name") or ""
            last_name = customer.get("last_name") or ""
            card_holder_name = f"{first_name} {last_name}".strip() or None

            customer_email = customer.get("email") or None

            customer_id = customer.get("id")
            customer_code = customer.get("customer_code")

            # user__id may be string, ObjectId, or None (webhook context)
            safe_user__id = str(user__id) if user__id else None

            method = cls(
                provider=cls.PROVIDER_PAYSTACK,
                authorization_code=auth.get("authorization_code"),
                card_type=auth.get("card_type"),
                last4=auth.get("last4"),
                exp_month=auth.get("exp_month"),
                exp_year=auth.get("exp_year"),
                bin=auth.get("bin"),
                bank=auth.get("bank"),
                channel=auth.get("channel"),
                signature=signature,
                reusable=auth.get("reusable", True),
                country_code=auth.get("country_code"),
                account_name=auth.get("account_name"),
                card_holder_name=card_holder_name,
                email=customer_email,
                paystack_customer_id=str(customer_id) if customer_id else None,
                paystack_customer_code=str(customer_code) if customer_code else None,
                label=label,
                is_primary=set_as_primary,
                status=cls.STATUS_ACTIVE,
                user_id=user_id,
                user__id=safe_user__id,
                business_id=str(business_id),
            )

            # processing_callback=True: skips permission + subscription checks (webhook-safe)
            method_id = method.save(processing_callback=True)
            if not method_id:
                Log.error(f"{log_tag} Failed to save payment method")
                return None

            # If setting as primary, demote others
            if set_as_primary:
                cls.set_primary(method_id, str(business_id))

            card_display = f"{(auth.get('card_type') or 'card').upper()} ****{auth.get('last4', '????')}"
            Log.info(f"{log_tag} saved: {method_id} ({card_display}), primary={set_as_primary}")
            return cls.get_by_id(method_id, str(business_id))

        except Exception as e:
            Log.error(f"{log_tag} {e}")
            return None

    # ═══════════════════════════════════════════════════════════════
    # CHARGE (used by subscription renewal)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def get_chargeable_method(cls, business_id):
        """
        Get the method to charge for subscription.
        Tries primary first, then any active non-expired card with valid auth_code + email.
        Returns the method with decrypted authorization_code (internal use only).
        """
        try:
            # Try primary first
            primary = cls.get_primary(str(business_id), include_auth_code=True)
            if primary and not primary.get("is_expired", False):
                auth_code = primary.get("authorization_code")
                email = primary.get("email")
                if auth_code and email:
                    return primary

            # Fallback: any active, reusable, non-expired card
            c = db.get_collection(cls.collection_name)
            cursor = c.find({
                "business_id": ObjectId(business_id),
                "hashed_status": hash_data(cls.STATUS_ACTIVE),
                "reusable": True,
            }).sort("created_at", -1)

            for doc in cursor:
                normalised = cls._normalise(dict(doc), include_auth_code=True)
                if normalised and not normalised.get("is_expired", False):
                    auth_code = normalised.get("authorization_code")
                    email = normalised.get("email")
                    if auth_code and email:
                        return normalised

            Log.info(f"[PaymentMethod.get_chargeable_method] No chargeable method for business={business_id}")
            return None
        except Exception as e:
            Log.error(f"[PaymentMethod.get_chargeable_method] {e}")
            return None

    @classmethod
    def record_charge_result(cls, method_id, business_id, success, status_message=None):
        """
        Record the result of a charge attempt.
        After 3 consecutive failures: auto-marks card as Failed and promotes next card.
        Uses atomic find_one_and_update to prevent race conditions.
        """
        log_tag = f"[PaymentMethod.record_charge_result][method={method_id}]"
        try:
            c = db.get_collection(cls.collection_name)
            now = datetime.utcnow()

            if success:
                c.update_one(
                    {"_id": ObjectId(method_id), "business_id": ObjectId(business_id)},
                    {"$set": {
                        "last_charged_at": now,
                        "last_charge_status": "success",
                        "failed_attempts": 0,
                        "updated_at": now,
                    }},
                )
                Log.info(f"{log_tag} charge successful")
                return

            # Failed charge — atomic increment + check
            result = c.find_one_and_update(
                {"_id": ObjectId(method_id), "business_id": ObjectId(business_id)},
                {
                    "$inc": {"failed_attempts": 1},
                    "$set": {
                        "last_charged_at": now,
                        "last_charge_status": f"failed: {status_message or 'unknown'}",
                        "updated_at": now,
                    },
                },
                return_document=True,
            )

            if not result:
                Log.error(f"{log_tag} method not found")
                return

            failures = result.get("failed_attempts", 0)

            if failures >= 3:
                # Mark card as failed and demote from primary
                c.update_one(
                    {"_id": ObjectId(method_id), "business_id": ObjectId(business_id)},
                    {"$set": {
                        "status": cls.STATUS_FAILED,
                        "hashed_status": hash_data(cls.STATUS_FAILED),
                        "is_primary": False,
                        "updated_at": now,
                    }},
                )
                Log.info(f"{log_tag} marked as FAILED after {failures} consecutive failures")

                # Auto-promote next active card
                cls._auto_promote_next_primary(str(business_id))
            else:
                Log.info(f"{log_tag} charge failed ({failures}/3): {status_message}")

        except Exception as e:
            Log.error(f"{log_tag} {e}")

    @classmethod
    def revoke(cls, method_id, business_id):
        """Revoke/remove a payment method. Auto-promotes next card if primary was revoked."""
        try:
            c = db.get_collection(cls.collection_name)

            method = c.find_one({"_id": ObjectId(method_id), "business_id": ObjectId(business_id)})
            if not method:
                return False

            was_primary = method.get("is_primary", False)

            result = c.update_one(
                {"_id": ObjectId(method_id), "business_id": ObjectId(business_id)},
                {"$set": {
                    "status": cls.STATUS_REVOKED,
                    "hashed_status": hash_data(cls.STATUS_REVOKED),
                    "is_primary": False,
                    "updated_at": datetime.utcnow(),
                }},
            )

            # If we revoked the primary, promote the next active card
            if was_primary and result.modified_count > 0:
                cls._auto_promote_next_primary(str(business_id))

            return result.modified_count > 0
        except Exception as e:
            Log.error(f"[PaymentMethod.revoke] {e}")
            return False

    # ═══════════════════════════════════════════════════════════════
    # UTILITY
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def get_card_summary(cls, business_id):
        """Get a brief summary for dashboard/billing page display."""
        try:
            methods = cls.get_all_by_business(str(business_id), status=cls.STATUS_ACTIVE)
            primary = next((m for m in methods if m.get("is_primary")), None)

            return {
                "total_cards": len(methods),
                "has_primary": primary is not None,
                "primary_card": {
                    "label": primary.get("label"),
                    "last4": primary.get("last4"),
                    "card_type": primary.get("card_type"),
                    "expiry_display": primary.get("expiry_display"),
                    "is_expired": primary.get("is_expired", False),
                } if primary else None,
                "cards": [
                    {
                        "_id": m.get("_id"),
                        "label": m.get("label"),
                        "last4": m.get("last4"),
                        "card_type": m.get("card_type"),
                        "is_primary": m.get("is_primary"),
                        "expiry_display": m.get("expiry_display"),
                        "is_expired": m.get("is_expired", False),
                    }
                    for m in methods
                ],
            }
        except Exception as e:
            Log.error(f"[PaymentMethod.get_card_summary] {e}")
            return {"total_cards": 0, "has_primary": False, "primary_card": None, "cards": []}

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("business_id", 1), ("is_primary", -1), ("hashed_status", 1)])
            c.create_index([("business_id", 1), ("hashed_status", 1), ("reusable", 1)])
            c.create_index([("business_id", 1), ("hashed_email", 1)])
            # Unique sparse: prevents duplicate cards per business (same Paystack signature)
            c.create_index([("business_id", 1), ("hashed_signature", 1)], unique=True, sparse=True)
            Log.info("[PaymentMethod.create_indexes] Indexes created successfully")
            return True
        except Exception as e:
            Log.error(f"[PaymentMethod.create_indexes] {e}")
            return False
