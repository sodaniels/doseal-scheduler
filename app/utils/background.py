# app/background.py
from concurrent.futures import ThreadPoolExecutor
from flask import current_app
from app.utils.logger import Log
import os
import traceback

_EXECUTOR = ThreadPoolExecutor(max_workers=int(os.getenv("BG_MAX_WORKERS", "4")))

def run_bg(fn, *args, **kwargs):
    """Run a callable in a background thread with Flask app context."""
    app = current_app._get_current_object()

    def _wrapped():
        with app.app_context():
            try:
                fn(*args, **kwargs)
            except Exception as e:
                Log.info(f"[background] error: {e}\n{traceback.format_exc()}")

    _EXECUTOR.submit(_wrapped)
