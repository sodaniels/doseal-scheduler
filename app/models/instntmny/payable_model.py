import os
from datetime import datetime
from bson.objectid import ObjectId

from app.extensions.db import db
from ..base_model import BaseModel
from ...utils.crypt import encrypt_data, decrypt_data, hash_data

# ---------------------------------
# Payable Model
# ---------------------------------

class Payable(BaseModel):
    """
    A Payable represents a scheduled outgoing payment with reminder offsets.
    Fields mirror the PayableSchema (Marshmallow).
    """

    collection_name = "payables"

    def __init__(
        self,
        business_id,
        created_by,                 # str(ObjectId) or ObjectId
        name,
        reference,
        currency,
        amount,
        due_at,                     # datetime (UTC)
        reminder_offsets_days,      # list[int]
        status="pending",
        created_at=None,
        updated_at=None,
    ):
        # persist multi-tenant references (ObjectIds)
        self.business_id = ObjectId(business_id) if isinstance(business_id, str) else business_id
        self.created_by = ObjectId(created_by) if isinstance(created_by, str) else created_by

        # hashed keys useful for uniqueness/lookup
        self.hashed_reference = hash_data(reference) if reference else None

        # encrypt text-like/PII-ish fields
        self.name = encrypt_data(name) if name else None
        self.reference = encrypt_data(reference) if reference else None
        self.currency = encrypt_data(currency) if currency else None
        self.status = encrypt_data(status) if status else None

        # store queryable/numeric/time fields in plaintext for efficient ops
        self.amount =  encrypt_data(float(amount)) if amount is not None else None
        if not isinstance(due_at, datetime):
            raise ValueError("due_at must be a datetime")
        self.due_at = due_at

        # reminder offsets (list[int])
        self.reminder_offsets_days = list({int(x) for x in reminder_offsets_days or []})  # de-dup

        # timestamps
        now = created_at or datetime.utcnow()
        self.created_at = now
        self.updated_at = updated_at or now

    # --------- Serialization ----------

    def to_dict(self):
        """
        Convert the Payable object to a Mongo-ready dict.
        """
        base = super().to_dict()
        base.update({
            "business_id": self.business_id,
            "created_by": self.created_by,

            "name": self.name,                   # encrypted
            "reference": self.reference,         # encrypted
            "currency": self.currency,           # encrypted
            "status": self.status,               # encrypted

            "hashed_reference": self.hashed_reference,  # hashed

            "amount": self.amount,               # plain
            "due_at": self.due_at,               # plain datetime
            "reminder_offsets_days": self.reminder_offsets_days,  # plain list[int]

            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return base

    # --------- Fetchers ----------

    @classmethod
    def get_by_id(cls, payable_id):
        """
        Retrieve a Payable by its _id and decrypt fields.
        """
        try:
            oid = ObjectId(payable_id)
        except Exception:
            return None

        col = db.get_collection(cls.collection_name)
        data = col.find_one({"_id": oid})
        if not data:
            return None

        # stringify ids
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data.get("business_id")) if data.get("business_id") else None
        data["created_by"] = str(data.get("created_by")) if data.get("created_by") else None

        # decrypt selected fields
        fields_to_decrypt = ["name", "reference", "currency", "status"]
        dec = {f: (decrypt_data(data.get(f)) if data.get(f) else None) for f in fields_to_decrypt}

        return {
            "payable_id": data["_id"],
            "business_id": data["business_id"],
            "created_by": data["created_by"],
            "name": dec["name"],
            "reference": dec["reference"],
            "currency": dec["currency"],
            "status": dec["status"],
            "amount": data.get("amount"),
            "due_at": data.get("due_at"),
            "reminder_offsets_days": data.get("reminder_offsets_days") or [],
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    @classmethod
    def get_by_id_and_business_id(cls, payable_id, business_id):
        """
        Retrieve a Payable scoped to a business, then decrypt fields.
        """
        try:
            oid = ObjectId(payable_id)
            bid = ObjectId(business_id) if isinstance(business_id, str) else business_id
        except Exception:
            return None

        col = db.get_collection(cls.collection_name)
        data = col.find_one({"_id": oid, "business_id": bid})
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data.get("business_id")) if data.get("business_id") else None
        data["created_by"] = str(data.get("created_by")) if data.get("created_by") else None

        fields_to_decrypt = ["name", "reference", "currency", "status"]
        dec = {f: (decrypt_data(data.get(f)) if data.get(f) else None) for f in fields_to_decrypt}

        return {
            "payable_id": data["_id"],
            "business_id": data["business_id"],
            "created_by": data["created_by"],
            "name": dec["name"],
            "reference": dec["reference"],
            "currency": dec["currency"],
            "status": dec["status"],
            "amount": data.get("amount"),
            "due_at": data.get("due_at"),
            "reminder_offsets_days": data.get("reminder_offsets_days") or [],
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

    # --------- Queries (paginated) ----------

    @classmethod
    def list_paginated(cls, business_id, status=None, page=1, per_page=10):
        """
        Paginated list of payables for a business.
        `status` is compared after decrypting (so we filter by encrypted value).
        """
        bid = ObjectId(business_id) if isinstance(business_id, str) else business_id
        page = int(page or 1)
        per_page = int(per_page or int(os.getenv("DEFAULT_PAGINATION_PER_PAGE", 10)))

        col = db.get_collection(cls.collection_name)
        q = {"business_id": bid}

        # If status filter provided, encrypt for query
        if status:
            q["status"] = encrypt_data(status)

        cursor = col.find(q).sort("due_at", 1)
        total_count = col.count_documents(q)
        cursor = cursor.skip((page - 1) * per_page).limit(per_page)

        result = []
        for doc in cursor:
            # ids
            doc_id = str(doc["_id"])
            b_id = str(doc.get("business_id")) if doc.get("business_id") else None
            c_by = str(doc.get("created_by")) if doc.get("created_by") else None

            # decrypt
            dec = {
                "name": decrypt_data(doc.get("name")) if doc.get("name") else None,
                "reference": decrypt_data(doc.get("reference")) if doc.get("reference") else None,
                "currency": decrypt_data(doc.get("currency")) if doc.get("currency") else None,
                "status": decrypt_data(doc.get("status")) if doc.get("status") else None,
            }

            result.append({
                "payable_id": doc_id,
                "business_id": b_id,
                "created_by": c_by,
                "name": dec["name"],
                "reference": dec["reference"],
                "currency": dec["currency"],
                "status": dec["status"],
                "amount": doc.get("amount"),
                "due_at": doc.get("due_at"),
                "reminder_offsets_days": doc.get("reminder_offsets_days") or [],
                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at"),
            })

        total_pages = (total_count + per_page - 1) // per_page
        return {
            "payables": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page,
        }

    # --------- Mutations ----------

    @classmethod
    def update(cls, payable_id, business_id, **updates):
        """
        Update a payable by id (handles encryption + housekeeping).
        """
        enc_map = {}

        # text-like fields to (re)encrypt if present
        if "name" in updates:
            enc_map["name"] = encrypt_data(updates["name"]) if updates.get("name") else None
        if "reference" in updates:
            enc_map["reference"] = encrypt_data(updates["reference"]) if updates.get("reference") else None
            enc_map["hashed_reference"] = hash_data(updates["reference"]) if updates.get("reference") else None
        if "currency" in updates:
            enc_map["currency"] = encrypt_data(updates["currency"]) if updates.get("currency") else None
        if "status" in updates:
            enc_map["status"] = encrypt_data(updates["status"]) if updates.get("status") else None

        # numeric/time/list fields (stored in plaintext)
        if "amount" in updates:
            enc_map["amount"] = float(updates["amount"]) if updates.get("amount") is not None else None
        if "due_at" in updates:
            enc_map["due_at"] = updates.get("due_at")
        if "reminder_offsets_days" in updates:
            offs = updates.get("reminder_offsets_days") or []
            enc_map["reminder_offsets_days"] = list({int(x) for x in offs})

        enc_map["updated_at"] = datetime.utcnow()
        return super().update(payable_id, business_id, **enc_map)

    @classmethod
    def delete(cls, payable_id, business_id):
        """
        Delete a payable by id.
        """
        return super().delete(payable_id, business_id)

    @classmethod
    def mark_status(cls, payable_id, business_id, new_status):
        """
        Convenience method to update only the status (+ updated_at).
        """
        return super().update(
            payable_id,
            business_id,
            status=encrypt_data(new_status),
            updated_at=datetime.utcnow(),
        )
