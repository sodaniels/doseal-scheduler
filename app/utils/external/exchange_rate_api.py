import requests

from ...config import Config

def get_exchange_rate(from_currency: str, to_currency: str) -> float | None:
    """
    Get the latest exchange rate from `from_currency` to `to_currency`
    using ExchangeRate-API (free / standard endpoint).

    Example:
        get_exchange_rate("USD", "EUR")  # => e.g. 0.91
    """
    base = from_currency.upper()
    target = to_currency.upper()
    
    API_KEY = Config.EXCHANGERATE_API_KEY

    url = f"https://v6.exchangerate-api.com/v6/{API_KEY}/latest/{base}"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error fetching rates: {e}")
        return None

    if data.get("result") != "success":
        print("API error:", data)
        return None

    rates = data.get("conversion_rates", {})
    rate = rates.get(target)
    if rate is None:
        print(f"Currency {target} not found in response.")
    return rate
