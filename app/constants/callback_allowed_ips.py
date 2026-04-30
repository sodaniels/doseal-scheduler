# app/constants/callback_allowed_ips.py

"""
Payment Gateway Webhook IP Allowlists
========================================
Defence-in-depth: IP filtering + signature verification.

Set to None = skip IP check, rely on signature verification only.
Set to a set() = enforce IP whitelist.

Sources:
  Paystack:  https://paystack.com/docs/payments/webhooks/#ip-whitelisting
  Stripe:    https://docs.stripe.com/ips (webhook section)
  Hubtel:    Verify with Hubtel support for latest
  Asoriba:   No published list — signature only
"""

# Paystack webhook IPs
PAYSTACK_ALLOWED_CALLBACK_IPS = {
    "52.31.139.75",
    "52.49.173.169",
    "52.214.14.220",
    "89.107.59.176", #fucah ip
}

# Stripe webhook IPs (from https://docs.stripe.com/ips)
STRIPE_ALLOWED_CALLBACK_IPS = {
    "3.18.12.63",
    "3.130.192.231",
    "13.235.14.237",
    "13.235.122.149",
    "18.211.135.69",
    "35.154.171.200",
    "52.15.183.38",
    "54.88.130.119",
    "54.88.130.237",
    "54.187.174.169",
    "54.187.205.235",
    "54.187.216.72",
    "35.157.207.129",
    "3.69.109.8",
    "3.120.168.93",
    "89.107.59.176", #fucah ip
}

# Hubtel webhook IPs (verify with Hubtel support)
HUBTEL_ALLOWED_CALLBACK_IPS = {
    "154.160.12.38",
    "154.160.12.39",
    "154.160.12.40",
    "154.160.12.41",
    "3.13.132.40",
    "3.130.120.28",
    "18.191.136.10",
    "89.107.59.176", #fucah ip
}

# Asoriba/MyBusinessPay — no published list, signature handles auth
ASORIBA_ALLOWED_CALLBACK_IPS = None

# Flutterwave — add when implemented
FLUTTERWAVE_ALLOWED_CALLBACK_IPS = None

# PayPal — uses API-based signature verification (not HMAC).
# No published static IP list; they recommend signature verification.
PAYPAL_ALLOWED_CALLBACK_IPS = None

# M-Pesa — Safaricom doesn't publish webhook IPs.
# Validation is via CheckoutRequestID matching + ResultCode.
MPESA_ALLOWED_CALLBACK_IPS = None




# ── Master registry for dynamic lookup ──
GATEWAY_ALLOWED_IPS = {
    "paystack": PAYSTACK_ALLOWED_CALLBACK_IPS,
    "stripe": STRIPE_ALLOWED_CALLBACK_IPS,
    "hubtel": HUBTEL_ALLOWED_CALLBACK_IPS,
    "asoriba": ASORIBA_ALLOWED_CALLBACK_IPS,
    "flutterwave": FLUTTERWAVE_ALLOWED_CALLBACK_IPS,
    "paypal": PAYPAL_ALLOWED_CALLBACK_IPS,
    "mpesa": MPESA_ALLOWED_CALLBACK_IPS,
}