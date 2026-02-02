# instntmny_api/utils/extensions.py

import os
from flask import request, g, has_request_context
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from .logger import Log


RATE_LIMIT_STORAGE_URI = os.getenv("RATE_LIMIT_STORAGE_URI", "memory://")


def _get_client_ip():
    """Safely get client IP, returns 'unknown' if outside request context."""
    if has_request_context():
        return get_remote_address() or "unknown"
    return "unknown"


def _format_time_period(seconds):
    """Convert seconds to human-readable format."""
    if seconds is None:
        return "unknown"
    
    seconds = int(seconds)
    
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours} hour{'s' if hours != 1 else ''}"
    else:
        days = seconds // 86400
        return f"{days} day{'s' if days != 1 else ''}"


def log_rate_limit_breach(request_limit):
    """
    Callback when a rate limit is breached.
    
    Called automatically by Flask-Limiter when any rate limit is exceeded.
    Provides centralized logging for all rate limit violations.
    """
    client_ip = _get_client_ip()
    user_id = getattr(g, "current_user_id", None) or getattr(
        getattr(g, "current_user", None), "id", None
    ) or "anonymous"
    
    endpoint = request.endpoint or "unknown"
    method = request.method
    path = request.path
    
    # Extract limit details from RequestLimit object
    try:
        limit_amount = request_limit.limit.amount
        limit_per_seconds = request_limit.limit.get_expiry()
        limit_per = _format_time_period(limit_per_seconds)
        limit_str = f"{limit_amount} per {limit_per}"
    except AttributeError:
        limit_str = str(getattr(request_limit, "limit", "unknown"))
    
    limit_key = getattr(request_limit, "key", "unknown")
    
    Log.warning(
        f"[RATE_LIMIT_BREACH][{client_ip}] "
        f"user={user_id}, limit={limit_str}, key={limit_key}, "
        f"method={method}, path={path}, endpoint={endpoint}"
    )


limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=RATE_LIMIT_STORAGE_URI,
    on_breach=log_rate_limit_breach,
)