"""Kodi Host wrapper to manipulate many hosts"""

import logging
import pickle
from pathlib import Path
from time import sleep
from dataclasses import asdict
from .rpc_client import KodiRPC
from .config import HostConfig, PathMapping
from .exceptions import APIError, ScanTimeout
from .models import EpisodeDetails, StoppedEpisode, ShowDetails, Notification


class LibraryManager:
    """A Wrapper that exposes methods of the JSON-RPC API.
    These methods are deployed in a redundant way with many
    instances of kodi.
    """

    PICKLE_PATH = Path(__file__).with_name("stopped_episodes.pk1")

    def __init__(self, host_configs: list[HostConfig], path_maps: list[PathMapping]) -> None:
        self.log = logging.getLogger("Kodi-Library-Manager")
        self.hosts: list[KodiRPC] = []

        self.log.debug("Building list of Kodi Hosts")
        for cfg in host_configs:
            if not cfg.enabled:
                self.log.debug("Skipping disabled host: %s", cfg.name)
                continue

            # Create RPC Host
            host_cfg = HostConfig(**asdict(cfg))
            host_cfg.path_maps = path_maps
            host = KodiRPC(host_cfg)

            # Test and store host
            self.log.debug("Testing connection with %s", cfg.name)
            if host.is_alive:
                self.hosts.append(host)

        self.log.info("Connection established with: [%s]", self.host_names)

    @property
    def host_names(self) -> str:
        """Comma separated list of host names"""
        return ", ".join([x.name for x in self.hosts])

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
        """Serialize and store list of stopped episodes"""
        self.log.debug("Storing stopped episodes. %s", stopped_eps)
        try:
            with self.PICKLE_PATH.open(mode="wb") as file:
                pickle.dump(stopped_eps, file)
        except IOError as e:
            self.log.warning("Failed to store stopped episodes. Error: %s", e)

    def _deserialize(self) -> list[StoppedEpisode]:
        """Deserialize previously recorded data for replaying stopped episodes"""
        self.log.debug("Reading stopped episodes file.")
        try:
            with self.PICKLE_PATH.open(mode="rb") as file:
                data = pickle.load(file)
            self.PICKLE_PATH.unlink()
        except IOError as e:
            self.log.warning("Failed to load previously stored episode data. ERROR: %s", e)
            return []

        return data

    # -------------- GUI Methods -------------------
    def update_guis(self) -> None:
        """Update GUI for all hosts not scanned"""
        for host in self.hosts_not_scanned:
            host.update_gui()

    def notify(self, notification: Notification) -> None:
        """Send notification to all enabled hosts if"""

        for host in self.hosts:
            host.notify(notification)

    # -------------- Player Methods ----------------
    def stop_playback(self, episode: EpisodeDetails, reason: str, store_result: bool = True) -> None:
        """Stop playback of an episode on any host"""
        title = "Sonarr - Stopped Playback"
        stopped_episodes: list[StoppedEpisode] = []
        for host in self.hosts:
            # Skip host if not playing the episode, otherwise collect playerid
            player_id = host.is_playing_episode(episode.episode_id)
            if player_id is None:
                continue

            # Stop the player and collect position
            self.log.info("%s Stopping playback of %s", host.name, episode)
            position = host.stop_player(player_id)
            if position is not None:
                stopped_episodes.append(StoppedEpisode(episode=episode, host_name=host.name, position=position))

        # Return early if nothing was stopped
        if not stopped_episodes:
            return

        # Store result of stopped
        if store_result:
            self._serialize(stopped_episodes)

        # Pause to allow UI to load
        sleep(3)

        # Send notifications about the stopped episode to the GUI
        for host in self.hosts:
            for stopped_ep in stopped_episodes:
                if host.name != stopped_ep.host_name:
                    continue
                host.notify(Notification(title=title, msg=reason))

    def start_playback(self, episode: EpisodeDetails) -> None:
        """Resume playback of a previously stopped episode"""
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
                host.start_episode(episode.episode_id, ep.position)

    # -------------- Library Scanning --------------
    def scan_directory(self, show_dir: str, skip_active: bool = False) -> list[EpisodeDetails]:
        """Scan show directory, optionally skipping any active devices

        Returns:
            Empty list: If new episodes not found
            List[EpisodeDetails]: If new episodes were found
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
                try:
                    host.scan_series_dir(show_dir)
                    scanned = True
                    break
                except (APIError, ScanTimeout) as e:
                    self.log.warning("Failed to scan. Skipping this host. Error: %s", e)
                    continue

            # Wait 5 seconds before trying all hosts again
            if not scanned:
                sleep(5)

        # Get current episodes (after scan)
        episodes_after_scan = self.get_episodes_by_dir(show_dir)

        return [x for x in episodes_after_scan if x not in episodes_before_scan]

    def full_scan(self, skip_active: bool = False) -> list[EpisodeDetails]:
        """Scan entire video library and return newly added episodes
        This is an IO and library expensive operation.
        """
        # Get episodes before scan
        episodes_before_scan = self.get_all_episodes()

        # Scan Video library
        scanned = False
        while not scanned:
            for host in self.hosts:
                # Optionally, Skip active hosts
                if skip_active and host.is_playing:
                    self.log.info("Skipping active player %s", host.name)
                    continue

                # Scan the directory
                try:
                    host.full_video_scan()
                    scanned = True
                    break
                except (APIError, ScanTimeout) as e:
                    self.log.warning("Failed to scan. Skipping this host. Error: %s", e)
                    continue

            # Wait 5 seconds before trying all hosts again
            if not scanned:
                sleep(5)

        # Get episodes after scan
        episodes_after_scan = self.get_all_episodes()

        # Calculate added episodes after scan
        new_episodes = [x for x in episodes_after_scan if x not in episodes_before_scan]

        # Restart any episodes that were playing
        for episode in new_episodes:
            for host in [x for x in self.hosts if x.stop_episode]:
                host.play_episode(episode)

        return new_episodes

    def clean_library(self, skip_active: bool = False, series_dir: str = None) -> None:
        """Clean Library and wait for completion"""

        # Clean library
        cleaned = False
        while not cleaned:
            for host in self.hosts:
                # Optionally, skip active hosts
                if skip_active and host.is_playing:
                    self.log.info("Skipping active player %s", host.name)
                    continue

                # Clean video library
                try:
                    host.clean_video_library(series_dir)
                    cleaned = True
                    break
                except APIError as e:
                    self.log.warning(e)
                    continue

            # Wait 5 seconds before trying all hosts again
            if not cleaned:
                sleep(5)

    # -------------- Episode Methods --------------
    def get_all_episodes(self) -> list[EpisodeDetails]:
        """Get all episodes from library
        This is Library expensive operation
        """
        self.log.info("Getting all episodes. This may take a moment.")
        for host in self.hosts:
            try:
                return host.get_all_episodes()
            except APIError:
                self.log.warning("%s Failed to get all episodes.", host.name)
                continue
        return []

    def get_episodes_by_dir(self, show_dir) -> list[EpisodeDetails]:
        """Get all episodes contained in a directory"""
        for host in self.hosts:
            try:
                return host.get_episodes_from_dir(show_dir)
            except APIError as e:
                self.log.warning("Failed to get episodes by directory %s. Trying next host. Error: %s", show_dir, e)
                continue

        return []

    def get_episodes_by_file(self, episode_path: str) -> list[EpisodeDetails]:
        """Get episode data for each episode file"""
        for host in self.hosts:
            try:
                return host.get_episodes_from_file(episode_path)
            except APIError as e:
                self.log.warning("Failed to get episodes by file %s. Trying next host. Error: %s", episode_path, e)
                continue

        return []

    def remove_episode(self, episode: EpisodeDetails) -> bool:
        """Remove episode from library, return true if success"""
        self.log.info("Removing episode %s", episode)
        for host in self.hosts:
            try:
                host.remove_episode(episode.episode_id)
            except APIError:
                self.log.warning("%s Failed to remove %s", host.name, episode)
                continue
            return True

        return False

    def copy_ep_metadata(self, old_eps: list[EpisodeDetails], new_eps: list[EpisodeDetails]) -> list[EpisodeDetails]:
        """Copy watched states and date added from old episodes to their matching new entires"""
        # Return if both lists are empty
        if not old_eps or not new_eps:
            return []

        edited_episodes = set()
        for host in self.hosts:
            for old_ep in old_eps:
                for new_ep in new_eps:
                    if old_ep == new_ep:
                        self.log.info("Applying metadata to new episode : %s", new_ep)
                        try:
                            host.set_episode_watched_state(old_ep, new_ep.episode_id)
                            edited_episodes.add(host.get_episode_from_id(new_ep.episode_id))
                        except APIError:
                            self.log.warning("%s Failed to set episode metadata.", host.name)
                            continue
            if len(edited_episodes) == len(new_eps):
                break

        return edited_episodes

    # -------------- Show Methods --------------
    def remove_show(self, series_path: str) -> list[ShowDetails]:
        """Remove show from library"""
        # Remove all TV Shows within the series path
        shows: set[ShowDetails] = set()
        removed_shows: set[ShowDetails] = set()

        # Get current shows in series_path
        self.log.info("Removing tvshows within %s", series_path)
        for host in self.hosts:
            try:
                shows = host.get_shows_from_dir(series_path)
            except APIError:
                self.log.warning("Failed to get shows in %s", series_path)
                continue
            break

        # Exit early if no shows to remove
        if not shows:
            self.log.warning("No shows found within %s", series_path)
            return []

        for host in self.hosts:
            for show in shows:
                try:
                    removed_shows.add(host.remove_tvshow(show.show_id))
                except APIError:
                    self.log.warning("Failed to remove TV Show %s", show)
                    continue
            break

        return removed_shows

    def show_exists(self, series_path: str) -> list[ShowDetails]:
        """Check if a show exists, return list of shows with series_path"""
        self.log.debug("Checking for existing show in %s", series_path)
        for host in self.hosts:
            try:
                return host.get_shows_from_dir(series_path)
            except APIError:
                continue
        return False
