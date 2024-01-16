"""Kodi Host wrapper to manipulate many hosts"""

import logging
from time import sleep
from dataclasses import asdict
from .rpc_client import KodiRPC
from .config import HostConfig
from .exceptions import APIError, ScanTimeout
from .models import EpisodeDetails, ShowDetails, Source


class LibraryManager:
    """A Wrapper that exposes methods of the JSON-RPC API.
    These methods are deployed in a redundant way with many
    instances of kodi.
    """

    def __init__(self, host_configs: list[HostConfig]) -> None:
        self.log = logging.getLogger("Kodi-Library-Manager")
        self.hosts: list[KodiRPC] = []

        self.log.info("Building list of Kodi Hosts")
        for cfg in host_configs:
            if not cfg.enabled:
                self.log.debug("Skipping disabled host: %s", cfg.name)
                continue

            # Create RPC Host
            host_cfg = HostConfig(**asdict(cfg))
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

    # -------------- GUI Methods --------------
    def update_guis(self) -> None:
        """Update GUI for all hosts not scanned"""
        self.log.info("Updating GUI on %s hosts", len(self.hosts_not_scanned))
        for host in self.hosts_not_scanned:
            host.update_gui()

    def notify(self, title: str, msg: str) -> None:
        """Send notification to all enabled hosts if"""
        self.log.info("Sending notification to %s hosts", len(self.hosts))
        for host in self.hosts:
            host.notify(msg, title)

    # -------------- Library Scanning --------------
    def scan_directory(self, show_dir: str, skip_active: bool = False) -> list[EpisodeDetails]:
        """Scan show directory, optionally skipping any active devices

        Returns:
            Empty list: If new episodes not found
            List[EpisodeDetails]: If new episodes were found
        """

        # Get current episodes
        episodes_before_scan = self.get_episodes_by_dir(show_dir)

        # Optionally, wait for inactive players
        if skip_active and len(self.hosts_not_playing) == 0:
            self.log.info("Directory scan paused while waiting for an inactive player")
            while len(self.hosts_not_playing) == 0:
                sleep(1)

        # Scan the show_dir
        self.log.info("Scanning show directory")
        for host in self.hosts:
            if skip_active and host.is_playing:
                self.log.info("Skipping active player %s", host.name)
                continue
            try:
                host.scan_series_dir(show_dir)
            except (APIError, ScanTimeout):
                self.log.warning("Failed to scan. Skipping this host.")
                continue

            break

        # Get current episodes (after scan)
        episodes_after_scan = self.get_episodes_by_dir(show_dir)

        return [x for x in episodes_after_scan if x not in episodes_before_scan]

    def full_scan(self, skip_active: bool = False) -> list[EpisodeDetails]:
        """Scan entire video library and return newly added episodes
        This is an IO and library expensive operation.
        """
        # Get episodes before scan
        episodes_before_scan = self.get_all_episodes()

        # Optionally, wait for inactive players
        if skip_active and len(self.hosts_not_playing) == 0:
            self.log.info("Full scan paused while waiting for an inactive player")
            while len(self.hosts_not_playing) == 0:
                sleep(1)

        # Scan Video library
        self.log.info("Performing full library scan")
        for host in self.hosts:
            if skip_active and host.is_playing:
                self.log.info("Skipping active player %s", host.name)
                continue
            try:
                host.full_video_scan()
            except APIError:
                continue

            break

        # Get episodes after scan
        episodes_after_scan = self.get_all_episodes()

        return [x for x in episodes_after_scan if x not in episodes_before_scan]

    def clean_library(self, skip_active: bool = False) -> None:
        """Clean Library and wait for completion"""
        # Optionally, wait for inactive players
        if skip_active and len(self.hosts_not_playing) == 0:
            self.log.info("Library cleaning paused while waiting for an inactive player")
            while len(self.hosts_not_playing) == 0:
                sleep(1)

        # Clean library
        self.log.info("Cleaning Library")
        for host in self.hosts:
            if skip_active and host.is_playing:
                self.log.info("Skipping active player %s", host.name)
                continue
            try:
                host.clean_video_library()
            except APIError:
                continue

            break

    # This may go away, only scan tvshow sources
    def scan_source_directories(self) -> list[EpisodeDetails] | None:
        """Scan all sources containing tv shows. This is expensive as all episodes
        are parsed from kodi within all sources.

        Returns:
            None: if no sources were found containing TV Shows
            Empty List: if no new episodes were found
            list[EpisodeDetails]: If new episodes were found
        """
        episodes_before_scan: list[EpisodeDetails] = []
        episodes_after_scan: list[EpisodeDetails] = []
        sources = self.get_show_sources()

        # Check for sources
        if not sources:
            self.log.warning("No Kodi sources containing TV Shows were found.")
            return None

        # Get all episodes before scan
        for source in sources:
            episodes_before_scan.extend(self.get_episodes_by_dir(source.file))

        self.log.info("Scanning all sources containing episodes")
        for host in self.hosts:
            all_sources_scanned = False
            for source in sources:
                try:
                    host.scan_series_dir(source.file)
                    all_sources_scanned = True
                except APIError:
                    self.log.warning("Failed to scan %s", source.file)
                    all_sources_scanned = False
                    continue

            if all_sources_scanned:
                break

        # Get all episodes after scan
        for source in sources:
            episodes_after_scan.extend(self.get_episodes_by_dir(source.file))

        return [x for x in episodes_after_scan if x not in episodes_before_scan]

    # -------------- Episode Methods --------------
    def get_all_episodes(self) -> list[EpisodeDetails]:
        """Get all episodes from library
        This is Library expensive operation
        """
        self.log.info("Getting all episodes")
        for host in self.hosts:
            try:
                return host.get_all_episodes()
            except APIError:
                self.log.warning("%s Failed to get all episodes.", host.name)
                continue
        return []

    def get_episodes_by_dir(self, show_dir) -> list[EpisodeDetails]:
        """Get all episodes contained in a directory"""
        self.log.info("Getting episodes within %s", show_dir)
        for host in self.hosts:
            try:
                return host.get_episodes_from_dir(show_dir)
            except APIError:
                self.log.warning("Failed to get episodes from %s", show_dir)

        return []

    def get_episodes_by_file(self, episode_path: str) -> list[EpisodeDetails] | None:
        """Get episode data for each episode file"""
        self.log.info("Getting episodes by file path %s", episode_path)
        for host in self.hosts:
            try:
                return host.get_episodes_from_file(episode_path)
            except APIError:
                continue

        return None

    def remove_episodes(self, episodes: list[EpisodeDetails]) -> list[EpisodeDetails] | None:
        """Remove episode from library"""
        if not episodes:
            return []

        removed_episodes = set()
        self.log.info("Removing %s episodes", len(episodes))
        for host in self.hosts:
            for ep in [x for x in episodes if x not in removed_episodes]:
                try:
                    host.remove_episode(ep.episode_id)
                    removed_episodes.add(ep)
                except APIError:
                    self.log.warning("%s Failed to remove %s", host.name, ep)
                    continue

            # If all episodes were removed break out of hosts loop
            if len(removed_episodes) == len(episodes):
                break

        return list(removed_episodes)

    def copy_ep_metadata(self, old_eps: list[EpisodeDetails], new_eps: list[EpisodeDetails]) -> list[EpisodeDetails]:
        """Copy watched states and date added from old episodes to their matching new entires"""
        edited_episodes = set()
        self.log.info("Copying %s episode[s] metadata to new episode[s]", len(new_eps))
        for host in self.hosts:
            for old_ep in old_eps:
                for new_ep in new_eps:
                    if old_ep == new_ep:
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
            break

        # Exit early if no shows to remove
        if not shows:
            self.log.warning("No shows found within %s", series_path)
            return None

        for host in self.hosts:
            for show in shows:
                try:
                    removed_shows.add(host.remove_tvshow(show.show_id))
                except APIError:
                    self.log.warning("Failed to remove TV Show %s", show)
                    continue

        return removed_shows

    def show_exists(self, series_path: str) -> list[ShowDetails]:
        """Check if a show exists, return list of shows with series_path"""
        self.log.info("Checking for existing show")
        for host in self.hosts:
            try:
                return host.get_shows_from_dir(series_path)
            except APIError:
                continue
        return False

    # This may go away, used by scan_source_directory
    def get_show_sources(self) -> list[Source] | None:
        """Get all TV Show sources from Kodi"""
        all_sources: list[Source] = []
        self.log.info("Getting show sources")
        for host in self.hosts:
            try:
                all_sources = host.get_show_sources()
            except APIError:
                self.log.warning("Failed to get sources from Kodi")
                continue

        if not all_sources:
            self.log.warning("Failed to get any sources from Kodi")
            return None

        return [x for x in all_sources if self.get_episodes_by_dir(x.file)]
