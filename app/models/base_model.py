# app/models/base_model.py

from datetime import datetime
import uuid, os
from zoneinfo import ZoneInfo
from ..extensions.db import db
from bson.objectid import ObjectId
from flask import g
from ..constants.service_code import SYSTEM_USERS
from ..utils.crypt import encrypt_data, hash_data, decrypt_data
from ..utils.logger import Log # import logging

class BaseModel:
    """
    A base class for models providing common CRUD operations.
    """
    collection_name = None

    def __init__(self, business_id, user_id=None, user__id=None, agent_id=None, admin_id=None, created_by=None, **kwargs):
        self.business_id = ObjectId(business_id)
        self.user_id = user_id
        self.user__id = ObjectId(user__id)
        if agent_id:
            self.agent_id = agent_id
        if admin_id:
            self.admin_id = ObjectId(admin_id)
        if created_by:
            self.created_by = ObjectId(created_by)
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

        # Initialize model attributes based on kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self):
        """
        Convert the model object to a dictionary representation.
        """
        return {key: getattr(self, key) for key in self.__dict__}

    @classmethod
    def check_permission(cls, operation, custom_model_name=None):
        """
        Check if the current user has the necessary permission for the operation.
        `operation` like "read", "create", "update", "delete".
        `custom_model_name` overrides the default model name (cls.__name__.lower()).
        """
        # Ensure g.current_user is available
        if not hasattr(g, "current_user") or not g.current_user:
            raise PermissionError("No current user found for permission check.")

        account_type = None
        permissions = g.current_user.get("permissions", {})

        if g.current_user.get("account_type"):
            account_type = decrypt_data(g.current_user.get("account_type"))

        # decide model_name
        model_name = (custom_model_name or cls.__name__).lower()
        # model_name = custom_model_name if custom_model_name is not None else cls.__class__.__name__.lower()
        

        Log.info("account_type: %s" % account_type)
        Log.info("model_name: %s" % model_name)

        model_permissions = permissions.get(model_name, [])

        # Check if there are permissions listed for this model and operation
        if model_permissions:
            # Permissions are stored in a list, check the first item
            permission = model_permissions[0] or {}

            # Check if this operation is allowed OR the user is privileged
            if permission.get(operation) == "1" or account_type in (
                SYSTEM_USERS["SUPER_ADMIN"],
                SYSTEM_USERS["SYSTEM_OWNER"],
                SYSTEM_USERS["BUSINESS_OWNER"]
            ):
                return True

        # Privileged roles should be checked even if no model_permissions
        if account_type in (
            SYSTEM_USERS["SUPER_ADMIN"],
            SYSTEM_USERS["SYSTEM_OWNER"],
            SYSTEM_USERS["BUSINESS_OWNER"]
        ):
            return True

        # Allow consumers
        if account_type == SYSTEM_USERS.get("CONSUMER", "consumer"):
            return True

        return False

    
    def save(self, processing_callback=False):
        """
        Save the model to the database after checking permission.
        """
        # Check if permission is allowed and not callback process
        if not processing_callback:
            if not self.__class__.check_permission("create"):
                raise PermissionError(f"User does not have permission to create {self.__class__.__name__}.")
                

        collection = db.get_collection(self.collection_name)
        result = collection.insert_one(self.to_dict())
        return str(result.inserted_id)


    @classmethod
    def get_by_id(cls, record_id, business_id, is_logging_in=False):
        """
        Retrieve a record by its ID after checking permission.
        """
        
        if not is_logging_in:
            # Check if permission is allowed
            cls.verify_permission("read", cls.__name__.lower())
            
        collection = db.get_collection(cls.collection_name) 
        data = collection.find_one({
            "_id": ObjectId(record_id), 
            "business_id": ObjectId(business_id)
        })
        if not data:
            return None  # Record not found
        # return cls(**data)
        return data

    @classmethod
    def get_all(cls, business_id):
        """
        Retrieve all records for a business by business_id after checking permission.
        """
        # Permission check 
        if not cls.check_permission("read"):
            raise PermissionError(f"User does not have permission to read {cls.__name__}.")
            
        collection = db.get_collection(cls.collection_name)  # Use the custom collection name
        records = collection.find({"business_id": business_id})
        return [cls(**record) for record in records]

    @classmethod
    def update(cls, record_id, business_id, processing_callback=False, **updates):
        """
        Update a record by its ID after checking permission.
        """
        
        
        # Permission if permission is allowed and not callback processing
        if not processing_callback:
            cls.verify_permission("update", cls.__name__.lower())
        
        if business_id is not None:
            collection = db.get_collection(cls.collection_name)  # Use the custom collection name
            updates["updated_at"] = datetime.now()  # Add timestamp for update
            result = collection.update_one({"_id": ObjectId(record_id), "business_id": ObjectId(business_id)}, {"$set": updates})  # Fixed issue here
            return result.modified_count > 0
        else:
            
            collection = db.get_collection(cls.collection_name)  # Use the custom collection name
            updates["updated_at"] = datetime.now()  # Add timestamp for update
            result = collection.update_one({"_id": ObjectId(record_id)}, {"$set": updates})  # Fixed issue here
            return result.modified_count > 0
    
    @classmethod
    def update_account_status_by_id(cls, record_id, ip_address, field, update_value):
        if not cls.collection_name:
            return {"success": False, "message": "Collection name not defined."}

        collection = db.get_collection(cls.collection_name)

        try:
            document = collection.find_one({"_id": ObjectId(record_id)})
        except Exception as e:
            return {"success": False, "message": f"Invalid record ID: {e}"}

        if not document:
            return {"success": False, "message": f"{cls.__name__} record not found"}

        encrypted_account_status = document.get("account_status", None)

        if encrypted_account_status is None:
            return {"success": False, "message": "Account status not found"}

        try:
            account_status = decrypt_data(encrypted_account_status)
        except Exception as e:
            return {"success": False, "message": f"Error decrypting account status: {str(e)}"}

        field_updated = False

        for status in account_status:
            if field in status:
                status[field]["status"] = update_value
                status[field]["created_at"] = datetime.now(ZoneInfo("Europe/London")).strftime('%Y-%m-%d %H:%M:%S')
                status[field]["ip_address"] = ip_address
                field_updated = True
                break

        if not field_updated:
            return {"success": False, "message": f"Field '{field}' not found in account status"}

        try:
            encrypted_account_status = encrypt_data(account_status)
        except Exception as e:
            return {"success": False, "message": f"Error encrypting account status: {str(e)}"}

        result = collection.update_one(
            {"_id": ObjectId(record_id)},
            {"$set": {"account_status": encrypted_account_status}}
        )

        if result.modified_count > 0:
            return True
        else:
            return False
    
    @classmethod
    def update_image_upload_status(cls, record_id, ip_address, field, update_value, upload_category, orientation):
        if not cls.collection_name:
            return {"success": False, "message": "Collection name not defined."}

        collection = db.get_collection(cls.collection_name)

        try:
            document = collection.find_one({"_id": ObjectId(record_id)})
        except Exception as e:
            return {"success": False, "message": f"Invalid record ID: {e}"}

        if not document:
            return {"success": False, "message": f"{cls.__name__} record not found"}

        encrypted_account_status = document.get("image_upload_status", None)

        if encrypted_account_status is None:
            return {"success": False, "message": "Image upload status not found"}

        try:
            account_status = decrypt_data(encrypted_account_status)
        except Exception as e:
            return {"success": False, "message": f"Error decrypting account status: {str(e)}"}

        field_updated = False

        for status in account_status:
            if field in status:
                status[field]["upload_category"] = upload_category
                status[field]["orientation"] = orientation
                status[field]["status"] = update_value
                status[field]["created_at"] = datetime.now(ZoneInfo("Europe/London")).strftime('%Y-%m-%d %H:%M:%S')
                status[field]["ip_address"] = ip_address
                field_updated = True
                break

        if not field_updated:
            return {"success": False, "message": f"Field '{field}' not found in account status"}

        try:
            encrypted_account_status = encrypt_data(account_status)
        except Exception as e:
            return {"success": False, "message": f"Error encrypting account status: {str(e)}"}

        result = collection.update_one(
            {"_id": ObjectId(record_id)},
            {"$set": {"account_status": encrypted_account_status}}
        )

        if result.modified_count > 0:
            return True
        else:
            return False
    
    @classmethod
    def check_item_exists(cls, agent_id, key, value):
        """
        Check if an item exists by agent_id and a specific key (hashed comparison).
        This method allows dynamic checks for any key (like 'name', 'phone', etc.).
        
        Args:
        - agent_id: The agent ID to filter the items.
        - key: The key (field) to check for existence (e.g., 'name', 'phone').
        - value: The value of the key to check for existence.

        Returns:
        - True if the item exists, False otherwise.
        """
        
         # Check if the user has permission to 'add' before proceeding
        # if not cls.check_permission(cls, 'read'):
        #     raise PermissionError(f"User does not have permission to view {cls.__name__}.")
      
        # Ensure that agent_id is in the correct ObjectId format if it's passed as a string
        if isinstance(agent_id, str):
            try:
                agent_id = ObjectId(agent_id)  # Convert string agent_id to ObjectId
            except Exception as e:
                raise ValueError(f"Invalid agent_id format: {agent_id}") from e

        # Dynamically hash the value of the key
        hashed_key = hash_data(value)  # Hash the value provided for the dynamic field

        # Dynamically create the query with agent_id and hashed field
        query = {
            "agent_id": agent_id,
            f"hashed_{key}": hashed_key  # Use the key dynamically (e.g., "hashed_name" or "hashed_phone")
        }

        # Query the database for an item matching the given agent_id and hashed value
        collection = db.get_collection(cls.collection_name)
        existing_item = collection.find_one(query)

        # Return True if a matching item is found, else return False
        if existing_item:
            return True  # Item exists
        else:
            return False  # Item does not exist
    
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
    
    @classmethod
    def check_multiple_item_for_user_id_exists(cls, business_id, user_id, fields: dict):
        """
        Check if a beneficiary exists based on multiple fields (e.g., phone, user_id, email).
        This method allows dynamic checks for any number of fields using hashed values.

        :param business_id: The ID of the business.
        :param fields: Dictionary of fields to check (e.g., {"phone": "123456789", "user_id": "abc123"}).
        :return: True if the beneficiary exists, False otherwise.
        """
        try:
            # Check permissions first
            if not cls.check_permission(cls, 'read', 'collections'):
                raise PermissionError(f"User does not have permission to read {cls.__name__}.")

            # Ensure business_id is ObjectId
            try:
                business_id_obj = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e
            
            try:
                user_id_obj = ObjectId(user_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {user_id}") from e

            # Start building the query
            query = {"business_id": business_id_obj, "user_id": user_id_obj}

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
     
    @classmethod
    def check_item_admin_id_exists(cls, admin_id, key, value):
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
        
        # Ensure that agent_id is in the correct ObjectId format if it's passed as a string
        if isinstance(admin_id, str):
            try:
                admin_id = ObjectId(admin_id)  # Convert string admin_id to ObjectId
            except Exception as e:
                raise ValueError(f"Invalid admin_id format: {admin_id}") from e

        # Dynamically hash the value of the key
        hashed_key = hash_data(value)  # Hash the value provided for the dynamic field

        # Dynamically create the query with agent_id and hashed field
        query = {
            "admin_id": admin_id,
            f"hashed_{key}": hashed_key  # Use the key dynamically (e.g., "hashed_name" or "hashed_phone")
        }

        # Query the database for an item matching the given agent_id and hashed value
        collection = db.get_collection(cls.collection_name)
        existing_item = collection.find_one(query)

        # Return True if a matching item is found, else return False
        if existing_item:
            return True  # Item exists
        else:
            return False  # Item does not exist   
    
    @classmethod
    def check_item_exists_business_id(cls, business_id, key, value):
        """
        Check if an item exists by business_id and a specific key (hashed comparison).
        This method allows dynamic checks for any key (like 'name', 'phone', etc.).
        
        Args:
        - business_id: The Business ID to filter the items.
        - key: The key (field) to check for existence (e.g., 'name', 'phone').
        - value: The value of the key to check for existence.

        Returns:
        - True if the item exists, False otherwise.
        """
      
        # Ensure that business_id is in the correct ObjectId format if it's passed as a string
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)  # Convert string business_id to ObjectId
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e

        # Dynamically hash the value of the key
        hashed_key = hash_data(value)  # Hash the value provided for the dynamic field

        # Dynamically create the query with business_id and hashed field
        query = {
            "business_id": business_id,
            f"hashed_{key}": hashed_key  # Use the key dynamically (e.g., "hashed_name" or "hashed_phone")
        }

        # Query the database for an item matching the given business_id and hashed value
        collection = db.get_collection(cls.collection_name)
        existing_item = collection.find_one(query)

        # Return True if a matching item is found, else return False
        if existing_item:
            return True  # Item exists
        else:
            return False  # Item does not exist
    
    @classmethod
    def get_all_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve records by user__id + business_id with pagination.
        Handles user__id stored either as ObjectId or as plain string/number.
        """
        # Check if permission is allowed
        cls.verify_permission("read", cls.__name__.lower())

        # Defaults from env
        default_page = int(os.getenv("DEFAULT_PAGINATION_PAGE", 1))
        default_per_page = int(os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10))

        page = int(page) if page else default_page
        per_page = int(per_page) if per_page else default_per_page

        # business_id *must* be an ObjectId (as per your schema)
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            raise ValueError(f"Invalid business_id format: {business_id}")

        # user__id may be ObjectId OR plain value
        # Try to convert if it looks like a 24-char hex string, otherwise use raw
        user_filter = user__id
        if isinstance(user__id, str) and len(user__id) == 24:
            try:
                user_filter = ObjectId(user__id)
            except Exception:
                # fallback to raw string if conversion fails
                user_filter = user__id

        collection = db.get_collection(cls.collection_name)

        filter_query = {
            "business_id": business_id_obj,
            "user__id": user_filter,
        }

        cursor = collection.find(filter_query)
        total_count = collection.count_documents(filter_query)

        cursor = cursor.skip((page - 1) * per_page).limit(per_page)

        items = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            if "business_id" in doc:
                doc["business_id"] = str(doc["business_id"])
            if "user__id" in doc:
                doc["user__id"] = str(doc["user__id"])
            items.append(doc)

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "items": items,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page,
        } 
        
    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve records by business_id with pagination.
        """
        # Check if permission is allowed
        cls.verify_permission("read", cls.__name__.lower())

        # Defaults from env
        default_page = int(os.getenv("DEFAULT_PAGINATION_PAGE", 1))
        default_per_page = int(os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10))

        page = int(page) if page else default_page
        per_page = int(per_page) if per_page else default_per_page

        # business_id *must* be an ObjectId (as per your schema)
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            raise ValueError(f"Invalid business_id format: {business_id}")


        collection = db.get_collection(cls.collection_name)

        filter_query = {
            "business_id": business_id_obj,
        }

        cursor = collection.find(filter_query)
        total_count = collection.count_documents(filter_query)

        cursor = cursor.skip((page - 1) * per_page).limit(per_page)

        items = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            if "business_id" in doc:
                doc["business_id"] = str(doc["business_id"])
            if "user__id" in doc:
                doc["user__id"] = str(doc["user__id"])
            items.append(doc)

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "items": items,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page,
        } 
      
    @classmethod
    def delete(cls, record_id, business_id):
        """
        Delete a record by its ID after checking permission.
        """
        cls.verify_permission("delete", cls.__name__.lower())
        
        try:
            business_id_obj = ObjectId(business_id)
        except Exception as e:
            raise ValueError(f"Invalid business_id format: {business_id}") from e
        
        try:
            record_id_obj = ObjectId(record_id)
        except Exception as e:
            raise ValueError(f"Invalid record_id format: {record_id}") from e
        
        collection = db.get_collection(cls.collection_name)
        
        result = collection.delete_one({"_id": record_id_obj, "business_id": business_id_obj})
        return result.deleted_count > 0

    @classmethod
    def verify_permission(cls, operation, model_name):
        """
        Retrieve a record by its ID after checking permission.
        """
        # Permission check to verify of action is permitted
        if not cls.check_permission(operation, model_name):
            raise PermissionError(f"User does not have permission to {operation} {model_name}.")


    @classmethod
    def paginate(cls, query=None, page=None, per_page=None, sort=None):
        """
        Generic pagination helper for MongoDB collections.

        Args:
            query: dict MongoDB filter
            page: int page number (1-based). Defaults to 1.
            per_page: int items per page. Defaults to 50.
            sort:
                - None -> sort by ("created_at", -1) if field exists
                - list of (field, direction) tuples, e.g. [("created_at", -1)]
                - single (field, direction) tuple, e.g. ("created_at", -1)

        Returns:
            dict:
            {
                "items": [...],
                "total_count": <int>,
                "total_pages": <int>,
                "current_page": <int>,
                "per_page": <int>,
            }
        """
        log_tag = f"[base_model.py][{cls.__name__}][paginate]"

        # Normalise query
        if query is None:
            query = {}

        # Normalise pagination
        try:
            page_int = int(page) if page is not None else 1
        except (TypeError, ValueError):
            page_int = 1

        try:
            per_page_int = int(per_page) if per_page is not None else 50
        except (TypeError, ValueError):
            per_page_int = 50

        if page_int < 1:
            page_int = 1
        if per_page_int <= 0:
            per_page_int = 50

        try:
            collection = db.get_collection(cls.collection_name)

            # Total count
            total_count = collection.count_documents(query)

            # Build cursor
            cursor = collection.find(query)

            # Handle sort
            if sort is None:
                # Default sort by created_at desc if you use that everywhere
                sort_spec = [("created_at", -1)]
            elif isinstance(sort, tuple):
                sort_spec = [sort]
            else:
                # Expect list of tuples
                sort_spec = sort

            if sort_spec:
                cursor = cursor.sort(sort_spec)

            # Pagination window
            cursor = cursor.skip((page_int - 1) * per_page_int).limit(per_page_int)

            items = list(cursor)

            # Compute total_pages
            if per_page_int > 0:
                total_pages = (total_count + per_page_int - 1) // per_page_int
            else:
                total_pages = 1

            result = {
                "items": items,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page_int,
                "per_page": per_page_int,
            }

            Log.info(
                f"{log_tag} query={query} page={page_int} per_page={per_page_int} "
                f"returned {len(items)} items (total_count={total_count})"
            )
            return result

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "items": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page_int,
                "per_page": per_page_int,
            }



















































