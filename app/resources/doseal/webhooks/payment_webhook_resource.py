# resources/payment_webhook_resource.py

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
from ....utils.payments.hubtel_utils import (
    verify_hubtel_callback, parse_hubtel_callback,validate_hubtel_callback_amount,
    get_hubtel_response_code_message
)

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
                        billing_period=billing_period,
                        package_id=package_id,
                        payment_method=PAYMENT_METHODS["HUBTEL"],
                        payment_reference=parsed['transaction_id'],
                        processing_callback=True,
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




