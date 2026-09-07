"""
TRACES Automation — Logging Configuration

Creates dated rotating log files and a console handler.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from config import LOGS_DIR


def setup_logger(name: str = "traces_automation") -> logging.Logger:
    """Configure and return the application logger.

    Creates:
        - A dated log file in LOGS_DIR  (DEBUG level)
        - A console stream handler       (INFO  level)
    """
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # ── File Handler ──
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = LOGS_DIR / f"traces_automation_{today}.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_fmt)

    # ── Console Handler ──
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    console_handler.setFormatter(console_fmt)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# Module-level convenience instance
logger = setup_logger()
