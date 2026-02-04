# utils/asoriba_utils.py

import base64
import hmac
import hashlib
from flask import request
from ..logger import Log
from ...config import Config



# --- Signature verification (since this callback is query-based)
# If Asoriba doesn't send any signature header, you CANNOT cryptographically verify.
# In that case, rely on:
# - a secret "token" you add to callback URL (recommended)
# - idempotency + strict matching of order_id/amount/currency
def verify_asoriba_signature(req):
    """
    Recommended approach for query callbacks:
    Add a secret token in your callback url, e.g.
      https://.../webhooks/payment/asoriba?webhook_token=XYZ

    Then verify it here. This is simple and effective.
    """
    expected = getattr(Config, "ASORIBA_WEBHOOK_TOKEN", None)
    received = req.args.get("webhook_token") or req.form.get("webhook_token")
    if not expected:
        # If you haven't configured a token, return True to avoid blocking
        # BUT it's less secure. Prefer adding a token.
        return True
    if not received:
        return False
    return hmac.compare_digest(str(received), str(expected))


def _get_param(name, default=None):
    """
    Read a field from query string or form body.
    """
    return request.args.get(name) or request.form.get(name) or default


def _extract_nested(prefix):
    """
    Extract nested params like:
      metadata[order_id] -> {"order_id": "..."}
      source[number]     -> {"number": "..."}
    """
    out = {}

    # query params
    for k, v in request.args.items():
        if k.startswith(prefix + "[") and k.endswith("]"):
            inner = k[len(prefix) + 1:-1]  # between [ ]
            out[inner] = v

    # form params
    for k, v in request.form.items():
        if k.startswith(prefix + "[") and k.endswith("]"):
            inner = k[len(prefix) + 1:-1]
            out[inner] = v

    return out


def parse_asoriba_callback_from_query():
    metadata = _extract_nested("metadata")
    source = _extract_nested("source")

    status_raw = _get_param("status", "")
    status = str(status_raw).strip().lower()
    status_code = str(_get_param("status_code", "")).strip()

    gateway_id = _get_param("id") or _get_param("transaction_id") or _get_param("checkout_id")
    reference = (
        metadata.get("order_id")
        or _get_param("order_id")
        or _get_param("reference")
        or gateway_id
    )

    payload = {
        "id": _get_param("id"),
        "status": status_raw,
        "status_code": status_code,
        "message": _get_param("message"),
        "amount": _get_param("amount"),
        "amount_after_charge": _get_param("amount_after_charge"),
        "charge": _get_param("charge"),
        "currency": _get_param("currency"),
        "email": _get_param("email"),
        "first_name": _get_param("first_name"),
        "last_name": _get_param("last_name"),
        "customer_remarks": _get_param("customer_remarks"),
        "payment_date": _get_param("payment_date"),
        "processor_transaction_id": _get_param("processor_transaction_id"),
        "reference": _get_param("reference"),
        "transaction_uuid": _get_param("transaction_uuid"),
        "tokenized": _get_param("tokenized"),
        "metadata": metadata,
        "source": source,
        "order_id": metadata.get("order_id"),
    }

    SUCCESS_STATUSES = {"success", "successful", "completed", "paid"}
    PENDING_STATUSES = {"pending", "processing", "in_progress"}

    is_success = (status in SUCCESS_STATUSES) and (status_code == "100")
    is_pending = (status in PENDING_STATUSES) and (not is_success)

    # If it's neither success nor pending, treat as failed
    is_failed = (not is_success) and (not is_pending)

    return {
        "reference": reference,
        "gateway_id": gateway_id,
        "status": status,
        "status_code": status_code,
        "is_success": is_success,
        "is_pending": is_pending,
        "is_failed": is_failed,
        "payload": payload,
    }
