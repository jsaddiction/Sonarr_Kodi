"""Sonarr Kodi Config Models"""

import logging
import sys
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
    def _missing_(cls, value: object) -> Any:
        value = value.upper()
        for member in cls:
            if member.value == value:
                return member
        return None


@dataclass
class LogCfg:
    """Log Config"""

    level: LogLevels
    write_file: bool

    def __post_init__(self) -> None:
        try:
            LogLevels(self.level)
        except ValueError:
            raise ValueError("Invalid logs.level. Must be one of [debug, info, warning, critical]") from None

        assert isinstance(self.write_file, bool), "Invalid logs.write_file. Must be one of [true, false, yes, no]"

    @classmethod
    def from_dict(cls: Type["LogCfg"], data: dict) -> Self:
        """Get Instance from dict values"""
        try:
            return cls(level=LogLevels(data["level"]).value, write_file=data["write_file"])
        except KeyError as err:
            log.critical("Invalid Logs Config. %s key not found.", err)
            sys.exit(1)
        except ValueError as err:
            log.critical("Invalid Logs Config. %s", err)
            sys.exit(1)


@dataclass
class PathMapping:
    """Sonarr to Host path maps"""

    sonarr: str
    kodi: str

    def __post_init__(self) -> None:
        assert isinstance(self.sonarr, str), "Invalid library.path_mapping.sonarr, Must be a string"

        assert isinstance(self.kodi, str), "Invalid library.path_mapping.kodi, Must be a string"

    @classmethod
    def from_dict(cls: Type["PathMapping"], data: dict) -> Self:
        """Get Instance from dict values"""
        try:
            return cls(sonarr=data["sonarr"], kodi=data["kodi"])
        except KeyError as err:
            log.critical("Invalid path_mapping Config. %s key not found.", err)
            sys.exit(1)
        except AssertionError as err:
            log.critical(err)
            sys.exit(1)


@dataclass
class LibraryCfg:
    """Library Config"""

    clean_after_update: bool
    skip_active: bool
    full_scan_fallback: bool
    wait_for_nfo: bool
    nfo_timeout_minuets: int
    path_mapping: list[PathMapping]

    def __post_init__(self) -> None:
        assert isinstance(
            self.clean_after_update, bool
        ), "Invalid library.clean_after_update. Must Be one of [true, false, yes, no]"

        assert isinstance(
            self.wait_for_nfo, bool
        ), "Invalid library.wait_for_nfo. Must Be one of [true, false, yes, no]"

        assert isinstance(self.nfo_timeout_minuets, int), "Invalid library.nfo_timeout_minuets. Must be an integer"

        assert isinstance(
            self.skip_active, bool
        ), "Invalid library.update_while_playing. Must Be one of [true, false, yes, no]"

        assert isinstance(
            self.full_scan_fallback, bool
        ), "Invalid library.full_scan_fallback. Must Be one of [true, false, yes, no]"

    @classmethod
    def from_dict(cls: Type["LibraryCfg"], data: dict) -> Self:
        """Get Instance from dict values"""
        path_mapping = []
        if "path_mapping" in data and data["path_mapping"] is not None:
            path_mapping = [PathMapping.from_dict(x) for x in data["path_mapping"]]

        try:
            return cls(
                clean_after_update=data["clean_after_update"],
                wait_for_nfo=data["wait_for_nfo"],
                nfo_timeout_minuets=data["nfo_timeout_minuets"],
                skip_active=data["skip_active"],
                full_scan_fallback=data["full_scan_fallback"],
                path_mapping=path_mapping,
            )
        except KeyError as err:
            log.critical("Invalid Library Config. %s key not found.", err)
            sys.exit(1)


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

    def __post_init__(self) -> None:
        assert isinstance(self.on_grab, bool), "Invalid notifications.on_grab. Must Be one of [true, false, yes, no]"

        assert isinstance(
            self.on_download_new, bool
        ), "Invalid notifications.on_download_new. Must Be one of [true, false, yes, no]"

        assert isinstance(
            self.on_download_upgrade, bool
        ), "Invalid notifications.on_download_upgrade. Must Be one of [true, false, yes, no]"

        assert isinstance(
            self.on_rename, bool
        ), "Invalid notifications.on_rename. Must Be one of [true, false, yes, no]"

        assert isinstance(
            self.on_delete, bool
        ), "Invalid notifications.on_delete. Must Be one of [true, false, yes, no]"

        assert isinstance(
            self.on_series_add, bool
        ), "Invalid notifications.on_series_add. Must Be one of [true, false, yes, no]"

        assert isinstance(
            self.on_series_delete, bool
        ), "Invalid notifications.on_series_delete. Must Be one of [true, false, yes, no]"

        assert isinstance(
            self.on_health_issue, bool
        ), "Invalid notifications.on_health_issue. Must Be one of [true, false, yes, no]"

        assert isinstance(
            self.on_health_restored, bool
        ), "Invalid notifications.on_health_restored. Must Be one of [true, false, yes, no]"

        assert isinstance(
            self.on_application_update, bool
        ), "Invalid notifications.on_application_update. Must Be one of [true, false, yes, no]"

        assert isinstance(
            self.on_manual_interaction_required, bool
        ), "Invalid notifications.on_manual_interaction_required. Must Be one of [true, false, yes, no]"

        assert isinstance(self.on_test, bool), "Invalid notifications.on_test. Must Be one of [true, false, yes, no]"

    @classmethod
    def from_dict(cls: Type["Notifications"], data: dict) -> Self:
        """Get Instance from dict values"""
        try:
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
        except KeyError as err:
            log.critical("Invalid hosts.notifications Config. %s key not found.", err)
            sys.exit(1)
        except ValueError as err:
            log.critical("Invalid host.notifications Config. %s", err)
            sys.exit(1)


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
        try:
            log_cfg = data["logs"]
            library_cfg = data["library"]
            hosts_cfg = data["hosts"]
            notification_cfg = data["notifications"]
        except KeyError as err:
            log.critical("Invalid Config. %s key not found.", err)
            sys.exit(1)

        return cls(
            logs=LogCfg.from_dict(log_cfg),
            library=LibraryCfg.from_dict(library_cfg),
            notifications=Notifications.from_dict(notification_cfg),
            hosts=[HostConfig.from_dict(x) for x in hosts_cfg],
        )
