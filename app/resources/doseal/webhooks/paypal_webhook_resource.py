# resources/payments/paypal_webhook_resource.py

"""
PayPal Webhook & Callback Endpoints
======================================
1. POST /webhooks/payment/paypal             - Receives PayPal event notifications
2. GET  /webhooks/payment/paypal/callback    - Customer redirect after approval
3. POST /webhooks/payment/paypal/verify      - Manual verification by order ID
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
from ....constants.payment_methods import PAYMENT_METHODS
from ....utils.logger import Log
from ....utils.json_response import prepared_response
from ....utils.payments.paypal_utils import (
    verify_webhook_signature,
    capture_order,
    get_order,
)
from ....services.email_service import send_payment_confirmation_email
from ....utils.invoice.generate_invoice import generate_invoice_pdf_bytes
from ....utils.media.storage_router import upload_invoice_and_get_asset
from ....decorators.callback_restriction import paypal_ip_whitelist
from ..admin.admin_business_resource import token_required

paypal_blp = Blueprint(
    "paypal_payments",
    __name__,
    description="PayPal payment webhook, callback, and verification handlers",
)


# =====================================================================
# SHARED HELPERS
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

def _process_successful_payment(payment, capture_data, client_ip, log_tag):
    """
    Shared logic for processing a successful PayPal payment.
    Called from both webhook and callback.
    Returns (success, subscription_id, error).
    """
    payment_id = str(payment.get("_id"))
    business_id = str(payment.get("business_id") or "")
    reference = payment.get("reference") or payment.get("order_id")

    amount_detail = _parse_amount_detail(payment)
    metadata = _parse_metadata(payment)

    addon_users = int(amount_detail.get("addon_users") or 0)
    package_amount = float(amount_detail.get("package_amount") or 0)
    currency_symbol = amount_detail.get("from_currency") or payment.get("currency") or "USD"
    original_total = float(amount_detail.get("original_total") or amount_detail.get("total_from_amount") or package_amount)
    total_from_amount = float(amount_detail.get("total_from_amount") or package_amount)
    amount_paid = total_from_amount

    discount_code = amount_detail.get("discount_code") or metadata.get("discount_code")
    discount_amount = float(amount_detail.get("discount_amount") or 0)
    has_discount = bool(discount_code and discount_amount > 0)

    local_currency = amount_detail.get("to_currency")
    local_amount = float(amount_detail.get("total_to_amount") or 0)
    exchange_rate_val = float(amount_detail.get("exchange_rate") or 0)
    show_local = bool(local_currency and local_currency != currency_symbol and local_amount > 0)

    customer_email = capture_data.get("payer_email") or payment.get("customer_email") or ""
    customer_name = capture_data.get("payer_name") or payment.get("customer_name") or ""
    customer_phone = payment.get("customer_phone") or ""

    package_id = metadata.get("package_id") or payment.get("package_id")
    old_package_id = metadata.get("old_package_id")
    billing_period = metadata.get("billing_period") or "monthly"
    user_id = metadata.get("user_id") or payment.get("user_id")
    user__id = metadata.get("user__id") or payment.get("user__id")

    capture_id = capture_data.get("capture_id") or capture_data.get("order_id")

    package = Package.get_by_id(str(package_id)) if package_id else {}
    plan_name = (package or {}).get("name") or "Subscription"
    paid_date = str(datetime.utcnow())
    invoice_number = reference

    # Mark success
    Payment.update_status(payment_id, Payment.STATUS_SUCCESS, gateway_transaction_id=capture_id)
    Payment.update(
        payment_id, business_id=business_id, processing_callback=True,
        completed_at=datetime.utcnow(),
        callback_response=capture_data.get("raw", capture_data),
        customer_email=customer_email,
        customer_name=customer_name,
        updated_at=datetime.utcnow(),
    )

    # Invoice + email
    try:
        invoice_bytes = generate_invoice_pdf_bytes(
            invoice_number=invoice_number, fullname=customer_name, email=customer_email,
            plan_name=plan_name, currency=currency_symbol, payment_method="paypal",
            receipt_number=customer_phone, paid_date=paid_date,
            addon_users=addon_users, package_amount=package_amount,
            amount=amount_paid, total_from_amount=original_total,
            discount_code=discount_code if has_discount else None,
            discount_amount=discount_amount if has_discount else None,
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
            payment_method="paypal", paid_date=paid_date, plan_name=plan_name,
            addon_users=addon_users, package_amount=package_amount,
            amount=amount_paid, total_from_amount=original_total,
            invoice_pdf_bytes=invoice_bytes,
            invoice_url=(invoice_asset or {}).get("url"),
            discount_code=discount_code if has_discount else None,
            discount_amount=discount_amount if has_discount else None,
            original_price=original_total if has_discount else None,
            local_currency=local_currency if show_local else None,
            local_amount=local_amount if show_local else None,
            exchange_rate=exchange_rate_val if show_local else None,
        )
    except Exception as e:
        Log.warning(f"{log_tag} Invoice/email error (ignored): {e}")

    
    Log.info(f"{log_tag} Payment processed successfully: ref={reference}, capture_id={capture_id}")
    return True, payment_id, None

def _find_payment_by_paypal_order(paypal_order_id, reference=None):
    """Find our payment record by PayPal order ID or internal reference."""
    payment = None
    if reference:
        payment = Payment.get_by_reference(reference) or Payment.get_by_order_id(reference)
    if not payment and paypal_order_id:
        payment = Payment.get_by_order_id(paypal_order_id) or Payment.get_by_reference(paypal_order_id)
    return payment


# =====================================================================
# PAYPAL WEBHOOK
# =====================================================================

@paypal_blp.route("/webhooks/payment/paypal", methods=["POST"])
class PayPalWebhook(MethodView):

    @paypal_ip_whitelist
    @paypal_blp.response(200)
    def post(self):
        log_tag = "[paypal_webhook_resource.py][PayPalWebhook][post]"
        client_ip = request.remote_addr

        try:
            Log.info(f"{log_tag} Received PayPal webhook ip={client_ip}")

            # Signature verification
            raw_body = request.get_data()
            if not verify_webhook_signature(request.headers, raw_body):
                Log.warning(f"{log_tag} Invalid webhook signature")
                return jsonify({"error": "Invalid signature"}), 401

            event = request.get_json(silent=True) or {}
            event_type = event.get("event_type", "")
            resource = event.get("resource", {})

            Log.info(f"{log_tag} Event: {event_type}, resource_id={resource.get('id')}")

            # ── CHECKOUT.ORDER.APPROVED ──
            if event_type == "CHECKOUT.ORDER.APPROVED":
                return self._handle_order_approved(resource, client_ip, log_tag)

            # ── PAYMENT.CAPTURE.COMPLETED ──
            elif event_type == "PAYMENT.CAPTURE.COMPLETED":
                return self._handle_capture_completed(resource, client_ip, log_tag)

            # ── PAYMENT.CAPTURE.DENIED / DECLINED ──
            elif event_type in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED"):
                return self._handle_capture_failed(resource, log_tag)

            # ── PAYMENT.CAPTURE.REFUNDED ──
            elif event_type == "PAYMENT.CAPTURE.REFUNDED":
                return self._handle_capture_refunded(resource, log_tag)

            Log.info(f"{log_tag} Event {event_type} acknowledged (no handler)")
            return jsonify({"received": True}), 200

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return jsonify({"error": str(e)}), 200

    def _handle_order_approved(self, resource, client_ip, log_tag):
        """Customer approved the order on PayPal — now capture it."""
        order_id = resource.get("id")
        pu = (resource.get("purchase_units") or [{}])[0]
        reference = pu.get("custom_id") or pu.get("reference_id")

        Log.info(f"{log_tag} Order approved: {order_id}, ref={reference}")

        payment = _find_payment_by_paypal_order(order_id, reference)
        if not payment:
            Log.warning(f"{log_tag} Payment not found for order {order_id}")
            return jsonify({"received": True, "message": "Payment not found"}), 200

        current_status = (payment.get("status") or "").strip()
        if current_status == Payment.STATUS_SUCCESS:
            return jsonify({"received": True, "message": "Already processed"}), 200

        # Capture the payment
        success, capture_data, error = capture_order(order_id)
        if not success:
            Log.error(f"{log_tag} Capture failed: {error}")
            Payment.update_status(str(payment["_id"]), Payment.STATUS_FAILED, error_message=error)
            return jsonify({"received": True, "message": f"Capture failed: {error}"}), 200

        ok, sub_id, sub_error = _process_successful_payment(payment, capture_data, client_ip, log_tag)

        return jsonify({
            "received": True,
            "payment_status": "success" if ok else "subscription_failed",
            "subscription_id": sub_id,
        }), 200

    def _handle_capture_completed(self, resource, client_ip, log_tag):
        """Payment capture completed — process if not already done."""
        capture_id = resource.get("id")
        custom_id = resource.get("custom_id") or ""
        invoice_id = resource.get("invoice_id") or ""
        reference = custom_id or invoice_id

        Log.info(f"{log_tag} Capture completed: {capture_id}, ref={reference}")

        payment = _find_payment_by_paypal_order(None, reference)
        if not payment:
            Log.warning(f"{log_tag} Payment not found ref={reference}")
            return jsonify({"received": True}), 200

        current_status = (payment.get("status") or "").strip()
        if current_status == Payment.STATUS_SUCCESS:
            return jsonify({"received": True, "message": "Already processed"}), 200

        capture_data = {
            "capture_id": capture_id,
            "order_id": resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id"),
            "payer_email": "",
            "payer_name": "",
            "raw": resource,
        }

        ok, sub_id, _ = _process_successful_payment(payment, capture_data, client_ip, log_tag)
        return jsonify({"received": True, "subscription_id": sub_id}), 200

    def _handle_capture_failed(self, resource, log_tag):
        """Capture denied or declined."""
        capture_id = resource.get("id")
        reference = resource.get("custom_id") or resource.get("invoice_id")

        Log.warning(f"{log_tag} Capture failed: {capture_id}")

        if reference:
            payment = _find_payment_by_paypal_order(None, reference)
            if payment:
                Payment.update_status(
                    str(payment["_id"]), Payment.STATUS_FAILED,
                    gateway_transaction_id=capture_id,
                    error_message="PayPal capture denied",
                )

        return jsonify({"received": True}), 200

    def _handle_capture_refunded(self, resource, log_tag):
        """Capture was refunded."""
        refund_id = resource.get("id")
        refund_amount = float(resource.get("amount", {}).get("value") or 0)
        reference = resource.get("custom_id") or resource.get("invoice_id")

        Log.info(f"{log_tag} Refund: {refund_id}, amount={refund_amount}")

        if reference:
            payment = _find_payment_by_paypal_order(None, reference)
            if payment:
                try:
                    Payment.update(
                        str(payment["_id"]),
                        business_id=str(payment.get("business_id") or ""),
                        processing_callback=True,
                        refund_status="Refunded",
                        refunded_amount=refund_amount,
                        refunded_at=datetime.utcnow(),
                    )
                except Exception as e:
                    Log.warning(f"{log_tag} Refund update failed: {e}")

        return jsonify({"received": True}), 200


# =====================================================================
# PAYPAL CALLBACK (customer redirect after approval)
# =====================================================================

@paypal_blp.route("/webhooks/payment/paypal/callback", methods=["GET"])
class PayPalCallback(MethodView):

    def get(self):
        log_tag = "[paypal_webhook_resource.py][PayPalCallback][get]"
        frontend_return_url = os.getenv("PAYMENT_FRONT_END_RETURN_URL", "")

        try:
            # PayPal appends token (order ID) and PayerID to return_url
            paypal_order_id = request.args.get("token") or request.args.get("order_id")
            payer_id = request.args.get("PayerID")
            reference = request.args.get("reference")
            client_ip = request.remote_addr

            Log.info(f"{log_tag} Callback order_id={paypal_order_id} PayerID={payer_id} ref={reference}")

            if not paypal_order_id:
                if frontend_return_url:
                    return redirect(f"{frontend_return_url}?{urlencode({'status': 'error', 'message': 'Missing PayPal order ID'})}", code=302)
                return prepared_response(False, "BAD_REQUEST", "Missing PayPal order token")

            # Find payment record
            payment = _find_payment_by_paypal_order(paypal_order_id, reference)

            if payment:
                metadata = _parse_metadata(payment)
                callback_return_url = metadata.get("return_url")
                if callback_return_url:
                    frontend_return_url = callback_return_url
                if not reference:
                    reference = payment.get("reference")

            # Check current status
            current_status = (payment.get("status") or "").strip() if payment else ""

            if current_status == Payment.STATUS_SUCCESS:
                Log.info(f"{log_tag} Already processed by webhook")
                if frontend_return_url:
                    return redirect(f"{frontend_return_url}?{urlencode({'status': 'success', 'reference': reference or '', 'payment_method': 'paypal'})}", code=302)
                return prepared_response(True, "OK", "Payment already processed", data={"reference": reference})

            # Capture the order
            success, capture_data, error = capture_order(paypal_order_id)

            if success and payment:
                ok, sub_id, sub_error = _process_successful_payment(payment, capture_data, client_ip, log_tag)
                txn_status = "success"
                Log.info(f"{log_tag} Callback capture+subscription: ok={ok}, sub_id={sub_id}")

            elif success and not payment:
                Log.warning(f"{log_tag} Captured but no payment record found")
                txn_status = "success"

            else:
                Log.error(f"{log_tag} Capture failed: {error}")
                txn_status = "failed"
                if payment:
                    Payment.update_status(
                        str(payment["_id"]), Payment.STATUS_FAILED,
                        error_message=error,
                    )

            # Redirect to frontend
            if frontend_return_url:
                query_params = {
                    "status": txn_status,
                    "reference": reference or "",
                    "order_id": paypal_order_id,
                    "payment_method": "paypal",
                    "status_code": "200" if txn_status == "success" else "400",
                }
                if txn_status != "success":
                    query_params["message"] = error or "Payment failed"

                return redirect(f"{frontend_return_url}?{urlencode(query_params)}", code=302)

            return prepared_response(
                status=(txn_status == "success"),
                status_code="OK" if txn_status == "success" else "BAD_REQUEST",
                message=f"Payment {txn_status}",
                data={"reference": reference, "order_id": paypal_order_id, "status": txn_status},
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if frontend_return_url:
                return redirect(f"{frontend_return_url}?{urlencode({'status': 'error', 'message': str(e)})}", code=302)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Callback error: {str(e)}")


# =====================================================================
# MANUAL VERIFY (authenticated)
# =====================================================================

@paypal_blp.route("/webhooks/payment/paypal/verify", methods=["POST"])
class PayPalVerifyPayment(MethodView):

    @token_required
    @paypal_blp.response(200)
    def post(self):
        log_tag = "[PayPalVerifyPayment][post]"

        try:
            json_data = request.get_json(silent=True) or {}
            order_id = json_data.get("order_id") or json_data.get("reference")

            if not order_id:
                return prepared_response(False, "BAD_REQUEST", "order_id or reference is required")

            success, data, error = get_order(order_id)

            if success:
                return prepared_response(True, "OK", "Verification complete", data=data)
            else:
                return prepared_response(False, "BAD_REQUEST", error or "Verification failed")

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to verify payment", errors=[str(e)])
