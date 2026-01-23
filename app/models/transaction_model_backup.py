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

#Transaction model
class Transaction(BaseModel):
    """
    A Transaction represents a financial or operational transaction, including
    details about the transaction type, sender, receiver, amount details, and
    other payment-related fields.
    """

    collection_name = "transactions"

    def __init__(self, tenant_id, business_id=None, user_id=None, user__id=None, beneficiary_id=None, beneficiary_account=None,
                 sender_id=None, agent_id=None, is_external_partner=False, payment_mode=None, billpay_id=None, sender_account=None,
                 extr_id=None, receiver_country=None, system_reference=None, common_identifier=None, checksum=None, 
                 access_mode=None, account_id=None, user_contact_id=None, account=None, transaction_type=None, 
                 zeepay_id=None, trans_id=None, medium=None, mno=None, receiver_msisdn=None, transaction_status=None, 
                 status_message=None, sender_details=None, recipient_details=None, fraud_kyc=None, payable=None, 
                 amount_details=None, extra=None, address=None, description=None, internal_reference=None,
                 external_reference=None, external_response=None, gift_card_provider=None, user_payload=None, payload=None, 
                 payment_type=None, gateway_id=None,status=None, status_code=411, provider=None, cr_created=False, reversed=False, 
                 created_by=None, referrer=None, callback_url=None, created_at=None, updated_at=None):

        super().__init__(tenant_id=tenant_id, business_id=business_id, user_id=user_id,user__id=user__id, beneficiary_id=beneficiary_id, beneficiary_account=beneficiary_account, 
                         agent_id=agent_id, sender_account=sender_account, payment_mode=payment_mode, checksum=checksum,
                         sender_id=sender_id, is_external_partner=is_external_partner, billpay_id=billpay_id, extr_id=extr_id, receiver_country=receiver_country,
                         system_reference=system_reference, common_identifier=common_identifier,
                         access_mode=access_mode, account_id=account_id, user_contact_id=user_contact_id, account=account,
                         transaction_type=transaction_type, zeepay_id=zeepay_id, trans_id=trans_id, medium=medium, mno=mno,
                         receiver_msisdn=receiver_msisdn, transaction_status=transaction_status,
                         status_message=status_message, sender_details=sender_details, recipient_details=recipient_details,
                         fraud_kyc=fraud_kyc, payable=payable, amount_details=amount_details, extra=extra, address=address,
                         description=description, internal_reference=internal_reference,
                         external_reference=external_reference, external_response=external_response, gift_card_provider=gift_card_provider,
                         user_payload=user_payload, payload=payload, payment_type=payment_type, gateway_id=gateway_id, status=status, 
                         status_code=status_code, provider=provider, cr_created=cr_created, reversed=reversed, created_by=created_by, 
                         referrer=referrer, callback_url=callback_url, created_at=created_at, updated_at=updated_at)

        # Business, User, and Beneficiary IDs are not encrypted
        self.business_id = ObjectId(business_id)
        self.user_id = user_id
        self.user__id = ObjectId(user__id)
        self.beneficiary_id = ObjectId(beneficiary_id)
        self.sender_id = ObjectId(sender_id)
        self.agent_id = ObjectId(agent_id)
        
        self.hashed_checksum = hash_data(checksum) if checksum else None
        self.hashed_internal_reference = hash_data(internal_reference) if internal_reference else None
        self.hashed_transaction_type = hash_data(transaction_type) if transaction_type else None

        # Encrypt sensitive fields
        self.tenant_id = encrypt_data(tenant_id) if tenant_id else None
        self.beneficiary_account = encrypt_data(beneficiary_account) if beneficiary_account else None
        self.sender_account = encrypt_data(sender_account) if sender_account else None
        self.receiver_country = encrypt_data(receiver_country) if receiver_country else None
        self.system_reference = encrypt_data(system_reference) if system_reference else None
        self.common_identifier = encrypt_data(common_identifier) if common_identifier else None
        self.payment_mode = encrypt_data(payment_mode) if payment_mode else None
        self.access_mode = encrypt_data(access_mode) if access_mode else None
        self.mno = encrypt_data(mno) if mno else None
        self.account_id = encrypt_data(account_id) if account_id else None
        self.account = encrypt_data(account) if account else None
        self.transaction_type = encrypt_data(transaction_type) if transaction_type else None
        self.zeepay_id = encrypt_data(zeepay_id) if zeepay_id else None
        self.trans_id = encrypt_data(trans_id) if trans_id else None
        self.medium = encrypt_data(medium) if medium else None
        self.receiver_msisdn = encrypt_data(receiver_msisdn) if receiver_msisdn else None
        self.transaction_status = encrypt_data(transaction_status) if transaction_status else None
        self.status_message = encrypt_data(status_message) if status_message else None
        self.sender_details = encrypt_data(sender_details) if sender_details else None
        self.recipient_details = encrypt_data(recipient_details) if recipient_details else None
        self.fraud_kyc = encrypt_data(fraud_kyc) if fraud_kyc else None
        self.amount_details = encrypt_data(amount_details) if amount_details else None
        self.extra = encrypt_data(extra) if extra else None
        self.address = encrypt_data(address) if address else None
        self.description = encrypt_data(description) if description else None
        self.internal_reference = encrypt_data(internal_reference) if internal_reference else None
        self.external_reference = encrypt_data(external_reference) if external_reference else None
        self.external_response = encrypt_data(external_response) if external_response else None
        self.gift_card_provider = encrypt_data(gift_card_provider) if gift_card_provider else None
        self.user_payload = encrypt_data(user_payload) if user_payload else None
        self.payload = encrypt_data(payload) if payload else None
        self.payment_type = encrypt_data(payment_type) if payment_type else None
        self.gateway_id = encrypt_data(gateway_id) if gateway_id else None
        self.status = encrypt_data(status) if status else None
        self.provider = encrypt_data(provider) if provider else None
        self.referrer = encrypt_data(referrer) if referrer else None
        self.callback_url = encrypt_data(callback_url) if callback_url else None
        self.user_contact_id = encrypt_data(user_contact_id) if user_contact_id else None
        self.extr_id = encrypt_data(extr_id) if extr_id else None
        self.reversed = encrypt_data(reversed) if reversed else None
        self.status_code = encrypt_data(status_code) if status_code else None
        self.cr_created = encrypt_data(cr_created) if cr_created else None
        self.created_by = encrypt_data(created_by) if created_by else None

        # Add created and updated timestamps
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self):
        """
        Convert the transaction object to a dictionary representation.
        """
        transaction_dict = super().to_dict()
        transaction_dict.update({
            "tenant_id": self.tenant_id,
            "business_id": self.business_id,
            "user_id": self.user_id,
            "user__id": self.user__id,
            "beneficiary_id": self.beneficiary_id,
            "sender_id": self.sender_id,
            "agent_id": self.agent_id,
            "extr_id": self.extr_id,
            "beneficiary_account": self.beneficiary_account,
            "sender_account": self.sender_account,
            "receiver_country": self.receiver_country,
            "system_reference": self.system_reference,
            "common_identifier": self.common_identifier,
            "payment_mode": self.payment_mode,
            "mno": self.mno,
            "access_mode": self.access_mode,
            "account_id": self.account_id,
            "user_contact_id": self.user_contact_id,
            "account": self.account,
            "type": self.transaction_type,
            "zeepay_id": self.zeepay_id,
            "trans_id": self.trans_id,
            "medium": self.medium,
            "receiver_msisdn": self.receiver_msisdn,
            "status_message": self.status_message,
            "sender_details": self.sender_details,
            "recipient_details": self.recipient_details,
            "fraud_kyc": self.fraud_kyc,
            "amount_details": self.amount_details,
            "extra": self.extra,
            "address": self.address,
            "description": self.description,
            "internal_reference": self.internal_reference,
            "external_reference": self.external_reference,
            "external_response": self.external_response,
            "gift_card_provider": self.gift_card_provider,
            "payload": self.payload,
            "payment_type": self.payment_type,
            "gateway_id": self.gateway_id,
            "status": self.status,
            "transaction_status": self.transaction_status,
            "status_code": self.status_code,
            "provider": self.provider,
            "cr_created": self.cr_created,
            "reversed": self.reversed,
            "transaction_type": self.transaction_type,
            "created_by": self.created_by,
            "referrer": self.referrer,
            # "checksum": self.checksum,
            # "hashed_checksum": self.hashed_checksum,
            "callback_url": self.callback_url,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return transaction_dict

    @classmethod
    def get_by_id(cls, transaction_id, agent_id=None):
        """
        Retrieve a transaction by transaction_id, decrypting all fields except the date fields.
        """
        try:
             # Check if the user has permission to 'view' before proceeding
            if not cls.check_permission(cls, 'view'):
                raise PermissionError(f"User does not have permission to view {cls.__name__}.")
            
            transaction_id_obj = ObjectId(transaction_id)
            agent_id_obj = ObjectId(agent_id) if agent_id else None
        except Exception:
            return None

        transaction_collection = db.get_collection(cls.collection_name)
        data = transaction_collection.find_one({"_id": transaction_id_obj, "agent_id": agent_id_obj})
        if not data:
            return None  # Transaction not found

        # Convert ObjectIds to strings
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"]) if data.get("business_id") else None
        data["user_id"] = str(data["user_id"]) if data.get("user_id") else None
        data["user__id"] = str(data["user__id"]) if data.get("user__id") else None
        data["beneficiary_id"] = str(data["beneficiary_id"]) if data.get("beneficiary_id") else None
        data["sender_id"] = str(data["sender_id"]) if data.get("sender_id") else None
        data["agent_id"] = str(data["agent_id"]) if data.get("agent_id") else None

        # Fields to decrypt (excluding date fields like created_at, updated_at)
        fields_to_decrypt = [
            "receiver_country", "beneficiary_account","sender_account","system_reference", "common_identifier", "access_mode",
            "account_id", "account", "transaction_type", "payment_mode", "zeepay_id", "trans_id", "medium",
            "receiver_msisdn", "transaction_status", "status_message", "sender_details",
            "recipient_details", "fraud_kyc", "amount_details", "extra", "address",
            "description", "internal_reference", "mno", "external_reference",
            "external_response", "gift_card_provider", "user_payload", "payload",
            "payment_type", "gateway_id", "status", "provider", "referrer", "callback_url"
        ]

        decrypted = {}
        for field in fields_to_decrypt:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        # Return with decrypted fields included
        return {
            "transaction_id": str(data["_id"]),
            "business_id": data["business_id"],
            "user_id": data["user_id"],
            "beneficiary_id": data["beneficiary_id"],
            **decrypted,
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    @classmethod
    def get_by_checksum(cls, business_id, key, value):
        """
        Check if a transaction exists based on a specific key (e.g., trans_id, receiver_msisdn) and value.
        This method allows dynamic checks for any key (like 'trans_id', 'receiver_msisdn', etc.) using hashed values.
        
        :param business_id: The ID of the business.
        :param key: The field to check (e.g., "trans_id", "receiver_msisdn").
        :param value: The value to check for the given key.
        :return: True if the transaction exists, False otherwise.
        """
        try:
            # Check if the user has permission to 'add' before proceeding
            if not cls.check_permission(cls, 'add'):
                raise PermissionError(f"User does not have permission to view {cls.__name__}.")

            # Ensure that business_id is in the correct ObjectId format if it's passed as a string
            if isinstance(business_id, str):
                try:
                    business_id = ObjectId(business_id)  # Convert string business_id to ObjectId
                except Exception as e:
                    raise ValueError(f"Invalid business_id format: {business_id}") from e

            # Dynamically hash the value of the key
            hashed_key = hash_data(value)  # Assuming hash_data is a method to hash the value
            
            # Dynamically create the query with business_id and hashed key
            query = {
                "business_id": business_id,  # Ensure query filters by business_id
                f"hashed_{key}": hashed_key  # Use dynamic key for hashed comparison (e.g., "hashed_trans_id")
            }

            # Query the database for a transaction matching the given business_id and hashed value
            transaction_collection = db.get_collection(cls.collection_name)
            existing_item = transaction_collection.find_one(query)

            # Return True if a matching item is found, else return False
            if existing_item:
                return str(existing_item["_id"])  # Item exists
            else:
                return False  # Item does not exist

        except Exception as e:
            # Handle errors and return False in case of an exception
            print(f"Error occurred: {e}")  # For debugging purposes
            return False
    
    @classmethod
    def check_item_exists(cls, business_id, key, value):
        """
        Check if a transaction exists based on a specific key (e.g., trans_id, receiver_msisdn) and value.
        This method allows dynamic checks for any key (like 'trans_id', 'receiver_msisdn', etc.) using hashed values.
        
        :param business_id: The ID of the business.
        :param key: The field to check (e.g., "trans_id", "receiver_msisdn").
        :param value: The value to check for the given key.
        :return: True if the transaction exists, False otherwise.
        """
        try:
            # Check if the user has permission to 'add' before proceeding
            if not cls.check_permission(cls, 'add'):
                raise PermissionError(f"User does not have permission to view {cls.__name__}.")

            # Ensure that business_id is in the correct ObjectId format if it's passed as a string
            if isinstance(business_id, str):
                try:
                    business_id = ObjectId(business_id)  # Convert string business_id to ObjectId
                except Exception as e:
                    raise ValueError(f"Invalid business_id format: {business_id}") from e

            # Dynamically hash the value of the key
            hashed_key = hash_data(value)  # Assuming hash_data is a method to hash the value
            
            # Dynamically create the query with business_id and hashed key
            query = {
                "business_id": business_id,  # Ensure query filters by business_id
                f"hashed_{key}": hashed_key  # Use dynamic key for hashed comparison (e.g., "hashed_trans_id")
            }

            # Query the database for a transaction matching the given business_id and hashed value
            transaction_collection = db.get_collection(cls.collection_name)
            existing_item = transaction_collection.find_one(query)

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
    def get_by_user_id(cls, user_id, page=1, per_page=10):
        """
        Retrieve transactions by user_id, decrypting fields and implementing pagination.

        :param user_id: The user_id to search transactions by.
        :param page: The page number to retrieve (default is 1).
        :param per_page: The number of transactions to retrieve per page (default is 10).
        :return: A dictionary with the list of transactions and pagination details.
        """
        if isinstance(user_id, str):
            try:
                user_id = ObjectId(user_id)
            except Exception as e:
                raise ValueError(f"Invalid user_id format: {user_id}") from e

        default_page = os.getenv("DEFAULT_PAGINATION_PAGE", 1)
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10)

        page = int(page) if page else int(default_page)
        per_page = int(per_page) if per_page else int(default_per_page)
        
        transaction_collection = db.get_collection(cls.collection_name)
        transactions_cursor = transaction_collection.find({"user_id": user_id})
        total_count = transaction_collection.count_documents({"user_id": user_id})
        transactions_cursor = transactions_cursor.skip((page - 1) * per_page).limit(per_page)

        fields_to_decrypt = [
            "beneficiary_account", "sender_account", "receiver_country", "system_reference",
            "common_identifier", "access_mode", "payment_mode", "account_id", "account",
            "transaction_type", "zeepay_id", "trans_id", "medium", "receiver_msisdn",
            "transaction_status", "status_message", "sender_details", "recipient_details",
            "fraud_kyc", "amount_details", "extra", "mno", "address", "description",
            "internal_reference", "external_reference", "external_response", "gift_card_provider",
            "user_payload", "payload", "payment_type", "cr_created", "gateway_id", "status",
            "provider", "referrer", "callback_url"
        ]

        result = []
        for transaction in transactions_cursor:
            decrypted = {}
            for field in fields_to_decrypt:
                decrypted[field] = decrypt_data(transaction.get(field)) if transaction.get(field) else None

            result.append({
                "_id": str(transaction.get("_id")),
                "business_id": str(transaction.get("business_id")),
                "user_id": str(transaction.get("user_id")),
                "user__id": str(transaction.get("user__id")),
                "beneficiary_id": str(transaction.get("beneficiary_id")),
                "agent_id": str(transaction.get("agent_id")),
                **{field: decrypted[field] for field in fields_to_decrypt},
                "created_at": transaction.get("created_at"),
                "updated_at": transaction.get("updated_at")
            })

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "transactions": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def update(cls, tranaction_id, processing_callback=False, **updates):
        """
        Update a transaction's information by tranaction_id.
        """
        if "zeepay_id" in updates:
            updates["zeepay_id"] = encrypt_data(updates.get("zeepay_id")) if updates.get("zeepay_id") else None
            updates["hashed_zeepay_id"] = hash_data(str(updates.get("zeepay_id"))) if updates.get("zeepay_id") else None
        if "payment_url" in updates:
            updates["payment_url"] = encrypt_data(updates["payment_url"]) if updates.get("payment_url") else None
        if "status_message" in updates:
            updates["status_message"] = encrypt_data(updates["status_message"]) if updates.get("status_message") else None
        if "transaction_status" in updates:
            updates["transaction_status"] = encrypt_data(updates.get("transaction_status")) if updates.get("transaction_status") else None
        if "gateway_id" in updates:
            updates["gateway_id"] = encrypt_data(updates["gateway_id"]) if updates.get("gateway_id") else None
        if "external_reference" in updates:
            updates["external_reference"] = encrypt_data(updates.get("external_reference")) if updates.get("external_reference") else None
            updates["hashed_external_reference"] = hash_data(updates.get("external_reference")) if updates.get("external_reference") else None
        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"]) if updates.get("status") else None
        if "status_code" in updates:
            updates["status_code"] = encrypt_data(updates["status_code"]) if updates.get("status_code") else None
        if "cr_created" in updates:
            updates["cr_created"] = encrypt_data(str(updates.get("cr_created"))) if updates.get("cr_created") else None
        if "reversed" in updates:
            updates["reversed"] = encrypt_data(updates["reversed"]) if updates.get("reversed") else None
        if "extr_id" in updates:
            updates["extr_id"] = encrypt_data(updates.get("extr_id")) if updates.get("extr_id") else None
        
      
        # hashed_internal_reference
        return super().update(tranaction_id, processing_callback, **updates)

    @classmethod
    def get_by_internal_reference(cls, internal_reference, type):
        """
        Retrieve a transaction by internal_reference, decrypting all fields except the date fields.
        """
        
        hashed_internal_reference = hash_data(internal_reference)
        hashed_transaction_type = hash_data(type)

        transaction_collection = db.get_collection(cls.collection_name)
        data = transaction_collection.find_one(
            {
            "hashed_internal_reference": hashed_internal_reference, 
            "hashed_transaction_type": hashed_transaction_type
            }
        )
        if not data:
            return None  # Transaction not found

        # Convert ObjectIds to strings
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"]) if data.get("business_id") else None
        data["user_id"] = str(data["user_id"]) if data.get("user_id") else None
        data["user__id"] = str(data["user__id"]) if data.get("user__id") else None
        data["beneficiary_id"] = str(data.get("beneficiary_id")) if data.get("beneficiary_id") else None
        data["sender_id"] = str(data.get("sender_id")) if data.get("sender_id") else None
        data["agent_id"] = str(data.get("agent_id")) if data.get("agent_id") else None

        # Fields to decrypt (excluding date fields like created_at, updated_at)
        fields_to_decrypt = [
            "receiver_country", "beneficiary_account","sender_account","system_reference", "common_identifier", "access_mode",
            "account_id", "account", "transaction_type", "payment_mode", "zeepay_id", "trans_id", "medium",
            "receiver_msisdn", "transaction_status", "status_message", "sender_details",
            "recipient_details", "fraud_kyc", "mno", "amount_details", "extra", "address",
            "description", "internal_reference", "external_reference",
            "external_response", "gift_card_provider", "user_payload", "payload",
            "payment_type", "tenant_id", "gateway_id","cr_created", "status", "provider", "referrer", "callback_url"
        ]

        decrypted = {}
        for field in fields_to_decrypt:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        # Return with decrypted fields included
        return {
            "transaction_id": str(data.get("_id")),
            "business_id": str(data.get("business_id")),
            "agent_id": str(data.get("agent_id")),
            "sender_id": str(data.get("sender_id")),
            "user_id": data.get("user_id"),
            "user__id": str(data.get("user__id")),
            "beneficiary_id": str(data.get("beneficiary_id")),
            **decrypted,
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    @classmethod
    def get_by_zeepay_id_and_transaction_type(cls, zeepay_id, type):
        """
        Retrieve a transaction by zeepay_id, decrypting all fields except the date fields.
        """
        
        hashed_zeepay_id = hash_data(zeepay_id)
        hashed_transaction_type = hash_data(type)

        transaction_collection = db.get_collection(cls.collection_name)
        data = transaction_collection.find_one(
            {
            "hashed_zeepay_id": hashed_zeepay_id, 
            "hashed_transaction_type": hashed_transaction_type
            }
        )
        if not data:
            return None  # Transaction not found

        # Convert ObjectIds to strings
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"]) if data.get("business_id") else None
        data["user_id"] = str(data["user_id"]) if data.get("user_id") else None
        data["user__id"] = str(data["user__id"]) if data.get("user__id") else None
        data["beneficiary_id"] = str(data.get("beneficiary_id")) if data.get("beneficiary_id") else None
        data["sender_id"] = str(data.get("sender_id")) if data.get("sender_id") else None
        data["agent_id"] = str(data.get("agent_id")) if data.get("agent_id") else None

        # Fields to decrypt (excluding date fields like created_at, updated_at)
        fields_to_decrypt = [
            "receiver_country", "beneficiary_account","sender_account","system_reference", "common_identifier", "access_mode",
            "account_id", "account", "transaction_type", "payment_mode", "zeepay_id", "trans_id", "medium",
            "receiver_msisdn", "transaction_status", "status_message", "sender_details",
            "recipient_details", "mno", "fraud_kyc", "amount_details", "extra", "address",
            "description", "internal_reference", "external_reference",
            "external_response", "gift_card_provider", "user_payload", "payload",
            "payment_type", "tenant_id", "gateway_id","cr_created", "status", "provider", "referrer", "callback_url"
        ]

        decrypted = {}
        for field in fields_to_decrypt:
            decrypted[field] = decrypt_data(data.get(field)) if data.get(field) else None

        # Return with decrypted fields included
        return {
            "transaction_id": str(data.get("_id")),
            "business_id": str(data.get("business_id")),
            "agent_id": str(data.get("agent_id")),
            "sender_id": str(data.get("sender_id")),
            "user_id": data.get("user_id"),
            "user__id": str(data.get("user__id")),
            "beneficiary_id": str(data.get("beneficiary_id")),
            **decrypted,
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    @classmethod
    def get_by_agent_id(cls, agent_id, page=1, per_page=10):
        """
        Retrieve transactions by agent_id, decrypting fields and implementing pagination.

        :param agent_id: The agent_id to search transactions by.
        :param page: The page number to retrieve (default is 1).
        :param per_page: The number of transactions to retrieve per page (default is 10).
        :return: A dictionary with the list of transactions and pagination details.
        """
        if isinstance(agent_id, str):
            try:
                agent_id = ObjectId(agent_id)
            except Exception as e:
                raise ValueError(f"Invalid agent_id format: {agent_id}") from e

        default_page = os.getenv("DEFAULT_PAGINATION_PAGE", 1)
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10)

        page = int(page) if page else int(default_page)
        per_page = int(per_page) if per_page else int(default_per_page)

        transaction_collection = db.get_collection(cls.collection_name)
        transactions_cursor = transaction_collection.find({"agent_id": agent_id})
        total_count = transaction_collection.count_documents({"agent_id": agent_id})
        transactions_cursor = transactions_cursor.skip((page - 1) * per_page).limit(per_page)

        fields_to_decrypt = [
            "beneficiary_account", "sender_account", "receiver_country", "system_reference",
            "common_identifier", "access_mode", "payment_mode", "account_id", "account",
            "transaction_type", "zeepay_id", "trans_id", "medium", "receiver_msisdn",
            "transaction_status", "mno", "status_message", "sender_details", "recipient_details",
            "fraud_kyc", "amount_details", "extra", "address", "description",
            "internal_reference", "external_reference", "external_response", "gift_card_provider",
            "user_payload", "payload", "payment_type", "cr_created", "gateway_id", "status",
            "provider", "referrer", "callback_url"
        ]

        result = []
        for transaction in transactions_cursor:
            decrypted = {}
            for field in fields_to_decrypt:
                decrypted[field] = decrypt_data(transaction.get(field)) if transaction.get(field) else None

            result.append({
                "_id": str(transaction.get("_id")),
                "business_id": str(transaction.get("business_id")),
                "user_id": str(transaction.get("user_id")),
                "user__id": str(transaction.get("user__id")),
                "beneficiary_id": str(transaction.get("beneficiary_id")),
                "agent_id": str(transaction.get("agent_id")),
                **{field: decrypted[field] for field in fields_to_decrypt},
                "created_at": transaction.get("created_at"),
                "updated_at": transaction.get("updated_at")
            })

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "transactions": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def get_by_sender_id(cls, sender_id, page=1, per_page=10):
        """
        Retrieve transactions by sender_id, decrypting fields and implementing pagination.

        :param sender_id: The sender_id to search transactions by.
        :param page: The page number to retrieve (default is 1).
        :param per_page: The number of transactions to retrieve per page (default is 10).
        :return: A dictionary with the list of transactions and pagination details.
        """
        if isinstance(sender_id, str):
            try:
                sender_id = ObjectId(sender_id)
            except Exception as e:
                raise ValueError(f"Invalid sender_id format: {sender_id}") from e

        default_page = os.getenv("DEFAULT_PAGINATION_PAGE", 1)
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10)

        page = int(page) if page else int(default_page)
        per_page = int(per_page) if per_page else int(default_per_page)

        transaction_collection = db.get_collection(cls.collection_name)
        transactions_cursor = transaction_collection.find({"sender_id": sender_id})
        total_count = transaction_collection.count_documents({"sender_id": sender_id})
        transactions_cursor = transactions_cursor.skip((page - 1) * per_page).limit(per_page)

        fields_to_decrypt = [
            "beneficiary_account", "sender_account", "receiver_country", "system_reference",
            "common_identifier", "access_mode", "payment_mode", "account_id", "account",
            "transaction_type", "zeepay_id", "trans_id", "medium", "receiver_msisdn",
            "transaction_status", "mno", "status_message", "sender_details", "recipient_details",
            "fraud_kyc", "amount_details", "extra", "address", "description",
            "internal_reference", "external_reference", "external_response", "gift_card_provider",
            "user_payload", "payload", "payment_type","cr_created", "gateway_id", "status",
            "provider", "referrer", "callback_url"
        ]

        result = []
        for transaction in transactions_cursor:
            decrypted = {}
            for field in fields_to_decrypt:
                decrypted[field] = decrypt_data(transaction.get(field)) if transaction.get(field) else None

            result.append({
                "_id": str(transaction.get("_id")),
                "business_id": str(transaction.get("business_id")),
                "user_id": str(transaction.get("user_id")),
                "user__id": str(transaction.get("user__id")),
                "beneficiary_id": str(transaction.get("beneficiary_id")),
                "agent_id": str(transaction.get("agent_id")),
                "sender_id": str(transaction.get("sender_id")),
                **{field: decrypted[field] for field in fields_to_decrypt},
                "created_at": transaction.get("created_at"),
                "updated_at": transaction.get("updated_at")
            })

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "transactions": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }















