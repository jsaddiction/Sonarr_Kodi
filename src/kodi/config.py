"""Kodi JSON-RPC client Config"""
from dataclasses import dataclass
from ipaddress import IPv4Address
from typing import Tuple, Self, Type


@dataclass
class ClientConfig:
    """Kodi Client Config"""

    name: str
    host: str
    port: int
    user: str
    password: str
    enabled: bool
    priority: int

    def __post_init__(self) -> None:
        assert isinstance(self.name, str) and len(self.name) > 0, "Invalid hosts.name"

        assert IPv4Address(self.host).version == 4, "Invalid IPv4 address hosts.host"

        assert isinstance(self.port, int) and self.port > 0 and self.port <= 65535, "Invalid hosts.port"

        assert isinstance(self.user, str) or self.user is None, "Invalid user. Must be a string"

        assert isinstance(self.password, str) or self.user is None, "Invalid password, Must be a string"

        assert isinstance(self.enabled, bool), "Invalid hosts.enabled. Must be one of [true, false, yes, no]"

        assert (
            isinstance(self.priority, int) and self.priority >= 0
        ), "Invalid hosts.priority. Must be a positive integer"

    @property
    def credentials(self) -> Tuple[str, str]:
        """Tuple of credentials"""
        return (self.user, self.password)

    @classmethod
    def from_dict(cls: Type["ClientConfig"], data: dict) -> Self:
        """Get Instance from dict values"""
        try:
            return cls(
                name=data["name"],
                host=data["host"],
                port=data["port"],
                user=data["user"],
                password=data["password"],
                enabled=data["enabled"],
                priority=data["priority"],
            )
        except (KeyError, ValueError):
            pass
