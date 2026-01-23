import bcrypt, json, jwt, os, time, secrets, ast
from datetime import datetime
from functools import wraps
from redis import Redis
from functools import wraps
from flask import current_app, g, redirect
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import jsonify, request
from pymongo.errors import PyMongoError
from marshmallow import ValidationError
from rq import Queue
from ....utils.helpers import (
    generate_tokens, create_token_response_system_user
)
from ....services.doseal.confirm_pin_service import confirm_pin
from ....utils.calculation_engine import hash_transaction

from ....utils.essentials import Essensial
from ....utils.helpers import validate_and_format_phone_number
from ....utils.helpers import generate_tokens
#helper functions
from ....utils.generators import (
    generate_temporary_password,
    generate_otp,
    generate_registration_verification_token,
    generate_return_url_with_payload,
    generate_subscriber_registration_verification_token,
    generate_secure_referral_code
)
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.file_upload import (
    upload_file, upload_file_to_bucket_unique_filename
)
from ....utils.json_response import prepared_response
from ....services.shop_api_service import ShopApiService
from tasks import (
    send_user_registration_email, 
    send_subscriber_registration_email
)
#helper functions

from ..admin.admin_business_resource import token_required
from ....utils.logger import Log # import logging
from ....utils.redis import (
    get_redis, set_redis_with_expiry, remove_redis, set_redis
)

# model
from ....models.subscriber_model import Subscriber

from ....models.business_model import Business
from ....models.user_model import User
from ....models.superadmin_model import Role
from ....utils.essentials import Essensial
from ....models.business_model import Client, Token
from ....schemas.business_schema import OAuthCredentialsSchema
from ....constants.service_code import (
    HTTP_STATUS_CODES, AUTOMATED_TEST_USERNAMES
)


#schema
from ....schemas.doseal.subscriber.subscriber_registration_schema import (
    SubscriberLoginInitSchema, SubscriberVerifyOTPSchema, SubscriberRegistrationChoosePinSchema,
    SubscriberIdQuerySchema, SubscriberRegistrationBasicKYCSchema, SubscriberRegistrationEmailSchema,
    SubscriberRegistrationVerifyEmailSchema, SubscriberRegistrationPoAUploadDocumentsSchema,
    SubscriberRegistrationUploadIDDocumentsSchema
)

blp_subscriber_registration = Blueprint("Subscriber Registration", __name__, description="Subscriber Registration Management")

@blp_subscriber_registration.route("/oauth/token", methods=["POST"])
@blp_subscriber_registration.arguments(OAuthCredentialsSchema)
@blp_subscriber_registration.arguments(OAuthCredentialsSchema, location="json")
@blp_subscriber_registration.doc(
    summary="Generate an OAuth token",
    description="This endpoint authenticates a client using `client_id` and `client_secret`. "
                "If authentication is successful, it returns a Bearer token valid for 24 hours.",
    responses={
        200: {
            "description": "Successful authentication",
            "content": {
                "application/json": {
                    "example": {
                        "access_token": "eyJhbGciOiJIUzI1...",
                        "token_type": "Bearer",
                        "expires_in": 86400
                    }
                }
            }
        },
        401: {
            "description": "Invalid credentials or access revoked",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Invalid client credentials"
                    }
                }
            }
        },
        422:{
        "description": "Validation error: Missing required fields",
            "content": {
            "application/json": {
                "example": {
                    "code": 422,
                    "errors": {
                        "json": {
                            "client_id": [
                                "Client ID is required"
                            ],
                            "client_secret": [
                                "Client secret is required"
                            ]
                        }
                    },
                    "status": "Unprocessable Entity"
                }
            }
            }
        }
    }
)
def post(self, data):
    client_ip = request.remote_addr
    
    log_tag = f'[auth_resource.py][OAuthTokenResource][post][{client_ip}]'
    
    # verify that the request contain valid key and secret
    app_key = request.headers.get('x-app-key')
    app_secret = request.headers.get('x-app-secret')
    
    server_app_key = os.getenv("MTO_PARTNER_ID")
    server_app_secret = os.getenv("MTO_PARTNER_SECRET")
    
    if str(app_key) != server_app_key or app_secret != server_app_secret:
        Log.info(f"{log_tag}[{client_ip}] invalid x-app-key or x-app-secret in header")
        return prepared_response(False, "UNAUTHORIZED", f"Unauthorized request.")
    
    
    client_id = data.get('client_id')
    truncated_client_id = client_id[:7] + "..." if client_id else None
    
    Log.info(f"{log_tag} [{truncated_client_id}] request from IP: {client_ip}")
    Log.info(f"{log_tag} [{truncated_client_id}][{client_ip}]")

    # Validate client credentials
    client = Client.retrieve_client(client_id)
    if not client:
        abort(401, message="Invalid client credentials")
        
    business = Business.get_business(client_id)
    if not business:
        abort(401, message="Your access has been revoked")
    
    #FOR AUTOMATED TESTING   
    business_id = str(business.get("_id"))
    set_redis('automated_test_business_id', business_id)
    #FOR AUTOMATED TESTING
        
    email = decrypt_data(business["email"])
        
    # Check if the user exists based on email
    user = User.get_user_by_email(email)
    if user is None:
        Log.info(f"{log_tag} [{client_ip}][{business['email']}]: login email does not exist")
        return prepared_response(False, "UNAUTHORIZED", f"Invalid access.")
        
    
    # Generate both access token and refresh token using the user object
    permissions = None
    access_token, refresh_token = generate_tokens(user, permissions)
    Token.create_token(client_id, access_token, refresh_token, 190900, 604800)

    # Token is for 24 hours
    return jsonify({'access_token': access_token, 'token_type': 'Bearer', 'expires_in': 86400})


# -----------------------SUBSCRIBER REGISTRATION INITIATE-----------------------------------------
@blp_subscriber_registration.route("/registration/initiate", methods=["POST"])
class SubscriberRegistrationResource(MethodView):
     # POST Subscriber (Create a new Subscriber)
    @token_required
    @blp_subscriber_registration.arguments(SubscriberLoginInitSchema, location="form")
    @blp_subscriber_registration.response(200, SubscriberLoginInitSchema)
    @blp_subscriber_registration.doc(
        summary="Create a new subscriber",
        description="""
            Create a new subscriber account.

            This endpoint requires an `Authorization` header with a Bearer token.

            - **POST**: Provide the subscriber's phone number (`username`), 
            `country_iso_2`, `device_id`, `location`, and `agreed_terms_and_conditions`.
            Optionally attach files (e.g., profile image) using multipart/form-data.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SubscriberLoginInitSchema,
                    "example": {
                        "country_iso_2": "gb",
                        "username": "07568983843",
                        "agreed_terms_and_conditions": True,
                        "device_id": "e0f1b2c3d4e5f6a7b8c9d0e1f2aa99cc",
                        "location": "51.5074,-0.1278",
                        "image": "file (optional_profile_image.jpg)"
                    }
                }
            },
        },
        responses={
            201: {
                "description": "Subscriber created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 201,
                            "message": "Subscriber created successfully"
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
        security=[{"Bearer": []}],
    )
    def post(self, item_data):
        
        log_tag = '[subscriber_authenticaiton.py][SubscriberRegistrationResource][post]'
        """Handle the POST request to create a new Subscriber."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        tenant_id = None
        username = None
        terms = str.lower(str(item_data.get("agreed_terms_and_conditions")))
        
        # check if terms and conditions has been accepted
        if terms != "true" and terms != "1" and terms != "yes": 
            Log.info(f"{log_tag} Terms and conditions must be accepted before you can proceed.")
            return prepared_response(False, "BAD_REQUEST", f"Terms and conditions must be accepted before you can proceed.")
        
        tenant_id = decrypt_data(user_info.get("tenant_id"))
            
        if tenant_id is None:
            Log.info(f"{log_tag} An unexpected error occurred while retrieving tenants.")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while retrieving tenants.")
            
        tenant = Essensial.get_tenant_by_id(tenant_id)
        country_iso_2 = tenant.get("country_iso_2")
        
        # validate and format the number using the country code
        username = validate_and_format_phone_number(item_data.get("username"), country_iso_2)
        
        try:
            if username is None:
                Log.info(f"{log_tag} Invalid phone number")
                return prepared_response(False, "BAD_REQUEST", f"Invalid phone number")
            
            # Check if the subscriber already exists based on business_id and username
            Log.info(f"{log_tag}[{client_ip}]checking if subscriber already exists")
            if Subscriber.check_item_exists(user_info["business_id"], key="username", value=username):
                return prepared_response(False, "CONFLICT", f"Subscriber with this phone number already exists.")
                
            # sending OTP
            shop_service = ShopApiService(tenant_id)
                      
            app_mode = os.getenv("APP_RUN_MODE")
            
            location_string = item_data.get("location")
                    
            location_obj = json.loads(location_string)
            
            device_checksum = {
                "username": item_data.get("username"),
                "device_id": item_data.get("device_id"),
                "location": location_obj,
                "ip_address": client_ip,
                "time": str(datetime.utcnow())
            }
            # hash the device information
            device_hashed = hash_transaction(device_checksum)
            # prepare the device detail for encryption
            device_string = json.dumps(device_checksum, sort_keys=True)
            #encrypt the device details
            encrypted_device = encrypt_data(device_string)
            
            # store the encrypted device in redis using the transaction hash as a key
            set_redis_with_expiry(device_hashed, 600, encrypted_device)
            
            # needed for automated testing
            if username in AUTOMATED_TEST_USERNAMES or app_mode =='development':
                
                automated_test_otp = os.getenv("AUTOMATED_TEST_OTP")
                
                pin = automated_test_otp
                
                message = f'Your Zeepay security code is {pin} and expires in 5 minutes. If you did not initiate this, DO NOT APPROVE IT.'
                redisKey = f'otp_token_{username}'
                set_redis_with_expiry(redisKey, 300, pin)
            
                set_redis_with_expiry("automate_test_username", 300, username)
                set_redis_with_expiry("otp_token_automated_test", 300, pin)
                
                Log.info(f"{log_tag}[{client_ip}][{username}][{pin}] AUTOMATED TESTING OTP")
                return jsonify({
                    "success": True,
                    "status_code": HTTP_STATUS_CODES["OK"],
                    "device_checksum": str.upper(device_hashed),
                    "message": "OTP has been sent",
                }), HTTP_STATUS_CODES["OK"]
            else:
                # every other number part from the one using for automated testing
                pin = generate_otp()
                message = f'Your Zeepay security code is {pin} and expires in 5 minutes. If you did not initiate this, DO NOT APPROVE IT.'
                redisKey = f'otp_token_{username}'
                set_redis_with_expiry(redisKey, 300, pin)
            
                Log.info(f"{log_tag}[{client_ip}][{username}][{pin}] sending OTP")
                response = shop_service.send_sms(username, message, tenant_id)
                
                Log.info(f"{log_tag}[{client_ip}] SMS response: {response}")
                if response and response.get("status") == "success":
                    return jsonify({
                        "success": True,
                        "status_code": HTTP_STATUS_CODES["OK"],
                        "device_checksum": str.upper(device_hashed),
                        "message": "OTP has been sent",
                    }), HTTP_STATUS_CODES["OK"]
                    
                else:
                    return prepared_response(False, "BAD_REQUEST", f"Could not send OTP")             
        
                
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")
            

# -----------------------AGENT REGISTRATION VERIFY OTP-----------------------------------------
@blp_subscriber_registration.route("/registration/verify-otp", methods=["POST"])
class SubscriberRegistrationVerifyOTPResource(MethodView):
     # POST Subscriber (Verify subscriber OTP)
    @token_required
    @blp_subscriber_registration.arguments(SubscriberVerifyOTPSchema, location="form")
    @blp_subscriber_registration.response(201, SubscriberVerifyOTPSchema)
    @blp_subscriber_registration.doc(
        summary="Verify OTP for agent registration",
            description="""
                This endpoint allows you to verify the OTP sent to an agent's phone number during registration. 
                The request requires an `Authorization` header with a Bearer token.
                - **POST**: Verify the OTP by providing the `username` (phone number) and the `otp` that was sent to the phone.
            """,
            requestBody={
                "required": True,
                "content": {
                    "application/json": {
                        "schema": SubscriberVerifyOTPSchema,  # Updated schema for OTP verification
                        "example": {
                            "username": "987-654-3210",  # Example phone number (username)
                            "otp": "123456"  # Example OTP
                        }
                    }
                },
            },
            responses={
                201: {
                    "description": "OTP has been verified successfully",
                    "content": {
                        "application/json": {
                            "example": {
                                "account_status": [
                                            {
                                                "account_verified": {
                                                    "created_at": str(datetime.utcnow()),
                                                    "status": True,
                                                    "ip_address": "127.0.0.1"
                                                },
                                            },
                                            {
                                                "choose_pin": {
                                                    "status": False,
                                                },
                                            }, 
                                            {
                                                "basic_kyc_added": {
                                                    "status": False,
                                                }
                                            },
                                            {
                                                "business_email_verified": {
                                                    "status": False,
                                                }
                                            },
                                            {
                                                "uploaded_agent_id_info": {
                                                    "status": False,
                                                }
                                            },
                                            {
                                                "uploaded_director_id_info": {
                                                    "status": False,
                                                }
                                            },
                                            {
                                                "registration_completed": {
                                                    "status": False,
                                                }
                                            },
                                            {
                                                "onboarding_in_progress": {
                                                    "status": False,
                                                }
                                            },
                                            {
                                                "onboarding_in_progress": {
                                                    "status": False,
                                                }
                                            }
                                        ],
                                "message": "OTP verified and agent registration is in progress",
                                "status_code": 200,
                                "success": True  # This would indicate that OTP verification was successful
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
        log_tag = '[subscriber_authenticaiton.py][SubscriberRegistrationVerifyOTPResource][post]'
        """Handle the POST request to verify OTP."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        username = None
        
        tenant_id = decrypt_data(user_info.get("tenant_id"))
        business_id = str(user_info.get("business_id"))
        
            
        if tenant_id:
            # validate phone number only if not testing
            automated_test_username = os.getenv("AUTOMATED_TEST_USERNAME")
            if username != automated_test_username:
                tenant = Essensial.get_tenant_by_id(tenant_id)
                country_iso_2 = tenant.get("country_iso_2")
                username = validate_and_format_phone_number(item_data.get("username"), country_iso_2)
            
            otp = item_data.get("otp")
            
            redisKey = f'otp_token_{username}'
            
            token_byte_string = get_redis(redisKey)
            
            if not token_byte_string:
                return prepared_response(False, "UNAUTHORIZED", f"The OTP is not valid")
            
            # Decode the byte string and convert to integer
            token = token_byte_string.decode('utf-8')
            
            #check device checksum is not tempered
            try:
                device_checksum = item_data.get("device_checksum", None)
                device_checksum_hash_transformed = str.lower(device_checksum)
                Log.info(f"{log_tag} retrieving device information from redis")
                encrypted_device_info = get_redis(device_checksum_hash_transformed)
                
                if encrypted_device_info is None:
                    message = f"The device info has expired or the checksum is invalid. Kindly call the 'registration/initiate' endpoint again and ensure the checksum is valid."
                    Log.info(f"{log_tag} {message}")
                    return prepared_response(False, "BAD_REQUEST", f"{message}")
                
                decrypted_device_info = decrypt_data(encrypted_device_info)
                
                device_details = json.loads(decrypted_device_info)
                
                checksum_username = validate_and_format_phone_number(device_details.get("username"), country_iso_2)
                    
                if username != checksum_username:
                    Log.info(f"{log_tag} Missmatch phone number in checksum payload and the verify phone number.")
                    return prepared_response(False, "BAD_REQUEST", f"We found some inconsistencies in your request.")
            
                
                
                if device_details is None:
                    Log.info(f"{log_tag} Device Information validation failed.")
                    return prepared_response(False, "BAD_REQUEST", f"Device verification failed.")
            except Exception as e:
                Log.info(f"{log_tag} error retrieving device from redis: {str(e)}")
                return prepared_response(False, "BAD_REQUEST", f"An eror ocurred while retrieving device. Error: {str(e)}")
                
            
            if str(otp) != str(token):
                Log.info(f"{log_tag}[otp: {otp}][token: {token}] verification failed" )
                return prepared_response(False, "UNAUTHORIZED", f"The OTP is not valid")
            else:
                Log.info(f"{log_tag} verification worked")
                # remove token from redis
                remove_redis(redisKey)
                
                #verification completed, proceed to create agent
                # Assign user_id and business_id from current user
                try:
                    business = Business.get_business_by_id(business_id)
                except ValueError as e:
                    Log.info(f"{log_tag} error pulling business information: {str(e)}")
                    
                subscriber_data = {}
                subscriber_data["username"] = username
                subscriber_data["business_id"] = str(business_id)
                subscriber_data["tenant_id"] = tenant_id
                subscriber_data["agreed_terms_and_conditions"] = True
                
                # Create the structure for account_status 
                
                account_status = [
                                    {
                                        "account_verified": {
                                            "created_at": str(datetime.utcnow()),
                                            "status": True,
                                            "ip_address": client_ip
                                        },
                                    },
                                        {
                                        "choose_pin": {
                                            "status": False,
                                        },
                                    }, 
                                    {
                                        "basic_kyc_updated": {
                                            "status": False,
                                        }
                                    },
                                    {
                                        "account_email_verified": {
                                            "status": False,
                                        }
                                    },
                                    {
                                        "uploaded_id_front": {
                                            "status": False,
                                        }
                                    },
                                    {
                                        "uploaded_id_back": {
                                            "status": False,
                                        }
                                    },
                                    {
                                        "uploaded_id_utility": {
                                            "status": False,
                                        }
                                    },
                                    {
                                        "onboarding_completed": {
                                            "status": False,
                                        }
                                    }
                                ]
                
                subscriber_data["account_status"] = account_status
                
                try:
                    # Check if the subscriber already exists based on business_id and username
                    Log.info(f"{log_tag}[{client_ip}]checking if subscriber already exists")
                    if Subscriber.check_item_exists(user_info["business_id"], key="username", value=item_data["username"]):
                        return prepared_response(False, "CONFLICT", f"Subscriber with this phone number already exists.")
                        
                        
                    # generate referral_code
                    referral_code = generate_secure_referral_code()
                    
                    #check if referral_code already exists
                    # keep generating until unique
                    while Subscriber.check_item_exists(user_info["business_id"], key="referral_code", value=referral_code):
                        referral_code = generate_secure_referral_code()
                        
                    subscriber_data["referral_code"] = referral_code
                    
                    # Create a new subscriber instance
                    Log.info(f"{log_tag} committing subscriber to the database")
                    
                    # Record the start time
                    start_time = time.time()
                    
                    subscriber_obj = Subscriber(**subscriber_data)
                    subscriber_id = subscriber_obj.save()
                    
                    Log.info(f"{log_tag} subscriber_id: {subscriber_id}")
                    
                    # Record the end time
                    end_time = time.time()
                    
                    # Calculate the duration
                    duration = end_time - start_time
                    
                    # Log the response and time taken
                    Log.info(f"{log_tag} [{client_ip}] commit subscriber completed in {duration:.2f} seconds")
                    
                    if subscriber_id:
                        user_data = {}
                        user_data["username"] = username
                        user_data["referral_code"] = referral_code
                        user_data["account_type"] = "consumer"
                        user_data["type"] = "Consumer"
                        user_data["business_id"] = str(business_id) 
                        user_data["tenant_id"] = business.get("tenant_id")
                        user_data["client_id"] = decrypt_data(business.get("client_id"))
                        
                        user_data["device_id"] = device_details.get("device_id")
                        user_data["location"] = device_details.get("location")
                        user_data["ip_address"] = device_details.get("ip_address")
                        user_data["phone_number"] = username
                        password = generate_temporary_password()
                        user_data["password"] = bcrypt.hashpw(password.encode("utf-8"),
                            bcrypt.gensalt()
                        ).decode("utf-8")
                    
                        create_user = commit_subscriber_user(
                            log_tag=log_tag, 
                            client_ip=client_ip, 
                            user_data=user_data,
                            account_status=account_status, 
                            subscriber_id=subscriber_id
                        )
                        
                        # check if user creation was successful
                        if create_user is None:
                            Log.info(f"{log_tag}[{client_ip}] subscriber user could not be created")
                            return prepared_response(False, "BAD_REQUEST", f"Subscriber user could not be created")
                        
                        # retrieve subscriber and system user information
                        try:
                            subscriber = Subscriber.get_by_username(username)
                        except Exception as e:
                            Log.info(f"{log_tag}[{client_ip}] error retrieving subscriber: {str(e)}")
                        
                        # retrieve system user information using subscriber_id
                        try:
                            s_user = User.get_user_by_subscriber_id(subscriber_id)
                        except Exception as e:
                            Log.info(f"{log_tag}  [post][{client_ip}]: error retreiving for system user: {e}")
                            
                        if s_user is None:
                            Log.info(f"{log_tag}[{client_ip}] user not found for : {username}") 
                            return prepared_response(False, "NOT_FOUND", f"User not found for {username}")
                        
                        s_user["business_id"] = str(s_user.get("business_id"))
                        s_user["subscriber_id"] = str(subscriber_id)
                        s_user["account_status"] = subscriber.get("account_status")
                        
                        s_user["first_name"] = subscriber.get("first_name") if subscriber.get("first_name") else None
                        s_user["middle_name"] = s_user.get("middle_name") if s_user.get("middle_name") else None
                        s_user["last_name"] = subscriber.get("last_name") if subscriber.get("last_name") else None
                        return create_token_response_system_user(s_user, subscriber_id, client_ip, log_tag, redisKey)
                        
                        
                    else:
                        return prepared_response(False, "BAD_REQUEST", f"Subscriber could not be created")
                except Exception as e:
                    return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")
        else:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred")


# -----------------------SUBSCRIBER REGISTRATION CHOOSE PIN-----------------------------------------
@blp_subscriber_registration.route("/registration/choose-pin", methods=["PATCH"])
class SubscriberRegistrationChoosePINResource(MethodView):
     # POST Subscriber (Create a new Subscriber)
    @token_required
    @blp_subscriber_registration.arguments(SubscriberRegistrationChoosePinSchema, location="form")
    @blp_subscriber_registration.response(200, SubscriberRegistrationChoosePinSchema)
    @blp_subscriber_registration.doc(
        summary="Choose PIN for subscriber registration",
        description="""
            This endpoint allows a subscriber to set their PIN after successfully registering.
            The request requires an `Authorization` header with a Bearer token.
            - **POST**: Set the PIN for the subscriber by providing the `subscriber_id` and the `pin`.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": SubscriberRegistrationChoosePinSchema,  # Updated schema for choosing the pin
                    "example": {
                        "subscriber_id": "60d21b4967d0d8992e610c85",  # Example subscriber ID (ObjectId)
                        "pin": "1234"  # Example PIN
                    }
                }
            },
        },
        responses={
            201: {
                "description": "PIN has been successfully set",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Account PIN updated successfully",
                            "status_code": 200,
                            "success": True  # Success should be True on successful update
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
    def patch(self, item_data):
        """Handle the POST request to choose account PIN."""
        
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        subscriber_id = user_info.get("subscriber_id")
        
        client_ip = request.remote_addr
        account_status = dict()
        
        log_tag = f'[subscriber_authenticaiton.py][SubscriberRegistrationChoosePINResource][post][{client_ip}][{business_id}][{subscriber_id}]'
        
        # check if subscriber exist before proceeding to update the information 
        try:
            subscriber = Subscriber.get_by_id(business_id=business_id, subscriber_id=subscriber_id)
            if not subscriber:
                Log.info(f"{log_tag} subscriber_id with ID: {subscriber_id} does not exist")
                return prepared_response(False, "NOT_FOUND", f"Subscriber_id with ID: {subscriber_id} does not exist")
            
            account_status = subscriber.get("account_status")
            
            # Get the status for 'choose_pin'
            choose_pin_status = next((item["choose_pin"]["status"] for item in account_status if "choose_pin" in item), None)
            
            #Check if account PIN has already been set
            if choose_pin_status:
                # stop the action if status PIN has already been set
                Log.info(f"{log_tag} Account PIN has already been set.")
                return prepared_response(False, "BAD_REQUEST", f"Account PIN has already been set.")

        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
 
        
        try:
          
            pin = item_data["pin"]
            # update acount pin
            Log.info(f"{log_tag}[{client_ip}] updating account PIN")
            
            # Record the start time
            start_time = time.time()
            
            update_pin = User.update_account_pin_by_subscriber_id(
                subscriber_id=subscriber_id, 
                pin=pin
            )
            
            # Record the end time
            end_time = time.time()
            
            # Calculate the duration
            duration = end_time - start_time
            
            # Log the response and time taken
            Log.info(f"{log_tag}[{client_ip}] updating PIN completed in {duration:.2f} seconds")
            
            
            if update_pin:
                # update choose_pin status for account_status in agents collection
                Log.info(f"{log_tag}[{client_ip}] updating account PIN")
                
                update_account_status = Subscriber.update_account_status_by_subscriber_id(
                    subscriber_id,
                    client_ip,
                    'choose_pin',
                    True
                )
                
                Log.info(f"{log_tag}[{client_ip}] update_account_status: {update_account_status}")
                
                if update_account_status and update_account_status.get("success"):
                    Log.info(f"{log_tag} Account PIN updated successfully.")
                    return prepared_response(False, "OK", f"Account PIN updated successfully.")
                else:
                    Log.info(f"{log_tag} PIN update failed.")
                    return prepared_response(False, "BAD_REQUEST", f"PIN update failed.")
                
            else:
                Log.info(f"{log_tag} Account PIN could not be updated.")
                return prepared_response(False, "BAD_REQUEST", f"Account PIN could not be updated.")
                
        except Exception as e:
            Log.info(f"{log_tag} error updating account PIN: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")
        

# -----------------------GET REGISTRATION SUBSCRIBER-----------------------------------------
@blp_subscriber_registration.route("/registration/subscriber", methods=["GET"])
class SubscriberRegistrationGetResource(MethodView):
    # GET Subscriber (Retrieve by Subscriber_id)
    @token_required
    @blp_subscriber_registration.arguments(SubscriberIdQuerySchema, location="query")
    @blp_subscriber_registration.response(200, SubscriberIdQuerySchema)
    @blp_subscriber_registration.doc(
        summary="Retrieve subscriber by subscriber_id",
        description="""
            This endpoint allows you to retrieve a subscriber based on the `subscriber_id` in the query parameters.
            - **GET**: Retrieve a subscriber by providing `subscriber_id`.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Define that Bearer token authentication is required
    )
    def get(self, agent_data):
        
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        subscriber_id = user_info.get("subscriber_id")
        
        client_ip = request.remote_addr
        
        log_tag = f'[subscriber_authenticaiton.py][SubscriberRegistrationChoosePINResource][post][{client_ip}][{business_id}][{subscriber_id}]'

        if not subscriber_id:
            Log.info(f"{log_tag}[{client_ip}] subscriber_id must be provided.")
            return prepared_response(False, "BAD_REQUEST", f"subscriber_id must be provided.")

        try:
            Log.info(f"{log_tag}[{client_ip}][{subscriber_id}] retrieving agent.")
            start_time = time.time()

            subscriber = Subscriber.get_by_id(
                business_id=business_id, 
                subscriber_id=subscriber_id
            )

            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag}[{client_ip}][{business_id}] retrieving subscriber completed in {duration:.2f} seconds")

            if not subscriber:
                Log.info(f"{log_tag}[{client_ip}][{business_id}] subscriber not found.")
                return prepared_response(False, "NOT_FOUND", f"Subscriber not found.")

            Log.info(f"{log_tag}[{client_ip}][{business_id}] Subscriber retrieved successfully.")
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": subscriber
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag}[{client_ip}][{subscriber_id}] error retrieving subscriber. {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while retrieving the subscriber.")

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}][{subscriber_id}] error retrieving subscriber. {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")


# -----------------------SUBSCRIBER REGISTRATION BASIC KYC-----------------------------------------
@blp_subscriber_registration.route("/registration/basic-kyc", methods=["PATCH"])
class SubscriberRegistrationBasicKYCResource(MethodView):
     # PATCH Subscriber (Update Subscriber KYC)
    @token_required
    @blp_subscriber_registration.arguments(SubscriberRegistrationBasicKYCSchema, location="form")
    @blp_subscriber_registration.response(200, SubscriberRegistrationBasicKYCSchema)
    @blp_subscriber_registration.doc(
        summary="Update Basic KYC for Subscriber",
        description="""
            Update the basic KYC (Know Your Customer) information for a subscriber during registration.

            The request must include an `Authorization` header with a Bearer token.

            - **PUT**: Provide `subscriber_id`, `first_name`, `last_name`, `gender`, and `email`.
            Optional fields: `middle_name`, `referral_code`.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": SubscriberRegistrationBasicKYCSchema,  # Marshmallow schema
                    "example": {
                        "subscriber_id": "67ff9e32272817d5812ab2fc",  # Example (ObjectId string)
                        "first_name": "John",
                        "middle_name": "K.",
                        "last_name": "Doe",
                        "gender": "Male",  # One of: Male | Female
                        "email": "john.doe@example.com",
                        "referral_code": "ABC123"  # Optional, 6–8 chars
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Subscriber KYC details have been successfully updated",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Subscriber KYC updated successfully",
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
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        """Handle the POST request to verify OTP."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = user_info.get("business_id")
        subscriber_id = user_info.get("subscriber_id")
        subscriber = None
        
        log_tag = f'[subscriber_authenticaiton.py][SubscriberRegistrationBasicKYCResource][post][{client_ip}][{business_id}][{subscriber_id}]'
        
        item_data["remote_ip"] = client_ip
        item_data["subscriber_id"] = subscriber_id
        
        # Assign user_id and business_id from current user
        item_data["business_id"] =business_id 
        agent_id = item_data.get("agent_id")
        
        
        # check if subscriber exist before proceeding to update the information 
        try:
            subscriber = Subscriber.get_by_id(
                business_id=business_id, 
                subscriber_id=subscriber_id
            )
            
            if not subscriber:
                Log.info(f"{log_tag} subscriber_id with ID: {subscriber_id} does not exist")
                
                return prepared_response(False, "NOT_FOUND", f"Subscriber_id with ID: {agent_id} does not exist")
        
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
        
        # check if subscriber email is already used by another user
        try:
            if Subscriber.check_multiple_item_exists(business_id, {"email": item_data.get("email")}):
                Log.info(f"{log_tag} This email has already been used by another subscriber.")
                return prepared_response(False, "CONFLICT", f"This email has already been used by another subscriber.")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
        
        
        if item_data.get("referral_code") is not None:
            # check if referral_code exist and get the referrer ID to add to the payload
            try:
                Log.info(f"{log_tag} checking if referral_code exist")
                referrer_subscriber = Subscriber.get_subscriber_by_referral_code(user_info["business_id"], key="referral_code", value=item_data["referral_code"])
                
                if referrer_subscriber:
                    item_data["referrer"] = referrer_subscriber
                    Log.info(f"{log_tag} referrer: {referrer_subscriber}")
                
                
            except Exception as e:
                Log.info(f"{log_tag} error occurred while getting referrer ID. {e}")
    
        try:
            Log.info(f"{log_tag}[{client_ip}][{subscriber_id}] updating subscribers kyc.")
            start_time = time.time()
            
            # remove referral_code if it exists
            if item_data.get("referral_code"):
                item_data.pop("referral_code", None)

            update = Subscriber.update(subscriber_id, **item_data)

            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag} update: {update}")
            Log.info(f"{log_tag}[{client_ip}][{business_id}] subscriber update completed in {duration:.2f} seconds")
            
            if not update:
                Log.info(f"{log_tag} Could not update subscriber.")
                return prepared_response(False, "BAD_REQUEST", f"Could not update subscriber.")
            
            update_account_status = Subscriber.update_account_status_by_subscriber_id(
                subscriber_id,
                client_ip,
                'basic_kyc_updated',
                True
            )
            
            Log.info(f"{log_tag}[{client_ip}] update_account_status: {update_account_status}")
            
            if update_account_status and update_account_status.get("success"):
                Log.info(f"{log_tag} Subscriber updated successfully.")
                return prepared_response(False, "OK", f"Subscriber updated successfully.")
            else:
                Log.info(f"{log_tag} PIN update failed.")
                return prepared_response(False, "BAD_REQUEST", f"PIN update failed.")

        except PyMongoError as e:
            Log.info(f"{log_tag}[{client_ip}][{subscriber_id}] error updating subscriber. {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while updating the subscriber.")

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}][{subscriber_id}] error updating subscriber. {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")
        

# -----------------------AGENT REGISTRATION INITIATE EMAIL VERIFICAITON-----------------------------------------
@blp_subscriber_registration.route("/registration/initiate-email-verification", methods=["POST"])
class SubscriberRegistrationInitiateEmailVerificationResource(MethodView):
     # PATCH Subscriber (Initiate Email Validation)
    @token_required
    @blp_subscriber_registration.arguments(SubscriberRegistrationEmailSchema, location="form")
    @blp_subscriber_registration.response(200, SubscriberRegistrationEmailSchema)
    @blp_subscriber_registration.doc(
        summary="Verify Business Email for agent",
        description="""
            This endpoint allows you to verify the business email for an agent during registration. 
            The request requires an `Authorization` header with a Bearer token.
            - **POST**: Verify the business email by providing `agent_id` and `return_url`.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": SubscriberRegistrationEmailSchema,  # Schema for verifying business email
                    "example": {
                        "agent_id": "67ff9e32272817d5812ab2fc",  # Example agent ID (ObjectId)
                        "return_url": "http://localhost:9090/redirect"  # Example return URL
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
        business_id = user_info.get("business_id")
        subscriber_id = str(user_info.get("subscriber_id"))
        subscriber = None
        email = None
        subscriber_name = None
        
        log_tag = f'[subscriber_authenticaiton.py][SubscriberRegistrationInitiateEmailVerificationResource][post][{client_ip}][{business_id}][{subscriber_id}]'
        
        # Assign user_id and business_id from current user
        return_url = item_data.get("return_url")
        
        # check if subscriber exist before proceeding to update the information 
        try:
            Log.info(f"{log_tag} checking if agent exist")
            subscriber = Subscriber.get_by_id(
                business_id=business_id, 
                subscriber_id=subscriber_id
            )
            if not subscriber:
                Log.info(f"{log_tag} Subscriber with ID: {subscriber_id} does not exist.")
                return prepared_response(False, "NOT_FOUND", f"Subscriber with ID: {subscriber_id} does not exist.")
            
            email = subscriber.get('email', None)
            
            # check if email is already verified and disallow re-verification
            account_status = subscriber.get("account_status")
            
            # Get the status for 'account_email_verified'
            subscriber_email_verified_status = next((item["account_email_verified"]["status"] for item in account_status if "account_email_verified" in item), None)
            
            #Check if subscriber email has already been verified
            if subscriber_email_verified_status:
                # stop the action of re-verification if status is already True
                Log.info(f"{log_tag} Subscriber's email has already been verified.")
                return prepared_response(False, "BAD_REQUEST", f"Subscriber's email has already been verified.")
            
            
            if not email:  # Check if subscriber email exists
                # subscriber subscriber kyc not updated
                Log.info(f"{log_tag} The KYC information including the email has not  been added. First call the 'registration/basic-kyc' before you can verify the email.")
                return prepared_response(False, "BAD_REQUEST", f"The KYC information including the email has not  been added. First call the 'registration/basic-kyc' before you can verify the email.")

            subscriber_name = subscriber.get("first_name") + " " + subscriber.get("last_name")
        
            base_url = request.host_url
            
            token = secrets.token_urlsafe(32)  # Generates a 32-byte URL-safe token
            
            encrypt_subscriber_id = encrypt_data(subscriber_id)
            
            reset_url = generate_subscriber_registration_verification_token(base_url, encrypt_subscriber_id, token)
            
            Log.info(f"reset_url: {reset_url}")
            
            redisKey = f'email_token_{subscriber_id}'
            
            payload = {"token": token, "return_url": return_url}
            set_redis_with_expiry(redisKey, 300, str(payload))
            
            try:
                Log.info(f"{log_tag} making request to send email for verification")
                send = send_subscriber_registration_email(email, subscriber_name, reset_url)
                if send and send.status_code == 200:
                    Log.info(f"{log_tag} Email has been sent to subscriber email successfully.")
                    return prepared_response(True, "OK", f"Email has been sent to subscriber email successfully.")
                else:
                    Log.info(f"{log_tag} An error occurred while sending email to subscriber's email.")
                    return prepared_response(False, "BAD_REQUEST", f"An error occurred while sending email to subscriber's email.")
                    
            except Exception as e:
                    Log.info(f"{log_tag} \t An error occurred sending emails: {e}")
                    return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")

                
            
        except Exception as e:
            Log.info(f"{log_tag} \t An error occurred sending emails: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")


# -----------------------SUBSCRIBER REGISTRATION VERIFY EMAIL-----------------------------------------
@blp_subscriber_registration.route("/registration/verify-email", methods=["GET"])
class SubscriberRegistrationVerifyEmailResource(MethodView):
     # GET verify subscriber email (Verify subscriber Email)
    @blp_subscriber_registration.arguments(SubscriberRegistrationVerifyEmailSchema, location="query")
    @blp_subscriber_registration.response(200, SubscriberRegistrationVerifyEmailSchema)
    @blp_subscriber_registration.doc(
        summary="Verify Email for Subscriber",
        description="""
            This endpoint allows you to verify the email for a subscriber during registration. 

            The request does not require a Bearer token.

            - **POST**: Verify the email by providing `token` and `subscriber_id`.
            After verification, the subscriber will be redirected to the `return_url` provided.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": SubscriberRegistrationVerifyEmailSchema,  # Schema for verifying subscriber email
                    "example": {
                        "token": "Hevpo9mkiuh67ffb4d02ed2c13ca4fa5a5b",  # Example verification token
                        "subscriber_id": "67ff9e32272817d5812ab2fc",   # Example subscriber ID (ObjectId)
                        "return_url": "https://app.example.com/dashboard"  # Redirect URL after verification
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Email verification processed successfully. Subscriber will be redirected.",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Verification email sent. Please check your inbox for further instructions.",
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
    def get(self, item_data):
        """Handle the POST request to verify Email."""
        client_ip = request.remote_addr
        log_tag = f'[subscriber_authenticaiton.py][SubscriberRegistrationVerifyEmailResource][post][{client_ip}]'
        
        decrypted_subscriber_id = None
        token = item_data.get("token")
        subscriber_id = item_data.get("user_id")
        
        # decrypt agent ID
        try:
            decrypted_subscriber_id = decrypt_data(subscriber_id)
            if decrypted_subscriber_id is None:
                Log.info(f"{log_tag} The token is not valid")
                query_params = {"status_code": 400, "message": "The token is not valid"}
                return_url = "https://instntmny.com"
                return_url_payload = generate_return_url_with_payload(return_url, query_params)
                return redirect(f"{return_url_payload}")
            
            Log.info(f"{log_tag} Subscriber ID decrypted")
            redisKey = f'email_token_{decrypted_subscriber_id}'
            
            payload = get_redis(redisKey)
            
            payload_decoded = payload.decode('utf-8')
            
            Log.info(f"{log_tag} payload_decoded: {payload_decoded}")
            
            
            # Convert the string to a dictionary
            payload_dict = ast.literal_eval(payload_decoded)
            
            redis_token = payload_dict["token"]
            return_url = payload_dict["return_url"]
            
            if not redis_token or not return_url:
                Log.info(f"{log_tag} Extracting token from redis failed. The token is not valid")
                query_params = {"status_code": 400, "message": "The token is not valid"}
                return_url_payload = generate_return_url_with_payload(return_url, query_params)
                return redirect(f"{return_url_payload}")
            else:
                # token exist, proceed to update account_status
                Log.info(f"{log_tag} Redis token has been extracted from redis")
                
                
                if str(redis_token) == str(token):
                    Log.info(f"{log_tag} Redis token same as request token")
                    
                    update_account_status = Subscriber.update_account_status_by_subscriber_id(
                        decrypted_subscriber_id,
                        client_ip,
                        'account_email_verified',
                        True
                    )
                
                    if update_account_status and update_account_status.get("success"):
                        Log.info(f"update_account_status: {update_account_status}")
                        
                        query_params = {"status_code": 200, "message": "Email verified successfully"}
                        
                        return_url_payload = generate_return_url_with_payload(return_url, query_params)
                        
                        remove_redis(redisKey) # remove token from redis
                        Log.info(f"{log_tag} return_url_payload: {return_url_payload}")
                        return redirect(f"{return_url_payload}")
                    else:
                        return prepared_response(False, "BAD_REQUEST", f"The token is not valid")
                else:
                        Log.info(f"{log_tag} Redis token different from request token")
                        
                        Log.info(f"{log_tag} Redis token: {redis_token}")
                        Log.info(f"{log_tag} Request token: {token}")
                        return prepared_response(False, "BAD_REQUEST", f"The token is not valid")
           
                
               
        except Exception as e:
            Log.info(f"{log_tag} An unexpected error occurred: {str(e)}")
            query_params = {"status_code": 400, "message": "An unexpected error occurred"}
            return_url = "https://instntmny.com"
            return_url_payload = generate_return_url_with_payload(return_url, query_params)
            return redirect(f"{return_url_payload}")


# -----------------------SUBSCRIBER REGISTRATION UPLOAD ID DOCUMENTS-----------------------------------------
@blp_subscriber_registration.route("/registration/id-document-upload", methods=["PATCH"])
class SubscriberRegistrationIDUploadResource(MethodView):
    # PATCH Subscriber (Subscriber upload ID document)
    @token_required
    @blp_subscriber_registration.arguments(SubscriberRegistrationUploadIDDocumentsSchema, location="form")
    @blp_subscriber_registration.response(200, SubscriberRegistrationUploadIDDocumentsSchema)
    @blp_subscriber_registration.doc(
        summary="Update Subscriber Documents",
        description="""
            This endpoint allows you to update the documents for a subscriber during registration.

            The request requires an `Authorization` header with a Bearer token.

            - **PATCH**: Update the subscriber's documents by providing:
                - `subscriber_id`
                - `id_type` (optional)
                - `id_number` (optional)
                - `id_expiry` (optional; recommended ISO date, e.g. 2030-12-31)
                - `id_front_image` (optional file)
                - `id_back_image` (optional file)
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SubscriberRegistrationUploadIDDocumentsSchema,
                    "example": {
                        "subscriber_id": "67ff9e32272817d5812ab2fc",
                        "id_type": "Passport",
                        "id_number": "A12345678",
                        "id_expiry": "2030-12-31",
                        "id_front_image": "file (front.jpg)",
                        "id_back_image": "file (back.jpg)",
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Subscriber documents updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Documents updated successfully",
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
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        client_ip = request.remote_addr
        
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        subscriber_id = str(user_info.get("subscriber_id"))
        item_data["subscriber_id"] = subscriber_id
        
        remote_ip = client_ip
        
        log_tag = f'[subscriber_registration.py][SubscriberRegistrationIDUploadResource][patch][{client_ip}]'
        
        # verify subscriber exists
        try:
            subscriber = Subscriber.get_by_id(
                business_id=business_id,
                subscriber_id=subscriber_id
            )
            if not subscriber:
                return prepared_response(False, "NOT_FOUND", f"Subscriber with ID: {subscriber_id} does not exist.")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Error verifying subscriber: {e}")

        try:
            # Detect content type
            content_type = (request.mimetype or request.content_type or "").lower()
            is_multipart = content_type.startswith("multipart/form-data")
            

            item_data = {}

            if is_multipart:
                form_data = request.form.to_dict(flat=True)
                Log.info(f"{log_tag} multipart form_data: {form_data.keys()} | files: {list(request.files.keys())}")

                if not subscriber_id:
                    return prepared_response(False, "BAD_REQUEST", "subscriber_id is required.")

                # copy scalar values (added id_expiry)
                scalar_whitelist = ["id_type", "id_number", "id_expiry"]
                for k in scalar_whitelist:
                    if k in form_data:
                        item_data[k] = form_data.get(k)

                # --- handle file uploads via temp + unique bucket filename ---
                upload_fields = ["id_front_image", "id_back_image"]
                for field in upload_fields:
                    if field in request.files:
                        file_obj = request.files[field]
                        if file_obj and file_obj.filename:
                            temp_path = f"/tmp/{file_obj.filename}"
                            try:
                                file_obj.save(temp_path)

                                remote_base = f"subscribers/{business_id}/{subscriber_id}/{field}/{file_obj.filename}"
                                result = upload_file_to_bucket_unique_filename(temp_path, remote_base)

                                if not result or not result.get("url") or not result.get("path"):
                                    return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Error uploading {field}")

                                item_data[field] = result["url"]
                                item_data[f"{field}_file_path"] = result["path"]
                            except ValueError as e:
                                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Upload error for {field}: {e}")
                            finally:
                                try:
                                    if temp_path and os.path.exists(temp_path):
                                        os.remove(temp_path)
                                except Exception as ce:
                                    Log.info(f"{log_tag} Temp cleanup warning for {field}: {ce}")

            else:
                # JSON
                payload_json = request.get_json(silent=True) or {}
                Log.info(f"{log_tag} json payload: {payload_json}")
                subscriber_id = payload_json.get("subscriber_id")
                if not subscriber_id:
                    return prepared_response(False, "BAD_REQUEST", "subscriber_id is required.")

                # Accept URLs directly; include id_expiry
                json_whitelist = [
                    "id_type",
                    "id_number",
                    "id_expiry",
                    "id_front_image",
                    "id_front_image_file_path",
                    "id_back_image",
                    "id_back_image_file_path",
                ]
                for k in json_whitelist:
                    if k in payload_json:
                        item_data[k] = payload_json.get(k)

            # add context
            item_data["business_id"] = business_id
            item_data["updated_by"] = user_info.get("_id")
            item_data.pop("subscriber_id", None)

            result = Subscriber.upload_id_documents_by_subscriber_id(subscriber_id, remote_ip, **item_data)
            Log.info(f"{log_tag} update_subscriber_documents: {result}")

            if result and result.get("success"):
                return prepared_response(True, "OK", "Documents updated successfully.")
            return prepared_response(False, "BAD_REQUEST", result.get("message", "Documents could not be updated."))

        except Exception as e:
            Log.error(f"{log_tag}[{client_ip}] Exception: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Unexpected error: {e}")


@blp_subscriber_registration.route("/registration/poa-document-upload", methods=["PATCH"])
class SubscriberRegistrationPOAUploadResource(MethodView):
    # PATCH Subscriber (Subscriber upload documents)
    @token_required
    @blp_subscriber_registration.arguments(SubscriberRegistrationPoAUploadDocumentsSchema, location="form")
    @blp_subscriber_registration.response(200, SubscriberRegistrationPoAUploadDocumentsSchema)
    @blp_subscriber_registration.doc(
        summary="Update Subscriber Documents",
        description="""
            This endpoint allows you to update the documents for a subscriber during registration.

            The request requires an `Authorization` header with a Bearer token.

            - **PATCH**: Update the subscriber's documents by providing:
                - `id_type`
                - `proof_of_address` (optional file)
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SubscriberRegistrationPoAUploadDocumentsSchema,
                    "example": {
                        "poa_type": "Utility Bill",
                        "proof_of_address": "file (address.jpg)"
                    }
                }
            },
        },
        responses={
            200: {
                "description": "Subscriber documents updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Documents updated successfully",
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
        security=[{"Bearer": []}],
    )
    def patch(self, item_data):
        client_ip = request.remote_addr
        
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        subscriber_id = str(user_info.get("subscriber_id"))
        item_data["subscriber_id"] = subscriber_id
        
        remote_ip = client_ip
        
        log_tag = f'[subscriber_registration.py][SubscriberRegistrationPOAUploadResource][patch][{client_ip}]'
        
        # verify subscriber exists
        try:
            subscriber = Subscriber.get_by_id(
                business_id=business_id,
                subscriber_id=subscriber_id
            )
            if not subscriber:
                return prepared_response(False, "NOT_FOUND", f"Subscriber with ID: {subscriber_id} does not exist.")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Error verifying subscriber: {e}")

        try:
            # Detect content type
            content_type = (request.mimetype or request.content_type or "").lower()
            is_multipart = content_type.startswith("multipart/form-data")
            

            item_data = {}

            if is_multipart:
                form_data = request.form.to_dict(flat=True)
                Log.info(f"{log_tag} multipart form_data: {form_data.keys()} | files: {list(request.files.keys())}")

                if not subscriber_id:
                    return prepared_response(False, "BAD_REQUEST", "subscriber_id is required.")

                # copy scalar values (added id_expiry)
                scalar_whitelist = ["id_type", "id_number", "id_expiry"]
                for k in scalar_whitelist:
                    if k in form_data:
                        item_data[k] = form_data.get(k)

                # --- handle file uploads via temp + unique bucket filename ---
                upload_fields = ["proof_of_address"]
                for field in upload_fields:
                    if field in request.files:
                        file_obj = request.files[field]
                        if file_obj and file_obj.filename:
                            temp_path = f"/tmp/{file_obj.filename}"
                            try:
                                file_obj.save(temp_path)

                                remote_base = f"subscribers/{business_id}/{subscriber_id}/{field}/{file_obj.filename}"
                                result = upload_file_to_bucket_unique_filename(temp_path, remote_base)

                                if not result or not result.get("url") or not result.get("path"):
                                    return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Error uploading {field}")

                                item_data[field] = result["url"]
                                item_data[f"{field}_file_path"] = result["path"]
                            except ValueError as e:
                                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Upload error for {field}: {e}")
                            finally:
                                try:
                                    if temp_path and os.path.exists(temp_path):
                                        os.remove(temp_path)
                                except Exception as ce:
                                    Log.info(f"{log_tag} Temp cleanup warning for {field}: {ce}")

            else:
                # JSON
                payload_json = request.get_json(silent=True) or {}
                Log.info(f"{log_tag} json payload: {payload_json}")
                subscriber_id = payload_json.get("subscriber_id")
                if not subscriber_id:
                    return prepared_response(False, "BAD_REQUEST", "subscriber_id is required.")

                # Accept URLs directly; include id_expiry
                json_whitelist = [
                    "poa_type",
                    "proof_of_address",
                    "proof_of_address_file_path",
                ]
                for k in json_whitelist:
                    if k in payload_json:
                        item_data[k] = payload_json.get(k)

            # add context
            item_data["business_id"] = business_id
            item_data["updated_by"] = user_info.get("_id")
            item_data.pop("subscriber_id", None)

            result = Subscriber.upload_poa_documents_by_subscriber_id(subscriber_id, remote_ip, **item_data)
            Log.info(f"{log_tag} update_subscriber_documents: {result}")

            if result and result.get("success"):
                return prepared_response(True, "OK", "Documents updated successfully.")
            return prepared_response(False, "BAD_REQUEST", result.get("message", "Documents could not be updated."))

        except Exception as e:
            Log.error(f"{log_tag}[{client_ip}] Exception: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Unexpected error: {e}")

            
        

















  








def commit_subscriber_user(log_tag, client_ip, user_data, account_status, subscriber_id):
    # Check if the subscriber already exists based on username
    Log.info(f"{log_tag}[{client_ip}] checking if subscriber already exists")
    if User.get_user_by_username(user_data["username"]) is not None:
        return prepared_response(False, "CONFLICT", f"Account already exists")
                
    Log.info(f"{log_tag}[{client_ip}][committing subscriber into the database: {user_data}")
    
    user_data["subscriber_id"] = subscriber_id
    
    # committing subscriber data to db
    user = User(**user_data, )
    user_client_id = user.save()
    if user_client_id:
        return jsonify({
            "success": True,
            "status_code": HTTP_STATUS_CODES["OK"],
            "subscriber_id": str(subscriber_id),
            "message": f"Subscriber was created",
            "account_status": account_status
        }), HTTP_STATUS_CODES["OK"] 
    else:
        return prepared_response(False, "BAD_REQUEST", f"Subscriber could not be created")
        






