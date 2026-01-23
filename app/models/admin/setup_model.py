import uuid, os, bcrypt

from pymongo import MongoClient
from bson.objectid import ObjectId
from pymongo import ASCENDING
from pymongo.errors import PyMongoError
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from app import db
from ...utils.logger import Log # import logging
from ...utils.generators import (
    generate_gift_card_code
)
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.generators import generate_store_code
from ...utils.helpers import name_to_slug
from ...models.base_model import BaseModel

# Store Class Definition

class Store(BaseModel):
    """
    A store represents a business entity in the system.
    """

    collection_name = "stores"  # Set the collection name

    def __init__(self, business_id, user_id, name, phone, email, address1, user__id,
                 address2=None, city=None, postal_code=None, receipt_header=None,
                 receipt_footer=None, tax=None, code=None, image=None, file_path=None, town=None, 
                 status="Active", ):
        super().__init__(business_id, user_id, name=name, status=status, user__id=user__id) 
        
        # Ensure valid data types
        if not isinstance(name, str):
            raise ValueError("Store name must be a string.")
        
        # Initialize fields
        self.store_id = str(uuid.uuid4())  # Custom field for store_id
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.phone = encrypt_data(phone)
        self.email = encrypt_data(email)
        self.hashed_email = hash_data(email)
        self.address1 = encrypt_data(address1)
        self.address2 = encrypt_data(address2) if address2 else None
        self.city = encrypt_data(city) if city else None
        self.town = encrypt_data(town) if town else None
        self.postal_code = encrypt_data(postal_code) if postal_code else None
        self.code = encrypt_data(code) if code else None
        self.receipt_header = encrypt_data(receipt_header) if receipt_header else None
        self.receipt_footer = encrypt_data(receipt_footer) if receipt_footer else None
        self.tax = encrypt_data(tax) if tax else None
        self.image = encrypt_data(image) if image else None
        self.file_path = encrypt_data(file_path) if file_path else None
        self.status = encrypt_data(status)
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the store object to a dictionary representation.
        """
        store_dict = super().to_dict()
        store_dict.update({
            "store_id": self.store_id,
            "phone": self.phone,
            "email": self.email,
            "hashed_email": self.hashed_email,
            "address1": self.address1,
            "address2": self.address2,
            "code": self.code,
            "image": self.image,
            "file_path": self.file_path,
            "city": self.city,
            "postal_code": self.postal_code,
            "receipt_header": self.receipt_header,
            "receipt_footer": self.receipt_footer,
            "tax": self.tax,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return store_dict

    @classmethod
    def get_by_id(cls, store_id, business_id):
        """
        Retrieve a store by store_id.
        """
        
        try:
            business_id_obj = ObjectId(business_id)
        except Exception as e:
            return None
        
        try:
            store_id_obj = ObjectId(store_id)
        except Exception as e:
            return None

        data = super().get_by_id(store_id_obj, business_id_obj)

        if not data:
            return None  # Store not found

        data["_id"] = str(data["_id"])
        data["user__id"] = str(data["user__id"])
        data["business_id"] = str(data["business_id"])

        # Decrypt fields only if they exist (are not None)
        data["name"] = decrypt_data(data["name"]) if data.get("name") else None
        data["phone"] = decrypt_data(data["phone"]) if data.get("phone") else None
        data["email"] = decrypt_data(data["email"]) if data.get("email") else None
        data["address1"] = decrypt_data(data["address1"]) if data.get("address1") else None
        data["address2"] = decrypt_data(data["address2"]) if data.get("address2") else None
        data["city"] = decrypt_data(data["city"]) if data.get("city") else None
        data["town"] = decrypt_data(data["town"]) if data.get("town") else None
        data["postal_code"] = decrypt_data(data["postal_code"]) if data.get("postal_code") else None
        data["receipt_header"] = decrypt_data(data["receipt_header"]) if data.get("receipt_header") else None
        data["receipt_footer"] = decrypt_data(data["receipt_footer"]) if data.get("receipt_footer") else None
        data["tax"] = decrypt_data(data["tax"]) if data.get("tax") else None
        data["image"] = decrypt_data(data["image"]) if data.get("image") else None
        data["file_path"] = decrypt_data(data["file_path"]) if data.get("file_path") else None
        data["status"] = decrypt_data(data["status"]) if data.get("status") else None

        # Remove sensitive information
        data.pop("email_hashed", None)
        data.pop("hashed_name", None)
        data.pop("file_path", None)
        data.pop("hashed_email", None)

        return data

    @classmethod
    def update(cls, store_id, **updates):
        """
        Update a store's information by store_id.
        """
        
        # Encrypt fields before updating
        updates = {key: encrypt_data(value) if key in ['name', 'phone', 'email', 'address1', 'address2', 'code', 'image', 'status', 'city', 'postal_code', 'receipt_header', 'receipt_footer', 'tax'] else value for key, value in updates.items()}

        # Calling the update method from the BaseModel
        return super().update(store_id, **updates)

    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve stores by business_id with pagination and decrypted fields.
        Uses BaseModel.get_all_by_business_id(...) and post-processes the docs.
        """
        payload = super().get_all_by_user__id_and_business_id(user__id, business_id, page, per_page)
        processed = []

        for store in payload["items"]:
            # Normalise IDs
            store["_id"] = str(store["_id"])
            if "user__id" in store:
                store["user__id"] = str(store["user__id"])
            if "business_id" in store:
                store["business_id"] = str(store["business_id"])

            # Keep these as-is (already plain)
            store["store_id"] = store.get("store_id")
            store["user_id"] = store.get("user_id")

            # Decrypt fields only if they are present
            store["name"] = decrypt_data(store["name"]) if store.get("name") else None
            store["phone"] = decrypt_data(store["phone"]) if store.get("phone") else None
            store["email"] = decrypt_data(store["email"]) if store.get("email") else None
            store["address1"] = decrypt_data(store["address1"]) if store.get("address1") else None
            store["address2"] = decrypt_data(store["address2"]) if store.get("address2") else None
            store["city"] = decrypt_data(store["city"]) if store.get("city") else None
            store["code"] = decrypt_data(store["code"]) if store.get("code") else None
            store["postal_code"] = decrypt_data(store["postal_code"]) if store.get("postal_code") else None
            store["receipt_header"] = decrypt_data(store["receipt_header"]) if store.get("receipt_header") else None
            store["receipt_footer"] = decrypt_data(store["receipt_footer"]) if store.get("receipt_footer") else None
            store["tax"] = decrypt_data(store["tax"]) if store.get("tax") else None
            store["image"] = decrypt_data(store["image"]) if store.get("image") else None
            store["file_path"] = decrypt_data(store["file_path"]) if store.get("file_path") else None
            store["status"] = decrypt_data(store["status"]) if store.get("status") else None

            # created_at / updated_at are already usable
            store["created_at"] = store.get("created_at")
            store["updated_at"] = store.get("updated_at")

            # Remove sensitive / internal fields
            store.pop("file_path", None)
            store.pop("hashed_email", None)
            store.pop("hashed_name", None)

            processed.append(store)

        # Replace generic key with domain-specific one
        payload["items"] = processed
        payload.pop("items", None)

        return payload

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve stores by business_id with pagination and decrypted fields.
        Uses BaseModel.get_all_by_business_id(...) and post-processes the docs.
        """
        payload = super().get_by_business_id(business_id, page, per_page)
        processed = []

        for store in payload["items"]:
            # Normalise IDs
            store["_id"] = str(store["_id"])
            if "business_id" in store:
                store["business_id"] = str(store["business_id"])

            # Keep these as-is (already plain)
            store["store_id"] = store.get("store_id")
            store["user_id"] = store.get("user_id")

            # Decrypt fields only if they are present
            store["name"] = decrypt_data(store["name"]) if store.get("name") else None
            store["phone"] = decrypt_data(store["phone"]) if store.get("phone") else None
            store["email"] = decrypt_data(store["email"]) if store.get("email") else None
            store["address1"] = decrypt_data(store["address1"]) if store.get("address1") else None
            store["address2"] = decrypt_data(store["address2"]) if store.get("address2") else None
            store["city"] = decrypt_data(store["city"]) if store.get("city") else None
            store["code"] = decrypt_data(store["code"]) if store.get("code") else None
            store["postal_code"] = decrypt_data(store["postal_code"]) if store.get("postal_code") else None
            store["receipt_header"] = decrypt_data(store["receipt_header"]) if store.get("receipt_header") else None
            store["receipt_footer"] = decrypt_data(store["receipt_footer"]) if store.get("receipt_footer") else None
            store["tax"] = decrypt_data(store["tax"]) if store.get("tax") else None
            store["image"] = decrypt_data(store["image"]) if store.get("image") else None
            store["file_path"] = decrypt_data(store["file_path"]) if store.get("file_path") else None
            store["status"] = decrypt_data(store["status"]) if store.get("status") else None

            # created_at / updated_at are already usable
            store["created_at"] = store.get("created_at")
            store["updated_at"] = store.get("updated_at")

            # Remove sensitive / internal fields
            store.pop("file_path", None)
            store.pop("hashed_email", None)
            store.pop("hashed_name", None)

            processed.append(store)

        # Replace generic key with domain-specific one
        payload["stores"] = processed
        payload.pop("items", None) 

        return payload

    @classmethod
    def delete(cls, store_id, business_id):
        """
        Delete a store by store_id and business_id.
        """
        return super().delete(store_id, business_id)

#Unit Class Definition
class Unit(BaseModel):
    """
    A unit represents a physical unit of measurement.
    """

    collection_name = "units"  # Set the collection name

    def __init__(self, business_id, user_id, unit, name, user__id, status="Active"):
        super().__init__(business_id, user_id, unit=unit, name=name, status=status,
                         user__id=user__id)

        # Basic type checks (optional but mirrors Store pattern)
        if not isinstance(unit, str):
            raise ValueError("Unit must be a string.")
        if not isinstance(name, str):
            raise ValueError("Unit name must be a string.")

        # Encrypt & hash fields
        self.unit = encrypt_data(unit)
        self.hashed_unit = hash_data(unit)  # Create a hashed unit for comparison
        self.name = encrypt_data(name)
        self.status = encrypt_data(status)
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the unit object to a dictionary representation.
        """
        unit_dict = super().to_dict()
        unit_dict.update({
            "unit": self.unit,
            "name": self.name,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "hashed_unit": self.hashed_unit,
        })
        return unit_dict

    
    @classmethod
    def get_by_id(cls, unit_id, business_id):
        """
        Retrieve a unit by unit_id and business_id.
        """
        
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None  # Invalid business_id format

        try:
            unit_id_obj = ObjectId(unit_id)
        except Exception:
            return None  # Invalid _id format

        data = super().get_by_id(unit_id_obj, business_id_obj)

        if not data:
            return None  # Unit not found

        # Convert IDs to strings
        data["_id"] = str(data["_id"])
        if "business_id" in data:
            data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])

        # Decrypt fields only if they exist
        data["unit"] = decrypt_data(data["unit"]) if data.get("unit") else None
        data["name"] = decrypt_data(data["name"]) if data.get("name") else None
        data["status"] = decrypt_data(data["status"]) if data.get("status") else None

        # Remove sensitive information
        data.pop("hashed_unit", None)
        data.pop("admin_id", None)
        data.pop("agent_id", None)

        return data

    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve units for a given user__id + business_id with pagination,
        using the BaseModel generic helper and then post-processing.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for unit in payload.get("items", []):
            # Normalise IDs
            if "_id" in unit:
                unit["_id"] = str(unit["_id"])
            if "user__id" in unit:
                unit["user__id"] = str(unit["user__id"])
            if "business_id" in unit:
                unit["business_id"] = str(unit["business_id"])

            # Decrypt fields (if present)
            unit["unit"] = decrypt_data(unit["unit"]) if unit.get("unit") else None
            unit["name"] = decrypt_data(unit["name"]) if unit.get("name") else None
            unit["status"] = decrypt_data(unit["status"]) if unit.get("status") else None

            # created_at / updated_at already usable (datetime or ISO)
            unit["created_at"] = unit.get("created_at")
            unit["updated_at"] = unit.get("updated_at")

            # Remove internal / sensitive fields
            unit.pop("hashed_unit", None)
            unit.pop("admin_id", None)
            unit.pop("agent_id", None)

            processed.append(unit)

        # Replace generic key with domain-specific one
        payload["units"] = processed
        payload.pop("items", None)

        return payload
    
    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve all units for a business_id with pagination.
        """
        payload = super().get_by_business_id(
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for unit in payload.get("items", []):
            if "_id" in unit:
                unit["_id"] = str(unit["_id"])
            if "business_id" in unit:
                unit["business_id"] = str(unit["business_id"])
            if "user__id" in unit:
                unit["user__id"] = str(unit["user__id"])

            unit["unit"] = decrypt_data(unit["unit"]) if unit.get("unit") else None
            unit["name"] = decrypt_data(unit["name"]) if unit.get("name") else None
            unit["status"] = decrypt_data(unit["status"]) if unit.get("status") else None

            unit["created_at"] = unit.get("created_at")
            unit["updated_at"] = unit.get("updated_at")

            unit.pop("hashed_unit", None)
            unit.pop("admin_id", None)
            unit.pop("agent_id", None)

            processed.append(unit)

        payload["units"] = processed
        payload.pop("items", None)

        return payload
    
    @classmethod
    def update(cls, unit_id, **updates):
        """
        Update a unit's information by unit_id.
        Encrypts and hashes fields if updated.
        """
        
        if "unit" in updates and updates["unit"] is not None:
            updates["hashed_unit"] = hash_data(updates["unit"])
            updates["unit"] = encrypt_data(updates["unit"])

        if "name" in updates and updates["name"] is not None:
            updates["name"] = encrypt_data(updates["name"])

        if "status" in updates and updates["status"] is not None:
            updates["status"] = encrypt_data(updates["status"])

        return super().update(unit_id, **updates)

    @classmethod
    def delete(cls, unit_id, business_id):
        """
        Delete a unit by unit_id and business_id.
        """
        
        return super().delete(unit_id, business_id)

# Product Category
class Category(BaseModel):
    """
    A category represents a classification of units or products in a business.
    """

    collection_name = "categories"

    def __init__(self, business_id, user_id,user__id, name, slug=None, status="Active"):
        super().__init__(business_id, user_id, user__id=user__id, name=name, slug=slug, status=status)

        # Ensure slug is well-formed
        if slug:
            slug = name_to_slug(slug)
        else:
            slug = name_to_slug(name)

        # Encrypt name and slug
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.slug = encrypt_data(slug)

        # Encrypt status
        self.status = encrypt_data(status)

        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the category object to a dictionary representation.
        """
        category_dict = super().to_dict()
        category_dict.update({
            "slug": self.slug,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return category_dict

    @classmethod
    def get_by_id(cls, category_id, business_id):
        """
        Retrieve a category by _id (MongoDB's default identifier).
        """
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None
        try:
            category_id_obj = ObjectId(category_id)
        except Exception:
            return None

        data = super().get_by_id(category_id_obj, business_id_obj)

        if not data:
            return None  # Unit not found

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["user__id"] = str(data["user__id"])

        data["name"] = decrypt_data(data["name"])
        data["slug"] = decrypt_data(data["slug"]) if data.get("slug") else None
        data["status"] = decrypt_data(data["status"])

        data.pop("hashed_name", None)
        data.pop("admin_id", None)
        data.pop("agent_id", None)

        return data

    @classmethod
    def update(cls, category_id, **updates):
        """
        Update a category's information by category_id (MongoDB _id).
        Encrypts updated fields and hashes the name if updated.
        """
        if "name" in updates:
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])

        if "slug" in updates:
            # ensure slug is normalized
            updates["slug"] = name_to_slug(updates["slug"])
            updates["slug"] = encrypt_data(updates["slug"])

        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])

        updates["updated_at"] = datetime.now()

        return super().update(category_id, **updates)

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve categories by business_id, decrypting fields and supporting pagination.
        Uses BaseModel.get_by_business_id(...) and post-processes the docs.
        """
        payload = super().get_by_business_id(
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for category in payload.get("items", []):
            # Normalise IDs
            if "_id" in category:
                category["_id"] = str(category["_id"])
            if "business_id" in category:
                category["business_id"] = str(category["business_id"])
            if "user__id" in category:
                category["user__id"] = str(category["user__id"])

            # Decrypt fields
            category["name"] = decrypt_data(category["name"]) if category.get("name") else None
            category["slug"] = decrypt_data(category["slug"]) if category.get("slug") else None
            category["status"] = decrypt_data(category["status"]) if category.get("status") else None

            # Keep timestamps as they are
            category["created_at"] = category.get("created_at")
            category["updated_at"] = category.get("updated_at")

            # Strip internal fields
            category.pop("hashed_name", None)
            category.pop("admin_id", None)
            category.pop("agent_id", None)

            processed.append(category)

        # Rename items → categories for domain clarity
        payload["categories"] = processed
        payload.pop("items", None)

        return payload

    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve categories by user__id and business_id, decrypting fields and supporting pagination.
        Uses BaseModel.get_all_by_user__id_and_business_id(...) and post-processes the docs.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for category in payload.get("items", []):
            # Normalise IDs
            if "_id" in category:
                category["_id"] = str(category["_id"])
            if "business_id" in category:
                category["business_id"] = str(category["business_id"])
            if "user__id" in category:
                category["user__id"] = str(category["user__id"])

            # Decrypt fields
            category["name"] = decrypt_data(category["name"]) if category.get("name") else None
            category["slug"] = decrypt_data(category["slug"]) if category.get("slug") else None
            category["status"] = decrypt_data(category["status"]) if category.get("status") else None

            # Keep timestamps
            category["created_at"] = category.get("created_at")
            category["updated_at"] = category.get("updated_at")

            # Strip internal fields
            category.pop("hashed_name", None)
            category.pop("admin_id", None)
            category.pop("agent_id", None)

            processed.append(category)

        payload["categories"] = processed
        payload.pop("items", None)

        return payload
    
    @classmethod
    def update_category(cls, category_id, **updates):
        """
        Alternative explicit update method using direct update_one (kept for backwards compatibility).
        """
        if "name" in updates:
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])

        if "slug" in updates:
            updates["slug"] = name_to_slug(updates["slug"])
            updates["slug"] = encrypt_data(updates["slug"])

        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])

        updates["updated_at"] = datetime.now()

        try:
            result = db.get_collection(cls.collection_name).update_one(
                {"_id": ObjectId(category_id)}, {"$set": updates}
            )
            if result.matched_count == 0:
                return False
            return result.modified_count > 0
        except Exception:
            return False

    @classmethod
    def delete(cls, category_id, business_id):
        """
        Delete a category by MongoDB's _id via BaseModel.
        """
        return super().delete(category_id, business_id)
    
# Product Sub Category
class SubCategory(BaseModel):
    """
    A SubCategory represents a classification under a specific category in a business.
    """

    collection_name = "subcategories"

    def __init__(
        self,
        category_id,
        business_id,
        user_id,
        user__id,
        name,
        code=generate_store_code(),
        description=None,
        image=None,
        file_path=None,
        status="Active",
    ):
        super().__init__(
            business_id,
            user_id,
            user__id,
            name=name,
            code=code,
            description=description,
            status=status,
            image=image,
            file_path=file_path,
        )

        self.category_id = ObjectId(category_id)

        # Encrypt fields
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.code = encrypt_data(code) if code else None
        self.description = encrypt_data(description) if description else None
        self.image = encrypt_data(image) if image else None
        self.file_path = encrypt_data(file_path) if file_path else None
        self.status = encrypt_data(status)

        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        subcategory_dict = super().to_dict()
        subcategory_dict.update({
            "category_id": self.category_id,
            "code": self.code,
            "description": self.description,
            "image": self.image,
            "file_path": self.file_path,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return subcategory_dict

    @classmethod
    def get_by_id(cls, subcategory_id, business_id):
        """
        Retrieve a subcategory by _id and business_id.
        """
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None  # Invalid business_id format

        try:
            subcategory_id_obj = ObjectId(subcategory_id)
        except Exception:
            return None  # Invalid _id format

        data = super().get_by_id(subcategory_id_obj, business_id_obj)

        if not data:
            return None  # Unit not found

        # Convert IDs to strings
        data["_id"] = str(data["_id"])
        if "business_id" in data:
            data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])
        if "category_id" in data:
            data["category_id"] = str(data["category_id"])

        data["name"] = decrypt_data(data["name"])
        data["code"] = decrypt_data(data["code"]) if data.get("code") else None
        data["description"] = decrypt_data(data["description"]) if data.get("description") else None
        data["image"] = decrypt_data(data["image"]) if data.get("image") else None
        data["file_path"] = decrypt_data(data["file_path"]) if data.get("file_path") else None
        data["status"] = decrypt_data(data["status"])

        data.pop("hashed_name", None)
        data.pop("file_path", None)

        return data

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve subcategories by business_id, with pagination and decrypted fields.
        Uses BaseModel.get_by_business_id(...) and post-processes the docs.
        """
        # Use BaseModel helper (returns a payload with "items" + pagination meta)
        payload = super().get_by_business_id(business_id, page, per_page)
        processed = []

        for subcategory in payload.get("items", []):
            # Normalise IDs
            if "_id" in subcategory:
                subcategory["_id"] = str(subcategory["_id"])
            if "business_id" in subcategory:
                subcategory["business_id"] = str(subcategory["business_id"])
            if "user__id" in subcategory:
                subcategory["user__id"] = str(subcategory["user__id"])
            if "category_id" in subcategory:
                subcategory["category_id"] = str(subcategory["category_id"])

            # Decrypt fields
            subcategory["name"] = decrypt_data(subcategory["name"]) if subcategory.get("name") else None
            subcategory["code"] = decrypt_data(subcategory["code"]) if subcategory.get("code") else None
            subcategory["description"] = decrypt_data(subcategory["description"]) if subcategory.get("description") else None
            subcategory["image"] = decrypt_data(subcategory["image"]) if subcategory.get("image") else None
            subcategory["file_path"] = decrypt_data(subcategory["file_path"]) if subcategory.get("file_path") else None
            subcategory["status"] = decrypt_data(subcategory["status"]) if subcategory.get("status") else None

            # Remove internal / sensitive fields
            subcategory.pop("hashed_name", None)
            subcategory.pop("file_path", None)   # don't expose physical path

            processed.append(subcategory)

        # Replace generic key with domain-specific one
        payload["subcategories"] = processed
        payload.pop("items", None)

        return payload

    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve subcategories by user__id and business_id, with pagination and decrypted fields.
        Uses BaseModel.get_all_by_user__id_and_business_id(...) and post-processes the docs.
        """
        # Use BaseModel helper (returns a payload with "items" + pagination meta)
        payload = super().get_all_by_user__id_and_business_id(user__id, business_id, page, per_page)
        processed = []

        for subcategory in payload.get("items", []):
            # Normalise IDs
            if "_id" in subcategory:
                subcategory["_id"] = str(subcategory["_id"])
            if "business_id" in subcategory:
                subcategory["business_id"] = str(subcategory["business_id"])
            if "user__id" in subcategory:
                subcategory["user__id"] = str(subcategory["user__id"])
            if "category_id" in subcategory:
                subcategory["category_id"] = str(subcategory["category_id"])

            # Decrypt fields
            subcategory["name"] = decrypt_data(subcategory["name"]) if subcategory.get("name") else None
            subcategory["code"] = decrypt_data(subcategory["code"]) if subcategory.get("code") else None
            subcategory["description"] = decrypt_data(subcategory["description"]) if subcategory.get("description") else None
            subcategory["image"] = decrypt_data(subcategory["image"]) if subcategory.get("image") else None
            subcategory["file_path"] = decrypt_data(subcategory["file_path"]) if subcategory.get("file_path") else None
            subcategory["status"] = decrypt_data(subcategory["status"]) if subcategory.get("status") else None

            # Remove internal / sensitive fields
            subcategory.pop("hashed_name", None)
            subcategory.pop("file_path", None)   # don't expose physical path

            processed.append(subcategory)

        # Replace generic key with domain-specific one
        payload["subcategories"] = processed
        payload.pop("items", None)

        return payload

    @classmethod
    def update(cls, subcategory_id, **updates):
        """
        Update a subcategory's information by subcategory_id.
        """
        now = datetime.now()
        updates["updated_at"] = now

        if "name" in updates:
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])

        if "code" in updates:
            updates["code"] = encrypt_data(updates["code"])
        if "description" in updates:
            updates["description"] = encrypt_data(updates["description"])
        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])
        if "image" in updates:
            updates["image"] = encrypt_data(updates["image"])
        if "file_path" in updates:
            updates["file_path"] = encrypt_data(updates["file_path"])

        return super().update(subcategory_id, **updates)

    @classmethod
    def delete(cls, subcategory_id, business_id):
        """
        Delete a subcategory by _id and business_id.
        """
        try:
            subcategory_id_obj = ObjectId(subcategory_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(subcategory_id_obj, business_id_obj)
      
# ---------------------- BRAND MODEL ---------------------- #
class Brand(BaseModel):
    """
    A Brand represents a company or product line under a specific business.
    """

    collection_name = "brands"

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        name,
        image=None,
        status="Active",
        file_path=None,
    ):
        super().__init__(
            business_id,
            user_id,
            user__id,
            name=name,
            image=image,
            status=status,
            file_path=file_path,
        )

        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.image = encrypt_data(image) if image else None
        self.file_path = encrypt_data(file_path) if file_path else None
        self.status = encrypt_data(status)

        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the brand object to a dictionary representation.
        """
        brand_dict = super().to_dict()
        brand_dict.update({
            "image": self.image,
            "file_path": self.file_path,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return brand_dict

    @classmethod
    def get_by_id(cls, brand_id, business_id):
        """
        Retrieve a brand by _id and business_id.
        """
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None  # Invalid business_id format

        try:
            brand_id_obj = ObjectId(brand_id)
        except Exception:
            return None  # Invalid _id format

        data = super().get_by_id(brand_id_obj, business_id_obj)

        if not data:
            return None  # Unit not found

        # Convert IDs to strings
        data["_id"] = str(data["_id"])
        if "business_id" in data:
            data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])


        # Decrypt fields
        data["name"] = decrypt_data(data["name"])
        data["image"] = decrypt_data(data["image"]) if data.get("image") else None
        data["file_path"] = decrypt_data(data["file_path"]) if data.get("file_path") else None
        data["status"] = decrypt_data(data["status"])

        # Remove internal/sensitive fields
        data.pop("hashed_name", None)
        data.pop("file_path", None)
        data.pop("agent_id", None)
        data.pop("admin_id", None)

        return data

    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve brands for a given user__id + business_id with pagination,
        using the BaseModel generic helper and then post-processing.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for brand in payload.get("items", []):
            # Normalise IDs
            if "_id" in brand:
                brand["_id"] = str(brand["_id"])
            if "user__id" in brand:
                brand["user__id"] = str(brand["user__id"])
            if "business_id" in brand:
                brand["business_id"] = str(brand["business_id"])

            # Decrypt business fields
            brand["name"] = decrypt_data(brand["name"]) if brand.get("name") else None
            brand["image"] = decrypt_data(brand["image"]) if brand.get("image") else None
            brand["status"] = decrypt_data(brand["status"]) if brand.get("status") else None

            # Keep timestamps as-is (datetime or ISO)
            brand["created_at"] = brand.get("created_at")
            brand["updated_at"] = brand.get("updated_at")

            # Remove internal / sensitive fields
            brand.pop("hashed_name", None)
            brand.pop("file_path", None)
            brand.pop("admin_id", None)
            brand.pop("agent_id", None)

            processed.append(brand)

        # Replace generic key with domain-specific one
        payload["brands"] = processed
        payload.pop("items", None)

        return payload

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve all brands for a business_id with pagination,
        using the BaseModel generic helper and then post-processing.
        """
        payload = super().get_by_business_id(
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for brand in payload.get("items", []):
            # Normalise IDs
            if "_id" in brand:
                brand["_id"] = str(brand["_id"])
            if "business_id" in brand:
                brand["business_id"] = str(brand["business_id"])
            if "user__id" in brand:
                brand["user__id"] = str(brand["user__id"])

            # Decrypt business fields
            brand["name"] = decrypt_data(brand["name"]) if brand.get("name") else None
            brand["image"] = decrypt_data(brand["image"]) if brand.get("image") else None
            brand["status"] = decrypt_data(brand["status"]) if brand.get("status") else None

            # Timestamps
            brand["created_at"] = brand.get("created_at")
            brand["updated_at"] = brand.get("updated_at")

            # Strip internal / sensitive
            brand.pop("hashed_name", None)
            brand.pop("file_path", None)
            brand.pop("admin_id", None)
            brand.pop("agent_id", None)

            processed.append(brand)

        payload["brands"] = processed
        payload.pop("items", None)

        return payload
   
    @classmethod
    def update(cls, brand_id, **updates):
        """
        Update a brand's information by brand_id.
        """
        updates["updated_at"] = datetime.now()

        if "name" in updates:
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])

        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])
        if "image" in updates:
            updates["image"] = encrypt_data(updates["image"])
        if "file_path" in updates:
            updates["file_path"] = encrypt_data(updates["file_path"])

        return super().update(brand_id, **updates)

    @classmethod
    def delete(cls, brand_id, business_id):
        """
        Delete a brand by _id and business_id.
        """
        try:
            brand_id_obj = ObjectId(brand_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(brand_id_obj, business_id_obj)

# ---------------------- VARIANT MODEL ---------------------- #
class Variant(BaseModel):
    """
    A Variant represents a specific variation of a product in a business,
    such as different colors or sizes.
    """

    collection_name = "variants"

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        name,
        values,
        status="Active",
        image=None,
        file_path=None,
    ):
        super().__init__(
            business_id,
            user_id,
            user__id,
            name=name,
            values=values,
            status=status,
            image=image,
            file_path=file_path,
        )

        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.values = encrypt_data(values)
        self.image = encrypt_data(image) if image else None
        self.file_path = encrypt_data(file_path) if file_path else None
        self.status = encrypt_data(status)

        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the variant object to a dictionary representation.
        """
        variant_dict = super().to_dict()
        variant_dict.update({
            "values": self.values,
            "image": self.image,
            "file_path": self.file_path,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return variant_dict

    # ---------------------------------------------------------------------
    # SINGLE FETCH
    # ---------------------------------------------------------------------
    @classmethod
    def get_by_id(cls, variant_id, business_id):
        """
        Retrieve a variant by _id and business_id.
        Mirrors Brand.get_by_id style: direct collection call + decrypt.
        """
        try:
            variant_id_obj = ObjectId(variant_id)
        except Exception:
            return None

        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        data = super().get_by_id(variant_id_obj, business_id_obj)

        if not data:
            return None

        # IDs to strings
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])

        # Decrypt fields
        data["name"] = decrypt_data(data["name"])
        data["values"] = decrypt_data(data["values"])
        data["image"] = decrypt_data(data["image"]) if data.get("image") else None
        data["file_path"] = decrypt_data(data["file_path"]) if data.get("file_path") else None
        data["status"] = decrypt_data(data["status"])

        # Remove internal/sensitive
        data.pop("hashed_name", None)
        data.pop("file_path", None)   # hide internal storage path
        data.pop("agent_id", None)
        data.pop("admin_id", None)

        return data

    # ---------------------------------------------------------------------
    # LIST FETCH – BY BUSINESS
    # ---------------------------------------------------------------------
    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve variants by business_id with pagination and decrypted fields.
        Uses BaseModel.get_by_business_id(...) and post-processes the docs.
        """
        payload = super().get_by_business_id(
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for variant in payload.get("items", []):
            # Normalise IDs
            if "_id" in variant:
                variant["_id"] = str(variant["_id"])
            if "business_id" in variant:
                variant["business_id"] = str(variant["business_id"])
            if "user__id" in variant:
                variant["user__id"] = str(variant["user__id"])

            # Decrypt fields only if they are present
            variant["name"] = decrypt_data(variant["name"]) if variant.get("name") else None
            variant["values"] = decrypt_data(variant["values"]) if variant.get("values") else None
            variant["image"] = decrypt_data(variant["image"]) if variant.get("image") else None
            variant["status"] = decrypt_data(variant["status"]) if variant.get("status") else None

            # created_at / updated_at are already usable
            variant["created_at"] = variant.get("created_at")
            variant["updated_at"] = variant.get("updated_at")

            # Remove sensitive / internal fields
            variant.pop("hashed_name", None)
            variant.pop("file_path", None)
            variant.pop("agent_id", None)
            variant.pop("admin_id", None)

            processed.append(variant)

        # Replace generic key with domain-specific one
        payload["variants"] = processed
        payload.pop("items", None)

        return payload

    # ---------------------------------------------------------------------
    # LIST FETCH – BY USER__ID + BUSINESS
    # ---------------------------------------------------------------------
    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve variants by user__id and business_id with pagination and decrypted fields.
        Uses BaseModel.get_all_by_user__id_and_business_id(...) and post-processes the docs.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for variant in payload.get("items", []):
            # Normalise IDs
            if "_id" in variant:
                variant["_id"] = str(variant["_id"])
            if "user__id" in variant:
                variant["user__id"] = str(variant["user__id"])
            if "business_id" in variant:
                variant["business_id"] = str(variant["business_id"])

            # Decrypt fields only if they are present
            variant["name"] = decrypt_data(variant["name"]) if variant.get("name") else None
            variant["values"] = decrypt_data(variant["values"]) if variant.get("values") else None
            variant["image"] = decrypt_data(variant["image"]) if variant.get("image") else None
            variant["status"] = decrypt_data(variant["status"]) if variant.get("status") else None

            # created_at / updated_at are already usable
            variant["created_at"] = variant.get("created_at")
            variant["updated_at"] = variant.get("updated_at")

            # Remove sensitive / internal fields
            variant.pop("hashed_name", None)
            variant.pop("file_path", None)
            variant.pop("agent_id", None)
            variant.pop("admin_id", None)

            processed.append(variant)

        # Replace generic key with domain-specific one
        payload["variants"] = processed
        payload.pop("items", None)

        return payload

    # ---------------------------------------------------------------------
    # UPDATE / DELETE
    # ---------------------------------------------------------------------
    @classmethod
    def update(cls, variant_id, **updates):
        """
        Update a variant's information by variant_id.
        Mirrors Brand.update for encryption behaviour.
        """
        updates["updated_at"] = datetime.now()

        if "name" in updates:
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])

        if "values" in updates:
            updates["values"] = encrypt_data(updates["values"])
        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])
        if "image" in updates:
            updates["image"] = encrypt_data(updates["image"])
        if "file_path" in updates:
            updates["file_path"] = encrypt_data(updates["file_path"])

        return super().update(variant_id, **updates)

    @classmethod
    def delete(cls, variant_id, business_id):
        """
        Delete a variant by _id and business_id.
        """
        try:
            variant_id_obj = ObjectId(variant_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(variant_id_obj, business_id_obj)
    
# ---------------------- TAX MODEL ---------------------- #
class Tax(BaseModel):
    """
    A Tax represents a specific tax applied to a business, such as sales tax or value-added tax.
    """

    collection_name = "taxes"

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        name,
        rate,
        status="Active",
    ):
        super().__init__(
            business_id,
            user_id,
            user__id,
            name=name,
            rate=rate,
            status=status,
        )

        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.rate = encrypt_data(rate)
        self.status = encrypt_data(status)

        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the tax object to a dictionary representation.
        """
        tax_dict = super().to_dict()
        tax_dict.update({
            "rate": self.rate,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return tax_dict

    @classmethod
    def get_by_id(cls, tax_id, business_id):
        """
        Retrieve a tax by _id and business_id.
        """
        try:
            tax_id_obj = ObjectId(tax_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        data = super().get_by_id(tax_id_obj, business_id_obj)

        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])

        data["name"] = decrypt_data(data["name"])
        data["rate"] = decrypt_data(data["rate"])
        data["status"] = decrypt_data(data["status"])

        data.pop("hashed_name", None)
        data.pop("agent_id", None)
        data.pop("admin_id", None)

        return data

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve taxes by business_id with pagination and decrypted fields.
        Uses BaseModel.get_by_business_id(...) and post-processes the docs.
        """
        payload = super().get_by_business_id(business_id, page, per_page)
        processed = []

        for tax in payload.get("items", []):
            # Normalise IDs
            if "_id" in tax:
                tax["_id"] = str(tax["_id"])
            if "business_id" in tax:
                tax["business_id"] = str(tax["business_id"])
            if "user__id" in tax:
                tax["user__id"] = str(tax["user__id"])

            # Decrypt fields only if they are present
            tax["name"] = decrypt_data(tax["name"]) if tax.get("name") else None
            tax["rate"] = decrypt_data(tax["rate"]) if tax.get("rate") else None
            tax["status"] = decrypt_data(tax["status"]) if tax.get("status") else None

            # created_at / updated_at are already usable
            tax["created_at"] = tax.get("created_at")
            tax["updated_at"] = tax.get("updated_at")

            # Remove sensitive / internal fields
            tax.pop("hashed_name", None)
            tax.pop("agent_id", None)
            tax.pop("admin_id", None)

            processed.append(tax)

        # Replace generic key with domain-specific one
        payload["taxes"] = processed
        payload.pop("items", None)

        return payload

    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve taxes by user__id and business_id with pagination and decrypted fields.
        Uses BaseModel.get_all_by_user__id_and_business_id(...) and post-processes the docs.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )
        processed = []

        for tax in payload.get("items", []):
            # Normalise IDs
            if "_id" in tax:
                tax["_id"] = str(tax["_id"])
            if "user__id" in tax:
                tax["user__id"] = str(tax["user__id"])
            if "business_id" in tax:
                tax["business_id"] = str(tax["business_id"])

            # Decrypt fields only if they are present
            tax["name"] = decrypt_data(tax["name"]) if tax.get("name") else None
            tax["rate"] = decrypt_data(tax["rate"]) if tax.get("rate") else None
            tax["status"] = decrypt_data(tax["status"]) if tax.get("status") else None

            # created_at / updated_at are already usable
            tax["created_at"] = tax.get("created_at")
            tax["updated_at"] = tax.get("updated_at")

            # Remove sensitive / internal fields
            tax.pop("hashed_name", None)
            tax.pop("agent_id", None)
            tax.pop("admin_id", None)

            processed.append(tax)

        # Replace generic key with domain-specific one
        payload["taxes"] = processed
        payload.pop("items", None)

        return payload
    
    @classmethod
    def update(cls, tax_id, **updates):
        """
        Update a tax's information by tax_id.
        """
        updates["updated_at"] = datetime.now()

        if "name" in updates:
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])

        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])
        if "rate" in updates:
            updates["rate"] = encrypt_data(updates["rate"])

        return super().update(tax_id, **updates)

    @classmethod
    def delete(cls, tax_id, business_id):
        """
        Delete a tax by _id and business_id.
        """
        try:
            tax_id_obj = ObjectId(tax_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(tax_id_obj, business_id_obj)

# ---------------------- WARRANTY MODEL ---------------------- #
class Warranty(BaseModel):
    """
    A Warranty represents a specific warranty applied to a product or service.
    """

    collection_name = "warranties"

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        name,
        duration,
        period,
        status="Active",
        description=None,
    ):
        super().__init__(
            business_id,
            user_id,
            user__id,
            name=name,
            duration=duration,
            period=period,
            status=status,
            description=description,
        )

        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.duration = encrypt_data(duration)
        self.period = encrypt_data(period)
        self.description = encrypt_data(description) if description else None
        self.status = encrypt_data(status)

        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the warranty object to a dictionary representation.
        """
        warranty_dict = super().to_dict()
        warranty_dict.update(
            {
                "duration": self.duration,
                "period": self.period,
                "status": self.status,
                "description": self.description,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
        )
        return warranty_dict

    @classmethod
    def get_by_id(cls, warranty_id, business_id):
        """
        Retrieve a warranty by _id and business_id.
        """
        try:
            warranty_id_obj = ObjectId(warranty_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        data = super().get_by_id(warranty_id_obj, business_id_obj)

        if not data:
            return None

        # Convert IDs to strings
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])

        # Decrypt fields
        data["name"] = decrypt_data(data["name"])
        data["duration"] = decrypt_data(data["duration"])
        data["period"] = decrypt_data(data["period"])
        data["status"] = decrypt_data(data["status"])
        data["description"] = (
            decrypt_data(data["description"]) if data.get("description") else None
        )

        # Remove internal/sensitive fields
        data.pop("hashed_name", None)
        data.pop("agent_id", None)
        data.pop("admin_id", None)

        return data

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve warranties by business_id with pagination and decrypted fields.
        Uses BaseModel.get_by_business_id(...) and post-processes the docs.
        """
        payload = super().get_by_business_id(business_id, page, per_page)
        processed = []

        for warranty in payload.get("items", []):
            # Normalise IDs
            if "_id" in warranty:
                warranty["_id"] = str(warranty["_id"])
            if "business_id" in warranty:
                warranty["business_id"] = str(warranty["business_id"])
            if "user__id" in warranty:
                warranty["user__id"] = str(warranty["user__id"])

            # Decrypt fields only if they are present
            warranty["name"] = decrypt_data(warranty["name"]) if warranty.get("name") else None
            warranty["duration"] = decrypt_data(warranty["duration"]) if warranty.get("duration") else None
            warranty["period"] = decrypt_data(warranty["period"]) if warranty.get("period") else None
            warranty["status"] = decrypt_data(warranty["status"]) if warranty.get("status") else None
            warranty["description"] = (
                decrypt_data(warranty["description"])
                if warranty.get("description")
                else None
            )

            # created_at / updated_at are already usable
            warranty["created_at"] = warranty.get("created_at")
            warranty["updated_at"] = warranty.get("updated_at")

            # Remove internal/sensitive fields
            warranty.pop("hashed_name", None)
            warranty.pop("agent_id", None)
            warranty.pop("admin_id", None)

            processed.append(warranty)

        # Replace generic key with domain-specific one
        payload["warranties"] = processed
        payload.pop("items", None)

        return payload

    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve warranties by user__id and business_id with pagination and decrypted fields.
        Uses BaseModel.get_all_by_user__id_and_business_id(...) and post-processes the docs.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )
        processed = []

        for warranty in payload.get("items", []):
            # Normalise IDs
            if "_id" in warranty:
                warranty["_id"] = str(warranty["_id"])
            if "business_id" in warranty:
                warranty["business_id"] = str(warranty["business_id"])
            if "user__id" in warranty:
                warranty["user__id"] = str(warranty["user__id"])

            # Decrypt fields only if they are present
            warranty["name"] = decrypt_data(warranty["name"]) if warranty.get("name") else None
            warranty["duration"] = decrypt_data(warranty["duration"]) if warranty.get("duration") else None
            warranty["period"] = decrypt_data(warranty["period"]) if warranty.get("period") else None
            warranty["status"] = decrypt_data(warranty["status"]) if warranty.get("status") else None
            warranty["description"] = (
                decrypt_data(warranty["description"])
                if warranty.get("description")
                else None
            )

            # created_at / updated_at are already usable
            warranty["created_at"] = warranty.get("created_at")
            warranty["updated_at"] = warranty.get("updated_at")

            # Remove internal/sensitive fields
            warranty.pop("hashed_name", None)
            warranty.pop("agent_id", None)
            warranty.pop("admin_id", None)

            processed.append(warranty)

        # Replace generic key with domain-specific one
        payload["warranties"] = processed
        payload.pop("items", None)

        return payload
    
    @classmethod
    def update(cls, warranty_id, **updates):
        """
        Update a warranty's information by warranty_id.
        """
        updates["updated_at"] = datetime.now()

        if "name" in updates:
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])

        if "duration" in updates:
            updates["duration"] = encrypt_data(updates["duration"])
        if "period" in updates:
            updates["period"] = encrypt_data(updates["period"])
        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])
        if "description" in updates:
            updates["description"] = encrypt_data(updates["description"])

        return super().update(warranty_id, **updates)

    @classmethod
    def delete(cls, warranty_id, business_id):
        """
        Delete a warranty by _id and business_id.
        """
        try:
            warranty_id_obj = ObjectId(warranty_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(warranty_id_obj, business_id_obj)

# ---------------------- SUPPLIER MODEL ---------------------- #
class Supplier(BaseModel):
    """
    A Supplier represents a business or individual supplier in the system.
    """

    collection_name = "suppliers"
    
    # Centralise fields that must always be encrypted
    ENCRYPTED_FIELDS = {
        "name",
        "description",
        "first_name",
        "last_name",
        "company",
        "email",
        "phone",
        "fax",
        "website",
        "twitter",
        "street",
        "suburb",
        "city",
        "state",
        "zipcode",
        "country",
        "status",
    }

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        name,
        description,
        first_name,
        last_name,
        company,
        email=None,
        phone=None,
        fax=None,
        website=None,
        twitter=None,
        street=None,
        suburb=None,
        city=None,
        state=None,
        zipcode=None,
        country=None,
        status="Active",
    ):
        super().__init__(
            business_id,
            user_id,
            user__id,
            name=name,
            description=description,
            first_name=first_name,
            last_name=last_name,
            company=company,
            email=email,
            phone=phone,
            fax=fax,
            website=website,
            twitter=twitter,
            street=street,
            suburb=suburb,
            city=city,
            state=state,
            zipcode=zipcode,
            country=country,
            status=status,
        )

        # Encrypted and derived fields
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)

        self.description = encrypt_data(description) if description else None
        self.first_name = encrypt_data(first_name)
        self.last_name = encrypt_data(last_name)
        self.company = encrypt_data(company)

        self.email = encrypt_data(email) if email else None
        self.phone = encrypt_data(phone) if phone else None
        self.fax = encrypt_data(fax) if fax else None
        self.website = encrypt_data(website) if website else None
        self.twitter = encrypt_data(twitter) if twitter else None

        self.street = encrypt_data(street) if street else None
        self.suburb = encrypt_data(suburb) if suburb else None
        self.city = encrypt_data(city) if city else None
        self.state = encrypt_data(state) if state else None
        self.zipcode = encrypt_data(zipcode) if zipcode else None
        self.country = encrypt_data(country) if country else None

        self.status = encrypt_data(status)

        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the supplier object to a dictionary representation.
        """
        supplier_dict = super().to_dict()
        supplier_dict.update({
            "description": self.description,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "company": self.company,
            "email": self.email,
            "phone": self.phone,
            "fax": self.fax,
            "website": self.website,
            "twitter": self.twitter,
            "street": self.street,
            "suburb": self.suburb,
            "city": self.city,
            "state": self.state,
            "zipcode": self.zipcode,
            "country": self.country,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return supplier_dict

    # ---------- SINGLE RETRIEVAL ----------

    @classmethod
    def get_by_id(cls, supplier_id, business_id):
        """
        Retrieve a supplier by _id and business_id.
        """
        try:
            supplier_id_obj = ObjectId(supplier_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        data = super().get_by_id(supplier_id_obj, business_id_obj)

        if not data:
            return None

        # Convert IDs to strings
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])

        # Decrypt fields
        data["name"] = decrypt_data(data["name"])
        data["description"] = decrypt_data(data["description"]) if data.get("description") else None
        data["first_name"] = decrypt_data(data["first_name"])
        data["last_name"] = decrypt_data(data["last_name"])
        data["company"] = decrypt_data(data["company"])

        data["email"] = decrypt_data(data["email"]) if data.get("email") else None
        data["phone"] = decrypt_data(data["phone"]) if data.get("phone") else None
        data["fax"] = decrypt_data(data["fax"]) if data.get("fax") else None
        data["website"] = decrypt_data(data["website"]) if data.get("website") else None
        data["twitter"] = decrypt_data(data["twitter"]) if data.get("twitter") else None

        data["street"] = decrypt_data(data["street"]) if data.get("street") else None
        data["suburb"] = decrypt_data(data["suburb"]) if data.get("suburb") else None
        data["city"] = decrypt_data(data["city"]) if data.get("city") else None
        data["state"] = decrypt_data(data["state"]) if data.get("state") else None
        data["zipcode"] = decrypt_data(data["zipcode"]) if data.get("zipcode") else None
        data["country"] = decrypt_data(data["country"]) if data.get("country") else None

        data["status"] = decrypt_data(data["status"])

        # Remove internal/sensitive fields
        data.pop("hashed_name", None)
        data.pop("agent_id", None)
        data.pop("admin_id", None)

        return data

    # ---------- LIST BY BUSINESS (PAGINATED) ----------

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve suppliers by business_id with pagination and decrypted fields.
        Uses BaseModel.get_by_business_id(...) and post-processes the docs.
        """
        payload = super().get_by_business_id(
            business_id=business_id,
            page=page,
            per_page=per_page,
        )
        processed = []

        for supplier in payload.get("items", []):
            # Convert IDs to strings if present
            if "_id" in supplier:
                supplier["_id"] = str(supplier["_id"])
            if "business_id" in supplier:
                supplier["business_id"] = str(supplier["business_id"])
            if "user__id" in supplier:
                supplier["user__id"] = str(supplier["user__id"])

            # Decrypt core identity fields
            supplier["name"] = decrypt_data(supplier["name"]) if supplier.get("name") else None
            supplier["description"] = (
                decrypt_data(supplier["description"])
                if supplier.get("description")
                else None
            )
            supplier["first_name"] = decrypt_data(supplier["first_name"]) if supplier.get("first_name") else None
            supplier["last_name"] = decrypt_data(supplier["last_name"]) if supplier.get("last_name") else None
            supplier["company"] = decrypt_data(supplier["company"]) if supplier.get("company") else None

            # Decrypt contact fields
            supplier["email"] = decrypt_data(supplier["email"]) if supplier.get("email") else None
            supplier["phone"] = decrypt_data(supplier["phone"]) if supplier.get("phone") else None
            supplier["fax"] = decrypt_data(supplier["fax"]) if supplier.get("fax") else None
            supplier["website"] = decrypt_data(supplier["website"]) if supplier.get("website") else None
            supplier["twitter"] = decrypt_data(supplier["twitter"]) if supplier.get("twitter") else None

            # Decrypt address fields
            supplier["street"] = decrypt_data(supplier["street"]) if supplier.get("street") else None
            supplier["suburb"] = decrypt_data(supplier["suburb"]) if supplier.get("suburb") else None
            supplier["city"] = decrypt_data(supplier["city"]) if supplier.get("city") else None
            supplier["state"] = decrypt_data(supplier["state"]) if supplier.get("state") else None
            supplier["zipcode"] = decrypt_data(supplier["zipcode"]) if supplier.get("zipcode") else None
            supplier["country"] = decrypt_data(supplier["country"]) if supplier.get("country") else None

            # Decrypt status
            supplier["status"] = decrypt_data(supplier["status"]) if supplier.get("status") else None

            # Preserve timestamps
            supplier["created_at"] = supplier.get("created_at")
            supplier["updated_at"] = supplier.get("updated_at")

            # Remove internal / sensitive fields
            supplier.pop("hashed_name", None)
            supplier.pop("agent_id", None)
            supplier.pop("admin_id", None)

            processed.append(supplier)

        # Replace generic key with domain-specific one
        payload["suppliers"] = processed
        payload.pop("items", None)

        return payload

    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve suppliers by user__id and business_id with pagination and decrypted fields.
        Uses BaseModel.get_all_by_user__id_and_business_id(...) and post-processes the docs.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )
        processed = []

        for supplier in payload.get("items", []):
            # Convert IDs to strings if present
            if "_id" in supplier:
                supplier["_id"] = str(supplier["_id"])
            if "business_id" in supplier:
                supplier["business_id"] = str(supplier["business_id"])
            if "user__id" in supplier:
                supplier["user__id"] = str(supplier["user__id"])

            # Decrypt core identity fields
            supplier["name"] = decrypt_data(supplier["name"]) if supplier.get("name") else None
            supplier["description"] = (
                decrypt_data(supplier["description"])
                if supplier.get("description")
                else None
            )
            supplier["first_name"] = decrypt_data(supplier["first_name"]) if supplier.get("first_name") else None
            supplier["last_name"] = decrypt_data(supplier["last_name"]) if supplier.get("last_name") else None
            supplier["company"] = decrypt_data(supplier["company"]) if supplier.get("company") else None

            # Decrypt contact fields
            supplier["email"] = decrypt_data(supplier["email"]) if supplier.get("email") else None
            supplier["phone"] = decrypt_data(supplier["phone"]) if supplier.get("phone") else None
            supplier["fax"] = decrypt_data(supplier["fax"]) if supplier.get("fax") else None
            supplier["website"] = decrypt_data(supplier["website"]) if supplier.get("website") else None
            supplier["twitter"] = decrypt_data(supplier["twitter"]) if supplier.get("twitter") else None

            # Decrypt address fields
            supplier["street"] = decrypt_data(supplier["street"]) if supplier.get("street") else None
            supplier["suburb"] = decrypt_data(supplier["suburb"]) if supplier.get("suburb") else None
            supplier["city"] = decrypt_data(supplier["city"]) if supplier.get("city") else None
            supplier["state"] = decrypt_data(supplier["state"]) if supplier.get("state") else None
            supplier["zipcode"] = decrypt_data(supplier["zipcode"]) if supplier.get("zipcode") else None
            supplier["country"] = decrypt_data(supplier["country"]) if supplier.get("country") else None

            # Decrypt status
            supplier["status"] = decrypt_data(supplier["status"]) if supplier.get("status") else None

            # Preserve timestamps
            supplier["created_at"] = supplier.get("created_at")
            supplier["updated_at"] = supplier.get("updated_at")

            # Remove internal / sensitive fields
            supplier.pop("hashed_name", None)
            supplier.pop("agent_id", None)
            supplier.pop("admin_id", None)

            processed.append(supplier)

        # Replace generic key with domain-specific one
        payload["suppliers"] = processed
        payload.pop("items", None)

        return payload

    # ---------- UPDATE / DELETE ----------

    @classmethod
    def update(cls, supplier_id, **updates):
        """
        Update a supplier's information by supplier_id.

        - Adds/updates `updated_at`
        - Hashes `name` into `hashed_name` if provided
        - Encrypts all configured fields that appear in `updates`
        """

        # Work on a copy so we don't surprise callers
        updates = {k: v for k, v in updates.items() if v is not None}

        # Timestamp
        updates["updated_at"] = datetime.utcnow()

        # Handle name separately: hash + encrypt
        if "name" in updates:
            plain_name = updates["name"]
            updates["hashed_name"] = hash_data(plain_name)
            updates["name"] = encrypt_data(plain_name)

        # Encrypt the rest of the fields defined in ENCRYPTED_FIELDS
        for field in cls.ENCRYPTED_FIELDS:
            # `name` already handled above
            if field in updates and field != "name":
                updates[field] = encrypt_data(updates[field])

        return super().update(supplier_id, **updates)
    
    @classmethod
    def delete(cls, supplier_id, business_id):
        """
        Delete a supplier by _id and business_id.
        """
        try:
            supplier_id_obj = ObjectId(supplier_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(supplier_id_obj, business_id_obj)

# ---------------------- TAG MODEL ---------------------- #
class Tag(BaseModel):
    """
    A Tag represents a specific label or category assigned to products in a business.
    """

    collection_name = "tags"

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        name,
        number_of_products=0,
        status="Active",
    ):
        super().__init__(
            business_id,
            user_id,
            user__id,
            name=name,
            number_of_products=number_of_products,
            status=status,
        )

        self.name = encrypt_data(name)          # Encrypt the name
        self.hashed_name = hash_data(name)      # Hashed name for comparison/search
        self.number_of_products = number_of_products
        self.status = encrypt_data(status)      # Encrypt status

        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the tag object to a dictionary representation.
        """
        tag_dict = super().to_dict()
        tag_dict.update({
            "number_of_products": self.number_of_products,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return tag_dict

    @classmethod
    def get_by_id(cls, tag_id, business_id):
        """
        Retrieve a tag by _id and business_id.
        """
        try:
            tag_id_obj = ObjectId(tag_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        data = super().get_by_id(tag_id_obj, business_id_obj)

        if not data:
            return None

        # Normalize IDs to strings
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])

        # Decrypt fields
        data["name"] = decrypt_data(data["name"])
        data["status"] = decrypt_data(data["status"])
        data["number_of_products"] = data.get("number_of_products", 0)

        # Remove internal fields not needed by client
        data.pop("hashed_name", None)
        data.pop("agent_id", None)
        data.pop("admin_id", None)

        return data

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve tags by business_id with pagination and decrypted fields.
        Uses BaseModel.get_by_business_id(...) and post-processes the docs.
        """
        payload = super().get_by_business_id(
            business_id=business_id,
            page=page,
            per_page=per_page,
        )
        processed = []

        for tag in payload.get("items", []):
            # Normalise IDs
            if "_id" in tag:
                tag["_id"] = str(tag["_id"])
            if "business_id" in tag:
                tag["business_id"] = str(tag["business_id"])
            if "user__id" in tag:
                tag["user__id"] = str(tag["user__id"])

            # Decrypt fields (only if present)
            tag["name"] = decrypt_data(tag["name"]) if tag.get("name") else None
            tag["status"] = decrypt_data(tag["status"]) if tag.get("status") else None

            # number_of_products – keep numeric or default to 0
            tag["number_of_products"] = tag.get("number_of_products", 0)

            # created_at / updated_at are already usable
            tag["created_at"] = tag.get("created_at")
            tag["updated_at"] = tag.get("updated_at")

            # Remove internal/sensitive fields
            tag.pop("hashed_name", None)
            tag.pop("agent_id", None)
            tag.pop("admin_id", None)

            processed.append(tag)

        # Replace generic key with domain-specific one
        payload["tags"] = processed
        payload.pop("items", None)

        return payload

    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve tags by user__id and business_id with pagination and decrypted fields.
        Uses BaseModel.get_all_by_user__id_and_business_id(...) and post-processes the docs.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )
        processed = []

        for tag in payload.get("items", []):
            # Normalise IDs
            if "_id" in tag:
                tag["_id"] = str(tag["_id"])
            if "business_id" in tag:
                tag["business_id"] = str(tag["business_id"])
            if "user__id" in tag:
                tag["user__id"] = str(tag["user__id"])

            # Decrypt fields (only if present)
            tag["name"] = decrypt_data(tag["name"]) if tag.get("name") else None
            tag["status"] = decrypt_data(tag["status"]) if tag.get("status") else None

            # number_of_products – keep numeric or default to 0
            tag["number_of_products"] = tag.get("number_of_products", 0)

            # created_at / updated_at are already usable
            tag["created_at"] = tag.get("created_at")
            tag["updated_at"] = tag.get("updated_at")

            # Remove internal/sensitive fields
            tag.pop("hashed_name", None)
            tag.pop("agent_id", None)
            tag.pop("admin_id", None)

            processed.append(tag)

        # Replace generic key with domain-specific one
        payload["tags"] = processed
        payload.pop("items", None)

        return payload
    
    @classmethod
    def update(cls, tag_id, **updates):
        """
        Update a tag's information by tag_id.
        """
        updates["updated_at"] = datetime.now()

        # If the name is being updated, hash and encrypt it
        if "name" in updates:
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])

        # Encrypt other sensitive fields if they are being updated
        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])

        # number_of_products is kept as a plain integer
        # (no encryption needed unless you want to hide counts)
        # if "number_of_products" in updates:
        #     updates["number_of_products"] = updates["number_of_products"]

        return super().update(tag_id, **updates)

    @classmethod
    def delete(cls, tag_id, business_id):
        """
        Delete a tag by _id and business_id.
        """
        try:
            tag_id_obj = ObjectId(tag_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(tag_id_obj, business_id_obj)


# Product Composite Variant
# ---------------------- COMPOSITE VARIANT MODEL ---------------------- #
class CompositeVariant(BaseModel):
    """
    A CompositeVariant represents a specific variation of a product in a business,
    with additional features like barcode symbology, code, images, stock, and taxes.
    """

    collection_name = "composite_variants"

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        values=None,
        status="Active",
        thumbnail=None,
        barcode_symbology=None,
        code=None,
        image=None,
        quantity=None,
        quantity_alert=None,
        tax_type=None,
        tax=None,
        discount_type=None,
        discount_value=None,
        file_path=None,
    ):
        super().__init__(
            business_id,
            user_id,
            user__id,
            values=values,
            status=status,
            thumbnail=thumbnail,
            barcode_symbology=barcode_symbology,
            code=code,
            image=image,
            quantity=quantity,
            quantity_alert=quantity_alert,
            tax_type=tax_type,
            tax=tax,
            discount_type=discount_type,
            discount_value=discount_value,
            file_path=file_path,
        )

        # Business-level identifier (not the Mongo _id)
        self.variant_id = str(uuid.uuid4())

        # Encrypt core fields
        self.values = encrypt_data(values) if values else None
        self.hashed_values = hash_data(values) if values else None

        self.status = encrypt_data(status)
        self.thumbnail = encrypt_data(thumbnail) if thumbnail else None
        self.barcode_symbology = encrypt_data(barcode_symbology) if barcode_symbology else None
        self.code = encrypt_data(code) if code else None
        self.image = encrypt_data(image) if image else None
        self.quantity = encrypt_data(quantity) if quantity else None
        self.quantity_alert = encrypt_data(quantity_alert) if quantity_alert else None
        self.tax_type = encrypt_data(tax_type) if tax_type else None
        self.tax = encrypt_data(tax) if tax else None
        self.discount_type = encrypt_data(discount_type) if discount_type else None
        self.discount_value = encrypt_data(discount_value) if discount_value else None
        self.file_path = encrypt_data(file_path) if file_path else None

        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the CompositeVariant object to a dictionary representation.
        """
        variant_dict = super().to_dict()
        variant_dict.update({
            "variant_id": self.variant_id,
            "values": self.values,
            "hashed_values": self.hashed_values,
            "status": self.status,
            "thumbnail": self.thumbnail,
            "barcode_symbology": self.barcode_symbology,
            "code": self.code,
            "image": self.image,
            "quantity": self.quantity,
            "quantity_alert": self.quantity_alert,
            "tax_type": self.tax_type,
            "tax": self.tax,
            "discount_type": self.discount_type,
            "discount_value": self.discount_value,
            "file_path": self.file_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return variant_dict

    # ---------------------- READ: SINGLE (by _id + business) ---------------------- #
    @classmethod
    def get_by_id(cls, composite_variant_id, business_id):
        """
        Retrieve a composite variant by Mongo _id and business_id.
        """
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None  # Invalid business_id format

        try:
            variant_obj_id = ObjectId(composite_variant_id)
        except Exception:
            return None  # Invalid _id format

        data = super().get_by_id(variant_obj_id, business_id_obj)
        if not data:
            return None

        # Normalise IDs
        data["_id"] = str(data["_id"])
        if "business_id" in data:
            data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])

        # Decrypt fields
        data["values"] = decrypt_data(data["values"]) if data.get("values") else None
        data["status"] = decrypt_data(data["status"]) if data.get("status") else None
        data["thumbnail"] = decrypt_data(data["thumbnail"]) if data.get("thumbnail") else None
        data["barcode_symbology"] = decrypt_data(data["barcode_symbology"]) if data.get("barcode_symbology") else None
        data["code"] = decrypt_data(data["code"]) if data.get("code") else None
        data["image"] = decrypt_data(data["image"]) if data.get("image") else None
        data["quantity"] = decrypt_data(data["quantity"]) if data.get("quantity") else None
        data["quantity_alert"] = decrypt_data(data["quantity_alert"]) if data.get("quantity_alert") else None
        data["tax_type"] = decrypt_data(data["tax_type"]) if data.get("tax_type") else None
        data["tax"] = decrypt_data(data["tax"]) if data.get("tax") else None
        data["discount_type"] = decrypt_data(data["discount_type"]) if data.get("discount_type") else None
        data["discount_value"] = decrypt_data(data["discount_value"]) if data.get("discount_value") else None
        data["file_path"] = decrypt_data(data["file_path"]) if data.get("file_path") else None

        # Strip internal / sensitive fields
        data.pop("hashed_values", None)
        data.pop("admin_id", None)
        data.pop("agent_id", None)

        return data

    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve composite variants for a given user__id + business_id with pagination,
        using the BaseModel generic helper and then post-processing.

        Mirrors Brand.get_by_user__id_and_business_id format.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for variant in payload.get("items", []):
            # Normalise IDs
            if "_id" in variant:
                variant["_id"] = str(variant["_id"])
            if "user__id" in variant:
                variant["user__id"] = str(variant["user__id"])
            if "business_id" in variant:
                variant["business_id"] = str(variant["business_id"])

            # Decrypt fields
            variant["values"] = decrypt_data(variant["values"]) if variant.get("values") else None
            variant["status"] = decrypt_data(variant["status"]) if variant.get("status") else None
            variant["thumbnail"] = decrypt_data(variant["thumbnail"]) if variant.get("thumbnail") else None
            variant["barcode_symbology"] = decrypt_data(variant["barcode_symbology"]) if variant.get("barcode_symbology") else None
            variant["code"] = decrypt_data(variant["code"]) if variant.get("code") else None
            variant["image"] = decrypt_data(variant["image"]) if variant.get("image") else None
            variant["quantity"] = decrypt_data(variant["quantity"]) if variant.get("quantity") else None
            variant["quantity_alert"] = decrypt_data(variant["quantity_alert"]) if variant.get("quantity_alert") else None
            variant["tax_type"] = decrypt_data(variant["tax_type"]) if variant.get("tax_type") else None
            variant["tax"] = decrypt_data(variant["tax"]) if variant.get("tax") else None
            variant["discount_type"] = decrypt_data(variant["discount_type"]) if variant.get("discount_type") else None
            variant["discount_value"] = decrypt_data(variant["discount_value"]) if variant.get("discount_value") else None

            # Keep timestamps as-is
            variant["created_at"] = variant.get("created_at")
            variant["updated_at"] = variant.get("updated_at")

            # Remove internal / sensitive fields
            variant.pop("hashed_values", None)
            variant.pop("file_path", None)
            variant.pop("admin_id", None)
            variant.pop("agent_id", None)

            processed.append(variant)

        # Replace generic key with domain-specific one
        payload["composite_variants"] = processed
        payload.pop("items", None)

        return payload

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve all composite variants for a business_id with pagination,
        using the BaseModel generic helper and then post-processing.

        Mirrors Brand.get_by_business_id format.
        """
        payload = super().get_by_business_id(
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for variant in payload.get("items", []):
            # Normalise IDs
            if "_id" in variant:
                variant["_id"] = str(variant["_id"])
            if "business_id" in variant:
                variant["business_id"] = str(variant["business_id"])
            if "user__id" in variant:
                variant["user__id"] = str(variant["user__id"])

            # Decrypt fields
            variant["values"] = decrypt_data(variant["values"]) if variant.get("values") else None
            variant["status"] = decrypt_data(variant["status"]) if variant.get("status") else None
            variant["thumbnail"] = decrypt_data(variant["thumbnail"]) if variant.get("thumbnail") else None
            variant["barcode_symbology"] = decrypt_data(variant["barcode_symbology"]) if variant.get("barcode_symbology") else None
            variant["code"] = decrypt_data(variant["code"]) if variant.get("code") else None
            variant["image"] = decrypt_data(variant["image"]) if variant.get("image") else None
            variant["quantity"] = decrypt_data(variant["quantity"]) if variant.get("quantity") else None
            variant["quantity_alert"] = decrypt_data(variant["quantity_alert"]) if variant.get("quantity_alert") else None
            variant["tax_type"] = decrypt_data(variant["tax_type"]) if variant.get("tax_type") else None
            variant["tax"] = decrypt_data(variant["tax"]) if variant.get("tax") else None
            variant["discount_type"] = decrypt_data(variant["discount_type"]) if variant.get("discount_type") else None
            variant["discount_value"] = decrypt_data(variant["discount_value"]) if variant.get("discount_value") else None

            # Timestamps
            variant["created_at"] = variant.get("created_at")
            variant["updated_at"] = variant.get("updated_at")

            # Strip internal / sensitive
            variant.pop("hashed_values", None)
            variant.pop("file_path", None)
            variant.pop("admin_id", None)
            variant.pop("agent_id", None)

            processed.append(variant)

        payload["composite_variants"] = processed
        payload.pop("items", None)

        return payload
   
    # ---------------------- UPDATE ---------------------- #
    @classmethod
    def update(cls, composite_variant_id, **updates):
        """
        Update a composite variant's information by Mongo _id.
        """
        updates["updated_at"] = datetime.now()

        # Encrypt fields before updating
        if "values" in updates:
            updates["hashed_values"] = hash_data(updates["values"])
            updates["values"] = encrypt_data(updates["values"])
        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])
        if "image" in updates:
            updates["image"] = encrypt_data(updates["image"])
        if "thumbnail" in updates:
            updates["thumbnail"] = encrypt_data(updates["thumbnail"])
        if "barcode_symbology" in updates:
            updates["barcode_symbology"] = encrypt_data(updates["barcode_symbology"])
        if "code" in updates:
            updates["code"] = encrypt_data(updates["code"])
        if "quantity" in updates:
            updates["quantity"] = encrypt_data(updates["quantity"])
        if "quantity_alert" in updates:
            updates["quantity_alert"] = encrypt_data(updates["quantity_alert"])
        if "tax_type" in updates:
            updates["tax_type"] = encrypt_data(updates["tax_type"])
        if "tax" in updates:
            updates["tax"] = encrypt_data(updates["tax"])
        if "discount_type" in updates:
            updates["discount_type"] = encrypt_data(updates["discount_type"])
        if "discount_value" in updates:
            updates["discount_value"] = encrypt_data(updates["discount_value"])
        if "file_path" in updates:
            updates["file_path"] = encrypt_data(updates["file_path"])

        return super().update(composite_variant_id, **updates)

    # ---------------------- DELETE ---------------------- #
    @classmethod
    def delete(cls, composite_variant_id, business_id):
        """
        Delete a composite variant by Mongo _id and business_id.
        """
        try:
            composite_variant_obj_id = ObjectId(composite_variant_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(composite_variant_obj_id, business_id_obj)

# Gift Card
class GiftCard(BaseModel):
    """
    A GiftCard represents a digital or physical gift card that can be issued
    to a customer, with an associated value and validity period.
    """

    collection_name = "giftcards"

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        name,
        customer_id,
        issue_date,
        expiry_date,
        amount,
        reference=None,
        status="Active",
        created_at=None,
        updated_at=None,
    ):
        # Normalise customer_id to ObjectId (relational reference to Customer)
        customer_obj_id = ObjectId(customer_id) if isinstance(customer_id, str) else customer_id

        # Auto-generate reference if not provided
        reference = reference or generate_gift_card_code()

        super().__init__(
            business_id,
            user_id,
            user__id,
            name=name,
            customer_id=customer_obj_id,
            issue_date=issue_date,
            expiry_date=expiry_date,
            amount=amount,
            reference=reference,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
        )

        # Store relational id
        self.customer_id = customer_obj_id

        # Encrypt business fields
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)

        self.issue_date = encrypt_data(issue_date) if issue_date is not None else None
        self.expiry_date = encrypt_data(expiry_date) if expiry_date is not None else None
        self.amount = encrypt_data(amount) if amount is not None else None
        self.reference = encrypt_data(reference) if reference is not None else None
        self.status = encrypt_data(status) if status is not None else None

        # Timestamps
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        """
        Convert the gift card object to a dictionary representation.
        """
        gift_card_dict = super().to_dict()
        gift_card_dict.update({
            "name": self.name,
            "customer_id": self.customer_id,
            "issue_date": self.issue_date,
            "expiry_date": self.expiry_date,
            "amount": self.amount,
            "reference": self.reference,
            "status": self.status,
            "hashed_name": self.hashed_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return gift_card_dict

    # -------------------------------------------------
    # GET BY ID (business-scoped)
    # -------------------------------------------------
    @classmethod
    def get_by_id(cls, gift_card_id, business_id):
        """
        Retrieve a gift card by _id and business_id (business-scoped).
        """
        try:
            gift_card_id_obj = ObjectId(gift_card_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        data = super().get_by_id(gift_card_id_obj, business_id_obj)
        if not data:
            return None

        # Normalise IDs
        if "_id" in data:
            data["_id"] = str(data["_id"])
        if "business_id" in data:
            data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])
        if "user_id" in data and data["user_id"] is not None:
            data["user_id"] = str(data["user_id"])
        if "customer_id" in data and data["customer_id"] is not None:
            data["customer_id"] = str(data["customer_id"])

        # Decrypt fields
        data["name"] = decrypt_data(data["name"]) if data.get("name") else None
        data["issue_date"] = decrypt_data(data["issue_date"]) if data.get("issue_date") else None
        data["expiry_date"] = decrypt_data(data["expiry_date"]) if data.get("expiry_date") else None
        data["amount"] = decrypt_data(data["amount"]) if data.get("amount") else None
        data["reference"] = decrypt_data(data["reference"]) if data.get("reference") else None
        data["status"] = decrypt_data(data["status"]) if data.get("status") else None

        # Timestamps preserved
        data["created_at"] = data.get("created_at")
        data["updated_at"] = data.get("updated_at")

        # Remove internal fields
        data.pop("hashed_name", None)
        data.pop("agent_id", None)
        data.pop("admin_id", None)

        return data

    # -------------------------------------------------
    # GET BY BUSINESS ID (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve gift cards by business_id with pagination.
        """
        payload = super().get_by_business_id(business_id, page, per_page)
        processed = []

        for gc in payload.get("items", []):
            # Normalise IDs
            if "_id" in gc:
                gc["_id"] = str(gc["_id"])
            if "business_id" in gc:
                gc["business_id"] = str(gc["business_id"])
            if "user__id" in gc:
                gc["user__id"] = str(gc["user__id"])
            if "user_id" in gc and gc["user_id"] is not None:
                gc["user_id"] = str(gc["user_id"])
            if "customer_id" in gc and gc["customer_id"] is not None:
                gc["customer_id"] = str(gc["customer_id"])

            # Decrypt fields
            gc["name"] = decrypt_data(gc["name"]) if gc.get("name") else None
            gc["issue_date"] = decrypt_data(gc["issue_date"]) if gc.get("issue_date") else None
            gc["expiry_date"] = decrypt_data(gc["expiry_date"]) if gc.get("expiry_date") else None
            gc["amount"] = decrypt_data(gc["amount"]) if gc.get("amount") else None
            gc["reference"] = decrypt_data(gc["reference"]) if gc.get("reference") else None
            gc["status"] = decrypt_data(gc["status"]) if gc.get("status") else None

            # Timestamps
            gc["created_at"] = gc.get("created_at")
            gc["updated_at"] = gc.get("updated_at")

            # Remove internal fields
            gc.pop("hashed_name", None)
            gc.pop("agent_id", None)
            gc.pop("admin_id", None)

            processed.append(gc)

        payload["giftcards"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # GET BY USER + BUSINESS (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve gift cards by user__id and business_id with pagination.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for gc in payload.get("items", []):
            # Normalise IDs
            if "_id" in gc:
                gc["_id"] = str(gc["_id"])
            if "business_id" in gc:
                gc["business_id"] = str(gc["business_id"])
            if "user__id" in gc:
                gc["user__id"] = str(gc["user__id"])
            if "user_id" in gc and gc["user_id"] is not None:
                gc["user_id"] = str(gc["user_id"])
            if "customer_id" in gc and gc["customer_id"] is not None:
                gc["customer_id"] = str(gc["customer_id"])

            # Decrypt fields
            gc["name"] = decrypt_data(gc["name"]) if gc.get("name") else None
            gc["issue_date"] = decrypt_data(gc["issue_date"]) if gc.get("issue_date") else None
            gc["expiry_date"] = decrypt_data(gc["expiry_date"]) if gc.get("expiry_date") else None
            gc["amount"] = decrypt_data(gc["amount"]) if gc.get("amount") else None
            gc["reference"] = decrypt_data(gc["reference"]) if gc.get("reference") else None
            gc["status"] = decrypt_data(gc["status"]) if gc.get("status") else None

            # Timestamps
            gc["created_at"] = gc.get("created_at")
            gc["updated_at"] = gc.get("updated_at")

            # Remove internal fields
            gc.pop("hashed_name", None)
            gc.pop("agent_id", None)
            gc.pop("admin_id", None)

            processed.append(gc)

        payload["giftcards"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # UPDATE
    # -------------------------------------------------
    @classmethod
    def update(cls, gift_card_id, **updates):
        """
        Update a gift card's information by gift_card_id.
        """
        updates["updated_at"] = datetime.now()

        # Normalise relational id if present
        if "customer_id" in updates and isinstance(updates["customer_id"], str):
            updates["customer_id"] = ObjectId(updates["customer_id"])

        # Encrypt business fields if present
        if "name" in updates:
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])

        if "issue_date" in updates:
            updates["issue_date"] = encrypt_data(updates["issue_date"]) if updates["issue_date"] else None

        if "expiry_date" in updates:
            updates["expiry_date"] = encrypt_data(updates["expiry_date"]) if updates["expiry_date"] else None

        if "amount" in updates:
            updates["amount"] = encrypt_data(updates["amount"]) if updates["amount"] is not None else None

        if "reference" in updates:
            updates["reference"] = encrypt_data(updates["reference"]) if updates["reference"] else None

        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"]) if updates["status"] else None

        return super().update(gift_card_id, **updates)

    # -------------------------------------------------
    # DELETE (business-scoped)
    # -------------------------------------------------
    @classmethod
    def delete(cls, gift_card_id, business_id):
        """
        Delete a gift card by _id and business_id (business-scoped).
        """
        try:
            gift_card_id_obj = ObjectId(gift_card_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(gift_card_id_obj, business_id_obj)

# Outlets and Register
class Outlet(BaseModel):
    """
    An Outlet represents a physical store or location associated with a business.
    """

    collection_name = "outlets"  # Set the collection name

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        name,
        location,
        time_zone,
        registers=None,
        status="Active",
        created_at=None,
        updated_at=None,
    ):
        # Call BaseModel with raw values
        super().__init__(
            business_id,
            user_id,
            user__id,
            name=name,
            location=location,
            time_zone=time_zone,
            registers=registers,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
        )

        # ----------------- Encrypt scalar fields ----------------- #
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.time_zone = encrypt_data(time_zone) if time_zone is not None else None
        
        self.status = encrypt_data(status) if status is not None else None
        self.hashed_status = hash_data(status) if status is not None else None

        # ----------------- Encrypt nested `location` objects ----------------- #
        encrypted_locations = []
        for loc in (location or []):
            if not isinstance(loc, dict):
                continue
            enc_loc = {}
            for key, value in loc.items():
                enc_loc[key] = encrypt_data(value) if value is not None else None
            encrypted_locations.append(enc_loc)
        self.location = encrypted_locations

        # ----------------- Encrypt nested `registers` objects ----------------- #
        encrypted_registers = []
        for reg in (registers or []):
            if not isinstance(reg, dict):
                continue
            enc_reg = {}
            for key, value in reg.items():
                enc_reg[key] = encrypt_data(value) if value is not None else None
            encrypted_registers.append(enc_reg)
        self.registers = encrypted_registers

        # Timestamps
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

        # -------------------------------------------------
    # INTERNAL UTILITY: Unified post-process handler
    # -------------------------------------------------
    @classmethod
    def _post_process_payload(cls, payload):
        """
        Takes a payload in the form:
        {
            "items": [ {...}, {...}, ... ],
            "total": N,
            "page": X,
            "per_page": Y
        }

        And returns:
        {
            "outlets": [...processed...],
            "total": N,
            "page": X,
            "per_page": Y
        }
        """

        processed = []

        for o in payload.get("items", []) or []:

            # Normalise IDs
            if "_id" in o:
                o["_id"] = str(o["_id"])
            if "business_id" in o:
                o["business_id"] = str(o["business_id"])
            if "user__id" in o:
                o["user__id"] = str(o["user__id"])
            if "user_id" in o and o["user_id"] is not None:
                o["user_id"] = str(o["user_id"])

            # Decrypt scalar fields
            o["name"] = decrypt_data(o["name"]) if o.get("name") else None
            o["time_zone"] = decrypt_data(o["time_zone"]) if o.get("time_zone") else None
            o["status"] = decrypt_data(o["status"]) if o.get("status") else None

            # Decrypt nested `location`
            dec_locations = []
            for loc in o.get("location", []) or []:
                if isinstance(loc, dict):
                    dec = {k: decrypt_data(v) if v else None for k, v in loc.items()}
                    dec_locations.append(dec)
            o["location"] = dec_locations

            # Decrypt nested `registers`
            dec_registers = []
            for reg in o.get("registers", []) or []:
                if isinstance(reg, dict):
                    dec = {k: decrypt_data(v) if v else None for k, v in reg.items()}
                    dec_registers.append(dec)
            o["registers"] = dec_registers

            # Remove internal fields
            o.pop("hashed_status", None)
            o.pop("hashed_name", None)
            o.pop("agent_id", None)
            o.pop("admin_id", None)

            processed.append(o)

        # Replace items with outlets
        payload["outlets"] = processed
        payload.pop("items", None)
        return payload


    def to_dict(self):
        """
        Convert the outlet object to a dictionary representation.
        All stored values here are already encrypted.
        """
        outlet_dict = super().to_dict()
        outlet_dict.update({
            "location": self.location,
            "time_zone": self.time_zone,
            "registers": self.registers,
            "status": self.status,
            "hashed_name": self.hashed_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return outlet_dict

    @classmethod
    def count_active_by_business_id(cls, business_id):
        from bson import ObjectId
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return 0
        col = db.get_collection(cls.collection_name)
        return col.count_documents({
            "business_id": business_id_obj,
            "hashed_status": hash_data("Active"),
        })

    @classmethod
    def get_active_by_business_id(cls, business_id, limit=None, sort=None):
        """
        Get active outlets for a business (optionally limited / sorted).
        """
        from bson import ObjectId
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return {"outlets": []}

        col = db.get_collection(cls.collection_name)

        query = {
            "business_id": business_id_obj,
            "hashed_status": hash_data("Active"),
        }

        cursor = col.find(query)
        if sort:
            cursor = cursor.sort(sort)
        if limit:
            cursor = cursor.limit(limit)

        items = list(cursor)
        payload = {"items": items}
        # reuse your existing post-processing:
        # this will decrypt and normalise
        return cls._post_process_payload(payload)


    # -------------------------------------------------
    # GET BY ID (business-scoped)
    # -------------------------------------------------
    @classmethod
    def get_by_id(cls, outlet_id, business_id):
        """
        Retrieve an outlet by _id and business_id (business-scoped).
        Mirrors Customer.get_by_id / Sale.get_by_id style.
        """
        try:
            outlet_id_obj = ObjectId(outlet_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None  # Invalid id / business_id format

        # Use BaseModel.get_by_id (id, business_id)
        data = super().get_by_id(outlet_id_obj, business_id_obj)
        if not data:
            return None

        # Normalise IDs
        if "_id" in data:
            data["_id"] = str(data["_id"])
        if "business_id" in data:
            data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])
        if "user_id" in data and data["user_id"] is not None:
            data["user_id"] = str(data["user_id"])

        # Decrypt scalar fields
        data["name"] = decrypt_data(data["name"]) if data.get("name") else None
        data["time_zone"] = decrypt_data(data["time_zone"]) if data.get("time_zone") else None
        data["status"] = decrypt_data(data["status"]) if data.get("status") else None

        # Decrypt nested `location`
        decrypted_locations = []
        for loc in data.get("location", []) or []:
            if not isinstance(loc, dict):
                continue
            dec_loc = {}
            for key, value in loc.items():
                dec_loc[key] = decrypt_data(value) if value is not None else None
            decrypted_locations.append(dec_loc)
        data["location"] = decrypted_locations

        # Decrypt nested `registers`
        decrypted_registers = []
        for reg in data.get("registers", []) or []:
            if not isinstance(reg, dict):
                continue
            dec_reg = {}
            for key, value in reg.items():
                dec_reg[key] = decrypt_data(value) if value is not None else None
            decrypted_registers.append(dec_reg)
        data["registers"] = decrypted_registers

        # Timestamps kept as-is
        data["created_at"] = data.get("created_at")
        data["updated_at"] = data.get("updated_at")

        # Remove internal fields
        data.pop("hashed_name", None)
        data.pop("agent_id", None)
        data.pop("admin_id", None)

        return data

    # -------------------------------------------------
    # GET BY BUSINESS ID (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None, active_only=False):
        """
        Retrieve outlets by business_id with pagination,
        using BaseModel.get_by_business_id and then post-processing.
        Mirrors Customer.get_by_business_id behaviour.
        """
        payload = super().get_by_business_id(
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        # Optional filtering: only active outlets
        if active_only:
            hashed_active = hash_data("Active")
            payload["items"] = [
                o for o in payload.get("items", []) if o.get("status") == hashed_active
            ]

        return cls._post_process_payload(payload)
    
    
    # -------------------------------------------------
    # GET BY USER + BUSINESS (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None, active_only=False):
        """
        Retrieve outlets by user__id and business_id with pagination.
        Mirrors Customer.get_by_user__id_and_business_id.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        if active_only:
            hashed_active = hash_data("Active")
            payload["items"] = [
                o for o in payload.get("items", []) if o.get("status") == hashed_active
            ]

        return cls._post_process_payload(payload)

    # -------------------------------------------------
    # UPDATE
    # -------------------------------------------------
    @classmethod
    def update(cls, outlet_id, **updates):
        """
        Update an outlet's information by outlet_id.
        Encrypts the updated fields, including nested location/registers.
        """
        updates["updated_at"] = datetime.now()

        # Name
        if "name" in updates:
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])

        # Scalar fields
        if "time_zone" in updates:
            updates["time_zone"] = encrypt_data(updates["time_zone"]) if updates["time_zone"] is not None else None
        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"]) if updates["status"] is not None else None

        # Nested `location`
        if "location" in updates:
            encrypted_locations = []
            for loc in (updates["location"] or []):
                if not isinstance(loc, dict):
                    continue
                enc_loc = {}
                for key, value in loc.items():
                    enc_loc[key] = encrypt_data(value) if value is not None else None
                encrypted_locations.append(enc_loc)
            updates["location"] = encrypted_locations

        # Nested `registers`
        if "registers" in updates:
            encrypted_registers = []
            for reg in (updates["registers"] or []):
                if not isinstance(reg, dict):
                    continue
                enc_reg = {}
                for key, value in reg.items():
                    enc_reg[key] = encrypt_data(value) if value is not None else None
                encrypted_registers.append(enc_reg)
            updates["registers"] = encrypted_registers

        return super().update(outlet_id, **updates)

    # -------------------------------------------------
    # DELETE (business-scoped)
    # -------------------------------------------------
    @classmethod
    def delete(cls, outlet_id, business_id):
        """
        Delete an outlet by _id and business_id (business-scoped).
        Mirrors Customer.delete / Sale.delete.
        """
        try:
            outlet_id_obj = ObjectId(outlet_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(outlet_id_obj, business_id_obj)

    # -------------------------------------------------
    # UNIQUE INDEXES (real duplicate protection)
    # -------------------------------------------------
    @classmethod
    def create_indexes(cls):
        """
        Ensure unique index on (business_id, hashed_name) so outlet names are
        unique per business at the DB level (prevents race-condition duplicates).
        """
        col = db.get_collection(cls.collection_name)

        col.create_index(
            [("business_id", ASCENDING), ("hashed_name", ASCENDING)],
            unique=True,
            sparse=True,
            name="uniq_business_outlet_name",
        )

    # -------------------------------------------------
    # COUNT BY BUSINESS (for multi_outlet logic)
    # -------------------------------------------------
    @classmethod
    def count_by_business_id(cls, business_id):
        """
        Count outlets for a given business_id.
        Useful for rules like:
          - first outlet free
          - require multi_outlet feature after 1, etc.
        """
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return 0

        col = db.get_collection(cls.collection_name)
        return col.count_documents({"business_id": business_id_obj})


# Business Location
class BusinessLocation(BaseModel):
    """
    A BusinessLocation represents a location where a business operates, including details such as 
    the location name, address, contact information, invoice schemes, and payment options.
    """

    collection_name = "business_locations"  # Set the collection name for business locations

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        location_id=None,
        name="",
        city="",
        state="",
        phone=None,
        email="",
        landmark="",
        invoice_scheme_for_pos="",
        invoice_layout_for_pos="",
        default_selling_price_group=None,
        post_code="",
        country="",
        alternate_contact_number=None,
        website=None,
        invoice_scheme_for_sale="",
        invoice_layout_for_sale="",
        pos_screen_featured_products=None,
        payment_options=None,
        status="Active",
        created_at=None,
        updated_at=None,
    ):
        # Call BaseModel with raw values
        super().__init__(
            business_id,
            user_id,
            user__id,
            location_id=location_id,
            name=name,
            city=city,
            state=state,
            phone=phone,
            email=email,
            landmark=landmark,
            invoice_scheme_for_pos=invoice_scheme_for_pos,
            invoice_layout_for_pos=invoice_layout_for_pos,
            default_selling_price_group=default_selling_price_group,
            post_code=post_code,
            country=country,
            alternate_contact_number=alternate_contact_number,
            website=website,
            invoice_scheme_for_sale=invoice_scheme_for_sale,
            invoice_layout_for_sale=invoice_layout_for_sale,
            pos_screen_featured_products=pos_screen_featured_products,
            payment_options=payment_options,
            status=status,
            created_at=created_at,
            updated_at=updated_at,
        )

        self.user_id = user_id
        self.user__id = user__id

        # Encrypt scalar fields
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.city = encrypt_data(city)
        self.state = encrypt_data(state)
        self.phone = encrypt_data(phone) if phone else None
        self.email = encrypt_data(email)
        self.landmark = encrypt_data(landmark)
        self.invoice_scheme_for_pos = encrypt_data(invoice_scheme_for_pos)
        self.invoice_layout_for_pos = encrypt_data(invoice_layout_for_pos)
        self.default_selling_price_group = (
            encrypt_data(default_selling_price_group) if default_selling_price_group else None
        )
        self.post_code = encrypt_data(post_code)
        self.country = encrypt_data(country)
        self.alternate_contact_number = (
            encrypt_data(alternate_contact_number) if alternate_contact_number else None
        )
        self.website = encrypt_data(website) if website else None
        self.invoice_scheme_for_sale = encrypt_data(invoice_scheme_for_sale)
        self.invoice_layout_for_sale = encrypt_data(invoice_layout_for_sale)

        # Keep pos_screen_featured_products as-is (if you later want, you can encrypt similarly)
        self.pos_screen_featured_products = pos_screen_featured_products or []

        # Encrypt payment options if provided (assumed list of strings)
        encrypted_payment_options = []
        for po in (payment_options or []):
            encrypted_payment_options.append(encrypt_data(po) if po is not None else None)
        self.payment_options = encrypted_payment_options

        # Status
        self.status = encrypt_data(status) if status is not None else None

        # Timestamps
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        """
        Convert the BusinessLocation object to a dictionary representation.
        All stored values here are already encrypted.
        """
        location_dict = super().to_dict()
        location_dict.update({
            "location_id": self.location_id,
            "name": self.name,
            "city": self.city,
            "state": self.state,
            "phone": self.phone,
            "email": self.email,
            "landmark": self.landmark,
            "invoice_scheme_for_pos": self.invoice_scheme_for_pos,
            "invoice_layout_for_pos": self.invoice_layout_for_pos,
            "default_selling_price_group": self.default_selling_price_group,
            "post_code": self.post_code,
            "country": self.country,
            "alternate_contact_number": self.alternate_contact_number,
            "website": self.website,
            "invoice_scheme_for_sale": self.invoice_scheme_for_sale,
            "invoice_layout_for_sale": self.invoice_layout_for_sale,
            "pos_screen_featured_products": self.pos_screen_featured_products,
            "payment_options": self.payment_options,
            "status": self.status,
            "hashed_name": self.hashed_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return location_dict

    # -------------------------------------------------
    # GET BY ID (business-scoped)
    # -------------------------------------------------
    @classmethod
    def get_by_id(cls, location_id, business_id):
        """
        Retrieve a business location by _id and business_id (business-scoped).
        Mirrors Outlet.get_by_id / Customer.get_by_id style.
        """
        try:
            location_id_obj = ObjectId(location_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None  # Invalid id / business_id format

        # Use BaseModel.get_by_id (id, business_id)
        data = super().get_by_id(location_id_obj, business_id_obj)
        if not data:
            return None

        # Normalise IDs
        if "_id" in data:
            data["_id"] = str(data["_id"])
        if "business_id" in data:
            data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])
        if "user_id" in data and data["user_id"] is not None:
            data["user_id"] = str(data["user_id"])

        # Decrypt scalar fields
        data["name"] = decrypt_data(data["name"]) if data.get("name") else None
        data["city"] = decrypt_data(data["city"]) if data.get("city") else None
        data["state"] = decrypt_data(data["state"]) if data.get("state") else None
        data["phone"] = decrypt_data(data["phone"]) if data.get("phone") else None
        data["email"] = decrypt_data(data["email"]) if data.get("email") else None
        data["landmark"] = decrypt_data(data["landmark"]) if data.get("landmark") else None
        data["invoice_scheme_for_pos"] = (
            decrypt_data(data["invoice_scheme_for_pos"])
            if data.get("invoice_scheme_for_pos") else None
        )
        data["invoice_layout_for_pos"] = (
            decrypt_data(data["invoice_layout_for_pos"])
            if data.get("invoice_layout_for_pos") else None
        )
        data["default_selling_price_group"] = (
            decrypt_data(data["default_selling_price_group"])
            if data.get("default_selling_price_group") else None
        )
        data["post_code"] = decrypt_data(data["post_code"]) if data.get("post_code") else None
        data["country"] = decrypt_data(data["country"]) if data.get("country") else None
        data["alternate_contact_number"] = (
            decrypt_data(data["alternate_contact_number"])
            if data.get("alternate_contact_number") else None
        )
        data["website"] = decrypt_data(data["website"]) if data.get("website") else None
        data["invoice_scheme_for_sale"] = (
            decrypt_data(data["invoice_scheme_for_sale"])
            if data.get("invoice_scheme_for_sale") else None
        )
        data["invoice_layout_for_sale"] = (
            decrypt_data(data["invoice_layout_for_sale"])
            if data.get("invoice_layout_for_sale") else None
        )

        # pos_screen_featured_products kept as stored (no encryption)
        # Decrypt payment_options
        decrypted_payment_options = []
        for po in data.get("payment_options", []) or []:
            decrypted_payment_options.append(decrypt_data(po) if po is not None else None)
        data["payment_options"] = decrypted_payment_options

        data["status"] = decrypt_data(data["status"]) if data.get("status") else None

        # Timestamps kept as-is
        data["created_at"] = data.get("created_at")
        data["updated_at"] = data.get("updated_at")

        # Remove internal fields
        data.pop("hashed_name", None)
        data.pop("agent_id", None)
        data.pop("admin_id", None)

        return data

    # -------------------------------------------------
    # GET BY BUSINESS ID (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve business locations by business_id with pagination,
        using BaseModel.get_by_business_id and then post-processing.
        Mirrors Customer.get_by_business_id / Outlet.get_by_business_id behaviour.
        Expected BaseModel payload structure:
            {
                "items": [...],
                "total_count": int,
                "total_pages": int,
                "current_page": int,
                "per_page": int,
            }
        """
        payload = super().get_by_business_id(
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for loc in payload.get("items", []):
            # Normalise IDs
            if "_id" in loc:
                loc["_id"] = str(loc["_id"])
            if "business_id" in loc:
                loc["business_id"] = str(loc["business_id"])
            if "user__id" in loc:
                loc["user__id"] = str(loc["user__id"])
            if "user_id" in loc and loc["user_id"] is not None:
                loc["user_id"] = str(loc["user_id"])

            # Decrypt scalar fields
            loc["name"] = decrypt_data(loc["name"]) if loc.get("name") else None
            loc["city"] = decrypt_data(loc["city"]) if loc.get("city") else None
            loc["state"] = decrypt_data(loc["state"]) if loc.get("state") else None
            loc["phone"] = decrypt_data(loc["phone"]) if loc.get("phone") else None
            loc["email"] = decrypt_data(loc["email"]) if loc.get("email") else None
            loc["landmark"] = decrypt_data(loc["landmark"]) if loc.get("landmark") else None
            loc["invoice_scheme_for_pos"] = (
                decrypt_data(loc["invoice_scheme_for_pos"])
                if loc.get("invoice_scheme_for_pos") else None
            )
            loc["invoice_layout_for_pos"] = (
                decrypt_data(loc["invoice_layout_for_pos"])
                if loc.get("invoice_layout_for_pos") else None
            )
            loc["default_selling_price_group"] = (
                decrypt_data(loc["default_selling_price_group"])
                if loc.get("default_selling_price_group") else None
            )
            loc["post_code"] = decrypt_data(loc["post_code"]) if loc.get("post_code") else None
            loc["country"] = decrypt_data(loc["country"]) if loc.get("country") else None
            loc["alternate_contact_number"] = (
                decrypt_data(loc["alternate_contact_number"])
                if loc.get("alternate_contact_number") else None
            )
            loc["website"] = decrypt_data(loc["website"]) if loc.get("website") else None
            loc["invoice_scheme_for_sale"] = (
                decrypt_data(loc["invoice_scheme_for_sale"])
                if loc.get("invoice_scheme_for_sale") else None
            )
            loc["invoice_layout_for_sale"] = (
                decrypt_data(loc["invoice_layout_for_sale"])
                if loc.get("invoice_layout_for_sale") else None
            )

            # pos_screen_featured_products kept as stored
            # Decrypt payment_options
            decrypted_payment_options = []
            for po in loc.get("payment_options", []) or []:
                decrypted_payment_options.append(decrypt_data(po) if po is not None else None)
            loc["payment_options"] = decrypted_payment_options

            loc["status"] = decrypt_data(loc["status"]) if loc.get("status") else None

            # Timestamps
            loc["created_at"] = loc.get("created_at")
            loc["updated_at"] = loc.get("updated_at")

            # Remove internal fields
            loc.pop("hashed_name", None)
            loc.pop("agent_id", None)
            loc.pop("admin_id", None)

            processed.append(loc)

        payload["locations"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # GET BY USER + BUSINESS (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve business locations by user__id and business_id with pagination.
        Mirrors Customer.get_by_user__id_and_business_id / Outlet.get_by_user__id_and_business_id.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for loc in payload.get("items", []):
            # Normalise IDs
            if "_id" in loc:
                loc["_id"] = str(loc["_id"])
            if "business_id" in loc:
                loc["business_id"] = str(loc["business_id"])
            if "user__id" in loc:
                loc["user__id"] = str(loc["user__id"])
            if "user_id" in loc and loc["user_id"] is not None:
                loc["user_id"] = str(loc["user_id"])

            # Decrypt scalar fields
            loc["name"] = decrypt_data(loc["name"]) if loc.get("name") else None
            loc["city"] = decrypt_data(loc["city"]) if loc.get("city") else None
            loc["state"] = decrypt_data(loc["state"]) if loc.get("state") else None
            loc["phone"] = decrypt_data(loc["phone"]) if loc.get("phone") else None
            loc["email"] = decrypt_data(loc["email"]) if loc.get("email") else None
            loc["landmark"] = decrypt_data(loc["landmark"]) if loc.get("landmark") else None
            loc["invoice_scheme_for_pos"] = (
                decrypt_data(loc["invoice_scheme_for_pos"])
                if loc.get("invoice_scheme_for_pos") else None
            )
            loc["invoice_layout_for_pos"] = (
                decrypt_data(loc["invoice_layout_for_pos"])
                if loc.get("invoice_layout_for_pos") else None
            )
            loc["default_selling_price_group"] = (
                decrypt_data(loc["default_selling_price_group"])
                if loc.get("default_selling_price_group") else None
            )
            loc["post_code"] = decrypt_data(loc["post_code"]) if loc.get("post_code") else None
            loc["country"] = decrypt_data(loc["country"]) if loc.get("country") else None
            loc["alternate_contact_number"] = (
                decrypt_data(loc["alternate_contact_number"])
                if loc.get("alternate_contact_number") else None
            )
            loc["website"] = decrypt_data(loc["website"]) if loc.get("website") else None
            loc["invoice_scheme_for_sale"] = (
                decrypt_data(loc["invoice_scheme_for_sale"])
                if loc.get("invoice_scheme_for_sale") else None
            )
            loc["invoice_layout_for_sale"] = (
                decrypt_data(loc["invoice_layout_for_sale"])
                if loc.get("invoice_layout_for_sale") else None
            )

            # pos_screen_featured_products kept as stored
            # Decrypt payment_options
            decrypted_payment_options = []
            for po in loc.get("payment_options", []) or []:
                decrypted_payment_options.append(decrypt_data(po) if po is not None else None)
            loc["payment_options"] = decrypted_payment_options

            loc["status"] = decrypt_data(loc["status"]) if loc.get("status") else None

            # Remove internal fields
            loc.pop("hashed_name", None)
            loc.pop("agent_id", None)
            loc.pop("admin_id", None)

            processed.append(loc)

        payload["locations"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # UPDATE
    # -------------------------------------------------
    @classmethod
    def update(cls, location_id, **updates):
        """
        Update a business location's information by location_id.
        Encrypts the updated fields.
        """
        updates["updated_at"] = datetime.now()

        if "name" in updates:
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])
        if "city" in updates:
            updates["city"] = encrypt_data(updates["city"])
        if "state" in updates:
            updates["state"] = encrypt_data(updates["state"])
        if "phone" in updates:
            updates["phone"] = encrypt_data(updates["phone"]) if updates["phone"] else None
        if "email" in updates:
            updates["email"] = encrypt_data(updates["email"])
        if "landmark" in updates:
            updates["landmark"] = encrypt_data(updates["landmark"])
        if "invoice_scheme_for_pos" in updates:
            updates["invoice_scheme_for_pos"] = encrypt_data(updates["invoice_scheme_for_pos"])
        if "invoice_layout_for_pos" in updates:
            updates["invoice_layout_for_pos"] = encrypt_data(updates["invoice_layout_for_pos"])
        if "default_selling_price_group" in updates:
            updates["default_selling_price_group"] = (
                encrypt_data(updates["default_selling_price_group"])
                if updates["default_selling_price_group"] else None
            )
        if "post_code" in updates:
            updates["post_code"] = encrypt_data(updates["post_code"])
        if "country" in updates:
            updates["country"] = encrypt_data(updates["country"])
        if "alternate_contact_number" in updates:
            updates["alternate_contact_number"] = (
                encrypt_data(updates["alternate_contact_number"])
                if updates["alternate_contact_number"] else None
            )
        if "website" in updates:
            updates["website"] = (
                encrypt_data(updates["website"]) if updates["website"] else None
            )
        if "invoice_scheme_for_sale" in updates:
            updates["invoice_scheme_for_sale"] = encrypt_data(updates["invoice_scheme_for_sale"])
        if "invoice_layout_for_sale" in updates:
            updates["invoice_layout_for_sale"] = encrypt_data(updates["invoice_layout_for_sale"])

        # pos_screen_featured_products left as plain
        if "payment_options" in updates:
            enc_pos = []
            for po in (updates["payment_options"] or []):
                enc_pos.append(encrypt_data(po) if po is not None else None)
            updates["payment_options"] = enc_pos

        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"]) if updates["status"] is not None else None

        return super().update(location_id, **updates)

    # -------------------------------------------------
    # DELETE (business-scoped)
    # -------------------------------------------------
    @classmethod
    def delete(cls, location_id, business_id):
        """
        Delete a business location by _id and business_id (business-scoped).
        Mirrors Outlet.delete / Customer.delete.
        """
        try:
            location_id_obj = ObjectId(location_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(location_id_obj, business_id_obj)