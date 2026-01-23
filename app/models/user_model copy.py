import bcrypt
from bson.objectid import ObjectId
from datetime import datetime
from app.extensions.db import db
from ..utils.logger import Log # import logging
from ..utils.generators import generate_promo_code, generate_agent_id
from ..utils.crypt import encrypt_data, decrypt_data, hash_data
ENCRYPT_AT_REST = {"status"}


                   
class User:
    def __init__(self, phone_number, password, client_id, business_id, fullname=None, email=None, 
                 status="Inactive", admin_id=None, email_verified=None, account_type=None, 
                 username=None, system_user_id=None, role = None, tenant_id=None, type=None, 
                 last_login=None, referral_code=None, device_id=None, location=None, 
                 ip_address=None, created_by=None):
        
        self.system_user_id = ObjectId(system_user_id) if system_user_id else None
        self.role = ObjectId(role) if role else None
        if admin_id is not None and admin_id is not "":
            self.admin_id = ObjectId(admin_id)
        if created_by is not None:
            self.created_by = ObjectId(created_by)
        self.user_id = generate_agent_id() # generate temporary user id. it will be overriden later
        self.tenant_id = tenant_id if tenant_id is not None else None
        self.business_id = ObjectId(business_id)
        self.fullname = encrypt_data(fullname) if fullname else None
        
        # ----------------------
        # DEVICES COLLECTION
        # ----------------------
        self.devices = []
        self.device_id = device_id if device_id else None
        # If a device_id is provided at registration, add it into devices[]
        if device_id is not None or ip_address is not None:
            self.add_device(device_id, ip_address)
          
        # ----------------------
        # LOCATIONS COLLECTION
        # ----------------------
        self.location = location if location else None   
        # 🔹 locations collection
        self.locations = []
        if location:
            self.add_location(
                latitude=location.get("latitude"),
                longitude=location.get("longitude"),
            )
        
        self.username = encrypt_data(username) if username else None
        self.username_hashed = hash_data(username) if username else None
        
        self.email = encrypt_data(email) if email else None 
        self.email_hashed = hash_data(email) if email else None 
        self.phone_number = encrypt_data(phone_number) 
        self.status = encrypt_data(status)
        self.account_type = encrypt_data(account_type) if account_type else None
        self.account_type = encrypt_data(account_type) if account_type else None
        self.type = encrypt_data(type) if type else None
        self.client_id = encrypt_data(client_id)
        self.client_id_hashed = hash_data(client_id)
           # ✅ Only hash the password if it's not already hashed
        if not password.startswith("$2b$"):
            self.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        else:
            self.password = password  # If already hashed, store as is
        self.email_verified = email_verified if email_verified else None
        self.last_login = last_login if last_login else None
        # promo code settings
        self.referrals = []
        self.transactions = 0
        self.referral_code = encrypt_data(referral_code) if referral_code else None
        # promo code settings
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    #magic method discribing the object
    def __str__(self):
         return f"User with fullname {self.fullname} and email {self.email}"
    
    def to_dict(self):
        
        user_object = {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "role": self.role,
            "type": self.type,
            "business_id": self.business_id,
            "fullname": self.fullname,
            "phone_number": self.phone_number,
            "username": self.username,
            "username_hashed": self.username_hashed,
            "email": self.email,
            "email_hashed": self.email_hashed,
            "status": self.status,
            "account_type": self.account_type,
            "client_id": self.client_id,
            
            "devices": self.devices,
            "locations": self.locations,
            
            "client_id_hashed": self.client_id_hashed,
            "password": self.password,
            "email_verified": self.email_verified,
            "transactions": self.transactions,
            "referrals": self.referrals,
            "referral_code": self.referral_code,
            "last_login": self.last_login,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.system_user_id:
            user_object["system_user_id"] = self.system_user_id
            
        if self.admin_id:
            user_object["admin_id"] = self.admin_id
        if self.created_by:
            user_object["created_by"] = self.created_by
            
        return user_object
    
    def save(self):
            """Save the user to the MongoDB database."""
            users_collection = db.get_collection("users")
            result = users_collection.insert_one(self.to_dict())
            return result.inserted_id
    
    # 🔹 Helper method to add a device into the collection
    def add_device(self, device_id, ip_address=None):
        """
        Add a device to this user's devices collection.
        You can also call this later to append new devices.
        """
        if not device_id:
            return

        device_obj = {
            "_id": ObjectId(),              
            "device_id": encrypt_data(device_id),
            "hashed_device_id": hash_data(device_id),
            "ip_address": encrypt_data(ip_address),
            "registered_at": datetime.now(),
        }

        self.devices.append(device_obj)
    
    # 🔹 instance helper: add a location into self.locations
    def add_location(self, latitude, longitude):
        location_object = {
            "_id": ObjectId(),
            "latitude": encrypt_data(str(latitude)),
            "longitude": encrypt_data(str(longitude)),
            "captured_at": datetime.now(),
        }
        self.locations.append(location_object)

    @staticmethod
    def verify_password(email, password):
        hashed_email = hash_data(email)
        user = db.get_collection("users").find_one({"email_hashed": hashed_email})

        if not user:
            print("❌ User not found")
            return False

        stored_hash = user["password"]
        
        # Verify password
        if bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
            print("✅ Password match successful")
            return True
        else:
            print("❌ Password mismatch")
            return False

    @staticmethod
    def email_verification_needed(email):
        """
        Select user by email
        """
        hashed_email = hash_data(email)
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"email_hashed": hashed_email})
        
        if user.get('email_verified') != 'verified':
            return True  # Email verification needed
        else:
            return False  # No email verification needed
    
    @staticmethod
    def update_auth_code(email, auth_code):
        """Update only the auth_code for the given user by email."""
        users_collection = db.get_collection("users")
        hashed_email = hash_data(email)
        
        # Search for the user by hashed email
        user = users_collection.find_one({"email_hashed": hashed_email})
        
        if not user:
            return False  # User not found
        
        # Update only the auth_code field
        auth_code_hashed = hash_data(auth_code)
        result = users_collection.update_one(
            {"email_hashed": hashed_email},  # Search condition
            {"$set": {"auth_code": auth_code_hashed}}  # Update operation
        )
        
        # Return success or failure of the update operation
        if result.matched_count > 0:
            return True  # Update successful
        else:
            return False  # No document matched (should not happen if email exists)

    @staticmethod
    def get_auth_code(auth_code):
        # Search for the user by auth_code
        hashed_token = hash_data(auth_code)
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"auth_code": hashed_token})
        if not user:
            print("❌ User not found")
            return False  # User not found

        print("✅ User found")
        return user
    
    @staticmethod
    def update_user_status(email_hashed):
        """Update only the auth_code for the given user by email."""
        users_collection = db.get_collection("users")
        # Search for the user by hashed email
        user = users_collection.find_one({"email_hashed": email_hashed})
        
        if not user:
            return False  # User not found
        
        # Update only the status field
        result = users_collection.update_one(
            {"email_hashed": email_hashed},  # Search condition
            {"$set": {"status": encrypt_data("Active"), 'email_verified': "verified"}, 
             "$unset": {"auth_code": ""}}  # Update operation
        )
        
        # Return success or failure of the update operation
        if result.matched_count > 0:
            return True  # Update successful
        else:
            return False  # No document matched (should not happen if email exists)

    @staticmethod
    def update_last_login(
        *,
        subscriber_id: str | ObjectId,
        ip_address: str | None = None
    ) -> bool:
        """
        Update the subscriber's last login timestamp and append a record to login_history.

        Args:
            subscriber_id (str | ObjectId): MongoDB ObjectId of the subscriber.
            ip_address (str, optional): IP address of the login source.

        Returns:
            bool: True if the update succeeded, False if subscriber not found.

        Example:
            UserModel.update_last_login(
                subscriber_id="68dd57a2cb9ce2d79c6a805f",
                ip_address="192.168.1.10"
            )
        """
        users_collection = db.get_collection("users")

        # Ensure valid ObjectId
        if not subscriber_id:
            raise ValueError("subscriber_id is required")
        if not isinstance(subscriber_id, ObjectId):
            subscriber_id = ObjectId(subscriber_id)

        # Prepare login info
        current_time = datetime.utcnow().isoformat()
        login_entry = {
            "timestamp": current_time,
            "ip_address": ip_address or "unknown"
        }

        # Update 'last_login' and push to 'login_history'
        update_doc = {
            "$set": {"last_login": current_time},
            "$push": {"login_history": login_entry}
        }

        result = users_collection.update_one({"subscriber_id": subscriber_id}, update_doc)
        return result.matched_count > 0
    
    @staticmethod
    def update_agent_last_login(
        *,
        agent_id: str | ObjectId,
        ip_address: str | None = None
    ) -> bool:
        """
        Update the subscriber's last login timestamp and append a record to login_history.

        Args:
            subscriber_id (str | ObjectId): MongoDB ObjectId of the subscriber.
            ip_address (str, optional): IP address of the login source.

        Returns:
            bool: True if the update succeeded, False if subscriber not found.

        Example:
            UserModel.update_last_login(
                agent_id="68dd57a2cb9ce2d79c6a805f",
                ip_address="192.168.1.10"
            )
        """
        users_collection = db.get_collection("users")

        # Ensure valid ObjectId
        if not agent_id:
            raise ValueError("agent_id is required")
        if not isinstance(agent_id, ObjectId):
            agent_id = ObjectId(agent_id)

        # Prepare login info
        current_time = datetime.utcnow().isoformat()
        login_entry = {
            "timestamp": current_time,
            "ip_address": ip_address or "unknown"
        }

        # Update 'last_login' and push to 'login_history'
        update_doc = {
            "$set": {"last_login": current_time},
            "$push": {"login_history": login_entry}
        }

        result = users_collection.update_one({"agent_id": agent_id}, update_doc)
        return result.matched_count > 0
    
    @staticmethod
    def get_user_by_email(email):
        """
        Select user by email
        """
        hashed_email = hash_data(email)
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"email_hashed": hashed_email})
        if not user:
            return None  # User not found
        
        user.pop("password", None)
        return user
    
    @staticmethod
    def get_user_by_username(username):
        """
        Select user by username
        """
        hashed_username = hash_data(username)
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"username_hashed": hashed_username})
        if not user:
            return None  # User not found
        
        user.pop("password", None)
        return user
     
    @staticmethod
    def get_user_role(role_id):
        """
        Select role by role_id
        """
        collection = db.get_collection("roles")
        role = collection.find_one({"_id": role_id})
        if not role:
            return None  # User not found
        return role
   
    @staticmethod
    def get_user_by_user__id(user_id):
        """
        Select user by user_id
        """
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            return None  # User not found
        return user
    
    @staticmethod
    def update_user_promo_mechanism(user_id, promo):
        """
        Update user transactions and update a specific promo in user.promos
        """
        users_collection = db.get_collection("users")

        # Fetch user
        user = users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            Log.error("User not found.")
            return False

        # Calculate new balance
        current_balance = float(user.get("transactions", 0))
        new_balance = current_balance + float(promo.get("promo_amount", 0))

        Log.info(f"new_balance: {new_balance}")

        # Update promos list
        updated_promos = []
        target_promo_id = str(promo.get("promo_id"))

        for p in user.get("promos", []):
            if str(p.get("promo_id")) == target_promo_id:
                # decrement promo_left
                p["promo_left"] = max(0, int(p.get("promo_left", 0)) - 1)
            updated_promos.append(p)

        # Build update payload
        update_data = {
            "transactions": new_balance,
            "promos": updated_promos,
            "updated_at": datetime.utcnow()
        }

        # Save updates
        result = users_collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": update_data}
        )

        if result.modified_count > 0:
            Log.info("[user_model.py][update_user_promo_mechanism] User promo and balance updated successfully.")
            return True

        Log.warning("[user_model.py][update_user_promo_mechanism] No changes were made to the user.")
        return False

    @staticmethod
    def confirm_user_pin(user__id, pin, account_type=None):
        """
        Validate a PIN by hashing it and checking it against the stored hashed PIN.
        """

        if pin is None:
            print("❌ PIN is required")
            return False

        # Hash the PIN for lookup
        hashed_pin = hash_data(pin)

        users_collection = db.get_collection("users")

        if str.lower(account_type) == "agent":
            # Look up by hashed PIN
            user = users_collection.find_one({"agent_id": ObjectId(user__id), "pin": hashed_pin})
            
        elif str.lower(account_type) == "subscriber":
            # Look up by hashed PIN
            user = users_collection.find_one({"subscriber_id": ObjectId(user__id), "pin": hashed_pin})

        if not user:
            print("❌ Invalid PIN")
            return False

        print("✅ PIN matched, user found")
        return user
  
    @staticmethod
    def get_by_id(_id, business_id):
        """
        Select user by ID
        """
        user_id_obj = None
        business_id_obj = None
        try:
            user_id_obj = ObjectId(_id)
            business_id_obj = ObjectId(business_id)
        except Exception as e:
            pass
        
        users_collection = db.get_collection("users")
        user = users_collection.find_one({
            "_id": ObjectId(user_id_obj),
            "business_id": ObjectId(business_id_obj)
        })
        if not user:
            return None  # User not found
        return user
    
    
    @staticmethod
    def get_user_by_agent_id(agent_id):
        """
        Select user by agent_id
        """
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"agent_id": ObjectId(agent_id)})
        if not user:
            return None  # User not found
        return user
    
    @staticmethod
    def get_user_by_system_user_id(system_user_id):
        """
        Select user by agent_id
        """
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"system_user_id": ObjectId(system_user_id)})
        if not user:
            return None  # User not found
        return user
    
    @staticmethod
    def get_user_by_subscriber_id(subscriber_id):
        """
        Select user by subscriber
        """
        try:
            subscriber_id = ObjectId(subscriber_id)
        except Exception as e:
            pass
        
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"subscriber_id": subscriber_id})
        if not user:
            return None  # User not found
        return user
    
    @staticmethod
    def get_system_user_by__id(system_user_id):
        """
        Select user by agent_id
        """
        users_collection = db.get_collection("system_users")
        user = users_collection.find_one({"_id": ObjectId(system_user_id)})
        if not user:
            return None  # User not found
        return user
    
    @staticmethod
    def update_account_pin_by_agent_id(agent_id, pin):
        """Update only the auth_code for the given user by email."""
        users_collection = db.get_collection("users")
        
        # Search for the user by hashed email
        user = users_collection.find_one({"agent_id": ObjectId(agent_id)})
        
        if not user:
            return False  # User not found
        
        # Update only the pin field
        email_hashed = user.get("email_hashed")
        hashed_pin = hash_data(pin)
        
        result = users_collection.update_one(
            {"email_hashed": email_hashed},  # Search condition
            {"$set": {"pin": hashed_pin}}  # Update operation
        )
        
        # Return success or failure of the update operation
        if result.matched_count > 0:
            return True  # Update successful
        else:
            return False  # No document matched (should not happen if email exists)

    @staticmethod
    def update_account_pin_by_subscriber_id(subscriber_id, pin):
        """Update only the auth_code for the given user by email."""
        users_collection = db.get_collection("users")
        
        # Search for the user by hashed email
        user = users_collection.find_one({"subscriber_id": ObjectId(subscriber_id)})
        
        if not user:
            return False  # User not found
        
        # Update only the pin field
        username_hashed = user.get("username_hashed")
        hashed_pin = hash_data(pin)
        
        result = users_collection.update_one(
            {"username_hashed": username_hashed},  # Search condition
            {"$set": {"pin": hashed_pin}}  # Update operation
        )
        
        # Return success or failure of the update operation
        if result.matched_count > 0:
            return True  # Update successful
        else:
            return False  # No document matched (should not happen if email exists)

    @classmethod
    def check_multiple_item_exists(cls, business_id, fields: dict):
        """
        Check if a beneficiary exists based on multiple fields (e.g., phone, user_id, email).
        This method allows dynamic checks for any number of fields using hashed values.

        :param business_id: The ID of the business.
        :param fields: Dictionary of fields to check (e.g., {"phone": "123456789", "user_id": "abc123"}).
        :return: True if the beneficiary exists, False otherwise.
        """
        try:
            # Ensure business_id is ObjectId
            try:
                business_id_obj = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e

            # Start building the query
            query = {"business_id": business_id_obj}

            # Hash each field value dynamically
            for key, value in fields.items():
                hashed_value = hash_data(value)  # Assume hash_data function is defined
                query[f"hashed_{key}"] = hashed_value

            # Query DB
            collection = db.get_collection(cls.collection_name)
            existing_item = collection.find_one(query)

            return existing_item is not None

        except Exception as e:
            print(f"Error occurred: {e}")
            return False
    
    # -----------------------------------
    # AGENT or SUBSCRIBER DEVICES AND LOCATIONS UPDATE
    # -----------------------------------
    @staticmethod
    def add_device_by_agent_or_subscriber(
        agent_id=None,
        subscriber_id=None,
        device_id=None,
        ip_address=None,
    ):
        """
        Add a new device object to user's 'devices' array using agent_id or subscriber_id.
        """

        Log.info(f"🔎 add_device_by_agent_or_subscriber called with: "
                 f"agent_id={agent_id}, subscriber_id={subscriber_id}, "
                 f"device_id={device_id}, ip_address={ip_address}")

        if not device_id:
            return {"success": False, "message": "device_id is required"}

        users_collection = db.get_collection("users")

        # Determine filter
        if agent_id:
            try:
                filter_query = {"agent_id": ObjectId(agent_id)}
            except Exception:
                return {"success": False, "message": "Invalid agent_id"}
        elif subscriber_id:
            try:
                filter_query = {"subscriber_id": ObjectId(subscriber_id)}
            except Exception:
                return {"success": False, "message": "Invalid subscriber_id"}
        else:
            return {"success": False, "message": "agent_id or subscriber_id is required"}

        device_object = {
            "_id": ObjectId(),
            "device_id": encrypt_data(device_id),
            "hashed_device_id": hash_data(device_id),
            # 👇 only treat None specially; empty string will still be encrypted
            "ip_address": encrypt_data(ip_address) if ip_address is not None else None,
            "registered_at": datetime.now(),
        }

        Log.info(f"📦 Device object being saved: {device_object}")

        result = users_collection.update_one(
            filter_query,
            {
                "$push": {"devices": device_object},
                "$set": {"updated_at": datetime.now()},
            }
        )

        if result.matched_count == 0:
            return {"success": False, "message": "User not found"}

        return {
            "success": True,
            "message": "Device added successfully",
            "device": device_object,
        }

    # 🔹 static method: append a new location to an existing user
    @staticmethod
    def add_location_by_agent_or_subscriber(
        agent_id=None,
        subscriber_id=None,
        latitude=None,
        longitude=None,
    ):
        """
        Append a new location entry to the 'locations' array
        for a user identified by agent_id or subscriber_id.
        """

        if latitude is None or longitude is None:
            return {"success": False, "message": "latitude and longitude are required"}

        users_collection = db.get_collection("users")

        # build filter
        if agent_id:
            try:
                filter_query = {"agent_id": ObjectId(agent_id)}
            except Exception:
                return {"success": False, "message": "Invalid agent_id"}
        elif subscriber_id:
            try:
                filter_query = {"subscriber_id": ObjectId(subscriber_id)}
            except Exception:
                return {"success": False, "message": "Invalid subscriber_id"}
        else:
            return {
                "success": False,
                "message": "agent_id or subscriber_id is required",
            }

        location_object = {
            "_id": ObjectId(),
            "latitude": encrypt_data(str(latitude)),
            "longitude": encrypt_data(str(longitude)),
            "captured_at": datetime.now(),
        }

        # optional logging
        try:
            Log.info(
                f"[User.update_locations] filter={filter_query}, "
                f"location_object={location_object}"
            )
        except Exception:
            pass

        result = users_collection.update_one(
            filter_query,
            {
                "$push": {"locations": location_object},
                "$set": {"updated_at": datetime.now()},
            },
        )

        if result.matched_count == 0:
            return {"success": False, "message": "User not found"}

        return {
            "success": True,
            "message": "Location added successfully",
            "location": location_object,
        }

    
    # -------------------------------------------------
    # DELETE CORRESPONDING USER ACCOUNT (business-scoped)
    # -------------------------------------------------
    @staticmethod
    def delete_by_system_user(system_user_id, business_id):
        """Delete User document(s) linked to a given system_user_id in a business."""
        try:
            collection = db.get_collection("users")

            # If your business_id is stored as ObjectId in User documents:
            try:
                business_id_obj = ObjectId(business_id)
                system_user_id_obj = ObjectId(system_user_id)
            except Exception:
                pass

            query = {
                "system_user_id": system_user_id_obj,
                "business_id": business_id_obj,
            }

            result = collection.delete_many(query)
            Log.info(
                f"[user_model.py] system_user_id={system_user_id}, "
                f"business_id={business_id} -> deleted_count={result.deleted_count}"
            )
            return True
        except Exception as e:
            Log.error(
                f"[user_model.py] Unexpected error while deleting user "
                f"for system_user_id={system_user_id}, business_id={business_id}: {e}"
            )
            return False



































