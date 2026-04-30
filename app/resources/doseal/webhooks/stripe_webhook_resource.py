# resources/payments/stripe_webhook_resource.py

"""
Stripe Webhook & Callback Endpoints
=====================================
1. POST /payments/stripe/webhook   - Receives Stripe event notifications
2. GET  /payments/stripe/callback  - Customer redirect after Checkout Session
3. POST /payments/stripe/verify    - Manual verification by reference or ID
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
from ....utils.payments.stripe_utils import (
    verify_webhook_signature,
    retrieve_payment_intent,
    retrieve_checkout_session,
)
from ....services.email_service import send_payment_confirmation_email
from ....utils.invoice.generate_invoice import generate_invoice_pdf_bytes
from ....utils.media.storage_router import upload_invoice_and_get_asset
from ..admin.admin_business_resource import token_required
from ....decorators.callback_restriction import stripe_ip_whitelist


stripe_blp = Blueprint(
    "stripe_payments",
    __name__,
    description="Stripe payment webhook, callback, and verification handlers",
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


def _record_discount_redemption(metadata, stripe_metadata, business_id, user__id, subscription_id, log_tag):
    discount_code = (metadata or {}).get("discount_code") or (stripe_metadata or {}).get("discount_code")
    discount_id = (metadata or {}).get("discount_id") or (stripe_metadata or {}).get("discount_id")
    discount_amount_saved = float((metadata or {}).get("discount_amount") or (stripe_metadata or {}).get("discount_amount") or 0)

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
            Log.warning(f"{log_tag} Failed to record discount: {e}")


def _process_referral_commission(business_id, total_from_amount, package_amount, reference, currency_symbol, plan_name, billing_period, log_tag):
    try:
        from ....models.admin.promo_model import CommissionService
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
    except Exception as e:
        Log.error(f"{log_tag} Commission EXCEPTION: {e}", exc_info=True)


def _create_or_renew_subscription(
    *, business_id, package_id, old_package_id, user_id, user__id,
    billing_period, reference, amount_detail, addon_users, client_ip, log_tag,
):
    if not package_id:
        return False, None, "package_id is None"
    if not user__id:
        return False, None, "user__id is None"

    if not old_package_id:
        try:
            success, subscription_id, error = SubscriptionService.create_subscription(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                package_id=str(package_id),
                payment_method=PAYMENT_METHODS.get("STRIPE", "stripe"),
                payment_reference=reference,
                payment_done=True,
                amount_detail=amount_detail,
                addon_users=addon_users,
            )
        except Exception as e:
            return False, None, str(e)

        if success:
            try:
                Business.update_account_status_by_business_id(business_id, client_ip, "subscribed_to_package", True)
            except Exception:
                pass

        return success, subscription_id, error
    else:
        try:
            success, subscription_id, error = SubscriptionService.apply_or_renew_from_payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                package_id=str(package_id),
                billing_period=billing_period,
                payment_method=PAYMENT_METHODS.get("STRIPE", "stripe"),
                payment_reference=reference,
            )
        except Exception as e:
            return False, None, str(e)

        return success, subscription_id, error

def _is_system_billing_payment(purchase_type):
    """System billing (subscription/storage) vs social collection (donation/offering/event)."""
    return purchase_type in ("subscription", "storage_addon")


# =====================================================================
# STRIPE WEBHOOK
# =====================================================================
@stripe_blp.route("/webhooks/payment/stripe", methods=["POST"])
class StripeWebhook(MethodView):

    @stripe_ip_whitelist
    @stripe_blp.response(200)
    def post(self):
        reference = None
        log_tag = "[stripe_webhook_resource.py][StripeWebhook][post]"
        client_ip = request.remote_addr

        try:
            Log.info(f"{log_tag} Received Stripe webhook ip={client_ip}")

            sig_header = request.headers.get("Stripe-Signature", "")
            raw_body = request.get_data()

            if not verify_webhook_signature(raw_body, sig_header):
                Log.warning(f"{log_tag} Invalid webhook signature")
                return jsonify({"error": "Invalid signature"}), 401

            event_payload = request.get_json(silent=True) or {}
            event_type = event_payload.get("type", "")
            event_data = event_payload.get("data", {}).get("object", {})

            Log.info(f"{log_tag} Event: {event_type}")

            if event_type == "checkout.session.completed":
                return self._handle_checkout_completed(event_data, client_ip, log_tag)
            elif event_type == "payment_intent.succeeded":
                return self._handle_payment_succeeded(event_data, client_ip, log_tag)
            elif event_type == "payment_intent.payment_failed":
                return self._handle_payment_failed(event_data, log_tag)
            elif event_type == "charge.refunded":
                return self._handle_charge_refunded(event_data, log_tag)

            Log.info(f"{log_tag} Event {event_type} acknowledged (no handler)")
            return jsonify({"received": True}), 200

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return jsonify({"error": str(e)}), 200

    def _handle_checkout_completed(self, session, client_ip, log_tag):
        """Handle checkout.session.completed event."""
        session_id = session.get("id")
        payment_intent_id = session.get("payment_intent")
        stripe_metadata = session.get("metadata", {}) or {}
        reference = stripe_metadata.get("reference")

        Log.info(f"{log_tag} Checkout completed: session={session_id}, pi={payment_intent_id}, ref={reference}")

        if not reference:
            Log.warning(f"{log_tag} No reference in metadata")
            return jsonify({"received": True, "message": "No reference"}), 200

        payment = Payment.get_by_reference(reference) or Payment.get_by_order_id(reference)
        if not payment:
            Log.error(f"{log_tag} Payment not found ref={reference}")
            return jsonify({"received": True, "message": "Payment not found"}), 200

        payment_id = str(payment.get("_id"))
        business_id = str(payment.get("business_id") or "")
        current_status = (payment.get("status") or "").strip()

        if current_status in [Payment.STATUS_SUCCESS, Payment.STATUS_FAILED]:
            return jsonify({"received": True, "message": "Already processed"}), 200

        # Extract data
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

        customer_email = session.get("customer_email") or session.get("customer_details", {}).get("email") or payment.get("customer_email") or ""
        customer_name = session.get("customer_details", {}).get("name") or payment.get("customer_name") or ""
        customer_phone = payment.get("customer_phone") or ""

        package_id = metadata.get("package_id") or stripe_metadata.get("package_id") or payment.get("package_id")
        old_package_id = metadata.get("old_package_id") or stripe_metadata.get("old_package_id")
        billing_period = metadata.get("billing_period") or stripe_metadata.get("billing_period") or "monthly"
        user_id = metadata.get("user_id") or stripe_metadata.get("user_id") or payment.get("user_id")
        user__id = metadata.get("user__id") or stripe_metadata.get("user__id") or payment.get("user__id")

        purchase_type = (
            metadata.get("purchase_type")
            or stripe_metadata.get("purchase_type")
            or amount_detail.get("purchase_type")
            or "subscription"
        )
        storage_addon_gb = (
            metadata.get("storage_addon_gb")
            or stripe_metadata.get("storage_addon_gb")
            or amount_detail.get("storage_addon_gb")
        )

        package = Package.get_by_id(str(package_id)) if package_id else {}
        package = package or {}
        plan_name = (
            f"{storage_addon_gb}GB Storage Add-on"
            if purchase_type == "storage_addon"
            else (package.get("name") or metadata.get("purchase_label") or "Payment")
        )
        paid_date = str(datetime.utcnow())
        invoice_number = payment.get("reference") or reference

        # ── Mark success (always) ──
        Payment.update_status(payment_id, Payment.STATUS_SUCCESS, gateway_transaction_id=payment_intent_id or session_id)
        Payment.update(
            payment_id, business_id=business_id, processing_callback=True,
            completed_at=datetime.utcnow(),
            callback_response=session,
            customer_email=customer_email,
            customer_name=customer_name,
            updated_at=datetime.utcnow(),
        )

        # ── Invoice + email (always) ──
        try:
            invoice_bytes = generate_invoice_pdf_bytes(
                invoice_number=invoice_number, fullname=customer_name, email=customer_email,
                plan_name=plan_name, currency=currency_symbol, payment_method="stripe",
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
                payment_method="stripe", paid_date=paid_date, plan_name=plan_name,
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
                            return jsonify({"received": True, "message": "Storage addon failed"}), 200
                except Exception as e:
                    Log.error(f"{log_tag} Storage addon error: {e}", exc_info=True)
                    Payment.update(
                        payment_id, business_id=business_id, processing_callback=True,
                        notes=f"Payment OK but storage addon error: {e}",
                    )
                    return jsonify({"received": True, "message": f"Storage addon error: {e}"}), 200

            else:
                # Subscription
                if not package_id or not user__id:
                    Payment.update(
                        payment_id, business_id=business_id, processing_callback=True,
                        notes="Payment OK but missing package_id or user__id",
                    )
                    return jsonify({"received": True, "message": "Missing package_id or user__id"}), 200

                if not old_package_id:
                    success, subscription_id, error = SubscriptionService.create_subscription(
                        business_id=business_id,
                        user_id=user_id,
                        user__id=user__id,
                        package_id=str(package_id),
                        payment_method=PAYMENT_METHODS.get("STRIPE", "stripe"),
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
                        return jsonify({"received": True, "message": f"Subscription failed: {error}"}), 200

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
                        payment_method=PAYMENT_METHODS.get("STRIPE", "stripe"),
                        payment_reference=reference,
                    )

                    if not success:
                        Payment.update(
                            payment_id, business_id=business_id, processing_callback=True,
                            notes=f"Payment OK but renewal failed: {error}",
                        )
                        Log.info(f"{log_tag} Payment OK but subscription failed: {error}")
                        return jsonify({"received": True, "message": f"Renewal failed: {error}"}), 200

            # Discount + commission (system billing only)
            _record_discount_redemption(metadata, stripe_metadata, business_id, user__id, subscription_id, log_tag)
            _process_referral_commission(
                business_id, total_from_amount, package_amount,
                reference, currency_symbol, plan_name, billing_period, log_tag,
            )

        # ══════════════════════════════════════════════
        # CHURCH COLLECTION (donation, offering, event)
        # ══════════════════════════════════════════════
        else:
            Log.info(f"{log_tag} Church collection: purchase_type={purchase_type}, ref={reference}")

        return jsonify({
            "received": True,
            "payment_status": "success",
            "purchase_type": purchase_type,
            "subscription_id": subscription_id,
            "storage": storage_result,
        }), 200

    def _handle_payment_succeeded(self, pi_data, client_ip, log_tag):
        """Handle payment_intent.succeeded — fallback if checkout event doesn't fire."""
        pi_id = pi_data.get("id")
        stripe_metadata = pi_data.get("metadata", {}) or {}
        reference = stripe_metadata.get("reference")

        Log.info(f"{log_tag} PaymentIntent succeeded: {pi_id}, ref={reference}")

        if not reference:
            return jsonify({"received": True}), 200

        payment = Payment.get_by_reference(reference) or Payment.get_by_order_id(reference)
        if not payment:
            return jsonify({"received": True, "message": "Payment not found"}), 200

        current_status = (payment.get("status") or "").strip()
        if current_status == Payment.STATUS_SUCCESS:
            Log.info(f"{log_tag} Already processed by checkout event")
            return jsonify({"received": True, "message": "Already processed"}), 200

        Payment.update_status(str(payment["_id"]), Payment.STATUS_SUCCESS, gateway_transaction_id=pi_id)
        Payment.update(
            str(payment["_id"]), business_id=str(payment.get("business_id") or ""),
            processing_callback=True, completed_at=datetime.utcnow(),
            callback_response=pi_data,
        )

        Log.info(f"{log_tag} PaymentIntent marked SUCCESS")
        return jsonify({"received": True}), 200

    def _handle_payment_failed(self, pi_data, log_tag):
        """Handle payment_intent.payment_failed."""
        pi_id = pi_data.get("id")
        stripe_metadata = pi_data.get("metadata", {}) or {}
        reference = stripe_metadata.get("reference")
        error_msg = (pi_data.get("last_payment_error") or {}).get("message") or "Payment failed"

        Log.warning(f"{log_tag} PaymentIntent failed: {pi_id}, ref={reference}, error={error_msg}")

        if not reference:
            return jsonify({"received": True}), 200

        payment = Payment.get_by_reference(reference) or Payment.get_by_order_id(reference)
        if payment:
            Payment.update_status(str(payment["_id"]), Payment.STATUS_FAILED, gateway_transaction_id=pi_id, error_message=error_msg)

        return jsonify({"received": True}), 200

    def _handle_charge_refunded(self, charge_data, log_tag):
        """Handle charge.refunded — update payment record."""
        pi_id = charge_data.get("payment_intent")
        refund_amount = charge_data.get("amount_refunded", 0) / 100

        Log.info(f"{log_tag} Charge refunded: pi={pi_id}, amount={refund_amount}")

        if pi_id:
            stripe_metadata = charge_data.get("metadata", {}) or {}
            reference = stripe_metadata.get("reference")

            if reference:
                payment = Payment.get_by_reference(reference)
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
                        Log.warning(f"{log_tag} Failed to update refund status: {e}")

        return jsonify({"received": True}), 200

# =====================================================================
# STRIPE CALLBACK (customer redirect after Checkout Session)
# =====================================================================

@stripe_blp.route("/webhooks/payment/stripe/callback", methods=["GET"])
class StripeCallback(MethodView):

    def get(self):
        log_tag = "[stripe_webhook_resource.py][StripeCallback][get]"
        frontend_return_url = os.getenv("PAYMENT_FRONT_END_RETURN_URL", "")

        try:
            session_id = request.args.get("session_id")
            reference = request.args.get("reference")
            client_ip = request.remote_addr

            Log.info(f"{log_tag} Callback session_id={session_id} ref={reference}")

            if not session_id and not reference:
                if frontend_return_url:
                    return redirect(f"{frontend_return_url}?{urlencode({'status': 'error', 'message': 'Missing session or reference'})}", code=302)
                return prepared_response(False, "BAD_REQUEST", "Missing session_id or reference")

            # Retrieve session from Stripe
            txn_status = "unknown"
            verify_data = {}

            if session_id:
                success, session_data, error = retrieve_checkout_session(session_id)
                if success:
                    payment_status = session_data.get("payment_status", "")
                    txn_status = "success" if payment_status == "paid" else payment_status
                    verify_data = session_data
                    reference = reference or (session_data.get("metadata") or {}).get("reference")
                else:
                    Log.error(f"{log_tag} Session retrieval failed: {error}")

            # Find payment
            payment = None
            if reference:
                payment = Payment.get_by_reference(reference) or Payment.get_by_order_id(reference)

            if payment:
                payment_id = str(payment.get("_id"))
                business_id = str(payment.get("business_id") or "")
                current_status = (payment.get("status") or "").strip()

                metadata = _parse_metadata(payment)
                callback_return_url = metadata.get("return_url")
                if callback_return_url:
                    frontend_return_url = callback_return_url

                if current_status not in [Payment.STATUS_SUCCESS, Payment.STATUS_FAILED]:
                    if txn_status == "success":
                        Payment.update_status(payment_id, Payment.STATUS_SUCCESS, gateway_transaction_id=session_id)
                        Payment.update(
                            payment_id, business_id=business_id, processing_callback=True,
                            callback_response=verify_data, completed_at=datetime.utcnow(),
                        )

                        # Subscription (webhook will likely handle, this is fallback)
                        try:
                            amount_detail = _parse_amount_detail(payment)
                            stripe_meta = verify_data.get("metadata", {}) or {}

                            package_id = metadata.get("package_id") or stripe_meta.get("package_id") or payment.get("package_id")
                            user_id = metadata.get("user_id") or stripe_meta.get("user_id") or payment.get("user_id")
                            user__id = metadata.get("user__id") or stripe_meta.get("user__id") or payment.get("user__id")
                            billing_period = metadata.get("billing_period") or "monthly"
                            addon_users = int(amount_detail.get("addon_users") or 0)

                            if package_id and user__id:
                                success, sub_id, error = _create_or_renew_subscription(
                                    business_id=business_id, package_id=package_id,
                                    old_package_id=metadata.get("old_package_id"),
                                    user_id=user_id, user__id=user__id,
                                    billing_period=billing_period, reference=reference,
                                    amount_detail=amount_detail, addon_users=addon_users,
                                    client_ip=client_ip, log_tag=log_tag,
                                )
                                Log.info(f"{log_tag} Callback subscription: success={success}, sub_id={sub_id}")
                        except Exception as e:
                            Log.warning(f"{log_tag} Callback subscription error: {e}")

                    elif txn_status in ("unpaid", "no_payment_required"):
                        pass  # Will be handled by webhook
                else:
                    Log.info(f"{log_tag} Already processed")

            # Redirect
            if frontend_return_url:
                query_params = {
                    "status": txn_status,
                    "reference": reference or "",
                    "session_id": session_id or "",
                    "payment_method": "stripe",
                    "status_code": "200" if txn_status == "success" else "400",
                }
                return redirect(f"{frontend_return_url}?{urlencode(query_params)}", code=302)

            return prepared_response(
                status=(txn_status == "success"),
                status_code="OK" if txn_status == "success" else "BAD_REQUEST",
                message=f"Payment {txn_status}",
                data={"reference": reference, "status": txn_status},
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            if frontend_return_url:
                return redirect(f"{frontend_return_url}?{urlencode({'status': 'error', 'message': str(e)})}", code=302)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Callback error: {str(e)}")


# =====================================================================
# MANUAL VERIFY (authenticated)
# =====================================================================

@stripe_blp.route("/payments/stripe/verify", methods=["POST"])
class StripeVerifyPayment(MethodView):

    @token_required
    @stripe_blp.response(200)
    def post(self):
        log_tag = "[StripeVerifyPayment][post]"

        try:
            json_data = request.get_json(silent=True) or {}
            reference = json_data.get("reference")
            session_id = json_data.get("session_id")
            payment_intent_id = json_data.get("payment_intent_id")

            identifier = payment_intent_id or session_id or reference
            if not identifier:
                return prepared_response(False, "BAD_REQUEST", "Provide reference, session_id, or payment_intent_id")

            if payment_intent_id:
                success, data, error = retrieve_payment_intent(payment_intent_id)
            elif session_id:
                success, data, error = retrieve_checkout_session(session_id)
            else:
                from ....utils.payments.stripe_utils import verify_transaction
                success, data, error = verify_transaction(reference)

            if success:
                return prepared_response(True, "OK", "Verification complete", data=data)
            else:
                return prepared_response(False, "BAD_REQUEST", error or "Verification failed")

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to verify payment", errors=[str(e)])
