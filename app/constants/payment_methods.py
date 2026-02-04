# constants/payment_methods.py

"""
Payment method constants for the application.
Centralized payment method definitions.
"""

PAYMENT_METHODS = {
    # Card Payments
    "CREDIT_CARD": "credit_card",
    "DEBIT_CARD": "debit_card",
    
    # Digital Wallets
    "MOBILE_MONEY": "mobile_money",
    "PAYPAL": "paypal",
    "STRIPE": "stripe",
    
    # Bank Transfers
    "BANK_TRANSFER": "bank_transfer",
    "WIRE_TRANSFER": "wire_transfer",
    "ACH": "ach",
    
    # Cash
    "CASH": "cash",
    
    # Mobile Payment Platforms (East Africa)
    "MPESA": "mpesa",
    "AIRTEL_MONEY": "airtel_money",
    "TIGO_PESA": "tigo_pesa",
    
    # Mobile Payment Platforms (West Africa)
    "MTN_MOBILE_MONEY": "mtn_mobile_money",
    "VODAFONE_CASH": "vodafone_cash",
    "ORANGE_MONEY": "orange_money",
    
    "ASORIBA": "asoriba",
    
    # African Payment Gateways
    "FLUTTERWAVE": "flutterwave",
    "PAYSTACK": "paystack",
    "INTERSWITCH": "interswitch",
    
    # Hubtel (Ghana)
    "HUBTEL": "hubtel",
    "HUBTEL_MOBILE_MONEY": "hubtel_mobile_money",
    "HUBTEL_CARD": "hubtel_card",
    
    # Other Methods
    "CHECK": "check",
    "CRYPTOCURRENCY": "cryptocurrency",
    "DIRECT_DEBIT": "direct_debit",
}


# Helper function to get all payment method values
def get_all_payment_methods():
    """Get list of all payment method values."""
    return list(PAYMENT_METHODS.values())


# Helper function to validate payment method
def is_valid_payment_method(method):
    """Check if payment method is valid."""
    return method in PAYMENT_METHODS.values()


# Payment method display names
PAYMENT_METHOD_NAMES = {
    "credit_card": "Credit Card",
    "debit_card": "Debit Card",
    "mobile_money": "Mobile Money",
    "paypal": "PayPal",
    "stripe": "Stripe",
    "bank_transfer": "Bank Transfer",
    "wire_transfer": "Wire Transfer",
    "ach": "ACH Transfer",
    "cash": "Cash",
    "mpesa": "M-Pesa",
    "airtel_money": "Airtel Money",
    "tigo_pesa": "Tigo Pesa",
    "mtn_mobile_money": "MTN Mobile Money",
    "vodafone_cash": "Vodafone Cash",
    "orange_money": "Orange Money",
    "flutterwave": "Flutterwave",
    "paystack": "Paystack",
    "interswitch": "Interswitch",
    "check": "Check/Cheque",
    "cryptocurrency": "Cryptocurrency",
    "direct_debit": "Direct Debit",
    #hubtel
    "hubtel": "Hubtel",
    "hubtel_mobile_money": "Hubtel Mobile Money",
    "hubtel_card": "Hubtel Card Payment",
}


# Payment method categories
PAYMENT_METHOD_CATEGORIES = {
    "card": ["credit_card", "debit_card"],
    "mobile_money": [
        "mobile_money", "mpesa", "airtel_money", "tigo_pesa",
        "mtn_mobile_money", "vodafone_cash", "orange_money"
    ],
    "bank": ["bank_transfer", "wire_transfer", "ach", "direct_debit"],
    "gateway": ["flutterwave", "paystack", "interswitch", "stripe", "paypal", "hubtel"],
    "cash": ["cash"],
    "crypto": ["cryptocurrency"],
    "other": ["check"],
}


# Regional payment methods
REGIONAL_PAYMENT_METHODS = {
    "kenya": ["mpesa", "airtel_money", "credit_card", "bank_transfer"],
    "ghana": [
        "mtn_mobile_money", 
        "vodafone_cash", 
        "airtel_money", 
        "credit_card",
        "hubtel",  # ✅ Added
        "hubtel_mobile_money",  # ✅ Added
    ],
    "nigeria": ["paystack", "flutterwave", "interswitch", "bank_transfer"],
    "uganda": ["mtn_mobile_money", "airtel_money", "credit_card"],
    "tanzania": ["mpesa", "tigo_pesa", "airtel_money", "credit_card"],
    "international": ["credit_card", "debit_card", "paypal", "stripe", "cryptocurrency"],
}