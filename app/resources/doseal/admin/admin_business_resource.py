import bcrypt
import jwt
import os
import time
import secrets

from functools import wraps
from redis import Redis
from functools import wraps
from flask import current_app, g
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import jsonify, request
from pymongo.errors import PyMongoError
from marshmallow import ValidationError
from rq import Queue

from datetime import datetime, timedelta
# from app import queue
from ....models.business_model import Business
from ....schemas.business_schema import BusinessSchema
from ....schemas.business_schema import OAuthCredentialsSchema
from ....schemas.login_schema import LoginSchema
from ....utils.helpers import generate_tokens
from ....models.business_model import Client, Token
from ....models.user_model import User
from ....models.superadmin_model import Role
from ....models.admin.super_superadmin_model import Role as AdminRole

from ....utils.logger import Log # import logging
from ....utils.generators import generate_client_id, generate_client_secret
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.json_response import prepared_response
from ....utils.redis import (
    set_redis_with_expiry, set_redis
)
from ....constants.service_code import (
    HTTP_STATUS_CODES, SYSTEM_USERS
)
from tasks import (
    send_user_registration_email, 
    send_new_contact_sale_email
)
from ....utils.generators import (
    generate_reset_token,
    generate_confirm_email_token
)
from ....utils.rate_limits import (
    register_rate_limiter,
    logout_rate_limiter
)
from ....utils.file_upload import upload_file



SECRET_KEY = os.getenv("SECRET_KEY") 

REDIS_HOST = os.getenv("REDIS_HOST")
connection = Redis(host=REDIS_HOST, port=6379)
queue = Queue("emails", connection=connection)

blp_business_auth = Blueprint("Business Auth", __name__, url_prefix="/v1/auth", description="Authentication Management")

blp_admin_preauth = Blueprint("Admin Pre Auth", __name__, url_prefix="/v1/auth", description="Admin Pre Auth Management")


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # Get the Authorization header
        auth_header = request.headers.get('Authorization')
        
        if not auth_header or not auth_header.startswith("Bearer "):
            abort(401, message="Authentication Required")

        token = auth_header.split()[1]
        user = dict()
        s_user = {}
        log_tag = f"[business_resources.py][token_required]"

        try:
            # Decode the access token
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])

            try:
                user = User.get_user_by_user__id(data.get("user_id"))
            except Exception as e:
                Log.info(f"{log_tag} error retrieving user: {str(e)}")
            
            if user is None:
                abort(401, message="Invalid access token")
                
            try:
                s_user = User.get_system_user_by__id(user.get("system_user_id"))
                if s_user:
                    user["agent_id"] = s_user.get("agent_id")
            except Exception as e:
                Log.info(f"{log_tag} system user error: {str(e)}")

            # Clean up sensitive data
            user.pop('password', None)
            user.pop('email_hashed', None)
            user.pop('client_id_hashed', None)
            user.pop('email_verified', None)
            user.pop('updated_at', None)
            user.pop('pin', None)
            
            account_type = decrypt_data(user.get("account_type"))
            # Log.info(f"{log_tag}: account_type: {account_type}" )
            
            if account_type not in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["BUSINESS_OWNER"]):
                permissions = data.get('permissions')
                user['permissions'] = permissions
                user['account_type'] = account_type
            else:
                user['account_type'] = account_type

            g.current_user = user

        except jwt.ExpiredSignatureError:
            # Handle expired access token
            refresh_token = None
            
            # Try to get refresh token from different sources
            if request.is_json and request.json:
                refresh_token = request.json.get('refresh_token')
            elif request.form:
                refresh_token = request.form.get('refresh_token')
            elif request.headers.get('X-Refresh-Token'):
                refresh_token = request.headers.get('X-Refresh-Token')
            
            if not refresh_token:
                abort(401, message="Token expired, and no refresh token provided")
            
            try:
                # Decode and verify the refresh token
                refresh_data = jwt.decode(refresh_token, SECRET_KEY, algorithms=["HS256"])
                
                # Get user data for the new token
                user_id = refresh_data['user_id']
                
                new_access_token = jwt.encode({
                    'user_id': user_id,
                    'account_type': refresh_data.get('account_type'),  # Include account_type if needed
                    'exp': datetime.utcnow() + timedelta(minutes=15)
                }, SECRET_KEY, algorithm='HS256')

                # Update token in database
                Token.create_token(user_id, new_access_token, refresh_token, 900, 604800)
                
                # Get user data and set g.current_user
                try:
                    user = User.get_user_by_user__id(user_id)
                    if user:
                        # Clean up and set user data (same as above)
                        user.pop('password', None)
                        user.pop('email_hashed', None)
                        user.pop('client_id_hashed', None)
                        user.pop('email_verified', None)
                        user.pop('updated_at', None)
                        
                        try:
                            role = Role.get_by_id(user.get("role"))
                            if role is not None:
                                permissions = role.get('permissions')
                                user['permissions'] = permissions
                                user['account_type'] = refresh_data.get('account_type')
                        except:
                            Log.error("Failed to get role for user_id: %s")
                        
                        g.current_user = user
                        
                        # Add new token to response headers
                        response = make_response(f(*args, **kwargs))
                        response.headers['X-New-Access-Token'] = new_access_token
                        return response
                        
                except Exception as e:
                    Log.error(f"Error getting user data after token refresh: {str(e)}")
                    abort(401, message="Invalid user")

            except jwt.InvalidTokenError:
                abort(401, message="Invalid or expired refresh token")
            except Exception as e:
                Log.error(f"Error during token refresh: {str(e)}")
                abort(401, message="Token refresh failed")

        except jwt.InvalidTokenError:
            abort(401, message="Invalid access token")

        # Check if the token exists in MongoDB
        stored_token = Token.get_token(token)
        if not stored_token:
            abort(401, message="Invalid token")

        return f(*args, **kwargs)

    return decorated


@blp_business_auth.route("/auth/register", methods=["POST"])
class RegisterBusinessResource(MethodView):
    decorators = [register_rate_limiter()]
    
    @blp_business_auth.arguments(BusinessSchema, location="form")
    @blp_business_auth.response(201, BusinessSchema)
    @blp_business_auth.doc(
        summary="Add a new business entry with details",
        description="This endpoint allows business to register a new business with details like full name, email, phone number, company name, store URL, and user password. A valid authentication token is required for authorization.",
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": BusinessSchema,
                    "example": {
                        "fullname": "John Doe",
                        "email": "johndoe@example.com",
                        "phone_number": "1234567890",
                        "company_name": "Doe Enterprises",
                        "store_url": "doeenterprises",
                        "password": "SecurePass123"
                    }
                }
            }
        },
        responses={
            201: {
                "description": "Business created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Business created successfully",
                            "status_code": 200,
                            "success": True
                        }
                    }
                }
            },
            400: {
                "description": "Invalid request data",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Invalid input data"
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized request",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Invalid authentication token"
                        }
                    }
                }
            },
            500: {
                "description": "Internal Server Error",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 500,
                            "message": "An unexpected error occurred",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    def post(self, business_data):
        client_ip = request.remote_addr
        
        log_tag = f"[business_resource.py][RegisterBusinessResource][post][{client_ip}]"

        # Check if the business already exists based on email item_data["business_id"], key="name", value=item_data["name"]
        if Business.check_item_exists(key="email", value=business_data["email"]):
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["CONFLICT"],
                "message": "Business account already exists", 
            }), HTTP_STATUS_CODES["CONFLICT"]

        business_data["password"] = bcrypt.hashpw(
            business_data["password"].encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")
        
        user_data = {}
        
        user_data["fullname"] = f"{business_data.get('first_name', '')} {business_data.get('last_name', '')}".strip()
        user_data["email"] = business_data.get('email')
        user_data["phone_number"] = business_data.get('business_contact')
        user_data["password"] = business_data.get('password')
        user_data["account_type"] = business_data.get('account_type')
        
        business_data["password"] = business_data.get('password')
        
        
        # Create a new user instance
        business = Business(**business_data)

        # Try saving the business to MongoDB and handle any errors
        try:
            # send email after successful signup
            Log.info(f"{log_tag} [{business_data['business_name']}][committing assignment history")
            # committing business data to db
            
            # Record the start time
            start_time = time.time()
            
            (client_id, tenant_id, business_id, email) = business.save()
      
            # Handle logo image upload
            actual_path = None
            if 'image' in request.files:
                image = request.files['image']
                try:
                    # Use the upload function to upload the logo
                    image_path, actual_path = upload_file(image, business_id)
                    result = Business.update_business_image(user_data['email'], image_path, actual_path)
                    if result:
                        Log.info(f"{log_tag} image upload success: {result}")
                    else:
                        Log.info(f"{log_tag} image upload failed: {result}")
                except ValueError as e:
                    Log.info(f"{log_tag} image upload error: {e}")
            
            
            # Record the end time
            end_time = time.time()
            
            # Calculate the duration
            duration = end_time - start_time
            
            # Log the response and time taken
            Log.info(f"{log_tag} commit business completed in {duration:.2f} seconds")
            
            if client_id:
                
                user_data["tenant_id"] = tenant_id
                user_data["client_id"] = client_id
                user_data["business_id"] = business_id
     
                try:
                    Log.info(f"{log_tag}[committing business information")
                    # committing user data to db
                    user = User(**user_data)
                    user_client_id = user.save()
                    
                    if user_client_id:
                        #update business with user_id
                        try:
                            data = {
                                "user_id": user_client_id
                            }
                            update_business = Business.update_business_with_user_id(business_id, **data)
                            Log.info(f"{log_tag}\t respone updating business with user_id")
                        except Exception as e:
                            Log.info(f"{log_tag}\t error updating business with user_id: {e}")
                        
                         #create a client secret
                        client_secret = generate_client_secret()
                        Client.create_client(client_id, client_secret)
                        
                        try:
                            return_url= business_data["return_url"]
                            token = secrets.token_urlsafe(32) # Generates a 32-byte URL-safe token 
                            reset_url = generate_confirm_email_token(return_url, token)
            
                            update_code = User.update_auth_code(business_data["email"], token)
                            
                            # for automated test
                            email_ = business_data["email"]
                            trancated_email = email_[:-14]
                            redisKey = f"automated_test_email_confirmation_link_{trancated_email}"
                            set_redis(redisKey, reset_url)
                            # for automated test
                            
                
                            if update_code:
                                Log.info(f"{log_tag}\t reset_url: {reset_url}")
                                send_user_registration_email(business_data["email"], user_data['fullname'], reset_url)
                        except Exception as e:
                            Log.info(f"{log_tag}\t An error occurred sending emails: {e}")
                        
                        try:
                            # send email to admins about registration
                            send_new_contact_sale_email(
                                "s.daniels@myzeeapy.com", "Samuel Daniels", 
                                user_data['email'],
                                user_data['fullname'],
                                user_data['phone_number'],
                                business_data['business_name'],
                                business_data['store_url']
                                ) 
                            pass
                        except Exception as e:
                            Log.info(f"{log_tag} error sending emails: { str(e)}")
                        
                        return jsonify({
                            "success": True,
                            "status_code": HTTP_STATUS_CODES["OK"],
                            "message": "Business created successfully.", 
                        }), HTTP_STATUS_CODES["OK"]
                        
                    
                except Exception as e:
                    Log.info(f"{log_tag} An error occurred while creating user: {e}")
                    # Create a new user instance
                    return jsonify({
                        "success": False,
                        "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                        "message": "An unexpected error occurred",
                        "error": str(e)
                    }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                
        except PyMongoError as e:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
        except Exception as e:
             return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "An unexpected error occurred",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

