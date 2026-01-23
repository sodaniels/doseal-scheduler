import os
import hashlib
import json
import logging
from decimal import Decimal
# from services.external.process_rate_service import execute as rate_service_execute

# Calculation functions
def cal_receive_amount_with_rate(send_amount, rate):
    amount = Decimal(send_amount) * Decimal(rate)
    return float(round(amount, 2))

def cal_total_send_amount(send_amount, fee):
    amount = Decimal(send_amount) + Decimal(fee)
    return float(round(amount, 2))

def calculate_discounted_amount(amount):
    discount_percentage = Decimal("2.33")
    discount = (discount_percentage / Decimal("100.0")) * Decimal(amount)
    return float(round(Decimal(amount) - discount, 2))

def calculate_fee(account_type, amount):
    try:
        if account_type.upper() == "BANK":
            bank_fee = Decimal(os.getenv("SEND_TO_BANK_FEE", "0"))
            return float(round(bank_fee * Decimal(amount), 2))
        else:
            wallet_fee = Decimal(os.getenv("SEND_TO_WALLET_FEE", "0"))
            return float(round(wallet_fee * Decimal(amount), 2))
    except Exception as e:
        logging.error(f"[TransactionsController.py][calculate_fee] error: {e}")
        return 0.0

def cal_total_receive_amount(receive_amount, incentive):
    return float(round(Decimal(receive_amount) + Decimal(incentive), 2))

# Hashing functions
def hash_transaction(request):
    request = dict(request)
    transaction_string = json.dumps(request, sort_keys=True)
    return hashlib.sha256(transaction_string.encode()).hexdigest()

def verify_transaction(request, original_hash):
    request = dict(request)
    transaction_string = json.dumps(request, sort_keys=True)
    # request.pop("amount", None)
    new_hash = hashlib.sha256(transaction_string.encode()).hexdigest()
    return new_hash.upper() == original_hash

def hash_billpay_transaction(request):
    transaction_string = json.dumps(request, sort_keys=True)
    return hashlib.sha256(transaction_string.encode()).hexdigest()

def verify_billpay_transaction(request, original_hash):
    transaction_string = json.dumps(request, sort_keys=True)
    new_hash = hashlib.sha256(transaction_string.encode()).hexdigest()
    return new_hash.upper() == original_hash

async def get_rate(from_currency, to_currency):
    from_currency = from_currency.lower()
    to_currency = to_currency.lower()

    if from_currency == to_currency:
        return 1.0

    rate_response = await rate_service_execute(from_currency, to_currency)
    if rate_response and rate_response.get("success"):
        return float(rate_response["rates"]["rate"])

    return rate_response

def calculate_composite_fee(recipient_currency, amount):
    amount = float(amount)
    currency = recipient_currency.upper()
    if currency == "NGN":
        return get_nigeria_price(amount)
    elif currency == "BBD":
        return get_barbados_price(amount)
    return get_ghana_price(amount)

# Fee schedules
def get_ghana_price(amount):
    if amount <= 0:
        return 0
    caps = list(range(50, 2001, 50))
    for i, cap in enumerate(caps):
        if amount <= cap:
            return 2 + i
    return 80

def get_barbados_price(amount):
    logging.info("[calculation_engine.py][get_barbados_price] calculating Barbados price")
    if amount <= 0:
        return 0
    elif amount <= 50:
        return 0
    elif amount <= 100:
        return 2.7
    elif amount <= 500:
        return 4.8
    elif amount <= 750:
        return 5.4
    elif amount <= 1500:
        return 8.4
    elif amount <= 2000:
        return 9.6
    else:
        return 10.0

def get_nigeria_price(amount):
    logging.info("[calculation_engine.py][get_nigeria_price] calculating Nigeria price")
    
    if amount <= 0:
        return 0
    elif amount <= 100:
        return 5
    elif amount <= 200:
        return 10
    elif amount <= 300:
        return 14
    elif amount <= 400:
        return 18
    elif amount <= 500:
        return 20
    elif amount <= 600:
        return 24
    elif amount <= 700:
        return 28
    elif amount <= 800:
        return 30
    elif amount <= 900:
        return 35
    elif amount <= 1000:
        return 40
    elif amount <= 3000:
        return amount * 0.04
    else:
        return amount * 0.03

# Result formatting
def order_transaction_results(results):
    keys = [
        "sendAmount", "totalSendAmount", "receiveAmount", "totalReceiveAmount",
        "discountAmount", "incentive", "incentiveAmount", "incentiveAmountInReceiverCurrency",
        "fee", "rate", "billing_id", "sender_id", "paymentMode", "card", "isAgent",
        "senderFullName", "senderPhoneNumber", "senderCurrency", "senderCountryIso2",
        "senderAddress", "type", "recipientFullName", "recipientPhoneNumber", "recipientCountry",
        "recipientCountryIso2", "recipientCurrency", "bankName", "accountName", "recipientAccountNumber",
        "routingNumber", "mno"
    ]
    return {key: results.get(key) for key in keys if key in results}

def order_billpay_transaction_results(results):
    keys = [
        "destination_account", "send_amount", "receive_amount", "sender_currency",
        "recipient_name", "recipient_currency", "receiver_country", "sender_country",
        "fees", "rate"
    ]
    return {key: results.get(key) for key in keys if key in results}

# Agent commission calculations
def cal_agent_commission(transaction):
    if str(transaction.get("transaction_status")) == "200":
        details = json.loads(transaction.get("amount_details", "{}"))
        fee = Decimal(details.get("fee", 0))
    else:
        fee = Decimal(0)
    return str(round(fee * Decimal("0.6"), 2))

def cal_agent_total_commission(transactions):
    total = sum(Decimal(cal_agent_commission(tx)) for tx in transactions or [])
    return str(round(total, 2))

def cal_agent_total_sent(transactions):
    total = Decimal("0.0")
    for tx in transactions or []:
        if str(tx.get("transaction_status")) == "200":
            amount = Decimal(json.loads(tx.get("amount_details", "{}")).get("sendAmount", 0))
            total += amount
    return str(round(total, 2))

def cal_agent_total_amount_sent(transactions):
    total = Decimal("0.0")
    for tx in transactions or []:
        if str(tx.get("transaction_status")) == "200":
            amount = Decimal(json.loads(tx.get("amount_details", "{}")).get("totalSendAmount", 0))
            total += amount
    return str(round(total, 2))
