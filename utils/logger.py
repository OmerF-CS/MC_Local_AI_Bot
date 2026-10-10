import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional

from utils.run_context import get_current_run_id, set_current_run_id, get_run_directory


class RunIdFilter(logging.Filter):
    """Injects current run_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id") or not record.run_id:
            record.run_id = get_current_run_id()
        return True


def setup_logging(config=None, run_id: Optional[str] = None):
    """Central logging configuration with run-isolated logging support."""
    # Fix stdout encoding on Windows
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except AttributeError:
            pass

    if run_id:
        set_current_run_id(run_id)

    active_run_id = get_current_run_id()

    log_level_str = getattr(config, "LOG_LEVEL", "INFO") if config else os.getenv("LOG_LEVEL", "INFO")
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)

    # Clean root logger to avoid duplicate log handlers
    root = logging.getLogger()
    if root.handlers:
        for handler in list(root.handlers):
            root.removeHandler(handler)

    root.setLevel(log_level)

    log_format = "%(asctime)s [%(levelname)s] [%(run_id)s] [%(name)s]: %(message)s"
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")
    run_filter = RunIdFilter()

    # 1. Console output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(run_filter)
    root.addHandler(console_handler)

    # 2. Shared File output (Rotating File: logs/minecraft_bot.log)
    try:
        if not os.path.exists("logs"):
            os.makedirs("logs", exist_ok=True)

        shared_handler = RotatingFileHandler(
            "logs/minecraft_bot.log",
            maxBytes=5*1024*1024,  # 5MB
            backupCount=3,
            encoding='utf-8'
        )
        shared_handler.setFormatter(formatter)
        shared_handler.addFilter(run_filter)
        root.addHandler(shared_handler)
    except Exception as e:
        sys.stderr.write(f"Failed to setup shared file logger: {e}\n")

    # 3. Run-isolated File output (runs/<run_id>/bot.log)
    try:
        run_dir = get_run_directory(active_run_id)
        run_log_path = os.path.join(run_dir, "bot.log")
        run_file_handler = logging.FileHandler(run_log_path, encoding='utf-8')
        run_file_handler.setFormatter(formatter)
        run_file_handler.addFilter(run_filter)
        root.addHandler(run_file_handler)
    except Exception as e:
        sys.stderr.write(f"Failed to setup run-isolated file logger: {e}\n")

    # Silence noise from external libraries
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Returns a logger instance for modules."""
    return logging.getLogger(name)
