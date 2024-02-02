"""Response Models for Kodi JSON-RPC"""

from enum import Enum
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime


DT_FORMAT = "%Y-%m-%d %H:%M:%S"
EP_PROPERTIES = [
    "lastplayed",
    "playcount",
    "file",
    "season",
    "episode",
    "tvshowid",
    "showtitle",
    "dateadded",
    "title",
    "resume",
]
SHOW_PROPERTIES = ["title", "file", "year"]


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


@dataclass(frozen=True, order=True)
class RPCVersion:
    """JSON-RPC Version info"""

    major: int
    minor: int
    patch: int = field(compare=False)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass
class Notification:
    """Kodi Notification"""

    title: str
    msg: str
    display_time: int = field(default=5000)
    image: str = field(default="https://github.com/jsaddiction/KodiLibrarian/raw/main/img/Sonarr.png")

    def __str__(self) -> str:
        return f"TITLE='{self.title}' MSG='{self.msg}'"


@dataclass
class KodiResponseError:
    """Error Response"""

    code: int = field(default=None)
    message: str = field(default=None)
    method: str = field(default=None)
    stack_name: str = field(default=None)
    stack_type: str = field(default=None)
    stack_message: str = field(default=None)
    stack_property_message: str = field(default=None)
    stack_property_type: str = field(default=None)
    timed_out: bool = field(default=False)
    http_error: str | None = field(default=None)
    connection_error: str | None = field(default=None)

    def __str__(self) -> str:
        """Print the error"""
        return f"{self.method} {self.stack_message}, {self.stack_property_message}, {self.stack_name} CODE: {self.code}"


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
class Player:
    """A Content player"""

    player_id: int
    player_type: str
    type: str


@dataclass
class PlayerItem:
    """What the player is playing"""

    item_id: int
    label: str
    type: str


@dataclass
class ResumeState:
    """Resume Point of a Media Item"""

    position: int = field(default=0)
    total: int = field(default=0)

    @property
    def percent(self) -> float:
        """Percent complete"""
        if self.total == 0 or self.position == 0:
            return 0.0

        return (self.position / self.total) * 100

    def __str__(self) -> str:
        return f"Resume {self.percent:.2f}% Complete."


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
        if not self.last_played:
            return False

        return bool(self.last_played) and self.play_count > 0

    def __str__(self) -> str:
        return f"Added={self.date_added} Plays={self.play_count} LastPlay={self.last_played} {self.resume}"


@dataclass
class ShowDetails:
    """Details of a Show"""

    show_id: int
    file: str
    title: str
    year: int

    def __str__(self) -> str:
        return f"{self.title} ({self.year})"


@dataclass(frozen=True, order=False, eq=True)
class EpisodeDetails:
    """Details of an episode"""

    episode_id: int = field(compare=False, hash=False)
    show_id: int = field(compare=True, hash=True)
    file: str = field(compare=False, hash=False)
    show_title: str = field(compare=False, hash=False)
    episode_title: str = field(compare=False, hash=False)
    season: int = field(compare=True, hash=True)
    episode: int = field(compare=True, hash=True)
    watched_state: WatchedState = field(compare=False, hash=False)

    @staticmethod
    def sanitize_ep_title(raw_title: str) -> str:
        """Static method to sanitize episode title"""
        if "-" in raw_title:
            return raw_title.rsplit(" - ", 1)[-1].strip()
        return raw_title

    def __str__(self) -> str:
        return f"{self.show_title} - S{self.season:02}E{self.episode:02} - {self.sanitize_ep_title(self.episode_title)}"


@dataclass(frozen=True)
class StoppedEpisode:
    """Episode that was playing during delete event"""

    episode: EpisodeDetails
    host_name: str
    position: float
    paused: bool

    def __str__(self) -> str:
        return f"{self.episode} on {self.host_name} stopped at {self.position}"
