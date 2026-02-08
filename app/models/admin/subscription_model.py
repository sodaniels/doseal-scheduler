# app/models/admin/subscription_model.py

from datetime import datetime, timedelta
from bson import ObjectId
from typing import Optional, Dict, Any, List, Union

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
    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_SCHEDULED = "Scheduled"
    STATUS_EXPIRED = "Expired"
    STATUS_CANCELLED = "Cancelled"
    STATUS_SUSPENDED = "Suspended"

    # Fields to decrypt
    FIELDS_TO_DECRYPT = ["status", "cancellation_reason", "suspension_reason", "billing_period", "currency"]

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

    @staticmethod
    def _normalise_subscription_doc(subscription: dict) -> Optional[dict]:
        if not subscription:
            return None

        subscription["_id"] = str(subscription["_id"])
        subscription["business_id"] = str(subscription["business_id"])
        subscription["package_id"] = str(subscription["package_id"])
        if subscription.get("user__id"):
            subscription["user__id"] = str(subscription["user__id"])
        if subscription.get("previous_subscription_id"):
            subscription["previous_subscription_id"] = str(subscription["previous_subscription_id"])

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
