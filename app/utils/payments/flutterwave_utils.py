# app/utils/payments/flutterwave_utils.py

"""
Flutterwave Payment Utilities (v3 Standard API)
==================================================
Uses Flutterwave Standard checkout for hosted payment page flow.

Supports: Cards, Bank Transfer, Mobile Money (MPesa, MTN, Airtel),
          USSD, Apple Pay, Google Pay — 30+ countries.

API Flow:
  1. POST /v3/payments → returns checkout link
  2. Customer pays on Flutterwave's hosted page
  3. Webhook receives charge.completed event
  4. Verify transaction via GET /v3/transactions/{id}/verify

Environment variables:
  FLW_PUBLIC_KEY      - FLWPUBK-xxxxx
  FLW_SECRET_KEY      - FLWSECK-xxxxx
  FLW_SECRET_HASH     - Your webhook secret hash (from dashboard)
  FLW_ENCRYPTION_KEY  - Optional (for direct card charge)
"""

import os
import requests
from ..logger import Log


BASE_URL = "https://api.flutterwave.com/v3"


def _get_config():
    return {
        "public_key": os.getenv("FLW_PUBLIC_KEY", ""),
        "secret_key": os.getenv("FLW_SECRET_KEY", ""),
        "secret_hash": os.getenv("FLW_SECRET_HASH", ""),
        "encryption_key": os.getenv("FLW_ENCRYPTION_KEY", ""),
    }


def _headers():
    config = _get_config()
    return {
        "Authorization": f"Bearer {config['secret_key']}",
        "Content-Type": "application/json",
    }


# ═══════════════════════════════════════════════════════════════
# STANDARD CHECKOUT (hosted payment page)
# ═══════════════════════════════════════════════════════════════

def initialize_payment(
    amount,
    currency="NGN",
    tx_ref=None,
    redirect_url=None,
    customer_email=None,
    customer_name=None,
    customer_phone=None,
    description=None,
    metadata=None,
    payment_options=None,
    customizations=None,
):
    """
    Create a Flutterwave Standard checkout session.

    Args:
        amount: Amount in major currency unit
        currency: ISO currency code (NGN, USD, GBP, GHS, KES, etc.)
        tx_ref: Your unique transaction reference
        redirect_url: URL to redirect customer after payment
        customer_email: Required — customer email
        customer_name: Customer full name
        customer_phone: Customer phone number
        description: Payment description
        metadata: Dict of additional data
        payment_options: Comma-separated string e.g. "card,banktransfer,mobilemoney"
        customizations: Dict with title, description, logo

    Returns:
        (success, data, error)
    """
    log_tag = "[flutterwave_utils.initialize_payment]"
    config = _get_config()

    if not config["secret_key"]:
        return False, None, "FLW_SECRET_KEY not configured"

    if not customer_email:
        return False, None, "Customer email is required for Flutterwave"

    try:
        payload = {
            "tx_ref": tx_ref,
            "amount": str(float(amount)),
            "currency": currency.upper(),
            "redirect_url": redirect_url or "",
            "customer": {
                "email": customer_email,
            },
        }

        if customer_name:
            payload["customer"]["name"] = customer_name
        if customer_phone:
            payload["customer"]["phonenumber"] = customer_phone

        if payment_options:
            payload["payment_options"] = payment_options

        if description:
            payload["payment_plan"] = None  # not a subscription
            payload["meta"] = {"description": description}

        if metadata and isinstance(metadata, dict):
            existing_meta = payload.get("meta", {})
            existing_meta.update(metadata)
            payload["meta"] = existing_meta

        if customizations:
            payload["customizations"] = customizations
        else:
            payload["customizations"] = {
                "title": "WorshipDesk",
                "description": description or "Subscription Payment",
            }

        Log.info(f"{log_tag} Initializing: amount={amount} {currency}, ref={tx_ref}")

        response = requests.post(
            f"{BASE_URL}/payments",
            json=payload,
            headers=_headers(),
            timeout=30,
        )
        result = response.json()

        if result.get("status") == "success" and result.get("data", {}).get("link"):
            data = result["data"]
            Log.info(f"{log_tag} Checkout created successfully")
            return True, {
                "checkout_url": data["link"],
                "reference": tx_ref,
                "raw": result,
            }, None
        else:
            error_msg = result.get("message") or "Failed to create Flutterwave checkout"
            Log.error(f"{log_tag} Failed: {error_msg}")
            return False, None, error_msg

    except requests.Timeout:
        return False, None, "Flutterwave request timed out"
    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# VERIFY TRANSACTION
# ═══════════════════════════════════════════════════════════════

def verify_transaction(transaction_id):
    """
    Verify a transaction by Flutterwave transaction ID.

    Returns:
        (success, data, error)
    """
    log_tag = f"[flutterwave_utils.verify_transaction][{transaction_id}]"

    try:
        response = requests.get(
            f"{BASE_URL}/transactions/{transaction_id}/verify",
            headers=_headers(),
            timeout=30,
        )
        result = response.json()

        if result.get("status") == "success" and result.get("data"):
            data = result["data"]
            return True, {
                "transaction_id": data.get("id"),
                "tx_ref": data.get("tx_ref"),
                "flw_ref": data.get("flw_ref"),
                "status": data.get("status"),
                "amount": float(data.get("amount") or 0),
                "charged_amount": float(data.get("charged_amount") or 0),
                "currency": data.get("currency"),
                "customer_email": data.get("customer", {}).get("email"),
                "customer_name": data.get("customer", {}).get("name"),
                "customer_phone": data.get("customer", {}).get("phone_number"),
                "payment_type": data.get("payment_type"),
                "created_at": data.get("created_at"),
                "raw": data,
            }, None
        else:
            error_msg = result.get("message") or "Verification failed"
            return False, None, error_msg

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


def verify_by_tx_ref(tx_ref):
    """
    Verify a transaction by tx_ref (your reference).
    Flutterwave requires the transaction_id, so we search first.
    """
    log_tag = f"[flutterwave_utils.verify_by_tx_ref][{tx_ref}]"

    try:
        response = requests.get(
            f"{BASE_URL}/transactions",
            params={"tx_ref": tx_ref},
            headers=_headers(),
            timeout=30,
        )
        result = response.json()

        if result.get("status") == "success":
            transactions = result.get("data", [])
            if transactions:
                txn = transactions[0]
                return verify_transaction(txn["id"])
            else:
                return False, None, f"No transaction found for tx_ref: {tx_ref}"
        else:
            return False, None, result.get("message") or "Search failed"

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# REFUND
# ═══════════════════════════════════════════════════════════════

def refund_transaction(transaction_id, amount=None, reason=None):
    """
    Create a refund for a Flutterwave transaction.

    Args:
        transaction_id: Flutterwave transaction ID
        amount: Partial refund amount (None = full refund)
        reason: Refund reason

    Returns:
        (success, data, error)
    """
    log_tag = f"[flutterwave_utils.refund_transaction][{transaction_id}]"

    try:
        payload = {}
        if amount is not None:
            payload["amount"] = float(amount)
        if reason:
            payload["comments"] = reason[:500]

        Log.info(f"{log_tag} Refunding: amount={amount}")

        response = requests.post(
            f"{BASE_URL}/transactions/{transaction_id}/refund",
            json=payload,
            headers=_headers(),
            timeout=30,
        )
        result = response.json()

        if result.get("status") == "success" and result.get("data"):
            data = result["data"]
            Log.info(f"{log_tag} Refund created: {data.get('id')}")
            return True, {
                "refund_id": str(data.get("id")),
                "status": data.get("status"),
                "amount_refunded": float(data.get("amount_refunded") or 0),
                "raw": data,
            }, None
        else:
            error_msg = result.get("message") or "Refund failed"
            return False, None, error_msg

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# WEBHOOK SIGNATURE VERIFICATION
# ═══════════════════════════════════════════════════════════════

def verify_webhook_signature(verif_hash_header):
    config = _get_config()
    secret_hash = config["secret_hash"]

    if not secret_hash:
        Log.warning("[flutterwave_utils] No secret_hash configured — allowing request")
        return True  # No hash set = skip verification

    if not verif_hash_header:
        Log.warning("[flutterwave_utils] Missing verif-hash header")
        return False

    if verif_hash_header != secret_hash:
        Log.warning("[flutterwave_utils] Hash mismatch")
        return False

    return True