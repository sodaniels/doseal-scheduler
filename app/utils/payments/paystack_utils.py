# utils/payments/paystack_utils.py

"""
Paystack Payment Gateway Utilities
===================================
Handles all direct HTTP interactions with the Paystack API.

Endpoints used:
  - POST https://api.paystack.co/transaction/initialize
  - GET  https://api.paystack.co/transaction/verify/{reference}
  - GET  https://api.paystack.co/transaction/{id}
  - POST https://api.paystack.co/transaction/charge_authorization

IMPORTANT:
  - Amounts MUST be in the subunit of the currency
    (kobo for NGN, pesewas for GHS, cents for USD/ZAR/KES).
    e.g. GHS 10.00 → 1000 pesewas
  - Authorization header: "Bearer <SECRET_KEY>"
  - Webhook signature: HMAC-SHA512 of raw body, signed with SECRET_KEY
"""

import os
import hmac
import hashlib
import requests

from ...utils.logger import Log

PAYSTACK_BASE_URL = "https://api.paystack.co"

# Paystack whitelisted webhook IPs (test + live)
PAYSTACK_WEBHOOK_IPS = [
    "52.31.139.75",
    "52.49.173.169",
    "52.214.14.220",
]


# ------------------------------------------------------------------ #
#  Auth helpers
# ------------------------------------------------------------------ #

def _resolve_secret_key(secret_key: str = None) -> str:
    """
    Resolve Paystack secret key from:
      1. explicitly provided secret_key
      2. PAYSTACK_SECRET_KEY env var
    """
    resolved = secret_key or os.getenv("PAYSTACK_SECRET_KEY")
    if not resolved:
        raise ValueError("Paystack secret key is not configured")
    return resolved


def _get_headers(secret_key: str = None) -> dict:
    """Return standard Paystack request headers."""
    resolved_secret = _resolve_secret_key(secret_key)
    return {
        "Authorization": f"Bearer {resolved_secret}",
        "Content-Type": "application/json",
    }


# ------------------------------------------------------------------ #
#  Initialize Transaction
# ------------------------------------------------------------------ #

def initialize_transaction(
    email: str,
    amount_subunit: int,
    reference: str,
    currency: str = "GHS",
    callback_url: str = None,
    channels: list = None,
    metadata: dict = None,
    secret_key: str = None,
) -> tuple:
    """
    Initialize a Paystack transaction.

    Args:
        email:           Customer email address (required by Paystack).
        amount_subunit:  Amount in the smallest currency unit.
        reference:       Your unique internal reference for this transaction.
        currency:        ISO 4217 currency code – GHS, NGN, ZAR, KES, USD …
        callback_url:    URL Paystack redirects the customer to after payment.
        channels:        Allowed payment channels.
        metadata:        Dict of custom metadata attached to the transaction.
        secret_key:      Optional Paystack secret key from integration credentials.

    Returns:
        (success: bool, data: dict | None, error: str | None)
    """
    log_tag = "[paystack_utils.py][initialize_transaction]"

    try:
        if not email:
            return False, None, "Customer email is required"

        if int(amount_subunit) <= 0:
            return False, None, "Amount must be greater than 0"

        payload = {
            "email": email,
            "amount": int(amount_subunit),
            "reference": reference,
            "currency": currency,
        }

        if callback_url:
            payload["callback_url"] = callback_url

        if channels:
            payload["channels"] = channels

        if metadata:
            payload["metadata"] = metadata

        Log.info(
            f"{log_tag} Initializing transaction ref={reference}, "
            f"amount={amount_subunit} {currency}"
        )

        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transaction/initialize",
            json=payload,
            headers=_get_headers(secret_key),
            timeout=30,
        )

        try:
            result = response.json()
        except Exception:
            result = {}

        if response.status_code == 200 and result.get("status") is True:
            data = result.get("data", {})
            Log.info(
                f"{log_tag} Transaction initialized successfully. "
                f"access_code={data.get('access_code')}"
            )
            return True, data, None

        error_msg = result.get("message") or f"Paystack initialization failed with status {response.status_code}"
        Log.error(f"{log_tag} Initialization failed: {error_msg}")
        return False, None, error_msg

    except requests.exceptions.Timeout:
        Log.error(f"{log_tag} Request timed out")
        return False, None, "Paystack request timed out"

    except requests.exceptions.ConnectionError as e:
        Log.error(f"{log_tag} Connection error: {str(e)}")
        return False, None, "Could not connect to Paystack"

    except requests.exceptions.RequestException as e:
        Log.error(f"{log_tag} Request error: {str(e)}")
        return False, None, str(e)

    except Exception as e:
        Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
        return False, None, str(e)


# ------------------------------------------------------------------ #
#  Verify Transaction
# ------------------------------------------------------------------ #

def verify_transaction(reference: str, secret_key: str = None) -> tuple:
    """
    Verify a Paystack transaction by its reference.

    Args:
        reference:  The transaction reference used during initialization.
        secret_key: Optional Paystack secret key from integration credentials.

    Returns:
        (success: bool, data: dict | None, error: str | None)
    """
    log_tag = f"[paystack_utils.py][verify_transaction][{reference}]"

    try:
        Log.info(f"{log_tag} Verifying transaction")

        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
            headers=_get_headers(secret_key),
            timeout=30,
        )

        try:
            result = response.json()
        except Exception:
            result = {}

        if response.status_code == 200 and result.get("status") is True:
            data = result.get("data", {})
            txn_status = data.get("status")
            Log.info(
                f"{log_tag} Verification result: status={txn_status}, "
                f"gateway_response={data.get('gateway_response')}"
            )
            return True, data, None

        error_msg = result.get("message") or "Verification failed"
        Log.error(f"{log_tag} Verification failed: {error_msg}")
        return False, None, error_msg

    except requests.exceptions.Timeout:
        Log.error(f"{log_tag} Verification request timed out")
        return False, None, "Paystack verification timed out"

    except requests.exceptions.ConnectionError as e:
        Log.error(f"{log_tag} Connection error: {str(e)}")
        return False, None, "Could not connect to Paystack"

    except requests.exceptions.RequestException as e:
        Log.error(f"{log_tag} Request error: {str(e)}")
        return False, None, str(e)

    except Exception as e:
        Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
        return False, None, str(e)


# ------------------------------------------------------------------ #
#  Fetch Transaction by Paystack ID
# ------------------------------------------------------------------ #

def fetch_transaction(transaction_id: int, secret_key: str = None) -> tuple:
    """
    Fetch a single transaction by its Paystack numeric ID.

    Args:
        transaction_id: The Paystack transaction ID.
        secret_key:     Optional Paystack secret key from integration credentials.

    Returns:
        (success: bool, data: dict | None, error: str | None)
    """
    log_tag = f"[paystack_utils.py][fetch_transaction][{transaction_id}]"

    try:
        response = requests.get(
            f"{PAYSTACK_BASE_URL}/transaction/{transaction_id}",
            headers=_get_headers(secret_key),
            timeout=30,
        )

        try:
            result = response.json()
        except Exception:
            result = {}

        if response.status_code == 200 and result.get("status") is True:
            return True, result.get("data", {}), None

        return False, None, result.get("message", "Failed to fetch transaction")

    except requests.exceptions.Timeout:
        Log.error(f"{log_tag} Request timed out")
        return False, None, "Paystack fetch transaction timed out"

    except requests.exceptions.ConnectionError as e:
        Log.error(f"{log_tag} Connection error: {str(e)}")
        return False, None, "Could not connect to Paystack"

    except requests.exceptions.RequestException as e:
        Log.error(f"{log_tag} Request error: {str(e)}")
        return False, None, str(e)

    except Exception as e:
        Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
        return False, None, str(e)


# ------------------------------------------------------------------ #
#  Charge Authorization (recurring payments)
# ------------------------------------------------------------------ #

def charge_authorization(
    email: str,
    amount_subunit: int,
    authorization_code: str,
    reference: str,
    currency: str = "GHS",
    metadata: dict = None,
    secret_key: str = None,
) -> tuple:
    """
    Charge a previously authorized card/bank for recurring payments.

    Args:
        email:               Customer email.
        amount_subunit:      Amount in subunit.
        authorization_code:  Authorization code from a previous successful charge.
        reference:           Unique transaction reference.
        currency:            ISO 4217 currency code.
        metadata:            Additional metadata dict.
        secret_key:          Optional Paystack secret key from integration credentials.

    Returns:
        (success: bool, data: dict | None, error: str | None)
    """
    log_tag = f"[paystack_utils.py][charge_authorization][{reference}]"

    try:
        if not email:
            return False, None, "Customer email is required"

        if not authorization_code:
            return False, None, "Authorization code is required"

        if int(amount_subunit) <= 0:
            return False, None, "Amount must be greater than 0"

        payload = {
            "email": email,
            "amount": int(amount_subunit),
            "authorization_code": authorization_code,
            "reference": reference,
            "currency": currency,
        }

        if metadata:
            payload["metadata"] = metadata

        Log.info(f"{log_tag} Charging authorization {authorization_code}")

        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transaction/charge_authorization",
            json=payload,
            headers=_get_headers(secret_key),
            timeout=30,
        )

        try:
            result = response.json()
        except Exception:
            result = {}

        if response.status_code == 200 and result.get("status") is True:
            data = result.get("data", {})
            Log.info(f"{log_tag} Charge result: {data.get('status')}")
            return True, data, None

        error_msg = result.get("message", "Charge failed")
        Log.error(f"{log_tag} Charge failed: {error_msg}")
        return False, None, error_msg

    except requests.exceptions.Timeout:
        Log.error(f"{log_tag} Request timed out")
        return False, None, "Paystack charge authorization timed out"

    except requests.exceptions.ConnectionError as e:
        Log.error(f"{log_tag} Connection error: {str(e)}")
        return False, None, "Could not connect to Paystack"

    except requests.exceptions.RequestException as e:
        Log.error(f"{log_tag} Request error: {str(e)}")
        return False, None, str(e)

    except Exception as e:
        Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
        return False, None, str(e)


# ------------------------------------------------------------------ #
#  Refund Transaction
# ------------------------------------------------------------------ #

def refund_transaction(
    transaction_reference: str = None,
    transaction_id: int = None,
    amount_subunit: int = None,
    currency: str = None,
    merchant_note: str = None,
    customer_note: str = None,
    secret_key: str = None,
) -> tuple:
    """
    Refund a Paystack transaction fully or partially.

    Args:
        transaction_reference: Paystack reference.
        transaction_id:        Paystack numeric transaction ID.
        amount_subunit:        Optional partial refund amount in subunit.
        currency:              Optional ISO currency code.
        merchant_note:         Internal note.
        customer_note:         Customer-visible note.
        secret_key:            Optional Paystack secret key from integration credentials.

    Returns:
        (success: bool, data: dict | None, error: str | None)
    """
    log_tag = "[paystack_utils.py][refund_transaction]"

    try:
        if not transaction_reference and not transaction_id:
            return False, None, "transaction_reference or transaction_id is required"

        payload = {}

        if transaction_reference:
            payload["transaction"] = transaction_reference
        elif transaction_id:
            payload["transaction"] = transaction_id

        if amount_subunit is not None:
            payload["amount"] = int(amount_subunit)

        if currency:
            payload["currency"] = currency

        if merchant_note:
            payload["merchant_note"] = merchant_note

        if customer_note:
            payload["customer_note"] = customer_note

        Log.info(f"{log_tag} Creating refund for transaction={payload.get('transaction')}")

        response = requests.post(
            f"{PAYSTACK_BASE_URL}/refund",
            json=payload,
            headers=_get_headers(secret_key),
            timeout=30,
        )

        try:
            result = response.json()
        except Exception:
            result = {}

        if response.status_code in (200, 201) and result.get("status") is True:
            data = result.get("data", {})
            Log.info(f"{log_tag} Refund created successfully")
            return True, data, None

        error_msg = result.get("message", "Refund failed")
        Log.error(f"{log_tag} Refund failed: {error_msg}")
        return False, None, error_msg

    except requests.exceptions.Timeout:
        Log.error(f"{log_tag} Refund request timed out")
        return False, None, "Paystack refund request timed out"

    except requests.exceptions.ConnectionError as e:
        Log.error(f"{log_tag} Connection error: {str(e)}")
        return False, None, "Could not connect to Paystack"

    except requests.exceptions.RequestException as e:
        Log.error(f"{log_tag} Request error: {str(e)}")
        return False, None, str(e)

    except Exception as e:
        Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
        return False, None, str(e)


# ------------------------------------------------------------------ #
#  Webhook Signature Verification
# ------------------------------------------------------------------ #

def verify_webhook_signature(payload_body: bytes, signature: str, secret_key: str = None) -> bool:
    """
    Verify that a webhook request actually originated from Paystack.

    Args:
        payload_body: The raw request body (bytes).
        signature:    Value of the X-Paystack-Signature header.
        secret_key:   Optional Paystack secret key from integration credentials.

    Returns:
        True if the signature is valid, False otherwise.
    """
    log_tag = "[paystack_utils.py][verify_webhook_signature]"

    try:
        resolved_secret = _resolve_secret_key(secret_key)

        expected = hmac.new(
            resolved_secret.encode("utf-8"),
            payload_body,
            hashlib.sha512,
        ).hexdigest()

        is_valid = hmac.compare_digest(expected, signature)

        if not is_valid:
            Log.warning(f"{log_tag} Signature mismatch — possible spoofed webhook")

        return is_valid

    except Exception as e:
        Log.error(f"{log_tag} Error: {str(e)}")
        return False


def is_paystack_ip(ip_address: str) -> bool:
    """Check if the request IP is in Paystack's whitelist."""
    return ip_address in PAYSTACK_WEBHOOK_IPS


# ------------------------------------------------------------------ #
#  Currency helpers
# ------------------------------------------------------------------ #

def to_subunit(amount: float) -> int:
    """
    Convert a major-unit amount to subunit.
    e.g. 10.50 -> 1050
    """
    return int(round(float(amount) * 100))


def from_subunit(amount_subunit: int) -> float:
    """Convert a subunit amount back to major units."""
    return round(int(amount_subunit) / 100, 2)


# ------------------------------------------------------------------ #
#  Supported Paystack currencies
# ------------------------------------------------------------------ #

PAYSTACK_CURRENCIES = {
    "GHA": "GHS",
    "NGA": "NGN",
    "ZAF": "ZAR",
    "KEN": "KES",
    "CIV": "XOF",
    "EGY": "EGP",
    "USA": "USD",
    "GBR": "GBP",
}


def get_paystack_currency(country_iso_3: str) -> str:
    """
    Map an ISO 3166-1 alpha-3 country code to the Paystack currency code.
    Falls back to USD if the country is not in the map.
    """
    return PAYSTACK_CURRENCIES.get(str(country_iso_3).upper(), "USD")