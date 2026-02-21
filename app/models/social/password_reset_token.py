from datetime import datetime, timedelta
from bson.objectid import ObjectId
from ...extensions.db import db
from ...utils.logger import Log
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
import secrets


class PasswordResetToken:
    """
    PasswordResetToken represents a short-lived, single-use token
    used to securely reset a user's password.
    """

    collection_name = "password_reset_tokens"

    def __init__(
        self,
        email,
        user_id,
        business_id,
        token,
        expires_at,
        used=False,
        created_at=None,
        used_at=None,
        invalidated_at=None,
    ):
        self.email = encrypt_data(email)
        self.hashed_email = hash_data(email)

        self.token = encrypt_data(token)
        self.hashed_token = hash_data(token)

        self.user_id = ObjectId(user_id) if isinstance(user_id, str) else user_id
        self.business_id = ObjectId(business_id) if isinstance(business_id, str) else business_id

        self.expires_at = expires_at
        self.used = used
        self.created_at = created_at or datetime.utcnow()
        self.used_at = used_at
        self.invalidated_at = invalidated_at

    def to_dict(self):
        """Convert model to MongoDB document."""
        return {
            "email": self.email,
            "hashed_email": self.hashed_email,
            "token": self.token,
            "hashed_token": self.hashed_token,
            "user_id": self.user_id,
            "business_id": self.business_id,
            "expires_at": self.expires_at,
            "used": self.used,
            "created_at": self.created_at,
            "used_at": self.used_at,
            "invalidated_at": self.invalidated_at,
        }

    # ------------------------------------------------------------------
    # CREATE TOKEN
    # ------------------------------------------------------------------
    @classmethod
    def create_token(cls, email, user_id, business_id, expiry_minutes=5):
        log_tag = f"[PasswordResetToken][create_token][{email}]"

        try:
            collection = db.get_collection(cls.collection_name)

            user_id_obj = ObjectId(user_id)
            business_id_obj = ObjectId(business_id)

            # Invalidate existing active tokens for this email + business
            collection.update_many(
                {
                    "hashed_email": hash_data(email),
                    "business_id": business_id_obj,
                    "used": False,
                },
                {
                    "$set": {
                        "used": True,
                        "invalidated_at": datetime.utcnow(),
                    }
                },
            )

            raw_token = secrets.token_urlsafe(32)
            expires_at = datetime.utcnow() + timedelta(minutes=expiry_minutes)

            token_model = cls(
                email=email,
                user_id=user_id_obj,
                business_id=business_id_obj,
                token=raw_token,
                expires_at=expires_at,
            )

            result = collection.insert_one(token_model.to_dict())
            if not result.inserted_id:
                raise RuntimeError("Failed to insert password reset token")

            Log.info(f"{log_tag} Token created (expires in {expiry_minutes} minutes)")
            return True, raw_token, None  # return RAW token for email

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False, None, str(e)

    # ------------------------------------------------------------------
    # VALIDATE TOKEN
    # ------------------------------------------------------------------
    @classmethod
    def validate_token(cls, token):
        log_tag = "[PasswordResetToken][validate_token]"

        try:
            collection = db.get_collection(cls.collection_name)

            data = collection.find_one(
                {
                    "hashed_token": hash_data(token),
                    "used": False,
                    "expires_at": {"$gt": datetime.utcnow()},
                }
            )

            if not data:
                Log.warning(f"{log_tag} Invalid or expired token")
                return None

            return {
                "token_id": str(data["_id"]),
                "email": decrypt_data(data["email"]),
                "user_id": str(data["user_id"]),
                "business_id": str(data["business_id"]),
                "expires_at": data["expires_at"],
                "created_at": data["created_at"],
            }

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return None

    # ------------------------------------------------------------------
    # MARK TOKEN AS USED
    # ------------------------------------------------------------------
    @classmethod
    def mark_token_used(cls, token):
        log_tag = "[PasswordResetToken][mark_token_used]"

        try:
            collection = db.get_collection(cls.collection_name)

            result = collection.update_one(
                {
                    "hashed_token": hash_data(token),
                    "used": False,
                },
                {
                    "$set": {
                        "used": True,
                        "used_at": datetime.utcnow(),
                    }
                },
            )

            if result.modified_count == 0:
                Log.warning(f"{log_tag} Token not found or already used")
                return False

            Log.info(f"{log_tag} Token marked as used")
            return True

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # INDEXES
    # ------------------------------------------------------------------
    @classmethod
    def create_indexes(cls):
        log_tag = "[PasswordResetToken][create_indexes]"

        try:
            collection = db.get_collection(cls.collection_name)

            collection.create_index("hashed_token", unique=True)
            collection.create_index("hashed_email")
            collection.create_index(
                "expires_at",
                expireAfterSeconds=0,
            )
            collection.create_index(
                [("business_id", 1), ("created_at", -1)]
            )

            Log.info(f"{log_tag} Indexes created successfully")
            return True

        except Exception as e:
            Log.error(f"{log_tag} Error creating indexes: {str(e)}", exc_info=True)
            return False