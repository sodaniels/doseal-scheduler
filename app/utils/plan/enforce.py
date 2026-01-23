# app/utils/plan/enforce.py
from functools import wraps
from flask import g
from ...utils.json_response import prepared_response
from .quota_enforcer import QuotaEnforcer, PlanLimitError

def enforce_plan(*, feature=None, limit_key=None, counter=None, qty=1, period="billing", business_id_resolver=None):
    """
    business_id_resolver: optional callable (args, kwargs) -> business_id
      - If not provided, defaults to g.current_user.business_id
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = g.get("current_user", {}) or {}

            # ✅ resolve target business_id
            if callable(business_id_resolver):
                business_id = business_id_resolver(args, kwargs)
            else:
                business_id = user.get("business_id")

            if not business_id:
                return prepared_response(False, "UNAUTHORIZED", "Authentication required.")

            enforcer = QuotaEnforcer(str(business_id))

            reserved = False
            try:
                if feature:
                    enforcer.require_feature(feature)

                if limit_key and counter:
                    enforcer.reserve(
                        counter_name=counter,
                        limit_key=limit_key,
                        qty=qty,
                        period=period,
                        reason=f"{fn.__name__}:{counter}",
                    )
                    reserved = True

                rv = fn(*args, **kwargs)

                # if your enforce.py already has the "release on failure" logic, keep it here
                return rv

            except PlanLimitError as e:
                return prepared_response(False, "FORBIDDEN", e.message, errors=e.meta)

            except Exception:
                if reserved and limit_key and counter:
                    try:
                        enforcer.release(counter_name=counter, qty=qty, period=period)
                    except Exception:
                        pass
                raise
        return wrapper
    return decorator
