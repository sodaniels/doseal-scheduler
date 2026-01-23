from crontab import CronTab

# Set the cron job parameters
cron = CronTab(user=True)

script_path = '/var/www/html/unity-sandbox.instntmny.com/app/scripts/daily_log_runner.sh'
job_command = f'{script_path}'

# Check for duplicates
if not any(job_command in job.command for job in cron):
    job = cron.new(command=job_command, comment='Daily log ping at 12 AM UK time')
    job.setall('@daily')
    cron.write()
    print("✅ Cron job added to run at 12:00 AM daily.")
else:
    print("⚠️ Cron job already exists.")
