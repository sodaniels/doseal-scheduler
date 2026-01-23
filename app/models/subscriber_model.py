import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from bson.objectid import ObjectId
from app.extensions.db import db
from ..utils.crypt import encrypt_data, decrypt_data, hash_data
from ..models.base_model import BaseModel

class Subscriber(BaseModel):
    """
    A Subscriber represents an end user subscribing to the service.
    """

    collection_name = "subscribers"
    user_collection_name = "users" 

    def __init__(self, tenant_id, business_id, user_id=None, username=None, first_name=None, middle_name=None,
                 last_name=None, date_of_birth=None, phone_number=None, email=None, post_code=None,
                 device_uuid=None, request=None, remote_ip=None, account_status=None, gender=None, 
                 referral_code=None, agreed_terms_and_conditions= None, address=None):
        
        super().__init__(tenant_id=tenant_id, business_id=business_id, user_id=user_id)

        self.user_id = user_id if user_id else str(uuid.uuid4())
        self.business_id = ObjectId(business_id)
        self.tenant_id = encrypt_data(tenant_id) if tenant_id else None
        self.username = encrypt_data(username) if username else None
        self.hashed_username = hash_data(username) if username else None
        self.first_name = encrypt_data(first_name) if first_name else None
        self.middle_name = encrypt_data(middle_name) if middle_name else None
        self.last_name = encrypt_data(last_name) if last_name else None
        self.date_of_birth = encrypt_data(date_of_birth) if date_of_birth else None
        self.phone_number = encrypt_data(phone_number) if phone_number else None
        self.email = encrypt_data(email) if email else None
        self.gender = encrypt_data(gender) if gender else None
        self.post_code = encrypt_data(post_code) if post_code else None
        self.address = encrypt_data(address) if address else None
        self.device_uuid = encrypt_data(device_uuid) if device_uuid else None
        self.request = encrypt_data(request) if request else None
        self.remote_ip = encrypt_data(remote_ip) if remote_ip else None
        self.referral_code = encrypt_data(referral_code) if referral_code else None
        self.hashed_referral_code = hash_data(referral_code) if referral_code else None
        self.account_status = encrypt_data(account_status) if account_status else None
        self.hashed_first_name = hash_data(first_name) if first_name else None
        self.hashed_middle_name = hash_data(middle_name) if middle_name else None
        self.hashed_last_name = hash_data(last_name) if last_name else None 
        self.hashed_email = hash_data(email) if email else None 
        self.agreed_terms_and_conditions = agreed_terms_and_conditions

        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def save(self):
        subscriber_collection = db.get_collection(self.collection_name)
        result = subscriber_collection.insert_one(self.to_dict())
        return result.inserted_id

    def to_dict(self):
        subscriber_dict = super().to_dict()
        subscriber_dict.update({
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "username": self.username,
            "hashed_username": self.hashed_username,
            "first_name": self.first_name,
            "middle_name": self.middle_name,
            "last_name": self.last_name,
            "date_of_birth": self.date_of_birth,
            "phone_number": self.phone_number,
            "email": self.email,
            "post_code": self.post_code,
            "referral_code": self.referral_code,
            "hashed_referral_code": self.hashed_referral_code,
            "address": self.address,
            "device_uuid": self.device_uuid,
            "request": self.request,
            "remote_ip": self.remote_ip,
            "agreed_terms_and_conditions": self.agreed_terms_and_conditions,
            "account_status": self.account_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        })
        return subscriber_dict

    @classmethod
    def get_all(
        cls,
        business_id: str,
        page: int = 1,
        per_page: int = 10,
        *,
        start_date=None,
        end_date=None,
        username: str | None = None,          
        first_name: str | None = None,            
        last_name: str | None = None,            
        user_id: str | None = None,           
        has_uploaded_id_documents: bool | None = None,  # True/False to filter presence of uploads
        has_uploaded_poa_documents: bool | None = None,  # True/False to filter presence of uploads
        sort: list[tuple[str, int]] | None = None,
    ):
        """
        Retrieve subscribers for a business with pagination and optional filters.

        Filters:
        - start_date, end_date: YYYY-MM-DD or datetime for created_at range (inclusive)
        - username: exact username (matched via hashed_username)
        - user_id: exact match (your custom string user_id, not _id)
        - has_uploaded_id_documents: True to require presence of uploads; False for missing/None
        - sort: list of (field, direction) pairs; defaults to [("created_at", -1)]
        """
        # Validate business_id
        try:
            bid = ObjectId(business_id)
        except Exception:
            return {
                "subscribers": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": int(page or 1),
                "per_page": int(per_page or 10),
            }

        # Permission check (align with your BaseModel policy names)
        if not cls.check_permission(cls, "read", "subscribers"):
            raise PermissionError(f"User does not have permission to view {cls.__name__}.")

        page = int(page or 1)
        per_page = int(per_page or 10)

        col = db.get_collection(cls.collection_name)

        # --- Build query ---
        query = {"business_id": bid}

        # Date range on created_at
        if start_date or end_date:
            created_range = {}
            if start_date:
                if isinstance(start_date, str):
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                created_range["$gte"] = start_date
            if end_date:
                if isinstance(end_date, str):
                    end_date = datetime.strptime(end_date, "%Y-%m-%d")
                # make end inclusive to end of the day if you prefer:
                created_range["$lte"] = end_date
            query["created_at"] = created_range

        # username (via hash)
        if username:
            query["hashed_username"] = hash_data(username)
            
        if first_name:
            query["hashed_first_name"] = hash_data(first_name)
            
        if last_name:
            query["hashed_last_name"] = hash_data(last_name)
        
        if last_name:
            query["hashed_last_name"] = hash_data(last_name)

        # user_id (your custom id field)
        if user_id:
            query["user_id"] = user_id

        # uploaded_id_documents presence
        if has_uploaded_id_documents is True:
            query["uploaded_id_documents"] = {"$exists": True, "$ne": None}
        elif has_uploaded_id_documents is False:
            query["$or"] = [
                {"uploaded_id_documents": {"$exists": False}},
                {"uploaded_id_documents": None},
            ]
            
        # uploaded_poa_documents presence
        if has_uploaded_poa_documents is True:
            query["uploaded_poa_documents"] = {"$exists": True, "$ne": None}
        elif has_uploaded_poa_documents is False:
            query["$or"] = [
                {"uploaded_poa_documents": {"$exists": False}},
                {"uploaded_poa_documents": None},
            ]

        # --- Count total ---
        total_count = col.count_documents(query)

        # --- Sorting / Pagination ---
        cursor = (
            col.find(query)
            .sort(sort or [("created_at", -1)])
            .skip((page - 1) * per_page)
            .limit(per_page)
        )

        # --- Decrypt selected fields for response ---
        fields_to_decrypt = [
            "tenant_id", "username", "first_name", "middle_name", "last_name",
            "date_of_birth", "phone_number", "email", "post_code", "address", "device_uuid",
            "request", "remote_ip", "account_status", "uploaded_id_documents","uploaded_poa_documents", 
            "gender", "referral_code",
        ]

        results = []
        for doc in cursor:
            out = {
                "_id": str(doc.get("_id")),
                "user_id": doc.get("user_id"),
                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at"),
            }
            # Best-effort decrypt; if a field is plaintext (e.g., balance==0), fall back
            for f in fields_to_decrypt:
                val = doc.get(f)
                if val is None:
                    out[f] = None
                    continue
                try:
                    out[f] = decrypt_data(val)
                except Exception:
                    out[f] = val  # fallback if not encrypted or malformed
            results.append(out)

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "subscribers": results,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page,
        }

    @classmethod
    def get_by_id(cls, business_id, subscriber_id):
        """
        Retrieve a subscriber by subscriber_id, decrypting selected fields.
        """
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None
        
        try:
            subscriber_id_obj = ObjectId(subscriber_id)
        except Exception:
            return None
        
        # Permission check (align with your BaseModel policy names)
        if not cls.check_permission(cls, "read", "subscribers"):
            raise PermissionError(f"User does not have permission to view {cls.__name__}.")
        

        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({
            "_id": subscriber_id_obj, 
            "business_id": business_id_obj
        })
        if not data:
            return None

        fields_to_decrypt = [
            "tenant_id", "username", "first_name", "middle_name", "last_name",
            "date_of_birth", "phone_number", "email", "post_code", "address", "device_uuid",
            "request", "remote_ip", "account_status","uploaded_id_documents", 
            "uploaded_poa_documents", "gender", "referral_code",
        ]

        decrypted = {}
        for field in fields_to_decrypt:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None
            
        payload = {
            "_id": str(data["_id"]),
            "user_id": data["user_id"],
            "tenant_id": decrypted["tenant_id"],
            "username": decrypted["username"],
            "first_name": decrypted["first_name"],
            "middle_name": decrypted["middle_name"],
            "last_name": decrypted["last_name"],
            "date_of_birth": decrypted["date_of_birth"],
            "phone_number": decrypted["phone_number"],
            "email": decrypted["email"],
            "gender": decrypted["gender"],
            "post_code": decrypted["post_code"],
            "address": decrypted["address"],
            "device_uuid": decrypted["device_uuid"],
            "request": decrypted["request"],
            "remote_ip": decrypted["remote_ip"],
            "referral_code": decrypted["referral_code"],
            "account_status": decrypted["account_status"],
            "uploaded_id_documents": decrypted["uploaded_id_documents"],
            "uploaded_poa_documents": decrypted["uploaded_poa_documents"],
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }
        
        
        referrer_payload = dict()
        
        if data.get("referrer") is not None:
            referrer_payload["referrer"] = str(data.get("referrer"))
        
        payload.update(referrer_payload)
        
        return payload
        
        
    @classmethod
    def subscriber_search(cls, business_id, search_term):
        """
        Search for subscribers within a business by first_name, last_name, email, or username.
        Returns a list of matching subscribers with decrypted fields.
        """
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return []

        # Permission check (align with your BaseModel policy names)
        if not cls.check_permission(cls, "read", "subscribers"):
            raise PermissionError(f"User does not have permission to view {cls.__name__}.")

        collection = db.get_collection(cls.collection_name)

        # Because these fields are encrypted in the DB, we can’t directly query them.
        # So we fetch all subscribers for the business and then decrypt + filter.
        cursor = collection.find({"business_id": business_id_obj})

        fields_to_decrypt = [
            "tenant_id", "username", "first_name", "middle_name", "last_name",
            "date_of_birth", "phone_number", "email", "post_code", "device_uuid",
            "request", "remote_ip", "account_status", "uploaded_id_documents", 
            "uploaded_poa_documents", "referral_code"
        ]

        results = []
        for data in cursor:
            decrypted = {}
            for field in fields_to_decrypt:
                decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

            # Match search term (case-insensitive) against searchable fields
            if any(
                search_term.lower() in (decrypted.get(key) or "").lower()
                for key in ["first_name", "last_name", "email", "username", "referral_code"]
            ):
                results.append({
                    "user_id": data.get("user_id"),
                    "tenant_id": decrypted["tenant_id"],
                    "username": decrypted["username"],
                    "first_name": decrypted["first_name"],
                    "middle_name": decrypted["middle_name"],
                    "last_name": decrypted["last_name"],
                    "date_of_birth": decrypted["date_of_birth"],
                    "phone_number": decrypted["phone_number"],
                    "email": decrypted["email"],
                    "post_code": decrypted["post_code"],
                    "device_uuid": decrypted["device_uuid"],
                    "request": decrypted["request"],
                    "remote_ip": decrypted["remote_ip"],
                    "account_status": decrypted["account_status"],
                    "uploaded_id_documents": decrypted["uploaded_id_documents"],
                    "uploaded_poa_documents": decrypted["uploaded_poa_documents"],
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                })

        return results

    @classmethod
    def check_item_exists(cls, business_id, key, value):
        """
        Check if an item exists by business_id and a specific key (hashed comparison).
        This method allows dynamic checks for any key (like 'name', 'phone', etc.).
        
        Args:
        - business_id: The subscriber ID to filter the items.
        - key: The key (field) to check for existence (e.g., 'name', 'phone').
        - value: The value of the key to check for existence.

        Returns:
        - True if the item exists, False otherwise.
        """

        try:
            business_id_obj = ObjectId(business_id)  # Convert string subscriber_id to ObjectId
        except Exception as e:
            raise ValueError(f"Invalid business_id format: {business_id}") from e

        # Dynamically hash the value of the key
        hashed_key = hash_data(value)  # Hash the value provided for the dynamic field

        # Dynamically create the query with agent_id and hashed field
        query = {
            "business_id": business_id_obj,
            f"hashed_{key}": hashed_key 
        }

        # Query the database for an item matching the given agent_id and hashed value
        collection = db.get_collection(cls.collection_name)
        existing_item = collection.find_one(query)

        # Return True if a matching item is found, else return False
        if existing_item:
            return True  # Item exists
        else:
            return False  # Item does not exist
    
    @staticmethod
    def update_account_status_by_subscriber_id(subscriber_id, ip_address, field, update_value):
        """Update a specific field in the 'account_status' for the given subscriber ID."""
        subscribers_collection = db.get_collection("subscribers")  # Using the 'subscribers' collection instead of 'users'
        
        # Search for the subscriber by subscriber_id
        subscriber = subscribers_collection.find_one({"_id": ObjectId(subscriber_id)})
        
        if not subscriber:
            return {"success": False, "message": "Subscriber not found"}  # Subscriber not found
        
        # Get the encrypted account_status field from the subscriber document
        encrypted_account_status = subscriber.get("account_status", None)
        
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
        result = subscribers_collection.update_one(
            {"_id": ObjectId(subscriber_id)},  # Search condition
            {"$set": {"account_status": encrypted_account_status}}  # Update operation
        )
        
        # Return success or failure of the update operation
        if result.matched_count > 0:
            return {"success": True, "message": "Account status updated successfully"}
        else:
            return {"success": False, "message": "Failed to update account status"}

    @classmethod
    def get_subscriber_by_referral_code(cls, business_id, key, value):
        try:
            business_id_obj = ObjectId(business_id)  # Convert string subscriber_id to ObjectId
        except Exception as e:
            raise ValueError(f"Invalid business_id format: {business_id}") from e

        # Dynamically hash the value of the key
        hashed_key = hash_data(value)  # Hash the value provided for the dynamic field

        # Dynamically create the query with agent_id and hashed field
        query = {
            "business_id": business_id_obj,
            f"hashed_{key}": hashed_key 
        }

        # Query the database for an item matching the given agent_id and hashed value
        collection = db.get_collection(cls.collection_name)
        existing_item = collection.find_one(query)

        # Return True if a matching item is found, else return False
        if existing_item:
            return str(existing_item.get("_id"))
        else:
            return False  # Item does not exist
    
    @classmethod
    def get_by_username(cls, username):
        """
        Retrieve a subscriber by username, decrypting selected fields.
        """
        hashed_username = hash_data(username)
        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({"hashed_username": hashed_username})
        if not data:
            return None

        fields_to_decrypt = [
            "tenant_id", "username", "first_name", "middle_name", "last_name",
            "date_of_birth", "phone_number", "email", "post_code", "device_uuid",
            "request", "remote_ip", "account_status", "referral_code"
        ]

        decrypted = {}
        for field in fields_to_decrypt:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        return {
            "_id": str(data.get("_id")),
            "user_id": data["user_id"],
            "tenant_id": decrypted["tenant_id"],
            "username": decrypted["username"],
            "first_name": decrypted["first_name"],
            "middle_name": decrypted["middle_name"],
            "last_name": decrypted["last_name"],
            "date_of_birth": decrypted["date_of_birth"],
            "phone_number": decrypted["phone_number"],
            "email": decrypted["email"],
            "post_code": decrypted["post_code"],
            "device_uuid": decrypted["device_uuid"],
            "request": decrypted["request"],
            "remote_ip": decrypted["remote_ip"],
            "referral_code": decrypted["referral_code"],
            "account_status": decrypted["account_status"],
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    @staticmethod
    def update_uploaded_documents(**subscriber_details):
        """Update or add specific uploaded document fields for the given subscriber ID."""
        subscribers_collection = db.get_collection("subscribers")  # Use 'subscribers' collection
        subscriber_id = subscriber_details.get("subscriber_id")
        
        # Search for the subscriber by subscriber_id
        subscriber = subscribers_collection.find_one({"_id": ObjectId(subscriber_id)})
        
        if not subscriber:
            return {"success": False, "message": "Subscriber not found"}
        
        # Get the encrypted uploaded_documents field from the subscriber document
        encrypted_uploaded_documents = subscriber.get("uploaded_documents", None)
        
        # If uploaded_documents details are not found, initialize a new entry
        if encrypted_uploaded_documents is None:
            # Initialize the uploaded_documents field with the new details
            uploaded_documents = [{
                "id_front_image": subscriber_details.get("id_front_image", None),
                "id_front_image_file_path": subscriber_details.get("id_front_image_file_path", ""),
                "id_back_image": subscriber_details.get("id_back_image", None),
                "id_back_image_file_path": subscriber_details.get("id_back_image_file_path", ""),
                "proof_of_address": subscriber_details.get("proof_of_address", None),
                "proof_of_address_file_path": subscriber_details.get("proof_of_address_file_path", "")
            }]
        else:
            # Decrypt the uploaded_documents field if it already exists
            try:
                uploaded_documents = decrypt_data(encrypted_uploaded_documents)
            except Exception as e:
                return {"success": False, "message": f"Error decrypting uploaded document details: {str(e)}"}
            
            # Overwrite the previous uploaded documents with new info
            uploaded_documents = [{
                "id_front_image": subscriber_details.get("id_front_image", uploaded_documents[0].get("id_front_image")),
                "id_front_image_file_path": subscriber_details.get("id_front_image_file_path", uploaded_documents[0].get("id_front_image_file_path")),
                "id_back_image": subscriber_details.get("id_back_image", uploaded_documents[0].get("id_back_image")),
                "id_back_image_file_path": subscriber_details.get("id_back_image_file_path", uploaded_documents[0].get("id_back_image_file_path")),
                "proof_of_address": subscriber_details.get("proof_of_address", uploaded_documents[0].get("proof_of_address")),
                "proof_of_address_file_path": subscriber_details.get("proof_of_address_file_path", uploaded_documents[0].get("proof_of_address_file_path"))
            }]

        # Re-encrypt the updated uploaded_documents field before saving back
        try:
            encrypted_uploaded_documents = encrypt_data(uploaded_documents)
        except Exception as e:
            return {"success": False, "message": f"Error encrypting uploaded document details: {str(e)}"}
        
        # Update or set the 'uploaded_documents' field in the database
        result = subscribers_collection.update_one(
            {"_id": ObjectId(subscriber_id)},  # Search condition
            {"$set": {"uploaded_documents": encrypted_uploaded_documents}}  # Update operation
        )
        
        if result.matched_count > 0:
            return True
        else:
            return False
 
    @staticmethod
    def update_intermex_uploaded_documents(**subscriber_details):
        """Update or append uploaded document based on orientation and upload_category."""
        subscribers_collection = db.get_collection("subscribers")
        subscriber_id = subscriber_details.get("subscriber_id")

        # Find subscriber
        subscriber = subscribers_collection.find_one({"_id": ObjectId(subscriber_id)})
        if not subscriber:
            return {"success": False, "message": "Subscriber not found"}

        # Decrypt existing documents if any
        encrypted_uploaded_documents = subscriber.get("uploaded_documents", None)
        uploaded_documents = []

        if encrypted_uploaded_documents:
            try:
                uploaded_documents = decrypt_data(encrypted_uploaded_documents)
            except Exception as e:
                return {"success": False, "message": f"Error decrypting uploaded documents: {str(e)}"}

        # Build new upload entry
        orientation = subscriber_details.get("orientation")
        upload_category = subscriber_details.get("upload_category", "Identification")
        
        new_entry = {
            "intermex_upload_id": subscriber_details.get("intermex_upload_id"),
            "orientation": orientation,
            "upload_category": upload_category,
        }

        if orientation == "Front":
            new_entry["sender_image1"] = subscriber_details.get("sender_image1")
            new_entry["sender_image1_file_path"] = subscriber_details.get("sender_image1_file_path")
        elif orientation == "Back":
            new_entry["sender_image2"] = subscriber_details.get("sender_image2")
            new_entry["sender_image2_file_path"] = subscriber_details.get("sender_image2_file_path")

        # Update if both orientation and upload_category match
        updated = False
        for idx, doc in enumerate(uploaded_documents):
            if doc.get("orientation") == orientation and doc.get("upload_category") == upload_category:
                uploaded_documents[idx] = new_entry
                updated = True
                break

        if not updated:
            uploaded_documents.append(new_entry)

        # Encrypt updated list
        try:
            encrypted_uploaded_documents = encrypt_data(uploaded_documents)
        except Exception as e:
            return {"success": False, "message": f"Error encrypting uploaded documents: {str(e)}"}

        # Update in DB
        result = subscribers_collection.update_one(
            {"_id": ObjectId(subscriber_id)},
            {"$set": {"uploaded_documents": encrypted_uploaded_documents}}
        )

        return result.matched_count > 0

    @classmethod
    def upload_id_documents_by_subscriber_id(cls, subscriber_id, remote_ip=None, **document_details):
        """
        Update (or create) the single documents KYC fields for the given subscriber_id.
        - Uses the 'subscribers' collection
        - Replaces 'directors' with 'documents'
        - No loop needed: one subscriber → one documents record
        """
        subscribers_collection = db.get_collection("subscribers")

        if not subscriber_id:
            return {"success": False, "message": "subscriber_id is required"}

        # Validate ObjectId
        try:
            _sid = ObjectId(subscriber_id)
        except Exception:
            return {"success": False, "message": "Invalid subscriber_id"}

        # Find subscriber
        subscriber = subscribers_collection.find_one({"_id": _sid})
        if not subscriber:
            return {"success": False, "message": "Subscriber not found"}

        # Get existing (encrypted) documents field
        encrypted_documents = subscriber.get("uploaded_id_documents")

        # Decrypt if present
        if encrypted_documents is not None:
            try:
                documents = decrypt_data(encrypted_documents)
                if isinstance(documents, list):
                    documents = documents[0] if documents else {}
                elif not isinstance(documents, dict):
                    documents = {}
            except Exception as e:
                return {"success": False, "message": f"Error decrypting documents: {str(e)}"}
        else:
            documents = {}

        # Allowed/managed fields for documents
        updatable_keys = [
            "id_type",
            "id_number",
            "id_expiry",
            "id_front_image",
            "id_front_image_file_path",
            "id_back_image",
            "id_back_image_file_path",
        ]

        # Merge updates (only overwrite if provided)
        for key in updatable_keys:
            if key in document_details:
                #check if id_front was uploaded
                if key == "id_front_image":
                    cls.update_account_status_by_subscriber_id(
                        subscriber_id,
                        remote_ip,
                        'uploaded_id_front',
                        True
                    )
                    
                #check if id_back was uploaded
                elif key == "id_back_image":
                    cls.update_account_status_by_subscriber_id(
                        subscriber_id,
                        remote_ip,
                        'uploaded_id_back',
                        True
                    )
                documents[key] = document_details.get(key)

        # Re-encrypt before saving
        try:
            encrypted_documents = encrypt_data(documents)
        except Exception as e:
            return {"success": False, "message": f"Error encrypting documents: {str(e)}"}

        # Persist
        result = subscribers_collection.update_one(
            {"_id": _sid},
            {"$set": {"uploaded_id_documents": encrypted_documents}}
        )

        if result.matched_count > 0:
            return {"success": True, "message": "ID Document updated successfully"}
        else:
            return {"success": False, "message": "Failed to update documents"}

    @classmethod
    def upload_poa_documents_by_subscriber_id(cls, subscriber_id, remote_ip=None, **document_details):
        """
        Update (or create) the single documents KYC fields for the given subscriber_id.
        - Uses the 'subscribers' collection
        - Replaces 'directors' with 'documents'
        - No loop needed: one subscriber → one documents record
        """
        subscribers_collection = db.get_collection("subscribers")

        if not subscriber_id:
            return {"success": False, "message": "subscriber_id is required"}

        # Validate ObjectId
        try:
            _sid = ObjectId(subscriber_id)
        except Exception:
            return {"success": False, "message": "Invalid subscriber_id"}

        # Find subscriber
        subscriber = subscribers_collection.find_one({"_id": _sid})
        if not subscriber:
            return {"success": False, "message": "Subscriber not found"}

        # Get existing (encrypted) documents field
        encrypted_documents = subscriber.get("uploaded_poa_documents")

        # Decrypt if present
        if encrypted_documents is not None:
            try:
                documents = decrypt_data(encrypted_documents)
                if isinstance(documents, list):
                    documents = documents[0] if documents else {}
                elif not isinstance(documents, dict):
                    documents = {}
            except Exception as e:
                return {"success": False, "message": f"Error decrypting documents: {str(e)}"}
        else:
            documents = {}

        # Allowed/managed fields for documents
        updatable_keys = [
            "poa_type",
            "proof_of_address",
            "proof_of_address_file_path",
        ]

        # Merge updates (only overwrite if provided)
        for key in updatable_keys:
            if key in document_details:
                #check if id_front was uploaded
                if key == "proof_of_address":
                    cls.update_account_status_by_subscriber_id(
                        subscriber_id,
                        remote_ip,
                        'uploaded_id_utility',
                        True
                    )
                documents[key] = document_details.get(key)

        # Re-encrypt before saving
        try:
            encrypted_documents = encrypt_data(documents)
        except Exception as e:
            return {"success": False, "message": f"Error encrypting documents: {str(e)}"}

        # Persist
        result = subscribers_collection.update_one(
            {"_id": _sid},
            {"$set": {"uploaded_poa_documents": encrypted_documents}}
        )

        if result.matched_count > 0:
            return {"success": True, "message": "Proof of Address Document updated successfully"}
        else:
            return {"success": False, "message": "Failed to update documents"}


    @classmethod
    def update(cls, user_id, **updates):
        """
        Update a subscriber's information by user_id with encryption.
        """
        encrypt_fields = [
            "first_name", "middle_name", "last_name", "phone_number", "email",
            "post_code", "device_uuid", "request", "remote_ip", 
            "account_status", "gender", "post_code", "address",
        ]
        
        if updates.get("referrer"):
            updates["referrer"] = ObjectId(updates.get("referrer"))
        

        for field in encrypt_fields:
            if field in updates:
                #check if email exist in the update
                if field == "email":
                    updates["hashed_email"] = hash_data(updates["email"])
                    
                    cls.update_account_status_by_subscriber_id(
                        user_id,
                        updates["remote_ip"],
                        'account_email_verified',
                        False
                    )
                
                updates[field] = encrypt_data(updates[field])
                

        return super().update(user_id, **updates)

    @classmethod
    def delete(cls, user_id):
        """
        Delete a subscriber by user_id.
        """
        
        # 2. Delete the subscriber
        subscriber_deleted = super().delete(user_id)
        
        # 3. Delete the associated user if subscriber was deleted
        if subscriber_deleted and user_id:
            user_collection = db.get_collection(cls.user_collection_name)
            user_collection.delete_one({"subscriber_id": ObjectId(user_id)})

        return subscriber_deleted