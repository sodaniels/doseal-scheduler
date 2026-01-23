
from app.utils.logger import Log
from app.extensions.db import db
from app.utils.crypt import encrypt_data, decrypt_data, hash_data


class BusinessDAO(object):
    
    def __init__(self):
        self.db = db
        
    def get_business_by_email(self, email):
        """Retrieve a business by email."""
        try:
            hashed_email = hash_data(email)
            business = db.businesses.find_one({"email_hashed": hashed_email})
            if business:
                business["_id"] = str(business["_id"])
                # Decrypt other fields as necessary
                business.pop("password", None)
        
            return business
        except Exception as e:
            Log.info(f"[get_business_by_email] Error: {str(e)}")