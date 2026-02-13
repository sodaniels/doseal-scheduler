# app/models/admin/subscription_model.py
# Add these methods to your existing Subscription class

from datetime import datetime, timedelta
from typing import Optional
from bson import ObjectId

from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.logger import Log


class Subscription:
    """
    Extended Subscription model with trial support.
    """
    
    collection_name = "subscriptions"
    
    # -------------------------
    # Subscription Statuses
    # -------------------------
    STATUS_ACTIVE = "Active"
    STATUS_TRIAL = "Trial"
    STATUS_TRIAL_EXPIRED = "TrialExpired"
    STATUS_EXPIRED = "Expired"
    STATUS_CANCELLED = "Cancelled"
    STATUS_SUSPENDED = "Suspended"
    STATUS_PENDING = "Pending"
    
    # -------------------------
    # Trial Constants
    # -------------------------
    DEFAULT_TRIAL_DAYS = 30
    
    # -------------------------
    # Fields to decrypt
    # -------------------------
    FIELDS_TO_DECRYPT = [
        "status",
        "cancellation_reason",
        "suspension_reason",
        "billing_period",
        "currency",
    ]
    
    def to_dict(self) -> dict:
        """
        Prepare subscription document for MongoDB insertion.
        Encrypt & hash sensitive fields here.
        """
        doc = dict(self.collection_name)

        # ObjectId conversions
        for field in ("business_id", "package_id", "user_id", "user__id", "previous_subscription_id"):
            if field in doc and doc[field] and not isinstance(doc[field], ObjectId):
                doc[field] = ObjectId(doc[field])

        # Encrypt status
        if "status" in doc:
            doc["status"] = encrypt_data(doc["status"])
            doc["hashed_status"] = hash_data(self.data["status"])

        # Encrypt optional fields
        for field in ("billing_period", "currency", "payment_method"):
            if field in doc and doc[field]:
                doc[field] = encrypt_data(str(doc[field]))

        if "price_paid" in doc:
            doc["price_paid"] = encrypt_data(str(doc["price_paid"]))

        return doc

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
    
    @classmethod
    def _normalise_subscription_doc(cls, doc: dict) -> Optional[dict]:
        """Normalize and decrypt subscription document."""
        if not doc:
            return None
        
        if doc.get("_id"):
            doc["_id"] = str(doc["_id"])
        
        if doc.get("business_id"):
            doc["business_id"] = str(doc["business_id"])
        
        if doc.get("package_id"):
            doc["package_id"] = str(doc["package_id"])
        
        if doc.get("user_id"):
            doc["user_id"] = str(doc["user_id"])
        
        # Decrypt encrypted fields
        for field in cls.FIELDS_TO_DECRYPT:
            if field in doc:
                doc[field] = cls._safe_decrypt(doc[field])
        
        # Decrypt price_paid if present
        if doc.get("price_paid"):
            try:
                doc["price_paid"] = float(cls._safe_decrypt(doc["price_paid"]))
            except:
                doc["price_paid"] = 0.0
        
        # Remove hashed fields from response
        doc.pop("hashed_status", None)
        
        return doc
    
    # =========================================
    # TRIAL SUBSCRIPTION METHODS
    # =========================================
    
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
    def get_current_access_by_business(cls, business_id: str) -> Optional[dict]:
        """
        Get current PAID (ACTIVE) subscription.
        Explicitly excludes trials.
        """
        col = db.get_collection(cls.collection_name)

        doc = col.find_one(
            {
                "business_id": ObjectId(business_id),
                "hashed_status": hash_data(cls.STATUS_ACTIVE),
                "$or": [
                    {"is_trial": {"$exists": False}},
                    {"is_trial": False},
                ],
            },
            sort=[("created_at", -1)],
        )

        return cls._normalise_subscription_doc(doc) if doc else None
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
    def create_indexes(cls):
        """Create necessary indexes for subscription queries."""
        log_tag = "[Subscription][create_indexes]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            collection.create_index([("business_id", 1), ("hashed_status", 1)])
            collection.create_index([("business_id", 1), ("is_trial", 1)])
            collection.create_index([("hashed_status", 1), ("trial_end_date", 1)])
            collection.create_index([("is_trial", 1), ("trial_end_date", 1)])
            collection.create_index([("package_id", 1)])
            collection.create_index([("created_at", -1)])
            
            Log.info(f"{log_tag} Indexes created successfully")
            return True
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return False
    
    
    @classmethod
    def mark_all_access_subscriptions_inactive(cls, business_id: str) -> int:
        """
        Expire all ACTIVE or TRIAL subscriptions for a business.
        Used before creating a new term.
        """
        log_tag = f"[Subscription][mark_all_access_subscriptions_inactive][{business_id}]"

        try:
            col = db.get_collection(cls.collection_name)
            now = datetime.utcnow()

            res = col.update_many(
                {
                    "business_id": ObjectId(business_id),
                    "hashed_status": {
                        "$in": [
                            hash_data(cls.STATUS_ACTIVE),
                            hash_data(cls.STATUS_TRIAL),
                        ]
                    },
                },
                {
                    "$set": {
                        "status": encrypt_data(cls.STATUS_EXPIRED),
                        "hashed_status": hash_data(cls.STATUS_EXPIRED),
                        "updated_at": now,
                    }
                },
            )

            Log.info(f"{log_tag} expired={res.modified_count}")
            return res.modified_count

        except Exception as e:
            Log.error(f"{log_tag} error: {e}", exc_info=True)
            return 0
        
        
    @classmethod
    def payment_reference_exists(cls, payment_reference: str) -> bool:
        if not payment_reference:
            return False

        col = db.get_collection(cls.collection_name)
        return bool(col.find_one({"payment_reference": payment_reference}))
    
    @classmethod
    def insert_one(cls, doc: dict):
        col = db.get_collection(cls.collection_name)
        res = col.insert_one(doc)
        return str(res.inserted_id)
    
    def save(self, return_id: bool = False):
        col = db.get_collection(self.collection_name)
        data = self.to_dict()
        res = col.insert_one(data)
        return str(res.inserted_id) if return_id else True
    
    @classmethod
    def get_by_id(cls, subscription_id: str, business_id: str) -> Optional[dict]:
        log_tag = f"[Subscription][get_by_id][{subscription_id}]"

        try:
            col = db.get_collection(cls.collection_name)
            doc = col.find_one({
                "_id": ObjectId(subscription_id),
                "business_id": ObjectId(business_id),
            })

            return cls._normalise_subscription_doc(doc) if doc else None

        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return None
            
    
    
    
    
    
    
    