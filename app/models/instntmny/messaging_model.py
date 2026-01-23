from datetime import datetime
from app.extensions.db import db
from bson.objectid import ObjectId
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
import os
from ..base_model import BaseModel

# Contacts Model
class Contacts(BaseModel):
    """
    A Contacts represents an entity for storing contacts with name, contacts, business_id, and created_by.
    """
    collection_name = "contacts"

    def __init__(self, name, contacts, business_id, user_id, 
                 created_by, user__id, created_at=None, updated_at=None):
        super().__init__(business_id=business_id, user_id=user_id, user__id=user__id)

        # Initialize fields
        self.name = encrypt_data(name)  # Encrypting the name
        self.hashed_name = hash_data(name)  # Hashing the name for unique identification
        self.contacts = encrypt_data(contacts)  # Encrypt contacts before storing
        self.business_id = business_id  # Business ID associated with the notice
        self.created_by = created_by  # The user who created the notice
        self.user_id = user_id  # The user who created the notice

        # Dates
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        """
        Convert the notice board object to a dictionary representation.
        """
        notice_board_dict = super().to_dict()
        notice_board_dict.update({
            "name": self.name,
            "contacts": self.contacts,  # This field will be encrypted when saving
            "business_id": self.business_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return notice_board_dict

    @classmethod
    def get_by_id(cls, contact_id, business_id):
        """
        Retrieve a notice board by its ID, decrypting fields before returning.
        """
        try:
            contact_id_obj = ObjectId(contact_id)
            business_id_obj = ObjectId(business_id)
        except Exception as e:
            return None
        
        contact_collection = db.get_collection(cls.collection_name)
        data = contact_collection.find_one(
            {
                "_id": contact_id_obj, 
                "business_id": business_id_obj
            }
        )

        if not data:
            return None  # Notice not found

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["created_by"] = str(data["created_by"])

        # Decrypt fields before returning
        data["name"] = decrypt_data(data["name"])
        data["contacts"] = decrypt_data(data["contacts"])  # Decrypt the contacts field

        return data

    @classmethod
    def update(cls, notice_board_id, **updates):
        """
        Update a notice board's information by its ID.
        """
        if "name" in updates:
            updates["name"] = encrypt_data(updates["name"])
            updates["hashed_name"] = hash_data(updates["name"])

        if "contacts" in updates:
            updates["contacts"] = encrypt_data(updates["contacts"])  # Encrypt contacts before storing

        updates["updated_at"] = datetime.now()

        return super().update(notice_board_id, **updates)

    @classmethod
    def create(cls, name, contacts, business_id, created_by):
        """
        Create a new notice board entry.
        """
        notice_board = cls(name=name, contacts=contacts, business_id=business_id, created_by=created_by)
        return notice_board.save()

    @classmethod
    def get_all(cls, business_id, page=1, per_page=10):
        """
        Get all notices, decrypting fields and implementing pagination.
        """
        default_page = os.getenv("DEFAULT_PAGINATION_PAGE")
        default_per_page = os.getenv("DEFAULT_PAGINATION_PER_PAGE")
        
        try:
            business_id_obj = ObjectId(business_id)
        except Exception as e:
            return None
        
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
            notice["created_by"] = str(notice["created_by"])

            # Decrypt fields before returning them
            notice["name"] = decrypt_data(notice["name"])
            notice["contacts"] = decrypt_data(notice["contacts"])  # Decrypt the contacts field

            notice.pop("user__id", None)
            
            # Append the processed notice data to the result list
            result.append(notice)

        # Calculate the total number of pages
        total_pages = (total_count + per_page - 1) // per_page  # Ceiling division

        return {
            "contact_list": result,
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
