# app/extensions/celery_tasks.py

from celery import Celery
from celery.schedules import crontab
from ..jobs.trial_expiration_job import process_expired_trials, send_trial_expiring_reminders

celery = Celery('tasks')

@celery.task
def process_expired_trials_task():
    return process_expired_trials()

@celery.task
def send_trial_reminders_task():
    return send_trial_expiring_reminders(days_before=3)

# Schedule
celery.conf.beat_schedule = {
    'expire-trials-hourly': {
        'task': 'app.celery_tasks.process_expired_trials_task',
        'schedule': crontab(minute=0),  # Every hour
    },
    'trial-reminders-daily': {
        'task': 'app.celery_tasks.send_trial_reminders_task',
        'schedule': crontab(hour=9, minute=0),  # Daily at 9 AM
    },
}