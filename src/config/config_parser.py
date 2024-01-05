"""Sonarr Kodi Configuration Manager"""

import os
import sys
import stat
import shutil
import yaml
from .models import Config

APP_DIR = os.path.abspath(os.path.join(__file__, "../../../"))
CONFIG_PATH = os.path.join(APP_DIR, "settings.yaml")
DEFAULT_CFG_PATH = os.path.join(os.path.dirname(__file__), "default_config.yaml")
RW_PERMS = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


def _read_config(path: str) -> Config:
    if not os.path.isfile(path):
        raise FileNotFoundError("User Config file not found.")

    try:
        with open(path, mode="r", encoding="utf8") as file:
            cfg = yaml.safe_load(file.read())
    except OSError as err:
        raise OSError(f"Failed to read  config file. ERROR: {err}") from None

    return Config.from_dict(cfg)


def get_config() -> Config:
    """Read config file, copy default if none exists"""
    if not os.path.isfile(CONFIG_PATH):
        try:
            shutil.copy(DEFAULT_CFG_PATH, CONFIG_PATH)
            os.chmod(CONFIG_PATH, RW_PERMS)
        except OSError as err:
            raise OSError(f"Failed to write default config file. ERROR: {err}") from None

    def_config = _read_config(DEFAULT_CFG_PATH)
    usr_config = _read_config(CONFIG_PATH)

    if def_config == usr_config:
        print(f"Default config detected. Please Edit {CONFIG_PATH} before using this script.")
        sys.exit(0)

    return usr_config
