"""Sonarr Kodi Configuration Manager"""

import sys
import ipaddress
from pathlib import Path
import yaml
from .models import Config, LogLevels
from .exceptions import ConfigError

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


class ConfigParser:
    """Parse and validate config files"""

    @classmethod
    def _validate_config(cls, config: dict, schema: dict, path: list[str] = None) -> None:
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
                cls._validate_config(actual_value, expected_type, current_path)
            elif isinstance(expected_type, list):
                # Validate each item in the list against the schema
                if not isinstance(actual_value, list):
                    raise ConfigError(f"Expected a list for '{current_path_str}', got {type(actual_value)}.")

                for i, item in enumerate(actual_value):
                    if not isinstance(item, dict):
                        raise ConfigError(f"Each item in '{current_path_str}' list must be a dictionary.")
                    cls._validate_config(item, expected_type[0], current_path + [f"[{i}]"])
            else:
                # Validate primitive types
                if not isinstance(actual_value, expected_type):
                    val_type = type(actual_value)
                    raise ConfigError(
                        f"Invalid type for '{current_path_str}', expected {expected_type}, got {val_type}."
                    )

                # Validate log.level field
                if key == "level":
                    if actual_value.upper() not in LogLevels.values():
                        opts = ", ".join(LogLevels.values())
                        raise ConfigError(
                            f"Invalid value for '{current_path_str}', options: {opts}, got {actual_value}"
                        )

                # Validate host[x].ip_addr field
                if key == "ip_addr":
                    try:
                        ipaddress.ip_address(actual_value)
                    except ValueError as e:
                        raise ConfigError(f"Invalid value for '{current_path_str}' got {actual_value}") from e
                    continue

                # Validate host[x].port field
                if key == "port":
                    if actual_value < 0 or actual_value > 65535:
                        raise ConfigError(
                            f"Invalid value for '{current_path_str}' got {actual_value}. Must be between 0-65535"
                        )

    def is_default(self, config: Config) -> bool:
        """Determine if Config dataclass matches default config"""
        default_cfg_path = Path(__file__).with_name("default_config.yaml")
        default_cfg = self.get_config(default_cfg_path)

        return default_cfg == config

    def get_config(self, config_path: Path) -> Config:
        """Read config and return Config dataclass"""
        try:
            with open(config_path, mode="r", encoding="utf8") as file:
                cfg = yaml.safe_load(file.read())
        except FileNotFoundError as e:
            print(f"Config file not found at '{config_path}' Error: {e}", file=sys.stderr)
            sys.exit(1)
        except OSError as e:
            print(f"Failed to read config file. Error: {e}", file=sys.stderr)
            sys.exit(1)

        try:
            self._validate_config(cfg, CONFIG_SCHEMA)
        except ConfigError as e:
            print(f"Invalid Config file. {e}", file=sys.stderr)
            sys.exit(1)

        return Config.from_dict(cfg)
