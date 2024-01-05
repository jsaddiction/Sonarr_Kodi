"""Response Models for Kodi JSON-RPC"""

from enum import Enum
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime


DT_FORMAT = "%Y-%m-%d %H:%M:%S"


class Platform(Enum):
    """Kodi Platform enumeration"""

    ANDROID = "System.Platform.Android"
    DARWIN = "System.Platform.Darwin"
    IOS = "System.Platform.IOS"
    LINUX = "System.Platform.Linux"
    OSX = "System.Platform.OSX"
    TVOS = "System.Platform.TVOS"
    UWP = "System.Platform.UWP"
    WINDOWS = "System.Platform.Windows"
    UNKNOWN = "Unknown"


@dataclass
class KodiResponseError:
    """Error Response"""

    code: int = field(default=None)
    message: str = field(default=None)
    timed_out: bool = field(default=False)
    http_error: str | None = field(default=None)
    connection_error: str | None = field(default=None)


@dataclass
class KodiResponse:
    """Kodi JSON-RPC Response Model"""

    req_id: int
    jsonrpc: str
    result: Optional[dict] | None = field(default=None)
    error: Optional[KodiResponseError] | None = field(default=None)

    def is_valid(self, expected_str: str = None) -> bool:
        """Check validity of response"""
        # If an error or no result was found
        if self.error is not None or self.result is None:
            return False

        # Check for list typed responses:
        if isinstance(self.result, list):
            return len(self.result) > 0

        # Check for string typed responses
        if isinstance(self.result, str):
            return self.result == expected_str

        # Check for dict typed responses
        if isinstance(self.result, dict):
            if expected_str:
                return expected_str in self.result
            return len(self.result.keys()) > 0

        # Unsupported response type
        return False


@dataclass
class Source:
    """Directory of a Show"""

    file: str
    label: str


@dataclass
class ResumeState:
    """Resume Point of a Media Item"""

    position: float = field(default=0.0)
    total: float = field(default=0.0)


@dataclass
class WatchedState:
    """Watched State of a Media Item"""

    play_count: int | None = field(default=None)
    date_added: datetime | None = field(default=None)
    last_played: datetime | None = field(default=None)
    resume: ResumeState = field(default_factory=ResumeState)

    @property
    def date_added_str(self) -> str:
        """Formatted Date Added DT"""
        if not self.date_added:
            return ""
        return self.date_added.strftime(DT_FORMAT)

    @property
    def last_played_str(self) -> str:
        """Formatted Last Played DT"""
        if not self.last_played:
            return ""
        return self.last_played.strftime(DT_FORMAT)

    @property
    def is_watched(self) -> bool:
        """If this state represents watched"""
        if self.play_count is None:
            return False
        if self.last_played:
            return False

        return bool(self.last_played) and self.play_count > 0


@dataclass
class ShowDetails:
    """Details of a Show"""

    show_id: int
    file: str
    title: str


@dataclass(frozen=True)
class EpisodeDetails:
    """Details of an episode"""

    episode_id: int
    show_id: int
    file: str
    show_title: str
    episode_title: str
    season: str
    episode: str
    watched_state: WatchedState

    def __hash__(self):
        return hash(self.episode_id)

    def __eq__(self, other) -> bool:
        if not isinstance(other, EpisodeDetails):
            return False
        return self.show_id == other.show_id and self.season == other.season and self.episode == other.episode

    def __str__(self) -> str:
        return f"{self.show_title} - S{self.season:02}E{self.episode:02} - {self.episode_title}"
