# resources/payment_webhook_resource.py

import os
from datetime import datetime
from flask import request, g, jsonify
from flask.views import MethodView
from flask_smorest import Blueprint

from ....services.pos.subscription_service import SubscriptionService
from ....constants.payment_methods import PAYMENT_METHODS
from ....models.business_model import Business
from ....utils.logger import Log
from ....utils.json_response import prepared_response
from ....utils.payments.mpesa_utils import verify_mpesa_signature
from ....models.admin.payment import Payment
from ....services.shop_api_service import ShopApiService
from ....utils.payments.hubtel_utils import (
    verify_hubtel_callback, parse_hubtel_callback,validate_hubtel_callback_amount,
    get_hubtel_response_code_message
)
from ....utils.payments.asoriba_utils import (
    verify_asoriba_signature, parse_asoriba_callback_from_query
)
from ....utils.helpers import build_receipt_sms


payment_webhook_blp = Blueprint("payment_webhooks", __name__, description="Payment gateway webhooks")


@payment_webhook_blp.route("/webhooks/payment/hubtel", methods=["POST"])
class HubtelWebhook(MethodView):
    """Handle Hubtel payment webhooks/callbacks."""
    
    def post(self):
        """Process Hubtel payment callback."""
        
        client_reference = None
        log_tag = "[HubtelWebhook][post]"
        client_ip = request.remote_addr
        
        try:
            # Get raw request data
            data = request.get_json()
            
            Log.info(f"{log_tag} Received Hubtel webhook")
            Log.info(f"{log_tag} Callback Transaction: {data}")
            
            # Verify and parse callback
            if not verify_hubtel_callback(data):
                Log.error(f"{log_tag} Invalid Hubtel callback structure")
                return {
                    "code": 401,
                    "message": "Invalid callback structure"
                }, 401
            
            # Parse callback data using helper
            parsed = parse_hubtel_callback(data)
            if not parsed:
                Log.error(f"{log_tag} Failed to parse callback")
                return {
                    "code": 400,
                    "message": "Failed to parse callback"
                }, 400
            
            client_reference = parsed['client_reference']
            
            Log.info(f"{log_tag} Processing payment - Reference: {client_reference}, Code: {parsed['response_code']}")
            
            # Get payment from database
            payment = Payment.get_by_order_id(client_reference)
            
            if not payment:
                Log.error(f"{log_tag} Payment not found for reference: {client_reference}")
                return {
                    "code": 404,
                    "message": "Payment not found"
                }, 404
            
            payment_id = payment.get('_id')
            current_status = payment.get('status')
            
            Log.info(f"{log_tag} Payment found: {payment_id}, Current status: {current_status}")
            
            # Check if payment is already processed
            if current_status in [Payment.STATUS_SUCCESS, Payment.STATUS_FAILED]:
                Log.warning(f"{log_tag} Payment already processed with status: {current_status}")
                return {
                    "code": 200,
                    "message": "Callback already processed"
                }, 200
            
            # Validate amount matches
            if parsed['amount']:
                amount_valid = validate_hubtel_callback_amount(
                    parsed['amount'],
                    payment.get('amount')
                )
                if not amount_valid:
                    Log.warning(f"{log_tag} Amount mismatch detected")
                    # Continue anyway, but log the discrepancy
            
            # Update payment with callback data
            update_data = {
                "checkout_request_id": parsed['checkout_id'] or payment.get('checkout_request_id'),
                "customer_phone": parsed['customer_phone'] or payment.get('customer_phone'),
                "customer_name": parsed['customer_name'] or payment.get('customer_name'),
                "customer_email": parsed['customer_email'] or payment.get('customer_email'),
            }
            
            
            # Add payment details to metadata
            if parsed['payment_details']:
                existing_metadata = payment.get('metadata', {})
                existing_metadata['payment_details'] = parsed['payment_details']
                existing_metadata['sales_invoice_id'] = parsed['sales_invoice_id']
                existing_metadata['charges'] = parsed['charges']
                update_data['metadata'] = existing_metadata
                update_data['callback_response'] = data
            
            # Process based on success/failure
            if parsed['is_success']:
                # Payment successful
                Log.info(f"{log_tag} Payment successful - Transaction ID: {parsed['transaction_id']}")
                
                # Update payment status
                Payment.update_status(
                    payment_id,
                    Payment.STATUS_SUCCESS,
                    gateway_transaction_id=parsed['transaction_id']
                )
                
                # Update additional fields
                business_id = payment.get("business_id")
                Payment.update(
                    payment_id, 
                    business_id=business_id,
                    processing_callback=True, 
                    **update_data
                )
                
                # Create subscription
                metadata = payment.get('metadata', {})
                old_package_id = metadata.get('old_package_id')
                package_id = metadata.get('package_id') or payment.get('package_id')
                business_id = payment.get('business_id')
                user_id = payment.get('user_id')
                user__id = payment.get('user__id')
                billing_period = metadata.get('billing_period', 'monthly')
                
                
                if not old_package_id:
                    Log.info(f"{log_tag} Creating subscription for business {business_id} with package {package_id}")
                    success, subscription_id, error = SubscriptionService.create_subscription(
                        business_id=business_id,
                        user_id=user_id,
                        user__id=user__id,
                        package_id=package_id,
                        payment_method=PAYMENT_METHODS["HUBTEL"],
                        payment_reference=parsed['transaction_id'],
                        payment_done=True
                    )
                    
                    if success:
                        Log.info(f"{log_tag} Subscription created: {subscription_id}")
                        
                        #update subscription status
                        
                        try:
                            update_account_status_package = Business.update_account_status_by_business_id(
                                business_id,
                                client_ip,
                                'subscribed_to_package',
                                True
                            )
                            Log.info(f"{log_tag} update_account_status_package: {update_account_status_package}")
                        except Exception as e:
                            Log.info(f"{log_tag} \t Error updating account status: {str(e)}")
                        
                        
                        return {
                            "code": 200,
                            "message": "Callback processed successfully",
                            "subscription_id": subscription_id
                        }, 200
                    else:
                        Log.error(f"{log_tag} Subscription creation failed: {error}")
                        Payment.update(
                            payment_id,
                            business_id=business_id,
                            processing_callback=True,
                            notes=f"Payment successful but subscription failed: {error}"
                        )
                        return {
                            "code": 500,
                            "message": f"Payment successful but subscription failed: {error}"
                        }, 500
                else:
                    Log.info(f"{log_tag} Old package ID: {package_id}")
                    success, subscription_id, error  = SubscriptionService.apply_or_renew_from_payment(
                        business_id=business_id,
                        user_id=user_id,
                        user__id=user__id,
                        package_id=package_id,
                        billing_period=billing_period,
                        payment_method=PAYMENT_METHODS["HUBTEL"],
                        payment_reference=parsed['transaction_id'],
                        payment_id=str(payment.get("_id")),
                        processing_callback=True,
                        source="hubtel_callback",
                    )
                    
                    if success:
                        Log.info(f"{log_tag} Subscription created: {subscription_id}")
                        return {
                            "code": 200,
                            "message": "Callback processed successfully",
                            "subscription_id": subscription_id
                        }, 200
                    else:
                        Log.error(f"{log_tag} Subscription creation failed: {error}")
                        Payment.update(
                            payment_id,
                            business_id=business_id,
                            processing_callback=True,
                            notes=f"Payment successful but subscription failed: {error}"
                        )
                        return {
                            "code": 500,
                            "message": f"Payment successful but subscription failed: {error}"
                        }, 500
                                        
                
            else:
                # Payment failed
                error_message = get_hubtel_response_code_message(parsed['response_code'])
                Log.warning(f"{log_tag} Payment failed - {error_message}")
                
                Payment.update_status(
                    payment_id,
                    Payment.STATUS_FAILED,
                    error_message=error_message
                )
                
                Payment.update(
                    payment_id,
                    business_id=business_id,
                    processing_callback=True,
                    **update_data
                )
                
                return {
                    "code": 200,
                    "message": "Callback processed - Payment failed",
                    "payment_status": parsed['status'],
                    "error": error_message
                }, 200
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            
            if client_reference:
                try:
                    payment = Payment.get_by_order_id(client_reference)
                    business_id = payment.get("business_id")
                    if payment:
                        Payment.update(
                            payment['_id'],
                            business_id=business_id,
                            processing_callback=True,
                            notes=f"Callback error: {str(e)}"
                        )
                except Exception:
                    pass
            
            return {
                "code": 500,
                "message": f"Error processing callback: {str(e)}"
            }, 500


@payment_webhook_blp.route("/webhooks/payment/asoriba", methods=["GET", "POST"])
class AsoribaWebhook(MethodView):
    """Handle Asoriba/MyBusinessPay payment webhooks/callbacks (query-string format)."""

    def get(self):
        return self._handle()

    def post(self):
        return self._handle()

    def _handle(self):
        client_reference = None
        log_tag = "[AsoribaWebhook][handle]"
        
        try:
            # 1️⃣ Get real client IP (supports reverse proxies)
            forwarded_for = request.headers.get("X-Forwarded-For")
            real_ip = request.headers.get("X-Real-IP")

            if forwarded_for:
                # X-Forwarded-For can contain multiple IPs: client, proxy1, proxy2
                client_ip = forwarded_for.split(",")[0].strip()
            elif real_ip:
                client_ip = real_ip
            else:
                client_ip = request.remote_addr

            Log.info(
                f"{log_tag} Incoming webhook | IP={client_ip} | "
                f"Method={request.method} | Time={datetime.utcnow().isoformat()}Z"
            )

            # 2️⃣ Log headers (useful for debugging / verification)
            Log.debug(
                f"{log_tag}] Headers: {dict(request.headers)}"
            )

            # 3️⃣ Capture payload
            if request.method == "GET":
                payload = request.args.to_dict(flat=True)
            else:
                payload = request.get_json(silent=True) or request.form.to_dict(flat=True)

            Log.info(
                f"{log_tag} Payload from {client_ip}: {payload}"
            )
        except Exception as e:
            f"{log_tag} error getting IP: {str(e)}"

        try:
            # Log raw callback
            Log.info(f"{log_tag} Received Asoriba callback")
            Log.info(f"{log_tag} args={dict(request.args)}")
            if request.form:
                Log.info(f"{log_tag} form={dict(request.form)}")

            # Verify “signature” (token-based recommended)
            if not verify_asoriba_signature(request):
                Log.error(f"{log_tag} Invalid webhook token/signature")
                return {"code": 401, "message": "Invalid signature"}, 401

            parsed = parse_asoriba_callback_from_query()
            client_reference = parsed["reference"]
            
            if not client_reference:
                Log.error(f"{log_tag} Missing order_id/reference in callback")
                return {"code": 400, "message": "Missing reference/order_id"}, 400

            Log.info(
                f"{log_tag} Processing reference={client_reference} "
                f"status={parsed['status']} status_code={parsed['status_code']} gateway_id={parsed['gateway_id']}"
            )

            # Lookup payment
            payment = Payment.get_by_order_id(client_reference)
            if not payment and parsed.get("gateway_id"):
                payment = Payment.get_by_checkout_request_id(parsed["gateway_id"])

            if not payment:
                Log.error(f"{log_tag} Payment not found for reference={client_reference}")
                # Acknowledge to prevent retries
                return {"code": 200, "message": "Payment not found but acknowledged"}, 200

            payment_id = payment.get("_id")
            business_id = payment.get("business_id")
            current_status = payment.get("status")

            # Idempotency
            if current_status in [Payment.STATUS_SUCCESS, Payment.STATUS_FAILED]:
                Log.warning(f"{log_tag} Already processed. status={current_status}")
                return {"code": 200, "message": "Callback already processed"}, 200

            callback_payload = parsed["payload"]
            

            # Common update fields
            update_data = {
                "checkout_request_id": parsed["gateway_id"] or payment.get("checkout_request_id"),
                "customer_phone": (callback_payload.get("source", {}) or {}).get("number") or payment.get("customer_phone"),
                "customer_name": f"{callback_payload.get('first_name','')} {callback_payload.get('last_name','')}".strip() or payment.get("customer_name"),
                "customer_email": callback_payload.get("email") or payment.get("customer_email"),
                "callback_response": callback_payload,
                "processing_callback": True,
            }
            
            # Amount verification (log only; don't fail hard unless you want to)
            cb_amount = callback_payload.get("amount")
            if cb_amount is not None:
                try:
                    stored_amount = str(payment.get("amount"))
                    if str(cb_amount) != stored_amount:
                        Log.warning(f"{log_tag} Amount mismatch callback={cb_amount} stored={stored_amount}")
                    update_data["paid_amount"] = str(cb_amount)
                except Exception:
                    pass

            if callback_payload.get("currency"):
                update_data["currency"] = callback_payload["currency"]
                
            # Get frontend return URL from environment
            frontend_return_url = os.getenv("PAYMENT_FRONT_END_RETURN_URL", "")
            

            # ---- Status handling ----
            if parsed["is_success"]:
                Payment.update_status(
                    payment_id,
                    Payment.STATUS_SUCCESS,
                    gateway_transaction_id=callback_payload.get("processor_transaction_id") or parsed["gateway_id"]
                )
                Payment.update(payment_id, business_id=business_id, **update_data)

                
                # Build query parameters for redirect
                query_params = {
                    "amount": callback_payload.get("amount", ""),
                    "amount_after_charge": callback_payload.get("amount_after_charge", ""),
                    "charge": callback_payload.get("charge", ""),
                    "currency": callback_payload.get("currency", ""),
                    "customer_remarks": callback_payload.get("customer_remarks", ""),
                    "email": callback_payload.get("email", ""),
                    "first_name": callback_payload.get("first_name", ""),
                    "id": parsed.get("gateway_id", ""),
                    "last_name": callback_payload.get("last_name", ""),
                    "message": callback_payload.get("message", ""),
                    "payment_date": callback_payload.get("payment_date", ""),
                    "processor_transaction_id": callback_payload.get("processor_transaction_id", ""),
                    "reference": client_reference,
                    "status": parsed.get("status", "successful"),
                    "status_code": parsed.get("status_code", "100"),
                    "tokenized": str(callback_payload.get("tokenized", "false")).lower(),
                    "transaction_uuid": callback_payload.get("transaction_uuid", ""),
                }
                
                try:
                    tenant_id = 1
                    username = os.getenv("SYSTEM_OWNER_PHONE_NUMBER")

                    sms_text = build_receipt_sms(query_params)

                    shop_service = ShopApiService(tenant_id)
                    response = shop_service.send_sms(username, sms_text, tenant_id)

                    Log.info("SMS sent successfully", extra={
                        "reference": client_reference,
                        "hubtel_response": response
                    })
                except Exception as e:
                    Log.exception("Failed to send payment receipt SMS", extra={
                        "reference": client_reference,
                        "tenant_id": tenant_id
                    })

                # Add source information
                source = callback_payload.get("source", {}) or {}
                if source:
                    query_params["source[number]"] = source.get("number", "")
                    query_params["source[object]"] = source.get("object", "")
                    query_params["source[processor_transaction_id]"] = source.get("processor_transaction_id", "")
                    query_params["source[reference]"] = source.get("reference", "")
                    query_params["source[type]"] = source.get("type", "")

                # Add metadata if present
                metadata = callback_payload.get("metadata", {}) or {}
                if metadata:
                    for key, value in metadata.items():
                        query_params[f"metadata[{key}]"] = str(value)

                # Build redirect URL
                from urllib.parse import urlencode
                query_string = urlencode(query_params)
                redirect_url = f"{frontend_return_url}?{query_string}"

                Log.info(f"{log_tag} Redirecting to: {redirect_url}")

                # Return redirect response
                from flask import redirect
                return redirect(redirect_url, code=302)

            if parsed["is_pending"]:
                # Keep as pending/processing
                Payment.update_status(
                    payment_id,
                    Payment.STATUS_PROCESSING
                )
                Payment.update(payment_id, business_id=business_id, **update_data)

                
                # Build query parameters for pending status
                query_params = {
                    "amount": callback_payload.get("amount", ""),
                    "currency": callback_payload.get("currency", ""),
                    "first_name": callback_payload.get("first_name", ""),
                    "last_name": callback_payload.get("last_name", ""),
                    "message": callback_payload.get("message", "Payment is being processed"),
                    "reference": client_reference,
                    "status": "pending",
                    "status_code": parsed.get("status_code", "102"),
                }
                
                # send pending sms to self
                try:
                    tenant_id = 1
                    username = os.getenv("SYSTEM_OWNER_PHONE_NUMBER")

                    sms_text = build_receipt_sms(query_params)

                    shop_service = ShopApiService(tenant_id)
                    response = shop_service.send_sms(username, sms_text, tenant_id)

                    Log.info("SMS sent successfully", extra={
                        "reference": client_reference,
                        "hubtel_response": response
                    })
                except Exception as e:
                    Log.exception("Failed to send payment receipt SMS", extra={
                        "reference": client_reference,
                        "tenant_id": tenant_id
                    })



                from urllib.parse import urlencode
                query_string = urlencode(query_params)
                redirect_url = f"{frontend_return_url}?{query_string}"

                Log.info(f"{log_tag} Redirecting to pending page: {redirect_url}")

                from flask import redirect
                return redirect(redirect_url, code=302)

            # Failed / unknown
            error_message = callback_payload.get("message") or "Payment not successful"
            Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=str(error_message))
            Payment.update(payment_id, business_id=business_id, **update_data)

            # Build query parameters for failed status
            query_params = {
                "amount": callback_payload.get("amount", ""),
                "currency": callback_payload.get("currency", ""),
                "first_name": callback_payload.get("first_name", ""),
                "last_name": callback_payload.get("last_name", ""),
                "email": callback_payload.get("email", ""),
                "message": str(error_message),
                "reference": client_reference,
                "status": "failed",
                "status_code": parsed.get("status_code", "400"),
                "error": str(error_message),
            }
            
            # send failed sms to self
            try:
                tenant_id = 1
                username = os.getenv("SYSTEM_OWNER_PHONE_NUMBER")

                sms_text = build_receipt_sms(query_params)

                shop_service = ShopApiService(tenant_id)
                response = shop_service.send_sms(username, sms_text, tenant_id)

                Log.info("SMS sent successfully", extra={
                    "reference": client_reference,
                    "hubtel_response": response
                })
            except Exception as e:
                Log.exception("Failed to send payment receipt SMS", extra={
                    "reference": client_reference,
                    "tenant_id": tenant_id
                })

            # Add source information if available
            source = callback_payload.get("source", {}) or {}
            if source:
                query_params["source[number]"] = source.get("number", "")
                query_params["source[type]"] = source.get("type", "")

            from urllib.parse import urlencode
            query_string = urlencode(query_params)
            redirect_url = f"{frontend_return_url}?{query_string}"

            Log.info(f"{log_tag} Redirecting to failed page: {redirect_url}")

            from flask import redirect
            return redirect(redirect_url, code=302)
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if client_reference:
                try:
                    payment = Payment.get_by_order_id(client_reference)
                    if payment:
                        Payment.update(
                            payment["_id"],
                            business_id=payment.get("business_id"),
                            processing_callback=True,
                            notes=f"Callback error: {str(e)}"
                        )
                except Exception:
                    pass
            # Redirect to error page even on exception
        frontend_return_url = os.getenv("PAYMENT_FRONT_END_RETURN_URL", "")
        if frontend_return_url:
            from urllib.parse import urlencode
            from flask import redirect
            
            query_params = {
                "status": "error",
                "message": f"Error processing payment: {str(e)}",
                "reference": client_reference or "unknown",
            }
            
            #send failed sms to self
            try:
                tenant_id = 1
                username = os.getenv("SYSTEM_OWNER_PHONE_NUMBER")

                sms_text = build_receipt_sms(query_params)

                shop_service = ShopApiService(tenant_id)
                response = shop_service.send_sms(username, sms_text, tenant_id)

                Log.info("SMS sent successfully", extra={
                    "reference": client_reference,
                    "hubtel_response": response
                })
            except Exception as e:
                Log.exception("Failed to send payment receipt SMS", extra={
                    "reference": client_reference,
                    "tenant_id": tenant_id
                })
            
            query_string = urlencode(query_params)
            redirect_url = f"{frontend_return_url}?{query_string}"
            
            return redirect(redirect_url, code=302)

        return {"code": 500, "message": f"Error processing callback: {str(e)}"}, 500


