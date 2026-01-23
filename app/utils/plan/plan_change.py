# app/utils/plan/plan_change.py

from datetime import datetime
from bson import ObjectId

from ...extensions.db import db
from ...models.admin.subscription_model import Subscription
from ...models.admin.package_model import Package
from ...models.admin.setup_model import Outlet
from ...utils.crypt import encrypt_data
from ...utils.logger import Log


class PlanChangeService:
    """
    Apply plan changes (upgrade/downgrade) AFTER payment confirmation.
    """

    @staticmethod
    def apply_new_subscription(
        business_id: str,
        package_id: str,
        billing_period: str,
        payment_id: str | None = None,
        payment_reference: str | None = None,
        payment_method: str | None = None,
        user_id: str | None = None,
        user__id: str | None = None,
        source: str = "payment_callback",
    ) -> str | None:
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

        # If your Package stores billing_period in the doc, you can validate here:
        # if billing_period != pkg.get("billing_period"): ...

        sub_col = db.get_collection(Subscription.collection_name)
        now = datetime.utcnow()

        # 1) Deactivate previous Active subscriptions (business-scoped)
        sub_col.update_many(
            {"business_id": business_oid, "status": "Active"},
            {"$set": {"status": "Inactive", "ended_at": now, "updated_at": now}},
        )

        # 2) Create new Active subscription
        # Adapt field names to your Subscription model if needed.
        new_sub = Subscription(
            business_id=str(business_oid),
            package_id=str(package_oid),
            status="Active",
            billing_period=billing_period,
            payment_id=payment_id,
            payment_reference=payment_reference,
            payment_method=payment_method,
            user_id=user_id,
            user__id=user__id,
            source=source,
            started_at=now,
        )

        sub_id = new_sub.save()
        Log.info(f"{log_tag} new subscription created: {sub_id}")

        # 3) Enforce limits right now (downgrade enforcement)
        PlanChangeService._enforce_outlet_limit(business_id=str(business_id), package_doc=pkg)

        return str(sub_id) if sub_id else None

    @staticmethod
    def _enforce_outlet_limit(business_id: str, package_doc: dict) -> None:
        """
        Enforce max_outlets by deactivating extra outlets.
        Keeps oldest outlets Active and disables the rest.
        """
        log_tag = "[PlanChangeService][_enforce_outlet_limit]"

        # Your PlanResolver normalises limits into pkg["limits"].
        limits = (package_doc.get("limits") or {}).copy()
        for k, v in package_doc.items():
            if k.startswith("max_") or k in ("storage_limit_gb",):
                limits.setdefault(k, v)

        max_outlets = limits.get("max_outlets")
        if max_outlets is None:
            Log.info(f"{log_tag} unlimited max_outlets, skip")
            return

        try:
            business_oid = ObjectId(str(business_id))
        except Exception:
            return

        col = db.get_collection(Outlet.collection_name)
        enc_active = encrypt_data("Active")
        enc_inactive = encrypt_data("Inactive")

        active_outlets = list(
            col.find({"business_id": business_oid, "status": enc_active}).sort("created_at", 1)
        )

        if len(active_outlets) <= int(max_outlets):
            Log.info(f"{log_tag} active_outlets <= max_outlets, ok")
            return

        to_disable_ids = [o["_id"] for o in active_outlets[int(max_outlets):]]

        res = col.update_many(
            {"_id": {"$in": to_disable_ids}},
            {"$set": {"status": enc_inactive}},
        )

        Log.info(
            f"{log_tag} downgraded business={business_id}: "
            f"disabled {res.modified_count} outlets to meet max_outlets={max_outlets}"
        )


    # =====================================================
    # MAIN ENTRY POINT
    # =====================================================
    @staticmethod
    def enforce_all_limits(business_id: str, package_doc: dict):
        """
        Enforce all downgrade-sensitive limits.
        Called ONLY when a scheduled subscription becomes active.
        """

        Log.info(f"[PlanChangeService] Enforcing limits for business {business_id}")

        # Order matters: structural → operational
        PlanChangeService._enforce_outlet_limit(business_id, package_doc)
        # Future additions:
        # PlanChangeService._enforce_product_limit(...)
        # PlanChangeService._enforce_user_limit(...)
        # PlanChangeService._enforce_pos_limit(...)
        # PlanChangeService._enforce_transaction_limit(...)

    # =====================================================
    # OUTLET LIMIT (CRITICAL)
    # =====================================================
    @staticmethod
    def _enforce_outlet_limit(business_id: str, package_doc: dict):
        """
        Disable outlets beyond plan limit.
        Never deletes data.
        """

        max_outlets = package_doc.get("max_outlets")

        # Unlimited
        if max_outlets in (None, 0):
            return

        business_oid = ObjectId(business_id)
        outlet_col = db.get_collection(Outlet.collection_name)

        # Get ACTIVE outlets only
        active_outlets = list(
            outlet_col.find(
                {
                    "business_id": business_oid,
                    "status": {"$ne": "Disabled"},
                }
            ).sort("created_at", 1)  # oldest first
        )

        if len(active_outlets) <= max_outlets:
            return  # ✅ compliant

        # Disable excess outlets
        excess = active_outlets[max_outlets:]

        outlet_ids = [o["_id"] for o in excess]

        outlet_col.update_many(
            {"_id": {"$in": outlet_ids}},
            {
                "$set": {
                    "status": "Disabled",
                    "disabled_reason": "Plan downgrade",
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        Log.warning(
            f"[PlanChangeService] Disabled {len(outlet_ids)} outlets for business {business_id}"
        )





