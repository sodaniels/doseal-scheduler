# models/social/password_reset_token.py

from datetime import datetime, timedelta
from bson import ObjectId
from ...extensions.db import db
from ...utils.logger import Log
import secrets


class PasswordResetToken:
    """Model for password reset tokens."""
    
    collection_name = "password_reset_tokens"
    
    @staticmethod
    def create_token(email, user_id, business_id, expiry_minutes=5):
        """
        Create a new password reset token.
        
        Args:
            email: User's email
            user_id: User's ObjectId or string
            business_id: Business's ObjectId or string
            expiry_minutes: Token validity in minutes (default: 5)
            
        Returns:
            Tuple (success: bool, token: str or None, error: str or None)
        """
        log_tag = f"[PasswordResetToken][create_token][{email}]"
        
        try:
            collection = db.get_collection(PasswordResetToken.collection_name)
            
            # Invalidate any existing tokens for this email
            collection.update_many(
                {"email": email, "used": False},
                {"$set": {"used": True, "invalidated_at": datetime.utcnow()}}
            )
            
            # Generate new token
            reset_token = secrets.token_urlsafe(32)
            
            # Calculate expiry
            expires_at = datetime.utcnow() + timedelta(minutes=expiry_minutes)
            
            user_id_obj = ObjectId(user_id) if not isinstance(user_id, ObjectId) else user_id
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            # Insert token
            token_doc = {
                "email": email,
                "user_id": user_id_obj,
                "business_id": business_id_obj,
                "token": reset_token,
                "created_at": datetime.utcnow(),
                "expires_at": expires_at,
                "used": False
            }
            
            result = collection.insert_one(token_doc)
            
            if result.inserted_id:
                Log.info(f"{log_tag} Token created (expires in {expiry_minutes} min)")
                return True, reset_token, None
            else:
                Log.error(f"{log_tag} Failed to create token")
                return False, None, "Failed to create reset token"
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False, None, str(e)
    
    @staticmethod
    def validate_token(token):
        """
        Validate a reset token.
        
        Args:
            token: Reset token string
            
        Returns:
            Dict with token data or None if invalid
        """
        log_tag = f"[PasswordResetToken][validate_token]"
        
        try:
            collection = db.get_collection(PasswordResetToken.collection_name)
            
            token_doc = collection.find_one({
                "token": token,
                "used": False,
                "expires_at": {"$gt": datetime.utcnow()}
            })
            
            if token_doc:
                # Convert ObjectId to string
                token_doc["_id"] = str(token_doc["_id"])
                token_doc["user_id"] = str(token_doc["user_id"])
                Log.info(f"{log_tag} Valid token found")
                return token_doc
            else:
                Log.warning(f"{log_tag} Invalid or expired token")
                return None
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def mark_token_used(token):
        """
        Mark a token as used.
        
        Args:
            token: Reset token string
            
        Returns:
            Bool - success status
        """
        log_tag = f"[PasswordResetToken][mark_token_used]"
        
        try:
            collection = db.get_collection(PasswordResetToken.collection_name)
            
            result = collection.update_one(
                {"token": token},
                {
                    "$set": {
                        "used": True,
                        "used_at": datetime.utcnow()
                    }
                }
            )
            
            if result.modified_count > 0:
                Log.info(f"{log_tag} Token marked as used")
                return True
            else:
                Log.warning(f"{log_tag} Token not found or already used")
                return False
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False
    
    @staticmethod
    def create_indexes():
        """Create database indexes."""
        try:
            collection = db.get_collection(PasswordResetToken.collection_name)
            
            # Index for token lookup
            collection.create_index([("token", 1)])
            
            # Auto-delete expired tokens after 10 minutes
            collection.create_index([("expires_at", 1)], expireAfterSeconds=600)
            
            # Index for email lookup
            collection.create_index([("email", 1), ("created_at", -1)])
            
            Log.info("[PasswordResetToken] Indexes created successfully")
            return True
            
        except Exception as e:
            Log.error(f"[PasswordResetToken] Error creating indexes: {str(e)}")
            return False