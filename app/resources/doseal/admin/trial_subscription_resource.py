# app/resources/doseal/admin/admin/trial_subscription_resource.py

import os
import time
from datetime import datetime, timezone
from flask_smorest import Blueprint
from flask import request, jsonify, g
from flask.views import MethodView
from bson import ObjectId

from build.lib.app.utils.crypt import encrypt_data, hash_data

from ....constants.service_code import HTTP_STATUS_CODES, SYSTEM_USERS
from ....utils.logger import Log
from ....utils.helpers import make_log_tag
from ....utils.json_response import prepared_response
from ....extensions.db import db

from ....models.admin.subscription_model import Subscription
from ....models.admin.payment import Payment
from ....models.admin.package_model import Package
from ...doseal.admin.admin_business_resource import token_required
from ....utils.rate_limits import (
    trial_start_limiter,
    trial_status_limiter,
    trial_convert_limiter,
    read_protected_user_limiter,
    trial_cancel_limiter,
    subscription_packages_limiter
)


blp_trial_subscription = Blueprint("trial_subscription", __name__)


# =========================================
# START TRIAL SUBSCRIPTION
# =========================================
@trial_start_limiter("trial_start")
@blp_trial_subscription.route("/subscription/trial/start", methods=["POST"])
class StartTrialResource(MethodView):
    """
    Start a 30-day trial subscription for the authenticated user's business.
    
    Body:
    {
        "package_id": "6981ee8d6316bfd407ab5126"  // Required: Package to trial
    }
    
    Returns:
    {
        "success": true,
        "message": "Trial started successfully",
        "data": {
            "subscription": {...},
            "trial_info": {
                "days_remaining": 30,
                "end_date": "2026-03-15T12:00:00Z"
            }
        }
    }
    """
    
    @token_required
    def post(self):
        client_ip = request.remote_addr
        
        user_info = g.get("current_user", {}) or {}
        user_id = str(user_info.get("_id", ""))
        business_id = str(user_info.get("business_id", ""))
        account_type = user_info.get("account_type")
        
        log_tag = make_log_tag(
            "trial_subscription_resource.py",
            "StartTrialResource",
            "post",
            client_ip,
            user_id,
            account_type,
            business_id,
            business_id,
        )
        
        start_time = time.time()
        Log.info(f"{log_tag} Starting trial subscription")
        
        body = request.get_json(silent=True) or {}
        package_id = body.get("package_id")
        
        if not package_id:
            return jsonify({
                "success": False,
                "message": "package_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            # Validate package exists and is active
            package = Package.get_by_id(package_id)
            
            if not package:
                return jsonify({
                    "success": False,
                    "message": "Package not found",
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            if package.get("status") != Package.STATUS_ACTIVE:
                return jsonify({
                    "success": False,
                    "message": "Package is not available",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # Check trial eligibility
            trial_status = Subscription.get_trial_status(business_id)
            
            if not trial_status.get("can_start_trial"):
                if trial_status.get("is_on_trial"):
                    return jsonify({
                        "success": False,
                        "message": "You are already on a trial",
                        "code": "ALREADY_ON_TRIAL",
                        "data": {
                            "trial_days_remaining": trial_status.get("trial_days_remaining"),
                            "trial_end_date": trial_status.get("trial_end_date"),
                        },
                    }), HTTP_STATUS_CODES["CONFLICT"]
                
                if trial_status.get("has_used_trial"):
                    return jsonify({
                        "success": False,
                        "message": "You have already used your free trial. Please subscribe to continue.",
                        "code": "TRIAL_ALREADY_USED",
                    }), HTTP_STATUS_CODES["FORBIDDEN"]
            
            # Check for existing active subscription
            existing_sub = Subscription.get_active_by_business(business_id)
            if existing_sub:
                status = existing_sub.get("status")
                if status == Subscription.STATUS_ACTIVE:
                    return jsonify({
                        "success": False,
                        "message": "You already have an active subscription",
                        "code": "ALREADY_SUBSCRIBED",
                    }), HTTP_STATUS_CODES["CONFLICT"]
            
            # Create trial subscription
            trial_days = Subscription.DEFAULT_TRIAL_DAYS  # 30 days
            
            subscription = Subscription.create_trial_subscription(
                business_id=business_id,
                user_id=user_id,
                package_id=package_id,
                trial_days=trial_days,
                log_tag=log_tag,
            )
            
            if not subscription:
                return jsonify({
                    "success": False,
                    "message": "Failed to start trial. Please try again.",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Trial started successfully in {duration:.2f}s")
            
            subscription["business_id"] = str(subscription.get("business_id"))
            subscription["user_id"] = str(subscription.get("user_id"))
            subscription["package_id"] = str(subscription.get("package_id"))
            
            #Send email notification
            try:
                from ....services.email_service import send_trial_started_email
                from ....models.business_model import Business
                
                business = Business.get_business_by_id(business_id)
                email = business.get("email") if business else None
                business_name = business.get("business_name") if business else None
                
                dashboard_url = os.getenv("DASHBOARD_URL", "https://app.schedulefy.org/dashboard")
                
                trial_email_response = send_trial_started_email(
                    email=email,
                    fullname=business_name,
                    plan_name=package.get("name"),
                    trial_days=subscription.get("trial_days"),
                    trial_start_date=subscription.get("trial_start_date"),
                    trial_end_date=subscription.get("trial_end_date"),
                    dashboard_url=dashboard_url
                )
                Log.info(f"{log_tag} Trial started email sent: {trial_email_response}")
            except Exception as e:
                Log.error(f"{log_tag} Error sending trial started email: {e}")
                
            
            return jsonify({
                "success": True,
                "message": "Trial started successfully! You have 30 days to explore all features.",
                "data": {
                    "subscription": subscription,
                    "trial_info": {
                        "days_remaining": trial_days,
                        "end_date": subscription.get("trial_end_date"),
                    },
                    "package": {
                        "name": package.get("name"),
                        "tier": package.get("tier"),
                        "features": package.get("features"),
                    },
                },
            }), HTTP_STATUS_CODES["CREATED"]
            
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Error after {duration:.2f}s: {e}")
            import traceback
            traceback.print_exc()
            
            return jsonify({
                "success": False,
                "message": "Failed to start trial",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# GET TRIAL STATUS
# =========================================
@trial_status_limiter("trial_status")
@blp_trial_subscription.route("/subscription/trial/status", methods=["GET"])
class TrialStatusResource(MethodView):
    """
    Get current trial status for the authenticated user's business.
    
    Returns:
    {
        "success": true,
        "data": {
            "has_used_trial": false,
            "is_on_trial": false,
            "trial_days_remaining": null,
            "trial_end_date": null,
            "trial_expired": false,
            "can_start_trial": true,
            "subscription": null
        }
    }
    """
    
    @token_required
    def get(self):
        client_ip = request.remote_addr
        
        user_info = g.get("current_user", {}) or {}
        business_id = str(user_info.get("business_id", ""))
        
        log_tag = f"[trial_subscription_resource.py][TrialStatusResource][get][{client_ip}][{business_id}]"
        
        try:
            # Get trial status
            trial_status = Subscription.get_trial_status(business_id)
            
            # Get current subscription if any
            subscription = Subscription.get_active_by_business(business_id)
            
            # Get latest subscription if no active one
            if not subscription:
                subscription = Subscription.get_latest_by_business(business_id)
            
            return jsonify({
                "success": True,
                "data": {
                    **trial_status,
                    "subscription": subscription,
                },
            }), HTTP_STATUS_CODES["OK"]
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to get trial status",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# =========================================
# CONVERT TRIAL TO PAID
# =========================================
@trial_convert_limiter("trial_convert")
@blp_trial_subscription.route("/subscription/trial/convert", methods=["POST"])
class ConvertTrialResource(MethodView):
    """
    Convert a trial subscription to a paid subscription.
    
    This is called after successful payment processing.
    
    Body:
    {
        "subscription_id": "...",
        "billing_period": "monthly",
        "payment_reference": "PAY_123456",  // REQUIRED - must exist and be successful
        "payment_method": "card",
        "auto_renew": true
    }
    
    Note: price_paid and currency are retrieved from the verified payment record.
    """
    
    @token_required
    def post(self):
        client_ip = request.remote_addr
        
        user_info = g.get("current_user", {}) or {}
        business_id = str(user_info.get("business_id", ""))
        user_id = str(user_info.get("_id", ""))
        
        log_tag = f"[trial_subscription_resource.py][ConvertTrialResource][post][{client_ip}][{business_id}]"
        
        start_time = time.time()
        Log.info(f"{log_tag} Converting trial to paid subscription")
        
        body = request.get_json(silent=True) or {}
        subscription_id = body.get("subscription_id")
        payment_reference = body.get("payment_reference")
        
        # =========================================
        # 1. VALIDATE REQUIRED FIELDS
        # =========================================
        if not subscription_id:
            return jsonify({
                "success": False,
                "message": "subscription_id is required",
                "code": "MISSING_SUBSCRIPTION_ID",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if not payment_reference:
            return jsonify({
                "success": False,
                "message": "payment_reference is required",
                "code": "MISSING_PAYMENT_REFERENCE",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            # =========================================
            # 2. VERIFY SUBSCRIPTION EXISTS AND BELONGS TO BUSINESS
            # =========================================
            subscription_col = db.get_collection(Subscription.collection_name)
            subscription = subscription_col.find_one({
                "_id": ObjectId(subscription_id),
                "business_id": ObjectId(business_id),
            })
            
            if not subscription:
                Log.info(f"{log_tag} Subscription not found: {subscription_id}")
                return jsonify({
                    "success": False,
                    "message": "Subscription not found",
                    "code": "SUBSCRIPTION_NOT_FOUND",
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            # =========================================
            # 3. VERIFY SUBSCRIPTION IS A TRIAL
            # =========================================
            if not subscription.get("is_trial"):
                Log.info(f"{log_tag} Subscription is not a trial: {subscription_id}")
                return jsonify({
                    "success": False,
                    "message": "This subscription is not a trial and cannot be converted",
                    "code": "NOT_A_TRIAL",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # Check if already converted
            decrypted_status = Subscription._safe_decrypt(subscription.get("status"))
            if decrypted_status == Subscription.STATUS_ACTIVE:
                Log.info(f"{log_tag} Trial already converted: {subscription_id}")
                return jsonify({
                    "success": False,
                    "message": "This trial has already been converted to a paid subscription",
                    "code": "ALREADY_CONVERTED",
                }), HTTP_STATUS_CODES["CONFLICT"]
            
            # =========================================
            # 4. VERIFY PAYMENT EXISTS
            # =========================================
            payment = Payment.get_by_reference(payment_reference)
            
            # Also try by order_id if not found by reference
            if not payment:
                payment = Payment.get_by_order_id(payment_reference)
            
            # Also try by gateway_transaction_id
            if not payment:
                payment = Payment.get_by_gateway_transaction_id(payment_reference)
            
            if not payment:
                Log.info(f"{log_tag} Payment not found: {payment_reference}")
                return jsonify({
                    "success": False,
                    "message": "Payment reference not found. Please ensure the payment was completed.",
                    "code": "PAYMENT_NOT_FOUND",
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            Log.info(f"{log_tag} Payment found: {payment.get('_id')}, status: {payment.get('status')}")
            
            # =========================================
            # 5. VERIFY PAYMENT BELONGS TO THIS BUSINESS
            # =========================================
            if str(payment.get("business_id")) != business_id:
                Log.warning(f"{log_tag} Payment business mismatch. Payment business: {payment.get('business_id')}, Request business: {business_id}")
                return jsonify({
                    "success": False,
                    "message": "Payment does not belong to this account",
                    "code": "PAYMENT_BUSINESS_MISMATCH",
                }), HTTP_STATUS_CODES["FORBIDDEN"]
            
            # =========================================
            # 6. VERIFY PAYMENT STATUS IS SUCCESS
            # =========================================
            payment_status = payment.get("status")
            
            if payment_status == Payment.STATUS_PENDING:
                Log.info(f"{log_tag} Payment still pending: {payment_reference}")
                return jsonify({
                    "success": False,
                    "message": "Payment is still being processed. Please wait for confirmation.",
                    "code": "PAYMENT_PENDING",
                    "data": {
                        "payment_status": payment_status,
                        "payment_id": payment.get("_id"),
                    },
                }), HTTP_STATUS_CODES["ACCEPTED"]  # 202 - request accepted but not yet completed
            
            if payment_status == Payment.STATUS_PROCESSING:
                Log.info(f"{log_tag} Payment still processing: {payment_reference}")
                return jsonify({
                    "success": False,
                    "message": "Payment is still being processed. Please wait for confirmation.",
                    "code": "PAYMENT_PROCESSING",
                    "data": {
                        "payment_status": payment_status,
                        "payment_id": payment.get("_id"),
                    },
                }), HTTP_STATUS_CODES["ACCEPTED"]
            
            if payment_status == Payment.STATUS_FAILED:
                Log.info(f"{log_tag} Payment failed: {payment_reference}")
                return jsonify({
                    "success": False,
                    "message": "Payment failed. Please try again with a different payment method.",
                    "code": "PAYMENT_FAILED",
                    "data": {
                        "payment_status": payment_status,
                        "error_message": payment.get("error_message"),
                    },
                }), HTTP_STATUS_CODES["PAYMENT_REQUIRED"]
            
            if payment_status == Payment.STATUS_CANCELLED:
                Log.info(f"{log_tag} Payment cancelled: {payment_reference}")
                return jsonify({
                    "success": False,
                    "message": "Payment was cancelled. Please make a new payment.",
                    "code": "PAYMENT_CANCELLED",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            if payment_status == Payment.STATUS_REFUNDED:
                Log.info(f"{log_tag} Payment refunded: {payment_reference}")
                return jsonify({
                    "success": False,
                    "message": "This payment has been refunded and cannot be used.",
                    "code": "PAYMENT_REFUNDED",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            if payment_status != Payment.STATUS_SUCCESS:
                Log.info(f"{log_tag} Payment not successful: {payment_reference}, status: {payment_status}")
                return jsonify({
                    "success": False,
                    "message": f"Payment has not been completed successfully. Current status: {payment_status}",
                    "code": "PAYMENT_NOT_SUCCESSFUL",
                    "data": {
                        "payment_status": payment_status,
                    },
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # =========================================
            # 7. VERIFY PAYMENT HAS NOT BEEN USED FOR ANOTHER SUBSCRIPTION
            # =========================================
            payment_id = payment.get("_id")
            
            # Check if this payment is already linked to a subscription
            existing_subscription_with_payment = subscription_col.find_one({
                "payment_id": ObjectId(payment_id) if not isinstance(payment_id, ObjectId) else payment_id,
            })
            
            if existing_subscription_with_payment:
                existing_sub_id = str(existing_subscription_with_payment.get("_id"))
                
                # Allow if it's the same subscription being re-processed
                if existing_sub_id != subscription_id:
                    Log.warning(f"{log_tag} Payment already used for subscription: {existing_sub_id}")
                    return jsonify({
                        "success": False,
                        "message": "This payment has already been applied to another subscription",
                        "code": "PAYMENT_ALREADY_USED",
                        "data": {
                            "existing_subscription_id": existing_sub_id,
                        },
                    }), HTTP_STATUS_CODES["CONFLICT"]
            
            # Also check by payment_reference field in subscriptions
            existing_sub_by_ref = subscription_col.find_one({
                "payment_reference": payment_reference,
                "_id": {"$ne": ObjectId(subscription_id)},  # Exclude current subscription
            })
            
            if existing_sub_by_ref:
                existing_sub_id = str(existing_sub_by_ref.get("_id"))
                Log.warning(f"{log_tag} Payment reference already used for subscription: {existing_sub_id}")
                return jsonify({
                    "success": False,
                    "message": "This payment reference has already been used for another subscription",
                    "code": "PAYMENT_REFERENCE_ALREADY_USED",
                    "data": {
                        "existing_subscription_id": existing_sub_id,
                    },
                }), HTTP_STATUS_CODES["CONFLICT"]
            
            # =========================================
            # 8. VERIFY PAYMENT AMOUNT MATCHES PACKAGE PRICE (Optional but recommended)
            # =========================================
            package_id = subscription.get("package_id")
            if package_id:
                package = Package.get_by_id(str(package_id))
                
                if package:
                    expected_price = package.get("price")
                    paid_amount = payment.get("amount", 0)
                    
                    # Allow for small floating point differences
                    if expected_price is not None and abs(float(paid_amount) - float(expected_price)) > 0.01:
                        Log.warning(f"{log_tag} Payment amount mismatch. Expected: {expected_price}, Paid: {paid_amount}")
                        # This is a warning, not a blocker - you might have discounts, promotions, etc.
                        # Uncomment below to make it a hard requirement:
                        # return jsonify({
                        #     "success": False,
                        #     "message": f"Payment amount ({paid_amount}) does not match package price ({expected_price})",
                        #     "code": "AMOUNT_MISMATCH",
                        # }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # =========================================
            # 9. VERIFY PAYMENT TYPE IS SUBSCRIPTION-RELATED
            # =========================================
            payment_type = payment.get("payment_type")
            valid_payment_types = [
                Payment.TYPE_SUBSCRIPTION,
                Payment.TYPE_RENEWAL,
                Payment.TYPE_PURCHASE,
            ]
            
            if payment_type and payment_type not in valid_payment_types:
                Log.warning(f"{log_tag} Invalid payment type: {payment_type}")
                return jsonify({
                    "success": False,
                    "message": f"This payment type ({payment_type}) cannot be used for subscription activation",
                    "code": "INVALID_PAYMENT_TYPE",
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            # =========================================
            # 10. ALL VALIDATIONS PASSED - CONVERT TRIAL TO PAID
            # =========================================
            Log.info(f"{log_tag} All validations passed. Converting trial to paid subscription.")
            
            # Build payment data from verified payment record
            payment_data = {
                "billing_period": body.get("billing_period", "monthly"),
                "payment_reference": payment_reference,
                "payment_id": str(payment_id),
                "payment_method": payment.get("payment_method") or body.get("payment_method"),
                "price_paid": payment.get("amount", 0),  # Use amount from verified payment
                "currency": payment.get("currency", "GBP"),  # Use currency from verified payment
                "auto_renew": body.get("auto_renew", True),
                "gateway": payment.get("gateway"),
                "gateway_transaction_id": payment.get("gateway_transaction_id"),
            }
            
            updated_subscription = Subscription.convert_trial_to_paid(
                subscription_id=subscription_id,
                payment_data=payment_data,
                log_tag=log_tag,
            )
            
            if not updated_subscription:
                Log.error(f"{log_tag} Failed to convert trial to paid")
                return jsonify({
                    "success": False,
                    "message": "Failed to convert trial to paid subscription. Please contact support.",
                    "code": "CONVERSION_FAILED",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            
            # =========================================
            # 11. UPDATE PAYMENT RECORD TO LINK TO SUBSCRIPTION
            # =========================================
            try:
                payment_col = db.get_collection(Payment.collection_name)
                payment_col.update_one(
                    {"_id": ObjectId(payment_id)},
                    {
                        "$set": {
                            "subscription_id": ObjectId(subscription_id),
                            "applied_to_subscription": True,
                            "applied_at": datetime.utcnow(),
                            "updated_at": datetime.utcnow(),
                        }
                    }
                )
                Log.info(f"{log_tag} Payment linked to subscription")
            except Exception as e:
                Log.error(f"{log_tag} Failed to update payment record: {e}")
                # Don't fail the whole operation, subscription is already converted
            
            duration = time.time() - start_time
            Log.info(f"{log_tag} Trial converted successfully in {duration:.2f}s")
            
            return jsonify({
                "success": True,
                "message": "Subscription activated successfully! Thank you for your purchase.",
                "data": {
                    "subscription": updated_subscription,
                    "payment": {
                        "payment_id": str(payment_id),
                        "amount": payment.get("amount"),
                        "currency": payment.get("currency"),
                        "payment_method": payment.get("payment_method"),
                        "gateway": payment.get("gateway"),
                    },
                },
            }), HTTP_STATUS_CODES["OK"]
            
        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Error after {duration:.2f}s: {e}")
            import traceback
            traceback.print_exc()
            
            return jsonify({
                "success": False,
                "message": "Failed to convert trial. Please contact support.",
                "code": "INTERNAL_ERROR",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# =========================================
# GET AVAILABLE PACKAGES FOR TRIAL
# =========================================
@read_protected_user_limiter("package_for_trial")
@blp_trial_subscription.route("/subscription/packages", methods=["GET"])
class AvailablePackagesResource(MethodView):
    """
    Get available packages with trial information.
    
    Returns packages that the user can trial or subscribe to.
    """
    
    @token_required
    def get(self):
        client_ip = request.remote_addr
        
        user_info = g.get("current_user", {}) or {}
        business_id = str(user_info.get("business_id", ""))
        
        log_tag = f"[trial_subscription_resource.py][AvailablePackagesResource][get][{client_ip}]"
        
        try:
            # Get active packages
            packages_result = Package.get_all_active(page=1, per_page=10)
            packages = packages_result.get("packages", [])
            
            # Get trial status
            trial_status = Subscription.get_trial_status(business_id)
            
            # Get current subscription
            current_subscription = Subscription.get_active_by_business(business_id)
            
            return jsonify({
                "success": True,
                "data": {
                    "packages": packages,
                    "trial_status": trial_status,
                    "current_subscription": current_subscription,
                    "trial_days": Subscription.DEFAULT_TRIAL_DAYS,
                },
            }), HTTP_STATUS_CODES["OK"]
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            
            return jsonify({
                "success": False,
                "message": "Failed to get packages",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# CANCEL SUBSCRIPTION
# =========================================
@trial_cancel_limiter("trial_cancel")
@blp_trial_subscription.route("/subscription/trial/cancel", methods=["POST"])
class CancelSubscriptionResource(MethodView):
    """
    Cancel an active or trial subscription.

    This does NOT delete history.
    It marks the subscription as CANCELLED.

    Body:
    {
        "subscription_id": "...",          // REQUIRED
        "reason": "No longer needed"        // OPTIONAL
    }
    """

    @token_required
    def post(self):
        client_ip = request.remote_addr
        start_time = time.time()

        user_info = g.get("current_user", {}) or {}
        business_id = str(user_info.get("business_id", ""))
        user_id = str(user_info.get("_id", ""))

        log_tag = (
            f"[subscription_resource.py][CancelSubscriptionResource]"
            f"[post][{client_ip}][{business_id}]"
        )

        Log.info(f"{log_tag} Cancel subscription request received")

        body = request.get_json(silent=True) or {}
        subscription_id = body.get("subscription_id")
        reason = body.get("reason")

        # =========================================
        # 1. VALIDATE INPUT
        # =========================================
        if not subscription_id:
            Log.info(f"{log_tag} Missing subscription_id in request body")
            return prepared_response(False, "BAD_REQUEST", "subscription_id is required")

        try:
            subscription_col = db.get_collection(Subscription.collection_name)

            # =========================================
            # 2. FETCH SUBSCRIPTION & VERIFY OWNERSHIP
            # =========================================
            subscription = subscription_col.find_one({
                "_id": ObjectId(subscription_id),
                "business_id": ObjectId(business_id),
            })

            if not subscription:
                Log.info(f"{log_tag} Subscription not found: {subscription_id}")
                return prepared_response(False, "NOT_FOUND", "Subscription not found")

            decrypted_status = Subscription._safe_decrypt(subscription.get("status"))

            # =========================================
            # 3. BLOCK INVALID STATES
            # =========================================
            if decrypted_status in [
                Subscription.STATUS_CANCELLED,
                Subscription.STATUS_EXPIRED,
            ]:
                Log.info(f"{log_tag} Subscription already inactive: {subscription_id}")
                return jsonify({
                    "success": True,
                    "message": "Subscription is already inactive",
                    "data": {
                        "subscription_id": subscription_id,
                        "status": decrypted_status,
                    },
                }), HTTP_STATUS_CODES["OK"]

            if decrypted_status == Subscription.STATUS_SUSPENDED:
                Log.info(f"{log_tag} Cancelling suspended subscription")

            # =========================================
            # 4. PERFORM CANCELLATION
            # =========================================
            now = datetime.utcnow()

            update_doc = {
                "status": encrypt_data(Subscription.STATUS_CANCELLED),
                "hashed_status": hash_data(Subscription.STATUS_CANCELLED),
                "cancelled_at": now,
                "cancelled_by": ObjectId(user_id),
                "updated_at": now,
            }

            if reason:
                update_doc["cancellation_reason"] = encrypt_data(reason)

            subscription_col.update_one(
                {"_id": ObjectId(subscription_id)},
                {"$set": update_doc},
            )

            Log.info(f"{log_tag} Subscription cancelled successfully")

            # =========================================
            # 5. UPDATE BUSINESS ACCOUNT STATUS
            # =========================================
            Subscription._update_business_subscription_status(
                business_id=business_id,
                subscribed=False,
                is_trial=bool(subscription.get("is_trial")),
                log_tag=log_tag,
            )

            duration = time.time() - start_time
            Log.info(f"{log_tag} Completed in {duration:.2f}s")

            return jsonify({
                "success": True,
                "message": "Subscription cancelled successfully",
                "data": {
                    "subscription_id": subscription_id,
                    "cancelled_at": now.isoformat(),
                    "previous_status": decrypted_status,
                },
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            duration = time.time() - start_time
            Log.error(f"{log_tag} Error after {duration:.2f}s: {e}", exc_info=True)
            
            return prepared_response(False, "INTERNAL_ERROR", "Failed to cancel subscription. Please contact support.")








































