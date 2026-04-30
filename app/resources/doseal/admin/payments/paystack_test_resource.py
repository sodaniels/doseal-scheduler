# app/resources/admin/paystack_test_resource.py

"""
Paystack Recurring Charge Test Endpoints
==========================================
DEVELOPMENT ONLY — remove or protect behind super_admin in production.

Provides endpoints to manually test each step of the recurring charge flow:
  1. Check stored authorizations
  2. Trigger a single renewal charge
  3. Run the full renewal batch
  4. Verify scheduler is registered
"""

import os
from flask import request, g
from flask.views import MethodView
from flask_smorest import Blueprint

from .....utils.logger import Log
from .....utils.json_response import prepared_response
from .....constants.service_code import SYSTEM_USERS
from ..admin_business_resource import token_required

paystack_test_blp = Blueprint(
    "paystack_test",
    __name__,
    description="Paystack recurring charge testing (dev only)"
)


@paystack_test_blp.route("/test/paystack/stored-auth", methods=["GET"])
class TestStoredAuth(MethodView):
    """Check if the current business has a stored Paystack authorization."""

    @token_required
    @paystack_test_blp.response(200)
    def get(self):
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))

        try:
            from .....models.admin.paystack_authorization import PaystackAuthorization

            # Get default
            default_auth = PaystackAuthorization.get_default_for_business(business_id)

            # Get all
            all_auths = PaystackAuthorization.get_all_for_business(business_id)

            if not default_auth and not all_auths:
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="No stored Paystack authorizations found. Make a payment first via Paystack checkout.",
                    data={
                        "business_id": business_id,
                        "stored_cards": 0,
                        "tip": "Complete a test payment at /payments/execute with payment_method=paystack, "
                               "then check this endpoint again."
                    }
                )

            # Sanitize — don't expose full authorization_code
            def sanitize(auth):
                return {
                    "_id": auth.get("_id"),
                    "authorization_code": auth.get("authorization_code", "")[:10] + "...",
                    "email": auth.get("email"),
                    "card_type": auth.get("card_type"),
                    "last4": auth.get("last4"),
                    "exp_month": auth.get("exp_month"),
                    "exp_year": auth.get("exp_year"),
                    "bank": auth.get("bank"),
                    "channel": auth.get("channel"),
                    "brand": auth.get("brand"),
                    "reusable": auth.get("reusable"),
                    "is_default": auth.get("is_default"),
                    "is_active": auth.get("is_active"),
                    "signature": auth.get("signature"),
                    "last_charged_at": str(auth.get("last_charged_at") or "Never"),
                    "created_at": str(auth.get("created_at", "")),
                }

            return prepared_response(
                status=True,
                status_code="OK",
                message=f"Found {len(all_auths)} stored authorization(s)",
                data={
                    "business_id": business_id,
                    "default_card": sanitize(default_auth) if default_auth else None,
                    "all_cards": [sanitize(a) for a in all_auths],
                }
            )

        except Exception as e:
            Log.error(f"[TestStoredAuth] Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message=str(e)
            )


@paystack_test_blp.route("/test/paystack/charge-now", methods=["POST"])
class TestChargeNow(MethodView):
    """
    Manually trigger a recurring charge for the current business.
    Uses the stored default authorization.
    
    Body (optional):
        {
            "amount_override": 1.00   // override amount for testing (in major units)
        }
    """

    @token_required
    @paystack_test_blp.response(200)
    def post(self):
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))

        # Only allow in development or for super_admin
        account_type = user_info.get("account_type")
        if os.getenv("APP_ENV") != "development" and account_type != SYSTEM_USERS.get("BUSINESS_OWNER"):
            return prepared_response(
                status=False,
                status_code="FORBIDDEN",
                message="This endpoint is only available in development or for super admins"
            )

        try:
            from .....models.admin.paystack_authorization import PaystackAuthorization
            from .....utils.payments.paystack_utils import charge_authorization, to_subunit
            from .....utils.generators import generate_internal_reference

            json_data = request.get_json(silent=True) or {}

            # Get stored authorization
            auth = PaystackAuthorization.get_default_for_business(business_id)
            if not auth:
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="No stored authorization. Complete a Paystack payment first."
                )

            # Use test amount
            amount = float(json_data.get("amount_override", 1.00))
            currency = "GHS"
            reference = generate_internal_reference("PSK-TEST")

            Log.info(f"[TestChargeNow] Charging {amount} {currency} on card ****{auth.get('last4')} "
                     f"for business={business_id}")

            success, data, error = charge_authorization(
                email=auth["email"],
                amount_subunit=to_subunit(amount),
                authorization_code=auth["authorization_code"],
                reference=reference,
                currency=currency,
                metadata={
                    "business_id": business_id,
                    "charge_type": "manual_test",
                    "test": True,
                },
            )

            if success:
                # Mark as charged
                PaystackAuthorization.mark_charged(auth["_id"])

                return prepared_response(
                    status=True,
                    status_code="OK",
                    message="Charge successful!",
                    data={
                        "reference": reference,
                        "status": data.get("status"),
                        "amount": amount,
                        "currency": currency,
                        "gateway_response": data.get("gateway_response"),
                        "card": f"****{auth.get('last4')}",
                        "requires_2fa": bool(data.get("paused")),
                        "authorization_url": data.get("authorization_url"),
                        "paystack_id": data.get("id"),
                    }
                )
            else:
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Charge failed: {error}",
                    data={
                        "reference": reference,
                        "card": f"****{auth.get('last4')}",
                        "email_used": auth.get("email"),
                    }
                )

        except Exception as e:
            Log.error(f"[TestChargeNow] Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message=str(e)
            )


@paystack_test_blp.route("/test/paystack/run-renewals", methods=["POST"])
class TestRunRenewals(MethodView):
    """
    Manually trigger the full renewal batch processor.
    Same as what the daily cron job runs.
    
    Body (optional):
        {
            "grace_days": 0
        }
    """

    @token_required
    @paystack_test_blp.response(200)
    def post(self):
        user_info = g.get("current_user", {})
        account_type = user_info.get("account_type")

        if os.getenv("APP_ENV") != "development" and account_type != SYSTEM_USERS.get("BUSINESS_OWNER"):
            return prepared_response(
                status=False,
                status_code="FORBIDDEN",
                message="Super admin only"
            )

        try:
            from .....services.payments.paystack_recurring_service import PaystackRecurringService

            json_data = request.get_json(silent=True) or {}
            grace_days = int(json_data.get("grace_days", 0))

            Log.info(f"[TestRunRenewals] Manually triggering renewal batch grace_days={grace_days}")

            results = PaystackRecurringService.process_due_renewals(grace_days=grace_days)

            return prepared_response(
                status=True,
                status_code="OK",
                message="Renewal batch complete",
                data=results
            )

        except Exception as e:
            Log.error(f"[TestRunRenewals] Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message=str(e)
            )


@paystack_test_blp.route("/test/paystack/scheduler-status", methods=["GET"])
class TestSchedulerStatus(MethodView):
    """Check if the rq_scheduler jobs are registered."""

    @token_required
    @paystack_test_blp.response(200)
    def get(self):
        try:
            from .....extensions.queue import ping_redis
            from .....extensions.redis_conn import redis_client

            redis_ok = ping_redis()
            scheduler_key = "rq:scheduler:scheduled_jobs"

            jobs = []
            try:
                job_ids = redis_client.zrange(scheduler_key, 0, -1)

                for job_id in job_ids:
                    job_key = f"rq:job:{job_id}"

                    # Read only text-safe fields individually — avoid hgetall
                    # which chokes on pickled binary fields like 'meta' and 'data'
                    try:
                        func_name = redis_client.hget(job_key, "description") or "unknown"
                        status = redis_client.hget(job_key, "status") or "scheduled"
                        origin = redis_client.hget(job_key, "origin") or ""
                        timeout = redis_client.hget(job_key, "timeout") or ""
                    except Exception:
                        func_name = "could not read"
                        status = "unknown"
                        origin = ""
                        timeout = ""

                    jobs.append({
                        "id": job_id,
                        "func": func_name,
                        "status": status,
                        "origin": origin,
                        "timeout": timeout,
                    })

            except Exception as e:
                jobs = [{"error": f"Could not list jobs: {str(e)}"}]

            return prepared_response(
                status=True,
                status_code="OK",
                message="Scheduler status",
                data={
                    "redis_connected": redis_ok,
                    "scheduled_jobs_count": len(jobs),
                    "jobs": jobs,
                }
            )

        except Exception as e:
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message=str(e)
            )
            
# -------------------------------------------------------------------
# Blueprint registration — add to your app factory:
#
#   from app.resources.admin.paystack_test_resource import paystack_test_blp
#   api.register_blueprint(paystack_test_blp, url_prefix="/api/v1")
#
# -------------------------------------------------------------------
