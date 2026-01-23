from app.utils.logger import Log

def rate(from_currency: str, to_currency: str) -> float:
    try:
        rate = None
        
        if from_currency == to_currency:
            rate = 1
            return rate

        
    except Exception as error:
        Log.error(f"[calculate_rate.py][rate] \t error: {error}")
        return 0.0
