from datetime import datetime
from app.extensions.db import db
from bson import ObjectId 

class ValidateRegistry:
    def __init__(self, person=None, address=None, endUserId=None, callback_url=None,
                 vendorData=None, endpoint=None, request_id=None
                ):
        self.person = person
        self.address = address
        self.endUserId = endUserId
        self.callback_url = callback_url
        self.vendorData = vendorData,
        self.endpoint = endpoint,
        self.request_id = request_id,
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        return {
            "person": self.person,
            "address": self.address,
            "endUserId": self.endUserId,
            "callback_url": self.callback_url,
            "admin_id": self.vendorData,
            "endpoint": self.endpoint,
            "request_id": self.request_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    def save(self):
            """Save the verificaiton to the MongoDB database."""
            verifications_collection = db.get_collection("validate_registry")
            result = verifications_collection.insert_one(self.to_dict())
            return result.inserted_id
        
    @staticmethod
    def update(record_id, updates):
        """
        Update an existing verification record in the MongoDB database.
        
        Args:
            record_id (str): The ID of the record to update.
            updates (dict): A dictionary of fields to update.
        
        Returns:
            dict: The result of the update operation.
        """
        verifications_collection = db.get_collection("verifications")
        updates["updated_at"] = datetime.now()  # Automatically update the `updated_at` field
        result = verifications_collection.update_one(
            {"_id": ObjectId(record_id)},  # Match by ObjectId
            {"$set": updates}  # Apply updates
        )
        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
            "acknowledged": result.acknowledged,
        }
    
    @staticmethod
    def update_validate_registry_response(request_id, response):
        """
        Update validate_registry response to the verifications collection response
        """
        # MongoDB connection
        verifications_collection = db.get_collection("validate_registry")
        
        # Update only if submit_verification.verification does not exist
        filter_query = {
            "request_id": request_id,
        }

        update_query = {
            "$set": {
                "response": response
            }
        }

        # Perform the update operation
        result = verifications_collection.update_one(filter_query, update_query)

        return {
            "matched_count": result.matched_count,
            "modified_count": result.modified_count,
            "acknowledged": result.acknowledged,
        }
    