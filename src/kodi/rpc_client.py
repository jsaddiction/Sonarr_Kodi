"""Kodi JSON-RPC Interface"""

# import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import PurePosixPath, PureWindowsPath
import requests

from .config import HostConfig
from .exceptions import APIError, ScanTimeout
from .models import (
    RPCVersion,
    Platform,
    Notification,
    KodiResponse,
    WatchedState,
    ResumeState,
    EpisodeDetails,
    ShowDetails,
    Player,
    PlayerItem,
    EP_PROPERTIES,
    SHOW_PROPERTIES,
)


class KodiRPC:
    """Kodi JSON-RPC Client"""

    RETRIES = 3
    TIMEOUT = 5
    REQ_ID = 0
    HEADERS = {"Content-Type": "application/json", "Accept": "plain/text"}

    def __init__(self, cfg: HostConfig) -> None:
        self.log = logging.getLogger(f"Kodi.{cfg.name}")
        self.base_url = f"http://{cfg.ip_addr}:{cfg.port}/jsonrpc"
        self.name = cfg.name
        self.credentials = cfg.credentials
        self.enabled = cfg.enabled
        self.disable_notifications = cfg.disable_notifications
        self.priority = cfg.priority
        self.path_maps = cfg.path_maps
        self.library_scanned = False
        self.platform: Platform = None

    def __str__(self) -> str:
        return f"{self.name} JSON-RPC({self.rpc_version})"

    @property
    def rpc_version(self) -> RPCVersion | None:
        """Return JSON-RPC Version of host"""
        try:
            resp = self._req("JSONRPC.Version")
        except APIError as e:
            self.log.warning("Failed to get JSON-RPC Version. Error: %s", e)
            return None

        return RPCVersion(
            major=resp.result["version"].get("major"),
            minor=resp.result["version"].get("minor"),
            patch=resp.result["version"].get("patch"),
        )

    @property
    def is_alive(self) -> bool:
        """Return True if Kodi Host is responsive"""
        try:
            resp = self._req("JSONRPC.Ping")
        except APIError as e:
            self.log.warning("Failed to ping host. Error: %s", e)
            return False

        return resp.result == "pong"

    @property
    def is_playing(self) -> bool:
        """Return True if Kodi Host is currently playing content"""
        return bool(self.active_players)

    @property
    def active_players(self) -> list[Player]:
        """Get a list of active players"""
        try:
            resp = self._req("Player.GetActivePlayers")
        except APIError as e:
            self.log.warning("Failed to get active players. Error: %s", e)
            return []

        active_players: list[Player] = []
        for active_player in resp.result:
            active_players.append(
                Player(
                    player_id=active_player["playerid"],
                    player_type=active_player["playertype"],
                    type=active_player["type"],
                )
            )

        return active_players

    @property
    def is_scanning(self) -> bool:
        """True if a library scan is in progress"""
        params = {"booleans": ["Library.IsScanning"]}
        try:
            resp = self._req("XBMC.GetInfoBooleans", params=params)
        except APIError as e:
            self.log.warning("Failed to determine scanning state. Error: %s", e)
            return False

        return resp.result["Library.IsScanning"]

    @property
    def is_posix(self) -> bool:
        """If this host uses posix file naming conventions"""
        return self.platform not in [Platform.WINDOWS, Platform.UNKNOWN]

    @staticmethod
    def _to_dt(dt_str: str) -> datetime | None:
        try:
            return datetime.fromisoformat(dt_str)
        except ValueError:
            return None

    @staticmethod
    def _parse_show_details(show_data: dict) -> ShowDetails:
        try:
            return ShowDetails(
                show_id=show_data.get("tvshowid"),
                file=show_data.get("file"),
                title=show_data.get("title"),
                year=show_data.get("year"),
            )
        except KeyError:
            return None

    @staticmethod
    def _parse_ep_details(episode_data: dict) -> EpisodeDetails | None:
        try:
            return EpisodeDetails(
                episode_id=episode_data["episodeid"],
                show_id=episode_data["tvshowid"],
                file=episode_data["file"],
                show_title=episode_data["showtitle"],
                episode_title=episode_data["title"],
                season=episode_data["season"],
                episode=episode_data["episode"],
                watched_state=WatchedState(
                    play_count=episode_data["playcount"],
                    date_added=KodiRPC._to_dt(episode_data["dateadded"]),
                    last_played=KodiRPC._to_dt(episode_data["lastplayed"]),
                    resume=ResumeState(
                        position=episode_data["resume"]["position"],
                        total=episode_data["resume"]["total"],
                    ),
                ),
            )
        except KeyError:
            return None

    # --------------- Helper Methods -----------------
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

    def _wait_for_video_scan(self, max_secs: int = 1800) -> timedelta:
        """Wait for video scan to complete"""
        # Default timeout = 30 Min
        start = datetime.now()
        self.log.debug("Waiting up to %s minuets for library scan to complete", max_secs / 60)
        while True:
            elapsed = datetime.now() - start

            # Check if scanning, may raise APIError if failed to communicate
            if not self.is_scanning:
                return elapsed

            if elapsed.total_seconds() >= max_secs:
                raise ScanTimeout(f"Waited for {elapsed}. Giving up.")

    def _req(self, method: str, params: dict = None, timeout: int = None) -> KodiResponse | None:
        """Send request to this Kodi Host"""
        req_params = {"jsonrpc": "2.0", "id": self.REQ_ID, "method": method}
        if params:
            req_params["params"] = params
        response = None
        try:
            resp = requests.post(
                url=self.base_url,
                data=json.dumps(req_params).encode("utf-8"),
                headers=self.HEADERS,
                auth=self.credentials,
                timeout=timeout or self.TIMEOUT,
            )
            resp.raise_for_status()
            response = resp.json()
        except requests.Timeout as e:
            raise APIError(f"Request timed out after {timeout}s") from e
        except requests.HTTPError as e:
            if resp.status_code == 401:
                raise APIError("HTTP Error. Unauthorized. Check Credentials") from e
            raise APIError(f"HTTP Error. Error: {e}") from e
        except requests.ConnectionError as e:
            raise APIError(f"Connection Error. {e}") from e
        finally:
            KodiRPC.REQ_ID += 1

        if "error" in response:
            raise APIError(response.get("error"))

        return KodiResponse(
            req_id=response.get("id"),
            jsonrpc=response.get("jsonrpc"),
            result=response.get("result"),
        )

    # --------------- System Methods -----------------
    def get_platform(self) -> Platform:
        """Get platform of this client"""
        if self.platform:
            return self.platform

        params = {"booleans": [x.value for x in Platform]}
        try:
            resp = self._req("XBMC.GetInfoBooleans", params=params)
        except APIError as e:
            self.log.warning("Failed to get platform info. Error: %s", e)
            return Platform.UNKNOWN

        for k, v in resp.result.items():
            if v:
                return Platform(k)
        return Platform.UNKNOWN

    # --------------- UI Methods ---------------------
    def update_gui(self) -> None:
        """Update GUI|Widgets by scanning a non existent path"""
        params = {"directory": "/does_not_exist/", "showdialogs": False}
        self.log.info("Updating GUI")
        try:
            self._req("VideoLibrary.Scan", params=params)
        except APIError as e:
            self.log.warning("Failed to update GUI. Error: %s", e)

    def notify(self, notification: Notification, force: bool = False) -> None:
        """Send GUI Notification to Kodi Host"""
        if self.disable_notifications and not force:
            self.log.debug("All Host GUI Notifications disabled. Skipping.")
            return

        params = {
            "title": str(notification.title),
            "message": str(notification.msg),
            "displaytime": int(notification.display_time),
            "image": notification.image,
        }
        self.log.info("Sending GUI Notification :: %s", notification)
        try:
            self._req("GUI.ShowNotification", params=params)
        except APIError as e:
            self.log.warning("Failed to send notification. Error: %s", e)

    # --------------- Player Methods -----------------
    def is_paused(self, player_id: int) -> bool:
        """Return True if player is currently paused"""
        # If player is stopped, speed is 0 (paused). Check for playing first.
        if not self.is_playing:
            return False

        params = {"playerid": player_id, "properties": ["speed"]}
        try:
            resp = self._req("Player.GetProperties", params=params)
        except APIError as e:
            self.log.warning("Failed to determine paused state of player. Error: %s", e)
            return False

        return int(resp.result["speed"]) == 0

    def player_percent(self, player_id: int) -> float:
        """Return Position of player in percent complete"""
        params = {"playerid": player_id, "properties": ["percentage"]}
        try:
            resp = self._req("Player.GetProperties", params=params)
        except APIError as e:
            self.log.warning("Failed to get player position. Error: %s", e)
            return 0.0

        return resp.result["percentage"]

    def get_player_item(self, player_id: int) -> PlayerItem | None:
        """Get items a given player is playing"""
        params = {"playerid": player_id}
        try:
            resp = self._req("Player.GetItem", params=params)
        except APIError as e:
            self.log.warning("Failed to get player item. Error: %s", e)
            return None

        try:
            return PlayerItem(
                item_id=resp.result["item"]["id"],
                label=resp.result["item"]["label"],
                type=resp.result["item"]["type"],
            )
        except KeyError:
            return None

    def pause_player(self, player_id: int) -> None:
        """Pauses a player"""
        params = {"playerid": player_id}
        while True:
            try:
                resp = self._req("Player.PlayPause", params=params)
            except APIError as e:
                self.log.warning("Failed to pause player. Error: %s", e)
                return

            if resp.result["speed"] == 0:
                return

    def stop_player(self, player_id: int) -> None:
        """Stops a player"""
        params = {"playerid": player_id}
        try:
            self._req("Player.Stop", params=params)
        except APIError as e:
            self.log.warning("Failed to stop player. Error: %s", e)

    def start_episode(self, episode_id: int, position: float) -> Player | None:
        """Play a given episode"""
        self.log.info("Restarting Episode %s", episode_id)
        params = {"item": {"episodeid": episode_id}, "options": {"resume": position}}
        try:
            self._req("Player.Open", params=params)
        except APIError as e:
            self.log.warning("Failed to start episode. Error: %s", e)
            return None

        # Wait for player to start
        start = datetime.now()
        while True:
            for player in self.active_players:
                item = self.get_player_item(player.player_id)
                if item and item.type == "episode" and item.item_id == episode_id:
                    return player

            # Break out if time limit exceeded
            if (datetime.now() - start).total_seconds() > 5:
                self.log.warning("Episode failed to start after 5 second. Giving up.")
                return None

    # --------------- Library Methods ----------------
    def scan_series_dir(self, directory: str) -> bool:
        """Scan a directory"""
        # Ensure trailing slash
        mapped_path = self._map_path(directory)
        mapped_path = mapped_path.rstrip("/") + "/"
        params = {"directory": mapped_path, "showdialogs": False}

        # Scan the Directory
        self.log.info("Scanning directory '%s'", mapped_path)
        try:
            self._req("VideoLibrary.Scan", params=params)
        except APIError as e:
            self.log.warning("Failed to scan %s. Error: %s", mapped_path, e)
            return False

        # Wait for library to scan
        try:
            elapsed = self._wait_for_video_scan(max_secs=120)
        except ScanTimeout as e:
            self.log.warning("Scan timed out. Error: %s", e)
            return False

        self.log.info("Scan completed in %s", elapsed)
        self.library_scanned = True
        return True

    def full_video_scan(self) -> bool:
        """Perform full video library scan"""
        params = {"showdialogs": False}
        self.log.info("Performing full library scan")
        try:
            self._req("VideoLibrary.Scan", params=params)
        except APIError as e:
            self.log.warning("Failed to scan full library. Error: %s", e)
            return False

        try:
            elapsed = self._wait_for_video_scan()
        except ScanTimeout as e:
            self.log.warning("Scan timed out. Error: %s", e)
            return False

        self.log.info("Scan completed in %s", elapsed)
        self.library_scanned = True
        return True

    def clean_video_library(self) -> bool:
        """Clean Video Library"""
        # Passing a series_dir does not initiate clean. With or without trailing '/'
        # Preferably, should set {'directory': series_dir} vice {'content': 'tvshows'}
        params = {"showdialogs": False, "content": "tvshows"}

        self.log.info("Cleaning tvshows library.")
        try:
            self._req("VideoLibrary.Clean", params=params)
        except APIError as e:
            self.log.warning("Failed to clean library. Error: %s", e)
            return False

        # Wait for cleaning to complete
        try:
            elapsed = self._wait_for_video_scan(max_secs=300)
        except ScanTimeout as e:
            self.log.warning("Library Clean timed out. Error: %s", e)
            return False

        self.log.info("Library Clean completed in %s", elapsed)
        self.library_scanned = True
        return True

    # ----------------- Episode Methods ---------------
    def set_episode_watched_state(self, episode: EpisodeDetails, new_ep_id: int) -> bool:
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

        try:
            self._req("VideoLibrary.SetEpisodeDetails", params=params)
        except APIError as e:
            self.log.warning("Failed to set episode metadata. Error: %s", e)
            return False

        return True

    def get_all_episodes(self) -> list[EpisodeDetails]:
        """Get all episodes in library, waits upto a minuet for response"""
        self.log.debug("Getting all episodes")
        params = {"properties": EP_PROPERTIES}
        try:
            resp = self._req("VideoLibrary.GetEpisodes", params=params, timeout=60)
        except APIError as e:
            self.log.warning("Failed to get all episodes. Error: %s", e)
            return []

        return [self._parse_ep_details(x) for x in resp.result["episodes"]]

    def get_episodes_from_file(self, file_path: str) -> list[EpisodeDetails]:
        """Get details of episodes given a file_path"""
        mapped_path = self._map_path(file_path)
        file_name = self._get_filename_from_path(mapped_path)
        file_dir = self._get_dirname_from_path(mapped_path)
        params = {
            "properties": EP_PROPERTIES,
            "filter": {
                "and": [
                    {"operator": "startswith", "field": "path", "value": file_dir},
                    {"operator": "is", "field": "filename", "value": file_name},
                ]
            },
        }

        self.log.debug("Getting all episodes from path %s", mapped_path)
        try:
            resp = self._req("VideoLibrary.GetEpisodes", params=params)
        except APIError as e:
            self.log.warning("Failed to get episodes from file '%s'. Error: %s", mapped_path, e)
            return []

        return [self._parse_ep_details(x) for x in resp.result["episodes"]]

    def get_episodes_from_dir(self, series_dir: str) -> list[EpisodeDetails]:
        """Get all episodes given a directory"""
        mapped_path = self._map_path(series_dir)
        params = {
            "properties": EP_PROPERTIES,
            "filter": {"operator": "startswith", "field": "path", "value": mapped_path},
        }

        self.log.debug("Getting all episodes in %s", mapped_path)
        try:
            resp = self._req("VideoLibrary.GetEpisodes", params=params)
        except APIError as e:
            self.log.warning("Failed to get episodes from directory '%s'. Error: %s", mapped_path, e)
            return []

        return [self._parse_ep_details(x) for x in resp.result["episodes"]]

    def get_episode_from_id(self, episode_id: int) -> EpisodeDetails | None:
        """Get details of a specific episode"""
        params = {"episodeid": episode_id, "properties": EP_PROPERTIES}
        self.log.debug("Getting episode details with episode id %s", episode_id)
        try:
            resp = self._req("VideoLibrary.GetEpisodeDetails", params=params)
        except APIError as e:
            self.log.warning("Failed to get episode from id '%s'. Error: %s", episode_id, e)
            return None

        return self._parse_ep_details(resp.result["episodedetails"])

    def remove_episode(self, episode_id: int) -> bool:
        """Remove an episode from library and return it's details"""
        params = {"episodeid": episode_id}
        self.log.debug("Removing episode with episode id %s", episode_id)
        try:
            self._req("VideoLibrary.RemoveEpisode", params=params)
        except APIError as e:
            self.log.warning("Failed to remove episode by id '%s'. Error: %s", episode_id, e)
            return False

        self.library_scanned = True
        return True

    # ------------------ Show Methods ------------------
    def remove_tvshow(self, show_id: int) -> ShowDetails | None:
        """Remove a TV Show from library and return it's details"""
        show_details = self.get_show_from_id(show_id)
        if not show_details:
            return None

        params = {"tvshowid": show_details.show_id}
        self.log.debug("Removing TV Show with tvshowid %s", show_id)
        try:
            self._req("VideoLibrary.RemoveTVShow", params=params)
        except APIError as e:
            self.log.warning("Failed to remove tvshow by id '%s'. Error: %s", show_id, e)
            return None

        self.library_scanned = True

        return show_details

    def get_shows_from_dir(self, directory: str) -> list[ShowDetails]:
        """Get list of shows within a directory"""
        mapped_path = self._map_path(directory)
        params = {
            "properties": SHOW_PROPERTIES,
            "filter": {"operator": "startswith", "field": "path", "value": mapped_path},
        }

        self.log.debug("Getting shows in %s", mapped_path)
        try:
            resp = self._req("VideoLibrary.GetTVShows", params=params)
        except APIError as e:
            self.log.warning("Failed to get shows from directory '%s'. Error: %s", mapped_path, e)
            return []

        return [self._parse_show_details(x) for x in resp.result.get("tvshows")]

    def get_show_from_id(self, show_id: int) -> ShowDetails | None:
        """Get details of a specific TV Show"""
        params = {"tvshowid": show_id, "properties": SHOW_PROPERTIES}
        self.log.debug("Getting show details with tvshowid %s", show_id)
        try:
            resp = self._req("VideoLibrary.GetTVShowDetails", params=params)
        except APIError as e:
            self.log.warning("Failed to get show from id '%s'. Error: %s", show_id, e)
            return None

        return self._parse_show_details(resp.result.get("tvshowdetails"))
