from datetime import datetime, timezone, timedelta


def parse_token_expiry(val):
    """
    Normalize token_expires_at into datetime or None.
    Accepts:
      - datetime
      - ISO string
      - unix timestamp (seconds)
    """
    if not val:
        return None

    if isinstance(val, datetime):
        return val

    # ISO string
    if isinstance(val, str):
        try:
            return datetime.fromisoformat(val.replace("Z", "+00:00"))
        except Exception:
            return None

    # unix timestamp
    try:
        return datetime.fromtimestamp(float(val), tz=timezone.utc)
    except Exception:
        return None


def is_token_expired(acct: dict) -> bool:
    exp_dt = parse_token_expiry(acct.get("token_expires_at"))
    if not exp_dt:
        # No expiry recorded => treat as valid
        return False

    return exp_dt <= datetime.now(timezone.utc)


def is_token_expiring_soon(acct: dict, minutes: int = 10) -> bool:
    exp_dt = parse_token_expiry(acct.get("token_expires_at"))
    if not exp_dt:
        return False

    return exp_dt <= datetime.now(timezone.utc) + timedelta(minutes=minutes)