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


from ....utils.essentials import Essensial
from ....utils.helpers import validate_and_format_phone_number
from ....utils.helpers import (
    generate_tokens, create_token_response_system_user
)
from ....services.doseal.confirm_pin_service import confirm_pin
from ....utils.calculation_engine import hash_transaction
#helper functions
from ....utils.generators import (
    generate_temporary_password,
    generate_otp,
    generate_registration_verification_token,
    generate_return_url_with_payload
)
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.file_upload import (
    upload_file, upload_file_to_bucket_unique_filename
)
from ....utils.json_response import prepared_response
from ....services.shop_api_service import ShopApiService
from tasks import send_user_registration_email
#helper functions

from ..admin.admin_business_resource import token_required
from ....utils.logger import Log # import logging
from ....utils.redis import (
    get_redis, set_redis_with_expiry, remove_redis, set_redis
)

# model
from ....models.subscriber_model import Subscriber
from ....models.user_model import User

from ....models.business_model import Business
from ....models.superadmin_model import Role
from ....utils.essentials import Essensial
from ....models.business_model import Client, Token
from ....schemas.business_schema import OAuthCredentialsSchema
from ....constants.service_code import (
    HTTP_STATUS_CODES, AUTOMATED_TEST_USERNAMES
)


#schema
from ....schemas.doseal.subscriber.subscriber_login_schema import (
    SubscriberLoginInitSchema, SubscriberLoginExecSchema
)

blp_subscriber_login = Blueprint("Subscriber Login", __name__, description="Subscriber Login Management")


# -----------------------SUBSCRIBER LOGIN INITIATE-----------------------------------------
@blp_subscriber_login.route("/login/initiate", methods=["POST"])
class SubscriberLoginInitiateResource(MethodView):
     # POST login (Subscriber Login Initiate)
    @blp_subscriber_login.arguments(SubscriberLoginInitSchema, location="form")
    @blp_subscriber_login.response(200, SubscriberLoginInitSchema)
    @blp_subscriber_login.doc(
        summary="Initiate Subscriber Login",
        description="""
            This endpoint allows you to initiate the login process for a subscriber by verifying 
            their phone number (username), country ISO2 code, device identifier, and location.

            The request must include an `Authorization` header with a Bearer token.

            - **POST**: Submit the subscriber's `username` (phone number), `country_iso_2`, 
            `device_id`, and `location` to initiate login. An OTP will be sent to the provided 
            phone number (and the PIN may be validated if supplied, depending on your business logic).
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": SubscriberLoginInitSchema,
                    "example": {
                        "username": "07568983843",
                        "country_iso_2": "gb",
                        "device_id": "e0f1b2c3d4e5f6a7b8c9d0e1f2a3b4c5",
                        "location": "51.5074,-0.1278",  # e.g. "lat,lon" or "London, UK"
                        "pin": "1234"  # optional
                    }
                }
            }
        },
        responses={
            200: {
                "description": "OTP has been sent successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "OTP has been sent",
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
        },
        security=[{"Bearer": []}],  # Bearer token authentication is required
    )
    def post(self, item_data):
        log_tag = '[subscriber_login.py][SubscriberLoginInitiateResource][post]'
        """Handle the POST request to initiate subscriber login process."""
        client_ip = request.remote_addr
        is_devices_exists = False
        is_pin_confirmed = False
        
        
        try:
            location_string = item_data.get("location")
            location_obj = json.loads(location_string)
                    
            country_iso_2 = item_data.get("country_iso_2")
            country_iso_2_upper = str.upper(country_iso_2)
            
            username = validate_and_format_phone_number(item_data.get("username"), country_iso_2_upper)
            
            if not username:
                Log.info(f"{log_tag} Invalid phone number")
                return prepared_response(False, "BAD_REQUEST", f"Invalid phone number")
            
            # Check if the subscriber exists before attempting to login
            Log.info(f"{log_tag}[{client_ip}][{username}] checking if subscriber already exists")
            
            try:
                subscriber_check = Subscriber.get_by_username(username)
            except Exception as e:
                Log.info(f"{log_tag}[{client_ip}] error retrieving subscriber: {str(e)}")

            
            if not subscriber_check:
                Log.info(f"{log_tag}[{client_ip}] Account not found.")
                return prepared_response(False, "NOT_FOUND", f"Account not found.")
               
            try:
                Log.info(f"{log_tag}[{client_ip}] retrieving tenant with: {country_iso_2_upper} ") 
                tenant = Essensial.get_tenant_by_iso_2(country_iso_2_upper)
                if tenant is None:
                    Log.info(f"{log_tag}[{client_ip}][{username}] Could not retrieve tenant")
                    return prepared_response(False, "BAD_REQUEST", f"Could not retrieve tenant")
            except Exception as e:
                Log.info(f"{log_tag}[{client_ip}][{username}] Error occurred while retrieving tenant. {str(e)}")
            
            

            tenant_id = tenant.get("id")
            Log.info(f"{log_tag}[{client_ip}] initiating login one: {username} ") 
            
            
            # sending OTP
            shop_service = ShopApiService(tenant_id)
            
            automated_test_username = os.getenv("AUTOMATED_TEST_USERNAME")
            app_mode = os.getenv("APP_RUN_MODE")
            
            # check if device is new and require PIN
            try:
                subscriber_id = str(subscriber_check.get("_id"))
                subscriber_user = User.get_user_by_subscriber_id(subscriber_id)
                
                device_id = item_data.get("device_id")
                devices = subscriber_user.get("devices")
                
                for device in devices:
                    if device.get("hashed_device_id") == hash_data(device_id):
                        Log.info(f"{log_tag}[{client_ip}][{username}][{device_id}] Old device found.")
                        is_devices_exists = True
                        
                # if is_devices_exists is still False, require PIN
                if devices is None or (not is_devices_exists and item_data.get("pin") is None):
                    Log.info(f"{log_tag}[{client_ip}][{username}][{device_id}] Login is from a new device, require PIN")
                    return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["DEVICE_IS_NEW_PIN_REQUIRED"],
                    "required_field": 'pin',
                    "message": 'Login is from a new device, require PIN',
                    "message_to_show": "You are logging in from a new device, kindly provide your PIN to proceed.",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
                
            except Exception as e:
                Log.info(f"{log_tag}[{client_ip}] error retrieving agent user: {str(e)}")
            
            
            Log.info(f"devices: {devices}")
            Log.info(f"is_devices_exists: {is_devices_exists}")
            
            # if pin exists in the case of new device, verify the pin
            if not is_devices_exists and item_data.get("pin") is not None:
                account_status = subscriber_check.get("account_status")
                # Get the status for 'choose_pin'
                choose_pin_status = next((item["choose_pin"]["status"] for item in account_status if "choose_pin" in item), None)
                
                
                #Check if account PIN has not already been set
                if not choose_pin_status:
                    Log.info(f"{log_tag}[{client_ip}][{username}][{device_id}] Account PIN needs to be set by the primary device.")
                    return jsonify({
                        "success": False,
                        "status_code": HTTP_STATUS_CODES["ACCOUNT_PIN_MUST_BE_SET_BY_PRIMARY_DEVICE"],
                        "required_field": 'pin',
                        "message": 'Account PIN needs to be set by the primary device.',
                        "message_to_show": "Account PIN has not been set. Kindly use the device you used in creating the account to set the PIN. Please contact support for more information.",
                    }), HTTP_STATUS_CODES["BAD_REQUEST"]
                
                try:
                    ########### CONFIRM PIN##############################
                    validate_pin_response, status = confirm_pin(subscriber_id, item_data.get("pin"), account_type="subscriber")
                    validate_pin_response_json = validate_pin_response.get_json()
                    
                    if status == 400 or status == 500 or status == 404:
                        error_message = validate_pin_response_json.get("message")
                        Log.info(f"{log_tag} Validate PIN failed. {error_message}")
                        Log.info(f"{log_tag} status: {status}")
                        Log.info(f"{log_tag} validate_pin_response_json: {validate_pin_response_json}")
                        return jsonify(validate_pin_response_json)
                    elif status != 200:
                        error_message = validate_pin_response_json.get("message")
                        Log.info(f"{log_tag} Validate PIN failed. {error_message}")
                        Log.info(f"{log_tag} status: {status}")
                        Log.info(f"{log_tag} validate_pin_response_json: {validate_pin_response_json}")
                        return jsonify(validate_pin_response_json)
                    ########## CONFIRM PIN##############################
                    
                    elif status == 200:
                        #add the current device to the list of devices for the user 
                        Log.info(f"{log_tag}[{client_ip}][{username}][{device_id}] Add the current device to the list of devices for the user.")
                        
                        is_pin_confirmed = True 

                        try:
                            update_device = User.add_device_by_agent_or_subscriber(
                                subscriber_id=subscriber_id,
                                device_id=item_data.get("device_id"),
                                ip_address=str(client_ip)
                            )
                            Log.info(f"{log_tag}[{client_ip}][{username}][{device_id}] update_device: {update_device}")
                        except Exception as e:
                            Log.info(f"{log_tag}[{client_ip}][{username}][{device_id}] error updating user devices: {str(e)}")
                        
                        try:
                            update_location = User.add_location_by_agent_or_subscriber(
                                subscriber_id=subscriber_id,
                                latitude=location_obj.get("latitude"),
                                longitude=location_obj.get("longitude"),
                            )
                            Log.info(f"{log_tag}[{client_ip}][{username}][{location_obj}] update_location: {update_location}")
                        except Exception as e:
                            Log.info(f"{log_tag}[{client_ip}][{username}][{location_obj}] error updating user devices: {str(e)}")
                    
                except Exception as e:
                    Log.info(f"{log_tag}[{client_ip}] An error occurred while verifying PIN: {str(e)}") 
            
            #check if it's a new device and yet PIN is not confirmed
            if not is_devices_exists and item_data.get("pin") is not None and not is_pin_confirmed:
                Log.info(f"{log_tag}[{client_ip}][{username}][{device_id}] PIN confirmation is required for new devices.")
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                    "message": 'PIN confirmation is required for new devices.',
                    "message_to_show": "PIN confirmation is required for new devices. Please contact support for more information.",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            
            
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
            if (username == automated_test_username) or (app_mode =='development'):
                automated_test_otp = os.getenv("AUTOMATED_TEST_OTP")
                
                pin = automated_test_otp
                
                message = f'Your Zeepay security code is {pin} and expires in 5 minutes. If you did not initiate this, DO NOT APPROVE IT.'
                redisKey = f'subscriber_otp_token_{username}'
                set_redis_with_expiry(redisKey, 300, pin)
            
                set_redis_with_expiry("automate_test_username", 300, username)
                set_redis_with_expiry("otp_token_automated_test", 300, pin)
                
                Log.info(f"{log_tag}[{client_ip}][{username}][{pin}] AUTOMATED TESTING OTP")
                Log.info(f"{log_tag}[{client_ip}][{username}][{pin}] OTP has been sent")
                return jsonify({
                    "success": True,
                    "status_code": HTTP_STATUS_CODES["OK"],
                    "device_checksum": str.upper(device_hashed),
                    "message": "OTP has been sent",
                }), HTTP_STATUS_CODES["OK"]
                # needed for automated testing
            else:
                pin = generate_otp()
                message = f'Your Zeepay security code is {pin} and expires in 5 minutes. If you did not initiate this, DO NOT APPROVE IT.'
                redisKey = f'subscriber_otp_token_{username}'
                set_redis_with_expiry(redisKey, 300, pin)
            
                Log.info(f"{log_tag}[{client_ip}][{username}][{pin}] sending OTP")
                response = shop_service.send_sms(username, message, tenant_id)
                Log.info(f"{log_tag}[{client_ip}] SMS response: {response}")
                
                # return response
                if response.get("status_code") == 500:
                    return jsonify(response)
                
                if response and response.get("status") == "success":
                    Log.info(f"{log_tag}[{client_ip}][{username}] OTP has been sent")
                    return jsonify({
                        "success": True,
                        "status_code": HTTP_STATUS_CODES["OK"],
                        "device_checksum": str.upper(device_hashed),
                        "message": "OTP has been sent",
                    }), HTTP_STATUS_CODES["OK"]
                    
                else:
                    Log.info(f"{log_tag}[{client_ip}][{username}] Could not send OTP")
                    return prepared_response(False, "BAD_REQUEST", f"Could not send OTP")
                
                 
                
        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] An unexpected error occurred: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {str(e)}")
 
 
 # -----------------------SUBSCRIBER LOGIN EXECUTE-----------------------------------------
@blp_subscriber_login.route("/login/execute", methods=["POST"])
class SubscriberLoginExecuteResource(MethodView):
     # POST Agent (Login agent)
    @blp_subscriber_login.arguments(SubscriberLoginExecSchema, location="form")
    @blp_subscriber_login.response(200, SubscriberLoginExecSchema)
    @blp_subscriber_login.doc(
        summary="Verify OTP and complete subscriber login",
        description="""
            Verify the one-time password (OTP) to complete login for a subscriber.
            Requires `username` (phone), `country_iso_2` (ISO2), `otp` (6 characters),
            and `device_checksum` (device integrity/fingerprint token).

            Returns an access token and user details, including account verification progress.
        """,
        requestBody={
            "required": True,
            "content": {
                "application/json": {
                    "schema": SubscriberLoginExecSchema,
                    "example": {
                        "username": "07568983843",
                        "country_iso_2": "gb",
                        "otp": "123456",
                        "device_checksum": "b7f5e1c2a9d0f8..."
                    }
                },
                "multipart/form-data": {
                    "schema": SubscriberLoginExecSchema,
                    "example": {
                        "username": "07568983843",
                        "country_iso_2": "gb",
                        "otp": "123456",
                        "device_checksum": "b7f5e1c2a9d0f8..."
                    }
                }
            }
        },
        responses={
            200: {
                "description": "Login successful. Access token and user details returned.",
                "content": {
                    "application/json": {
                        "examples": {
                            "with_middle_name": {
                                "summary": "Middle name present with full account status",
                                "value": {
                                    "access_token": "eyJhbGciOi...",
                                    "token_type": "Bearer",
                                    "expires_in": 3600,
                                    "first_name": "James",
                                    "middle_name": "Kwame",
                                    "last_name": "Bond",
                                    "business_id": "683cc90dd2dbb331bb9d84a8",
                                    "account_status": [
                                        {
                                            "account_verified": {
                                                "created_at": "2025-10-13 09:32:55.822051",
                                                "ip_address": "127.0.0.1",
                                                "status": True
                                            }
                                        },
                                        {
                                            "choose_pin": {
                                                "created_at": "2025-10-13T09:34:16.938014",
                                                "ip_address": "127.0.0.1",
                                                "status": True
                                            }
                                        },
                                        {
                                            "basic_kyc_updated": {
                                                "created_at": "2025-10-13T09:34:28.917965",
                                                "ip_address": "127.0.0.1",
                                                "status": True
                                            }
                                        },
                                        {
                                            "account_email_verified": {
                                                "created_at": "2025-10-13T09:35:12.367644",
                                                "ip_address": "127.0.0.1",
                                                "status": True
                                            }
                                        },
                                        {
                                            "uploaded_id_front": {
                                                "created_at": "2025-10-13T09:35:26.993659",
                                                "ip_address": "127.0.0.1",
                                                "status": True
                                            }
                                        },
                                        {
                                            "uploaded_id_back": {
                                                "created_at": "2025-10-13T09:35:27.184511",
                                                "ip_address": "127.0.0.1",
                                                "status": True
                                            }
                                        },
                                        {
                                            "uploaded_id_utility": {
                                                "created_at": "2025-10-13T09:35:27.372983",
                                                "ip_address": "127.0.0.1",
                                                "status": True
                                            }
                                        },
                                        {
                                            "onboarding_completed": {
                                                "status": False
                                            }
                                        }
                                    ]
                                }
                            },
                            "without_middle_name": {
                                "summary": "Middle name omitted when null",
                                "value": {
                                    "access_token": "eyJhbGciOi...",
                                    "token_type": "Bearer",
                                    "expires_in": 3600,
                                    "first_name": "James",
                                    "last_name": "Bond",
                                    "business_id": "683cc90dd2dbb331bb9d84a8",
                                    "account_status": [
                                        {
                                            "account_verified": {
                                                "created_at": "2025-10-13 09:32:55.822051",
                                                "ip_address": "127.0.0.1",
                                                "status": True
                                            }
                                        },
                                        {
                                            "onboarding_completed": {
                                                "status": False
                                            }
                                        }
                                    ]
                                }
                            }
                        }
                    }
                }
            },
            400: {
                "description": "Invalid request data (malformed or missing fields).",
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
                "description": "Unauthorized or invalid/expired OTP.",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Invalid OTP"
                        }
                    }
                }
            },
            422: {
                "description": "Validation error (e.g., OTP not 6 chars, bad ISO2, missing device checksum).",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 422,
                            "errors": {
                                "otp": ["OTP must be 6 characters long"],
                                "country_iso_2": ["Invalid Country ISO2"],
                                "device_checksum": ["Device Checksum is required"]
                            }
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
        log_tag = '[subscriber_login.py][SubscriberLoginExecuteResource][post]'
        """Handle the POST request to execute agent login process."""
        client_ip = request.remote_addr
        subscriber_id = None
        subscriber = {}
        
        try:
            country_iso_2 = item_data.get("country_iso_2")
            country_iso_2_upper = str.upper(country_iso_2)
            
            username = validate_and_format_phone_number(item_data.get("username"), country_iso_2_upper)
            
            if username is None:
                Log.info(f"{log_tag} Invalid phone number")
                return prepared_response(False, "BAD_REQUEST", f"Invalid phone number")
            
            
            # Check if the subscriber exists before attempting to login
            try:
                subscriber = Subscriber.get_by_username(username)
            except Exception as e:
                Log.info(f"{log_tag}[{client_ip}] error retrieving subscriber: {str(e)}")
                
            
            Log.info(f"{log_tag}[{client_ip}] checking if subscriber already exists")
            if not subscriber:
                Log.info(f"{log_tag}[{client_ip}] subscriber do not exists")
                return prepared_response(False, "NOT_FOUND", f"Account not found.")
                
            try:
                Log.info(f"{log_tag}[{client_ip}] initiating verify otp for: {username} ")
                    
                otp = item_data.get("otp")
        
                redisKey = f'subscriber_otp_token_{username}'
                
                token_byte_string = get_redis(redisKey)
                
                if not token_byte_string:
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
                
                subscriber_id = str(subscriber.get("_id"))
                
                #check device checksum is not tempered
                try:
                    device_checksum = item_data.get("device_checksum", None)
                    device_checksum_hash_transformed = str.lower(device_checksum)
                    Log.info(f"{log_tag} retrieving device information from redis")
                    encrypted_device_info = get_redis(device_checksum_hash_transformed)
                    
                    if encrypted_device_info is None:
                        message = f"The device info has expired or the checksum is invalid. Kindly call the 'login/initiate' endpoint again and ensure the checksum is valid."
                        Log.info(f"{log_tag} {message}")
                        return prepared_response(False, "BAD_REQUEST", f"{message}")
                    
                    decrypted_device_info = decrypt_data(encrypted_device_info)
                    device_details = json.loads(decrypted_device_info)
                    
                    checksum_username = validate_and_format_phone_number(device_details.get("username"), country_iso_2_upper)
                    
                    if username != checksum_username:
                        Log.info(f"{log_tag} Missmatch phone number in checksum payload and the verify phone number.")
                        return prepared_response(False, "BAD_REQUEST", f"We found some inconsistencies in your request.")
                    
                    
                    if device_details is None:
                        Log.info(f"{log_tag} Device Information validation failed.")
                        return prepared_response(False, "BAD_REQUEST", f"Device verification failed.")
                except Exception as e:
                    Log.info(f"{log_tag} error retrieving device from redis: {str(e)}")
                    return prepared_response(False, "BAD_REQUEST", f"An eror ocurred while retrieving device. Error: {str(e)}")

                
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
                    
                
                
            except Exception as e:
                Log.info(f"{log_tag}[{client_ip}] error verifying otp for : {username} and {country_iso_2_upper}: Error: {str(e)}")
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while verifying otp. {str(e)}")
            
            
            
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while verifying otp. {str(e)}")



















  








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
        






