# app/decorators/subscription_decorator.py

from functools import wraps
from flask import g, request
from ..constants.church_permissions import has_permission
from ..utils.json_response import prepared_response
from ..utils.helpers import _resolve_business_id, _safe_account_type
from ..utils.logger import Log



def require_active_subscription(allow_read=False, grace_days=0):
    """
    Decorator that checks if the business has an active subscription.
    Use AFTER @token_required so g.current_user is set.

    Args:
        allow_read: If True, GET requests bypass the subscription check.
                    Useful for letting expired users still VIEW their data
                    but not create/update/delete.
        grace_days: Number of days after expiry to still allow access.
                    0 = strict, no grace period.

    Usage:
        @token_required
        @require_active_subscription()
        @require_permission("donations", "create")
        def post(self, json_data):
            ...

        # Allow reading even with expired subscription
        @token_required
        @require_active_subscription(allow_read=True)
        @require_permission("donations", "read")
        def get(self, qd):
            ...

    Bypass:
        - SYSTEM_OWNER always bypasses (platform operator)
        - SUPER_ADMIN bypasses (business owner — they need access to renew)
        - Subscription/billing/settings endpoints should NOT use this decorator
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user_info = g.get("current_user", {}) or {}
            account_type = _safe_account_type(user_info.get("account_type", ""))

            # Extract resource/method for logging
            resource_name = f.__qualname__.rsplit(".", 1)[0] if "." in f.__qualname__ else f.__name__
            method_name = f.__name__
            log_tag = f"[subscription_check][{resource_name}.{method_name}]"

            # ── 1. SYSTEM_OWNER bypass — platform operator only ──
            if account_type == "SYSTEM_OWNER":
                return f(*args, **kwargs)

            # ── 2. Allow read operations if configured ──
            if allow_read and request.method == "GET":
                return f(*args, **kwargs)

            # ── 3. Resolve business_id ──
            target_business_id = _resolve_business_id(user_info)
            if not target_business_id:
                Log.info(f"{log_tag} no business_id found for user")
                return prepared_response(
                    False, "FORBIDDEN",
                    "Unable to determine your business. Please contact support."
                )

            # ── 4. Check subscription ──
            try:
                from ..models.admin.subscription_model import Subscription

                subscription = Subscription.get_active_by_business(target_business_id)

                if not subscription:
                    Log.info(f"{log_tag} no active subscription for business_id={target_business_id}")

                    # Check if there's an expired/cancelled one for better messaging
                    latest = Subscription.get_latest_by_business(target_business_id)

                    if not latest:
                        return prepared_response(
                            False, "PAYMENT_REQUIRED",
                            "No subscription found. Please subscribe to a plan to continue.",
                            errors={"subscription_status": "none", "action_required": "subscribe"}
                        )

                    latest_status = latest.get("status", "").upper()

                    if latest_status == "TRIALEXPIRED":
                        return prepared_response(
                            False, "PAYMENT_REQUIRED",
                            "Your free trial has expired. Please subscribe to a plan to continue using the platform.",
                            errors={
                                "subscription_status": "trial_expired",
                                "trial_end_date": latest.get("trial_end_date"),
                                "action_required": "subscribe",
                            }
                        )

                    if latest_status == "CANCELLED":
                        return prepared_response(
                            False, "PAYMENT_REQUIRED",
                            "Your subscription has been cancelled. Please renew to continue.",
                            errors={
                                "subscription_status": "cancelled",
                                "cancelled_at": latest.get("cancelled_at"),
                                "action_required": "renew",
                            }
                        )

                    if latest_status == "EXPIRED":
                        return prepared_response(
                            False, "PAYMENT_REQUIRED",
                            "Your subscription has expired. Please renew to continue.",
                            errors={
                                "subscription_status": "expired",
                                "end_date": latest.get("end_date"),
                                "action_required": "renew",
                            }
                        )

                    if latest_status == "SUSPENDED":
                        return prepared_response(
                            False, "PAYMENT_REQUIRED",
                            "Your subscription has been suspended. Please contact support.",
                            errors={
                                "subscription_status": "suspended",
                                "suspended_at": latest.get("suspended_at"),
                                "action_required": "contact_support",
                            }
                        )

                    # Generic fallback
                    return prepared_response(
                        False, "PAYMENT_REQUIRED",
                        "Your subscription is not active. Please subscribe or renew to continue.",
                        errors={"subscription_status": latest_status.lower(), "action_required": "subscribe"}
                    )

                # ── 6. Subscription exists — check trial expiry ──
                sub_status = subscription.get("status", "").upper()
                trial_end_date = subscription.get("trial_end_date")

                if sub_status == "TRIAL" and trial_end_date:
                    from datetime import datetime, timedelta
                    now = datetime.utcnow()

                    if isinstance(trial_end_date, str):
                        try:
                            trial_end_date = datetime.fromisoformat(trial_end_date)
                        except:
                            pass

                    if isinstance(trial_end_date, datetime):
                        grace_end = trial_end_date + timedelta(days=grace_days)

                        if now > grace_end:
                            Log.info(f"{log_tag} trial expired (past grace) for business_id={target_business_id}")

                            # Calculate days overdue
                            days_overdue = (now - trial_end_date).days

                            return prepared_response(
                                False, "PAYMENT_REQUIRED",
                                f"Your free trial expired {days_overdue} day(s) ago. Please subscribe to continue.",
                                errors={
                                    "subscription_status": "trial_expired",
                                    "trial_end_date": trial_end_date.isoformat(),
                                    "days_overdue": days_overdue,
                                    "action_required": "subscribe",
                                }
                            )

                        # Trial still active — calculate remaining days
                        days_remaining = (trial_end_date - now).days
                        if days_remaining <= 3:
                            # Inject warning header for frontend to show banner
                            response = f(*args, **kwargs)
                            if hasattr(response, 'headers'):
                                response.headers["X-Trial-Warning"] = f"Trial expires in {days_remaining} day(s)"
                                response.headers["X-Trial-Days-Remaining"] = str(days_remaining)
                            return response

                # ── 7. Check paid subscription end date ──
                end_date = subscription.get("end_date")
                if end_date and sub_status == "ACTIVE":
                    from datetime import datetime, timedelta
                    now = datetime.utcnow()

                    if isinstance(end_date, str):
                        try:
                            end_date = datetime.fromisoformat(end_date)
                        except:
                            pass

                    if isinstance(end_date, datetime):
                        grace_end = end_date + timedelta(days=grace_days)

                        if now > grace_end:
                            days_overdue = (now - end_date).days
                            Log.info(f"{log_tag} subscription expired (past grace) for business_id={target_business_id}")

                            return prepared_response(
                                False, "PAYMENT_REQUIRED",
                                f"Your subscription expired {days_overdue} day(s) ago. Please renew to continue.",
                                errors={
                                    "subscription_status": "expired",
                                    "end_date": end_date.isoformat(),
                                    "days_overdue": days_overdue,
                                    "action_required": "renew",
                                }
                            )

                        # Subscription active but expiring soon
                        days_remaining = (end_date - now).days
                        if days_remaining <= 7:
                            response = f(*args, **kwargs)
                            if hasattr(response, 'headers'):
                                response.headers["X-Subscription-Warning"] = f"Subscription expires in {days_remaining} day(s)"
                                response.headers["X-Subscription-Days-Remaining"] = str(days_remaining)
                            return response

                # ── 8. All checks passed ──
                return f(*args, **kwargs)

            except Exception as e:
                Log.error(f"{log_tag} subscription check error: {e}")
                return prepared_response(
                    False, "INTERNAL_SERVER_ERROR",
                    "Unable to verify your subscription status. Please try again or contact support.",
                    errors={
                        "subscription_status": "check_failed",
                        "action_required": "retry",
                    }
                )

        return wrapper
    return decorator
