# services/payments/payment_service.py

import requests
import os
import json
import base64
from datetime import datetime
from bson import ObjectId

from ...models.admin.payment import Payment
from ...models.admin.package_model import Package
from ...constants.payment_methods import PAYMENT_METHODS
from ...constants.service_code import HTTP_STATUS_CODES
from ...config import Config
from ...utils.logger import Log
from ...utils.generators import generate_internal_reference
from ...utils.payments.hubtel_utils import get_hubtel_auth_token
from ...utils.external.exchange_rate_api import get_exchange_rate
from ...utils.config import Config as PaymentConfig
from ...utils.helpers import split_name


class PaymentService:
    """Service for handling payment processing."""


    # ========================================
    # HUBTEL PAYMENT METHODS
    # ========================================
    
    @staticmethod
    def initiate_hubtel_payment(
        business_id, 
        user_id, 
        user__id, 
        package_id, 
        billing_period, 
        payment_details,
        customer_name=None,
        phone_number=None,
        customer_email=None,
        metadata=None
    ):
        """
        Initiate Hubtel payment.
        
        Args:
            business_id: Business ID
            user_id: User string ID
            user__id: User ObjectId
            package_id: Package ID
            billing_period: Billing period
            customer_name: Customer name
            customer_phone: Customer phone (optional)
            customer_email: Customer email (optional)
            metadata: Additional metadata
            
        Returns:
            Tuple (success: bool, data: dict or None, error: str or None)
        """
        log_tag = f"[PaymentService][initiate_hubtel_payment]"
        
        payment_id = None  # Initialize for error handling
        
        try:
            # Get package details
            package = Package.get_by_id(package_id)
            if not package:
                return False, None, "Package not found"
            
            amount = float(package.get("price", 0))
            if amount <= 0:
                return False, None, "Invalid package price"
            
            # Get Hubtel auth token
            auth_token = get_hubtel_auth_token()
            if not auth_token:
                return False, None, "Failed to generate Hubtel auth token. Please check credentials."
            
            Log.info(f"{log_tag} Auth token generated successfully (length: {len(auth_token)})")
            
            reference = payment_details.get("internal_reference")
            
            amount_detail = payment_details.get("amount_detail")
            from_currency = amount_detail.get("from_currency")
            amount =  amount_detail.get("paid_amount") if  amount_detail.get("paid_amount") else  amount_detail.get("total_from_amount")
            
            
            # Create payment record
            payment = Payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                reference=reference,
                amount=amount,
                currency=from_currency,
                amount_detail=amount_detail,
                payment_method=PAYMENT_METHODS["HUBTEL"],
                payment_type=Payment.TYPE_SUBSCRIPTION,
                package_id=package_id,
                gateway="hubtel",
                order_id=reference,
                status=Payment.STATUS_PENDING,
                status_code=HTTP_STATUS_CODES["PENDING"],
                customer_name=customer_name,
                customer_phone=phone_number,
                customer_email=customer_email,
                metadata=metadata or {},
                callback_url=f"{Config.CALLBACK_BASE_URL}/webhooks/payment/hubtel",
                redirect_url=Config.HUBTEL_RETURN_URL
            )
            
            payment_id = payment.save()
            
            if not payment_id:
                return False, None, "Failed to create payment record"
            
            Log.info(f"{log_tag} Payment record created: {payment_id}")
            
            # Prepare Hubtel payment request
            hubtel_url = Config.HUBTEL_CHECKOUT_BASE_URL
            
            headers = {
                "Authorization": f"Basic {auth_token}",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            payload = {
                "totalAmount": amount,
                "description": f"Subscription: {package.get('name')} - {billing_period} ({Config.APP_NAME})",
                "clientReference": reference,
                "merchantAccountNumber": Config.HUBTEL_MERCHANT_ACCOUNT_NUMBER,
                "callbackUrl": f"{Config.CALLBACK_BASE_URL}/webhooks/payment/hubtel",
                "returnUrl": Config.HUBTEL_RETURN_URL,
                "cancellationUrl": Config.HUBTEL_CANCELLATION_URL,
            }
            
            Log.info(f"{log_tag} Sending Hubtel payment request")
            Log.info(f"{log_tag} URL: {hubtel_url}")
            Log.info(f"{log_tag} Reference: {reference}")
            Log.info(f"{log_tag} Amount: {from_currency} {amount} ")
            
            # Make request
            response = requests.post(
                hubtel_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            # Log raw response for debugging
            Log.info(f"{log_tag} Response Status Code: {response.status_code}")
            Log.info(f"{log_tag} Response Headers: {dict(response.headers)}")
            Log.info(f"{log_tag} Response Text (first 500 chars): {response.text[:500]}")
            
            # Check if response is empty
            if not response.text or response.text.strip() == "":
                Log.error(f"{log_tag} Empty response from Hubtel")
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Empty response from payment gateway")
                return False, None, "Payment gateway returned empty response. Please check your Hubtel credentials."
            
            # Check content type
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' not in content_type:
                Log.error(f"{log_tag} Non-JSON response. Content-Type: {content_type}")
                Log.error(f"{log_tag} Response body: {response.text}")
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=f"Invalid response format: {content_type}")
                return False, None, f"Payment gateway returned invalid format: {content_type}. Response: {response.text[:200]}"
            
            # Try to parse JSON
            try:
                response_data = response.json()
            except json.JSONDecodeError as e:
                Log.error(f"{log_tag} JSON decode error: {str(e)}")
                Log.error(f"{log_tag} Response text: {response.text}")
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Invalid JSON response from gateway")
                return False, None, f"Invalid JSON response from payment gateway: {str(e)}"
            
            Log.info(f"{log_tag} Hubtel response parsed: {json.dumps(response_data, indent=2)}")
            
            # Handle different response status codes
            if response.status_code in [200, 201]:
                # Success - extract checkout URL
                checkout_url = None
                checkout_id = None
                
                # Try different response structures
                if isinstance(response_data, dict):
                    # Structure 1: {data: {checkoutUrl: ..., checkoutId: ...}}
                    data_obj = response_data.get('data', {})
                    if isinstance(data_obj, dict):
                        checkout_url = data_obj.get('checkoutUrl') or data_obj.get('CheckoutUrl')
                        checkout_id = data_obj.get('checkoutId') or data_obj.get('CheckoutId')
                    
                    # Structure 2: {checkoutUrl: ..., checkoutId: ...}
                    if not checkout_url:
                        checkout_url = response_data.get('checkoutUrl') or response_data.get('CheckoutUrl')
                        checkout_id = response_data.get('checkoutId') or response_data.get('CheckoutId')
                    
                    # Structure 3: {Data: {CheckoutUrl: ..., CheckoutId: ...}}
                    if not checkout_url:
                        data_obj_upper = response_data.get('Data', {})
                        if isinstance(data_obj_upper, dict):
                            checkout_url = data_obj_upper.get('CheckoutUrl')
                            checkout_id = data_obj_upper.get('CheckoutId')
                
                if checkout_url:
                    # Update payment with checkout ID
                    Payment.update(
                        payment_id,
                        business_id=business_id,
                        checkout_request_id=checkout_id or reference,
                        status=Payment.STATUS_PROCESSING,
                        initial_response = data_obj
                    )
                    
                    Log.info(f"{log_tag} Payment initiated successfully. Checkout URL: {checkout_url}")
                    
                    return True, {
                        "payment_id": str(payment_id),
                        "checkout_url": checkout_url,
                        "checkout_id": checkout_id,
                        "reference": reference,
                        "amount": amount,
                        "currency": from_currency,
                        "message": "Payment initiated. Redirecting to Hubtel checkout..."
                    }, None
                else:
                    # No checkout URL found
                    error_msg = response_data.get('message') or response_data.get('Message') or 'Failed to get checkout URL'
                    Log.error(f"{log_tag} No checkout URL in response: {error_msg}")
                    Log.error(f"{log_tag} Full response: {response_data}")
                    
                    Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                    return False, None, error_msg
            
            elif response.status_code == 400:
                # Bad request
                error_msg = response_data.get('message') or response_data.get('Message') or 'Bad request'
                errors = response_data.get('errors') or response_data.get('Errors') or []
                
                if errors:
                    error_details = ", ".join([str(e) for e in errors])
                    error_msg = f"{error_msg}: {error_details}"
                
                Log.error(f"{log_tag} Bad request (400): {error_msg}")
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                return False, None, error_msg
            
            elif response.status_code == 401:
                # Unauthorized
                error_msg = "Invalid Hubtel credentials. Please check your username and password."
                Log.error(f"{log_tag} Unauthorized (401)")
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                return False, None, error_msg
            
            elif response.status_code == 403:
                # Forbidden
                error_msg = "Access forbidden. Please check your Hubtel account permissions."
                Log.error(f"{log_tag} Forbidden (403)")
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                return False, None, error_msg
            
            elif response.status_code == 404:
                # Not found
                error_msg = "Hubtel API endpoint not found. Please check the base URL."
                Log.error(f"{log_tag} Not found (404)")
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                return False, None, error_msg
            
            elif response.status_code >= 500:
                # Server error
                error_msg = "Hubtel server error. Please try again later."
                Log.error(f"{log_tag} Server error ({response.status_code})")
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                return False, None, error_msg
            
            else:
                # Other status codes
                error_msg = response_data.get('message') or response_data.get('Message') or f'Payment failed (Status: {response.status_code})'
                Log.error(f"{log_tag} Unexpected status ({response.status_code}): {error_msg}")
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                return False, None, error_msg
                
        except requests.exceptions.Timeout:
            Log.error(f"{log_tag} Request timeout")
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Request timeout")
            return False, None, "Request timeout. Please try again."
            
        except requests.exceptions.ConnectionError as e:
            Log.error(f"{log_tag} Connection error: {str(e)}")
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Connection error")
            return False, None, "Connection error: Unable to reach payment gateway"
            
        except requests.exceptions.RequestException as e:
            Log.error(f"{log_tag} Request error: {str(e)}")
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=str(e))
            return False, None, f"Network error: {str(e)}"
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=str(e))
            return False, None, str(e)
    
    # ========================================
    # HUBTEL PAYMENT METHODS
    # ========================================
    
    @staticmethod
    def verify_payment_status(payment_id=None, checkout_request_id=None):
        """
        Verify payment status.
        
        Args:
            payment_id: Payment ID (optional)
            checkout_request_id: Checkout request ID (optional)
            
        Returns:
            Dict with payment status
        """
        log_tag = f"[PaymentService][verify_payment_status]"
        
        try:
            if payment_id:
                payment = Payment.get_by_id(payment_id)
            elif checkout_request_id:
                payment = Payment.get_by_checkout_request_id(checkout_request_id)
            else:
                return {"status": "error", "message": "Payment identifier required"}
            
            if not payment:
                return {"status": "error", "message": "Payment not found"}
            
            return {
                "status": "success",
                "payment": payment
            }
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    @staticmethod
    def create_manual_payment(
        business_id, 
        user_id, 
        user__id, 
        package_id, 
        billing_period, 
        payment_method, 
        payment_reference, 
        amount, 
        currency="USD", 
        **kwargs
    ):
        """
        Create manual payment (for bank transfers, cash, etc.).
        
        Args:
            business_id: Business ID
            user_id: User string ID
            user__id: User ObjectId
            package_id: Package ID
            billing_period: Billing period
            payment_method: Payment method
            payment_reference: Payment reference/receipt number
            amount: Amount paid
            currency: Currency code
            **kwargs: Additional fields (customer details, notes, etc.)
            
        Returns:
            Tuple (success: bool, payment_id: str or None, error: str or None)
        """
        log_tag = f"[PaymentService][create_manual_payment]"
        
        try:
            # Verify package exists
            package = Package.get_by_id(package_id)
            if not package:
                return False, None, "Package not found"
            
            # Generate reference
            reference = generate_internal_reference("MANUAL")
            
            # Create payment record with Success status
            payment = Payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                amount=amount,
                currency=currency,
                payment_method=payment_method,
                payment_type=Payment.TYPE_SUBSCRIPTION,
                package_id=package_id,
                gateway="manual",
                gateway_transaction_id=payment_reference,
                order_id=reference,
                status=Payment.STATUS_SUCCESS,  # Manual payments are pre-verified
                customer_phone=kwargs.get("customer_phone"),
                customer_email=kwargs.get("customer_email"),
                customer_name=kwargs.get("customer_name"),
                notes=kwargs.get("notes"),
                metadata={"billing_period": billing_period}
            )
            
            payment.completed_at = datetime.utcnow()
            payment_id = payment.save()
            
            if payment_id:
                Log.info(f"{log_tag} Manual payment created: {payment_id}")
                return True, str(payment_id), None
            else:
                return False, None, "Failed to create payment record"
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False, None, str(e)
        
    # ========================================
    # END OF HUBTEL PAYMENT METHODS
    # ========================================
    @staticmethod
    def initiate_asoriba_payment(
        business_id, 
        user_id, 
        user__id, 
        package_id, 
        payment_details,
        customer_name=None,
        phone_number=None,
        customer_email=None,
        metadata=None
    ):
        """
        Initiate ASORIBA (MyBusinessPay) payment.

        Returns:
            Tuple (success: bool, data: dict or None, error: str or None)
        """
        log_tag = "[PaymentService][initiate_asoriba_payment]"
        payment_id = None

        try:
            # Get package details
            package = Package.get_by_id(package_id)
            if not package:
                return False, None, "Package not found"
            
            amount = float(package.get("price", 0))
            if amount <= 0:
                return False, None, "Invalid package price"
              
            reference = payment_details.get("internal_reference")
            
            amount_detail = payment_details.get("amount_detail")
            from_currency = amount_detail.get("from_currency")
            amount =  amount_detail.get("paid_amount") if  amount_detail.get("paid_amount") else  amount_detail.get("total_from_amount")
            
            first, last = split_name(customer_name)

            # --- Create payment record (local DB) ---
            payment = Payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                reference=reference,
                amount=amount,
                currency=from_currency,
                amount_detail=amount_detail,
                payment_method=PAYMENT_METHODS["ASORIBA"],
                payment_type=Payment.TYPE_SUBSCRIPTION,
                package_id=package_id,
                gateway="asoriba",
                order_id=reference,
                status=Payment.STATUS_PENDING,
                status_code=HTTP_STATUS_CODES["PENDING"],
                customer_name=customer_name,
                customer_phone=phone_number,
                customer_email=customer_email,
                metadata=metadata or {},
                callback_url=f"{PaymentConfig.CALLBACK_BASE_URL}/webhooks/payment/asoriba",
                redirect_url=PaymentConfig.ASORIBA_RETURN_URL
            )

            payment_id = payment.save()
            if not payment_id:
                return False, None, "Failed to create payment record"

            Log.info(f"{log_tag} Payment record created: {payment_id} reference={reference}")

            # --- Prepare payload for MyBusinessPay / Asoriba ---
            asoriba_url = PaymentConfig.ASORIBA_PAYMENT_URL

            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            # IMPORTANT: JSON-safe amount
            amount_str = str(amount)

            # Merge metadata: keep your existing style + allow extra keys
            merged_metadata = {
                "order_id": reference,
                "product_name": "Donation",
                "product_description": "Payment to Samuel Daniels Website",
            }
            if isinstance(metadata, dict):
                merged_metadata.update(metadata)

            payload = {
                "metadata": merged_metadata,
                "amount": amount_str,
                "currency": from_currency,
                "callback": PaymentConfig.ASORIBA_CALL_BACK_URL,
                "post_url": PaymentConfig.ASORIBA_POST_URL,
                "pub_key": PaymentConfig.ASORIBA_API_KEY,
                # "order_image_url": "https://samueldaniels.co.uk/wp-content/uploads/2025/12/samuel-daniels-logo-black.webp",
                "first_name": first,
                "last_name": last,
                "email": customer_email,  # optional
                "phone_number": phone_number,
            }

            Log.info(f"{log_tag} Sending Asoriba request url={asoriba_url} ref={reference} amount={amount_str} {from_currency}")

            # --- Make request ---
            response = requests.post(
                asoriba_url,
                json=payload,
                headers=headers,
                timeout=30
            )

            Log.info(f"{log_tag} Gateway HTTP status={response.status_code}")
            Log.info(f"{log_tag} Gateway response (first 500 chars)={response.text[:500]}")

            # Empty response
            if not response.text or response.text.strip() == "":
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Empty response from Asoriba gateway")
                return False, None, "Payment gateway returned empty response."

            # Parse JSON safely
            try:
                response_data = response.json()
            except json.JSONDecodeError:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Non-JSON response from Asoriba gateway")
                return False, None, f"Payment gateway returned non-JSON response: {response.text[:200]}"

            Log.info(f"{log_tag} Parsed gateway response: {json.dumps(response_data, indent=2)}")

            # --- Interpret Asoriba response ---

            status = str(response_data.get("status", "")).lower()
            status_code = str(response_data.get("status_code", ""))
            checkout_url = response_data.get("url")
            gateway_id = response_data.get("id")

            # Consider HTTP 200/201 success, but also check their internal status markers
            is_success = (status == "success" and status_code == "100" and checkout_url)

            if is_success:
                # Update DB record with gateway details
                Payment.update(
                    payment_id,
                    business_id=business_id,
                    checkout_request_id=gateway_id or reference,
                    status=Payment.STATUS_PROCESSING,
                    gateway_response=response_data,      # store full response if you want
                    initial_response=response_data,      # keep compatibility with your existing schema
                )

                Log.info(f"{log_tag} Payment initiated successfully. checkout_url={checkout_url} gateway_id={gateway_id}")

                return True, {
                    "payment_id": str(payment_id),
                    "checkout_url": checkout_url,
                    "gateway_id": gateway_id,
                    "reference": reference,
                    "amount": amount_str,
                    "currency": from_currency,
                    "message": "Payment initiated. Redirecting to checkout..."
                }, None

            # Failure case: attempt to extract message
            error_msg = (
                response_data.get("message")
                or response_data.get("error")
                or response_data.get("status")
                or "Payment initiation failed"
            )

            Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=str(error_msg))
            Log.error(f"{log_tag} Payment initiation failed. error={error_msg} response={response_data}")
            return False, None, str(error_msg)

        except requests.exceptions.Timeout:
            Log.error(f"{log_tag} Request timeout")
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Request timeout")
            return False, None, "Request timeout. Please try again."

        except requests.exceptions.ConnectionError as e:
            Log.error(f"{log_tag} Connection error: {str(e)}")
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Connection error")
            return False, None, "Connection error: Unable to reach payment gateway."

        except requests.exceptions.RequestException as e:
            Log.error(f"{log_tag} Request error: {str(e)}")
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=str(e))
            return False, None, f"Network error: {str(e)}"

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=str(e))
            return False, None, str(e)
    
    