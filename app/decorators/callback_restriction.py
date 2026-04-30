# app/decorators/callback_restriction.py

from functools import wraps
from flask import request, jsonify
from ..constants.callback_allowed_ips import GATEWAY_ALLOWED_IPS
from ..utils.logger import Log


def _get_client_ip():
    """Extract real client IP, handling reverse proxy / load balancer."""
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.headers.get("X-Real-Ip", "").strip()
    if not client_ip:
        client_ip = request.remote_addr or ""
    return client_ip


def gateway_ip_whitelist(gateway_name):
    """
    Factory decorator for any gateway.
    Usage: @gateway_ip_whitelist("paystack")

    If the gateway has no IP list (None), the decorator is a no-op
    and security relies on signature verification in the handler.
    """
    allowed_ips = GATEWAY_ALLOWED_IPS.get(gateway_name)

    def decorator(f):
        # No IP list — skip filtering, rely on signature
        if allowed_ips is None:
            return f

        @wraps(f)
        def decorated(*args, **kwargs):
            client_ip = _get_client_ip()

            if client_ip not in allowed_ips:
                Log.warning(
                    f"[{gateway_name}_ip_whitelist] BLOCKED: ip={client_ip} "
                    f"endpoint={request.path} method={request.method}"
                )
                return jsonify({"code": 403, "message": "Forbidden: IP not allowed"}), 403

            Log.info(f"[{gateway_name}_ip_whitelist] ALLOWED: ip={client_ip}")
            return f(*args, **kwargs)

        return decorated
    return decorator


# ── Convenience shortcuts (one-liner per gateway) ──

def paystack_ip_whitelist(f):
    """Restrict to Paystack webhook IPs."""
    return gateway_ip_whitelist("paystack")(f)

def stripe_ip_whitelist(f):
    """Restrict to Stripe webhook IPs."""
    return gateway_ip_whitelist("stripe")(f)

def hubtel_ip_whitelist(f):
    """Restrict to Hubtel webhook IPs."""
    return gateway_ip_whitelist("hubtel")(f)

def asoriba_ip_whitelist(f):
    """Asoriba — no IP list, signature only."""
    return gateway_ip_whitelist("asoriba")(f)

def flutterwave_ip_whitelist(f):
    """Flutterwave — add IPs when implemented."""
    return gateway_ip_whitelist("flutterwave")(f)

def paypal_ip_whitelist(f):
    """PayPal — no IP list, API signature verification."""
    return gateway_ip_whitelist("paypal")(f)

def mpesa_ip_whitelist(f):
    """M-Pesa — no published IPs, validation via CheckoutRequestID."""
    return gateway_ip_whitelist("mpesa")(f)

