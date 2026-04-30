# app/utils/payments/mpesa_utils.py

"""
M-Pesa (Safaricom Daraja API) Payment Utilities
==================================================
Uses Lipa Na M-Pesa Online (STK Push) for payment initiation.
Customer receives a push notification on their phone to enter PIN.

Supports: M-Pesa (Kenya), extensible for Vodacom M-Pesa (Tanzania).

API Flow:
  1. Get OAuth access token
  2. STK Push → customer gets PIN prompt on phone
  3. Callback receives payment result
  4. Query status for verification

Environment variables:
  MPESA_CONSUMER_KEY       - From Daraja portal
  MPESA_CONSUMER_SECRET    - From Daraja portal
  MPESA_SHORTCODE          - Business shortcode (Paybill/Till)
  MPESA_PASSKEY            - Lipa Na M-Pesa Online passkey
  MPESA_MODE               - "sandbox" or "live"
  MPESA_INITIATOR_NAME     - For B2C/reversal (optional)
  MPESA_SECURITY_CREDENTIAL - For B2C/reversal (optional)
"""

import os
import base64
import time
import requests
from datetime import datetime
from requests.auth import HTTPBasicAuth
from ..logger import Log


# ── Config ──

def _get_config():
    mode = os.getenv("MPESA_MODE", "sandbox").strip().lower()
    return {
        "consumer_key": os.getenv("MPESA_CONSUMER_KEY", ""),
        "consumer_secret": os.getenv("MPESA_CONSUMER_SECRET", ""),
        "shortcode": os.getenv("MPESA_SHORTCODE", "174379"),
        "passkey": os.getenv("MPESA_PASSKEY", ""),
        "mode": mode,
        "base_url": (
            "https://api.safaricom.co.ke"
            if mode == "live"
            else "https://sandbox.safaricom.co.ke"
        ),
    }


# ═══════════════════════════════════════════════════════════════
# OAUTH ACCESS TOKEN
# ═══════════════════════════════════════════════════════════════

_token_cache = {"token": None, "expires_at": 0}


def get_access_token():
    """Get OAuth token from Safaricom. Cached until expiry."""
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"], None

    config = _get_config()
    if not config["consumer_key"] or not config["consumer_secret"]:
        return None, "M-Pesa consumer_key or consumer_secret not configured"

    try:
        url = f"{config['base_url']}/oauth/v1/generate?grant_type=client_credentials"
        response = requests.get(
            url,
            auth=HTTPBasicAuth(config["consumer_key"], config["consumer_secret"]),
            timeout=30,
        )
        result = response.json()

        if response.status_code == 200 and result.get("access_token"):
            _token_cache["token"] = result["access_token"]
            _token_cache["expires_at"] = now + int(result.get("expires_in", 3599))
            return result["access_token"], None
        else:
            error = result.get("errorMessage") or result.get("error_description") or "Token request failed"
            Log.error(f"[mpesa_utils.get_access_token] {error}")
            return None, error

    except Exception as e:
        Log.error(f"[mpesa_utils.get_access_token] {e}", exc_info=True)
        return None, str(e)


def _auth_headers():
    token, error = get_access_token()
    if not token:
        raise Exception(f"M-Pesa auth failed: {error}")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _generate_password():
    """Generate the base64 encoded password for STK Push."""
    config = _get_config()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    raw = f"{config['shortcode']}{config['passkey']}{timestamp}"
    password = base64.b64encode(raw.encode("utf-8")).decode("utf-8")
    return password, timestamp


# ═══════════════════════════════════════════════════════════════
# STK PUSH (Lipa Na M-Pesa Online)
# ═══════════════════════════════════════════════════════════════

def initiate_stk_push(
    phone_number,
    amount,
    account_reference=None,
    description=None,
    callback_url=None,
    reference=None,
    metadata=None,
):
    """
    Initiate an STK Push (Lipa Na M-Pesa Online).
    Customer receives a PIN prompt on their phone.

    Args:
        phone_number: Customer phone (254XXXXXXXXX format)
        amount: Amount in KES (integer, min 1)
        account_reference: Business reference (max 12 chars)
        description: Transaction description (max 13 chars)
        callback_url: URL for M-Pesa to send results
        reference: Your internal payment reference
        metadata: Additional data (not sent to M-Pesa, for your records)

    Returns:
        (success, data, error)
    """
    log_tag = "[mpesa_utils.initiate_stk_push]"
    config = _get_config()

    if not config["passkey"]:
        return False, None, "MPESA_PASSKEY not configured"

    if not callback_url:
        return False, None, "Callback URL is required for M-Pesa STK Push"

    try:
        # Normalise phone number to 254 format
        phone = _normalise_phone(phone_number)
        if not phone:
            return False, None, f"Invalid phone number: {phone_number}. Use 254XXXXXXXXX format."

        # Amount must be integer >= 1
        amount_int = int(float(amount))
        if amount_int < 1:
            return False, None, "M-Pesa minimum amount is KES 1"

        password, timestamp = _generate_password()

        payload = {
            "BusinessShortCode": config["shortcode"],
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount_int,
            "PartyA": phone,
            "PartyB": config["shortcode"],
            "PhoneNumber": phone,
            "CallBackURL": callback_url,
            "AccountReference": (account_reference or reference or "WorshipDesk")[:12],
            "TransactionDesc": (description or "Payment")[:13],
        }

        url = f"{config['base_url']}/mpesa/stkpush/v1/processrequest"

        Log.info(f"{log_tag} STK Push: phone={phone}, amount={amount_int} KES, ref={reference}")

        response = requests.post(url, json=payload, headers=_auth_headers(), timeout=30)
        result = response.json()

        response_code = result.get("ResponseCode")
        checkout_request_id = result.get("CheckoutRequestID")
        merchant_request_id = result.get("MerchantRequestID")

        if response.status_code == 200 and response_code == "0":
            Log.info(f"{log_tag} STK Push sent: CheckoutRequestID={checkout_request_id}")
            return True, {
                "checkout_request_id": checkout_request_id,
                "merchant_request_id": merchant_request_id,
                "reference": reference,
                "phone": phone,
                "amount": amount_int,
                "message": result.get("CustomerMessage") or "Please check your phone to complete the payment",
                "raw": result,
            }, None
        else:
            error_msg = (
                result.get("errorMessage")
                or result.get("ResponseDescription")
                or f"STK Push failed (code: {response_code})"
            )
            Log.error(f"{log_tag} Failed: {error_msg}")
            return False, None, error_msg

    except requests.Timeout:
        return False, None, "M-Pesa request timed out"
    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# QUERY STK PUSH STATUS
# ═══════════════════════════════════════════════════════════════

def query_stk_status(checkout_request_id):
    """
    Query the status of an STK Push transaction.

    Returns:
        (success, data, error)
    """
    log_tag = f"[mpesa_utils.query_stk_status][{checkout_request_id}]"
    config = _get_config()

    try:
        password, timestamp = _generate_password()

        payload = {
            "BusinessShortCode": config["shortcode"],
            "Password": password,
            "Timestamp": timestamp,
            "CheckoutRequestID": checkout_request_id,
        }

        url = f"{config['base_url']}/mpesa/stkpushquery/v1/query"

        response = requests.post(url, json=payload, headers=_auth_headers(), timeout=30)
        result = response.json()

        result_code = result.get("ResultCode")

        if result_code == "0" or result_code == 0:
            return True, {
                "checkout_request_id": checkout_request_id,
                "status": "success",
                "result_code": result_code,
                "result_desc": result.get("ResultDesc"),
                "raw": result,
            }, None
        elif result_code == "1032":
            return True, {
                "checkout_request_id": checkout_request_id,
                "status": "cancelled",
                "result_code": result_code,
                "result_desc": "Transaction cancelled by user",
                "raw": result,
            }, None
        else:
            return True, {
                "checkout_request_id": checkout_request_id,
                "status": "failed",
                "result_code": result_code,
                "result_desc": result.get("ResultDesc") or "Transaction failed",
                "raw": result,
            }, None

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


def verify_transaction(checkout_request_id):
    """Alias for query_stk_status."""
    return query_stk_status(checkout_request_id)


# ═══════════════════════════════════════════════════════════════
# CALLBACK PARSING
# ═══════════════════════════════════════════════════════════════

def parse_stk_callback(callback_data):
    """
    Parse M-Pesa STK Push callback data.

    M-Pesa sends:
    {
        "Body": {
            "stkCallback": {
                "MerchantRequestID": "...",
                "CheckoutRequestID": "...",
                "ResultCode": 0,
                "ResultDesc": "...",
                "CallbackMetadata": {
                    "Item": [
                        {"Name": "Amount", "Value": 1.00},
                        {"Name": "MpesaReceiptNumber", "Value": "XXX"},
                        {"Name": "TransactionDate", "Value": 20260428},
                        {"Name": "PhoneNumber", "Value": 254712345678}
                    ]
                }
            }
        }
    }

    Returns:
        dict with parsed fields or None
    """
    try:
        stk_callback = (callback_data or {}).get("Body", {}).get("stkCallback", {})
        if not stk_callback:
            return None

        result_code = stk_callback.get("ResultCode")
        is_success = (result_code == 0 or result_code == "0")

        parsed = {
            "merchant_request_id": stk_callback.get("MerchantRequestID"),
            "checkout_request_id": stk_callback.get("CheckoutRequestID"),
            "result_code": result_code,
            "result_desc": stk_callback.get("ResultDesc"),
            "is_success": is_success,
        }

        # Extract metadata items (only present on success)
        metadata_items = (stk_callback.get("CallbackMetadata") or {}).get("Item", [])
        for item in metadata_items:
            name = item.get("Name", "")
            value = item.get("Value")

            if name == "Amount":
                parsed["amount"] = float(value or 0)
            elif name == "MpesaReceiptNumber":
                parsed["mpesa_receipt"] = str(value or "")
            elif name == "TransactionDate":
                parsed["transaction_date"] = str(value or "")
            elif name == "PhoneNumber":
                parsed["phone_number"] = str(value or "")
            elif name == "Balance":
                parsed["balance"] = value

        return parsed

    except Exception as e:
        Log.error(f"[mpesa_utils.parse_stk_callback] {e}", exc_info=True)
        return None


# ═══════════════════════════════════════════════════════════════
# PHONE NUMBER NORMALISATION
# ═══════════════════════════════════════════════════════════════

def _normalise_phone(phone):
    """
    Normalise phone number to 254XXXXXXXXX format.
    Accepts: 0712345678, +254712345678, 254712345678, 712345678
    """
    if not phone:
        return None

    phone = str(phone).strip().replace(" ", "").replace("-", "")

    if phone.startswith("+"):
        phone = phone[1:]

    if phone.startswith("0") and len(phone) == 10:
        phone = "254" + phone[1:]

    if len(phone) == 9 and phone[0] in ("7", "1"):
        phone = "254" + phone

    if phone.startswith("254") and len(phone) == 12:
        return phone

    return None


# ═══════════════════════════════════════════════════════════════
# TRANSACTION STATUS QUERY (general)
# ═══════════════════════════════════════════════════════════════

def check_transaction_status(transaction_id, identifier_type="4"):
    """
    Check status of any M-Pesa transaction using Transaction Status API.
    Requires MPESA_INITIATOR_NAME and MPESA_SECURITY_CREDENTIAL.

    Returns:
        (success, data, error)
    """
    log_tag = f"[mpesa_utils.check_transaction_status][{transaction_id}]"
    config = _get_config()

    initiator = os.getenv("MPESA_INITIATOR_NAME", "")
    security_credential = os.getenv("MPESA_SECURITY_CREDENTIAL", "")

    if not initiator or not security_credential:
        return False, None, "MPESA_INITIATOR_NAME and MPESA_SECURITY_CREDENTIAL required"

    try:
        api_base = os.getenv("API_BASE_URL", "").rstrip("/")

        payload = {
            "Initiator": initiator,
            "SecurityCredential": security_credential,
            "CommandID": "TransactionStatusQuery",
            "TransactionID": transaction_id,
            "PartyA": config["shortcode"],
            "IdentifierType": identifier_type,
            "ResultURL": f"{api_base}/api/v1/webhooks/payment/mpesa/status-result",
            "QueueTimeOutURL": f"{api_base}/api/v1/webhooks/payment/mpesa/status-timeout",
            "Remarks": "Transaction status check",
        }

        url = f"{config['base_url']}/mpesa/transactionstatus/v1/query"
        response = requests.post(url, json=payload, headers=_auth_headers(), timeout=30)
        result = response.json()

        if result.get("ResponseCode") == "0":
            return True, result, None
        else:
            return False, None, result.get("errorMessage") or "Status query failed"

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# REVERSAL (refund equivalent)
# ═══════════════════════════════════════════════════════════════

def reverse_transaction(transaction_id, amount, receiver_party=None, remarks=None):
    """
    Reverse an M-Pesa transaction.
    Requires MPESA_INITIATOR_NAME and MPESA_SECURITY_CREDENTIAL.

    Returns:
        (success, data, error)
    """
    log_tag = f"[mpesa_utils.reverse_transaction][{transaction_id}]"
    config = _get_config()

    initiator = os.getenv("MPESA_INITIATOR_NAME", "")
    security_credential = os.getenv("MPESA_SECURITY_CREDENTIAL", "")

    if not initiator or not security_credential:
        return False, None, "MPESA_INITIATOR_NAME and MPESA_SECURITY_CREDENTIAL required for reversal"

    try:
        api_base = os.getenv("API_BASE_URL", "").rstrip("/")

        payload = {
            "Initiator": initiator,
            "SecurityCredential": security_credential,
            "CommandID": "TransactionReversal",
            "TransactionID": transaction_id,
            "Amount": int(float(amount)),
            "ReceiverParty": receiver_party or config["shortcode"],
            "RecieverIdentifierType": "11",
            "ResultURL": f"{api_base}/api/v1/webhooks/payment/mpesa/reversal-result",
            "QueueTimeOutURL": f"{api_base}/api/v1/webhooks/payment/mpesa/reversal-timeout",
            "Remarks": (remarks or "Transaction reversal")[:100],
            "Occasion": "",
        }

        url = f"{config['base_url']}/mpesa/reversal/v1/request"
        response = requests.post(url, json=payload, headers=_auth_headers(), timeout=30)
        result = response.json()

        if result.get("ResponseCode") == "0":
            Log.info(f"{log_tag} Reversal initiated: {result.get('ConversationID')}")
            return True, {
                "conversation_id": result.get("ConversationID"),
                "originator_conversation_id": result.get("OriginatorConversationID"),
                "raw": result,
            }, None
        else:
            error_msg = result.get("errorMessage") or "Reversal failed"
            return False, None, error_msg

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)
