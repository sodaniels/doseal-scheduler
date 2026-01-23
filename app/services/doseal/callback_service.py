from bson import ObjectId
from flask import (
    jsonify
)
import json, os
from ...utils.logger import Log # import logging
from ...utils.essentials import Essensial
from ...utils.json_response import prepared_response
from ...utils.helpers import (
    prepare_credit_transaction_payload, 
    prepare_payment_payload,
    prepare_billpay_payment_payload,
    send_transaction_status_message,
    referral_code_processor,
    update_transaction_with_callback_request,
    split_name
)
from ..wallet_service import (
    place_hold,
    capture_hold,
    release_hold,
    refund_capture,
)
from ...utils.agent_balance_keys import (
    keys_for_funding, 
    keys_for_hold, 
    keys_for_capture, 
    keys_for_release, 
    keys_for_refund
)

from ...models.transaction_model import Transaction
from ..shop_api_service import ShopApiService
from ..gateways.zeepay_payment_gateway_service import ZeepayPaymentGatewayService


class CallbackService: 
    """
    A robust and reusable callback service for interacting with external APIs.
    """
    def __init__(self, code, message, internal_reference, log_tag, timeout=10):
        """
        Initialize the ApiService with a base URL and optional timeout.

        :param base_url: The base URL of the external API.
        :param timeout: Request timeout in seconds (default is 10 seconds).
        """
        self.code = code
        self.message = message
        self.internal_reference = internal_reference
        self.log_tag = log_tag
        self.timeout = timeout
        self.support_line = os.getenv("ZEEMONEY_UK_SUPPORT_LINE")
        
    def dr_callback_processor(self):
        """
        This method process DR callback and create corresponding CR transaction.
        :param code: The status code of the callback payload.
        :param message: The message to of the callback payload.
        :param internal_reference: The reference of the callback.
        """
        code = self.code
        internal_reference = self.internal_reference
        message = self.message
        log_tag = self.log_tag
        
        
        # check if callback contains valid request body
        if code is None or internal_reference is None:
            Log.info(f"{log_tag}[{internal_reference}] invalid callback response")
            return prepared_response(False, "BAD_REQUEST", f"Invalid callback response")
        
        # retrieve transaction based on internal reference
        Log.info(f"{log_tag}[{internal_reference}] retrieving transaction by internal_reference")
        transaction = Transaction.get_by_internal_reference(internal_reference, "Dr")
        if not transaction:
            Log.info(f"{log_tag}[{internal_reference}] Transaction not found")
            return prepared_response(False, "NOT_FOUND", f"Transaction not found")
    
        # retrieve tenant_id from transaction and instantiate shop api service
        tenant_id = transaction.get("tenant_id")
        shop_service = ShopApiService(tenant_id)
        transaction_id = str(transaction.get("_id"))
        business_id = str(transaction.get("business_id"))
        
        # process callback for 400 transactions
        if code == "400":
            Log.info(f"{log_tag}[{internal_reference}] entered 400 block")
            # update transaction with failed callback request
            try:
                update_transaction_with_callback_request(
                    log_tag=log_tag,
                    message=message,
                    code=code,
                    internal_reference=internal_reference,
                    transaction_id=transaction_id
                )
            except Exception as e:
                Log.info(f"{log_tag}[{internal_reference}] error updating transaction callback")
            
            
            hold_id = transaction.get("ledger_hold_id")
            
            #release only when holder_id is present in the case of agents transactions
            if hold_id is not None:
                # run release_hold to release held agent's position since transaction failed.
                try:
                    Log.info(f"{log_tag}[{internal_reference}] running release_hold to release held agent's position since transaction failed")
                    
                    business_id = transaction.get("business_id")
                
                    k = keys_for_release(business_id, hold_id)
                    release_hold(
                        business_id=ObjectId(business_id),
                        hold_id=hold_id,    
                        idempotency_key=k.idem
                    )
                except Exception as e:
                    Log.info(f"{log_tag}[{internal_reference}] error updating transaction callback")
                
                
            # send sms to sender
            sender_account_detail = transaction.get("sender_account")
            
            sender_name = sender_account_detail.get("name")
            sender_account_no = transaction.get("account_no")

            status_messages = {
                "Failed at payment Gateway": f"Sorry {sender_name}, your transaction failed. Call support on {self.support_line}.",
                "Decline": f"Sorry {sender_name}, your transaction was declined. Contact your bank or support: {self.support_line}.",
                "Invalid field": f"Sorry {sender_name}, verify card details. Need help? Call {self.support_line}."
            }

            if message in status_messages:
            
                try:
                    Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] sending transaction failed messsage to sender")
                    response = shop_service.send_sms(sender_account_no, status_messages[message])
                    if response:
                        Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] transaction failed messsage sent to sender succcessfully")
                    else:
                        Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] failed to send transaction failed messsage to sender")
                except Exception:
                    Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] error updating sending message to sender: {str(e)}")
        
        elif str(code) == "200" and transaction.get("transaction_type") == "Dr" and str(transaction.get("transaction_status")) == "411":
            Log.info(f"{log_tag}[{internal_reference}] entered 200 block")     
            
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
            
            # stop the process if preparing credit payload fails
            if tranasction_data is None:
                Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] preparing tranasction_data for cr commit failed")
                return prepared_response(False, "BAD_REQUEST", f"preparing tranasction_data for cr commit failed")   
            

            try:
                Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] committing Cr transaction")
                credit_transaction_obj = Transaction(**tranasction_data)
                commit_cr_transaction_id = credit_transaction_obj.save(processing_callback=True)
                
                # if credit transaction was not created, abort the operation
                if commit_cr_transaction_id is None:
                    Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] Credit transaction was not creating. Aborting the operation.")
                    return prepared_response(False, "BAD_REQUEST", f"Credit transaction was not creating. Aborting the operation.")   
                
                Log.info(f"{log_tag} commit_cr_transaction_id: {commit_cr_transaction_id}")
                
                # update Dr transaction with callback information
                try:
                    transaction_cr_data = dict()
                    update_transaction_dr = None
                    
                    transaction_cr_data["cr_created"] = True
                    transaction_cr_data["status_message"] = message
                    transaction_cr_data["transaction_status"] = code
                    update_transaction_dr = Transaction.update_callback(transaction_id, business_id, **transaction_cr_data)
                    Log.info(f"{log_tag}[{internal_reference}][{transaction_id}] Dr updated with cr_created: {update_transaction_dr}")
                    if update_transaction_dr:
                        Log.info(f"{log_tag}[{internal_reference}][{transaction_id}] Dr updated with cr_created: {update_transaction_dr}")
                except Exception as e:
                    Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] error updating DR with callback information: {str(e)}")

                        
                try:
                    '''Purform Zeepay Cash In to shop
                    credit beneficiary'''
                    
                    zeepay_payment_gateway = ZeepayPaymentGatewayService(tenant_id)
                    
                    request_type = transaction.get("request_type", "")
                    
                    if str.upper(request_type) == 'BILLPAY':
                        #process billpay transactions
                        Log.info(f"{log_tag}[{cr_internal_reference}] processing billpay transaction")
                        payment_payload = prepare_billpay_payment_payload(transaction)
                        
                        beneficiary_account = transaction.get("beneficiary_account")
                        amount_details = transaction.get("amount_details")
                        sender_account = transaction.get("sender_account")
                        sender_names = sender_account.get("name", None)
                        sender_firstname, sender_lastname = split_name(name=sender_names)
                            
                        
                        billerData = {
                            "destination_account": beneficiary_account.get("account_no"),
                            "payer_name": sender_firstname + " " + sender_lastname,
                            "send_country": amount_details.get("sender_country_iso_2"),
                            "send_currency": amount_details.get("sender_currency"),
                            "send_amount": amount_details.get("send_amount"),
                            "receive_amount": amount_details.get("total_receive_amount"),
                            "receive_country": amount_details.get("receiver_country"),
                            "receive_currency": amount_details.get("receive_currency"),
                            "reference": cr_internal_reference,
                            "biller_id": transaction.get("billpay_id"),
                        }
                        
                        shop_service = ShopApiService(tenant_id)
                        
                        beneficiary_id = str(transaction.get("beneficiary_id"))
                        sender_id = str(transaction.get("sender_id"))
                
                        Log.info(f"{log_tag}[{business_id}][{beneficiary_id}][{sender_id}][{commit_cr_transaction_id}] performing billpay validation request")
                        Log.info(f"{log_tag}[{business_id}][{beneficiary_id}][{sender_id}][{commit_cr_transaction_id}] billerRequestData: {billerData}")
                        billpay_response = shop_service.post_billpay_account_validation(billerData)
                        Log.info(f"{log_tag}[{business_id}][{beneficiary_id}][{sender_id}][{commit_cr_transaction_id}] billpay_response: {billpay_response}")
                        
                        if billpay_response.get("zeepay_id"):
                            billpay_tranasction_update = dict()
                            billpay_tranasction_update["billpay_zeepay_id"] = billpay_response.get("zeepay_id")
                            billpay_update_tranaction = Transaction.update(commit_cr_transaction_id, **billpay_tranasction_update)
                            if billpay_update_tranaction:
                                Log.info(f"{log_tag}[{business_id}][{beneficiary_id}][{sender_id}][{commit_cr_transaction_id}] Transaction updated with billpay zeepay_id")
                                
                            billpay_custom_response = dict()
                            
                            billpay_custom_response.update(billpay_response)
                            
                            billpay_custom_response["message"] = "Transaction initiated successfully"
                            billpay_custom_response["code"] = 411
                        
                            return jsonify(billpay_custom_response)
                        
                    else:
                        
                        try:
                            # process non-billpay transactions
                            Log.info(f"{log_tag}[{cr_internal_reference}] processing non-billpay transaction.")
                            
                            payment_payload = prepare_payment_payload(transaction)
                            
                            # if callack transaction payload fails don't proceed
                            if payment_payload is None:
                                Log.info(f"{log_tag}[{internal_reference}][{transaction_id}] preparing payment_payload failed")
                                return prepared_response(False, "BAD_REQUEST", f"preparing payment_payload failed")
                            
                            #proceed to make payment on shop
                            Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] payment_payload: ", payment_payload)
                            
                            try:
                                shop_payment_response = zeepay_payment_gateway.payout(**payment_payload)
                                Log.info(f"{log_tag}[{internal_reference}][{transaction_id}] CR shop_payment_response: {shop_payment_response}" )
                                
                                if shop_payment_response is None:
                                    Log.info(f"{log_tag}[{internal_reference}][{transaction_id}] payment on shop failed")
                                    
                                update_transaction_data = dict()
                                update_transaction_data["zeepay_id"] = str(shop_payment_response.get("zeepay_id")) if shop_payment_response.get("zeepay_id") else ""
                                update_transaction_data["transaction_status"] = shop_payment_response.get("code")
                                update_transaction_data["status_message"] = shop_payment_response.get("message")
                                
                                update_transaction_with_response = Transaction.update_callback(commit_cr_transaction_id, business_id, **update_transaction_data)
                                if update_transaction_with_response:
                                    Log.info(f"{log_tag}[{internal_reference}][{transaction_id}] CR tranaction updated with callback response: ")
                                    
                                '''check if response is 400 and trigger reversal request
                                400 response implies that the transaction failed instantly, hence, 
                                DR has to be updated accordingly.
                                '''
                                if str(shop_payment_response.get("code")) == "400":
                                    Log.info(f"{log_tag}[{cr_internal_reference}] Transaction failed, trigger automatic reversal request")
                                    try:
                                        zeepay_id = transaction.get("zeepay_id")
                                        reason = "Debit worked but credit leg of transaction failed."
                                        transaction_debit_reversal = zeepay_payment_gateway.reverse_transaction(zeepay_id=zeepay_id, reason=reason)
                                        Log.info(f"{log_tag}[{cr_internal_reference}] transaction_debit_reversal: {transaction_debit_reversal} ")
                                        
                                        if str(transaction_debit_reversal.get("code")) == "200":
                                            Log.info(f"{log_tag}[{cr_internal_reference}] transaction reveral was successful")
                                            reversal_transaction_data = dict()
                                            reversal_transaction_data["transaction_status"] = transaction_debit_reversal.get("code")
                                            reversal_transaction_data["status_message"] = transaction_debit_reversal.get("message")
                                            
                                            dr_transaction_id = transaction.get("_id")
                                            
                                            update_transaction_with_response = Transaction.update_callback(
                                                dr_transaction_id, 
                                                business_id, 
                                                **reversal_transaction_data
                                            )   
                                    except Exception as e:
                                        Log.info(f"{log_tag}[{cr_internal_reference}] Transaction reveral failed: {str(e)} ")
                                if str(shop_payment_response.get("code")) == "411":
                                    return jsonify(shop_payment_response)
                                
                                # If DR callback was successful, nothing happens here, 
                                # a callback will for CR will be sent later
                            except Exception as e:
                                Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] error processing payment via Zeepay Gateway: {str(e)}")
                        
                        
                        except Exception as e:
                                Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] error updating transaction with callback: {str(e)}")
                                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"error processing Cr transaction")
                    
                except Exception as e:
                    Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] error initiating payment gateway service: {str(e)}")
                
            except Exception as e:
                Log.error(f"{log_tag}[{internal_reference}][{transaction_id}] error committing Cr transaction: {str(e)}")
            
        return prepared_response(False, "OK", f"Callback processed successfully")
        
    def cr_callback_processor(self, zeepay_id, gateway_id=None):
        """
        This method process CR callback transaction.
        :param code: The status code of the callback payload.
        :param message: The message to of the callback payload.
        :param internal_reference: The reference of the callback.
        """
        code = self.code
        internal_reference = self.internal_reference
        message = self.message
        log_tag = self.log_tag
        
        # check if callback contains valid request body
        if code is None or internal_reference is None or zeepay_id is None:
            Log.info(f"{log_tag}[{internal_reference}] invalid callback response")
            return prepared_response(False, "BAD_REQUEST", f"Invalid callback response")
        
        # retrieve transaction based on internal_reference and transaction type
        Log.info(f"{log_tag}[{internal_reference}] retrieving transaction by internal_reference")
        transaction = Transaction.get_by_internal_reference(internal_reference, "Cr")
        if not transaction:
            Log.info(f"{log_tag}[{internal_reference}] Transaction not found")
            return prepared_response(False, "NOT_FOUND", f"Transaction not found")
        
        
        ledger_release_hold_response = dict()
        
        # retrieve tenant_id from transaction and instantiate shop api service
        tenant_id = transaction.get("tenant_id")
        agent_id = transaction.get("agent_id", None)
        
        shop_service = ShopApiService(tenant_id)
        transaction_id = str(transaction.get("_id"))
        business_id = str(transaction.get("business_id"))
        amount_details = transaction.get("amount_details")
        medium = transaction.get("medium", "")
        payment_mode = transaction.get("payment_mode")
        
        # process callback for 400 transactions
        if str(code) == "400" and transaction.get("transaction_type") == "Cr" and str(transaction.get("transaction_status")) == "411":
            Log.info(f"{log_tag}[{internal_reference}] process entered 400 block")
            
            
            #Retrieve the country code and purform reversal base the countrycode
            sender_country_iso_2 = amount_details.get("sender_country_iso_2")
            
            hold_id = transaction.get("ledger_hold_id")
            
            # run release_hold to release held agent's position since transaction failed.
            if hold_id is not None:
                try:
                    Log.info(f"{log_tag}[{internal_reference}] running release_hold to release held agent's position since transaction failed")

                    k = keys_for_release(business_id, hold_id)
                    ledger_release_hold_response= release_hold(
                        business_id=ObjectId(business_id),
                        hold_id=hold_id,    
                        idempotency_key=k.idem
                    )
                    Log.info(f"{log_tag}[{internal_reference}] ledger_release_hold_response: {ledger_release_hold_response}")
                except Exception as e:
                    Log.info(f"{log_tag}[{internal_reference}] error running release_hold: {str(e)}")
                
            
            zeepay_payment_gateway = ZeepayPaymentGatewayService(tenant_id)
            
            # process agent's position reversal for cash transactions
            if str.lower(medium) == "agent-channel" and str.lower(payment_mode) == "cash":
                # return prepared_response(True, "OK", f"Agent transaction callback")
                try:
                    transaction_data = dict()
                    transaction_data["status_message"] = message
                    transaction_data["transaction_status"] = code
                    transaction_data["status_code"] = code
                    
                    if ledger_release_hold_response.get("status_code") == 200:
                        transaction_data["reversed"] = True
                        
                    # update agent callback_update_transaction
                    update_transaction = Transaction.update_callback(transaction_id, business_id, **transaction_data)
                    Log.info(f"{log_tag} agent update_transaction: {update_transaction}")
                    
                    return prepared_response(True, "OK", f"Callback processed successfully")
                    
                except Exception as e:
                    Log.error(f"{log_tag}[{cr_internal_reference}][{transaction_id}] error running cr callback update for agent: {str(e)}")
            
            
            
            #process reversal for UK
            if str.upper(sender_country_iso_2) == "GB":
            
                Log.info(f"{log_tag}[{internal_reference}] process reversal for UK")
                
                internal_reference_cr = transaction.get("internal_reference")
                ref_segment = internal_reference_cr.split("_")[1]
                dr_internal_reference = f"DR_{ref_segment}"
                
                dr_internal_reference = f"DR_{ref_segment}"
                dr_transaction = Transaction.get_by_internal_reference(dr_internal_reference, "Dr")
                
                dr_zeepay_id = dr_transaction.get("zeepay_id")
                Log.info(f"{log_tag}: processing reversal for {dr_zeepay_id}")
                try:
                    reason = 'Debit worked but credit leg of transaction failed.'
                    reverse_uk_transaction = zeepay_payment_gateway.reverse_transaction(zeepay_id=dr_zeepay_id, reason=reason)
                    Log.info(f"{log_tag}[{internal_reference}] reverse_uk_transaction: {reverse_uk_transaction}")
                    
                except Exception as e:
                    Log.error(f"{log_tag}[{internal_reference}] error processing reversal for UK: {str(e)}")
            else:
                #process reversal for the other corridors
                Log.info(f"{log_tag}[{internal_reference}] process reversal for the other corridors")
            
            
        elif str(code) == "200" and transaction.get("transaction_type") == "Cr" and str(transaction.get("transaction_status")) == "411":
            Log.info(f"{log_tag}[{internal_reference}] entered 200 block")  
                    
            internal_reference_ = transaction.get("internal_reference")
            ref_segment = internal_reference_.split("_")[1]
            cr_internal_reference = f"CR_{ref_segment}"
            
            hold_id = transaction.get("ledger_hold_id")
            
            if hold_id is not None:
                try:
                    # run capture_hold to debit agent's position
                    Log.error(f"{log_tag}[{cr_internal_reference}][{transaction_id}] running capture_hold to debit agent's position")
                    
                    
                    k = keys_for_release(business_id, hold_id)
                    
                    if hold_id is not None:
                        ledger_response = capture_hold(
                            business_id=ObjectId(business_id),
                            hold_id=hold_id,
                            idempotency_key=k.idem
                        )
                        Log.info(f"{log_tag}[{cr_internal_reference}][{transaction_id}] ledger_response: {ledger_response}")
                except Exception as e:
                    Log.error(f"{log_tag}[{cr_internal_reference}][{transaction_id}] error running capture_hold: {str(e)}")
                
            try:
                transaction_data = dict()
                transaction_data["status_message"] = message
                transaction_data["transaction_status"] = code
                transaction_data["status_code"] = code
                
                if zeepay_id:
                    transaction_data["zeepay_id"] = zeepay_id
                    
                if gateway_id:
                    transaction_data["gateway_id"] = gateway_id
                    
                # update callback_update_transaction
                update_transaction = Transaction.update_callback(transaction_id, business_id, **transaction_data)
                Log.info(f"{log_tag} update_transaction: {update_transaction}")
                
            except Exception as e:
                Log.error(f"{log_tag}[{cr_internal_reference}][{transaction_id}] error running callback update: {str(e)}")
                
            # check subscriber promo mechanism
            try:
                amount_details = transaction.get("amount_details")
                promo = amount_details.get("promo")
                
                # checking if promo limit is not reached
                Log.info(f"{log_tag} checking if promo limit is reached")
                if promo and not promo.get("promo_limit_reached"):
                    Log.info(f"{log_tag} Promo limit is not reached")
                    
                    if transaction.get("referrer"):
                        referral_code_processor(
                            created_by=transaction.get("created_by"), 
                            referrer=transaction.get("referrer"),
                            promo=promo
                        )
            except Exception as e:
                Log.info(f"{log_tag} error occurred updating promo: {str(e)}")
        
            
        return prepared_response(True, "OK", f"Callback processed successfully")
