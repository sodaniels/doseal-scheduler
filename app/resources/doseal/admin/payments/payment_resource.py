# resources/payment_resource.py

from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint

from .....constants.payment_methods import PAYMENT_METHODS
from .....constants.service_code import SYSTEM_USERS
from ...admin.admin_business_resource import token_required
from .....utils.json_response import prepared_response
from .....utils.crypt import decrypt_data
from .....utils.helpers import make_log_tag
from .....models.admin.payment import Payment
from .....models.admin.package_model import Package
#services
from .....services.payments.payment_service import PaymentService
from .....services.pos.subscription_service import SubscriptionService
from .....utils.payments.hubtel_utils import get_hubtel_auth_token
#schemas
from .....schemas.payments.payment_schema import (
    InitiatePaymentSchema,
    VerifyPaymentSchema,
    ManualPaymentSchema,
    InitiatePaymentPlanChangeSchema
)
from .....utils.logger import Log

payment_blp = Blueprint(
    "payments",
    __name__,
    description="Payment processing and management"
)


@payment_blp.route("/payments/initiate", methods=["POST"])
class InitiatePayment(MethodView):
    """Initiate a payment transaction."""
    
    @token_required
    @payment_blp.arguments(InitiatePaymentSchema, location="json")
    @payment_blp.response(200)
    def post(self, json_data):
        """Initiate payment for subscription."""
        
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))
        
        
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        
        log_tag = make_log_tag(
            "payment_resource.py",
            "InitiatePayment",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        try:
            package_id = json_data["package_id"]
            billing_period = json_data["billing_period"]
            payment_method = json_data["payment_method"]
            
            # Get package to verify price
            package = Package.get_by_id(package_id)
            
            if not package:
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="Package not found"
                )
            
            if package.get("status") != "Active":
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Package is not available"
                )
            
            # Check if it's a free package
            if package.get("price", 0) == 0:
                # Free package - create subscription directly
                success, subscription_id, error = SubscriptionService.create_subscription(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    package_id=package_id,
                    payment_method=None,
                    payment_reference=None
                )
                
                if success:
                    return prepared_response(
                        status=True,
                        status_code="CREATED",
                        message="Subscription activated (Free plan)",
                        data={"subscription_id": subscription_id}
                    )
                else:
                    return prepared_response(
                        status=False,
                        status_code="INTERNAL_SERVER_ERROR",
                        message=error or "Failed to create subscription"
                    )
            
            # Paid package - process payment
            metadata = {
                "package_id": package_id,
                "billing_period": billing_period,
                "business_id": business_id,
                "user_id": user_id,
                "user__id": user__id,
                **json_data.get("metadata", {})
            }
            
            # PAYMENT USING HUBTEL        
            if payment_method in [PAYMENT_METHODS["HUBTEL"], PAYMENT_METHODS["HUBTEL_MOBILE_MONEY"]]:
                phone = json_data.get("customer_phone")
                if not phone:
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="Phone number is required for Hubtel payments"
                    )
                
                try:
                    customer_name = decrypt_data(user_info.get("fullname")) if user_info.get("fullname") else ""
                    customer_email = decrypt_data(user_info.get("email")) if user_info.get("email") else ""
                    
                    success, data, error = PaymentService.initiate_hubtel_payment(
                        business_id=business_id,
                        user_id=user_id,
                        user__id=user__id,
                        package_id=package_id,
                        billing_period=billing_period,
                        customer_name=customer_name,
                        phone_number=phone,
                        customer_email=customer_email,
                        metadata=metadata,
                    )
                    
                    if success:
                        return prepared_response(
                            status=True,
                            status_code="OK",
                            message=data.get("message"),
                            data=data
                        )
                    else:
                        return prepared_response(
                            status=False,
                            status_code="BAD_REQUEST",
                            message=error or "Failed to initiate payment"
                        )
                
                except Exception as e:
                    Log.info(f"{log_tag} Error occurred: {str(e)}")
              
            # Route to appropriate payment gateway
            elif payment_method == PAYMENT_METHODS["MPESA"]:
                # TODO: Implement Paystack/Flutterwave payment initiation
                return prepared_response(
                    status=False,
                    status_code="NOT_IMPLEMENTED",
                    message=f"{payment_method} payment not yet implemented"
                )
            elif payment_method in [PAYMENT_METHODS["PAYSTACK"], PAYMENT_METHODS["FLUTTERWAVE"]]:
                # TODO: Implement Paystack/Flutterwave payment initiation
                return prepared_response(
                    status=False,
                    status_code="NOT_IMPLEMENTED",
                    message=f"{payment_method} payment not yet implemented"
                )
            
            else:
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Unsupported payment method: {payment_method}"
                )
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to initiate payment",
                errors=[str(e)]
            )


@payment_blp.route("/plan/change/payments/initiate", methods=["POST"])
class InitiatePayment(MethodView):
    """Initiate a payment transaction."""
    
    @token_required
    @payment_blp.arguments(InitiatePaymentPlanChangeSchema, location="json")
    @payment_blp.response(200)
    def post(self, json_data):
        """Initiate payment for subscription."""
        
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))
        
        
        account_type_enc = user_info.get("account_type")
        account_type = account_type_enc if account_type_enc else None
        
        log_tag = make_log_tag(
            "payment_resource.py",
            "InitiatePayment",
            "post",
            client_ip,
            user__id,
            account_type,
            business_id,
            business_id,
        )
        
        try:
            package_id = json_data["new_package_id"]
            old_package_id = json_data["old_package_id"]
            billing_period = json_data["billing_period"]
            payment_method = json_data["payment_method"]
            
            # Get package to verify price
            new_package = Package.get_by_id(package_id)
            old_package = Package.get_by_id(old_package_id)
            
            if not new_package:
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="New Package not found"
                )
                
            if not old_package:
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="Old Package not found"
                )
            
            if new_package.get("status") != "Active":
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="New Package is not available"
                )
                
            if old_package.get("status") != "Active":
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="Old Package is not available"
                )
            
            # Check if it's a free package
            if new_package.get("price", 0) == 0:
                # Free package - create subscription directly
                success, subscription_id, error = SubscriptionService.create_subscription(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    package_id=package_id,
                    payment_method=None,
                    payment_reference=None
                )
                
                if success:
                    return prepared_response(
                        status=True,
                        status_code="CREATED",
                        message="Subscription activated (Free plan)",
                        data={"subscription_id": subscription_id}
                    )
                else:
                    return prepared_response(
                        status=False,
                        status_code="INTERNAL_SERVER_ERROR",
                        message=error or "Failed to create subscription"
                    )
            
            # Paid package - process payment
            metadata = {
                "package_id": package_id,
                "old_package_id": old_package_id,
                "billing_period": billing_period,
                "business_id": business_id,
                "user_id": user_id,
                "user__id": user__id,
                **json_data.get("metadata", {})
            }
            
            # PAYMENT USING HUBTEL        
            if payment_method in [PAYMENT_METHODS["HUBTEL"], PAYMENT_METHODS["HUBTEL_MOBILE_MONEY"]]:
                phone = json_data.get("customer_phone")
                if not phone:
                    return prepared_response(
                        status=False,
                        status_code="BAD_REQUEST",
                        message="Phone number is required for Hubtel payments"
                    )
                
                try:
                    customer_name = decrypt_data(user_info.get("fullname")) if user_info.get("fullname") else ""
                    customer_email = decrypt_data(user_info.get("email")) if user_info.get("email") else ""
                    
                    success, data, error = PaymentService.initiate_hubtel_payment(
                        business_id=business_id,
                        user_id=user_id,
                        user__id=user__id,
                        package_id=package_id,
                        billing_period=billing_period,
                        customer_name=customer_name,
                        phone_number=phone,
                        customer_email=customer_email,
                        metadata=metadata,
                    )
                    
                    if success:
                        return prepared_response(
                            status=True,
                            status_code="OK",
                            message=data.get("message"),
                            data=data
                        )
                    else:
                        return prepared_response(
                            status=False,
                            status_code="BAD_REQUEST",
                            message=error or "Failed to initiate payment"
                        )
                
                except Exception as e:
                    Log.info(f"{log_tag} Error occurred: {str(e)}")
              
            # Route to appropriate payment gateway
            elif payment_method == PAYMENT_METHODS["MPESA"]:
                # TODO: Implement Paystack/Flutterwave payment initiation
                return prepared_response(
                    status=False,
                    status_code="NOT_IMPLEMENTED",
                    message=f"{payment_method} payment not yet implemented"
                )
            elif payment_method in [PAYMENT_METHODS["PAYSTACK"], PAYMENT_METHODS["FLUTTERWAVE"]]:
                # TODO: Implement Paystack/Flutterwave payment initiation
                return prepared_response(
                    status=False,
                    status_code="NOT_IMPLEMENTED",
                    message=f"{payment_method} payment not yet implemented"
                )
            
            else:
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message=f"Unsupported payment method: {payment_method}"
                )
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to initiate payment",
                errors=[str(e)]
            )


@payment_blp.route("/payments/verify", methods=["POST"])
class VerifyPayment(MethodView):
    """Verify payment status."""
    
    @token_required
    @payment_blp.arguments(VerifyPaymentSchema, location="json")
    @payment_blp.response(200)
    def post(self, json_data):
        """Verify payment status by payment_id or checkout_request_id."""
        
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        
        log_tag = f"[VerifyPayment][post][{business_id}]"
        
        try:
            payment_id = json_data.get("payment_id")
            checkout_request_id = json_data.get("checkout_request_id")
            gateway_transaction_id = json_data.get("gateway_transaction_id")
            
            if not any([payment_id, checkout_request_id, gateway_transaction_id]):
                return prepared_response(
                    status=False,
                    status_code="BAD_REQUEST",
                    message="At least one payment identifier is required"
                )
            
            result = PaymentService.verify_payment_status(
                payment_id=payment_id,
                checkout_request_id=checkout_request_id
            )
            
            if result.get("status") == "success":
                return prepared_response(
                    status=True,
                    status_code="OK",
                    message="Payment status retrieved",
                    data=result.get("payment")
                )
            else:
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message=result.get("message", "Payment not found")
                )
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to verify payment",
                errors=[str(e)]
            )


@payment_blp.route("/payments/history", methods=["GET"])
class PaymentHistory(MethodView):
    """Get payment history for business."""
    
    @token_required
    @payment_blp.response(200)
    def get(self):
        """Get payment history."""
        
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        
        log_tag = f"[PaymentHistory][get][{business_id}]"
        
        try:
            page = request.args.get("page", 1, type=int)
            per_page = request.args.get("per_page", 20, type=int)
            status = request.args.get("status")
            
            result = Payment.get_by_business_id(
                business_id=business_id,
                page=page,
                per_page=per_page,
                status=status
            )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Payment history retrieved successfully",
                data=result
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to retrieve payment history",
                errors=[str(e)]
            )


@payment_blp.route("/admin/payments/manual", methods=["POST"])
class CreateManualPayment(MethodView):
    """Create manual payment (admin only)."""
    
    @token_required
    @payment_blp.arguments(ManualPaymentSchema, location="json")
    @payment_blp.response(200)
    def post(self, json_data):
        """Create manual payment and subscription."""
        
        user_info = g.get("current_user", {})
        account_type = user_info.get("account_type")
        
        # Only admin/super_admin can create manual payments
        if account_type not in [SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["BUSINESS_OWNER"]]:
            return prepared_response(
                status=False,
                status_code="FORBIDDEN",
                message="Insufficient permissions"
            )
        
        log_tag = f"[CreateManualPayment][post]"
        
        try:
            # Extract business from request or use admin's business
            business_id = json_data.get("business_id") or str(user_info.get("business_id"))
            user_id = json_data.get("user_id") or user_info.get("user_id")
            user__id = json_data.get("user__id") or str(user_info.get("_id"))
            
            # Create manual payment
            success, payment_id, error = PaymentService.create_manual_payment(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                package_id=json_data["package_id"],
                billing_period=json_data["billing_period"],
                payment_method=json_data["payment_method"],
                payment_reference=json_data["payment_reference"],
                amount=json_data["amount"],
                currency=json_data.get("currency", "USD"),
                customer_phone=json_data.get("customer_phone"),
                customer_email=json_data.get("customer_email"),
                customer_name=json_data.get("customer_name"),
                notes=json_data.get("notes")
            )
            
            if not success:
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message=error or "Failed to create payment"
                )
            
            # Create subscription
            sub_success, subscription_id, sub_error = SubscriptionService.create_subscription(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                package_id=json_data["package_id"],
                payment_method=json_data["payment_method"],
                payment_reference=json_data["payment_reference"]
            )
            
            if sub_success:
                return prepared_response(
                    status=True,
                    status_code="CREATED",
                    message="Manual payment and subscription created successfully",
                    data={
                        "payment_id": payment_id,
                        "subscription_id": subscription_id
                    }
                )
            else:
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message=sub_error or "Payment created but subscription failed"
                )
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to create manual payment",
                errors=[str(e)]
            )