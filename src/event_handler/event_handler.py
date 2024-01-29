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

    # ------------- Helpers --------------------
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
                    self.log.debug("Found %s", file.name)
                    files_found.add(file)

                # return false if we timed out
                elif elapsed.total_seconds() >= max_sec:
                    self.log.warning("Exceeded %s waiting for %s NFO files.", elapsed, len(nfos))
                    self.log.warning("Missing NFO files. [%s]", ", ".join(nfos))
                    return False

            sleep(delay)
        sec_per_nfo = int(elapsed.total_seconds() / len(nfos))
        self.log.info("All required NFO files were found after %s. %ss per file.", elapsed, sec_per_nfo)
        return True

    # ------------- Events -------------------------
    def grab(self) -> None:
        """Grab Events"""
        self.log.info("Grab Event Detected")

        # Skip notifications if disabled
        if not self.cfg.notifications.on_grab:
            self.log.info("Grab notifications disabled. Skipping.")
            return

        # Send notification for each attempted download
        title = "Sonarr - Attempting Download"
        for ep_num, ep_title in zip(self.env.release_episode_numbers, self.env.release_episode_titles):
            msg = f"{self.env.series_title} - S{self.env.release_season_number:02}E{ep_num:02} - {ep_title}"
            self.kodi.notify(Notification(title=title, msg=msg))

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

        # Skip notifications if disabled
        if not self.cfg.notifications.on_download_new:
            self.log.info("Download New Episode notifications disabled. Skipping.")
            return

        # Notify clients
        title = "Sonarr - Downloaded New Episode"
        for episode in new_episodes:
            self.kodi.notify(Notification(title=title, msg=episode))

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

        # Store library data for replaced episodes and remove those entries
        removed_episodes = []
        for path in self.env.deleted_paths:
            old_eps = self.kodi.get_episodes_by_file(path)
            for ep in old_eps:
                if self.kodi.remove_episode(ep):
                    removed_episodes.append(ep)

        # Force library clean if manual removal failed
        if not removed_episodes:
            self.log.warning("Failed to remove old episodes. Unable to persist watched states. Cleaning Required.")
            if not self.cfg.library.clean_after_update:
                self.kodi.clean_library(skip_active=self.cfg.library.skip_active, series_dir=self.env.series_path)

        # Scan show directory and fall back to full scan if configured
        new_episodes = self.kodi.scan_directory(self.env.series_path, skip_active=self.cfg.library.skip_active)
        if not new_episodes and self.cfg.library.full_scan_fallback:
            new_episodes = self.kodi.full_scan(skip_active=self.cfg.library.skip_active)

        # Optionally, Clean Library
        if self.cfg.library.clean_after_update:
            self.kodi.clean_library()

        # reapply metadata from old library entries
        self.kodi.copy_ep_metadata(removed_episodes, new_episodes)

        # update remaining guis
        self.kodi.update_guis()

        # Restart playback of previously stopped episode5
        for ep in new_episodes:
            self.kodi.start_playback(ep)

        # Skip notifications if disabled
        if not self.cfg.notifications.on_download_upgrade:
            self.log.info("Upgrade Episode notifications disabled. Skipping.")
            return

        # notify clients
        title = "Sonarr - Upgraded Episode"
        for episode in new_episodes:
            self.kodi.notify(Notification(title=title, msg=episode))

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

        # Store library data for replaced episodes and remove those entries
        removed_episodes = []
        for path in self.env.episode_file_previous_paths:
            old_eps = self.kodi.get_episodes_by_file(path)
            for ep in old_eps:
                # Stop Player
                self.kodi.stop_playback(ep, reason="Rename in progress. Please wait...")

                # Remove episode from library
                if self.kodi.remove_episode(ep):
                    removed_episodes.append(ep)

        if not removed_episodes:
            self.log.warning("Failed to remove old episodes. Unable to persist watched states. Cleaning Required.")
            if not self.cfg.library.clean_after_update:
                self.kodi.clean_library(skip_active=self.cfg.library.skip_active, series_dir=self.env.series_path)

        # Scan for new episodes
        new_episodes = self.kodi.scan_directory(self.env.series_path, skip_active=self.cfg.library.skip_active)

        # Fall back to full library scan
        if not new_episodes and self.cfg.library.full_scan_fallback:
            new_episodes = self.kodi.full_scan(skip_active=self.cfg.library.skip_active)

        # Optionally, Clean Library
        if self.cfg.library.clean_after_update:
            self.kodi.clean_library()

        # Reapply metadata
        self.kodi.copy_ep_metadata(removed_episodes, new_episodes)

        # Update GUIs
        self.kodi.update_guis()

        # Restart playback of previously stopped episode
        for ep in new_episodes:
            self.kodi.start_playback(ep)

        # Skip notifications if disabled
        if not self.cfg.notifications.on_rename:
            self.log.info("Rename Episode notifications disabled. Skipping.")
            return

        # Notify clients
        title = "Sonarr - Renamed Episode"
        for episode in new_episodes:
            self.kodi.notify(Notification(title=title, msg=episode))

    def episode_delete(self) -> None:
        """Remove an episode"""
        self.log.info("Delete File Event Detected")

        # Upgrades only. Stop playback and store data for restart after sonarr replaces file
        if self.env.episode_file_delete_reason.lower() == "upgrade":
            # Stop episodes that are currently playing
            for old_ep in self.kodi.get_episodes_by_file(self.env.episode_file_path):
                self.kodi.stop_playback(old_ep, reason="Processing Upgrade. Please Wait...")
            return

        # Store library data for removed episodes and remove those entries
        removed_episodes = []
        for old_ep in self.kodi.get_episodes_by_file(self.env.episode_file_path):
            # Stop Player
            self.kodi.stop_playback(old_ep, reason="Deleted Episode")

            # Remove episode from library
            if self.kodi.remove_episode(old_ep):
                removed_episodes.append(old_ep)

        if not removed_episodes:
            self.log.warning("Failed to remove any old episodes. Cleaning Required.")
            if not self.cfg.library.clean_after_update:
                self.kodi.clean_library(skip_active=self.cfg.library.skip_active, series_dir=self.env.series_path)

        # Optionally, Clean Library
        if self.cfg.library.clean_after_update:
            self.kodi.clean_library(skip_active=self.cfg.library.skip_active)

        # Update remaining guis
        self.kodi.update_guis()

        # Skip notifications if disabled
        if not self.cfg.notifications.on_delete:
            self.log.info("Delete Episode notifications disabled. Skipping.")
            return

        # Notify clients
        title = "Sonarr - Deleted Episode"
        for episode in removed_episodes:
            self.kodi.notify(Notification(title=title, msg=episode))

    def series_add(self) -> None:
        """Adding a Series"""
        self.log.info("Series Add Event Detected")

        # Skip notifications if disabled
        if not self.cfg.notifications.on_series_add:
            self.log.info("Series Add notifications disabled. Skipping.")
            return

        # Notify clients
        title = "Sonarr - Series Added"
        self.kodi.notify(Notification(title=title, msg=f"{self.env.series_title} ({self.env.series_year})"))

    def series_delete(self) -> None:
        """Deleting a Series"""
        self.log.info("Series Delete Event Detected")

        # Edit library only if files were deleted
        if self.env.series_deleted_files:
            # Remove Show
            self.kodi.remove_show(self.env.series_path)

            # Optionally, Clean Library
            if self.cfg.library.clean_after_update:
                self.kodi.clean_library()

            # Update GUIs
            self.kodi.update_guis()
        else:
            self.log.info("No files were deleted. Not editing library or sending notifications.")
            return

        # Skip notifications if disabled
        if not self.cfg.notifications.on_series_delete:
            self.log.info("Series Delete notifications disabled. Skipping.")
            return

        # Notify Clients
        title = "Sonarr Deleted Show"
        self.kodi.notify(Notification(title=title, msg=f"{self.env.series_title} ({self.env.series_year})"))

    def health_issue(self) -> None:
        """Experienced a Health Issue"""
        self.log.info("Health Issue Event Detected")

        # Skip notifications if disabled
        if not self.cfg.notifications.on_health_issue:
            self.log.info("Health Issue notifications disabled. Skipping.")
            return

        # Notify Clients
        title = "Sonarr - Health Issue"
        msg = self.env.health_issue_msg
        self.kodi.notify(Notification(title=title, msg=msg))

    def health_restored(self) -> None:
        """Health Restored"""
        self.log.info("Health Restored Event Detected")

        # Skip notifications if disabled
        if not self.cfg.notifications.on_health_restored:
            self.log.info("Health Restored notifications disabled. Skipping.")
            return

        # Notify Clients
        title = "Sonarr - Health Restored"
        msg = f"{self.env.health_restored_msg} Resolved"
        self.kodi.notify(Notification(title=title, msg=msg))

    def application_update(self) -> None:
        """Application Updated"""
        self.log.info("Application Update Event Detected")

        # Skip notifications if disabled
        if not self.cfg.notifications.on_application_update:
            self.log.info("Application Update notifications disabled. Skipping.")
            return

        # Notify Clients
        title = "Sonarr - Application Update"
        msg = self.env.update_message
        self.kodi.notify(Notification(title=title, msg=msg))

    def manual_interaction_required(self) -> None:
        """Manual Interaction Required"""
        self.log.info("Manual Interaction Event Detected")

        # Skip notifications if disabled
        if not self.cfg.notifications.on_manual_interaction_required:
            self.log.info("Manual Interaction Required notifications disabled. Skipping.")
            return

        # Notify Clients
        title = "Sonarr - Manual Interaction Required"
        msg = f"Sonarr needs help with {self.env.series_title} ({self.env.series_year})"
        self.kodi.notify(Notification(title=title, msg=msg))

    def test(self) -> None:
        """Sonarr Tested this script"""
        self.log.info("Test Event Detected")

        # Skip notifications if disabled
        if not self.cfg.notifications.on_test:
            self.log.info("Test notifications disabled. Skipping.")
            return

        # Notify Clients
        title = "Sonarr - Testing"
        msg = "Test Passed"
        self.kodi.notify(Notification(title=title, msg=msg))
