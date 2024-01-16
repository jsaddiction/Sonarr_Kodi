"""Kodi JSON-RPC client Config"""
from dataclasses import dataclass, field
from ipaddress import IPv4Address
from typing import Tuple, Self, Type


@dataclass
class PathMapping:
    """Kodi Client Path Mapping"""

    sonarr: str
    kodi: str


@dataclass
class HostConfig:
    """Kodi Host Config"""

    name: str
    ip_addr: str
    port: int
    user: str
    password: str
    enabled: bool
    disable_notifications: bool
    priority: int
    path_maps: list[PathMapping] = field(default_factory=list)

    def __post_init__(self) -> None:
        assert isinstance(self.name, str) and len(self.name) > 0, "Invalid hosts.name"

        assert IPv4Address(self.ip_addr).version == 4, "Invalid IPv4 address hosts.host"

        assert isinstance(self.port, int) and self.port > 0 and self.port <= 65535, "Invalid hosts.port"

        assert isinstance(self.user, str) or self.user is None, "Invalid user. Must be a string"

        assert isinstance(self.password, str) or self.user is None, "Invalid password, Must be a string"

        assert isinstance(self.enabled, bool), "Invalid hosts.enabled. Must be one of [true, false, yes, no]"

        assert isinstance(
            self.disable_notifications, bool
        ), "Invalid hosts.disable_notifications. Must be one of [true, false, yes, no]"

        assert (
            isinstance(self.priority, int) and self.priority >= 0
        ), "Invalid hosts.priority. Must be a positive integer"

    @property
    def credentials(self) -> Tuple[str, str]:
        """Tuple of credentials"""
        return (self.user, self.password)

    @classmethod
    def from_dict(cls: Type["HostConfig"], data: dict) -> Self:
        """Get Instance from dict values"""
        try:
            return cls(
                name=data["name"],
                ip_addr=data["ip_addr"],
                port=data["port"],
                user=data["user"],
                password=data["password"],
                enabled=data["enabled"],
                disable_notifications=data["disable_notifications"],
                priority=data["priority"],
            )
        except (KeyError, ValueError):
            pass
