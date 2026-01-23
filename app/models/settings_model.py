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

# Limit Model
class Limit(BaseModel):
    """
    A Limit represents a financial threshold or restriction associated with a user or business.
    """
    collection_name = "limits"

    def __init__(self, user_id, business_id, amount, agent_id=None, created_at=None, updated_at=None):
        super().__init__(user_id=user_id, business_id=business_id, agent_id=agent_id, amount=amount,
                         created_at=created_at, updated_at=updated_at)

        self.user_id = ObjectId(user_id)
        self.business_id = ObjectId(business_id)
        self.agent_id = ObjectId(agent_id) if agent_id else None
        self.amount = encrypt_data(amount)
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        limit_dict = super().to_dict()
        limit_dict.update({
            "user_id": self.user_id,
            "business_id": self.business_id,
            "agent_id": self.agent_id,
            "amount": self.amount,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        })
        return limit_dict

    @classmethod
    def get_by_business_and_agent_id(cls, business_id, agent_id):
        """
        Retrieve a limit by business_id and agent_id.
        """
        try:
            business_id_obj = ObjectId(business_id)
            agent_id_obj = ObjectId(agent_id)
        except Exception:
            return None

        query = {
            "business_id": business_id_obj,
            "agent_id": agent_id_obj
        }

        setting_collection = db.get_collection(cls.collection_name)
        data = setting_collection.find_one(query)
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["user_id"] = str(data["user_id"])
        data["business_id"] = str(data["business_id"])
        data["agent_id"] = str(data["agent_id"])
        data["amount"] = data["amount"]

        return data

    @classmethod
    def get_by_business_and_user_id(cls, business_id, user_id):
        """
        Retrieve a limit by business_id and user_id.
        """
        try:
            business_id_obj = ObjectId(business_id)
            user_id_id_obj = ObjectId(user_id)
        except Exception:
            return None

        query = {
            "business_id": business_id_obj,
            "user_id": user_id_id_obj
        }

        setting_collection = db.get_collection(cls.collection_name)
        data = setting_collection.find_one(query)
        if not data:
            return None

        data["_id"] = str(data["_id"])
        data["user_id"] = str(data["user_id"])
        data["business_id"] = str(data["business_id"])
        data["agent_id"] = str(data.get("agent_id")) if data.get("agent_id") else None
        data["amount"] = data["amount"]

        return data

    @classmethod
    def update(cls, limit_id, **updates):
        if "amount" in updates:
            business_id = updates.get("business_id")
            updates["amount"] = encrypt_data(updates["amount"])
        updates["updated_at"] = datetime.now()
        return super().update(limit_id, business_id, **updates)

    def create_or_update(self):
        query = {
            "user_id": self.user_id,
            "business_id": self.business_id,
            "agent_id": self.agent_id
        }

        setting_collection = db.get_collection(self.collection_name)
        existing_limit = setting_collection.find_one(query)

        if existing_limit:
            return self.update(existing_limit["_id"], amount=decrypt_data(self.amount))
        else:
            return setting_collection.insert_one(self.to_dict()).inserted_id
