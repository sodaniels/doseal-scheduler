# app/utils/trial_enforcer.py

from functools import wraps
from datetime import datetime
from flask import g, jsonify

from ..constants.service_code import HTTP_STATUS_CODES
from ..models.admin.subscription_model import Subscription
from ..utils.logger import Log


def require_active_subscription(f):
    """
    Decorator to enforce active subscription (Active or Trial that hasn't expired).
    
    Use this on endpoints that require a paid or trial subscription.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_info = g.get("current_user", {}) or {}
        business_id = str(user_info.get("business_id", ""))
        
        if not business_id:
            return jsonify({
                "success": False,
                "message": "Authentication required",
                "code": "AUTH_REQUIRED",
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]
        
        # Get active subscription
        subscription = Subscription.get_active_by_business(business_id)
        
        if not subscription:
            # Check if trial expired
            trial_status = Subscription.get_trial_status(business_id)
            
            if trial_status.get("trial_expired"):
                return jsonify({
                    "success": False,
                    "message": "Your trial has expired. Please subscribe to continue using this feature.",
                    "code": "TRIAL_EXPIRED",
                    "data": {
                        "trial_expired": True,
                        "upgrade_url": "/pricing",
                    },
                }), HTTP_STATUS_CODES["PAYMENT_REQUIRED"]
            
            return jsonify({
                "success": False,
                "message": "Subscription required. Please subscribe or start a free trial.",
                "code": "SUBSCRIPTION_REQUIRED",
                "data": {
                    "can_start_trial": trial_status.get("can_start_trial", True),
                    "pricing_url": "/pricing",
                },
            }), HTTP_STATUS_CODES["PAYMENT_REQUIRED"]
        
        # Check if trial and if it's expired
        if subscription.get("is_trial"):
            trial_end_date = subscription.get("trial_end_date")
            
            if trial_end_date:
                # Handle both string and datetime
                if isinstance(trial_end_date, str):
                    trial_end_date = datetime.fromisoformat(trial_end_date.replace('Z', '+00:00'))
                
                if datetime.utcnow() > trial_end_date.replace(tzinfo=None):
                    # Expire the trial
                    Subscription.expire_trial(subscription.get("_id"))
                    
                    return jsonify({
                        "success": False,
                        "message": "Your trial has expired. Please subscribe to continue.",
                        "code": "TRIAL_EXPIRED",
                        "data": {
                            "trial_expired": True,
                            "upgrade_url": "/pricing",
                        },
                    }), HTTP_STATUS_CODES["PAYMENT_REQUIRED"]
        
        # Store subscription in g for use in the endpoint
        g.subscription = subscription
        
        return f(*args, **kwargs)
    
    return decorated_function


def check_subscription_status(business_id: str) -> dict:
    """
    Check subscription status for a business.
    
    Returns:
        {
            "has_active_subscription": bool,
            "is_trial": bool,
            "trial_expired": bool,
            "days_remaining": int or None,
            "status": str,
            "subscription": dict or None,
        }
    """
    subscription = Subscription.get_active_by_business(business_id)
    
    if not subscription:
        trial_status = Subscription.get_trial_status(business_id)
        
        return {
            "has_active_subscription": False,
            "is_trial": False,
            "trial_expired": trial_status.get("trial_expired", False),
            "days_remaining": None,
            "status": "expired" if trial_status.get("trial_expired") else "none",
            "subscription": None,
            "can_start_trial": trial_status.get("can_start_trial", True),
        }
    
    is_trial = subscription.get("is_trial", False)
    days_remaining = None
    
    if is_trial:
        trial_end_date = subscription.get("trial_end_date")
        if trial_end_date:
            if isinstance(trial_end_date, str):
                trial_end_date = datetime.fromisoformat(trial_end_date.replace('Z', '+00:00'))
            
            delta = trial_end_date.replace(tzinfo=None) - datetime.utcnow()
            days_remaining = max(0, delta.days)
    
    return {
        "has_active_subscription": True,
        "is_trial": is_trial,
        "trial_expired": False,
        "days_remaining": days_remaining,
        "status": subscription.get("status"),
        "subscription": subscription,
        "can_start_trial": False,
    }