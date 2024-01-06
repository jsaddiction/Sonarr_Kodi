"""Sonarr Kodi"""

import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from .config.models import LogCfg

# Setup Logging
LOG_FILE_PATH = "/config/logs"
LOG_FILE_NAME = "Sonarr_Kodi.txt"
FILE_LOG_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
CONSOLE_LOG_FMT = "%(name)s - %(levelname)s - %(message)s"


def config_log(log_cfg: LogCfg) -> None:
    """Configure Logging"""
    # Establish file handler
    fh = RotatingFileHandler(
        filename=Path(LOG_FILE_PATH, LOG_FILE_NAME), mode="a", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(FILE_LOG_FMT)

    # Establish stderr output
    sh = logging.StreamHandler()
    sh.setFormatter(CONSOLE_LOG_FMT)

    # Build handler list based on config
    handlers = [sh]
    if log_cfg.write_file:
        handlers.append(fh)

    # Write config to logger
    logging.basicConfig(level=log_cfg.level, handlers=handlers)
