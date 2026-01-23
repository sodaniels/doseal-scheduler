# app/utils/plan/release_component.py
from flask import g
from .limits_map import LIMIT_RULES
from .quota_enforcer import QuotaEnforcer

def release_component(component: str, qty: int = 1, business_id: str | None = None):
    """
    Releases quota for a component using the same LIMIT_RULES mapping used by enforce_component().
    """
    rule = LIMIT_RULES.get(component)
    if not rule:
        return  # not limited, nothing to release

    # resolve business_id
    if not business_id:
        user = g.get("current_user", {}) or {}
        business_id = user.get("business_id")

    if not business_id:
        return

    enforcer = QuotaEnforcer(str(business_id))
    enforcer.release(
        counter_name=rule["counter"],
        qty=int(qty),
        period=rule.get("period", "billing"),
    )
