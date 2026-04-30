# models/admin/paystack_authorization.py

"""
PaystackAuthorization Model
============================
Stores reusable card/bank authorizations from Paystack against a business/user.

CRITICAL RULES (from Paystack docs):
  1. Store the ENTIRE authorization object — do not cherry-pick fields.
  2. Store the EMAIL used during the initial transaction alongside the authorization.
     Only that exact email can be used to charge the authorization. If the user
     changes their email on your system, the authorization becomes unchargeable.
  3. Use the `signature` field to deduplicate — each payment instrument has a
     unique signature across your integration.
  4. Only authorizations with `reusable: true` can be charged recurrently.
"""

from datetime import datetime
from bson import ObjectId
from ...extensions.db import db
from ...utils.logger import Log


class PaystackAuthorization:
    """Stored Paystack card/bank authorization for recurring charges."""

    collection_name = "paystack_authorizations"

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        email,
        authorization_code,
        signature,
        card_type=None,
        last4=None,
        exp_month=None,
        exp_year=None,
        bin_number=None,
        bank=None,
        channel=None,
        brand=None,
        country_code=None,
        account_name=None,
        reusable=True,
        is_active=True,
        is_default=False,
        raw_authorization=None,
        **kwargs,
    ):
        self.business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
        self.user__id = ObjectId(user__id) if not isinstance(user__id, ObjectId) else user__id
        self.user_id = user_id

        # CRITICAL: store the exact email used during the first charge
        self.email = email

        # Core authorization fields
        self.authorization_code = authorization_code
        self.signature = signature  # unique per payment instrument
        self.reusable = reusable

        # Card display details
        self.card_type = card_type
        self.last4 = last4
        self.exp_month = exp_month
        self.exp_year = exp_year
        self.bin_number = bin_number
        self.bank = bank
        self.channel = channel  # "card", "bank", "mobile_money"
        self.brand = brand      # "visa", "mastercard", etc.
        self.country_code = country_code
        self.account_name = account_name

        # Status
        self.is_active = is_active
        self.is_default = is_default

        # Store the full raw authorization object from Paystack
        self.raw_authorization = raw_authorization or {}

        # Timestamps
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.last_charged_at = None
        self.deactivated_at = None

    def to_dict(self):
        return {
            "business_id": self.business_id,
            "user_id": self.user_id,
            "user__id": self.user__id,
            "email": self.email,
            "authorization_code": self.authorization_code,
            "signature": self.signature,
            "reusable": self.reusable,
            "card_type": self.card_type,
            "last4": self.last4,
            "exp_month": self.exp_month,
            "exp_year": self.exp_year,
            "bin_number": self.bin_number,
            "bank": self.bank,
            "channel": self.channel,
            "brand": self.brand,
            "country_code": self.country_code,
            "account_name": self.account_name,
            "is_active": self.is_active,
            "is_default": self.is_default,
            "raw_authorization": self.raw_authorization,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_charged_at": self.last_charged_at,
            "deactivated_at": self.deactivated_at,
        }

    # ------------------------------------------------------------------ #
    #  SAVE / UPSERT
    # ------------------------------------------------------------------ #

    @classmethod
    def store_authorization(cls, business_id, user_id, user__id, email, authorization: dict) -> str:
        """
        Store or update a Paystack authorization.
        Uses the `signature` field to deduplicate — if the same card/instrument
        has been used before, update it rather than creating a duplicate.

        Args:
            business_id: Business ObjectId string
            user_id:     User string ID
            user__id:    User ObjectId string
            email:       The email used during the transaction (CRITICAL)
            authorization: The full authorization object from Paystack

        Returns:
            str: The _id of the stored/updated authorization document
        """
        log_tag = "[PaystackAuthorization][store_authorization]"

        try:
            collection = db.get_collection(cls.collection_name)
            signature = authorization.get("signature")
            auth_code = authorization.get("authorization_code")

            if not signature or not auth_code:
                Log.error(f"{log_tag} Missing signature or authorization_code")
                return None

            if not authorization.get("reusable"):
                Log.info(f"{log_tag} Authorization is not reusable — skipping storage")
                return None

            # Check if this instrument already exists for this business
            existing = collection.find_one({
                "business_id": ObjectId(business_id),
                "signature": signature,
            })

            if existing:
                # Update the authorization_code (Paystack may rotate it)
                collection.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {
                        "authorization_code": auth_code,
                        "email": email,
                        "reusable": authorization.get("reusable", True),
                        "card_type": authorization.get("card_type"),
                        "last4": authorization.get("last4"),
                        "exp_month": authorization.get("exp_month"),
                        "exp_year": authorization.get("exp_year"),
                        "bin_number": authorization.get("bin"),
                        "bank": authorization.get("bank"),
                        "channel": authorization.get("channel"),
                        "brand": authorization.get("brand"),
                        "country_code": authorization.get("country_code"),
                        "account_name": authorization.get("account_name"),
                        "raw_authorization": authorization,
                        "is_active": True,
                        "updated_at": datetime.utcnow(),
                    }}
                )
                Log.info(f"{log_tag} Updated existing authorization sig={signature} last4={authorization.get('last4')}")
                return str(existing["_id"])
            else:
                # Create new
                auth = cls(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    email=email,
                    authorization_code=auth_code,
                    signature=signature,
                    card_type=authorization.get("card_type"),
                    last4=authorization.get("last4"),
                    exp_month=authorization.get("exp_month"),
                    exp_year=authorization.get("exp_year"),
                    bin_number=authorization.get("bin"),
                    bank=authorization.get("bank"),
                    channel=authorization.get("channel"),
                    brand=authorization.get("brand"),
                    country_code=authorization.get("country_code"),
                    account_name=authorization.get("account_name"),
                    reusable=authorization.get("reusable", True),
                    is_default=True,  # newest card becomes default
                    raw_authorization=authorization,
                )

                # Unset previous default for this business
                collection.update_many(
                    {"business_id": ObjectId(business_id), "is_default": True},
                    {"$set": {"is_default": False}}
                )

                result = collection.insert_one(auth.to_dict())
                Log.info(f"{log_tag} Stored new authorization sig={signature} last4={authorization.get('last4')}")
                return str(result.inserted_id)

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return None

    # ------------------------------------------------------------------ #
    #  QUERIES
    # ------------------------------------------------------------------ #

    @classmethod
    def get_default_for_business(cls, business_id) -> dict:
        """Get the default (most recent) active authorization for a business."""
        try:
            collection = db.get_collection(cls.collection_name)
            auth = collection.find_one({
                "business_id": ObjectId(business_id),
                "is_active": True,
                "reusable": True,
                "is_default": True,
            })

            if not auth:
                # Fallback: get most recently created active authorization
                auth = collection.find_one(
                    {
                        "business_id": ObjectId(business_id),
                        "is_active": True,
                        "reusable": True,
                    },
                    sort=[("created_at", -1)],
                )

            if auth:
                auth["_id"] = str(auth["_id"])
                auth["business_id"] = str(auth["business_id"])
                auth["user__id"] = str(auth["user__id"])

            return auth

        except Exception as e:
            Log.error(f"[PaystackAuthorization][get_default_for_business] Error: {str(e)}")
            return None

    @classmethod
    def get_all_for_business(cls, business_id) -> list:
        """Get all active authorizations for a business."""
        try:
            collection = db.get_collection(cls.collection_name)
            auths = list(collection.find({
                "business_id": ObjectId(business_id),
                "is_active": True,
                "reusable": True,
            }).sort("created_at", -1))

            for a in auths:
                a["_id"] = str(a["_id"])
                a["business_id"] = str(a["business_id"])
                a["user__id"] = str(a["user__id"])

            return auths

        except Exception as e:
            Log.error(f"[PaystackAuthorization][get_all_for_business] Error: {str(e)}")
            return []

    @classmethod
    def set_default(cls, authorization_id, business_id) -> bool:
        """Set a specific authorization as the default for a business."""
        try:
            collection = db.get_collection(cls.collection_name)

            # Unset all defaults
            collection.update_many(
                {"business_id": ObjectId(business_id)},
                {"$set": {"is_default": False}}
            )

            # Set the chosen one
            result = collection.update_one(
                {"_id": ObjectId(authorization_id), "business_id": ObjectId(business_id)},
                {"$set": {"is_default": True, "updated_at": datetime.utcnow()}}
            )

            return result.modified_count > 0

        except Exception as e:
            Log.error(f"[PaystackAuthorization][set_default] Error: {str(e)}")
            return False

    @classmethod
    def deactivate(cls, authorization_id, business_id) -> bool:
        """Deactivate (soft-delete) an authorization."""
        try:
            collection = db.get_collection(cls.collection_name)
            result = collection.update_one(
                {"_id": ObjectId(authorization_id), "business_id": ObjectId(business_id)},
                {"$set": {
                    "is_active": False,
                    "is_default": False,
                    "deactivated_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }}
            )
            return result.modified_count > 0

        except Exception as e:
            Log.error(f"[PaystackAuthorization][deactivate] Error: {str(e)}")
            return False

    @classmethod
    def mark_charged(cls, authorization_id) -> bool:
        """Update last_charged_at timestamp after a successful recurring charge."""
        try:
            collection = db.get_collection(cls.collection_name)
            result = collection.update_one(
                {"_id": ObjectId(authorization_id)},
                {"$set": {
                    "last_charged_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                }}
            )
            return result.modified_count > 0

        except Exception as e:
            Log.error(f"[PaystackAuthorization][mark_charged] Error: {str(e)}")
            return False

    # ------------------------------------------------------------------ #
    #  INDEXES
    # ------------------------------------------------------------------ #

    @classmethod
    def create_indexes(cls):
        """Create indexes for optimal query performance."""
        try:
            collection = db.get_collection(cls.collection_name)
            collection.create_index([("business_id", 1), ("is_active", 1), ("is_default", -1)])
            collection.create_index([("business_id", 1), ("signature", 1)], unique=True)
            collection.create_index([("authorization_code", 1)], unique=True, sparse=True)
            collection.create_index([("user__id", 1)])
            Log.info("[PaystackAuthorization][create_indexes] Indexes created")
            return True
        except Exception as e:
            Log.error(f"[PaystackAuthorization][create_indexes] Error: {str(e)}")
            return False
