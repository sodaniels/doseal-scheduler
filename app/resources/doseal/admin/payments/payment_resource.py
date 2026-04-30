# resources/payment_resource.py

import os, json
from flask import g, request, jsonify
from flask.views import MethodView
from flask_smorest import Blueprint

from .....constants.payment_methods import PAYMENT_METHODS
from .....constants.service_code import(
     SYSTEM_USERS, HTTP_STATUS_CODES, TRANSACTION_STATUS_CODE, SYSTEM_USERS
)
from ...admin.admin_business_resource import token_required
from .....utils.json_response import prepared_response
from .....utils.crypt import decrypt_data, encrypt_data
from .....utils.helpers import make_log_tag, stringify_object_ids
from .....utils.rate_limits import (
    subscription_payment_ip_limiter,
    subscription_payment_limiter
)

from .....utils.calculation_engine import hash_transaction

from .....utils.generators import generate_internal_reference
from .....utils.external.exchange_rate_api import get_exchange_rate
from .....utils.redis import (
    set_redis_with_expiry, get_redis
)

from .....utils.essentials import Essensial

#models
from .....models.admin.payment import Payment
from .....models.admin.package_model import Package
#services
from .....services.payments.payment_service import PaymentService
from .....services.pos.subscription_service import SubscriptionService
from .....utils.payments.hubtel_utils import get_hubtel_auth_token
#schemas
from .....schemas.payments.payment_schema import (
    InitiatePaymentSchema,
    ExecutePaymentSchema,
    VerifyPaymentSchema,
    ManualPaymentSchema,
    InitiatePaymentPlanChangeSchema
)
from .....utils.logger import Log

from .....utils.payments.paystack_utils import (
    get_paystack_currency,
)
from .....services.payments.paystack_payment_service import PaystackPaymentMixin

from .....services.payments.payment_integration_service import PaymentIntegrationService

payment_blp = Blueprint(
    "payments",
    __name__,
    description="Payment processing and management"
)

# ======================================================
# PAYMENT INITIATE
# ======================================================
@payment_blp.route("/payments/initiate", methods=["POST"])
class InitiatePayment(MethodView):
    @token_required
    @payment_blp.arguments(InitiatePaymentSchema, location="json")
    @payment_blp.response(200)
    def post(self, json_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))
        reference = None
        

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        log_tag = make_log_tag(
            "payment_resource.py",
            "InitiatePayment",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        preferred_provider = (json_data.get("provider") or "").strip().lower() or None
        branch_id = json_data.get("branch_id")
        
        provider_credentials = {}
        provider_settings = {}
        payment_method = None

        # ── Step 1: If no provider specified, check business default settings ──
        if not preferred_provider:
            try:
                from .....models.social.provider_setting_model import ProviderSetting

                default_settings = ProviderSetting.get_for_business(
                    business_id=business_id,
                    branch_id=branch_id,
                    processing_callback=True,
                )
                

                if default_settings and default_settings.get("default_payment_provider"):
                    preferred_provider = default_settings["default_payment_provider"]
                    Log.info(f"{log_tag} Using default provider from settings: {preferred_provider}")

            except Exception as e:
                Log.warning(f"{log_tag} Failed to load provider settings (ignored): {e}")

        # ── Step 2: Resolve credentials for the provider ──
        try:
            provider, provider_credentials, provider_settings, provider_error = (
                PaymentIntegrationService.get_provider_credentials(
                    business_id=business_id,
                    branch_id=branch_id,
                    preferred_provider=preferred_provider,
                )
            )

            if provider_error or not provider:
                payment_method = str(
                    os.getenv("DEFAULT_PAYMENT_GATEWAY", "paystack")
                ).strip().lower()
                provider_credentials = {}
                provider_settings = {}

                Log.warning(
                    f"{log_tag} Falling back to env gateway. "
                    f"reason={provider_error or 'No active payment integration found'}"
                )
            else:
                payment_method = str(provider).strip().lower()
                Log.info(f"{log_tag} Using payment provider: {payment_method}")

        except Exception as e:
            payment_method = str(
                os.getenv("DEFAULT_PAYMENT_GATEWAY", "paystack")
            ).strip().lower()
            provider_credentials = {}
            provider_settings = {}

            Log.warning(
                f"{log_tag} Provider resolution failed. "
                f"Falling back to env gateway. error={e}"
            )

        tenant = {}
        try:
            tenant_id = json_data.get("tenant_id")
            tenant = Essensial.get_tenant_by_id(tenant_id) or {}

            if tenant:
                Log.info(f"{log_tag} Tenant resolved successfully")
            else:
                Log.info(f"{log_tag} No tenant information found. Proceeding with defaults.")

        except Exception as e:
            tenant = {}
            Log.info(f"{log_tag} Error retrieving tenant. Error: {str(e)}")

        try:
            from .....constants.storage_addon_pricing import STORAGE_ADDON_PRICING

            purchase_type = (json_data.get("purchase_type") or "subscription").strip().lower()
            billing_period = json_data.get("billing_period")
            discount_code = json_data.get("discount_code")

            package_id = json_data.get("package_id")
            addon_users = int(json_data.get("addon_users", 0) or 0)
            storage_addon_gb = json_data.get("storage_addon_gb")

            if addon_users < 0:
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Invalid addon_users entered",
                )

            package = None
            amount = 0.0
            original_total = 0.0
            total_from_amount = 0.0
            purchase_label = None

            # --------------------------------------------------
            # PURCHASE TYPE + PRICING
            # --------------------------------------------------
            if purchase_type == "subscription":
                if not package_id:
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="package_id is required for subscription purchase",
                    )

                package = Package.get_by_id(package_id)
                if not package:
                    return prepared_response(
                        status=False,
                        status_code="NOT_FOUND",
                        message="Package not found",
                    )

                if package.get("status") != "Active":
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="Package is not available",
                    )

                amount = float(package.get("price", 0) or 0)
                if amount < 0:
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="Invalid package price",
                    )

                total_from_amount = round(amount * addon_users, 2) if addon_users > 0 else amount
                original_total = total_from_amount
                purchase_label = package.get("name") or package.get("tier") or "Subscription"

            elif purchase_type == "storage_addon":
                if storage_addon_gb is None:
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="storage_addon_gb is required for storage addon purchase",
                    )

                try:
                    storage_addon_gb = int(storage_addon_gb)
                except Exception:
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="storage_addon_gb must be a valid integer",
                    )

                if storage_addon_gb not in STORAGE_ADDON_PRICING:
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="Invalid storage addon selected",
                    )

                addon_pricing = STORAGE_ADDON_PRICING[storage_addon_gb]
                amount = float(addon_pricing.get(billing_period, 0) or 0)

                if amount <= 0:
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message=f"No pricing configured for {storage_addon_gb}GB on {billing_period} plan",
                    )

                total_from_amount = amount
                original_total = amount
                purchase_label = f"{storage_addon_gb}GB Storage Addon"

            else:
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Invalid purchase_type. Expected 'subscription' or 'storage_addon'",
                )

            # --------------------------------------------------
            # DISCOUNT VALIDATION
            # --------------------------------------------------
            discount_info = None
            discount_amount = 0

            if discount_code and purchase_type == "subscription":
                from .....models.social.discount_model import Discount

                package_tier = package.get("tier", "Free")

                is_valid, result = Discount.validate_code(
                    code=discount_code,
                    business_id=business_id,
                    package_tier=package_tier,
                    billing_period=billing_period,
                    original_amount=total_from_amount,
                )

                if not is_valid:
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message=result,
                        errors={"field": "discount_code", "code": discount_code},
                    )

                discount_info = result
                discount_amount = result["discount_amount"]
                total_from_amount = result["final_amount"]

                Log.info(
                    f"{log_tag} Discount applied: {discount_code} → "
                    f"${original_total} - ${discount_amount} = ${total_from_amount}"
                )

            # --------------------------------------------------
            # CURRENCY RESOLUTION
            # --------------------------------------------------
            if payment_method == "paystack":
                to_currency = (
                    provider_settings.get("currency")
                    or tenant.get("country_currency")
                    or "GHS"
                )
            else:
                to_currency = (
                    provider_settings.get("currency")
                    or tenant.get("country_currency")
                    or "GHS"
                )

            from_currency = os.getenv("DEFUALT_PACKAGE_CURRENCY", "USD")
            exchange_rate = get_exchange_rate(from_currency, to_currency)

            Log.info(
                f"{log_tag} Converting {from_currency} {total_from_amount} to "
                f"{to_currency} {round(total_from_amount * exchange_rate, 2)} "
                f"(rate: {exchange_rate})"
            )

            # --------------------------------------------------
            # AMOUNT DETAIL
            # --------------------------------------------------
            amount_detail = {
                "purchase_type": purchase_type,
                "from_currency": from_currency,
                "total_from_amount": total_from_amount,
                "total_to_amount": round(total_from_amount * exchange_rate, 2),
                "to_currency": to_currency,
                "exchange_rate": exchange_rate,
                "original_total": original_total,
                "payment_gateway": payment_method,
            }

            if purchase_type == "subscription":
                amount_detail.update({
                    "package_id": package_id,
                    "addon_users": addon_users,
                    "package_amount": amount,
                })
            else:
                amount_detail.update({
                    "storage_addon_gb": storage_addon_gb,
                    "storage_addon_price": amount,
                })

            if discount_info:
                amount_detail["discount_code"] = discount_code.strip().upper()
                amount_detail["discount_type"] = discount_info["discount_type"]
                amount_detail["discount_value"] = discount_info["discount_value"]
                amount_detail["discount_amount"] = discount_amount
                amount_detail["discount_display"] = discount_info["display_value"]
                amount_detail["discount_id"] = discount_info["discount_id"]
                amount_detail["discount_duration"] = discount_info.get("duration", "once")

            if os.getenv("APP_ENV") == "development" and payment_method != "paystack":
                amount_detail["paid_amount"] = 1

            # --------------------------------------------------
            # FREE / 100% DISCOUNT SUBSCRIPTION PATH
            # --------------------------------------------------
            if purchase_type == "subscription" and total_from_amount <= 0 and discount_info:
                from .....models.social.discount_model import Discount
                from .....services.pos.subscription_service import SubscriptionService

                Discount.record_redemption(
                    discount_id=discount_info["discount_id"],
                    business_id=business_id,
                    user_id=user__id,
                    amount_saved=original_total,
                )

                success, subscription_id, error = SubscriptionService.create_subscription(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    package_id=package_id,
                    payment_method="discount_100pct",
                    payment_reference=f"DISC-{discount_code.strip().upper()}"
                )

                if success:
                    return prepared_response(
                        status=True,
                        status_code="CREATED",
                        message="Subscription activated with 100% discount.",
                        data={
                            "subscription_id": subscription_id,
                            "discount_applied": {
                                "code": discount_code.strip().upper(),
                                "type": discount_info["discount_type"],
                                "display": discount_info["display_value"],
                                "original_price": original_total,
                                "discount_amount": discount_amount,
                                "final_price": 0,
                            },
                            "amount_charged": 0,
                        },
                    )

                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message=error or "Failed to create subscription",
                )

            # --------------------------------------------------
            # METADATA
            # --------------------------------------------------
            metadata = {
                "purchase_type": purchase_type,
                "billing_period": billing_period,
                "business_id": business_id,
                "user_id": user_id,
                "user__id": user__id,
                "return_url": json_data.get("return_url"),
                "selected_provider": payment_method,
                "provider": payment_method,
                **(json_data.get("metadata") or {}),
            }

            if branch_id:
                metadata["branch_id"] = branch_id

            if purchase_type == "subscription":
                metadata["package_id"] = package_id
                metadata["addon_users"] = addon_users
            else:
                metadata["storage_addon_gb"] = storage_addon_gb

            if discount_info:
                metadata["discount_code"] = discount_code.strip().upper()
                metadata["discount_id"] = discount_info["discount_id"]
                metadata["discount_amount"] = discount_amount

            # --------------------------------------------------
            # REFERENCE
            # --------------------------------------------------
            reference_prefix_map = {
                "hubtel": "HUB",
                "asoriba": "ASB",
                "paystack": "PAY",
                "flutterwave": "FLW",
                "stripe": "STP",
                "paypal": "PPL",
                "mpesa": "MPE",
            }

            reference = generate_internal_reference(reference_prefix_map.get(str(payment_method).strip().lower(), "PMT")
)

            customer_name = decrypt_data(user_info.get("fullname")) if user_info.get("fullname") else ""
            customer_email = decrypt_data(user_info.get("email")) if user_info.get("email") else ""

            # --------------------------------------------------
            # PAYMENT PAYLOAD STORED IN REDIS
            # --------------------------------------------------
            payment_payload = {
                "metadata": metadata,
                "amount_detail": amount_detail,
                "customer_phone": json_data.get("customer_phone"),
                "billing_period": billing_period,
                "customer_name": customer_name,
                "customer_email": customer_email,
                "internal_reference": reference,
                "purchase_label": purchase_label,
                "provider_credentials": provider_credentials or {},
                "provider_settings": provider_settings or {},
            }

            if package_id:
                payment_payload["package_id"] = package_id

            if storage_addon_gb:
                payment_payload["storage_addon_gb"] = storage_addon_gb

            if discount_info:
                payment_payload["discount_code"] = discount_code.strip().upper()
                payment_payload["discount_info"] = {
                    "discount_id": discount_info["discount_id"],
                    "discount_type": discount_info["discount_type"],
                    "discount_value": discount_info["discount_value"],
                    "discount_amount": discount_amount,
                    "display_value": discount_info["display_value"],
                    "original_total": original_total,
                    "final_total": total_from_amount,
                    "duration": discount_info.get("duration", "once"),
                }

            payment_hashed = hash_transaction(payment_payload)
            payment_string = json.dumps(payment_payload, sort_keys=True, default=str)
            encrypted_payment = encrypt_data(payment_string)
            set_redis_with_expiry(payment_hashed, 600, encrypted_payment)
            
            # remove sinsitive data from payload
            payment_payload.pop("provider_credentials", None)
            payment_payload.pop("provider_settings", None)

            response = {
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "message": TRANSACTION_STATUS_CODE["PAYMENT_INITIATED"],
                "results": payment_payload,
                "checksum": str.upper(payment_hashed),
            }
            

            Log.info(f"{log_tag}[{client_ip}] Payment initiated successfully")
            return response

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to initiate payment",
                errors=[str(e)],
            )


# ======================================================
# PAYMENT EXECUTE
# ======================================================
@payment_blp.route("/payments/execute", methods=["POST"])
class ExecutePayment(MethodView):

    @token_required
    @payment_blp.arguments(ExecutePaymentSchema, location="json")
    @payment_blp.response(200)
    def post(self, json_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))

        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None

        checksum = (json_data.get("checksum") or "").strip()
        checksum_hash_transformed = checksum.lower() if checksum else None

        log_tag = make_log_tag(
            "payment_resource.py",
            "ExecutePayment",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        try:
            if not checksum_hash_transformed:
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    "checksum is required",
                )

            Log.info(f"{log_tag} retrieving payment from redis")
            encrypted_payment = get_redis(checksum_hash_transformed)

            if encrypted_payment is None:
                message = (
                    "The payment has expired or the checksum is invalid. Kindly call the "
                    "'payments/initiate' endpoint again and ensure the checksum is valid."
                )
                Log.info(f"{log_tag} {message}")
                return prepared_response(False, "BAD_REQUEST", message)

            decrypted_payment = decrypt_data(encrypted_payment)
            payment_details = json.loads(decrypted_payment)

            metadata = payment_details.get("metadata", {}) or {}
            amount_detail = payment_details.get("amount_detail", {}) or {}
            billing_period = payment_details.get("billing_period")
            customer_name = payment_details.get("customer_name")
            customer_email = payment_details.get("customer_email")
            customer_phone = payment_details.get("customer_phone")

            purchase_type = metadata.get("purchase_type", "subscription")
            package_id = payment_details.get("package_id") or metadata.get("package_id")
            storage_addon_gb = payment_details.get("storage_addon_gb") or metadata.get("storage_addon_gb")
            discount_info = payment_details.get("discount_info")
            discount_code = payment_details.get("discount_code")

            # --------------------------------------------------
            # Resolve provider
            # --------------------------------------------------
            preferred_provider = (
                metadata.get("selected_provider")
                or metadata.get("provider")
                or json_data.get("provider")
            )
            branch_id = metadata.get("branch_id") or json_data.get("branch_id")

            provider_credentials = payment_details.get("provider_credentials") or {}
            provider_settings = payment_details.get("provider_settings") or {}

            provider_name = None
            provider_error = None

            if not provider_credentials and not provider_settings:
                provider_name, provider_credentials, provider_settings, provider_error = (
                    PaymentIntegrationService.get_provider_credentials(
                        business_id=business_id,
                        branch_id=branch_id,
                        preferred_provider=preferred_provider,
                    )
                )

                if provider_error or not provider_name:
                    payment_method = str(
                        os.getenv("DEFAULT_PAYMENT_GATEWAY", "paystack")
                    ).strip().lower()

                    provider_credentials = {}
                    provider_settings = {}

                    Log.warning(
                        f"{log_tag} Falling back to env gateway during execute. "
                        f"reason={provider_error or 'No active payment integration found'}"
                    )
                else:
                    payment_method = str(provider_name).strip().lower()
                    Log.info(
                        f"{log_tag} Using payment provider from integration during execute: "
                        f"{payment_method}"
                    )
            else:
                payment_method = str(
                    preferred_provider or os.getenv("DEFAULT_PAYMENT_GATEWAY", "paystack")
                ).strip().lower()

                Log.info(
                    f"{log_tag} Using provider from stored payment payload during execute: "
                    f"{payment_method}"
                )

            # --------------------------------------------------
            # Free / discounted flows
            # --------------------------------------------------
            if (
                purchase_type == "subscription"
                and discount_info
                and float(amount_detail.get("total_to_amount", 0) or 0) <= 0
            ):
                from .....models.social.discount_model import Discount

                Discount.record_redemption(
                    discount_id=discount_info["discount_id"],
                    business_id=business_id,
                    user_id=user__id,
                    amount_saved=discount_info.get("original_total", 0),
                )

                success, subscription_id, error = SubscriptionService.create_subscription(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    package_id=package_id,
                    payment_method="discount_100pct",
                    payment_reference=f"DISC-{discount_code}",
                    processing_callback=True,
                )

                if success:
                    Discount.record_redemption(
                        discount_id=discount_info["discount_id"],
                        business_id=business_id,
                        user_id=user__id,
                        amount_saved=discount_info.get("original_total", 0),
                        subscription_id=subscription_id,
                    )

                    return prepared_response(
                        status=True,
                        status_code="CREATED",
                        message="Subscription activated with 100% discount.",
                        data={
                            "subscription_id": subscription_id,
                            "discount_applied": discount_info,
                            "amount_charged": 0,
                        },
                    )

                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message=error or "Failed to create subscription",
                )

            if purchase_type == "subscription":
                package = Package.get_by_id(package_id)
                if not package:
                    return prepared_response(False, "NOT_FOUND", "Package not found")

                if float(package.get("price", 0) or 0) == 0 and not discount_info:
                    success, subscription_id, error = SubscriptionService.create_subscription(
                        business_id=business_id,
                        user_id=user_id,
                        user__id=user__id,
                        package_id=package_id,
                        payment_method=None,
                        payment_reference=None,
                    )

                    if success:
                        return prepared_response(
                            status=True,
                            status_code="CREATED",
                            message="Subscription activated (Free plan)",
                            data={"subscription_id": subscription_id},
                        )

                    return prepared_response(
                        status=False,
                        status_code="INTERNAL_SERVER_ERROR",
                        message=error or "Failed to create subscription",
                    )

            # --------------------------------------------------
            # Merge metadata
            # --------------------------------------------------
            metadata = {
                **metadata,
                **(json_data.get("metadata") or {}),
            }

            metadata["selected_provider"] = payment_method
            if branch_id:
                metadata["branch_id"] = branch_id
            if purchase_type == "storage_addon" and storage_addon_gb:
                metadata["storage_addon_gb"] = storage_addon_gb

            # --------------------------------------------------
            # HUBTEL PAYMENT EXECUTION
            # --------------------------------------------------
            if payment_method in {
                "hubtel",
                str(PAYMENT_METHODS.get("HUBTEL", "")).lower(),
                str(PAYMENT_METHODS.get("HUBTEL_MOBILE_MONEY", "")).lower(),
            }:
                if not customer_phone:
                    return prepared_response(
                        False,
                        "BAD_REQUEST",
                        "Phone number is required for Hubtel payments",
                    )

                success, data, error = PaymentService.initiate_hubtel_payment(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    package_id=package_id,
                    billing_period=billing_period,
                    customer_name=customer_name,
                    payment_details=payment_details,
                    phone_number=customer_phone,
                    customer_email=customer_email,
                    metadata=metadata,
                    gateway_credentials=provider_credentials,
                    gateway_settings=provider_settings,
                )

                if success:
                    return prepared_response(True, "OK", data.get("message"), data=data)

                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    error or "Failed to initiate Hubtel payment",
                )
            # --------------------------------------------------
            # ASORIBA PAYMENT EXECUTION
            # --------------------------------------------------
            elif payment_method in {
                "asoriba",
                str(PAYMENT_METHODS.get("ASORIBA", "")).lower(),
            }:
                success, data, error = PaymentService.initiate_asoriba_payment(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    package_id=package_id,
                    customer_name=customer_name,
                    payment_details=payment_details,
                    phone_number=customer_phone,
                    customer_email=customer_email,
                    metadata=metadata,
                    gateway_credentials=provider_credentials,
                    gateway_settings=provider_settings,
                )

                if success:
                    return prepared_response(True, "OK", data.get("message"), data=data)

                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    error or "Failed to initiate Asoriba payment",
                )
            # --------------------------------------------------
            # PAYSTACK PAYMENT EXECUTION
            # --------------------------------------------------
            elif payment_method in {
                "paystack",
                str(PAYMENT_METHODS.get("PAYSTACK", "")).lower(),
            }:
                if not customer_email:
                    return prepared_response(
                        False,
                        "BAD_REQUEST",
                        "Email is required for Paystack payments",
                    )

                success, data, error = PaystackPaymentMixin.initiate_paystack_payment(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    package_id=package_id,
                    billing_period=billing_period,
                    customer_name=customer_name,
                    customer_email=customer_email,
                    payment_details=payment_details,
                    phone_number=customer_phone,
                    metadata=metadata,
                    gateway_credentials=provider_credentials,
                    gateway_settings=provider_settings,
                )

                if success:
                    return prepared_response(True, "OK", data.get("message"), data=data)

                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    error or "Failed to initiate Paystack payment",
                )
            # --------------------------------------------------
            # FLUTTER PAYMENT EXECUTION
            # --------------------------------------------------
            elif payment_method in {
                "flutterwave",
                str(PAYMENT_METHODS.get("FLUTTERWAVE", "")).lower(),
            }:
                if not customer_email:
                    return prepared_response(
                        False, "BAD_REQUEST",
                        "Email is required for Flutterwave payments",
                    )

                success, data, error = PaymentService.initiate_flutterwave_payment(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    package_id=package_id,
                    billing_period=billing_period,
                    customer_name=customer_name,
                    customer_email=customer_email,
                    payment_details=payment_details,
                    phone_number=customer_phone,
                    metadata=metadata,
                    gateway_credentials=provider_credentials,
                    gateway_settings=provider_settings,
                )

                if success:
                    return prepared_response(True, "OK", data.get("message"), data=data)

                return prepared_response(
                    False, "BAD_REQUEST",
                    error or "Failed to initiate Flutterwave payment",
                )
            # --------------------------------------------------
            # STRIPE PAYMENT EXECUTION
            # --------------------------------------------------
            elif payment_method in {
                "stripe",
                str(PAYMENT_METHODS.get("STRIPE", "")).lower(),
            }:
                if not customer_email:
                    return prepared_response(
                        False,
                        "BAD_REQUEST",
                        "Email is required for Stripe payments",
                    )

                success, data, error = PaymentService.initiate_stripe_payment(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    package_id=package_id,
                    billing_period=billing_period,
                    customer_name=customer_name,
                    customer_email=customer_email,
                    payment_details=payment_details,
                    phone_number=customer_phone,
                    metadata=metadata,
                    gateway_credentials=provider_credentials,
                    gateway_settings=provider_settings,
                )

                if success:
                    return prepared_response(True, "OK", data.get("message"), data=data)

                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    error or "Failed to initiate Stripe payment",
                )
            # --------------------------------------------------
            # PAYPAL PAYMENT EXECUTION
            # --------------------------------------------------
            elif payment_method in {
                "paypal",
                str(PAYMENT_METHODS.get("PAYPAL", "")).lower(),
            }:
                if not customer_email:
                    return prepared_response(
                        False, "BAD_REQUEST",
                        "Email is required for PayPal payments",
                    )

                success, data, error = PaymentService.initiate_paypal_payment(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    package_id=package_id,
                    billing_period=billing_period,
                    customer_name=customer_name,
                    customer_email=customer_email,
                    payment_details=payment_details,
                    phone_number=customer_phone,
                    metadata=metadata,
                    gateway_credentials=provider_credentials,
                    gateway_settings=provider_settings,
                )

                if success:
                    return prepared_response(True, "OK", data.get("message"), data=data)

                return prepared_response(
                    False, "BAD_REQUEST",
                    error or "Failed to initiate PayPal payment",
                )
            # --------------------------------------------------
            # MPESA PAYMENT EXECUTION
            # --------------------------------------------------
            elif payment_method in {
                "mpesa",
                str(PAYMENT_METHODS.get("MPESA", "")).lower(),
            }:
                if not customer_phone:
                    return prepared_response(
                        False, "BAD_REQUEST",
                        "Phone number is required for M-Pesa payments",
                    )

                success, data, error = PaymentService.initiate_mpesa_payment(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    package_id=package_id,
                    billing_period=billing_period,
                    customer_name=customer_name,
                    customer_email=customer_email,
                    payment_details=payment_details,
                    phone_number=customer_phone,
                    metadata=metadata,
                    gateway_credentials=provider_credentials,
                    gateway_settings=provider_settings,
                )

                if success:
                    return prepared_response(True, "OK", data.get("message"), data=data)

                return prepared_response(
                    False, "BAD_REQUEST",
                    error or "Failed to initiate M-Pesa payment",
                )

            return prepared_response(
                False,
                "BAD_REQUEST",
                f"Unsupported payment method: {payment_method}",
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to execute payment",
                errors=[str(e)],
            )


@payment_blp.route("/plan/change/payments/initiate", methods=["POST"])
class InitiatePayment(MethodView):
    """Initiate a payment transaction."""
    
    @token_required
    @payment_blp.arguments(InitiatePaymentPlanChangeSchema, location="json")
    @payment_blp.response(200)
    def post(self, json_data):
        """Initiate payment for subscription."""
        
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))
        
        
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        
        log_tag = make_log_tag(
            "payment_resource.py",
            "InitiatePayment",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        try:
            package_id = json_data["new_package_id"]
            old_package_id = json_data["old_package_id"]
            billing_period = json_data["billing_period"]
            payment_method = json_data["payment_method"]
            
            # Get package to verify price
            new_package = Package.get_by_id(package_id)
            old_package = Package.get_by_id(old_package_id)
            
            if not new_package:
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="New Package not found"
                )
                
            if not old_package:
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="Old Package not found"
                )
            
            if new_package.get("status") != "Active":
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="New Package is not available"
                )
                
            if old_package.get("status") != "Active":
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Old Package is not available"
                )
            
            # Check if it's a free package
            if new_package.get("price", 0) == 0:
                # Free package - create subscription directly
                success, subscription_id, error = SubscriptionService.create_subscription(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    package_id=package_id,
                    payment_method=None,
                    payment_reference=None
                )
                
                if success:
                    return prepared_response(
                        status=True,
                        status_code="CREATED",
                        message="Subscription activated (Free plan)",
                        data={"subscription_id": subscription_id}
                    )
                else:
                    return prepared_response(
                        status=False,
                        status_code="INTERNAL_SERVER_ERROR",
                        message=error or "Failed to create subscription"
                    )
            
            # Paid package - process payment
            metadata = {
                "package_id": package_id,
                "old_package_id": old_package_id,
                "billing_period": billing_period,
                "business_id": business_id,
                "user_id": user_id,
                "user__id": user__id,
                **json_data.get("metadata", {})
            }
            
            # PAYMENT USING HUBTEL        
            if payment_method in [PAYMENT_METHODS["HUBTEL"], PAYMENT_METHODS["HUBTEL_MOBILE_MONEY"]]:
                phone = json_data.get("customer_phone")
                if not phone:
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="Phone number is required for Hubtel payments"
                    )
                
                try:
                    customer_name = decrypt_data(user_info.get("fullname")) if user_info.get("fullname") else ""
                    customer_email = decrypt_data(user_info.get("email")) if user_info.get("email") else ""
                    
                    success, data, error = PaymentService.initiate_hubtel_payment(
                        business_id=business_id,
                        user_id=user_id,
                        user__id=user__id,
                        package_id=package_id,
                        billing_period=billing_period,
                        customer_name=customer_name,
                        phone_number=phone,
                        customer_email=customer_email,
                        metadata=metadata,
                    )
                    
                    if success:
                        return prepared_response(
                            status=True,
                            status_code="OK",
                            message=data.get("message"),
                            data=data
                        )
                    else:
                        return prepared_response(
                            status=False,
                            status_code="BAD_REQUEST",
                            message=error or "Failed to initiate payment"
                        )
                
                except Exception as e:
                    Log.info(f"{log_tag} Error occurred: {str(e)}")
              
            # Route to appropriate payment gateway
            elif payment_method == PAYMENT_METHODS["MPESA"]:
                # TODO: Implement Paystack/Flutterwave payment initiation
                return prepared_response(
                    status=False,
                    status_code="NOT_IMPLEMENTED",
                    message=f"{payment_method} payment not yet implemented"
                )
            # PAYMENT USING PAYSTACK (plan change)
            elif payment_method == PAYMENT_METHODS["PAYSTACK"]:
                customer_email_val = decrypt_data(user_info.get("email")) if user_info.get("email") else ""
                
                if not customer_email_val:
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="Email is required for Paystack payments"
                    )

                try:
                    customer_name = decrypt_data(user_info.get("fullname")) if user_info.get("fullname") else ""

                    success, data, error = PaystackPaymentMixin.initiate_paystack_payment(
                        business_id=business_id,
                        user_id=user_id,
                        user__id=user__id,
                        package_id=package_id,
                        billing_period=billing_period,
                        customer_name=customer_name,
                        customer_email=customer_email_val,
                        payment_details={
                            "amount_detail": {
                                "total_to_amount": float(new_package.get("price", 0)),
                                "to_currency": "GHS",  # or resolve from tenant
                            },
                            "internal_reference": None,
                        },
                        phone_number=json_data.get("customer_phone"),
                        metadata=metadata,
                    )

                    if success:
                        return prepared_response(
                            status=True,
                            status_code="OK",
                            message=data.get("message"),
                            data=data
                        )
                    else:
                        return prepared_response(
                            status=False,
                            status_code="BAD_REQUEST",
                            message=error or "Failed to initiate payment"
                        )

                except Exception as e:
                    Log.info(f"{log_tag} Error occurred: {str(e)}")
                    return prepared_response(
                        status=False,
                        status_code="INTERNAL_SERVER_ERROR",
                        message="Paystack payment processing failed"
                    )
                    
            
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to initiate payment",
                errors=[str(e)]
            )


@payment_blp.route("/payments/verify", methods=["POST"])
class VerifyPayment(MethodView):
    """Verify payment status."""
    
    @token_required
    @payment_blp.arguments(VerifyPaymentSchema, location="json")
    @payment_blp.response(200)
    def post(self, json_data):
        """Verify payment status by payment_id or checkout_request_id."""
        
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        
        log_tag = f"[VerifyPayment][post][{business_id}]"
        
        try:
            payment_id = json_data.get("payment_id")
            checkout_request_id = json_data.get("checkout_request_id")
            gateway_transaction_id = json_data.get("gateway_transaction_id")
            
            if not any([payment_id, checkout_request_id, gateway_transaction_id]):
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="At least one payment identifier is required"
                )
            
            result = PaymentService.verify_payment_status(
                payment_id=payment_id,
                checkout_request_id=checkout_request_id
            )
            
            if result.get("status") == "success":
                return prepared_response(
                    status=True,
                    status_code="OK",
                    message="Payment status retrieved",
                    data=result.get("payment")
                )
            else:
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message=result.get("message", "Payment not found")
                )
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to verify payment",
                errors=[str(e)]
            )


@payment_blp.route("/payments/history", methods=["GET"])
class PaymentHistory(MethodView):
    """Get payment history for business."""
    
    @token_required
    @payment_blp.response(200)
    def get(self):
        """Get payment history."""
        
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        
        log_tag = f"[PaymentHistory][get][{business_id}]"
        
        try:
            page = request.args.get("page", 1, type=int)
            per_page = request.args.get("per_page", 20, type=int)
            status = request.args.get("status")
            
            result = Payment.get_by_business_id(
                business_id=business_id,
                page=page,
                per_page=per_page,
                status=status
            )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Payment history retrieved successfully",
                data=result
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to retrieve payment history",
                errors=[str(e)]
            )


@payment_blp.route("/admin/payments/manual", methods=["POST"])
class CreateManualPayment(MethodView):
    """Create manual payment (admin only)."""
    
    @token_required
    @payment_blp.arguments(ManualPaymentSchema, location="json")
    @payment_blp.response(200)
    def post(self, json_data):
        """Create manual payment and subscription."""
        
        user_info = g.get("current_user", {})
        account_type = user_info.get("account_type")
        
        # Only admin/super_admin can create manual payments
        if account_type not in [SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["BUSINESS_OWNER"]]:
            return prepared_response(
                status=False,
                status_code="FORBIDDEN",
                message="Insufficient permissions"
            )
        
        log_tag = f"[CreateManualPayment][post]"
        
        try:
            # Extract business from request or use admin's business
            business_id = json_data.get("business_id") or str(user_info.get("business_id"))
            user_id = json_data.get("user_id") or user_info.get("user_id")
            user__id = json_data.get("user__id") or str(user_info.get("_id"))
            
            # Create manual payment
            success, payment_id, error = PaymentService.create_manual_payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                package_id=json_data["package_id"],
                billing_period=json_data["billing_period"],
                payment_method=json_data["payment_method"],
                payment_reference=json_data["payment_reference"],
                amount=json_data["amount"],
                currency=json_data.get("currency", "USD"),
                customer_phone=json_data.get("customer_phone"),
                customer_email=json_data.get("customer_email"),
                customer_name=json_data.get("customer_name"),
                notes=json_data.get("notes")
            )
            
            if not success:
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message=error or "Failed to create payment"
                )
            
            # Create subscription
            sub_success, subscription_id, sub_error = SubscriptionService.create_subscription(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                package_id=json_data["package_id"],
                payment_method=json_data["payment_method"],
                payment_reference=json_data["payment_reference"]
            )
            
            if sub_success:
                return prepared_response(
                    status=True,
                    status_code="CREATED",
                    message="Manual payment and subscription created successfully",
                    data={
                        "payment_id": payment_id,
                        "subscription_id": subscription_id
                    }
                )
            else:
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message=sub_error or "Payment created but subscription failed"
                )
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to create manual payment",
                errors=[str(e)]
            )