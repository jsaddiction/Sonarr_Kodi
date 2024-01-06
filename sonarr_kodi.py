#!/usr/bin/env python

"""Sonarr Kodi Main Interface"""
import logging
import sys
from os import environ
from src import config_log
from src.kodi import KodiClient, ClientConfig
from src.environment import ENV, Events
from src.event_handler import EventHandler
from src.config import CFG, Config


def collect_hosts(cfg: Config, log: logging.Logger) -> list[KodiClient]:
    """Instantiate list of kodi hosts"""
    client_lst: list[KodiClient] = []
    log.info("Building Client list")
    for host in cfg.hosts:
        if not host.enabled:
            log.warning("Skipping disabled host: %s", host.name)
            continue
        client = KodiClient(
            ClientConfig(
                name=host.name,
                host=host.host,
                port=host.port,
                user=host.user,
                password=host.password,
                priority=host.priority,
                enabled=host.enabled,
            )
        )

        log.debug("Testing Connection with '%s'", host.name)
        if client.is_alive:
            client_lst.append(client)

    host_names = ", ".join([x.name for x in client_lst])
    log.info("Connection established with: [%s]", host_names)

    return client_lst


def main() -> None:
    """Main Entry Point"""
    config_log(CFG.logs)
    log = logging.getLogger("Sonarr-Kodi")
    log.info("Starting...")
    clients = collect_hosts(CFG, log)
    eh = EventHandler(ENV, CFG, clients)

    log.debug("=========Parsed Environment========")
    for k, v in environ.items():
        if "sonarr" not in k.lower():
            continue
        log.debug("%s=%s", k, v)
    log.debug("=========Parsed Environment========")

    if len(clients) == 0:
        log.critical("Unable to modify library. No active clients.")
        return

    match ENV.event_type:
        case Events.ON_GRAB:
            eh.grab()
        case Events.ON_DOWNLOAD:
            if ENV.is_upgrade:
                eh.download_upgrade()
            else:
                eh.download_new()
        case Events.ON_RENAME:
            eh.rename()
        case Events.ON_DELETE:
            eh.delete()
        case Events.ON_SERIES_ADD:
            eh.series_add()
        case Events.ON_SERIES_DELETE:
            eh.series_delete()
        case Events.ON_HEALTH_ISSUE:
            eh.health_issue()
        case Events.ON_HEALTH_RESTORED:
            eh.health_restored()
        case Events.ON_APPLICATION_UPDATE:
            eh.application_update()
        case Events.ON_MANUAL_INTERACTION_REQUIRED:
            eh.manual_interaction_required()
        case Events.ON_TEST:
            eh.test()
        case _:
            log.critical("Event type was unknown or could not be parsed")
            sys.exit(1)


if __name__ == "__main__":
    main()
