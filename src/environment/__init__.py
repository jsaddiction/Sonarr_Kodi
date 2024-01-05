"""Sonarr Environment Variable Parsing"""

from .sonarr import SonarrEnvironment, Events

ENV = SonarrEnvironment()

__all__ = [
    "ENV",
    "Events",
]
