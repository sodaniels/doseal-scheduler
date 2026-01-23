#!/usr/bin/env python3

import sys
import os
from datetime import datetime

# Add app root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(project_root)

try:
    from utils.logger import Log  # Update if your logger is in a different module
except ImportError:
    print("[ERROR] Could not import logger.")
    sys.exit(1)

# Log a heartbeat line
Log.info("✅ Daily logger check at %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
