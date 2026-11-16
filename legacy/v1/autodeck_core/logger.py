import logging
import json
import sys
from typing import Optional

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_obj)

def setup_logger(name: str, level: int = logging.INFO, log_callback: Optional[callable] = None) -> logging.Logger:
    """
    Sets up a logger with JSON formatting on stdout.
    Optionally accepts a callback to stream logs to a UI.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid adding duplicate handlers
    if not logger.handlers:
        # Console Handler (JSON)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(JSONFormatter())
        logger.addHandler(console_handler)
    
    # UI Callback Handler (if provided)
    if log_callback:
        class CallbackHandler(logging.Handler):
            def emit(self, record):
                # Format message
                msg = f"[{record.levelname}] {record.getMessage()}"
                try:
                    log_callback(msg)
                except Exception:
                    # Avoid crashing if callback fails (e.g. UI element gone)
                    pass
        
        # Remove existing CallbackHandlers to ensure we use the latest callback
        # (Crucial for Streamlit where callbacks might close over stale UI elements)
        logger.handlers = [h for h in logger.handlers if not isinstance(h, CallbackHandler)]
        
        cb_handler = CallbackHandler()
        cb_handler.setFormatter(logging.Formatter('%(message)s')) 
        logger.addHandler(cb_handler)

    return logger
