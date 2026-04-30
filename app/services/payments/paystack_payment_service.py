# services/payments/paystack_payment_service.py

"""
Paystack Payment Service Methods
=================================
Supports:
- Integration-based Paystack credentials
- Env fallback
- Subscription payments
- Storage add-on payments
- Saving reusable cards
"""

import os
from datetime import datetime
from bson import ObjectId

from ...utils.logger import Log
from ...utils.generators import generate_internal_reference
from ...utils.payments.paystack_utils import (
    initialize_transaction,
    verify_transaction,
    charge_authorization,
    to_subunit,
    get_paystack_currency,
)
from ...constants.service_code import HTTP_STATUS_CODES
from ...models.admin.payment import Payment


class PaystackPaymentMixin:
    """
    Mixin containing Paystack-specific methods.
    """

    @staticmethod
    def _resolve_paystack_config(gateway_credentials=None, gateway_settings=None):
        """
        Resolve Paystack config from integration credentials first,
        then fall back to environment variables.
        """
        gateway_credentials = gateway_credentials or {}
        gateway_settings = gateway_settings or {}

        secret_key = (
            gateway_credentials.get("secret_key")
            or os.getenv("PAYSTACK_SECRET_KEY")
        )

        public_key = (
            gateway_credentials.get("public_key")
            or os.getenv("PAYSTACK_PUBLIC_KEY")
        )

        callback_url = (
            gateway_settings.get("callback_url")
            or os.getenv("PAYSTACK_CALLBACK_URL")
            or os.getenv("APP_BASE_URL", "") + "/api/v1/webhooks/payment/paystack"
        )

        return_url = (
            gateway_settings.get("return_url")
            or os.getenv("PAYMENT_FRONT_END_RETURN_URL")
            or os.getenv("PAYSTACK_RETURN_URL")
        )

        currency = (
            gateway_settings.get("currency")
            or "GHS"
        )

        return {
            "secret_key": secret_key,
            "public_key": public_key,
            "callback_url": callback_url,
            "return_url": return_url,
            "currency": currency,
        }

    @staticmethod
    def initiate_paystack_payment(
        business_id: str,
        user_id: str,
        user__id: str,
        package_id: str,
        billing_period: str,
        customer_name: str,
        customer_email: str,
        payment_details: dict,
        phone_number: str = None,
        metadata: dict = None,
        gateway_credentials: dict = None,
        gateway_settings: dict = None,
    ) -> tuple:
        """
        Initialize a Paystack payment transaction.
        """
        log_tag = f"[PaystackPaymentService][initiate_paystack_payment][{business_id}]"

        try:
            metadata = metadata or {}
            payment_details = payment_details or {}
            amount_detail = payment_details.get("amount_detail", {}) or {}

            paystack_cfg = PaystackPaymentMixin._resolve_paystack_config(
                gateway_credentials=gateway_credentials,
                gateway_settings=gateway_settings,
            )

            if not paystack_cfg["secret_key"]:
                return False, None, "Missing Paystack secret key"

            if not customer_email:
                return False, None, "Customer email is required for Paystack"

            purchase_type = (
                metadata.get("purchase_type")
                or amount_detail.get("purchase_type")
                or "subscription"
            )

            if os.getenv("APP_ENV") == "development" and amount_detail.get("paid_amount"):
                charge_amount = float(amount_detail["paid_amount"])
            else:
                charge_amount = float(amount_detail.get("total_to_amount", 0))

            if charge_amount <= 0:
                return False, None, "Invalid payment amount"

            currency = amount_detail.get("to_currency") or paystack_cfg["currency"]
            reference = payment_details.get("internal_reference") or generate_internal_reference("PSK")
            amount_subunit = to_subunit(charge_amount)

            paystack_metadata = {
                "business_id": str(business_id),
                "user_id": user_id,
                "user__id": str(user__id),
                "package_id": package_id,
                "billing_period": billing_period,
                "internal_reference": reference,
                "purchase_type": purchase_type,
                "custom_fields": [
                    {
                        "display_name": "Customer Name",
                        "variable_name": "customer_name",
                        "value": customer_name or "",
                    },
                    {
                        "display_name": "Billing Period",
                        "variable_name": "billing_period",
                        "value": billing_period or "",
                    },
                    {
                        "display_name": "Purchase Type",
                        "variable_name": "purchase_type",
                        "value": purchase_type,
                    },
                ],
            }

            if package_id:
                paystack_metadata["package_id"] = package_id

            if metadata:
                paystack_metadata.update(metadata)

            channels = ["card", "bank_transfer"]
            if currency == "GHS":
                channels.append("mobile_money")
            elif currency == "NGN":
                channels.extend(["bank", "ussd"])

            # IMPORTANT:
            # initialize_transaction in your utils likely uses env internally.
            # You should update that util too so it can accept `secret_key`.
            success, ps_data, error = initialize_transaction(
                email=customer_email,
                amount_subunit=amount_subunit,
                reference=reference,
                currency=currency,
                callback_url=paystack_cfg["return_url"],
                channels=channels,
                metadata=paystack_metadata,
                secret_key=paystack_cfg["secret_key"],   # add this support in utils
            )

            if not success:
                Log.error(f"{log_tag} Paystack initialization failed: {error}")
                return False, None, error

            payment_type = (
                Payment.TYPE_SUBSCRIPTION
                if purchase_type == "subscription"
                else "storage_addon"
            )

            payment = Payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                amount=charge_amount,
                amount_detail=amount_detail,
                payment_method="paystack",
                payment_type=payment_type,
                reference=reference,
                currency=currency,
                package_id=package_id,
                gateway="paystack",
                checkout_request_id=ps_data.get("access_code"),
                order_id=reference,
                status=Payment.STATUS_PENDING,
                status_message="Transaction initialized",
                status_code=HTTP_STATUS_CODES["PENDING"],
                initial_response=ps_data,
                customer_phone=phone_number,
                customer_email=customer_email,
                customer_name=customer_name,
                metadata=paystack_metadata,
                callback_url=paystack_cfg["callback_url"],
                redirect_url=ps_data.get("authorization_url"),
            )

            payment_id = payment.save()

            if not payment_id:
                return False, None, "Failed to save payment record"

            Log.info(f"{log_tag} Payment record created. ref={reference}")

            return True, {
                "message": "Payment initialized. Redirect customer to authorization_url.",
                "authorization_url": ps_data.get("authorization_url"),
                "access_code": ps_data.get("access_code"),
                "reference": reference,
                "amount": charge_amount,
                "currency": currency,
            }, None

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False, None, str(e)

    @staticmethod
    def verify_paystack_payment(reference: str, secret_key: str = None) -> tuple:
        """
        Verify a Paystack transaction and update the local Payment record.
        """
        log_tag = f"[PaystackPaymentService][verify_paystack_payment][{reference}]"

        try:
            success, ps_data, error = verify_transaction(
                reference,
                secret_key=secret_key,   # add this support in utils too
            )

            if not success:
                return False, None, error

            txn_status = ps_data.get("status")
            gateway_response = ps_data.get("gateway_response")
            gateway_txn_id = str(ps_data.get("id", ""))

            payment = Payment.get_by_reference(reference)

            if not payment:
                Log.error(f"{log_tag} No local payment found for ref={reference}")
                return False, None, "Payment record not found"

            payment_id = payment.get("_id")

            if txn_status == "success":
                Payment.update_status(
                    payment_id=payment_id,
                    new_status=Payment.STATUS_SUCCESS,
                    gateway_transaction_id=gateway_txn_id,
                )

                authorization = ps_data.get("authorization", {}) or {}
                if authorization.get("reusable"):
                    from ...models.church.payment_method_model import PaymentMethod

                    ps_metadata = ps_data.get("metadata", {}) or {}
                    PaymentMethod.save_from_paystack(
                        business_id=ps_metadata.get("business_id") or str(payment.get("business_id", "")),
                        paystack_response=ps_data,
                        user_id=ps_metadata.get("user_id") or payment.get("user_id"),
                        user__id=ps_metadata.get("user__id") or str(payment.get("user__id", "")),
                        set_as_primary=ps_metadata.get("set_as_primary", False),
                        label=ps_metadata.get("label"),
                    )
                    Log.info(f"{log_tag} Card saved from verification")

            elif txn_status == "failed":
                Payment.update_status(
                    payment_id=payment_id,
                    new_status=Payment.STATUS_FAILED,
                    gateway_transaction_id=gateway_txn_id,
                    error_message=gateway_response,
                )
                Log.info(f"{log_tag} Payment failed: {gateway_response}")
            else:
                Log.info(f"{log_tag} Payment status: {txn_status}")

            return True, {
                "status": txn_status,
                "gateway_response": gateway_response,
                "gateway_transaction_id": gateway_txn_id,
                "amount": ps_data.get("amount"),
                "currency": ps_data.get("currency"),
                "channel": ps_data.get("channel"),
                "paid_at": ps_data.get("paid_at"),
                "authorization": ps_data.get("authorization"),
                "customer": ps_data.get("customer"),
                "metadata": ps_data.get("metadata"),
                "reference": reference,
                "payment_id": payment_id,
            }, None

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False, None, str(e)

    @staticmethod
    def handle_paystack_webhook_event(event: dict) -> tuple:
        """
        Process an incoming Paystack webhook event.
        """
        log_tag = "[PaystackPaymentService][handle_paystack_webhook_event]"

        try:
            event_type = event.get("event")
            data = event.get("data", {})
            reference = data.get("reference")

            Log.info(f"{log_tag} Received event: {event_type}, ref={reference}")

            if event_type == "charge.success":
                return PaystackPaymentMixin._handle_charge_success(data, reference)

            elif event_type == "charge.failed":
                return PaystackPaymentMixin._handle_charge_failed(data, reference)

            else:
                Log.info(f"{log_tag} Unhandled event type: {event_type}")
                return True, f"Event {event_type} acknowledged"

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False, str(e)

    @staticmethod
    def _handle_charge_success(data: dict, reference: str) -> tuple:
        log_tag = f"[PaystackPaymentService][_handle_charge_success][{reference}]"

        try:
            payment = Payment.get_by_reference(reference)

            if not payment:
                Log.error(f"{log_tag} Payment not found")
                return False, "Payment record not found"

            payment_id = payment.get("_id")
            current_status = payment.get("status")

            if current_status == Payment.STATUS_SUCCESS:
                Log.info(f"{log_tag} Payment already marked as successful — skipping")
                return True, "Already processed"

            gateway_txn_id = str(data.get("id", ""))

            Payment.update_status(
                payment_id=payment_id,
                new_status=Payment.STATUS_SUCCESS,
                gateway_transaction_id=gateway_txn_id,
            )

            from ...extensions.db import db
            collection = db.get_collection(Payment.collection_name)
            collection.update_one(
                {"_id": ObjectId(payment_id)},
                {"$set": {
                    "callback_response": data,
                    "updated_at": datetime.utcnow(),
                }}
            )

            metadata = data.get("metadata", {}) or {}
            business_id = metadata.get("business_id") or payment.get("business_id")
            user_id = metadata.get("user_id") or payment.get("user_id")
            user__id = metadata.get("user__id") or payment.get("user__id")
            package_id = metadata.get("package_id") or payment.get("package_id")
            purchase_type = metadata.get("purchase_type", "subscription")

            if purchase_type == "subscription" and package_id:
                from ...services.pos.subscription_service import SubscriptionService

                sub_success, subscription_id, sub_error = SubscriptionService.create_subscription(
                    business_id=str(business_id),
                    user_id=user_id,
                    user__id=str(user__id),
                    package_id=str(package_id),
                    payment_method="paystack",
                    payment_reference=reference,
                )

                if sub_success:
                    Log.info(f"{log_tag} Subscription {subscription_id} created")
                    collection.update_one(
                        {"_id": ObjectId(payment_id)},
                        {"$set": {"subscription_id": ObjectId(subscription_id)}}
                    )
                else:
                    Log.error(f"{log_tag} Subscription creation failed: {sub_error}")

            authorization = data.get("authorization", {}) or {}
            if authorization.get("reusable"):
                from ...models.church.payment_method_model import PaymentMethod

                PaymentMethod.save_from_paystack(
                    business_id=str(business_id),
                    paystack_response=data,
                    user_id=user_id,
                    user__id=str(user__id),
                    set_as_primary=True,
                )
                Log.info(
                    f"{log_tag} Card saved: "
                    f"{authorization.get('card_type')} ****{authorization.get('last4')}"
                )

            return True, "Payment processed successfully"

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False, str(e)

    @staticmethod
    def _handle_charge_failed(data: dict, reference: str) -> tuple:
        log_tag = f"[PaystackPaymentService][_handle_charge_failed][{reference}]"

        try:
            payment = Payment.get_by_reference(reference)

            if not payment:
                Log.error(f"{log_tag} Payment not found")
                return False, "Payment record not found"

            payment_id = payment.get("_id")
            gateway_response = data.get("gateway_response", "Transaction failed")

            Payment.update_status(
                payment_id=payment_id,
                new_status=Payment.STATUS_FAILED,
                gateway_transaction_id=str(data.get("id", "")),
                error_message=gateway_response,
            )

            metadata = data.get("metadata", {}) or {}
            business_id = metadata.get("business_id") or str(payment.get("business_id", ""))
            auth_id = metadata.get("authorization_id")

            if auth_id and business_id:
                from ...models.church.payment_method_model import PaymentMethod
                PaymentMethod.record_charge_result(
                    auth_id,
                    business_id,
                    success=False,
                    status_message=gateway_response,
                )
                Log.info(f"{log_tag} Card failure recorded: auth_id={auth_id}")

            from ...extensions.db import db
            collection = db.get_collection(Payment.collection_name)
            collection.update_one(
                {"_id": ObjectId(payment_id)},
                {"$set": {
                    "callback_response": data,
                    "updated_at": datetime.utcnow(),
                }}
            )

            Log.info(f"{log_tag} Payment marked as failed: {gateway_response}")
            return True, "Failure recorded"

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False, str(e)