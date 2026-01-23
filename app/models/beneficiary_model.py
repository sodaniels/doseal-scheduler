import uuid
import bcrypt
import os
from bson.objectid import ObjectId
from datetime import datetime
from app.extensions.db import db
from ..utils.crypt import encrypt_data, decrypt_data, hash_data
from ..models.base_model import BaseModel


from datetime import datetime
import uuid

#Beneficiary model
class Beneficiary(BaseModel):
    """
    A Beneficiary represents an entity for payment information, including details
    about the payment mode, bank information, recipient details, and other
    payment-related fields.
    """

    collection_name = "beneficiaries"

    def __init__(self, business_id, user_id, agent_id, payment_mode, country, sender_id, address=None, flag=None, currency_code=None, bank_name=None,
                 account_name=None, account_number=None, recipient_name=None, recipient_phone_number=None, mno=None,
                 routing_number=None, verified_name=None, recipient_country_iso2=None, recipient_country_iso3=None,
                 status="Active", created_at=None, updated_at=None,):
        
        super().__init__(user_id=user_id, business_id=business_id, agent_id=agent_id, payment_mode=payment_mode, 
                         country=country, sender_id=sender_id, address=address, flag=flag,
                         currency_code=currency_code, bank_name=bank_name, account_name=account_name, 
                         account_number=account_number, recipient_name=recipient_name, 
                         recipient_phone_number=recipient_phone_number, mno=mno, routing_number=routing_number,
                         verified_name=verified_name, recipient_country_iso2=recipient_country_iso2, 
                         recipient_country_iso3=recipient_country_iso3, status=status, 
                         created_at=created_at, updated_at=updated_at)

        # No encryption for business_id and user_id
        self.business_id = ObjectId(business_id)
        self.user_id = user_id
        self.agent_id = agent_id
        self.sender_id = ObjectId(sender_id)
        
        # hashed keys
        self.hashed_account_number = hash_data(account_number) if account_number else None
        self.hashed_mno = hash_data(mno) if mno else None
        self.hashed_recipient_phone_number = hash_data(recipient_phone_number) if recipient_phone_number else None

        # Encrypt other sensitive fields
        self.payment_mode = encrypt_data(payment_mode)
        self.country = encrypt_data(country)
        self.address = encrypt_data(address) if address else None
        self.flag = encrypt_data(flag) if flag else None
        self.currency_code = encrypt_data(currency_code) if currency_code else None
        self.bank_name = encrypt_data(bank_name) if bank_name else None
        self.account_name = encrypt_data(account_name) if account_name else None
        self.account_number = encrypt_data(account_number) if account_number else None
        self.recipient_name = encrypt_data(recipient_name) if recipient_name else None
        self.recipient_phone_number = encrypt_data(recipient_phone_number) if recipient_phone_number else None
        self.mno = encrypt_data(mno) if mno else None
        self.routing_number = encrypt_data(routing_number) if routing_number else None
        self.verified_name = encrypt_data(verified_name) if verified_name else None
        self.recipient_country_iso2 = encrypt_data(recipient_country_iso2)
        self.recipient_country_iso3 = encrypt_data(recipient_country_iso3) if recipient_country_iso3 else None
        self.status = encrypt_data(status)
        self.date = encrypt_data(str(datetime.now()))
        # Add created and updated timestamps
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        """
        Convert the beneficiary object to a dictionary representation.
        """
        beneficiary_dict = super().to_dict()
        beneficiary_dict.update({
            "business_id": self.business_id,
            "user_id": self.user_id, 
            "agent_id": self.agent_id, 
            "sender_id": self.sender_id, 
            "payment_mode": self.payment_mode,
            "country": self.country,
            "address": self.address,
            "flag": self.flag,
            "currency_code": self.currency_code,
            "bank_name": self.bank_name,
            "account_name": self.account_name,
            "account_number": self.account_number,
            "recipient_name": self.recipient_name,
            "recipient_phone_number": self.recipient_phone_number,
            "mno": self.mno,
            "routing_number": self.routing_number,
            "verified_name": self.verified_name,
            "recipient_country_iso2": self.recipient_country_iso2,
            "recipient_country_iso3": self.recipient_country_iso3,
            "date": self.date,
            "status": self.status,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return beneficiary_dict

    @classmethod
    def get_by_id(cls, beneficiary_id, business_id=None):
        """
        Retrieve a beneficiary by beneficiary_id, decrypting sensitive fields.
        """
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None
        
        try:
            beneficiary_id_obj = ObjectId(beneficiary_id)
        except Exception:
            return None
        
        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({"_id": beneficiary_id_obj, "business_id": business_id_obj})
        if not data:
            return None  # Beneficiary not found

        # Convert ObjectIds to strings
        data["_id"] = str(data["_id"])
        data["user_id"] = str(data["user_id"]) if data.get("user_id") else None
        data["agent_id"] = str(data["agent_id"]) if data.get("agent_id") else None
        data["sender_id"] = str(data["sender_id"]) if data.get("sender_id") else None

        # Fields to decrypt
        fields_to_decrypt = [
            "payment_mode", "country", "address", "flag", "currency_code", "bank_name",
            "account_name", "account_number", "recipient_name", "recipient_phone_number",
            "mno", "routing_number", "verified_name", "recipient_country_iso2",
            "recipient_country_iso3", "status", "date"
        ]

        decrypted = {}
        for field in fields_to_decrypt:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        return {
            "beneficiary_id": str(data["_id"]),
            "user_id": data["user_id"],
            "agent_id": data["agent_id"],
            "sender_id": data["sender_id"],
            "payment_mode": decrypted["payment_mode"],
            "country": decrypted["country"],
            "address": decrypted["address"],
            "flag": decrypted["flag"],
            "currency_code": decrypted["currency_code"],
            "bank_name": decrypted["bank_name"],
            "account_name": decrypted["account_name"],
            "account_number": decrypted["account_number"],
            "recipient_name": decrypted["recipient_name"],
            "recipient_phone_number": decrypted["recipient_phone_number"],
            "mno": decrypted["mno"],
            "routing_number": decrypted["routing_number"],
            "verified_name": decrypted["verified_name"],
            "recipient_country_iso2": decrypted["recipient_country_iso2"],
            "recipient_country_iso3": decrypted["recipient_country_iso3"],
            "status": decrypted["status"],
            "date": decrypted["date"],
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    @classmethod
    def get_by_id_and_user_id_and_business_id(cls, beneficiary_id, user_id, business_id):
        """
        Retrieve a beneficiary by beneficiary_id, user_id, decrypting sensitive fields.
        """
        try:
            beneficiary_id_obj = ObjectId(beneficiary_id)
        except Exception:
            return None
        
        try:
            user_id_obj = ObjectId(user_id)
        except Exception:
            return None
        
        try:
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None
        
        collection = db.get_collection(cls.collection_name)
        data = collection.find_one({
            "_id": beneficiary_id_obj,
            "user_id": user_id_obj,
            "business_id": business_id_obj,
        })
        if not data:
            return None  # Beneficiary not found

        # Convert ObjectIds to strings
        data["_id"] = str(data["_id"])
        data["user_id"] = str(data["user_id"]) if data.get("user_id") else None
        data["agent_id"] = str(data["agent_id"]) if data.get("agent_id") else None
        data["sender_id"] = str(data["sender_id"]) if data.get("sender_id") else None

        # Fields to decrypt
        fields_to_decrypt = [
            "payment_mode", "country", "address", "flag", "currency_code", "bank_name",
            "account_name", "account_number", "recipient_name", "recipient_phone_number",
            "mno", "routing_number", "verified_name", "recipient_country_iso2",
            "recipient_country_iso3", "status", "date"
        ]

        decrypted = {}
        for field in fields_to_decrypt:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        return {
            "beneficiary_id": str(data["_id"]),
            "user_id": data["user_id"],
            "agent_id": data["agent_id"],
            "sender_id": data["sender_id"],
            "payment_mode": decrypted["payment_mode"],
            "country": decrypted["country"],
            "address": decrypted["address"],
            "flag": decrypted["flag"],
            "currency_code": decrypted["currency_code"],
            "bank_name": decrypted["bank_name"],
            "account_name": decrypted["account_name"],
            "account_number": decrypted["account_number"],
            "recipient_name": decrypted["recipient_name"],
            "recipient_phone_number": decrypted["recipient_phone_number"],
            "mno": decrypted["mno"],
            "routing_number": decrypted["routing_number"],
            "verified_name": decrypted["verified_name"],
            "recipient_country_iso2": decrypted["recipient_country_iso2"],
            "recipient_country_iso3": decrypted["recipient_country_iso3"],
            "status": decrypted["status"],
            "date": decrypted["date"],
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }


    @classmethod
    def check_item_exists(cls, business_id, key, value):
        """
        Check if a beneficiary exists based on a specific key (e.g., phone, user_id) and value.
        This method allows dynamic checks for any key (like 'phone', 'user_id', etc.) using hashed values.
        
        :param business_id: The ID of the business.
        :param key: The field to check (e.g., "phone", "user_id").
        :param value: The value to check for the given key.
        :return: True if the beneficiary exists, False otherwise.
        """
        try:
            # Check if the user has permission to 'add' before proceeding
            if not cls.check_permission(cls, 'add'):
                raise PermissionError(f"User does not have permission to view {cls.__name__}.")

            # Ensure that business_id is in the correct ObjectId format if it's passed as a string
            try:
                business_id_obj = ObjectId(business_id)  # Convert string business_id to ObjectId
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e

                
            # Dynamically hash the value of the key
            hashed_key = hash_data(value)  # Assuming hash_data is a method to hash the value
            
            # Dynamically create the query with business_id and hashed key
            query = {
                "business_id": business_id_obj,  # Ensure query filters by business_id
                f"hashed_{key}": hashed_key  # Use dynamic key for hashed comparison (e.g., "hashed_phone")
            }

            # Query the database for an item matching the given business_id and hashed value
            collection = db.get_collection(cls.collection_name)
            existing_item = collection.find_one(query)

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
    def get_beneficiaries_by_user_id(cls, user_id, page=1, per_page=10):
        """
        Retrieve beneficiaries by user_id, decrypting fields and implementing pagination.

        :param user_id: The user_id to search beneficiaries by.
        :param page: The page number to retrieve (default is 1).
        :param per_page: The number of beneficiaries to retrieve per page (default is 10).
        :return: A dictionary with the list of beneficiaries and pagination details.
        """
        # Ensure that user_id is in the correct ObjectId format if it's passed as a string
        if isinstance(user_id, str):
            try:
                user_id = ObjectId(user_id)  # Convert string user_id to ObjectId if necessary
            except Exception as e:
                raise ValueError(f"Invalid user_id format: {user_id}") from e

        # Load default settings from environment
        default_page = os.getenv("DEFAULT_PAGINATION_PAGE", 1)  # Default to 1 if not found
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10)  # Default to 10 if not found
        total_pages = None

        # Ensure page and per_page are integers
        page = int(page) if page else int(default_page)  # Convert page to integer
        per_page = int(per_page) if per_page else int(default_per_page)  # Convert per_page to integer

        # Query the database to find beneficiaries by user_id
        collection = db.get_collection(cls.collection_name)
        beneficiaries_cursor = collection.find({"user_id": user_id})

        # Get total count for pagination using count_documents()
        total_count = collection.count_documents({"user_id": user_id})

        # Apply pagination using skip and limit
        beneficiaries_cursor = beneficiaries_cursor.skip((page - 1) * per_page).limit(per_page)
        
        fields_to_decrypt = [
            "payment_mode", "country", "flag", "currency_code", "bank_name",
            "account_name", "account_number", "recipient_name", "recipient_phone_number",
            "mno", "routing_number", "verified_name", "recipient_country_iso2",
            "recipient_country_iso3", "post_code", "date", "status"
        ]
 
        result = []
        for beneficiary in beneficiaries_cursor:
            decrypted = {}
            for field in fields_to_decrypt:
                decrypted[field] = decrypt_data(beneficiary.get(field)) if beneficiary.get(field) else None

            result.append({
                "_id": str(beneficiary["_id"]),
                "user_id": str(beneficiary.get("user_id")),
                "agent_id": str(beneficiary.get("agent_id")),
                "business_id": str(beneficiary.get("business_id")),
                "sender_id": str(beneficiary.get("sender_id")),
                "payment_mode": decrypted["payment_mode"],
                "country": decrypted["country"],
                "flag": decrypted["flag"],
                "currency_code": decrypted["currency_code"],
                "bank_name": decrypted["bank_name"],
                "account_name": decrypted["account_name"],
                "account_number": decrypted["account_number"],
                "recipient_name": decrypted["recipient_name"],
                "recipient_phone_number": decrypted["recipient_phone_number"],
                "mno": decrypted["mno"],
                "routing_number": decrypted["routing_number"],
                "verified_name": decrypted["verified_name"],
                "recipient_country_iso2": decrypted["recipient_country_iso2"],
                "recipient_country_iso3": decrypted["recipient_country_iso3"],
                "post_code": decrypted["post_code"],
                "date": decrypted["date"],
                "status": decrypted["status"],
                "created_at": beneficiary.get("created_at"),
                "updated_at": beneficiary.get("updated_at")
            })
    

            # Calculate the total number of pages
            total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

        # Return paginated results
        return {
            "beneficiaries": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def get_beneficiaries_search(
        cls,
        business_id,
        page=1,
        per_page=10,
        recipient_phone_number=None,
        account_number=None,
    ):
        """
        Retrieve beneficiaries by business_id, with optional search by
        recipient_phone_number or account_number (hashed lookup). Supports decryption and pagination.

        :param business_id: The business_id to search beneficiaries by.
        :param page: Page number to retrieve (default 1).
        :param per_page: Page size (default 10).
        :param recipient_phone_number: Optional recipient phone number to filter.
        :param account_number: Optional account number to filter.
        :return: Dict with beneficiaries and pagination details.
        """

        # ---- ID coercion ----
        try:
            business_id = ObjectId(business_id)
        except Exception as e:
            raise ValueError(f"Invalid business_id format: {business_id}") from e

        # ---- Pagination defaults ----
        default_page = int(os.getenv("DEFAULT_PAGINATION_PAGE", 1))
        default_per_page = int(os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10))
        page = int(page) if page else default_page
        per_page = int(per_page) if per_page else default_per_page
        if page < 1:
            page = default_page
        if per_page < 1:
            per_page = default_per_page

        collection = db.get_collection(cls.collection_name)

        # ---- Base query ----
        query = {"business_id": business_id}

        # ---- Optional hashed search conditions ----
        def _clean(s):
            return s.strip() if isinstance(s, str) else s

        search_conditions = []
        if recipient_phone_number:
            search_conditions.append({
                "hashed_recipient_phone_number": hash_data(_clean(recipient_phone_number))
            })
        if account_number:
            search_conditions.append({
                "hashed_account_number": hash_data(_clean(account_number))
            })
        if search_conditions:
            query["$or"] = search_conditions

        # ---- Projection (pull only needed fields) ----
        projection = {
            "_id": 1, "user_id": 1, "agent_id": 1, "business_id": 1, "sender_id": 1,
            "payment_mode": 1, "country": 1, "flag": 1, "currency_code": 1,
            "bank_name": 1, "account_name": 1, "account_number": 1,
            "recipient_name": 1, "recipient_phone_number": 1, "mno": 1,
            "routing_number": 1, "verified_name": 1, "recipient_country_iso2": 1,
            "recipient_country_iso3": 1, "post_code": 1, "date": 1, "status": 1,
            "created_at": 1, "updated_at": 1,
        }

        # ---- Count & query (sorted for stable pagination) ----
        total_count = collection.count_documents(query)
        cursor = (
            collection.find(query, projection=projection)
            .sort("created_at", -1)
            .skip((page - 1) * per_page)
            .limit(per_page)
        )

        fields_to_decrypt = [
            "payment_mode", "country", "flag", "currency_code", "bank_name",
            "account_name", "account_number", "recipient_name", "recipient_phone_number",
            "mno", "routing_number", "verified_name", "recipient_country_iso2",
            "recipient_country_iso3", "post_code", "date", "status",
        ]

        results = []
        for b in cursor:
            dec = {}
            for f in fields_to_decrypt:
                dec[f] = decrypt_data(b.get(f)) if b.get(f) else None
            results.append({
                "_id": str(b["_id"]),
                "user_id": str(b.get("user_id")) if b.get("user_id") else None,
                "agent_id": str(b.get("agent_id")) if b.get("agent_id") else None,
                "business_id": str(b.get("business_id")) if b.get("business_id") else None,
                "sender_id": str(b.get("sender_id")) if b.get("sender_id") else None,
                "payment_mode": dec["payment_mode"],
                "country": dec["country"],
                "flag": dec["flag"],
                "currency_code": dec["currency_code"],
                "bank_name": dec["bank_name"],
                "account_name": dec["account_name"],
                "account_number": dec["account_number"],
                "recipient_name": dec["recipient_name"],
                "recipient_phone_number": dec["recipient_phone_number"],
                "mno": dec["mno"],
                "routing_number": dec["routing_number"],
                "verified_name": dec["verified_name"],
                "recipient_country_iso2": dec["recipient_country_iso2"],
                "recipient_country_iso3": dec["recipient_country_iso3"],
                "post_code": dec["post_code"],
                "date": dec["date"],
                "status": dec["status"],
                "created_at": b.get("created_at"),
                "updated_at": b.get("updated_at"),
            })

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "beneficiaries": results,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page,
            "search_applied": bool(search_conditions),
        }


    @classmethod
    def get_beneficiaries_by_sender_id(cls, sender_id, page=1, per_page=10):
        """
        Retrieve beneficiaries by sender_id, decrypting fields and implementing pagination.

        :param sender_id: The sender_id to search beneficiaries by.
        :param page: The page number to retrieve (default is 1).
        :param per_page: The number of beneficiaries to retrieve per page (default is 10).
        :return: A dictionary with the list of beneficiaries and pagination details.
        """
        # Ensure that sender_id is in the correct ObjectId format if it's passed as a string
        if isinstance(sender_id, str):
            try:
                sender_id = ObjectId(sender_id)  # Convert string sender_id to ObjectId if necessary
            except Exception as e:
                raise ValueError(f"Invalid sender_id format: {sender_id}") from e

        # Load default settings from environment
        default_page = os.getenv("DEFAULT_PAGINATION_PAGE", 1)  # Default to 1 if not found
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10)  # Default to 10 if not found
        total_pages = None

        # Ensure page and per_page are integers
        page = int(page) if page else int(default_page)  # Convert page to integer
        per_page = int(per_page) if per_page else int(default_per_page)  # Convert per_page to integer

        # Query the database to find beneficiaries by user_id
        sender_collection = db.get_collection(cls.collection_name)
        beneficiaries_cursor = sender_collection.find({"sender_id": sender_id})

        # Get total count for pagination using count_documents()
        total_count = sender_collection.count_documents({"sender_id": sender_id})

        # Apply pagination using skip and limit
        beneficiaries_cursor = beneficiaries_cursor.skip((page - 1) * per_page).limit(per_page)
        
        fields_to_decrypt = [
            "payment_mode", "country", "flag", "currency_code", "bank_name",
            "account_name", "account_number", "recipient_name", "recipient_phone_number",
            "mno", "routing_number", "verified_name", "recipient_country_iso2",
            "recipient_country_iso3", "post_code", "date", "status"
        ]
 
        result = []
        for beneficiary in beneficiaries_cursor:
            decrypted = {}
            for field in fields_to_decrypt:
                decrypted[field] = decrypt_data(beneficiary.get(field)) if beneficiary.get(field) else None

            result.append({
                "_id": str(beneficiary["_id"]),
                "user_id": str(beneficiary.get("user_id")),
                "agent_id": str(beneficiary.get("agent_id")),
                "business_id": str(beneficiary.get("business_id")),
                "sender_id": str(beneficiary.get("sender_id")),
                "payment_mode": decrypted["payment_mode"],
                "country": decrypted["country"],
                "flag": decrypted["flag"],
                "currency_code": decrypted["currency_code"],
                "bank_name": decrypted["bank_name"],
                "account_name": decrypted["account_name"],
                "account_number": decrypted["account_number"],
                "recipient_name": decrypted["recipient_name"],
                "recipient_phone_number": decrypted["recipient_phone_number"],
                "mno": decrypted["mno"],
                "routing_number": decrypted["routing_number"],
                "verified_name": decrypted["verified_name"],
                "recipient_country_iso2": decrypted["recipient_country_iso2"],
                "recipient_country_iso3": decrypted["recipient_country_iso3"],
                "post_code": decrypted["post_code"],
                "date": decrypted["date"],
                "status": decrypted["status"],
                "created_at": beneficiary.get("created_at"),
                "updated_at": beneficiary.get("updated_at")
            })
    

            # Calculate the total number of pages
            total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

        # Return paginated results
        return {
            "beneficiaries": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def update(cls, beneficiary_id, business_id, **updates):
        """
        Update a beneficiary's information by beneficiary_id.
        """
        if "payment_mode" in updates:
            updates["payment_mode"] = encrypt_data(updates["payment_mode"])
        if "country" in updates:
            updates["country"] = encrypt_data(updates["country"])
        if "address" in updates:
            updates["address"] = encrypt_data(updates["address"]) if updates.get("address") else None
        if "flag" in updates:
            updates["flag"] = encrypt_data(updates["flag"]) if updates.get("flag") else None
        if "currency_code" in updates:
            updates["currency_code"] = encrypt_data(updates["currency_code"]) if updates.get("currency_code") else None
        if "bank_name" in updates:
            updates["bank_name"] = encrypt_data(updates["bank_name"]) if updates.get("bank_name") else None
        if "account_name" in updates:
            updates["account_name"] = encrypt_data(updates["account_name"]) if updates.get("account_name") else None
            updates["hashed_account_number"] = hash_data(updates["account_name"]) if updates.get("account_name") else None
        if "account_number" in updates:
            updates["account_number"] = encrypt_data(updates["account_number"]) if updates.get("account_number") else None
        if "recipient_name" in updates:
            updates["recipient_name"] = encrypt_data(updates["recipient_name"]) if updates.get("recipient_name") else None
        if "recipient_phone_number" in updates:
            updates["recipient_phone_number"] = encrypt_data(updates["recipient_phone_number"]) if updates.get("recipient_phone_number") else None
            updates["hashed_recipient_phone_number"] = hash_data(updates["recipient_phone_number"]) if updates.get("recipient_phone_number") else None
        if "mno" in updates:
            updates["mno"] = encrypt_data(updates["mno"]) if updates.get("mno") else None
        if "routing_number" in updates:
            updates["routing_number"] = encrypt_data(updates["routing_number"]) if updates.get("routing_number") else None
        if "verified_name" in updates:
            updates["verified_name"] = encrypt_data(updates["verified_name"]) if updates.get("verified_name") else None
        if "recipient_country_iso2" in updates:
            updates["recipient_country_iso2"] = encrypt_data(updates["recipient_country_iso2"])
        if "recipient_country_iso3" in updates:
            updates["recipient_country_iso3"] = encrypt_data(updates["recipient_country_iso3"]) if updates.get("recipient_country_iso3") else None

        return super().update(beneficiary_id, business_id, **updates)

    @classmethod
    def delete(cls, beneficiary_id, business_id):
        """
        Delete a beneficiary by beneficiary_id.
        """
        return super().delete(beneficiary_id, business_id)