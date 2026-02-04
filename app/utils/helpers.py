from flask import jsonify, g
import re, jwt, os, hmac, json, hashlib, unicodedata, phonenumbers
from datetime import datetime, timedelta
from bson import ObjectId
from phonenumbers import geocoder, carrier, PhoneNumberFormat


from tasks import send_payment_receipt
from ..utils.crypt import decrypt_data, encrypt_data
from ..utils.logger import Log # import logging
from ..utils.generators import generate_internal_reference
from ..services.shop_api_service import ShopApiService
from ..utils.json_response import prepared_response
#models
from ..models.business_model import Token, Business
from ..models.user_model import User

from ..models.subscriber_model import Subscriber
from ..models.superadmin_model import Role
from ..models.transaction_model import Transaction
from ..models.admin.super_superadmin_model import Role
from ..extensions.db import db

from ..constants.service_code import (
    HTTP_STATUS_CODES, SYSTEM_USERS, BUSINESS_FIELDS
)

from ..utils.redis import remove_redis

class Helper:
   @staticmethod
   def isItemExists(tableObject, tableField, fieldValue):
    """
    Check if an item exists in the given collection based on a specific field and value.

    Args:
        tableObject: The MongoDB collection object.
        tableField: The field to check in the collection.
        fieldValue: The value to search for in the specified field.

    Returns:
        bool: True if the item exists, False otherwise.
    """
    if tableObject.find_one({tableField: fieldValue}):
        return True
    return False

   @staticmethod
   def validate_email(email):
    """
    Validates if the provided email address is in a valid format.

    Args:
        email (str): The email address to validate.

    Returns:
        bool: True if valid, False otherwise.
    """
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(email_regex, email))   


def generate_signature(sessionId):
    """
    Generate the `X-HMAC-SIGNATURE` header using HMAC-SHA256.

    :param payload: The request payload (as a dictionary or JSON string).
    :return: Hex-encoded HMAC-SHA256 signature prefixed with 'sha256='.
    """
    VERIFF_SHARED_SECRET_KEY = os.getenv("VERIFF_LIVE_SHARED_SECRET_KEY") if os.getenv("APP_ENV") != "development" else os.getenv("VERIFF_SHARED_SECRET_KEY")

    # Encode the payload as UTF-8 bytes
    sessionId_bytes = sessionId.encode("utf-8")
    key_bytes = VERIFF_SHARED_SECRET_KEY.encode('utf-8')

    # Generate HMAC-SHA256 signature
    hash = hmac.new(key_bytes, sessionId_bytes, hashlib.sha256)
    
    x_hmac_signature = hash.hexdigest()

    return x_hmac_signature

def get_status_by_code(code):
    """
    Maps status codes to their corresponding statuses and returns the status for the given code.

    Args:
        code (int): The status code.

    Returns:
        str: The corresponding status, or None if the code is not found.
    """
    status_mapping = {
        7001: "Started",
        7002: "Submitted",
        9001: "Approved",
        9102: "Declined",
        9103: "Resubmission",
        9104: "Expired/Abandoned",
        9121: "Review"
    }
    return status_mapping.get(code, "Unknown status code")

def get_description_by_code(code):
    """
    Maps status codes to their descriptions and returns the description for the given code.

    Args:
        code (int): The status code.

    Returns:
        str: The corresponding description, or None if the code is not found.
    """
    description_mapping = {
        7001: "The end-user has started their session and landed in our verification flow. No decision is available yet.",
        7002: "The end-user has submitted the requested data in the verification flow. No decision is available yet.",
        9001: "The end-user was verified. The verification process is complete. Accessing the sessionURL again will show the end-user that nothing is to be done here.",
        9102: "The end-user has not been verified. The verification process is complete. Either it was a fraud case or some other severe reason that the end-user could not be verified. You should investigate the session further and read the reason and decision codes. If you decide to give the end-user another try, you need to create a new session.",
        9103: "Resubmission has been requested. The verification process has not been completed. Something was missing from the end-user, and they need to go through the flow once more. The same sessionURL can and should be used for this purpose.",
        9104: "Verification has been expired (a session will expire 7 days after having been created unless it gets a conclusive decision before that). The verification process is complete. If the end-user started the verification process, the response shows abandoned. If the end-user has never accessed the verification, the status will be expired. If you decide to give the end-user another try, you need to create a new session.",
        9121: "Note that this status is sent only when you have implemented the fully automated verification flow. Review status is issued whenever the automation engine could not issue a conclusive decision and the verification session needs to be reviewed by a human on your side."
    }
    return description_mapping.get(code, "Unknown description for the given code")

def prepare_response(verification):
    prepared_response = {}

    # Add keys dynamically if they exist
    keys_to_check = [
        "id", "code", "person", "reason", "status", "comments", "document",
        "reasonCode", "vendorData", "endUserId", "decisionTime", "acceptanceTime",
        "additionalVerifiedData", "riskScore", "riskLabels", "biometricAuthentication"
    ]

    for key in keys_to_check:
        if key in verification:
            prepared_response[key] = verification[key]
            
    # Map the code to its status using get_status_by_code
    if "code" in prepared_response:
        code = prepared_response["code"]
        prepared_response["code"] = get_status_by_code(prepared_response["code"])
        prepared_response["codeDescription"] = get_description_by_code(code)
       

    return prepared_response

# Helper function to generate tokens
def generate_tokens(user, account_type, permissions=None):
    # Secret key for encoding and decoding tokens
    SECRET_KEY = os.getenv("SECRET_KEY")
    # Define the expiration time
    access_token_expiration = timedelta(minutes=3600) #change to 15 minutes
    refresh_token_expiration = timedelta(days=7)
    
    payload_access = {
        'user_id': str(user["_id"]),
        'exp': datetime.utcnow() + access_token_expiration,
        "account_type": account_type,
        "type": decrypt_data(user.get("type"))  if user.get("type") else None,
        'permissions': permissions,  # This includes the permissions dictionary
    }
    
    payload_refresh = {
        'user_id': str(user["_id"]),
        'exp': datetime.utcnow() + refresh_token_expiration,
        "account_type": account_type,
        "type": decrypt_data(user.get("type"))  if user.get("type") else None,
        'permissions': permissions,  # This includes the permissions dictionary
    }
    
    # Create access token (valid for 15 minutes)
    access_token = jwt.encode(payload_access, SECRET_KEY, algorithm='HS256')

    # Create refresh token (valid for 7 days)
    refresh_token = jwt.encode(payload_refresh, SECRET_KEY, algorithm='HS256')

    return access_token, refresh_token

def name_to_slug(name):
    # Convert to lowercase
    name = name.lower()
    
    # Normalize to remove accented characters
    name = unicodedata.normalize('NFD', name)
    name = ''.join([c for c in name if unicodedata.category(c) != 'Mn'])
    
    # Replace spaces with hyphens
    name = name.replace(" ", "-")
    
    # Remove any non-alphanumeric characters (except hyphens)
    name = re.sub(r'[^a-z0-9-]', '', name)
    
    return name

def check_permission(operation, model_name):
    """
    Check if the current user has the necessary permission for the operation.
    """
    # Ensure g.current_user is available
    if not hasattr(g, 'current_user') or not g.current_user:
        raise PermissionError("No current user found for permission check.")

    # Access the permissions dictionary directly
    permissions = g.current_user.get('permissions', {})
    
    # Dynamically fetch permission for the current model
    model_permissions = permissions.get(model_name, [])

    # Check if there are permissions listed for this model
    if model_permissions:
        # The permissions for the model are stored in a list, check the first item
        permission = model_permissions[0]  # Permissions are stored in a list, so we access the first item

        # Check if the operation is allowed (like "edit", "view", etc.)
        if permission.get(operation) == '1':
            return True
        else:
            # Log the denied permission
            Log.info("Permission denied for %s operation on %s model", operation, model_name)

    # Return False if the operation is not allowed or no permissions exist
    return False

def validate_and_format_phone_number(phone_number, country_iso_2):
    """
    Validate the phone number based on the given country ISO 2 code
    and return the phone number in the format: country_code + number without spaces.
    
    Args:
        phone_number (str): The phone number to validate.
        country_iso_2 (str): The 2-letter ISO country code for the phone number.
    
    Returns:
        str: The phone number in the desired format, or None if invalid.
    """
    try:
        # Parse the phone number with the country code
        parsed_number = phonenumbers.parse(phone_number, country_iso_2)
        
        # Check if the number is valid
        if not phonenumbers.is_valid_number(parsed_number):
            print("Invalid phone number.")
            return None
        
        # Get the country code and the national number
        country_code = str(parsed_number.country_code)
        national_number = str(parsed_number.national_number)
        
        # Return the number in the format: 447568983863
        return country_code + national_number
    
    except phonenumbers.phonenumberutil.NumberParseException as e:
        print(f"Error parsing phone number: {e}")
        return None

def split_name(name):
    """A function to split name string into two
    """
    name = name.strip()
    if ' ' in name:
        last_name = re.sub(r'.*\s([\w-]*)$', r'\1', name)
    else:
        last_name = ''

    # Escape special regex characters in last_name
    escaped_last_name = re.escape(last_name)
    first_name = re.sub(escaped_last_name, '', name).strip()

    if len(last_name) < 2:
        last_name = first_name

    return [first_name, last_name]
    
def prepare_credit_transaction_payload(transaction, cr_internal_reference=None):
    transaction_data = dict()
    
    transaction_data["transaction_type"] = "Cr"
    transaction_data["business_id"] = str(transaction.get("business_id"))
    transaction_data["user_id"] = transaction.get("user_id")
    transaction_data["agent_id"] = transaction.get("agent_id")
    transaction_data["tenant_id"] = str(transaction.get("tenant_id"))
    transaction_data["user__id"] = str(transaction.get("user__id"))
    transaction_data["created_by"] = str(transaction.get("created_by"))
    transaction_data["beneficiary_id"] = transaction.get("beneficiary_id")
    transaction_data["sender_id"] = str(transaction.get("sender_id"))

    transaction_data["common_identifier"] = transaction.get("internal_reference")
    transaction_data["internal_reference"] = cr_internal_reference
    transaction_data["beneficiary_account"] = transaction.get("beneficiary_account")
    transaction_data["sender_account"] = transaction.get("sender_account")
    transaction_data["payment_mode"] = transaction.get("payment_mode")
    transaction_data["transaction_status"] = transaction.get("transaction_status")
    transaction_data["status_message"] = transaction.get("status_message")
    transaction_data["amount_details"] = transaction.get("amount_details")
    transaction_data["description"] = transaction.get("description")
    transaction_data["payment_type"] = transaction.get("payment_type")
    
    transaction_data["ledger_account_id"] = transaction.get("ledger_account_id")
    transaction_data["ledger_hold_id"] = transaction.get("ledger_hold_id")
    transaction_data["partner_name"] = transaction.get("partner_name")
    transaction_data["referrer"] = transaction.get("referrer")
    if transaction.get("medium"):
        transaction_data["medium"] = transaction.get("medium")
        
    if transaction.get("billpay_id"):   
        transaction_data["billpay_id"] = transaction.get("billpay_id")
        
    if transaction.get("request_type"):   
        transaction_data["request_type"] = transaction.get("request_type")
        
    
    return transaction_data

def prepare_payment_payload(transaction):
    payment_data = dict()
    
    amount_details = transaction.get("amount_details")
    sender_account = transaction.get("sender_account")
    beneficiary_account = transaction.get("beneficiary_account")
    
    #split sender fullname into firstname and lastname
    sender_names = sender_account.get("name", None)
    if sender_names:
        sender_first_name, sender_last_name = split_name(name=sender_names)
    
    #split beneficiary fullname into firstname and lastname    
    beneficiary_names = beneficiary_account.get("name", None)
    if beneficiary_names:
        receiver_first_name, receiver_last_name = split_name(name=beneficiary_names)
    
    payment_data["amount"] = amount_details.get("total_receive_amount")
    payment_data["send_amount"] = amount_details.get("total_receive_amount")
    payment_data["sender_country"] = amount_details.get("sender_country_iso_2")
    payment_data["sending_currency"] = amount_details.get("sender_currency")
    payment_data["sender_first_name"] = amount_details.get("sender_firstname")
    payment_data["sender_first_name"] = sender_first_name
    payment_data["sender_last_name"] = sender_last_name
    payment_data["receiver_first_name"] = receiver_first_name
    payment_data["receiver_last_name"] = receiver_last_name
    payment_data["service_type"] = str.lower(transaction.get("payment_type"))
    payment_data["receiver_msisdn"] = beneficiary_account.get("recipient_account")
    payment_data["account_number"] = beneficiary_account.get("account_no")
    payment_data["routing_number"] = beneficiary_account.get("routing_number")
    payment_data["receiver_country"] = amount_details.get("recipient_country_iso_2")
    payment_data["receiver_currency"] = amount_details.get("recipient_currency")
    payment_data["transaction_type"] = "Cr"
    payment_data["extr_id"] = transaction.get("internal_reference")
    
    if transaction.get("mno") is not None:
        payment_data["mno"] = transaction.get("mno")
    
    return payment_data

def prepare_billpay_payment_payload(transaction):
    payment_data = dict()
    
    amount_details = transaction.get("amount_details")
    sender_account = transaction.get("sender_account")
    beneficiary_account = transaction.get("beneficiary_account")
    
    #split sender fullname into firstname and lastname
    sender_names = sender_account.get("name", None)
    if sender_names:
        sender_first_name, sender_last_name = split_name(name=sender_names)
    
    #split beneficiary fullname into firstname and lastname    
    beneficiary_names = beneficiary_account.get("name", None)
    if beneficiary_names:
        receiver_first_name, receiver_last_name = split_name(name=beneficiary_names)
    
    payment_data["amount"] = amount_details.get("total_receive_amount")
    payment_data["send_amount"] = amount_details.get("total_receive_amount")
    payment_data["sender_country"] = amount_details.get("sender_country_iso_2")
    payment_data["sending_currency"] = amount_details.get("sender_currency")
    payment_data["sender_first_name"] = amount_details.get("sender_firstname")
    payment_data["sender_first_name"] = sender_first_name
    payment_data["sender_last_name"] = sender_last_name
    payment_data["receiver_first_name"] = receiver_first_name
    payment_data["receiver_last_name"] = receiver_last_name
    payment_data["service_type"] = str.lower(transaction.get("payment_type"))
    payment_data["receiver_msisdn"] = beneficiary_account.get("recipient_account")
    payment_data["account_number"] = beneficiary_account.get("account_no")
    payment_data["routing_number"] = beneficiary_account.get("routing_number")
    payment_data["receiver_country"] = amount_details.get("recipient_country_iso_2")
    payment_data["receiver_currency"] = amount_details.get("recipient_currency")
    payment_data["transaction_type"] = "Cr"
    payment_data["extr_id"] = transaction.get("internal_reference")
    
    if transaction.get("mno") is not None:
        payment_data["mno"] = transaction.get("mno")
    
    return payment_data


def send_transaction_status_message(transaction, callbackResponse, log_tag):
    body = callbackResponse
    support_line = os.getenv("ZEEMONEY_UK_SUPPORT_LINE")
    internal_reference = body.get("reference")
    
    message = body.get("message")
    code = str(body.get("code"))
    
    # retrieve tenant_id from transaction and instantiate shop api service
    tenant_id = transaction.get("tenant_id")
    shop_service = ShopApiService(tenant_id)
    tranaction_id = str(transaction.get("transaction_id"))
    
    # send sms to sender
    sender_account_detail = transaction.get("sender_account")
    sender_name = sender_account_detail.get("name")
    sender_account_no = "+447568983863" #sender_account_detail.get("account_no")
    
    # amount details
    amount_details = transaction.get("amount_details")
    currency = amount_details.get("recipient_currency")
    amount = amount_details.get("total_receive_amount")
    
    # beneficiary details
    beneficiary_account = transaction.get("beneficiary_account", None)
    beneficiary_name = beneficiary_account.get("name", None)
    beneficiary_account_no = beneficiary_account.get("account_no", None)
    
    if code == "400":
        message = f"Hi {sender_name}  your transfer of {currency} {amount} to {beneficiary_name} ({beneficiary_account_no}) could not be processed. The money will be reversed shortly. The transaction reference is: {internal_reference}.  For further assistance, call customer support on {support_line}."
        
        try:
            Log.info(f"{log_tag}[{internal_reference}][{tranaction_id}] sending transaction failed messsage to {sender_account_no}")
            response = shop_service.send_sms(sender_account_no, message)
            if response:
                Log.info(f"{log_tag}[{internal_reference}][{tranaction_id}] transaction failed messsage sent to {sender_account_no} succcessfully")
            else:
                Log.debug(f"{log_tag}[{internal_reference}][{tranaction_id}] failed to send transaction failed messsage to {sender_account_no}")
        except Exception as e:
            Log.error(f"{log_tag}[{internal_reference}][{tranaction_id}] error updating sending message to {sender_account_no}: {str(e)}")

# function to create bearer token for user      
def create_token_response_for_user(user, json_response, account_status=None):
    user_data = {}
    
    user.pop("password", None) # remove password from user object
    
    user_data["business_id"] = str(user['business_id'])
    user_data["user_id"] = str(user.get("_id"))
    user_data["_id"] = str(user.get("_id"))
    user_data["type"] = encrypt_data('Agent')
    user_data["account_type"] = user.get("account_type") if user.get("account_type") else None
    user_data["fullname"] = decrypt_data(user.get("fullname")) if user.get("fullname") else None
    user_data["phone_number"] = decrypt_data(user.get("phone_number")) if user.get("phone_number") else None
    client_id = decrypt_data(user.get("client_id"))
    
    """initilize empty permission dictionary so that the code do not break, as generate_tokens
    expects permissions dictionary
    """
    permissions = {}

    # Generate both access token and refresh token using the user object
    access_token, refresh_token = generate_tokens(user_data, permissions)

    # Save both tokens to the database (with 15 minutes expiration for access token)
    access_token_time_to_live = os.getenv("MTO_LOGIN_ACCESS_TOKEN_TIME_TO_LIVE")
    refresh_time_to_live = os.getenv("MTO_LOGIN_REFRESH_TOKEN_TIME_TO_LIVE")
    Token.create_token(client_id, access_token, refresh_token, access_token_time_to_live, refresh_time_to_live) # change to 900 before prod

    # Token is for 24 hours change to 900 on prod 
    return jsonify({
        "fullname": user_data.get("fullname"),
        "intermex": json_response,
        "mto": {
            "app_token": access_token,
            "token_type": "Bearer",
            "expires_in": access_token_time_to_live,
            "user_id": str(user.get("user_id")),
            "subscriber_id": str(user.get("subscriber_id"))
            },
        "account_status": account_status,
        }) 

# function to commit user to the database
def commit_subscriber_user(log_tag, client_ip, user_data, account_status, subscriber_id):
    # Check if the subscriber already exists based on username
    Log.info(f"{log_tag}[{client_ip}] checking if subscriber already exists")
    if User.get_user_by_username(user_data["username"]) is not None:
        return prepared_response(False, "CONFLICT", f"Account already exists")
                
    Log.info(f"{log_tag}[{client_ip}][committing subscriber into the database")

    user_data["subscriber_id"] = subscriber_id

    # committing subscriber data to db
    user = User(**user_data, )
    user_id = user.save()
    if user_id is not None:
        return str(user_id) 
    else:
        return prepared_response(False, "BAD_REQUEST", f"User could not be created")
 
 #send

#send email after wire is sent
def send_receipt_about_transaction(pin_number, intermex_token, log_tag, subscriber_id):
    base_url = os.getenv("INTERMEX_SENDERS_URL")
    
    imx_api_service = IntermexApiService(client_url=base_url)
    
    headers = {"Authorization": f"Bearer {intermex_token}"}
      
    Log.info(f"{log_tag} initiating [POST] to: {base_url}/api/2/transaction/detail")
    params = {"PinNumber": pin_number}
     
    try:
        Log.info(f"{log_tag} sending email after wire")
        #send email about transaction
        json_response = imx_api_service.get(
            "api/2/transaction/detail",
            headers=headers,
            params=params,
            header_credentials_required=True
        )
        
        if json_response is not None:
            # Log.info(f"{log_tag} json_response: {json_response}")
            
            Log.info(f"{log_tag} retrieving subscriber with ID: {subscriber_id}")
            subscriber = Subscriber.get_by_id(subscriber_id)
            
            if subscriber is not None:
                email = subscriber.get("email")
                
                Log.info(f"{log_tag} sending email to {email}")
                
                try:
                    send_payment_receipt(
                        email='s.daniels@myzeepay.com', #put email here
                        payload=json_response
                    )
                except Exception as e:
                    Log.error(f"{log_tag} error sending email to {email}")
            
            # return subscriber
        
    except Exception as e:
        Log.info(f"{log_tag} error sending email: {str(e)}")

def create_token_response_super_agent(user, agent_id, client_ip, log_tag, agent, redisKey):
    user_data = {}
    permissions = {}
    
    user.pop("password", None) # remove password from user object
                                
    user_data["agent_id"] = str(user['agent_id'])
    
    user_data["business_id"] = str(user['business_id'])
    user_data["user_id"] = str(user.get("_id"))
    user_data["_id"] = str(user.get("_id"))
    
    user_data["role"] = decrypt_data(user.get("role")) if user.get("role") else None
    user_data["type"] = user.get("type") if user.get("type") else None
    user_data["account_type"] = user.get("account_type") if user.get("account_type") else None
    user_data["fullname"] = decrypt_data(user.get("fullname")) if user.get("fullname") else None
    user_data["phone_number"] = decrypt_data(user.get("phone_number")) if user.get("phone_number") else None
    
    client_id = decrypt_data(user.get("client_id"))
    
    try:
        role_id = user.get("role") if user.get("role") else None
        
        role = None
        
        if role_id:
            role =  Role.get_by_id(role_id)
        
        if role:
            # retreive the permissions for the user
            permissions = role.get("permissions")
    except Exception as e:
        Log.info(f"{log_tag}  [post][{client_ip}]: error retreiving permissions for user: {e}")


    # Generate both access token and refresh token using the user object
    access_token, refresh_token = generate_tokens(user_data, permissions)

    # Save both tokens to the database (with 15 minutes expiration for access token)
    access_token_time_to_live = os.getenv("AGENT_LOGIN_ACCESS_TOKEN_TIME_TO_LIVE")
    refresh_time_to_live = os.getenv("AGENT_LOGIN_REFRESH_TOKEN_TIME_TO_LIVE")
    Token.create_token(client_id, access_token, refresh_token, access_token_time_to_live, refresh_time_to_live) # change to 900 before prod
    
    # remove token from redis
    remove_redis(redisKey)
    
    # retrieve agent business name from agent data
    business_name = None
    contact_person_fullname = None
    if agent.get("business"):
        business = decrypt_data(agent.get("business"))
        if len(business) > 0:
            business_name_str = business[0]
            business_name = business_name_str.get("business_name")
            contact_person_fullname = business_name_str.get("contact_person_fullname")
    
    
    # Token is for 24 hours
    if agent_id is not None:
        return jsonify({
            'access_token': access_token, 
            'token_type': 'Bearer', 
            'expires_in': access_token_time_to_live, 
            "business_name": business_name,
            "contact_person_fullname": contact_person_fullname,
            "agent_id": str(agent_id),
            "business_id": str(user.get("business_id"))
            }) # change to 900 on prod
    else:
        return jsonify({
            'access_token': access_token, 
            'token_type': 'Bearer', 
            'expires_in': access_token_time_to_live,
            "business_id": str(user.get("business_id")),
            "fullname": user_data.get("fullname")}) # change to 900 on prod

def create_token_response_admin(user, client_ip, account_type, log_tag):
    
    user_data = {}
    permissions = dict()
    
    user.pop("password", None) 
                                
    # decrypte_full_name = decrypt_data(user.get("fullname"))
    
    business_id = str(user['business_id'])
    cash_session_id = str(user.get("cash_session_id"))
    user_data["business_id"] = business_id
    user_data["user_id"] = str(user.get("_id"))
    user_data["_id"] = str(user.get("_id"))
    
    if cash_session_id:
        user_data["cash_session_id"] = cash_session_id
    
    user_data["role"] = user.get("role") if user.get("role") else None
    user_data["type"] = user.get("type") if user.get("type") else None
    user_data["account_type"] = account_type
    user_data["fullname"] = decrypt_data(user.get("fullname")) if user.get("fullname") else None
    user_data["phone_number"] = decrypt_data(user.get("phone_number")) if user.get("phone_number") else None
    
    
    client_id = decrypt_data(user.get("client_id"))
    
    try:
        role_id = user.get("role") if user.get("role") else None
        
        role = None
        
        if role_id is not None:
            role =  Role.get_by_id(role_id=role_id, business_id=business_id, is_logging_in=True)
            
        
        if role is not None:
            # retreive the permissions for the user
            permissions = role.get("permissions")

    except Exception as e:
        Log.info(f"{log_tag} [helpers.py][{client_ip}]: error retreiving permissions for user: {e}")
    
    # Generate both access token and refresh token using the user object
    access_token, refresh_token = generate_tokens(user_data, account_type, permissions)

    # Save both tokens to the database (with 15 minutes expiration for access token)
    access_token_time_to_live = os.getenv("ADMIN_LOGIN_ACCESS_TOKEN_TIME_TO_LIVE", 900)
    refresh_time_to_live = os.getenv("ADMIN_LOGIN_REFRESH_TOKEN_TIME_TO_LIVE", 900)
    
    Token.create_token(
        client_id, 
        access_token, 
        refresh_token, 
        access_token_time_to_live, 
        refresh_time_to_live
    )
    
    # business = Business.get_business_by_id(user.get("business_id"))
    # business["_id"] = str(business.get("_id"))
    
    # business.pop("user_id", None)
    
    # business_info = dict()
    
    # business_info = {key: safe_decrypt(business.get(key)) for key in BUSINESS_FIELDS}
    
    # Token is for 24 hours
    response = {
        'access_token': access_token, 
        'token_type': 'Bearer', 
        'expires_in': access_token_time_to_live, 
        # "fullname": decrypte_full_name,
        # "admin_id": str(user.get("_id")),
        # "business_id": str(user.get("business_id")),
        # "profile": business_info
    }
    
    
    # response["account_type"] = account_type

    # if account_type in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["BUSINESS_OWNER"]) :
    #     response["permissions"] = {}
    # else:
    #     response["permissions"] = permissions
        
    return jsonify(response)


def safe_decrypt(value, decrypt=decrypt_data):
    """Return decrypted value, or None if missing/empty or decrypt fails."""
    if not value:
        return None
    try:
        out = decrypt(value)
        # Treat empty/whitespace strings as None
        return (out.strip() or None) if isinstance(out, str) else out
    except Exception:
        return None


def create_token_response_system_user(user, subscriber_id, client_ip, log_tag, redisKey):
    user_data = {}
    permissions = {}
    
    user.pop("password", None) # remove password from user object
                                
    user_data["subscriber_id"] = str(subscriber_id)
    
    user_data["business_id"] = str(user['business_id'])
    user_data["user_id"] = str(user.get("_id"))
    user_data["_id"] = str(user.get("_id"))
    user_data["account_status"] = user.get("account_status")
    
    user_data["role"] = str(user.get("role")) if user.get("role") else None
    user_data["type"] = encrypt_data('Subscriber')
    user_data["account_type"] = user.get("account_type") if user.get("account_type") else None
    user_data["first_name"] = user.get("first_name") if user.get("first_name") else None
    user_data["middle_name"] = user.get("middle_name") if user.get("middle_name") else None
    user_data["last_name"] = user.get("last_name") if user.get("last_name") else None
    user_data["phone_number"] = decrypt_data(user.get("phone_number")) if user.get("phone_number") else None
    
    # return jsonify(user_data)
    
    client_id = decrypt_data(user.get("client_id"))

    permissions = {}
    # Generate both access token and refresh token using the user object
    access_token, refresh_token = generate_tokens(user_data, permissions)

    # Save both tokens to the database (with 15 minutes expiration for access token)
    access_token_time_to_live = os.getenv("AGENT_LOGIN_ACCESS_TOKEN_TIME_TO_LIVE")
    refresh_time_to_live = os.getenv("AGENT_LOGIN_REFRESH_TOKEN_TIME_TO_LIVE")
    Token.create_token(client_id, access_token, refresh_token, access_token_time_to_live, refresh_time_to_live) # change to 900 before prod
    
    # remove token from redis
    remove_redis(redisKey)
    
    subscriber_id = str(user.get("subscriber_id"))

    # Token is for 24 hours
    response_data = {
        'access_token': access_token,
        'token_type': 'Bearer',
        'expires_in': access_token_time_to_live,
        'account_status': user_data.get("account_status"),
        'first_name': user_data.get('first_name'),
        'last_name': user_data.get('last_name'),
        'subscriber_id': subscriber_id,
        'business_id': str(user['business_id'])
    }

    # Add middle_name only if not null or empty
    middle_name = user_data.get('middle_name')
    if middle_name:
        response_data['middle_name'] = middle_name
        
    # update last login
    try:
        Log.info(f"{log_tag}[{client_ip}]: updating last login for user: {user['subscriber_id']}")
        last_login_update = User.update_last_login(
            subscriber_id=subscriber_id, 
            ip_address=client_ip
        )
        Log.info(f"{log_tag}[{client_ip}]: last login updated for user: {last_login_update}")
    except Exception as e:
        Log.error(f"{log_tag}[{client_ip}]: error updating last login for user: {e}")   

    return jsonify(response_data)
 # change to 900 on prod 

def referral_code_processor(created_by, referrer, promo):
    log_tag = "[helpers.py][referral_code_processor]"
    
    subscriber_user = User.get_user_by_subscriber_id(referrer)
    # Log.info(f"{log_tag} subscriber_user: {subscriber_user}")
    
    referrer_user_id= subscriber_user.get("_id")
    
    referal_user_update = db.get_collection("users").find_one_and_update(
        {
            "_id": referrer_user_id,
            "referrals": {"$nin": [created_by]}
        },
        {
            "$push": {"referrals": created_by},
            "$set": {"updated_at": datetime.utcnow()}
        },
        return_document=True
    )
    
    if referal_user_update is not None:
        
        # Log.info(f"{log_tag} referal_user_update: {referal_user_update}")
        
        user_promos = referal_user_update.get("promos")
        for i in user_promos:
            if str(promo.get("promo_id")) == i["promo_id"]:
                Log.info(f"current_promo: {i}")
                update_user_promo = User.update_user_promo_mechanism(referrer_user_id, i)
            
def update_transaction_with_callback_request(
    log_tag, 
    internal_reference, 
    transaction_id,
    message=None,
    code =None,
    cr_created=None
):
    try:
        transaction_data = dict()
        
        if message:
            transaction_data["status_message"] = message
            transaction_data["transaction_status"] = code if code else 200
        if cr_created:
            transaction_data["cr_created"] = str(cr_created)
            
        Log.info(f"{log_tag}[{internal_reference}][{transaction_id}] updating transaction with callback")
        update_transaction = Transaction.update(transaction_id, processing_callback=True, **transaction_data)
        if update_transaction:
            Log.info(f"{log_tag}[{internal_reference}][{transaction_id}] updated transaction with callback")
    except Exception as e:
        Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] error updating transaction with callback: {str(e)}")
        

def commit_agent_user(log_tag, client_ip, user_data, email, account_status, agent_id):
    # Check if the agent already exists based on username
    Log.info(f"{log_tag}[{client_ip}] checking if agent already exists")
    if User.get_user_by_email(email):
        # If agent exists, delete the uploaded image before returning conflict response
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["CONFLICT"],
            "message": "Account already exists"
        }), HTTP_STATUS_CODES["CONFLICT"]
                
    Log.info(f"{log_tag}[{client_ip}][committing agent user")
    # committing user data to db
    user = User(**user_data)
    user_client_id = user.save()
    if user_client_id:
        return jsonify({
            "success": True,
            "status_code": HTTP_STATUS_CODES["OK"],
            "agent_id": str(agent_id),
            "message": f"Agent was created",
            "account_status": account_status
        }), HTTP_STATUS_CODES["OK"] 
    else:
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["OK"],
            "message": f"Agent could not be created",
        }), HTTP_STATUS_CODES["OK"]
     
def can_access_business(target_business_id: str | ObjectId) -> bool:
    """
    Check if the authenticated user is allowed to access the given business_id.
    - system_owner: can access any business
    - others: can only access their own business_id
    """
    user_info = g.get("current_user", {}) or {}
    account_type_enc = user_info.get("account_type")
    account_type = account_type_enc if account_type_enc else None

    user_business_id = user_info.get("business_id")

    if isinstance(target_business_id, ObjectId):
        target_id_str = str(target_business_id)
    else:
        target_id_str = str(target_business_id)

    if isinstance(user_business_id, ObjectId):
        user_business_id_str = str(user_business_id)
    else:
        user_business_id_str = str(user_business_id) if user_business_id else None

    # System owner / global super admin can see all businesses
    if account_type in ("system_owner", "super_admin"):
        return True

    # All other users must match business_id
    return user_business_id_str is not None and user_business_id_str == target_id_str

def make_log_tag(file, resource, method, ip, user_id, role, auth_business_id, target_business_id, **kwargs):
    # Base tag
    log_tag = (
        f"[{file}]"
        f"[{resource}]"
        f"[{method}]"
        f"[ip:{ip}]"
        f"[user:{user_id}]"
        f"[role:{role}]"
        f"[auth_business:{auth_business_id}]"
        f"[target_business:{target_business_id}]"
    )

    # Append extra context fields
    for key, value in kwargs.items():
        log_tag += f"[{key}:{value}]"

    return log_tag


def sanitize_device_id(device_id: str, max_length: int = 50) -> str:
    """
    Convert a device_id into a safe Redis key component.
    
    - Strips whitespace
    - Replaces invalid characters with '_'
    - Enforces lowercase
    - Optionally shortens to max_length
    - Fallbacks to 'unknown' if empty after sanitization
    """

    if not device_id:
        return "unknown"

    # ensure string
    device_id = str(device_id).strip()

    # replace any char not A-Z, a-z, 0-9, _ or - with underscore
    device_id = re.sub(r'[^A-Za-z0-9_-]+', '_', device_id)

    # normalize to lowercase
    device_id = device_id.lower()

    # enforce maximum length to avoid huge redis keys
    device_id = device_id[:max_length]

    # fallback if cleaned value is empty
    if not device_id:
        return "unknown"

    return device_id


def resolve_target_business_id(args, kwargs):
    """
    In MethodView, args is typically (self, item_data) for POST with @arguments.
    """
    user = g.get("current_user", {}) or {}
    auth_business_id = str(user.get("business_id"))

    account_type_enc = user.get("account_type")
    role = account_type_enc if account_type_enc else None

    # item_data is usually args[1]
    item_data = args[1] if len(args) > 1 and isinstance(args[1], dict) else {}
    form_business_id = item_data.get("business_id")

    if role in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
        return str(form_business_id)

    return auth_business_id

def resolve_target_business_id_from_payload(payload: dict | None = None):
    user = g.get("current_user", {}) or {}

    auth_business_id = str(user.get("business_id"))
    role = user.get("account_type")

    payload = payload or {}
    form_business_id = payload.get("business_id")

    if role in (SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["SUPER_ADMIN"]) and form_business_id:
        return str(form_business_id)

    return auth_business_id

def build_receipt_sms(p: dict) -> str:
    Log.info("Building SMS receipt message", extra={
        "reference": p.get("reference"),
        "status": p.get("status"),
        "amount": p.get("amount"),
        "currency": p.get("currency")
    })

    status = (p.get("status") or "").upper()
    currency = p.get("currency") or "GHS"

    sms = (
        f"Donation Receipt ({status})\n"
        f"Ref: {p.get('reference','-')}\n"
        f"Amount: {currency} {p.get('amount','0.00')}\n"
        f"Fee: {currency} {p.get('charge','0.00')}\n"
        f"Received: {currency} {p.get('amount_after_charge','0.00')}\n"
        f"TxnID: {p.get('processor_transaction_id','-')}\n"
        f"Date: {p.get('payment_date','-')}\n"
        f"Name: {(p.get('first_name','') + ' ' + p.get('last_name','')).strip() or 'Anonymous'}"
    )

    Log.debug("SMS content built successfully", extra={
        "sms_length": len(sms)
    })

    return sms































