# Sonarr_Kodi

### - Manage Kodi Library with Sonarr -

Operating several database synchronized Kodi instances referencing the same content library driven by Sonarr is simplified with this script.

#### The problem:

Sonarr employs a standard method to inform Kodi of changed library content. This action initiates a scan on a single instance of Kodi. This works very well when each Kodi instance maintains it's own library or there is only to manage.

In systems that employ several Kodi instances that share the same library database over engines like MariaDb, the complications grow. Sonarr is not aware of shared library systems which is where these issues arise. For instance, it would make since to identify one Kodi device to handle all library transactions and instruct Sonarr to communicate with that device. With this architecture, other devices will not be aware of any library changes. Widgets do not update and notifications are not displayed leaving the user to either restart or trigger some sort of skin refresh action randomly to identify new content. Further, if this "master" device is offline, no library actions are taken and the user must manually scan for new content. The problem gets worse if content was upgraded based on quality or updates to ".nfo" files were made. Sonarr will remove the upgraded content and perform a scan on it's directory effectively resetting fields like "dateadded" or it's watched states. This becomes evident when sorting lists based on these attributes.

#### The Fix:

This script is designed to intelligently manage these shortcomings with shared libraries. Any change Sonarr makes to the content initiates this script to handle any needed updates to the library. Based on it's configuration, a collection of Kodi devices are defined to process the change. The first available Kodi device handles the specific Sonarr event such as downloads, upgrades, deletes etc. Once that operation completes, dateadded and watched state fields, if available, are applied to that content. Then the remaining clients are instructed to scan a non-existent directory which forcefully updates it's GUI. Lastly, based on configuration, a notification is sent to all available Kodi devices informing the user of this change.

#### Installation:

This script is designed as an extension of Sonarr. Specifically, the dockerized version established by [linuxserver.io](https://www.linuxserver.io/). There are many ways to run Sonarr and I can't possible handle each of them. As such [linuxserver.io Sonarr](https://hub.docker.com/r/linuxserver/sonarr) is the only one I can support.

- Create a directory and map it to `/config/custom-cont-init.d/`
- Download and place [script_init.sh](https://github.com/jsaddiction/Sonarr_Kodi/script_init.sh) in `/config/custom-cont-init.d`
- Start the container
- Navigate to and edit `/config/scripts/Sonarr_Kodi/settings.yaml`

#### Configuration:

:exclamation: If a default configuration is detected, this script will exit immediately.

:exclamation: The default configuration defines the minimum required fields with the exception of `path_mapping` and it's children, which can be safely removed.

- `logs`
  - `level`: Can be one of `[DEBUG, INFO, WARNING, CRITICAL]`
  - `write_file`: Will write logs to the standard log directory and is visible in Sonarr's log file page
- `library`
  - `clean_after_update`: Perform a library clean after changes are made. Be sure Kodi's sources are configured appropriately
  - `wait_for_nfo`: If Kodi's scraper is configured as "local data only" and Sonarr is configured to write nfo files, this script will wait for those files before proceeding
  - `nfo_timeout_minuets`: How long to wait for the nfo files before giving up
  - `update_while_playing`: Some underpowered devices do not perform library scans well while playing.
  - `path_map`: If your content's root paths are different, indicate that here. For example:
    Assuming the following paths relate to the same file on the two systems - Sonarr: `/mnt/media/tvshows/Some Show/Some Season/Some Episode.mkv` - Kodi: `/mnt/tvshows/Some Show/Some Season/Some Episode.mkv`
    - You would then write:
      ```yaml
      path_map:
          - sonarr: /mnt/media/tvshows
          kodi: /mnt/tvshows
      ```
    - Simply, the path map replaces the Sonarr string with the kodi string. More than one path map can be defined. If you don't need path maps, remove the entire definition
- `notifications`: These settings enable/disable notifications for all Kodi instances
- `hosts`: This is where you define a list of Kodi devices. The default config shows only one defined host. You may define as many as you like.
  - `name`: The name used when referencing this host. Only effects logging
  - `host`: The IP address
  - `port`: The http port to use
  - `user`: The username of this instance
  - `password`: The password of this instance
  - `enabled`: Enable/Disable this instance
  - `priority`: Set a priority level. Useful if you want to prioritize wired clients
