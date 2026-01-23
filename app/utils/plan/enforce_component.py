# app/utils/plan/enforce_component.py
from .enforce import enforce_plan
from .limits_map import LIMIT_RULES

def enforce_component(component: str, qty: int = 1, business_id_resolver=None):
    rule = LIMIT_RULES.get(component)
    if not rule:
        def passthrough(fn): return fn
        return passthrough

    return enforce_plan(
        feature=rule.get("feature"),
        limit_key=rule.get("limit_key"),
        counter=rule.get("counter"),
        qty=qty,
        period=rule.get("period", "billing"),
        business_id_resolver=business_id_resolver,  # ✅
    )
