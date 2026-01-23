from flask import (
    request, 
    jsonify, g, 
    redirect, 
    url_for, 
    session
)
from flask_smorest import Blueprint, abort
import os
import uuid
import base64
from bson import ObjectId
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
from ..models.transaction_model import Transaction
from ..utils.logger import Log # import logging
from ..utils.essentials import Essensial
from ..services.shop_api_service import ShopApiService
from ..services.gateways.zeepay_payment_gateway_service import ZeepayPaymentGatewayService
from ..utils.json_response import prepared_response
from ..utils.helpers import (
    prepare_credit_transaction_payload, 
    prepare_payment_payload, 
    send_transaction_status_message,
    referral_code_processor,
    update_transaction_with_callback_request
)
from ..services.wallet_service import (
    place_hold,
    capture_hold,
    release_hold,
    refund_capture,
)
from ..utils.agent_balance_keys import (
    keys_for_funding, 
    keys_for_hold, 
    keys_for_capture, 
    keys_for_release, 
    keys_for_refund
)
from ..services.doseal.callback_service import CallbackService


from ..constants.service_code import (
    HTTP_STATUS_CODES
)

# process volume DR transaction callback
def get_confirm_account_():
    """Returns the list of attempt objects with sessionId = {sessionId}.
    Returns the user-defined statuses data if those have been set in the Veriff environment.

    Args:
        sessionId (String): The ID of the session
    """
    client_ip = request.remote_addr
    auth_value = request.args.get('token')
    return_url = request.args.get('return_url')
    
    try:
        Log.info(f"[sessionsinternal_controller_controller.py][get_confirm_account] IP: {client_ip}")
        user_from_auth = User.get_auth_code(auth_value)
        Log.info(f"user_from_auth: {user_from_auth}")
        
        if user_from_auth:
            
            business = Business.get_business(decrypt_data(user_from_auth.get("client_id")))
            
            Log.info(f"business: {business}")
            
            update_status = User.update_user_status(user_from_auth["email_hashed"])
            
            # Log.info(f"update_status: {update_status}")
            
            if update_status:
                # Redirect to return_url with success status
                Log.info(f"[sessionsinternal_controller_controller.py][get_confirm_account] IP: {client_ip} \t user status update successful")
                
                return_url_from_business = decrypt_data(business.get("return_url"))
                query_params = {"status": "Successful"}
                return_url_payload = generate_return_url_with_payload(return_url_from_business, query_params)
                
                
                return redirect(f"{return_url_payload}")
            else:
                # Redirect to return_url with failed status
                Log.info(f"[sessionsinternal_controller_controller.py][get_confirm_account] IP: {client_ip} \t user status update failed")
                
                query_params = {"status": "Failed"}
                return_url_payload = generate_return_url_with_payload(return_url, query_params)
                return redirect(f"{return_url_payload}")
        else:
            # Redirect to return_url with failed status
            Log.info(f"[sessionsinternal_controller_controller.py][get_confirm_account] IP: {client_ip} \t user status update failed")
            
            query_params = {"status": "Failed", "message": "Registration code expired"}
            return_url_payload = generate_return_url_with_payload(return_url, query_params)
            return redirect(f"{return_url_payload}")
    except Exception as e:
        Log.info(f"[sessionsinternal_controller_controller.py][get_confirm_account][{client_ip}] error : {e}")
        # Redirect to return_url with failed status
        
        query_params = {"status": "Failed", "message": "Registration code expired"}
        return_url_payload = generate_return_url_with_payload(return_url, query_params)
        return redirect(f"{return_url_payload}")
    
# callback to update DR transaction and trigger DR creation
def process_volume_transaction_callback():
    """process volume debit transaction callback 
    """
    
    client_ip = request.remote_addr
    
    log_tag = f'[callback_controller.py][process_volume_transaction_callback][{client_ip}]'
    
    Log.info(f"{log_tag} IP: {request.remote_addr}")
    Log.info(f"{log_tag} Request: {request.json}")
    
    body = request.json
    code = str(body.get("code"))
    message = body.get("message")
    internal_reference = body.get("reference")
    
    #Instantiate callback service with arguments
    callback_service = CallbackService(code, message, internal_reference, log_tag)
    
    #process DR callback service
    return callback_service.dr_callback_processor()
 
# callback to update CR transaction and complete transaction legs
def process_transaction_third_party_callback():
    """process zeepay third party transaction callback 
    """
    
    client_ip = request.remote_addr
    
    log_tag = f'[callback_controller.py][process_transaction_third_party_callback][{client_ip}]'
    
    Log.info(f"{log_tag} IP: {request.remote_addr}")
    Log.info(f"{log_tag} Request: {request.json}")
    
    body = request.json
    internal_reference = body.get("reference")
    code = str(body.get("code"))
    zeepay_id = str(body.get("zeepay_id"))
    message = body.get("message")
    gateway_id = body.get("gateway_id")
    
    #Instantiate callback service with arguments
    callback_service = CallbackService(code, message, internal_reference, log_tag)
    
    #process CR callback service
    return callback_service.cr_callback_processor(zeepay_id, gateway_id)
    
    


#Intermex callbacks
def process_intermex_transaction_callback():
    """process intermex transaction callback 
    """
    
    client_ip = request.remote_addr
    
    log_tag = f'[callback_controller.py][process_intermex_transaction_callback][{client_ip}]'
    
    Log.info(f"{log_tag} IP: {request.remote_addr}")
    
    # verify that the request contain valid key and secret
    app_key = request.headers.get('x-app-key')
    app_secret = request.headers.get('x-app-secret')
    
    server_app_key = os.getenv("INTERMEX_CALLBACK_X_APP_KEY")
    server_app_secret = os.getenv("INTERMEX_CALLBACK_X_APP_SECRET")
    
    if str(app_key) != server_app_key or app_secret != server_app_secret:
        Log.info(f"{log_tag}[{client_ip}][{app_key}] invalid x-app-key or x-app-secret in header")
        return prepared_response(False, "UNAUTHORIZED", f"Unauthorized callback access.")
    
    
    Log.info(f"{log_tag}[{app_key}] Callback requestBody: {request.json}")
    
    body = request.json
    pin_number = body.get("WirePinNumber")
    internal_reference = body.get("reference")
    code = str(body.get("code"))
    zeepay_id = str(body.get("zeepay_id"))
    message = body.get("message")
    support_line = os.getenv("ZEEMONEY_UK_SUPPORT_LINE")
    
    
    # check if callback contains valid request body
    if pin_number is None:
        Log.info(f"{log_tag}[{pin_number}] invalid callback response")
        return prepared_response(False, "BAD_REQUEST", f"Invalid callback response")
    
    Log.info(f"{log_tag}[{app_key}] retrieving callback transaction")
    transaction = Transaction.get_by_pin_number(pin_number)
    
    if transaction is None:
        Log.info(f"{log_tag}[{app_key}] Transaction do not exist")
        return prepared_response(False, "BAD_REQUEST", f"Transaction do not exist")

    transaction_data = dict()
    transaction_data["callback_status"] = 200
    transaction_data["status_message"] = body.get("WireStatusDescription")
    transaction_data["callback_payload"] = json.dumps(body)
    
    transaction_id = transaction.get("_id")
    
    update_transaction = Transaction.update(transaction_id, processing_callback=True, **transaction_data)
    Log.info(f"{log_tag}[{app_key}] Callback transaction updated: {update_transaction}")
    
    #move this to the button
    if update_transaction:
        return callback_dispatched(pin_number, log_tag)

    
    # default callback message
    return callback_default_message()


    # retrieve transaction based on internal_reference and transaction type
    Log.info(f"{log_tag}[{internal_reference}] retrieving transaction by internal_reference")
    transaction = Transaction.get_by_internal_reference(internal_reference, "Cr")
    if not transaction:
        Log.info(f"{log_tag}[{internal_reference}] Transaction not found")
        return prepared_response(False, "NOT_FOUND", f"Transaction not found")
    
    # retrieve tenant_id from transaction and instantiate shop api service
    tenant_id = transaction.get("tenant_id")
    shop_service = ShopApiService(tenant_id)
    transaction_id = str(transaction.get("transaction_id"))
    amount_details = transaction.get("amount_details")
    
    # process callback for 400 transactions
    if code == "400":
        Log.info(f"{log_tag}[{internal_reference}] entered 400 block")
        
        # update transaction with failed callback request
        update_transaction_with_callback_request(
                log_tag=log_tag,
                message=message,
                internal_reference=internal_reference,
                transaction_id=transaction_id
            )
        
        #send sms to sender about transaction failure
        send_transaction_status_message(transaction, body, log_tag)
        
        #Retrieve the country code and purform reversal base the countrycode
        sender_country_iso_2 = amount_details.get("sender_country_iso_2")
        
        #process reversal for UK
        if str.upper(sender_country_iso_2) == "GP":
            Log.info(f"{log_tag}[{internal_reference}] process reversal for UK")
        else:
            #process reversal for the other corridors
            Log.info(f"{log_tag}[{internal_reference}] process reversal for the other corridors")
        
    
    elif code == "200" and transaction.get("transaction_type") == "Dr" and str(transaction.get("transaction_status")) == "411":
        Log.info(f"{log_tag}[{internal_reference}] entered 200 block")          
        # update transaction with succcessful callback request
        update_transaction_with_callback_request(
                log_tag=log_tag,
                message=message,
                internal_reference=internal_reference,
                transaction_id=transaction_id
            )
        
        internal_reference_ = transaction.get("internal_reference")
        ref_segment = internal_reference_.split("_")[1]
        cr_internal_reference = f"CR_{ref_segment}"
        
        
        # check if credit request alreay exists and discard subsequent
        try:
            credit_transaction = Transaction.get_by_internal_reference(cr_internal_reference, "Cr")
            if credit_transaction:
                Log.info(f"{log_tag}[{cr_internal_reference}] Callback already processed.")
                return prepared_response(True, "OK", f"Callback already processed.")
        except Exception as e:
             Log.error(f"{log_tag}[{cr_internal_reference}][{transaction_id}] error retrieving Cr transaction: {str(e)}")
             
        # prepare credit transaction datas
        tranasction_data = prepare_credit_transaction_payload(transaction, cr_internal_reference)
        
        if tranasction_data is not None:
            try:
                Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] committing Cr transaction")
                credit_transaction_obj = Transaction(**tranasction_data)
                commit_cr_transaction_id = credit_transaction_obj.save(processing_callback=True)
                if commit_cr_transaction_id is not None:
                    transaction_cr_data = dict()
                    transaction_cr_data["cr_created"] = "true"
                    update_transaction_dr = Transaction.update(transaction_id, processing_callback=True, **transaction_cr_data)
                    if update_transaction_dr:
                            Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] Dr updated with cr_created: {update_transaction_dr}")
                            
                    #Purform Zeepay Cash In to shop
                    #credit beneficiary
                    
                    zeepay_payment_gateway = ZeepayPaymentGatewayService(tenant_id)
                    
                    service_type = transaction.get("service_type")
                    
                    if service_type and str.upper(service_type) == 'BILLPAY':
                        #process billpay transactions
                        Log.info(f"{log_tag}[{cr_internal_reference}] processing billpay transaction")
                    else:
                        
                        try:
                            # process non-billpay transactions
                            Log.info(f"{log_tag}[{cr_internal_reference}] processing non-billpay transaction.")
                            
                            payment_payload = prepare_payment_payload(transaction)
                            
                            if payment_payload is not None:
                                #proceed to make payment on shop
                                Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] payment_payload: ", payment_payload)
                                
                                shop_payment_response = zeepay_payment_gateway.payout(**payment_payload)
                                
                                if shop_payment_response is not None:
                                    Log.info(f"{log_tag}[{internal_reference}][{transaction_id}] CR payment was sucessful: ", shop_payment_response)
                                    
                                    update_transaction_data = dict()
                                    update_transaction_data["zeepay_id"] = shop_payment_response.get("zeepay_id")
                                    update_transaction_data["transaction_status"] = shop_payment_response.get("code")
                                    update_transaction_data["status_message"] = shop_payment_response.get("message")
                                    update_transaction_with_response = Transaction.update(commit_cr_transaction_id, processing_callback=True, **update_transaction_data)
                                    if update_transaction_with_response:
                                        Log.info(f"{log_tag}[{internal_reference}][{transaction_id}] CR tranaction updated with callback response: ")
                                else:
                                    Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] payment on shop failed")
                            else:
                                Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] preparing payment_payload failed")
                                return prepared_response(False, "BAD_REQUEST", f"preparing payment_payload failed")
                        
                        except Exception as e:
                             Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] error updating transaction with callback: {str(e)}")
                             return prepared_response(False, "INTERNAL_SERVER_ERROR", f"error processing Cr transaction")
                        
            except Exception as e:
                Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] error committing Cr transaction: {str(e)}")
        else:
            Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] preparing tranasction_data for cr commit failed")
            return prepared_response(False, "BAD_REQUEST", f"preparing tranasction_data for cr commit failed")   
    return prepared_response(False, "OK", f"Callback processed successfully")

def callback_dispatched(pin_number, log_tag):
    date = datetime.utcnow().isoformat() + "Z"
    Log.info(f"{log_tag} ", {
        "success": True,
        "message": "Callback dispatched successfully",
        "timestamp": date,
        "pin_number": pin_number,
        "callback_status": "delivered"
    })
    
    return jsonify({
        "success": True,
        "message": "Callback dispatched successfully",
        "timestamp": date,
        "pin_number": pin_number,
        "callback_status": "delivered"
    })
    
def callback_dispatched_alread(pin_number):
    return jsonify({
        "status": False,
        "message": "Callback has already been dispatched"
    })
    
def callback_default_message():
    return jsonify({
        "status": True,
        "message": "Callback dispatched successfully"
    })
    
    
#PAYMENT WEBHOOKS

def process_hubtel_payment_webhook():
    """process hubtel payment webhook
    """
    
    client_ip = request.remote_addr
    
    log_tag = f'[callback_controller.py][process_hubtel_payment_webhook][{client_ip}]'
    
    try:
        data = request.get_json()
        
        # Verify webhook signature (important for security)
        if not verify_mpesa_signature(data):
            return {"status": "error", "message": "Invalid signature"}, 401
        
        # Extract payment details
        payment_status = data.get("status")  # "success" or "failed"
        payment_reference = data.get("TransID")
        amount = float(data.get("TransAmount"))
        
        # Extract metadata (package_id, business_id, etc.)
        metadata = data.get("metadata", {})
        package_id = metadata.get("package_id")
        business_id = metadata.get("business_id")
        user_id = metadata.get("user_id")
        user__id = metadata.get("user__id")
        billing_period = metadata.get("billing_period")
        
        if payment_status == "success":
            # ✅ PAYMENT SUCCESSFUL - CREATE SUBSCRIPTION
            success, subscription_id, error = SubscriptionService.create_subscription(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                package_id=package_id,
                payment_method=PAYMENT_METHODS["MPESA"],
                payment_reference=payment_reference
            )
            
            if success:
                Log.info(f"Subscription created: {subscription_id} via M-Pesa: {payment_reference}")
                
                # Send confirmation email/SMS to user
                send_subscription_confirmation(business_id, subscription_id)
                
                return {"status": "success", "subscription_id": subscription_id}, 200
            else:
                Log.error(f"Failed to create subscription: {error}")
                return {"status": "error", "message": error}, 500
        else:
            # Payment failed
            Log.warning(f"Payment failed: {payment_reference}")
            return {"status": "failed", "message": "Payment was not successful"}, 200
            
    except Exception as e:
        Log.error(f"Webhook error: {str(e)}")
        return {"status": "error", "message": str(e)}, 500

    
    