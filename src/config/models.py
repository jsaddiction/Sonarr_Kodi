"""Sonarr Kodi Config Models"""

import logging
from dataclasses import dataclass, field
from typing import Any, Type, Self
from enum import Enum
from src.kodi.config import HostConfig

log = logging.getLogger("Config Parser")


class LogLevels(Enum):
    """Supported Logging Levels"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

    @classmethod
    def values(cls) -> list[str]:
        """List of values within LogLevels"""
        return [member.value for member in cls]

    @classmethod
    def _missing_(cls, value: object) -> Any:
        value = value.upper()
        for member in cls:
            if member.value == value:
                return member
        return None


@dataclass
class LogCfg:
    """Log Config"""

    level: LogLevels = field(metadata={"type": str})
    write_file: bool = field(metadata={"type": bool})

    @classmethod
    def from_dict(cls: Type["LogCfg"], data: dict) -> Self:
        """Get Instance from dict values"""

        # Parse into dataclass
        return cls(level=LogLevels(data["level"]).value, write_file=data["write_file"])


@dataclass
class PathMapping:
    """Sonarr to Host path maps"""

    sonarr: str = field(metadata={"type": str})
    kodi: str = field(metadata={"type": str})

    @classmethod
    def from_dict(cls: Type["PathMapping"], data: dict) -> Self:
        """Get Instance from dict values"""

        # Parse into dataclass
        return cls(sonarr=data["sonarr"], kodi=data["kodi"])


@dataclass
class LibraryCfg:
    """Library Config"""

    clean_after_update: bool
    skip_active: bool
    full_scan_fallback: bool
    wait_for_nfo: bool
    nfo_timeout_minuets: int
    path_mapping: list[PathMapping] = field(default_factory=list)

    @classmethod
    def from_dict(cls: Type["LibraryCfg"], data: dict) -> Self:
        """Get Instance from dict values"""

        # Parse into dataclass
        library_cfg = cls(
            clean_after_update=data["clean_after_update"],
            wait_for_nfo=data["wait_for_nfo"],
            nfo_timeout_minuets=data["nfo_timeout_minuets"],
            skip_active=data["skip_active"],
            full_scan_fallback=data["full_scan_fallback"],
        )

        # Check for and add optional path mapping definitions
        if "path_mapping" in data and data["path_mapping"] is not None:
            library_cfg.path_mapping = [PathMapping.from_dict(x) for x in data["path_mapping"]]

        return library_cfg


@dataclass
class Notifications:
    """Notification Config"""

    on_grab: bool
    on_download_new: bool
    on_download_upgrade: bool
    on_rename: bool
    on_delete: bool
    on_series_add: bool
    on_series_delete: bool
    on_health_issue: bool
    on_health_restored: bool
    on_application_update: bool
    on_manual_interaction_required: bool
    on_test: bool

    @classmethod
    def from_dict(cls: Type["Notifications"], data: dict) -> Self:
        """Get Instance from dict values"""

        # Parse into dataclass
        return cls(
            on_grab=data["on_grab"],
            on_download_new=data["on_download_new"],
            on_download_upgrade=data["on_download_upgrade"],
            on_rename=data["on_rename"],
            on_delete=data["on_delete"],
            on_series_add=data["on_series_add"],
            on_series_delete=data["on_series_delete"],
            on_health_issue=data["on_health_issue"],
            on_health_restored=data["on_health_restored"],
            on_application_update=data["on_application_update"],
            on_manual_interaction_required=data["on_manual_interaction_required"],
            on_test=data["on_test"],
        )


@dataclass
class Config:
    """Configuration Model"""

    logs: LogCfg = field(default_factory=LogCfg)
    library: LibraryCfg = field(default_factory=LibraryCfg)
    notifications: Notifications = field(default_factory=Notifications)
    hosts: list[HostConfig] = field(default_factory=list)

    @classmethod
    def from_dict(cls: Type["Config"], data: dict) -> Self:
        """Get Instance from dict values"""

        # Parse into dataclass
        return cls(
            logs=LogCfg.from_dict(data["logs"]),
            library=LibraryCfg.from_dict(data["library"]),
            notifications=Notifications.from_dict(data["notifications"]),
            hosts=[HostConfig.from_dict(x) for x in data["hosts"]],
        )
