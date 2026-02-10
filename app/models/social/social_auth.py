# app/models/social/social_auth.py

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from bson import ObjectId

from ...extensions.db import db
from ...utils.logger import Log
from ...utils.crypt import encrypt_data, decrypt_data, hash_data


class SocialAuth:
    """
    Stores social login connections for users.
    
    A user can have multiple social accounts linked.
    Social accounts can be used for login or just for API access (posting).
    """
    
    collection_name = "social_auth"
    
    # Supported providers
    PROVIDER_FACEBOOK = "facebook"
    PROVIDER_GOOGLE = "google"
    PROVIDER_APPLE = "apple"
    PROVIDER_TWITTER = "twitter"  # X
    PROVIDER_LINKEDIN = "linkedin"
    PROVIDER_GITHUB = "github"
    PROVIDER_MICROSOFT = "microsoft"
    
    SUPPORTED_PROVIDERS = [
        PROVIDER_FACEBOOK,
        PROVIDER_GOOGLE,
        PROVIDER_APPLE,
        PROVIDER_TWITTER,
        PROVIDER_LINKEDIN,
        PROVIDER_GITHUB,
        PROVIDER_MICROSOFT,
    ]
    
    # Connection types
    TYPE_LOGIN = "login"           # Can be used for login
    TYPE_API_ONLY = "api_only"     # Only for API access (posting, etc.)
    
    @classmethod
    def _oid_str(cls, doc: dict) -> dict:
        """Convert ObjectIds to strings."""
        if not doc:
            return None
        for key in ["_id", "business_id", "user__id"]:
            if key in doc and doc[key]:
                doc[key] = str(doc[key])
        return doc
    
    @classmethod
    def create(cls, data: dict) -> dict:
        """
        Create a new social auth connection.
        
        Args:
            data: {
                "business_id": str,
                "user__id": str,
                "provider": str,
                "provider_user_id": str,
                "email": str (optional),
                "name": str (optional),
                "profile_picture": str (optional),
                "access_token": str,
                "refresh_token": str (optional),
                "token_expires_at": datetime (optional),
                "scopes": list (optional),
                "connection_type": str (login or api_only),
                "profile_data": dict (optional, raw profile from provider),
            }
        """
        col = db.get_collection(cls.collection_name)
        
        provider_user_id = str(data["provider_user_id"])
        provider = data["provider"]
        email = data.get("email")
        
        doc = {
            "business_id": ObjectId(str(data["business_id"])) if data.get("business_id") else None,
            "user__id": ObjectId(str(data["user__id"])) if data.get("user__id") else None,
            "provider": provider,
            "provider_user_id": provider_user_id,
            "provider_user_id_hashed": hash_data(f"{provider}:{provider_user_id}"),
            "email": encrypt_data(email) if email else None,
            "email_hashed": hash_data(email) if email else None,
            "name": encrypt_data(data.get("name")) if data.get("name") else None,
            "profile_picture": data.get("profile_picture"),
            "access_token": encrypt_data(data["access_token"]) if data.get("access_token") else None,
            "refresh_token": encrypt_data(data["refresh_token"]) if data.get("refresh_token") else None,
            "token_expires_at": data.get("token_expires_at"),
            "scopes": data.get("scopes", []),
            "connection_type": data.get("connection_type", cls.TYPE_LOGIN),
            "profile_data": data.get("profile_data", {}),
            "is_primary": data.get("is_primary", False),
            "last_used_at": datetime.now(timezone.utc),
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        
        result = col.insert_one(doc)
        doc["_id"] = result.inserted_id
        
        return cls._oid_str(doc)
    
    @classmethod
    def get_by_provider_user_id(cls, provider: str, provider_user_id: str) -> Optional[dict]:
        """
        Find a social auth record by provider and provider's user ID.
        This is used during login to find if user already exists.
        """
        col = db.get_collection(cls.collection_name)
        
        hashed = hash_data(f"{provider}:{provider_user_id}")
        
        doc = col.find_one({"provider_user_id_hashed": hashed})
        
        if doc:
            # Decrypt sensitive fields
            if doc.get("email"):
                doc["email_plain"] = decrypt_data(doc["email"])
            if doc.get("name"):
                doc["name_plain"] = decrypt_data(doc["name"])
            if doc.get("access_token"):
                doc["access_token_plain"] = decrypt_data(doc["access_token"])
            if doc.get("refresh_token"):
                doc["refresh_token_plain"] = decrypt_data(doc["refresh_token"])
        
        return cls._oid_str(doc)
    
    @classmethod
    def get_by_email(cls, provider: str, email: str) -> Optional[dict]:
        """Find a social auth record by provider and email."""
        col = db.get_collection(cls.collection_name)
        
        email_hashed = hash_data(email)
        
        doc = col.find_one({
            "provider": provider,
            "email_hashed": email_hashed,
        })
        
        if doc:
            if doc.get("access_token"):
                doc["access_token_plain"] = decrypt_data(doc["access_token"])
            if doc.get("refresh_token"):
                doc["refresh_token_plain"] = decrypt_data(doc["refresh_token"])
        
        return cls._oid_str(doc)
    
    @classmethod
    def get_by_user(cls, business_id: str, user__id: str, provider: str = None) -> List[dict]:
        """Get all social auth connections for a user."""
        col = db.get_collection(cls.collection_name)
        
        query = {
            "business_id": ObjectId(str(business_id)),
            "user__id": ObjectId(str(user__id)),
        }
        
        if provider:
            query["provider"] = provider
        
        docs = list(col.find(query).sort("created_at", -1))
        
        for doc in docs:
            cls._oid_str(doc)
            # Don't expose tokens in list
            doc.pop("access_token", None)
            doc.pop("refresh_token", None)
        
        return docs
    
    @classmethod
    def get_login_connections(cls, business_id: str, user__id: str) -> List[dict]:
        """Get social connections that can be used for login."""
        col = db.get_collection(cls.collection_name)
        
        docs = list(col.find({
            "business_id": ObjectId(str(business_id)),
            "user__id": ObjectId(str(user__id)),
            "connection_type": cls.TYPE_LOGIN,
        }))
        
        for doc in docs:
            cls._oid_str(doc)
            doc.pop("access_token", None)
            doc.pop("refresh_token", None)
        
        return docs
    
    @classmethod
    def update_tokens(
        cls,
        social_auth_id: str,
        access_token: str,
        refresh_token: str = None,
        token_expires_at: datetime = None,
    ) -> bool:
        """Update tokens after refresh."""
        col = db.get_collection(cls.collection_name)
        
        updates = {
            "access_token": encrypt_data(access_token),
            "last_used_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
        
        if refresh_token:
            updates["refresh_token"] = encrypt_data(refresh_token)
        if token_expires_at:
            updates["token_expires_at"] = token_expires_at
        
        result = col.update_one(
            {"_id": ObjectId(str(social_auth_id))},
            {"$set": updates}
        )
        
        return result.modified_count > 0
    
    @classmethod
    def update_last_used(cls, social_auth_id: str) -> bool:
        """Update last used timestamp."""
        col = db.get_collection(cls.collection_name)
        
        result = col.update_one(
            {"_id": ObjectId(str(social_auth_id))},
            {"$set": {
                "last_used_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }}
        )
        
        return result.modified_count > 0
    
    @classmethod
    def link_to_user(
        cls,
        social_auth_id: str,
        business_id: str,
        user__id: str,
    ) -> bool:
        """Link an existing social auth to a user account."""
        col = db.get_collection(cls.collection_name)
        
        result = col.update_one(
            {"_id": ObjectId(str(social_auth_id))},
            {"$set": {
                "business_id": ObjectId(str(business_id)),
                "user__id": ObjectId(str(user__id)),
                "updated_at": datetime.now(timezone.utc),
            }}
        )
        
        return result.modified_count > 0
    
    @classmethod
    def unlink(cls, social_auth_id: str, business_id: str, user__id: str) -> bool:
        """Remove a social auth connection."""
        col = db.get_collection(cls.collection_name)
        
        result = col.delete_one({
            "_id": ObjectId(str(social_auth_id)),
            "business_id": ObjectId(str(business_id)),
            "user__id": ObjectId(str(user__id)),
        })
        
        return result.deleted_count > 0
    
    @classmethod
    def set_primary(cls, social_auth_id: str, business_id: str, user__id: str) -> bool:
        """Set a social auth as primary (for login)."""
        col = db.get_collection(cls.collection_name)
        
        # First, unset all as primary
        col.update_many(
            {
                "business_id": ObjectId(str(business_id)),
                "user__id": ObjectId(str(user__id)),
            },
            {"$set": {"is_primary": False}}
        )
        
        # Then set the specified one as primary
        result = col.update_one(
            {
                "_id": ObjectId(str(social_auth_id)),
                "business_id": ObjectId(str(business_id)),
                "user__id": ObjectId(str(user__id)),
            },
            {"$set": {"is_primary": True, "updated_at": datetime.now(timezone.utc)}}
        )
        
        return result.modified_count > 0
    
    @classmethod
    def ensure_indexes(cls):
        """Create indexes for efficient queries."""
        col = db.get_collection(cls.collection_name)
        
        col.create_index("provider_user_id_hashed", unique=True)
        col.create_index([("provider", 1), ("email_hashed", 1)])
        col.create_index([("business_id", 1), ("user__id", 1)])
        col.create_index([("business_id", 1), ("user__id", 1), ("provider", 1)])
        
        return True