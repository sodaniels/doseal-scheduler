from bson.objectid import ObjectId
import os
from datetime import datetime, timedelta
from app.extensions.db import db
from ..models.base_model import BaseModel

def _prune_empty(value):
        """
        Recursively remove None, "", [], {} from dictionaries/lists.
        Keep valid falsy values like 0, 0.0, False.
        """
        if isinstance(value, dict):
            cleaned = {}
            for k, v in value.items():
                v2 = _prune_empty(v)
                if v2 is None or v2 == "" or v2 == [] or v2 == {}:
                    continue
                cleaned[k] = v2
            return cleaned
        elif isinstance(value, list):
            cleaned_list = []
            for item in value:
                i2 = _prune_empty(item)
                if i2 is None or i2 == "" or i2 == [] or i2 == {}:
                    continue
                cleaned_list.append(i2)
            return cleaned_list
        else:
            return value


class Transaction(BaseModel):
    """
    A Transaction represents a financial or operational transaction, including
    details about the transaction type, sender, receiver, amount details, and
    other payment-related fields.
    """

    collection_name = "transactions"

    def __init__(self, tenant_id, business_id=None, user_id=None, user__id=None, beneficiary_id=None, beneficiary_account=None,
                 sender_id=None, senderId=None,receiverId=None, agent_id=None, is_external_partner=False, payment_mode=None, 
                 billpay_id=None, sender_account=None, pin_number=None, extr_id=None, receiver_country=None, system_reference=None, 
                 common_identifier=None, checksum=None, access_mode=None, account_id=None, user_contact_id=None, account=None,  
                 zeepay_id=None, trans_id=None, medium=None, mno=None, receiver_msisdn=None, transaction_status=None, 
                 status_message=None, sender_details=None, recipient_details=None, fraud_kyc=None, payable=None, 
                 amount_details=None, extra=None, address=None, description=None, internal_reference=None,transaction_type=None,
                 external_reference=None, external_response=None, gift_card_provider=None, user_payload=None, payload=None, 
                 payment_type=None, gateway_id=None,status=None, status_code=411, provider=None, cr_created=False, reversed=False, 
                 created_by=None, referrer=None, callback_url=None, callback_status=None, callback_payload=None,
                 ledger_account_id=None, ledger_hold_id=None, created_at=None, updated_at=None, partner_name=None,
                 request_type=None, billpay_zeepay_id=None):

        super().__init__(
            tenant_id=tenant_id, business_id=business_id, user_id=user_id, user__id=user__id, 
            beneficiary_id=beneficiary_id, beneficiary_account=beneficiary_account, pin_number=pin_number, 
            agent_id=agent_id, receiverId=receiverId, sender_account=sender_account, payment_mode=payment_mode, checksum=checksum,
            sender_id=sender_id, senderId=senderId, is_external_partner=is_external_partner, billpay_id=billpay_id, extr_id=extr_id, 
            receiver_country=receiver_country, system_reference=system_reference, common_identifier=common_identifier,
            access_mode=access_mode, account_id=account_id, user_contact_id=user_contact_id, account=account,
            transaction_type=transaction_type, zeepay_id=zeepay_id, trans_id=trans_id, medium=medium, mno=mno,
            receiver_msisdn=receiver_msisdn, transaction_status=transaction_status,
            status_message=status_message, sender_details=sender_details, recipient_details=recipient_details,
            fraud_kyc=fraud_kyc, payable=payable, amount_details=amount_details, extra=extra, address=address,
            description=description, internal_reference=internal_reference,callback_payload=callback_payload,
            external_reference=external_reference, external_response=external_response, gift_card_provider=gift_card_provider,
            user_payload=user_payload, payload=payload, payment_type=payment_type, gateway_id=gateway_id, status=status, 
            status_code=status_code, provider=provider, cr_created=cr_created, callback_status=callback_status, reversed=reversed, 
            created_by=created_by, ledger_account_id=ledger_account_id , ledger_hold_id=ledger_hold_id,
            referrer=referrer, partner_name=partner_name, callback_url=callback_url, created_at=created_at, 
            updated_at=updated_at, request_type=request_type, billpay_zeepay_id=billpay_zeepay_id
        )

        self.business_id = ObjectId(business_id) if business_id else None
        self.user_id = user_id
        self.user__id = ObjectId(user__id) if user__id else None
        self.beneficiary_id = ObjectId(beneficiary_id) if beneficiary_id else None
        self.sender_id = ObjectId(sender_id) if sender_id else None
        self.agent_id = ObjectId(agent_id) if agent_id else None
        self.senderId = senderId if senderId else None
        self.billpay_id = billpay_id if billpay_id else None
        self.receiverId = receiverId if receiverId else None
        self.pin_number = pin_number if pin_number else None
        self.callback_status = callback_status if callback_status else None
        self.callback_payload = callback_payload if callback_payload else None
        
        #ledger settings
        self.ledger_account_id = ledger_account_id if ledger_account_id else None
        self.ledger_hold_id = ledger_hold_id if ledger_hold_id else None

        # No encryption/hashing
        self.tenant_id = tenant_id
        self.partner_name = partner_name
        self.beneficiary_account = beneficiary_account
        self.sender_account = sender_account
        self.receiver_country = receiver_country
        self.system_reference = system_reference
        self.common_identifier = common_identifier
        self.payment_mode = payment_mode
        self.access_mode = access_mode
        self.account_id = account_id if account_id else None
        self.billpay_zeepay_id = billpay_zeepay_id if billpay_zeepay_id else None
        self.account = account
        self.transaction_type = transaction_type
        self.request_type = request_type
        self.zeepay_id = zeepay_id
        self.trans_id = trans_id
        self.medium = medium
        self.mno = mno
        self.receiver_msisdn = receiver_msisdn
        self.transaction_status = transaction_status
        self.status_message = status_message
        self.sender_details = sender_details
        self.recipient_details = recipient_details
        self.fraud_kyc = fraud_kyc
        self.amount_details = amount_details
        self.extra = extra
        self.address = address
        self.description = description
        self.internal_reference = internal_reference
        self.external_reference = external_reference
        self.external_response = external_response
        self.gift_card_provider = gift_card_provider
        self.user_payload = user_payload
        self.payload = payload
        self.payment_type = payment_type if payment_type else None
        self.gateway_id = gateway_id
        self.status = status
        self.provider = provider
        self.referrer = ObjectId(referrer) if referrer else None
        self.callback_url = callback_url
        self.user_contact_id = user_contact_id
        self.extr_id = extr_id
       
        self.payload = payload
        self.status_code = status_code
        
        if reversed:
            self.reversed = reversed
        if cr_created:
            self.cr_created = cr_created
        
        self.created_by = ObjectId(created_by)

        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self):
        """
        Convert the transaction object to a dictionary representation
        and drop fields that don't have actual values.
        """
        transaction_dict = super().to_dict()
        # "cr_created": self.cr_created,
        
        
        general_payload = {
            "tenant_id": self.tenant_id,
            "partner_name": self.partner_name,
            "business_id": self.business_id if self.business_id else None,
            "receiverId": str(self.receiverId) if self.receiverId else None,
            "user_id": self.user_id,
            "user__id": self.user__id if self.user__id else None,
            "sender_id": self.sender_id if self.sender_id else None,
            "agent_id": self.agent_id if self.agent_id else None,
            "senderId": str(self.senderId) if self.senderId else None,
            "extr_id": self.extr_id,
            "beneficiary_account": self.beneficiary_account,
            "sender_account": self.sender_account,
            "receiver_country": self.receiver_country,
            "system_reference": self.system_reference,
            "common_identifier": self.common_identifier,
            "payment_mode": self.payment_mode,
            "mno": self.mno,
            "access_mode": self.access_mode,
            "user_contact_id": self.user_contact_id,
            "account": self.account,
            "transaction_type": self.transaction_type,
            "request_type": self.request_type,
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
            "payload": self.payload,
            "address": self.address,
            "description": self.description,
            "internal_reference": self.internal_reference,
            "external_reference": self.external_reference,
            "external_response": self.external_response,
            "gift_card_provider": self.gift_card_provider,
            "gateway_id": self.gateway_id,
            "status": self.status,
            "transaction_status": self.transaction_status,
            "status_code": self.status_code,
            "provider": self.provider,
            "cr_created": self.cr_created,
            "reversed": self.reversed,
            "created_by": self.created_by,
            "referrer": self.referrer,
            "callback_url": self.callback_url,
            "callback_status": self.callback_status,
            "callback_payload": self.callback_payload,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        
        if self.pin_number:
            general_payload["pin_number"] = self.pin_number
            
        if self.billpay_id:
            general_payload["billpay_id"] = self.billpay_id
            
        if self.beneficiary_id:
            general_payload["beneficiary_id"] = self.beneficiary_id
        
        if self.ledger_account_id:
            general_payload["ledger_account_id"] = self.ledger_account_id
            
        if self.ledger_hold_id:
            general_payload["ledger_hold_id"] = self.ledger_hold_id
            
        if self.account_id:
            general_payload["account_id"] = self.account_id
            
        if self.payment_type:
            general_payload["payment_type"] = self.payment_type
            
        if self.billpay_zeepay_id:
            general_payload["billpay_zeepay_id"] = self.billpay_zeepay_id
            
        if self.cr_created:
            general_payload["cr_created"] = self.cr_created
        
        transaction_dict.update(general_payload)

        # Deep-clean before returning
        return _prune_empty(transaction_dict)


    @classmethod
    def get_by_id(cls, transaction_id, agent_id=None):
        try:
            if not cls.check_permission(cls, 'view'):
                raise PermissionError(f"User does not have permission to view {cls.__name__}.")

            transaction_id_obj = ObjectId(transaction_id)
            agent_id_obj = ObjectId(agent_id) if agent_id else None
        except Exception:
            return None

        transaction_collection = db.get_collection(cls.collection_name)
        data = transaction_collection.find_one({"_id": transaction_id_obj, "agent_id": agent_id_obj})
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data.get("business_id")) if data.get("business_id") else None
        data["user_id"] = str(data.get("user_id")) if data.get("user_id") else None
        data["user__id"] = str(data.get("user__id")) if data.get("user__id") else None
        data["beneficiary_id"] = str(data.get("beneficiary_id")) if data.get("beneficiary_id") else None
        data["sender_id"] = str(data.get("sender_id")) if data.get("sender_id") else None
        data["agent_id"] = str(data.get("agent_id")) if data.get("agent_id") else None

        return data

    @classmethod
    def get_by_checksum(cls, business_id, key, value):
        try:
            if not cls.check_permission(cls, 'add'):
                raise PermissionError(f"User does not have permission to view {cls.__name__}.")

            if isinstance(business_id, str):
                try:
                    business_id = ObjectId(business_id)
                except Exception as e:
                    raise ValueError(f"Invalid business_id format: {business_id}") from e

            query = {
                "business_id": business_id,
                key: value
            }

            transaction_collection = db.get_collection(cls.collection_name)
            existing_item = transaction_collection.find_one(query)
            if existing_item:
                return str(existing_item["_id"])
            else:
                return False

        except Exception as e:
            print(f"Error occurred: {e}")
            return False

    @classmethod
    def check_item_exists(cls, business_id, key, value):
        try:
            if not cls.check_permission(cls, 'add'):
                raise PermissionError(f"User does not have permission to view {cls.__name__}.")

            if isinstance(business_id, str):
                try:
                    business_id = ObjectId(business_id)
                except Exception as e:
                    raise ValueError(f"Invalid business_id format: {business_id}") from e

            query = {
                "business_id": business_id,
                key: value
            }

            transaction_collection = db.get_collection(cls.collection_name)
            existing_item = transaction_collection.find_one(query)
            return bool(existing_item)

        except Exception as e:
            print(f"Error occurred: {e}")
            return False

    @classmethod
    def get_by_user_id(cls, user_id, page=1, per_page=10):
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

        result = []
        for transaction in transactions_cursor:
            transaction["_id"] = str(transaction.get("_id"))
            transaction["business_id"] = str(transaction.get("business_id")) if transaction.get("business_id") else None
            transaction["user_id"] = str(transaction.get("user_id")) if transaction.get("user_id") else None
            transaction["user__id"] = str(transaction.get("user__id")) if transaction.get("user__id") else None
            transaction["beneficiary_id"] = str(transaction.get("beneficiary_id")) if transaction.get("beneficiary_id") else None
            transaction["agent_id"] = str(transaction.get("agent_id")) if transaction.get("agent_id") else None
            result.append(transaction)

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "transactions": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def update(cls, transaction_id, processing_callback=False, **updates):
        transaction_collection = db.get_collection(cls.collection_name)
        
        # Handle appending to callback_payload if it's in updates
        if 'callback_payload' in updates:
            # Fetch the current document
            doc = transaction_collection.find_one({"_id": ObjectId(transaction_id)})
            current_payload = doc.get("callback_payload", [])
            # Ensure it's a list
            if not isinstance(current_payload, list):
                current_payload = [current_payload] if current_payload else []
            # Append the new value(s)
            new_payload = updates.pop('callback_payload')
            if isinstance(new_payload, list):
                current_payload.extend(new_payload)
            else:
                current_payload.append(new_payload)
            # Update the field with the new, appended list
            updates['callback_payload'] = current_payload

        # Perform the update with $set (for all fields in updates, including callback_payload)
        result = transaction_collection.update_one(
            {"_id": ObjectId(transaction_id)},
            {"$set": updates}
        )
        return result.modified_count > 0

    @classmethod
    def update_callback(cls, transaction_id, business_id,  **updates):
        """
        Update transaction with callback payload
        """
        if "cr_created" in updates:
            updates["cr_created"] = updates["cr_created"]
            
        if "zeepay_id" in updates:
            updates["zeepay_id"] = updates["zeepay_id"]
            
        if "gateway_id" in updates:
            updates["gateway_id"] = updates["gateway_id"]
        if "status_message" in updates:
            updates["status_message"] = updates["status_message"]
            
        if "transaction_status" in updates:
            updates["transaction_status"] = updates["transaction_status"]
            updates["transaction_status"] = updates["transaction_status"]
        
        
        return super().update(
            transaction_id, 
            business_id, 
            processing_callback=True, 
            **updates
        )

    @classmethod
    def get_by_internal_reference(cls, internal_reference, type):
        transaction_collection = db.get_collection(cls.collection_name)
        data = transaction_collection.find_one(
            {
                "internal_reference": internal_reference, 
                "transaction_type": type
            }
        )
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data.get("business_id")) if data.get("business_id") else None
        data["user_id"] = str(data.get("user_id")) if data.get("user_id") else None
        data["user__id"] = str(data.get("user__id")) if data.get("user__id") else None
        data["beneficiary_id"] = str(data.get("beneficiary_id")) if data.get("beneficiary_id") else None
        data["sender_id"] = str(data.get("sender_id")) if data.get("sender_id") else None
        data["agent_id"] = str(data.get("agent_id")) if data.get("agent_id") else None

        return data

    @classmethod
    def get_by_zeepay_id_and_transaction_type(cls, zeepay_id, type):
        transaction_collection = db.get_collection(cls.collection_name)
        data = transaction_collection.find_one(
            {
                "zeepay_id": zeepay_id, 
                "transaction_type": type
            }
        )
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data.get("business_id")) if data.get("business_id") else None
        data["user_id"] = str(data.get("user_id")) if data.get("user_id") else None
        data["user__id"] = str(data.get("user__id")) if data.get("user__id") else None
        data["beneficiary_id"] = str(data.get("beneficiary_id")) if data.get("beneficiary_id") else None
        data["sender_id"] = str(data.get("sender_id")) if data.get("sender_id") else None
        data["agent_id"] = str(data.get("agent_id")) if data.get("agent_id") else None

        return data

    @classmethod
    def get_by_agent_id(cls, agent_id, page=1, per_page=10):
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

        result = []
        for transaction in transactions_cursor:
            transaction["_id"] = str(transaction.get("_id"))
            transaction["business_id"] = str(transaction.get("business_id")) if transaction.get("business_id") else None
            transaction["user_id"] = str(transaction.get("user_id")) if transaction.get("user_id") else None
            transaction["user__id"] = str(transaction.get("user__id")) if transaction.get("user__id") else None
            transaction["beneficiary_id"] = str(transaction.get("beneficiary_id")) if transaction.get("beneficiary_id") else None
            transaction["agent_id"] = str(transaction.get("agent_id")) if transaction.get("agent_id") else None
            result.append(transaction)

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

        result = []
        for transaction in transactions_cursor:
            transaction["_id"] = str(transaction.get("_id"))
            transaction["business_id"] = str(transaction.get("business_id")) if transaction.get("business_id") else None
            transaction["user_id"] = str(transaction.get("user_id")) if transaction.get("user_id") else None
            transaction["user__id"] = str(transaction.get("user__id")) if transaction.get("user__id") else None
            transaction["beneficiary_id"] = str(transaction.get("beneficiary_id")) if transaction.get("beneficiary_id") else None
            transaction["agent_id"] = str(transaction.get("agent_id")) if transaction.get("agent_id") else None
            transaction["sender_id"] = str(transaction.get("sender_id")) if transaction.get("sender_id") else None
            result.append(transaction)

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "transactions": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def get_by_pin_number(cls, pin_number):
        transaction_collection = db.get_collection(cls.collection_name)
        data = transaction_collection.find_one(
            {
                "pin_number": pin_number
            }
        )
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data.get("business_id")) if data.get("business_id") else None
        data["user_id"] = str(data.get("user_id")) if data.get("user_id") else None
        data["user__id"] = str(data.get("user__id")) if data.get("user__id") else None
        data["beneficiary_id"] = str(data.get("beneficiary_id")) if data.get("beneficiary_id") else None
        data["sender_id"] = str(data.get("sender_id")) if data.get("sender_id") else None
        data["agent_id"] = str(data.get("agent_id")) if data.get("agent_id") else None

        return data

    #admin transactions
    @classmethod
    def get_by_business_id(
        cls,
        business_id,
        page=1,
        per_page=10,
        start_date=None,
        end_date=None,
        partner_name=None
    ):
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e

        # --- Rescue accidental positional usage: get_by_business_id(biz_id, "Intermex") ---
        if isinstance(page, str) and page.strip().lower() in {"intermex", "instntmny", "instntmny"}:
            partner_name = page
            page = os.getenv("DEFAULT_PAGINATION_PAGE", 1)

        default_page = int(os.getenv("DEFAULT_PAGINATION_PAGE", 1))
        default_per_page = int(os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10))

        def _to_int(v, fallback):
            try:
                return int(v)
            except Exception:
                return fallback

        page = _to_int(page, default_page)
        per_page = _to_int(per_page, default_per_page)

        query = {"business_id": business_id}

        # Date filters
        date_filter = {}
        if start_date:
            try:
                date_filter["$gte"] = datetime.fromisoformat(start_date)
            except Exception:
                raise ValueError("Invalid date-time format for 'start_date'. Use ISO 8601 (YYYY-MM-DDTHH:MM:SS).")
        if end_date:
            try:
                date_filter["$lte"] = datetime.fromisoformat(end_date)
            except Exception:
                raise ValueError("Invalid date-time format for 'end_date'. Use ISO 8601 (YYYY-MM-DDTHH:MM:SS).")
        if date_filter:
            query["created_at"] = date_filter

        # Normalize and validate partner_name
        def _normalize_partner(p):
            if p is None:
                return None
            p = p.strip().lower()
            if p == "intermex":
                return "Intermex"
            if p in {"instntmny", "instntmny"}:
                # Use the canonical spelling you actually store in DB:
                return "InstntMny"
            raise ValueError("Invalid partner_name. Use 'Intermex' or 'InstntMny'.")

        partner_name = _normalize_partner(partner_name)
        if partner_name:
            query["partner_name"] = partner_name

        col = db.get_collection(cls.collection_name)
        cursor = col.find(query)
        total_count = col.count_documents(query)
        cursor = cursor.skip((page - 1) * per_page).limit(per_page)

        result = []
        for doc in cursor:
            doc["_id"] = str(doc.get("_id"))
            for f in ["business_id", "user_id", "user__id", "beneficiary_id", "agent_id", "sender_id"]:
                if doc.get(f):
                    doc[f] = str(doc[f])
            result.append(doc)

        total_pages = (total_count + per_page - 1) // per_page
        return {
            "transactions": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

  
    @classmethod
    def get_by_business_id_and_agent_id(
        cls,
        business_id,
        agent_id,
        page=1,
        per_page=10,
        start_date=None,
        end_date=None
    ):
        if not business_id or not agent_id:
            raise ValueError("Both business_id and agent_id are required.")
        # Ensure business_id and agent_id are ObjectId, if necessary
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e
        if isinstance(agent_id, str):
            try:
                agent_id = ObjectId(agent_id)
            except Exception as e:
                raise ValueError(f"Invalid agent_id format: {agent_id}") from e

        default_page = os.getenv("DEFAULT_PAGINATION_PAGE", 1)
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10)
        page = int(page) if page else int(default_page)
        per_page = int(per_page) if per_page else int(default_per_page)

        # Build AND query for both business_id and agent_id
        query = {"business_id": business_id, "agent_id": agent_id}

        # Optional date filters
        date_filter = {}
        if start_date:
            try:
                from_date_obj = datetime.fromisoformat(start_date)
                date_filter["$gte"] = from_date_obj
            except Exception:
                raise ValueError("Invalid date-time format for 'From'. Expected ISO 8601.")
        if end_date:
            try:
                to_date_obj = datetime.fromisoformat(end_date)
                date_filter["$lte"] = to_date_obj
            except Exception:
                raise ValueError("Invalid date-time format for 'To'. Expected ISO 8601.")
        if date_filter:
            query["created_at"] = date_filter  # Use your actual date field name if different

        transaction_collection = db.get_collection(cls.collection_name)
        transactions_cursor = transaction_collection.find(query)
        total_count = transaction_collection.count_documents(query)
        transactions_cursor = transactions_cursor.skip((page - 1) * per_page).limit(per_page)

        result = []
        for transaction in transactions_cursor:
            transaction["_id"] = str(transaction.get("_id"))
            transaction["business_id"] = str(transaction.get("business_id")) if transaction.get("business_id") else None
            transaction["agent_id"] = str(transaction.get("agent_id")) if transaction.get("agent_id") else None
            transaction["user_id"] = str(transaction.get("user_id")) if transaction.get("user_id") else None
            transaction["user__id"] = str(transaction.get("user__id")) if transaction.get("user__id") else None
            transaction["beneficiary_id"] = str(transaction.get("beneficiary_id")) if transaction.get("beneficiary_id") else None
            transaction["sender_id"] = str(transaction.get("sender_id")) if transaction.get("sender_id") else None
            result.append(transaction)

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "transactions": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }
        
    @classmethod
    def get_by_business_id_and_sender_id(
        cls,
        business_id,
        sender_id,
        page=1,
        per_page=10,
        start_date=None,
        end_date=None
    ):
        if not business_id or not sender_id:
            raise ValueError("Both business_id and sender_id are required.")
        # Ensure business_id and sender_id are ObjectId, if necessary
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e
        if isinstance(sender_id, str):
            try:
                sender_id = ObjectId(sender_id)
            except Exception as e:
                raise ValueError(f"Invalid sender_id format: {sender_id}") from e

        default_page = os.getenv("DEFAULT_PAGINATION_PAGE", 1)
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10)
        page = int(page) if page else int(default_page)
        per_page = int(per_page) if per_page else int(default_per_page)

        # Build AND query for both business_id and sender_id
        query = {"business_id": business_id, "sender_id": sender_id}

        # Optional date filters
        date_filter = {}
        if start_date:
            try:
                from_date_obj = datetime.fromisoformat(start_date)
                date_filter["$gte"] = from_date_obj
            except Exception:
                raise ValueError("Invalid date-time format for 'From'. Expected ISO 8601.")
        if end_date:
            try:
                to_date_obj = datetime.fromisoformat(end_date)
                date_filter["$lte"] = to_date_obj
            except Exception:
                raise ValueError("Invalid date-time format for 'To'. Expected ISO 8601.")
        if date_filter:
            query["created_at"] = date_filter  # Use your actual date field name if different

        transaction_collection = db.get_collection(cls.collection_name)
        transactions_cursor = transaction_collection.find(query)
        total_count = transaction_collection.count_documents(query)
        transactions_cursor = transactions_cursor.skip((page - 1) * per_page).limit(per_page)

        result = []
        for transaction in transactions_cursor:
            transaction["_id"] = str(transaction.get("_id"))
            transaction["business_id"] = str(transaction.get("business_id")) if transaction.get("business_id") else None
            transaction["agent_id"] = str(transaction.get("agent_id")) if transaction.get("agent_id") else None
            transaction["user_id"] = str(transaction.get("user_id")) if transaction.get("user_id") else None
            transaction["user__id"] = str(transaction.get("user__id")) if transaction.get("user__id") else None
            transaction["beneficiary_id"] = str(transaction.get("beneficiary_id")) if transaction.get("beneficiary_id") else None
            transaction["sender_id"] = str(transaction.get("sender_id")) if transaction.get("sender_id") else None
            result.append(transaction)

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "transactions": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def get_by_business_id_and_pin_number(cls, business_id, pin_number):
        
        if not business_id or not pin_number:
            raise ValueError("Both business_id and pin_number are required.")
        
        # Ensure business_id is objectId
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e
            
        transaction_collection = db.get_collection(cls.collection_name)
        data = transaction_collection.find_one(
            {
                "business_id": business_id,
                "pin_number": pin_number,
            }
        )
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data.get("business_id")) if data.get("business_id") else None
        data["user_id"] = str(data.get("user_id")) if data.get("user_id") else None
        data["user__id"] = str(data.get("user__id")) if data.get("user__id") else None
        data["beneficiary_id"] = str(data.get("beneficiary_id")) if data.get("beneficiary_id") else None
        data["sender_id"] = str(data.get("sender_id")) if data.get("sender_id") else None
        data["agent_id"] = str(data.get("agent_id")) if data.get("agent_id") else None

        return data

    @classmethod
    def get_by_business_id_and_internal_reference(cls, business_id, internal_reference):
        
        if not business_id or not internal_reference:
            raise ValueError("Both business_id and internal_reference are required.")
        
        # Ensure business_id is objectId
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e
            
        transaction_collection = db.get_collection(cls.collection_name)
        data = transaction_collection.find_one(
            {
                "business_id": business_id,
                "internal_reference": internal_reference,
            }
        )
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data.get("business_id")) if data.get("business_id") else None
        data["user_id"] = str(data.get("user_id")) if data.get("user_id") else None
        data["user__id"] = str(data.get("user__id")) if data.get("user__id") else None
        data["beneficiary_id"] = str(data.get("beneficiary_id")) if data.get("beneficiary_id") else None
        data["sender_id"] = str(data.get("sender_id")) if data.get("sender_id") else None
        data["agent_id"] = str(data.get("agent_id")) if data.get("agent_id") else None

        return data

    @classmethod
    def get_by_business_id_and_receiver_id(cls, business_id, receiver_id):
        if not business_id or not receiver_id:
            raise ValueError("Both business_id and receiver_id are required.")
        
        # Ensure business_id is ObjectId
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e

        transaction_collection = db.get_collection(cls.collection_name)
        data = transaction_collection.find_one(
            {
                "business_id": business_id,
                "receiverId": receiver_id,  # Field name as in your collection
            }
        )
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data.get("business_id")) if data.get("business_id") else None
        data["user_id"] = str(data.get("user_id")) if data.get("user_id") else None
        data["user__id"] = str(data.get("user__id")) if data.get("user__id") else None
        data["beneficiary_id"] = str(data.get("beneficiary_id")) if data.get("beneficiary_id") else None
        data["sender_id"] = str(data.get("sender_id")) if data.get("sender_id") else None
        data["agent_id"] = str(data.get("agent_id")) if data.get("agent_id") else None

        return data

    @classmethod
    def search_by_business_id_and_account(
        cls,
        business_id,
        account,
        page=1,
        per_page=10,
        start_date=None,
        end_date=None
    ):
        if not business_id or not account:
            raise ValueError("Both business_id and account are required.")

        # Ensure business_id is ObjectId
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e

        default_page = os.getenv("DEFAULT_PAGINATION_PAGE", 1)
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10)
        page = int(page) if page else int(default_page)
        per_page = int(per_page) if per_page else int(default_per_page)

        # Build AND query for both business_id and account
        query = {"business_id": business_id, "account": account}

        # Optional date filters (assume 'created_at' field)
        date_filter = {}
        if start_date:
            try:
                from_date_obj = datetime.fromisoformat(start_date)
                date_filter["$gte"] = from_date_obj
            except Exception:
                raise ValueError("Invalid date-time format for 'From'. Expected ISO 8601.")
        if end_date:
            try:
                to_date_obj = datetime.fromisoformat(end_date)
                date_filter["$lte"] = to_date_obj
            except Exception:
                raise ValueError("Invalid date-time format for 'To'. Expected ISO 8601.")
        if date_filter:
            query["created_at"] = date_filter

        transaction_collection = db.get_collection(cls.collection_name)
        transactions_cursor = transaction_collection.find(query)
        total_count = transaction_collection.count_documents(query)
        transactions_cursor = transactions_cursor.skip((page - 1) * per_page).limit(per_page)

        result = []
        for transaction in transactions_cursor:
            transaction["_id"] = str(transaction.get("_id"))
            transaction["business_id"] = str(transaction.get("business_id")) if transaction.get("business_id") else None
            transaction["account"] = str(transaction.get("account")) if transaction.get("account") else None
            transaction["user_id"] = str(transaction.get("user_id")) if transaction.get("user_id") else None
            transaction["user__id"] = str(transaction.get("user__id")) if transaction.get("user__id") else None
            transaction["beneficiary_id"] = str(transaction.get("beneficiary_id")) if transaction.get("beneficiary_id") else None
            transaction["sender_id"] = str(transaction.get("sender_id")) if transaction.get("sender_id") else None
            transaction["agent_id"] = str(transaction.get("agent_id")) if transaction.get("agent_id") else None
            result.append(transaction)

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "transactions": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def search_by_business_id_and_senderId(
        cls,
        business_id,
        sender_id,
        page=1,
        per_page=10,
        start_date=None,
        end_date=None
    ):
        if not business_id or not sender_id:
            raise ValueError("Both business_id and sender_id are required.")

        # Ensure business_id is ObjectId
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e

        default_page = os.getenv("DEFAULT_PAGINATION_PAGE", 1)
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10)
        page = int(page) if page else int(default_page)
        per_page = int(per_page) if per_page else int(default_per_page)

        # Build AND query for both business_id and sender_id
        query = {"business_id": business_id, "senderId": sender_id}

        # Optional date filters (assume 'created_at' field)
        date_filter = {}
        if start_date:
            try:
                from_date_obj = datetime.fromisoformat(start_date)
                date_filter["$gte"] = from_date_obj
            except Exception:
                raise ValueError("Invalid date-time format for 'From'. Expected ISO 8601.")
        if end_date:
            try:
                to_date_obj = datetime.fromisoformat(end_date)
                date_filter["$lte"] = to_date_obj
            except Exception:
                raise ValueError("Invalid date-time format for 'To'. Expected ISO 8601.")
        if date_filter:
            query["created_at"] = date_filter

        transaction_collection = db.get_collection(cls.collection_name)
        transactions_cursor = transaction_collection.find(query)
        total_count = transaction_collection.count_documents(query)
        transactions_cursor = transactions_cursor.skip((page - 1) * per_page).limit(per_page)

        result = []
        for transaction in transactions_cursor:
            transaction["_id"] = str(transaction.get("_id"))
            transaction["business_id"] = str(transaction.get("business_id")) if transaction.get("business_id") else None
            transaction["sender_id"] = str(transaction.get("sender_id")) if transaction.get("sender_id") else None
            transaction["account"] = str(transaction.get("account")) if transaction.get("account") else None
            transaction["user_id"] = str(transaction.get("user_id")) if transaction.get("user_id") else None
            transaction["user__id"] = str(transaction.get("user__id")) if transaction.get("user__id") else None
            transaction["beneficiary_id"] = str(transaction.get("beneficiary_id")) if transaction.get("beneficiary_id") else None
            transaction["agent_id"] = str(transaction.get("agent_id")) if transaction.get("agent_id") else None
            result.append(transaction)

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "transactions": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def get_by_business_id_and_receiverId(
        cls,
        business_id,
        receiverId,
        page=1,
        per_page=10,
        start_date=None,
        end_date=None
    ):
        if not business_id or not receiverId:
            raise ValueError("Both business_id and receiverId are required.")

        # Ensure business_id is ObjectId
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e

        default_page = os.getenv("DEFAULT_PAGINATION_PAGE", 1)
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10)
        page = int(page) if page else int(default_page)
        per_page = int(per_page) if per_page else int(default_per_page)

        # Build AND query for both business_id and receiverId
        query = {"business_id": business_id, "receiverId": receiverId}

        # Optional date filters (assume 'created_at' field)
        date_filter = {}
        if start_date:
            try:
                from_date_obj = datetime.fromisoformat(start_date)
                date_filter["$gte"] = from_date_obj
            except Exception:
                raise ValueError("Invalid date-time format for 'From'. Expected ISO 8601.")
        if end_date:
            try:
                to_date_obj = datetime.fromisoformat(end_date)
                date_filter["$lte"] = to_date_obj
            except Exception:
                raise ValueError("Invalid date-time format for 'To'. Expected ISO 8601.")
        if date_filter:
            query["created_at"] = date_filter

        transaction_collection = db.get_collection(cls.collection_name)
        transactions_cursor = transaction_collection.find(query)
        total_count = transaction_collection.count_documents(query)
        transactions_cursor = transactions_cursor.skip((page - 1) * per_page).limit(per_page)

        result = []
        for transaction in transactions_cursor:
            transaction["_id"] = str(transaction.get("_id"))
            transaction["business_id"] = str(transaction.get("business_id")) if transaction.get("business_id") else None
            transaction["receiverId"] = str(transaction.get("receiverId")) if transaction.get("receiverId") else None
            transaction["account"] = str(transaction.get("account")) if transaction.get("account") else None
            transaction["user_id"] = str(transaction.get("user_id")) if transaction.get("user_id") else None
            transaction["user__id"] = str(transaction.get("user__id")) if transaction.get("user__id") else None
            transaction["beneficiary_id"] = str(transaction.get("beneficiary_id")) if transaction.get("beneficiary_id") else None
            transaction["sender_id"] = str(transaction.get("sender_id")) if transaction.get("sender_id") else None
            transaction["agent_id"] = str(transaction.get("agent_id")) if transaction.get("agent_id") else None
            result.append(transaction)

        total_pages = (total_count + per_page - 1) // per_page

        return {
            "transactions": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def transaction_summary_by_business(cls, business_id, partner_name=None):
        if not business_id:
            raise ValueError("business_id is required.")

        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e

        # --- Partner Name Normalization ---
        def _normalize_partner(p):
            if p is None:
                return None
            p = p.strip().lower()
            if p == "intermex":
                return "Intermex"
            if p in {"instntmny", "instntmny", "instntmny"}:
                return "InstntMny"
            raise ValueError("Invalid partner_name. Must be 'Intermex' or 'InstntMny'.")

        partner_name = _normalize_partner(partner_name)

        transaction_collection = db.get_collection(cls.collection_name)

        now = datetime.now()
        start_today = datetime(now.year, now.month, now.day)
        start_week = start_today - timedelta(days=now.weekday())
        start_month = datetime(now.year, now.month, 1)
        start_year = datetime(now.year, 1, 1)

        # Build base query
        base_query = {"business_id": business_id}

        # Add partner_name filter if provided
        if partner_name:
            base_query["partner_name"] = partner_name

        def count_in_range(start_dt):
            query = base_query.copy()
            query["created_at"] = {"$gte": start_dt}
            return transaction_collection.count_documents(query)

        summary = {
            "today": count_in_range(start_today),
            "this_week": count_in_range(start_week),
            "this_month": count_in_range(start_month),
            "this_year": count_in_range(start_year)
        }

        return {"transaction_summary": summary}



    

















