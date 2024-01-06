"""Sonarr_Kodi Event handler"""
import logging
from datetime import datetime
from time import sleep
from pathlib import PosixPath, PurePosixPath, PureWindowsPath
from .environment import SonarrEnvironment
from .config import Config
from .kodi import KodiClient, APIError, ScanTimeout, EpisodeDetails


class NFOTimeout(Exception):
    """Timed out while waiting for NFO to be created"""


class EventHandler:
    """Handles Sonarr Events and deploys Kodi JSON-RPC calls"""

    def __init__(self, env: SonarrEnvironment, cfg: Config, clients: list[KodiClient]) -> None:
        self.env = env
        self.cfg = cfg
        self.clients = clients
        self.log = logging.getLogger("EventHandler")

    def _map_path_to_kodi(self, sonarr_path: str, to_posix: bool) -> str:
        for path_map in self.cfg.library.path_mapping:
            if path_map.sonarr in sonarr_path:
                out_str = sonarr_path.replace(path_map.sonarr, path_map.kodi)
                if to_posix:
                    return str(PurePosixPath(out_str))
                else:
                    return str(PureWindowsPath(out_str))

        return sonarr_path

    def _full_scan_and_clean(self) -> None:
        """Scan all TV libraries then clean"""
        if not self.cfg.library.full_scan_fallback:
            self.log.warning("Full scan disabled. Skipping.")
            return

        self.log.info("Falling back to full library scan and clean.")

        # Scan tvshow library
        for client in self.clients:
            client.scan_show_library()
            if not client.library_scanned:
                continue

            # Optionally, clean library after scan
            if self.cfg.library.clean_after_update:
                client.clean_video_library()

    def _wait_for_nfos(self, nfos: list[PosixPath]) -> bool:
        """Wait for all files in nfos list to be present before proceeding"""
        # always return true if this check is disabled
        if not self.cfg.library.wait_for_nfo:
            return True

        # Ensure list was passed
        if not isinstance(nfos, list):
            raise ValueError(f"Expected a list of paths got '{nfos}'")

        # Ensure at least one nfo in the list
        if len(nfos) < 1:
            raise ValueError("Expected at least one nfo. Got empty list.")

        delay = 1
        max_sec = (self.cfg.library.nfo_timeout_minuets * len(nfos)) * 60
        self.log.info("Waiting up to %s minuets for %s NFO Files.", max_sec / 60, len(nfos))

        files_found = set()
        start = datetime.now()
        while len(nfos) > len(files_found):
            elapsed = datetime.now() - start

            for file in nfos:
                # skip files already found
                if file in files_found:
                    continue

                # record files when they propagate
                if file.exists():
                    files_found.add(file)

                # return false if we timed out
                elif elapsed.total_seconds() >= max_sec:
                    self.log.warning("Waited %s. %s NFO files not found.", elapsed, len(nfos))
                    self.log.warning("Missing NFO files. [%s]", ", ".join(nfos))
                    return False

            sleep(delay)

        self.log.info("All required NFO files were found after %s", elapsed)
        return True

    def _update_guis(self) -> None:
        """Update GUI for all clients not scanned"""
        for client in [x for x in self.clients if not x.library_scanned]:
            self.log.info("Updating GUI on %s", client.name)
            client.update_gui()

    def _notify_clients(self, title: str, msg: str) -> None:
        """Send notification to all clients"""
        for client in self.clients:
            self.log.info("Sending Notification %s : %s to %s", title, msg, client.name)
            client.notify(msg, title)

    def grab(self) -> None:
        """Grab Events"""
        self.log.info("Grab Event Detected")
        if not self.cfg.notifications.on_grab:
            self.log.warning("Notifications disabled. Skipping")
            return

        # Send notification for each attempted download
        for ep_num, ep_title in zip(self.env.release_episode_numbers, self.env.release_episode_titles):
            msg = f"{self.env.series_title} - S{self.env.release_season_number:02}E{ep_num:02} - {ep_title}"
            title = "Sonarr - Attempting Download"
            self._notify_clients(msg=msg, title=title)

    def download_new(self) -> None:
        """Downloaded a new episode"""
        self.log.info("Download New Episode Event Detected")
        new_episodes = []

        # optionally, wait for NFO files to generate
        ep_nfo = PosixPath(self.env.episode_file_path).with_suffix(".nfo")
        show_nfo = PosixPath(self.env.series_path).joinpath("tvshow.nfo")
        if not self._wait_for_nfos([ep_nfo, show_nfo]):
            self.log.warning("NFO files never created, falling back to full library scan.")
            self._full_scan_and_clean()
            return

        # Scan new episode file into kodi library
        for client in self.clients:
            series_path = self._map_path_to_kodi(self.env.series_path, client.is_posix)
            try:
                new_episodes = client.scan_series_dir(series_path)
            except (APIError, ScanTimeout):
                self.log.warning("Failed to scan. Skipping this client.")
                continue
            break

        # Exit if no episodes were added to library
        if len(new_episodes) == 0:
            self.log.warning("No new episodes found in %s.", series_path)
            self._full_scan_and_clean()
        else:
            self.log.info("Scan found %s new episode[s].", len(new_episodes))

        # Update GUI on clients not previously scanned and not playing
        self._update_guis()

        # Notify clients
        if self.cfg.notifications.on_download_new:
            title = "Sonarr - Downloaded New Episode"
            for episode in new_episodes:
                self._notify_clients(title=title, msg=episode)

    def download_upgrade(self) -> None:
        """Downloaded an upgraded episode file"""
        self.log.info("Upgrade Episode Event Detected")
        for client in self.clients:
            series_path = self._map_path_to_kodi(self.env.series_path, client.is_posix)
            old_ep_paths = [self._map_path_to_kodi(x, client.is_posix) for x in self.env.deleted_paths]

            # Optionally, wait for nfo files to be created
            ep_nfo = PosixPath(self.env.episode_file_path).with_suffix(".nfo")
            show_nfo = PosixPath(self.env.series_path).joinpath("tvshow.nfo")
            if not self._wait_for_nfos([ep_nfo, show_nfo]):
                self._full_scan_and_clean()
                return

            # Get current data in library
            self.log.info("Storing current episode data")
            try:
                curr_episodes = client.get_episodes_from_dir(series_path)
            except APIError:
                continue

            # Remove old episodes
            deleted_episodes: list[EpisodeDetails] = []
            self.log.info("Removing episodes from database.")
            for ep in [x for x in curr_episodes if x.file in old_ep_paths]:
                try:
                    client.remove_episode(ep.episode_id)
                except APIError:
                    self.log.warning("Failed to remove %s", ep)
                    continue
                deleted_episodes.append(ep)

            # Scan for new files
            self.log.info("Scanning %s with %s", series_path, client.name)
            try:
                new_episodes = client.scan_series_dir(series_path)
            except (APIError, ScanTimeout):
                self.log.warning("Failed to scan %s", series_path)
                continue

            # Reapply metadata to new episodes
            for new_ep in new_episodes:
                for old_ep in deleted_episodes:
                    if new_ep == old_ep:
                        if not old_ep.watched_state.is_watched:
                            self.log.info("Not setting watched state on unwatched episode")
                            continue
                        self.log.info("Setting Watched state of %s", new_ep)
                        try:
                            client.set_episode_watched_state(old_ep, new_ep.episode_id)
                        except APIError:
                            self.log.warning("Failed to set episode watched state for %s", new_ep)
                            break

            if client.library_scanned:
                break

        # Update GUI on remaining clients
        self._update_guis()

        # Notify clients
        if self.cfg.notifications.on_download_upgrade:
            title = "Sonarr - Upgraded Episode"
            for episode in new_episodes:
                self._notify_clients(title=title, msg=episode)

    def rename(self) -> None:
        """Renamed an episode file"""
        self.log.info("File Rename Event Detected")

        # Optionally, wait for nfo files to be created
        new_files = [PosixPath(self.env.series_path, x) for x in self.env.episode_file_rel_paths]
        nfos = [x.with_suffix(".nfo") for x in new_files]
        nfos.append(PosixPath(self.env.series_path).joinpath("tvshow.nfo"))
        if not self._wait_for_nfos(nfos):
            self.log.warning("NFO files never created, falling back to full library scan.")
            self._full_scan_and_clean()
            return

        for client in self.clients:
            old_paths = [self._map_path_to_kodi(x, client.is_posix) for x in self.env.episode_file_previous_paths]
            series_path = self._map_path_to_kodi(self.env.series_path, client.is_posix)
            old_episodes: list[EpisodeDetails] = []

            # Get old data
            self.log.info("Getting current info from Kodi")
            for old_path in old_paths:
                try:
                    old_episodes.extend(client.get_episodes_from_file(old_path))
                except APIError:
                    continue

            # Remove old episodes
            self.log.info("Removing episodes from database.")
            for old_episode in old_episodes:
                try:
                    client.remove_episode(old_episode.episode_id)
                except APIError:
                    self.log.warning("Failed to remove old episode %s", old_episode)

            # Scan new content
            try:
                new_episodes = client.scan_series_dir(series_path)
            except (APIError, ScanTimeout):
                self.log.warning("Failed to scan, Skipping this client.")
                continue

            # Reapply metadata to new episodes
            self.log.info("Applying old watched states")
            for new_ep in new_episodes:
                for old_ep in old_episodes:
                    if new_ep == old_ep:
                        try:
                            client.set_episode_watched_state(old_ep, new_ep.episode_id)
                        except APIError:
                            self.log.warning("Failed to set episode watched state for %s", new_ep)
                            break

            if client.library_scanned:
                break

        # Update GUI on remaining clients
        self._update_guis()

        # Notify clients
        if self.cfg.notifications.on_rename:
            title = "Sonarr - Renamed Episode"
            for episode in new_episodes:
                self._notify_clients(title=title, msg=episode)

    def delete(self) -> None:
        """Remove an episode"""
        self.log.info("Delete File Event Detected")
        # Ignore delete event if upgrade is pending
        deleted_reason = self.env.episode_file_delete_reason
        if deleted_reason.lower() == "upgrade":
            self.log.info("Ignoring this delete. It's part of an upgrade.")
            return

        for client in self.clients:
            deleted_file = self._map_path_to_kodi(self.env.episode_file_path, client.is_posix)
            episodes: list[EpisodeDetails] = client.get_episodes_from_file(deleted_file)
            for episode in episodes:
                try:
                    client.remove_episode(episode.episode_id)
                except APIError:
                    self.log.warning("Failed to remove %s", deleted_file)

            if client.library_scanned:
                break

        # Update remaining guis
        self._update_guis()

        # Notify clients
        if self.cfg.notifications.on_delete:
            title = "Sonarr - Deleted Episode"
            for episode in episodes:
                self._notify_clients(title=title, msg=episode)

    def series_add(self) -> None:
        """Adding a Series"""

    def series_delete(self) -> None:
        """Deleting a Series"""

    def health_issue(self) -> None:
        """Experienced a Health Issue"""

    def health_restored(self) -> None:
        """Health Restored"""

    def application_update(self) -> None:
        """Application Updated"""

    def manual_interaction_required(self) -> None:
        """Manual Interaction Required"""

    def test(self) -> None:
        """Sonarr Tested this script"""
