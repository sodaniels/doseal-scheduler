import bcrypt
from bson.objectid import ObjectId
from datetime import datetime
from app.extensions.db import db
from ..utils.logger import Log  # import logging
from ..utils.generators import generate_promo_code, generate_agent_id
from ..utils.crypt import encrypt_data, decrypt_data, hash_data
from ..models.base_model import BaseModel

ENCRYPT_AT_REST = {"status"}


class User(BaseModel):
    """
    User model, aligned with Subscriber/BaseModel conventions.
    """

    collection_name = "users"

    def __init__(
        self,
        phone_number,
        password,
        client_id,
        business_id,
        fullname=None,
        email=None,
        status="Inactive",
        admin_id=None,
        email_verified=None,
        account_type=None,
        username=None,
        system_user_id=None,
        role=None,
        tenant_id=None,
        type=None,
        last_login=None,
        referral_code=None,
        device_id=None,
        location=None,
        ip_address=None,
        created_by=None,
        user_id=None,
    ):
        # Initialise BaseModel (tenant + business + user_id)
        super().__init__(
            tenant_id=tenant_id,
            business_id=business_id,
            user_id=user_id,
        )

        # ----------------------
        # CORE IDENTIFIERS
        # ----------------------
        self.user_id = user_id if user_id else generate_agent_id()

        self.business_id = ObjectId(business_id)
        # Align with Subscriber: encrypt tenant_id
        self.tenant_id = encrypt_data(tenant_id) if tenant_id else None

        self.system_user_id = ObjectId(system_user_id) if system_user_id else None
        self.role = ObjectId(role) if role else None

        if admin_id is not None and admin_id != "":
            self.admin_id = ObjectId(admin_id)
        else:
            self.admin_id = None

        self.created_by = ObjectId(created_by) if created_by is not None else None

        # ----------------------
        # BASIC PROFILE
        # ----------------------
        self.fullname = encrypt_data(fullname) if fullname else None
        self.hashed_fullname = hash_data(fullname) if fullname else None

        self.username = encrypt_data(username) if username else None
        self.username_hashed = hash_data(username) if username else None

        self.email = encrypt_data(email) if email else None
        self.email_hashed = hash_data(email) if email else None

        self.phone_number = encrypt_data(phone_number) if phone_number else None
        self.hashed_phone_number = hash_data(phone_number) if phone_number else None

        self.status = encrypt_data(status) if status else None
        self.account_type = encrypt_data(account_type) if account_type else None
        self.type = encrypt_data(type) if type else None

        # ----------------------
        # CLIENT / LOGIN INFO
        # ----------------------
        self.client_id = encrypt_data(client_id)
        self.client_id_hashed = hash_data(client_id)

        # ✅ Only hash the password if it's not already bcrypt-hashed
        if password and not password.startswith("$2b$"):
            self.password = bcrypt.hashpw(
                password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")
        else:
            self.password = password  # already hashed

        self.email_verified = email_verified if email_verified else None
        self.last_login = last_login if last_login else None

        # ----------------------
        # DEVICES COLLECTION
        # ----------------------
        self.devices = []
        self.device_id = device_id if device_id else None
        if device_id is not None or ip_address is not None:
            self.add_device(device_id, ip_address)

        # ----------------------
        # LOCATIONS COLLECTION
        # ----------------------
        self.location = location if location else None
        self.locations = []
        if location:
            self.add_location(
                latitude=location.get("latitude"),
                longitude=location.get("longitude"),
            )

        # ----------------------
        # REFERRAL / PROMOS
        # ----------------------
        self.referrals = []
        self.transactions = 0
        self.referral_code = encrypt_data(referral_code) if referral_code else None

        # Timestamps (BaseModel may already set them, but we keep explicit as in Subscriber)
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def __str__(self):
        return f"User with fullname {self.fullname} and email {self.email}"

    def to_dict(self):
        """
        Merge BaseModel fields with User-specific fields,
        similar to Subscriber.to_dict().
        """
        user_object = super().to_dict()
        user_object.update(
            {
                "user_id": self.user_id,
                "tenant_id": self.tenant_id,
                "role": self.role,
                "type": self.type,
                "business_id": self.business_id,
                "fullname": self.fullname,
                "hashed_fullname": getattr(self, "hashed_fullname", None),
                "phone_number": self.phone_number,
                "hashed_phone_number": getattr(self, "hashed_phone_number", None),
                "username": self.username,
                "username_hashed": self.username_hashed,
                "email": self.email,
                "email_hashed": self.email_hashed,
                "status": self.status,
                "account_type": self.account_type,
                "client_id": self.client_id,
                "client_id_hashed": self.client_id_hashed,
                "devices": self.devices,
                "locations": self.locations,
                "password": self.password,
                "email_verified": self.email_verified,
                "transactions": self.transactions,
                "referrals": self.referrals,
                "referral_code": self.referral_code,
                "last_login": self.last_login,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
        )

        if self.system_user_id:
            user_object["system_user_id"] = self.system_user_id

        if getattr(self, "admin_id", None):
            user_object["admin_id"] = self.admin_id

        if self.created_by:
            user_object["created_by"] = self.created_by

        return user_object

    def save(self):
        """Save the user to the MongoDB database."""
        users_collection = db.get_collection(self.collection_name)
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
            "ip_address": encrypt_data(ip_address) if ip_address is not None else None,
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

    # ----------------------
    # AUTH / LOGIN HELPERS
    # ----------------------
    @staticmethod
    def verify_password(email, password):
        hashed_email = hash_data(email)
        user = db.get_collection("users").find_one({"email_hashed": hashed_email})

        if not user:
            print("❌ User not found")
            return False

        stored_hash = user["password"]

        if bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8")):
            print("✅ Password match successful")
            return True
        else:
            print("❌ Password mismatch")
            return False

    @classmethod
    def verify_change_password(cls, user_doc: dict, plain_password) -> bool:
        """
        Compare plaintext password with stored bcrypt hash.
        Supports hash stored as str or bytes.
        """
        try:
            stored_hash = (user_doc or {}).get("password")

            if not stored_hash or not plain_password:
                return False

            # ---- ensure types ----
            if not isinstance(plain_password, str):
                Log.info(f"[user_model.py][verify_password] plain_password not str: {type(plain_password)}")
                return False

            # bcrypt hash may be str or bytes
            if isinstance(stored_hash, str):
                stored_hash = stored_hash.encode("utf-8")

            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                stored_hash,
            )

        except Exception as e:
            Log.info(f"[user_model.py][verify_password] error: {e}")
            return False
    
    @classmethod
    def update_password(cls, *, user_id: str, business_id: str, new_password: str) -> bool:
        """
        Update password for a user within a business scope.
        """
        log_tag = f"[user_model.py][User][update_password][user_id={user_id}][business_id={business_id}]"

        try:
            col = db.get_collection(cls.collection_name)

            hashed = bcrypt.hashpw(
                new_password.encode("utf-8"),
                bcrypt.gensalt()
            ).decode("utf-8")

            res = col.update_one(
                {"_id": ObjectId(user_id), "business_id": ObjectId(business_id)},
                {"$set": {"password": hashed, "updated_at": datetime.utcnow()}}
            )
            return res.modified_count > 0

        except Exception as e:
            Log.info(f"{log_tag} error: {e}")
            return False
        
    @staticmethod
    def email_verification_needed(email):
        """
        Select user by email
        """
        hashed_email = hash_data(email)
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"email_hashed": hashed_email})

        if user.get("email_verified") != "verified":
            return True
        else:
            return False

    @staticmethod
    def update_auth_code(email, auth_code):
        """Update only the auth_code for the given user by email."""
        users_collection = db.get_collection("users")
        hashed_email = hash_data(email)

        user = users_collection.find_one({"email_hashed": hashed_email})
        if not user:
            return False

        auth_code_hashed = hash_data(auth_code)
        result = users_collection.update_one(
            {"email_hashed": hashed_email},
            {"$set": {"auth_code": auth_code_hashed}},
        )
        return result.matched_count > 0

    @staticmethod
    def get_auth_code(auth_code):
        hashed_token = hash_data(auth_code)
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"auth_code": hashed_token})
        if not user:
            print("❌ User not found")
            return False

        print("✅ User found")
        return user

    @staticmethod
    def update_user_status(email_hashed):
        """Activate user and clear auth_code by hashed email."""
        users_collection = db.get_collection("users")

        user = users_collection.find_one({"email_hashed": email_hashed})
        if not user:
            return False

        result = users_collection.update_one(
            {"email_hashed": email_hashed},
            {
                "$set": {
                    "status": encrypt_data("Active"),
                    "email_verified": "verified",
                },
                "$unset": {"auth_code": ""},
            },
        )
        return result.matched_count > 0

    @staticmethod
    def update_last_login(
        *, _id: str | ObjectId, ip_address: str | None = None
    ) -> bool:
        """
        Update the user's last login timestamp and append a record to login_history.
        """
        users_collection = db.get_collection("users")

        if not _id:
            raise ValueError("_id is required")
        if not isinstance(_id, ObjectId):
            _id = ObjectId(_id)

        current_time = datetime.utcnow().isoformat()
        login_entry = {
            "timestamp": current_time,
            "ip_address": ip_address or "unknown",
        }

        update_doc = {
            "$set": {"last_login": current_time},
            "$push": {"login_history": login_entry},
        }

        result = users_collection.update_one({"_id": _id}, update_doc)
        return result.matched_count > 0

    @staticmethod
    def update_agent_last_login(
        *, agent_id: str | ObjectId, ip_address: str | None = None
    ) -> bool:
        """
        Update the agent's last login timestamp and append a record to login_history.
        """
        users_collection = db.get_collection("users")

        if not agent_id:
            raise ValueError("agent_id is required")
        if not isinstance(agent_id, ObjectId):
            agent_id = ObjectId(agent_id)

        current_time = datetime.utcnow().isoformat()
        login_entry = {
            "timestamp": current_time,
            "ip_address": ip_address or "unknown",
        }

        update_doc = {
            "$set": {"last_login": current_time},
            "$push": {"login_history": login_entry},
        }

        result = users_collection.update_one({"agent_id": agent_id}, update_doc)
        return result.matched_count > 0

    # ----------------------
    # BASIC GETTERS
    # ----------------------
    @staticmethod
    def get_user_by_email(email):
        hashed_email = hash_data(email)
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"email_hashed": hashed_email})
        if not user:
            return None

        user.pop("password", None)
        return user

    @staticmethod
    def get_user_by_username(username):
        hashed_username = hash_data(username)
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"username_hashed": hashed_username})
        if not user:
            return None

        user.pop("password", None)
        return user

    @staticmethod
    def get_user_role(role_id):
        collection = db.get_collection("roles")
        role = collection.find_one({"_id": role_id})
        if not role:
            return None
        return role

    @staticmethod
    def get_user_by_user__id(user_id):
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            return None
        return user

    @staticmethod
    def get_by_id(_id, business_id):
        """
        Select user by ID & business_id
        """
        try:
            user_id_obj = ObjectId(_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        users_collection = db.get_collection("users")
        user = users_collection.find_one(
            {"_id": user_id_obj, "business_id": business_id_obj}
        )
        if not user:
            return None
        return user

    @staticmethod
    def get_user_by_agent_id(agent_id):
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"agent_id": ObjectId(agent_id)})
        if not user:
            return None
        return user

    @staticmethod
    def get_user_by_system_user_id(system_user_id):
        users_collection = db.get_collection("users")
        user = users_collection.find_one({"system_user_id": ObjectId(system_user_id)})
        if not user:
            return None
        return user

    @staticmethod
    def get_user_by_subscriber_id(subscriber_id):
        try:
            subscriber_id = ObjectId(subscriber_id)
        except Exception:
            pass

        users_collection = db.get_collection("users")
        user = users_collection.find_one({"subscriber_id": subscriber_id})
        if not user:
            return None
        return user

    @staticmethod
    def get_system_user_by__id(system_user_id):
        users_collection = db.get_collection("system_users")
        user = users_collection.find_one({"_id": ObjectId(system_user_id)})
        if not user:
            return None
        return user

    # ----------------------
    # PROMO / BALANCE
    # ----------------------
    @staticmethod
    def update_user_promo_mechanism(user_id, promo):
        """
        Update user transactions and update a specific promo in user.promos
        """
        users_collection = db.get_collection("users")

        user = users_collection.find_one({"_id": ObjectId(user_id)})
        if not user:
            Log.error("User not found.")
            return False

        current_balance = float(user.get("transactions", 0))
        new_balance = current_balance + float(promo.get("promo_amount", 0))

        Log.info(f"new_balance: {new_balance}")

        updated_promos = []
        target_promo_id = str(promo.get("promo_id"))

        for p in user.get("promos", []):
            if str(p.get("promo_id")) == target_promo_id:
                p["promo_left"] = max(0, int(p.get("promo_left", 0)) - 1)
            updated_promos.append(p)

        update_data = {
            "transactions": new_balance,
            "promos": updated_promos,
            "updated_at": datetime.utcnow(),
        }

        result = users_collection.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})

        if result.modified_count > 0:
            Log.info(
                "[user_model.py][update_user_promo_mechanism] "
                "User promo and balance updated successfully."
            )
            return True

        Log.warning(
            "[user_model.py][update_user_promo_mechanism] "
            "No changes were made to the user."
        )
        return False

    # ----------------------
    # PIN MANAGEMENT
    # ----------------------
    @staticmethod
    def confirm_user_pin(user__id, pin, account_type=None):
        """
        Validate a PIN by hashing it and checking it against the stored hashed PIN.
        """
        if pin is None:
            print("❌ PIN is required")
            return False

        hashed_pin = hash_data(pin)
        users_collection = db.get_collection("users")

        user = None
        if account_type and str.lower(account_type) == "agent":
            user = users_collection.find_one({"agent_id": ObjectId(user__id), "pin": hashed_pin})
        elif account_type and str.lower(account_type) == "subscriber":
            user = users_collection.find_one({"subscriber_id": ObjectId(user__id), "pin": hashed_pin})

        if not user:
            print("❌ Invalid PIN")
            return False

        print("✅ PIN matched, user found")
        return user

    @staticmethod
    def update_account_pin_by_agent_id(agent_id, pin):
        users_collection = db.get_collection("users")

        user = users_collection.find_one({"agent_id": ObjectId(agent_id)})
        if not user:
            return False

        email_hashed = user.get("email_hashed")
        hashed_pin = hash_data(pin)

        result = users_collection.update_one(
            {"email_hashed": email_hashed},
            {"$set": {"pin": hashed_pin}},
        )
        return result.matched_count > 0

    @staticmethod
    def update_account_pin_by_subscriber_id(subscriber_id, pin):
        users_collection = db.get_collection("users")

        user = users_collection.find_one({"subscriber_id": ObjectId(subscriber_id)})
        if not user:
            return False

        username_hashed = user.get("username_hashed")
        hashed_pin = hash_data(pin)

        result = users_collection.update_one(
            {"username_hashed": username_hashed},
            {"$set": {"pin": hashed_pin}},
        )
        return result.matched_count > 0

    # ----------------------
    # MULTI-FIELD EXISTENCE CHECK
    # ----------------------
    @classmethod
    def check_multiple_item_exists(cls, business_id, fields: dict):
        """
        Check if a user exists based on multiple hashed fields.
        E.g. {"email": "...", "phone_number": "..."}
        """
        try:
            try:
                business_id_obj = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e

            query = {"business_id": business_id_obj}

            for key, value in fields.items():
                hashed_value = hash_data(value)
                query[f"{key}_hashed" if key in ["email", "username", "client_id"] else f"hashed_{key}"] = hashed_value

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
        Log.info(
            f"🔎 add_device_by_agent_or_subscriber called with: "
            f"agent_id={agent_id}, subscriber_id={subscriber_id}, "
            f"device_id={device_id}, ip_address={ip_address}"
        )

        if not device_id:
            return {"success": False, "message": "device_id is required"}

        users_collection = db.get_collection("users")

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
            "ip_address": encrypt_data(ip_address) if ip_address is not None else None,
            "registered_at": datetime.now(),
        }

        Log.info(f"📦 Device object being saved: {device_object}")

        result = users_collection.update_one(
            filter_query,
            {
                "$push": {"devices": device_object},
                "$set": {"updated_at": datetime.now()},
            },
        )

        if result.matched_count == 0:
            return {"success": False, "message": "User not found"}

        return {
            "success": True,
            "message": "Device added successfully",
            "device": device_object,
        }

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

            try:
                business_id_obj = ObjectId(business_id)
                system_user_id_obj = ObjectId(system_user_id)
            except Exception:
                return False

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
