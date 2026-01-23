import uuid
import bcrypt
import os
from bson.objectid import ObjectId
from datetime import datetime
from app.extensions.db import db
from ..utils.logger import Log
from ..utils.generators import generate_agent_id
from ..utils.crypt import encrypt_data, decrypt_data, hash_data
from ..models.base_model import BaseModel

# User
class SystemUser(BaseModel):
    """
    A SystemUser represents a user in the system with different roles such as Consumer or Agent.
    """

    collection_name = "system_users"  # Set the collection name

    def __init__(self, tenant_id, user_id=None, type="Consumer", username=None, first_name=None, middle_name=None, 
                 last_name=None, date_of_birth=None, alt_phone_number=None, alt_email=None, post_code=None, 
                 identification=None, device_uuid=None, request=None, logo=None, remote_ip=None, last_login=None, 
                 referrer=None, referral_code=None, referrals=None, transactions=None, balance=0, balance_update_status=None,
                 ):
        
        super().__init__(tenant_id=tenant_id, user_id=user_id, username=username)

        self.user_id = user_id if user_id else str(uuid.uuid4())  # Generate a user ID if not provided
        self.type = type
        
        self.username = encrypt_data(username) if username else None  # Encrypt username
        self.first_name = encrypt_data(first_name) if first_name else None  # Encrypt first name
        self.middle_name = encrypt_data(middle_name) if middle_name else None  # Encrypt middle name
        self.last_name = encrypt_data(last_name) if last_name else None  # Encrypt last name
        self.date_of_birth = encrypt_data(date_of_birth) if date_of_birth else None
        self.alt_phone_number = encrypt_data(alt_phone_number) if alt_phone_number else None  # Encrypt alternative phone number
        self.alt_email = encrypt_data(alt_email) if alt_email else None  # Encrypt alternative email
        self.post_code = encrypt_data(post_code) if post_code else None  # Encrypt post code
        self.identification = encrypt_data(identification) if identification else None  # Encrypt identification
        self.device_uuid = encrypt_data(device_uuid) if device_uuid else None  # Encrypt device UUID
        self.request = encrypt_data(request) if request else None  # Encrypt request
        self.logo = encrypt_data(logo) if logo else None  # Encrypt logo
        self.remote_ip = encrypt_data(remote_ip) if remote_ip else None  # Encrypt remote IP
        self.last_login = encrypt_data(last_login) if last_login else datetime.now()  # Encrypt last login
        self.referrer = encrypt_data(referrer) if referrer else None  # Encrypt referrer
        self.referral_code = encrypt_data(referral_code) if referral_code else None  # Encrypt referral code
        self.referrals = encrypt_data(referrals) if referrals else []  # Encrypt referrals
        self.transactions = encrypt_data(transactions) if transactions else 0  # Encrypt transactions
        self.balance = encrypt_data(balance) if balance else 0  # Encrypt balance
        self.balance_update_status = encrypt_data(balance_update_status) if balance_update_status else None  # Encrypt balance update status

        # Add created and updated timestamps
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the system user object to a dictionary representation.
        """
        user_dict = super().to_dict()
        user_dict.update({
            "user_id": self.user_id,
            "type": self.type,
            "tenant_id": self.tenant_id,
            "username": decrypt_data(self.username) if self.username else None,
            "first_name": decrypt_data(self.first_name) if self.first_name else None,
            "middle_name": decrypt_data(self.middle_name) if self.middle_name else None,
            "last_name": decrypt_data(self.last_name) if self.last_name else None,
            "date_of_birth": decrypt_data(self.date_of_birth) if self.date_of_birth else None,
            "alt_phone_number": decrypt_data(self.alt_phone_number) if self.alt_phone_number else None,
            "alt_email": decrypt_data(self.alt_email) if self.alt_email else None,
            "post_code": decrypt_data(self.post_code) if self.post_code else None,
            "identification": decrypt_data(self.identification) if self.identification else None,
            "device_uuid": decrypt_data(self.device_uuid) if self.device_uuid else None,
            "request": decrypt_data(self.request) if self.request else None,
            "logo": decrypt_data(self.logo) if self.logo else None,
            "remote_ip": decrypt_data(self.remote_ip) if self.remote_ip else None,
            "last_login": decrypt_data(self.last_login) if self.last_login else None,
            "referrer": decrypt_data(self.referrer) if self.referrer else None,
            "referral_code": decrypt_data(self.referral_code) if self.referral_code else None,
            "referrals": decrypt_data(self.referrals) if self.referrals else None,
            "transactions": decrypt_data(self.transactions) if self.transactions else None,
            "balance": decrypt_data(self.balance) if self.balance else None,
            "balance_update_status": decrypt_data(self.balance_update_status) if self.balance_update_status else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return user_dict

    @classmethod
    def get_by_id(cls, user_id):
        """
        Retrieve a system user by user_id.
        """
        try:
            user_id_obj = ObjectId(user_id)
        except Exception as e:
            return None  # Return None if conversion fails (invalid _id format)

        # Query using _id (which is MongoDB's default unique identifier)
        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({"_id": user_id_obj})

        if not data:
            return None  # User not found

        # Convert ObjectId to string for JSON serialization
        data["_id"] = str(data["_id"])
        data["tenant_id"] = data["tenant_id"]

        # Decrypt fields before returning
        data["username"] = decrypt_data(data["username"]) if data["username"] else None
        data["first_name"] = decrypt_data(data["first_name"]) if data["first_name"] else None
        data["middle_name"] = decrypt_data(data["middle_name"]) if data["middle_name"] else None
        data["last_name"] = decrypt_data(data["last_name"]) if data["last_name"] else None
        data["date_of_birth"] = decrypt_data(data["date_of_birth"]) if data["date_of_birth"] else None
        data["alt_phone_number"] = decrypt_data(data["alt_phone_number"]) if data["alt_phone_number"] else None
        data["alt_email"] = decrypt_data(data["alt_email"]) if data["alt_email"] else None
        data["post_code"] = decrypt_data(data["post_code"]) if data["post_code"] else None
        data["identification"] = decrypt_data(data["identification"]) if data["identification"] else None
        data["device_uuid"] = decrypt_data(data["device_uuid"]) if data["device_uuid"] else None
        data["request"] = decrypt_data(data["request"]) if data["request"] else None
        data["logo"] = decrypt_data(data["logo"]) if data["logo"] else None
        data["remote_ip"] = decrypt_data(data["remote_ip"]) if data["remote_ip"] else None
        data["last_login"] = decrypt_data(data["last_login"]) if data["last_login"] else None
        data["referrer"] = decrypt_data(data["referrer"]) if data["referrer"] else None
        data["referral_code"] = decrypt_data(data["referral_code"]) if data["referral_code"] else None
        data["referrals"] = decrypt_data(data["referrals"]) if data["referrals"] else None
        data["transactions"] = decrypt_data(data["transactions"]) if data["transactions"] else None
        data["balance"] = decrypt_data(data["balance"]) if data["balance"] else None
        data["balance_update_status"] = decrypt_data(data["balance_update_status"]) if data["balance_update_status"] else None

        return data

    @classmethod
    def update(cls, user_id, **updates):
        """
        Update a system user's information by user_id.
        """
        # Encrypt fields if they are being updated
        if "first_name" in updates:
            updates["first_name"] = encrypt_data(updates["first_name"])
        if "middle_name" in updates:
            updates["middle_name"] = encrypt_data(updates["middle_name"])
        if "last_name" in updates:
            updates["last_name"] = encrypt_data(updates["last_name"])
        if "alt_phone_number" in updates:
            updates["alt_phone_number"] = encrypt_data(updates["alt_phone_number"])
        if "alt_email" in updates:
            updates["alt_email"] = encrypt_data(updates["alt_email"])
        if "post_code" in updates:
            updates["post_code"] = encrypt_data(updates["post_code"])
        if "identification" in updates:
            updates["identification"] = encrypt_data(updates["identification"])
        if "device_uuid" in updates:
            updates["device_uuid"] = encrypt_data(updates["device_uuid"])
        if "request" in updates:
            updates["request"] = encrypt_data(updates["request"])
        if "logo" in updates:
            updates["logo"] = encrypt_data(updates["logo"])
        if "remote_ip" in updates:
            updates["remote_ip"] = encrypt_data(updates["remote_ip"])
        if "last_login" in updates:
            updates["last_login"] = encrypt_data(updates["last_login"])
        if "referrer" in updates:
            updates["referrer"] = encrypt_data(updates["referrer"])
        if "referral_code" in updates:
            updates["referral_code"] = encrypt_data(updates["referral_code"])
        if "referrals" in updates:
            updates["referrals"] = encrypt_data(updates["referrals"])
        if "transactions" in updates:
            updates["transactions"] = encrypt_data(updates["transactions"])
        if "balance" in updates:
            updates["balance"] = encrypt_data(updates["balance"])
        if "balance_update_status" in updates:
            updates["balance_update_status"] = encrypt_data(updates["balance_update_status"])

        return super().update(user_id, **updates)

    @classmethod
    def delete(cls, user_id):
        """
        Delete a system user by user_id.
        """
        return super().delete(user_id)

#Agent
from datetime import datetime
import uuid

class Agent(BaseModel):
    """
    An Agent represents a user with roles like Consumer or Agent, handling agent-specific data.
    """

    collection_name = "agents"  # Set the collection name

    def __init__(self, tenant_id, business_id, user_id=generate_agent_id(), username=None, first_name=None, middle_name=None, 
                 last_name=None, date_of_birth=None, alt_phone_number=None, alt_email=None, post_code=None, 
                 identification=None, device_uuid=None, request=None, remote_ip=None,
                 referrer=None, referral_code=None, referrals=None, transactions=None, balance=0, balance_update_status=None, 
                 account_status=None, business_email=None):
        
        super().__init__(tenant_id=tenant_id, business_id=business_id, user_id=user_id, username=username)

        self.business_id = business_id
        self.user_id = user_id
        self.tenant_id = encrypt_data(tenant_id) if tenant_id else None
        
        self.username = encrypt_data(username) if username else None  # Encrypt username
        self.hashed_username = hash_data(username) if username else None  # hash username
        
        self.first_name = encrypt_data(first_name) if first_name else None  # Encrypt first name
        self.middle_name = encrypt_data(middle_name) if middle_name else None  # Encrypt middle name
        self.last_name = encrypt_data(last_name) if last_name else None  # Encrypt last name
        self.date_of_birth = encrypt_data(date_of_birth) if date_of_birth else None  # Encrypt date of birth
        self.alt_phone_number = encrypt_data(alt_phone_number) if alt_phone_number else None  # Encrypt alternate phone number
        self.alt_email = encrypt_data(alt_email) if alt_email else None  # Encrypt alternate email
        self.post_code = encrypt_data(post_code) if post_code else None  # Encrypt post code
        self.identification = encrypt_data(identification) if identification else None  # Encrypt identification
        self.device_uuid = encrypt_data(device_uuid) if device_uuid else None  # Encrypt device UUID
        self.request = encrypt_data(request) if request else None  # Encrypt request
        self.remote_ip = encrypt_data(remote_ip) if remote_ip else None  # Encrypt remote IP
        self.referrer = encrypt_data(referrer) if referrer else None  # Encrypt referrer
        self.referral_code = encrypt_data(referral_code) if referral_code else None  # Encrypt referral code
        self.referrals = encrypt_data(referrals) if referrals else []  # Encrypt referrals
        self.transactions = encrypt_data(transactions) if transactions else 0  # Encrypt transactions
        self.balance = encrypt_data(balance) if balance else 0  # Encrypt balance
        self.balance_update_status = encrypt_data(balance_update_status) if balance_update_status else None  # Encrypt balance update status
        self.account_status = encrypt_data(account_status) if account_status else None 

        # Add created and updated timestamps
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def save(self):
        """Save the agent to the MongoDB database."""
        agent_collection = db.get_collection("agents")
        result = agent_collection.insert_one(self.to_dict())
        return (decrypt_data(self.account_status), result.inserted_id)

    def to_dict(self):
        """
        Convert the agent object to a dictionary representation.
        """
        agent_dict = super().to_dict()
        agent_dict.update({
            "user_id": self.user_id,
            "business_id": self.business_id,
            "tenant_id": self.tenant_id,
            "username": self.username,
            "first_name": self.first_name,
            "middle_name": self.middle_name,
            "last_name": self.last_name,
            "date_of_birth": self.date_of_birth,
            "alt_phone_number": self.alt_phone_number,
            "alt_email": self.alt_email,
            "post_code": self.post_code,
            "identification": self.identification,
            "device_uuid": self.device_uuid,
            "request": self.request,
            "remote_ip": self.remote_ip,
            "referrer": self.referrer,
            "referral_code": self.referral_code,
            "referrals": self.referrals,
            "transactions": self.transactions,
            "balance": self.balance,
            "balance_update_status": self.balance_update_status,
            "account_status": self.account_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return agent_dict

    @classmethod
    def get_by_id(cls, user_id):
        """
        Retrieve an agent by user_id.
        """
        try:
            user_id_obj = ObjectId(user_id)
        except Exception as e:
            return None  # Return None if conversion fails (invalid _id format)

        # Query using _id (which is MongoDB's default unique identifier)
        people_collection = db.get_collection(cls.collection_name)
        data = people_collection.find_one({"_id": user_id_obj})

        if not data:
            return None  # Agent not found

        # Convert ObjectId to string for JSON serialization
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["tenant_id"] = data["tenant_id"]

        # Decrypt fields before returning
        data["username"] = decrypt_data(data["username"]) if data["username"] else None
        data["first_name"] = decrypt_data(data["first_name"]) if data["first_name"] else None
        data["middle_name"] = decrypt_data(data["middle_name"]) if data["middle_name"] else None
        data["last_name"] = decrypt_data(data["last_name"]) if data["last_name"] else None
        data["date_of_birth"] = decrypt_data(data["date_of_birth"]) if data["date_of_birth"] else None
        data["alt_phone_number"] = decrypt_data(data["alt_phone_number"]) if data["alt_phone_number"] else None
        data["alt_email"] = decrypt_data(data["alt_email"]) if data["alt_email"] else None
        data["post_code"] = decrypt_data(data["post_code"]) if data["post_code"] else None
        data["identification"] = decrypt_data(data["identification"]) if data["identification"] else None
        data["device_uuid"] = decrypt_data(data["device_uuid"]) if data["device_uuid"] else None
        data["request"] = decrypt_data(data["request"]) if data["request"] else None
        data["remote_ip"] = decrypt_data(data["remote_ip"]) if data["remote_ip"] else None
        data["last_login"] = decrypt_data(data.get("last_login")) if data.get("last_login") else None
        data["referrer"] = decrypt_data(data["referrer"]) if data["referrer"] else None
        data["referral_code"] = decrypt_data(data["referral_code"]) if data["referral_code"] else None
        data["referrals"] = decrypt_data(data["referrals"]) if data["referrals"] else None
        data["transactions"] = decrypt_data(data["transactions"]) if data["transactions"] else None
        data["balance"] = decrypt_data(data["balance"]) if data["balance"] else None
        data["balance_update_status"] = decrypt_data(data["balance_update_status"]) if data["balance_update_status"] else None
        data["account_status"] = decrypt_data(data["account_status"]) if data["account_status"] else None
        data["tenant_id"] = decrypt_data(data["tenant_id"]) if data["tenant_id"] else None
        data["business"] = decrypt_data(data.get("business")) if data.get("business") else None
        data["directors"] = decrypt_data(data.get("directors")) if data.get("directors") else None
        data["uploads"] = decrypt_data(data.get("uploads")) if data.get("uploads") else None
        
        if data.get("hashed_username"):
            data.pop("hashed_username", None)

        return data

    @classmethod
    def get_by_username(cls, username):
        """
        Retrieve an agent by username.
        """
        
        hashed_username = hash_data(username)
        
        people_collection = db.get_collection(cls.collection_name)
        data = people_collection.find_one({"hashed_username": hashed_username})
        
        if not data:
            return False  # Agent not found

        return True

    @classmethod
    def get_user_by_username(cls, username):
        """
        Retrieve an agent by username.
        """
        
        hashed_username = hash_data(username)
        
        people_collection = db.get_collection(cls.collection_name)
        data = people_collection.find_one({"hashed_username": hashed_username})
        
        if not data:
            return False  # Agent not found

        return data

    @classmethod
    def get_by_id_and_business_id(cls, agent_id, business_id, view_only_acess=None):
        """
        Retrieve an agent by ID and business_id.
        """
        
        if view_only_acess is None:
            # Check if the user has 'read' permission
            if not cls.check_permission(cls, 'read', 'agents'):
                raise PermissionError(f"User does not have permission to view {cls.__name__}.")
            
        # Validate and convert user_id to ObjectId
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None  # Invalid ObjectId format
        
        try:
            agent_id_obj = ObjectId(agent_id)
        except Exception:
            return None  # Invalid ObjectId format

        # Query the database
        people_collection = db.get_collection(cls.collection_name)
        data = people_collection.find_one({
            "_id": agent_id_obj, 
            "business_id": business_id_obj})
        
        if not data:
            return None  # Agent not found

        # Convert ObjectIds to strings for JSON serialization
        data["_id"] = str(data["_id"])
        if data.get("business_id"):
            data["business_id"] = str(data["business_id"])

        # Define encrypted fields that need decryption
        encrypted_fields = [
            "username", "first_name", "middle_name", "last_name", "date_of_birth",
            "alt_phone_number", "alt_email", "post_code", "identification", 
            "device_uuid", "request", "remote_ip", "last_login", "referrer",
            "referral_code", "referrals", "transactions", "balance",
            "balance_update_status", "account_status", "tenant_id", "business",
            "directors", "uploads"
        ]
        
        # Decrypt all encrypted fields
        for field in encrypted_fields:
            if data.get(field):
                data[field] = decrypt_data(data[field])
        
        # Remove sensitive hashed data
        data.pop("hashed_username", None)
        
        return data
      
    @classmethod
    def get_by_username_and_business_id(cls, username, business_id):
        """
        Retrieve an agent by username and business_id.
        """
        # Check if the user has 'read' permission
        if not cls.check_permission(cls, 'read', 'agents'):
            raise PermissionError(f"User does not have permission to view {cls.__name__}.")
        
        # Validate and convert user_id to ObjectId
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None  # Invalid ObjectId format
        
        hashed_username = hash_data(username)

        # Query the database
        people_collection = db.get_collection(cls.collection_name)
        data = people_collection.find_one({
            "hashed_username": hashed_username, 
            "business_id": business_id_obj})
        
        if not data:
            return None  # Agent not found

        # Convert ObjectIds to strings for JSON serialization
        data["_id"] = str(data["_id"])
        if data.get("business_id"):
            data["business_id"] = str(data["business_id"])

        # Define encrypted fields that need decryption
        encrypted_fields = [
            "username", "first_name", "middle_name", "last_name", "date_of_birth",
            "alt_phone_number", "alt_email", "post_code", "identification", 
            "device_uuid", "request", "remote_ip", "last_login", "referrer",
            "referral_code", "referrals", "transactions", "balance",
            "balance_update_status", "account_status", "tenant_id", "business",
            "directors", "uploads"
        ]
        
        # Decrypt all encrypted fields
        for field in encrypted_fields:
            if data.get(field):
                data[field] = decrypt_data(data[field])
        
        # Remove sensitive hashed data
        data.pop("hashed_username", None)
        
        return data
        
    @classmethod
    def get_agents_business_id(cls, business_id, page=1, per_page=10):
        """
        Retrieve agents by business_id with pagination.

        Returns:
            {
                "agents": [ ... ],
                "total_count": int,
                "total_pages": int,
                "current_page": int,
                "per_page": int
            }
        Raises:
            PermissionError: if user lacks 'read' permission on agents.
            ValueError: if business_id is not a valid ObjectId string.
        """
        # Permission check (kept from your original)
        if not cls.check_permission(cls, "read", "agents"):
            raise PermissionError(f"User does not have permission to view {cls.__name__}.")

        # Validate and convert business_id to ObjectId (align with example: raise ValueError)
        if isinstance(business_id, str):
            try:
                business_id_obj = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e
        elif isinstance(business_id, ObjectId):
            business_id_obj = business_id
        else:
            raise ValueError(f"Invalid business_id type: {type(business_id).__name__}")

        # Pagination defaults (from ENV, like your example)
        default_page = os.getenv("DEFAULT_PAGINATION_PAGE", 1)
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10)

        page = int(page) if page else int(default_page)
        per_page = int(per_page) if per_page else int(default_per_page)

        # Query + pagination
        people_collection = db.get_collection(cls.collection_name)
        query = {"business_id": business_id_obj}

        total_count = people_collection.count_documents(query)
        cursor = (
            people_collection.find(query)
            .skip((page - 1) * per_page)
            .limit(per_page)
        )

        # Fields to decrypt (from your original)
        encrypted_fields = [
            "username", "first_name", "middle_name", "last_name", "date_of_birth",
            "alt_phone_number", "alt_email", "post_code", "identification",
            "device_uuid", "request", "remote_ip", "last_login", "referrer",
            "referral_code", "referrals", "transactions", "balance",
            "balance_update_status", "account_status", "tenant_id", "business",
            "directors", "uploads"
        ]

        agents = []
        for doc in cursor:
            # Convert ObjectIds to strings (be defensive about presence)
            if "_id" in doc:
                doc["_id"] = str(doc["_id"])
            if doc.get("business_id"):
                doc["business_id"] = str(doc["business_id"])

            # If your schema includes other ObjectId fields, convert them here as needed
            # e.g., doc["user_id"] = str(doc["user_id"]) if doc.get("user_id") else None

            # Decrypt encrypted fields if present
            for field in encrypted_fields:
                if doc.get(field):
                    doc[field] = decrypt_data(doc[field])

            # Remove sensitive hashed data
            doc.pop("hashed_username", None)

            agents.append(doc)

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "agents": agents,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def get_by_phone_number(cls, username):
        """
        Retrieve an agent by phone_number.
        """
        
        hashed_username = hash_data(username)
        
        people_collection = db.get_collection(cls.collection_name)
        data = people_collection.find_one({"hashed_username": hashed_username})

        if not data:
            return False  # Agent not found

        return data

    @classmethod
    def update(cls, user_id, **updates):
        """
        Update an agent's information by user_id using the updated AgentSchema.
        """
        # Encrypt fields if they are being updated
        if "first_name" in updates:
            updates["first_name"] = encrypt_data(updates["first_name"])
        if "middle_name" in updates:
            updates["middle_name"] = encrypt_data(updates["middle_name"])
        if "last_name" in updates:
            updates["last_name"] = encrypt_data(updates["last_name"])
        if "alt_phone_number" in updates:
            updates["alt_phone_number"] = encrypt_data(updates["alt_phone_number"])
        if "alt_email" in updates:
            updates["alt_email"] = encrypt_data(updates["alt_email"])
        if "post_code" in updates:
            updates["post_code"] = encrypt_data(updates["post_code"])
        if "identification" in updates:
            updates["identification"] = encrypt_data(updates["identification"])
        if "device_uuid" in updates:
            updates["device_uuid"] = encrypt_data(updates["device_uuid"])
        if "request" in updates:
            updates["request"] = encrypt_data(updates["request"])
        if "remote_ip" in updates:
            updates["remote_ip"] = encrypt_data(updates["remote_ip"])
        if "last_login" in updates:
            updates["last_login"] = encrypt_data(updates["last_login"])
        if "referrer" in updates:
            updates["referrer"] = encrypt_data(updates["referrer"])
        if "referral_code" in updates:
            updates["referral_code"] = encrypt_data(updates["referral_code"])
        if "referrals" in updates:
            updates["referrals"] = encrypt_data(updates["referrals"])
        if "transactions" in updates:
            updates["transactions"] = encrypt_data(updates["transactions"])
        if "balance" in updates:
            updates["balance"] = encrypt_data(updates["balance"])
        if "balance_update_status" in updates:
            updates["balance_update_status"] = encrypt_data(updates["balance_update_status"])
            

        # Check if business-related fields are being updated
        if "business" in updates:
            updates["business"] = encrypt_data(updates["business"])
            

        # Check if account status-related fields are being updated
        if "account_status" in updates:
            updates["account_status"] = encrypt_data(updates["account_status"])

        return super().update(user_id, **updates)

    @classmethod
    def update_info_agent_by_id(cls, agent_id, **updates):

        #check if edit permission user has permission to perform this activity
        # Check if the user has 'edit' permission
        if not cls.check_permission(cls, 'edit', 'agents'):
            raise PermissionError(f"User does not have permission to edit {cls.__name__}.")
        
        agents_collection = db.get_collection("agents")
        users_collection = db.get_collection("users")

        # Always update timestamp
        updates["updated_at"] = datetime.now()

        # Make sure username exists before encryption
        if "username" in updates and updates["username"]:
            username_raw = updates["username"]
            encrypted_username = encrypt_data(updates["username"])
            if not isinstance(encrypted_username, str):
                raise ValueError("encrypt_data() must return a string")
            
            business_id = updates["business_id"]
            
            agent_data = dict()
            agent_data["username"] = encrypted_username
            agent_data["hashed_username"] = hash_data(username_raw)

        # Update agent
        agent_result = agents_collection.update_one(
            {
                "_id": ObjectId(agent_id), 
                "business_id": ObjectId(business_id)}, 
            {"$set": agent_data}
        )
        agent_updated = agent_result.modified_count > 0
        Log.info(f"agent_updated: {agent_updated}")
        
        user_data = dict()
        user_data["username"] = encrypted_username
        user_data["username_hashed"] = hash_data(username_raw)
        

        # Update related user
        user_result = users_collection.update_one(
            {
                "agent_id": ObjectId(agent_id), 
                "business_id": ObjectId(business_id)}, 
            {"$set": user_data}
        )
        user_updated = user_result.modified_count > 0

        if agent_updated:
            Log.info("[people_model][update_info_agent_by_id] agent username updated")
            
        if user_updated:
            Log.info("[people_model][update_info_agent_by_id] user username updated")

        
        return agent_updated and user_updated
    
    
    @classmethod
    def delete(cls, user_id):
        """
        Delete an agent by user_id.
        """
        return super().delete(user_id)

    @staticmethod
    def update_account_status_by_agent_id(agent_id, ip_address, field, update_value):
        """Update a specific field in the 'account_status' for the given agent ID."""
        agents_collection = db.get_collection("agents")  # Using the 'agents' collection instead of 'users'
        
        # Search for the agent by agent_id
        agent = agents_collection.find_one({"_id": ObjectId(agent_id)})
        
        if not agent:
            return {"success": False, "message": "Agent not found"}  # Agent not found
        
        # Get the encrypted account_status field from the agent document
        encrypted_account_status = agent.get("account_status", None)
        
        # Check if account_status is None
        if encrypted_account_status is None:
            return {"success": False, "message": "Account status not found"}
        
        # Decrypt the account_status field
        try:
            account_status = decrypt_data(encrypted_account_status)  # Assuming decrypt_data is correct
        except Exception as e:
            return {"success": False, "message": f"Error decrypting account status: {str(e)}"}
        
        # Flag to track if the field was updated
        field_updated = False
        
        # Loop through account_status and find the specific field to update
        for status in account_status:
            if field in status:
                # Update the field's status, created_at, and ip_address
                status[field]["status"] = update_value  # Set the status to update_value
                status[field]["created_at"] = datetime.utcnow().isoformat()  # Convert datetime to ISO string
                status[field]["ip_address"] = ip_address  # Add the IP address
                field_updated = True  # Mark as updated
                break  # Exit loop once found and updated
        
        # If the field was not found
        if not field_updated:
            return {"success": False, "message": f"Field '{field}' not found in account status"}
        
        # Re-encrypt the updated account_status before saving back
        try:
            encrypted_account_status = encrypt_data(account_status)  # Assuming encrypt_data is correct
        except Exception as e:
            return {"success": False, "message": f"Error encrypting account status: {str(e)}"}
        
        # Update the 'account_status' in the database
        result = agents_collection.update_one(
            {"_id": ObjectId(agent_id)},  # Search condition
            {"$set": {"account_status": encrypted_account_status}}  # Update operation
        )
        
        # Return success or failure of the update operation
        if result.matched_count > 0:
            return {"success": True, "message": "Account status updated successfully"}
        else:
            return {"success": False, "message": "Failed to update account status"}

    @staticmethod
    def update_business_kyc_by_agent_id(**business_details):
        """Update or add specific business KYC fields for the given agent ID."""
        agents_collection = db.get_collection("agents")  # Using the 'agents' collection instead of 'users'
        agent_id = business_details.get("agent_id")
        
        # Search for the agent by agent_id
        agent = agents_collection.find_one({"_id": ObjectId(agent_id)})
        
        if not agent:
            return {"success": False, "message": "Agent not found"}  # Agent not found
        
        # Get the encrypted business field from the agent document
        encrypted_business = agent.get("business", None)
        
        hashed_business_email= None
        hashed_contact_person_phone_number= None
        
        # If business details are not found, we initialize a new business entry
        if encrypted_business is None:
            # Initialize the business field with the new details
            business = [{
                "business_name": business_details.get("business_name", ""),
                "business_email": business_details.get("business_email", ""),
                "business_address": business_details.get("business_address", ""),
                "contact_person_fullname": business_details.get("contact_person_fullname", ""),
                "contact_person_phone_number": business_details.get("contact_person_phone_number", ""),
                "referral_code": business_details.get("referral_code", "")
            }]
        else:
            # Decrypt the business field if it already exists
            try:
                business = decrypt_data(encrypted_business)
            except Exception as e:
                return {"success": False, "message": f"Error decrypting business details: {str(e)}"}
            
            # Flag to track if the field was updated
            field_updated = False
            
            
            # Loop through business and find the specific field to update
            for business_entry in business:
                # Update the business KYC details if field exists
                business_entry["business_name"] = business_details.get("business_name", business_entry.get("business_name"))
                business_entry["business_email"] = business_details.get("business_email", business_entry.get("business_email"))
                business_entry["business_address"] = business_details.get("business_address", business_entry.get("business_address"))
                business_entry["contact_person_fullname"] = business_details.get("contact_person_fullname", business_entry.get("contact_person_fullname"))
                business_entry["contact_person_phone_number"] = business_details.get("contact_person_phone_number", business_entry.get("contact_person_phone_number"))
                business_entry["referral_code"] = business_details.get("referral_code", business_entry.get("referral_code"))
        
                field_updated = True  # Mark as updated
                break  # Exit loop once found and updated
            
            # If the field was not found
            if not field_updated:
                return {"success": False, "message": f"Business details not found for agent {agent_id}"}
        
        # Re-encrypt the updated business field before saving back
        try:
            encrypted_business = encrypt_data(business)
        except Exception as e:
            return {"success": False, "message": f"Error encrypting business details: {str(e)}"}
        
        if business_details.get("business_email"):
                hashed_business_email = hash_data(business_details.get("business_email"))
                
        if business_details.get("contact_person_phone_number"):
                hashed_contact_person_phone_number = hash_data(business_details.get("contact_person_phone_number"))
                
         
                
        # Update or set the 'business' field in the database
        update_fields = {
            "business": encrypted_business
        }

        if hashed_business_email is not None:
            update_fields["hashed_business_email"] = hashed_business_email

        if hashed_contact_person_phone_number is not None:
            update_fields["hashed_contact_person_phone_number"] = hashed_contact_person_phone_number

        result = agents_collection.update_one(
            {"_id": ObjectId(agent_id)},
            {"$set": update_fields}
        )
        
        # Return success or failure of the update operation
        if result.matched_count > 0:
            return {"success": True, "message": "Business KYC details updated successfully"}
        else:
            return {"success": False, "message": "Failed to update business KYC details"}

    @staticmethod
    def check_agent_business_email_exists(agent_id, business_email):
        """Check if Agent business email already exists"""
        agents_collection = db.get_collection("agents")
        
        # Search for the agent by agent_id
        agent = agents_collection.find_one({"_id": ObjectId(agent_id)})
        
        if not agent:
            return {"success": False, "message": "Agent not found"}
        
        # Get the encrypted business field from the agent document
        encrypted_business = agent.get("business", None)
        
        # If business details exist, check if business_email already exists
        if encrypted_business is not None:
            try:
                business = decrypt_data(encrypted_business)
                
                # Normalize the input business_email (strip spaces and convert to lowercase)
                normalized_input_email = business_email.strip().lower() if business_email else ""
                
                # Check if business_email already exists in any business entry
                for business_entry in business:
                    existing_email = business_entry.get("business_email")
                    if existing_email:
                        # Normalize existing email (strip spaces and convert to lowercase)
                        normalized_existing_email = existing_email.strip().lower()
                        
                        if normalized_existing_email == normalized_input_email:
                            return {"success": False, "message": "Business email already exists, agent will not be updated"}
            except Exception as e:
                return {"success": False, "message": f"Error decrypting business details: {str(e)}"}
        
        return {"success": True, "message": "Business email does not exist, agent can be updated"}

    @staticmethod
    def update_director_id_info_by_agent_id(**director_details):
        """Update or add specific director KYC fields for the given agent ID."""
        agents_collection = db.get_collection("agents")  # Using the 'agents' collection instead of 'users'
        agent_id = director_details.get("agent_id")
        
        # Search for the agent by agent_id
        agent = agents_collection.find_one({"_id": ObjectId(agent_id)})
        
        if not agent:
            return {"success": False, "message": "Agent not found"}  # Agent not found
        
        # Get the encrypted directors field from the agent document
        encrypted_directors = agent.get("directors", None)
        
        # If directors details are not found, initialize a new directors entry
        if encrypted_directors is None:
            # Initialize the directors field with the new details
            directors = [{
                "fullname": director_details.get("fullname", ""),
                "phone_number": director_details.get("phone_number", ""),
                "id_type": director_details.get("id_type", ""),
                "id_number": director_details.get("id_number", ""),
                "id_front_image": director_details.get("id_front_image", None),
                "id_front_image_file_path": director_details.get("id_front_image_file_path", ""),
                "id_back_image": director_details.get("id_back_image", None),
                "id_back_image_file_path": director_details.get("id_back_image_file_path", ""),
                "proof_of_address": director_details.get("proof_of_address", None),
                "proof_of_address_file_path": director_details.get("proof_of_address_file_path", "")
            }]
        else:
            # Decrypt the directors field if it already exists
            try:
                directors = decrypt_data(encrypted_directors)
            except Exception as e:
                return {"success": False, "message": f"Error decrypting director details: {str(e)}"}
            
            # Flag to track if the field was updated
            field_updated = False
            
            # Loop through directors and find the specific director to update
            for director_entry in directors:
                # Check if the director already exists and update the fields
                if director_entry.get("phone_number") == director_details.get("phone_number"):
                    director_entry["phone_number"] = director_details.get("phone_number", director_entry.get("phone_number"))
                    director_entry["id_type"] = director_details.get("id_type", director_entry.get("id_type"))
                    director_entry["id_number"] = director_details.get("id_number", director_entry.get("id_number"))
                    director_entry["id_front_image"] = director_details.get("id_front_image", director_entry.get("id_front_image"))
                    director_entry["id_front_image_file_path"] = director_details.get("id_front_image_file_path", director_entry.get("id_front_image_file_path"))
                    director_entry["id_back_image"] = director_details.get("id_back_image", director_entry.get("id_back_image"))
                    director_entry["id_back_image_file_path"] = director_details.get("id_back_image_file_path", director_entry.get("id_back_image_file_path"))
                    director_entry["proof_of_address"] = director_details.get("proof_of_address", director_entry.get("proof_of_address"))
                    director_entry["proof_of_address_file_path"] = director_details.get("proof_of_address_file_path", director_entry.get("proof_of_address_file_path"))
                    
                    field_updated = True  # Mark as updated
                    break  # Exit loop once found and updated
            
            # If the director was not found, append the new director information
            if not field_updated:
                directors.append({
                    "fullname": director_details.get("fullname", ""),
                    "phone_number": director_details.get("phone_number", ""),
                    "id_type": director_details.get("id_type", ""),
                    "id_number": director_details.get("id_number", ""),
                    "id_front_image": director_details.get("id_front_image", None),
                    "id_front_image_file_path": director_details.get("id_front_image_file_path", ""),
                    "id_back_image": director_details.get("id_back_image", None),
                    "id_back_image_file_path": director_details.get("id_back_image_file_path", ""),
                    "proof_of_address": director_details.get("proof_of_address", ""),
                    "proof_of_address_file_path": director_details.get("proof_of_address_file_path", ""),
                })

        # Re-encrypt the updated directors field before saving back
        try:
            encrypted_directors = encrypt_data(directors)
        except Exception as e:
            return {"success": False, "message": f"Error encrypting director details: {str(e)}"}
        
        # Update or set the 'directors' field in the database
        result = agents_collection.update_one(
            {"_id": ObjectId(agent_id)},  # Search condition
            {"$set": {"directors": encrypted_directors}}  # Update operation
        )
        
        # Return success or failure of the update operation
        if result.matched_count > 0:
            return {"success": True, "message": "Director KYC details updated successfully"}
        else:
            return {"success": False, "message": "Failed to update director KYC details"}

    @staticmethod
    def update_agent_edd_info_by_agent_id(**director_details):
        """Update or add EDD questionnaire fields for the given agent ID."""
        agents_collection = db.get_collection("agents")  # Using the 'agents' collection
        agent_id = director_details.get("agent_id")

        # Search for the agent by agent_id
        agent = agents_collection.find_one({"_id": ObjectId(agent_id)})

        if not agent:
            return {"success": False, "message": "Agent not found"}

        # Get the encrypted uploads field from the agent document
        encrypted_uploads = agent.get("uploads", None)

        # If uploads data is not found, initialize with EDD fields
        if encrypted_uploads is None:
            uploads = {
                "edd_questionnaire": director_details.get("edd_questionnaire", None),
                "edd_questionnaire_file_path": director_details.get("edd_questionnaire_file_path", "")
            }
        else:
            # Decrypt the uploads field if it already exists
            try:
                uploads = decrypt_data(encrypted_uploads)
            except Exception as e:
                return {"success": False, "message": f"Error decrypting uploads data: {str(e)}"}

            # Update only the EDD fields
            uploads["edd_questionnaire"] = director_details.get("edd_questionnaire", uploads.get("edd_questionnaire", None))
            uploads["edd_questionnaire_file_path"] = director_details.get("edd_questionnaire_file_path", uploads.get("edd_questionnaire_file_path", ""))

        # Re-encrypt the uploads field
        try:
            encrypted_uploads = encrypt_data(uploads)
        except Exception as e:
            return {"success": False, "message": f"Error encrypting uploads data: {str(e)}"}

        try:
            # Update the 'uploads' field in the database
            result = agents_collection.update_one(
                {"_id": ObjectId(agent_id)},
                {"$set": {"uploads": encrypted_uploads}}
            )
        except Exception as e:
            return {"success": False, "message": f"Error updating EDD Questionnaire: {str(e)}"}

        # Return success or failure of the update operation
        if result.matched_count > 0:
            return {"success": True, "message": "EDD questionnaire updated successfully"}
        else:
            return {"success": False, "message": "Failed to update EDD questionnaire"}
  
    
class Client:
    @staticmethod
    def create_client(client_id, client_secret):
        client_collection = db.get_collection("clients")
        client_collection.insert_one({"client_id": client_id, "client_secret": client_secret})

    @staticmethod
    def get_client(client_id, client_secret):
        client_collection = db.get_collection("clients")
        return client_collection.find_one({"client_id": client_id, "client_secret": client_secret})


class Token:
    @staticmethod
    def create_token(client_id, access_token, refresh_token, expires_in, refresh_expires_in):
        db.tokens.insert_one({
            "client_id": client_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "refresh_expires_in": refresh_expires_in
        })

    @staticmethod
    def get_token(access_token):
        return db.tokens.find_one({"access_token": access_token})

    @staticmethod
    def get_refresh_token(refresh_token):
        return db.tokens.find_one({"refresh_token": refresh_token})