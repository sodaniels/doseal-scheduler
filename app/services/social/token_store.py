# app/services/social/token_store.py
from datetime import datetime, timezone

def is_expired(expires_at) -> bool:
    if not expires_at:
        return False
    try:
        dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).astimezone(timezone.utc)
        return dt <= datetime.now(timezone.utc)
    except Exception:
        return False