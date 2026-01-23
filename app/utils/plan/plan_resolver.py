# app/utils/plan/plan_resolver.py
from flask import g
from ...models.admin.subscription_model import Subscription
from ...models.admin.package_model import Package
from ...utils.logger import Log

DEFAULT_FREE_PLAN = {
    "name": "Free Plan (Default)",
    "tier": "Free",
    "billing_period": "monthly",  # ✅ changed: no lifetime support
    "price": 0,
    "currency": "USD",
    "trial_days": 0,
    "max_users": 1,
    "max_outlets": 1,
    "max_products": 100,
    "max_transactions_per_month": 500,
    "storage_limit_gb": 1,
    "features": {
        "pos": True,
        "inventory": True,
        "reports": True,
        "multi_outlet": False,
        "api_access": False,
        "custom_branding": False,
        "priority_support": False,
        "advanced_analytics": False,
        "integrations": False,
        "mobile_app": True,
        "web_app": True,
        "backup_restore": False,
        "user_permissions": False,
        "discount_coupons": True,
        "loyalty_program": False,
        "email_notifications": True,
        "sms_notifications": False,
        "whatsapp_notifications": False,
    },
    "status": "Active",
}

class PlanResolver:
    """
    Resolves the active package for a business using your Models:
      - Subscription.get_active_by_business(business_id)
      - Package.get_by_id(package_id)

    Normalises:
      - pkg["limits"] from top-level max_* + storage_limit_gb
      - pkg["features"] always dict
    """

    @staticmethod
    def get_active_package(business_id: str) -> dict:
        business_id = str(business_id)
        cache_key = f"_plan_{business_id}"

        # per-request cache
        try:
            cached = g.get(cache_key)
        except Exception:
            cached = getattr(g, cache_key, None)

        if cached:
            return cached

        sub = Subscription.get_active_by_business(business_id)
        Log.info(f"PlanResolver: business_id={business_id} active subscription: {sub}")
        if not sub:
            pkg = DEFAULT_FREE_PLAN.copy()
            try:
                g[cache_key] = pkg
            except Exception:
                setattr(g, cache_key, pkg)
            return pkg

        pkg = Package.get_by_id(sub.get("package_id"))
        if not pkg:
            pkg = DEFAULT_FREE_PLAN.copy()

        # Normalise limits (supports both top-level max_* and nested limits)
        limits = (pkg.get("limits") or {}).copy()
        for k, v in pkg.items():
            if k.startswith("max_") or k in ("storage_limit_gb",):
                limits.setdefault(k, v)

        pkg["limits"] = limits
        pkg["features"] = pkg.get("features") or {}

        # Ensure billing_period exists (default monthly)
        if not pkg.get("billing_period"):
            pkg["billing_period"] = "monthly"

        try:
            g[cache_key] = pkg
        except Exception:
            setattr(g, cache_key, pkg)
        return pkg
