"""Sonarr Environment parser"""
from dataclasses import dataclass, field, fields
from enum import Enum
from typing import get_args, get_origin, Any
from os import environ


class Events(Enum):
    """Sonarr Events"""

    ON_GRAB = "Grab"
    ON_DOWNLOAD = "Download"
    ON_RENAME = "Rename"
    ON_DELETE = "EpisodeFileDelete"
    ON_SERIES_ADD = "SeriesAdd"
    ON_SERIES_DELETE = "SeriesDelete"
    ON_HEALTH_ISSUE = "HealthIssue"
    ON_HEALTH_RESTORED = "HealthRestored"
    ON_APPLICATION_UPDATE = "ApplicationUpdate"
    ON_MANUAL_INTERACTION_REQUIRED = "ManualInteractionRequired"
    ON_TEST = "Test"
    UNKNOWN = "Unknown"

    @classmethod
    def _missing_(cls, value: object) -> Any:
        value = value.upper()
        for member in cls:
            if member.value.upper() == value:
                return member
        return cls.UNKNOWN


@dataclass
class SonarrEnvironment:
    """Sonarr Environment Variables"""

    event_type: Events = field(default=Events.UNKNOWN, metadata={"var": "Sonarr_EventType"})
    instance_name: str = field(default=None, metadata={"var": "Sonarr_InstanceName"})
    application_url: str = field(default=None, metadata={"var": "Sonarr_ApplicationUrl"})
    series_title: str = field(default=None, metadata={"var": "Sonarr_Series_Title"})
    series_year: int = field(default=None, metadata={"var": "Sonarr_Series_Year"})
    series_path: str = field(default=None, metadata={"var": "Sonarr_Series_Path"})
    series_deleted_files: bool = field(default=None, metadata={"var": "Sonarr_Series_DeletedFiles"})
    release_season_number: int = field(default=None, metadata={"var": "Sonarr_Release_SeasonNumber"})
    release_episode_numbers: list[int] = field(default_factory=list, metadata={"var": "Sonarr_Release_EpisodeNumbers"})
    release_episode_titles: list[str] = field(default_factory=list, metadata={"var": "Sonarr_Release_EpisodeTitles"})
    episode_file_path: str = field(default=None, metadata={"var": "Sonarr_EpisodeFile_Path"})
    episode_file_previous_paths: list[str] = field(
        default_factory=list, metadata={"var": "Sonarr_EpisodeFile_PreviousPaths"}
    )
    episode_file_rel_paths: list[str] = field(
        default_factory=list, metadata={"var": "Sonarr_EpisodeFile_RelativePaths"}
    )
    episode_file_delete_reason: str = field(default=None, metadata={"var": "Sonarr_EpisodeFile_DeleteReason"})
    deleted_paths: list[str] = field(default_factory=list, metadata={"var": "Sonarr_deletedpaths"})
    is_upgrade: bool = field(default=None, metadata={"var": "Sonarr_IsUpgrade"})
    health_issue_msg: str = field(default=None, metadata={"var": "Sonarr_Health_Issue_Message"})
    health_issue_type: str = field(default=None, metadata={"var": "Sonarr_Health_Issue_Type"})
    health_restored_msg: str = field(default=None, metadata={"var": "Sonarr_Health_Restored_Message"})
    health_restored_type: str = field(default=None, metadata={"var": "Sonarr_Health_Restored_Type"})
    update_message: str = field(default=None, metadata={"var": "Sonarr_Update_Message"})
    update_prev_vers: str = field(default=None, metadata={"var": "Sonarr_Update_PreviousVersion"})
    update_new_vers: str = field(default=None, metadata={"var": "Sonarr_Update_NewVersion"})

    @classmethod
    def _parse_bool(cls, value: str) -> bool:
        if isinstance(value, str):
            if value.lower().strip() == "true":
                return True
            if value.lower().strip() == "false":
                return False

        raise ValueError(f"Failed to parse '{value}' to a boolean")

    @classmethod
    def _parse_int(cls, value: str) -> int:
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                pass

        raise ValueError(f"Failed to parse {value} to int")

    def __post_init__(self) -> None:
        # Get environment variables
        env_vars = {k.lower().strip(): v for k, v in environ.items() if k.lower().startswith("sonarr")}

        # Loop through dataclass fields
        for attr in fields(self):
            var_name = attr.metadata.get("var")
            value = env_vars.get(var_name.lower())
            if not value:
                continue

            # Based on attribute type, store this environment variable's value
            if issubclass(attr.type, Events):
                self.__setattr__(attr.name, Events(value))

            elif issubclass(attr.type, str):
                self.__setattr__(attr.name, value.strip())

            elif issubclass(attr.type, bool):
                self.__setattr__(attr.name, self._parse_bool(value))

            elif issubclass(attr.type, int):
                self.__setattr__(attr.name, self._parse_int(value))

            # Handle lists
            elif get_origin(attr.type) == list:
                list_type = get_args(attr.type)[0]

                # List of strings
                if issubclass(list_type, str):
                    value_lst = [x.strip() for x in value.split("|")]
                    self.__setattr__(attr.name, value_lst)

                # List of integers
                elif issubclass(list_type, int):
                    value_lst = [self._parse_int(x) for x in value.split(",")]
                    self.__setattr__(attr.name, value_lst)
