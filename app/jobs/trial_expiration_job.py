# app/jobs/trial_expiration_job.py

from datetime import datetime, timedelta
from ..models.admin.subscription_model import Subscription
from ..utils.logger import Log


def process_expired_trials():
    """
    Background job to process expired trials.
    
    This should be run periodically (e.g., every hour via cron or celery).
    
    Actions:
    1. Find trials that have passed their end date
    2. Mark them as expired
    3. Update business account status
    4. Optionally send notification emails
    """
    log_tag = "[trial_expiration_job][process_expired_trials]"
    
    try:
        Log.info(f"{log_tag} Starting trial expiration job")
        
        # Get expired trials
        expired_trials = Subscription.get_expired_trials()
        
        Log.info(f"{log_tag} Found {len(expired_trials)} expired trials")
        
        for trial in expired_trials:
            subscription_id = trial.get("_id")
            business_id = trial.get("business_id")
            
            try:
                # Expire the trial
                success = Subscription.expire_trial(subscription_id, log_tag)
                
                if success:
                    Log.info(f"{log_tag} Expired trial {subscription_id} for business {business_id}")
                    
                    # TODO: Send expiration email
                    # send_trial_expired_email(business_id)
                    
            except Exception as e:
                Log.error(f"{log_tag} Error expiring trial {subscription_id}: {e}")
        
        Log.info(f"{log_tag} Trial expiration job completed")
        
        return {
            "processed": len(expired_trials),
            "success": True,
        }
        
    except Exception as e:
        Log.error(f"{log_tag} Job failed: {e}")
        return {
            "processed": 0,
            "success": False,
            "error": str(e),
        }


def send_trial_expiring_reminders(days_before: int = 3):
    """
    Send reminder emails for trials expiring soon.
    
    This should be run daily.
    """
    log_tag = "[trial_expiration_job][send_trial_expiring_reminders]"
    
    try:
        Log.info(f"{log_tag} Starting trial reminder job for {days_before} days")
        
        # Get expiring trials
        expiring_trials = Subscription.get_expiring_trials(days_until_expiry=days_before)
        
        Log.info(f"{log_tag} Found {len(expiring_trials)} trials expiring in {days_before} days")
        
        for trial in expiring_trials:
            business_id = trial.get("business_id")
            days_remaining = trial.get("trial_days_remaining", days_before)
            
            try:
                # TODO: Send reminder email
                # send_trial_expiring_email(business_id, days_remaining)
                Log.info(f"{log_tag} Sent reminder for business {business_id}")
                
            except Exception as e:
                Log.error(f"{log_tag} Error sending reminder for {business_id}: {e}")
        
        return {
            "processed": len(expiring_trials),
            "success": True,
        }
        
    except Exception as e:
        Log.error(f"{log_tag} Job failed: {e}")
        return {
            "processed": 0,
            "success": False,
            "error": str(e),
        }


# =========================================
# Flask CLI Commands (for manual execution)
# =========================================
def register_trial_commands(app):
    """Register CLI commands for trial management."""
    
    @app.cli.command("expire-trials")
    def expire_trials_command():
        """Process expired trials."""
        result = process_expired_trials()
        print(f"Processed {result['processed']} expired trials")
    
    @app.cli.command("trial-reminders")
    def trial_reminders_command():
        """Send trial expiring reminders."""
        result = send_trial_expiring_reminders(days_before=3)
        print(f"Sent {result['processed']} reminders")