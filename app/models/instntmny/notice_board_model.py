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


# NoticeBoard Model
class NoticeBoard(BaseModel):
    """
    A NoticeBoard represents an entity for storing notices with title, excerpt, and an optional message.
    """
    collection_name = "notice_boards"

    def __init__(self, title, excerpt, message=None, business_id=None, user__id=None, user_id=None, 
                 created_by=None,created_at=None, updated_at=None):
        
        super().__init__(business_id=business_id, user_id=user_id, user__id=user__id)

        # Initialize business_id and created_by
        self.business_id = business_id
        self.created_by = created_by

        # Encrypt sensitive fields if needed
        self.title = encrypt_data(title)
        self.hashed_title = hash_data(title)
        self.excerpt = encrypt_data(excerpt)
        self.message = encrypt_data(message) if message else None

        # Dates
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        """
        Convert the notice board object to a dictionary representation.
        """
        notice_board_dict = super().to_dict()
        notice_board_dict.update({
            "title": self.title,
            "excerpt": self.excerpt,
            "message": self.message,
            "business_id": self.business_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return notice_board_dict

    @classmethod
    def get_by_id(cls, business_id, notice_board_id):
        """
        Retrieve a notice board by its ID, decrypting fields before returning.
        """
        try:
            notice_board_id_obj = ObjectId(notice_board_id)
        except Exception as e:
            return None
        
        try:
            business_id_obj = ObjectId(business_id)
        except Exception as e:
            return None

        notice_board_collection = db.get_collection(cls.collection_name)
        data = notice_board_collection.find_one(
            {
            "_id": notice_board_id_obj, 
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
        data["title"] = decrypt_data(data["title"])
        data["excerpt"] = decrypt_data(data["excerpt"])
        data["message"] = decrypt_data(data["message"]) if data.get("message") else None

        data.pop("user__id", None)
        data.pop("user_id", None)
        
        return data

    @classmethod
    def update(cls, notice_board_id, **updates):
        """
        Update a notice board's information by its ID.
        """
        if "title" in updates:
            updates["title"] = encrypt_data(updates["title"])
            updates["hashed_title"] = hash_data(updates["title"])
        if "excerpt" in updates:
            updates["excerpt"] = encrypt_data(updates["excerpt"])
        if "message" in updates:
            updates["message"] = encrypt_data(updates["message"]) if updates.get("message") else None

        updates["updated_at"] = datetime.now()

        return super().update(notice_board_id, **updates)

    @classmethod
    def create(cls, title, excerpt, message=None, business_id=None, user__id=None):
        """
        Create a new notice board entry.
        """
        notice_board = cls(title=title, excerpt=excerpt, message=message, business_id=business_id, user__id=user__id)
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

        notice_board_collection = db.get_collection(cls.collection_name)
        notices_cursor = notice_board_collection.find({"business_id": business_id_obj})

        # Get total count for pagination
        total_count = notice_board_collection.count_documents({})

        # Apply pagination using skip and limit
        notices_cursor = notices_cursor.skip((page - 1) * per_page).limit(per_page)

        result = []
        for notice in notices_cursor:
            notice["_id"] = str(notice["_id"])
            notice["business_id"] = str(notice["business_id"])
            notice["user__id"] = str(notice["user__id"])
            notice["created_by"] = str(notice["created_by"])

            # Decrypt fields before returning them
            notice["title"] = decrypt_data(notice["title"])
            notice["excerpt"] = decrypt_data(notice["excerpt"])
            notice["message"] = decrypt_data(notice["message"]) if notice.get("message") else None

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
    def delete(cls, notice_board_id, business_id):
        """
        Delete a notice board by its ID.
        """
        return super().delete(notice_board_id, business_id)
