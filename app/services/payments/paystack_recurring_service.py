# services/payments/paystack_recurring_service.py

"""
Paystack Recurring Charge Service
===================================
Handles automatic subscription renewal by charging stored card authorizations.

Usage:
  Called from a cron job / APScheduler / Celery beat task that runs daily.

Flow:
  1. Find subscriptions expiring today (or within a grace window)
  2. For each, look up the stored Paystack authorization for that business
  3. Call Paystack charge_authorization endpoint
  4. Paystack processes the charge → webhook handles the result
  5. On success webhook: subscription is renewed automatically

IMPORTANT Paystack rules:
  - You MUST use the same email that was used for the initial transaction
  - Amount must be in subunit (pesewas/kobo/cents)
  - If the card requires 2FA/challenge, Paystack returns a redirect URL —
    you'll need to notify the customer to complete authentication
"""

import os
from datetime import datetime, timedelta
from bson import ObjectId

from ...utils.logger import Log
from ...utils.generators import generate_internal_reference
from ...utils.payments.paystack_utils import (
    charge_authorization,
    to_subunit,
)
from ...utils.external.exchange_rate_api import get_exchange_rate
from ...models.admin.payment import Payment
from ...models.admin.package_model import Package
from ...models.church.payment_method_model import PaymentMethod
from ...services.email_service import (
    send_paystack_recurring_auth_required_email,
    send_subscription_manual_payment_reminder_email,
    send_subscription_2fa_required_email,
    send_subscription_failed_charge_email,
    send_paystack_auth_required_email  
)


class PaystackRecurringService:
    """Service for charging stored Paystack authorizations on subscription renewal."""

    @staticmethod
    def charge_subscription_renewal(
        business_id: str,
        user_id: str,
        user__id: str,
        subscription: dict,
        package: dict = None,
    ) -> tuple:
        """
        Charge a stored card for a single subscription renewal.

        Args:
            business_id:   Business ObjectId string
            user_id:       User string ID
            user__id:      User ObjectId string
            subscription:  The subscription document (must include package_id, etc.)
            package:       Optional pre-fetched package document

        Returns:
            (success: bool, data: dict | None, error: str | None)
        """
        log_tag = f"[PaystackRecurringService][charge_subscription_renewal][{business_id}]"

        try:
            # ---- 1. Get stored authorization ---- #
            auth = PaymentMethod.get_chargeable_method(business_id)

            if not auth:
                Log.warning(f"{log_tag} No active Paystack authorization found")
                return False, None, "No stored payment method. Customer needs to pay manually."

            authorization_code = auth.get("authorization_code")
            auth_email = auth.get("email")  # MUST use the original email
            auth_id = auth.get("_id")

            if not authorization_code or not auth_email:
                Log.error(f"{log_tag} Authorization missing code or email")
                return False, None, "Invalid stored authorization"

            # ---- 2. Get package details ---- #
            package_id = str(subscription.get("package_id") or "")
            if not package:
                package = Package.get_by_id(package_id)

            if not package:
                Log.error(f"{log_tag} Package not found: {package_id}")
                return False, None, "Package not found"

            if package.get("status") != "Active":
                return False, None, "Package is not active"

            # ---- 3. Calculate amount ---- #
            base_amount = float(package.get("price", 0))
            if base_amount <= 0:
                Log.info(f"{log_tag} Free package — no charge needed")
                return True, {"message": "Free package, no charge"}, None

            # Handle addon users
            amount_detail = subscription.get("amount_detail") or {}
            addon_users = int(amount_detail.get("addon_users") or 0)

            if addon_users > 0:
                total_amount = round(base_amount * addon_users, 2)
            else:
                total_amount = base_amount

            # Currency conversion
            from_currency = os.getenv("DEFUALT_PACKAGE_CURRENCY", "USD")
            to_currency = amount_detail.get("to_currency") or subscription.get("currency") or "GHS"

            if from_currency != to_currency:
                exchange_rate = get_exchange_rate(from_currency, to_currency)
                charge_amount = round(total_amount * exchange_rate, 2)
            else:
                charge_amount = total_amount
                exchange_rate = 1.0


            amount_subunit = to_subunit(charge_amount)

            # ---- 4. Generate reference ---- #
            reference = generate_internal_reference("PSK-REN")

            # ---- 5. Build metadata ---- #
            metadata = {
                "business_id": business_id,
                "user_id": user_id,
                "user__id": user__id,
                "package_id": package_id,
                "subscription_id": str(subscription.get("_id", "")),
                "billing_period": subscription.get("billing_period", "monthly"),
                "charge_type": "recurring_renewal",
                "authorization_id": auth_id,
                "custom_fields": [
                    {
                        "display_name": "Charge Type",
                        "variable_name": "charge_type",
                        "value": "Subscription Renewal",
                    },
                    {
                        "display_name": "Package",
                        "variable_name": "package_name",
                        "value": package.get("name", ""),
                    },
                ],
            }

            Log.info(
                f"{log_tag} Charging authorization last4={auth.get('last4')} "
                f"amount={charge_amount} {to_currency} ref={reference}"
            )

            # ---- 6. Call Paystack charge_authorization ---- #
            success, ps_data, error = charge_authorization(
                email=auth_email,
                amount_subunit=amount_subunit,
                authorization_code=authorization_code,
                reference=reference,
                currency=to_currency,
                metadata=metadata,
            )

            if not success:
                Log.error(f"{log_tag} Charge failed: {error}")
                # Record failure on the payment method
                PaymentMethod.record_charge_result(auth_id, business_id, success=False, status_message=error)
                return False, None, error

            # ---- 7. Check if 2FA challenge is required ---- #
            txn_status = ps_data.get("status")

            if txn_status == "success":
                # Immediate success (no 2FA needed)
                Log.info(f"{log_tag} Charge successful immediately ref={reference}")

                # Mark authorization as recently charged
                PaymentMethod.record_charge_result(auth_id, business_id, success=True)

            elif ps_data.get("paused"):
                # Card requires 2FA — customer needs to complete authentication
                auth_url = ps_data.get("authorization_url")
                Log.warning(
                    f"{log_tag} Card requires 2FA. Customer must visit: {auth_url}"
                )
                
                # Send email/SMS to customer with the auth_url
                # The webhook will handle the result once they authenticate
                _send_paystack_auth_required_email_fn(
                    auth_email=auth_email,
                    auth=auth,
                    package=package,
                    subscription=subscription,
                    auth_url=auth_url,
                    reference=reference,
                    charge_amount=charge_amount,
                    to_currency=to_currency,
                    log_tag=log_tag,
                )
                
                try:
                    customer_fullname = auth.get("account_name") or ""
                    plan_name = package.get("name", "Subscription Plan")
                    billing_period = subscription.get("billing_period", "monthly")

                    send_paystack_recurring_auth_required_email(
                        email=auth_email,
                        fullname=customer_fullname,
                        authorization_url=auth_url,
                        reference=reference,
                        amount=charge_amount,
                        currency=to_currency,
                        plan_name=plan_name,
                        billing_period=billing_period,
                    )

                    Log.info(f"{log_tag} 2FA email sent successfully ref={reference}")

                except Exception as notify_error:
                    Log.error(
                        f"{log_tag} Failed to send 2FA email ref={reference}: {str(notify_error)}",
                        exc_info=True,
                    )

            # ---- 8. Create Payment record ---- #
            new_amount_detail = {
                "addon_users": addon_users,
                "package_amount": base_amount,
                "from_currency": from_currency,
                "total_from_amount": total_amount,
                "total_to_amount": charge_amount,
                "to_currency": to_currency,
                "exchange_rate": exchange_rate,
                "payment_gateway": "paystack",
                "charge_type": "recurring_renewal",
            }

            payment = Payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                amount=charge_amount,
                amount_detail=new_amount_detail,
                payment_method="paystack",
                payment_type=Payment.TYPE_RENEWAL,
                reference=reference,
                currency=to_currency,
                package_id=package_id,
                gateway="paystack",
                gateway_transaction_id=str(ps_data.get("id", "")),
                checkout_request_id=ps_data.get("access_code"),
                status=Payment.STATUS_SUCCESS if txn_status == "success" else Payment.STATUS_PENDING,
                status_message=ps_data.get("gateway_response"),
                status_code=200 if txn_status == "success" else 102,
                initial_response=ps_data,
                customer_email=auth_email,
                customer_name=auth.get("account_name"),
                metadata=metadata,
            )

            payment_doc = payment.to_dict()
            payment.save(payment_doc)

            Log.info(f"{log_tag} Payment record created ref={reference} status={txn_status}")

            return True, {
                "reference": reference,
                "status": txn_status,
                "amount": charge_amount,
                "currency": to_currency,
                "gateway_response": ps_data.get("gateway_response"),
                "requires_2fa": bool(ps_data.get("paused")),
                "authorization_url": ps_data.get("authorization_url"),
            }, None

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False, None, str(e)

    @staticmethod
    def process_due_renewals(grace_days: int = 0) -> dict:
        """
        Find all subscriptions due for renewal and charge them.
        
        Call this from a daily cron job / APScheduler / Celery beat.

        Args:
            grace_days: Number of days after expiry to still attempt charge.
                        0 = charge on the expiry date itself.

        Returns:
            dict with summary: {
                "total_due": int,
                "charged": int,
                "failed": int,
                "skipped": int,
                "details": [...]
            }
        """
        log_tag = "[PaystackRecurringService][process_due_renewals]"
        Log.info(f"{log_tag} Starting renewal processing grace_days={grace_days}")

        results = {
            "total_due": 0,
            "charged": 0,
            "failed": 0,
            "skipped": 0,
            "requires_2fa": 0,
            "details": [],
        }

        try:
            from ...services.pos.subscription_service import SubscriptionService
            from ...extensions.db import db

            # Find subscriptions expiring today (± grace window)
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            window_start = today - timedelta(days=grace_days)
            window_end = today + timedelta(days=1)  # end of today

            subscription_col = db.get_collection("subscriptions")
            due_subscriptions = list(subscription_col.find({
                "status": "Active",
                "payment_method": {"$in": ["paystack", "PAYSTACK"]},
                "auto_renew": True,
                "end_date": {
                    "$gte": window_start,
                    "$lt": window_end,
                },
            }))

            results["total_due"] = len(due_subscriptions)
            Log.info(f"{log_tag} Found {len(due_subscriptions)} subscriptions due for renewal")

            for sub in due_subscriptions:
                sub_id = str(sub.get("_id"))
                business_id = str(sub.get("business_id"))
                user_id = sub.get("user_id")
                user__id = str(sub.get("user__id"))

                try:
                    # Check if a renewal payment was already created today (idempotency)
                    existing_renewal = db.get_collection(Payment.collection_name).find_one({
                        "business_id": ObjectId(business_id),
                        "payment_type": Payment.TYPE_RENEWAL,
                        "gateway": "paystack",
                        "created_at": {"$gte": today},
                        "metadata.subscription_id": sub_id,
                    })

                    if existing_renewal:
                        Log.info(f"{log_tag} Renewal already attempted today for sub={sub_id} — skipping")
                        results["skipped"] += 1
                        results["details"].append({
                            "subscription_id": sub_id,
                            "business_id": business_id,
                            "status": "skipped",
                            "reason": "Already attempted today",
                        })
                        continue

                    # Check if business has a stored authorization
                    auth = PaymentMethod.get_chargeable_method(business_id)
                    if not auth:
                        Log.info(f"{log_tag} No stored auth for business={business_id} — skipping")
                        results["skipped"] += 1
                        results["details"].append({
                            "subscription_id": sub_id,
                            "business_id": business_id,
                            "status": "skipped",
                            "reason": "No stored payment method",
                        })
                        
                        # Send reminder email to customer to pay manually
                        _send_subscription_manual_payment_reminder_email_fn(
                            sub=sub,
                            sub_id=sub_id,
                            log_tag=log_tag,
                        )
                        continue

                    # Attempt charge
                    success, data, error = PaystackRecurringService.charge_subscription_renewal(
                        business_id=business_id,
                        user_id=user_id,
                        user__id=user__id,
                        subscription=sub,
                    )

                    if success:
                        if data and data.get("requires_2fa"):
                            results["requires_2fa"] += 1
                            results["details"].append({
                                "subscription_id": sub_id,
                                "business_id": business_id,
                                "status": "requires_2fa",
                                "reference": data.get("reference"),
                                "authorization_url": data.get("authorization_url"),
                            })
                            
                            # Notify customer to complete 2FA
                            _send_subscription_2fa_required_email_fn(
                                sub=sub,
                                data=data,
                                business_id=business_id,
                                sub_id=sub_id,
                                log_tag=log_tag,
                            )
                        else:
                            results["charged"] += 1
                            results["details"].append({
                                "subscription_id": sub_id,
                                "business_id": business_id,
                                "status": "charged",
                                "reference": data.get("reference"),
                                "amount": data.get("amount"),
                            })
                    else:
                        results["failed"] += 1
                        results["details"].append({
                            "subscription_id": sub_id,
                            "business_id": business_id,
                            "status": "failed",
                            "error": error,
                        })
                        
                        # Send failed charge notification to customer
                        _send_subscription_failed_charge_email_fn(
                            sub=sub,
                            business_id=business_id,
                            sub_id=sub_id,               
                            log_tag=log_tag,
                        )

                except Exception as sub_error:
                    Log.error(f"{log_tag} Error processing sub={sub_id}: {str(sub_error)}")
                    results["failed"] += 1
                    results["details"].append({
                        "subscription_id": sub_id,
                        "business_id": business_id,
                        "status": "error",
                        "error": str(sub_error),
                    })

            Log.info(
                f"{log_tag} Renewal processing complete: "
                f"total={results['total_due']} charged={results['charged']} "
                f"failed={results['failed']} skipped={results['skipped']} "
                f"2fa={results['requires_2fa']}"
            )

            return results

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            results["error"] = str(e)
            return results




def _send_subscription_manual_payment_reminder_email_fn(
    sub: dict,
    sub_id: str,
    log_tag: str,
):
    """
    Send an email to the customer reminding them to make a manual payment for their subscription renewal.

    Args:
        email: Customer's email address
        fullname: Customer's full name
        plan_name: Name of the subscription plan
        amount: Amount due
        currency: Currency code (e.g. "USD")
        billing_period: Billing period (e.g. "monthly")
        due_date: Due date for payment
        payment_url: URL where the customer can make the payment
    """
    try:
        subscription_email = (
            sub.get("customer_email")
            or sub.get("email")
            or sub.get("account_email")
        )

        subscription_fullname = (
            sub.get("customer_name")
            or sub.get("fullname")
            or sub.get("business_name")
            or ""
        )

        package_id = str(sub.get("package_id") or "")
        package = Package.get_by_id(package_id) if package_id else None

        amount_detail = sub.get("amount_detail") or {}
        addon_users = int(amount_detail.get("addon_users") or 0)

        base_amount = float(package.get("price", 0)) if package else 0.0
        total_amount = round(base_amount * addon_users, 2) if addon_users > 0 else base_amount

        from_currency = os.getenv("DEFAULT_PACKAGE_CURRENCY", "USD")
        to_currency = amount_detail.get("to_currency") or sub.get("currency") or "GHS"

        if from_currency != to_currency:
            exchange_rate = get_exchange_rate(from_currency, to_currency)
            charge_amount = round(total_amount * exchange_rate, 2)
        else:
            charge_amount = total_amount

        payment_url = f"{os.getenv('APP_BASE_URL', '').rstrip('/')}/billing/renew?subscription_id={sub_id}"

        if subscription_email:
            send_subscription_manual_payment_reminder_email(
                email=subscription_email,
                fullname=subscription_fullname,
                plan_name=package.get("name", "Subscription Plan") if package else "Subscription Plan",
                amount=charge_amount,
                currency=to_currency,
                billing_period=sub.get("billing_period", "monthly"),
                due_date=sub.get("end_date").strftime("%Y-%m-%d") if sub.get("end_date") else None,
                payment_url=payment_url,
            )

            Log.info(f"{log_tag} Manual payment reminder sent for sub={sub_id}")
        else:
            Log.warning(f"{log_tag} No customer email found for sub={sub_id}")

    except Exception as reminder_error:
        Log.error(
            f"{log_tag} Failed to send manual payment reminder for sub={sub_id}: {str(reminder_error)}",
            exc_info=True,
        )

def _send_subscription_2fa_required_email_fn(
    sub: dict,
    data: dict,
    business_id: str,
    sub_id: str,
    log_tag: str,
):
    """
    Send an email to the customer notifying them that their card requires 2FA authentication
    to complete the subscription renewal charge.

    Args:
        email: Customer's email address
        fullname: Customer's full name
        plan_name: Name of the subscription plan
        amount: Amount charged
        currency: Currency code (e.g. "USD")
        billing_period: Billing period (e.g. "monthly")
        auth_url: The URL the customer must visit to complete 2FA authentication
    """
    try:
        auth = PaymentMethod.get_primary(business_id)

        subscription_email = (
            (auth or {}).get("email")
            or sub.get("customer_email")
            or sub.get("email")
            or sub.get("account_email")
        )

        subscription_fullname = (
            (auth or {}).get("account_name")
            or sub.get("customer_name")
            or sub.get("fullname")
            or sub.get("business_name")
            or ""
        )

        package_id = str(sub.get("package_id") or "")
        package = Package.get_by_id(package_id) if package_id else None

        if subscription_email and data.get("authorization_url"):
            send_subscription_2fa_required_email(
                email=subscription_email,
                fullname=subscription_fullname,
                authorization_url=data.get("authorization_url"),
                reference=data.get("reference"),
                amount=data.get("amount"),
                currency=sub.get("currency") or "GHS",
                plan_name=package.get("name", "Subscription Plan") if package else "Subscription Plan",
                billing_period=sub.get("billing_period", "monthly"),
            )

            Log.info(f"{log_tag} 2FA reminder email sent for sub={sub_id}")
        else:
            Log.warning(
                f"{log_tag} Could not send 2FA reminder for sub={sub_id}. "
                f"email={subscription_email}, authorization_url={data.get('authorization_url') if data else None}"
            )

    except Exception as notify_error:
        Log.error(
            f"{log_tag} Failed to send 2FA reminder for sub={sub_id}: {str(notify_error)}",
            exc_info=True,
        )

def _send_subscription_failed_charge_email_fn(
    sub: dict,
    business_id: str,
    sub_id: str,
    log_tag: str,
):
    """
    Send an email to the customer notifying them that their subscription renewal charge failed.

    Args:
        email: Customer's email address
        fullname: Customer's full name
        plan_name: Name of the subscription plan
        amount: Amount attempted to charge
        currency: Currency code (e.g. "USD")
        billing_period: Billing period (e.g. "monthly")
        error_message: The error message returned from the failed charge attempt
    """
    try:
        auth = PaystackAuthorization.get_default_for_business(business_id)

        subscription_email = (
            (auth or {}).get("email")
            or sub.get("customer_email")
            or sub.get("email")
            or sub.get("account_email")
        )

        subscription_fullname = (
            (auth or {}).get("account_name")
            or sub.get("customer_name")
            or sub.get("fullname")
            or sub.get("business_name")
            or ""
        )

        package_id = str(sub.get("package_id") or "")
        package = Package.get_by_id(package_id) if package_id else None

        amount_detail = sub.get("amount_detail") or {}
        addon_users = int(amount_detail.get("addon_users") or 0)

        base_amount = float(package.get("price", 0)) if package else 0.0
        total_amount = round(base_amount * addon_users, 2) if addon_users > 0 else base_amount

        from_currency = os.getenv("DEFAULT_PACKAGE_CURRENCY", "USD")
        to_currency = amount_detail.get("to_currency") or sub.get("currency") or "GHS"

        if from_currency != to_currency:
            exchange_rate = get_exchange_rate(from_currency, to_currency)
            charge_amount = round(total_amount * exchange_rate, 2)
        else:
            charge_amount = total_amount

        payment_url = (
            f"{os.getenv('APP_BASE_URL', '').rstrip('/')}"
            f"/billing/renew?subscription_id={sub_id}"
        )

        if subscription_email:
            send_subscription_failed_charge_email(
                email=subscription_email,
                fullname=subscription_fullname,
                plan_name=package.get("name", "Subscription Plan") if package else "Subscription Plan",
                amount=charge_amount,
                currency=to_currency,
                billing_period=sub.get("billing_period", "monthly"),
                due_date=sub.get("end_date").strftime("%Y-%m-%d") if sub.get("end_date") else None,
                failure_reason="Payment could not be processed",
                payment_url=payment_url,
            )

            Log.info(f"{log_tag} Failed charge email sent for sub={sub_id}")
        else:
            Log.warning(f"{log_tag} No authorization_url returned.")
        

    except Exception as notify_error:
        Log.error(
            f"{log_tag} Failed to send failed charge notification for sub={sub_id}: {str(notify_error)}",
            exc_info=True,
        )

def _send_paystack_auth_required_email_fn(
    auth_email: str,
    auth: dict,
    package: dict,
    subscription: dict,
    auth_url: str,
    reference: str,
    charge_amount: float,
    to_currency: str,
    log_tag: str,
):
    """
    Send an email to the customer notifying them that their card requires 2FA authentication
    to complete a Paystack charge.

    Args:
        email: Customer's email address
        fullname: Customer's full name
        plan_name: Name of the subscription plan
        amount: Amount charged
        currency: Currency code (e.g. "USD")
        billing_period: Billing period (e.g. "monthly")
        auth_url: The URL the customer must visit to complete 2FA authentication
    """
    try:
        customer_fullname = auth.get("account_name") or ""
        plan_name = package.get("name", "Subscription Plan")
        billing_period = subscription.get("billing_period", "monthly")

        if auth_url:
            send_paystack_auth_required_email(
                email=auth_email,
                fullname=customer_fullname,
                authorization_url=auth_url,
                reference=reference,
                amount=charge_amount,
                currency=to_currency,
                plan_name=plan_name,
                billing_period=billing_period,
            )
            Log.info(f"{log_tag} Auth required email sent successfully ref={reference}")

        else:
            Log.warning(f"{log_tag} No authorization_url returned for ref={reference}")

    except Exception as notify_error:
        Log.error(
            f"{log_tag} Failed to send auth required notification ref={reference}: {str(notify_error)}",
            exc_info=True,
        )










