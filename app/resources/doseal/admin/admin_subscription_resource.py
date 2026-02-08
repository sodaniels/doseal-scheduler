# app/resources/admin/subscription_resource.py

from flask import g, request, jsonify
from flask.views import MethodView
from flask_smorest import Blueprint

from .admin_business_resource import token_required
from ....models.admin.subscription_model import Subscription
from ....services.pos.subscription_service import SubscriptionService
from ....schemas.admin.package_schema import (
    SubscriptionSchema, CancelSubscriptionSchema
)

from ....utils.helpers import make_log_tag
from ....utils.json_response import prepared_response
from ....utils.logger import Log
from ....constants.service_code import (
    HTTP_STATUS_CODES, SYSTEM_USERS
)

blp_subscription = Blueprint("subscriptions", __name__, description="Subscription management")


@blp_subscription.route("/admin/subscriptions/subscribe", methods=["POST"])
class Subscribe(MethodView):
    """Subscribe to a package."""

    @token_required
    @blp_subscription.arguments(SubscriptionSchema, location="json")
    def post(self, json_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        account_type = user_info.get("account_type")
        auth_business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))

        target_business_id = json_data.get("business_id")

        log_tag = make_log_tag(
            "admin_subscription_resource.py",
            "Subscribe",
            "post",
            client_ip,
            user__id,
            account_type,
            auth_business_id,
            target_business_id,
        )

        # Only system owner can create subscriptions for other businesses (as you coded)
        if account_type != SYSTEM_USERS["SYSTEM_OWNER"]:
            Log.info(f"{log_tag} forbidden")
            return prepared_response(False, "FORBIDDEN", "Only system owner can create subscriptions")

        try:
            success, subscription_id, error = SubscriptionService.create_subscription(
                business_id=target_business_id,
                user_id=user_id,
                user__id=user__id,
                package_id=json_data["package_id"],
                billing_period=json_data.get("billing_period") or "monthly",
                price_paid=float(json_data.get("price_paid") or 0.0),
                currency=json_data.get("currency") or "USD",
                payment_method=json_data.get("payment_method"),
                payment_reference=json_data.get("payment_reference"),
                auto_renew=bool(json_data.get("auto_renew") or False),
                status=Subscription.STATUS_ACTIVE,
            )

            if not success:
                return prepared_response(False, "BAD_REQUEST", error or "Failed to create subscription")

            subscription = Subscription.get_by_id(subscription_id, target_business_id)

            return prepared_response(True, "CREATED", "Subscription created successfully", data=subscription)

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to create subscription", errors=[str(e)])


@blp_subscription.route("/subscriptions/current", methods=["GET"])
class GetCurrentSubscription(MethodView):
    """Get current active subscription."""
    @token_required
    def get(self):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        account_type = user_info.get("account_type")
        auth_business_id = str(user_info.get("business_id"))
        user_id = user_info.get("_id")

        log_tag = make_log_tag(
            "admin_subscription_resource.py",
            "GetCurrentSubscription",
            "get",
            client_ip,
            user_id,
            account_type,
            auth_business_id,
            auth_business_id
        )

        try:
            subscription = Subscription.get_current_access_by_business(auth_business_id)
            if not subscription:
                return prepared_response(False, "NOT_FOUND", "No active subscription found")

            return prepared_response(True, "OK", "Subscription retrieved successfully", data=subscription)

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to retrieve subscription", errors=[str(e)])


@blp_subscription.route("/subscriptions/<subscription_id>/cancel", methods=["POST"])
class CancelSubscription(MethodView):
    """Cancel a subscription."""

    @token_required
    @blp_subscription.arguments(CancelSubscriptionSchema, location="json")
    def post(self, json_data, subscription_id):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})

        account_type = user_info.get("account_type")
        auth_business_id = str(user_info.get("business_id"))
        user_id = user_info.get("_id")

        log_tag = make_log_tag(
            "admin_subscription_resource.py",
            "CancelSubscription",
            "post",
            client_ip,
            user_id,
            account_type,
            auth_business_id,
            auth_business_id,
        )

        try:
            ok, err = SubscriptionService.cancel_subscription(
                business_id=auth_business_id,
                subscription_id=subscription_id,
                reason=json_data.get("reason"),
            )
            if not ok:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", err or "Failed to cancel subscription")

            return prepared_response(True, "OK", "Subscription cancelled successfully")

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to cancel subscription", errors=[str(e)])


@blp_subscription.route("/subscriptions/<subscription_id>/renew", methods=["POST"])
class RenewSubscription(MethodView):
    """
    Renew a specific subscription by ID (user clicks Renew on that row).
    Creates a NEW subscription term record.
    """
    @token_required
    def post(self, json_data=None, subscription_id=None):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}

        account_type = user_info.get("account_type")
        business_id = str(user_info.get("business_id") or "")
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id") or "")

        log_tag = make_log_tag(
            "admin_subscription_resource.py",
            "RenewSubscription",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )

        if not business_id or not user__id:
            return prepared_response(False, "UNAUTHORIZED", "Unauthorized")

        data = request.get_json(silent=True) or {}

        try:
            ok, new_sub_id, err = SubscriptionService.renew_subscription_by_id(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                old_subscription_id=subscription_id,   # ✅ THIS is the key
                payment_reference=data.get("payment_reference"),
                payment_method=data.get("payment_method"),
                auto_renew=data.get("auto_renew"),
            )

            if not ok:
                return prepared_response(False, "BAD_REQUEST", err or "Failed to renew subscription")

            current = Subscription.get_current_access_by_business(business_id)

            return prepared_response(
                True,
                "OK",
                "Subscription renewed successfully",
                data={"subscription_id": str(new_sub_id), "current": current},
            )

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to renew subscription", errors=[str(e)])






