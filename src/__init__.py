"""Sonarr Kodi"""

import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from .config.models import LogCfg

# Setup Logging
LOG_FILE_PATH = "/config/logs"
LOG_FILE_NAME = "Sonarr_Kodi.txt"
LOG_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FMT = ""


def config_log(log_cfg: LogCfg) -> None:
    """Configure Logging"""
    # Establish file handler
    fh = RotatingFileHandler(
        filename=Path(LOG_FILE_PATH, LOG_FILE_NAME), mode="a", maxBytes=1_000_000, backupCount=5, encoding="utf-8"
    )

    # Establish stderr output
    sh = logging.StreamHandler()

    # Build handler list based on config
    handlers = [sh]
    if log_cfg.write_file:
        handlers.append(fh)

    # Write config to logger
    logging.basicConfig(format=LOG_FMT, datefmt=DATE_FMT, level=log_cfg.level, handlers=handlers)
