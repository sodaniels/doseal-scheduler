# resources/payments/mpesa_webhook_resource.py

"""
M-Pesa (Daraja API) Webhook & Utility Endpoints
==================================================
1. POST /webhooks/payment/mpesa              - STK Push callback (results)
2. POST /webhooks/payment/mpesa/verify       - Manual STK query
3. POST /webhooks/payment/mpesa/status-result    - Transaction status result
4. POST /webhooks/payment/mpesa/status-timeout   - Transaction status timeout
5. POST /webhooks/payment/mpesa/reversal-result  - Reversal result
6. POST /webhooks/payment/mpesa/reversal-timeout - Reversal timeout

M-Pesa is social-facing (collections) — no subscription logic.
"""

import json
import os
from datetime import datetime
from flask import request, jsonify
from flask.views import MethodView
from flask_smorest import Blueprint

from ....models.admin.payment import Payment
from ....constants.payment_methods import PAYMENT_METHODS
from ....utils.logger import Log
from ....utils.json_response import prepared_response
from ....utils.payments.mpesa_utils import parse_stk_callback, query_stk_status
from ....services.email_service import send_payment_confirmation_email
from ....utils.invoice.generate_invoice import generate_invoice_pdf_bytes
from ....utils.media.storage_router import upload_invoice_and_get_asset
from ....decorators.callback_restriction import mpesa_ip_whitelist
from ..admin.admin_business_resource import token_required

mpesa_blp = Blueprint(
    "mpesa_payments",
    __name__,
    description="M-Pesa (Safaricom Daraja) payment webhook and verification handlers",
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


def _process_successful_payment(payment, mpesa_data, client_ip, log_tag):
    """Process a successful M-Pesa payment — mark success, invoice, email."""
    payment_id = str(payment.get("_id"))
    business_id = str(payment.get("business_id") or "")
    reference = payment.get("reference") or payment.get("order_id")

    amount_detail = _parse_amount_detail(payment)
    metadata = _parse_metadata(payment)

    currency_symbol = amount_detail.get("from_currency") or payment.get("currency") or "KES"
    total_from_amount = float(amount_detail.get("total_from_amount") or mpesa_data.get("amount") or payment.get("amount") or 0)
    package_amount = float(amount_detail.get("package_amount") or total_from_amount)

    customer_email = payment.get("customer_email") or ""
    customer_name = payment.get("customer_name") or ""
    customer_phone = mpesa_data.get("phone_number") or payment.get("customer_phone") or ""
    mpesa_receipt = mpesa_data.get("mpesa_receipt") or ""

    purchase_label = metadata.get("purchase_label") or amount_detail.get("purchase_label") or "Payment"
    paid_date = str(datetime.utcnow())

    # Mark success
    Payment.update_status(payment_id, Payment.STATUS_SUCCESS, gateway_transaction_id=mpesa_receipt)
    Payment.update(
        payment_id, business_id=business_id, processing_callback=True,
        completed_at=datetime.utcnow(),
        callback_response=mpesa_data,
        customer_phone=customer_phone,
        updated_at=datetime.utcnow(),
    )

    # Invoice + email
    try:
        invoice_bytes = generate_invoice_pdf_bytes(
            invoice_number=reference, fullname=customer_name, email=customer_email,
            plan_name=purchase_label, currency=currency_symbol, payment_method="mpesa",
            receipt_number=mpesa_receipt or customer_phone, paid_date=paid_date,
            addon_users=0, package_amount=package_amount,
            amount=total_from_amount, total_from_amount=total_from_amount,
        )

        invoice_asset = upload_invoice_and_get_asset(
            business_id=business_id,
            user__id=str(metadata.get("user__id") or ""),
            invoice_number=reference,
            invoice_pdf_bytes=invoice_bytes,
        )

        Payment.update(payment_id, business_id=business_id, invoice_asset=invoice_asset, processing_callback=True)

        if customer_email:
            send_payment_confirmation_email(
                email=customer_email, fullname=customer_name, currency=currency_symbol,
                receipt_number=mpesa_receipt or customer_phone, invoice_number=reference,
                payment_method="mpesa", paid_date=paid_date, plan_name=purchase_label,
                addon_users=0, package_amount=package_amount,
                amount=total_from_amount, total_from_amount=total_from_amount,
                invoice_pdf_bytes=invoice_bytes,
                invoice_url=(invoice_asset or {}).get("url"),
            )
    except Exception as e:
        Log.warning(f"{log_tag} Invoice/email error (ignored): {e}")

    Log.info(f"{log_tag} Payment processed: ref={reference}, receipt={mpesa_receipt}")
    return True, payment_id, None


# =====================================================================
# M-PESA STK PUSH CALLBACK
# =====================================================================

@mpesa_blp.route("/webhooks/payment/mpesa", methods=["POST"])
class MpesaWebhook(MethodView):

    @mpesa_ip_whitelist
    @mpesa_blp.response(200)
    def post(self):
        log_tag = "[mpesa_webhook_resource.py][MpesaWebhook][post]"
        client_ip = request.remote_addr

        try:
            Log.info(f"{log_tag} Received M-Pesa callback ip={client_ip}")

            callback_data = request.get_json(silent=True) or {}
            Log.info(f"{log_tag} Raw callback: {json.dumps(callback_data)[:1000]}")

            # Parse the STK callback
            parsed = parse_stk_callback(callback_data)
            if not parsed:
                Log.warning(f"{log_tag} Failed to parse callback")
                return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200

            checkout_request_id = parsed.get("checkout_request_id")
            result_code = parsed.get("result_code")
            is_success = parsed.get("is_success", False)

            Log.info(
                f"{log_tag} Parsed: checkout_id={checkout_request_id}, "
                f"result_code={result_code}, success={is_success}, "
                f"receipt={parsed.get('mpesa_receipt')}"
            )

            if not checkout_request_id:
                return jsonify({"ResultCode": 0, "ResultDesc": "No CheckoutRequestID"}), 200

            # Find payment by checkout_request_id
            payment = Payment.get_by_checkout_request_id(checkout_request_id)
            if not payment:
                # Try by merchant_request_id
                payment = Payment.get_by_order_id(parsed.get("merchant_request_id"))
            if not payment:
                Log.warning(f"{log_tag} Payment not found: checkout_id={checkout_request_id}")
                return jsonify({"ResultCode": 0, "ResultDesc": "Payment not found"}), 200

            payment_id = str(payment.get("_id"))
            business_id = str(payment.get("business_id") or "")
            current_status = (payment.get("status") or "").strip()

            if current_status in [Payment.STATUS_SUCCESS, Payment.STATUS_FAILED]:
                Log.info(f"{log_tag} Already processed: {current_status}")
                return jsonify({"ResultCode": 0, "ResultDesc": "Already processed"}), 200

            # ── SUCCESS ──
            if is_success:
                Log.info(f"{log_tag} Payment SUCCESS: receipt={parsed.get('mpesa_receipt')}")
                ok, _, error = _process_successful_payment(payment, parsed, client_ip, log_tag)

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Callback processed successfully",
                }), 200

            # ── FAILED / CANCELLED ──
            else:
                result_desc = parsed.get("result_desc") or "Transaction failed"
                Log.warning(f"{log_tag} Payment FAILED: code={result_code}, desc={result_desc}")

                Payment.update_status(
                    payment_id, Payment.STATUS_FAILED,
                    gateway_transaction_id=checkout_request_id,
                    error_message=f"ResultCode {result_code}: {result_desc}",
                )
                Payment.update(
                    payment_id, business_id=business_id, processing_callback=True,
                    failed_at=datetime.utcnow(),
                    callback_response=parsed,
                    updated_at=datetime.utcnow(),
                )

                return jsonify({
                    "ResultCode": 0,
                    "ResultDesc": "Failure callback processed",
                }), 200

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            # M-Pesa expects ResultCode 0 even on our errors
            return jsonify({"ResultCode": 0, "ResultDesc": f"Error: {str(e)}"}), 200


# =====================================================================
# MANUAL VERIFY (STK Query)
# =====================================================================

@mpesa_blp.route("/webhooks/payment/mpesa/verify", methods=["POST"])
class MpesaVerifyPayment(MethodView):

    @token_required
    @mpesa_blp.response(200)
    def post(self):
        log_tag = "[MpesaVerifyPayment][post]"

        try:
            json_data = request.get_json(silent=True) or {}
            checkout_request_id = json_data.get("checkout_request_id")
            reference = json_data.get("reference")

            if not checkout_request_id and reference:
                # Look up checkout_request_id from payment record
                payment = Payment.get_by_reference(reference)
                if payment:
                    checkout_request_id = payment.get("checkout_request_id")

            if not checkout_request_id:
                return prepared_response(False, "BAD_REQUEST", "checkout_request_id or reference is required")

            success, data, error = query_stk_status(checkout_request_id)

            if success:
                return prepared_response(True, "OK", "Query complete", data=data)
            else:
                return prepared_response(False, "BAD_REQUEST", error or "Query failed")

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to verify", errors=[str(e)])


# =====================================================================
# TRANSACTION STATUS RESULT / TIMEOUT
# =====================================================================

@mpesa_blp.route("/webhooks/payment/mpesa/status-result", methods=["POST"])
class MpesaStatusResult(MethodView):

    @mpesa_blp.response(200)
    def post(self):
        log_tag = "[MpesaStatusResult]"
        try:
            data = request.get_json(silent=True) or {}
            Log.info(f"{log_tag} Status result: {json.dumps(data)[:1000]}")
            # Process as needed — typically update payment record
            return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return jsonify({"ResultCode": 0, "ResultDesc": "Error"}), 200


@mpesa_blp.route("/webhooks/payment/mpesa/status-timeout", methods=["POST"])
class MpesaStatusTimeout(MethodView):

    @mpesa_blp.response(200)
    def post(self):
        log_tag = "[MpesaStatusTimeout]"
        try:
            data = request.get_json(silent=True) or {}
            Log.warning(f"{log_tag} Status timeout: {json.dumps(data)[:500]}")
            return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200
        except Exception as e:
            return jsonify({"ResultCode": 0, "ResultDesc": "Error"}), 200


# =====================================================================
# REVERSAL RESULT / TIMEOUT
# =====================================================================

@mpesa_blp.route("/webhooks/payment/mpesa/reversal-result", methods=["POST"])
class MpesaReversalResult(MethodView):

    @mpesa_blp.response(200)
    def post(self):
        log_tag = "[MpesaReversalResult]"
        try:
            data = request.get_json(silent=True) or {}
            Log.info(f"{log_tag} Reversal result: {json.dumps(data)[:1000]}")

            result = data.get("Result", {})
            result_code = result.get("ResultCode")
            transaction_id = result.get("TransactionID")

            if result_code == 0 or result_code == "0":
                Log.info(f"{log_tag} Reversal successful: {transaction_id}")
                # Update payment refund status if needed
            else:
                Log.warning(f"{log_tag} Reversal failed: code={result_code}")

            return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return jsonify({"ResultCode": 0, "ResultDesc": "Error"}), 200


@mpesa_blp.route("/webhooks/payment/mpesa/reversal-timeout", methods=["POST"])
class MpesaReversalTimeout(MethodView):

    @mpesa_blp.response(200)
    def post(self):
        log_tag = "[MpesaReversalTimeout]"
        try:
            data = request.get_json(silent=True) or {}
            Log.warning(f"{log_tag} Reversal timeout: {json.dumps(data)[:500]}")
            return jsonify({"ResultCode": 0, "ResultDesc": "Accepted"}), 200
        except Exception as e:
            return jsonify({"ResultCode": 0, "ResultDesc": "Error"}), 200
