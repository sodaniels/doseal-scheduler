# resources/payments/flutterwave_webhook_resource.py

"""
Flutterwave Webhook & Callback Endpoints
===========================================
1. POST /webhooks/payment/flutterwave             - Receives Flutterwave events
2. GET  /webhooks/payment/flutterwave/callback    - Customer redirect after checkout
3. POST /webhooks/payment/flutterwave/verify      - Manual verification
"""

import json
import os
from datetime import datetime
from urllib.parse import urlencode
from flask import request, g, jsonify, redirect
from flask.views import MethodView
from flask_smorest import Blueprint

from ....models.admin.payment import Payment
from ....constants.payment_methods import PAYMENT_METHODS
from ....utils.logger import Log
from ....utils.json_response import prepared_response
from ....utils.payments.flutterwave_utils import (
    verify_webhook_signature,
    verify_transaction,
    verify_by_tx_ref,
)
from ....services.email_service import send_payment_confirmation_email
from ....utils.invoice.generate_invoice import generate_invoice_pdf_bytes
from ....utils.media.storage_router import upload_invoice_and_get_asset
from ....decorators.callback_restriction import flutterwave_ip_whitelist
from ..admin.admin_business_resource import token_required

flutterwave_blp = Blueprint(
    "flutterwave_payments",
    __name__,
    description="Flutterwave payment webhook, callback, and verification handlers",
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


def _process_successful_payment(payment, flw_data, client_ip, log_tag):
    """Process a successful Flutterwave payment — mark success, invoice, email. No subscription logic."""
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

    local_currency = amount_detail.get("to_currency")
    local_amount = float(amount_detail.get("total_to_amount") or 0)
    exchange_rate_val = float(amount_detail.get("exchange_rate") or 0)
    show_local = bool(local_currency and local_currency != currency_symbol and local_amount > 0)

    customer_email = flw_data.get("customer_email") or payment.get("customer_email") or ""
    customer_name = flw_data.get("customer_name") or payment.get("customer_name") or ""
    customer_phone = flw_data.get("customer_phone") or payment.get("customer_phone") or ""

    gateway_txn_id = str(flw_data.get("transaction_id") or flw_data.get("flw_ref") or "")

    purchase_label = metadata.get("purchase_label") or amount_detail.get("purchase_label") or "Payment"
    paid_date = str(datetime.utcnow())

    # Mark success
    Payment.update_status(payment_id, Payment.STATUS_SUCCESS, gateway_transaction_id=gateway_txn_id)
    Payment.update(
        payment_id, business_id=business_id, processing_callback=True,
        completed_at=datetime.utcnow(),
        callback_response=flw_data.get("raw", flw_data),
        customer_email=customer_email,
        customer_name=customer_name,
        updated_at=datetime.utcnow(),
    )

    # Invoice + email
    try:
        invoice_bytes = generate_invoice_pdf_bytes(
            invoice_number=reference, fullname=customer_name, email=customer_email,
            plan_name=purchase_label, currency=currency_symbol, payment_method="flutterwave",
            receipt_number=customer_phone, paid_date=paid_date,
            addon_users=addon_users, package_amount=package_amount,
            amount=total_from_amount, total_from_amount=original_total,
            local_currency=local_currency if show_local else None,
            local_amount=local_amount if show_local else None,
            exchange_rate=exchange_rate_val if show_local else None,
        )

        invoice_asset = upload_invoice_and_get_asset(
            business_id=business_id,
            user__id=str(metadata.get("user__id") or ""),
            invoice_number=reference,
            invoice_pdf_bytes=invoice_bytes,
        )

        Payment.update(payment_id, business_id=business_id, invoice_asset=invoice_asset, processing_callback=True)

        send_payment_confirmation_email(
            email=customer_email, fullname=customer_name, currency=currency_symbol,
            receipt_number=customer_phone, invoice_number=reference,
            payment_method="flutterwave", paid_date=paid_date, plan_name=purchase_label,
            addon_users=addon_users, package_amount=package_amount,
            amount=total_from_amount, total_from_amount=original_total,
            invoice_pdf_bytes=invoice_bytes,
            invoice_url=(invoice_asset or {}).get("url"),
            local_currency=local_currency if show_local else None,
            local_amount=local_amount if show_local else None,
            exchange_rate=exchange_rate_val if show_local else None,
        )
    except Exception as e:
        Log.warning(f"{log_tag} Invoice/email error (ignored): {e}")

    Log.info(f"{log_tag} Payment processed successfully: ref={reference}, gateway_txn={gateway_txn_id}")
    return True, payment_id, None


# =====================================================================
# FLUTTERWAVE WEBHOOK
# =====================================================================

@flutterwave_blp.route("/webhooks/payment/flutterwave", methods=["POST"])
class FlutterwaveWebhook(MethodView):

    @flutterwave_ip_whitelist
    @flutterwave_blp.response(200)
    def post(self):
        log_tag = "[flutterwave_webhook_resource.py][FlutterwaveWebhook][post]"
        client_ip = request.remote_addr

        try:
            Log.info(f"{log_tag} Received Flutterwave webhook ip={client_ip}")

            # Signature verification via verif-hash header
            verif_hash = (
                request.headers.get("verif-hash", "")
                or request.headers.get("Verif-Hash", "")
                or request.headers.get("VERIF-HASH", "")
            )
            if not verify_webhook_signature(verif_hash):
                Log.warning(f"{log_tag} Invalid webhook signature")
                return jsonify({"error": "Invalid signature"}), 401

            payload = request.get_json(silent=True) or {}
            event_type = payload.get("event") or ""
            data = payload.get("data", {})

            tx_ref = data.get("tx_ref")
            flw_ref = data.get("flw_ref")
            transaction_id = data.get("id")
            status = (data.get("status") or "").lower()

            Log.info(f"{log_tag} Event: {event_type}, tx_ref={tx_ref}, status={status}, id={transaction_id}")

            if not tx_ref:
                return jsonify({"received": True, "message": "No tx_ref"}), 200

            # Find our payment record
            payment = Payment.get_by_reference(tx_ref) or Payment.get_by_order_id(tx_ref)
            if not payment:
                Log.warning(f"{log_tag} Payment not found tx_ref={tx_ref}")
                return jsonify({"received": True, "message": "Payment not found"}), 200

            payment_id = str(payment.get("_id"))
            business_id = str(payment.get("business_id") or "")
            current_status = (payment.get("status") or "").strip()

            if current_status in [Payment.STATUS_SUCCESS, Payment.STATUS_FAILED]:
                Log.info(f"{log_tag} Already processed: {current_status}")
                return jsonify({"received": True, "message": "Already processed"}), 200

            # ── charge.completed ──
            if event_type == "charge.completed" and status == "successful":
                # Verify with Flutterwave before processing
                if transaction_id:
                    verify_ok, verify_data, verify_error = verify_transaction(transaction_id)
                    if not verify_ok:
                        Log.error(f"{log_tag} Verification failed: {verify_error}")
                        return jsonify({"received": True, "message": "Verification failed"}), 200

                    if verify_data.get("status") != "successful":
                        Log.error(f"{log_tag} Verify status mismatch: {verify_data.get('status')}")
                        return jsonify({"received": True, "message": "Status mismatch"}), 200

                    # Amount check
                    amount_detail = _parse_amount_detail(payment)
                    expected = float(amount_detail.get("total_to_amount") or amount_detail.get("total_from_amount") or 0)
                    actual = float(verify_data.get("amount") or 0)

                    if expected > 0 and abs(actual - expected) > 1:
                        Log.error(f"{log_tag} Amount mismatch: expected={expected}, got={actual}")
                        Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=f"Amount mismatch: expected {expected}, got {actual}")
                        return jsonify({"received": True, "message": "Amount mismatch"}), 200

                    flw_data = verify_data
                else:
                    customer = data.get("customer", {})
                    flw_data = {
                        "transaction_id": transaction_id,
                        "tx_ref": tx_ref,
                        "flw_ref": flw_ref,
                        "status": status,
                        "customer_email": customer.get("email"),
                        "customer_name": customer.get("name"),
                        "customer_phone": customer.get("phone_number"),
                        "raw": data,
                    }

                ok, sub_id, error = _process_successful_payment(payment, flw_data, client_ip, log_tag)

                return jsonify({
                    "received": True,
                    "payment_status": "success" if ok else "subscription_failed",
                    "subscription_id": sub_id,
                }), 200

            # ── charge.failed ──
            elif status in ("failed", "cancelled"):
                error_msg = data.get("processor_response") or "Payment failed"
                Log.warning(f"{log_tag} Payment failed: {error_msg}")
                Payment.update_status(payment_id, Payment.STATUS_FAILED, gateway_transaction_id=str(transaction_id or ""), error_message=error_msg)
                return jsonify({"received": True, "payment_status": "failed"}), 200

            Log.info(f"{log_tag} Event {event_type} status={status} — acknowledged")
            return jsonify({"received": True}), 200

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return jsonify({"error": str(e)}), 200


# =====================================================================
# FLUTTERWAVE CALLBACK (customer redirect)
# =====================================================================

@flutterwave_blp.route("/webhooks/payment/flutterwave/callback", methods=["GET"])
class FlutterwaveCallback(MethodView):

    def get(self):
        log_tag = "[flutterwave_webhook_resource.py][FlutterwaveCallback][get]"
        frontend_return_url = os.getenv("PAYMENT_FRONT_END_RETURN_URL", "")

        try:
            # Flutterwave appends: ?status=successful&tx_ref=XXX&transaction_id=123
            flw_status = request.args.get("status", "")
            tx_ref = request.args.get("tx_ref") or request.args.get("reference")
            transaction_id = request.args.get("transaction_id")
            client_ip = request.remote_addr

            Log.info(f"{log_tag} Callback status={flw_status} tx_ref={tx_ref} txn_id={transaction_id}")

            if not tx_ref and not transaction_id:
                if frontend_return_url:
                    return redirect(f"{frontend_return_url}?{urlencode({'status': 'error', 'message': 'Missing transaction reference'})}", code=302)
                return prepared_response(False, "BAD_REQUEST", "Missing tx_ref or transaction_id")

            # Find payment
            payment = None
            if tx_ref:
                payment = Payment.get_by_reference(tx_ref) or Payment.get_by_order_id(tx_ref)

            if payment:
                metadata = _parse_metadata(payment)
                callback_return_url = metadata.get("return_url")
                if callback_return_url:
                    frontend_return_url = callback_return_url

            current_status = (payment.get("status") or "").strip() if payment else ""

            # Already processed
            if current_status == Payment.STATUS_SUCCESS:
                Log.info(f"{log_tag} Already processed by webhook")
                txn_status = "success"

            elif flw_status == "successful" and transaction_id:
                # Verify and process
                verify_ok, verify_data, verify_error = verify_transaction(transaction_id)

                if verify_ok and verify_data.get("status") == "successful" and payment:
                    ok, sub_id, sub_error = _process_successful_payment(payment, verify_data, client_ip, log_tag)
                    txn_status = "success" if ok else "failed"
                    Log.info(f"{log_tag} Callback processing: ok={ok}, sub_id={sub_id}, error={sub_error}")
                elif verify_ok and verify_data.get("status") == "successful" and not payment:
                    txn_status = "success"
                    Log.warning(f"{log_tag} Verified but no payment record")
                else:
                    txn_status = "failed"
                    if payment:
                        Payment.update_status(
                            str(payment["_id"]), Payment.STATUS_FAILED,
                            error_message=verify_error or "Verification failed",
                        )

            elif flw_status == "cancelled":
                txn_status = "cancelled"
                if payment:
                    Payment.update_status(str(payment["_id"]), Payment.STATUS_FAILED, error_message="Customer cancelled")

            else:
                txn_status = flw_status or "unknown"

            # Redirect
            if frontend_return_url:
                query_params = {
                    "status": txn_status,
                    "reference": tx_ref or "",
                    "transaction_id": transaction_id or "",
                    "payment_method": "flutterwave",
                    "status_code": "200" if txn_status == "success" else "400",
                }
                if txn_status not in ("success",):
                    query_params["message"] = f"Payment {txn_status}"

                return redirect(f"{frontend_return_url}?{urlencode(query_params)}", code=302)

            return prepared_response(
                status=(txn_status == "success"),
                status_code="OK" if txn_status == "success" else "BAD_REQUEST",
                message=f"Payment {txn_status}",
                data={"reference": tx_ref, "transaction_id": transaction_id, "status": txn_status},
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if frontend_return_url:
                return redirect(f"{frontend_return_url}?{urlencode({'status': 'error', 'message': str(e)})}", code=302)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Callback error: {str(e)}")


# =====================================================================
# MANUAL VERIFY (authenticated)
# =====================================================================

@flutterwave_blp.route("/webhooks/payment/flutterwave/verify", methods=["POST"])
class FlutterwaveVerifyPayment(MethodView):

    @token_required
    @flutterwave_blp.response(200)
    def post(self):
        log_tag = "[FlutterwaveVerifyPayment][post]"

        try:
            json_data = request.get_json(silent=True) or {}
            transaction_id = json_data.get("transaction_id")
            tx_ref = json_data.get("tx_ref") or json_data.get("reference")

            if transaction_id:
                success, data, error = verify_transaction(transaction_id)
            elif tx_ref:
                success, data, error = verify_by_tx_ref(tx_ref)
            else:
                return prepared_response(False, "BAD_REQUEST", "Provide transaction_id or tx_ref")

            if success:
                return prepared_response(True, "OK", "Verification complete", data=data)
            else:
                return prepared_response(False, "BAD_REQUEST", error or "Verification failed")

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to verify", errors=[str(e)])
