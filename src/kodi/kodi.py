"""Kodi JSON-RPC Interface"""

import os
import json
import logging
from time import sleep
from datetime import datetime
import requests

from .config import ClientConfig
from .exceptions import APIError, ScanTimeout
from .models import (
    Platform,
    KodiResponse,
    KodiResponseError,
    WatchedState,
    ResumeState,
    EpisodeDetails,
    ShowDetails,
    Source,
)


class KodiClient:
    """Kodi JSON-RPC Client"""

    RETRIES = 3
    TIMEOUT = 5
    REQ_ID = 0
    HEADERS = {"Content-Type": "application/json", "Accept": "plain/text"}
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
    SHOW_PROPERTIES = ["title", "file"]

    def __init__(self, cfg: ClientConfig) -> None:
        self.log = logging.getLogger(f"Client.{cfg.name}")
        self.base_url = f"http://{cfg.host}:{cfg.port}/jsonrpc"
        self.name = cfg.name
        self.credentials = cfg.credentials
        self.enabled = cfg.enabled
        self.priority = cfg.priority
        self.library_scanned = False
        self.platform: Platform = None

    def get_platform(self) -> Platform:
        """Get platform of this client"""
        params = {"booleans": [x.value for x in Platform]}
        resp = self._req("XBMC.GetInfoBooleans", params=params)
        if not resp.is_valid():
            raise ValueError("Failed to get host OS info.")

        for k, v in resp.result.items():
            if v:
                return Platform(k)
        return Platform.UNKNOWN

    @property
    def is_alive(self) -> bool:
        """Return True if Kodi Host is responsive"""
        resp = self._req("JSONRPC.Ping")
        if resp.error:
            if resp.error.timed_out:
                self.log.critical("Timed out. Is device powered on?")
            elif resp.error.connection_error:
                self.log.critical("Connection Failed: Check kodi config.")
        return resp.is_valid("pong")

    @property
    def is_playing(self) -> bool:
        """Return True if Kodi Host is currently playing content"""
        resp = self._req("Player.GetActivePlayers")
        return resp.is_valid()

    @property
    def is_scanning(self) -> bool:
        """True if a library scan is in progress"""
        params = {"booleans": ["Library.IsScanning"]}
        resp = self._req("XBMC.GetInfoBooleans", params=params)
        if not resp.is_valid():
            return False

        return resp.result["Library.IsScanning"]

    @property
    def is_posix(self) -> bool:
        """If this host uses posix file naming conventions"""
        if not self.platform:
            self.platform = self.get_platform()

        return self.platform not in [Platform.WINDOWS, Platform.UNKNOWN]

    @staticmethod
    def _to_dt(dt_str: str) -> datetime | None:
        try:
            return datetime.fromisoformat(dt_str)
        except ValueError:
            return None

    @staticmethod
    def _to_int(num_str: str) -> int | None:
        try:
            return int(num_str)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_float(float_str: str) -> float:
        try:
            return float(float_str)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _parse_show_details(shows: list[dict]) -> list[ShowDetails]:
        show_details_lst = []
        for show in shows:
            show_details_lst.append(
                ShowDetails(show_id=KodiClient._to_int(show["tvshowid"]), file=show["file"], title=show["title"])
            )
        return show_details_lst

    @staticmethod
    def _parse_ep_details(episodes: list[dict]) -> list[EpisodeDetails]:
        ep_details_lst = []
        for episode in episodes:
            ep_details_lst.append(
                EpisodeDetails(
                    episode_id=KodiClient._to_int(episode["episodeid"]),
                    show_id=KodiClient._to_int(episode["tvshowid"]),
                    file=episode["file"],
                    show_title=episode["showtitle"],
                    episode_title=episode["title"],
                    season=KodiClient._to_int(episode["season"]),
                    episode=KodiClient._to_int(episode["episode"]),
                    watched_state=WatchedState(
                        play_count=KodiClient._to_int(episode["playcount"]),
                        date_added=KodiClient._to_dt(episode["dateadded"]),
                        last_played=KodiClient._to_dt(episode["lastplayed"]),
                        resume=ResumeState(
                            position=KodiClient._to_float(episode["resume"]["position"]),
                            total=KodiClient._to_float(episode["resume"]["total"]),
                        ),
                    ),
                )
            )
        return ep_details_lst

    def _req(self, method: str, params: dict = None, timeout: int = None) -> KodiResponse | None:
        """Send request to this Kodi Host"""
        req_params = {"jsonrpc": "2.0", "id": self.REQ_ID, "method": method}
        if params:
            req_params["params"] = params

        if not timeout:
            timeout = self.TIMEOUT

        try:
            resp = requests.post(
                url=self.base_url,
                data=json.dumps(req_params).encode("utf-8"),
                headers=self.HEADERS,
                auth=self.credentials,
                timeout=timeout,
            )
            resp.raise_for_status()
            response = resp.json()
        except requests.Timeout:
            return KodiResponse(
                req_id=self.REQ_ID,
                jsonrpc=req_params["jsonrpc"],
                error=KodiResponseError(timed_out=True),
            )
        except requests.HTTPError as err:
            if resp.status_code == 401:
                self.log.critical("Request Error: Unauthorized. Check Credentials.")
            else:
                self.log.critical("Request Error: %s", err)
            return KodiResponse(
                req_id=self.REQ_ID,
                jsonrpc=req_params["jsonrpc"],
                error=KodiResponseError(http_error=err),
            )
        except requests.ConnectionError as err:
            return KodiResponse(
                req_id=self.REQ_ID,
                jsonrpc=req_params["jsonrpc"],
                error=KodiResponseError(connection_error=err),
            )

        KodiClient.REQ_ID += 1

        error_data = response.get("error")
        error = KodiResponseError(**error_data) if error_data else None

        return KodiResponse(
            req_id=response.get("id"),
            jsonrpc=response.get("jsonrpc"),
            result=response.get("result"),
            error=error,
        )

    def set_episode_watched_state(self, episode: EpisodeDetails, new_ep_id: int) -> None:
        """Set Episode Watched State"""
        params = {
            "episodeid": new_ep_id,
            "playcount": episode.watched_state.play_count,
            "lastplayed": episode.watched_state.last_played_str,
            "dateadded": episode.watched_state.date_added_str,
            "resume": {
                "position": episode.watched_state.resume.position,
                "total": episode.watched_state.resume.total,
            },
        }
        resp = self._req("VideoLibrary.SetEpisodeDetails", params=params)

        print(resp)

        if not resp.is_valid("OK"):
            raise APIError("Invalid response while setting watched state.")

    def _get_show_sources(self) -> list[Source]:
        """Get all sources which contain at least one episode of a Tv Show"""
        sources = []
        params = {"media": "video"}
        resp = self._req("Files.GetSources", params=params)

        if not resp.is_valid("sources"):
            raise APIError("Invalid response while collecting sources")

        for src in resp.result["sources"]:
            source = Source(**src)
            try:
                if len(self.get_shows_from_dir(source.file)) > 0:
                    sources.append(source)
            except APIError:
                continue

        return sources

    def get_episodes_from_file(self, file_path: str) -> list[EpisodeDetails]:
        """Get details of episodes given a file_path"""
        file_name = os.path.basename(file_path)
        file_dir = os.path.dirname(file_path)
        params = {
            "properties": self.EP_PROPERTIES,
            "filter": {
                "and": [
                    {"operator": "startswith", "field": "path", "value": file_dir},
                    {"operator": "is", "field": "filename", "value": file_name},
                ]
            },
        }
        resp = self._req("VideoLibrary.GetEpisodes", params=params)

        if not resp.is_valid("episodes"):
            raise APIError(f"Invalid response while finding episodes for file '{file_path}'")

        return self._parse_ep_details(resp.result["episodes"])

    def get_episodes_from_dir(self, series_dir: str) -> list[EpisodeDetails]:
        """Get all episodes given a directory"""
        params = {
            "properties": self.EP_PROPERTIES,
            "filter": {"operator": "startswith", "field": "path", "value": series_dir},
        }

        resp = self._req("VideoLibrary.GetEpisodes", params=params)

        if not resp.is_valid("episodes"):
            raise APIError(f"Invalid response while finding episodes for directory '{series_dir}'")

        return self._parse_ep_details(resp.result["episodes"])

    def get_shows_from_dir(self, directory: str) -> list[ShowDetails]:
        """Get list of shows within a directory"""
        params = {
            "properties": self.SHOW_PROPERTIES,
            "filter": {"operator": "startswith", "field": "path", "value": directory},
        }

        resp = self._req("VideoLibrary.GetTVShows", params=params)

        if not resp.is_valid("tvshows"):
            raise APIError(f"Invalid response while finding shows for directory '{directory}'")

        return self._parse_show_details(resp.result["tvshows"])

    def get_episode_from_id(self, episode_id: int) -> EpisodeDetails:
        """Get details of a specific episode"""
        params = {"episodeid": episode_id, "properties": self.EP_PROPERTIES}
        resp = self._req("VideoLibrary.GetEpisodeDetails", params=params)

        if not resp.is_valid("episodedetails"):
            raise APIError(f"Invalid response while finding episode details for id: {episode_id}")

        ep_details_lst = self._parse_ep_details([resp.result["episodedetails"]])
        if len(ep_details_lst) == 1:
            return ep_details_lst[0]

        return None

    def scan_series_dir(self, directory: str) -> list[EpisodeDetails]:
        """Scan a directory returning new episodes"""
        # Ensure trailing slash
        directory = directory.rstrip("/") + "/"
        params = {"directory": directory, "showdialogs": False}

        # Get episodes currently in the library
        self.log.debug("Getting Episodes Before scan")
        try:
            old_episodes = self.get_episodes_from_dir(directory)
        except APIError:
            old_episodes = []

        # Scan the Directory
        self.log.debug("Scanning %s", directory)
        resp = self._req("VideoLibrary.Scan", params=params)
        if not resp.is_valid("OK"):
            raise APIError("Invalid Response")

        # Wait for library to scan
        self.log.debug("Waiting for scan to complete.")
        self._wait_for_video_scan()
        self.library_scanned = True

        # Build list of episodes added
        try:
            new_episodes = self.get_episodes_from_dir(directory)
            return [x for x in new_episodes if x not in old_episodes]
        except APIError:
            return []

    def scan_show_library(self) -> None:
        """Scan all sources which contain shows, fall back to all video library"""
        try:
            show_sources = self._get_show_sources()
        except APIError:
            show_sources = []

        for show in show_sources:
            self.log.info("Scanning source %s", show.file)
            show_dir = show.file.rstrip("/") + "/"
            params = {"showdialogs": False, "directory": show_dir}
            resp = self._req("VideoLibrary.Scan", params=params)
            if not resp.is_valid("OK"):
                self.log.warning("Failed to scan %s", show_dir)
                continue
            self._wait_for_video_scan()
            self.library_scanned = True

        if len(show_sources) < 1:
            self.log.warning("No sources contain shows, falling back to full scan.")
            params = {"showdialogs": False}
            resp = self._req("VideoLibrary.Scan", params=params)
            self._wait_for_video_scan()
            if not resp.is_valid("OK"):
                self.log.warning("Failed to scan video library")
                return
            self.library_scanned = True

    def clean_video_library(self) -> None:
        """Clean Video Library"""
        self.log.info("Cleaning TVShow Library.")
        params = {"showdialogs": False, "content": "tvshows"}
        resp = self._req("VideoLibrary.Clean", params=params, timeout=1800)
        if not resp.is_valid("OK"):
            raise APIError("Failed to clean video Library.")

    def remove_episode(self, episode_id: int) -> EpisodeDetails:
        """Remove an episode from library and return it's details"""
        ep_details = self.get_episode_from_id(episode_id)
        params = {"episodeid": episode_id}
        resp = self._req("VideoLibrary.RemoveEpisode", params=params)

        if not resp.is_valid("OK"):
            raise APIError(f"Failed to remove episode id: {episode_id}")

        self.library_scanned = True

        return ep_details

    def _wait_for_video_scan(self) -> None:
        """Wait for video scan to complete"""
        delay = 0.25
        max_time_sec = 1800  # 30 Min
        start = datetime.now()
        while True:
            elapsed = datetime.now() - start

            if not self.is_scanning:
                return

            if elapsed.total_seconds() >= max_time_sec:
                raise ScanTimeout  # (elapsed, waited for)

            # Pause execution to prevent api saturation
            sleep(delay)

    def update_gui(self) -> None:
        """Update GUI|Widgets by scanning a non existent path"""
        params = {"directory": "/does_not_exist/", "showdialogs": False}
        resp = self._req("VideoLibrary.Scan", params=params)
        if not resp.is_valid("OK"):
            self.log.info("Failed to update GUI.")

    def notify(self, msg: str, title: str) -> None:
        """Send GUI Notification to Kodi Host"""
        params = {
            "title": str(title),
            "message": str(msg),
            "displaytime": 5000,
            "image": "https://github.com/jsaddiction/KodiLibrarian/raw/main/img/Sonarr.png",
        }
        resp = self._req("GUI.ShowNotification", params)
        if not resp.is_valid("OK"):
            self.log.warning("Failed to send notification")
            return
