import time
import json
import os

from flask import jsonify, request, g, current_app
from pymongo.errors import PyMongoError
from typing import Dict, Any
from ...utils.essentials import Essensial
from ...utils.logger import Log # import logging
from ...services.shop_api_service import ShopApiService
from ...services.gateways.volume_payment_gateway_service import VolumePaymentGatewayService
from ...services.gateways.zeepay_payment_gateway_service import ZeepayPaymentGatewayService
from ...models.transaction_model import Transaction
from ...constants.service_code import (
    TRANSACTION_STATUS_CODE, HTTP_STATUS_CODES, 
)
from ...utils.calculation_engine import hash_transaction
from ...utils.crypt import (
    encrypt_data, decrypt_data
)
from ...utils.redis import set_redis_with_expiry
from ...utils.helpers import split_name
from ...utils.json_response import prepared_response
from ...services.wallet_service import place_hold
from ...utils.agent_balance_keys import keys_for_hold
from ...utils.helpers import prepare_payment_payload

from ...services.doseal.callback_service import CallbackService

class GatewayService:
    def __init__(self, tenant_id):
        self.shop_api_service = ShopApiService(tenant_id)
        
    # Agent tranasctions
    def process_transaction_initiate(self, **kwargs):
        log_tag = '[gateway_service.py][process_agents_transaction]'
        client_ip = request.remote_addr
        
        try:
            Log.info(f"{log_tag}[{client_ip}] processing bank transaction INIT")
            
            results = kwargs
            
            # attach access_mode to the payload
            access_mode = g.access_mode
            
            results["access_mode"] = access_mode if access_mode else None
            results["partner_name"] = "InstntMny"
            
            # hash the transaction detail
            transaction_hashed = hash_transaction(results)
            
            # prepare the transaction detail for encryption
            transaction_string = json.dumps(results, sort_keys=True)
            
            #encrypt the transaction details
            encrypted_transaction = encrypt_data(transaction_string)
            
            # store the encrypted transaction in redis using the transaction hash as a key
            set_redis_with_expiry(transaction_hashed, 600, encrypted_transaction)
            
            # prunning results object before sending for confirmation
            results.pop("agent_id", None)
            results.pop("business_id", None)
            results.pop("receive_amount", None)
            results.pop("send_amount", None)
            results.pop("user__id", None)
            results.pop("created_by", None)
            results.pop("subscriber_id", None)
            results.pop("referrer", None)
            results.pop("user_id", None)
            results.pop("fraud_kyc", None)
            
            # prepare transaction INIT response
            response = {
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "message": TRANSACTION_STATUS_CODE["TRANSACTION_INITIALTED"],
                "results": results,
                "checksum": str.upper(transaction_hashed),
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
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                "message": f"An unexpected error occurred processing transaction INIT.",
                "error": str(e)
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
                  
    def execute_transaction_execute(self, **kwargs):
        log_tag = '[gateway_service.py][execute_transaction_execute]'
        client_ip = request.remote_addr
        payment_url = None
        
        
        business_id=kwargs.get("business_id")
        sender_id=kwargs.get("sender_id")
        beneficiary_id=kwargs.get("beneficiary_id")
        agent_id=kwargs.get("agent_id")
        user_id=kwargs.get("user_id")
        user__id=kwargs.get("user__id")
        created_by=kwargs.get("created_by")
        subscriber_id=kwargs.get("subscriber_id")
        
        tenant_id=kwargs.get("tenant_id")
        payment_type=kwargs.get("payment_type")
        mno=kwargs.get("mno")
        source=kwargs.get("source")
        destination=kwargs.get("destination")
        receive_amount=kwargs.get("receive_amount")
        send_amount=kwargs.get("send_amount")
        beneficiary_account=kwargs.get("beneficiary_account")
        sender_account=kwargs.get("sender_account")
        amount_details=kwargs.get("amount_details")
        fraud_kyc=kwargs.get("fraud_kyc")
        payment_mode=kwargs.get("payment_mode")
        description=kwargs.get("description")
        internal_reference=kwargs.get("internal_reference")
        access_mode=kwargs.get("access_mode")
        checksum=kwargs.get("checksum")
        partner_name=kwargs.get("partner_name")
        
        account_details = kwargs.get("sender_account", {})
        username = kwargs.get("username")
        referrer = kwargs.get("referrer", "")
        medium = kwargs.get("medium")
        request_type = kwargs.get("request_type", "")
        billpay_id = kwargs.get("billpay_id", "")
        account_id = kwargs.get("account_id", "")
        
        
        # Check if the transaction already exists based on business_id and phone number
        Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] checking if tranaction already exists")
        if Transaction.check_item_exists(business_id, key="checksum", value=checksum):
            message = f"Transaction with checksum {str.upper(checksum)} already exist. Use the 'payment_url' of the transaction to make payment, otherwise make the 'transaction/initiate' call again."
            Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] [{checksum}]checking if tranaction already exists")
            
            transaction_item = Transaction.get_by_checksum(business_id, key="checksum", value=checksum)
            
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["CONFLICT"],
                "transaction_id": transaction_item,
                "message": f"{message}",
            }), HTTP_STATUS_CODES["CONFLICT"]
            
        #run place_hold to hold the fund so the agent do not over-transact while transaction is pending
        send_amount = amount_details.get("send_amount")
        ledger_account_id = None
        ledger_hold_id = None
        
        # hold the send_amount from the agent's position
        if agent_id is not None:
            try:
                k = keys_for_hold(business_id, agent_id, client_ref=internal_reference, amount=send_amount)
                ledger_response = place_hold(
                    business_id=business_id,
                    agent_id=agent_id,
                    amount=send_amount,     
                    idempotency_key=k.idem,
                    ref=k.ref,
                    purpose=description,
                )
                
                # Agent's position could not be debited
                Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}][{checksum}] ledger_response: {ledger_response}")
                if ledger_response.get("status_code") != 200:
                    Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}][{checksum}] Agent's position couldn't been debited")
                    return prepared_response(False, "BAD_REQUEST", f"Agent's position couldn't been debited")
                    
                ledger_account_id = ledger_response.get("account_id")
                ledger_hold_id = ledger_response.get("hold_id")
                
            except Exception as e:
                Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}][{checksum}] An error occurred while debiting agent's position: {str(e)}")
            
        # define transaction object
        transaction = Transaction(
            tenant_id=tenant_id,
            business_id=business_id,
            user_id=user_id,
            user__id=user__id,
            created_by=created_by,
            beneficiary_id=beneficiary_id,
            partner_name=partner_name,
            sender_id=sender_id,
            agent_id=agent_id,
            account=username,
            beneficiary_account=beneficiary_account,
            sender_account=sender_account,
            payment_type=payment_type,
            amount_details=amount_details,
            fraud_kyc=fraud_kyc,
            mno=mno if mno else None,
            internal_reference=internal_reference,
            description=description,
            payment_mode=payment_mode,
            access_mode=access_mode,
            checksum=checksum,
            ledger_account_id=ledger_account_id,
            ledger_hold_id=ledger_hold_id,
            referrer=referrer,
            medium=medium,
            request_type=request_type,
            billpay_id=billpay_id,
            account_id=account_id,
            transaction_type=TRANSACTION_STATUS_CODE["DEBIT_TRANSACTION"],
            transaction_status=TRANSACTION_STATUS_CODE["PENDING"],
            status_message= TRANSACTION_STATUS_CODE["STATUS_MESSAGE"],
        )
        
        try:
            Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] committing transaction")
            start_time = time.time()
            
            transaction_id = transaction.save()
            
            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] committing transaction completed in {duration:.2f} seconds")
            
            if transaction_id is None:
                Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] Failed to commit transaction")
                return prepared_response(False, "BAD_REQUEST", f"Failed to commit transaction")
            
            
        
            # committed transanction worked
            Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] committed transaction. process to process debit")
            sender_firstname = None
            sender_lastname = None
            
            sender_names = sender_account.get("name", None)
            if sender_names:
                sender_firstname, sender_lastname = split_name(name=sender_names)
               
                
            # ********PROCESSS CARD TRANSACTION******************
            if str.lower(payment_mode) == 'card':
                Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] initiating CARD payment process")
                    
                try:
                    # post transaction to volume
                    payment_payload = {
                        "receiving_country": amount_details.get("recipient_country_iso_2"),
                        "sending_country": amount_details.get("sender_country_iso_2"),
                        "sender_firstname": sender_firstname,
                        "sender_lastname": sender_lastname,
                        "sender_currency": amount_details.get("sender_currency"),
                        "description": description,
                        "sender_phoneNumber": sender_account.get("account_no"),
                        "external_id": internal_reference,
                        "amount": amount_details.get("total_send_amount")
                    }
                    
                    json_response = dict()
                    
                    #retrieve the default processor from env
                    current_processor = os.getenv("CURRENT_PAYMENT_PROCESSOR", "VOLUME")
                    
                    #precess payment using volume gateway
                    if current_processor == "VOLUME":
                        
                        Log.info(f"{log_tag}[{client_ip}]CURRENT PROCESSOR: VOLUME")
                        Log.info(f"{log_tag}[{client_ip}]using VolumePaymentGatewayService to process transaction")
                        payment_processor = VolumePaymentGatewayService(tenant_id)
                        
                        json_response = payment_processor.process_volume_transaction(**payment_payload)
                        
                        Log.info(f"{log_tag}[{client_ip}]json_response: {json_response}")
                        
                        if json_response.get("code") == TRANSACTION_STATUS_CODE["PENDING"]:
                            zeepay_id = json_response.get("zeepay_id")
                            response = {
                                "status_code": json_response.get("code"),
                                "zeepay_id": zeepay_id,
                                "message": "Transaction created. Proceed to load payment page",
                                "payment_url": json_response.get("payment_url"),
                            }
                            
                            # send sms to sender about the payment
                            payment_url = json_response.get("payment_url")
                            
                            
                            sender_account = sender_account.get("account_no")
                            
                            shop_service = ShopApiService(tenant_id)
                            
                            # send message is not billpay
                            if request_type != "billpay" or agent_id is not None:
                                Log.info(f"{log_tag}[{client_ip}][{sender_account}] sending OTP")
                                message = f'You have initiated a transaction using Zeepay Agent Portal. Use the link below to complete the transaction. If you did not make the request, please ignore this message and contact our customer service.\n {payment_url}'
                                response = shop_service.send_sms(sender_account, message, tenant_id)
                                Log.info(f"{log_tag}[{client_ip}] SMS response: {response}")
                                
                                # The SMS could not be sent
                                if str.lower(response.get("status", "")) != "success":
                                    Log.info(f"{log_tag}[{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] An error occurred while sending SMS. Kindly contact support for more information.")
                                    return prepared_response(False, "BAD_REQUEST", f"An error occurred while sending SMS. Kindly contact support for more information.")
                            
                        
                            # Update the transaction with the new data
                            tranasction_update = dict()
                            
                            tranasction_update["payment_url"] = payment_url
                            tranasction_update["zeepay_id"] = zeepay_id
                            
                            try:
                                Log.info(f"{log_tag}[{client_ip}][{zeepay_id}]updading transaction with zeepay_id: {zeepay_id}")
                                update_tranaction = Transaction.update(transaction_id, **tranasction_update)
                                if update_tranaction:
                                    Log.info(f"{log_tag}[{client_ip}]Debit transaction updated successfully")

                                    # only for agents
                                    if agent_id is not None:
                                        #SMS was sent, sending response to the agent.
                                        message_to_show = f"We sent a message to the Sender's mobile phone. Kindly ask them to proceed to make payment to complete this transaction."
                                        response_json = {
                                            "success": True,
                                            "status_code": HTTP_STATUS_CODES["OK"],
                                            "message": "Payment link sent to sender successfully",
                                            "message_to_show": message_to_show
                                        }
                                        Log.info(f"{log_tag}[{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] SMS was sent, sending response to the agent.")
                                        return jsonify(response_json), HTTP_STATUS_CODES["OK"]
                                    else:
                                        #SMS was sent, sending response to the agent.
                                        response_json = {
                                            "success": True,
                                            "status_code": HTTP_STATUS_CODES["OK"],
                                            "payment_url": tranasction_update["payment_url"],
                                            "message": "Payment link generated successfully",
                                        }
                                        Log.info(f"{log_tag}[{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] Payment link generated successfully")
                                        return jsonify(response_json), HTTP_STATUS_CODES["OK"]
                                else:
                                    Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] Failed to update debit transaction")
                                    return prepared_response(False, "BAD_REQUEST", f"debit transaction failed")
                                
                            except Exception as e:
                                Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] error updating transaction: {str(e)}")
                                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"error updating transaction: {str(e)}")
                            
                        else:
                            Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] debit transaction failed: {json_response}")
                            return prepared_response(False, "BAD_REQUEST", f"debit transaction failed")
                        
                    elif current_processor == "TRUST":
                        # process payment with trust
                        Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] CURRENT PROCESSOR: VOLUME")
                        Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] using VolumePaymentGatewayService to process transaction")
                    else:
                        Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] no payment processor set")
                        return prepared_response(False, "BAD_REQUEST", f"No payment processor set")   
                except Exception as e:
                    Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] error processing debit request: {str(e)}")
                    return prepared_response(False, "INTERNAL_SERVER_ERROR", f"error processing debit request: {str(e)}")
                
            # ********PROCESSS CASH TRANSACTION******************
            if str.lower(payment_mode) == 'cash':
                Log.info(f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}] initiating CASH payment process")
                try:
                    
                    log_tag = f"{log_tag}[{client_ip}][{business_id}][{agent_id}][{beneficiary_id}][{sender_id}][{internal_reference}]"
                    
                    #Instantiate callback service with successful callback response 
                    # to finilise the DR and trigger the CR creation
                    callback_service = CallbackService("200", "Transaction Successful", internal_reference, log_tag)
                    
                    #process DR callback service
                    response_json = callback_service.dr_callback_processor()
                    cr_response = response_json.get_json()
                    Log.info(f"{log_tag} cr_response: {cr_response}")
                    
                    if str(cr_response.get("code")) == "411":
                            Log.info(f"{log_tag} Transaction was sent successfully")
                            response_obj = {
                                "status_code": cr_response.get("code"),
                                "message": cr_response.get("message"),
                                "message_to_show": "Transaction has been sent successfully. We'll update you when the status changes.",
                            }
                            
                            if cr_response.get("zeepay_id"):
                                response_obj["zeepay_id"] = cr_response.get("zeepay_id")
                                
                                
                            return jsonify(response_obj), HTTP_STATUS_CODES["OK"]
                        
                    elif str(cr_response.get("code")) == "400":
                        Log.info(f"{log_tag} Transaction failed")
                        return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Transaction failed")
                    
                    else:
                        Log.info(f"{log_tag} Unknown Transaction Status")
                        return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Unknown Transaction Status")
                    
                    
                except Exception as e:
                    Log.info(f"{log_tag}[{client_ip}][{business_id}][{beneficiary_id}][{sender_id}] error processing cash payment request: {str(e)}")
                    return prepared_response(False, "INTERNAL_SERVER_ERROR", f" error processing cash payment request: {str(e)}")
                
             
                
        except PyMongoError as e:
            Log.info(f"{log_tag}[{client_ip}][{agent_id}] error committing transaction: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"pymongo error: error committing transaction: {e}")
        
        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}][{agent_id}] error committing transaction: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred committing transaction: {e}")
    