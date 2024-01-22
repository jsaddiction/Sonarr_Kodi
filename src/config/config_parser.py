"""Sonarr Kodi Configuration Manager"""

import os
import sys
import stat
import shutil
import yaml
from typing import List
from .models import Config, LogLevels

APP_DIR = os.path.abspath(os.path.join(__file__, "../../../"))
CONFIG_PATH = os.path.join(APP_DIR, "settings.yaml")
DEFAULT_CFG_PATH = os.path.join(os.path.dirname(__file__), "default_config.yaml")
RW_PERMS = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
CONFIG_SCHEMA = {
    "logs": {
        "level": str,
        "write_file": bool,
    },
    "library": {
        "clean_after_update": bool,
        "wait_for_nfo": bool,
        "nfo_timeout_minuets": int,
        "full_scan_fallback": bool,
        "skip_active": bool,
        "path_mapping": [
            {"sonarr": str, "kodi": str},
        ],
    },
    "notifications": {
        "on_grab": bool,
        "on_download_new": bool,
        "on_download_upgrade": bool,
        "on_rename": bool,
        "on_delete": bool,
        "on_series_add": bool,
        "on_series_delete": bool,
        "on_health_issue": bool,
        "on_health_restored": bool,
        "on_application_update": bool,
        "on_manual_interaction_required": bool,
    },
    "hosts": [
        {
            "name": str,
            "ip_addr": str,
            "port": int,
            "user": str,
            "password": str,
            "enabled": bool,
            "disable_notifications": bool,
            "priority": int,
        }
    ],
}


class ConfigError(Exception):
    """An Error was found in the config file"""


def validate_config(config: dict, schema: dict, path: List[str] = None) -> None:
    """Validate Config dict"""
    if path is None:
        path = []
    for key, expected_type in schema.items():
        current_path = path + [key]
        current_path_str = ".".join(current_path)
        if key not in config:
            if key == "path_mapping":
                continue
            raise ConfigError(f"'{current_path_str}' is missing in the config.")

        actual_value = config[key]
        if isinstance(expected_type, dict):
            # Recursive call for nested dictionaries
            validate_config(actual_value, expected_type, current_path)
        elif isinstance(expected_type, list):
            # Validate each item in the list against the schema
            if not isinstance(actual_value, list):
                raise ConfigError(f"Expected a list for '{current_path_str}', got {type(actual_value)}.")

            for i, item in enumerate(actual_value):
                if not isinstance(item, dict):
                    raise ConfigError(f"Each item in '{current_path_str}' list must be a dictionary.")
                validate_config(item, expected_type[0], current_path + [f"{i}"])
        else:
            # Validate primitive types
            if key == "level" and not isinstance(actual_value, str):
                raise ConfigError(f"Invalid type for '{current_path_str}', expected str, got {type(actual_value)}")

            if key == "level" and actual_value.upper() not in LogLevels.values():
                opts = ", ".join(LogLevels.values())
                raise ConfigError(f"Invalid value for '{current_path_str}', options: {opts}, got {actual_value}")

            if not isinstance(actual_value, expected_type):
                raise ConfigError(
                    f"Invalid type for '{current_path_str}', expected {expected_type}, got {type(actual_value)}."
                )


def _read_config(path: str) -> Config:
    if not os.path.isfile(path):
        raise FileNotFoundError("User Config file not found.")

    print(f"Reading file: {os.path.abspath(path)}")

    try:
        with open(path, mode="r", encoding="utf8") as file:
            cfg = yaml.safe_load(file.read())
    except OSError as err:
        raise OSError(f"Failed to read  config file. ERROR: {err}") from None

    # Validate Config file
    try:
        validate_config(cfg, CONFIG_SCHEMA)
    except ConfigError as e:
        print(f"Invalid Config. Error: {e}")
        sys.exit(1)

    # Build config dataclass
    return Config.from_dict(cfg)


def get_config() -> Config:
    """Read config file, copy default if none exists"""
    print(LogLevels)
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
