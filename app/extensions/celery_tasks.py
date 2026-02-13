# app/extensions/celery_tasks.py

from celery import Celery
from celery.schedules import crontab

from ..services.social.appctx import run_in_app_context
from app.jobs.trial_expiration_job import (
    process_expired_trials,
    send_trial_expiring_reminders,
)

celery = Celery("tasks")


@celery.task(name="process_expired_trials_task")
def process_expired_trials_task():
    return run_in_app_context(process_expired_trials)


@celery.task(name="send_trial_reminders_task")
def send_trial_reminders_task():
    return run_in_app_context(send_trial_expiring_reminders, days_before=3)