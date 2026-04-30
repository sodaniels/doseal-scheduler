# app/utils/payments/paypal_utils.py

"""
PayPal Payment Utilities (Orders API v2)
==========================================
Uses PayPal's REST Orders API for checkout flow:
  1. Get access token (client credentials)
  2. Create Order → returns approval_url
  3. Customer approves on PayPal
  4. Capture Order → completes payment

Supports: PayPal balance, cards, Pay Later, Venmo (US).

Environment variables:
  PAYPAL_CLIENT_ID       - From Developer Dashboard
  PAYPAL_CLIENT_SECRET   - From Developer Dashboard
  PAYPAL_MODE            - "sandbox" or "live"
  PAYPAL_WEBHOOK_ID      - Webhook ID for signature verification
"""

import os
import json
import hashlib
import hmac
import base64
import time
import requests
from ..logger import Log


# ── Config ──

def _get_config():
    mode = os.getenv("PAYPAL_MODE", "sandbox").strip().lower()
    return {
        "client_id": os.getenv("PAYPAL_CLIENT_ID", ""),
        "client_secret": os.getenv("PAYPAL_CLIENT_SECRET", ""),
        "mode": mode,
        "base_url": (
            "https://api-m.paypal.com"
            if mode == "live"
            else "https://api-m.sandbox.paypal.com"
        ),
        "webhook_id": os.getenv("PAYPAL_WEBHOOK_ID", ""),
    }


# ═══════════════════════════════════════════════════════════════
# ACCESS TOKEN (OAuth 2.0 Client Credentials)
# ═══════════════════════════════════════════════════════════════

_token_cache = {"token": None, "expires_at": 0}


def get_access_token():
    """
    Get an OAuth 2.0 access token from PayPal.
    Caches the token until expiry.
    """
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"], None

    config = _get_config()
    if not config["client_id"] or not config["client_secret"]:
        return None, "PayPal client_id or client_secret not configured"

    try:
        response = requests.post(
            f"{config['base_url']}/v1/oauth2/token",
            headers={
                "Accept": "application/json",
                "Accept-Language": "en_US",
            },
            data={"grant_type": "client_credentials"},
            auth=(config["client_id"], config["client_secret"]),
            timeout=30,
        )

        result = response.json()

        if response.status_code == 200 and result.get("access_token"):
            _token_cache["token"] = result["access_token"]
            _token_cache["expires_at"] = now + int(result.get("expires_in", 3600))
            return result["access_token"], None
        else:
            error = result.get("error_description") or result.get("error") or "Token request failed"
            Log.error(f"[paypal_utils.get_access_token] {error}")
            return None, error
        
    except requests.exceptions.JSONDecodeError:
        return None, f"Non-JSON response from M-Pesa OAuth (HTTP {response.status_code}): {response.text[:200]}"
    
    except Exception as e:
        Log.error(f"[paypal_utils.get_access_token] {e}", exc_info=True)
        return None, str(e)


def _auth_headers():
    token, error = get_access_token()
    if not token:
        raise Exception(f"PayPal auth failed: {error}")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


# ═══════════════════════════════════════════════════════════════
# CREATE ORDER
# ═══════════════════════════════════════════════════════════════

def create_order(
    amount,
    currency="USD",
    reference=None,
    description=None,
    return_url=None,
    cancel_url=None,
    customer_email=None,
    customer_name=None,
    metadata=None,
):
    """
    Create a PayPal Order (Checkout Session equivalent).
    Customer is redirected to PayPal's approval page.

    Args:
        amount: Amount in major currency unit (e.g. 49.00)
        currency: ISO currency code (USD, GBP, EUR, etc.)
        reference: Your internal payment reference
        description: Order description
        return_url: Redirect after approval
        cancel_url: Redirect if cancelled
        customer_email: Pre-fill payer email
        customer_name: Payer name
        metadata: Additional data (stored in custom_id)

    Returns:
        (success, data, error)
    """
    log_tag = "[paypal_utils.create_order]"
    config = _get_config()

    try:
        # Build metadata string (PayPal custom_id max 127 chars)
        custom_id = reference or ""
        if metadata and isinstance(metadata, dict):
            # Store full metadata as invoice_id (max 127 chars)
            meta_compact = json.dumps({
                k: v for k, v in metadata.items()
                if v is not None and k in (
                    "business_id", "user__id", "package_id",
                    "billing_period", "purchase_type", "reference",
                )
            }, separators=(",", ":"))
            if len(meta_compact) > 127:
                meta_compact = meta_compact[:127]
        else:
            meta_compact = reference or ""

        order_payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": reference or "default",
                    "description": (description or "WorshipDesk Subscription")[:127],
                    "custom_id": custom_id[:127],
                    "invoice_id": reference[:127] if reference else None,
                    "amount": {
                        "currency_code": currency.upper(),
                        "value": f"{float(amount):.2f}",
                    },
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED",
                        "landing_page": "LOGIN",
                        "user_action": "PAY_NOW",
                        "return_url": return_url or "",
                        "cancel_url": cancel_url or "",
                    }
                }
            },
        }

        # Clean None values from purchase_units
        pu = order_payload["purchase_units"][0]
        order_payload["purchase_units"][0] = {k: v for k, v in pu.items() if v is not None}

        if customer_email:
            order_payload["payment_source"]["paypal"]["email_address"] = customer_email

        Log.info(f"{log_tag} Creating order: amount={amount} {currency}, ref={reference}")

        response = requests.post(
            f"{config['base_url']}/v2/checkout/orders",
            json=order_payload,
            headers=_auth_headers(),
            timeout=30,
        )
        result = response.json()

        if response.status_code in (200, 201) and result.get("id"):
            order_id = result["id"]
            approval_url = None

            for link in result.get("links", []):
                if link.get("rel") == "payer-action":
                    approval_url = link.get("href")
                    break
                if link.get("rel") == "approve":
                    approval_url = link.get("href")

            Log.info(f"{log_tag} Order created: {order_id}, status={result.get('status')}")

            return True, {
                "order_id": order_id,
                "checkout_url": approval_url,
                "status": result.get("status"),
                "reference": reference,
                "raw": result,
            }, None
        else:
            details = result.get("details", [])
            error_msg = (
                details[0].get("description") if details
                else result.get("message") or "Failed to create PayPal order"
            )
            Log.error(f"{log_tag} Failed: {error_msg}")
            return False, None, error_msg

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# CAPTURE ORDER (after customer approves)
# ═══════════════════════════════════════════════════════════════

def capture_order(order_id):
    """
    Capture a previously approved PayPal order.
    Call this after the customer returns from PayPal.

    Returns:
        (success, data, error)
    """
    log_tag = f"[paypal_utils.capture_order][{order_id}]"
    config = _get_config()

    try:
        Log.info(f"{log_tag} Capturing order")

        response = requests.post(
            f"{config['base_url']}/v2/checkout/orders/{order_id}/capture",
            json={},
            headers=_auth_headers(),
            timeout=30,
        )
        result = response.json()

        if response.status_code in (200, 201) and result.get("status") == "COMPLETED":
            captures = []
            for pu in result.get("purchase_units", []):
                for cap in (pu.get("payments", {}).get("captures") or []):
                    captures.append(cap)

            capture_id = captures[0].get("id") if captures else None
            payer = result.get("payer", {})

            Log.info(f"{log_tag} Capture successful: capture_id={capture_id}")

            return True, {
                "order_id": order_id,
                "capture_id": capture_id,
                "status": "COMPLETED",
                "payer_email": payer.get("email_address"),
                "payer_name": (
                    f"{payer.get('name', {}).get('given_name', '')} "
                    f"{payer.get('name', {}).get('surname', '')}"
                ).strip(),
                "payer_id": payer.get("payer_id"),
                "captures": captures,
                "raw": result,
            }, None
        else:
            details = result.get("details", [])
            error_msg = (
                details[0].get("description") if details
                else result.get("message") or f"Capture failed: {result.get('status')}"
            )
            Log.error(f"{log_tag} Failed: {error_msg}")
            return False, None, error_msg

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# GET ORDER DETAILS
# ═══════════════════════════════════════════════════════════════

def get_order(order_id):
    """Retrieve order details by PayPal order ID."""
    config = _get_config()
    try:
        response = requests.get(
            f"{config['base_url']}/v2/checkout/orders/{order_id}",
            headers=_auth_headers(),
            timeout=30,
        )
        result = response.json()

        if response.status_code == 200 and result.get("id"):
            payer = result.get("payer", {})
            pu = result.get("purchase_units", [{}])[0]

            return True, {
                "order_id": result["id"],
                "status": result.get("status"),
                "amount": float(pu.get("amount", {}).get("value") or 0),
                "currency": pu.get("amount", {}).get("currency_code"),
                "reference": pu.get("reference_id"),
                "custom_id": pu.get("custom_id"),
                "payer_email": payer.get("email_address"),
                "payer_name": (
                    f"{payer.get('name', {}).get('given_name', '')} "
                    f"{payer.get('name', {}).get('surname', '')}"
                ).strip(),
                "raw": result,
            }, None
        else:
            return False, None, result.get("message") or "Order not found"

    except Exception as e:
        Log.error(f"[paypal_utils.get_order] {e}")
        return False, None, str(e)


def verify_transaction(reference):
    """Verify by PayPal order ID or search by reference."""
    if reference and len(reference) > 10:
        return get_order(reference)
    return False, None, f"Invalid order ID: {reference}"


# ═══════════════════════════════════════════════════════════════
# REFUND
# ═══════════════════════════════════════════════════════════════

def refund_capture(capture_id, amount=None, currency="USD", reason=None):
    """
    Refund a captured payment.

    Args:
        capture_id: The PayPal capture ID (from capture_order)
        amount: Partial refund amount (None = full refund)
        currency: ISO currency code
        reason: Refund reason (max 255 chars)

    Returns:
        (success, data, error)
    """
    log_tag = f"[paypal_utils.refund_capture][{capture_id}]"
    config = _get_config()

    try:
        payload = {}
        if amount is not None:
            payload["amount"] = {
                "value": f"{float(amount):.2f}",
                "currency_code": currency.upper(),
            }
        if reason:
            payload["note_to_payer"] = reason[:255]

        Log.info(f"{log_tag} Refunding: amount={amount}")

        response = requests.post(
            f"{config['base_url']}/v2/payments/captures/{capture_id}/refund",
            json=payload,
            headers=_auth_headers(),
            timeout=30,
        )
        result = response.json()

        if response.status_code in (200, 201) and result.get("id"):
            Log.info(f"{log_tag} Refund created: {result['id']}")
            return True, {
                "refund_id": result["id"],
                "status": result.get("status"),
                "amount": float(result.get("amount", {}).get("value") or 0),
                "raw": result,
            }, None
        else:
            details = result.get("details", [])
            error_msg = (
                details[0].get("description") if details
                else result.get("message") or "Refund failed"
            )
            return False, None, error_msg

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# WEBHOOK SIGNATURE VERIFICATION
# ═══════════════════════════════════════════════════════════════

def verify_webhook_signature(request_headers, raw_body):
    """
    Verify PayPal webhook signature using the API verification endpoint.

    PayPal uses a different approach than HMAC — it requires calling
    their verification API with the event details.

    Args:
        request_headers: Flask request.headers
        raw_body: Raw request body bytes

    Returns:
        bool
    """
    config = _get_config()
    webhook_id = config["webhook_id"]

    if not webhook_id:
        Log.warning("[paypal_utils.verify_webhook_signature] No webhook_id — skipping verification")
        return True

    try:
        transmission_id = request_headers.get("Paypal-Transmission-Id", "")
        timestamp = request_headers.get("Paypal-Transmission-Time", "")
        cert_url = request_headers.get("Paypal-Cert-Url", "")
        auth_algo = request_headers.get("Paypal-Auth-Algo", "")
        transmission_sig = request_headers.get("Paypal-Transmission-Sig", "")

        if not all([transmission_id, timestamp, cert_url, auth_algo, transmission_sig]):
            Log.warning("[paypal_utils] Missing PayPal signature headers")
            return False

        if isinstance(raw_body, bytes):
            raw_body = raw_body.decode("utf-8")

        event_body = json.loads(raw_body)

        verify_payload = {
            "auth_algo": auth_algo,
            "cert_url": cert_url,
            "transmission_id": transmission_id,
            "transmission_sig": transmission_sig,
            "transmission_time": timestamp,
            "webhook_id": webhook_id,
            "webhook_event": event_body,
        }

        response = requests.post(
            f"{config['base_url']}/v1/notifications/verify-webhook-signature",
            json=verify_payload,
            headers=_auth_headers(),
            timeout=30,
        )
        result = response.json()

        verified = result.get("verification_status") == "SUCCESS"
        if not verified:
            Log.warning(f"[paypal_utils] Signature verification: {result.get('verification_status')}")

        return verified

    except Exception as e:
        Log.error(f"[paypal_utils.verify_webhook_signature] Error: {e}")
        return False
