# resources/payments/paystack_webhook_resource.py

import json
import os
import ast
from datetime import datetime
from urllib.parse import urlencode

from flask import request, jsonify, redirect
from flask.views import MethodView
from flask_smorest import Blueprint

from ....constants.payment_methods import PAYMENT_METHODS
from ....models.admin.package_model import Package
from ....models.admin.payment import Payment
from ....models.business_model import Business
from ....services.pos.subscription_service import SubscriptionService
from ....services.payments.payment_integration_service import PaymentIntegrationService
from ....utils.helpers import build_receipt_sms
from ....utils.invoice.generate_invoice import generate_invoice_pdf_bytes
from ....utils.json_response import prepared_response
from ....utils.logger import Log
from ....utils.media.storage_router import upload_invoice_and_get_asset
from ....utils.payments.paystack_utils import (
    verify_webhook_signature,
    verify_transaction,
)
from ....services.email_service import send_payment_confirmation_email
from ....decorators.callback_restriction import paystack_ip_whitelist


paystack_blp = Blueprint(
    "paystack_webhooks",
    __name__,
    description="Paystack webhooks and callbacks",
)

# At the top of the file, add this helper:

def _is_system_billing_payment(purchase_type):
    """
    Determine if this payment is a system billing transaction (subscription/storage)
    vs a church collection (donation, offering, event, etc.)
    """
    return purchase_type in ("subscription", "storage_addon")

def _parse_amount_detail(payment):
    amount_detail_raw = payment.get("amount_detail")
    if not amount_detail_raw:
        return {}
    if isinstance(amount_detail_raw, dict):
        return amount_detail_raw
    if isinstance(amount_detail_raw, str):
        try:
            return json.loads(amount_detail_raw)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(amount_detail_raw)
            except (ValueError, SyntaxError):
                return {}
    return {}


def _parse_metadata(payment):
    metadata = payment.get("metadata") or {}
    if not isinstance(metadata, dict):
        try:
            metadata = json.loads(metadata) if isinstance(metadata, str) else {}
        except Exception:
            metadata = {}
    return metadata


def _extract_purchase_type(metadata, extra_metadata, amount_detail):
    return (
        (metadata or {}).get("purchase_type")
        or (extra_metadata or {}).get("purchase_type")
        or (amount_detail or {}).get("purchase_type")
        or "subscription"
    )


def _extract_storage_addon_gb(metadata, extra_metadata, amount_detail):
    return (
        (metadata or {}).get("storage_addon_gb")
        or (extra_metadata or {}).get("storage_addon_gb")
        or (amount_detail or {}).get("storage_addon_gb")
    )


def _resolve_paystack_secret_for_payment(payment, log_tag):
    try:
        metadata = _parse_metadata(payment)
        selected_provider = (
            metadata.get("selected_provider")
            or metadata.get("provider")
            or payment.get("payment_method")
            or "paystack"
        )
        branch_id = metadata.get("branch_id")
        business_id = str(payment.get("business_id") or "")

        if str(selected_provider).lower() != "paystack":
            return os.getenv("PAYSTACK_SECRET_KEY")

        provider, credentials, settings, error = PaymentIntegrationService.get_provider_credentials(
            business_id=business_id,
            branch_id=branch_id,
            preferred_provider="paystack",
        )

        if provider and isinstance(credentials, dict):
            secret_key = credentials.get("secret_key")
            if secret_key:
                Log.info(f"{log_tag} Using Paystack secret from integration")
                return secret_key

        env_secret = os.getenv("PAYSTACK_SECRET_KEY")
        if env_secret:
            Log.warning(f"{log_tag} Falling back to PAYSTACK_SECRET_KEY from env")
            return env_secret

        Log.error(f"{log_tag} No Paystack secret could be resolved")
        return None

    except Exception as e:
        Log.error(f"{log_tag} Failed to resolve Paystack secret: {e}", exc_info=True)
        return os.getenv("PAYSTACK_SECRET_KEY")


def _record_discount_redemption(metadata, ps_metadata, business_id, user__id, subscription_id, log_tag):
    discount_id = (
        (metadata or {}).get("discount_id")
        or (ps_metadata or {}).get("discount_id")
    )
    discount_amount_saved = float(
        (metadata or {}).get("discount_amount")
        or (ps_metadata or {}).get("discount_amount")
        or 0
    )

    if discount_id and discount_amount_saved > 0:
        try:
            from ....models.church.discount_model import Discount

            Discount.record_redemption(
                discount_id=discount_id,
                business_id=str(business_id),
                user_id=str(user__id) if user__id else None,
                amount_saved=discount_amount_saved,
                subscription_id=str(subscription_id) if subscription_id else None,
            )
        except Exception as e:
            Log.warning(f"{log_tag} Failed to record discount redemption: {e}")


def _save_card_from_paystack(data, business_id, user_id, user__id, log_tag):
    paystack_authorization = data.get("authorization", {}) or {}
    if not paystack_authorization.get("reusable"):
        return

    try:
        from ....models.church.payment_method_model import PaymentMethod

        PaymentMethod.save_from_paystack(
            business_id=str(business_id),
            paystack_response=data,
            user_id=user_id,
            user__id=str(user__id) if user__id else None,
            set_as_primary=True,
        )
    except Exception as e:
        Log.warning(f"{log_tag} Error saving card via PaymentMethod: {e}")

    try:
        from ....models.admin.paystack_authorization import PaystackAuthorization

        paystack_customer = data.get("customer", {}) or {}
        PaystackAuthorization.store_authorization(
            business_id=str(business_id),
            user_id=user_id,
            user__id=str(user__id) if user__id else None,
            email=paystack_customer.get("email"),
            authorization=paystack_authorization,
        )
    except Exception as e:
        Log.warning(f"{log_tag} Error storing legacy authorization: {e}")


def _process_storage_addon_purchase(payment, metadata, amount_detail, business_id, user__id, reference, log_tag):
    try:
        from ....models.church.form_model import StorageQuota

        storage_addon_gb = (
            (metadata or {}).get("storage_addon_gb")
            or (amount_detail or {}).get("storage_addon_gb")
            or 0
        )

        try:
            storage_addon_gb = int(storage_addon_gb)
        except Exception:
            storage_addon_gb = 0

        if storage_addon_gb <= 0:
            return False, None, "Invalid storage_addon_gb"

        paid_amount = float(
            (amount_detail or {}).get("total_from_amount")
            or payment.get("amount")
            or 0
        )

        ok = StorageQuota.add_addon_storage(
            business_id=business_id,
            addon_gb=storage_addon_gb,
            payment_reference=reference,
            price=paid_amount,
            processing_callback=True,
        )
        if not ok:
            return False, None, "Failed to add purchased storage"

        quota = StorageQuota.get_or_create(business_id, processing_callback=True)

        return True, {
            "purchase_type": "storage_addon",
            "storage_addon_gb": storage_addon_gb,
            "quota": quota,
        }, None

    except Exception as e:
        Log.error(f"{log_tag} Storage addon processing failed: {e}", exc_info=True)
        return False, None, str(e)


@paystack_blp.route("/webhooks/payment/paystack", methods=["POST"])
class PaystackWebhook(MethodView):

    @paystack_ip_whitelist
    def post(self):
        reference = None
        log_tag = "[paystack_webhook_resource.py][paystack_webhook_resource.py][PaystackWebhook][post]"
        client_ip = request.remote_addr

        try:
            Log.info(f"{log_tag} Request From IP : {client_ip}")

            signature = request.headers.get("X-Paystack-Signature", "")
            raw_body = request.get_data()

            if not signature:
                return jsonify({"code": 401, "message": "Missing signature"}), 401

            event_payload = request.get_json(silent=True) or {}
            event_type = event_payload.get("event")
            data = event_payload.get("data", {}) or {}
            reference = data.get("reference")

            if not reference:
                return jsonify({"code": 200, "message": "No reference — acknowledged"}), 200

            payment = Payment.get_by_reference(reference) or Payment.get_by_order_id(reference)
            if not payment:
                return jsonify({"code": 200, "message": "Payment not found — acknowledged"}), 200

            paystack_secret = _resolve_paystack_secret_for_payment(payment, log_tag)
            if not paystack_secret:
                return jsonify({"code": 401, "message": "Webhook secret not configured"}), 401

            if not verify_webhook_signature(raw_body, signature, secret_key=paystack_secret):
                return jsonify({"code": 401, "message": "Invalid signature"}), 401

            if event_type not in ("charge.success", "charge.failed"):
                return jsonify({"code": 200, "message": f"Event {event_type} acknowledged"}), 200

            payment_id = str(payment.get("_id"))
            business_id = str(payment.get("business_id") or "")
            current_status = (payment.get("status") or "").strip()

            if current_status in [Payment.STATUS_SUCCESS, Payment.STATUS_FAILED]:
                return jsonify({"code": 200, "message": "Already processed"}), 200

            amount_detail = _parse_amount_detail(payment)
            metadata = _parse_metadata(payment)
            ps_metadata = data.get("metadata", {}) or {}
            paystack_customer = data.get("customer", {}) or {}
            paystack_authorization = data.get("authorization", {}) or {}
            gateway_txn_id = str(data.get("id") or "")

            addon_users = int(amount_detail.get("addon_users") or 0)
            package_amount = float(amount_detail.get("package_amount") or 0)
            currency_symbol = amount_detail.get("from_currency") or payment.get("currency") or "USD"
            original_total = float(
                amount_detail.get("original_total")
                or amount_detail.get("total_from_amount")
                or package_amount
            )
            total_from_amount = float(amount_detail.get("total_from_amount") or package_amount)
            amount_paid = total_from_amount

            discount_code = (
                amount_detail.get("discount_code")
                or metadata.get("discount_code")
                or ps_metadata.get("discount_code")
            )
            discount_amount = float(
                amount_detail.get("discount_amount")
                or metadata.get("discount_amount")
                or 0
            )
            has_discount = bool(discount_code and discount_amount > 0)

            customer_name = (
                ((paystack_customer.get("first_name") or "") + " " + (paystack_customer.get("last_name") or "")).strip()
                or payment.get("customer_name")
                or ""
            )
            customer_email = paystack_customer.get("email") or payment.get("customer_email") or ""
            customer_phone = paystack_customer.get("phone") or payment.get("customer_phone") or ""

            package_id = metadata.get("package_id") or ps_metadata.get("package_id") or payment.get("package_id")
            old_package_id = metadata.get("old_package_id") or ps_metadata.get("old_package_id") or payment.get("old_package_id")
            billing_period = metadata.get("billing_period") or ps_metadata.get("billing_period") or amount_detail.get("billing_period") or "monthly"
            user_id = metadata.get("user_id") or ps_metadata.get("user_id") or payment.get("user_id")
            user__id = metadata.get("user__id") or ps_metadata.get("user__id") or payment.get("user__id")

            purchase_type = _extract_purchase_type(metadata, ps_metadata, amount_detail)
            storage_addon_gb = _extract_storage_addon_gb(metadata, ps_metadata, amount_detail)

            update_data = {
                "checkout_request_id": data.get("id") or payment.get("checkout_request_id"),
                "customer_phone": customer_phone,
                "customer_name": customer_name,
                "customer_email": customer_email,
                "callback_response": data,
                "updated_at": datetime.utcnow(),
            }

            # ══════════════════════════════════════════════
            # CHARGE SUCCESS
            # ══════════════════════════════════════════════
            if event_type == "charge.success":
                verify_success, verify_data, verify_error = verify_transaction(
                    reference,
                    secret_key=paystack_secret,
                )
                if verify_success and verify_data.get("status") != "success":
                    return jsonify({"code": 200, "message": "Verification mismatch — acknowledged"}), 200

                Payment.update_status(
                    payment_id,
                    Payment.STATUS_SUCCESS,
                    gateway_transaction_id=gateway_txn_id,
                )
                Payment.update(
                    payment_id,
                    business_id=business_id,
                    processing_callback=True,
                    completed_at=datetime.utcnow(),
                    **update_data,
                )

                package = Package.get_by_id(str(package_id)) if package_id else {}
                package = package or {}
                plan_name = (
                    f"{storage_addon_gb}GB Storage Add-on"
                    if purchase_type == "storage_addon"
                    else (package.get("name") or metadata.get("purchase_label") or "Payment")
                )
                paid_date = str(data.get("paid_at") or datetime.utcnow())
                invoice_number = payment.get("reference") or reference

                # ── Invoice + Email (always) ──
                try:
                    invoice_bytes = generate_invoice_pdf_bytes(
                        invoice_number=invoice_number,
                        fullname=customer_name,
                        email=customer_email,
                        plan_name=plan_name,
                        currency=currency_symbol,
                        payment_method="paystack",
                        receipt_number=customer_phone,
                        paid_date=paid_date,
                        addon_users=addon_users,
                        package_amount=package_amount,
                        amount=amount_paid,
                        total_from_amount=original_total,
                    )

                    invoice_asset = upload_invoice_and_get_asset(
                        business_id=business_id,
                        user__id=str(user__id) if user__id else str(payment.get("user__id") or ""),
                        invoice_number=invoice_number,
                        invoice_pdf_bytes=invoice_bytes,
                    )

                    Payment.update(
                        payment_id,
                        business_id=business_id,
                        invoice_asset=invoice_asset,
                        processing_callback=True,
                    )

                    send_payment_confirmation_email(
                        email=customer_email,
                        fullname=customer_name,
                        currency=currency_symbol,
                        receipt_number=customer_phone,
                        invoice_number=invoice_number,
                        payment_method="paystack",
                        paid_date=paid_date,
                        plan_name=plan_name,
                        addon_users=addon_users,
                        package_amount=package_amount,
                        amount=amount_paid,
                        total_from_amount=original_total,
                        invoice_pdf_bytes=invoice_bytes,
                        invoice_url=(invoice_asset or {}).get("url"),
                    )
                except Exception as e:
                    Log.warning(f"{log_tag} Invoice/email error: {e}")

                # ── Save card (always) ──
                _save_card_from_paystack(
                    data=data,
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    log_tag=log_tag,
                )

                subscription_id = None
                storage_result = None

                # ══════════════════════════════════════════════
                # SYSTEM BILLING (subscription / storage addon)
                # ══════════════════════════════════════════════
                if _is_system_billing_payment(purchase_type):
                    Log.info(f"{log_tag} System billing: purchase_type={purchase_type}")

                    if purchase_type == "storage_addon":
                        storage_success, storage_result, storage_error = _process_storage_addon_purchase(
                            payment=payment,
                            metadata=metadata,
                            amount_detail=amount_detail,
                            business_id=business_id,
                            user__id=user__id,
                            reference=reference,
                            log_tag=log_tag,
                        )
                        if not storage_success:
                            Payment.update(
                                payment_id, business_id=business_id, processing_callback=True,
                                notes=f"Payment OK but storage addon failed: {storage_error}",
                            )
                            Log.info(f"{log_tag} Payment OK but storage addon failed: {storage_error}")
                            return jsonify({
                                "code": 200,
                                "message": "Payment OK but storage addon failed",
                                "error": storage_error,
                            }), 200

                    else:
                        # Subscription
                        if not package_id or not user__id:
                            Payment.update(
                                payment_id, business_id=business_id, processing_callback=True,
                                notes="Payment OK but missing package_id or user__id",
                            )
                            Log.info(f"{log_tag} Missing package_id or user__id — subscription not created")
                            return jsonify({
                                "code": 200,
                                "message": "Missing package_id or user__id — subscription not created",
                            }), 200

                        if not old_package_id:
                            success, subscription_id, error = SubscriptionService.create_subscription(
                                business_id=business_id,
                                user_id=user_id,
                                user__id=user__id,
                                package_id=str(package_id),
                                payment_method=PAYMENT_METHODS.get("PAYSTACK", "paystack"),
                                payment_reference=reference,
                                payment_done=True,
                                amount_detail=amount_detail,
                                addon_users=addon_users,
                            )

                            if not success:
                                Payment.update(
                                    payment_id, business_id=business_id, processing_callback=True,
                                    notes=f"Payment OK but subscription failed: {error}",
                                )
                                Log.info(f"{log_tag} Payment OK but subscription failed: {error}")
                                return jsonify({
                                    "code": 200,
                                    "message": "Payment OK but subscription failed",
                                    "error": error,
                                }), 200

                            try:
                                Business.update_account_status_by_business_id(
                                    business_id, client_ip, "subscribed_to_package", True,
                                )
                            except Exception:
                                pass
                        else:
                            success, subscription_id, error = SubscriptionService.apply_or_renew_from_payment(
                                business_id=business_id,
                                user_id=user_id,
                                user__id=user__id,
                                package_id=str(package_id),
                                billing_period=billing_period,
                                payment_method=PAYMENT_METHODS.get("PAYSTACK", "paystack"),
                                payment_reference=reference,
                            )

                            if not success:
                                Payment.update(
                                    payment_id, business_id=business_id, processing_callback=True,
                                    notes=f"Payment OK but renewal failed: {error}",
                                )
                                Log.info(f"{log_tag} Payment OK but renewal failed: {error}")
                                return jsonify({
                                    "code": 200,
                                    "message": "Payment OK but renewal failed",
                                    "error": error,
                                }), 200

                    # Discount + commission (system billing only)
                    _record_discount_redemption(
                        metadata=metadata,
                        ps_metadata=ps_metadata,
                        business_id=business_id,
                        user__id=user__id,
                        subscription_id=subscription_id,
                        log_tag=log_tag,
                    )

                    try:
                        from ....models.admin.promo_model import CommissionService
                        CommissionService.process_commission(
                            referred_business_id=business_id,
                            payment_amount=float(total_from_amount or package_amount or 0),
                            payment_reference=reference,
                            currency=currency_symbol,
                            plan_name=plan_name,
                            billing_period=billing_period,
                        )
                    except Exception as e:
                        Log.warning(f"{log_tag} Commission error (ignored): {e}")

                # ══════════════════════════════════════════════
                # CHURCH COLLECTION (donation, offering, event)
                # ══════════════════════════════════════════════
                else:
                    Log.info(f"{log_tag} Church collection: purchase_type={purchase_type}, ref={reference}")

                return jsonify({
                    "code": 200,
                    "message": "Callback processed successfully",
                    "payment_status": Payment.STATUS_SUCCESS,
                    "purchase_type": purchase_type,
                    "subscription_id": subscription_id,
                    "storage": storage_result,
                    "discount_redeemed": discount_code if has_discount else None,
                }), 200

            # ══════════════════════════════════════════════
            # CHARGE FAILED
            # ══════════════════════════════════════════════
            gateway_response = data.get("gateway_response", "Transaction failed")
            Payment.update_status(
                payment_id,
                Payment.STATUS_FAILED,
                gateway_transaction_id=gateway_txn_id,
                error_message=str(gateway_response),
            )
            Payment.update(
                payment_id,
                business_id=business_id,
                processing_callback=True,
                failed_at=datetime.utcnow(),
                **update_data,
            )

            return jsonify({
                "code": 200,
                "message": "Payment failed",
                "payment_status": Payment.STATUS_FAILED,
                "error": gateway_response,
            }), 200

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return jsonify({"code": 200, "message": f"Error: {str(e)}"}), 200


@paystack_blp.route("/webhooks/payment/paystack/callback", methods=["GET"])
class PaystackCallback(MethodView):

    def get(self):
        log_tag = "[paystack_webhook_resource.py][PaystackCallback][get]"
        reference = None
        frontend_return_url = os.getenv("PAYMENT_FRONT_END_RETURN_URL", "")

        try:
            reference = request.args.get("reference") or request.args.get("trxref")
            if not reference:
                if frontend_return_url:
                    return redirect(
                        f"{frontend_return_url}?{urlencode({'status': 'error', 'message': 'Missing transaction reference'})}",
                        code=302,
                    )
                return prepared_response(False, "BAD_REQUEST", "Missing transaction reference")

            payment = Payment.get_by_reference(reference) or Payment.get_by_order_id(reference)
            if not payment:
                if frontend_return_url:
                    return redirect(
                        f"{frontend_return_url}?{urlencode({'status': 'error', 'reference': reference, 'message': 'Payment record not found'})}",
                        code=302,
                    )
                return prepared_response(False, "NOT_FOUND", "Payment not found")

            paystack_secret = _resolve_paystack_secret_for_payment(payment, log_tag)

            verify_success, verify_data, verify_error = verify_transaction(
                reference,
                secret_key=paystack_secret,
            )

            if not verify_success:
                if frontend_return_url:
                    return redirect(
                        f"{frontend_return_url}?{urlencode({'status': 'error', 'message': verify_error or 'Verification failed', 'reference': reference})}",
                        code=302,
                    )
                return prepared_response(False, "BAD_REQUEST", verify_error or "Verification failed")

            txn_status = verify_data.get("status")
            paystack_customer = verify_data.get("customer", {}) or {}
            paystack_authorization = verify_data.get("authorization", {}) or {}
            ps_metadata = verify_data.get("metadata", {}) or {}

            payment_id = str(payment.get("_id"))
            business_id = str(payment.get("business_id") or "")
            current_status = (payment.get("status") or "").strip()

            metadata = _parse_metadata(payment)
            amount_detail = _parse_amount_detail(payment)

            callback_return_url = metadata.get("return_url")
            if callback_return_url:
                frontend_return_url = callback_return_url

            gateway_txn_id = str(verify_data.get("id", ""))
            purchase_type = _extract_purchase_type(metadata, ps_metadata, amount_detail)
            storage_addon_gb = _extract_storage_addon_gb(metadata, ps_metadata, amount_detail)

            if current_status not in [Payment.STATUS_SUCCESS, Payment.STATUS_FAILED]:
                if txn_status == "success":
                    Payment.update_status(
                        payment_id,
                        Payment.STATUS_SUCCESS,
                        gateway_transaction_id=gateway_txn_id,
                    )
                    Payment.update(
                        payment_id,
                        business_id=business_id,
                        processing_callback=True,
                        callback_response=verify_data,
                        completed_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )

            _save_card_from_paystack(
                data=verify_data,
                business_id=business_id,
                user_id=payment.get("user_id"),
                user__id=payment.get("user__id"),
                log_tag=log_tag,
            )

            if frontend_return_url:
                raw_amount = verify_data.get("amount", 0)
                display_amount = round(raw_amount / 100, 2) if raw_amount else 0

                query_params = {
                    "status": txn_status,
                    "reference": reference,
                    "amount": str(display_amount),
                    "currency": verify_data.get("currency") or "",
                    "message": verify_data.get("gateway_response") or "",
                    "email": paystack_customer.get("email") or "",
                    "first_name": paystack_customer.get("first_name") or "",
                    "last_name": paystack_customer.get("last_name") or "",
                    "payment_date": str(verify_data.get("paid_at") or ""),
                    "processor_transaction_id": str(verify_data.get("id") or ""),
                    "payment_method": "paystack",
                    "purchase_type": purchase_type,
                    "storage_addon_gb": str(storage_addon_gb or ""),
                    "source[type]": verify_data.get("channel") or "",
                    "source[number]": paystack_authorization.get("last4") or "",
                    "status_code": "200" if txn_status == "success" else "400",
                }

                return redirect(f"{frontend_return_url}?{urlencode(query_params)}", code=302)

            return prepared_response(
                status=(txn_status == "success"),
                status_code="OK" if txn_status == "success" else "BAD_REQUEST",
                message=f"Payment {txn_status}",
                data={
                    "reference": reference,
                    "status": txn_status,
                },
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if frontend_return_url:
                return redirect(
                    f"{frontend_return_url}?{urlencode({'status': 'error', 'message': str(e), 'reference': reference or 'unknown'})}",
                    code=302,
                )
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Callback error: {str(e)}")