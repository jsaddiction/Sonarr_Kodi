"""Kodi JSON-RPC Interface"""

from .kodi import (
    ClientConfig,
    KodiResponse,
    KodiResponseError,
    ResumeState,
    WatchedState,
    EpisodeDetails,
    APIError,
    ScanTimeout,
    KodiClient,
)

__all__ = [
    "ClientConfig",
    "KodiResponse",
    "KodiResponseError",
    "ResumeState",
    "WatchedState",
    "EpisodeDetails",
    "APIError",
    "ScanTimeout",
    "KodiClient",
]
