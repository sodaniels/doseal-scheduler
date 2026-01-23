from flask import jsonify, request
from typing import Dict, Any
from ...utils.logger import Log # import logging
from ...utils.essentials import Essensial
from ...models.people_model import Agent
from ...models.subscriber_model import Subscriber
from ...models.beneficiary_model import Beneficiary
from ...models.sender_model import Sender
from ...services.shop_api_service import ShopApiService
from ...models.settings_model import Limit
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.json_response import prepared_response
from ...constants.service_code import (
    HTTP_STATUS_CODES, TRANSACTION_GENERAL_REQUIRED_FIELDS
)
from ...factories.request_factory import RequestFactory
from ...utils.calculate_composite_fee import calculate_composite_fee
from ...utils.transaction_utils import Transaction_amount_wizard
from ...utils.request import RequestMaker
from ...services.gateways.gateway_service import GatewayService
from ...utils.generators import generate_internal_reference



class TransactionGatewayService:
        
    @classmethod   
    def initiate_input(self, body: Dict[str, Any]) -> Dict:
        client_ip = request.remote_addr
        log_tag = f'[transaction_gateway_service.py][initiate_input][{client_ip}]'
        
        transaction_data = body
        
        business_id = str(body.get("business_id"))
        transaction_data["business_id"] = business_id
        transaction_data["user_id"] = body.get("user_id")
        transaction_data["user__id"] = body.get("user__id")
        transaction_data["created_by"] = body.get("user__id")
        transaction_type = transaction_data.get("transaction_type")
        billpay_id = transaction_data.get("billpay_id")
        account_id = transaction_data.get("account_id")
        
        agent_id = str(transaction_data.get("agent_id")) if transaction_data.get("agent_id") else None
        
        sender_currency = None
        tenant_id = None
        current_rate = {}
        amount_details={}
        rate = None
        fee = None
        
        payment_mode = transaction_data.get("payment_mode")
            
        internal_reference = generate_internal_reference("DR")
        
        referrer = transaction_data.get("referrer") if transaction_data.get("referrer") else None
            
        
        subscriber_id = str(transaction_data.get("subscriber_id")) if transaction_data.get("subscriber_id") else None
        
    
        # Retrieve user info.
        if agent_id is not None:
            Log.info(f"{log_tag} retrieving agent information")
            try:
                Log.info(f"{log_tag} retrieving user information")
                agent = Agent.get_by_id(agent_id)
                if agent is None:
                    Log.info(f"{log_tag} Agent does not exist")
                    return prepared_response(False, "NOT_FOUND", f"Agent does not exist.")
                
                tenant_id = agent.get("tenant_id")
                transaction_data["tenant_id"] = tenant_id
                transaction_data["sender_phone_number"] = agent.get("username")
                transaction_data["agent_id"] = agent_id
                transaction_data["username"] = agent.get("username")
                transaction_data["user_type"] = "Agent"
                transaction_data["sender_full_name"] = " ".join(
                    filter(None, [agent.get("first_name"), agent.get("middle_name"), agent.get("last_name")])
                )
                
                tenant = Essensial.get_tenant_by_id(tenant_id)
                if tenant:
                    sender_currency = tenant.get("country_currency")
                    transaction_data["sender_currency"] = sender_currency
                    transaction_data["sender_country_iso_2"] = tenant.get("country_iso_2")
                
            except Exception as e:
                Log.info(f"{log_tag} error retrieving agent information: error {str(e)}")
        
        elif subscriber_id is not None:
            # remove unused variables
            transaction_data.pop("agent_id", None)
            
            Log.info(f"{log_tag} entering subscriber block")
            try:
                Log.info(f"{log_tag} retrieving user information")
                subscriber = Subscriber.get_by_id(business_id=business_id, subscriber_id=subscriber_id)
                if subscriber is not None:
                    tenant_id = subscriber.get("tenant_id")
                    transaction_data["tenant_id"] = tenant_id
                    transaction_data["sender_phone_number"] = subscriber.get("username")
                    transaction_data["user_type"] = "Subscriber"
                    transaction_data["sender_full_name"] = " ".join(
                        filter(None, [subscriber.get("first_name"), subscriber.get("middle_name"), subscriber.get("last_name")])
                    )
                    tenant = Essensial.get_tenant_by_id(tenant_id)
                    if tenant:
                        sender_currency = tenant.get("country_currency")
                        transaction_data["sender_currency"] = sender_currency
                        transaction_data["sender_country_iso_2"] = tenant.get("country_iso_2")
                else:
                    return prepared_response(False, "NOT_FOUND", f"Agent does not exist")
            except Exception as e:
                Log.info(f"{log_tag} error retrieving agent information: error {str(e)}")
         
        
        # retrieving beneficiary
        try:
            Log.info(f"{log_tag} retrieving beneficiary information")
            beneficiary = Beneficiary.get_by_id(
                business_id=business_id, 
                beneficiary_id=transaction_data.get("beneficiary_id")
            )
            
            # if not beneficiary exist, return with error message
            if not beneficiary:
                Log.info(f"{log_tag} Beneficiary does not exist.")
                return prepared_response(False, "NOT_FOUND", f"Beneficiary does not exist")
            
            # if beneficiary is found, prepare the transaction payload
            transaction_data['recipient_full_name'] = beneficiary["verified_name"]
            transaction_data['recipient_phone_number'] = beneficiary["recipient_phone_number"]
            transaction_data['recipient_country_iso_2'] = beneficiary["recipient_country_iso2"]
            transaction_data['recipient_currency'] = beneficiary["currency_code"]
            transaction_data['payment_type'] = str.upper(beneficiary["payment_mode"])
            
            payment_type = str.upper(transaction_data.get("payment_type"))
            
            Log.info(f"new payment_type: {payment_type}")
            
            if payment_type == 'BANK':
                transaction_data['bank_name'] = beneficiary["bank_name"]
                transaction_data['account_name'] = beneficiary["account_name"]
                transaction_data['account_number'] = beneficiary["account_number"]
                transaction_data['routing_number'] = beneficiary["routing_number"]
                
            if payment_type == 'WALLET':
                transaction_data['mno'] = beneficiary["mno"]
                
        except Exception as e:
            Log.info(f"{log_tag} error retrieving beneficiary information: {str(e)}")
            
    
        # retrieving sender and add to the payload
        # only for agents have senders
        if agent_id is not None:
            transaction_data['medium'] = "Agent-Channel"
            try:
                Log.info(f"{log_tag} retrieving sender information")
                sender = Sender.get_by_id(transaction_data.get("sender_id"))
                
                if not sender:
                    return prepared_response(False, "NOT_FOUND", f"Sender does not exist")
                
                if sender:
                    transaction_data['sender_full_name'] = sender["full_name"]
                    transaction_data['sender_phone_number'] = sender["phone_number"]
                    transaction_data['sender_address'] = sender["post_code_address"]
                    transaction_data['sender_id'] = str(sender["_id"])
                
            except Exception as e:
                Log.info(f"{log_tag} error retrieving sender information: {str(e)}")
                
        
            # retrieving agent limit  
            try:
                Log.info(f"{log_tag}[{agent_id}] retrieving agent limit")
                transaction_limit = Limit.get_by_business_and_agent_id(business_id, agent_id)
                if transaction_limit:
                    allowed_amount = decrypt_data(transaction_limit.get("amount"))
                    # limit_amount_converted = int(limit_amount)
                    send_amount = transaction_data.get("send_amount")
                    
                    if(int(send_amount) > int(allowed_amount) ):
                        message = f"Transaction exceeds the allowed limit of {sender_currency} {allowed_amount}"
                        return prepared_response(False, "FORBIDDEN", f"{message}")
                        
            except Exception as e:
                Log.info(f"{log_tag}[{agent_id}] error retrieving agent limit: {str(e)}")
          
          
        try:
            # calculating composite fee
            Log.info(f"{log_tag} calculating composite fee")
            transaction_fee = calculate_composite_fee(transaction_data['recipient_currency'], transaction_data['send_amount'], transaction_type)
            
            if transaction_fee is not None:
                fee = transaction_fee
        except Exception as e:
            Log.info(f"{log_tag} error calculating composite fee: {str(e)}")

      
        try:
            shop_service = ShopApiService(tenant_id)
            
            from_currency = transaction_data.get("sender_currency")
            to_currency = transaction_data.get("recipient_currency")
            account_type = transaction_data.get("payment_type")
            send_amount = transaction_data.get("send_amount")
            user_type = transaction_data.get("user_type")
            
            # retrieving rate
            if from_currency and to_currency and account_type:
                Log.info(f"{log_tag}[{agent_id}] retrieving rate for {from_currency} and {to_currency}")
                rate = shop_service.get_rates(
                    from_currency=from_currency, 
                    to_currency=to_currency, 
                    account_type=account_type
                )
                if rate:
                    if rate.get("code") == 403:
                        return jsonify(rate)
                    current_rate = rate["rates"]["rate"]
                    Log.info(f"{log_tag} current rate for {from_currency} and {to_currency} :{current_rate}")
        except Exception as e:
            Log.info(f"{log_tag} error has occurred while retrieving rate: {str(e)}")
            
        
            
        if from_currency and to_currency and current_rate and user_type:
        
            amount_details = Transaction_amount_wizard.create(
                sender_currency=from_currency,
                recipient_currency=to_currency,
                send_amount=send_amount,
                fee=fee,
                rate=current_rate,
                user_type=user_type,
                business_id=business_id,
                subscriber_id=subscriber_id,
                transaction_type=transaction_type
            )
            transaction_data.pop("send_amount")
            
            if transaction_type == "billpay":
                amount_details["receive_currency"] = str.upper(beneficiary.get("currency_code"))
                amount_details["receiver_country"] = str.upper(beneficiary.get("recipient_country_iso2"))
            
            # add sender and recipient countries to amount_detials object
            amount_details["sender_country_iso_2"] = transaction_data["sender_country_iso_2"]
            amount_details["recipient_country_iso_2"] = transaction_data["recipient_country_iso_2"]
            
        transaction_data["amount_details"] = amount_details
        
        
        try:
            # prepare the transaction request in the factory
            transaction_request = RequestFactory.make_transaction(transaction_data)
            
            
            
            # prepare transaction failed
            if transaction_request is None:
                Log.info(f"{log_tag} preparing transaction request failed") 
                return prepared_response(False, "BAD_REQUEST", f"preparing transaction request failed")
                
            # prepared requests
            tenant_id = RequestMaker.get_tenant_id(transaction_request)
            payment_type = RequestMaker.get_payment_type(transaction_request)
            source = RequestMaker.get_source(transaction_request)
            destination = RequestMaker.get_destination(transaction_request)
            receive_amount = RequestMaker.get_receive_amount(transaction_request)
            send_amount = RequestMaker.get_send_amount(transaction_request)
            beneficiary_account = RequestMaker.get_beneficiary_account(transaction_request)
            sender_account = RequestMaker.get_sender_account(transaction_request)
            amount_details = RequestMaker.get_amount_details(transaction_request)
            fraud_kyc = RequestMaker.get_fraud_kyc(transaction_request)
            payment_mode = RequestMaker.get_payment_mode(transaction_request)
            tenant_id = RequestMaker.get_tenant_id(transaction_request)
            mno = RequestMaker.get_mno(transaction_request)
            callback_url = RequestMaker.get_callback_url(transaction_request)
            description = RequestMaker.get_description(transaction_request)
            business_id = RequestMaker.get_business_id(transaction_request)
            beneficiary_id = RequestMaker.get_beneficiary_id(transaction_request)
            sender_id = RequestMaker.get_sender_id(transaction_request)
            agent_id = RequestMaker.get_agent_id(transaction_request)
            user_id = RequestMaker.get_user_id(transaction_request)
            user__id = RequestMaker.get_user__id(transaction_request)
            created_by = RequestMaker.get_created_by(transaction_request)
            subscriber_id = RequestMaker.get_subscriber_id(transaction_request)
            username = RequestMaker.get_username(transaction_request)
            medium = RequestMaker.get_medium(transaction_request)
            transaction_type = RequestMaker.get_transaction_type(transaction_request)
            account_id = RequestMaker.get_account_id(transaction_request)
            
            # initialize gateway service with tenant ID
            gateway_service = GatewayService(tenant_id)
            
            # for billpay transactions
            if transaction_type == 'billpay':
                Log.info(f"{log_tag} billpay transctions processor")
                json_response = gateway_service.process_transaction_initiate(
                    tenant_id=tenant_id,
                    payment_type=payment_type,
                    source=source,
                    destination=destination,
                    receive_amount=receive_amount,
                    send_amount=send_amount,
                    beneficiary_account=beneficiary_account,
                    sender_account=sender_account,
                    amount_details=amount_details,
                    fraud_kyc=fraud_kyc,
                    payment_mode=payment_mode,
                    description=description,
                    internal_reference=internal_reference,
                    business_id=business_id,
                    beneficiary_id=beneficiary_id,
                    sender_id=sender_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    user__id=user__id,
                    created_by=created_by,
                    subscriber_id=subscriber_id,
                    referrer=referrer,
                    username=username,
                    medium=medium,
                    request_type=transaction_type,
                    billpay_id=billpay_id,
                    account_id=account_id,
                )
                return jsonify(json_response)
                
                
            #for bank and wallet transactions             
            if str.lower(payment_type) == 'bank':
                # process agent bank traction
                Log.info(f"{log_tag} processing agent bank traction")
                
                json_response = gateway_service.process_transaction_initiate(
                    tenant_id=tenant_id,
                    payment_type=payment_type,
                    source=source,
                    destination=destination,
                    receive_amount=receive_amount,
                    send_amount=send_amount,
                    beneficiary_account=beneficiary_account,
                    sender_account=sender_account,
                    amount_details=amount_details,
                    fraud_kyc=fraud_kyc,
                    payment_mode=payment_mode,
                    description=description,
                    internal_reference=internal_reference,
                    business_id=business_id,
                    beneficiary_id=beneficiary_id,
                    sender_id=sender_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    user__id=user__id,
                    created_by=created_by,
                    subscriber_id=subscriber_id,
                    referrer=referrer,
                    username=username,
                    medium=medium,
                )
                return jsonify(json_response)
            
            elif str.lower(payment_type) == 'wallet':
                Log.info(f"{log_tag} processing wallet bank traction")
                
                json_response = gateway_service.process_transaction_initiate(
                    tenant_id=tenant_id,
                    payment_type=payment_type,
                    source=source,
                    mno=mno,
                    destination=destination,
                    receive_amount=receive_amount,
                    send_amount=send_amount,
                    beneficiary_account=beneficiary_account,
                    sender_account=sender_account,
                    amount_details=amount_details,
                    fraud_kyc=fraud_kyc,
                    payment_mode=payment_mode,
                    description=description,
                    internal_reference=internal_reference,
                    business_id=business_id,
                    beneficiary_id=beneficiary_id,
                    sender_id=sender_id,
                    agent_id=agent_id,
                    user_id=user_id,
                    user__id=user__id,
                    referrer=referrer,
                    username=username,
                    medium=medium,
                )
                return jsonify(json_response)
            else:
                Log.info(f"{log_tag} UNKOWN TRANSACTION TYPE")
             
            
        except Exception as e:
           Log.info(f"{log_tag} error preparing transaction request in the factory: {str(e)}") 
            
        

       