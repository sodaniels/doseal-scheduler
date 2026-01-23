import logging
import logging.handlers
import os
from datetime import datetime

class DynamicDailyFileHandler(logging.handlers.WatchedFileHandler):
    """
    A file handler that automatically creates new log files when the day changes.
    """
    def __init__(self, base_log_dir, encoding='utf-8'):
        self.base_log_dir = base_log_dir
        self.current_date = None
        self.current_stream = None
        # Initialize with today's log file
        initial_filename = self._get_current_log_path()
        super().__init__(initial_filename, encoding=encoding)
    
    def _get_current_log_path(self):
        """Generate the current log file path based on today's date."""
        now = datetime.now()
        year = now.strftime("%Y")
        month = now.strftime("%m")
        day = now.strftime("%Y-%m-%d")
        
        logs_folder = os.path.join(self.base_log_dir, year, month)
        os.makedirs(logs_folder, exist_ok=True)
        
        return os.path.join(logs_folder, f"log-{day}.log")
    
    def emit(self, record):
        """
        Emit a record, checking if we need to roll over to a new day's log file.
        """
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            
            # Check if the date has changed
            if self.current_date != today:
                # Close current file if it exists
                if self.stream and not self.stream.closed:
                    self.stream.close()
                
                # Update to new log file
                self.current_date = today
                new_log_path = self._get_current_log_path()
                self.baseFilename = new_log_path
                
                # Reopen the stream with the new file
                self.stream = self._open()
            
            # Call parent emit method
            super().emit(record)
            
        except Exception:
            self.handleError(record)

def get_base_log_dir():
    """Get the base log directory from environment or default."""
    base_log_dir = os.environ.get("APP_LOG_DIR")
    if base_log_dir is None:
        base_log_dir = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '../../storage/logs')
        )
    return base_log_dir

# Initialize logger
BASE_LOG_DIR = get_base_log_dir()

Log = logging.getLogger("MyLogger")
Log.setLevel(logging.DEBUG)

if not Log.handlers:
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)

    # Dynamic daily file handler
    file_handler = DynamicDailyFileHandler(BASE_LOG_DIR, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    Log.addHandler(console_handler)
    Log.addHandler(file_handler)

Log.debug("Logger initialized with dynamic daily file handler.")

__all__ = ["Log"]