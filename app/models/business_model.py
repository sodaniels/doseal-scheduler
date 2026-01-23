import uuid
import bcrypt

from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from marshmallow import ValidationError
from datetime import datetime
from app.extensions.db import db
from app.utils.logger import Log # import logging
from app.utils.generators import generate_client_id
from app.utils.crypt import encrypt_data, decrypt_data, hash_data

class Business:
    def __init__(self,tenant_id, business_name, start_date, country, city, state, postcode, currency, 
                 website, alternate_contact_number, time_zone, first_name, last_name, username, password, 
                 email, package, landmark=None, image=None, business_contact=None, store_url = None, 
                 prefix=None, user_id=None, return_url=None, callback_url=None, status="Active", 
                 account_type="super_admin",):
        # Generate client_id
        client_id = generate_client_id()

        self.tenant_id = encrypt_data(tenant_id)
        self.business_name = encrypt_data(business_name)
        self.start_date = encrypt_data(start_date)
        self.image = image  # This will be handled separately if uploaded
        self.business_contact = encrypt_data(business_contact)
        self.country = encrypt_data(country)
        self.city = encrypt_data(city)
        self.state = encrypt_data(state)
        self.postcode = encrypt_data(postcode)
        self.landmark = encrypt_data(landmark) if landmark else None
        self.currency = encrypt_data(currency)
        self.website = encrypt_data(website) if website else None
        self.alternate_contact_number = encrypt_data(alternate_contact_number)
        self.time_zone = encrypt_data(time_zone)
        self.prefix = encrypt_data(prefix) if prefix else None
        self.first_name = encrypt_data(first_name)
        self.last_name = encrypt_data(last_name)
        self.username = encrypt_data(username)
        # Hash the password if not already hashed
        if not password.startswith("$2b$"):
            self.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        else:
            self.password = password  # If already hashed, store as is
        self.email = encrypt_data(email)
        self.hashed_email = hash_data(email)
        self.store_url = encrypt_data(store_url)
        self.package = encrypt_data(package)
        self.user_id = user_id if user_id else None
        self.return_url = encrypt_data(return_url) if return_url else None
        self.callback_url = encrypt_data(callback_url) if callback_url else None
        self.status = encrypt_data(status)
        self.client_id = encrypt_data(client_id)
        self.client_id_hashed = hash_data(client_id)
        self.account_type = encrypt_data(account_type)
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the business object to a dictionary representation.
        """
        business_dict = {
            "tenant_id": self.tenant_id,
            "business_name": self.business_name,
            "start_date": self.start_date,
            "image": self.image,
            "business_contact": self.business_contact,
            "country": self.country,
            "city": self.city,
            "state": self.state,
            "postcode": self.postcode,
            "landmark": self.landmark,
            "currency": self.currency,
            "website": self.website,
            "alternate_contact_number": self.alternate_contact_number,
            "time_zone": self.time_zone,
            "prefix": self.prefix,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "username": self.username,
            "password": self.password,
            "email": self.email,
            "hashed_email": self.hashed_email,
            "store_url": self.store_url,
            "package": self.package,
            "user_id": self.user_id,
            "client_id": self.client_id,
            "client_id_hashed": self.client_id_hashed,
            "return_url": self.return_url,
            "callback_url": self.callback_url,
            "status": self.status,
            "account_type": self.account_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return business_dict

    def save(self):
        """Save the business to the MongoDB database."""
        business_collection = db.get_collection("businesses")
        result = business_collection.insert_one(self.to_dict())
        return (self.client_id, self.tenant_id, result.inserted_id, self.email)

    @staticmethod
    def get_business_by_id(business_id):
        """Retrieve a business by its MongoDB _id."""
        try:
            object_id = ObjectId(business_id)
        except Exception as e:
            raise ValueError(f"Invalid _id format: {business_id}") from e

        collection = db.get_collection("businesses")
        business = collection.find_one({"_id": object_id})
        if business:
            business["_id"] = str(business["_id"])
            business["business_name"] = decrypt_data(business["business_name"])
            business["email"] = decrypt_data(business["email"])
            business["phone_number"] = decrypt_data(business["business_contact"])
            # Decrypt other fields as necessary
            business.pop("password", None)
        return business

    @staticmethod
    def get_business_by_client_id(client_id):
        """Retrieve a business by its client_id."""
        businesses_collection = db.get_collection("businesses")
        business = businesses_collection.find_one({"client_id": client_id})
        if business:
            business["_id"] = str(business["_id"])
            business["business_name"] = decrypt_data(business["business_name"])
            business["email"] = decrypt_data(business["email"])
            business["business_contact"] = decrypt_data(business["business_contact"])
            # Decrypt other fields as necessary
            business.pop("password", None)
        return business

    @staticmethod
    def get_business_by_email(email):
        """Retrieve a business by email."""
        hashed_email = hash_data(email)
        collection = db.get_collection("businesses")
        business = collection.find_one({"email_hashed": hashed_email})
        if business:
            business["_id"] = str(business["_id"])
            business["business_name"] = decrypt_data(business["business_name"])
            business["email"] = decrypt_data(business["email"])
            business["phone_number"] = decrypt_data(business["phone_number"])
            # Decrypt other fields as necessary
            business.pop("password", None)
        return business

    @staticmethod
    def update_business(email, **updates):
        """Update a business's details."""
        updates["updated_at"] = datetime.now()
        collection = db.get_collection("businesses")
        result = collection.update_one({"email": email}, {"$set": updates})
        return result.inserted_id
        
    @staticmethod
    def update_business_with_user_id(business_id, **updates):
        """Update a business's details."""
        updates["updated_at"] = datetime.now()
        collection = db.get_collection("businesses")
        result = collection.update_one({"_id": ObjectId(business_id)}, {"$set": updates})
        return result
       
    @staticmethod
    def update_business_image(email, image, file_path):
        """Update a business's image and file path."""
        try:
            # Ensure the image is valid (this could be done with a validation check, depending on your requirements)
            if not image:
                raise ValueError("No image provided")

            # Prepare the updates
            updates = {
                "image": encrypt_data(image),
                "file_path": encrypt_data(file_path), 
                "updated_at": datetime.now()
            }

            # Update the business in the database
            hashed_email = hash_data(email)
            collection = db.get_collection("businesses")
            result = collection.update_one({"hashed_email": hashed_email}, {"$set": updates})
            
            # Check if any document was updated
            if result.modified_count == 0:
                raise ValueError("Business not found or no change was made")

            return True

        except Exception as e:
            return False

    @staticmethod
    def check_item_exists(key, value):
        """
        Check if an item exists by business_id and a specific key (hashed comparison).
        This method allows dynamic checks for any key (like 'name', 'phone', etc.).
        
        Args:
        - business_id: The business ID to filter the items.
        - key: The key (field) to check for existence (e.g., 'name', 'phone').
        - value: The value of the key to check for existence.

        Returns:
        - True if the item exists, False otherwise.
        """
        
        # Dynamically hash the value of the key
        hashed_key = hash_data(value)  # Hash the value provided for the dynamic field

        # Dynamically create the query with business_id and hashed field
        query = {
            f"hashed_{key}": hashed_key  # Use the key dynamically (e.g., "hashed_name" or "hashed_phone")
        }

        # Query the database for an item matching the given business_id and hashed value
        collection = db.get_collection("businesses")
        existing_item = collection.find_one(query)

        # Return True if a matching item is found, else return False
        if existing_item:
            return True  # Item exists
        else:
            return False  # Item does not exist
    
    @staticmethod
    def get_business(client_id):
        collection = db.get_collection("businesses")
        return collection.find_one({"client_id": client_id})
    
    @staticmethod
    def check_password(business, password):
        """Check if the password is correct."""
        return check_password_hash(business['password'], password)
   
    @staticmethod
    def delete_business_with_cascade(business_id):
        """
        Deletes a business and cascades the deletion to related users and agents.
        """
        # First, find the business to delete
        business = db.get_collection("businesses").find_one({"_id": ObjectId(business_id)})
        
        if not business:
            raise ValidationError("Business not found.")
        
        # Delete related agents and users (assuming they have the `business_id` field)
        db.get_collection("agents").delete_many({"business_id": ObjectId(business_id)}) 
        db.get_collection("users").delete_many({"business_id": ObjectId(business_id)})
        
        # Finally, delete the business itself
        db.get_collection("businesses").delete_one({"_id": ObjectId(business_id)})  # Delete the business
        
        response_json = {
            "status_code": 200,
            "message": "Business and related data deleted successfully."
        }

        return response_json
  
    
class Client:
    @staticmethod
    def create_client(client_id, client_secret):
        collection = db.get_collection("clients")
        collection.insert_one({"client_id": client_id, "client_secret": client_secret})

    @staticmethod
    def get_client(client_id, client_secret):
        collection = db.get_collection("clients")
        return collection.find_one({"client_id": client_id, "client_secret": client_secret})
    
    @staticmethod
    def retrieve_client(client_id):
        collection = db.get_collection("clients")
        client = collection.find_one({"client_id": client_id})
        
        if client:
            return client
        else:
            return None


class Token:
    @staticmethod
    def create_token(client_id, access_token, refresh_token, expires_in, refresh_expires_in):
        collection = db.get_collection("tokens")
        collection.insert_one({
            "client_id": client_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
            "refresh_expires_in": refresh_expires_in
        })

    @staticmethod
    def get_token(access_token):
        collection = db.get_collection("tokens")
        return collection.find_one({"access_token": access_token})

    @staticmethod
    def delete_token(access_token):
        collection = db.get_collection("tokens")
        result = collection.delete_one({"access_token": access_token})
        return result.deleted_count > 0
    
    @staticmethod
    def get_refresh_token(refresh_token):
        collection = db.get_collection("tokens")
        return collection.find_one({"refresh_token": refresh_token})