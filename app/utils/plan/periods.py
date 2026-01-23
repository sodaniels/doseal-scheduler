# app/utils/plan/periods.py
from datetime import datetime, timezone

def month_key(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")  # e.g. 2025-12

def year_key(dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    return dt.strftime("%Y")  # e.g. 2025

def resolve_quota_period_from_billing(billing_period: str | None) -> str:
    """
    Convert package.billing_period to quota period.
    We do NOT support 'lifetime' quotas anymore.
    - yearly  -> year (YYYY)
    - monthly -> month (YYYY-MM)
    - quarterly -> month (YYYY-MM) (quota resets monthly unless you later add quarter quotas)
    """
    bp = (billing_period or "").strip().lower()
    if bp == "yearly":
        return "year"
    return "month"

def period_key(period: str, dt: datetime | None = None) -> str:
    if period == "year":
        return year_key(dt)
    return month_key(dt)
