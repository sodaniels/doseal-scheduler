# services/subscription_service.py

from datetime import datetime, timedelta
from bson import ObjectId
from ...models.admin.package_model import Package
from ...models.admin.subscription_model import Subscription
from ...utils.logger import Log
from ...utils.plan.plan_change import PlanChangeService
from ...extensions.db import db
from ...utils.crypt import hash_data, encrypt_data


class SubscriptionService:
    """
    Central subscription lifecycle service.

    Supports:
    - Create new subscription (free or paid)
    - Renew existing subscription if same package + same billing_period
    - Change plan (deactivate old, create new)
    - Validate billing_period matches Package.billing_period
    - Optional "enforce downgrade" hook after plan change
    """
    
    @staticmethod
    def create_subscription( business_id, user_id, user__id, package_id,  payment_method=None, 
                            payment_reference=None, auto_renew=True, processing_callback=True, 
                            payment_done=False, billing_period=None):
        """
        Create a new subscription for a business.
        
        Args:
            business_id: Business ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            package_id: Package ObjectId or string
            payment_method: Optional payment method
            payment_reference: Optional payment transaction reference
            
        Returns:
            Tuple (success: bool, subscription_id: str or None, error: str or None)
        """
        log_tag = f"[SubscriptionService][create_subscription][{business_id}][{package_id}]"
        
        try:
            # Get package details
            package = Package.get_by_id(package_id)
            
            if not package:
                Log.error(f"{log_tag} Package not found")
                return False, None, "Package not found"
            
            if package.get("status") != "Active":
                Log.error(f"{log_tag} Package is not active")
                return False, None, "Package is not available"
            
            # Check for existing active subscription
            existing_sub = Subscription.get_active_by_business(business_id)
            
            if existing_sub:
                Log.warning(f"{log_tag} Business already has active subscription")
                return False, None, "Business already has an active subscription"
            
            # Calculate dates
            start_date = datetime.utcnow()
            trial_days = package.get("trial_days", 0)
            trial_end_date = None
            
            # Trial end date
            if payment_done:
                status = Subscription.STATUS_ACTIVE
            else:
                if trial_days > 0:
                    trial_end_date = start_date + timedelta(days=trial_days)
                    status = Subscription.STATUS_TRIAL
                else:
                    status = Subscription.STATUS_ACTIVE
            
            Log.info(f"{log_tag} status: {status}")
            
            
            # Subscription end date based on billing period
            billing_period = package.get("billing_period")
            if billing_period == "monthly":
                end_date = start_date + timedelta(days=30)
            elif billing_period == "quarterly":
                end_date = start_date + timedelta(days=90)
            elif billing_period == "yearly":
                end_date = start_date + timedelta(days=365)
            elif billing_period == "lifetime":
                end_date = None  # No end date for lifetime
            else:
                end_date = start_date + timedelta(days=30)  # Default to monthly
            
            # Next payment date
            next_payment_date = trial_end_date if trial_end_date else end_date
            
            # Create subscription
            subscription = Subscription(
                business_id=business_id,
                package_id=package_id,
                user_id=user_id,
                user__id=user__id,
                billing_period=billing_period,
                price_paid=package.get("price", 0),
                currency=package.get("currency", "USD"),
                start_date=start_date,
                end_date=end_date,
                trial_end_date=trial_end_date,
                status=status,
                auto_renew=auto_renew,
                payment_method=payment_method,
                payment_reference=payment_reference,
                last_payment_date=datetime.utcnow() if payment_reference else None,
                next_payment_date=next_payment_date
            )
            
            subscription_id = subscription.save(processing_callback)
            
            if subscription_id:
                Log.info(f"{log_tag} Subscription created successfully: {subscription_id}")
                return True, str(subscription_id), None
            else:
                Log.error(f"{log_tag} Failed to save subscription")
                return False, None, "Failed to create subscription"
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False, None, str(e)
    
    @staticmethod
    def check_subscription_limits(business_id, limit_type):
        """
        Check if business has reached subscription limits.
        
        Args:
            business_id: Business ObjectId or string
            limit_type: Type of limit to check (users, outlets, products, etc.)
            
        Returns:
            Tuple (within_limits: bool, current_count: int, limit: int or None)
        """
        log_tag = f"[SubscriptionService][check_subscription_limits][{business_id}][{limit_type}]"
        
        try:
            # Get active subscription
            subscription = Subscription.get_active_by_business(business_id)
            
            if not subscription:
                Log.warning(f"{log_tag} No active subscription found")
                return False, 0, 0
            
            # Get package details
            package = Package.get_by_id(subscription["package_id"])
            
            if not package:
                Log.error(f"{log_tag} Package not found")
                return False, 0, 0
            
            # Get limit from package
            limit_field_map = {
                "users": "max_users",
                "outlets": "max_outlets",
                "products": "max_products",
                "transactions": "max_transactions_per_month",
                "storage": "storage_limit_gb"
            }
            
            limit_field = limit_field_map.get(limit_type)
            if not limit_field:
                Log.error(f"{log_tag} Invalid limit type: {limit_type}")
                return True, 0, None  # Allow if unknown limit type
            
            limit = package.get(limit_field)
            
            # If no limit set (None), allow unlimited
            if limit is None:
                return True, 0, None
            
            # Get current count (this would need to query respective collections)
            # For now, returning placeholder
            current_count = 0  # TODO: Implement actual counting
            
            within_limits = current_count < limit
            
            Log.info(f"{log_tag} Limit check: {current_count}/{limit} - Within limits: {within_limits}")
            return within_limits, current_count, limit
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return True, 0, None  # Allow on error (fail open)
    
    @staticmethod
    def check_feature_access(business_id, feature_name):
        """
        Check if business has access to a specific feature.
        
        Args:
            business_id: Business ObjectId or string
            feature_name: Feature to check (e.g., "api_access", "multi_outlet")
            
        Returns:
            Bool - True if feature is available
        """
        log_tag = f"[SubscriptionService][check_feature_access][{business_id}][{feature_name}]"
        
        try:
            # Get active subscription
            subscription = Subscription.get_active_by_business(business_id)
            
            if not subscription:
                Log.warning(f"{log_tag} No active subscription - denying feature access")
                return False
            
            # Get package details
            package = Package.get_by_id(subscription["package_id"])
            
            if not package:
                Log.error(f"{log_tag} Package not found")
                return False
            
            # Check feature flag
            features = package.get("features", {})
            has_access = features.get(feature_name, False)
            
            Log.info(f"{log_tag} Feature access: {has_access}")
            return has_access
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False  # Deny on error (fail closed)
    
    @staticmethod
    def renew_subscription(subscription_id, business_id, payment_reference=None):
        """
        Renew an existing subscription.
        
        Args:
            subscription_id: Subscription ObjectId or string
            business_id: Business ObjectId or string
            payment_reference: Optional payment transaction reference
            
        Returns:
            Tuple (success: bool, error: str or None)
        """
        log_tag = f"[SubscriptionService][renew_subscription][{subscription_id}]"
        
        try:
            subscription_id = ObjectId(subscription_id) if not isinstance(subscription_id, ObjectId) else subscription_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            # Get subscription
            subscription = Subscription.get_by_id(subscription_id, business_id)
            
            if not subscription:
                return False, "Subscription not found"
            
            # Get package for billing period
            package = Package.get_by_id(subscription["package_id"])
            
            if not package:
                return False, "Package not found"
            
            # Calculate new end date
            current_end = subscription.get("end_date") or datetime.utcnow()
            billing_period = subscription.get("billing_period")
            
            if billing_period == "monthly":
                new_end_date = current_end + timedelta(days=30)
            elif billing_period == "quarterly":
                new_end_date = current_end + timedelta(days=90)
            elif billing_period == "yearly":
                new_end_date = current_end + timedelta(days=365)
            else:
                new_end_date = current_end + timedelta(days=30)
            
            # Update subscription
            collection = db.get_collection(Subscription.collection_name)
            
            update_doc = {
                "end_date": new_end_date,
                "next_payment_date": new_end_date,
                "last_payment_date": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
            if payment_reference:
                update_doc["payment_reference"] = payment_reference
                update_doc["hashed_status"] = hash_data(Subscription.STATUS_ACTIVE)
                update_doc["status"] = encrypt_data(Subscription.STATUS_ACTIVE)
            
            result = collection.update_one(
                {"_id": subscription_id, "business_id": business_id},
                {"$set": update_doc}
            )
            
            if result.modified_count > 0:
                Log.info(f"{log_tag} Subscription renewed until {new_end_date}")
                return True, None
            else:
                Log.error(f"{log_tag} Failed to renew subscription")
                return False, "Failed to update subscription"
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, str(e)

    
    # -------------------------
    # PUBLIC: apply or renew (used by payment callback)
    # -------------------------
    # @staticmethod
    # def apply_or_renew_from_payment(
    #     business_id: str,
    #     user_id: str,
    #     user__id: str,
    #     package_id: str,
    #     billing_period: str,
    #     payment_method: str | None = None,
    #     payment_reference: str | None = None,
    #     payment_id: str | None = None,
    #     processing_callback=True,
    #     auto_renew=True,
    #     source: str = "payment_callback",
    # ):
    #     """
    #     Called after payment success (callback) OR for free plan activation.

    #     Rules:
    #     - Validate billing_period matches the Package.billing_period (since you store it in package doc)
    #     - If active subscription exists:
    #         * same package + same billing_period => renew existing subscription
    #         * else => deactivate old and create new subscription
    #     - If no active subscription => create new subscription

    #     Returns: (success: bool, subscription_id: str|None, error: str|None)
    #     """
    #     log_tag = "[SubscriptionService][apply_or_renew_from_payment]"

    #     # -------------------------
    #     # Validate IDs & package
    #     # -------------------------
    #     try:
    #         business_oid = ObjectId(str(business_id))
    #         package_oid = ObjectId(str(package_id))
    #     except Exception as e:
    #         return False, None, f"Invalid business_id/package_id: {e}"

    #     pkg = Package.get_by_id(str(package_oid))
    #     if not pkg:
    #         return False, None, "Package not found"

    #     # ✅ Validate billing_period matches Package.billing_period (your requirement)
    #     pkg_period = (pkg.get("billing_period") or "").strip().lower()
    #     req_period = (billing_period or "").strip().lower()

    #     if not pkg_period:
    #         return False, None, "Package billing_period missing"

    #     if req_period != pkg_period:
    #         return False, None, f"billing_period mismatch: requested={req_period}, package={pkg_period}"

    #     # -------------------------
    #     # Get active subscription
    #     # -------------------------
    #     try:
    #         active_sub = Subscription.get_active_by_business(str(business_oid))
    #     except Exception as e:
    #         Log.error(f"{log_tag} failed to load active subscription: {e}")
    #         active_sub = None

    #     if active_sub:
    #         active_sub_id = str(active_sub.get("_id"))
    #         active_package_id = str(active_sub.get("package_id"))
    #         active_period = (active_sub.get("billing_period") or "").strip().lower()

    #         # ✅ SAME package + SAME billing_period => renew
    #         if active_package_id == str(package_oid) and active_period == req_period:
    #             Log.info(f"{log_tag} Renewing existing subscription {active_sub_id}")

    #             ok, err = SubscriptionService.renew_subscription(
    #                 subscription_id=active_sub_id,
    #                 business_id=str(business_oid),
    #                 payment_reference=payment_reference,
    #             )
    #             if not ok:
    #                 Log.error(f"{log_tag} renew failed: {err}")
    #                 return False, None, err or "Failed to renew subscription"

    #             return True, active_sub_id, None

    #         # ✅ Different package or period => change plan (deactivate old, create new)
    #         Log.info(
    #             f"{log_tag} Changing plan from sub={active_sub_id} "
    #             f"(pkg={active_package_id}, period={active_period}) "
    #             f"to pkg={package_id}, period={req_period}"
    #         )

    #         new_sub_id = SubscriptionService._apply_new_subscription(
    #             business_id=str(business_oid),
    #             user_id=user_id,
    #             user__id=user__id,
    #             package_id=str(package_oid),
    #             billing_period=req_period,
    #             payment_method=payment_method,
    #             payment_reference=payment_reference,
    #             payment_id=payment_id,
    #             processing_callback=processing_callback,
    #             auto_renew=auto_renew,
    #             source=source,
    #         )

    #         if not new_sub_id:
    #             Log.error(f"{log_tag} Failed to apply new subscription")
    #             return False, None, "Failed to apply new subscription"

    #         return True, new_sub_id, None

    #     # ✅ No active subscription => create new
    #     Log.info(f"{log_tag} No active subscription - creating new one")

    #     new_sub_id = SubscriptionService._apply_new_subscription(
    #         business_id=str(business_oid),
    #         user_id=user_id,
    #         user__id=user__id,
    #         package_id=str(package_oid),
    #         billing_period=req_period,
    #         payment_method=payment_method,
    #         payment_reference=payment_reference,
    #         payment_id=payment_id,
    #         processing_callback=processing_callback,
    #         auto_renew=auto_renew,
    #         source=source,
    #     )

    #     if not new_sub_id:
    #         Log.error(f"{log_tag} Failed to create subscription")
    #         return False, None, "Failed to create subscription"

    #     return True, new_sub_id, None

    @staticmethod
    def apply_or_renew_from_payment(
        business_id: str,
        user_id: str,
        user__id: str,
        package_id: str,
        billing_period: str,
        payment_method: str | None = None,
        payment_reference: str | None = None,
        payment_id: str | None = None,
        processing_callback=True,
        auto_renew=True,
        source: str = "payment_callback",
    ):
        """
        Entry point after payment success.
        Handles:
        - renewal
        - upgrade (immediate)
        - downgrade (scheduled)
        """

        log_tag = "[SubscriptionService][apply_or_renew_from_payment]"

        business_oid = ObjectId(str(business_id))
        package_oid = ObjectId(str(package_id))

        new_pkg = Package.get_by_id(str(package_oid))
        if not new_pkg:
            return False, None, "Package not found"

        # Validate billing period
        if billing_period != new_pkg.get("billing_period"):
            return False, None, "Billing period mismatch"

        active_sub = Subscription.get_active_by_business(str(business_oid))

        # ─────────────────────────────────────────────
        # 1) No active subscription → create immediately
        # ─────────────────────────────────────────────
        if not active_sub:
            sub_id = SubscriptionService._create_subscription(
                business_id,
                user_id,
                user__id,
                new_pkg,
                billing_period,
                start_date=datetime.utcnow(),
                payment_method=payment_method,
                payment_reference=payment_reference,
                auto_renew=auto_renew,
                processing_callback=processing_callback,
            )
            return True, sub_id, None

        active_pkg = Package.get_by_id(str(active_sub["package_id"]))

        # ─────────────────────────────────────────────
        # 2) Same plan + same period → renew
        # ─────────────────────────────────────────────
        if (
            str(active_sub["package_id"]) == str(package_oid)
            and active_sub["billing_period"] == billing_period
        ):
            ok, err = SubscriptionService.renew_subscription(
                active_sub["_id"], business_id, payment_reference
            )
            return ok, str(active_sub["_id"]), err

        # ─────────────────────────────────────────────
        # 3) Downgrade → schedule
        # ─────────────────────────────────────────────
        if PlanComparator.is_downgrade(active_pkg, new_pkg):
            Log.info(f"{log_tag} Downgrade detected → scheduling")

            sub_id = SubscriptionService._schedule_subscription(
                business_id,
                user_id,
                user__id,
                new_pkg,
                billing_period,
                start_date=active_sub["end_date"],
                payment_method=payment_method,
                payment_reference=payment_reference,
                auto_renew=auto_renew,
                processing_callback=processing_callback,
            )

            return True, sub_id, None

        # ─────────────────────────────────────────────
        # 4) Upgrade → apply immediately
        # ─────────────────────────────────────────────
        Log.info(f"{log_tag} Upgrade detected → applying immediately")

        Subscription.deactivate_all(business_id)

        sub_id = SubscriptionService._create_subscription(
            business_id,
            user_id,
            user__id,
            new_pkg,
            billing_period,
            start_date=datetime.utcnow(),
            payment_method=payment_method,
            payment_reference=payment_reference,
            auto_renew=auto_renew,
            processing_callback=processing_callback,
        )

        return True, sub_id, None

    @staticmethod
    def _schedule_subscription(
        business_id,
        user_id,
        user__id,
        pkg,
        billing_period,
        start_date,
        payment_method=None,
        payment_reference=None,
        auto_renew=True,
        processing_callback=True,
    ):
        now = datetime.utcnow()

        if billing_period == "monthly":
            end_date = start_date + timedelta(days=30)
        elif billing_period == "quarterly":
            end_date = start_date + timedelta(days=90)
        elif billing_period == "yearly":
            end_date = start_date + timedelta(days=365)
        else:
            end_date = start_date + timedelta(days=30)

        sub = Subscription(
            business_id=business_id,
            user_id=user_id,
            user__id=user__id,
            package_id=str(pkg["_id"]),
            billing_period=billing_period,
            price_paid=pkg.get("price", 0),
            currency=pkg.get("currency", "USD"),
            start_date=start_date,
            end_date=end_date,
            next_payment_date=end_date,
            status=Subscription.STATUS_SCHEDULED,  # 👈 KEY
            auto_renew=auto_renew,
            payment_method=payment_method,
            payment_reference=payment_reference,
            created_at=now,
            updated_at=now,
        )

        return str(sub.save(processing_callback))

    @staticmethod
    def _create_subscription(
        business_id,
        user_id,
        user__id,
        pkg,
        billing_period,
        start_date,
        payment_method=None,
        payment_reference=None,
        auto_renew=True,
        processing_callback=True,
    ):
        now = datetime.utcnow()

        if billing_period == "monthly":
            end_date = start_date + timedelta(days=30)
        elif billing_period == "quarterly":
            end_date = start_date + timedelta(days=90)
        elif billing_period == "yearly":
            end_date = start_date + timedelta(days=365)
        else:
            end_date = start_date + timedelta(days=30)

        sub = Subscription(
            business_id=business_id,
            user_id=user_id,
            user__id=user__id,
            package_id=str(pkg["_id"]),
            billing_period=billing_period,
            price_paid=pkg.get("price", 0),
            currency=pkg.get("currency", "USD"),
            start_date=start_date,
            end_date=end_date,
            next_payment_date=end_date,
            status=Subscription.STATUS_ACTIVE,
            auto_renew=auto_renew,
            payment_method=payment_method,
            payment_reference=payment_reference,
            created_at=now,
            updated_at=now,
        )

        return str(sub.save(processing_callback))

    # -------------------------
    # PRIVATE: apply new subscription (deactivate old + create new)
    # -------------------------
    @staticmethod
    def _apply_new_subscription(
        business_id: str,
        user_id: str,
        user__id: str,
        package_id: str,
        billing_period: str,
        payment_method: str | None = None,
        payment_reference: str | None = None,
        payment_id: str | None = None,
        processing_callback=True,
        auto_renew=True,
        source: str = "payment_callback",
    ) -> str | None:
        """
        Deactivate any current active subscription and create a new one.
        Returns: subscription_id (str) or None
        """
        log_tag = "[SubscriptionService][_apply_new_subscription]"

        try:
            business_oid = ObjectId(str(business_id))
            package_oid = ObjectId(str(package_id))
        except Exception as e:
            Log.error(f"{log_tag} invalid ids: {e}")
            return None

        pkg = Package.get_by_id(str(package_oid))
        if not pkg:
            Log.error(f"{log_tag} package not found: {package_id}")
            return None

        now = datetime.utcnow()
        sub_col = db.get_collection(Subscription.collection_name)

        # 1) Deactivate old active subs
        try:
            sub_col.update_many(
                {"business_id": business_oid, "status": Subscription.STATUS_ACTIVE},
                {"$set": {"status": Subscription.STATUS_INACTIVE, "ended_at": now, "updated_at": now}},
            )
        except Exception as e:
            Log.error(f"{log_tag} failed to deactivate old subs: {e}")

        # 2) Compute end date from billing period (monthly/quarterly/yearly)
        start_date = now
        bp = (billing_period or "").strip().lower()

        if bp == "monthly":
            end_date = now + timedelta(days=30)
        elif bp == "quarterly":
            end_date = now + timedelta(days=90)
        elif bp == "yearly":
            end_date = now + timedelta(days=365)
        else:
            # fallback
            end_date = now + timedelta(days=30)

        next_payment_date = end_date

        # 3) Create subscription
        try:
            sub = Subscription(
                business_id=str(business_oid),
                package_id=str(package_oid),
                user_id=user_id,
                user__id=user__id,
                billing_period=bp,
                price_paid=pkg.get("price", 0),
                currency=pkg.get("currency", "USD"),
                start_date=start_date,
                end_date=end_date,
                status=Subscription.STATUS_ACTIVE,
                auto_renew=auto_renew,
                payment_method=payment_method,
                payment_reference=payment_reference,
                last_payment_date=now if payment_reference else None,
                next_payment_date=next_payment_date,
                source=source,
            )

            # IMPORTANT: your model uses save(processing_callback)
            sub_id = sub.save(processing_callback)

            if not sub_id:
                Log.error(f"{log_tag} failed to save subscription")
                return None

            sub_id = str(sub_id)
            Log.info(f"{log_tag} Subscription created successfully: {sub_id}")

        except Exception as e:
            Log.error(f"{log_tag} error saving subscription: {e}", exc_info=True)
            return None

        # 4) OPTIONAL: enforce downgrade limits now (outlets first, then others)
        # If you have PlanChangeService, enable this:
        # try:
        #     from ...utils.plan.plan_change import PlanChangeService
        #     PlanChangeService.enforce_all(business_id=str(business_oid), package_doc=pkg)
        # except Exception as e:
        #     Log.error(f"{log_tag} enforce limits failed: {e}")

        return sub_id

    # -------------------------
    # PUBLIC: renew subscription (extend end_date)
    # -------------------------
    @staticmethod
    def renew_subscription(subscription_id, business_id, payment_reference=None):
        """
        Renew an existing subscription.

        Returns: (success: bool, error: str|None)
        """
        log_tag = f"[SubscriptionService][renew_subscription][{subscription_id}]"

        try:
            subscription_id = ObjectId(subscription_id) if not isinstance(subscription_id, ObjectId) else subscription_id
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id

            # Get subscription
            subscription = Subscription.get_by_id(subscription_id, business_id)
            if not subscription:
                return False, "Subscription not found"

            # Get package for billing period validation or reference
            package = Package.get_by_id(subscription["package_id"])
            if not package:
                return False, "Package not found"

            # Use subscription billing_period
            billing_period = (subscription.get("billing_period") or "").strip().lower()
            current_end = subscription.get("end_date") or datetime.utcnow()

            if billing_period == "monthly":
                new_end_date = current_end + timedelta(days=30)
            elif billing_period == "quarterly":
                new_end_date = current_end + timedelta(days=90)
            elif billing_period == "yearly":
                new_end_date = current_end + timedelta(days=365)
            else:
                new_end_date = current_end + timedelta(days=30)

            update_doc = {
                "end_date": new_end_date,
                "next_payment_date": new_end_date,
                "last_payment_date": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }

            if payment_reference:
                update_doc["payment_reference"] = payment_reference
                # ensure status active
                update_doc["status"] = Subscription.STATUS_ACTIVE

            collection = db.get_collection(Subscription.collection_name)
            result = collection.update_one(
                {"_id": subscription_id, "business_id": business_id},
                {"$set": update_doc},
            )

            if result.modified_count > 0:
                Log.info(f"{log_tag} Subscription renewed until {new_end_date}")
                return True, None

            Log.error(f"{log_tag} Failed to renew subscription (no modification)")
            return False, "Failed to update subscription"

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return False, str(e)

    @staticmethod
    def activate_due_scheduled_subscriptions():
        now = datetime.utcnow()
        col = db.get_collection(Subscription.collection_name)

        due = col.find({
            "status": Subscription.STATUS_SCHEDULED,
            "start_date": {"$lte": now},
        })

        for sub in due:
            business_id = sub["business_id"]

            # expire old active
            col.update_many(
                {"business_id": business_id, "status": Subscription.STATUS_ACTIVE},
                {"$set": {"status": Subscription.STATUS_EXPIRED}},
            )

            # activate scheduled
            col.update_one(
                {"_id": sub["_id"]},
                {"$set": {"status": Subscription.STATUS_ACTIVE}},
            )

            Log.info(f"[SubscriptionService] Activated scheduled subscription {sub['_id']}")

            # 🔒 enforce limits NOW
            pkg = Package.get_by_id(str(sub["package_id"]))
            PlanChangeService.enforce_all_limits(str(business_id), pkg)












