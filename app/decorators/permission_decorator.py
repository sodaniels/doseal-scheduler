# app/decorators/permission_decorator.py

from functools import wraps
from flask import g, request
from ..constants.social_permissions import has_permission
from ..utils.json_response import prepared_response
from ..utils.helpers import make_log_tag, _resolve_business_id
from ..utils.logger import Log


def require_permission(module, action):
    """
    Decorator that logs and checks permission before executing the endpoint.
    Use AFTER @token_required so g.current_user is set.

    Usage:
        @token_required
        @require_permission("donations", "create")
        def post(self, json_data):
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            client_ip = request.remote_addr
            user_info = g.get("current_user", {}) or {}
            account_type = user_info.get("account_type", "")
            auth_user__id = str(user_info.get("_id", ""))
            auth_business_id = str(user_info.get("business_id", ""))

            # Extract resource and method from the function and class
            resource_name = f.__qualname__.rsplit(".", 1)[0] if "." in f.__qualname__ else f.__name__
            method_name = f.__name__

            log_tag = make_log_tag(
                f.__module__.rsplit(".", 1)[-1] + ".py",
                resource_name, method_name,
                client_ip, auth_user__id, account_type,
                auth_business_id, auth_business_id,
            )

            Log.info(f"{log_tag} checking permission: {module}.{action}")

            if not has_permission(user_info, module, action):
                Log.info(f"{log_tag} DENIED: {module}.{action} for account_type={account_type}")
                return prepared_response(
                    False, "FORBIDDEN",
                    f"You don't have permission to {action} {module}."
                )

            Log.info(f"{log_tag} GRANTED: {module}.{action}")
            return f(*args, **kwargs)
        return wrapper
    return decorator

