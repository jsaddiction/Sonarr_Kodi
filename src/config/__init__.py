"""Sonarr Kodi Configuration"""

from .config_parser import get_config
from .models import Config

CFG = get_config()

__all__ = [
    "CFG",
    "Config",
]
