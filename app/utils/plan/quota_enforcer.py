# app/utils/plan/quota_enforcer.py
from __future__ import annotations

from datetime import datetime, timezone
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ...extensions.db import db
from .plan_resolver import PlanResolver
from .periods import resolve_quota_period_from_billing, period_key


class PlanLimitError(Exception):
    def __init__(self, code: str, message: str, meta=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.meta = meta or {}


class QuotaEnforcer:
    """
    Central plan enforcement:
      - Feature gates
      - Quotas (limits)
      - Atomic reserve/release

    IMPORTANT FIXES INCLUDED:
      ✅ No conflicting updates on 'counters' (we never set counters:{} while $inc counters.x)
      ✅ Finite-limit path NEVER uses upsert=True on the conditional increment
         (prevents inserting a new business_usage doc when limit is reached)
      ✅ Creates the base usage doc first (safe upsert), then conditionally increments (upsert=False)
      ✅ Handles potential race DuplicateKeyError by retrying the conditional increment
    """

    USAGE_COLLECTION = "business_usage"

    def __init__(self, business_id: str):
        self.business_id = str(business_id)
        self.package = PlanResolver.get_active_package(self.business_id)

    def _usage_col(self):
        return db.get_collection(self.USAGE_COLLECTION)

    # ---------------- Features ----------------
    def has_feature(self, feature_key: str) -> bool:
        return bool((self.package.get("features") or {}).get(feature_key, False))

    def require_feature(self, feature_key: str):
        if not self.has_feature(feature_key):
            raise PlanLimitError(
                "FEATURE_NOT_AVAILABLE",
                f"This feature is not available on your current plan: {feature_key}",
                meta={"feature": feature_key, "tier": self.package.get("tier")},
            )

    # ---------------- Limits ----------------
    def get_limit(self, limit_key: str):
        return (self.package.get("limits") or {}).get(limit_key)

    # ---------------- Period ----------------
    def resolve_period(self, period: str | None) -> str:
        """
        period:
          - "billing" => derived from package.billing_period
          - "month" or "year" => explicit override
        """
        p = (period or "billing").strip().lower()
        if p == "billing":
            return resolve_quota_period_from_billing(self.package.get("billing_period"))
        if p in ("month", "year"):
            return p
        return resolve_quota_period_from_billing(self.package.get("billing_period"))

    # ---------------- Reserve / Release ----------------
    def reserve(
        self,
        *,
        counter_name: str,
        limit_key: str,
        qty: int = 1,
        period: str = "billing",
        dt=None,
        reason: str = "",
    ) -> dict:
        qty = int(qty)
        if qty <= 0:
            return {"reserved": 0}

        tier = self.package.get("tier")
        limit = self.get_limit(limit_key)

        resolved_period = self.resolve_period(period)  # month/year
        key = period_key(resolved_period, dt)
        now = datetime.now(timezone.utc)

        base_selector = {
            "business_id": self.business_id,
            "period": resolved_period,
            "period_key": key,
        }

        # 1) Ensure base usage document exists (safe upsert)
        #    (NO 'counters': {} here to avoid conflict with $inc counters.<x>)
        try:
            self._usage_col().update_one(
                base_selector,
                {
                    "$setOnInsert": {
                        "business_id": self.business_id,
                        "period": resolved_period,
                        "period_key": key,
                        "created_at": now,
                    },
                    "$set": {"updated_at": now},
                },
                upsert=True,
            )
        except DuplicateKeyError:
            # Another request created it first; OK.
            pass

        # Unlimited => always allow increment
        if limit is None:
            doc = self._usage_col().find_one_and_update(
                base_selector,
                {
                    "$inc": {f"counters.{counter_name}": qty},
                    "$set": {"updated_at": now},
                },
                upsert=False,  # base doc is ensured above
                return_document=ReturnDocument.AFTER,
            )
            return {
                "reserved": qty,
                "limit": None,
                "doc": doc,
                "period": resolved_period,
                "period_key": key,
            }

        # Finite limit
        try:
            limit_int = int(limit)
        except Exception:
            raise PlanLimitError(
                "PACKAGE_LIMIT_INVALID",
                f"Package limit misconfigured: {limit_key}",
                meta={"limit_key": limit_key, "value": limit, "tier": tier},
            )

        # 2) Conditional increment WITHOUT upsert (CRITICAL)
        filter_q = {
            **base_selector,
            "$or": [
                {f"counters.{counter_name}": {"$exists": False}},
                {f"counters.{counter_name}": {"$lte": (limit_int - qty)}},
            ],
        }

        def _try_conditional_inc():
            return self._usage_col().find_one_and_update(
                filter_q,
                {
                    "$inc": {f"counters.{counter_name}": qty},
                    "$set": {"updated_at": now},
                },
                upsert=False,  # ✅ prevents creating new doc when limit is reached
                return_document=ReturnDocument.AFTER,
            )

        try:
            doc = _try_conditional_inc()
        except DuplicateKeyError:
            # Rare race: retry once
            doc = _try_conditional_inc()

        if not doc:
            existing = self._usage_col().find_one(
                base_selector,
                {f"counters.{counter_name}": 1},
            ) or {}
            current = int(((existing.get("counters") or {}).get(counter_name)) or 0)

            raise PlanLimitError(
                "PACKAGE_LIMIT_REACHED",
                f"Package limit reached for {limit_key}. Upgrade your plan to continue.",
                meta={
                    "limit_key": limit_key,
                    "counter": counter_name,
                    "limit": limit_int,
                    "current": current,
                    "attempted": qty,
                    "tier": tier,
                    "period": resolved_period,
                    "period_key": key,
                    "reason": reason,
                    "billing_period": self.package.get("billing_period"),
                },
            )

        return {
            "reserved": qty,
            "limit": limit_int,
            "doc": doc,
            "period": resolved_period,
            "period_key": key,
        }

    def release(
        self,
        *,
        counter_name: str,
        qty: int = 1,
        period: str = "billing",
        dt=None,
    ):
        qty = int(qty)
        if qty <= 0:
            return

        resolved_period = self.resolve_period(period)
        key = period_key(resolved_period, dt)
        now = datetime.now(timezone.utc)

        base_selector = {
            "business_id": self.business_id,
            "period": resolved_period,
            "period_key": key,
        }

        self._usage_col().update_one(
            base_selector,
            {
                "$inc": {f"counters.{counter_name}": -qty},
                "$set": {"updated_at": now},
            },
            upsert=False,
        )
