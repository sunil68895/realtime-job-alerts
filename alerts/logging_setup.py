"""Configure hourly rotating logs and remove expired job-alert log files."""

import logging
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path


LOG_NAME = "job-alerts.log"
ROTATED_LOG_PATTERN = re.compile(r"^job-alerts\.log\.\d{4}-\d{2}-\d{2}_\d{2}$")
LOG_RETENTION = timedelta(days=5)


def _delete_expired_logs(log_dir: Path) -> int:
    cutoff = datetime.now(timezone.utc).timestamp() - LOG_RETENTION.total_seconds()
    deleted = 0
    for path in log_dir.iterdir():
        if not ROTATED_LOG_PATTERN.fullmatch(path.name) or not path.is_file():
            continue
        if path.stat().st_mtime < cutoff:
            path.unlink()
            deleted += 1
    return deleted


def _log_uncaught_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.getLogger("alerts").critical(
        "Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback)
    )


def configure_logging(log_dir: Path) -> logging.Logger:
    """Write logs to stdout and an hourly rotating file, retaining five days."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    _delete_expired_logs(log_dir)

    logger = logging.getLogger("alerts")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(
        fmt="%(asctime)sZ %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime

    file_handler = TimedRotatingFileHandler(
        log_dir / LOG_NAME,
        when="H",
        interval=1,
        backupCount=0,
        utc=True,
        encoding="utf-8",
    )
    file_handler.suffix = "%Y-%m-%d_%H"
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    sys.excepthook = _log_uncaught_exception
    return logger
