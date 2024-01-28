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
    Platform,
    Notification,
    KodiResponse,
    KodiResponseError,
    WatchedState,
    ResumeState,
    EpisodeDetails,
    ShowDetails,
    Source,
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
        self.stopped_episode: EpisodeDetails = None
        self.stopped_episode_position: float = None

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
        return len(self._get_active_players()) > 0

    @property
    def is_scanning(self) -> bool:
        """True if a library scan is in progress"""
        params = {"booleans": ["Library.IsScanning"]}
        resp = self._req("XBMC.GetInfoBooleans", params=params)
        if not resp.is_valid():
            raise APIError("Failed to determine library scanning state.")

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
    def _parse_response_error(error: dict) -> KodiResponseError | None:
        """Parse error data into dataclass"""
        if not error:
            return None
        error_data = error.get("data")
        stack_data = error_data.get("stack")
        stack_data_property = stack_data.get("property")
        return KodiResponseError(
            code=error.get("code"),
            message=error.get("message"),
            method=error_data.get("method"),
            stack_message=stack_data.get("message"),
            stack_name=stack_data.get("name"),
            stack_type=stack_data.get("type"),
            stack_property_message=stack_data_property.get("message"),
            stack_property_type=stack_data_property.get("type"),
        )

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
                            position=KodiRPC._to_int(episode["resume"]["position"]),
                            total=KodiRPC._to_int(episode["resume"]["total"]),
                        ),
                    ),
                )
            )
        return ep_details_lst

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

    def _get_active_players(self) -> list[Player]:
        """Get a list of player ids that are playing a file"""
        active_players: list[Player] = []

        resp = self._req("Player.GetActivePlayers")
        if not resp.is_valid():
            return active_players

        for active_player in resp.result:
            active_players.append(
                Player(
                    player_id=active_player["playerid"],
                    player_type=active_player["playertype"],
                    type=active_player["type"],
                )
            )

        return active_players

    def _get_player_item(self, player_id: int) -> PlayerItem | None:
        """Get items a given player is playing"""
        params = {"playerid": player_id}
        resp = self._req("Player.GetItem", params=params)
        if not resp.is_valid("item"):
            self.log.warning("Failed to get player item. Error: %s", resp.error)
            return None

        data = resp.result["item"]
        return PlayerItem(
            item_id=data["id"],
            label=data["label"],
            type=data["type"],
        )

    def _get_player_position(self, player_id: int) -> float:
        """Get current position of an active player"""
        params = {"playerid": player_id, "properties": ["percentage"]}
        resp = self._req("Player.GetProperties", params=params)
        if not resp.is_valid("percentage"):
            raise APIError(f"Failed to get player position. Error: {resp.error}")

        return resp.result["percentage"]

    def _stop_player(self, player_id: int) -> None:
        """Stops an active player"""
        params = {"playerid": player_id}
        resp = self._req("Player.Stop", params=params)
        if not resp.is_valid("OK"):
            raise APIError(f"Failed to stop the active player. Error: {resp.error}")

    def _wait_for_video_scan(self) -> timedelta:
        """Wait for video scan to complete"""
        max_time_sec = 1800  # 30 Min
        start = datetime.now()
        self.log.debug("Waiting up to %s minuets for library scan to complete", max_time_sec / 60)
        while True:
            elapsed = datetime.now() - start

            # Check if scanning, may raise APIError if failed to communicate
            if not self.is_scanning:
                return elapsed

            if elapsed.total_seconds() >= max_time_sec:
                raise ScanTimeout(f"Scan timed out after {elapsed}")

    def _set_resume_state(self, resume: ResumeState, episode_id: int) -> None:
        """Set episode resume state"""
        self.log.debug("Setting resume point %s on episode %s", resume, episode_id)
        params = {
            "episodeid": episode_id,
            "resume": {
                "position": resume.position,
                "total": resume.total,
            },
        }
        resp = self._req("VideoLibrary.SetEpisodeDetails", params=params)

        if not resp.is_valid("OK"):
            raise APIError(f"Invalid response while setting resume point. Error: {resp.error}")

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

        return KodiResponse(
            req_id=response.get("id"),
            jsonrpc=response.get("jsonrpc"),
            result=response.get("result"),
            error=self._parse_response_error(response.get("error")),
        )

    # --------------- System Methods -----------------
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

    # --------------- UI Methods ---------------------
    def update_gui(self) -> None:
        """Update GUI|Widgets by scanning a non existent path"""
        if self.library_scanned:
            self.log.info("Library Scanned. GUI update not required, Skipping.")
            return

        params = {"directory": "/does_not_exist/", "showdialogs": False}
        self.log.debug("Updating GUI")
        resp = self._req("VideoLibrary.Scan", params=params)
        if not resp.is_valid("OK"):
            self.log.info("Failed to update GUI.")

    def notify(self, notification: Notification) -> None:
        """Send GUI Notification to Kodi Host"""
        if self.disable_notifications:
            self.log.debug("Notifications disabled. Skipping")
            return

        params = {
            "title": str(notification.title),
            "message": str(notification.msg),
            "displaytime": int(notification.display_time),
            "image": notification.image,
        }
        self.log.info("Sending GUI Notification :: %s", notification)
        resp = self._req("GUI.ShowNotification", params=params)
        if not resp.is_valid("OK"):
            self.log.warning("Failed to send notification")
            return

    # --------------- Player Methods -----------------
    def stop_episode(self, episode: EpisodeDetails) -> bool:
        """Stops a player if currently playing an episode, return True if item was stopped"""
        for player in self._get_active_players():
            if player.type.lower() != "video":
                continue

            # Get the item playing, skip if not found or not an episode
            item = self._get_player_item(player.player_id)
            if not item or item.type != "episode":
                continue

            # Confirm that the episode is the item being played
            if item.item_id == episode.episode_id:
                self.log.info("Stopping episode %s", episode)
                try:
                    self.stopped_episode_position = self._get_player_position(player.player_id)
                    self.stopped_episode = self.get_episode_from_id(item.item_id)
                    self._stop_player(player.player_id)
                except APIError as e:
                    self.log.warning(e)
                    return False

                return True

        return False

    def start_episode(self, episode: EpisodeDetails) -> None:
        """Play a given episode"""
        # Skip if we don't have a record of a previously stopped episode
        if not self.stopped_episode:
            return

        # Skip if the supplied episode wasn't previously stopped
        if not episode == self.stopped_episode:
            return

        self.log.info("Restarting Episode %s", episode)

        params = {"item": {"episodeid": episode.episode_id}, "options": {"resume": self.stopped_episode_position}}
        resp = self._req("Player.Open", params=params)
        if not resp.is_valid("OK"):
            self.log.warning("Invalid response while starting episode. Error: %s", resp.error)
            return
        self.stopped_episode = None
        self.stopped_episode_position = None

    # --------------- Library Methods ----------------
    def scan_series_dir(self, directory: str) -> None:
        """Scan a directory"""
        # Ensure trailing slash
        mapped_path = self._map_path(directory)
        mapped_path = mapped_path.rstrip("/") + "/"
        params = {"directory": mapped_path, "showdialogs": False}

        # Scan the Directory
        self.log.info("Scanning directory '%s'", mapped_path)
        resp = self._req("VideoLibrary.Scan", params=params)
        if not resp.is_valid("OK"):
            raise APIError(f"Invalid Response While Scanning {directory}. Error: {resp.error}")

        # Wait for library to scan
        elapsed = self._wait_for_video_scan()
        self.log.info("Scan completed in %s", elapsed)
        self.library_scanned = True

    def full_video_scan(self) -> None:
        """Perform full video library scan"""
        params = {"showdialogs": False}
        self.log.debug("Performing full video library scan")
        resp = self._req("VideoLibrary.Scan", params=params)
        if not resp.is_valid("OK"):
            raise APIError(f"Invalid response when attempting full scan. Error: Error: {resp.error}")
        elapsed = self._wait_for_video_scan()
        self.log.info("Scan completed in %s", elapsed)
        self.library_scanned = True

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

    def get_show_sources(self) -> list[Source]:
        """Get all sources which contain at least one episode of a Tv Show"""
        params = {"media": "video"}
        self.log.debug("Getting all sources")
        resp = self._req("Files.GetSources", params=params)

        if not resp.is_valid("sources"):
            raise APIError("Invalid response while collecting sources")

        return [Source(**x) for x in resp.result["sources"]]

    # ----------------- Episode Methods ---------------
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

        if not resp.is_valid("OK"):
            raise APIError("Invalid response while setting watched state.")

    def get_all_episodes(self) -> list[EpisodeDetails]:
        """Get all episodes in library, waits upto a minuet for response"""
        self.log.debug("Getting all episodes")
        params = {"properties": EP_PROPERTIES}
        resp = self._req("VideoLibrary.GetEpisodes", params=params, timeout=60)

        if not resp.is_valid("episodes"):
            raise APIError("Invalid response while getting all episodes")

        return self._parse_ep_details(resp.result["episodes"])

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

        self.log.debug("Getting all episodes from file %s using mapped path %s", file_path, mapped_path)
        resp = self._req("VideoLibrary.GetEpisodes", params=params)

        if not resp.is_valid("episodes"):
            raise APIError(f"Invalid response: {resp}")

        return self._parse_ep_details(resp.result["episodes"])

    def get_episodes_from_dir(self, series_dir: str) -> list[EpisodeDetails]:
        """Get all episodes given a directory"""
        mapped_path = self._map_path(series_dir)
        params = {
            "properties": EP_PROPERTIES,
            "filter": {"operator": "startswith", "field": "path", "value": mapped_path},
        }

        self.log.debug("Getting all episodes in %s using mapped path %s", series_dir, mapped_path)
        resp = self._req("VideoLibrary.GetEpisodes", params=params)

        if not resp.is_valid("episodes"):
            raise APIError(f"Invalid response: {resp}")

        return self._parse_ep_details(resp.result["episodes"])

    def get_episode_from_id(self, episode_id: int) -> EpisodeDetails:
        """Get details of a specific episode"""
        params = {"episodeid": episode_id, "properties": EP_PROPERTIES}
        self.log.debug("Getting episode details with episode id %s", episode_id)
        resp = self._req("VideoLibrary.GetEpisodeDetails", params=params)

        if not resp.is_valid("episodedetails"):
            raise APIError(f"Invalid response while finding episode details for id: {episode_id}")

        ep_details_lst = self._parse_ep_details([resp.result["episodedetails"]])
        if len(ep_details_lst) == 1:
            return ep_details_lst[0]

        return None

    def remove_episode(self, episode_id: int) -> None:
        """Remove an episode from library and return it's details"""
        params = {"episodeid": episode_id}
        self.log.debug("Removing episode with episode id %s", episode_id)
        resp = self._req("VideoLibrary.RemoveEpisode", params=params)

        if not resp.is_valid("OK"):
            raise APIError(f"Failed to remove episode id: {episode_id}")

        self.library_scanned = True

    # ------------------ Show Methods ------------------
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

    def get_shows_from_dir(self, directory: str) -> list[ShowDetails]:
        """Get list of shows within a directory"""
        mapped_path = self._map_path(directory)
        params = {
            "properties": SHOW_PROPERTIES,
            "filter": {"operator": "startswith", "field": "path", "value": mapped_path},
        }

        self.log.debug("Getting shows in %s using mapped path %s", directory, mapped_path)
        resp = self._req("VideoLibrary.GetTVShows", params=params)

        if not resp.is_valid("tvshows"):
            raise APIError(f"Invalid response while finding shows for directory '{directory}'")

        return self._parse_show_details(resp.result["tvshows"])

    def get_show_from_id(self, show_id: int) -> ShowDetails:
        """Get details of a specific TV Show"""
        params = {"tvshowid": show_id, "properties": SHOW_PROPERTIES}
        self.log.debug("Getting show details with tvshowid %s", show_id)
        resp = self._req("VideoLibrary.GetTVShowDetails", params=params)

        if not resp.is_valid("tvshowdetails"):
            raise APIError(f"Invalid response while finding TV Show details for id: {show_id}")

        show_details_lst = self._parse_show_details([resp.result["tvshowdetails"]])
        if len(show_details_lst) == 1:
            return show_details_lst[0]

        return None
