# app/utils/plan/plan_change.py

from __future__ import annotations

from datetime import datetime, timedelta
from bson import ObjectId
from typing import Optional

from ...extensions.db import db
from ...models.admin.subscription_model import Subscription
from ...models.admin.package_model import Package
from ...models.admin.setup_model import Outlet
from ...utils.crypt import encrypt_data, hash_data
from ...utils.logger import Log


class PlanChangeService:
    """
    Apply plan changes (upgrade/downgrade) AFTER payment confirmation.
    """

    # ------------------------------------------------------------------
    # PLAN COMPARISON
    # ------------------------------------------------------------------
    @staticmethod
    def is_downgrade(active_pkg: dict, new_pkg: dict) -> bool:
        """
        Decide whether moving from active_pkg -> new_pkg is a downgrade.

        Heuristic:
          1) If both have a numeric "rank" / "tier_rank", lower rank is downgrade.
          2) Else compare important limits: if any limit gets smaller => downgrade.
          3) Else compare price: if new is cheaper => downgrade.
          4) Otherwise not downgrade.

        NOTE: Adjust the field names to match how you store Package docs.
        """
        if not isinstance(active_pkg, dict) or not isinstance(new_pkg, dict):
            return False

        # 1) Rank/tier ordering (recommended if you have it)
        for key in ("tier_rank", "rank", "plan_rank", "tier", "order"):
            a = active_pkg.get(key)
            b = new_pkg.get(key)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return b < a

        # 2) Limits comparison
        limit_keys = [
            "max_users",
            "max_outlets",
            "max_products",
            "max_transactions_per_month",
            "storage_limit_gb",
        ]

        def _as_int(x):
            try:
                if x is None:
                    return None
                return int(x)
            except Exception:
                return None

        for k in limit_keys:
            a = _as_int(active_pkg.get(k))
            b = _as_int(new_pkg.get(k))

            # None means unlimited (treat as very large)
            if a is None and b is None:
                continue
            if a is None and b is not None:
                # unlimited -> limited = downgrade
                return True
            if a is not None and b is None:
                # limited -> unlimited = upgrade (not downgrade)
                continue
            if a is not None and b is not None and b < a:
                return True

        # 3) Price fallback
        try:
            a_price = float(active_pkg.get("price") or 0)
            b_price = float(new_pkg.get("price") or 0)
            if b_price < a_price:
                return True
        except Exception:
            pass

        return False

    # ------------------------------------------------------------------
    # SUBSCRIPTION APPLY (IMMEDIATE UPGRADE FLOW)
    # ------------------------------------------------------------------
    @staticmethod
    def apply_new_subscription(
        business_id: str,
        package_id: str,
        billing_period: str,
        payment_id: Optional[str] = None,
        payment_reference: Optional[str] = None,
        payment_method: Optional[str] = None,
        user_id: Optional[str] = None,
        user__id: Optional[str] = None,
        source: str = "payment_callback",
    ) -> Optional[str]:
        """
        Upgrade flow: deactivate current access subscription(s) and create a new ACTIVE subscription.
        """
        log_tag = "[PlanChangeService][apply_new_subscription]"

        try:
            business_oid = ObjectId(str(business_id))
            package_oid = ObjectId(str(package_id))
        except Exception as e:
            Log.error(f"{log_tag} invalid business_id/package_id: {e}")
            return None

        pkg = Package.get_by_id(str(package_oid))
        if not pkg:
            Log.error(f"{log_tag} package not found: {package_id}")
            return None

        now = datetime.utcnow()
        sub_col = db.get_collection(Subscription.collection_name)

        # Deactivate previous access-granting subscriptions (ACTIVE/TRIAL)
        # Your Subscription model stores status encrypted + hashed; use hashed.
        sub_col.update_many(
            {
                "business_id": business_oid,
                "hashed_status": {"$in": [hash_data(Subscription.STATUS_ACTIVE), hash_data(Subscription.STATUS_TRIAL)]},
            },
            {
                "$set": {
                    "status": encrypt_data(Subscription.STATUS_INACTIVE),
                    "hashed_status": hash_data(Subscription.STATUS_INACTIVE),
                    "ended_at": now,
                    "updated_at": now,
                }
            },
        )

        # Compute end_date from billing_period (use Package.billing_period if you want strict validation)
        end_date = PlanChangeService._compute_end_date(now, billing_period)
        next_payment_date = end_date

        new_sub = Subscription(
            business_id=str(business_oid),
            package_id=str(package_oid),
            status=Subscription.STATUS_ACTIVE,
            billing_period=billing_period,
            payment_id=payment_id,
            payment_reference=payment_reference,
            payment_method=payment_method,
            user_id=user_id,
            user__id=user__id,
            source=source,
            start_date=now,
            end_date=end_date,
            next_payment_date=next_payment_date,
            last_payment_date=now if payment_reference else None,
        )

        sub_id = new_sub.save()
        Log.info(f"{log_tag} new subscription created: {sub_id}")

        # Enforce downgrade-sensitive limits (safe to run for upgrade too)
        PlanChangeService.enforce_all_limits(business_id=str(business_id), package_doc=pkg)

        return str(sub_id) if sub_id else None

    @staticmethod
    def _compute_end_date(start: datetime, billing_period: str):
        bp = (billing_period or "").lower().strip()
        if bp == "monthly":
            return start + timedelta(days=30)
        if bp == "quarterly":
            return start + timedelta(days=90)
        if bp == "yearly":
            return start + timedelta(days=365)
        if bp == "lifetime":
            return None
        return start + timedelta(days=30)

    # =====================================================
    # MAIN ENTRY POINT
    # =====================================================
    @staticmethod
    def enforce_all_limits(business_id: str, package_doc: dict):
        """
        Enforce all downgrade-sensitive limits.
        Called when:
          - a scheduled subscription becomes active
          - or after applying new subscription
        """
        Log.info(f"[PlanChangeService] Enforcing limits for business {business_id}")

        # Order matters: structural → operational
        PlanChangeService._enforce_outlet_limit(business_id, package_doc)
        # Future additions:
        # PlanChangeService._enforce_product_limit(...)
        # PlanChangeService._enforce_user_limit(...)
        # PlanChangeService._enforce_transaction_limit(...)

    # =====================================================
    # OUTLET LIMIT (SINGLE CORRECT VERSION)
    # =====================================================
    @staticmethod
    def _enforce_outlet_limit(business_id: str, package_doc: dict) -> None:
        """
        Enforce max_outlets by deactivating extra outlets.
        Never deletes data.
        Keeps oldest outlets active and disables the rest.
        """
        log_tag = "[PlanChangeService][_enforce_outlet_limit]"

        # Your Package may store "max_outlets" directly OR inside "limits".
        limits = (package_doc.get("limits") or {}).copy()
        if "max_outlets" not in limits and package_doc.get("max_outlets") is not None:
            limits["max_outlets"] = package_doc.get("max_outlets")

        max_outlets = limits.get("max_outlets")

        # Unlimited
        if max_outlets is None:
            Log.info(f"{log_tag} unlimited max_outlets, skip")
            return

        try:
            max_outlets = int(max_outlets)
        except Exception:
            Log.info(f"{log_tag} invalid max_outlets={max_outlets}, skip")
            return

        if max_outlets <= 0:
            Log.info(f"{log_tag} max_outlets<=0 treated as unlimited, skip")
            return

        try:
            business_oid = ObjectId(str(business_id))
        except Exception:
            return

        outlet_col = db.get_collection(Outlet.collection_name)

        # Outlet statuses are encrypted in your system; use encrypted values
        enc_active = encrypt_data("Active")
        enc_inactive = encrypt_data("Inactive")

        active_outlets = list(
            outlet_col.find({"business_id": business_oid, "status": enc_active})
            .sort("created_at", 1)  # oldest first
        )

        if len(active_outlets) <= max_outlets:
            Log.info(f"{log_tag} outlets compliant {len(active_outlets)}/{max_outlets}")
            return

        to_disable = active_outlets[max_outlets:]
        to_disable_ids = [o["_id"] for o in to_disable]

        res = outlet_col.update_many(
            {"_id": {"$in": to_disable_ids}},
            {
                "$set": {
                    "status": enc_inactive,
                    "disabled_reason": encrypt_data("Plan downgrade"),
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        Log.warning(
            f"{log_tag} downgraded business={business_id}: "
            f"disabled {res.modified_count} outlets to meet max_outlets={max_outlets}"
        )