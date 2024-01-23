#!/usr/bin/env python

"""Sonarr Kodi Main Interface"""
import logging
import sys
from os import environ
from pathlib import Path
from src import config_log
from src.config import ConfigParser
from src.kodi import LibraryManager
from src.environment import ENV, Events
from src.event_handler import EventHandler

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "settings.yaml"


def main() -> None:
    """Main Entry Point"""
    cfg_parser = ConfigParser()
    cfg = cfg_parser.get_config(CONFIG_PATH)
    config_log(cfg.logs)
    log = logging.getLogger("Sonarr-Kodi")
    if cfg_parser.is_default(cfg):
        log.warning("Default config file detected. Please EDIT %s", CONFIG_PATH)
        sys.exit(0)
    log.info("Starting...")
    kodi = LibraryManager(cfg.hosts, cfg.library.path_mapping)
    event_handler = EventHandler(ENV, cfg, kodi)

    log.debug("=========Parsed Environment========")
    for k, v in environ.items():
        if "sonarr" not in k.lower():
            continue
        log.debug("%s=%s", k, v)
    log.debug("=========Parsed Environment========")

    if len(kodi.hosts) == 0:
        log.critical("Unable to modify library. No active Kodi Hosts.")
        return

    match ENV.event_type:
        case Events.ON_GRAB:
            event_handler.grab()
        case Events.ON_DOWNLOAD:
            if ENV.is_upgrade:
                event_handler.download_upgrade()
            else:
                event_handler.download_new()
        case Events.ON_RENAME:
            event_handler.rename()
        case Events.ON_DELETE:
            event_handler.episode_delete()
        case Events.ON_SERIES_ADD:
            event_handler.series_add()
        case Events.ON_SERIES_DELETE:
            event_handler.series_delete()
        case Events.ON_HEALTH_ISSUE:
            event_handler.health_issue()
        case Events.ON_HEALTH_RESTORED:
            event_handler.health_restored()
        case Events.ON_APPLICATION_UPDATE:
            event_handler.application_update()
        case Events.ON_MANUAL_INTERACTION_REQUIRED:
            event_handler.manual_interaction_required()
        case Events.ON_TEST:
            event_handler.test()
        case _:
            log.critical("Event type was unknown or could not be parsed :: %s", ENV.event_type)
            sys.exit(1)

    log.info("Processing Complete")


if __name__ == "__main__":
    main()
