# app/utils/plan/quota_enforcer.py
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from bson import ObjectId
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

    Supports "flat" package limits (NOT nested under package["limits"]).
    Example package:
      {
        "tier": "Standard",
        "billing_period": "monthly",
        "features": {...},
        "max_social_accounts": 1,
        "max_users": 1,
        "trial_days": 14,
        ...
      }

    IMPORTANT FIXES INCLUDED:
      ✅ No conflicting updates on 'counters' (we never set counters:{} while $inc counters.x)
      ✅ Finite-limit path NEVER uses upsert=True on the conditional increment
         (prevents inserting a new business_usage doc when limit is reached)
      ✅ Creates the base usage doc first (safe upsert), then conditionally increments (upsert=False)
      ✅ Handles potential race DuplicateKeyError by retrying the conditional increment
    """

    USAGE_COLLECTION = "business_usage"

    # Optional: allow bypassing limits in local/dev:
    #   DISABLE_PLAN_LIMITS=true
    DISABLE_LIMITS_ENV = "DISABLE_PLAN_LIMITS"

    def __init__(self, business_id: str):
        self.business_id = str(business_id)
        self.package = PlanResolver.get_active_package(self.business_id) or {}

    def _usage_col(self):
        return db.get_collection(self.USAGE_COLLECTION)

    def _limits_disabled(self) -> bool:
        return os.getenv(self.DISABLE_LIMITS_ENV, "false").strip().lower() in ("1", "true", "yes")

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
        """
        NEW: limits are flat keys on the package (e.g. package["max_social_accounts"]).

        Returns:
          - int-like value for finite limits
          - None for "unlimited" (if not present)
        """
        # prefer explicit flat key
        if limit_key in self.package:
            return self.package.get(limit_key)

        # backward compat if some docs still have {"limits": {...}}
        limits_obj = self.package.get("limits") or {}
        if isinstance(limits_obj, dict) and limit_key in limits_obj:
            return limits_obj.get(limit_key)

        return None

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
    ) -> Dict[str, Any]:
        """
        Atomically increment counters.<counter_name> up to package[limit_key].

        Example usage:
          enforcer.reserve(counter_name="social_accounts", limit_key="max_social_accounts", qty=1)

        Notes:
          - If limit_key does not exist => treated as unlimited (None).
          - If DISABLE_PLAN_LIMITS=true => treated as unlimited.
        """
        qty = int(qty)
        if qty <= 0:
            return {"reserved": 0}

        tier = self.package.get("tier")
        limit = None if self._limits_disabled() else self.get_limit(limit_key)

        resolved_period = self.resolve_period(period)  # month/year
        key = period_key(resolved_period, dt)
        now = datetime.now(timezone.utc)

        # IMPORTANT: use ObjectId in selector, but store string in inserted doc (you already had this)
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
                        "business_id": self.business_id,  # keep your existing storage format
                        "period": resolved_period,
                        "period_key": key,
                        "created_at": now,
                    },
                    "$set": {"updated_at": now},
                },
                upsert=True,
            )
        except DuplicateKeyError:
            pass

        # Unlimited => always allow increment
        if limit is None:
            doc = self._usage_col().find_one_and_update(
                base_selector,
                {
                    "$inc": {f"counters.{counter_name}": qty},
                    "$set": {"updated_at": now},
                },
                upsert=False,
                return_document=ReturnDocument.AFTER,
            )
            return {
                "reserved": qty,
                "limit": None,
                "doc": doc,
                "period": resolved_period,
                "period_key": key,
                "limits_disabled": self._limits_disabled(),
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

        if limit_int < 0:
            raise PlanLimitError(
                "PACKAGE_LIMIT_INVALID",
                f"Package limit must be >= 0: {limit_key}",
                meta={"limit_key": limit_key, "value": limit_int, "tier": tier},
            )

        # If qty itself is bigger than limit, fail early with a clean message
        if qty > limit_int:
            raise PlanLimitError(
                "PACKAGE_LIMIT_REACHED",
                f"Package limit reached for {limit_key}. Upgrade your plan to continue.",
                meta={
                    "limit_key": limit_key,
                    "counter": counter_name,
                    "limit": limit_int,
                    "current": None,
                    "attempted": qty,
                    "tier": tier,
                    "period": resolved_period,
                    "period_key": key,
                    "reason": reason,
                    "billing_period": self.package.get("billing_period"),
                },
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
                upsert=False,  # ✅ do NOT create a new doc when limit is reached
                return_document=ReturnDocument.AFTER,
            )

        try:
            doc = _try_conditional_inc()
        except DuplicateKeyError:
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
            "limits_disabled": self._limits_disabled(),
        }

    def release(
        self,
        *,
        counter_name: str,
        qty: int = 1,
        period: str = "billing",
        dt=None,
    ):
        """
        Release previously reserved quota units.
        Typically call this when a connect/create fails AFTER reserve().
        """
        qty = int(qty)
        if qty <= 0:
            return

        resolved_period = self.resolve_period(period)
        key = period_key(resolved_period, dt)
        now = datetime.now(timezone.utc)

        base_selector = {
            "business_id": self.business_id,  # keep consistent with how you store it in the doc
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