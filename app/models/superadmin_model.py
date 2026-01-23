import uuid
import bcrypt


from bson.objectid import ObjectId
from datetime import datetime
from ..extensions.db import db
from ..utils.logger import Log # import logging
from ..utils.crypt import encrypt_data, decrypt_data, hash_data
from ..models.base_model import BaseModel
from ..utils.generators import generate_coupons


#-------------------------ROLE--------------------------------------
class Role(BaseModel):
    """
    A Role represents a set of permissions for a specific role in a business. This includes various permissions
    for system users, beneficiaries, transactions, and other business-related entities.
    """

    collection_name = "roles"  # Set the collection name for roles

    def __init__(self, business_id, user_id, name, email, agent_id=None,
                 system_users=None, beneficiaries=None, senders=None, expenses=None, transactions=None,
                 send_money=None, notice_board=None, bill_pay_services=None, check_current_rate=None,
                 status="Active", created_by=None, created_at=None, updated_at=None):

        super().__init__(
            business_id, user_id, agent_id, name=name, email=email,
            system_users=system_users, beneficiaries=beneficiaries, senders=senders,
            expenses=expenses, transactions=transactions, send_money=send_money,
            notice_board=notice_board, bill_pay_services=bill_pay_services,
            check_current_rate=check_current_rate, status=status,
            created_at=created_at, created_by=created_by, updated_at=updated_at
        )

        self.name = encrypt_data(name)
        self.email = encrypt_data(email)
        self.hashed_email = hash_data(email)
        self.system_users = [encrypt_data(i) for i in system_users] if system_users else None
        self.beneficiaries = [encrypt_data(i) for i in beneficiaries] if beneficiaries else None
        self.senders = [encrypt_data(i) for i in senders] if senders else None
        self.expenses = [encrypt_data(i) for i in expenses] if expenses else None
        self.transactions = [encrypt_data(i) for i in transactions] if transactions else None
        self.send_money = [encrypt_data(i) for i in send_money] if send_money else None
        self.notice_board = [encrypt_data(i) for i in notice_board] if notice_board else None
        self.bill_pay_services = [encrypt_data(i) for i in bill_pay_services] if bill_pay_services else None
        self.check_current_rate = [encrypt_data(i) for i in check_current_rate] if check_current_rate else None
        self.status = encrypt_data(status)

        self.created_by = created_by if created_by else None,
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        role_dict = super().to_dict()
        role_dict.update({
            "name": self.name,
            "system_users": self.system_users,
            "beneficiaries": self.beneficiaries,
            "senders": self.senders,
            "expenses": self.expenses,
            "transactions": self.transactions,
            "send_money": self.send_money,
            "notice_board": self.notice_board,
            "bill_pay_services": self.bill_pay_services,
            "check_current_rate": self.check_current_rate,
            "status": self.status,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        })
        return role_dict

    @classmethod
    def get_by_id(cls, role_id):
        try:
            role_id_obj = ObjectId(role_id)
        except Exception:
            return None
        
        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({"_id": role_id_obj})
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["agent_id"] = str(data["agent_id"])

        data["name"] = decrypt_data(data["name"])
        fields = ["system_users", "beneficiaries", "senders", "expenses", "transactions",
                  "send_money", "notice_board", "bill_pay_services", "check_current_rate"]
        permissions = {}
        for field in fields:
            permissions[field] = [decrypt_data(item) for item in data.get(field, [])] if data.get(field) else None
        status = decrypt_data(data["status"])

        return {
            "permissions": permissions,
            "name": data["name"],
            "status": status,
            "role_id": str(data["_id"]),
        }

    @classmethod
    def get_admin_role_by_id(cls, role_id):
        try:
            role_id_obj = ObjectId(role_id)
        except Exception:
            return None
        
        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({"_id": role_id_obj})
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["agent_id"] = str(data["agent_id"])

        data["name"] = decrypt_data(data["name"])
        fields = ["system_users", "beneficiaries", "senders", "expenses", "transactions",
                  "send_money", "notice_board", "bill_pay_services", "check_current_rate"]
        permissions = {}
        for field in fields:
            permissions[field] = [decrypt_data(item) for item in data.get(field, [])] if data.get(field) else None
        status = decrypt_data(data["status"])

        return {
            "permissions": permissions,
            "name": data["name"],
            "status": status,
            "role_id": str(data["_id"]),
        }


    @classmethod
    def get_roles_by_business_id(cls, business_id):
        try:
            business_id = ObjectId(business_id)
        except Exception:
            raise ValueError(f"Invalid business_id format: {business_id}")
        superadmin_collection = db.get_collection(cls.collection_name)
        roles_cursor = superadmin_collection.find({"business_id": business_id})
        result = []
        for data in roles_cursor:
            data["_id"] = str(data["_id"])
            data["business_id"] = str(data["business_id"])
            data["agent_id"] = str(data["agent_id"])
            data["name"] = decrypt_data(data["name"])

            permissions = {}
            for field in ["system_users", "beneficiaries", "senders", "expenses", "transactions",
                          "send_money", "notice_board", "bill_pay_services", "check_current_rate"]:
                permissions[field] = [decrypt_data(item) for item in data.get(field, [])] if data.get(field) else None

            result.append({
                "permissions": permissions,
                "name": data["name"],
                "status": decrypt_data(data["status"]),
                "role_id": data["_id"]
            })
        return result

    @classmethod
    def get_roles_by_agent_id(cls, agent_id):
        try:
            agent_id = ObjectId(agent_id)
        except Exception:
            raise ValueError(f"Invalid agent_id format: {agent_id}")

        superadmin_collection = db.get_collection(cls.collection_name)
        roles_cursor = superadmin_collection.find({"agent_id": agent_id})
        result = []
        for data in roles_cursor:
            data["_id"] = str(data["_id"])
            data["business_id"] = str(data["business_id"])
            data["agent_id"] = str(data["agent_id"])
            data["name"] = decrypt_data(data["name"])

            permissions = {}
            for field in ["system_users", "beneficiaries", "senders", "expenses", "transactions",
                          "send_money", "notice_board", "bill_pay_services", "check_current_rate"]:
                permissions[field] = [decrypt_data(item) for item in data.get(field, [])] if data.get(field) else None

            result.append({
                "permissions": permissions,
                "name": data["name"],
                "status": decrypt_data(data["status"]),
                "role_id": data["_id"]
            })
        return result

    @classmethod
    def update(cls, role_id, **updates):
        encrypt_list = ["system_users", "beneficiaries", "senders", "expenses", "transactions",
                        "send_money", "notice_board", "bill_pay_services", "check_current_rate"]
        if "name" in updates:
            updates["name"] = encrypt_data(updates["name"])
        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])
        for key in encrypt_list:
            if key in updates:
                updates[key] = [encrypt_data(i) for i in updates[key]] if updates.get(key) else None

        return super().update(role_id, **updates)

    @classmethod
    def delete(cls, role_id):
        return super().delete(role_id)

#-------------------------ROLE--------------------------------------
#-------------------------EXPENSE MODEL--------------------------------------
class Expense(BaseModel):
    """
    An Expense represents an expense transaction in a business, including details such as the name, description,
    category, date, amount, and status.
    """
    
    collection_name = "expenses"  # Set the collection name

    def __init__(self, business_id, user_id, agent_id, name, description, date, category=None, amount=0.0, status="Active", 
                 created_at=None, updated_at=None):
        super().__init__(business_id, user_id, agent_id, name=name, description=description, category=category, date=date, 
                         amount=amount, status=status, created_at=created_at, updated_at=updated_at)
        
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.description = encrypt_data(description)
        self.category = encrypt_data(category) if category else None
        self.date = encrypt_data(date)
        self.amount = encrypt_data(amount)
        self.status = encrypt_data(status)

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
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return expense_dict

    @classmethod
    def get_by_id(cls, expense_id):
        """
        Retrieve an expense by _id (MongoDB's default identifier).
        """
        try:
            # Convert expense_id to ObjectId for the query
            expense_id_obj = ObjectId(expense_id)
        except Exception as e:
            return None  # Return None if conversion fails (invalid _id format)

        # Query using _id (which is MongoDB's default unique identifier)
        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({"_id": expense_id_obj})

        if not data:
            return None  # Expense not found

        # Convert ObjectId to string for JSON serialization
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["agent_id"] = str(data["agent_id"])

        # Decrypt fields before returning
        data["name"] = decrypt_data(data["name"])
        data["description"] = decrypt_data(data["description"])
        data["category"] = decrypt_data(data["category"]) if data.get("category") else None
        data["date"] = decrypt_data(data["date"])
        data["amount"] = decrypt_data(data["amount"])
        data["status"] = decrypt_data(data["status"])
        
        data.pop("hashed_name", None)

        return data

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

            # Convert _id to string for proper JSON serialization
            expense["_id"] = str(expense["_id"])
            expense["business_id"] = str(expense["business_id"])
            expense["agent_id"] = str(expense["agent_id"])
            
            expense.pop("hashed_name", None)

            result.append(expense)

        return result

    @classmethod
    def get_expenses_by_agent_id(cls, agent_id):
        """
        Retrieve expenses by agent_id, decrypting fields.
        """
        # Ensure that agent_id is in the correct ObjectId format if it's passed as a string
        if isinstance(agent_id, str):
            try:
                agent_id = ObjectId(agent_id)  # Convert string agent_id to ObjectId if necessary
            except Exception as e:
                raise ValueError(f"Invalid agent_id format: {agent_id}") from e

        collection = db.get_collection(cls.collection_name)
        expenses_cursor = collection.find({"agent_id": agent_id})

        result = []
        for expense in expenses_cursor:
            # Decrypt fields before returning them
            expense["name"] = decrypt_data(expense["name"])
            expense["description"] = decrypt_data(expense["description"])
            expense["category"] = decrypt_data(expense["category"]) if expense.get("category") else None
            expense["date"] = decrypt_data(expense["date"])
            expense["amount"] = decrypt_data(expense["amount"])
            expense["status"] = decrypt_data(expense["status"])

            # Convert _id to string for proper JSON serialization
            expense["_id"] = str(expense["_id"])
            expense["business_id"] = str(expense["business_id"])
            expense["agent_id"] = str(expense["agent_id"])
            
            expense.pop("hashed_name", None)

            result.append(expense)

        return result

    @classmethod
    def update(cls, expense_id, **updates):
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

        return super().update(expense_id, **updates)

    @classmethod
    def delete(cls, expense_id):
        """
        Delete an expense by expense_id.
        """
        return super().delete(expense_id)
#-------------------------EXPENSE MODEL--------------------------------------

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
    def get_by_id(cls, system_user_id):
        try:
            user_id_obj = ObjectId(system_user_id)
        except Exception:
            return None

        collection = db.get_collection(cls.collection_name)
        data =  collection.find_one({"_id": user_id_obj})
        if not data:
            return None

        data["_id"] = str(data["_id"])
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
    def get_system_users_by_agent_id(cls, agent_id):
        try:
            agent_id = ObjectId(agent_id)
        except Exception:
            raise ValueError(f"Invalid agent_id format: {agent_id}")

        collection = db.get_collection(cls.collection_name)
        users_cursor = collection.find({"agent_id": agent_id})
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
    def delete(cls, system_user_id):
        return super().delete(system_user_id)

#-------------------------SYSTEM USER MODEL--------------------------------------
