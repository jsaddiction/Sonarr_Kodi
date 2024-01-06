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

        start = datetime.now()
        for file in nfos:
            while True:
                elapsed = datetime.now() - start

                # Break out of loop if file found
                if file.exists():
                    self.log.info("Found %s", file.name)
                    break

                # Fail if timeout reached
                if elapsed.total_seconds() >= max_sec:
                    self.log.warning("Waited %s for %s. Giving Up.", elapsed, file.name)
                    return False

                sleep(delay)
        self.log.info("All required NFO files were found after %s", elapsed)
        return True

    def grab(self) -> None:
        """Grab Events"""
        log = logging.getLogger("GRAB")
        if not self.cfg.notifications.on_grab:
            log.warning("Notifications disabled. Skipping")
            return

        # Loop through each client
        for client in self.clients:
            # Send notification for each attempted download
            for ep_num, ep_title in zip(self.env.release_episode_numbers, self.env.release_episode_titles):
                msg = f"{self.env.series_title} - S{self.env.release_season_number:02}E{ep_num:02} - {ep_title}"
                title = "Sonarr - Attempting Download"
                client.notify(msg=msg, title=title)

    def download_new(self) -> None:
        """Downloaded a new episode"""
        log = logging.getLogger("NEW_EPISODE")
        new_episodes = []

        # optionally, wait for NFO files to generate
        ep_nfo = PosixPath(self.env.episode_file_path).with_suffix(".nfo")
        show_nfo = PosixPath(self.env.series_path).joinpath("tvshow.nfo")
        if not self._wait_for_nfos([ep_nfo, show_nfo]):
            self._full_scan_and_clean()
            return

        # Scan new episode file into kodi library
        for client in self.clients:
            mapped_series_dir = self._map_path_to_kodi(self.env.series_path, client.is_posix)
            try:
                new_episodes = client.scan_series_dir(mapped_series_dir)
            except (APIError, ScanTimeout):
                log.warning("Failed to scan. Skipping this client.")
                continue
            break

        # Exit if no episodes were added to library
        if len(new_episodes) == 0:
            log.warning("No new episodes found in %s.", mapped_series_dir)
            self._full_scan_and_clean()
        else:
            log.info("Scan found %s new episode[s].", len(new_episodes))

        # Update GUI on clients not previously scanned and not playing
        for client in [x for x in self.clients if not x.library_scanned and not x.is_playing]:
            try:
                client.update_gui()
            except APIError as e:
                log.warning("Failed to update GUI. Error: %s", e)
                continue

        # Notify clients
        if not self.cfg.notifications.on_download_new:
            log.info("Notifications Disabled. Skipping.")
            return

        for client in self.clients:
            for episode in new_episodes:
                client.notify(title="Sonarr - Downloaded New Episode", msg=episode)

    def download_upgrade(self) -> None:
        """Downloaded an upgraded episode file"""
        log = logging.getLogger("UPGRADE_EPISODE")

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
            log.info("Getting current episode data")
            try:
                curr_episodes = client.get_episodes_from_dir(series_path)
            except APIError:
                continue

            # Remove old episodes
            deleted_episodes: list[EpisodeDetails] = []
            for ep in [x for x in curr_episodes if x.file in old_ep_paths]:
                try:
                    client.remove_episode(ep.episode_id)
                except APIError:
                    log.warning("Failed to remove %s", ep)
                    continue
                deleted_episodes.append(ep)

            # Scan for new files
            new_episodes = client.scan_series_dir(series_path)

            # Reapply metadata to new episodes
            for new_ep in new_episodes:
                for old_ep in deleted_episodes:
                    if new_ep == old_ep:
                        try:
                            client.set_episode_watched_state(old_ep.watched_state, new_ep.episode_id)
                        except APIError:
                            log.warning("Failed to set episode watched state for %s", new_ep)
                            break

        # Update GUI on remaining clients
        for client in [x for x in self.clients if not x.library_scanned]:
            try:
                client.update_gui()
            except APIError:
                log.warning("Failed to update GUI")

        # Send notifications
        if not self.cfg.notifications.on_download_upgrade:
            log.info("Notifications Disabled. Skipping.")
            return

        for client in self.clients:
            for episode in new_episodes:
                client.notify(title="Sonarr - Upgraded Episode", msg=episode)

    def rename(self) -> None:
        """Renamed an episode file"""
        log = logging.getLogger("RENAME")
        log.info("Rename Event Detected")

        # Optionally, wait for nfo files to be created
        new_files = [PosixPath(self.env.series_path, x) for x in self.env.episode_file_rel_paths]
        nfos = [x.with_suffix(".nfo") for x in new_files]
        nfos.append(PosixPath(self.env.series_path).joinpath("tvshow.nfo"))
        if not self._wait_for_nfos(nfos):
            log.warning("NFO files never created, falling back to full library scan.")
            self._full_scan_and_clean()
            return

        for client in self.clients:
            old_paths = [self._map_path_to_kodi(x, client.is_posix) for x in self.env.episode_file_previous_paths]
            series_path = self._map_path_to_kodi(self.env.series_path, client.is_posix)
            old_episodes: list[EpisodeDetails] = []

            # Get old data
            for old_path in old_paths:
                try:
                    old_episodes.extend(client.get_episodes_from_file(old_path))
                except APIError:
                    continue

            # Remove old episodes
            for old_episode in old_episodes:
                try:
                    client.remove_episode(old_episode.episode_id)
                except APIError:
                    log.warning("Failed to remove old episode %s", old_episode)

            # Scan new content
            new_episodes = client.scan_series_dir(series_path)

            # Reapply metadata to new episodes
            for new_ep in new_episodes:
                for old_ep in old_episodes:
                    if new_ep == old_ep:
                        try:
                            client.set_episode_watched_state(old_ep, new_ep.episode_id)
                        except APIError:
                            log.warning("Failed to set episode watched state for %s", new_ep)
                            break

            if client.library_scanned:
                break

        # Update GUI on remaining clients
        for client in [x for x in self.clients if not x.library_scanned]:
            try:
                client.update_gui()
            except APIError:
                log.warning("Failed to update GUI on %s", client.name)

        # Send notifications
        if not self.cfg.notifications.on_rename:
            log.info("Notifications Disabled. Skipping.")
            return

        for client in self.clients:
            for episode in new_episodes:
                client.notify(title="Sonarr - Renamed Episode", msg=episode)

    def delete(self) -> None:
        """Remove an episode"""
        log = logging.getLogger("DELETE")

        deleted_reason = self.env.episode_file_delete_reason
        if deleted_reason.lower() == "upgrade":
            log.info("Ignoring this delete. It's part of an upgrade.")
            return

        for client in self.clients:
            deleted_file = self._map_path_to_kodi(self.env.episode_file_path, client.is_posix)
            try:
                episode: EpisodeDetails = client.get_episodes_from_file(deleted_file)
                client.remove_episode(episode.episode_id)
            except APIError:
                log.warning("Failed to remove %s", deleted_file)

            break

        for client in [x for x in self.clients if not x.library_scanned]:
            try:
                client.update_gui()
            except APIError:
                log.warning("Failed to update GUI")

        # Send notifications
        if not self.cfg.notifications.on_rename:
            log.info("Notifications Disabled. Skipping.")
            return

        for client in self.clients:
            client.notify(title="Sonarr - Deleted Episode", msg=episode)

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
