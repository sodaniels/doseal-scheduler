import uuid
import bcrypt
import json
import os

from bson.objectid import ObjectId
from datetime import datetime
from app.extensions.db import db
from ...utils.logger import Log
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...models.base_model import BaseModel
from ...utils.generators import generate_coupons
from ...constants.service_code import (
    HTTP_STATUS_CODES, PERMISSION_FIELDS_FOR_AGENTS
)

class Role(BaseModel):
    collection_name = "roles"

    def __init__(self, business_id, user_id, name, email, agent_id=None, status="Active", 
                 created_by=None, created_at=None, updated_at=None, **kwargs):
        super().__init__(
            business_id, user_id, name=name,email=email, agent_id=ObjectId(agent_id), status=status,
            created_at=created_at, created_by=created_by, updated_at=updated_at
        )
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.email = encrypt_data(email)
        self.hashed_email = hash_data(email)
        self.status = encrypt_data(status)

        ZERO_PERMISSION = {"view": "0", "add": "0", "edit": "0", "delete": "0"}

        for field in PERMISSION_FIELDS_FOR_AGENTS:
            field_value = kwargs.get(field, [ZERO_PERMISSION])
            encrypted_list = [
                {k: encrypt_data(v) for k, v in item.items()}
                for item in field_value
            ]
            setattr(self, field, encrypted_list)

        self.created_by = ObjectId(created_by) if created_by else None
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        role_dict = super().to_dict()
        role_dict.update({
            "name": self.name,
            "status": self.status,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        })
        for field in PERMISSION_FIELDS_FOR_AGENTS:
            role_dict[field] = getattr(self, field, [])
        return role_dict

    @classmethod
    def get_by_id(cls, role_id, business_id=None, agent_id=None):
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None
        try:
            role_id_obj = ObjectId(role_id)
        except Exception:
            return None

        try:
            agent_id_obj = ObjectId(agent_id)
        except Exception:
            return None
        
        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({
            "_id": role_id_obj, 
            "business_id": business_id_obj,
            "agent_id": agent_id_obj,
        })
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["agent_id"] = str(data["agent_id"])
        data["name"] = decrypt_data(data["name"])
        status = decrypt_data(data["status"])

        ZERO_PERMISSION = [{"view": "0", "add": "0", "edit": "0", "delete": "0"}]

        permissions = {}
        for field in PERMISSION_FIELDS_FOR_AGENTS:
            encrypted_permissions = data.get(field)
            if encrypted_permissions:
                permissions[field] = [
                    {k: decrypt_data(v) for k, v in item.items()}
                    for item in encrypted_permissions
                ]
            else:
                permissions[field] = ZERO_PERMISSION

        return {
            "permissions": permissions,
            "name": data["name"],
            "status": status,
            "role_id": str(data["_id"]),
        }

    @classmethod
    def check_item_exists(cls, agent_id, key, value):
        try:
            if not cls.check_permission(cls, 'add'):
                raise PermissionError(f"User does not have permission to view {cls.__name__}.")
            
            try:
                agent_id_obj = ObjectId(agent_id)
            except Exception:
                return None
            
            hashed_key = hash_data(value)
            query = {
                "agent_id": agent_id_obj,
                f"hashed_{key}": hashed_key
            }
            collection = db.get_collection(cls.collection_name)
            existing_item = collection.find_one(query)
            return bool(existing_item)
        except Exception as e:
            print(f"Error occurred: {e}")
            return False

    @classmethod
    def check_role_exists(cls, agent_id, name_key, name_value, email_key, email_value):
        try:
            # Check if the user has 'add' permission
            if not cls.check_permission(cls, 'add'):
                raise PermissionError(f"User does not have permission to view {cls.__name__}.")
            
            try:
                agent_id_obj = ObjectId(agent_id)
            except Exception:
                raise ValueError(f"Invalid agent_id format: {agent_id}")
            
            # Hash the name and email values
            hashed_name_key = hash_data(name_value)
            hashed_email_key = hash_data(email_value)
            
            # Prepare the query to check for existing role
            query = {
                "agent_id": agent_id_obj,
                f"hashed_{name_key}": hashed_name_key,
                f"hashed_{email_key}": hashed_email_key
            }

            # Fetch the collection and check for an existing item matching the query
            collection = db.get_collection(cls.collection_name)
            existing_item = collection.find_one(query)

            # Return True if an item is found, otherwise False
            return bool(existing_item)
        
        except PermissionError as pe:
            # Handle permission error separately
            print(f"Permission error: {pe}")
            return False
        except Exception as e:
            # Catch other exceptions and log them
            print(f"Error occurred while checking role existence: {e}")
            return False

    @classmethod
    def get_roles_by_business_id(cls, business_id):
        try:
            business_id = ObjectId(business_id)
        except Exception:
            raise ValueError(f"Invalid business_id format: {business_id}")

        superadmin_collection = db.get_collection(cls.collection_name)
        roles_cursor = superadmin_collection.find({
            "business_id": business_id,
            "created_by": {"$type": "objectId"}
        })

        result = []
        ZERO_PERMISSION = [{"view": "0", "add": "0", "edit": "0", "delete": "0"}]

        for data in roles_cursor:
            data["_id"] = str(data["_id"])
            data["business_id"] = str(data["business_id"])
            data["created_by"] = str(data["created_by"])
            data["name"] = decrypt_data(data["name"])
            data["status"] = decrypt_data(data["status"])

            permissions = {}
            for field in PERMISSION_FIELDS_FOR_AGENTS:
                encrypted_permissions = data.get(field)
                if encrypted_permissions:
                    permissions[field] = [
                        {k: decrypt_data(v) for k, v in item.items()}
                        for item in encrypted_permissions
                    ]
                else:
                    permissions[field] = ZERO_PERMISSION

            result.append({
                "permissions": permissions,
                "name": data["name"],
                "status": data["status"],
                "role_id": data["_id"]
            })

        return result

    @classmethod
    def get_roles_by_business_id_and_agent_id(cls, business_id, agent_id):
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            raise ValueError(f"Invalid business_id format: {business_id}")
        
        try:
            agent_id_obj = ObjectId(agent_id)
        except Exception:
            raise ValueError(f"Invalid business_id format: {agent_id}")

        superadmin_collection = db.get_collection(cls.collection_name)
        roles_cursor = superadmin_collection.find({
            "business_id": business_id_obj,
            "agent_id": agent_id_obj,
            "created_by": {"$type": "objectId"}
        })

        result = []
        ZERO_PERMISSION = [{"view": "0", "add": "0", "edit": "0", "delete": "0"}]

        for data in roles_cursor:
            data["_id"] = str(data["_id"])
            data["business_id"] = str(data["business_id"])
            data["created_by"] = str(data["created_by"])
            data["name"] = decrypt_data(data["name"])
            data["status"] = decrypt_data(data["status"])

            permissions = {}
            for field in PERMISSION_FIELDS_FOR_AGENTS:
                encrypted_permissions = data.get(field)
                if encrypted_permissions:
                    permissions[field] = [
                        {k: decrypt_data(v) for k, v in item.items()}
                        for item in encrypted_permissions
                    ]
                else:
                    permissions[field] = ZERO_PERMISSION

            result.append({
                "permissions": permissions,
                "name": data["name"],
                "status": data["status"],
                "role_id": data["_id"]
            })

        return result


    @classmethod
    def update(cls, role_id, **updates):
        if "name" in updates:
            updates["name"] = encrypt_data(updates["name"])
        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])

        for key in PERMISSION_FIELDS_FOR_AGENTS:
            if key in updates:
                updates[key] = [
                    {k: encrypt_data(v) for k, v in item.items()}
                    for item in updates[key]
                ] if updates[key] else None
        Log.info(f"updates: {updates}")

        return super().update(role_id, **updates)

    @classmethod
    def delete(cls, role_id, business_id):
        return super().delete(role_id, business_id)

#-------------------------ROLE--------------------------------------

#-------------------------EXPENSE MODEL--------------------------------------
class Expense(BaseModel):
    """
    An Expense represents an expense transaction in a business, including details such as the name, description,
    category, date, amount, and status.
    """
    
    collection_name = "expenses"  # Set the collection name

    def __init__(self, business_id, user_id, name, description, date, agent_id=None, category=None, amount=0.0, status="Active", 
                 created_at=None, admin_id=None, updated_at=None, image=None, image_path=None):
        super().__init__(business_id, user_id, agent_id=ObjectId(agent_id), admin_id=admin_id, name=name, description=description, category=category, date=date, 
                         amount=amount, status=status, image=image, image_path=image_path, created_at=created_at, updated_at=updated_at)
        
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.description = encrypt_data(description)
        self.category = encrypt_data(category) if category else None
        self.date = encrypt_data(date)
        self.amount = encrypt_data(amount)
        self.status = encrypt_data(status)
        self.image = encrypt_data(image)
        self.image_path = encrypt_data(image_path)

        # Add created and updated timestamps
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        """
        Convert the expense object to a dictionary representation.
        """
        expense_dict = super().to_dict()
        expense_dict.update({
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "date": self.date,
            "amount": self.amount,
            "status": self.status,
            "image": self.image,
            "image_path": self.image_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return expense_dict

    @classmethod
    def get_by_id(cls, expense_id, business_id, agent_id):
        """
        Retrieve an expense by _id, business_id and agent_id (MongoDB's default identifier).
        """
        try:
            # Convert expense_id to ObjectId for the query
            expense_id_obj = ObjectId(expense_id)
        except Exception as e:
            return None  # Return None if conversion fails (invalid _id format)
        
        try:
            # Convert business_id to ObjectId for the query
            business_id_obj = ObjectId(business_id)
        except Exception as e:
            return None  # Return None if conversion fails (invalid _id format)
        
        try:
            # Convert business_id to ObjectId for the query
            agent_id_obj = ObjectId(agent_id)
        except Exception as e:
            return None  # Return None if conversion fails (invalid _id format)

        # Query using _id (which is MongoDB's default unique identifier)
        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({
            "_id": expense_id_obj, 
            "business_id": business_id_obj,
            "agent_id": agent_id_obj,
        })

        if not data:
            return None  # Expense not found

        # Convert ObjectId to string for JSON serialization
        data["_id"] = str(data["_id"])
        data["user_id"] = str(data["user_id"])
        data["business_id"] = str(data["business_id"])
        data["agent_id"] = str(data["agent_id"])

        # Decrypt fields before returning
        data["name"] = decrypt_data(data["name"])
        data["description"] = decrypt_data(data["description"])
        data["category"] = decrypt_data(data["category"]) if data.get("category") else None
        data["date"] = decrypt_data(data["date"])
        data["amount"] = decrypt_data(data["amount"])
        data["status"] = decrypt_data(data["status"])
        if data.get("image"):
                data["image"] = decrypt_data(data["image"])
        
        data.pop("hashed_name", None)
        data.pop("image_path", None)

        return data

    @classmethod
    def get_all(cls, business_id, agent_id, page=1, per_page=10):
        """
        Get all notices, decrypting fields and implementing pagination.
        """
        # Load default settings from env
        default_page = os.getenv("DEFAULT_PAGINATION_PAGE")
        
        try:
            business_id_obj = ObjectId(business_id)
        except Exception as e:
            return None
        
        try:
            agent_id_obj = ObjectId(agent_id)
        except Exception as e:
            return None


        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE")
        
        # Ensure page and per_page are integers
        page = int(page) if page else int(default_page)
        per_page = int(per_page) if per_page else int(default_per_page)

        notice_board_collection = db.get_collection(cls.collection_name)
        notices_cursor = notice_board_collection.find({
            "agent_id": agent_id_obj,
            "business_id": business_id_obj
        })

        # Get total count for pagination
        total_count = notice_board_collection.count_documents({})

        # Apply pagination using skip and limit
        notices_cursor = notices_cursor.skip((page - 1) * per_page).limit(per_page)

        result = []
        for notice in notices_cursor:
            notice["_id"] = str(notice["_id"])
            notice["business_id"] = str(notice["business_id"])
            notice["agent_id"] = str(notice["agent_id"])

            # Decrypt fields before returning them
            notice["category"] = decrypt_data(notice["category"])
            notice["date"] = decrypt_data(notice["date"])
            notice["amount"] = decrypt_data(notice["amount"])
            notice["description"] = decrypt_data(notice["description"]) if notice.get("description") else None
            notice["image"] = decrypt_data(notice["image"]) if notice.get("image") else None
            notice["name"] = decrypt_data(notice["name"]) if notice.get("name") else None
            notice["status"] = decrypt_data(notice["status"])

            notice.pop("user__id", None)
            notice.pop("user_id", None)
            notice.pop("image_path", None)
            notice.pop("hashed_name", None)
            
            # Append the processed notice data to the result list
            result.append(notice)

        # Calculate the total number of pages
        total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

        return {
            "result": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def get_expenses_by_business_id(cls, business_id):
        """
        Retrieve expenses by business_id, decrypting fields.
        """
        # Ensure that business_id is in the correct ObjectId format if it's passed as a string
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)  # Convert string business_id to ObjectId if necessary
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e

        collection = db.get_collection(cls.collection_name)
        expenses_cursor = collection.find({"business_id": business_id})

        result = []
        for expense in expenses_cursor:
            # Decrypt fields before returning them
            expense["name"] = decrypt_data(expense["name"])
            expense["description"] = decrypt_data(expense["description"])
            expense["category"] = decrypt_data(expense["category"]) if expense.get("category") else None
            expense["date"] = decrypt_data(expense["date"])
            expense["amount"] = decrypt_data(expense["amount"])
            expense["status"] = decrypt_data(expense["status"])
            if expense.get("image"):
                expense["image"] = decrypt_data(expense["image"])

            # Convert _id to string for proper JSON serialization
            expense["_id"] = str(expense["_id"])
            expense["business_id"] = str(expense["business_id"])
            expense["agent_id"] = str(expense["agent_id"])
            
            expense.pop("hashed_name", None)
            expense.pop("image_path", None)

            result.append(expense)

        return result

    @classmethod
    def get_expenses_by_agent_id(cls, agent_id, business_id):
        """
        Retrieve expenses by agent_id, decrypting fields.
        """
        # Ensure that agent_id is in the correct ObjectId format if it's passed as a string
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)  # Convert string business_id to ObjectId if necessary
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e
        if isinstance(agent_id, str):
            try:
                agent_id = ObjectId(agent_id)  # Convert string agent_id to ObjectId if necessary
            except Exception as e:
                raise ValueError(f"Invalid agent_id format: {agent_id}") from e

        collection = db.get_collection("expenses")
        expenses_cursor = collection.find({
            "agent_id": agent_id, 
            "business_id": business_id
        })

        result = []
        for expense in expenses_cursor:
            # Decrypt fields before returning them
            expense["name"] = decrypt_data(expense["name"])
            expense["description"] = decrypt_data(expense["description"])
            expense["category"] = decrypt_data(expense["category"]) if expense.get("category") else None
            expense["date"] = decrypt_data(expense["date"])
            expense["amount"] = decrypt_data(expense["amount"])
            expense["status"] = decrypt_data(expense["status"])
            if expense.get("image"):
                expense["image"] = decrypt_data(expense["image"])

            # Convert _id to string for proper JSON serialization
            expense["_id"] = str(expense["_id"])
            expense["business_id"] = str(expense["business_id"])
            expense["agent_id"] = str(expense["agent_id"])
            
            expense.pop("hashed_name", None)

            result.append(expense)

        return result

    @classmethod
    def get_expenses_by_admin_id(cls, admin_id, business_id):
        """
        Retrieve expenses by admin_id, decrypting fields.
        """
        # Ensure that admin_id is in the correct ObjectId format if it's passed as a string
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)  # Convert string business_id to ObjectId if necessary
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e
        if isinstance(admin_id, str):
            try:
                admin_id = ObjectId(admin_id)  # Convert string admin_id to ObjectId if necessary
            except Exception as e:
                raise ValueError(f"Invalid agadmin_ident_id format: {admin_id}") from e

        collection = db.get_collection("expenses")
        expenses_cursor = collection.find({
            "admin_id": admin_id, 
            "business_id": business_id
        })

        result = []
        for expense in expenses_cursor:
            # Decrypt fields before returning them
            expense["name"] = decrypt_data(expense["name"])
            expense["description"] = decrypt_data(expense["description"])
            expense["category"] = decrypt_data(expense["category"]) if expense.get("category") else None
            expense["date"] = decrypt_data(expense["date"])
            expense["amount"] = decrypt_data(expense["amount"])
            expense["status"] = decrypt_data(expense["status"])
            
            if expense.get("image"):
                expense["image"] = decrypt_data(expense["image"])

            # Convert _id to string for proper JSON serialization
            expense["_id"] = str(expense["_id"])
            expense["business_id"] = str(expense["business_id"])
            expense["admin_id"] = str(expense["admin_id"])
            
            expense.pop("hashed_name", None)
            expense.pop("image_path", None)

            result.append(expense)

        return result

    @classmethod
    def check_item_exists(cls, agent_id, key, value):
        try:
            if not cls.check_permission(cls, 'add'):
                raise PermissionError(f"User does not have permission to view {cls.__name__}.")
            
            try:
                agent_id_obj = ObjectId(agent_id)
            except Exception:
                return None
            
            hashed_key = hash_data(value)
            query = {
                "agent_id": agent_id_obj,
                f"hashed_{key}": hashed_key
            }
            collection = db.get_collection(cls.collection_name)
            existing_item = collection.find_one(query)
            return bool(existing_item)
        except Exception as e:
            print(f"Error occurred: {e}")
            return False

    @classmethod
    def update(cls, expense_id, business_id, **updates):
        """
        Update an expense's information by expense_id.
        """
        # Encrypt fields if they are being updated
        if "name" in updates:
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
        if "image" in updates:
            updates["image"] = encrypt_data(updates["image"]) if updates["image"] else None
            updates["image_path"] = encrypt_data(updates["image_path"]) if updates["image_path"] else None
            
           

        return super().update(expense_id, business_id, **updates)

    @classmethod
    def delete(cls, expense_id, business_id):
        """
        Delete an expense by expense_id and business_id.
        """
        return super().delete(expense_id, business_id)

#-------------------------SYSTEM USER MODEL--------------------------------------
class SystemUser(BaseModel):
    """
    A SystemUser represents a user in the system with different roles such as Cashier, Manager, or Admin.
    """

    collection_name = "system_users"

    def __init__(self, business_id, role, user_id, agent_id, password,
                 fullname=None, phone=None, email=None, image=None, file_path=None, status="Active", 
                 date_of_birth=None, gender=None, alternative_phone=None, id_type=None, 
                 id_number=None, current_address=None):

        super().__init__(business_id=business_id, agent_id=agent_id, role=role, user_id=user_id,
                         phone=phone, email=email, image=image, file_path=file_path,
                         password=password, status=status)

        self.role = ObjectId(role)
        self.fullname = encrypt_data(fullname) if fullname else None
        self.phone = encrypt_data(phone) if phone else None
        self.phone_hashed = hash_data(phone) if phone else None
        self.email = encrypt_data(email) if email else None
        self.hashed_email = hash_data(email) if email else None
        self.image = encrypt_data(image) if image else None
        self.file_path = encrypt_data(file_path) if file_path else None

        self.password = (
            bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            if not password.startswith("$2b$")
            else password
        )

        self.status = encrypt_data(status)
        self.date_of_birth = encrypt_data(date_of_birth) if date_of_birth else None
        self.gender = encrypt_data(gender) if gender else None
        self.alternative_phone = encrypt_data(alternative_phone) if alternative_phone else None
        self.id_type = encrypt_data(id_type) if id_type else None
        self.id_number = encrypt_data(id_number) if id_number else None
        self.current_address = encrypt_data(current_address) if current_address else None

        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.last_logged_in = None

    def to_dict(self):
        user_dict = super().to_dict()
        user_dict.update({
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
        })
        return user_dict

    @classmethod
    def get_by_id(cls, system_user_id, business_id, agent_id):
        try:
            system_user_id_obj = ObjectId(system_user_id)
        except Exception:
            return None
        
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None
        
        try:
            agent_id_obj = ObjectId(agent_id)
        except Exception:
            return None

        collection = db.get_collection(cls.collection_name)
        data =  collection.find_one({
            "_id": system_user_id_obj,
            "business_id": business_id_obj,
            "agent_id": agent_id_obj,
        })
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["agent_id"] = str(data["agent_id"])
        data["role"] = str(data["role"])

        fields = [
            "fullname", "phone", "email", "image", "file_path", "status", "date_of_birth",
            "gender", "alternative_phone", "id_type", "id_number", "current_address"
        ]

        decrypted = {}
        for field in fields:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        return {
            "business_id": str(data["business_id"]),
            "agent_id": str(data["agent_id"]),
            "user_id": str(data["_id"]),
            "role": data["role"],
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
    def get_system_users_by_agent_id(cls, business_id, agent_id):\
        
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            raise ValueError(f"Invalid agent_id format: {business_id}")
        
        try:
            agent_id_obj = ObjectId(agent_id)
        except Exception:
            raise ValueError(f"Invalid agent_id format: {agent_id}")

        collection = db.get_collection(cls.collection_name)
        users_cursor = collection.find({
            "agent_id": agent_id_obj,
            "business_id": business_id_obj,
        })
        result = []

        for data in users_cursor:
            data["_id"] = str(data["_id"])
            data["business_id"] = str(data["business_id"])
            data["agent_id"] = str(data["agent_id"])
            data["role"] = str(data["role"])

            fields = [
                "fullname", "phone", "email", "image", "file_path", "status", "date_of_birth", "gender",
                "alternative_phone", "id_type", "id_number", "current_address"
            ]

            user = {
                "_id": data["_id"],
                "business_id": data["business_id"],
                "agent_id": data["agent_id"],
                "role": data["role"],
            }

            for field in fields:
                user[field] = decrypt_data(data.get(field)) if data.get(field) else None

            user["created_at"] = data.get("created_at")
            user["updated_at"] = data.get("updated_at")
            user["last_logged_in"] = data.get("last_logged_in")

            result.append(user)

        return result

    @classmethod
    def get_by_phone_number(cls, phone):
        
        phone_hashed = hash_data(phone)

        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({"phone_hashed": phone_hashed})
        if not data:
            return None

        data["system_user_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["role"] = str(data["role"])

        fields = [
            "fullname", "phone", "email", "image", "file_path", "status", "date_of_birth",
            "gender", "alternative_phone", "id_type", "id_number", "current_address"
        ]

        decrypted = {}
        for field in fields:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        return {
            "system_user_id": str(data["_id"]),
            "agent_id": str(data["agent_id"]),
            "business_id": data["business_id"],
            "role": data["role"],
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
    def update(cls, system_user_id, **updates):
        encrypt_fields = [
            "fullname", "phone", "email", "image", "file_path", "status", "date_of_birth",
            "gender", "alternative_phone", "id_type", "id_number", "current_address"
        ]

        if "role" in updates:
            updates["role"] = ObjectId(updates["role"])

        for field in encrypt_fields:
            if field in updates:
                updates[field] = encrypt_data(updates[field]) if updates[field] else None

        return super().update(system_user_id, **updates)

    @classmethod
    def delete(cls, system_user_id, business_id):
        return super().delete(system_user_id, business_id)

#-------------------------ADMIN--------------------------------------
class Admin(BaseModel):
    """
    An Admin represents a user in the system with different roles such as Cashier, Manager, or Admin.
    """

    collection_name = "admins"

    def __init__(self, business_id, role, user_id, admin_id, password,
                 fullname=None, phone=None, email=None, image=None, file_path=None, status="Active", 
                 date_of_birth=None, gender=None, alternative_phone=None, id_type=None, 
                 id_number=None, current_address=None, created_by=None):

        super().__init__(business_id=business_id, admin_id=admin_id, role=role, user_id=user_id,
                         phone=phone, email=email, image=image, file_path=file_path,
                         password=password, status=status, created_by=created_by)

        self.role = ObjectId(role)
        self.fullname = encrypt_data(fullname) if fullname else None
        self.phone = encrypt_data(phone) if phone else None
        self.phone_hashed = hash_data(phone) if phone else None
        self.email = encrypt_data(email) if email else None
        self.hashed_email = hash_data(email) if email else None
        self.image = encrypt_data(image) if image else None
        self.file_path = encrypt_data(file_path) if file_path else None
        self.created_by = ObjectId(created_by) if created_by else None

        self.password = (
            bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            if not password.startswith("$2b$")
            else password
        )

        self.status = encrypt_data(status)
        self.date_of_birth = encrypt_data(date_of_birth) if date_of_birth else None
        self.gender = encrypt_data(gender) if gender else None
        self.alternative_phone = encrypt_data(alternative_phone) if alternative_phone else None
        self.id_type = encrypt_data(id_type) if id_type else None
        self.id_number = encrypt_data(id_number) if id_number else None
        self.current_address = encrypt_data(current_address) if current_address else None

        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.last_logged_in = None

    def to_dict(self):
        user_dict = super().to_dict()
        user_dict.update({
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
        })
        return user_dict

    @classmethod
    def get_by_id(cls, business_id, system_user_id):
        try:
            user_id_obj = ObjectId(system_user_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        collection = db.get_collection(cls.collection_name)
        role_collection = db.get_collection("roles")
        
        data =  collection.find_one({
            "_id": user_id_obj, 
            "business_id": business_id_obj
        })
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["role"] = str(data["role"])
        role_id = data.get("role")
        
        ZERO_PERMISSION = [{"add": "0", "delete": "0", "edit": "0", "view": "0"}]
        
        user = {}
        
        # 🔁 Populate role with permissions and details
        if role_id:
            try:
                role_obj_id = ObjectId(role_id) if isinstance(role_id, str) else role_id
                role_doc = role_collection.find_one({"_id": role_obj_id})

                if role_doc:
                    permissions = {}
                    for field in PERMISSION_FIELDS_FOR_AGENTS:
                        encrypted_permissions = role_doc.get(field)
                        if encrypted_permissions:
                            permissions[field] = [
                                {k: decrypt_data(v) for k, v in item.items()}
                                for item in encrypted_permissions
                            ]
                        else:
                            permissions[field] = ZERO_PERMISSION

                    user["role"] = {
                        "name": decrypt_data(role_doc.get("name")),
                        "status": decrypt_data(role_doc.get("status")),
                        "role_id": str(role_doc["_id"]),
                        "permissions": permissions
                    }
                else:
                    user["role"] = None
            except Exception:
                user["role"] = None
        else:
            user["role"] = None

        fields = [
            "fullname", "phone", "email", "image", "file_path", "status", "date_of_birth",
            "gender", "alternative_phone", "id_type", "id_number", "current_address"
        ]

        decrypted = {}
        for field in fields:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        return {
            "user_id": str(data["_id"]),
            "role": data["role"],
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
            "role": user.get("role"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "last_logged_in": data.get("last_logged_in"),
        }

    @classmethod
    def get_system_users_by_business(cls, business_id):
        try:
            business_id = ObjectId(business_id)
        except Exception:
            raise ValueError(f"Invalid business_id format: {business_id}")

        collection = db.get_collection(cls.collection_name)
        role_collection = db.get_collection("roles")

        users_cursor = collection.find({
            "business_id": business_id,
            "created_by": {"$type": "objectId"}
        })

        result = []

        ZERO_PERMISSION = [{"add": "0", "delete": "0", "edit": "0", "view": "0"}]

        for data in users_cursor:
            data["_id"] = str(data["_id"])
            data["business_id"] = str(data["business_id"])
            data["agent_id"] = str(data["agent_id"])
            role_id = data.get("role")

            user = {
                "_id": data["_id"],
                "business_id": data["business_id"],
                "agent_id": data["agent_id"],
            }

            # 🔁 Populate role with permissions and details
            if role_id:
                try:
                    role_obj_id = ObjectId(role_id) if isinstance(role_id, str) else role_id
                    role_doc = role_collection.find_one({"_id": role_obj_id})

                    if role_doc:
                        permissions = {}
                        for field in PERMISSION_FIELDS_FOR_AGENTS:
                            encrypted_permissions = role_doc.get(field)
                            if encrypted_permissions:
                                permissions[field] = [
                                    {k: decrypt_data(v) for k, v in item.items()}
                                    for item in encrypted_permissions
                                ]
                            else:
                                permissions[field] = ZERO_PERMISSION

                        user["role"] = {
                            "name": decrypt_data(role_doc.get("name")),
                            "status": decrypt_data(role_doc.get("status")),
                            "role_id": str(role_doc["_id"]),
                            "permissions": permissions
                        }
                    else:
                        user["role"] = None
                except Exception:
                    user["role"] = None
            else:
                user["role"] = None

            # 🔐 Decrypt personal fields
            fields = [
                "fullname", "phone", "email", "image", "file_path", "status", "date_of_birth", "gender",
                "alternative_phone", "id_type", "id_number", "current_address"
            ]
            for field in fields:
                user[field] = decrypt_data(data.get(field)) if data.get(field) else None

            user["created_at"] = data.get("created_at")
            user["updated_at"] = data.get("updated_at")
            user["last_logged_in"] = data.get("last_logged_in")

            result.append(user)

        return result


    @classmethod
    def get_by_phone_number(cls, phone):
        
        phone_hashed = hash_data(phone)

        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({"phone_hashed": phone_hashed})
        if not data:
            return None

        data["system_user_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["role"] = str(data["role"])

        fields = [
            "fullname", "phone", "email", "image", "file_path", "status", "date_of_birth",
            "gender", "alternative_phone", "id_type", "id_number", "current_address"
        ]

        decrypted = {}
        for field in fields:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        return {
            "system_user_id": str(data["_id"]),
            "agent_id": str(data["agent_id"]),
            "business_id": data["business_id"],
            "role": data["role"],
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
    def update(cls, system_user_id, **updates):
        encrypt_fields = [
            "fullname", "phone", "email", "image", "file_path", "status", "date_of_birth",
            "gender", "alternative_phone", "id_type", "id_number", "current_address"
        ]

        if "role" in updates:
            updates["role"] = ObjectId(updates["role"])

        for field in encrypt_fields:
            if field in updates:
                updates[field] = encrypt_data(updates[field]) if updates[field] else None

        return super().update(system_user_id, **updates)

    @classmethod
    def check_admin_item_exists(cls, admin_id, key, value):
        """
        Check if an item exists by admin_id and a specific key (hashed comparison).
        This method allows dynamic checks for any key (like 'name', 'phone', etc.).
        
        Args:
        - admin_id: The admin ID to filter the items.
        - key: The key (field) to check for existence (e.g., 'name', 'phone').
        - value: The value of the key to check for existence.

        Returns:
        - True if the item exists, False otherwise.
        """
        
        # Check if the user has permission to 'add' before proceeding
        if not cls.check_permission(cls, 'add'):
            raise PermissionError(f"User does not have permission to view {cls.__name__}.")

        # Dynamically hash the value of the key
        hashed_key = hash_data(value)  # Hash the value provided for the dynamic field

        # Dynamically create the query with admin_id and hashed field
        query = {
            "admin_id": admin_id,
            f"hashed_{key}": hashed_key  # Use the key dynamically (e.g., "hashed_name" or "hashed_phone")
        }

        # Query the database for an item matching the given admin_id and hashed value
        collection = db.get_collection(cls.collection_name)
        existing_item = collection.find_one(query)

        # Return True if a matching item is found, else return False
        return bool(existing_item)


    @classmethod
    def delete(cls, system_user_id, business_id):
        return super().delete(system_user_id, business_id)

