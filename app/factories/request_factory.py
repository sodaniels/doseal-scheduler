from typing import Any, Dict, Optional
from pydantic import ValidationError
from ..utils.request import RequestMaker  # your Pydantic Request class
from ..utils.logger import Log



class RequestFactory:
    def make_transaction(body: Dict[str, Any]) -> Optional[RequestMaker]:
        try:
            # Basic setup
            source_msisdn = body.get("sender_phone_number", "")
            destination_msisdn = body.get("recipient_phone_number", "")
            receiver_msisdn = destination_msisdn.replace(" ", "").replace("+", "")
            
            if str.upper(body.get("recipient_country_iso_2")) == "BB":
                receiver_msisdn = receiver_msisdn.replace("(", "").replace(")", "").replace("-", "")

            if str.upper(body.get("recipient_currency")) == "ZMW":
                destination_msisdn = "260" + destination_msisdn[-9:]
                receiver_msisdn = "260" + receiver_msisdn[-9:]

            destination = {"type": "msisdn", "value": destination_msisdn}
            source = {"type": "msisdn", "value": source_msisdn}
            
            payment_mode = body.get("payment_mode")
            payment_type = str.upper(body.get("payment_type", ""))
            referrer = body.get("referrer", "")
            callback_url = body.get("callback_url", "")
            sender_id = body.get("sender_id")
            beneficiary_id = body.get("beneficiary_id")
            sender_address = body.get("sender_address", "")
            amount_details = body.get("amount_details")
            receive_amount = amount_details.get("receive_amount")
            send_amount = amount_details.get("send_amount")
            fraud_kyc = body.get("fraud_kyc")
            business_id = body.get("business_id")
            tenant_id=body.get("tenant_id")
            user_id=body.get("user_id")
            agent_id=body.get("agent_id")
            user__id=body.get("user__id")
            subscriber_id=body.get("subscriber_id")
            username=body.get("username")
            medium=body.get("medium")
            transaction_type=body.get("transaction_type", "")
            billpay_id=body.get("billpay_id", "")
            account_id=body.get("account_id", "")
            
            # Credit wallet setup
            if payment_type == "BANK":
                beneficiary_account = {
                    "name": body.get("recipient_full_name", ""),
                    "type": payment_type,
                    "account_no": body.get("account_number"),
                    "recipient_account": body.get("recipient_phone_number"),
                    "routing_number": body.get("routing_number"),
                    "bank_name": body.get("bank_name"),
                }
            else:
                beneficiary_account = {
                    "name": body.get("recipient_full_name", ""),
                    "type": 'BILLPAY' if transaction_type == 'billpay' else payment_type,
                    "account_no": receiver_msisdn,
                    "recipient_account": body.get("recipient_phone_number"),
                }

            sender_account = {
                "name": body.get("sender_full_name", ""),
                "type": "Zeepay",
                "account_no": source_msisdn,
            }

            extra = {
                "source_of_funds": body.get("source_of_funds"),
                "transfer_purpose": body.get("transfer_purpose"),
                "recipient_name": body.get("recipient_full_name"),
                "mno": body.get("mno") if body.get("mno") else None,
                "sender_country": body.get("sender_country_iso_2"),
                "recipient_country_iso_2": body.get("recipient_country_iso_2"),
                "sender_address": sender_address,
                "sender_currency": body.get("sender_currency")
            }
            
            details = {
                "details": sender_address
            }

            if agent_id is not None:
                if transaction_type == "billpay":
                    description = "Agent Billpay Transaction"
                else:
                    description = {
                        "wallet": "Agent Send to Wallet Transaction",
                        "bank": "Agent Send to Bank Transaction",
                    }.get(str.lower(payment_type), "Transaction")
                
            if subscriber_id is not None:
                
                if transaction_type == "billpay":
                    description = "Subscriber Billpay Transaction"
                else:
                    description = {
                        "wallet": "Subscriber Send to Wallet Transaction",
                        "bank": "Subscriber Send to Bank Transaction",
                    }.get(str.lower(payment_type), "Transaction")
              
            # prepare billpay request      
            if transaction_type == "billpay":
                # Create Bank RequestMaker object
                return RequestMaker(
                    payment_mode=payment_mode,
                    source=source,
                    destination=destination,
                    beneficiary_account=beneficiary_account,
                    sender_account=sender_account,
                    extra=extra,
                    amount_details=amount_details,
                    payment_type=payment_type,
                    description=description,
                    callback_url=callback_url,
                    recipient_account=body.get("account_number"),
                    routing_number=body.get("routing_number"),
                    bank_name=body.get("bank_name"),
                    tenant_id=body.get("tenant_id"),
                    sender_id=sender_id,
                    beneficiary_id=beneficiary_id,
                    business_id=business_id,
                    subscriber_id=subscriber_id,
                    agent_id=agent_id,
                    username=username,
                    medium=medium,
                    transaction_type=transaction_type,
                    billpay_id=billpay_id,
                    account_id=account_id,
                )
                
            
            if str.lower(payment_type) == 'wallet':
                # Create Bank RequestMaker object
                return RequestMaker(
                    payment_mode=payment_mode,
                    source=source,
                    destination=destination,
                    receive_amount=receive_amount,
                    send_amount=send_amount,
                    beneficiary_account=beneficiary_account,
                    sender_account=sender_account,
                    extra=extra,
                    amount_details=amount_details,
                    fraud_kyc=fraud_kyc,
                    payment_type=payment_type,
                    description=description,
                    mno=body.get("mno"),
                    referrer=referrer,
                    details=details,
                    callback_url=callback_url,
                    recipient_account=body.get("account_number"),
                    routing_number=body.get("routing_number"),
                    bank_name=body.get("bank_name"),
                    tenant_id=body.get("tenant_id"),
                    sender_id=sender_id,
                    beneficiary_id=beneficiary_id,
                    business_id=business_id,
                    agent_id=agent_id,
                    subscriber_id=subscriber_id,
                    username=username,
                    medium=medium
                )
                
            if str.lower(payment_type) == 'bank':
                #Create Wallet RequestMaker Object
                return RequestMaker(
                    payment_mode=payment_mode,
                    source=source,
                    destination=destination,
                    receive_amount=receive_amount,
                    send_amount=send_amount,
                    beneficiary_account=beneficiary_account,
                    sender_account=sender_account,
                    extra=extra,
                    amount_details=amount_details,
                    fraud_kyc=fraud_kyc,
                    payment_type=payment_type,
                    description=description,
                    referrer=referrer,
                    details=details,
                    callback_url=callback_url,
                    recipient_account=body.get("account_number"),
                    routing_number=body.get("routing_number"),
                    bank_name=body.get("bank_name"),
                    tenant_id=tenant_id,
                    sender_id=sender_id,
                    beneficiary_id=beneficiary_id,
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    agent_id=agent_id,
                    subscriber_id=subscriber_id,
                    username=username,
                    medium=medium
                )
            Log.info(f"[RequestFactory] Created request for {str.upper(payment_mode)}")

        except ValidationError as ve:
            Log.error(f"[RequestFactory] Validation error: {ve}")
        except Exception as e:
            Log.error(f"[RequestFactory] Unexpected error: {e}")
            return None