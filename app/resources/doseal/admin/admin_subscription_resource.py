# resources/subscription_resource.py

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
from ....utils.crypt import decrypt_data
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
        """Create a new subscription."""
        
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        auth_business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))
        
        # Only system owner can create packages
        if account_type != SYSTEM_USERS["SYSTEM_OWNER"]:
            Log.info(f"{log_tag} Only system owner can create packages")
            return prepared_response(
                status=False,
                status_code="FORBIDDEN",
                message="Only system owner can create packages"
            )
            
        
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
        
        try:
            success, subscription_id, error = SubscriptionService.create_subscription(
                business_id=target_business_id,
                user_id=user_id,
                user__id=user__id,
                package_id=json_data["package_id"],
                payment_method=json_data.get("payment_method"),
                payment_reference=json_data.get("payment_reference"),
                auto_renew=json_data.get("auto_renew") if json_data.get("auto_renew") else False
            )
            
            if not success:
                Log.info(f"{log_tag} Failed to create subscription")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=error or "Failed to create subscription"
                )
            
            subscription = Subscription.get_by_id(subscription_id, target_business_id)
            
            return prepared_response(
                status=True,
                status_code="CREATED",
                message="Subscription created successfully",
                data=subscription
            )
            
        except Exception as e:
            Log.info(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to create subscription",
                errors=[str(e)]
            )


@blp_subscription.route("/subscriptions/current", methods=["GET"])
class GetCurrentSubscription(MethodView):
    """Get current active subscription."""
    
    @token_required
    def get(self):
        """Get active subscription for business."""

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
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
            subscription = Subscription.get_active_by_business(auth_business_id)
            
            if not subscription:
                Log.info(f"{log_tag} No active subscription found")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="No active subscription found"
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Subscription retrieved successfully",
                data=subscription
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to retrieve subscription",
                errors=[str(e)]
            )


@blp_subscription.route("/subscriptions/<subscription_id>/cancel", methods=["POST"])
class CancelSubscription(MethodView):
    """Cancel a subscription."""
    
    @token_required
    @blp_subscription.arguments(CancelSubscriptionSchema, location="json")
    def post(self, json_data, subscription_id):
        """Cancel subscription."""
        
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
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
            subscription = Subscription.get_active_by_business(auth_business_id)
            
            if not subscription:
                Log.info(f"{log_tag} No active subscription found")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="No active subscription found"
                )
         
        except Exception as e:
            pass
        
        try:
            success = Subscription.cancel_subscription(
                subscription_id=subscription_id,
                business_id=auth_business_id,
                reason=json_data.get("reason")
            )
            
            if not success:
                Log.info(f"{log_tag} Failed to cancel subscription")
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message="Failed to cancel subscription"
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Subscription cancelled successfully"
            )
            
        except Exception as e:
            Log.info(f"{log_tag} Failed to cancel subscription: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to cancel subscription",
                errors=[str(e)]
            )


@blp_subscription.route("/subscriptions/<subscription_id>/renew", methods=["POST"])
class RenewSubscription(MethodView):
    """Renew a subscription."""
    
    @token_required
    def post(self, subscription_id):
        """Renew subscription."""
        
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        
        account_type_enc = user_info.get("account_type")
        account_type = decrypt_data(account_type_enc) if account_type_enc else None
        
        auth_business_id = str(user_info.get("business_id"))
        user_id = user_info.get("_id")
        
        log_tag = make_log_tag(
            "admin_subscription_resource.py",
            "RenewSubscription",
            "post",
            client_ip,
            user_id,
            account_type,
            auth_business_id,
            auth_business_id,
        )
        
        try:
            data = request.get_json() or {}
            
            success, error = SubscriptionService.renew_subscription(
                subscription_id=subscription_id,
                business_id=auth_business_id,
                payment_reference=data.get("payment_reference")
            )
            
            if not success:
                Log.info(f"{log_tag} Failed to renew subscription")
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=error or "Failed to renew subscription"
                )
            
            subscription = Subscription.get_by_id(subscription_id, auth_business_id)
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Subscription renewed successfully",
                data=subscription
            )
            
        except Exception as e:
            Log.error(f"[RenewSubscription] Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to renew subscription",
                errors=[str(e)]
            )