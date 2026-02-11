
# app/resources/admin/admin_business_resource.py

from __future__ import annotations

import bcrypt, jwt, os, time, secrets, json
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
from ....schemas.login_schema import (
    LoginInitiateSchema,
    LoginExecuteSchema,
    LoginExecuteResponseSchema,
    LoginInitiateResponseSchema
)
from ....schemas.social.change_password_schema import ChangePasswordSchema
from ....schemas.social.email_verification_schema import BusinessEmailVerificationSchema

from ....utils.helpers import generate_tokens
from ....models.business_model import Client, Token
from ....models.user_model import User
from ....models.admin.super_superadmin_model import Role
from ....models.notifications.notification_settings import NotificationSettings


from ....utils.logger import Log # import logging
from ....utils.generators import generate_client_id, generate_client_secret
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.json_response import prepared_response
from ....utils.calculation_engine import hash_transaction
from ....utils.redis import (
    set_redis_with_expiry, set_redis, get_redis, remove_redis
)
from ....utils.generators import generate_otp

from ....constants.service_code import (
    HTTP_STATUS_CODES, SYSTEM_USERS, BUSINESS_FIELDS
)

from ....services.email_service import (
    send_user_registration_email,
    send_new_contact_sale_email,
    send_password_changed_email,
    send_otp_email
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
from ....utils.generators import generate_registration_verification_token
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
        
        account_status = [
                {
                    "account_created": {
                        "created_at": str(datetime.utcnow()),
                        "status": True,
                    },
                },
                {
                    "business_email_verified": {
                        "status": False,
                    }
                },
                {
                    "subscribed_to_package": {
                        "status": False,
                    }
                }
            ]
                            
        business_data["account_status"] = account_status
        
        
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
                        
                        # seed notifications
                        try:
                            NotificationSettings.seed_for_user(
                                business_id=str(business_id),
                                user__id=str(user_client_id),
                            )
                        except Exception as e:
                            Log.info(f"{log_tag} Error seeding notifictions: {e}")
                        
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
                            
                            if update_code:
                                Log.info(f"{log_tag}\t reset_url: {reset_url}")
                                try:
                                    result = send_user_registration_email(business_data["email"], user_data["fullname"], reset_url)
                                    Log.info(f"Email sent result={result}")
                                except Exception as e:
                                    Log.error(f"Email sending failed: {e}")
                                    raise
                        except Exception as e:
                            Log.info(f"{log_tag}\t An error occurred sending emails: {e}")
                        
                        try:
                            send_new_contact_sale_email(
                                to_admins=["opokudaniels@yahoo.com", "dosealltd@gmail.com"],
                                admin_name="Samuel Daniels",
                                requester_email=user_data["email"],
                                requester_fullname=user_data["fullname"],
                                requester_phone_number=user_data["phone_number"],
                                company_name=business_data["business_name"],
                                cc_admins=["samuel@doseal.org"],
                            )
                        except Exception as e:
                            Log.error(f"{log_tag} error sending admin emails: {e}")
                        
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
# LOGIN INITIATE
#-------------------------------------------------------
@blp_business_auth.route("/auth/login/initiate", methods=["POST"])
class LoginBusinessInitiateResource(MethodView):
    @login_ip_limiter("login")
    @login_user_limiter("login")
    @blp_business_auth.arguments(LoginInitiateSchema, location="form")
    @blp_business_auth.response(200, LoginInitiateResponseSchema)
    @blp_business_auth.doc(
        summary="Login (Step 1): Initiate OTP",
        description=(
            "Step 1 of login.\n\n"
            "Validates email + password, then sends a 6-digit OTP to the user's email.\n"
            "OTP expires in 5 minutes.\n\n"
            "Step 2: Call `/auth/login/execute` with email + otp."
        ),
        parameters=[
            {
                "in": "header",
                "name": "x-app-key",
                "required": True,
                "schema": {"type": "string"},
                "description": "Application key required to access this endpoint.",
            },
            {
                "in": "header",
                "name": "x-app-secret",
                "required": True,
                "schema": {"type": "string"},
                "description": "Application secret required to access this endpoint.",
            }
        ],
        requestBody={
            "required": True,
            "content": {
                "application/x-www-form-urlencoded": {
                    "schema": LoginInitiateSchema,
                    "example": {
                        "email": "johndoe@example.com",
                        "password": "SecurePass123"
                    }
                }
            }
        },
        responses={
            200: {
                "description": "OTP sent to email",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "OTP has been sent to email",
                            "message_to_show": "We sent an OTP to your email address. Please provide it to proceed."
                        }
                    }
                },
            },
            401: {
                "description": "Unauthorized (invalid app key OR invalid email/password OR revoked access)",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Invalid email or password"
                        }
                    }
                },
            },
            429: {
                "description": "Rate limited (too many attempts)",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 429,
                            "message": "Too many requests. Please try again later."
                        }
                    }
                },
            },
            500: {
                "description": "Internal server error",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 500,
                            "message": "Internal error"
                        }
                    }
                },
            },
        },
    )
    
    def post(self, user_data):
        client_ip = request.remote_addr
        log_tag = '[admin_business_resource.py][LoginBusinessInitiateResource][post]'
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
        
        email = user_data.get("email")
    
        # Check if the user exists based on email
        user = User.get_user_by_email(email)
        if user is None:
           Log.info(f"{log_tag} [{client_ip}][{email}]: login email does not exist")
           return prepared_response(
                False,
                "UNAUTHORIZED",
                "Invalid email or password",
            )

        # Check if the user's credentials are not correct
        if not User.verify_password(email, user_data["password"]):
            Log.info(f"{log_tag} [{client_ip}][{email}]: email and password combination failed")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["UNAUTHORIZED"],
                "message": "Invalid email or password",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]
            
            
        Log.info(f"{log_tag} [{client_ip}][{email}]: login info matched")
        
        business = Business.get_business_by_email(email)
        if not business: 
            abort(401, message="Your access has been revoked. Contact your administrator")
            
        
        try:
            test_email = os.getenv("EMAIL_FOR_TESTING")
            
            app_name = os.getenv("APP_NAME", "Schedulefy")
            
            redisKey = f'login_otp_token_{email}'
            
            pin = None
            
            # needed for automated testing
            if (email == test_email):
                testing_otp = os.getenv("AUTOMATED_TEST_OTP", "200300")
                pin = testing_otp
            else:
                pin = generate_otp()
            
            fullname = decrypt_data(business.get("first_name")) + " " +decrypt_data(business.get("last_name"))
            
            message = f'Your {app_name} security code is {pin} and expires in 5 minutes. If you did not initiate this, DO NOT APPROVE IT.'
            
            set_redis_with_expiry(redisKey, 300, pin)
            
            try:
                result = send_otp_email(
                    email=email,
                    otp=pin,
                    message=message,
                    fullname=fullname,
                    expiry_minutes=5,
                )
                Log.info(f"Login Email sent result={result}")
            except Exception as e:
                Log.error(f"Login Email sending failed: {e}")
                raise
            
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "message": "OTP has been sent to email",
                "message_to_show": "We sent an OTP to your email address. Please provide it to proceed.",
            }), HTTP_STATUS_CODES["OK"]
        except Exception as e:
            Log.error(f"{log_tag} Error occurred: {str(e)}")
            
        
        
        
        
        
        # # when user was not found
        # if user is None:
        #     Log.info(f"{log_tag}[{client_ip}] user not found.") 
        #     return prepared_response(False, "NOT_FOUND", f"User not found.")
        
        # # proceed to create token when user payload was created
        # return create_token_response_admin(
        #     user=user,
        #     account_type=decrypted_data,
        #     client_ip=client_ip, 
        #     log_tag=log_tag, 
        # )
  
  
#-------------------------------------------------------
# LOGIN EXECUTE
#-------------------------------------------------------
@blp_business_auth.route("/auth/login/execute", methods=["POST"])
class LoginBusinessExecuteResource(MethodView):
    # @login_ip_limiter("login")
    # @login_user_limiter("login")
    @blp_business_auth.arguments(LoginExecuteSchema, location="form")
    @blp_business_auth.response(200, LoginExecuteResponseSchema)
    @blp_business_auth.doc(
        summary="Login (Step 2): Verify OTP and Issue Token",
        description=(
            "Step 2 of login.\n\n"
            "Verifies the OTP sent in Step 1 and returns an access token.\n"
            "OTP expires in 5 minutes.\n\n"
            "Requires `x-app-key` header."
        ),
        parameters=[
            {
                "in": "header",
                "name": "x-app-key",
                "required": True,
                "schema": {"type": "string"},
                "description": "Application key required to access this endpoint.",
            },
            {
                "in": "header",
                "name": "x-app-secret",
                "required": True,
                "schema": {"type": "string"},
                "description": "Application secret required to access this endpoint.",
            }
        ],
        requestBody={
            "required": True,
            "content": {
                "application/x-www-form-urlencoded": {
                    "schema": LoginExecuteSchema,
                    "example": {
                        "email": "johndoe@example.com",
                        "otp": "200300"
                    }
                }
            }
        },
        responses={
            200: {
                "description": "OTP verified, access token issued",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Login successful",
                            "access_token": "your_access_token_here",
                            "token_type": "Bearer",
                            "expires_in": 86400
                        }
                    }
                },
            },
            401: {
                "description": "Unauthorized (invalid app key OR invalid/expired OTP OR revoked access)",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "The OTP has expired"
                        }
                    }
                },
            },
            429: {
                "description": "Rate limited (too many attempts)",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 429,
                            "message": "Too many requests. Please try again later."
                        }
                    }
                },
            },
            500: {
                "description": "Internal server error",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 500,
                            "message": "Internal error"
                        }
                    }
                },
            },
        },
    )
    def post(self, user_data):
        client_ip = request.remote_addr
        log_tag = '[admin_business_resource.py][LoginBusinessExecuteResource][post]'
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
        
        email = user_data.get("email")
    
        # Check if the user exists based on email
        user = User.get_user_by_email(email)
        if user is None:
           Log.info(f"{log_tag} [{client_ip}][{email}]: login email does not exist")
           return prepared_response(
                False,
                "UNAUTHORIZED",
                "Invalid email or password",
            )
        try:
            
            business = Business.get_business_by_email(email)
            if not business: 
                abort(401, message="Your access has been revoked. Contact your administrator")
                
            account_type = business.get("account_type")

            # when user was not found
            if user is None:
                Log.info(f"{log_tag}[{client_ip}] user not found.") 
                return prepared_response(False, "NOT_FOUND", f"User not found.")
            
            
            otp = user_data.get("otp")
            
            redisKey = f'login_otp_token_{email}'
            
            token_byte_string = get_redis(redisKey)
            
            if not token_byte_string:
                Log.info(f"{log_tag} The OTP has expired")
                return prepared_response(False, "UNAUTHORIZED", f"The OTP has expired")
            
            # Decode the byte string and convert to integer
            token = token_byte_string.decode('utf-8')
            
            # Check if OTP is valid else send an invalid OTP response
            if str(otp) != str(token):
                Log.info(f"{log_tag}[otp: {otp}][token: {token}] verification failed" )
                return prepared_response(False, "UNAUTHORIZED", f"The OTP is not valid")
            
            # remove otp from redis
            remove_redis(redisKey)
            Log.info(f"{log_tag} verification otp applied")
            
            # proceed to create token when user payload was created
            return create_token_response_admin(
                user=user,
                account_type=account_type,
                client_ip=client_ip, 
                log_tag=log_tag, 
            )
        except Exception as e:
            Log.error(f"{log_tag} An error occurred: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An error occurred: {str(e)}")
  


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
            
            email = decrypt_data(auth_user.get("email"))
            fullname = decrypt_data(auth_user.get("fullname"))

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
            
            #send email about password change
            try:
                update_passsword = send_password_changed_email(
                    email=email,
                    fullname=fullname,
                    changed_at=datetime.now(),
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get("User-Agent"),
                )
                Log.error(f"{log_tag} change password email update: {update_passsword}")
            except Exception as e:
                Log.error(f"{log_tag} error sending change password emails: {e}")

            Log.info(f"{log_tag} [{client_ip}] password changed successfully for user_id={auth_user__id}")
            return prepared_response(True, "OK", "Password changed successfully.")

        except PyMongoError as e:
            Log.info(f"{log_tag} [{client_ip}] PyMongoError: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "An unexpected database error occurred.", errors=str(e))
        except Exception as e:
            Log.info(f"{log_tag} [{client_ip}] Unexpected error: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "An unexpected error occurred.", errors=str(e))
      

# -----------------------INITIATE EMAIL VERIFICAITON-----------------------------------------
@blp_business_auth.route("/initiate-email-verification", methods=["POST"])
class BusinessRegistrationInitiateEmailVerificationResource(MethodView):
    # PATCH Agent (Verify agent OTP)
    @profile_retrieval_limiter("change_password")
    @token_required
    @blp_business_auth.arguments(BusinessEmailVerificationSchema, location="form")
    @blp_business_auth.response(200, BusinessEmailVerificationSchema)
    @blp_business_auth.doc(
        summary="Verify Business Email",
        description="""
            This endpoint allows you to verify the business email for an business during registration. 
            The request requires an `Authorization` header with a Bearer token.
            - **POST**: Verify the business email by providing `agent_id` and `return_url`.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": BusinessEmailVerificationSchema,  # Schema for verifying business email
                    "example": {
                        "business_id": "67ff9e32272817d5812ab2fc",  # Example agent ID (ObjectId)
                        "return_url": "http://localhost:7007/redirect"  # Example return URL
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Email has been successfully sent to the agent's business email",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Email has been sent to agent business email successfully.",
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
        },
        security=[{"Bearer": []}],  # Bearer token authentication is required
    )
    def post(self, item_data):
        """Handle the POST request to verify OTP."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        
        log_tag = f'[admin_business_resource.py][BusinessRegistrationInitiateEmailVerificationResource][post][{client_ip}][{business_id}]'
        
        # Assign user_id and business_id from current user
        item_data["business_id"] = business_id
        return_url = item_data.get("return_url")
        
        # check if business exist before proceeding to update the information 
        try:
            Log.info(f"{log_tag} checking if business exist")
            business = Business.get_business_by_id(business_id)
            if not business:
                Log.info(f"{log_tag} business_id with ID: {business_id} does not exist")
                
                return prepared_response(False, "NOT_FOUND", f"Business with ID: {business_id} does not exist")
            
            
            # check if email is already verified and disallow re-verification
            account_status = decrypt_data(business.get("account_status"))
            
            # Get the status for 'business_email_verified'
            business_email_verified_status = next((item["business_email_verified"]["status"] for item in account_status if "business_email_verified" in item), None)
            
            #Check if business email has already been verified
            if business_email_verified_status:
                # stop the action of re-verification if status is already True
                Log.info(f"{log_tag} Business email has already been verified.")
                return prepared_response(False, "BAD_REQUEST", f" Business email has already been verified")
            

            fullname = business.get("fullname")
            email = business.get("email")
            return_url = decrypt_data(business.get("return_url"))
            
            try:
                token = secrets.token_urlsafe(32) # Generates a 32-byte URL-safe token 
                reset_url = generate_confirm_email_token(return_url, token)

                update_code = User.update_auth_code(email, token)
                
                if update_code:
                    Log.info(f"{log_tag}\t reset_url: {reset_url}")
                    send_user_registration_email(email, fullname, reset_url)
                    
                    Log.info(f"{log_tag} Email resent")
                    return prepared_response(False, "OK", f" Email resent")
            except Exception as e:
                Log.info(f"{log_tag}\t An error occurred sending emails: {e}")
            
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
     
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
        
        email = decrypt_data(user.get("email"))
        
        if user is None:
            Log.info(f"{log_tag} [{client_ip}] user not found")
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                "message": "User not found"
            }), HTTP_STATUS_CODES["NOT_FOUND"]
        
        # Get business info
        business = Business.get_business_by_email(email)
        
        decrypte_full_name = decrypt_data(user.get("fullname"))
        
        business_info = dict()
    
        business_info = {key: safe_decrypt(business.get(key)) for key in BUSINESS_FIELDS}
        
        # Token is for 24 hours
        response = {
            "fullname": decrypte_full_name,
            "admin_id": str(user.get("_id")),
            "business_id": target_business_id,
            "email": business.get("email"),
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
         
