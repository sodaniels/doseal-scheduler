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
from ...utils.payments.hubtel_utils import get_hubtel_auth_token


class PaymentService:
    """Service for handling payment processing."""

    # ========================================
    # INTERNAL HELPERS
    # ========================================

    @staticmethod
    def _get_purchase_context(package_id=None, payment_details=None):
        """
        Resolve common payment context for both subscription and storage addon purchases.
        """
        payment_details = payment_details or {}
        metadata = payment_details.get("metadata", {}) or {}
        amount_detail = payment_details.get("amount_detail", {}) or {}

        purchase_type = metadata.get("purchase_type") or amount_detail.get("purchase_type") or "subscription"
        billing_period = payment_details.get("billing_period") or metadata.get("billing_period")

        package = None
        purchase_label = "Payment"

        if purchase_type == "subscription":
            if not package_id:
                return False, None, None, None, None, "Package ID is required for subscription payment"

            package = Package.get_by_id(package_id)
            if not package:
                return False, None, None, None, None, "Package not found"

            purchase_label = package.get("name") or package.get("tier") or "Subscription"

        elif purchase_type == "storage_addon":
            storage_addon_gb = (
                payment_details.get("storage_addon_gb")
                or metadata.get("storage_addon_gb")
                or amount_detail.get("storage_addon_gb")
            )
            if not storage_addon_gb:
                return False, None, None, None, None, "storage_addon_gb is required for storage addon payment"

            purchase_label = f"{storage_addon_gb}GB Storage Add-on"
        else:
            return False, None, None, None, None, "Invalid purchase_type"

        from_currency = amount_detail.get("from_currency") or "USD"
        amount = amount_detail.get("paid_amount")
        if amount is None:
            amount = amount_detail.get("total_from_amount")

        try:
            amount = float(amount or 0)
        except Exception:
            amount = 0

        if amount <= 0:
            return False, None, None, None, None, "Invalid payment amount"

        return True, package, purchase_type, purchase_label, from_currency, amount, None

    @staticmethod
    def _resolve_hubtel_config(gateway_credentials=None, gateway_settings=None):
        gateway_credentials = gateway_credentials or {}
        gateway_settings = gateway_settings or {}

        client_id = gateway_credentials.get("client_id") or os.getenv("HUBTEL_CLIENT_ID")
        client_secret = gateway_credentials.get("client_secret") or os.getenv("HUBTEL_CLIENT_SECRET")
        merchant_account = (
            gateway_credentials.get("merchant_account")
            or gateway_settings.get("merchant_account")
            or getattr(Config, "HUBTEL_MERCHANT_ACCOUNT_NUMBER", None)
            or os.getenv("HUBTEL_MERCHANT_ACCOUNT_NUMBER")
        )

        checkout_url = (
            gateway_settings.get("checkout_url")
            or getattr(Config, "HUBTEL_CHECKOUT_BASE_URL", None)
            or os.getenv("HUBTEL_CHECKOUT_BASE_URL")
        )

        callback_url = (
            gateway_settings.get("callback_url")
            or f"{Config.CALLBACK_BASE_URL}/webhooks/payment/hubtel"
        )

        return_url = (
            gateway_settings.get("return_url")
            or getattr(Config, "HUBTEL_RETURN_URL", None)
            or os.getenv("HUBTEL_RETURN_URL")
        )

        cancellation_url = (
            gateway_settings.get("cancellation_url")
            or getattr(Config, "HUBTEL_CANCELLATION_URL", None)
            or os.getenv("HUBTEL_CANCELLATION_URL")
        )

        return {
            "client_id": client_id,
            "client_secret": client_secret,
            "merchant_account": merchant_account,
            "checkout_url": checkout_url,
            "callback_url": callback_url,
            "return_url": return_url,
            "cancellation_url": cancellation_url,
        }

    @staticmethod
    def _build_hubtel_auth_token(client_id, client_secret):
        if not client_id or not client_secret:
            return None
        raw = f"{client_id}:{client_secret}"
        return base64.b64encode(raw.encode("utf-8")).decode("utf-8")

    @staticmethod
    def _resolve_asoriba_config(gateway_credentials=None, gateway_settings=None):
        gateway_credentials = gateway_credentials or {}
        gateway_settings = gateway_settings or {}

        public_key = (
            gateway_credentials.get("public_key")
            or gateway_credentials.get("pub_key")
            or getattr(PaymentConfig, "ASORIBA_API_KEY", None)
            or os.getenv("ASORIBA_API_KEY")
        )

        payment_url = (
            gateway_settings.get("payment_url")
            or getattr(PaymentConfig, "ASORIBA_PAYMENT_URL", None)
            or os.getenv("ASORIBA_PAYMENT_URL")
        )

        callback_url = (
            gateway_settings.get("callback_url")
            or getattr(PaymentConfig, "ASORIBA_CALL_BACK_URL", None)
            or os.getenv("ASORIBA_CALL_BACK_URL")
        )

        post_url = (
            gateway_settings.get("post_url")
            or getattr(PaymentConfig, "ASORIBA_POST_URL", None)
            or os.getenv("ASORIBA_POST_URL")
        )

        return_url = (
            gateway_settings.get("return_url")
            or getattr(PaymentConfig, "ASORIBA_RETURN_URL", None)
            or os.getenv("ASORIBA_RETURN_URL")
        )

        return {
            "public_key": public_key,
            "payment_url": payment_url,
            "callback_url": callback_url,
            "post_url": post_url,
            "return_url": return_url,
        }

    @staticmethod
    def _resolve_purchase_context(package_id, payment_details):
        """
        Returns:
            (ok, package, purchase_type, purchase_label, from_currency, amount, error)
        """
        try:
            amount_detail = payment_details.get("amount_detail", {}) or {}
            purchase_type = amount_detail.get("purchase_type", "subscription")
            from_currency = amount_detail.get("from_currency", "USD")
            amount = amount_detail.get("paid_amount") if amount_detail.get("paid_amount") else amount_detail.get("total_from_amount")

            package = {}
            purchase_label = "Payment"

            if purchase_type == "subscription":
                package = Package.get_by_id(package_id)
                if not package:
                    return False, None, None, None, None, None, "Package not found"

                purchase_label = package.get("name") or package.get("tier") or "Subscription"

            elif purchase_type == "storage_addon":
                storage_addon_gb = payment_details.get("storage_addon_gb") or amount_detail.get("storage_addon_gb")
                purchase_label = f"{storage_addon_gb}GB Storage Addon"

            return True, package, purchase_type, purchase_label, from_currency, amount, None

        except Exception as e:
            return False, None, None, None, None, None, str(e)

    @staticmethod
    def _resolve_stripe_config(gateway_credentials=None, gateway_settings=None):
        gateway_credentials = gateway_credentials or {}
        gateway_settings = gateway_settings or {}

        api_base = os.getenv("API_BASE_URL", "").rstrip("/")

        return {
            "secret_key": (
                gateway_credentials.get("secret_key")
                or os.getenv("STRIPE_SECRET_KEY", "")
            ),
            "publishable_key": (
                gateway_credentials.get("api_key")          # ← matches your "requires"
                or gateway_credentials.get("publishable_key")
                or os.getenv("STRIPE_PUBLISHABLE_KEY", "")
            ),
            "webhook_secret": (
                gateway_credentials.get("webhook_secret")   # ← from your "optional"
                or os.getenv("STRIPE_WEBHOOK_SECRET", "")
            ),
            "success_url": (
                gateway_settings.get("success_url")
                or gateway_settings.get("callback_url")
                or f"{api_base}/api/v1/webhooks/payment/stripe/callback?session_id={{CHECKOUT_SESSION_ID}}"
            ),
            "cancel_url": (
                gateway_settings.get("cancel_url")
                or gateway_settings.get("return_url")
                or os.getenv("PAYMENT_FRONT_END_RETURN_URL", "")
            ),
        }  
    
    @staticmethod
    def _resolve_paypal_config(gateway_credentials=None, gateway_settings=None):
        gateway_credentials = gateway_credentials or {}
        gateway_settings = gateway_settings or {}

        api_base = os.getenv("API_BASE_URL", "").rstrip("/")
        mode = gateway_settings.get("mode") or os.getenv("PAYPAL_MODE", "sandbox")

        return {
            "client_id": (
                gateway_credentials.get("client_id")
                or os.getenv("PAYPAL_CLIENT_ID", "")
            ),
            "client_secret": (
                gateway_credentials.get("client_secret")
                or gateway_credentials.get("secret_key")
                or os.getenv("PAYPAL_CLIENT_SECRET", "")
            ),
            "webhook_id": (
                gateway_credentials.get("webhook_id")
                or os.getenv("PAYPAL_WEBHOOK_ID", "")
            ),
            "mode": mode,
            "return_url": (
                gateway_settings.get("callback_url")
                or f"{api_base}/api/v1/webhooks/payment/paypal/callback"
            ),
            "cancel_url": (
                gateway_settings.get("cancel_url")
                or gateway_settings.get("return_url")
                or os.getenv("PAYMENT_FRONT_END_RETURN_URL", "")
            ),
        }
    
    @staticmethod
    def _resolve_flutterwave_config(gateway_credentials=None, gateway_settings=None):
        gateway_credentials = gateway_credentials or {}
        gateway_settings = gateway_settings or {}

        api_base = os.getenv("API_BASE_URL", "").rstrip("/")

        return {
            "secret_key": (
                gateway_credentials.get("secret_key")
                or os.getenv("FLW_SECRET_KEY", "")
            ),
            "public_key": (
                gateway_credentials.get("public_key")
                or gateway_credentials.get("api_key")
                or os.getenv("FLW_PUBLIC_KEY", "")
            ),
            "secret_hash": (
                gateway_credentials.get("secret_hash")
                or os.getenv("FLW_SECRET_HASH", "")
            ),
            "redirect_url": (
                gateway_settings.get("callback_url")
                or f"{api_base}/api/v1/webhooks/payment/flutterwave/callback"
            ),
            "cancel_url": (
                gateway_settings.get("cancel_url")
                or gateway_settings.get("return_url")
                or os.getenv("PAYMENT_FRONT_END_RETURN_URL", "")
            ),
        }
    
    
    @staticmethod
    def _resolve_mpesa_config(gateway_credentials=None, gateway_settings=None):
        gateway_credentials = gateway_credentials or {}
        gateway_settings = gateway_settings or {}

        api_base = os.getenv("API_BASE_URL", "").rstrip("/")
        mode = gateway_settings.get("mode") or os.getenv("MPESA_MODE", "sandbox")

        return {
            "consumer_key": gateway_credentials.get("consumer_key") or os.getenv("MPESA_CONSUMER_KEY", ""),
            "consumer_secret": gateway_credentials.get("consumer_secret") or os.getenv("MPESA_CONSUMER_SECRET", ""),
            "shortcode": gateway_credentials.get("shortcode") or os.getenv("MPESA_SHORTCODE", "174379"),
            "passkey": gateway_credentials.get("passkey") or os.getenv("MPESA_PASSKEY", ""),
            "mode": mode,
            "callback_url": gateway_settings.get("callback_url") or f"{api_base}/api/v1/webhooks/payment/mpesa",
        }
    
    
    
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
        gateway_credentials=None,
        gateway_settings=None,
        metadata=None
    ):
        log_tag = "[payment_service.py][PaymentService][initiate_hubtel_payment]"
        payment_id = None

        try:
            ok, package, purchase_type, purchase_label, from_currency, amount, error = (
                PaymentService._resolve_purchase_context(package_id, payment_details)
            )
            if not ok:
                return False, None, error

            gateway_credentials = gateway_credentials or {}
            gateway_settings = gateway_settings or {}
            metadata = metadata or {}

            client_id = gateway_credentials.get("client_id") or gateway_settings.get("client_id")
            client_secret = gateway_credentials.get("client_secret") or gateway_settings.get("client_secret")
            merchant_account = (
                gateway_credentials.get("merchant_account")
                or gateway_settings.get("merchant_account")
                or Config.HUBTEL_MERCHANT_ACCOUNT_NUMBER
            )
            callback_url = (
                gateway_settings.get("callback_url")
                or f"{Config.CALLBACK_BASE_URL}/webhooks/payment/hubtel"
            )
            return_url = (
                gateway_settings.get("return_url")
                or Config.HUBTEL_RETURN_URL
            )
            cancellation_url = (
                gateway_settings.get("cancellation_url")
                or Config.HUBTEL_CANCELLATION_URL
            )

            if not client_id or not client_secret:
                return False, None, "Hubtel client_id and client_secret are required"

            if not merchant_account:
                return False, None, "Hubtel merchant_account is required"

            auth_token = get_hubtel_auth_token(
                client_id=client_id,
                client_secret=client_secret,
            )
            if not auth_token:
                return False, None, "Failed to generate Hubtel auth token. Please check credentials."

            Log.info(
                f"{log_tag} Hubtel credential check: "
                f"client_id_present={bool(client_id)}, "
                f"client_secret_present={bool(client_secret)}, "
                f"merchant_account_present={bool(merchant_account)}"
            )

            reference = payment_details.get("internal_reference")
            amount_detail = payment_details.get("amount_detail", {}) or {}

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
                package_id=package_id if package_id else None,
                gateway="hubtel",
                order_id=reference,
                status=Payment.STATUS_PENDING,
                status_code=HTTP_STATUS_CODES["PENDING"],
                customer_name=customer_name,
                customer_phone=phone_number,
                customer_email=customer_email,
                metadata=metadata,
                callback_url=callback_url,
                redirect_url=return_url,
            )

            payment_id = payment.save()
            if not payment_id:
                return False, None, "Failed to create payment record"

            hubtel_url = Config.HUBTEL_CHECKOUT_BASE_URL

            headers = {
                "Authorization": f"Basic {auth_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            payload = {
                "totalAmount": amount,
                "description": f"{purchase_label} - {billing_period} ({Config.APP_NAME})",
                "clientReference": reference,
                "merchantAccountNumber": merchant_account,
                "callbackUrl": callback_url,
                "returnUrl": return_url,
                "cancellationUrl": cancellation_url,
            }

            Log.info(f"{log_tag} Sending Hubtel payment request")
            Log.info(f"{log_tag} URL: {hubtel_url}")
            Log.info(f"{log_tag} Reference: {reference}")
            Log.info(f"{log_tag} Amount: {from_currency} {amount}")

            response = requests.post(
                hubtel_url,
                json=payload,
                headers=headers,
                timeout=30,
            )

            Log.info(f"{log_tag} Response Status Code: {response.status_code}")
            Log.info(f"{log_tag} Response Headers: {dict(response.headers)}")
            Log.info(f"{log_tag} Response Text (first 500 chars): {response.text[:500]}")

            if not response.text or response.text.strip() == "":
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Empty response from payment gateway")
                return False, None, "Payment gateway returned empty response. Please check your Hubtel credentials."

            content_type = response.headers.get("Content-Type", "")
            if "application/json" not in content_type:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=f"Invalid response format: {content_type}")
                return False, None, f"Payment gateway returned invalid format: {content_type}. Response: {response.text[:200]}"

            try:
                response_data = response.json()
            except json.JSONDecodeError as e:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Invalid JSON response from gateway")
                return False, None, f"Invalid JSON response from payment gateway: {str(e)}"

            Log.info(f"{log_tag} Hubtel response parsed: {json.dumps(response_data, indent=2)}")

            if response.status_code in [200, 201]:
                checkout_url = None
                checkout_id = None
                data_obj = {}

                if isinstance(response_data, dict):
                    data_obj = response_data.get("data", {}) if isinstance(response_data.get("data", {}), dict) else {}
                    checkout_url = (
                        data_obj.get("checkoutUrl")
                        or data_obj.get("CheckoutUrl")
                        or response_data.get("checkoutUrl")
                        or response_data.get("CheckoutUrl")
                    )
                    checkout_id = (
                        data_obj.get("checkoutId")
                        or data_obj.get("CheckoutId")
                        or response_data.get("checkoutId")
                        or response_data.get("CheckoutId")
                    )

                    if not checkout_url:
                        data_obj_upper = response_data.get("Data", {})
                        if isinstance(data_obj_upper, dict):
                            checkout_url = data_obj_upper.get("CheckoutUrl")
                            checkout_id = data_obj_upper.get("CheckoutId")

                if checkout_url:
                    Payment.update(
                        payment_id,
                        business_id=business_id,
                        checkout_request_id=checkout_id or reference,
                        status=Payment.STATUS_PROCESSING,
                        initial_response=data_obj or response_data,
                    )

                    return True, {
                        "payment_id": str(payment_id),
                        "checkout_url": checkout_url,
                        "checkout_id": checkout_id,
                        "reference": reference,
                        "amount": amount,
                        "currency": from_currency,
                        "message": "Payment initiated. Redirecting to Hubtel checkout...",
                    }, None

                error_msg = response_data.get("message") or response_data.get("Message") or "Failed to get checkout URL"
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                return False, None, error_msg

            elif response.status_code == 400:
                error_msg = response_data.get("message") or response_data.get("Message") or "Bad request"
                errors = response_data.get("errors") or response_data.get("Errors") or []
                if errors:
                    error_msg = f"{error_msg}: {', '.join([str(e) for e in errors])}"
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                return False, None, error_msg

            elif response.status_code == 401:
                error_msg = "Invalid Hubtel credentials. Please check your client_id and client_secret."
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                return False, None, error_msg

            elif response.status_code == 403:
                error_msg = "Access forbidden. Please check your Hubtel account permissions."
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                return False, None, error_msg

            elif response.status_code == 404:
                error_msg = "Hubtel API endpoint not found. Please check the base URL."
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                return False, None, error_msg

            elif response.status_code >= 500:
                error_msg = "Hubtel server error. Please try again later."
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
                return False, None, error_msg

            error_msg = response_data.get("message") or response_data.get("Message") or f"Payment failed (Status: {response.status_code})"
            Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_msg)
            return False, None, error_msg

        except requests.exceptions.Timeout:
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Request timeout")
            return False, None, "Request timeout. Please try again."

        except requests.exceptions.ConnectionError:
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Connection error")
            return False, None, "Connection error: Unable to reach payment gateway"

        except requests.exceptions.RequestException as e:
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=str(e))
            return False, None, f"Network error: {str(e)}"

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=str(e))
            return False, None, str(e)

    # ========================================
    # VERIFY PAYMENT
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
        log_tag = "[PaymentService][verify_payment_status]"

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
                "payment": payment,
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
        **kwargs,
    ):
        """
        Create manual payment (for bank transfers, cash, etc.).
        """
        log_tag = "[PaymentService][create_manual_payment]"

        try:
            package = Package.get_by_id(package_id)
            if not package:
                return False, None, "Package not found"

            reference = generate_internal_reference("MANUAL")

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
                status=Payment.STATUS_SUCCESS,
                customer_phone=kwargs.get("customer_phone"),
                customer_email=kwargs.get("customer_email"),
                customer_name=kwargs.get("customer_name"),
                notes=kwargs.get("notes"),
                metadata={"billing_period": billing_period},
            )

            payment.completed_at = datetime.utcnow()
            payment_id = payment.save()

            if payment_id:
                Log.info(f"{log_tag} Manual payment created: {payment_id}")
                return True, str(payment_id), None

            return False, None, "Failed to create payment record"

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False, None, str(e)

    # ========================================
    # ASORIBA PAYMENT METHODS
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
        gateway_credentials=None,
        gateway_settings=None,
        metadata=None,
    ):
        """
        Initiate ASORIBA (MyBusinessPay) payment.

        Returns:
            Tuple (success: bool, data: dict or None, error: str or None)
        """
        log_tag = "[payment_service.py][PaymentService][initiate_asoriba_payment]"
        payment_id = None

        try:
            ok, package, purchase_type, purchase_label, from_currency, amount, error = (
                PaymentService._get_purchase_context(
                    package_id=package_id,
                    payment_details=payment_details,
                )
            )
            if not ok:
                return False, None, error

            reference = payment_details.get("internal_reference")
            amount_detail = payment_details.get("amount_detail", {}) or {}
            first, last = split_name(customer_name or "")

            asoriba_cfg = PaymentService._resolve_asoriba_config(
                gateway_credentials=gateway_credentials,
                gateway_settings=gateway_settings,
            )

            if not asoriba_cfg["public_key"]:
                return False, None, "Missing Asoriba public key"

            if not asoriba_cfg["payment_url"]:
                return False, None, "Missing Asoriba payment URL"

            payment_type = (
                Payment.TYPE_SUBSCRIPTION
                if purchase_type == "subscription"
                else "storage_addon"
            )

            payment = Payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                reference=reference,
                amount=amount,
                currency=from_currency,
                amount_detail=amount_detail,
                payment_method=PAYMENT_METHODS["ASORIBA"],
                payment_type=payment_type,
                package_id=package_id,
                gateway="asoriba",
                order_id=reference,
                status=Payment.STATUS_PENDING,
                status_code=HTTP_STATUS_CODES["PENDING"],
                customer_name=customer_name,
                customer_phone=phone_number,
                customer_email=customer_email,
                metadata=metadata or {},
                callback_url=asoriba_cfg["callback_url"],
                redirect_url=asoriba_cfg["return_url"],
            )

            payment_id = payment.save()
            if not payment_id:
                return False, None, "Failed to create payment record"

            Log.info(f"{log_tag} Payment record created: {payment_id} reference={reference}")

            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }

            amount_str = str(amount)

            merged_metadata = {
                "order_id": reference,
                "product_name": purchase_label,
                "product_description": f"{purchase_label} payment",
            }
            if isinstance(metadata, dict):
                merged_metadata.update(metadata)

            payload = {
                "metadata": merged_metadata,
                "amount": amount_str,
                "currency": from_currency,
                "callback": asoriba_cfg["callback_url"],
                "post_url": asoriba_cfg["post_url"],
                "pub_key": asoriba_cfg["public_key"],
                "first_name": first,
                "last_name": last,
                "email": customer_email,
                "phone_number": phone_number,
            }

            Log.info(
                f"{log_tag} Sending Asoriba request url={asoriba_cfg['payment_url']} "
                f"ref={reference} amount={amount_str} {from_currency}"
            )

            response = requests.post(
                asoriba_cfg["payment_url"],
                json=payload,
                headers=headers,
                timeout=30,
            )

            Log.info(f"{log_tag} Gateway HTTP status={response.status_code}")
            Log.info(f"{log_tag} Gateway response (first 500 chars)={response.text[:500]}")

            if not response.text or response.text.strip() == "":
                Payment.update_status(
                    payment_id,
                    Payment.STATUS_FAILED,
                    error_message="Empty response from Asoriba gateway",
                )
                return False, None, "Payment gateway returned empty response."

            try:
                response_data = response.json()
            except json.JSONDecodeError:
                Payment.update_status(
                    payment_id,
                    Payment.STATUS_FAILED,
                    error_message="Non-JSON response from Asoriba gateway",
                )
                return False, None, f"Payment gateway returned non-JSON response: {response.text[:200]}"

            Log.info(f"{log_tag} Parsed gateway response: {json.dumps(response_data, indent=2)}")

            status = str(response_data.get("status", "")).lower()
            status_code = str(response_data.get("status_code", ""))
            checkout_url = response_data.get("url")
            gateway_id = response_data.get("id")

            is_success = (status == "success" and status_code == "100" and checkout_url)

            if is_success:
                Payment.update(
                    payment_id,
                    business_id=business_id,
                    checkout_request_id=gateway_id or reference,
                    status=Payment.STATUS_PROCESSING,
                    gateway_response=response_data,
                    initial_response=response_data,
                )

                Log.info(
                    f"{log_tag} Payment initiated successfully. "
                    f"checkout_url={checkout_url} gateway_id={gateway_id}"
                )

                return True, {
                    "payment_id": str(payment_id),
                    "checkout_url": checkout_url,
                    "gateway_id": gateway_id,
                    "reference": reference,
                    "amount": amount_str,
                    "currency": from_currency,
                    "message": "Payment initiated. Redirecting to checkout...",
                }, None

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

    @staticmethod
    def get_payment_method_for_subscription(business_id):
        """
        Get the best available payment method for subscription charging.
        Used by the subscription resource when determining how to charge.
        """
        from ...models.church.payment_method_model import PaymentMethod

        method = PaymentMethod.get_chargeable_method(business_id)
        if method:
            return {
                "provider": method.get("provider"),
                "method_id": method.get("_id"),
                "label": method.get("label"),
                "last4": method.get("last4"),
                "card_type": method.get("card_type"),
                "is_primary": method.get("is_primary"),
            }
        return None
    
    
    # ========================================
    # STRIPE PAYMENT METHODS
    # ========================================
    @staticmethod
    def initiate_stripe_payment(
        business_id, user_id, user__id, package_id,
        billing_period=None, customer_name=None, customer_email=None,
        payment_details=None, phone_number=None, metadata=None,
        gateway_credentials=None, gateway_settings=None,
    ):
        log_tag = "[payment_service.py][PaymentService][initiate_stripe_payment]"
        payment_id = None

        try:
            ok, package, purchase_type, purchase_label, from_currency, amount, error = (
                PaymentService._get_purchase_context(
                    package_id=package_id,
                    payment_details=payment_details,
                )
            )
            if not ok:
                return False, None, error

            reference = payment_details.get("internal_reference")
            amount_detail = payment_details.get("amount_detail", {}) or {}

            stripe_cfg = PaymentService._resolve_stripe_config(
                gateway_credentials=gateway_credentials,
                gateway_settings=gateway_settings,
            )

            if not stripe_cfg["secret_key"]:
                return False, None, "Missing Stripe secret key"

            # Temporarily set env for utility
            os.environ["STRIPE_SECRET_KEY"] = stripe_cfg["secret_key"]

            # Determine charge amount and currency
            charge_amount = float(amount_detail.get("total_to_amount") or amount_detail.get("total_from_amount") or amount)
            charge_currency = (amount_detail.get("to_currency") or from_currency or "usd").lower()

            payment_type = (
                Payment.TYPE_SUBSCRIPTION
                if purchase_type == "subscription"
                else "storage_addon"
            )

            # Save payment record
            payment = Payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                reference=reference,
                amount=amount,
                currency=from_currency,
                amount_detail=amount_detail,
                payment_method=PAYMENT_METHODS["STRIPE"],
                payment_type=payment_type,
                package_id=package_id,
                gateway="stripe",
                order_id=reference,
                status=Payment.STATUS_PENDING,
                customer_name=customer_name,
                customer_phone=phone_number,
                customer_email=customer_email,
                metadata=metadata or {},
            )

            payment_id = payment.save()
            if not payment_id:
                return False, None, "Failed to create payment record"

            Log.info(f"{log_tag} Payment record created: {payment_id} ref={reference}")

            # Build success URL with session ID placeholder
            api_base = os.getenv("API_BASE_URL", "").rstrip("/")
            success_url = (
                stripe_cfg.get("success_url")
                or f"{api_base}/api/v1/payments/stripe/callback?session_id={{CHECKOUT_SESSION_ID}}&reference={reference}"
            )
            # Stripe requires {CHECKOUT_SESSION_ID} placeholder
            if "{CHECKOUT_SESSION_ID}" not in success_url:
                separator = "&" if "?" in success_url else "?"
                success_url += f"{separator}session_id={{CHECKOUT_SESSION_ID}}"

            cancel_url = stripe_cfg.get("cancel_url") or os.getenv("PAYMENT_FRONT_END_RETURN_URL", "")
            if cancel_url and "?" not in cancel_url:
                cancel_url += f"?status=cancelled&reference={reference}"

            from ...utils.payments.stripe_utils import create_checkout_session

            success, stripe_data, error = create_checkout_session(
                amount=charge_amount,
                currency=charge_currency,
                customer_email=customer_email,
                reference=reference,
                success_url=success_url,
                cancel_url=cancel_url,
                description=f"WorshipDesk {purchase_label} - {billing_period or 'monthly'}",
                metadata=metadata,
                line_item_name=purchase_label,
            )

            if not success:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error)
                Log.error(f"{log_tag} Stripe session failed: {error}")
                return False, None, error

            # Update payment with Stripe session info
            Payment.update(
                payment_id,
                business_id=business_id,
                checkout_request_id=stripe_data.get("session_id"),
                checkout_url=stripe_data.get("checkout_url"),
                status=Payment.STATUS_PROCESSING,
                gateway_response=stripe_data.get("raw"),
                initial_response=stripe_data.get("raw"),
                processing_callback=True,
            )

            Log.info(f"{log_tag} Checkout session created: {stripe_data.get('session_id')}")

            return True, {
                "payment_id": str(payment_id),
                "checkout_url": stripe_data.get("checkout_url"),
                "session_id": stripe_data.get("session_id"),
                "reference": reference,
                "amount": str(charge_amount),
                "currency": charge_currency,
                "publishable_key": stripe_cfg["publishable_key"],
                "message": "Payment initiated. Redirecting to Stripe checkout...",
            }, None

        except requests.exceptions.Timeout:
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message="Request timeout")
            return False, None, "Request timeout. Please try again."

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=str(e))
            return False, None, str(e)
    
    # ========================================
    # PAYPAL PAYMENT METHODS
    # ========================================
    @staticmethod
    def initiate_paypal_payment(
        business_id, user_id, user__id, package_id,
        billing_period=None, customer_name=None, customer_email=None,
        payment_details=None, phone_number=None, metadata=None,
        gateway_credentials=None, gateway_settings=None,
    ):
        log_tag = "[payment_service.py][PaymentService][initiate_paypal_payment]"
        payment_id = None

        try:
            ok, package, purchase_type, purchase_label, from_currency, amount, error = (
                PaymentService._get_purchase_context(
                    package_id=package_id,
                    payment_details=payment_details,
                )
            )
            if not ok:
                return False, None, error

            reference = payment_details.get("internal_reference")
            amount_detail = payment_details.get("amount_detail", {}) or {}

            paypal_cfg = PaymentService._resolve_paypal_config(
                gateway_credentials=gateway_credentials,
                gateway_settings=gateway_settings,
            )

            if not paypal_cfg["client_id"] or not paypal_cfg["client_secret"]:
                return False, None, "Missing PayPal credentials"

            # Set env for utility
            os.environ["PAYPAL_CLIENT_ID"] = paypal_cfg["client_id"]
            os.environ["PAYPAL_CLIENT_SECRET"] = paypal_cfg["client_secret"]
            os.environ["PAYPAL_MODE"] = paypal_cfg["mode"]

            charge_amount = float(amount_detail.get("total_to_amount") or amount_detail.get("total_from_amount") or amount)
            charge_currency = (amount_detail.get("to_currency") or from_currency or "USD").upper()

            payment_type = (
                Payment.TYPE_SUBSCRIPTION
                if purchase_type == "subscription"
                else "storage_addon"
            )

            # Save payment record
            payment = Payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                reference=reference,
                amount=amount,
                currency=from_currency,
                amount_detail=amount_detail,
                payment_method=PAYMENT_METHODS["PAYPAL"],
                payment_type=payment_type,
                package_id=package_id,
                gateway="paypal",
                order_id=reference,
                status=Payment.STATUS_PENDING,
                customer_name=customer_name,
                customer_phone=phone_number,
                customer_email=customer_email,
                metadata=metadata or {},
            )

            payment_id = payment.save()
            if not payment_id:
                return False, None, "Failed to create payment record"

            Log.info(f"{log_tag} Payment saved: {payment_id} ref={reference}")

            # Build return URL with reference
            return_url = paypal_cfg["return_url"]
            if return_url and "?" not in return_url:
                return_url += f"?reference={reference}"
            elif return_url:
                return_url += f"&reference={reference}"

            cancel_url = paypal_cfg["cancel_url"]
            if cancel_url and "?" not in cancel_url:
                cancel_url += f"?status=cancelled&reference={reference}"

            from ...utils.payments.paypal_utils import create_order

            success, paypal_data, error = create_order(
                amount=charge_amount,
                currency=charge_currency,
                reference=reference,
                description=f"WorshipDesk {purchase_label} - {billing_period or 'monthly'}",
                return_url=return_url,
                cancel_url=cancel_url,
                customer_email=customer_email,
                customer_name=customer_name,
                metadata=metadata,
            )

            if not success:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error)
                return False, None, error

            # Store PayPal order ID
            paypal_order_id = paypal_data.get("order_id")
            Payment.update(
                payment_id,
                business_id=business_id,
                checkout_request_id=paypal_order_id,
                checkout_url=paypal_data.get("checkout_url"),
                status=Payment.STATUS_PROCESSING,
                gateway_response=paypal_data.get("raw"),
                processing_callback=True,
            )

            Log.info(f"{log_tag} PayPal order created: {paypal_order_id}")

            return True, {
                "payment_id": str(payment_id),
                "checkout_url": paypal_data.get("checkout_url"),
                "order_id": paypal_order_id,
                "reference": reference,
                "amount": str(charge_amount),
                "currency": charge_currency,
                "message": "Payment initiated. Redirecting to PayPal...",
            }, None

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=str(e))
            return False, None, str(e)


    # ========================================
    # FLUTTERWAVE PAYMENT METHODS
    # ========================================
    @staticmethod
    def initiate_flutterwave_payment(
        business_id, user_id, user__id, package_id,
        billing_period=None, customer_name=None, customer_email=None,
        payment_details=None, phone_number=None, metadata=None,
        gateway_credentials=None, gateway_settings=None,
    ):
        log_tag = "[payment_service.py][PaymentService][initiate_flutterwave_payment]"
        payment_id = None

        try:
            ok, package, purchase_type, purchase_label, from_currency, amount, error = (
                PaymentService._get_purchase_context(
                    package_id=package_id,
                    payment_details=payment_details,
                )
            )
            if not ok:
                return False, None, error

            reference = payment_details.get("internal_reference")
            amount_detail = payment_details.get("amount_detail", {}) or {}

            flw_cfg = PaymentService._resolve_flutterwave_config(
                gateway_credentials=gateway_credentials,
                gateway_settings=gateway_settings,
            )

            if not flw_cfg["secret_key"]:
                return False, None, "Missing Flutterwave secret key"

            os.environ["FLW_SECRET_KEY"] = flw_cfg["secret_key"]
            os.environ["FLW_PUBLIC_KEY"] = flw_cfg["public_key"]

            charge_amount = float(amount_detail.get("total_to_amount") or amount_detail.get("total_from_amount") or amount)
            charge_currency = (amount_detail.get("to_currency") or from_currency or "USD").upper()

            payment_type = (
                Payment.TYPE_SUBSCRIPTION
                if purchase_type == "subscription"
                else "storage_addon"
            )

            payment = Payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                reference=reference,
                amount=amount,
                currency=from_currency,
                amount_detail=amount_detail,
                payment_method=PAYMENT_METHODS["FLUTTERWAVE"],
                payment_type=payment_type,
                package_id=package_id,
                gateway="flutterwave",
                order_id=reference,
                status=Payment.STATUS_PENDING,
                customer_name=customer_name,
                customer_phone=phone_number,
                customer_email=customer_email,
                metadata=metadata or {},
            )

            payment_id = payment.save()
            if not payment_id:
                return False, None, "Failed to create payment record"

            Log.info(f"{log_tag} Payment saved: {payment_id} ref={reference}")

            redirect_url = flw_cfg["redirect_url"]
            if redirect_url and "?" not in redirect_url:
                redirect_url += f"?reference={reference}"
            elif redirect_url:
                redirect_url += f"&reference={reference}"

            from ...utils.payments.flutterwave_utils import initialize_payment as flw_init

            success, flw_data, error = flw_init(
                amount=charge_amount,
                currency=charge_currency,
                tx_ref=reference,
                redirect_url=redirect_url,
                customer_email=customer_email,
                customer_name=customer_name,
                customer_phone=phone_number,
                description=f"WorshipDesk {purchase_label} - {billing_period or 'monthly'}",
                metadata=metadata,
                customizations={
                    "title": "WorshipDesk",
                    "description": purchase_label,
                },
            )

            if not success:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error)
                return False, None, error

            Payment.update(
                payment_id, business_id=business_id,
                checkout_url=flw_data.get("checkout_url"),
                status=Payment.STATUS_PROCESSING,
                gateway_response=flw_data.get("raw"),
                processing_callback=True,
            )

            Log.info(f"{log_tag} Flutterwave checkout created")

            return True, {
                "payment_id": str(payment_id),
                "checkout_url": flw_data.get("checkout_url"),
                "reference": reference,
                "amount": str(charge_amount),
                "currency": charge_currency,
                "message": "Payment initiated. Redirecting to Flutterwave...",
            }, None

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=str(e))
            return False, None, str(e)


    # ========================================
    # MPESA PAYMENT METHODS
    # ========================================
    @staticmethod
    def initiate_mpesa_payment(
        business_id, user_id, user__id, package_id,
        billing_period=None, customer_name=None, customer_email=None,
        payment_details=None, phone_number=None, metadata=None,
        gateway_credentials=None, gateway_settings=None,
    ):
        log_tag = "[PaymentService][initiate_mpesa_payment]"
        payment_id = None

        try:
            ok, package, purchase_type, purchase_label, from_currency, amount, error = (
                PaymentService._get_purchase_context(
                    package_id=package_id,
                    payment_details=payment_details,
                )
            )
            if not ok:
                return False, None, error

            if not phone_number:
                return False, None, "Phone number is required for M-Pesa payments"

            reference = payment_details.get("internal_reference")
            amount_detail = payment_details.get("amount_detail", {}) or {}

            mpesa_cfg = PaymentService._resolve_mpesa_config(
                gateway_credentials=gateway_credentials,
                gateway_settings=gateway_settings,
            )

            if not mpesa_cfg["consumer_key"] or not mpesa_cfg["consumer_secret"]:
                return False, None, "Missing M-Pesa credentials"
            if not mpesa_cfg["passkey"]:
                return False, None, "Missing M-Pesa passkey"

            # Set env for utility
            os.environ["MPESA_CONSUMER_KEY"] = mpesa_cfg["consumer_key"]
            os.environ["MPESA_CONSUMER_SECRET"] = mpesa_cfg["consumer_secret"]
            os.environ["MPESA_SHORTCODE"] = mpesa_cfg["shortcode"]
            os.environ["MPESA_PASSKEY"] = mpesa_cfg["passkey"]
            os.environ["MPESA_MODE"] = mpesa_cfg["mode"]

            # M-Pesa uses KES — convert if needed
            charge_amount = float(amount_detail.get("total_to_amount") or amount_detail.get("total_from_amount") or amount)
            charge_currency = (amount_detail.get("to_currency") or "KES").upper()

            payment_type = (
                Payment.TYPE_SUBSCRIPTION
                if purchase_type == "subscription"
                else "storage_addon"
            )

            payment = Payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                reference=reference,
                amount=amount,
                currency=from_currency,
                amount_detail=amount_detail,
                payment_method=PAYMENT_METHODS.get("MPESA", "mpesa"),
                payment_type=payment_type,
                package_id=package_id,
                gateway="mpesa",
                order_id=reference,
                status=Payment.STATUS_PENDING,
                customer_name=customer_name,
                customer_phone=phone_number,
                customer_email=customer_email,
                metadata=metadata or {},
            )

            payment_id = payment.save()
            if not payment_id:
                return False, None, "Failed to create payment record"

            Log.info(f"{log_tag} Payment saved: {payment_id} ref={reference}")

            from ...utils.payments.mpesa_utils import initiate_stk_push

            success, mpesa_data, error = initiate_stk_push(
                phone_number=phone_number,
                amount=charge_amount,
                account_reference=reference[:12] if reference else "WorshipDesk",
                description="Payment",
                callback_url=mpesa_cfg["callback_url"],
                reference=reference,
                metadata=metadata,
            )

            if not success:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error)
                return False, None, error

            # Store checkout_request_id for callback matching
            Payment.update(
                payment_id, business_id=business_id,
                checkout_request_id=mpesa_data.get("checkout_request_id"),
                status=Payment.STATUS_PROCESSING,
                gateway_response=mpesa_data.get("raw"),
                processing_callback=True,
            )

            Log.info(f"{log_tag} STK Push sent: {mpesa_data.get('checkout_request_id')}")

            return True, {
                "payment_id": str(payment_id),
                "checkout_request_id": mpesa_data.get("checkout_request_id"),
                "merchant_request_id": mpesa_data.get("merchant_request_id"),
                "reference": reference,
                "phone": mpesa_data.get("phone"),
                "amount": str(charge_amount),
                "currency": charge_currency,
                "message": mpesa_data.get("message") or "Please check your phone to complete the payment",
            }, None

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if payment_id:
                Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=str(e))
            return False, None, str(e)














