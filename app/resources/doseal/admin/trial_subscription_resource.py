# app/resources/doseal/admin/admin/trial_subscription_resource.py

import os
import time
from datetime import datetime, timezone
from flask_smorest import Blueprint
from flask import request, jsonify, g
from flask.views import MethodView
from bson import ObjectId

from ....constants.service_code import HTTP_STATUS_CODES, SYSTEM_USERS
from ....utils.logger import Log
from ....utils.helpers import make_log_tag
from ....utils.json_response import prepared_response
from ....extensions.db import db

from ....models.admin.subscription_model import Subscription
from ....models.admin.package_model import Package
from ...doseal.admin.admin_business_resource import token_required


blp_trial_subscription = Blueprint("trial_subscription", __name__)


# =========================================
# START TRIAL SUBSCRIPTION
# =========================================
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
@blp_trial_subscription.route("/subscription/trial/convert", methods=["POST"])
class ConvertTrialResource(MethodView):
    """
    Convert a trial subscription to a paid subscription.
    
    This is called after successful payment processing.
    
    Body:
    {
        "subscription_id": "...",
        "billing_period": "monthly",
        "payment_reference": "PAY_123456",
        "payment_method": "card",
        "price_paid": 139.00,
        "currency": "GBP",
        "auto_renew": true
    }
    """
    
    @token_required
    def post(self):
        client_ip = request.remote_addr
        
        user_info = g.get("current_user", {}) or {}
        business_id = str(user_info.get("business_id", ""))
        
        log_tag = f"[trial_subscription_resource.py][ConvertTrialResource][post][{client_ip}][{business_id}]"
        
        body = request.get_json(silent=True) or {}
        subscription_id = body.get("subscription_id")
        
        if not subscription_id:
            return jsonify({
                "success": False,
                "message": "subscription_id is required",
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        try:
            # Verify subscription belongs to this business
            collection = db.get_collection(Subscription.collection_name)
            subscription = collection.find_one({
                "_id": ObjectId(subscription_id),
                "business_id": ObjectId(business_id),
            })
            
            if not subscription:
                return jsonify({
                    "success": False,
                    "message": "Subscription not found",
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            # Convert trial to paid
            payment_data = {
                "billing_period": body.get("billing_period", "monthly"),
                "payment_reference": body.get("payment_reference"),
                "payment_method": body.get("payment_method"),
                "price_paid": body.get("price_paid", 0),
                "currency": body.get("currency", "GBP"),
                "auto_renew": body.get("auto_renew", True),
            }
            
            updated_subscription = Subscription.convert_trial_to_paid(
                subscription_id=subscription_id,
                payment_data=payment_data,
                log_tag=log_tag,
            )
            
            if not updated_subscription:
                return jsonify({
                    "success": False,
                    "message": "Failed to convert trial to paid subscription",
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
            
            return jsonify({
                "success": True,
                "message": "Subscription activated successfully!",
                "data": {
                    "subscription": updated_subscription,
                },
            }), HTTP_STATUS_CODES["OK"]
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            import traceback
            traceback.print_exc()
            
            return jsonify({
                "success": False,
                "message": "Failed to convert trial",
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# =========================================
# GET AVAILABLE PACKAGES FOR TRIAL
# =========================================
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