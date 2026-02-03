from __future__ import annotations

import bcrypt
import json
import ast
from datetime import datetime
from typing import Any, Dict, Optional, Tuple, Iterable

from bson.objectid import ObjectId
from marshmallow import ValidationError

from werkzeug.security import generate_password_hash, check_password_hash

from app.extensions.db import db
from app.utils.logger import Log
from app.utils.generators import generate_client_id
from app.utils.crypt import encrypt_data, decrypt_data, hash_data
from ..models.base_model import BaseModel


def _now():
    return datetime.utcnow()


def _drop_nones(d: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of dict without keys whose value is None."""
    return {k: v for k, v in d.items() if v is not None}


class Business(BaseModel):
    """
    Business model (MongoDB).

    Goal:
      - No optional field is stored as null.
      - Store encrypted fields + hashed lookup fields.
      - Store password as bcrypt hash only.
    """

    collection_name = "businesses"

    # Fields in DB that are encrypted (so we can decrypt when returning to API callers)
    FIELDS_TO_DECRYPT = [
        "tenant_id",
        "business_name",
        "start_date",
        "business_contact",
        "account_status",
        "country",
        "city",
        "state",
        "postcode",
        "landmark",
        "currency",
        "website",
        "alternate_contact_number",
        "time_zone",
        "prefix",
        "username",
        "email",
        "store_url",
        "package",
        "return_url",
        "callback_url",
        "status",
        "account_type",
        "client_id",
        "file_path",
    ]

    @staticmethod
    def _enc(v: Any) -> Optional[str]:
        """Encrypt non-empty values; return None for empty."""
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return encrypt_data(str(v))

    @classmethod
    def update_account_status_by_business_id(cls, business_id, ip_address, field, update_value):
        """Update a specific field in the 'account_status' for the given agent ID."""
        business_collection = db.get_collection("businesses")
        
        # Search for the business by business_id
        business = business_collection.find_one({"_id": ObjectId(business_id)})
        
        if not business:
            return {"success": False, "message": "Business not found"}
        
        # Get the encrypted account_status field from the agent document
        encrypted_account_status = business.get("account_status")
        
        # Check if account_status is None
        if encrypted_account_status is None:
            return {"success": False, "message": "Account status not found"}
        
        # Decrypt the account_status field
        try:
            account_status = decrypt_data(encrypted_account_status)
            
            # Parse if it's a string
            if isinstance(account_status, str):
                try:
                    # First try JSON parsing
                    account_status = json.loads(account_status)
                except json.JSONDecodeError:
                    # If JSON fails, try ast.literal_eval for Python dict format
                    account_status = ast.literal_eval(account_status)
            
            Log.info(f"account_status: {account_status}")
            
        except Exception as e:
            return {"success": False, "message": f"Error decrypting account status: {str(e)}"}
        
        # Flag to track if the field was updated
        field_updated = False
        
        # Loop through account_status and find the specific field to update
        for status in account_status:
            if field in status:
                # Update the field's status, created_at, and ip_address
                status[field]["status"] = update_value
                status[field]["created_at"] = datetime.utcnow().isoformat()
                status[field]["ip_address"] = ip_address
                field_updated = True
                break
        
        # If the field was not found
        if not field_updated:
            return {"success": False, "message": f"Field '{field}' not found in account status"}
        
        # Re-encrypt the updated account_status before saving back
        try:
            encrypted_account_status = encrypt_data(account_status)
        except Exception as e:
            return {"success": False, "message": f"Error encrypting account status: {str(e)}"}
        
        # Update the 'account_status' in the database
        result = business_collection.update_one(
            {"_id": ObjectId(business_id)},
            {"$set": {"account_status": encrypted_account_status}}
        )
        
        # Return success or failure of the update operation
        if result.matched_count > 0:
            return {"success": True, "message": "Account status updated successfully"}
        else:
            return {"success": False, "message": "Failed to update account status"}
    
    @staticmethod
    def check_password(business_doc: dict, password: str) -> bool:
        stored_hash = (business_doc or {}).get("password")
        if not stored_hash or not password:
            return False
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except Exception:
            return False

    def __init__(
        self,
        tenant_id: str,
        business_name: str,
        first_name: str,
        last_name: str,
        email: str,
        password: str,
        account_status: None,
        # Optional
        country: Optional[str] = None,
        start_date: Optional[str] = None,
        business_contact: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        postcode: Optional[str] = None,
        landmark: Optional[str] = None,
        currency: Optional[str] = None,
        website: Optional[str] = None,
        alternate_contact_number: Optional[str] = None,
        time_zone: Optional[str] = None,
        prefix: Optional[str] = None,
        username: Optional[str] = None,
        store_url: Optional[str] = None,
        package: Optional[str] = None,
        return_url: Optional[str] = None,
        callback_url: Optional[str] = None,
        status: str = "Active",
        account_type: str = "super_admin",
        image: Optional[str] = None,  # kept plain
        user_id: Optional[str] = None,
        **kwargs,
    ):
        client_id_plain = generate_client_id()

        # Required encrypted fields
        self.tenant_id = self._enc(tenant_id)
        self.business_name = self._enc(business_name)
        self.country = self._enc(country)
        self.first_name = self._enc(first_name)
        self.last_name = self._enc(last_name)
        self.email = self._enc(email)
        self.account_status = self._enc(account_status)

        # Required hashed lookups
        self.hashed_email = hash_data(email)
        self.client_id = self._enc(client_id_plain)
        self.client_id_hashed = hash_data(client_id_plain)

        # Password (bcrypt only)
        self.password = self._hash_password(password)

        # Optional encrypted fields (only set if not None/empty)
        self.start_date = self._enc(start_date)
        self.business_contact = self._enc(business_contact)
        self.city = self._enc(city)
        self.state = self._enc(state)
        self.postcode = self._enc(postcode)
        self.landmark = self._enc(landmark)
        self.currency = self._enc(currency)
        self.website = self._enc(website)
        self.alternate_contact_number = self._enc(alternate_contact_number)
        self.time_zone = self._enc(time_zone)
        self.prefix = self._enc(prefix)
        self.username = self._enc(username)
        self.store_url = self._enc(store_url)
        self.package = self._enc(package)
        self.return_url = self._enc(return_url)
        self.callback_url = self._enc(callback_url)

        # Status/account_type
        self.status = self._enc(status or "Active")
        self.hashed_status = hash_data(status or "Active")
        self.account_type = self._enc(account_type or "super_admin")

        # Plain optional fields
        self.image = image
        self.user_id = user_id

        self.created_at = _now()
        self.updated_at = _now()

        # Extra fields (only set if not None)
        for k, v in kwargs.items():
            if v is not None:
                setattr(self, k, v)

    def to_dict(self) -> Dict[str, Any]:
        """
        IMPORTANT:
        - We drop None keys so MongoDB will not store them as null.
        """
        doc = {
            "tenant_id": self.tenant_id,
            "business_name": self.business_name,
            "start_date": getattr(self, "start_date", None),
            "image": getattr(self, "image", None),
            "business_contact": getattr(self, "business_contact", None),
            "country": self.country,
            "city": getattr(self, "city", None),
            "state": getattr(self, "state", None),
            "postcode": getattr(self, "postcode", None),
            "landmark": getattr(self, "landmark", None),
            "currency": getattr(self, "currency", None),
            "website": getattr(self, "website", None),
            "alternate_contact_number": getattr(self, "alternate_contact_number", None),
            "time_zone": getattr(self, "time_zone", None),
            "prefix": getattr(self, "prefix", None),
            "first_name": self.first_name,
            "last_name": self.last_name,
            "username": getattr(self, "username", None),
            "password": self.password,
            "email": self.email,
            "hashed_email": self.hashed_email,
            "store_url": getattr(self, "store_url", None),
            "package": getattr(self, "package", None),
            "user_id": getattr(self, "user_id", None),
            "client_id": self.client_id,
            "client_id_hashed": self.client_id_hashed,
            "return_url": getattr(self, "return_url", None),
            "callback_url": getattr(self, "callback_url", None),
            "status": self.status,
            "account_status": self.account_status,
            "hashed_status": self.hashed_status,
            "account_type": self.account_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return _drop_nones(doc)

    def save(self) -> Dict[str, Any]:
        collection = db.get_collection(self.collection_name)
        res = collection.insert_one(self.to_dict())

        # Return safe values
        return (self.client_id, self.tenant_id, res.inserted_id, self.email)

    # ----------------------------
    # Normalization / Decryption
    # ----------------------------
    @classmethod
    def _normalise_business_doc(cls, business: dict) -> Optional[dict]:
        if not business:
            return None

        business["_id"] = str(business["_id"])

        for f in cls.FIELDS_TO_DECRYPT:
            if f in business and business[f] is not None:
                try:
                    business[f] = decrypt_data(business[f])
                except Exception:
                    pass

        # never leak password hash
        business.pop("password", None)
        return business

    # ----------------------------
    # Queries
    # ----------------------------
    
    @staticmethod
    def get_business_by_id(business_id):
        """Retrieve a business by its MongoDB _id."""
        try:
            object_id = ObjectId(business_id)
        except Exception as e:
            raise ValueError(f"Invalid _id format: {business_id}") from e

        collection = db.get_collection("businesses")
        business = collection.find_one({"_id": object_id})
        if business:
            business["_id"] = str(business["_id"])
            business["business_name"] = decrypt_data(business["business_name"])
            business["email"] = decrypt_data(business["email"])
            # Decrypt other fields as necessary
            business.pop("password", None)
        return business

    @classmethod
    def get_business_by_email(cls, email_plain: str) -> Optional[dict]:
        hashed = hash_data(email_plain)
        collection = db.get_collection(cls.collection_name)
        doc = collection.find_one({"hashed_email": hashed})
        return cls._normalise_business_doc(doc)

    @staticmethod
    def get_business_by_client_id(client_id):
        """Retrieve a business by its client_id."""
        businesses_collection = db.get_collection("businesses")
        business = businesses_collection.find_one({"client_id": client_id})
        if business:
            business["_id"] = str(business["_id"])
            business["business_name"] = decrypt_data(business["business_name"])
            business["email"] = decrypt_data(business["email"])
            # Decrypt other fields as necessary
            business.pop("password", None)
        return business

    # ----------------------------
    # Updates (NO NULLS)
    # ----------------------------
    @classmethod
    def update_business_by_id(
        cls,
        business_id: str,
        *,
        unset_fields: Optional[Iterable[str]] = None,
        **updates,
    ) -> bool:
        """
        - Ignores None values so they won't be written as null.
        - If you want to REMOVE a field, pass it in unset_fields.
        """
        oid = ObjectId(business_id)
        collection = db.get_collection(cls.collection_name)

        updates = dict(updates or {})
        updates["updated_at"] = _now()

        # If caller passes None, we IGNORE it (so no nulls)
        updates = _drop_nones(updates)

        # Handle special fields that need hashing/encryption
        set_doc: Dict[str, Any] = {}

        # Email update must also update hashed_email
        if "email" in updates:
            plain = str(updates["email"])
            set_doc["email"] = encrypt_data(plain)
            set_doc["hashed_email"] = hash_data(plain)
            updates.pop("email", None)

        # Status update must also update hashed_status
        if "status" in updates:
            plain = str(updates["status"])
            set_doc["status"] = encrypt_data(plain)
            set_doc["hashed_status"] = hash_data(plain)
            updates.pop("status", None)

        # Password update (bcrypt only)
        if "password" in updates:
            set_doc["password"] = cls._hash_password(str(updates["password"]))
            updates.pop("password", None)

        # Encrypt fields that should be encrypted
        encryptable = set(cls.FIELDS_TO_DECRYPT) - {"email", "status"}  # already handled above
        for k, v in updates.items():
            if k in encryptable:
                set_doc[k] = encrypt_data(str(v))
            else:
                set_doc[k] = v

        mongo_update: Dict[str, Any] = {}
        if set_doc:
            mongo_update["$set"] = set_doc

        # Unset explicitly requested fields
        if unset_fields:
            mongo_update["$unset"] = {f: "" for f in unset_fields}

        if not mongo_update:
            return False

        res = collection.update_one({"_id": oid}, mongo_update)
        return res.modified_count > 0

    @classmethod
    def update_business_image(cls, email_plain: str, image: str, file_path: str) -> bool:
        """
        Keeps image/file_path as plaintext. If you want them encrypted, change here.
        """
        hashed = hash_data(email_plain)
        collection = db.get_collection(cls.collection_name)

        set_doc = _drop_nones(
            {
                "image": image,
                "file_path": file_path,
                "updated_at": _now(),
            }
        )

        res = collection.update_one({"hashed_email": hashed}, {"$set": set_doc})
        return res.modified_count > 0

    @classmethod
    def delete_business_with_cascade(cls, business_id: str) -> Dict[str, Any]:
        oid = ObjectId(business_id)
        businesses = db.get_collection(cls.collection_name)

        business = businesses.find_one({"_id": oid})
        if not business:
            raise ValidationError("Business not found.")

        db.get_collection("agents").delete_many({"business_id": oid})
        db.get_collection("users").delete_many({"business_id": oid})
        businesses.delete_one({"_id": oid})

        return {"status_code": 200, "message": "Business and related data deleted successfully."}

    @staticmethod
    def update_business_with_user_id(business_id, **updates):
        """Update a business's details."""
        updates["updated_at"] = datetime.now()
        collection = db.get_collection("businesses")
        result = collection.update_one({"_id": ObjectId(business_id)}, {"$set": updates})
        return result
    
    @staticmethod
    def check_item_exists(key, value):
        """
        Check if an item exists by business_id and a specific key (hashed comparison).
        This method allows dynamic checks for any key (like 'name', 'phone', etc.).
        
        Args:
        - business_id: The business ID to filter the items.
        - key: The key (field) to check for existence (e.g., 'name', 'phone').
        - value: The value of the key to check for existence.

        Returns:
        - True if the item exists, False otherwise.
        """
        
        # Dynamically hash the value of the key
        hashed_key = hash_data(value)  # Hash the value provided for the dynamic field

        # Dynamically create the query with business_id and hashed field
        query = {
            f"hashed_{key}": hashed_key  # Use the key dynamically (e.g., "hashed_name" or "hashed_phone")
        }

        # Query the database for an item matching the given business_id and hashed value
        collection = db.get_collection("businesses")
        existing_item = collection.find_one(query)

        # Return True if a matching item is found, else return False
        if existing_item:
            return True  # Item exists
        else:
            return False  # Item does not exist
    
    @staticmethod
    def get_business(client_id):
        collection = db.get_collection("businesses")
        return collection.find_one({"client_id": client_id})
    
    @staticmethod
    def check_password(business, password):
        """Check if the password is correct."""
        return check_password_hash(business['password'], password)
   
    
    
    
    
class Client:
    collection_name = "clients"

    @classmethod
    def create_client(cls, client_id: str, client_secret: str):
        db.get_collection(cls.collection_name).insert_one(
            _drop_nones(
                {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "created_at": _now(),
                }
            )
        )

    @classmethod
    def get_client(cls, client_id: str, client_secret: str):
        return db.get_collection(cls.collection_name).find_one(
            {"client_id": client_id, "client_secret": client_secret}
        )

    @classmethod
    def retrieve_client(cls, client_id: str):
        return db.get_collection(cls.collection_name).find_one({"client_id": client_id})


class Token:
    collection_name = "tokens"

    @classmethod
    def create_token(
        cls,
        client_id: str,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        refresh_expires_in: int,
    ):
        db.get_collection(cls.collection_name).insert_one(
            _drop_nones(
                {
                    "client_id": client_id,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_in": int(expires_in),
                    "refresh_expires_in": int(refresh_expires_in),
                    "created_at": _now(),
                }
            )
        )

    @classmethod
    def get_token(cls, access_token: str):
        return db.get_collection(cls.collection_name).find_one({"access_token": access_token})

    @classmethod
    def delete_token(cls, access_token: str) -> bool:
        res = db.get_collection(cls.collection_name).delete_one({"access_token": access_token})
        return res.deleted_count > 0

    @classmethod
    def get_refresh_token(cls, refresh_token: str):
        return db.get_collection(cls.collection_name).find_one({"refresh_token": refresh_token})