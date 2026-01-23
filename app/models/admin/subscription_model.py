# models/subscription.py

from datetime import datetime, timedelta
from bson import ObjectId
from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.logger import Log


class Subscription(BaseModel):
    """
    Business subscription model.
    Tracks active subscriptions and their status.
    """
    
    collection_name = "subscriptions"
    
    # Subscription Statuses
    STATUS_TRIAL = "Trial"
    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_SCHEDULED = "Scheduled"
    STATUS_EXPIRED = "Expired"
    STATUS_CANCELLED = "Cancelled"
    STATUS_SUSPENDED = "Suspended"
    
    # Fields to decrypt
    FIELDS_TO_DECRYPT = ["status", "cancellation_reason", "suspension_reason"]
    
    def __init__(
        self,
        business_id,
        package_id,
        user_id,
        user__id,
        # Subscription details
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
        **kwargs
    ):
        """
        Initialize a subscription.
        
        Args:
            business_id: Business ObjectId or string
            package_id: Package ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            billing_period: Billing cycle (monthly, quarterly, yearly)
            price_paid: Amount paid for subscription
            currency: Currency code
            start_date: Subscription start date
            end_date: Subscription end date
            trial_end_date: Trial period end date
            status: Subscription status
            auto_renew: Auto-renewal enabled
            payment_method: Payment method used
            payment_reference: Payment transaction reference
            last_payment_date: Last successful payment date
            next_payment_date: Next payment due date
        """
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
    
    def to_dict(self):
        """Convert to dictionary for MongoDB insertion."""
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
    
    @staticmethod
    def _normalise_subscription_doc(subscription: dict) -> dict:
        """Normalise ObjectId fields and decrypt data."""
        if not subscription:
            return None

        subscription["_id"] = str(subscription["_id"])
        subscription["business_id"] = str(subscription["business_id"])
        subscription["package_id"] = str(subscription["package_id"])
        if subscription.get("user__id"):
            subscription["user__id"] = str(subscription["user__id"])
        
        # Decrypt fields
        for field in Subscription.FIELDS_TO_DECRYPT:
            if field in subscription and subscription[field] is not None:
                subscription[field] = decrypt_data(subscription[field])
        
        # Decrypt pricing
        if subscription.get("price_paid"):
            try:
                subscription["price_paid"] = float(decrypt_data(subscription["price_paid"]))
            except (ValueError, TypeError):
                subscription["price_paid"] = 0.0
        
        if subscription.get("currency"):
            subscription["currency"] = decrypt_data(subscription["currency"])
        
        if subscription.get("billing_period"):
            subscription["billing_period"] = decrypt_data(subscription["billing_period"])
            
        subscription.pop("hashed_status", None)
        
        return subscription
    
    # ---------------- QUERIES ---------------- #
    
    @classmethod
    def get_by_id(cls, subscription_id, business_id):
        """Retrieve a subscription by ID."""
        log_tag = f"[subscription.py][Subscription][get_by_id][{subscription_id}]"
        
        try:
            subscription_id = ObjectId(subscription_id) if not isinstance(subscription_id, ObjectId) else subscription_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(cls.collection_name)
            subscription = collection.find_one({
                "_id": subscription_id,
                "business_id": business_id
            })
            
            if not subscription:
                Log.error(f"{log_tag} Subscription not found")
                return None
            
            subscription = cls._normalise_subscription_doc(subscription)
            Log.info(f"{log_tag} Subscription retrieved successfully")
            return subscription
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @classmethod
    def get_active_by_business(cls, business_id):
        """
        Get active or trial subscription for a business.
        (Returns any subscription that gives the business current access)
        """
        log_tag = f"[subscription.py][Subscription][get_active_by_business][{business_id}]"
        
        try:
            business_id_obj = ObjectId(business_id)
            
            collection = db.get_collection(cls.collection_name)
            
            # ✅ ACTIVE OR TRIAL - both give access
            subscription = collection.find_one({
                "business_id": business_id_obj,
                "hashed_status": {
                    "$in": [
                        hash_data(cls.STATUS_ACTIVE),
                        hash_data(cls.STATUS_TRIAL)
                    ]
                }
            }, sort=[("created_at", -1)])
            
            if subscription:
                subscription = cls._normalise_subscription_doc(subscription)
                Log.info(f"{log_tag} Active/Trial subscription found")
            else:
                Log.info(f"{log_tag} No active subscription found")
            
            return subscription
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return None
    
    @classmethod
    def cancel_subscription(cls, subscription_id, business_id, reason=None):
        """Cancel a subscription."""
        log_tag = f"[subscription.py][Subscription][cancel_subscription][{subscription_id}]"
        
        try:
            subscription_id = ObjectId(subscription_id) if not isinstance(subscription_id, ObjectId) else subscription_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(cls.collection_name)
            
            update_doc = {
                "status": encrypt_data(cls.STATUS_CANCELLED),
                "cancelled_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            if reason:
                update_doc["cancellation_reason"] = encrypt_data(reason)
            
            result = collection.update_one(
                {"_id": subscription_id, "business_id": business_id},
                {"$set": update_doc}
            )
            
            if result.modified_count > 0:
                Log.info(f"{log_tag} Subscription cancelled")
                return True
            else:
                Log.error(f"{log_tag} Failed to cancel subscription")
                return False
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False
    
    @classmethod
    def create_indexes(cls):
        """Create database indexes."""
        log_tag = f"[subscription.py][Subscription][create_indexes]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            collection.create_index([("business_id", 1), ("status", 1)])
            collection.create_index([("business_id", 1), ("created_at", -1)])
            collection.create_index([("end_date", 1)])  # For expiry checks
            collection.create_index([("next_payment_date", 1)])  # For renewal checks
            
            Log.info(f"{log_tag} Indexes created successfully")
            return True
            
        except Exception as e:
            Log.error(f"{log_tag} Error creating indexes: {str(e)}")
            return False