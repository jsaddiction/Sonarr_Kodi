"""Kodi JSON-RPC client Config"""
from dataclasses import dataclass, field
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

    @property
    def credentials(self) -> Tuple[str, str]:
        """Tuple of credentials"""
        return (self.user, self.password)

    @classmethod
    def from_dict(cls: Type["HostConfig"], data: dict) -> Self:
        """Get Instance from dict values"""
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
