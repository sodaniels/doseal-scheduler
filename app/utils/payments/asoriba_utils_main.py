# app/utils/payments/asoriba_utils.py

"""
Asoriba / MyBusinessPay Payment Utilities
============================================
Asoriba uses MyBusinessPay (app.mybusinesspay.com) as their payment gateway.
Supports: Ghana-issued cards, international cards, and mobile money (MTN, Vodafone, AirtelTigo).

API Flow:
  1. Initialize payment → returns checkout_url or USSD prompt
  2. Customer completes payment on Asoriba's hosted page or via USSD
  3. Webhook callback hits our server with payment status
  4. Verify transaction for confirmation

Environment variables:
  ASORIBA_PUBLIC_KEY     - Your MyBusinessPay public key
  ASORIBA_SECRET_KEY     - Your MyBusinessPay secret key
  ASORIBA_BASE_URL       - API base URL (default: https://payment.asoriba.com)
  ASORIBA_WEBHOOK_SECRET - Webhook signature secret for verification
"""

import os
import hmac
import hashlib
import requests
from ..logger import Log


# ── Config ──
def _get_config():
    return {
        "public_key": os.getenv("ASORIBA_PUBLIC_KEY", ""),
        "secret_key": os.getenv("ASORIBA_SECRET_KEY", ""),
        "base_url": os.getenv("ASORIBA_BASE_URL", "https://payment.asoriba.com"),
        "webhook_secret": os.getenv("ASORIBA_WEBHOOK_SECRET", ""),
    }


def _headers():
    config = _get_config()
    return {
        "Authorization": f"Bearer {config['secret_key']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ═══════════════════════════════════════════════════════════════
# INITIALIZE PAYMENT
# ═══════════════════════════════════════════════════════════════

def initialize_payment(
    amount,
    currency="GHS",
    email=None,
    first_name=None,
    last_name=None,
    phone_number=None,
    reference=None,
    callback_url=None,
    webhook_url=None,
    description=None,
    metadata=None,
    payment_method=None,
):
    """
    Initialize a payment on Asoriba/MyBusinessPay.

    Args:
        amount: Amount in major currency unit (e.g. 50.00 GHS)
        currency: GHS, USD, GBP, EUR
        email: Customer email
        first_name: Customer first name
        last_name: Customer last name
        phone_number: Mobile money number (for USSD/MoMo payments)
        reference: Your unique payment reference
        callback_url: URL to redirect customer after payment
        webhook_url: URL for server-to-server notification
        description: Payment description
        metadata: Dict of additional data to pass through
        payment_method: "card", "mobile_money", or None for all

    Returns:
        (success, data, error)
        data includes: checkout_url, reference, access_code
    """
    log_tag = "[asoriba_utils.initialize_payment]"
    config = _get_config()

    if not config["public_key"] or not config["secret_key"]:
        return False, None, "Asoriba API keys not configured"

    try:
        payload = {
            "amount": float(amount),
            "currency": currency.upper(),
            "publicKey": config["public_key"],
            "description": description or "WorshipDesk Subscription Payment",
        }

        if email:
            payload["email"] = email
        if first_name:
            payload["first_name"] = first_name
        if last_name:
            payload["last_name"] = last_name
        if phone_number:
            payload["phone_number"] = phone_number
        if reference:
            payload["reference"] = reference
        if callback_url:
            payload["callback_url"] = callback_url
        if webhook_url:
            payload["webhook_url"] = webhook_url
        if metadata:
            payload["metadata"] = metadata
        if payment_method:
            payload["payment_method"] = payment_method

        url = f"{config['base_url']}/api/v1/payment/initialize"

        Log.info(f"{log_tag} Initializing: amount={amount} {currency}, ref={reference}")

        response = requests.post(url, json=payload, headers=_headers(), timeout=30)
        result = response.json()

        Log.info(f"{log_tag} Response: status={response.status_code}")

        if response.status_code in (200, 201) and result.get("status") in (True, "success"):
            data = result.get("data", {})
            return True, {
                "checkout_url": data.get("checkout_url") or data.get("authorization_url") or data.get("link"),
                "reference": data.get("reference") or reference,
                "access_code": data.get("access_code"),
                "raw": data,
            }, None
        else:
            error_msg = result.get("message") or result.get("error") or "Payment initialization failed"
            Log.error(f"{log_tag} Failed: {error_msg}")
            return False, None, error_msg

    except requests.Timeout:
        Log.error(f"{log_tag} Request timed out")
        return False, None, "Asoriba payment request timed out"
    except requests.RequestException as e:
        Log.error(f"{log_tag} Request error: {e}")
        return False, None, f"Network error: {str(e)}"
    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# INITIALIZE MOBILE MONEY (USSD) PAYMENT
# ═══════════════════════════════════════════════════════════════

def initialize_mobile_money(
    amount,
    phone_number,
    network,
    first_name=None,
    last_name=None,
    reference=None,
    webhook_url=None,
    description=None,
    metadata=None,
):
    """
    Initialize a mobile money payment directly (USSD prompt).

    Args:
        amount: Amount in GHS
        phone_number: Customer's mobile money number
        network: "mtn", "vodafone", "airteltigo"
        first_name: Customer first name
        last_name: Customer last name
        reference: Your unique payment reference
        webhook_url: Webhook callback URL
        description: Payment description
        metadata: Additional data

    Returns:
        (success, data, error)
    """
    log_tag = "[asoriba_utils.initialize_mobile_money]"
    config = _get_config()

    if not config["public_key"] or not config["secret_key"]:
        return False, None, "Asoriba API keys not configured"

    network_map = {
        "mtn": "MTN",
        "vodafone": "VOD",
        "airteltigo": "ATL",
        "tigo": "ATL",
    }

    network_code = network_map.get(network.lower(), network.upper())

    try:
        payload = {
            "amount": float(amount),
            "currency": "GHS",
            "publicKey": config["public_key"],
            "phone_number": phone_number,
            "network": network_code,
            "description": description or "WorshipDesk Subscription Payment",
        }

        if first_name:
            payload["first_name"] = first_name
        if last_name:
            payload["last_name"] = last_name
        if reference:
            payload["reference"] = reference
        if webhook_url:
            payload["webhook_url"] = webhook_url
        if metadata:
            payload["metadata"] = metadata

        url = f"{config['base_url']}/api/v1/payment/mobile-money"

        Log.info(f"{log_tag} MoMo payment: amount={amount} GHS, phone={phone_number}, network={network_code}")

        response = requests.post(url, json=payload, headers=_headers(), timeout=30)
        result = response.json()

        if response.status_code in (200, 201) and result.get("status") in (True, "success"):
            data = result.get("data", {})
            return True, {
                "reference": data.get("reference") or reference,
                "ussd_code": data.get("ussd_code"),
                "message": data.get("message") or "Please check your phone to approve the payment",
                "raw": data,
            }, None
        else:
            error_msg = result.get("message") or "Mobile money payment failed"
            Log.error(f"{log_tag} Failed: {error_msg}")
            return False, None, error_msg

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# VERIFY TRANSACTION
# ═══════════════════════════════════════════════════════════════

def verify_transaction(reference):
    """
    Verify a transaction status by reference.

    Returns:
        (success, data, error)
    """
    log_tag = f"[asoriba_utils.verify_transaction][ref={reference}]"
    config = _get_config()

    if not config["secret_key"]:
        return False, None, "Asoriba secret key not configured"

    try:
        url = f"{config['base_url']}/api/v1/payment/verify/{reference}"

        Log.info(f"{log_tag} Verifying transaction")

        response = requests.get(url, headers=_headers(), timeout=30)
        result = response.json()

        if response.status_code == 200 and result.get("status") in (True, "success"):
            data = result.get("data", {})
            txn_status = (data.get("status") or "").lower()

            return True, {
                "status": txn_status,
                "reference": data.get("reference") or reference,
                "amount": data.get("amount"),
                "currency": data.get("currency"),
                "customer": data.get("customer", {}),
                "payment_method": data.get("payment_method") or data.get("channel"),
                "paid_at": data.get("paid_at") or data.get("completed_at"),
                "gateway_response": data.get("gateway_response") or data.get("message"),
                "raw": data,
            }, None
        else:
            error_msg = result.get("message") or "Verification failed"
            Log.error(f"{log_tag} Failed: {error_msg}")
            return False, None, error_msg

    except requests.Timeout:
        return False, None, "Verification request timed out"
    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# REFUND
# ═══════════════════════════════════════════════════════════════

def refund_transaction(reference, amount=None, reason=None):
    """
    Initiate a refund for a completed transaction.

    Args:
        reference: Original transaction reference
        amount: Partial refund amount (None = full refund)
        reason: Refund reason

    Returns:
        (success, data, error)
    """
    log_tag = f"[asoriba_utils.refund_transaction][ref={reference}]"
    config = _get_config()

    if not config["secret_key"]:
        return False, None, "Asoriba secret key not configured"

    try:
        payload = {"reference": reference}
        if amount is not None:
            payload["amount"] = float(amount)
        if reason:
            payload["reason"] = reason[:500]

        url = f"{config['base_url']}/api/v1/payment/refund"

        Log.info(f"{log_tag} Initiating refund: amount={amount}")

        response = requests.post(url, json=payload, headers=_headers(), timeout=30)
        result = response.json()

        if response.status_code in (200, 201) and result.get("status") in (True, "success"):
            data = result.get("data", {})
            gateway_ref = data.get("refund_reference") or data.get("id") or ""
            Log.info(f"{log_tag} Refund successful: {gateway_ref}")
            return True, {"refund_reference": str(gateway_ref), "raw": data}, None
        else:
            error_msg = result.get("message") or "Refund failed"
            Log.error(f"{log_tag} Failed: {error_msg}")
            return False, None, error_msg

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# WEBHOOK SIGNATURE VERIFICATION
# ═══════════════════════════════════════════════════════════════

def verify_webhook_signature(raw_body, signature):
    """
    Verify that a webhook request came from Asoriba.

    Args:
        raw_body: Raw request body bytes
        signature: Value from X-Asoriba-Signature header

    Returns:
        bool
    """
    config = _get_config()
    secret = config["webhook_secret"]

    if not secret:
        Log.warning("[asoriba_utils.verify_webhook_signature] No webhook secret configured — skipping verification")
        return True  # Allow in dev; enforce in production

    if not signature:
        return False

    try:
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")

        expected = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha512,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)
    except Exception as e:
        Log.error(f"[asoriba_utils.verify_webhook_signature] Error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# TRANSACTION LIST (optional)
# ═══════════════════════════════════════════════════════════════

def list_transactions(page=1, per_page=50, status=None, start_date=None, end_date=None):
    """
    List transactions from Asoriba dashboard.

    Returns:
        (success, data, error)
    """
    log_tag = "[asoriba_utils.list_transactions]"
    config = _get_config()

    try:
        params = {"page": page, "per_page": per_page}
        if status:
            params["status"] = status
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        url = f"{config['base_url']}/api/v1/transactions"
        response = requests.get(url, params=params, headers=_headers(), timeout=30)
        result = response.json()

        if response.status_code == 200:
            return True, result.get("data", {}), None
        else:
            return False, None, result.get("message", "Failed to list transactions")

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)
