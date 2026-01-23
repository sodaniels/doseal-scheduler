import time
import json
import os
from datetime import datetime

from flask import jsonify, request, g, current_app
from pymongo.errors import PyMongoError
from typing import Dict, Any
from ....utils.essentials import Essensial
from ....models.admin.sale import Sale
from ....utils.logger import Log # import logging
from ....services.shop_api_service import ShopApiService
from ....services.gateways.volume_payment_gateway_service import VolumePaymentGatewayService
from ....services.gateways.zeepay_payment_gateway_service import ZeepayPaymentGatewayService
from ....models.transaction_model import Transaction
from ....constants.service_code import (
    TRANSACTION_STATUS_CODE, HTTP_STATUS_CODES,
    REQUEST_STATUS_CODE
)

from ....services.pos.sale.sale_service import SaleService

from ....utils.calculation_engine import hash_transaction
from ....utils.crypt import (
    encrypt_data, decrypt_data
)
from ....utils.redis import (
    set_redis_with_expiry, get_redis, remove_redis
)
from ....utils.helpers import split_name
from ....utils.json_response import prepared_response
from ....services.wallet_service import place_hold
from ....utils.agent_balance_keys import keys_for_hold
from ....utils.helpers import (
    prepare_payment_payload, sanitize_device_id
)
from ...pos_ledger_service import (
    place_stock_hold,
    capture_stock_hold,
    release_stock_hold,
    release_expired_stock_holds
)
from ....utils.pos_idempotent_keys import (
    keys_for_stock_hold,
    keys_for_stock_release_expired,
    keys_for_stock_release,
    keys_for_stock_capture
)

from ....services.doseal.callback_service import CallbackService

class GatewayService:
    def __init__(self, tenant_id):
        self.shop_api_service = ShopApiService(tenant_id)
        
    # Initiate cart request
    def process_request_initiate(self, **kwargs):
        log_tag = '[gateway_service.py][process_request_initiate]'
        client_ip = request.remote_addr
        
        try:
            Log.info(f"{log_tag}[{client_ip}] processing bank initial checkout request")
            
            results = kwargs
            
            device_id = sanitize_device_id(results.get("device_id"))
            
            # attach access_mode to the payload
            access_mode = g.access_mode
            
            results["access_mode"] = access_mode if access_mode else None
            
            private_results = dict()
            private_results.update(results)
           
            transaction_hashed_private = hash_transaction(private_results)
            
            private_results["checksum_private"] = transaction_hashed_private
            
            # add curren datetime to the payload
            current_date = datetime.now()
            results["date"] = current_date.strftime("%Y-%m-%d %H:%M:%S")
            
            
            # hash the transaction detail
            transaction_hashed_public = hash_transaction(results)
            
            # prepare the transaction detail for encryption
            transaction_string_private = json.dumps(private_results, sort_keys=True)
            
            #encrypt the transaction details
            encrypted_transaction_private = encrypt_data(transaction_string_private)
            redis_key_string = f"{device_id}_{transaction_hashed_private}"
            # store the encrypted transaction in redis using the transaction hash as a key
            set_redis_with_expiry(redis_key_string, 600, encrypted_transaction_private)
            set_redis_with_expiry(transaction_hashed_public, 600, transaction_hashed_private)
            
            # prunning results object before sending for confirmation
            results.pop("business_id", None)
            results.pop("device_id", None)
            results.pop("sku", None)
            results.pop("date", None)
            results.pop("checksum_private", None)
            
            # prepare transaction INIT response
            response = {
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "message": REQUEST_STATUS_CODE["TRANSACTION_INITIALTED"],
                "results": results,
                "checksum": str.upper(transaction_hashed_public),
                "checksum_private": str.upper(transaction_hashed_private),
			}
            if response:
                Log.info(f"{log_tag}[{client_ip}] Transaction initiated successfully")
                return response
            else:
                Log.info(f"{log_tag}[{client_ip}] error processing transaction INIT")
                return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                    "message": f"error processing transaction INIT",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] Err: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred processing transaction INIT.",
                errors=[str(e)]
            )  

    # Execute cart request
    def execute_request_execute(self, checksum, **kwargs):
        log_tag = '[gateway_service.py][execute_request_execute]'
        client_ip = request.remote_addr
        
        user__id=kwargs.get("user__id")
        admin_id=kwargs.get("user__id")
        user_id=kwargs.get("user_id")
        cashier_id=kwargs.get("cashier_id")
        business_id=kwargs.get("business_id")
        outlet_id=kwargs.get("outlet_id")
        device_id=kwargs.get("device_id")
        customer_id=kwargs.get("customer_id")
        cart=kwargs.get("cart")
        payment_method=kwargs.get("payment_method")
        amount_paid=kwargs.get("amount_paid")
        user__id=kwargs.get("user__id")
        transaction_number=kwargs.get("transaction_number")
        receipt_number=kwargs.get("receipt_number")
        notes=kwargs.get("notes")
        
        discount_type=kwargs.get("discount_type")
        coupon_code=kwargs.get("coupon_code")
        promotion_id=kwargs.get("promotion_id")
        cash_session_id=kwargs.get("cash_session_id")
        
        checksum_private=kwargs.get("checksum_private")
        
        
        
        # Check if the transaction already exists based on business_id and phone number
        Log.info(f"{log_tag}[{client_ip}][{business_id}][{cashier_id}] checking if tranaction already exists")
        if Sale.check_multiple_item_exists(business_id, {"checksum": checksum}):
            message = f"Request with checksum {str.upper(checksum)} already exist."
            Log.info(f"[{client_ip}][{business_id}][{cashier_id}] [{checksum}]checking if tranaction already exists")
            
            return prepared_response(
                status=False,
                status_code="CONFLICT",
                message=f"{message}"
            )
            
        device_id_str = sanitize_device_id(device_id)
        cashier_id_str = sanitize_device_id(cashier_id)
        customer_id_str = sanitize_device_id(customer_id)
        
        hole_redis_key_string = f"{device_id_str}_{cashier_id_str}_{customer_id_str}"
        
        hold_id_encoded = get_redis(hole_redis_key_string)
        
        hold_id = None
        
        if hold_id_encoded:
            hold_id = hold_id_encoded.decode("utf-8")
            Log.info(f"hold_id_encoded: {hold_id}")
            
        #============================================
        #CHECK PAYMENT MODE AND IMPLEMENT ACCORDINGLY
        #============================================
        if str.lower(payment_method) == "cash":
            Log.info(f"{log_tag}[{client_ip}][{business_id}][{cashier_id}] processing CASH payment")
            # Create sale with enhanced schema
            success, sale_id, error, trn_number, rect_number = SaleService.create_sale_from_cart(
                business_id=business_id,
                outlet_id=outlet_id,
                user_id=user_id,
                user__id=user__id,
                cart=cart,
                payment_method=payment_method,
                # Core fields
                cashier_id=cashier_id,
                customer_id=customer_id,
                status=Sale.STATUS_COMPLETED,
                amount_paid=amount_paid,
                # Transaction identifiers
                transaction_number=transaction_number,
                receipt_number=receipt_number,
                # Discount & promotion
                discount_type=discount_type,
                coupon_code=coupon_code,
                promotion_id=promotion_id,
                cash_session_id=cash_session_id,
                device_id=device_id,
                # Metadata
                notes=notes,
                checksum=checksum,
                # Legacy fields
                admin_id=admin_id,
                hold_id=hold_id,
            )

            if not success:
                Log.error(f"{log_tag} SALE_CREATION_FAILED: {error}")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Sale creation failed: {error}",
                    errors=[error]
                )

            Log.info(f"{log_tag} Sale created successfully sale_id={sale_id}")

            #remove redis key
            public_checksum_hash_transformed = sanitize_device_id(checksum)
            device_id_formated = sanitize_device_id(device_id)
                        
            private_redis_key_string = f"{device_id_formated}_{checksum_private}"
            
            
            
            #========================
            # CAPTURE STOCK HOLD
            #=======================
            if hold_id:
                k = keys_for_stock_capture(business_id, hold_id, sale_id=sale_id)
                res = capture_stock_hold(
                    business_id=business_id,
                    hold_id=hold_id,
                    idempotency_key=k.idem,
                    sale_id=sale_id,
                    meta={"channel": "POS"}
                )
                
                #remove keys from redis
                remove_redis(hole_redis_key_string) # hold_id key removed
                remove_redis(private_redis_key_string) #private checksum key removed
                remove_redis(public_checksum_hash_transformed) #public checksum key removed
            
            return prepared_response(
                status=True,
                status_code="CREATED",
                message="Sale completed successfully",
                data={
                    "sale_id": sale_id,
                    "transaction_number": trn_number,
                    "receipt_number": rect_number,
                    "cart": cart
                }
            )
        else:
            #============================================
            #IMPLEMENT A GATEWAY FOR OTHER PAYMENTS
            #============================================
            Log.info(f"{log_tag}[{client_ip}][{business_id}][{cashier_id}] processing CASH payment")
        
