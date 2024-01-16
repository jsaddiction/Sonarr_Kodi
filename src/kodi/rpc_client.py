"""Kodi JSON-RPC Interface"""

# import os
import json
import logging
from time import sleep
from datetime import datetime
from pathlib import PurePosixPath, PureWindowsPath
import requests

from .config import HostConfig
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


class KodiRPC:
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
    SHOW_PROPERTIES = ["title", "file", "year"]

    def __init__(self, cfg: HostConfig) -> None:
        self.log = logging.getLogger(f"RPC_Client.{cfg.name}")
        self.base_url = f"http://{cfg.ip_addr}:{cfg.port}/jsonrpc"
        self.name = cfg.name
        self.credentials = cfg.credentials
        self.enabled = cfg.enabled
        self.disable_notifications = cfg.disable_notifications
        self.priority = cfg.priority
        self.path_maps = cfg.path_maps
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
                ShowDetails(
                    show_id=KodiRPC._to_int(show["tvshowid"]),
                    file=show["file"],
                    title=show["title"],
                    year=KodiRPC._to_int(show["year"]),
                )
            )
        return show_details_lst

    @staticmethod
    def _parse_ep_details(episodes: list[dict]) -> list[EpisodeDetails]:
        ep_details_lst = []
        for episode in episodes:
            ep_details_lst.append(
                EpisodeDetails(
                    episode_id=KodiRPC._to_int(episode["episodeid"]),
                    show_id=KodiRPC._to_int(episode["tvshowid"]),
                    file=episode["file"],
                    show_title=episode["showtitle"],
                    episode_title=episode["title"],
                    season=KodiRPC._to_int(episode["season"]),
                    episode=KodiRPC._to_int(episode["episode"]),
                    watched_state=WatchedState(
                        play_count=KodiRPC._to_int(episode["playcount"]),
                        date_added=KodiRPC._to_dt(episode["dateadded"]),
                        last_played=KodiRPC._to_dt(episode["lastplayed"]),
                        resume=ResumeState(
                            position=KodiRPC._to_float(episode["resume"]["position"]),
                            total=KodiRPC._to_float(episode["resume"]["total"]),
                        ),
                    ),
                )
            )
        return ep_details_lst

    def _map_path(self, path: str) -> str:
        """Map external paths to configured kodi path"""
        out_str = path
        for path_map in self.path_maps:
            if path_map.sonarr in path:
                out_str = path.replace(path_map.sonarr, path_map.kodi)

        if self.is_posix:
            return str(PurePosixPath(out_str))

        return str(PureWindowsPath(out_str))

    def _get_filename_from_path(self, path: str) -> str:
        """Extract filename from path based on os type"""
        if self.is_posix:
            return str(PurePosixPath(path).name)
        return str(PureWindowsPath(path).name)

    def _get_dirname_from_path(self, path: str) -> str:
        """Extract dir name from path based on os type"""
        if self.is_posix:
            return str(PurePosixPath(path).parent)
        return str(PureWindowsPath(path).parent)

    # used local only
    def _wait_for_video_scan(self) -> None:
        """Wait for video scan to complete"""
        delay = 0.25
        max_time_sec = 1800  # 30 Min
        start = datetime.now()
        self.log.debug("Waiting up to %s minuets for library scan to complete", max_time_sec / 60)
        while True:
            elapsed = datetime.now() - start

            if not self.is_scanning:
                return

            if elapsed.total_seconds() >= max_time_sec:
                raise ScanTimeout  # (elapsed, waited for)

            # Pause execution to prevent api saturation
            sleep(delay)

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

        KodiRPC.REQ_ID += 1

        error_data = response.get("error")
        error = KodiResponseError(**error_data) if error_data else None

        return KodiResponse(
            req_id=response.get("id"),
            jsonrpc=response.get("jsonrpc"),
            result=response.get("result"),
            error=error,
        )

    # --------------- Global Methods -----------------

    # used remote only
    def scan_series_dir(self, directory: str) -> None:
        """Scan a directory"""
        # Ensure trailing slash
        mapped_path = self._map_path(directory)
        mapped_path = mapped_path.rstrip("/") + "/"
        params = {"directory": mapped_path, "showdialogs": False}

        # Scan the Directory
        self.log.debug("Scanning %s using mapped path %s", directory, mapped_path)
        resp = self._req("VideoLibrary.Scan", params=params)
        if not resp.is_valid("OK"):
            raise APIError(f"Invalid Response While Scanning {directory}")

        # Wait for library to scan
        self._wait_for_video_scan()
        self.library_scanned = True

    # used remote only
    def full_video_scan(self) -> None:
        """Perform full video library scan"""
        params = {"showdialogs": False}
        self.log.debug("Performing full video library scan")
        resp = self._req("VideoLibrary.Scan", params=params)
        if not resp.is_valid("OK"):
            raise APIError("Failed to scan full library")
        self._wait_for_video_scan()
        self.library_scanned = True

    # not used yet
    def clean_video_library(self) -> None:
        """Clean Video Library"""
        params = {"showdialogs": False, "content": "tvshows"}

        self.log.debug("Cleaning tvshow library")
        resp = self._req("VideoLibrary.Clean", params=params, timeout=1800)

        if not resp.is_valid("OK"):
            raise APIError("Failed to clean video Library.")

        # Wait for cleaning to complete
        self._wait_for_video_scan()
        self.library_scanned = True

    # used remote only
    def get_show_sources(self) -> list[Source]:
        """Get all sources which contain at least one episode of a Tv Show"""
        params = {"media": "video"}
        self.log.debug("Getting all sources")
        resp = self._req("Files.GetSources", params=params)

        if not resp.is_valid("sources"):
            raise APIError("Invalid response while collecting sources")

        return [Source(**x) for x in resp.result["sources"]]

    # used remote only
    def update_gui(self) -> None:
        """Update GUI|Widgets by scanning a non existent path"""
        if self.library_scanned:
            self.log.info("GUI update not required, Skipping.")
            return

        params = {"directory": "/does_not_exist/", "showdialogs": False}
        self.log.debug("Updating GUI")
        resp = self._req("VideoLibrary.Scan", params=params)
        if not resp.is_valid("OK"):
            self.log.info("Failed to update GUI.")

    # used remote only
    def notify(self, msg: str, title: str) -> None:
        """Send GUI Notification to Kodi Host"""
        if self.disable_notifications:
            self.log.info("Notifications disabled. Skipping")
            return
        params = {
            "title": str(title),
            "message": str(msg),
            "displaytime": 5000,
            "image": "https://github.com/jsaddiction/KodiLibrarian/raw/main/img/Sonarr.png",
        }
        self.log.debug("Sending notification :: TITLE='%s' MSG='%s'", title, msg)
        resp = self._req("GUI.ShowNotification", params)
        if not resp.is_valid("OK"):
            self.log.warning("Failed to send notification")
            return

    # ----------------- Episode Methods ---------------

    # used remote only
    def set_episode_watched_state(self, episode: EpisodeDetails, new_ep_id: int) -> None:
        """Set Episode Watched State"""
        self.log.debug("Setting watched state %s on %s", episode.watched_state, episode)
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

    # used remote only
    def get_all_episodes(self) -> list[EpisodeDetails]:
        """Get all episodes in library, waits upto a minuet for response"""
        self.log.debug("Getting all episodes")
        params = {"properties": self.EP_PROPERTIES}
        resp = self._req("VideoLibrary.GetEpisodes", params=params, timeout=60)

        if not resp.is_valid("episodes"):
            raise APIError("Invalid response while getting all episodes")

        return self._parse_ep_details(resp.result["episodes"])

    # used remote only, Path mapped
    def get_episodes_from_file(self, file_path: str) -> list[EpisodeDetails]:
        """Get details of episodes given a file_path"""
        mapped_path = self._map_path(file_path)
        file_name = self._get_filename_from_path(mapped_path)
        file_dir = self._get_dirname_from_path(mapped_path)
        params = {
            "properties": self.EP_PROPERTIES,
            "filter": {
                "and": [
                    {"operator": "startswith", "field": "path", "value": file_dir},
                    {"operator": "is", "field": "filename", "value": file_name},
                ]
            },
        }

        self.log.debug("Getting all episodes from file %s using mapped path %s", file_path, mapped_path)
        resp = self._req("VideoLibrary.GetEpisodes", params=params)

        if not resp.is_valid("episodes"):
            self.log.warning("Failed to get episodes from %s", mapped_path)
            raise APIError(f"Invalid response while finding episodes for file '{mapped_path}'")

        return self._parse_ep_details(resp.result["episodes"])

    # used remote only
    def get_episodes_from_dir(self, series_dir: str) -> list[EpisodeDetails]:
        """Get all episodes given a directory"""
        mapped_path = self._map_path(series_dir)
        params = {
            "properties": self.EP_PROPERTIES,
            "filter": {"operator": "startswith", "field": "path", "value": mapped_path},
        }

        self.log.debug("Getting all episodes in %s using mapped path %s", series_dir, mapped_path)
        resp = self._req("VideoLibrary.GetEpisodes", params=params)

        if not resp.is_valid("episodes"):
            raise APIError(f"Invalid response while finding episodes for directory '{series_dir}'")

        return self._parse_ep_details(resp.result["episodes"])

    # used remote only
    def get_episode_from_id(self, episode_id: int) -> EpisodeDetails:
        """Get details of a specific episode"""
        params = {"episodeid": episode_id, "properties": self.EP_PROPERTIES}
        self.log.debug("Getting episode details with episode id %s", episode_id)
        resp = self._req("VideoLibrary.GetEpisodeDetails", params=params)

        if not resp.is_valid("episodedetails"):
            raise APIError(f"Invalid response while finding episode details for id: {episode_id}")

        ep_details_lst = self._parse_ep_details([resp.result["episodedetails"]])
        if len(ep_details_lst) == 1:
            return ep_details_lst[0]

        return None

    # used remote only
    def remove_episode(self, episode_id: int) -> None:
        """Remove an episode from library and return it's details"""
        params = {"episodeid": episode_id}
        self.log.debug("Removing episode with episode id %s", episode_id)
        resp = self._req("VideoLibrary.RemoveEpisode", params=params)

        if not resp.is_valid("OK"):
            raise APIError(f"Failed to remove episode id: {episode_id}")

        self.library_scanned = True

    # ------------------ Show Methods ------------------

    # used remote only
    def remove_tvshow(self, show_id: int) -> ShowDetails:
        """Remove a TV Show from library and return it's details"""
        show_details = self.get_show_from_id(show_id)
        params = {"tvshowid": show_details.show_id}
        self.log.debug("Removing TV Show with tvshowid %s", show_id)
        resp = self._req("VideoLibrary.RemoveTVShow", params=params)

        if not resp.is_valid("OK"):
            raise APIError(f"Failed to remove TVShow id: {show_id}")

        self.library_scanned = True

        return show_details

    # used remote only
    def get_shows_from_dir(self, directory: str) -> list[ShowDetails]:
        """Get list of shows within a directory"""
        mapped_path = self._map_path(directory)
        params = {
            "properties": self.SHOW_PROPERTIES,
            "filter": {"operator": "startswith", "field": "path", "value": mapped_path},
        }

        self.log.debug("Getting shows in %s using mapped path %s", directory, mapped_path)
        resp = self._req("VideoLibrary.GetTVShows", params=params)

        if not resp.is_valid("tvshows"):
            raise APIError(f"Invalid response while finding shows for directory '{directory}'")

        return self._parse_show_details(resp.result["tvshows"])

    # used local only
    def get_show_from_id(self, show_id: int) -> ShowDetails:
        """Get details of a specific TV Show"""
        params = {"tvshowid": show_id, "properties": self.SHOW_PROPERTIES}
        self.log.debug("Getting show details with tvshowid %s", show_id)
        resp = self._req("VideoLibrary.GetTVShowDetails", params=params)

        if not resp.is_valid("tvshowdetails"):
            raise APIError(f"Invalid response while finding TV Show details for id: {show_id}")

        show_details_lst = self._parse_show_details([resp.result["tvshowdetails"]])
        if len(show_details_lst) == 1:
            return show_details_lst[0]

        return None
