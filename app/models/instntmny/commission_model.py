import uuid
import bcrypt
import os
from bson.objectid import ObjectId
from datetime import datetime
from app.extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ..base_model import BaseModel


from datetime import datetime
import uuid

import uuid
from datetime import datetime
from app.extensions.db import db
from marshmallow import Schema, fields, validate
from ...utils.crypt import encrypt_data, decrypt_data
from ..base_model import BaseModel


# Commission Model
class Commission(BaseModel):
    """
    A Commission represents an entity for storing agents and Zeepay's commission.
    """
    collection_name = "commissions"

    def __init__(self, name, commission, business_id=None, user__id=None, user_id=None, 
                 created_by=None,created_at=None, updated_at=None):
        
        super().__init__(business_id=business_id, user_id=user_id, user__id=user__id)

        # Initialize business_id and created_by
        self.business_id = business_id
        self.created_by = created_by

        # Encrypt sensitive fields if needed
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        
        commision_str = str(commission)
        
        self.commission = encrypt_data(commision_str)
        self.hashed_commission = hash_data(commision_str)

        # Dates
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        """
        Convert the commission object to a dictionary representation.
        """
        commission_dict = super().to_dict()
        commission_dict.update({
            "name": self.name,
            "commission": self.commission,
            "business_id": self.business_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return commission_dict

    @classmethod
    def get_by_id(cls, business_id, commission_id):
        """
        Retrieve a commission by its ID, decrypting fields before returning.
        """
        try:
            commission_id_obj = ObjectId(commission_id)
        except Exception as e:
            return None
        
        try:
            business_id_obj = ObjectId(business_id)
        except Exception as e:
            return None

        commission_collection = db.get_collection(cls.collection_name)
        data = commission_collection.find_one(
            {
            "_id": commission_id_obj, 
            "business_id": business_id_obj
            }
        )

        if not data:
            return None  # Notice not found

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["user__id"] = str(data["user__id"])
        data["created_by"] = str(data["created_by"])

        # Decrypt fields before returning
        data["name"] = decrypt_data(data["name"])
        data["commission"] = decrypt_data(data["commission"])

        data.pop("user__id", None)
        data.pop("user_id", None)
        
        return data

    @classmethod
    def update(cls, commission_id, **updates):
        """
        Update a commission's information by its ID.
        """
        if "name" in updates:
            updates["name"] = encrypt_data(updates["name"])
        if "commission" in updates:
            updates["commission"] = encrypt_data(updates["commission"])
            updates["hashed_commission"] = hash_data(updates["commission"])
            
        updates["updated_at"] = datetime.now()

        return super().update(commission_id, **updates)

    @classmethod
    def create(cls, name, commission, business_id=None, user__id=None):
        """
        Create a new commission entry.
        """
        notice_board = cls(name=name, commission=commission, business_id=business_id, user__id=user__id)
        return notice_board.save()

    @classmethod
    def get_all(cls, business_id, page=1, per_page=10):
        """
        Get all notices, decrypting fields and implementing pagination.
        """
        # Load default settings from env
        default_page = os.getenv("DEFAULT_PAGINATION_PAGE")
        
        try:
            business_id_obj = ObjectId(business_id)
        except Exception as e:
            return None


        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE")
        
        # Ensure page and per_page are integers
        page = int(page) if page else int(default_page)
        per_page = int(per_page) if per_page else int(default_per_page)

        commission_collection = db.get_collection(cls.collection_name)
        notices_cursor = commission_collection.find({"business_id": business_id_obj})

        # Get total count for pagination
        total_count = commission_collection.count_documents({})

        # Apply pagination using skip and limit
        notices_cursor = notices_cursor.skip((page - 1) * per_page).limit(per_page)

        result = []
        for notice in notices_cursor:
            notice["_id"] = str(notice["_id"])
            notice["business_id"] = str(notice["business_id"])
            notice["user__id"] = str(notice["user__id"])
            notice["created_by"] = str(notice["created_by"])

            # Decrypt fields before returning them
            notice["name"] = decrypt_data(notice["name"])
            notice["commission"] = decrypt_data(notice["commission"])

            notice.pop("user__id", None)
            notice.pop("user_id", None)
            
            # Append the processed notice data to the result list
            result.append(notice)

        # Calculate the total number of pages
        total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

        return {
            "notices": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }

    @classmethod
    def delete(cls, commission_id, business_id):
        """
        Delete a commission by its ID.
        """
        return super().delete(commission_id, business_id)
