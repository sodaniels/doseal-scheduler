#!/bin/bash

# Get date components
YEAR=$(date +%Y)
MONTH=$(date +%m)
DAY=$(date +%F)

# Define log directory and file
LOG_DIR="/var/www/html/unity-sandbox.instntmny.com/app/storage/logs/$YEAR/$MONTH"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/log-$DAY.log"

# Run Python logger and write output
/var/www/html/unity-sandbox.instntmny.com/venv/bin/python /var/www/html/unity-sandbox.instntmny.com/app/scripts/daily_log_ping.py >> "$LOG_FILE" 2>&1
