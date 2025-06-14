"""Kodi Host wrapper to manipulate many hosts"""

import logging
import pickle
from pathlib import Path
from time import sleep
from src.config.models import HostConfig, PathMapping
from .rpc_client import KodiRPC
from .models import EpisodeDetails, StoppedEpisode, ShowDetails


class LibraryManager:
    """A Wrapper that exposes methods of the JSON-RPC API.
    These methods are deployed in a redundant way with many
    instances of kodi.
    """

    PICKLE_PATH = Path(__file__).with_name("stopped_episodes.pk1")

    def __init__(self, host_configs: list[HostConfig], path_maps: list[PathMapping]) -> None:
        self.log = logging.getLogger("Kodi-Library-Manager")
        self.log.debug("Building list of Kodi Hosts")
        self.hosts: list[KodiRPC] = []
        for cfg in host_configs:
            if not cfg.enabled:
                self.log.info("Skipping disabled host %s", cfg.name)
                continue

            if host := self._create_host(cfg, path_maps):
                self.hosts.append(host)
            else:
                self.log.info("Failed to connect to %s", cfg.name)

    def _create_host(self, cfg: HostConfig, path_maps: list[PathMapping]) -> KodiRPC:
        """Create a new KodiRPC instance and return it if connection is successful"""
        host = KodiRPC(
            name=cfg.name,
            ip_addr=cfg.ip_addr,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            disable_notifications=cfg.disable_notifications,
            priority=cfg.priority,
            path_maps=[{"sonarr": x.sonarr, "kodi": x.kodi} for x in path_maps],
        )
        self.log.debug("Testing connection with %s", cfg.name)
        if host.is_alive:
            self.log.info("Connection established with: %s", host)
            return host
        return None

    def dispose_hosts(self) -> None:
        """Close all sessions in all hosts"""
        for host in self.hosts:
            host.close_session()

    @property
    def hosts_not_scanned(self) -> list[KodiRPC]:
        """All Kodi Hosts that were not scanned"""
        return [x for x in self.hosts if not x.library_scanned]

    @property
    def hosts_not_playing(self) -> list[KodiRPC]:
        """list of hosts not currently playing"""
        return [x for x in self.hosts if not x.is_playing]

    # -------------- Helpers -----------------------
    def _serialize(self, stopped_eps: list[StoppedEpisode]) -> None:
        """Serialize and store list of stopped episodes

        Args:
            stopped_eps (list[StoppedEpisode]): Objects containing details of stopped library items
        """
        self.log.debug("Storing stopped episodes. %s", stopped_eps)
        try:
            with self.PICKLE_PATH.open(mode="wb") as file:
                pickle.dump(stopped_eps, file)
        except IOError as e:
            self.log.warning("Failed to store stopped episodes. Error: %s", e)

    def _deserialize(self) -> list[StoppedEpisode]:
        """Deserialize previously stored, stopped episodes. Deletes persistent storage once complete.

        Returns:
            list[StoppedEpisode]: Objects containing details of stopped library items
        """
        self.log.debug("Reading stopped episodes file.")
        try:
            with self.PICKLE_PATH.open(mode="rb") as file:
                data = pickle.load(file)
            self.PICKLE_PATH.unlink()
        except IOError as e:
            self.log.warning("Failed to load previously stored episode data. ERROR: %s", e)
            return []

        return data

    def _get_all_episodes(self) -> list[EpisodeDetails]:
        """Get all episodes from library. This is a SQL expensive operation"""
        self.log.info("Getting all episodes. This may take a moment.")
        for host in self.hosts:
            episodes = host.get_all_episodes()
            if episodes:
                return episodes

        return []

    # -------------- GUI Methods -------------------
    def update_guis(self) -> None:
        """Update GUI for all hosts not scanned"""
        for host in self.hosts_not_scanned:
            host.update_gui()

    def notify(self, title: str, msg: str) -> None:
        """Send notification to all enabled hosts"""

        for host in self.hosts:
            host.notify(title, msg)

    # -------------- Player Methods ----------------
    def stop_playback(self, episode: EpisodeDetails, reason: str, store_result: bool = True) -> None:
        """Stop playback of a given episode on any host

        Args:
            episode (EpisodeDetails): The episode to stop
            reason (str): Short description of why it was stopped. Used with notifications.
            store_result (bool, optional): True when the intent is to restart later. Defaults to True.
        """
        title = "Sonarr - Stopped Playback"
        stopped_episodes: list[StoppedEpisode] = []

        # Loop through players, get episode_id and player_id
        for host in self.hosts:
            for player in host.active_players:
                item = host.get_player_item(player.player_id)

                # Skip if not an episode
                if item and item.type.lower() != "episode":
                    continue

                # Skip if not the episode we are looking for
                if item.item_id != episode.episode_id:
                    continue

                # Stop the player and collect position, paused state
                self.log.info("%s Stopping playback of %s", host.name, episode)
                paused = host.is_paused(player.player_id)
                position = host.player_percent(player.player_id)
                host.stop_player(player.player_id)
                stopped_episodes.append(
                    StoppedEpisode(episode=episode, host_name=host.name, position=position, paused=paused)
                )

        # Return early if nothing was stopped on any host
        if not stopped_episodes:
            return

        # Store results of stopped episodes
        if store_result:
            self._serialize(stopped_episodes)

        # Pause to allow UI to load before sending notifications
        sleep(2)

        # Send notifications about the stopped episode to the GUI
        for host in self.hosts:
            for stopped_ep in stopped_episodes:
                if host.name != stopped_ep.host_name:
                    continue
                host.notify(title, reason, force=True)

    def start_playback(self, episode: EpisodeDetails) -> None:
        """Start playback of a given episode that was previously stopped and results were stored.

        Args:
            episode (EpisodeDetails): The episode to start.
        """
        # Do not attempt if nothing was previously stored
        if not self.PICKLE_PATH.exists():
            return

        stopped_episodes = self._deserialize()
        if stopped_episodes:
            self.log.debug("Attempting to restart episodes %s", stopped_episodes)
        for host in self.hosts:
            for ep in stopped_episodes:
                # Skip wrong host
                if ep.host_name != host.name:
                    continue

                # Skip wrong episode
                if ep.episode != episode:
                    continue

                # Start playback
                player = host.start_episode(episode.episode_id, ep.position)

                # Pause if was previously paused
                if ep.paused and player:
                    host.pause_player(player.player_id)

    # -------------- Library Scanning --------------
    def scan_directory(self, show_dir: str, skip_active: bool = False) -> list[EpisodeDetails]:
        """Scan a given directory by the first available host.

        Args:
            show_dir (str): The directory to scan
            skip_active (bool, optional): True if active hosts should be skipped. Defaults to False.

        Returns:
            list[EpisodeDetails]: New episodes that were added to the library.
        """

        # Get current episodes
        episodes_before_scan = self.get_episodes_by_dir(show_dir)

        # Scanning
        scanned = False
        while not scanned:
            for host in self.hosts:
                # Optionally, Skip active hosts
                if skip_active and host.is_playing:
                    self.log.info("Skipping active player %s", host.name)
                    continue

                # Scan the directory
                if host.scan_series_dir(show_dir):
                    scanned = True
                    break

            # Wait 5 seconds before trying all hosts again
            if not scanned:
                sleep(5)

        # Get current episodes (after scan)
        episodes_after_scan = self.get_episodes_by_dir(show_dir)

        return [x for x in episodes_after_scan if x not in episodes_before_scan]

    def full_scan(self, skip_active: bool = False) -> list[EpisodeDetails]:
        """Conduct a full library scan. This is SQL and Filesystem expensive.

        Args:
            skip_active (bool, optional): True if active hosts should be skipped. Defaults to False.

        Returns:
            list[EpisodeDetails]: New episodes that were added to the library.
        """
        # Get episodes before scan
        episodes_before_scan = self._get_all_episodes()

        # Scan Video library
        scanned = False
        while not scanned:
            for host in self.hosts:
                # Optionally, Skip active hosts
                if skip_active and host.is_playing:
                    self.log.info("Skipping active player %s", host.name)
                    continue

                # Scan the library
                if host.full_video_scan():
                    scanned = True
                    break

            # Wait 5 seconds before trying all hosts again
            if not scanned:
                sleep(5)

        # Get episodes after scan
        episodes_after_scan = self._get_all_episodes()

        # Calculate added episodes after scan and return
        return [x for x in episodes_after_scan if x not in episodes_before_scan]

    def clean_library(self, skip_active: bool = False, series_dir: str = None) -> None:
        """Clean the video library. Potentially a blocking method if no hosts successfully ever clean.

        Args:
            skip_active (bool, optional): True if active players should be skipped. Defaults to False.
            series_dir (str, optional): Directory to clean. Defaults to None.
        """

        # Clean library
        while True:
            for host in self.hosts:
                # Optionally, skip active hosts
                if skip_active and host.is_playing:
                    self.log.info("Skipping active player %s", host.name)
                    continue

                # Clean video library
                if host.clean_video_library():
                    return

            # Wait 5 seconds before trying all hosts again
            sleep(5)

    # -------------- Episode Methods --------------
    def get_episodes_by_dir(self, show_dir: str) -> list[EpisodeDetails]:
        """Get all episodes that reside in a specific directory

        Args:
            show_dir (str): the directory to filter on.

        Returns:
            list[EpisodeDetails]: Episodes gathered from the library.
        """
        for host in self.hosts:
            episodes = host.get_episodes_from_dir(show_dir)
            if episodes:
                return episodes

        return []

    def get_episodes_by_file(self, episode_path: str) -> list[EpisodeDetails]:
        """Get all episodes that reside in a specific file

        Args:
            episode_path (str): the file to filter on.

        Returns:
            list[EpisodeDetails]: Episodes gathered from the library.
        """
        for host in self.hosts:
            episodes = host.get_episodes_from_file(episode_path)
            if episodes:
                return episodes

        return []

    def remove_episode(self, episode: EpisodeDetails) -> bool:
        """Remove an episode from the library

        Args:
            episode (EpisodeDetails): The episode to remove

        Returns:
            bool: True if the episode was removed
        """
        self.log.info("Removing episode '%s'", episode)
        for host in self.hosts:
            if host.remove_episode(episode.episode_id):
                return True

        return False

    def copy_ep_metadata(self, old_ep: EpisodeDetails, new_ep: EpisodeDetails) -> bool:
        """Copy metadata from old episode to new episode

        Args:
            old_ep (EpisodeDetails): The episode to copy metadata from
            new_ep (EpisodeDetails): The episode to copy metadata to

        Returns:
            bool: True if the metadata was copied
        """
        for host in self.hosts:
            self.log.info("Applying metadata to new episode : %s", new_ep)
            if host.set_episode_watched_state(old_ep, new_ep.episode_id):
                return True

        return False

    # -------------- Show Methods --------------
    def remove_show(self, series_path: str) -> list[ShowDetails]:
        """Remove a show from the library

        Args:
            series_path (str): The directory containing the show to remove

        Returns:
            list[ShowDetails]: Shows that were removed
        """
        # Remove all TV Shows within the series path
        shows: list[ShowDetails] = []
        removed_shows: list[ShowDetails] = []

        # Get current shows in series_path
        self.log.info("Removing tvshows within %s", series_path)
        shows = self.get_shows_from_dir(series_path)

        # Exit early if no shows to remove
        if not shows:
            self.log.warning("No shows found within %s", series_path)
            return []

        # Try up to 3 times
        for _ in range(3):
            for host in self.hosts:
                for show in [x for x in shows if x not in removed_shows]:
                    if host.remove_tvshow(show):
                        removed_shows.append(show)

                if len(shows) == len(removed_shows):
                    return removed_shows

        remaining_shows = [x for x in shows if x not in removed_shows]
        self.log.warning("Failed to remove shows after 3 attempts. %s", remaining_shows)
        return removed_shows

    def get_shows_from_dir(self, directory: str) -> list[ShowDetails]:
        """Get all shows that reside in a specific directory

        Args:
            directory (str): the directory to filter on.

        Returns:
            list[ShowDetails]: Shows gathered from the library.
        """
        self.log.info("Getting shows from directory: %s", directory)
        for host in self.hosts:
            shows = host.get_shows_from_dir(directory)
            if shows:
                self.log.debug("Found %d shows", len(shows))
                return shows

        self.log.warning("No shows found in directory: %s", directory)

        return []

    def show_exists(self, series_path: str) -> list[ShowDetails]:
        """Check if a directory contains a show

        Args:
            series_path (str): The directory to check

        Returns:
            list[ShowDetails]: Shows that were found
        """
        self.log.debug("Checking for existing show in %s", series_path)
        for host in self.hosts:
            shows = host.get_shows_from_dir(series_path)
            if shows:
                return shows

        return []
