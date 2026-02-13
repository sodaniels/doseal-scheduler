# app/jobs/trial_expiration_job.py

from datetime import datetime
from typing import Dict

from ..models.admin.subscription_model import Subscription
from ..utils.logger import Log
from ..services.email_service import (
    send_trial_expiring_email,
    send_trial_expired_email,
)


# =========================================================
# PROCESS EXPIRED TRIALS
# =========================================================

def process_expired_trials() -> Dict:
    """
    Background job to process expired trials.

    Recommended schedule:
    - Run hourly via cron or Celery beat

    Actions:
    1. Find trials that have passed their end date
    2. Mark them as expired (idempotent)
    3. Update business account status
    4. Send trial expired email (once)
    """
    log_tag = "[trial_expiration_job][process_expired_trials]"
    processed = 0
    errors = 0

    try:
        Log.info(f"{log_tag} Starting job")

        expired_trials = Subscription.get_expired_trials()
        Log.info(f"{log_tag} Found {len(expired_trials)} expired trials")

        for trial in expired_trials:
            subscription_id = trial.get("_id")
            business_id = trial.get("business_id")

            if not subscription_id or not business_id:
                Log.warning(f"{log_tag} Skipping invalid trial record: {trial}")
                continue

            try:
                expired = Subscription.expire_trial(subscription_id, log_tag)

                if not expired:
                    # Already expired or race condition
                    continue

                processed += 1
                Log.info(
                    f"{log_tag} Trial expired | subscription={subscription_id} | business={business_id}"
                )

                # 🔔 Notify business (best-effort)
                try:
                    send_trial_expired_email(business_id)
                except Exception as email_err:
                    Log.error(
                        f"{log_tag} Failed to send expired email "
                        f"business={business_id}: {email_err}"
                    )

            except Exception as trial_err:
                errors += 1
                Log.error(
                    f"{log_tag} Failed to expire trial "
                    f"subscription={subscription_id}: {trial_err}",
                    exc_info=True,
                )

        Log.info(
            f"{log_tag} Completed | processed={processed} | errors={errors}"
        )

        return {
            "success": True,
            "processed": processed,
            "errors": errors,
        }

    except Exception as e:
        Log.critical(f"{log_tag} Job failed catastrophically: {e}", exc_info=True)
        return {
            "success": False,
            "processed": processed,
            "errors": errors + 1,
            "error": str(e),
        }


# =========================================================
# SEND EXPIRING TRIAL REMINDERS
# =========================================================

def send_trial_expiring_reminders(days_before: int = 3) -> Dict:
    """
    Send reminder emails for trials expiring soon.

    Recommended schedule:
    - Run once daily

    Default:
    - 3 days before expiry
    """
    log_tag = "[trial_expiration_job][send_trial_expiring_reminders]"
    processed = 0
    errors = 0

    try:
        Log.info(f"{log_tag} Starting reminders for {days_before} days")

        expiring_trials = Subscription.get_expiring_trials(
            days_until_expiry=days_before
        )

        Log.info(
            f"{log_tag} Found {len(expiring_trials)} trials expiring in {days_before} days"
        )

        for trial in expiring_trials:
            business_id = trial.get("business_id")
            days_remaining = trial.get("trial_days_remaining")

            if not business_id:
                Log.warning(f"{log_tag} Skipping trial with no business_id")
                continue

            try:
                send_trial_expiring_email(
                    business_id=business_id,
                    days_remaining=days_remaining or days_before,
                )
                processed += 1
                Log.info(
                    f"{log_tag} Reminder sent | business={business_id} | days_remaining={days_remaining}"
                )

            except Exception as email_err:
                errors += 1
                Log.error(
                    f"{log_tag} Failed to send reminder "
                    f"business={business_id}: {email_err}",
                    exc_info=True,
                )

        Log.info(
            f"{log_tag} Completed | reminders_sent={processed} | errors={errors}"
        )

        return {
            "success": True,
            "processed": processed,
            "errors": errors,
        }

    except Exception as e:
        Log.critical(f"{log_tag} Job failed catastrophically: {e}", exc_info=True)
        return {
            "success": False,
            "processed": processed,
            "errors": errors + 1,
            "error": str(e),
        }


# =========================================================
# FLASK CLI COMMANDS
# =========================================================

def register_trial_commands(app):
    """
    Register Flask CLI commands for manual execution.
    """

    @app.cli.command("expire-trials")
    def expire_trials_command():
        """Expire all overdue trials."""
        result = process_expired_trials()
        print(
            f"[expire-trials] success={result['success']} "
            f"processed={result['processed']} errors={result['errors']}"
        )

    @app.cli.command("trial-reminders")
    def trial_reminders_command():
        """Send trial expiring reminders (3 days before expiry)."""
        result = send_trial_expiring_reminders(days_before=3)
        print(
            f"[trial-reminders] success={result['success']} "
            f"sent={result['processed']} errors={result['errors']}"
        )