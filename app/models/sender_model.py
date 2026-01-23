
import re, os, math, bcrypt, uuid
from bson.objectid import ObjectId
from datetime import datetime
from app.extensions.db import db
from ..utils.crypt import encrypt_data, decrypt_data, hash_data
from ..models.base_model import BaseModel


from datetime import datetime
import uuid

# Sender Model
class Sender(BaseModel):
    """
    A Sender represents an entity for payment information, including details
    about the sender's personal details and other verification fields.
    """
    collection_name = "senders"

    def __init__(self, user_id, business_id, agent_id, full_name, phone_number, dob, id_type, id_number, id_expiry, post_code_address, 
                 proof_of_address=None, proof_of_address_onboarding_status=None, approved_by=None, 
                 date_approved=None, proof_of_source_of_funds=None, proof_of_source_of_funds_onboarding_status=None,
                 reviewed_by=None, poa_date_reviewed=None, posof_date_reviewed=None, created_at=None, updated_at=None):
        
        super().__init__(user_id=user_id, business_id=business_id, agent_id=agent_id, full_name=full_name, phone_number=phone_number, dob=dob, 
                         id_type=id_type, id_number=id_number, id_expiry=id_expiry, post_code_address=post_code_address,
                         proof_of_address=proof_of_address, proof_of_address_onboarding_status=proof_of_address_onboarding_status,
                         approved_by=approved_by, date_approved=date_approved, proof_of_source_of_funds=proof_of_source_of_funds,
                         proof_of_source_of_funds_onboarding_status=proof_of_source_of_funds_onboarding_status,
                         reviewed_by=reviewed_by, poa_date_reviewed=poa_date_reviewed, posof_date_reviewed=posof_date_reviewed,
                         created_at=created_at, updated_at=updated_at)

        # No encryption for agent_id and id_number
        self.user_id = user_id
        self.business_id = business_id
        self.agent_id = agent_id
        
        # hashed keys
        self.hashed_phone_number = hash_data(phone_number) if phone_number else None
        self.hashed_full_name = hash_data(full_name) if full_name else None
        self.hashed_post_code_address = hash_data(post_code_address) if post_code_address else None

        # Encrypt other sensitive fields
        self.full_name = encrypt_data(full_name)
        self.phone_number = encrypt_data(phone_number)
        self.dob = encrypt_data(dob)
        self.id_type = encrypt_data(id_type)
        self.id_number = encrypt_data(id_number)
        self.id_expiry = encrypt_data(id_expiry)
        self.post_code_address = encrypt_data(post_code_address)
        self.proof_of_address = encrypt_data(proof_of_address) if proof_of_address else None
        self.proof_of_address_onboarding_status = encrypt_data(proof_of_address_onboarding_status) if proof_of_address_onboarding_status else None
        self.approved_by = encrypt_data(approved_by) if approved_by else None
        self.date_approved = encrypt_data(date_approved) if date_approved else None
        self.proof_of_source_of_funds = encrypt_data(proof_of_source_of_funds) if proof_of_source_of_funds else None
        self.proof_of_source_of_funds_onboarding_status = encrypt_data(proof_of_source_of_funds_onboarding_status) if proof_of_source_of_funds_onboarding_status else None
        self.reviewed_by = encrypt_data(reviewed_by) if reviewed_by else None
        self.poa_date_reviewed = encrypt_data(poa_date_reviewed) if poa_date_reviewed else None
        self.posof_date_reviewed = encrypt_data(posof_date_reviewed) if posof_date_reviewed else None
        

        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        """
        Convert the sender object to a dictionary representation.
        """
        sender_dict = super().to_dict()
        sender_dict.update({
            "user_id": self.user_id,
            "business_id": self.business_id,
            "agent_id": self.agent_id,
            "full_name": self.full_name,
            "phone_number": self.phone_number,
            "dob": self.dob,
            "id_type": self.id_type,
            "id_number": self.id_number,
            "id_expiry": self.id_expiry,
            "post_code_address": self.post_code_address,
            "proof_of_address": self.proof_of_address,
            "proof_of_address_onboarding_status": self.proof_of_address_onboarding_status,
            "approved_by": self.approved_by,
            "date_approved": self.date_approved,
            "proof_of_source_of_funds": self.proof_of_source_of_funds,
            "proof_of_source_of_funds_onboarding_status": self.proof_of_source_of_funds_onboarding_status,
            "reviewed_by": self.reviewed_by,
            "poa_date_reviewed": self.poa_date_reviewed,
            "posof_date_reviewed": self.posof_date_reviewed,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return sender_dict

    @classmethod
    def get_by_id(cls, sender_id):
        """
        Retrieve a sender by sender_id, decrypting all fields except the date fields.
        """
        try:
            sender_id_obj = ObjectId(sender_id)
        except Exception as e:
            return None

        sender_collection = db.get_collection(cls.collection_name)
        data = sender_collection.find_one({"_id": sender_id_obj})

        if not data:
            return None  # Sender not found

        data["_id"] = str(data["_id"])
        data["user_id"] = str(data["user_id"])
        data["business_id"] = str(data["business_id"])
        data["agent_id"] = str(data["agent_id"])

        # Decrypt fields before returning
        data["full_name"] = decrypt_data(data["full_name"])
        data["phone_number"] = decrypt_data(data["phone_number"])
        data["dob"] = decrypt_data(data["dob"])
        data["id_type"] = decrypt_data(data["id_type"])
        data["id_number"] = decrypt_data(data["id_number"])
        data["id_expiry"] = decrypt_data(data["id_expiry"])
        data["post_code_address"] = decrypt_data(data["post_code_address"])
        data["proof_of_address"] = decrypt_data(data["proof_of_address"]) if data.get("proof_of_address") else None
        data["proof_of_address_onboarding_status"] = decrypt_data(data["proof_of_address_onboarding_status"]) if data.get("proof_of_address_onboarding_status") else None
        data["approved_by"] = decrypt_data(data["approved_by"]) if data.get("approved_by") else None
        data["date_approved"] = decrypt_data(data["date_approved"]) if data.get("date_approved") else None
        data["proof_of_source_of_funds"] = decrypt_data(data["proof_of_source_of_funds"]) if data.get("proof_of_source_of_funds") else None
        data["proof_of_source_of_funds_onboarding_status"] = decrypt_data(data["proof_of_source_of_funds_onboarding_status"]) if data.get("proof_of_source_of_funds_onboarding_status") else None
        data["reviewed_by"] = decrypt_data(data["reviewed_by"]) if data.get("reviewed_by") else None
        data["poa_date_reviewed"] = decrypt_data(data["poa_date_reviewed"]) if data.get("poa_date_reviewed") else None
        data["posof_date_reviewed"] = decrypt_data(data["posof_date_reviewed"]) if data.get("posof_date_reviewed") else None

        data.pop("hashed_phone_number", None)
        data.pop("business_id", None)

        return data

    @classmethod
    def get_by_id_and_user_id_and_business_id(cls, sender_id, user_id, business_id):
        """
        Retrieve a sender by sender_id, user_id and business_id decrypting all fields except the date fields.
        """
        try:
            sender_id_obj = ObjectId(sender_id)
        except Exception as e:
            return None
        
        try:
            user_id_obj = ObjectId(user_id)
        except Exception as e:
            return None
        
        try:
            business_id_obj = ObjectId(business_id)
        except Exception as e:
            return None

        sender_collection = db.get_collection(cls.collection_name)
        data = sender_collection.find_one({
            "_id": sender_id_obj,
            "user_id": user_id_obj,
            "business_id": business_id_obj,
        })

        if not data:
            return None  # Sender not found

        data["_id"] = str(data["_id"])
        data["user_id"] = str(data["user_id"])
        data["business_id"] = str(data["business_id"])
        data["agent_id"] = str(data["agent_id"])

        # Decrypt fields before returning
        data["full_name"] = decrypt_data(data["full_name"])
        data["phone_number"] = decrypt_data(data["phone_number"])
        data["dob"] = decrypt_data(data["dob"])
        data["id_type"] = decrypt_data(data["id_type"])
        data["id_number"] = decrypt_data(data["id_number"])
        data["id_expiry"] = decrypt_data(data["id_expiry"])
        data["post_code_address"] = decrypt_data(data["post_code_address"])
        data["proof_of_address"] = decrypt_data(data["proof_of_address"]) if data.get("proof_of_address") else None
        data["proof_of_address_onboarding_status"] = decrypt_data(data["proof_of_address_onboarding_status"]) if data.get("proof_of_address_onboarding_status") else None
        data["approved_by"] = decrypt_data(data["approved_by"]) if data.get("approved_by") else None
        data["date_approved"] = decrypt_data(data["date_approved"]) if data.get("date_approved") else None
        data["proof_of_source_of_funds"] = decrypt_data(data["proof_of_source_of_funds"]) if data.get("proof_of_source_of_funds") else None
        data["proof_of_source_of_funds_onboarding_status"] = decrypt_data(data["proof_of_source_of_funds_onboarding_status"]) if data.get("proof_of_source_of_funds_onboarding_status") else None
        data["reviewed_by"] = decrypt_data(data["reviewed_by"]) if data.get("reviewed_by") else None
        data["poa_date_reviewed"] = decrypt_data(data["poa_date_reviewed"]) if data.get("poa_date_reviewed") else None
        data["posof_date_reviewed"] = decrypt_data(data["posof_date_reviewed"]) if data.get("posof_date_reviewed") else None

        data.pop("hashed_phone_number", None)
        data.pop("business_id", None)
        data.pop("hashed_full_name", None)
        data.pop("hashed_post_code_address", None)

        return data


    @classmethod
    def check_item_exists(cls, user_id, key, value):
        """
        Check if a sender exists based on a specific key (e.g., phone, user_id) and value.
        This method allows dynamic checks for any key (like 'phone', 'user_id', etc.) using hashed values.
        
        :param agent_id: The ID of the agent.
        :param key: The field to check (e.g., "phone", "user_id").
        :param value: The value to check for the given key.
        :return: True if the sender exists, False otherwise.
        """
        try:
            # Dynamically hash the value of the key
            hashed_key = hash_data(value)  # Assuming hash_data is a method to hash the value
            
            # Dynamically create the query with agent_id and hashed key
            query = {
                "user_id": user_id,  # Ensure query filters by agent_id
                f"hashed_{key}": hashed_key  # Use dynamic key for hashed comparison (e.g., "hashed_phone")
            }

            # Query the database for an item matching the given agent_id and hashed value
            sender_collection = db.get_collection(cls.collection_name)
            existing_item = sender_collection.find_one(query)

            # Return True if a matching item is found, else return False
            if existing_item:
                return True  # Item exists
            else:
                return False  # Item does not exist

        except Exception as e:
            # Handle errors and return False in case of an exception
            print(f"Error occurred: {e}")  # For debugging purposes
            return False

    @classmethod
    def get_senders_by_user_id(cls, user_id, page=1, per_page=10):
        """
        Retrieve senders by user_id, decrypting fields and implementing pagination.
        
        :param user_id: The user_id to search senders by.
        :param page: The page number to retrieve (default is 1).
        :param per_page: The number of senders to retrieve per page (default is 10).
        :return: A dictionary with the list of senders and pagination details.
        """
        # Ensure that user_id is in the correct ObjectId format if it's passed as a string
        if isinstance(user_id, str):
            try:
                user_id = ObjectId(user_id)  # Convert string user_id to ObjectId if necessary
            except Exception as e:
                raise ValueError(f"Invalid user_id format: {user_id}") from e

        
        # load default settings from env
        default_page = os.getenv("DEFAULT_PAGINATION_PAGE")
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE")
        
        # Ensure page and per_page are integers
        page = int(page) if page else int(default_page) # Convert page to integer
        per_page = int(per_page) if per_page else int(default_per_page) # Convert per_page to integer

        # Query the database to find senders by user_id
        sender_collection = db.get_collection(cls.collection_name)
        senders_cursor = sender_collection.find({"user_id": user_id})
        
        # Get total count for pagination using count_documents()
        total_count = sender_collection.count_documents({"user_id": user_id})

        # Apply pagination using skip and limit
        senders_cursor = senders_cursor.skip((page - 1) * per_page).limit(per_page)
        
        result = []
        for sender in senders_cursor:
            if not isinstance(sender, dict):  # Ensure sender is a dictionary
                raise ValueError(f"Expected a dictionary but got {type(sender)}")
            
            # Decrypt fields before returning them
            sender["full_name"] = decrypt_data(sender["full_name"])
            sender["phone_number"] = decrypt_data(sender["phone_number"])
            sender["dob"] = decrypt_data(sender["dob"])
            sender["id_type"] = decrypt_data(sender["id_type"])
            sender["id_number"] = decrypt_data(sender["id_number"])
            sender["id_expiry"] = decrypt_data(sender["id_expiry"])
            sender["post_code_address"] = decrypt_data(sender["post_code_address"])
            sender["proof_of_address"] = decrypt_data(sender["proof_of_address"]) if sender["proof_of_address"] else None
            sender["proof_of_address_onboarding_status"] = decrypt_data(sender["proof_of_address_onboarding_status"]) if sender.get("proof_of_address_onboarding_status") else None
            sender["approved_by"] = decrypt_data(sender["approved_by"]) if sender.get("approved_by") else None
            sender["date_approved"] = decrypt_data(sender["date_approved"]) if sender.get("date_approved") else None
            sender["proof_of_source_of_funds"] = decrypt_data(sender["proof_of_source_of_funds"]) if sender.get("proof_of_source_of_funds") else None
            sender["proof_of_source_of_funds_onboarding_status"] = decrypt_data(sender["proof_of_source_of_funds_onboarding_status"]) if sender.get("proof_of_source_of_funds_onboarding_status") else None
            sender["reviewed_by"] = decrypt_data(sender["reviewed_by"]) if sender.get("reviewed_by") else None
            sender["poa_date_reviewed"] = decrypt_data(sender["poa_date_reviewed"]) if sender.get("poa_date_reviewed") else None
            sender["posof_date_reviewed"] = decrypt_data(sender["posof_date_reviewed"]) if sender.get("posof_date_reviewed") else None

            # Clean up sensitive data (hashed values, etc.)
            sender.pop("hashed_phone_number", None)
            sender.pop("hashed_full_name", None)
            sender.pop("hashed_post_code_address", None)

            # Convert _id to string for proper JSON serialization
            sender["_id"] = str(sender["_id"])
            sender["user_id"] = str(sender["user_id"])
            sender["business_id"] = str(sender["business_id"])
            sender["agent_id"] = str(sender["agent_id"])

            # Append the processed sender data to the result list
            result.append(sender)

        # Calculate the total number of pages
        total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

        # Return paginated results
        return {
            "senders": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def get_senders_by_agent_id(cls, agent_id, page=1, per_page=10):
        """
        Retrieve senders by agent_id, decrypting fields and implementing pagination.
        
        :param agent_id: The agent_id to search senders by.
        :param page: The page number to retrieve (default is 1).
        :param per_page: The number of senders to retrieve per page (default is 10).
        :return: A dictionary with the list of senders and pagination details.
        """
        # Ensure that user_id is in the correct ObjectId format if it's passed as a string
        if isinstance(agent_id, str):
            try:
                agent_id = ObjectId(agent_id)  # Convert string agent_id to ObjectId if necessary
            except Exception as e:
                raise ValueError(f"Invalid agent_id format: {agent_id}") from e

        
        # load default settings from env
        default_page = os.getenv("DEFAULT_PAGINATION_PAGE")
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE")
        
        # Ensure page and per_page are integers
        page = int(page) if page else int(default_page) # Convert page to integer
        per_page = int(per_page) if per_page else int(default_per_page) # Convert per_page to integer

        # Query the database to find senders by user_id
        sender_collection = db.get_collection(cls.collection_name)
        senders_cursor = sender_collection.find({"agent_id": agent_id})
        
        # Get total count for pagination using count_documents()
        total_count = sender_collection.count_documents({"agent_id": agent_id})

        # Apply pagination using skip and limit
        senders_cursor = senders_cursor.skip((page - 1) * per_page).limit(per_page)
        
        result = []
        for sender in senders_cursor:
            if not isinstance(sender, dict):  # Ensure sender is a dictionary
                raise ValueError(f"Expected a dictionary but got {type(sender)}")
            
            # Decrypt fields before returning them
            sender["full_name"] = decrypt_data(sender["full_name"])
            sender["phone_number"] = decrypt_data(sender["phone_number"])
            sender["dob"] = decrypt_data(sender["dob"])
            sender["id_type"] = decrypt_data(sender["id_type"])
            sender["id_number"] = decrypt_data(sender["id_number"])
            sender["id_expiry"] = decrypt_data(sender["id_expiry"])
            sender["post_code_address"] = decrypt_data(sender["post_code_address"])
            sender["proof_of_address"] = decrypt_data(sender["proof_of_address"]) if sender["proof_of_address"] else None
            sender["proof_of_address_onboarding_status"] = decrypt_data(sender["proof_of_address_onboarding_status"]) if sender.get("proof_of_address_onboarding_status") else None
            sender["approved_by"] = decrypt_data(sender["approved_by"]) if sender.get("approved_by") else None
            sender["date_approved"] = decrypt_data(sender["date_approved"]) if sender.get("date_approved") else None
            sender["proof_of_source_of_funds"] = decrypt_data(sender["proof_of_source_of_funds"]) if sender.get("proof_of_source_of_funds") else None
            sender["proof_of_source_of_funds_onboarding_status"] = decrypt_data(sender["proof_of_source_of_funds_onboarding_status"]) if sender.get("proof_of_source_of_funds_onboarding_status") else None
            sender["reviewed_by"] = decrypt_data(sender["reviewed_by"]) if sender.get("reviewed_by") else None
            sender["poa_date_reviewed"] = decrypt_data(sender["poa_date_reviewed"]) if sender.get("poa_date_reviewed") else None
            sender["posof_date_reviewed"] = decrypt_data(sender["posof_date_reviewed"]) if sender.get("posof_date_reviewed") else None

            # Clean up sensitive data (hashed values, etc.)
            sender.pop("hashed_phone_number", None)
            sender.pop("hashed_full_name", None)
            sender.pop("hashed_post_code_address", None)
            

            # Convert _id to string for proper JSON serialization
            sender["_id"] = str(sender["_id"])
            sender["user_id"] = str(sender["user_id"])
            sender["business_id"] = str(sender["business_id"])
            sender["agent_id"] = str(sender["agent_id"])

            # Append the processed sender data to the result list
            result.append(sender)

        # Calculate the total number of pages
        total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

        # Return paginated results
        return {
            "senders": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def sender_search(cls, business_id, search_term=None, page=1, per_page=10):
        """
        Search senders by business_id using hashed fields (full_name, phone_number, post_code_address).
        Returns paginated, decrypted results.

        :param business_id: Business ID to scope the search.
        :param search_term: Term to search by (hashed match on name, phone, or postcode).
        :param page: Page number for pagination.
        :param per_page: Number of results per page.
        :return: dict with senders, pagination info, etc.
        """
        # ---- Validate / coerce IDs ----
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        # ---- Pagination ----
        try:
            page = int(page) if page else 1
        except Exception:
            page = 1
        try:
            per_page = int(per_page) if per_page else 10
        except Exception:
            per_page = 10
        page = max(1, page)
        per_page = max(1, per_page)

        # ---- Base query ----
        query = {"business_id": business_id_obj}

        # ---- Apply hashed search ----
        if search_term:
            hashed_term = hash_data(search_term.strip())
            query["$or"] = [
                {"hashed_full_name": hashed_term},
                {"hashed_phone_number": hashed_term},
                {"hashed_post_code_address": hashed_term},
            ]

        # ---- Query Mongo ----
        collection = db.get_collection(cls.collection_name)
        total_count = collection.count_documents(query)
        total_pages = math.ceil(total_count / per_page) if per_page else 1
        skip = (page - 1) * per_page

        cursor = collection.find(query).skip(skip).limit(per_page)

        # ---- Fields to decrypt ----
        fields_to_decrypt = [
            "full_name",
            "phone_number",
            "email",
            "dob",
            "id_type",
            "id_number",
            "id_expiry",
            "post_code_address",
            "proof_of_address",
            "proof_of_address_onboarding_status",
            "approved_by",
            "date_approved",
            "proof_of_source_of_funds",
            "proof_of_source_of_funds_onboarding_status",
            "reviewed_by",
            "poa_date_reviewed",
            "posof_date_reviewed",
            "status",
        ]

        senders = []
        for doc in cursor:
            if not isinstance(doc, dict):
                continue  # skip invalid records

            # Convert ObjectIds
            doc_id = str(doc.get("_id")) if doc.get("_id") else None
            user_id = str(doc.get("user_id")) if doc.get("user_id") else None
            agent_id = str(doc.get("agent_id")) if doc.get("agent_id") else None
            business_id_str = str(doc.get("business_id")) if doc.get("business_id") else None

            # Decrypt sensitive fields
            decrypted = {}
            for f in fields_to_decrypt:
                decrypted[f] = decrypt_data(doc.get(f)) if doc.get(f) else None

            # Remove hashed values from response
            doc.pop("hashed_full_name", None)
            doc.pop("hashed_phone_number", None)
            doc.pop("hashed_post_code_address", None)

            # Assemble final output
            senders.append({
                "_id": doc_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "business_id": business_id_str,

                "full_name": decrypted["full_name"],
                "phone_number": decrypted["phone_number"],
                "email": decrypted["email"],
                "dob": decrypted["dob"],
                "id_type": decrypted["id_type"],
                "id_number": decrypted["id_number"],
                "id_expiry": decrypted["id_expiry"],
                "post_code_address": decrypted["post_code_address"],
                "proof_of_address": decrypted["proof_of_address"],
                "proof_of_address_onboarding_status": decrypted["proof_of_address_onboarding_status"],
                "approved_by": decrypted["approved_by"],
                "date_approved": decrypted["date_approved"],
                "proof_of_source_of_funds": decrypted["proof_of_source_of_funds"],
                "proof_of_source_of_funds_onboarding_status": decrypted["proof_of_source_of_funds_onboarding_status"],
                "reviewed_by": decrypted["reviewed_by"],
                "poa_date_reviewed": decrypted["poa_date_reviewed"],
                "posof_date_reviewed": decrypted["posof_date_reviewed"],
                "status": decrypted["status"],

                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at"),
            })

        return {
            "senders": senders,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page,
        }

    @classmethod
    def update(cls, sender_id, business_id, **updates):
        """
        Update a sender's information by sender_id.
        """
        if "full_name" in updates:
            updates["full_name"] = encrypt_data(updates["full_name"])
        if "phone_number" in updates:
            updates["phone_number"] = encrypt_data(updates["phone_number"])
            updates["hashed_phone_number"] = hash_data(updates["phone_number"])
        if "dob" in updates:
            updates["dob"] = encrypt_data(updates["dob"])
        if "id_type" in updates:
            updates["id_type"] = encrypt_data(updates["id_type"])
        if "id_number" in updates:
            updates["id_number"] = encrypt_data(updates["id_number"])
        if "id_expiry" in updates:
            updates["id_expiry"] = encrypt_data(updates["id_expiry"])
        if "post_code_address" in updates:
            updates["post_code_address"] = encrypt_data(updates["post_code_address"]) 
        if "proof_of_address" in updates:
            updates["proof_of_address"] = encrypt_data(updates["proof_of_address"]) if updates.get("proof_of_address") else None
        if "proof_of_address_onboarding_status" in updates:
            updates["proof_of_address_onboarding_status"] = encrypt_data(updates["proof_of_address_onboarding_status"]) if updates.get("proof_of_address_onboarding_status") else None
        if "approved_by" in updates:
            updates["approved_by"] = encrypt_data(updates["approved_by"]) if updates.get("approved_by") else None
        if "date_approved" in updates:
            updates["date_approved"] = encrypt_data(updates["date_approved"]) if updates.get("date_approved") else None
        if "proof_of_source_of_funds" in updates:
            updates["proof_of_source_of_funds"] = encrypt_data(updates["proof_of_source_of_funds"]) if updates.get("proof_of_source_of_funds") else None
        if "proof_of_source_of_funds_onboarding_status" in updates:
            updates["proof_of_source_of_funds_onboarding_status"] = encrypt_data(updates["proof_of_source_of_funds_onboarding_status"]) if updates.get("proof_of_source_of_funds_onboarding_status") else None
        if "reviewed_by" in updates:
            updates["reviewed_by"] = encrypt_data(updates["reviewed_by"]) if updates.get("reviewed_by") else None
        if "poa_date_reviewed" in updates:
            updates["poa_date_reviewed"] = encrypt_data(updates["poa_date_reviewed"]) if updates.get("poa_date_reviewed") else None
        if "posof_date_reviewed" in updates:
            updates["posof_date_reviewed"] = encrypt_data(updates["posof_date_reviewed"]) if updates.get("posof_date_reviewed") else None

        return super().update(sender_id, business_id, **updates)

    @classmethod
    def delete(cls, sender_id, business_id):
        """
        Delete a sender by sender_id.
        """
        return super().delete(sender_id, business_id)


