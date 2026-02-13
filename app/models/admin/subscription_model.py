# app/models/admin/subscription_model.py

import os
from datetime import datetime, timedelta
from bson import ObjectId
from typing import Optional, Dict, Any, List, Union
from flask import jsonify

from ...models.business_model import Business

from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.logger import Log


class Subscription(BaseModel):
    """
    Business subscription model.
    Tracks subscriptions as immutable "terms".
    When renewed after cancellation/expiry, create a NEW subscription document.
    """

    collection_name = "subscriptions"

    # Subscription Statuses (store encrypted + hashed)
    STATUS_TRIAL = "Trial"
    STATUS_TRIAL_EXPIRED = "TrialExpired"
    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_SCHEDULED = "Scheduled"
    STATUS_EXPIRED = "Expired"
    STATUS_CANCELLED = "Cancelled"
    STATUS_SUSPENDED = "Suspended"

    # Fields to decrypt
    FIELDS_TO_DECRYPT = ["status", "cancellation_reason", "suspension_reason", "billing_period", "currency"]
    
    # -------------------------
    # Trial Constants
    # -------------------------
    DEFAULT_TRIAL_DAYS = 30

    def __init__(
        self,
        business_id,
        package_id,
        user_id,
        user__id,
        billing_period,
        price_paid,
        currency="USD",

        # Dates
        start_date=None,
        end_date=None,
        trial_end_date=None,

        # Status
        status=STATUS_TRIAL,
        auto_renew=True,

        # Payment
        payment_method=None,
        payment_reference=None,
        last_payment_date=None,
        next_payment_date=None,

        # Cancellation/Suspension
        cancellation_reason=None,
        cancelled_at=None,
        suspension_reason=None,
        suspended_at=None,

        # NEW: term tracking
        previous_subscription_id: Optional[Union[str, ObjectId]] = None,
        term_number: Optional[int] = None,

        **kwargs
    ):
        super().__init__(
            business_id=business_id,
            user__id=user__id,
            user_id=user_id,
            **kwargs
        )

        # Convert to ObjectId
        self.business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
        self.package_id = ObjectId(package_id) if not isinstance(package_id, ObjectId) else package_id
        self.user__id = ObjectId(user__id) if not isinstance(user__id, ObjectId) else user__id

        # NEW: term linking
        self.previous_subscription_id = (
            ObjectId(previous_subscription_id)
            if previous_subscription_id and not isinstance(previous_subscription_id, ObjectId)
            else previous_subscription_id
        )
        self.term_number = int(term_number) if term_number is not None else None

        # Subscription details - ENCRYPTED
        self.status = encrypt_data(status)
        self.hashed_status = hash_data(status)

        # Pricing - ENCRYPTED
        self.price_paid = encrypt_data(str(price_paid))
        self.currency = encrypt_data(currency)
        self.billing_period = encrypt_data(billing_period)

        # Dates - PLAIN
        self.start_date = start_date or datetime.utcnow()
        self.end_date = end_date
        self.trial_end_date = trial_end_date

        # Auto-renewal - PLAIN
        self.auto_renew = bool(auto_renew)

        # Payment tracking - PLAIN
        self.user_id = user_id
        self.payment_method = payment_method
        self.payment_reference = payment_reference
        self.last_payment_date = last_payment_date
        self.next_payment_date = next_payment_date

        # Cancellation/Suspension - ENCRYPTED
        self.cancellation_reason = encrypt_data(cancellation_reason) if cancellation_reason else None
        self.cancelled_at = cancelled_at
        self.suspension_reason = encrypt_data(suspension_reason) if suspension_reason else None
        self.suspended_at = suspended_at

        # Timestamps
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        doc = {
            "business_id": self.business_id,
            "package_id": self.package_id,
            "user_id": self.user_id,
            "user__id": self.user__id,

            "billing_period": self.billing_period,
            "price_paid": self.price_paid,
            "currency": self.currency,

            "start_date": self.start_date,
            "status": self.status,
            "hashed_status": self.hashed_status,
            "auto_renew": self.auto_renew,

            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

        # NEW: term fields
        if self.previous_subscription_id:
            doc["previous_subscription_id"] = self.previous_subscription_id
        if self.term_number is not None:
            doc["term_number"] = self.term_number

        # Optional fields
        if self.end_date:
            doc["end_date"] = self.end_date
        if self.trial_end_date:
            doc["trial_end_date"] = self.trial_end_date
        if self.payment_method:
            doc["payment_method"] = self.payment_method
        if self.payment_reference:
            doc["payment_reference"] = self.payment_reference
        if self.last_payment_date:
            doc["last_payment_date"] = self.last_payment_date
        if self.next_payment_date:
            doc["next_payment_date"] = self.next_payment_date
        if self.cancellation_reason:
            doc["cancellation_reason"] = self.cancellation_reason
        if self.cancelled_at:
            doc["cancelled_at"] = self.cancelled_at
        if self.suspension_reason:
            doc["suspension_reason"] = self.suspension_reason
        if self.suspended_at:
            doc["suspended_at"] = self.suspended_at

        return doc

    # ---------------- INTERNAL HELPER ---------------- #
    
    @classmethod
    def _safe_decrypt(cls, value):
        """Safely decrypt a value, returning original if decryption fails."""
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        try:
            return decrypt_data(value)
        except Exception:
            return value

    @staticmethod
    def _normalise_subscription_doc(subscription: dict) -> Optional[dict]:
        if not subscription:
            return None

        subscription["_id"] = str(subscription["_id"])
        subscription["business_id"] = str(subscription["business_id"])
        subscription["package_id"] = str(subscription["package_id"])
        subscription["user_id"] = str(subscription["user_id"])
        if subscription.get("user__id"):
            subscription["user__id"] = str(subscription["user__id"])
        if subscription.get("previous_subscription_id"):
            subscription["previous_subscription_id"] = str(subscription["previous_subscription_id"])
            
        if subscription.get("cancelled_by"):
            subscription["cancelled_by"] = str(subscription["cancelled_by"])
            
        # Decrypt fields
        for field in Subscription.FIELDS_TO_DECRYPT:
            if field in subscription and subscription[field] is not None:
                subscription[field] = decrypt_data(subscription[field])

        # Decrypt pricing
        if subscription.get("price_paid"):
            try:
                subscription["price_paid"] = float(decrypt_data(subscription["price_paid"]))
            except Exception:
                subscription["price_paid"] = 0.0

        subscription.pop("hashed_status", None)
        return subscription

    # ---------------- QUERIES ---------------- #
    @classmethod
    def get_all(cls, business_id):
        """
        Retrieve all records for a business by business_id after checking permission.
        """
        # Permission check
        if not cls.check_permission("read"):
            raise PermissionError(f"User does not have permission to read {cls.__name__}.")

        col = db.get_collection(cls.collection_name)
        docs = col.find({"business_id": ObjectId(business_id)})

        # Return normalized dicts
        results = []
        for d in docs:
            # normalize objectid and encrypted fields if you have a normalise method
            record = cls._normalise_subscription_doc(d) if hasattr(cls, "_normalise_subscription_doc") else d
            results.append(record)

        return results

    @classmethod
    def insert_one(cls, doc: Dict[str, Any]) -> str:
        col = db.get_collection(cls.collection_name)
        res = col.insert_one(doc)
        return str(res.inserted_id)

    @classmethod
    def get_by_id(cls, subscription_id, business_id) -> Optional[dict]:
        log_tag = f"[subscription_model.py][Subscription][get_by_id][{subscription_id}]"
        try:
            sid = ObjectId(subscription_id) if not isinstance(subscription_id, ObjectId) else subscription_id
            bid = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            col = db.get_collection(cls.collection_name)
            sub = col.find_one({"_id": sid, "business_id": bid})
            return cls._normalise_subscription_doc(sub)
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None

    @classmethod
    def get_latest_by_business(cls, business_id: str) -> Optional[dict]:
        log_tag = f"[subscription_model.py][Subscription][get_latest_by_business][{business_id}]"
        try:
            bid = ObjectId(business_id)
            col = db.get_collection(cls.collection_name)
            sub = col.find_one({"business_id": bid}, sort=[("created_at", -1)])
            return cls._normalise_subscription_doc(sub)
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return None

    @classmethod
    def get_active_by_business(cls, business_id: str) -> Optional[dict]:
        """
        Get active subscription (Active or Trial) for a business.
        """
        log_tag = f"[Subscription][get_active_by_business][{business_id}]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            # Query for Active or Trial status
            query = {
                "business_id": ObjectId(business_id),
                "$or": [
                    {"hashed_status": hash_data(cls.STATUS_ACTIVE)},
                    {"hashed_status": hash_data(cls.STATUS_TRIAL)},
                ],
            }
            
            subscription = collection.find_one(query, sort=[("created_at", -1)])
            
            if subscription:
                return cls._normalise_subscription_doc(subscription)
            
            return None
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return None
    
    @classmethod
    def get_latest_by_business(cls, business_id: str) -> Optional[dict]:
        """
        Get the latest subscription for a business regardless of status.
        """
        log_tag = f"[Subscription][get_latest_by_business][{business_id}]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            subscription = collection.find_one(
                {"business_id": ObjectId(business_id)},
                sort=[("created_at", -1)]
            )
            
            if subscription:
                return cls._normalise_subscription_doc(subscription)
            
            return None
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return None
    
    @classmethod
    def get_trial_status(cls, business_id: str) -> dict:
        """
        Get detailed trial status for a business.
        
        Returns:
            {
                "has_used_trial": bool,
                "is_on_trial": bool,
                "trial_days_remaining": int or None,
                "trial_end_date": datetime or None,
                "trial_expired": bool,
                "can_start_trial": bool,
            }
        """
        log_tag = f"[Subscription][get_trial_status][{business_id}]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            # Find any trial subscription for this business
            trial_sub = collection.find_one({
                "business_id": ObjectId(business_id),
                "is_trial": True,
            })
            
            if not trial_sub:
                return {
                    "has_used_trial": False,
                    "is_on_trial": False,
                    "trial_days_remaining": None,
                    "trial_end_date": None,
                    "trial_expired": False,
                    "can_start_trial": True,
                }
            
            # Decrypt status
            status = cls._safe_decrypt(trial_sub.get("status"))
            trial_end_date = trial_sub.get("trial_end_date")
            now = datetime.utcnow()
            
            is_on_trial = status == cls.STATUS_TRIAL
            trial_expired = status == cls.STATUS_TRIAL_EXPIRED or (trial_end_date and now > trial_end_date)
            
            # Calculate days remaining
            trial_days_remaining = None
            if trial_end_date and not trial_expired:
                delta = trial_end_date - now
                trial_days_remaining = max(0, delta.days)
            
            return {
                "has_used_trial": True,
                "is_on_trial": is_on_trial and not trial_expired,
                "trial_days_remaining": trial_days_remaining,
                "trial_end_date": trial_end_date.isoformat() if trial_end_date else None,
                "trial_expired": trial_expired,
                "can_start_trial": False,  # Already used trial
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return {
                "has_used_trial": False,
                "is_on_trial": False,
                "trial_days_remaining": None,
                "trial_end_date": None,
                "trial_expired": False,
                "can_start_trial": True,
            }
    
    @classmethod
    def expire_trial(cls, subscription_id: str, log_tag: str = "") -> bool:
        """
        Mark a trial subscription as expired.
        """
        log_tag = log_tag or f"[Subscription][expire_trial][{subscription_id}]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            result = collection.update_one(
                {"_id": ObjectId(subscription_id)},
                {
                    "$set": {
                        "status": encrypt_data(cls.STATUS_TRIAL_EXPIRED),
                        "hashed_status": hash_data(cls.STATUS_TRIAL_EXPIRED),
                        "expired_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                    }
                }
            )
            
            if result.modified_count > 0:
                Log.info(f"{log_tag} Trial expired successfully")
                
                # Get subscription to update business status
                sub = collection.find_one({"_id": ObjectId(subscription_id)})
                if sub:
                    cls._update_business_subscription_status(
                        business_id=str(sub["business_id"]),
                        subscribed=False,
                        is_trial=True,
                        trial_expired=True,
                        log_tag=log_tag,
                    )
                
                return True
            
            return False
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return False
    
    @classmethod
    def convert_trial_to_paid(
        cls,
        subscription_id: str,
        payment_data: dict,
        log_tag: str = "",
    ) -> Optional[dict]:
        """
        Convert a trial subscription to a paid subscription.
        
        Args:
            subscription_id: The trial subscription ID
            payment_data: Payment details including:
                - price_paid: Amount paid
                - currency: Currency code
                - billing_period: monthly/yearly/etc
                - payment_reference: Payment gateway reference
                - payment_method: Payment method used
        
        Returns:
            Updated subscription document or None
        """
        log_tag = log_tag or f"[Subscription][convert_trial_to_paid][{subscription_id}]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            # Get existing subscription
            subscription = collection.find_one({"_id": ObjectId(subscription_id)})
            
            if not subscription:
                Log.error(f"{log_tag} Subscription not found")
                return None
            
            if not subscription.get("is_trial"):
                Log.error(f"{log_tag} Subscription is not a trial")
                return None
            
            now = datetime.utcnow()
            billing_period = payment_data.get("billing_period", "monthly")
            
            # Calculate new end date based on billing period
            if billing_period == "monthly":
                end_date = now + timedelta(days=30)
            elif billing_period == "quarterly":
                end_date = now + timedelta(days=90)
            elif billing_period == "yearly":
                end_date = now + timedelta(days=365)
            else:
                end_date = now + timedelta(days=30)
            
            # Update subscription
            update_doc = {
                "status": encrypt_data(cls.STATUS_ACTIVE),
                "hashed_status": hash_data(cls.STATUS_ACTIVE),
                
                # Payment info
                "price_paid": encrypt_data(str(payment_data.get("price_paid", 0))),
                "currency": encrypt_data(payment_data.get("currency", "GBP")),
                "billing_period": encrypt_data(billing_period),
                
                # Dates
                "paid_at": now,
                "start_date": now,
                "end_date": end_date,
                
                # Payment reference
                "payment_reference": payment_data.get("payment_reference"),
                "payment_method": payment_data.get("payment_method"),
                
                # Subscription settings
                "auto_renew": payment_data.get("auto_renew", True),
                "term_number": 1,
                
                # Timestamps
                "converted_from_trial_at": now,
                "updated_at": now,
            }
            
            result = collection.update_one(
                {"_id": ObjectId(subscription_id)},
                {"$set": update_doc}
            )
            
            if result.modified_count > 0:
                Log.info(f"{log_tag} Trial converted to paid successfully")
                
                # Update business status
                cls._update_business_subscription_status(
                    business_id=str(subscription["business_id"]),
                    subscribed=True,
                    is_trial=False,
                    log_tag=log_tag,
                )
                
                updated_sub = collection.find_one({"_id": ObjectId(subscription_id)})
                return cls._normalise_subscription_doc(updated_sub)
            
            return None
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return None
    
    @classmethod
    def get_current_access_by_business(cls, business_id: str) -> Optional[dict]:
        """
        The subscription that currently grants access:
        Active or Trial (latest)
        """
        log_tag = f"[subscription_model.py][Subscription][get_current_access_by_business][{business_id}]"
        try:
            bid = ObjectId(business_id)
            col = db.get_collection(cls.collection_name)

            sub = col.find_one(
                {
                    "business_id": bid,
                    "hashed_status": {"$in": [hash_data(cls.STATUS_ACTIVE), hash_data(cls.STATUS_TRIAL)]},
                },
                sort=[("created_at", -1)]
            )
            return cls._normalise_subscription_doc(sub)
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return None

    @classmethod
    def mark_all_access_subscriptions_inactive(cls, business_id: str) -> int:
        """
        Ensures at most one Active/Trial exists.
        When creating a new term, we mark other Active/Trial as Inactive.
        """
        log_tag = f"[subscription_model.py][Subscription][mark_all_access_subscriptions_inactive][{business_id}]"
        try:
            bid = ObjectId(business_id)
            col = db.get_collection(cls.collection_name)

            res = col.update_many(
                {
                    "business_id": bid,
                    "hashed_status": {"$in": [hash_data(cls.STATUS_ACTIVE), hash_data(cls.STATUS_TRIAL)]},
                },
                {
                    "$set": {
                        "status": encrypt_data(cls.STATUS_INACTIVE),
                        "hashed_status": hash_data(cls.STATUS_INACTIVE),
                        "updated_at": datetime.utcnow(),
                    }
                }
            )
            return int(res.modified_count or 0)
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return 0

    @classmethod
    def cancel_subscription(cls, subscription_id, business_id, reason=None) -> bool:
        log_tag = f"[subscription_model.py][Subscription][cancel_subscription][{subscription_id}]"
        try:
            sid = ObjectId(subscription_id) if not isinstance(subscription_id, ObjectId) else subscription_id
            bid = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            col = db.get_collection(cls.collection_name)

            update_doc = {
                "status": encrypt_data(cls.STATUS_CANCELLED),
                "hashed_status": hash_data(cls.STATUS_CANCELLED),
                "cancelled_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
                "auto_renew": False,
            }
            if reason:
                update_doc["cancellation_reason"] = encrypt_data(reason)

            res = col.update_one({"_id": sid, "business_id": bid}, {"$set": update_doc})
            return res.modified_count > 0

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False

    @classmethod
    def payment_reference_exists(cls, payment_reference: str) -> bool:
        if not payment_reference:
            return False
        col = db.get_collection(cls.collection_name)
        return col.find_one(
            {"payment_reference": payment_reference},
            {"_id": 1}
        ) is not None
    
    
    # =========================================
    # TRIAL SUBSCRIPTION METHODS
    # =========================================
    @classmethod
    def _update_business_subscription_status(
        cls,
        business_id: str,
        subscribed: bool,
        is_trial: bool = False,
        trial_expired: bool = False,
        log_tag: str = "",
    ):
        """
        Update business account_status to reflect subscription status.
        """
        log_tag = log_tag or f"[Subscription][_update_business_subscription_status][{business_id}]"
        
        try:
            business_col = db.get_collection("businesses")
            
            # Get current business
            business = business_col.find_one({"_id": ObjectId(business_id)})
            
            if not business:
                Log.error(f"{log_tag} Business not found")
                return
            
            # Decrypt current account_status
            current_status = business.get("account_status")
            if current_status and isinstance(current_status, str):
                try:
                    current_status = decrypt_data(current_status)
                except:
                    current_status = []
            
            if not isinstance(current_status, list):
                current_status = []
            
            # Update or add subscribed_to_package status
            now = str(datetime.utcnow())
            new_subscription_status = {
                "subscribed_to_package": {
                    "status": subscribed,
                    "is_trial": is_trial,
                    "trial_expired": trial_expired,
                    "updated_at": now,
                }
            }
            
            # Find and update the subscribed_to_package entry
            found = False
            for i, item in enumerate(current_status):
                if isinstance(item, dict) and "subscribed_to_package" in item:
                    current_status[i] = new_subscription_status
                    found = True
                    break
            
            if not found:
                current_status.append(new_subscription_status)
            
            # Update business
            business_col.update_one(
                {"_id": ObjectId(business_id)},
                {
                    "$set": {
                        "account_status": encrypt_data(current_status),
                        "updated_at": datetime.utcnow(),
                    }
                }
            )
            
            Log.info(f"{log_tag} Business subscription status updated: subscribed={subscribed}, is_trial={is_trial}")
            
        except Exception as e:
            Log.error(f"{log_tag} Error updating business status: {e}")
    
    @classmethod
    def get_expired_trials(cls) -> list:
        """
        Get all expired trials that need to be marked as expired.
        """
        log_tag = f"[Subscription][get_expired_trials]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            now = datetime.utcnow()
            
            query = {
                "is_trial": True,
                "hashed_status": hash_data(cls.STATUS_TRIAL),
                "trial_end_date": {"$lt": now},
            }
            
            trials = list(collection.find(query))
            return [cls._normalise_subscription_doc(t) for t in trials]
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return []
    
    
    @classmethod
    def get_expiring_trials(cls, days_until_expiry: int = 3) -> list:
        """
        Get trials expiring within the specified number of days.
        Useful for sending reminder emails.
        """
        log_tag = f"[Subscription][get_expiring_trials]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            now = datetime.utcnow()
            expiry_threshold = now + timedelta(days=days_until_expiry)
            
            query = {
                "is_trial": True,
                "hashed_status": hash_data(cls.STATUS_TRIAL),
                "trial_end_date": {
                    "$gte": now,
                    "$lte": expiry_threshold,
                },
            }
            
            trials = list(collection.find(query))
            return [cls._normalise_subscription_doc(t) for t in trials]
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return []
    
    
    @classmethod
    def create_trial_subscription(
        cls,
        business_id: str,
        user_id: str,
        package_id: str,
        trial_days: int = None,
        log_tag: str = "",
    ) -> Optional[dict]:
        """
        Create a trial subscription for a business.
        
        Args:
            business_id: The business ID
            user_id: The user ID who initiated the trial
            package_id: The package ID for the trial
            trial_days: Number of trial days (default: 30)
            log_tag: Logging tag
        
        Returns:
            The created subscription document or None if failed
        """
        log_tag = log_tag or f"[Subscription][create_trial_subscription][{business_id}]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            # Check if business already has an active or trial subscription
            existing = cls.get_active_by_business(business_id)
            if existing:
                Log.info(f"{log_tag} Business already has active subscription")
                return None
            
            # Check if business has already used a trial
            existing_trial = collection.find_one({
                "business_id": ObjectId(business_id),
                "is_trial": True,
            })
            
            if existing_trial:
                Log.info(f"{log_tag} Business has already used trial")
                return None
            
            # Get package details
            from ...models.admin.package_model import Package
            package = Package.get_by_id(package_id)
            
            if not package:
                Log.error(f"{log_tag} Package not found: {package_id}")
                return None
            
            # Calculate trial period
            trial_days = trial_days or cls.DEFAULT_TRIAL_DAYS
            now = datetime.utcnow()
            trial_end_date = now + timedelta(days=trial_days)
            
            # Create subscription document
            subscription_doc = {
                "business_id": ObjectId(business_id),
                "user_id": ObjectId(user_id),
                "package_id": ObjectId(package_id),
                
                # Status
                "status": encrypt_data(cls.STATUS_TRIAL),
                "hashed_status": hash_data(cls.STATUS_TRIAL),
                
                # Trial flags
                "is_trial": True,
                "trial_days": trial_days,
                "trial_start_date": now,
                "trial_end_date": trial_end_date,
                
                # Dates
                "start_date": now,
                "end_date": trial_end_date,  # Trial end is subscription end until payment
                
                # Pricing (trial is free)
                "price_paid": encrypt_data("0.0"),
                "currency": encrypt_data(package.get("currency", "GBP")),
                "billing_period": encrypt_data("trial"),
                
                # Package snapshot (store key limits for quick access)
                "package_snapshot": {
                    "name": package.get("name"),
                    "tier": package.get("tier"),
                    "max_users": package.get("max_users"),
                    "max_social_accounts": package.get("max_social_accounts"),
                    "bulk_schedule_limit": package.get("bulk_schedule_limit"),
                    "features": package.get("features"),
                },
                
                # Metadata
                "auto_renew": False,  # Trial doesn't auto-renew
                "term_number": 0,  # Trial is term 0
                
                # Timestamps
                "created_at": now,
                "updated_at": now,
            }
            
            result = collection.insert_one(subscription_doc)
            
            if result.inserted_id:
                Log.info(f"{log_tag} Trial subscription created: {result.inserted_id}")
                
                # Update business account_status
                cls._update_business_subscription_status(
                    business_id=business_id,
                    subscribed=True,
                    is_trial=True,
                    log_tag=log_tag,
                )
                
                subscription_doc["_id"] = result.inserted_id
                return cls._normalise_subscription_doc(subscription_doc)
            
            return None
            
        except Exception as e:
            Log.error(f"{log_tag} Error creating trial subscription: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    
    @classmethod
    def create_indexes(cls) -> bool:
        log_tag = f"[subscription_model.py][Subscription][create_indexes]"

        try:
            col = db.get_collection(cls.collection_name)

            # --------------------------------------------------
            # 1) Core access lookup (your most common query):
            #    get current subscription for business (trial/active)
            # --------------------------------------------------
            col.create_index(
                [("business_id", 1), ("hashed_status", 1), ("created_at", -1)],
                name="idx_business_status_created",
            )

            # --------------------------------------------------
            # 2) Fast listing / history for a business
            # --------------------------------------------------
            col.create_index(
                [("business_id", 1), ("created_at", -1)],
                name="idx_business_created",
            )

            # --------------------------------------------------
            # 3) Renewal / billing tasks
            # --------------------------------------------------
            col.create_index(
                [("next_payment_date", 1)],
                name="idx_next_payment_date",
            )

            col.create_index(
                [("end_date", 1)],
                name="idx_end_date",
            )

            # Optional but useful for cron jobs:
            # "find all active subs expiring soon for a business"
            col.create_index(
                [("hashed_status", 1), ("end_date", 1)],
                name="idx_status_end_date",
            )

            # --------------------------------------------------
            # 4) Plan / package analytics (optional but cheap)
            # --------------------------------------------------
            col.create_index(
                [("business_id", 1), ("package_id", 1), ("created_at", -1)],
                name="idx_business_package_created",
            )

            # --------------------------------------------------
            # 5) 🔐 Best uniqueness rule for payment_reference
            #    (prevents duplicates within the same business)
            # --------------------------------------------------
            col.create_index(
                [("business_id", 1), ("payment_reference", 1)],
                unique=True,
                sparse=True,  # allows docs without payment_reference
                name="uniq_business_payment_reference",
            )

            Log.info(f"{log_tag} Indexes created successfully")
            return True

        except Exception as e:
            Log.error(f"{log_tag} Error creating indexes: {str(e)}", exc_info=True)
            return False
