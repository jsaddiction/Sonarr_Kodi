"""Sonarr Kodi"""

import logging
import logging.config
from pathlib import Path
from .config import Config
from .config.models import LogCfg

__all__ = ["Config"]


def _get_log_path() -> str:
    """Determine where to store logs"""
    file_path = "/config/logs"
    file_name = "Sonarr_Kodi.txt"

    if not Path(file_path).exists():
        # Create and return a /logs directory within this package
        log_dir = Path(__file__).resolve().parent.parent / "logs"
        if not log_dir.exists():
            log_dir.mkdir()
        return str(Path(log_dir, file_name))

    # Return the default Sonarr logs directory
    return str(Path(file_path, file_name))


DEFAULT_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": True,
    "formatters": {
        "file": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
        "console": {
            "format": "%(name)s - %(levelname)s - %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "WARNING",
            "formatter": "console",
            "stream": "ext://sys.stderr",
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "INFO",
            "formatter": "file",
            "filename": _get_log_path(),
            "maxBytes": 1_000_000,
            "backupCount": 5,
        },
    },
    "loggers": {
        "root": {
            "handlers": ["console", "file"],
            "level": "DEBUG",
        }
    },
}

logging.config.dictConfig(DEFAULT_LOG_CONFIG)


def config_log(log_cfg: LogCfg) -> None:
    """Configure logging"""
    logger = logging.root
    for handler in logger.handlers:
        if handler.get_name() == "file":
            handler.setLevel(log_cfg.level)
            logger.removeHandler(handler)
