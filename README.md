# Media Server Dashboard

A dashboard for a macOS or Linux media server, plus a 3D office where your apps are the employees.

- **Dashboard** (`/`): CPU, memory, network and download graphs, service health, SABnzbd queue, drive space, recent movies and shows, and the next 14 days of releases.
- **Office** (`/office`): animated media-service workers, download parcels, recent-arrival posters, live data-center meters and graphs. The TV cycles through active Jellyfin sessions with artwork, viewer, device, title, progress and pause state.

Python 3 and its standard library handle the server. Three.js is bundled in `vendor/`. Media APIs are read on the server; credentials are never sent to the browser. Poster images come from your media services, TMDB and TheTVDB.

## Try it with made-up data

```sh
python3 server.py --demo
```

Open http://localhost:8900. Demo mode uses made-up data without reading your system or connecting to your media services.

## Run it for real

1. Install Python 3. On Linux, also install `iproute2`, `util-linux` and `iputils-ping` (Debian/Ubuntu package names).
2. Install any of Radarr, Sonarr, Prowlarr, Bazarr and SABnzbd on this machine, or expose their container ports on localhost. Missing apps are omitted.
3. Copy `config.example.json` to `config.json`. Set the paths to each app's settings file, which supplies its port, URL base and API key. The defaults are the usual macOS locations; Linux and Docker installations need their actual host paths.
4. Run `python3 server.py`, then open http://localhost:8900.

The dashboard process needs read access to the selected settings files and write access to its own directory for its password and session secret. Settings changes take effect after a restart.

### Select macOS or Linux monitoring

Set `system_platform` in `config.json`:

| Value | Collectors |
| --- | --- |
| `"auto"` (default) | Select Linux on Linux; otherwise retain the macOS collectors. |
| `"macos"` | macOS `iostat`, `vm_stat`, `netstat`, `df`, `lsof` and related tools. |
| `"linux"` | Linux `/proc` CPU, memory, network and disk counters; `findmnt` for disks, `ip` for routes and TCP checks for services. |

The switch selects all machine collectors, including **disk capacity and disk I/O**. It leaves the macOS implementation intact. Match an explicit override to the operating system you are running. Windows supports demo mode only.

Linux disk capacity includes local block devices and NFS/CIFS mounts, excludes squashfs/ISO images, and deduplicates bind mounts. Disk I/O measures whole physical/virtual block devices, excluding partitions and duplicate device-mapper counters; it does not measure NFS/CIFS throughput.

Example Linux configuration (adjust these paths to your installation):

```json
{
  "title": "Media Server Dashboard",
  "port": 8900,
  "system_platform": "auto",
  "radarr_config": "/opt/servarr/config/radarr/config.xml",
  "sonarr_config": "/opt/servarr/config/sonarr/config.xml",
  "prowlarr_config": "/opt/servarr/config/prowlarr/config.xml",
  "sabnzbd_config": "/opt/servarr/config/sabnzbd/sabnzbd.ini",
  "jellyfin_url": "http://jellyfin-server:8096",
  "jellyfin_key_file": "jellyfin-api-key"
}
```

### Connect Jellyfin

1. In Jellyfin, open **Dashboard → Advanced → API Keys** and create a key for this dashboard. You can also reuse an existing integration key that you control.
2. Save just the key in `jellyfin-api-key` beside `server.py`. Restrict access to the account running the dashboard (`chmod 600 jellyfin-api-key` on macOS/Linux).
3. Set `jellyfin_url` to the Jellyfin base URL reachable from the dashboard server, including any configured URL prefix. Set `jellyfin_key_file` to the key file; relative paths are resolved beside `server.py`, and absolute paths and `~` are supported.
4. Restart the dashboard and refresh `/office`.

Jellyfin can run on another machine. The server polls its read-only `/Sessions` endpoint every five seconds. The TV shows one session at a time, automatically advancing every eight seconds; click the TV to advance manually. Separate sessions for the same user remain separate slides. Long titles scroll, and paused sessions remain visible with a paused label. Playback controls are not sent to Jellyfin.

Artwork is fetched through an authenticated dashboard endpoint, using the current item's primary image with series/parent image fallback. The key stays on the server. Images are limited to active items, cached in bounded memory, and shown with a placeholder when unavailable. When no session is playing the TV says so; connection failures clear stale playback and show an unavailable message. Jellyfin watch history is not collected.

Leaving `jellyfin_url` empty disables this integration. The original Home Cinema integration remains available through `home_cinema_dir`; configuring Jellyfin takes precedence over Home Cinema for playback display.

### Start automatically

On **macOS**, `./install.sh` installs a launchd agent for your user. `./uninstall.sh` removes it.

On **Linux with systemd**, create `/etc/systemd/system/media-server-dashboard.service`, substituting your username and the absolute installation directory:

```ini
[Unit]
Description=Media Server Dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=YOUR_USER
WorkingDirectory=/absolute/path/media-server-dashboard
ExecStart=/usr/bin/python3 /absolute/path/media-server-dashboard/server.py
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Enable with `sudo systemctl daemon-reload` and `sudo systemctl enable --now media-server-dashboard`. Inspect logs with `journalctl -u media-server-dashboard`. To remove startup, run `sudo systemctl disable --now media-server-dashboard`, remove the unit file and run `sudo systemctl daemon-reload`.

## Opening it from other devices

Open `http://<server-address>:8900` on your home network. Other devices need the generated password in `password.txt`. Change that file to change the password and invalidate existing sessions. Loopback requests using localhost or 127.0.0.1 do not need a password.

Do not expose the port to the internet; this is a home-network dashboard.

## Privacy and notes

- `config.json`, `jellyfin-api-key`, `password.txt`, `.secret` and logs are ignored by Git. If you choose another key filename, add it to `.gitignore` yourself.
- API credentials remain server-side; artwork URLs contain item identifiers only.
- Graph history and artwork caches live in memory. Password and session-secret files persist on disk.
- Network meters read full at 100 Mbit/s.
- Three.js and this project are MIT licensed.

## License

MIT

## Tests

Run `python3 -m unittest -v test_support` for platform selection, disk filtering and Jellyfin session handling. Platform-selection tests check collector routing for both operating systems; they do not substitute for running the collectors on real macOS hardware.
