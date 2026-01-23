from app.utils.logger import Log

def calculate_composite_fee(recipient_currency: str, amount: float, transaction_type=None) -> float:
    try:
        currency = recipient_currency.upper()
        amount = float(amount)
        
        if transaction_type == 'billpay':
            return get_billpay_fee(amount)
        else:
            if currency == "NGN":
                return get_nigeria_price(amount)
            elif currency == "GHS":
                return get_ghana_price(amount)
            elif currency == "BBD":
                return get_barbados_price(amount)
            else:
                return get_ghana_price(amount)
    except Exception as error:
        Log.error(f"[TransactionsController.py][InititateTransaction][calculate_fee] \t error: {error}")
        return 0.0

def get_nigeria_price(amount: float) -> float:
    Log.info("[calculation_engine.py][get_nigeria_price] \t calculating Nigeria price")
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

def get_ghana_price(amount: float) -> float:
    Log.info("[calculation_engine.py][get_ghana_price] \t calculating Ghana price")
    if amount <= 0:
        return 0

    for step in range(50, 2001, 50):
        if amount <= step:
            return 2 + (step // 50)

    return 80

def get_barbados_price(amount: float) -> float:
    Log.info("[calculation_engine.py][get_barbados_price] \t calculating Barbados price")

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


def get_billpay_fee(amount: float) -> float:
    Log.info(f"[calculate_composite_fee.py][get_billpay_price]")
    return 0