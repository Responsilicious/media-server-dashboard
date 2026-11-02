# Media Server Dashboard

A dashboard for a Mac that runs a media server, plus a 3D office where your apps are the employees.

- **Dashboard** (`/`): CPU, memory, network and download graphs, which services are running (hover one to see what's wrong), the SABnzbd queue, drive space, recently added movies and shows, and what's coming up in the next 14 days.
- **Office** (`/office`): Radarr, Sonarr, Prowlarr, Bazarr and SABnzbd sit at their desks while they're working and wander off to the break room when they're idle. Hover a worker to see what they're doing. A pile of parcels grows with the download queue, the newest arrivals hang as posters on the wall, the data center racks light up with CPU, memory, network and drive use, and a whiteboard shows the live graphs.

Everything runs on your Mac. It needs nothing beyond the Python that comes with macOS: no installs, no accounts, no analytics, and it doesn't phone home. The only outside requests are the poster images from TMDB and TheTVDB that Radarr and Sonarr already point to.

## Try it with made-up data

```bash
python3 server.py --demo
```

Then open http://localhost:8900. Demo mode reads nothing from your Mac, which also makes it the safe way to take screenshots.

## Run it for real

1. Install any of [Radarr](https://radarr.video), [Sonarr](https://sonarr.tv), [Prowlarr](https://prowlarr.com), [Bazarr](https://www.bazarr.media) and [SABnzbd](https://sabnzbd.org) on the same Mac. Apps that aren't installed are simply left out.
2. Start the dashboard:
   ```bash
   python3 server.py
   ```
3. Open http://localhost:8900.

The dashboard finds each app's port and API key in that app's own settings file, in the usual macOS places. If yours live somewhere else, copy `config.example.json` to `config.json` and change the paths. You can also change the title and the port there.

### Start it automatically

```bash
./install.sh
```

This adds a launchd agent so the dashboard starts when you log in and restarts if it stops. `./uninstall.sh` removes it again.

## Opening it from other devices

The dashboard listens on your local network, so you can open `http://<your-mac's-name>.local:8900` from a phone or PC. Other devices need the password in `password.txt`. A random one is created on first run; change the file to set your own. The Mac itself doesn't need a password.

Don't expose the port to the internet. It's meant for your home network only.

## What stays private

- API keys are read on the server and never sent to the browser.
- `config.json`, `password.txt`, `.secret` and the log are in `.gitignore`, so they never end up in a fork or pull request.
- Nothing is stored apart from five minutes of graph history in memory.

## Notes

- macOS only: it reads system stats with `iostat`, `vm_stat`, `netstat`, `df` and `lsof`.
- The network meters on the racks and the whiteboard read full at 100 Mbit/s.
- There is a hidden integration for "Home Cinema", the author's own player, which drives the "who's watching" TV in the break room. It stays off unless `home_cinema_dir` is set. Plex or Jellyfin support would be a welcome contribution.
- The 3D office uses [three.js](https://threejs.org) (MIT), bundled in `vendor/`.

## License

MIT
