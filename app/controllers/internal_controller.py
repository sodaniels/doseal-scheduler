from flask import (
    request, 
    jsonify, g, 
    redirect, 
    url_for, 
    session
)
from twilio.request_validator import RequestValidator

from flask_smorest import Blueprint, abort
import os
import uuid
import base64
import json
import time
from datetime import datetime
import requests

from tasks import (
    send_contact_sale_registration_email, 
    send_user_registration_email,
    send_new_contact_sale_email,
    send_user_contact_sale_email,
)

from ..resources.doseal.admin.admin_business_resource import token_required
from ..utils.crypt import encrypt_data, decrypt_data, hash_data
from ..utils.generators import generate_return_url_with_payload
from ..constants.service_code import SERVICE_CODE
from .. import db
from ..models.user_model import User
from ..models.business_model import Business
from ..utils.logger import Log # import logging
from ..utils.essentials import Essensial
from ..services.shop_api_service import ShopApiService
from ..utils.json_response import prepared_response

from ..utils.rate_limits import (
    public_read_limiter,
    generic_limiter,
    crud_read_limiter,
    transaction_user_limiter,
)

TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

from ..models.instntmny.messages_model import Message
from ..constants.service_code import (
    HTTP_STATUS_CODES
)

# get confirm account
@public_read_limiter(
    entity_name="account-confirmation",
    limit_str="5 per minute; 20 per hour",
)
def get_confirm_account():
    """Returns the list of attempt objects with sessionId = {sessionId}.
    Returns the user-defined statuses data if those have been set in the Veriff environment.

    Args:
        sessionId (String): The ID of the session
    """
    client_ip = request.remote_addr
    auth_value = request.args.get('token')
    return_url = request.args.get('return_url')
    
    log_tag = f'[internal_controller.py][get_confirm_account]'
    
    # text = 'pziwZlhUjvmMlNa51ZscXuoFnGghKEdiP0jRLKh2ZevRuO/HdQJ7qgi4DxjWZy4BlDHUVqmL3eEXsvbEXSIuj8aReA=='
    
    # encryted_text = decrypt_data(text)
    
    # return jsonify(encryted_text)
    
    try:
        Log.info(f'{log_tag} IP: {client_ip}')
        user_from_auth = User.get_auth_code(auth_value)
        # Log.info(f"user_from_auth: {user_from_auth}")
        
        if user_from_auth.get("_id") is not None:
            
            business = Business.get_business(decrypt_data(user_from_auth.get("client_id")))
     
            Log.info(f"business: {business}")
            
            update_status = User.update_user_status(user_from_auth["email_hashed"])
            
            Log.info(f"update_status: {update_status}")
            
            if update_status:
                # Redirect to return_url with success status
                Log.info(f"{log_tag} \t user status update successful")
                
                try:
                    return_url_from_business = decrypt_data(business.get("return_url"))
                    query_params = {"status": "Successful"}
                    return_url_payload = generate_return_url_with_payload(return_url_from_business, query_params)
                    return redirect(f"{return_url_payload}")
                except Exception as e:
                    Log.info(f"{log_tag} \t error occurred while rending the return_url: {str(e)}")
                
            else:
                # Redirect to return_url with failed status
                Log.info(f"{log_tag} IP: {client_ip} \t user status update failed")
                
                query_params = {"status": "Failed"}
                return_url_payload = generate_return_url_with_payload(return_url, query_params)
                return redirect(f"{return_url_payload}")
        else:
            # Redirect to return_url with failed status
            Log.info(f"{log_tag} IP: {client_ip} \t user status update failed")
            
            query_params = {"status": "Failed", "message": "Registration code expired"}
            return_url_payload = generate_return_url_with_payload(return_url, query_params)
            return redirect(f"{return_url_payload}")
    except Exception as e:
        Log.info(f"{log_tag}[{client_ip}] error : {e}")
        # Redirect to return_url with failed status
        
        query_params = {"status": "Failed", "message": "Registration code expired"}
        return_url_payload = generate_return_url_with_payload(return_url, query_params)
        return redirect(f"{return_url_payload}")

# get countries
@public_read_limiter(
    entity_name="countries",
    limit_str="30 per minute; 300 per hour",
)
def get_countries():
    """Returns the list of countries.
    
    """
    client_ip = request.remote_addr
    
    # Check if x-app-ky header is present and valid
    app_key = request.headers.get('x-app-key')
    server_app_key = os.getenv("X_APP_KEY")
    
    if app_key != server_app_key:
        Log.info(f"[internal_controller.py][get_countries][{client_ip}] invalid x-app-ky header")
        return prepared_response(
            status=False,
            status_code="UNAUTHORIZED",
        )
    
    try:
        Log.info(f"[internal_controller.py][get_countries] retrieving a list of countries IP: {client_ip}")
        countries = Essensial.countries()
       
        if countries:
            results = []
            for country in countries:
                country["_id"] = str(country["_id"])
                results.append(country)
        
            response = {
                "success": True,
                "status_code": 200,
                "data": results
            }
            return jsonify(response)
         
        else:
            response = {
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "Failed to get countries"
            }
            return jsonify(response), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
    except Exception as e:
        Log.info(f"[internal_controller.py][get_countries][{client_ip}] error : {e}")
        return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": f"Failed to retreive countries: {str(e)}"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# get twilio webhook
@generic_limiter(
    entity_name="twilio-webhook",
    limit_str="100 per minute; 1000 per hour",
    methods=["POST"],
)
def twilio_status_webhook():
    # --- Verify Twilio signature (strongly recommended) ---
    signature = request.headers.get("X-Twilio-Signature", "")
    validator = RequestValidator(TWILIO_AUTH_TOKEN or "")
    # NOTE: ensure your reverse proxy forwards original proto/host so request.url matches what Twilio hit
    if TWILIO_AUTH_TOKEN and not validator.validate(request.url, request.form, signature):
        Log.info("[twilio-status] invalid signature")
        abort(403)

    # Twilio posts application/x-www-form-urlencoded
    payload = request.form.to_dict(flat=True)
    
    Log.info(f"[internal_controller.py][twilio_status_webhook] callback_payload: {payload}")

    sid = payload.get("MessageSid") or payload.get("SmsSid")
    tw_status = (payload.get("MessageStatus") or payload.get("SmsStatus") or "").lower()

    updates = {
        # internal 3-state
        "status": ("failed" if tw_status in ("failed", "undelivered") else "dispatched"),
        # raw delivery status
        "delivery_status": tw_status,
        "contact": payload.get("To"),
        "error_code": payload.get("ErrorCode"),
        "error_message": payload.get("ErrorMessage"),
        "price": payload.get("Price"),
        "price_unit": payload.get("PriceUnit"),
        "num_segments": payload.get("NumSegments"),
    }

    ok = Message.update_by_sid(sid=sid, **updates)
    if not ok:
        Log.info(f"[internal_controller.py][twilio_status_webhook] no parent matched for SID={sid}. "
                f"Ensure you add the SID to the parent doc’s 'sids' array during send.")
        
    return ("", 204)

#get banks list
@crud_read_limiter(
    entity_name="banks",
    limit_str="60 per minute; 600 per hour",
)
@token_required
def get_banks():
    """Returns the list of banks.
    Args:
        business_id (String): The Business ID of the session
    """
    client_ip = request.remote_addr
    user_info = g.get("current_user", {})
    user_id = user_info.get("user_id")
    business_id = user_info.get("business_id")
    
    Log.info(f"[internal_controller.py][get_banks][{user_id}][{business_id}][{client_ip}]\t getting banks list")

    try:
        Log.info(f"[internal_controller.py][get_countries] retrieving a list of countries IP: {client_ip}")
        countries = Essensial.countries()
       
        if countries:
            results = []
            for country in countries:
                country["_id"] = str(country["_id"])
                results.append(country)
        
            response = {
                "success": True,
                "status_code": 200,
                "data": results
            }
            return jsonify(response)
         
        else:
            response = {
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "Failed to get countries"
            }
            return jsonify(response), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
    except Exception as e:
        Log.info(f"[internal_controller.py][get_countries][{client_ip}] error : {e}")
        return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": f"Failed to retreive countries: {str(e)}"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# get countries
@public_read_limiter(
    entity_name="tenants",
    limit_str="30 per minute; 300 per hour",
)
def get_tenants():
    """Returns the list of countries.
    
    """
    client_ip = request.remote_addr
    
    # Check if x-app-ky header is present and valid
    app_key = request.headers.get('x-app-key')
    server_app_key = os.getenv("X_APP_KEY")
    
    if app_key != server_app_key:
        Log.info(f"[internal_controller.py][get_countries][{client_ip}] invalid x-app-ky header")
        
        return prepared_response(
            status=False,
            status_code="UNAUTHORIZED",
        )
    
    try:
        Log.info(f"[internal_controller.py][get_countries] retrieving a list of countries IP: {client_ip}")
        tenants = Essensial.tenants()
       
        if tenants:
            results = []
            for country in tenants:
                country["_id"] = str(country["_id"])
                results.append(country)
        
            response = {
                "success": True,
                "status_code": 200,
                "data": results
            }
            return jsonify(response)
         
        else:
            response = {
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": "Failed to get countries"
            }
            return jsonify(response), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
    except Exception as e:
        Log.info(f"[internal_controller.py][get_countries][{client_ip}] error : {e}")
        return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": f"Failed to retreive countries: {str(e)}"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


@transaction_user_limiter(
    entity_name="sms",
    limit_str="5 per minute; 30 per hour; 100 per day",
)
@token_required
def post_send_sms():
    """Send sms .
    
    """
    client_ip = request.remote_addr
 
    try:
        Log.info(f"[internal_controller.py][post_send_sms]IP: {client_ip}")
        
        data = request.get_json()
        
        phone = data.get('phone')
        message = data.get('message')
        tenant_id = data.get('tenant_id')
        
        
        shop_service = ShopApiService(tenant_id)
        
        response = shop_service.send_sms(phone, message)
        Log.info(f"[internal_controller.py][post_send_sms] response ***************")
        Log.info(f"[internal_controller.py][post_send_sms] response {response}")
        return response
       
    except Exception as e:
        Log.info(f"[internal_controller.py][post_send_sms][{client_ip}] error : {e}")
        return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": f"Failed to send sms: {str(e)}"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

@crud_read_limiter(
    entity_name="corridors",
    limit_str="60 per minute; 600 per hour",
)
@token_required
def get_corridors():
    """Returns the list of corridors.
    Args:
        business_id (String): The Business ID of the session
    """
    client_ip = request.remote_addr
    user_info = g.get("current_user", {})
    user_id = user_info.get("user_id")
    business_id = user_info.get("business_id")
    
    log_tag = '[internal_controller.py][get_corridors]'
    
    Log.info(f"{log_tag} [{user_id}][{business_id}][{client_ip}]\t getting banks list")

    try:
        Log.info(f"{log_tag} retrieving a list of corridors IP: {client_ip}")
        corridors = Essensial.corridors()
       
        if corridors:
            results = []
            for corridor in corridors:
                corridor["_id"] = str(corridor["_id"])
                results.append(corridor)
        
            response = {
                "success": True,
                "status_code": 200,
                "data": results
            }
            return jsonify(response)
         
        else:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Failed to get corridors")
    except Exception as e:
        Log.info(f"{log_tag} [{client_ip}] error : {e}")
        return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Failed to retreive corridors: {str(e)}")

