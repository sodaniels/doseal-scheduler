
import ast
import json

from decimal import Decimal, InvalidOperation
from flask import current_app, g, jsonify

from ...models.subscriber_model import Subscriber
from ...models.people_model import Agent
from ...models.admin.super_superadmin_model import Admin
from ...models.business_model import Business
from ...models.admin.subscription_model import Subscription
from ...models.base_model import BaseModel

from ..logger import Log # import logging
from ...constants.service_code import (
    ADMIN_PRE_PROCESS_VALIDATION_CHECKS,
    SYSTEM_USERS
)
from ..json_response import prepared_response

from ...services.wallet_service import (
    place_hold,
    capture_hold,
    release_hold,
    refund_capture,
    get_agent_account
)
from ..agent_balance_keys import (
    keys_for_funding, 
    keys_for_hold, 
    keys_for_capture, 
    keys_for_release, 
    keys_for_refund
)
from ...utils.crypt import decrypt_data


class PreProcessCheck(BaseModel):
    
    def __init__(self, business_id, account_type, admin_id):
        self.admin_id = admin_id
        self.business_id = business_id
        self.account_type = account_type
        
    ##############ACCOUNT PRE TRANSACTION CHECKS##################
    def initial_processs_checks(self):
        """
        Performs comprehensive pre-transaction validation checks before
        allowing any financial or privileged operation.

        This method ensures that:
        1. The business exists
        2. The acting admin exists (if required)
        3. Business onboarding requirements are complete
        4. The business has an ACTIVE paid subscription
            OR a valid (non-expired) trial

        ❌ Transactions are blocked if:
        - The business does not exist
        - Required onboarding steps are incomplete
        - No subscription exists
        - Trial exists but has expired
        - Subscription is inactive / cancelled / expired

        Returns:
            None
                → When ALL checks pass (caller may proceed)

            prepared_response(...)
                → When validation fails (caller must RETURN this response)

        Usage:
            validator = TransactionValidator(...)
            error = validator.initial_processs_checks()
            if error:
                return error
        """

        log_tag = "[pre_process_checks.py][initial_processs_checks]"

        # =========================================================
        # 1. VERIFY BUSINESS EXISTS
        # =========================================================
        try:
            Log.info(f"{log_tag} Verifying business exists")

            business = Business.get_business_by_id(
                business_id=self.business_id
            )

            if not business:
                Log.info(f"{log_tag} Business not found | id={self.business_id}")
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    f"Business with ID {self.business_id} does not exist",
                )

        except Exception as e:
            Log.error(f"{log_tag} Business lookup failed: {e}", exc_info=True)
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to verify business",
            )

        # =========================================================
        # 2. VERIFY ADMIN EXISTS (NON-OWNER ROLES)
        # =========================================================
        if self.account_type not in (
            SYSTEM_USERS["SUPER_ADMIN"],
            SYSTEM_USERS["SYSTEM_OWNER"],
            SYSTEM_USERS["BUSINESS_OWNER"],
        ):
            try:
                Log.info(f"{log_tag} Verifying admin exists")

                admin = Admin.get_by_id(
                    admin_id=self.admin_id,
                    business_id=self.business_id,
                    is_logging_in=True,
                )

                if not admin:
                    Log.info(f"{log_tag} Admin not found | id={self.admin_id}")
                    return prepared_response(
                        False,
                        "NOT_FOUND",
                        f"Admin with ID {self.admin_id} does not exist",
                    )

            except Exception as e:
                Log.error(f"{log_tag} Admin lookup failed: {e}", exc_info=True)
                return prepared_response(
                    False,
                    "INTERNAL_SERVER_ERROR",
                    "Failed to verify admin",
                )

        # =========================================================
        # 3. VERIFY BUSINESS ONBOARDING / ACCOUNT STATUS
        # =========================================================
        try:
            errors = []
            required_fields = []

            account_status = decrypt_data(business.get("account_status"))

            # Defensive parsing
            if isinstance(account_status, str):
                try:
                    account_status = json.loads(account_status)
                except Exception:
                    account_status = ast.literal_eval(account_status)

            if not account_status:
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    "Business onboarding is incomplete",
                )

            for check in ADMIN_PRE_PROCESS_VALIDATION_CHECKS:
                status_item = next(
                    (
                        value
                        for item in account_status
                        for key, value in item.items()
                        if key == check["key"]
                    ),
                    None,
                )

                if not status_item or not status_item.get("status"):
                    errors.append(check["message"])
                    required_fields.append(check["key"])

            if errors:
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    "Validation errors found. Please complete onboarding.",
                    errors,
                    required_fields,
                    self.admin_id,
                )

            Log.info(f"{log_tag} Business onboarding checks passed")

        except Exception as e:
            Log.error(f"{log_tag} Account status validation failed: {e}", exc_info=True)
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Failed to validate account status",
            )

        # =========================================================
        # 4. SUBSCRIPTION / TRIAL ENTITLEMENT CHECK
        # =========================================================
        try:
            Log.info(f"{log_tag} Checking subscription / trial entitlement")

            # 4.1 Check ACTIVE paid subscription
            active_subscription = Subscription.get_current_access_by_business(
                self.business_id
            )

            if active_subscription:
                Log.info(
                    f"{log_tag} Active subscription found | "
                    f"subscription_id={active_subscription.get('_id')}"
                )
                return None  # ✅ allow transaction

            # 4.2 No paid subscription → check trial
            trial_status = Subscription.get_trial_status(self.business_id)

            Log.info(f"{log_tag} Trial status: {trial_status}")

            # Valid trial
            if trial_status.get("is_on_trial") and not trial_status.get("trial_expired"):
                Log.info(
                    f"{log_tag} Valid trial | "
                    f"days_remaining={trial_status.get('trial_days_remaining')}"
                )
                return None  # ✅ allow transaction

            # Trial expired
            if trial_status.get("trial_expired"):
                Log.info(f"{log_tag} Trial expired — blocking transaction")
                return prepared_response(
                    False,
                    "PAYMENT_REQUIRED",
                    "Your free trial has expired. Please subscribe to continue.",
                    errors=["TRIAL_EXPIRED"],
                    required_fields=["subscription"],
                    user_id=self.admin_id,
                )

            # No subscription & no trial
            Log.info(f"{log_tag} No active subscription or trial")
            return prepared_response(
                False,
                "PAYMENT_REQUIRED",
                "No active subscription found. Please subscribe to continue.",
                errors=["NO_ACTIVE_SUBSCRIPTION"],
                required_fields=["subscription"],
                user_id=self.admin_id,
            )

        except Exception as e:
            Log.error(f"{log_tag} Subscription check failed: {e}", exc_info=True)
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Unable to verify subscription status",
            )







    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    















