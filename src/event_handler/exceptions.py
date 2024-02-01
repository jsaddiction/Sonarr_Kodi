"""Event handler exceptions"""
from pathlib import Path
from datetime import timedelta


class NFOTimeout(Exception):
    """Timed out while waiting for NFO to be created"""

    def __init__(self, elapsed_time: timedelta, missing_nfos: list[Path], *args: object) -> None:
        super().__init__(*args)
        self.missing_nfos: list[Path] = missing_nfos
        self.elapsed_time: timedelta = elapsed_time

    def __str__(self) -> str:
        nfo_str = ", ".join([x.name for x in self.missing_nfos])
        return f"NFO Timeout. Waited for {self.elapsed_time}. Still missing [{nfo_str}]"
