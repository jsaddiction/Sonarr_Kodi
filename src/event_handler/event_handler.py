"""Sonarr_Kodi Event handler"""
import logging
from datetime import datetime
from time import sleep
from pathlib import PosixPath
from src.environment import SonarrEnvironment
from src.config import Config
from src.kodi import LibraryManager, Notification


class NFOTimeout(Exception):
    """Timed out while waiting for NFO to be created"""


class EventHandler:
    """Handles Sonarr Events and deploys Kodi JSON-RPC calls"""

    def __init__(self, env: SonarrEnvironment, cfg: Config, kodi: LibraryManager) -> None:
        self.env = env
        self.cfg = cfg
        self.kodi = kodi
        self.log = logging.getLogger("EventHandler")

    # ------------- New Helpers --------------------
    def _wait_for_nfos(self, nfos: list[PosixPath]) -> bool:
        """Wait for all files in nfos list to be present before proceeding"""
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
                    self.log.warning("Exceeded %s waiting for %s NFO files.", elapsed, len(nfos))
                    self.log.warning("Missing NFO files. [%s]", ", ".join(nfos))
                    return False

            sleep(delay)

        self.log.info("All required NFO files were found after %s", elapsed)
        return True

    # ------------- Events -------------------------
    def grab(self) -> None:
        """Grab Events"""
        self.log.info("Grab Event Detected")

        # Send notification for each attempted download
        if self.cfg.notifications.on_grab:
            notifications = []
            for ep_num, ep_title in zip(self.env.release_episode_numbers, self.env.release_episode_titles):
                notifications.append(
                    Notification(
                        title="Sonarr - Attempting Download",
                        msg=f"{self.env.series_title} - S{self.env.release_season_number:02}E{ep_num:02} - {ep_title}",
                    )
                )

            self.kodi.notify(notifications)

    def download_new(self) -> None:
        """Downloaded a new episode"""
        self.log.info("Download New Episode Event Detected")
        new_episodes = []

        # optionally, wait for NFO files to generate
        if self.cfg.library.wait_for_nfo:
            ep_nfo = PosixPath(self.env.episode_file_path).with_suffix(".nfo")
            show_nfo = PosixPath(self.env.series_path).joinpath("tvshow.nfo")
            if not self._wait_for_nfos([ep_nfo, show_nfo]):
                return

        # New Show, perform full scan
        if not self.kodi.show_exists(self.env.series_path):
            self.log.info("New Show Detected, Full scan required.")
            new_episodes = self.kodi.full_scan(skip_active=self.cfg.library.skip_active)

        # Existing show, try scanning directory. Maybe fallback to full scan
        else:
            self.log.info("Existing Show Detected, Performing directory scan.")
            new_episodes = self.kodi.scan_directory(self.env.series_path, skip_active=self.cfg.library.skip_active)
            if not new_episodes and self.cfg.library.full_scan_fallback:
                self.log.info("No new episodes found during folder scan. Falling back to Full Scan.")
                new_episodes = self.kodi.full_scan(skip_active=self.cfg.library.skip_active)

        # Optionally, Clean Library
        if self.cfg.library.clean_after_update:
            self.kodi.clean_library()

        if not new_episodes:
            self.log.warning("No episodes were scanned into library. Exiting.")
            return

        self.log.info("Scan found %s new episode[s].", len(new_episodes))

        # Update GUI on clients not previously scanned and not playing
        self.kodi.update_guis()

        # Notify clients
        if self.cfg.notifications.on_download_new:
            notifications = []
            for episode in new_episodes:
                notifications.append(Notification(title="Sonarr - Downloaded New Episode", msg=episode))
            self.kodi.notify(notifications)

    def download_upgrade(self) -> None:
        """Downloaded an upgraded episode file"""
        self.log.info("Upgrade Episode Event Detected")

        # optionally, wait for NFO files to generate
        if self.cfg.library.wait_for_nfo:
            ep_nfo = PosixPath(self.env.episode_file_path).with_suffix(".nfo")
            show_nfo = PosixPath(self.env.series_path).joinpath("tvshow.nfo")
            if not self._wait_for_nfos([ep_nfo, show_nfo]):
                self.log.warning("NFO Files never created")
                return

        # get data from library for replaced files
        old_episodes = []
        for path in self.env.deleted_paths:
            old_episodes.extend(self.kodi.get_episodes_by_file(path))

        if len(old_episodes) == 0:
            self.log.warning("Failed to get old episode data. Unable to persist watched states.")
            removed_episodes = []
        else:
            # remove episodes
            self.log.info("Removing %s old episodes", len(old_episodes))
            removed_episodes = self.kodi.remove_episodes(list(old_episodes))

        # scan show directory
        new_episodes = self.kodi.scan_directory(self.env.series_path, skip_active=self.cfg.library.skip_active)

        # Fall back to full library scan
        if not new_episodes and self.cfg.library.full_scan_fallback:
            new_episodes = self.kodi.scan_video_library(skip_active=self.cfg.library.skip_active)

        # Optionally, Clean Library
        if self.cfg.library.clean_after_update:
            self.kodi.clean_library()

        # Fail if no episodes were scanned
        if not new_episodes:
            self.log.warning("No new episodes were found. Exiting")
            return

        # reapply metadata from old library entries
        self.kodi.copy_ep_metadata(removed_episodes, new_episodes)

        # update remaining guis
        self.kodi.update_guis()

        # notify clients
        if self.cfg.notifications.on_download_upgrade:
            notifications = []
            for episode in new_episodes:
                notifications.append(Notification(title="Sonarr - Upgraded Episode", msg=episode))
            self.kodi.notify(notifications)

    def rename(self) -> None:
        """Renamed an episode file"""
        self.log.info("File Rename Event Detected")

        # Optionally, wait for nfo files to be created
        if self.cfg.library.wait_for_nfo:
            new_files = [PosixPath(self.env.series_path, x) for x in self.env.episode_file_rel_paths]
            nfos = [x.with_suffix(".nfo") for x in new_files]
            nfos.append(PosixPath(self.env.series_path, "tvshow.nfo"))
            if not self._wait_for_nfos(nfos):
                self.log.warning("NFO Files never created")
                return

        # Get current data from library
        old_episodes = []
        for path in self.env.episode_file_previous_paths:
            old_episodes.extend(self.kodi.get_episodes_by_file(path))

        if not old_episodes:
            self.log.warning("Failed to get old episode data. Unable to persist watched states.")

        # Remove old episodes
        removed_episodes = self.kodi.remove_episodes(list(old_episodes))

        # Scan for new episodes
        new_episodes = self.kodi.scan_directory(self.env.series_path, skip_active=self.cfg.library.skip_active)
        # Fall back to full library scan
        if not new_episodes and self.cfg.library.full_scan_fallback:
            new_episodes = self.kodi.scan_video_library(skip_active=self.cfg.library.skip_active)

        # Optionally, Clean Library
        if self.cfg.library.clean_after_update:
            self.kodi.clean_library()

        # Reapply metadata
        self.kodi.copy_ep_metadata(removed_episodes, new_episodes)

        # Update GUIs
        self.kodi.update_guis()

        # Notify clients
        if self.cfg.notifications.on_rename:
            notifications = []
            for episode in new_episodes:
                notifications.append(Notification(title="Sonarr - Renamed Episode", msg=episode))
            self.kodi.notify(notifications)

    def episode_delete(self) -> None:
        """Remove an episode"""
        self.log.info("Delete File Event Detected")
        # Ignore delete event if upgrade is pending
        deleted_reason = self.env.episode_file_delete_reason
        if deleted_reason.lower() == "upgrade":
            self.log.info("Ignoring this delete. It's part of an upgrade.")
            return

        # Get current data from library
        old_episodes = set()
        for path in self.env.episode_file_path:
            old_episodes.add(self.kodi.get_episodes_by_file(path))

        # Remove episodes from library
        removed_episodes = self.kodi.remove_episodes(list(old_episodes))

        # Optionally, Clean Library
        if self.cfg.library.clean_after_update:
            self.kodi.clean_library()

        # Update remaining guis
        self.kodi.update_guis()

        # Notify clients
        if self.cfg.notifications.on_delete:
            notifications = []
            for episode in removed_episodes:
                notifications.append(Notification(title="Sonarr - Deleted Episode", msg=episode))
            self.kodi.notify(notifications)

    def series_add(self) -> None:
        """Adding a Series"""
        self.log.info("Series Add Event Detected")

        if self.cfg.notifications.on_series_add:
            notification = Notification(
                title="Sonarr - Series Added", msg=f"{self.env.series_title} ({self.env.series_year})"
            )
            self.kodi.notify(notifications=[notification])

    def series_delete(self) -> None:
        """Deleting a Series"""
        self.log.info("Series Delete Event Detected")

        # Exit early if no files were deleted
        if not self.env.series_deleted_files:
            self.log.info("No files were deleted. Not editing library.")
            title = "Sonarr Deleted Show"
            msg = f"{self.env.series_title} ({self.env.series_year})"
            self.kodi.notify(title, msg)
            return

        # Get Current library data
        deleted_episodes = self.kodi.get_episodes_by_dir(self.env.series_path)

        # Remove episodes
        self.kodi.remove_episodes(deleted_episodes)

        # Remove Show
        self.kodi.remove_show(self.env.series_path)

        # Optionally, Clean Library
        if self.cfg.library.clean_after_update:
            self.kodi.clean_library()

        # Update GUIs
        self.kodi.update_guis()

        # Notify Clients
        if self.cfg.notifications.on_series_delete:
            notification = Notification(
                title="Sonarr Deleted Show", msg=f"{self.env.series_title} ({self.env.series_year})"
            )
            self.kodi.notify(notifications=[notification])

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
