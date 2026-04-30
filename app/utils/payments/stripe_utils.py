# app/utils/payments/stripe_utils.py

"""
Stripe Payment Utilities
==========================
Uses Stripe Checkout Sessions for hosted payment page flow (consistent with
Paystack/Asoriba pattern) and PaymentIntents for embedded/custom flows.

Supports: Cards, Google Pay, Apple Pay, SEPA, iDEAL, and 40+ payment methods.

API Flow (Checkout Session — recommended):
  1. Create Checkout Session → returns checkout_url
  2. Customer pays on Stripe's hosted page
  3. Webhook receives payment_intent.succeeded / checkout.session.completed
  4. Verify via retrieve if needed

Environment variables:
  STRIPE_SECRET_KEY        - sk_live_... or sk_test_...
  STRIPE_PUBLISHABLE_KEY   - pk_live_... or pk_test_...
  STRIPE_WEBHOOK_SECRET    - whsec_... (from Stripe dashboard → Webhooks)
  STRIPE_API_VERSION       - Optional (defaults to latest)
"""

import os
import hmac
import hashlib
import time
import requests
from ..logger import Log


def _get_config():
    return {
        "secret_key": os.getenv("STRIPE_SECRET_KEY", ""),
        "publishable_key": os.getenv("STRIPE_PUBLISHABLE_KEY", ""),
        "webhook_secret": os.getenv("STRIPE_WEBHOOK_SECRET", ""),
        "api_version": os.getenv("STRIPE_API_VERSION", "2024-12-18.acacia"),
    }


def _headers():
    config = _get_config()
    return {
        "Authorization": f"Bearer {config['secret_key']}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Stripe-Version": config["api_version"],
    }


def _base_url():
    return "https://api.stripe.com/v1"


# ═══════════════════════════════════════════════════════════════
# CHECKOUT SESSION (hosted payment page — like Paystack popup)
# ═══════════════════════════════════════════════════════════════

def create_checkout_session(
    amount,
    currency="usd",
    customer_email=None,
    reference=None,
    success_url=None,
    cancel_url=None,
    description=None,
    metadata=None,
    line_item_name=None,
):
    """
    Create a Stripe Checkout Session.
    Customer is redirected to Stripe's hosted page to complete payment.

    Args:
        amount: Amount in major currency unit (e.g. 49.00 USD)
        currency: Three-letter ISO currency code
        customer_email: Pre-fill customer email
        reference: Your internal reference (stored in metadata)
        success_url: Redirect URL after successful payment
        cancel_url: Redirect URL if customer cancels
        description: Payment description
        metadata: Dict of additional data
        line_item_name: Display name on checkout page

    Returns:
        (success, data, error)
    """
    log_tag = "[stripe_utils.create_checkout_session]"
    config = _get_config()

    if not config["secret_key"]:
        return False, None, "STRIPE_SECRET_KEY not configured"

    try:
        amount_cents = int(float(amount) * 100)
        if amount_cents < 50:
            return False, None, "Minimum charge amount is $0.50 USD (or equivalent)"

        payload = {
            "mode": "payment",
            "payment_method_types[]": "card",
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][unit_amount]": str(amount_cents),
            "line_items[0][price_data][product_data][name]": line_item_name or description or "WorshipDesk Subscription",
            "line_items[0][quantity]": "1",
        }

        if customer_email:
            payload["customer_email"] = customer_email
        if success_url:
            payload["success_url"] = success_url
        if cancel_url:
            payload["cancel_url"] = cancel_url

        # Metadata
        meta = metadata or {}
        if reference:
            meta["reference"] = reference
        for k, v in meta.items():
            if v is not None:
                payload[f"metadata[{k}]"] = str(v)

        # Payment intent metadata (passed through to the PaymentIntent)
        for k, v in meta.items():
            if v is not None:
                payload[f"payment_intent_data[metadata][{k}]"] = str(v)

        if description:
            payload["payment_intent_data[description]"] = description

        Log.info(f"{log_tag} Creating session: amount={amount} {currency}, ref={reference}")

        response = requests.post(
            f"{_base_url()}/checkout/sessions",
            data=payload,
            headers=_headers(),
            timeout=30,
        )
        result = response.json()

        if response.status_code in (200, 201) and result.get("id"):
            Log.info(f"{log_tag} Session created: {result['id']}")
            return True, {
                "session_id": result["id"],
                "checkout_url": result.get("url"),
                "reference": reference,
                "payment_intent_id": result.get("payment_intent"),
                "raw": result,
            }, None
        else:
            error_msg = result.get("error", {}).get("message") or "Failed to create checkout session"
            Log.error(f"{log_tag} Failed: {error_msg}")
            return False, None, error_msg

    except requests.Timeout:
        return False, None, "Stripe request timed out"
    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# PAYMENT INTENT (for custom/embedded flows)
# ═══════════════════════════════════════════════════════════════

def create_payment_intent(
    amount,
    currency="usd",
    customer_email=None,
    reference=None,
    description=None,
    metadata=None,
    payment_method_types=None,
):
    """
    Create a Stripe PaymentIntent directly.
    Use this for embedded payment forms (Stripe Elements).

    Returns:
        (success, data, error)
    """
    log_tag = "[stripe_utils.create_payment_intent]"
    config = _get_config()

    if not config["secret_key"]:
        return False, None, "STRIPE_SECRET_KEY not configured"

    try:
        amount_cents = int(float(amount) * 100)

        payload = {
            "amount": str(amount_cents),
            "currency": currency.lower(),
            "automatic_payment_methods[enabled]": "true",
        }

        if description:
            payload["description"] = description
        if customer_email:
            payload["receipt_email"] = customer_email

        meta = metadata or {}
        if reference:
            meta["reference"] = reference
        for k, v in meta.items():
            if v is not None:
                payload[f"metadata[{k}]"] = str(v)

        if payment_method_types:
            for i, pmt in enumerate(payment_method_types):
                payload[f"payment_method_types[{i}]"] = pmt
            del payload["automatic_payment_methods[enabled]"]

        Log.info(f"{log_tag} Creating PaymentIntent: amount={amount} {currency}")

        response = requests.post(
            f"{_base_url()}/payment_intents",
            data=payload,
            headers=_headers(),
            timeout=30,
        )
        result = response.json()

        if response.status_code in (200, 201) and result.get("id"):
            return True, {
                "payment_intent_id": result["id"],
                "client_secret": result.get("client_secret"),
                "reference": reference,
                "status": result.get("status"),
                "raw": result,
            }, None
        else:
            error_msg = result.get("error", {}).get("message") or "Failed to create PaymentIntent"
            return False, None, error_msg

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# RETRIEVE / VERIFY
# ═══════════════════════════════════════════════════════════════

def retrieve_checkout_session(session_id):
    """Retrieve a Checkout Session by ID."""
    log_tag = f"[stripe_utils.retrieve_checkout_session][{session_id}]"
    try:
        response = requests.get(
            f"{_base_url()}/checkout/sessions/{session_id}",
            headers=_headers(),
            timeout=30,
        )
        result = response.json()

        if response.status_code == 200 and result.get("id"):
            return True, result, None
        else:
            return False, None, result.get("error", {}).get("message", "Session not found")
    except Exception as e:
        Log.error(f"{log_tag} Error: {e}")
        return False, None, str(e)


def retrieve_payment_intent(payment_intent_id):
    """Retrieve a PaymentIntent by ID."""
    log_tag = f"[stripe_utils.retrieve_payment_intent][{payment_intent_id}]"
    try:
        response = requests.get(
            f"{_base_url()}/payment_intents/{payment_intent_id}",
            headers=_headers(),
            timeout=30,
        )
        result = response.json()

        if response.status_code == 200 and result.get("id"):
            status = result.get("status", "")
            return True, {
                "payment_intent_id": result["id"],
                "status": status,
                "amount": result.get("amount", 0) / 100,
                "currency": result.get("currency"),
                "customer_email": result.get("receipt_email"),
                "payment_method": result.get("payment_method"),
                "metadata": result.get("metadata", {}),
                "raw": result,
            }, None
        else:
            return False, None, result.get("error", {}).get("message", "PaymentIntent not found")
    except Exception as e:
        Log.error(f"{log_tag} Error: {e}")
        return False, None, str(e)


def verify_transaction(reference):
    """
    Verify a transaction by searching PaymentIntents by metadata reference.
    Fallback: if reference looks like a pi_ or cs_ ID, retrieve directly.

    Returns: (success, data, error)
    """
    log_tag = f"[stripe_utils.verify_transaction][ref={reference}]"

    try:
        # If it's a PaymentIntent ID
        if reference and reference.startswith("pi_"):
            return retrieve_payment_intent(reference)

        # If it's a Checkout Session ID
        if reference and reference.startswith("cs_"):
            success, session, error = retrieve_checkout_session(reference)
            if success and session.get("payment_intent"):
                return retrieve_payment_intent(session["payment_intent"])
            return success, session, error

        # Search by metadata reference
        response = requests.get(
            f"{_base_url()}/payment_intents/search",
            params={"query": f"metadata['reference']:'{reference}'"},
            headers=_headers(),
            timeout=30,
        )
        result = response.json()

        if response.status_code == 200:
            data_list = result.get("data", [])
            if data_list:
                pi = data_list[0]
                return True, {
                    "payment_intent_id": pi["id"],
                    "status": pi.get("status"),
                    "amount": pi.get("amount", 0) / 100,
                    "currency": pi.get("currency"),
                    "metadata": pi.get("metadata", {}),
                    "raw": pi,
                }, None
            else:
                return False, None, f"No payment found for reference: {reference}"
        else:
            return False, None, result.get("error", {}).get("message", "Search failed")

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# REFUND
# ═══════════════════════════════════════════════════════════════

def refund_transaction(payment_intent_id, amount=None, reason=None):
    """
    Create a refund for a PaymentIntent.

    Args:
        payment_intent_id: The pi_... ID
        amount: Partial refund in major currency (None = full refund)
        reason: "duplicate", "fraudulent", or "requested_by_customer"

    Returns: (success, data, error)
    """
    log_tag = f"[stripe_utils.refund_transaction][{payment_intent_id}]"
    config = _get_config()

    if not config["secret_key"]:
        return False, None, "STRIPE_SECRET_KEY not configured"

    try:
        payload = {"payment_intent": payment_intent_id}

        if amount is not None:
            payload["amount"] = str(int(float(amount) * 100))
        if reason:
            valid_reasons = ["duplicate", "fraudulent", "requested_by_customer"]
            if reason in valid_reasons:
                payload["reason"] = reason

        Log.info(f"{log_tag} Creating refund: amount={amount}")

        response = requests.post(
            f"{_base_url()}/refunds",
            data=payload,
            headers=_headers(),
            timeout=30,
        )
        result = response.json()

        if response.status_code in (200, 201) and result.get("id"):
            Log.info(f"{log_tag} Refund created: {result['id']}")
            return True, {
                "refund_id": result["id"],
                "status": result.get("status"),
                "amount": result.get("amount", 0) / 100,
                "currency": result.get("currency"),
                "raw": result,
            }, None
        else:
            error_msg = result.get("error", {}).get("message") or "Refund failed"
            Log.error(f"{log_tag} Failed: {error_msg}")
            return False, None, error_msg

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)


# ═══════════════════════════════════════════════════════════════
# WEBHOOK SIGNATURE VERIFICATION
# ═══════════════════════════════════════════════════════════════

def verify_webhook_signature(raw_body, sig_header):
    """
    Verify Stripe webhook signature (Stripe-Signature header).

    Stripe uses HMAC-SHA256 with a tolerance window.
    Format: t=timestamp,v1=signature

    Args:
        raw_body: Raw request body bytes
        sig_header: Value from Stripe-Signature header

    Returns: bool
    """
    config = _get_config()
    secret = config["webhook_secret"]

    if not secret:
        Log.warning("[stripe_utils.verify_webhook_signature] No webhook secret — skipping verification")
        return True

    if not sig_header:
        return False

    try:
        # Parse header
        elements = {}
        for part in sig_header.split(","):
            key, _, value = part.strip().partition("=")
            elements.setdefault(key, []).append(value)

        timestamp = elements.get("t", [None])[0]
        signatures = elements.get("v1", [])

        if not timestamp or not signatures:
            Log.warning("[stripe_utils] Missing timestamp or signature in header")
            return False

        # Check timestamp tolerance (5 minutes)
        try:
            ts = int(timestamp)
            if abs(time.time() - ts) > 300:
                Log.warning("[stripe_utils] Webhook timestamp too old")
                return False
        except ValueError:
            return False

        # Compute expected signature
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")

        signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
        expected = hmac.new(
            secret.encode("utf-8"),
            signed_payload,
            hashlib.sha256,
        ).hexdigest()

        # Compare against all v1 signatures
        for sig in signatures:
            if hmac.compare_digest(expected, sig):
                return True

        Log.warning("[stripe_utils] Signature mismatch")
        return False

    except Exception as e:
        Log.error(f"[stripe_utils.verify_webhook_signature] Error: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# STRIPE CUSTOMER (optional — for saved cards / recurring)
# ═══════════════════════════════════════════════════════════════

def create_or_get_customer(email, name=None, metadata=None):
    """
    Create a Stripe Customer or retrieve existing by email.
    Useful for recurring payments and saved cards.
    """
    log_tag = f"[stripe_utils.create_or_get_customer][{email}]"

    try:
        # Search existing
        response = requests.get(
            f"{_base_url()}/customers/search",
            params={"query": f"email:'{email}'"},
            headers=_headers(),
            timeout=30,
        )
        result = response.json()

        if response.status_code == 200:
            existing = result.get("data", [])
            if existing:
                return True, {"customer_id": existing[0]["id"], "created": False}, None

        # Create new
        payload = {"email": email}
        if name:
            payload["name"] = name
        if metadata:
            for k, v in metadata.items():
                payload[f"metadata[{k}]"] = str(v)

        response = requests.post(
            f"{_base_url()}/customers",
            data=payload,
            headers=_headers(),
            timeout=30,
        )
        result = response.json()

        if response.status_code in (200, 201) and result.get("id"):
            return True, {"customer_id": result["id"], "created": True}, None
        else:
            return False, None, result.get("error", {}).get("message", "Customer creation failed")

    except Exception as e:
        Log.error(f"{log_tag} Error: {e}", exc_info=True)
        return False, None, str(e)
