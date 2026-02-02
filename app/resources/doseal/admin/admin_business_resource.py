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
from ....schemas.social.change_password_schema import ChangePasswordSchema

from ....utils.helpers import generate_tokens
from ....models.business_model import Client, Token
from ....models.user_model import User
from ....models.admin.super_superadmin_model import Role


from ....utils.logger import Log # import logging
from ....utils.generators import generate_client_id, generate_client_secret
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.json_response import prepared_response
from ....utils.redis import (
    set_redis_with_expiry, set_redis
)
from ....constants.service_code import (
    HTTP_STATUS_CODES, SYSTEM_USERS, BUSINESS_FIELDS
)
from tasks import (
    send_user_registration_email, 
    send_new_contact_sale_email
)
from ....utils.generators import (
    generate_reset_token,
    generate_confirm_email_token
)

from ....utils.helpers import (
    validate_and_format_phone_number, create_token_response_admin, 
    generate_tokens, safe_decrypt
)
from ....utils.file_upload import upload_file

from ....utils.rate_limits import (
    login_ip_limiter, login_user_limiter,
    register_rate_limiter, logout_rate_limiter,
    profile_retrieval_limiter 
)
from ....utils.helpers import resolve_target_business_id_from_payload
from ....services.seeders.social_role_seeder import SocialRoleSeeder

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


#-------------------------------------------------------
# REGISTER
#-------------------------------------------------------
@blp_business_auth.route("/auth/register", methods=["POST"])
class RegisterBusinessResource(MethodView):
    
    @register_rate_limiter("registration")
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
        
        account_type = SYSTEM_USERS["BUSINESS_OWNER"]
        
        # Check if x-app-ky header is present and valid
        app_key = request.headers.get('x-app-key')
        server_app_key = os.getenv("X_APP_KEY")
        
        if app_key != server_app_key:
            Log.info(f"{log_tag} invalid x-app-key headers")
            response = {
                "success": False,
                "status_code": HTTP_STATUS_CODES["UNAUTHORIZED"],
                "message": "Unauthorized."
            }
            return jsonify(response), HTTP_STATUS_CODES["UNAUTHORIZED"]

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
        user_data["account_type"] = account_type
        
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
                        
                        #Seed roles for business
                        try:
                            SocialRoleSeeder.seed_defaults(
                                business_id=str(business_id),
                                admin_user__id=str(user_client_id) if isinstance(user_client_id, str) else str(user_client_id),
                                admin_user_id=str(user_data.get("user_id") or ""),
                                admin_email=str(user_data.get("email") or ""),
                                admin_name=str(user_data.get("fullname") or "Admin"),
                            )
                        except Exception as e:
                            Log.info(f"{log_tag} default social roles seeding failed: {e}")
                            
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

#-------------------------------------------------------
# LOGIN
#-------------------------------------------------------
@blp_business_auth.route("/auth/login", methods=["POST"])
class LoginBusinessResource(MethodView):
    @login_ip_limiter("login")
    @login_user_limiter("login")
    @blp_business_auth.arguments(LoginSchema, location="form")
    @blp_business_auth.response(200, LoginSchema)
    @blp_business_auth.doc(
        summary="Login to an existing business account",
        description="This endpoint allows a business to log in using their email and password. A valid email and password are required. On successful login, an access token is returned for subsequent authorized requests.",
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": LoginSchema,  # Assuming you have a LoginSchema to validate the input data
                    "example": {
                        "email": "johndoe@example.com",
                        "password": "SecurePass123"
                    }
                }
            }
        },
        responses={
            200: {
                "description": "Login successful, returns an access token",
                "content": {
                    "application/json": {
                        "example": {
                            "access_token": "your_access_token_here",
                            "token_type": "Bearer",
                            "expires_in": 86400  # The token expiration time in seconds (1 day)
                        }
                    }
                }
            },
            400: {
                "description": "Invalid login data",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Invalid email or password"
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
                            "message": "Invalid authentication credentials"
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
    def post(self, user_data):
        client_ip = request.remote_addr
        log_tag = '[admin_business_resource.py][LoginBusinessResource][post]'
        Log.info(f"{log_tag} [{client_ip}][{user_data['email']}] initiating loging request")
        
        client_ip = request.remote_addr
    
        # Check if x-app-ky header is present and valid
        app_key = request.headers.get('x-app-key')
        server_app_key = os.getenv("X_APP_KEY")
        
        if app_key != server_app_key:
            Log.info(f"[internal_controller.py][get_countries][{client_ip}] invalid x-app-ky header")
            response = {
                "success": False,
                "status_code": HTTP_STATUS_CODES["UNAUTHORIZED"],
                "message": "Unauthorized request."
            }
            return jsonify(response), HTTP_STATUS_CODES["UNAUTHORIZED"]
    
        # Check if the user exists based on email
        user = User.get_user_by_email(user_data["email"])
        if user is None:
           Log.info(f"{log_tag} [{client_ip}][{user_data['email']}]: login email does not exist")
           return prepared_response(
                False,
                "UNAUTHORIZED",
                "Invalid email or password",
            )
           
        
        fullname = decrypt_data(user["fullname"])
        
        # Check if the user's email is not verified
        if User.email_verification_needed(user_data["email"]):
            Log.info(f"{log_tag} [{client_ip}][{user_data['email']}]: email needs verification")
            try:
                base_url = os.getenv("BACK_END_BASE_URL")
                token = secrets.token_urlsafe(32) # Generates a 32-byte URL-safe token 
                reset_url = generate_confirm_email_token(base_url, token)
                
                update_code = User.update_auth_code(user_data["email"], token)
    
                if update_code:
                    Log.info(f"{log_tag} [post]\t reset_url: {reset_url}")
                    send_user_registration_email(user_data["email"], fullname, reset_url)
            except Exception as e:
                Log.info(f"{log_tag} \t An error occurred sending emails: {e}")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["UNAUTHORIZED"],
                "message": "Email needs verification.",
                "hint": "Verification email has been sent to user"
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]


        # Check if the user's credentials are not correct
        if not User.verify_password(user_data["email"], user_data["password"]):
            Log.info(f"{log_tag} [{client_ip}][{user_data['email']}]: email and password combination failed")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["UNAUTHORIZED"],
                "message": "Invalid email or password",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            
        Log.info(f"{log_tag} [{client_ip}][{user_data['email']}]: login info matched")
        
        client_id = decrypt_data(user["client_id"])
        
        business = Business.get_business_by_client_id(client_id)
        if not business: 
            abort(401, message="Your access has been revoked. Contact your administrator")
            
        # Log.info(f"business: {business}")
        
        account_type = business.get("account_type")
        
        decrypted_data = decrypt_data(account_type)

        # when user was not found
        if user is None:
            Log.info(f"{log_tag}[{client_ip}] user not found.") 
            return prepared_response(False, "NOT_FOUND", f"User not found.")
        
        # proceed to create token when user payload was created
        return create_token_response_admin(
            user=user,
            account_type=decrypted_data,
            client_ip=client_ip, 
            log_tag=log_tag, 
        )
  
#-------------------------------------------------------
# CHANGE PASSWORD
#------------------------------------------------------- 
@blp_business_auth.route("/change-password", methods=["POST"])
class ChangePasswordResource(MethodView):

    @profile_retrieval_limiter("change_password")
    @token_required
    @blp_business_auth.arguments(ChangePasswordSchema, location="form")
    @blp_business_auth.doc(
        summary="Change password for the current authenticated user",
        description="""
            Change the password of the currently authenticated user.

            **How it works**
            - The user must provide `current_password` and `new_password`.
            - The API verifies `current_password` against the stored bcrypt hash.
            - If valid, the API hashes `new_password` and updates the user record.

            **Notes**
            - Requires a valid Bearer token.
            - Password update is enforced within the resolved business scope.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": ChangePasswordSchema,
                    "example": {
                        "current_password": "OldPassword123",
                        "new_password": "NewStrongPassword123"
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Password changed successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Password changed successfully."
                        }
                    }
                }
            },
            400: {
                "description": "Bad request / validation error",
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
                "description": "Unauthorized / wrong current password",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Current password is incorrect."
                        }
                    }
                }
            },
            404: {
                "description": "User not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "User not found"
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
        },
        security=[{"Bearer": []}],
    )
    def post(self, payload):
        client_ip = request.remote_addr
        log_tag = "[admin_business_resource.py][ChangePasswordResource][post]"

        try:
            body = request.get_json(silent=True) or {}

            auth_user = g.get("current_user", {}) or {}
            auth_user__id = str(auth_user.get("_id") or "")
            auth_business_id = str(auth_user.get("business_id") or "")
            account_type = auth_user.get("account_type")

            if not auth_user__id or not auth_business_id:
                Log.info(f"{log_tag} [{client_ip}] unauthorized: missing auth ids")
                return prepared_response(False, "UNAUTHORIZED", "Unauthorized.")

            target_business_id = resolve_target_business_id_from_payload(body)

            Log.info(
                f"{log_tag} [{client_ip}] change password request "
                f"user_id={auth_user__id} business_id={target_business_id} account_type={account_type}"
            )

            # 1) Load user in target business scope
            user_doc = User.get_by_id(auth_user__id, target_business_id)
            if not user_doc:
                Log.info(f"{log_tag} [{client_ip}] user not found")
                return prepared_response(False, "NOT_FOUND", "User not found.")

            current_password = payload.get("current_password")
            new_password = payload.get("new_password")

            if not current_password or not new_password:
                return prepared_response(False, "BAD_REQUEST", "current_password and new_password are required.")

            if current_password == new_password:
                return prepared_response(False, "BAD_REQUEST", "New password must be different from current password.")

            # 2) Verify current password
            if not User.verify_change_password(user_doc, current_password):
                Log.info(f"{log_tag} [{client_ip}] wrong current password for user_id={auth_user__id}")
                return prepared_response(False, "UNAUTHORIZED", "Current password is incorrect.")

            # 3) Update password
            updated = User.update_password(
                user_id=auth_user__id,
                business_id=target_business_id,
                new_password=new_password,
            )

            if not updated:
                Log.info(f"{log_tag} [{client_ip}] password update failed for user_id={auth_user__id}")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to change password.")

            Log.info(f"{log_tag} [{client_ip}] password changed successfully for user_id={auth_user__id}")
            return prepared_response(True, "OK", "Password changed successfully.")

        except PyMongoError as e:
            Log.info(f"{log_tag} [{client_ip}] PyMongoError: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "An unexpected database error occurred.", errors=str(e))
        except Exception as e:
            Log.info(f"{log_tag} [{client_ip}] Unexpected error: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "An unexpected error occurred.", errors=str(e))
           
#-------------------------------------------------------
# ME
#-------------------------------------------------------     
@blp_business_auth.route("/me", methods=["GET"])
class CurrentUserResource(MethodView):
    
    @profile_retrieval_limiter("me")
    @token_required
    @blp_business_auth.response(200)
    @blp_business_auth.doc(
        summary="Get current authenticated user",
        description="This endpoint returns the profile information of the currently authenticated user based on their JWT token.",
        responses={
            200: {
                "description": "Successfully retrieved user profile",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": {
                                "id": "user_id_here",
                                "email": "johndoe@example.com",
                                "fullname": "John Doe",
                                "client_id": "client_id_here",
                                "account_type": "admin",
                                "email_verified": True
                            }
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized - Invalid or missing token",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Missing or invalid authentication token"
                        }
                    }
                }
            },
            404: {
                "description": "User not found",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 404,
                            "message": "User not found"
                        }
                    }
                }
            }
        }
    )
    def get(self):
        client_ip = request.remote_addr
        log_tag = '[admin_business_resource.py][CurrentUserResource][get]'
        
        body = request.get_json(silent=True) or {}
        
        user = g.get("current_user", {}) or {}
        target_business_id = resolve_target_business_id_from_payload(body)

        auth_user__id = str(user.get("_id") or "")
        account_type = user.get("account_type")
        
        Log.info(f"{log_tag} [{client_ip}] fetching user profile for user_id: {auth_user__id}")
        
        # Get user from database
        user = User.get_by_id(auth_user__id, target_business_id)
        
        if user is None:
            Log.info(f"{log_tag} [{client_ip}] user not found")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                "message": "User not found"
            }), HTTP_STATUS_CODES["NOT_FOUND"]
        
        # Decrypt sensitive fields
        client_id = decrypt_data(user["client_id"])
        
        # Get business info
        business = Business.get_business_by_client_id(client_id)
        
        decrypte_full_name = decrypt_data(user.get("fullname"))
        
        business_info = dict()
    
        business_info = {key: safe_decrypt(business.get(key)) for key in BUSINESS_FIELDS}
        
        # Token is for 24 hours
        response = {
            "fullname": decrypte_full_name,
            "admin_id": str(user.get("_id")),
            "business_id": target_business_id,
            "profile": business_info
        }
    
        
        try:
            role_id = user.get("role") if user.get("role") else None
            
            role = None
            
            if role_id is not None:
                # role =  Role.get_by_id(role_id=role_id)
                role = Role.get_by_id(role_id=role_id, business_id=target_business_id, is_logging_in=True)
                
            if role is not None:
                # retreive the permissions for the user
                permissions = role.get("permissions")
                

        except Exception as e:
            Log.info(f"{log_tag} [admin_business_resource.py][{client_ip}]: error retreiving permissions for user: {e}")
            
        
        response["account_type"] = account_type

        if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["BUSINESS_OWNER"]) :
            response["permissions"] = {}
        else:
            response["permissions"] = permissions
            
        return jsonify(response), HTTP_STATUS_CODES["OK"]
        
#-------------------------------------------------------
# LOGOUT
#-------------------------------------------------------  
@blp_business_auth.route("/logout", methods=["POST"])
class LogoutResource(MethodView):
    @logout_rate_limiter("logout")
    @token_required
    @blp_business_auth.doc(
        summary="Logout from account",
        description="This endpoint allows a user to logout by invalidating their access token. A valid access token must be provided in the Authorization header.",
        security=[{"BearerAuth": []}],
        responses={
            200: {
                "description": "Logout successful",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Successfully logged out."
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized - Invalid or missing token",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Invalid or expired token."
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
                            "message": "An unexpected error occurred."
                        }
                    }
                }
            }
        }
    )
    def post(self):
        client_ip = request.remote_addr
        auth_header = request.headers.get('Authorization')
        log_tag = '[admin_business_resource.py][LogoutResource][post]'

        if not auth_header or not auth_header.startswith('Bearer '):
            return prepared_response(False, "UNAUTHORIZED", f"Authorization token is missing or invalid.")
        
        access_token = auth_header.split(' ')[1]
        
        try:
            # Delete or invalidate the token from database
            token_deleted = Token.delete_token(access_token)

            if token_deleted:
                Log.info(f"{log_tag} [{client_ip}]: token invalidated successfully.")
                return prepared_response(False, "OK", f"Successfully logged out.")
                
            else:
                Log.info(f"{log_tag}[{client_ip}]: token invalidation failed.")
                return prepared_response(False, "UNAUTHORIZED", f"Invalid or expired token.")
                
        except Exception as e:
            Log.error(f"{log_tag}[{client_ip}]: logout error: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")
         
