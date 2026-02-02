import uuid
import bcrypt
import json

from bson.objectid import ObjectId
from datetime import datetime
from ...extensions.db import db
from ...utils.logger import Log
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ..base_model import BaseModel
from ..user_model import User
from ...utils.generators import generate_coupons
from ...constants.service_code import (
    HTTP_STATUS_CODES, PERMISSION_FIELDS_FOR_ADMINS,
    PERMISSION_FIELDS_FOR_ADMIN_ROLE
)

def _zero_permission_for(field: str) -> list:
    """
    Build a zero-permission entry for a permission field based on
    PERMISSION_FIELDS_FOR_ADMIN_ROLE[field] actions.
    """
    actions = PERMISSION_FIELDS_FOR_ADMIN_ROLE.get(field, [])
    if not actions:
        # safe fallback if someone forgot to register actions for a field
        return [{"read": "0"}]
    return [{a: "0" for a in actions}]


class Role(BaseModel):
    collection_name = "roles"

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        name,
        email,
        admin_id=None,
        status="Active",
        created_by=None,
        created_at=None,
        updated_at=None,
        **kwargs,
    ):
        """
        Role model with encrypted core fields and optional permission fields.

        ✅ Only permission fields explicitly provided in kwargs (matching
        PERMISSION_FIELDS_FOR_ADMINS) are stored.

        Why:
          - Avoid storing huge permission payloads full of zeros in Mongo.
          - You return "zero permissions" dynamically at read time for fields not stored.
        """
        # Normalise admin_id / created_by to ObjectId where present
        admin_id_obj = ObjectId(admin_id) if admin_id else None
        created_by_obj = ObjectId(created_by) if created_by else None

        # Call BaseModel with raw fields
        super().__init__(
            business_id,
            user_id,
            user__id,
            name=name,
            email=email,
            admin_id=admin_id_obj,
            status=status,
            created_by=created_by_obj,
            created_at=created_at,
            updated_at=updated_at,
        )

        # ----------------- Encrypt scalar fields ----------------- #
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)

        self.email = encrypt_data(email)
        self.hashed_email = hash_data(email)

        self.status = encrypt_data(status) if status is not None else None

        # ----------------- Permission fields ----------------- #
        # Only store permission fields that are explicitly given in kwargs.
        # (We do NOT store ZERO_PERMISSION defaults here; they are used only at read time.)
        for field in PERMISSION_FIELDS_FOR_ADMINS:
            if field in kwargs and kwargs[field] is not None:
                perm_list = kwargs[field] or []
                encrypted_list = [
                    {k: encrypt_data(v) for k, v in item.items()}
                    for item in perm_list
                ]
                setattr(self, field, encrypted_list)

        self.admin_id = admin_id_obj
        self.created_by = created_by_obj
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        """
        Convert the Role object to a dictionary representation (encrypted fields).
        Only includes permission fields that exist on the instance.
        """
        role_dict = super().to_dict()
        role_dict.update(
            {
                "name": self.name,
                "email": self.email,
                "status": self.status,
                "hashed_name": self.hashed_name,
                "hashed_email": self.hashed_email,
                "admin_id": self.admin_id,
                "created_by": self.created_by,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
        )

        # Only include permission fields that are actually set on this instance
        for field in PERMISSION_FIELDS_FOR_ADMINS:
            if hasattr(self, field):
                role_dict[field] = getattr(self, field)

        return role_dict

    # -------------------------------------------------
    # GET BY ID (business-scoped)
    # -------------------------------------------------
    @classmethod
    def get_by_id(cls, role_id, business_id, is_logging_in=None):
        """
        Retrieve a role by _id and business_id (business-scoped),
        decrypting fields and expanding permissions.

        NOTE:
          - If a permission field was NOT stored in Mongo, we return
            a "zero permission" structure based on PERMISSION_FIELDS_FOR_ADMIN_ROLE.
        """
        try:
            role_id_obj = ObjectId(role_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        data = super().get_by_id(role_id_obj, business_id_obj, is_logging_in)
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
        if "admin_id" in data and data["admin_id"] is not None:
            data["admin_id"] = str(data["admin_id"])
        if "created_by" in data and data["created_by"] is not None:
            data["created_by"] = str(data["created_by"])

        # Decrypt scalar fields
        name = decrypt_data(data["name"]) if data.get("name") else None
        email = decrypt_data(data["email"]) if data.get("email") else None
        status = decrypt_data(data["status"]) if data.get("status") else None

        # Permissions (dynamic ZERO permissions)
        permissions = {}
        for field in PERMISSION_FIELDS_FOR_ADMINS:
            encrypted_permissions = data.get(field)
            if encrypted_permissions:
                permissions[field] = [
                    {k: decrypt_data(v) for k, v in item.items()}
                    for item in encrypted_permissions
                ]
            else:
                permissions[field] = _zero_permission_for(field)

        # Clean up internal fields
        data.pop("hashed_name", None)
        data.pop("hashed_email", None)
        data.pop("agent_id", None)

        return {
            "role_id": data["_id"],
            "business_id": data["business_id"],
            "name": name,
            "email": email,
            "status": status,
            "permissions": permissions,
            "admin_id": data.get("admin_id"),
            "created_by": data.get("created_by"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    # -------------------------------------------------
    # GET BY BUSINESS ID (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve roles for a business (paginated), decrypting fields and expanding permissions.
        Only roles with created_by present are included.
        """
        payload = super().get_by_business_id(business_id, page, per_page)
        processed = []

        for r in payload.get("items", []):
            # Require created_by to be present (keeps "real roles")
            created_by_val = r.get("created_by")
            if created_by_val is None:
                continue

            # Normalise IDs
            if "_id" in r:
                r["_id"] = str(r["_id"])
            if "business_id" in r:
                r["business_id"] = str(r["business_id"])
            if "user__id" in r:
                r["user__id"] = str(r["user__id"])
            if "user_id" in r and r["user_id"] is not None:
                r["user_id"] = str(r["user_id"])
            if "admin_id" in r and r["admin_id"] is not None:
                r["admin_id"] = str(r["admin_id"])
            if "created_by" in r and r["created_by"] is not None:
                r["created_by"] = str(r["created_by"])

            # Decrypt scalar fields
            name = decrypt_data(r["name"]) if r.get("name") else None
            email = decrypt_data(r["email"]) if r.get("email") else None
            status = decrypt_data(r["status"]) if r.get("status") else None

            # Permissions
            permissions = {}
            for field in PERMISSION_FIELDS_FOR_ADMINS:
                encrypted_permissions = r.get(field)
                if encrypted_permissions:
                    permissions[field] = [
                        {k: decrypt_data(v) for k, v in item.items()}
                        for item in encrypted_permissions
                    ]
                else:
                    permissions[field] = _zero_permission_for(field)

            processed.append(
                {
                    "role_id": r["_id"],
                    "business_id": r["business_id"],
                    "name": name,
                    "email": email,
                    "status": status,
                    "permissions": permissions,
                    "admin_id": r.get("admin_id"),
                    "created_by": r.get("created_by"),
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at"),
                }
            )

        payload["roles"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # GET BY USER + BUSINESS (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve roles created by a specific user within a business (paginated).
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for r in payload.get("items", []):
            # Normalise IDs
            if "_id" in r:
                r["_id"] = str(r["_id"])
            if "business_id" in r:
                r["business_id"] = str(r["business_id"])
            if "user__id" in r:
                r["user__id"] = str(r["user__id"])
            if "user_id" in r and r["user_id"] is not None:
                r["user_id"] = str(r["user_id"])
            if "admin_id" in r and r["admin_id"] is not None:
                r["admin_id"] = str(r["admin_id"])
            if "created_by" in r and r["created_by"] is not None:
                r["created_by"] = str(r["created_by"])

            # Decrypt scalar fields
            name = decrypt_data(r["name"]) if r.get("name") else None
            email = decrypt_data(r["email"]) if r.get("email") else None
            status = decrypt_data(r["status"]) if r.get("status") else None

            # Permissions
            permissions = {}
            for field in PERMISSION_FIELDS_FOR_ADMINS:
                encrypted_permissions = r.get(field)
                if encrypted_permissions:
                    permissions[field] = [
                        {k: decrypt_data(v) for k, v in item.items()}
                        for item in encrypted_permissions
                    ]
                else:
                    permissions[field] = _zero_permission_for(field)

            processed.append(
                {
                    "role_id": r["_id"],
                    "business_id": r["business_id"],
                    "name": name,
                    "email": email,
                    "status": status,
                    "permissions": permissions,
                    "admin_id": r.get("admin_id"),
                    "created_by": r.get("created_by"),
                    "created_at": r.get("created_at"),
                    "updated_at": r.get("updated_at"),
                }
            )

        payload["roles"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # EXISTING CHECK METHODS
    # -------------------------------------------------
    @classmethod
    def check_item_exists(cls, admin_id, key, value):
        try:
            if not cls.check_permission(cls, "add"):
                raise PermissionError(
                    f"User does not have permission to view {cls.__name__}."
                )

            hashed_key = hash_data(value)
            query = {
                "admin_id": ObjectId(admin_id),
                f"hashed_{key}": hashed_key,
            }
            collection = db.get_collection(cls.collection_name)
            existing_item = collection.find_one(query)
            return bool(existing_item)
        except Exception as e:
            Log.info(f"[Role.check_item_exists] error: {e}")
            return False

    @classmethod
    def check_role_exists(cls, admin_id, name_key, name_value, email_key, email_value):
        try:
            hashed_name_key = hash_data(name_value)
            hashed_email_key = hash_data(email_value)

            query = {
                "admin_id": ObjectId(admin_id),
                f"hashed_{name_key}": hashed_name_key,
                f"hashed_{email_key}": hashed_email_key,
            }

            collection = db.get_collection(cls.collection_name)
            existing_item = collection.find_one(query)
            return bool(existing_item)

        except Exception as e:
            Log.info(f"[Role.check_role_exists] error: {e}")
            return False

    # -------------------------------------------------
    # UPDATE
    # -------------------------------------------------
    @classmethod
    def update(cls, role_id, **updates):
        """
        Update a role by role_id, re-encrypting changed fields and
        updating hashes + permissions.
        """
        updates["updated_at"] = datetime.now()

        if "name" in updates:
            name_plain = updates["name"]
            updates["name"] = encrypt_data(name_plain)
            updates["hashed_name"] = hash_data(name_plain)

        if "email" in updates:
            email_plain = updates["email"]
            updates["email"] = encrypt_data(email_plain)
            updates["hashed_email"] = hash_data(email_plain)

        if "status" in updates:
            updates["status"] = (
                encrypt_data(updates["status"]) if updates["status"] is not None else None
            )

        # Permission fields – only re-encrypt if present in update payload
        for key in PERMISSION_FIELDS_FOR_ADMINS:
            if key in updates:
                perm_list = updates[key] or []
                if perm_list:
                    updates[key] = [
                        {k: encrypt_data(v) for k, v in item.items()}
                        for item in perm_list
                    ]
                else:
                    # If explicitly passed as empty list, store None to "clear" it
                    updates[key] = None

        Log.info(f"[Role.update] updates: {updates}")

        return super().update(role_id, **updates)

    # -------------------------------------------------
    # DELETE (business-scoped)
    # -------------------------------------------------
    @classmethod
    def delete(cls, role_id, business_id):
        """
        Delete a role by _id and business_id (business-scoped).
        """
        try:
            role_id_obj = ObjectId(role_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(role_id_obj, business_id_obj)

#-------------------------EXPENSE MODEL--------------------------------------
class Expense(BaseModel):
    """
    An Expense represents an expense transaction in a business, including details such as the name, description,
    category, date, amount, and status.
    """

    collection_name = "expenses"

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        name,
        description,
        date,
        category=None,
        amount=0.0,
        status="Active",
    ):
        super().__init__(
            business_id,
            user_id,
            user__id,
            name=name,
            description=description,
            category=category,
            date=date,
            amount=amount,
            status=status,
        )

        # Core encrypted + hashed name
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)

        # Other encrypted fields
        self.description = encrypt_data(description)
        self.category = encrypt_data(category) if category else None
        self.date = encrypt_data(date)
        self.amount = encrypt_data(amount)
        self.status = encrypt_data(status)

        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the expense object to a dictionary representation.
        """
        expense_dict = super().to_dict()
        expense_dict.update({
            "description": self.description,
            "category": self.category,
            "date": self.date,
            "amount": self.amount,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return expense_dict

    # ------------------------------------------------------------------
    # QUERIES
    # ------------------------------------------------------------------

    @classmethod
    def get_by_id(cls, expense_id, business_id):
        """
        Retrieve an expense by _id and business_id.
        """
        try:
            expense_id_obj = ObjectId(expense_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        data = super().get_by_id(expense_id_obj, business_id_obj)

        if not data:
            return None

        # Normalise IDs
        data["_id"] = str(data["_id"])
        if "business_id" in data:
            data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])

        # Decrypt business fields
        data["name"] = decrypt_data(data["name"]) if data.get("name") else None
        data["description"] = decrypt_data(data["description"]) if data.get("description") else None
        data["category"] = decrypt_data(data["category"]) if data.get("category") else None
        data["date"] = decrypt_data(data["date"]) if data.get("date") else None
        data["amount"] = decrypt_data(data["amount"]) if data.get("amount") else None
        data["status"] = decrypt_data(data["status"]) if data.get("status") else None

        # Timestamps are left as stored (datetime or ISO)
        data["created_at"] = data.get("created_at")
        data["updated_at"] = data.get("updated_at")

        # Remove internal / sensitive fields
        data.pop("hashed_name", None)
        data.pop("agent_id", None)
        data.pop("admin_id", None)

        return data

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve expenses by business_id with pagination and decrypted fields.
        Uses BaseModel.get_by_business_id(...) and post-processes the docs.
        """
        payload = super().get_by_business_id(
            business_id=business_id,
            page=page,
            per_page=per_page,
        )
        processed = []

        for expense in payload.get("items", []):
            # Normalise IDs
            if "_id" in expense:
                expense["_id"] = str(expense["_id"])
            if "business_id" in expense:
                expense["business_id"] = str(expense["business_id"])
            if "user__id" in expense:
                expense["user__id"] = str(expense["user__id"])

            # Decrypt fields
            expense["name"] = decrypt_data(expense["name"]) if expense.get("name") else None
            expense["description"] = decrypt_data(expense["description"]) if expense.get("description") else None
            expense["category"] = decrypt_data(expense["category"]) if expense.get("category") else None
            expense["date"] = decrypt_data(expense["date"]) if expense.get("date") else None
            expense["amount"] = decrypt_data(expense["amount"]) if expense.get("amount") else None
            expense["status"] = decrypt_data(expense["status"]) if expense.get("status") else None

            # Timestamps
            expense["created_at"] = expense.get("created_at")
            expense["updated_at"] = expense.get("updated_at")

            # Remove internal / sensitive fields
            expense.pop("hashed_name", None)
            expense.pop("agent_id", None)
            expense.pop("admin_id", None)

            processed.append(expense)

        # Replace generic key with domain-specific one
        payload["expenses"] = processed
        payload.pop("items", None)

        return payload

    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve expenses by user__id and business_id with pagination and decrypted fields.
        Uses BaseModel.get_all_by_user__id_and_business_id(...) and post-processes the docs.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )
        processed = []

        for expense in payload.get("items", []):
            # Normalise IDs
            if "_id" in expense:
                expense["_id"] = str(expense["_id"])
            if "user__id" in expense:
                expense["user__id"] = str(expense["user__id"])
            if "business_id" in expense:
                expense["business_id"] = str(expense["business_id"])

            # Decrypt fields
            expense["name"] = decrypt_data(expense["name"]) if expense.get("name") else None
            expense["description"] = decrypt_data(expense["description"]) if expense.get("description") else None
            expense["category"] = decrypt_data(expense["category"]) if expense.get("category") else None
            expense["date"] = decrypt_data(expense["date"]) if expense.get("date") else None
            expense["amount"] = decrypt_data(expense["amount"]) if expense.get("amount") else None
            expense["status"] = decrypt_data(expense["status"]) if expense.get("status") else None

            # Timestamps
            expense["created_at"] = expense.get("created_at")
            expense["updated_at"] = expense.get("updated_at")

            # Remove internal / sensitive fields
            expense.pop("hashed_name", None)
            expense.pop("agent_id", None)
            expense.pop("admin_id", None)

            processed.append(expense)

        # Replace generic key with domain-specific one
        payload["expenses"] = processed
        payload.pop("items", None)

        return payload

    # ------------------------------------------------------------------
    # UPDATE / DELETE
    # ------------------------------------------------------------------

    @classmethod
    def update(cls, expense_id, **updates):
        """
        Update an expense's information by expense_id.
        """
        updates["updated_at"] = datetime.now()

        if "name" in updates:
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])

        if "description" in updates:
            updates["description"] = encrypt_data(updates["description"])
        if "category" in updates:
            updates["category"] = encrypt_data(updates["category"]) if updates.get("category") else None
        if "date" in updates:
            updates["date"] = encrypt_data(updates["date"])
        if "amount" in updates:
            updates["amount"] = encrypt_data(updates["amount"])
        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])

        return super().update(expense_id, **updates)

    @classmethod
    def delete(cls, expense_id, business_id):
        """
        Delete an expense by _id and business_id.
        """
        try:
            expense_id_obj = ObjectId(expense_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(expense_id_obj, business_id_obj)

#-------------------------EXPENSE MODEL--------------------------------------

#-------------------------ADMIN MODEL--------------------------------------
class Admin(BaseModel):
    """
    An Admin represents a user in the system with different roles such as Cashier, Manager, or Admin.
    """

    collection_name = "admins"

    def __init__(
        self,
        business_id,
        role,
        user_id,
        password,
        fullname=None,
        phone=None,
        email=None,
        image=None,
        file_path=None,
        status="Active",
        date_of_birth=None,
        gender=None,
        alternative_phone=None,
        id_type=None,
        id_number=None,
        current_address=None,
        created_by=None,
    ):
        super().__init__(
            business_id=business_id,
            user_id=user_id,
            role=role,
            phone=phone,
            email=email,
            image=image,
            file_path=file_path,
            password=password,
            status=status,
            created_by=created_by,
        )

        # Foreign keys
        self.role = ObjectId(role) if role else None
        self.created_by = ObjectId(created_by) if created_by else None

        # Encrypted fields
        self.fullname = encrypt_data(fullname) if fullname else None

        self.phone = encrypt_data(phone) if phone else None
        self.phone_hashed = hash_data(phone) if phone else None

        self.email = encrypt_data(email) if email else None
        self.hashed_email = hash_data(email) if email else None

        self.image = encrypt_data(image) if image else None
        self.file_path = encrypt_data(file_path) if file_path else None

        self.status = encrypt_data(status)

        self.date_of_birth = encrypt_data(date_of_birth) if date_of_birth else None
        self.gender = encrypt_data(gender) if gender else None
        self.alternative_phone = encrypt_data(alternative_phone) if alternative_phone else None
        self.id_type = encrypt_data(id_type) if id_type else None
        self.id_number = encrypt_data(id_number) if id_number else None
        self.current_address = encrypt_data(current_address) if current_address else None

        # Password hashing (only if not already a bcrypt hash)
        self.password = (
            bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            if not password.startswith("$2b$")
            else password
        )

        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.last_logged_in = None

    def to_dict(self):
        user_dict = super().to_dict()
        user_dict.update(
            {
                "role": self.role,
                "fullname": self.fullname,
                "phone": self.phone,
                "email": self.email,
                "image": self.image,
                "file_path": self.file_path,
                "status": self.status,
                "date_of_birth": self.date_of_birth,
                "gender": self.gender,
                "alternative_phone": self.alternative_phone,
                "id_type": self.id_type,
                "id_number": self.id_number,
                "current_address": self.current_address,
                "last_logged_in": self.last_logged_in,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "phone_hashed": self.phone_hashed,
                "hashed_email": self.hashed_email,
            }
        )
        return user_dict

    # -------------------------------------------------
    # GET BY ID (business-scoped, with role + permissions)
    # -------------------------------------------------
    @classmethod
    def get_by_id(cls, business_id, admin_id):
        """
        Retrieve a system user by _id and business_id (business-scoped),
        and attach the resolved role + permissions.
        """
        try:
            business_id_obj = ObjectId(business_id)
            admin_id_obj = ObjectId(admin_id)
        except Exception:
            return None

        data = super().get_by_id(admin_id_obj, business_id_obj)
        if not data:
            return None

        # Normalise core IDs
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        if "admin_id" in data:
            data["admin_id"] = str(data["admin_id"])
        if "user_id" in data:
            data["user_id"] = str(data["user_id"])

        # ---------------------- ROLE + PERMISSIONS ---------------------- #
        role_collection = db.get_collection("roles")
        role_id = data.get("role")

        ZERO_PERMISSION = [{"view": "0", "add": "0", "edit": "0", "delete": "0"}]
        role_payload = None

        if role_id:
            try:
                role_obj_id = role_id if isinstance(role_id, ObjectId) else ObjectId(role_id)
                role_doc = role_collection.find_one({"_id": role_obj_id})
                if role_doc:
                    permissions = {}
                    for field in PERMISSION_FIELDS_FOR_ADMIN_ROLE:
                        encrypted_permissions = role_doc.get(field)
                        if encrypted_permissions:
                            permissions[field] = [
                                {k: decrypt_data(v) for k, v in item.items()}
                                for item in encrypted_permissions
                            ]
                        else:
                            permissions[field] = ZERO_PERMISSION

                    role_payload = {
                        "name": decrypt_data(role_doc.get("name")) if role_doc.get("name") else None,
                        "status": decrypt_data(role_doc.get("status")) if role_doc.get("status") else None,
                        "role_id": str(role_doc["_id"]),
                        "permissions": permissions,
                    }
            except Exception:
                role_payload = None

        # ---------------------- DECRYPT USER FIELDS ---------------------- #
        fields = [
            "fullname",
            "phone",
            "email",
            "image",
            "file_path",
            "status",
            "date_of_birth",
            "gender",
            "alternative_phone",
            "id_type",
            "id_number",
            "current_address",
        ]

        decrypted = {}
        for field in fields:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        return {
            "system_user_id": data["_id"],
            "business_id": data["business_id"],
            "admin_id": data.get("admin_id"),
            "user_id": data.get("user_id"),
            "role": role_payload,
            "fullname": decrypted["fullname"],
            "phone": decrypted["phone"],
            "email": decrypted["email"],
            "image": decrypted["image"],
            "file_path": decrypted["file_path"],
            "status": decrypted["status"],
            "date_of_birth": decrypted["date_of_birth"],
            "gender": decrypted["gender"],
            "alternative_phone": decrypted["alternative_phone"],
            "id_type": decrypted["id_type"],
            "id_number": decrypted["id_number"],
            "current_address": decrypted["current_address"],
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "last_logged_in": data.get("last_logged_in"),
        }

    # -------------------------------------------------
    # LIST SYSTEM USERS BY BUSINESS (with role + permissions)
    # -------------------------------------------------
    @classmethod
    def get_system_users_by_business(cls, business_id):
        """
        Retrieve all system users for a business along with their role + permissions.
        """
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            raise ValueError(f"Invalid business_id format: {business_id}")

        collection = db.get_collection(cls.collection_name)
        role_collection = db.get_collection("roles")

        users_cursor = collection.find(
            {
                "business_id": business_id_obj,
                "created_by": {"$type": "objectId"},
            }
        )

        result = []

        ZERO_PERMISSION = [{"view": "0", "add": "0", "edit": "0", "delete": "0"}]

        for data in users_cursor:
            # Normalise IDs
            data["_id"] = str(data["_id"])
            data["business_id"] = str(data["business_id"])
            if "admin_id" in data:
                data["admin_id"] = str(data["admin_id"])
            if "user_id" in data:
                data["user_id"] = str(data["user_id"])

            role_id = data.get("role")
            role_payload = None

            # ---------------------- ROLE + PERMISSIONS ---------------------- #
            if role_id:
                try:
                    role_obj_id = role_id if isinstance(role_id, ObjectId) else ObjectId(role_id)
                    role_doc = role_collection.find_one({"_id": role_obj_id})
                    if role_doc:
                        permissions = {}
                        for field in PERMISSION_FIELDS_FOR_ADMIN_ROLE:
                            encrypted_permissions = role_doc.get(field)
                            if encrypted_permissions:
                                permissions[field] = [
                                    {k: decrypt_data(v) for k, v in item.items()}
                                    for item in encrypted_permissions
                                ]
                            else:
                                permissions[field] = ZERO_PERMISSION

                        role_payload = {
                            "name": decrypt_data(role_doc.get("name")) if role_doc.get("name") else None,
                            "status": decrypt_data(role_doc.get("status")) if role_doc.get("status") else None,
                            "role_id": str(role_doc["_id"]),
                            "permissions": permissions,
                        }
                except Exception:
                    role_payload = None

            # ---------------------- DECRYPT PERSONAL FIELDS ---------------------- #
            user = {
                "system_user_id": data["_id"],
                "business_id": data["business_id"],
                "admin_id": data.get("admin_id"),
                "user_id": data.get("user_id"),
                "role": role_payload,
            }

            fields = [
                "fullname",
                "phone",
                "email",
                "image",
                "file_path",
                "status",
                "date_of_birth",
                "gender",
                "alternative_phone",
                "id_type",
                "id_number",
                "current_address",
            ]
            for field in fields:
                user[field] = decrypt_data(data.get(field)) if data.get(field) else None

            user["created_at"] = data.get("created_at")
            user["updated_at"] = data.get("updated_at")
            user["last_logged_in"] = data.get("last_logged_in")

            result.append(user)

        return result

    # -------------------------------------------------
    # LOOKUP BY PHONE (no role enrichment)
    # -------------------------------------------------
    @classmethod
    def get_by_phone_number(cls, phone):
        phone_hashed = hash_data(phone)

        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({"phone_hashed": phone_hashed})
        if not data:
            return None

        data["system_user_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        if "role" in data:
            data["role"] = str(data["role"])

        fields = [
            "fullname",
            "phone",
            "email",
            "image",
            "file_path",
            "status",
            "date_of_birth",
            "gender",
            "alternative_phone",
            "id_type",
            "id_number",
            "current_address",
        ]

        decrypted = {}
        for field in fields:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        return {
            "system_user_id": str(data["_id"]),
            "business_id": data["business_id"],
            "role": data.get("role"),
            "fullname": decrypted["fullname"],
            "phone": decrypted["phone"],
            "email": decrypted["email"],
            "image": decrypted["image"],
            "file_path": decrypted["file_path"],
            "status": decrypted["status"],
            "date_of_birth": decrypted["date_of_birth"],
            "gender": decrypted["gender"],
            "alternative_phone": decrypted["alternative_phone"],
            "id_type": decrypted["id_type"],
            "id_number": decrypted["id_number"],
            "current_address": decrypted["current_address"],
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "last_logged_in": data.get("last_logged_in"),
        }

    @classmethod
    def get_by_phone_number_and_business_id(cls, phone, business_id):
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        phone_hashed = hash_data(phone)

        collection = db.get_collection(cls.collection_name)
        data = collection.find_one(
            {
                "phone_hashed": phone_hashed,
                "business_id": business_id_obj,
            }
        )
        if not data:
            return None

        data["system_user_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        if "role" in data:
            data["role"] = str(data["role"])

        fields = [
            "fullname",
            "phone",
            "email",
            "image",
            "file_path",
            "status",
            "date_of_birth",
            "gender",
            "alternative_phone",
            "id_type",
            "id_number",
            "current_address",
        ]

        decrypted = {}
        for field in fields:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        return {
            "system_user_id": str(data["_id"]),
            "business_id": data["business_id"],
            "role": data.get("role"),
            "fullname": decrypted["fullname"],
            "phone": decrypted["phone"],
            "email": decrypted["email"],
            "image": decrypted["image"],
            "file_path": decrypted["file_path"],
            "status": decrypted["status"],
            "date_of_birth": decrypted["date_of_birth"],
            "gender": decrypted["gender"],
            "alternative_phone": decrypted["alternative_phone"],
            "id_type": decrypted["id_type"],
            "id_number": decrypted["id_number"],
            "current_address": decrypted["current_address"],
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "last_logged_in": data.get("last_logged_in"),
        }

    # -------------------------------------------------
    # UPDATE (with encryption + hashing)
    # -------------------------------------------------
    @classmethod
    def update(cls, system_user_id, **updates):
        encrypt_fields = [
            "fullname",
            "phone",
            "email",
            "image",
            "file_path",
            "status",
            "date_of_birth",
            "gender",
            "alternative_phone",
            "id_type",
            "id_number",
            "current_address",
        ]

        # Role (FK)
        if "role" in updates and updates["role"]:
            updates["role"] = ObjectId(updates["role"])

        # Hash fields BEFORE encrypting
        if "phone" in updates and updates["phone"]:
            updates["phone_hashed"] = hash_data(updates["phone"])
        if "email" in updates and updates["email"]:
            updates["hashed_email"] = hash_data(updates["email"])

        # Encrypt fields
        for field in encrypt_fields:
            if field in updates:
                updates[field] = encrypt_data(updates[field]) if updates[field] else None

        # Password update (if provided)
        if "password" in updates and updates["password"]:
            pwd = updates["password"]
            updates["password"] = (
                bcrypt.hashpw(pwd.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                if not pwd.startswith("$2b$")
                else pwd
            )

        return super().update(system_user_id, **updates)

    # -------------------------------------------------
    # DELETE (business-scoped)
    # -------------------------------------------------
    @classmethod
    def delete(cls, system_user_id, business_id):
        """
        Delete a system user by _id and business_id (business-scoped).
        """
        try:
            system_user_id_obj = ObjectId(system_user_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        ok = super().delete(system_user_id_obj, business_id_obj)
        
        if not ok:
            return False
        
        # Cascade delete User
        try:
            User.delete_by_system_user(system_user_id, business_id)
        except Exception as e:
            Log.error(f"[super_superadmin_model.py][delete] Failed to delete linked User for system_user_id={system_user_id}: {e}")
        return True

