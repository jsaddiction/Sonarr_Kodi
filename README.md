# Sonarr_Kodi

### Manage Your Synchronized Kodi Library with Sonarr

This script will help maintain your library if all of the following are true:

- Operate at least one Kodi instance
- Do all instances share a Mariadb or Mysql database
- Content is added with Sonarr?

---

#### Why do I need this?

Sonarr employs a standard method to inform Kodi of changed library content configured in the "Connect" section. First, if downloaded episode is from a brand new show, a full library scan is conducted and an optional library clean command is sent. If the download is an episode for a show which already exists, the show's root directory is scanned to save execution time. While you can certainly configure Sonarr to initiate these commands to multiple hosts, inefficiencies arise. If you are managing multiple kodi instances, these problems are compounded.

Shared library systems is the way to go when you have more than one viewing station. With this topology, you only really need to scan directories once when adding content. Unfortunately, this is where the problems start with Sonarr.

For the rest of this section let's assume you have 3 devices with Kodi installed and they are all running a shared database.

##### Sonarr configured to manage only one device

A new episode is downloaded and Kodi is instructed to perform a scan on device "A". This device conducts all the steps to insert records into the database and then updates its own GUI (widgets and such). Finally, a notification is optionally sent to the device. If you happen to be sitting at device "B", you have no idea new content has been added unless you perform some action that causes the system to generate a new database query. Not great, but at least you haven't generated 1 write and 3 reads on the new episode by scanning all 3 hosts independently.

An additional problem arises which is less noticeable. What if host "A" was offline during the scan?
_Hint: Single point of failure._

What about episode file upgrades? I personally, don't appreciate an "upgraded" episode populating toward the top of a recently added list just because it was scanned in as a "new" episode. Of course devices "B" and "C" don't know about the change in the library so they won't show this misinformation, yet.

Sonarr's async design also means that commands sent to Kodi are not done in a specific order compared with metadata generation. _Wait, what?_

##### Sonarr adds metadata to episode.nfo and tvshow.nfo files

For this to function properly, Kodi's TVShow source must be configured for "local data only". This ensures all metadata for your shows and episodes come from the information Sonarr scrapes. This is ideal since metadata isn't downloaded for every instance of Kodi. During a scan however, Kodi assumes that a video file MUST be accompanied with this metadata. If not, Kodi just refuses to add anything to it's library. There is no metadata so Kodi has nothing to add.

---

#### Ok, now what?

This script is designed to intelligently manage these shortcomings with shared libraries. Any change Sonarr makes to the content initiates an update to the library in a fault tolerant and distributed way. Based the configuration, a collection of Kodi devices are defined to process the change. Downloads, upgrades, deletes etc. are handled step by step by the first available device. If a device goes offline during the process, it is skipped. Once a specific library operation completes, dateadded and watched state fields, if available, are applied to that content. Then all clients which have not performed a scan are instructed to scan a non-existent directory which forcefully updates it's GUI. Lastly, a notification can be sent to all available Kodi devices informing the user of this change. It will even stop an episode you are watching, process the upgrade, then restart it from where you left off.

---

### Features

- Manage a shared library in a redundant way
- Handles every event Sonarr emits
- Retains dateadded, lastplayed, playcount, resume fields while processing
- Stops and Replays any episodes being watched rather than letting Kodi's video player crash
- Notifications are configured by event and individual hosts can be disabled
- Writes WARNING level logs to stderr so Sonarr can display them in the events tab
- All log entries at or above the level configured are written similar to the Sonarr.txt logs
- Install script does all the hard work in Sonarr to configure the correct "connect" fields

---

#### Installation:

This script is designed as an extension of Sonarr. Specifically, the dockerized version established by [linuxserver.io](https://www.linuxserver.io/). There are many ways to run Sonarr and I can't possible handle each of them. As such [linuxserver.io Sonarr](https://hub.docker.com/r/linuxserver/sonarr) is the only one I can support.

MANUAL: (Not supported)

- Clone this script into a directory manually
- Install dependencies listed in requirements.txt
- Configure Sonarr to call it with EVERY event selected.
- Copy the default config in /src/config/default_config.yaml into the root directory of this repo and configure to your liking.

DOCKER: ([linuxserver.io Sonarr](https://hub.docker.com/r/linuxserver/sonarr))

- Create a directory and map it to `/config/custom-cont-init.d/`
- Download and place [script_init.sh](https://github.com/jsaddiction/Sonarr_Kodi/blob/main/script_init.sh) in `/config/custom-cont-init.d`
- Start the container
- Navigate to and edit `/config/scripts/Sonarr_Kodi/settings.yaml`

---

#### Configuration:

:exclamation: The default configuration defines the minimum required fields with the exception of `path_mapping` and it's children, which can be safely removed if your installation doesn't require it.

- `logs`
  - `level`: Can be one of `[DEBUG, INFO, WARNING, CRITICAL]`
  - `write_file`: Will write logs to the standard log directory and is visible in Sonarr's log file page
- `library`

  - `clean_after_update`: Perform a library clean after changes are made. Be sure Kodi's sources are configured appropriately
  - `skip_active`: Prevent library scans on devices which are currently playing
  - `full_scan_fallback`: Fallback to a full library scan if needed
  - `wait_for_nfo`: If Kodi's scraper is configured as "local data only" and Sonarr is configured to write nfo files, this script will wait for those files before proceeding
  - `nfo_timeout_minuets`: How long to wait for the nfo files before giving up
  - `path_map`: If your content's root paths are different, indicate that here. For example:
    Assuming the following paths relate to the same file on the two systems

    - Sonarr: `/mnt/media/tvshows/Some Show/Some Season/Some Episode.mkv`
    - Kodi: `/mnt/tvshows/Some Show/Some Season/Some Episode.mkv`

    You would then write:

    ```yaml
    path_map:
      - sonarr: /mnt/media/tvshows
        kodi: /mnt/tvshows
    ```

    - Simply, the path map replaces the Sonarr string with the kodi string. More than one path map can be defined. Some logic is applied to determine if your Kodi instance is on a POSIX operating system and adjusts paths accordingly. If you don't need path maps, remove the entire definition

- `notifications`: These settings enable/disable notifications for all Kodi instances
- `hosts`: This is where you define a list of Kodi devices. The default config shows only one defined host. You may define as many as you like.
  - `name`: The name used when referencing this host. Only effects logging
  - `host`: The IP address
  - `port`: The http port to use
  - `user`: The username of this instance
  - `password`: The password of this instance
  - `enabled`: Enable/Disable this instance
  - `priority`: Set a priority level. Useful if you want to prioritize wired clients

#### Wait there's more

All of your Kodi instances will require some configuration to allow this script to communicate.

**Setup a static ip assignment for each Kodi instance**
_Use one of the two following methods_

- Set a static ip within kodi's configuration outside your configured DHCP range
- Set a dhcp reservation within your router (preferred)

**System > Services > Control**

- Set a `Username` and `Password`
- Enable `Allow remote control via HTTP`
- Leave `Enable SSL` Disabled
- Enable `Allow remote control from applications on other systems`

---

#### Testing

Once you have gotten the install script to run using the `Docker` version install above, you should see a `Sonarr_Kodi` item within the `Settings > Connect` page of Sonarr. Click on it, then press the test button. If everything went well during install and you configured the `settings.yaml` you should see a notification displayed on your Kodi instances. Be sure to disable all other "connect" methods before attempting a download.
