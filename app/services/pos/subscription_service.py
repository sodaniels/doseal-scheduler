# app/services/pos/subscription_service.py

from datetime import datetime, timedelta
from bson import ObjectId
from typing import Optional, Tuple

from ...models.admin.package_model import Package
from ...models.admin.payment import Payment
from ...models.admin.subscription_model import Subscription
from ...utils.logger import Log
from ...extensions.db import db
from ...utils.plan.plan_change import PlanChangeService
from ...utils.crypt import hash_data, encrypt_data, decrypt_data
from ...utils.json_response import prepared_response


class SubscriptionService:
    """
    Central subscription lifecycle service.

    RULES:
      - Cancel DOES NOT mutate history
      - Renew ALWAYS creates new subscription term
      - Only ONE Active/Trial subscription per business
      - Upgrades apply immediately
      - Downgrades scheduled
      - Scheduled subs activate when start_date reached
    """

    # ---------------------------------------------------------
    # INTERNAL HELPERS
    # ---------------------------------------------------------
    # -------------------------
    # Fields to decrypt
    # -------------------------
    FIELDS_TO_DECRYPT = [
        "status",
        "cancellation_reason",
        "suspension_reason",
        "billing_period",
        "currency",
    ]
    
    # -------------------------
    # Trial Constants
    # -------------------------
    DEFAULT_TRIAL_DAYS = 30
    
    
    
    @classmethod
    def _safe_decrypt(cls, value):
        """Safely decrypt a value, returning original if decryption fails."""
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        try:
            return decrypt_data(value)
        except Exception:
            return value

    @classmethod
    def _normalise_subscription_doc(cls, doc: dict) -> Optional[dict]:
        """Normalize and decrypt subscription document."""
        if not doc:
            return None
        
        if doc.get("_id"):
            doc["_id"] = str(doc["_id"])
        
        if doc.get("business_id"):
            doc["business_id"] = str(doc["business_id"])
        
        if doc.get("package_id"):
            doc["package_id"] = str(doc["package_id"])
        
        if doc.get("user_id"):
            doc["user_id"] = str(doc["user_id"])
        
        # Decrypt encrypted fields
        for field in cls.FIELDS_TO_DECRYPT:
            if field in doc:
                doc[field] = cls._safe_decrypt(doc[field])
        
        # Decrypt price_paid if present
        if doc.get("price_paid"):
            try:
                doc["price_paid"] = float(cls._safe_decrypt(doc["price_paid"]))
            except:
                doc["price_paid"] = 0.0
        
        # Remove hashed fields from response
        doc.pop("hashed_status", None)
        
        return doc
    
    @staticmethod
    def _compute_end_date(start: datetime, billing_period: str):
        bp = (billing_period or "").lower()

        if bp == "monthly":
            return start + timedelta(days=30)
        if bp == "quarterly":
            return start + timedelta(days=90)
        if bp == "yearly":
            return start + timedelta(days=365)
        if bp == "lifetime":
            return None

        return start + timedelta(days=30)

    # ---------------------------------------------------------
    # CREATE SUBSCRIPTION
    # ---------------------------------------------------------

    @staticmethod
    def create_subscription(
        business_id,
        user_id,
        user__id,
        package_id,
        payment_method=None,
        payment_reference=None,
        auto_renew=True,
        payment_done=False,
        processing_callback=False
    ):
        log_tag = f"[SubscriptionService][create_subscription][{business_id}]"

        try:
            pkg = Package.get_by_id(package_id)
            if not pkg:
                return False, None, "Package not found"

            if pkg.get("status") != "Active":
                return False, None, "Package is not active"

            # Ensure no active subscription exists
            existing = Subscription.get_current_access_by_business(business_id)
            if existing:
                return False, None, "Business already has active subscription"

            start = datetime.utcnow()

            billing_period = pkg.get("billing_period") or "monthly"
            trial_days = int(pkg.get("trial_days") or 0)

            trial_end = None
            if payment_done:
                status = Subscription.STATUS_ACTIVE
            elif trial_days > 0:
                trial_end = start + timedelta(days=trial_days)
                status = Subscription.STATUS_TRIAL
            else:
                status = Subscription.STATUS_ACTIVE

            end_date = SubscriptionService._compute_end_date(start, billing_period)

            next_payment_date = trial_end or end_date

            Subscription.mark_all_access_subscriptions_inactive(business_id)

            sub = Subscription(
                business_id=business_id,
                package_id=package_id,
                user_id=user_id,
                user__id=user__id,
                billing_period=billing_period,
                price_paid=pkg.get("price", 0),
                currency=pkg.get("currency", "USD"),
                start_date=start,
                end_date=end_date,
                trial_end_date=trial_end,
                status=status,
                auto_renew=auto_renew,
                payment_method=payment_method,
                payment_reference=payment_reference,
                last_payment_date=start if payment_reference else None,
                next_payment_date=next_payment_date,
                term_number=1,
            )

            sub_id = Subscription.insert_one(sub.to_dict())

            return True, sub_id, None

        except Exception as e:
            Log.error(f"{log_tag} error: {e}", exc_info=True)
            return False, None, str(e)

    # ---------------------------------------------------------
    # CANCEL
    # ---------------------------------------------------------

    @staticmethod
    def cancel_subscription(*, business_id: str, subscription_id: str, reason: str | None = None):
        log_tag = f"[subscription_service.py][cancel_subscription][{business_id}][{subscription_id}]"
        try:
            if not business_id or not subscription_id:
                return False, "Missing business_id or subscription_id"

            col = db.get_collection(Subscription.collection_name)

            biz_oid = ObjectId(str(business_id))
            sub_oid = ObjectId(str(subscription_id))

            now = datetime.utcnow()

            update_doc = {
                "status": encrypt_data(Subscription.STATUS_CANCELLED),
                "hashed_status": hash_data(Subscription.STATUS_CANCELLED),
                "cancelled_at": now,
                "updated_at": now,
            }
            if reason:
                update_doc["cancellation_reason"] = encrypt_data(reason)

            res = col.update_one(
                {"_id": sub_oid, "business_id": biz_oid},
                {"$set": update_doc},
            )

            if res.matched_count == 0:
                return False, "Subscription not found"

            if res.modified_count == 0:
                # already cancelled or same values
                return True, None

            Log.info(f"{log_tag} cancelled")
            return True, None

        except Exception as e:
            Log.error(f"{log_tag} error: {e}", exc_info=True)
            return False, str(e)

    # ---------------------------------------------------------
    # RENEW → CREATE NEW TERM
    # ---------------------------------------------------------

    @staticmethod
    def renew_subscription(
        business_id: str,
        user_id: str,
        user__id: str,
        payment_reference=None,
        payment_method=None,
    ):
        log_tag = f"[SubscriptionService][renew_subscription][{business_id}]"

        try:
            latest = Subscription.get_latest_by_business(business_id)
            if not latest:
                return False, "No subscription found"

            pkg = Package.get_by_id(latest["package_id"])
            if not pkg:
                return False, "Package not found"

            prev_id = latest["_id"]
            prev_term = int(latest.get("term_number") or 1)

            Subscription.mark_all_access_subscriptions_inactive(business_id)

            start = datetime.utcnow()
            billing_period = latest["billing_period"]

            end_date = SubscriptionService._compute_end_date(start, billing_period)

            sub = Subscription(
                business_id=business_id,
                package_id=latest["package_id"],
                user_id=user_id,
                user__id=user__id,
                billing_period=billing_period,
                price_paid=pkg.get("price", 0),
                currency=pkg.get("currency", "USD"),
                start_date=start,
                end_date=end_date,
                status=Subscription.STATUS_ACTIVE,
                auto_renew=True,
                payment_method=payment_method,
                payment_reference=payment_reference,
                last_payment_date=start,
                next_payment_date=end_date,
                previous_subscription_id=prev_id,
                term_number=prev_term + 1,
            )

            new_id = Subscription.insert_one(sub.to_dict())

            Log.info(f"{log_tag} renewed → new={new_id}")

            return True, None

        except Exception as e:
            Log.error(f"{log_tag} error: {e}", exc_info=True)
            return False, str(e)

    # ---------------------------------------------------------
    # APPLY FROM PAYMENT (upgrade / downgrade / renew)
    # ---------------------------------------------------------

    @staticmethod
    def apply_or_renew_from_payment(
        business_id,
        user_id,
        user__id,
        package_id,
        billing_period,
        payment_method=None,
        payment_reference=None,
        auto_renew=True,
    ):
        log_tag = "[SubscriptionService][apply_or_renew_from_payment]"

        new_pkg = Package.get_by_id(package_id)
        if not new_pkg:
            return False, None, "Package not found"

        active = Subscription.get_current_access_by_business(business_id)

        # ------------------------------------------------
        # No subscription → create
        # ------------------------------------------------
        if not active:
            return SubscriptionService.create_subscription(
                business_id,
                user_id,
                user__id,
                package_id,
                payment_method,
                payment_reference,
                auto_renew,
                payment_done=True,
            )

        active_pkg = Package.get_by_id(active["package_id"])

        # ------------------------------------------------
        # Same plan → renew
        # ------------------------------------------------
        if (
            str(active["package_id"]) == str(package_id)
            and active["billing_period"] == billing_period
        ):
            ok, err = SubscriptionService.renew_subscription(
                business_id,
                user_id,
                user__id,
                payment_reference,
                payment_method,
            )
            return ok, None, err

        # ------------------------------------------------
        # Downgrade → schedule
        # ------------------------------------------------
        if PlanChangeService.is_downgrade(active_pkg, new_pkg):

            start_date = active["end_date"]

            end_date = SubscriptionService._compute_end_date(
                start_date,
                billing_period,
            )

            sub = Subscription(
                business_id=business_id,
                package_id=package_id,
                user_id=user_id,
                user__id=user__id,
                billing_period=billing_period,
                price_paid=new_pkg.get("price", 0),
                currency=new_pkg.get("currency", "USD"),
                start_date=start_date,
                end_date=end_date,
                status=Subscription.STATUS_SCHEDULED,
                auto_renew=auto_renew,
                payment_method=payment_method,
                payment_reference=payment_reference,
                term_number=int(active.get("term_number") or 1) + 1,
                previous_subscription_id=active["_id"],
            )

            sid = Subscription.insert_one(sub.to_dict())
            return True, sid, None

        # ------------------------------------------------
        # Upgrade → immediate
        # ------------------------------------------------
        Subscription.mark_all_access_subscriptions_inactive(business_id)

        return SubscriptionService.create_subscription(
            business_id,
            user_id,
            user__id,
            package_id,
            payment_method,
            payment_reference,
            auto_renew,
            payment_done=True,
        )

    # ---------------------------------------------------------
    # CRON: ACTIVATE SCHEDULED
    # ---------------------------------------------------------

    @staticmethod
    def activate_due_scheduled_subscriptions():
        now = datetime.utcnow()

        col = db.get_collection(Subscription.collection_name)

        due = col.find({
            "hashed_status": hash_data(Subscription.STATUS_SCHEDULED),
            "start_date": {"$lte": now},
        })

        for sub in due:
            business_id = sub["business_id"]

            # expire old actives
            col.update_many(
                {
                    "business_id": business_id,
                    "hashed_status": {
                        "$in": [
                            hash_data(Subscription.STATUS_ACTIVE),
                            hash_data(Subscription.STATUS_TRIAL),
                        ]
                    },
                },
                {
                    "$set": {
                        "status": encrypt_data(Subscription.STATUS_EXPIRED),
                        "hashed_status": hash_data(Subscription.STATUS_EXPIRED),
                        "updated_at": now,
                    }
                },
            )

            # activate scheduled
            col.update_one(
                {"_id": sub["_id"]},
                {
                    "$set": {
                        "status": encrypt_data(Subscription.STATUS_ACTIVE),
                        "hashed_status": hash_data(Subscription.STATUS_ACTIVE),
                        "updated_at": now,
                    }
                },
            )

            Log.info(f"[SubscriptionService] Activated scheduled subscription {sub['_id']}")

            pkg = Package.get_by_id(str(sub["package_id"]))
            PlanChangeService.enforce_all_limits(str(business_id), pkg)


    @staticmethod
    def renew_subscription_by_id(
        *,
        business_id: str,
        user_id: str,
        user__id: str,
        old_subscription_id: str,
        payment_reference: str | None = None,
        payment_method: str | None = None,
        auto_renew: bool | None = None,
    ):
        log_tag = f"[SubscriptionService][renew_subscription_by_id][{business_id}][{old_subscription_id}]"

        try:
            old = Subscription.get_by_id(old_subscription_id, business_id)
            if not old:
                return False, None, "Subscription not found"

            # ✅ derive package & billing period from the old subscription
            package_id = old.get("package_id")
            billing_period = (old.get("billing_period") or "").lower().strip()

            if not package_id or not billing_period:
                return False, None, "Subscription is missing package/billing period"

            pkg = Package.get_by_id(package_id)
            if not pkg:
                return False, None, "Package not found"

            # Optional: block renew if package inactive
            if (pkg.get("status") or "") != "Active":
                return False, None, "This package is no longer available"

            now = datetime.utcnow()

            # ✅ decide start/end
            start_date = now
            if billing_period == "monthly":
                end_date = start_date + timedelta(days=30)
            elif billing_period == "quarterly":
                end_date = start_date + timedelta(days=90)
            elif billing_period == "yearly":
                end_date = start_date + timedelta(days=365)
            elif billing_period == "lifetime":
                end_date = None
            else:
                end_date = start_date + timedelta(days=30)

            # If auto_renew not provided, reuse old value
            if auto_renew is None:
                auto_renew = bool(old.get("auto_renew", True))
                
            #check if paymebt actually exists
            check_payment = Payment.get_by_reference(payment_reference)
            if not check_payment:
                Log.info(f"{log_tag} No payment with this reference was found.")
                return False, None, "No payment with this reference was found."
            
            # check if reference exists
            if payment_reference and Subscription.payment_reference_exists(payment_reference):
                Log.info(f"{log_tag} This payment reference has already been used.")
                return False, None, "This payment reference has already been used."

            # ✅ create NEW term (do not edit old)
            sub = Subscription(
                business_id=business_id,
                package_id=package_id,
                user_id=user_id,
                user__id=user__id,
                billing_period=billing_period,
                price_paid=pkg.get("price", 0),
                currency=pkg.get("currency", "USD"),
                start_date=start_date,
                end_date=end_date,
                status=Subscription.STATUS_ACTIVE,  # or Trial if you want trials again
                auto_renew=auto_renew,
                payment_method=payment_method,
                payment_reference=payment_reference,
                last_payment_date=now if payment_reference else None,
                next_payment_date=end_date,
            )

            new_id = sub.save(True)

            if not new_id:
                return False, None, "Failed to create renewed subscription"

            Log.info(f"{log_tag} renewed new_subscription_id={new_id}")
            return True, str(new_id), None

        except Exception as e:
            Log.error(f"{log_tag} error: {e}", exc_info=True)
            return False, None, str(e)












