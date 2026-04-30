# resources/payments/asoriba_webhook_resource.py

"""
Asoriba / MyBusinessPay Webhook & Callback Endpoints
======================================================
1. POST /payments/asoriba/webhook   - Receives Asoriba event notifications
2. GET  /payments/asoriba/callback  - Customer redirect after checkout
3. POST /payments/asoriba/verify    - Manual verification by reference
"""

import json
import os
from datetime import datetime
from urllib.parse import urlencode
from flask import request, g, jsonify, redirect
from flask.views import MethodView
from flask_smorest import Blueprint

from ....models.admin.payment import Payment
from ....models.admin.package_model import Package
from ....models.business_model import Business
from ....services.pos.subscription_service import SubscriptionService
from ....constants.payment_methods import PAYMENT_METHODS
from ....utils.logger import Log
from ....utils.json_response import prepared_response
from ....utils.helpers import (
    build_receipt_sms, _is_system_billing_payment
)
from ....utils.payments.asoriba_utils_main import verify_transaction, verify_webhook_signature
from ....services.email_service import send_payment_confirmation_email
from ....utils.invoice.generate_invoice import generate_invoice_pdf_bytes
from ....utils.media.storage_router import upload_invoice_and_get_asset
from ..admin.admin_business_resource import token_required
from ....decorators.callback_restriction import asoriba_ip_whitelist

asoriba_blp = Blueprint(
    "asoriba_payments",
    __name__,
    description="Asoriba/MyBusinessPay payment webhook, callback, and verification handlers",
)


# =====================================================================
# SHARED HELPERS (reuse from paystack_webhook_resource)
# =====================================================================

def _parse_amount_detail(payment):
    raw = payment.get("amount_detail")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
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


def _record_discount_redemption(metadata, asoriba_metadata, business_id, user__id, subscription_id, log_tag):
    discount_code = (metadata or {}).get("discount_code") or (asoriba_metadata or {}).get("discount_code")
    discount_id = (metadata or {}).get("discount_id") or (asoriba_metadata or {}).get("discount_id")
    discount_amount_saved = float((metadata or {}).get("discount_amount") or (asoriba_metadata or {}).get("discount_amount") or 0)

    if discount_id and discount_amount_saved > 0:
        try:
            from ....models.social.discount_model import Discount
            Discount.record_redemption(
                discount_id=discount_id,
                business_id=str(business_id),
                user_id=str(user__id) if user__id else None,
                amount_saved=discount_amount_saved,
                subscription_id=str(subscription_id) if subscription_id else None,
            )
            Log.info(f"{log_tag} Discount redeemed: code={discount_code}, saved=${discount_amount_saved}")
        except Exception as e:
            Log.warning(f"{log_tag} Failed to record discount redemption (ignored): {e}")


def _process_referral_commission(business_id, total_from_amount, package_amount, reference, currency_symbol, plan_name, billing_period, log_tag):
    try:
        from ....models.admin.promo_model import CommissionService
        Log.info(f"{log_tag} Processing referral commission: business={business_id}, amount={total_from_amount or package_amount}")
        credited, amount = CommissionService.process_commission(
            referred_business_id=business_id,
            payment_amount=float(total_from_amount or package_amount or 0),
            payment_reference=reference,
            currency=currency_symbol,
            plan_name=plan_name,
            billing_period=billing_period,
        )
        if credited:
            Log.info(f"{log_tag} Commission credited: ${amount}")
        else:
            Log.info(f"{log_tag} No commission to credit (no referral or amount=0)")
    except Exception as e:
        Log.error(f"{log_tag} Commission processing EXCEPTION: {e}", exc_info=True)


def _create_or_renew_subscription(
    *, business_id, package_id, old_package_id, user_id, user__id,
    billing_period, reference, amount_detail, addon_users, client_ip, log_tag,
):
    if not package_id:
        Log.error(f"{log_tag} SUBSCRIPTION BLOCKED: package_id is None")
        return False, None, "package_id is None"

    if not user__id:
        Log.error(f"{log_tag} SUBSCRIPTION BLOCKED: user__id is None")
        return False, None, "user__id is None"

    if not old_package_id:
        Log.info(f"{log_tag} Creating NEW subscription: business={business_id}, package={package_id}")
        try:
            success, subscription_id, error = SubscriptionService.create_subscription(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                package_id=str(package_id),
                payment_method=PAYMENT_METHODS.get("ASORIBA", "asoriba"),
                payment_reference=reference,
                payment_done=True,
                amount_detail=amount_detail,
                addon_users=addon_users,
            )
            Log.info(f"{log_tag} create_subscription: success={success}, sub_id={subscription_id}, error={error}")
        except Exception as e:
            Log.error(f"{log_tag} create_subscription EXCEPTION: {e}", exc_info=True)
            return False, None, str(e)

        if success:
            try:
                Business.update_account_status_by_business_id(business_id, client_ip, "subscribed_to_package", True)
            except Exception as e:
                Log.warning(f"{log_tag} Account status update failed (ignored): {e}")

        return success, subscription_id, error
    else:
        Log.info(f"{log_tag} Plan change/renew: old={old_package_id}, new={package_id}")
        try:
            success, subscription_id, error = SubscriptionService.apply_or_renew_from_payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                package_id=str(package_id),
                billing_period=billing_period,
                payment_method=PAYMENT_METHODS.get("ASORIBA", "asoriba"),
                payment_reference=reference,
            )
            Log.info(f"{log_tag} apply_or_renew: success={success}, sub_id={subscription_id}, error={error}")
        except Exception as e:
            Log.error(f"{log_tag} apply_or_renew EXCEPTION: {e}", exc_info=True)
            return False, None, str(e)

        return success, subscription_id, error


# =====================================================================
# ASORIBA WEBHOOK
# =====================================================================

@asoriba_blp.route("/webhooks/payment/asoriba", methods=["POST"])
class AsoribaWebhook(MethodView):

    @asoriba_ip_whitelist
    @asoriba_blp.response(200)
    def post(self):
        reference = None
        log_tag = "[asoriba_webhook_resource.py][AsoribaWebhook][post]"
        client_ip = request.remote_addr

        try:
            Log.info(f"{log_tag} Received Asoriba webhook ip={client_ip}")

            signature = request.headers.get("X-Asoriba-Signature", "") or request.headers.get("X-Webhook-Signature", "")
            raw_body = request.get_data()

            if not verify_webhook_signature(raw_body, signature):
                Log.warning(f"{log_tag} Invalid webhook signature")
                return jsonify({"code": 401, "message": "Invalid signature"}), 401

            event_payload = request.get_json(silent=True) or {}
            event_type = event_payload.get("event") or event_payload.get("type") or "payment"
            data = event_payload.get("data", {}) or event_payload

            reference = data.get("reference") or data.get("transaction_reference") or data.get("trxref")
            txn_status = (data.get("status") or "").lower()

            Log.info(f"{log_tag} Event: {event_type}, reference={reference}, status={txn_status}")

            if not reference:
                return jsonify({"code": 200, "message": "No reference"}), 200

            payment = Payment.get_by_reference(reference) or Payment.get_by_order_id(reference)
            if not payment:
                Log.error(f"{log_tag} Payment not found ref={reference}")
                return jsonify({"code": 200, "message": "Payment not found"}), 200

            payment_id = str(payment.get("_id"))
            business_id = str(payment.get("business_id") or "")
            current_status = (payment.get("status") or "").strip()

            if current_status in [Payment.STATUS_SUCCESS, Payment.STATUS_FAILED]:
                Log.info(f"{log_tag} Already processed: {current_status}")
                return jsonify({"code": 200, "message": "Already processed"}), 200

            # Extract data
            amount_detail = _parse_amount_detail(payment)
            metadata = _parse_metadata(payment)
            asoriba_metadata = data.get("metadata", {}) or {}
            customer = data.get("customer", {}) or {}

            addon_users = int(amount_detail.get("addon_users") or 0)
            package_amount = float(amount_detail.get("package_amount") or 0)
            currency_symbol = amount_detail.get("from_currency") or payment.get("currency") or "GHS"
            original_total = float(amount_detail.get("original_total") or amount_detail.get("total_from_amount") or package_amount)
            total_from_amount = float(amount_detail.get("total_from_amount") or package_amount)
            amount_paid = total_from_amount

            discount_code = amount_detail.get("discount_code") or metadata.get("discount_code")
            discount_amount = float(amount_detail.get("discount_amount") or metadata.get("discount_amount") or 0)
            discount_display = amount_detail.get("discount_display")
            discount_type = amount_detail.get("discount_type")
            discount_value = amount_detail.get("discount_value")
            has_discount = bool(discount_code and discount_amount > 0)

            local_currency = amount_detail.get("to_currency")
            local_amount = float(amount_detail.get("total_to_amount") or 0)
            exchange_rate_val = float(amount_detail.get("exchange_rate") or 0)
            show_local = bool(local_currency and local_currency != currency_symbol and local_amount > 0)

            customer_name = (customer.get("name") or
                             f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip() or
                             payment.get("customer_name") or "")
            customer_email = customer.get("email") or payment.get("customer_email") or ""
            customer_phone = customer.get("phone") or customer.get("phone_number") or payment.get("customer_phone") or ""

            package_id = metadata.get("package_id") or asoriba_metadata.get("package_id") or payment.get("package_id")
            old_package_id = metadata.get("old_package_id") or asoriba_metadata.get("old_package_id") or payment.get("old_package_id")
            billing_period = metadata.get("billing_period") or asoriba_metadata.get("billing_period") or amount_detail.get("billing_period") or "monthly"
            user_id = metadata.get("user_id") or asoriba_metadata.get("user_id") or payment.get("user_id")
            user__id = metadata.get("user__id") or asoriba_metadata.get("user__id") or payment.get("user__id")

            purchase_type = (
                metadata.get("purchase_type")
                or asoriba_metadata.get("purchase_type")
                or amount_detail.get("purchase_type")
                or "subscription"
            )
            storage_addon_gb = (
                metadata.get("storage_addon_gb")
                or asoriba_metadata.get("storage_addon_gb")
                or amount_detail.get("storage_addon_gb")
            )

            gateway_txn_id = str(data.get("id") or data.get("transaction_id") or "")

            Log.info(f"{log_tag} Extracted: package_id={package_id}, user__id={user__id}, purchase_type={purchase_type}")

            update_data = {
                "checkout_request_id": gateway_txn_id or payment.get("checkout_request_id"),
                "customer_phone": customer_phone,
                "customer_name": customer_name,
                "customer_email": customer_email,
                "callback_response": data,
                "updated_at": datetime.utcnow(),
            }

            package = Package.get_by_id(str(package_id)) if package_id else {}
            package = package or {}
            plan_name = (
                f"{storage_addon_gb}GB Storage Add-on"
                if purchase_type == "storage_addon"
                else (package.get("name") or metadata.get("purchase_label") or "Payment")
            )
            paid_date = str(data.get("paid_at") or data.get("completed_at") or datetime.utcnow())
            invoice_number = payment.get("reference") or reference

            # ══════════════════════════════════════════════
            # SUCCESS
            # ══════════════════════════════════════════════
            if txn_status in ("success", "successful", "completed", "paid"):
                Log.info(f"{log_tag} Payment SUCCESS ref={reference}")

                # Verify with Asoriba
                verify_success, verify_data_resp, verify_error = verify_transaction(reference)
                if verify_success and verify_data_resp.get("status") not in ("success", "successful", "completed", "paid"):
                    Log.error(f"{log_tag} Verify mismatch: {verify_data_resp.get('status')}")
                    return jsonify({"code": 200, "message": "Verification mismatch"}), 200

                Payment.update_status(payment_id, Payment.STATUS_SUCCESS, gateway_transaction_id=gateway_txn_id)
                Payment.update(payment_id, business_id=business_id, processing_callback=True, completed_at=datetime.utcnow(), **update_data)

                # ── Invoice + email (always) ──
                try:
                    invoice_bytes = generate_invoice_pdf_bytes(
                        invoice_number=invoice_number, fullname=customer_name, email=customer_email,
                        plan_name=plan_name, currency=currency_symbol, payment_method="asoriba",
                        receipt_number=customer_phone, paid_date=paid_date,
                        addon_users=addon_users, package_amount=package_amount,
                        amount=amount_paid, total_from_amount=original_total,
                        discount_code=discount_code if has_discount else None,
                        discount_amount=discount_amount if has_discount else None,
                        discount_display=discount_display if has_discount else None,
                        original_total=original_total if has_discount else None,
                        local_currency=local_currency if show_local else None,
                        local_amount=local_amount if show_local else None,
                        exchange_rate=exchange_rate_val if show_local else None,
                    )

                    invoice_asset = upload_invoice_and_get_asset(
                        business_id=business_id,
                        user__id=str(user__id) if user__id else "",
                        invoice_number=invoice_number,
                        invoice_pdf_bytes=invoice_bytes,
                    )

                    Payment.update(payment_id, business_id=business_id, invoice_asset=invoice_asset, processing_callback=True)

                    send_payment_confirmation_email(
                        email=customer_email, fullname=customer_name, currency=currency_symbol,
                        receipt_number=customer_phone, invoice_number=invoice_number,
                        payment_method="asoriba", paid_date=paid_date, plan_name=plan_name,
                        addon_users=addon_users, package_amount=package_amount,
                        amount=amount_paid, total_from_amount=original_total,
                        invoice_pdf_bytes=invoice_bytes,
                        invoice_url=(invoice_asset or {}).get("url"),
                        local_currency=local_currency if show_local else None,
                        local_amount=local_amount if show_local else None,
                        exchange_rate=exchange_rate_val if show_local else None,
                        discount_code=discount_code if has_discount else None,
                        discount_type=discount_type if has_discount else None,
                        discount_value=discount_value if has_discount else None,
                        discount_display=discount_display if has_discount else None,
                        discount_amount=discount_amount if has_discount else None,
                        original_price=original_total if has_discount else None,
                    )
                except Exception as e:
                    Log.warning(f"{log_tag} Invoice/email error (ignored): {e}")
                    import traceback
                    traceback.print_exc()

                subscription_id = None
                storage_result = None

                # ══════════════════════════════════════════════
                # SYSTEM BILLING (subscription / storage addon)
                # ══════════════════════════════════════════════
                if _is_system_billing_payment(purchase_type):
                    Log.info(f"{log_tag} System billing: purchase_type={purchase_type}")

                    if purchase_type == "storage_addon":
                        try:
                            from ....models.social.form_model import StorageQuota

                            addon_gb = int(storage_addon_gb or 0)
                            if addon_gb > 0:
                                paid_amount = float(amount_detail.get("total_from_amount") or payment.get("amount") or 0)
                                ok = StorageQuota.add_addon_storage(
                                    business_id=business_id,
                                    addon_gb=addon_gb,
                                    payment_reference=reference,
                                    price=paid_amount,
                                    processing_callback=True,
                                )
                                if ok:
                                    storage_result = {"storage_addon_gb": addon_gb}
                                else:
                                    Payment.update(
                                        payment_id, business_id=business_id, processing_callback=True,
                                        notes="Payment OK but storage addon failed",
                                    )
                                    Log.info(f"{log_tag} Payment OK but storage addon failed")
                                    return jsonify({"code": 200, "message": "Storage addon failed"}), 200
                        except Exception as e:
                            Log.error(f"{log_tag} Storage addon error: {e}", exc_info=True)
                            Payment.update(
                                payment_id, business_id=business_id, processing_callback=True,
                                notes=f"Payment OK but storage addon error: {e}",
                            )
                            return jsonify({"code": 200, "message": f"Storage addon error: {e}"}), 200

                    else:
                        # Subscription
                        if not package_id or not user__id:
                            Payment.update(
                                payment_id, business_id=business_id, processing_callback=True,
                                notes="Payment OK but missing package_id or user__id",
                            )
                            Log.info(f"{log_tag} Missing package_id or user__id — subscription not created")
                            return jsonify({"code": 200, "message": "Missing package_id or user__id"}), 200

                        if not old_package_id:
                            success, subscription_id, error = SubscriptionService.create_subscription(
                                business_id=business_id,
                                user_id=user_id,
                                user__id=user__id,
                                package_id=str(package_id),
                                payment_method=PAYMENT_METHODS.get("ASORIBA", "asoriba"),
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
                                return jsonify({"code": 200, "message": "Subscription failed", "error": error}), 200

                            try:
                                Business.update_account_status_by_business_id(business_id, client_ip, "subscribed_to_package", True)
                            except Exception:
                                pass
                        else:
                            success, subscription_id, error = SubscriptionService.apply_or_renew_from_payment(
                                business_id=business_id,
                                user_id=user_id,
                                user__id=user__id,
                                package_id=str(package_id),
                                billing_period=billing_period,
                                payment_method=PAYMENT_METHODS.get("ASORIBA", "asoriba"),
                                payment_reference=reference,
                            )

                            if not success:
                                Payment.update(
                                    payment_id, business_id=business_id, processing_callback=True,
                                    notes=f"Payment OK but renewal failed: {error}",
                                )
                                Log.info(f"{log_tag} Payment OK but renewal failed: {error}")
                                return jsonify({"code": 200, "message": "Renewal failed", "error": error}), 200

                    # Discount + commission (system billing only)
                    _record_discount_redemption(metadata, asoriba_metadata, business_id, user__id, subscription_id, log_tag)
                    _process_referral_commission(business_id, total_from_amount, package_amount, reference, currency_symbol, plan_name, billing_period, log_tag)

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
            # FAILURE
            # ══════════════════════════════════════════════
            elif txn_status in ("failed", "declined", "cancelled", "abandoned"):
                gateway_response = data.get("gateway_response") or data.get("message") or "Transaction failed"
                Log.warning(f"{log_tag} Payment FAILED: {gateway_response}")

                Payment.update_status(payment_id, Payment.STATUS_FAILED, gateway_transaction_id=gateway_txn_id, error_message=str(gateway_response))
                Payment.update(payment_id, business_id=business_id, processing_callback=True, failed_at=datetime.utcnow(), **update_data)

                return jsonify({"code": 200, "message": "Payment failed", "payment_status": Payment.STATUS_FAILED}), 200

            # ══════════════════════════════════════════════
            # PENDING / OTHER
            # ══════════════════════════════════════════════
            else:
                Log.info(f"{log_tag} Status '{txn_status}' — acknowledged, no action")
                return jsonify({"code": 200, "message": f"Status {txn_status} acknowledged"}), 200

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if reference:
                try:
                    p = Payment.get_by_reference(reference)
                    if p:
                        Payment.update(str(p["_id"]), business_id=str(p.get("business_id") or ""), processing_callback=True, notes=f"Webhook error: {str(e)}", updated_at=datetime.utcnow())
                except Exception:
                    pass
            return jsonify({"code": 200, "message": f"Error: {str(e)}"}), 200

# =====================================================================
# ASORIBA CALLBACK (customer redirect)
# =====================================================================

@asoriba_blp.route("/payments/asoriba/callback", methods=["GET"])
class AsoribaCallback(MethodView):

    def get(self):
        log_tag = "[asoriba_webhook_resource.py][AsoribaCallback][get]"
        reference = None
        frontend_return_url = os.getenv("PAYMENT_FRONT_END_RETURN_URL", "")

        try:
            reference = request.args.get("reference") or request.args.get("trxref") or request.args.get("transaction_reference")
            client_ip = request.remote_addr

            Log.info(f"{log_tag} Callback ref={reference} ip={client_ip}")

            if not reference:
                if frontend_return_url:
                    return redirect(f"{frontend_return_url}?{urlencode({'status': 'error', 'message': 'Missing transaction reference'})}", code=302)
                return prepared_response(False, "BAD_REQUEST", "Missing transaction reference")

            verify_success, verify_data, verify_error = verify_transaction(reference)

            if not verify_success:
                Log.error(f"{log_tag} Verification failed: {verify_error}")
                if frontend_return_url:
                    return redirect(f"{frontend_return_url}?{urlencode({'status': 'error', 'message': verify_error or 'Verification failed', 'reference': reference})}", code=302)
                return prepared_response(False, "BAD_REQUEST", verify_error or "Verification failed")

            txn_status = verify_data.get("status", "")
            customer = verify_data.get("customer", {}) or {}

            payment = Payment.get_by_reference(reference) or Payment.get_by_order_id(reference)

            if not payment:
                Log.warning(f"{log_tag} Payment not found ref={reference}")
                if frontend_return_url:
                    return redirect(f"{frontend_return_url}?{urlencode({'status': txn_status, 'reference': reference, 'message': 'Payment record not found'})}", code=302)
                return prepared_response(False, "NOT_FOUND", "Payment not found")

            payment_id = str(payment.get("_id"))
            business_id = str(payment.get("business_id") or "")
            current_status = (payment.get("status") or "").strip()

            metadata = _parse_metadata(payment)
            callback_return_url = metadata.get("return_url")
            if callback_return_url:
                frontend_return_url = callback_return_url

            gateway_txn_id = str(verify_data.get("raw", {}).get("id", "") or "")

            if current_status not in [Payment.STATUS_SUCCESS, Payment.STATUS_FAILED]:
                if txn_status in ("success", "successful", "completed", "paid"):
                    Payment.update_status(payment_id, Payment.STATUS_SUCCESS, gateway_transaction_id=gateway_txn_id)
                    Payment.update(
                        payment_id, business_id=business_id, processing_callback=True,
                        callback_response=verify_data, completed_at=datetime.utcnow(), updated_at=datetime.utcnow(),
                    )
                    Log.info(f"{log_tag} Payment marked SUCCESS from callback")

                    # Create subscription if webhook hasn't yet
                    try:
                        amount_detail = _parse_amount_detail(payment)
                        asoriba_metadata = verify_data.get("raw", {}).get("metadata", {}) or {}

                        package_id = metadata.get("package_id") or asoriba_metadata.get("package_id") or payment.get("package_id")
                        old_package_id = metadata.get("old_package_id") or asoriba_metadata.get("old_package_id") or payment.get("old_package_id")
                        billing_period = metadata.get("billing_period") or asoriba_metadata.get("billing_period") or amount_detail.get("billing_period") or "monthly"
                        user_id = metadata.get("user_id") or asoriba_metadata.get("user_id") or payment.get("user_id")
                        user__id = metadata.get("user__id") or asoriba_metadata.get("user__id") or payment.get("user__id")
                        addon_users = int(amount_detail.get("addon_users") or 0)

                        if package_id and user__id:
                            success, sub_id, error = _create_or_renew_subscription(
                                business_id=business_id, package_id=package_id,
                                old_package_id=old_package_id, user_id=user_id, user__id=user__id,
                                billing_period=billing_period, reference=reference,
                                amount_detail=amount_detail, addon_users=addon_users,
                                client_ip=client_ip, log_tag=log_tag,
                            )
                            if success:
                                Log.info(f"{log_tag} Callback subscription created: {sub_id}")
                            else:
                                Log.warning(f"{log_tag} Callback subscription failed: {error}")
                    except Exception as e:
                        Log.warning(f"{log_tag} Callback subscription error (webhook may handle): {e}")

                elif txn_status in ("failed", "declined", "cancelled"):
                    Payment.update_status(
                        payment_id, Payment.STATUS_FAILED,
                        gateway_transaction_id=gateway_txn_id,
                        error_message=verify_data.get("gateway_response", "Failed"),
                    )
            else:
                Log.info(f"{log_tag} Payment already processed by webhook")

            if frontend_return_url:
                display_amount = verify_data.get("amount") or 0

                query_params = {
                    "status": txn_status,
                    "reference": reference,
                    "amount": str(display_amount),
                    "currency": verify_data.get("currency") or "",
                    "message": verify_data.get("gateway_response") or "",
                    "email": customer.get("email") or "",
                    "payment_method": "asoriba",
                    "status_code": "200" if txn_status in ("success", "successful", "completed", "paid") else "400"
                }

                return redirect(f"{frontend_return_url}?{urlencode(query_params)}", code=302)

            return prepared_response(
                status=(txn_status in ("success", "successful", "completed", "paid")),
                status_code="OK" if txn_status in ("success", "successful") else "BAD_REQUEST",
                message=f"Payment {txn_status}",
                data={"reference": reference, "status": txn_status},
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if frontend_return_url:
                return redirect(f"{frontend_return_url}?{urlencode({'status': 'error', 'message': str(e), 'reference': reference or 'unknown'})}", code=302)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Callback error: {str(e)}")


# =====================================================================
# MANUAL VERIFY (authenticated)
# =====================================================================

@asoriba_blp.route("/payments/asoriba/verify", methods=["POST"])
class AsoribaVerifyPayment(MethodView):

    @token_required
    @asoriba_blp.response(200)
    def post(self):
        log_tag = "[AsoribaVerifyPayment][post]"

        try:
            json_data = request.get_json(silent=True) or {}
            reference = json_data.get("reference")

            if not reference:
                return prepared_response(False, "BAD_REQUEST", "Transaction reference is required")

            success, data, error = verify_transaction(reference)

            if success:
                return prepared_response(True, "OK", "Payment verification complete", data=data)
            else:
                return prepared_response(False, "BAD_REQUEST", error or "Verification failed")

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to verify payment", errors=[str(e)])
