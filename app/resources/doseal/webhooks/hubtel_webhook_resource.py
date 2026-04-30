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
from ....utils.helpers import (
    build_receipt_sms, _is_system_billing_payment
)
from ....utils.invoice.generate_invoice import generate_invoice_pdf_bytes
from ....utils.json_response import prepared_response
from ....utils.logger import Log
from ....utils.media.storage_router import upload_invoice_and_get_asset
from ....utils.payments.hubtel_utils import (
    verify_hubtel_callback,
    parse_hubtel_callback,
    validate_hubtel_callback_amount,
    get_hubtel_response_code_message,
)
from ....services.email_service import send_payment_confirmation_email
from ....decorators.callback_restriction import hubtel_ip_whitelist


hubtel_blp = Blueprint(
    "hubtel_webhooks",
    __name__,
    description="Hubtel webhooks and callbacks",
)


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


def _record_discount_redemption(metadata, business_id, user__id, subscription_id, log_tag):
    discount_id = (metadata or {}).get("discount_id")
    discount_amount_saved = float((metadata or {}).get("discount_amount") or 0)

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
        except Exception as e:
            Log.warning(f"{log_tag} Failed to record discount redemption: {e}")


def _process_storage_addon_purchase(payment, metadata, amount_detail, business_id, user__id, reference, log_tag):
    try:
        from ....models.social.form_model import StorageQuota

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


@hubtel_blp.route("/webhooks/payment/hubtel", methods=["POST"])
class HubtelWebhook(MethodView):

    @hubtel_ip_whitelist
    def post(self):
        client_reference = None
        log_tag = "[hubtel_webhook_resource.py][HubtelWebhook][post]"
        client_ip = request.remote_addr

        try:
            data = request.get_json(silent=True) or {}

            Log.info(f"{log_tag} Received Hubtel webhook ip={client_ip}")
            Log.info(f"{log_tag} Callback Transaction: {data}")

            if not verify_hubtel_callback(data):
                return jsonify({"code": 401, "message": "Invalid callback structure"}), 401

            parsed = parse_hubtel_callback(data)
            if not parsed:
                return jsonify({"code": 400, "message": "Failed to parse callback"}), 400

            client_reference = parsed.get("client_reference")
            if not client_reference:
                return jsonify({"code": 400, "message": "Missing client_reference"}), 400

            payment = Payment.get_by_order_id(client_reference)
            if not payment:
                return jsonify({"code": 404, "message": "Payment not found"}), 404

            payment_id = str(payment.get("_id"))
            business_id = str(payment.get("business_id") or "")
            current_status = (payment.get("status") or "").strip()

            if current_status in [Payment.STATUS_SUCCESS, Payment.STATUS_FAILED]:
                return jsonify({"code": 200, "message": "Already processed"}), 200

            if parsed.get("amount") is not None:
                try:
                    validate_hubtel_callback_amount(parsed["amount"], payment.get("amount"))
                except Exception:
                    pass

            update_data = {
                "checkout_request_id": parsed.get("checkout_id") or payment.get("checkout_request_id"),
                "customer_phone": parsed.get("customer_phone") or payment.get("customer_phone"),
                "customer_name": parsed.get("customer_name") or payment.get("customer_name"),
                "customer_email": parsed.get("customer_email") or payment.get("customer_email"),
                "updated_at": datetime.utcnow(),
            }

            amount_detail = _parse_amount_detail(payment)
            metadata = _parse_metadata(payment)

            addon_users = int(amount_detail.get("addon_users") or 0)
            package_amount = float(amount_detail.get("package_amount") or 0)
            currency_symbol = amount_detail.get("from_currency") or payment.get("currency") or "USD"
            total_from_amount = float(amount_detail.get("total_from_amount") or 0)

            purchase_type = _extract_purchase_type(metadata, {}, amount_detail)
            storage_addon_gb = _extract_storage_addon_gb(metadata, {}, amount_detail)

            if parsed.get("payment_details") is not None:
                existing_metadata = _parse_metadata(payment)
                existing_metadata["payment_details"] = parsed.get("payment_details")
                existing_metadata["sales_invoice_id"] = parsed.get("sales_invoice_id")
                existing_metadata["charges"] = parsed.get("charges")
                update_data["metadata"] = existing_metadata
                update_data["callback_response"] = data

            # ══════════════════════════════════════════════
            # PAYMENT SUCCESS
            # ══════════════════════════════════════════════
            if parsed.get("is_success") is True:
                Payment.update_status(
                    payment_id,
                    Payment.STATUS_SUCCESS,
                    gateway_transaction_id=parsed.get("transaction_id"),
                )
                Payment.update(
                    payment_id,
                    business_id=business_id,
                    processing_callback=True,
                    completed_at=datetime.utcnow(),
                    **update_data,
                )

                package_id = metadata.get("package_id") or payment.get("package_id")
                old_package_id = metadata.get("old_package_id") or payment.get("old_package_id")
                billing_period = metadata.get("billing_period") or amount_detail.get("billing_period") or "monthly"
                user_id = metadata.get("user_id") or payment.get("user_id")
                user__id = metadata.get("user__id") or payment.get("user__id")
                payment_reference = client_reference

                package = Package.get_by_id(str(package_id)) if package_id else {}
                package = package or {}
                plan_name = (
                    f"{storage_addon_gb}GB Storage Add-on"
                    if purchase_type == "storage_addon"
                    else (package.get("name") or metadata.get("purchase_label") or "Payment")
                )

                # ── Invoice + Email (always) ──
                try:
                    invoice_number = payment.get("reference") or client_reference
                    user__id_for_upload = str(user__id or payment.get("user__id") or "")

                    invoice_bytes = generate_invoice_pdf_bytes(
                        invoice_number=invoice_number,
                        fullname=payment.get("customer_name") or "",
                        email=payment.get("customer_email") or "",
                        plan_name=plan_name,
                        amount=float(total_from_amount or package_amount or 0),
                        currency=str(currency_symbol or ""),
                        payment_method=str(payment.get("payment_method") or "hubtel"),
                        receipt_number=str(payment.get("customer_phone") or ""),
                        paid_date=str(datetime.utcnow()),
                        addon_users=int(addon_users),
                        package_amount=float(package_amount or 0),
                        total_from_amount=float(total_from_amount or 0),
                    )

                    invoice_asset = upload_invoice_and_get_asset(
                        business_id=business_id,
                        user__id=user__id_for_upload,
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
                        email=payment.get("customer_email"),
                        fullname=payment.get("customer_name"),
                        currency=currency_symbol,
                        receipt_number=payment.get("customer_phone"),
                        invoice_number=invoice_number,
                        payment_method=payment.get("payment_method"),
                        paid_date=str(datetime.utcnow()),
                        plan_name=plan_name,
                        addon_users=int(addon_users),
                        package_amount=float(package_amount or 0),
                        amount=float(total_from_amount or package_amount or 0),
                        total_from_amount=float(total_from_amount or 0),
                        invoice_pdf_bytes=invoice_bytes,
                        invoice_url=(invoice_asset or {}).get("url"),
                    )
                except Exception as e:
                    Log.warning(f"{log_tag} Invoice/email error: {e}")

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
                            reference=payment_reference,
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
                                "message": "Payment processed but storage addon failed",
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
                                payment_method=PAYMENT_METHODS["HUBTEL"],
                                payment_reference=payment_reference,
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
                                    "message": "Payment processed but subscription creation failed",
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
                                payment_method=PAYMENT_METHODS["HUBTEL"],
                                payment_reference=payment_reference,
                            )

                            if not success:
                                Payment.update(
                                    payment_id, business_id=business_id, processing_callback=True,
                                    notes=f"Payment OK but renewal failed: {error}",
                                )
                                Log.info(f"{log_tag} Payment OK but renewal failed: {error}")
                                return jsonify({
                                    "code": 200,
                                    "message": "Payment processed but subscription renewal failed",
                                    "error": error,
                                }), 200

                    # Discount + commission (system billing only)
                    _record_discount_redemption(
                        metadata=metadata,
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
                            payment_reference=payment_reference,
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
                    Log.info(f"{log_tag} Church collection: purchase_type={purchase_type}, ref={payment_reference}")

                return jsonify({
                    "code": 200,
                    "message": "Callback processed successfully",
                    "payment_status": Payment.STATUS_SUCCESS,
                    "purchase_type": purchase_type,
                    "subscription_id": subscription_id,
                    "storage": storage_result,
                }), 200

            # ══════════════════════════════════════════════
            # PAYMENT FAILED
            # ══════════════════════════════════════════════
            error_message = get_hubtel_response_code_message(parsed.get("response_code"))
            Payment.update_status(payment_id, Payment.STATUS_FAILED, error_message=error_message)
            Payment.update(
                payment_id,
                business_id=business_id,
                processing_callback=True,
                failed_at=datetime.utcnow(),
                **update_data,
            )

            return jsonify({
                "code": 200,
                "message": "Callback processed - Payment failed",
                "payment_status": Payment.STATUS_FAILED,
                "error": error_message,
            }), 200

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return jsonify({"code": 200, "message": f"Error processing callback: {str(e)}"}), 200

@hubtel_blp.route("/webhooks/payment/hubtel/callback", methods=["GET"])
class HubtelCallback(MethodView):
    """
    Optional frontend callback/redirect endpoint for Hubtel if you want one separated.
    """

    def get(self):
        log_tag = "[hubtel_webhook_resource.py][HubtelCallback][get]"
        frontend_return_url = os.getenv("PAYMENT_FRONT_END_RETURN_URL", "")
        reference = request.args.get("clientReference") or request.args.get("reference")

        try:
            if not reference:
                if frontend_return_url:
                    return redirect(
                        f"{frontend_return_url}?{urlencode({'status': 'error', 'message': 'Missing transaction reference'})}",
                        code=302,
                    )
                return prepared_response(False, "BAD_REQUEST", "Missing transaction reference")

            payment = Payment.get_by_order_id(reference) or Payment.get_by_reference(reference)
            if not payment:
                if frontend_return_url:
                    return redirect(
                        f"{frontend_return_url}?{urlencode({'status': 'error', 'reference': reference, 'message': 'Payment record not found'})}",
                        code=302,
                    )
                return prepared_response(False, "NOT_FOUND", "Payment not found")

            status = payment.get("status") or "Pending"

            if frontend_return_url:
                query_params = {
                    "status": status.lower(),
                    "reference": reference,
                    "payment_method": "hubtel",
                }
                return redirect(f"{frontend_return_url}?{urlencode(query_params)}", code=302)

            return prepared_response(
                True,
                "OK",
                "Payment callback processed.",
                data={
                    "reference": reference,
                    "status": status,
                    "payment_method": "hubtel",
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