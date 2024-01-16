"""Sonarr Kodi"""

import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from .config import Config
from .config.models import LogCfg

# Setup Logging
LOG_FILE_PATH = "/config/logs"
LOG_FILE_NAME = "Sonarr_Kodi.txt"
FILE_LOG_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
CONSOLE_LOG_FMT = "%(name)s - %(levelname)s - %(message)s"

__all__ = ["Config"]


def config_log(log_cfg: LogCfg) -> None:
    """Configure Logging"""
    handlers: list[logging.Handler] = []

    # Establish stderr output
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter(CONSOLE_LOG_FMT))
    handlers.append(sh)

    # Create File handler if configured
    if log_cfg.write_file:
        file_path = Path(LOG_FILE_PATH, LOG_FILE_NAME)
        fh = RotatingFileHandler(filename=file_path, mode="a", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(logging.Formatter(FILE_LOG_FMT))
        handlers.append(fh)

    # Write config to logger
    logging.basicConfig(level=log_cfg.level, handlers=handlers)
