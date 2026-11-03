#!/usr/bin/python3
"""Media server dashboard and 3D office for a Mac. Standard library only.

Watches the machine and the apps on it strictly from the outside: system tools and each app's own API
(Radarr, Sonarr, Prowlarr, Bazarr, SABnzbd). Other devices on the network need the password in password.txt;
this Mac itself doesn't. API keys stay in here; only the fields picked out below reach the browser.

    python3 server.py          watch this Mac
    python3 server.py --demo   made-up data, for trying it out or taking screenshots
"""
import hashlib
import hmac
import html
import http.cookies
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
DEMO = "--demo" in sys.argv


def _settings():
    """config.json next to this file, if there is one. Every setting is optional; see config.example.json."""
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


CONFIG = _settings()
SYSTEM_PLATFORM = CONFIG.get("system_platform", "auto")
if SYSTEM_PLATFORM == "auto":
    SYSTEM_PLATFORM = "linux" if sys.platform.startswith("linux") else "macos"
if SYSTEM_PLATFORM not in ("linux", "macos"):
    raise ValueError('system_platform must be "auto", "linux" or "macos"')
where = lambda key, default: os.path.expanduser(CONFIG.get(key) or default)
PORT = int(CONFIG.get("port") or 8900)
TITLE = CONFIG.get("title") or "Media Server Dashboard"
# The usual places each app keeps its settings on a Mac; config.json can point somewhere else.
RADARR_XML = where("radarr_config", "~/Library/Application Support/Radarr/config.xml")
SONARR_XML = where("sonarr_config", "~/.config/Sonarr/config.xml")
PROWLARR_XML = where("prowlarr_config", "~/Library/Application Support/Prowlarr/config.xml")
BAZARR_YAML = where("bazarr_config", "/Applications/bazarr/data/config/config.yaml")
SAB_INI = where("sabnzbd_config", "~/Library/Application Support/SABnzbd/sabnzbd.ini")
# Home Cinema is the author's own player; leave this out of config.json and that part simply stays hidden.
CINEMA = os.path.expanduser(CONFIG["home_cinema_dir"]) if CONFIG.get("home_cinema_dir") else None

PASSWORD_FILE = os.path.join(HERE, "password.txt")  # change it any time; it applies straight away and signs everyone out
SECRET_FILE = os.path.join(HERE, ".secret")
VENDOR = {"/vendor/three.module.min.js": "three.module.min.js", "/vendor/OrbitControls.js": "OrbitControls.js", "/vendor/RoundedBoxGeometry.js": "RoundedBoxGeometry.js"}  # the 3D office's library, served as-is
POSTER_HOSTS = ("https://image.tmdb.org/", "https://artworks.thetvdb.com/")
poster_cache = {}
MAX_ATTEMPTS = 8
LOCKOUT = 5 * 60

TICK = 2            # seconds between system samples
KEEP = 150          # samples kept: 5 minutes
VIDEO = (".mkv", ".mp4", ".avi", ".m4v", ".mov", ".mpg", ".ts", ".wmv")
WATCHING_WINDOW = 90 * 1000  # Home Cinema saves progress while playing, so a save this recent means it is on now

history = {k: deque(maxlen=KEEP) for k in ("t", "cpu", "mem", "rx", "tx", "disk", "sab")}
state = {"system": {}, "services": [], "cinema": {}, "sab": {"ok": False}, "radarr": {"ok": False}, "sonarr": {"ok": False}, "prowlarr": {"ok": False}, "bazarr": {"ok": False}, "activity": {}, "network": {}, "disks": []}


def sh(*args, timeout=5):
    try:
        return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def sysctl(name):
    return sh("/usr/sbin/sysctl", "-n", name).strip()


def get_json(url, headers=None, timeout=6):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=timeout) as r:
        return json.load(r)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def arr_config(path):
    try:
        with open(path, encoding="utf-8") as f:
            xml = f.read()
    except OSError:
        return None
    tag = lambda n: (re.search(f"<{n}>(.*?)</{n}>", xml) or [None, ""])[1]
    return {"port": int(tag("Port") or 0), "key": tag("ApiKey"), "base": tag("UrlBase")}


def bazarr_config():
    try:
        with open(BAZARR_YAML, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        return None
    def val(section, name):
        body = (re.search(rf"^{section}:\n(.*?)(?=^\S|\Z)", txt, re.M | re.S) or [None, ""])[1]
        return (re.search(rf"^\s+{name}: *(.*)$", body, re.M) or [None, ""])[1].strip().strip("'\"")
    return {"port": int(val("general", "port") or 6767), "key": val("auth", "apikey"), "base": val("general", "base_url").rstrip("/")}


def sab_config():
    try:
        with open(SAB_INI, encoding="utf-8") as f:
            txt = f.read()
    except OSError:
        return None
    val = lambda n: (re.search(rf"^{n} *= *(.*)$", txt, re.M) or [None, ""])[1].strip().strip('"')
    return {"port": int(val("port") or 8080), "key": val("api_key"), "base": val("url_base").rstrip("/")}


# ---------- the machine, every couple of seconds ----------
net_last = {}


def sample_network():
    rx = tx = 0
    for line in sh("/usr/sbin/netstat", "-ibn").splitlines():
        p = line.split()
        if len(p) >= 10 and re.fullmatch(r"en\d+\*?", p[0]) and p[2].startswith("<Link#"):
            rx += int(p[-5])
            tx += int(p[-2])
    now = time.time()
    rates = (0, 0)
    if net_last and now > net_last["t"]:
        dt = now - net_last["t"]
        rates = (max(0, rx - net_last["rx"]) / dt, max(0, tx - net_last["tx"]) / dt)
    net_last.update(t=now, rx=rx, tx=tx)
    return rates


def sample_memory():
    out = sh("/usr/bin/vm_stat")
    size = int((re.search(r"page size of (\d+)", out) or [0, 4096])[1])
    pages = lambda n: int((re.search(n + r":\s+(\d+)", out) or [0, 0])[1])
    total = int(sysctl("hw.memsize") or 1)
    used = (pages("Pages active") + pages("Pages wired down") + pages("Pages occupied by compressor")) * size
    swap = re.search(r"total = ([\d.]+)M\s+used = ([\d.]+)M", sysctl("vm.swapusage"))
    return {
        "total": total, "used": used,
        "free_level": int(sysctl("kern.memorystatus_level") or 100),
        "swap_total": float(swap[1]) * 1048576 if swap else 0,
        "swap_used": float(swap[2]) * 1048576 if swap else 0,
    }


def system_loop():
    while True:
        started = time.time()
        # A one second iostat run gives CPU, disk speed and load in one go. Its last line is the live one.
        last = [ln.split() for ln in sh("/usr/sbin/iostat", "-n", "1", "-w", "1", "-c", "2").splitlines() if re.match(r"\s*[\d.]+\s", ln)]
        if last and len(last[-1]) >= 9:
            v = [float(x) for x in last[-1][-9:]]
            disk_mb, us, sy, idle, l1, l5, l15 = v[2], v[3], v[4], v[5], v[6], v[7], v[8]
            mem = sample_memory()
            rx, tx = sample_network()
            history["t"].append(int(time.time() * 1000))
            history["cpu"].append(round(100 - idle))
            history["mem"].append(round(mem["used"] / mem["total"] * 100, 1))
            history["rx"].append(round(rx))
            history["tx"].append(round(tx))
            history["disk"].append(disk_mb * 1048576)
            history["sab"].append(state["sab"].get("speed", 0))
            state["system"].update(cpu={"user": us, "system": sy, "idle": idle}, load=[l1, l5, l15], memory=mem)
        time.sleep(max(0.1, TICK - (time.time() - started)))


def looped(every, fn):
    def run():
        while True:
            try:
                fn()
            except Exception as e:  # one bad reading must not stop the dashboard
                print(f"{fn.__name__}: {type(e).__name__}", flush=True)
            time.sleep(every)
    threading.Thread(target=run, daemon=True).start()


def read_static():
    boot = re.search(r"sec = (\d+)", sysctl("kern.boottime"))
    state["system"].update(
        host=socket.gethostname().replace(".local", ""),
        cpu_name=sysctl("machdep.cpu.brand_string"), cores=int(sysctl("hw.logicalcpu") or 1),
        macos=sh("/usr/bin/sw_vers", "-productVersion").strip(), model=sysctl("hw.model"),
        booted=int(boot[1]) * 1000 if boot else None,
    )


def read_disks():
    disks = {}
    for ln in sh("/bin/df", "-kl").splitlines()[1:]:
        m = re.match(r"(\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+\d+%.*?\d+%\s+(/.*)$", ln)
        if not m or int(m[2]) < 1048576:  # skips mounted installers and the like
            continue
        mount = m[5]
        if mount == "/System/Volumes/Data":
            name = "Macintosh HD"
        elif mount.startswith("/Volumes/"):
            name = mount[9:]
        else:
            continue
        disks[name] = {"name": name, "total": int(m[2]) * 1024, "free": int(m[4]) * 1024}
    state["disks"] = list(disks.values())


def read_network():
    route = sh("/sbin/route", "-n", "get", "default")
    iface = (re.search(r"interface: (\S+)", route) or [None, ""])[1]
    lan = ""
    for i in ("en0", "en1", "en2"):
        lan = sh("/usr/sbin/ipconfig", "getifaddr", i).strip()
        if lan:
            break
    ping = sh("/sbin/ping", "-c", "1", "-t", "2", "1.1.1.1", timeout=4)
    ms = re.search(r"time=([\d.]+)", ping)
    state["network"] = {"lan": lan, "vpn": iface.startswith("utun"), "online": bool(ms), "ping": float(ms[1]) if ms else None}
    speed = re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", sh("/usr/bin/pmset", "-g", "therm"))
    state["system"]["speed_limit"] = int(speed[1]) if speed else 100


# ---------- apps ----------
def cinema_config():
    return (read_json(os.path.join(CINEMA, "config.json")) or {}) if CINEMA else {}


def read_services():
    """Is each app listening on its port?"""
    wanted = {"Home Cinema": cinema_config().get("port", 8765)} if CINEMA else {}
    for name, c in (("Radarr", arr_config(RADARR_XML)), ("Sonarr", arr_config(SONARR_XML)), ("Bazarr", bazarr_config()), ("Prowlarr", arr_config(PROWLARR_XML))):
        if c:
            wanted[name] = c["port"]
    sab = sab_config()
    if sab:
        wanted["SABnzbd"] = sab["port"]
    listening = {int(p) for p in re.findall(r":(\d+) \(LISTEN\)", sh("/usr/sbin/lsof", "-nP", "-iTCP", "-sTCP:LISTEN"))}
    state["services"] = [{"name": n, "up": port in listening} for n, port in wanted.items()]


def titles():
    """Home Cinema ids to names: its library cache has everything on connected drives, its poster cache has the rest."""
    known = {}
    if not CINEMA:
        return known, {}
    meta = read_json(os.path.join(CINEMA, "data/metadata.json")) or {}
    for k, v in meta.items():
        if isinstance(v, dict) and v.get("title"):
            known[k] = {"title": v["title"], "year": v.get("year")}
    lib = read_json(os.path.join(CINEMA, "data/library-cache.json")) or {}
    files = {}
    for m in lib.get("movies", []):
        known[m["id"]] = {"title": m["title"], "year": m.get("year")}
        for p in m.get("parts", []):
            files[p.get("file")] = known[m["id"]]
    for s in lib.get("shows", []):
        for e in s.get("episodes", []):
            label = f"{s['title']} S{e.get('season', 0):02d}E{e.get('episode') or 0:02d}"
            known[e["id"]] = {"title": label, "year": None}
            files[e.get("file")] = known[e["id"]]
    return known, files


def read_cinema():
    if not CINEMA:
        state["cinema"] = {"enabled": False, "profiles": [], "streams": [], "watched": [], "missing_drives": []}
        return
    cfg = cinema_config()
    port = cfg.get("port", 8765)
    known, files = titles()

    now = time.time() * 1000
    watched = []
    for prof in cfg.get("profiles", []):
        pid = re.sub(r"[^a-z0-9]+", "-", str(prof.get("id") or prof.get("name")).lower())
        for key, v in (read_json(os.path.join(CINEMA, f"data/progress-{pid}.json")) or {}).items():
            if not isinstance(v, dict) or not v.get("updated"):
                continue
            t = known.get(key)
            if not t:
                continue
            watched.append({"who": prof.get("name"), "title": t["title"], "year": t["year"], "pct": round(v.get("pct", 0) * 100), "when": v["updated"], "now": now - v["updated"] < WATCHING_WINDOW})
    watched.sort(key=lambda x: -x["when"])

    # Which video files the server and its ffmpeg have open.
    listener = sh("/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t").split()
    ffmpeg = sh("/usr/bin/pgrep", "-f", os.path.join(CINEMA, "ffmpeg/bin/ffmpeg")).split()
    # Other services (Bazarr) borrow Home Cinema's ffmpeg; name them by the program that started the ffmpeg.
    service = {}
    for pid in ffmpeg:
        parent = sh("/bin/ps", "-o", "command=", "-p", sh("/bin/ps", "-o", "ppid=", "-p", pid).strip())
        if "bazarr" in parent.lower():
            service[pid] = "Bazarr"
    open_files = {}
    if listener or ffmpeg:
        pid = None
        for ln in sh("/usr/sbin/lsof", "-nP", "-Fpn", "-p", ",".join(listener + ffmpeg)).splitlines():
            if ln.startswith("p"):
                pid = ln[1:]
            elif ln.startswith("n") and ln.lower().endswith(VIDEO):
                open_files.setdefault(ln[1:], service.get(pid))
    # Progress saves say who is watching; an open file with no recent save is on, but by someone unknown.
    streams = [{"title": w["title"], "who": w["who"], "pct": w["pct"]} for w in watched if w["now"]]
    for title, svc in sorted({(files.get(f) or {"title": os.path.basename(f)})["title"]: s for f, s in open_files.items()}.items()):
        if not any(st["title"] == title for st in streams):
            streams.append({"title": title, "service": svc})

    try:
        status = get_json(f"http://127.0.0.1:{port}/api/status", timeout=3)
    except (OSError, ValueError):
        status = {}

    missing = []
    for path in cfg.get("movieDirs", []) + cfg.get("showDirs", []):
        m = re.match(r"/Volumes/([^/]+)", path)
        if m and not os.path.isdir(path) and m[1] not in missing:
            missing.append(m[1])

    state["cinema"] = {"enabled": True, "ok": bool(status), "converting": len(ffmpeg), "profiles": [p.get("name") for p in cfg.get("profiles", [])], "streams": streams, "watched": watched[:5], "missing_drives": missing}


def poster(item):
    for img in item.get("images", []):
        if img.get("coverType") == "poster" and str(img.get("remoteUrl", "")).startswith("https://"):
            return img["remoteUrl"]
    return None


arr_slow = {}


def read_arr(kind, path):
    c = arr_config(path)
    if not c:
        return
    movies = kind == "radarr"
    def get(p):
        return get_json(f"http://127.0.0.1:{c['port']}{c['base']}/api/v3/{p}", {"X-Api-Key": c["key"]})
    include = "includeMovie=true" if movies else "includeSeries=true&includeEpisode=true"
    try:
        slow = arr_slow.get(kind)
        if not slow or time.time() - slow["at"] > 60:
            start = datetime.now(timezone.utc)
            end = start + timedelta(days=14)
            fmt = "%Y-%m-%dT%H:%M:%SZ"
            slow = {
                "at": time.time(), "status": get("system/status"), "health": get("health"), "roots": get("rootfolder"),
                "missing": get("wanted/missing?pageSize=1"),
                "items": get("movie" if movies else "series"),
                "history": get(f"history?pageSize=8&eventType=3&sortKey=date&sortDirection=descending&{include}"),
                "calendar": get(f"calendar?start={start.strftime(fmt)}&end={end.strftime(fmt)}" + ("" if movies else "&includeSeries=true")),
            }
            arr_slow[kind] = slow
    except (OSError, ValueError, urllib.error.URLError):
        state[kind] = {"ok": False}
        arr_slow.pop(kind, None)
        return

    ep = lambda e: f"S{e.get('seasonNumber', 0):02d}E{e.get('episodeNumber', 0):02d}"

    items = slow["items"]
    if movies:
        have = [m for m in items if m.get("hasFile")]
        have.sort(key=lambda m: (m.get("movieFile") or {}).get("dateAdded") or m.get("added") or "", reverse=True)
        recent = [{
            "title": m.get("title"), "year": m.get("year"), "poster": poster(m), "size": m.get("sizeOnDisk", 0),
            "quality": ((m.get("movieFile") or {}).get("quality") or {}).get("quality", {}).get("name"),
            "when": (m.get("movieFile") or {}).get("dateAdded") or m.get("added"),
        } for m in have[:8]]
        library = {"total": len(items), "have": len(have), "size": sum(m.get("sizeOnDisk", 0) for m in items)}
    else:
        stat = lambda s, k: (s.get("statistics") or {}).get(k, 0)
        recent = [{
            "title": (h.get("series") or {}).get("title") or h.get("sourceTitle"),
            "sub": ep(h["episode"]) + " " + h["episode"].get("title", "") if h.get("episode") else "",
            "poster": poster(h.get("series") or {}),
            "quality": ((h.get("quality") or {}).get("quality") or {}).get("name"), "when": h.get("date"),
        } for h in slow["history"].get("records", [])]
        library = {"total": len(items), "have": sum(stat(s, "episodeFileCount") for s in items), "episodes": sum(stat(s, "episodeCount") for s in items), "size": sum(stat(s, "sizeOnDisk") for s in items)}

    upcoming = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for c2 in slow["calendar"]:
        if c2.get("hasFile"):
            continue
        if movies:
            when = next((d for d in (c2.get("digitalRelease"), c2.get("physicalRelease"), c2.get("inCinemas")) if d and d >= now), None)
            if when:
                upcoming.append({"kind": "Movie", "title": c2.get("title"), "when": when})
        elif c2.get("airDateUtc"):
            upcoming.append({"kind": "Episode", "title": f"{(c2.get('series') or {}).get('title', '')} {ep(c2)}".strip(), "when": c2["airDateUtc"]})

    state[kind] = {
        "ok": True, "version": slow["status"].get("version"), "library": library, "missing": slow["missing"].get("totalRecords", 0),
        "recent": recent, "upcoming": upcoming,
        "health": [{"level": h.get("type"), "message": h.get("message")} for h in slow["health"]],
        "roots": [{"path": r.get("path"), "ok": r.get("accessible", True)} for r in slow["roots"]],
    }


def read_radarr():
    read_arr("radarr", RADARR_XML)


def read_sonarr():
    read_arr("sonarr", SONARR_XML)


def read_prowlarr():
    c = arr_config(PROWLARR_XML)
    if not c:
        return
    def get(p):
        return get_json(f"http://127.0.0.1:{c['port']}{c['base']}/api/v1/{p}", {"X-Api-Key": c["key"]})
    try:
        indexers = get("indexer")
        state["prowlarr"] = {
            "ok": True, "version": get("system/status").get("version"), "indexers": len(indexers),
            "enabled": sum(1 for i in indexers if i.get("enable")),
            "health": [{"level": h.get("type"), "message": h.get("message")} for h in get("health")],
        }
    except (OSError, ValueError, urllib.error.URLError):
        state["prowlarr"] = {"ok": False}


def read_bazarr():
    c = bazarr_config()
    if not c:
        return
    try:
        health = get_json(f"http://127.0.0.1:{c['port']}{c['base']}/api/system/health", {"X-API-KEY": c["key"]})["data"]
        state["bazarr"] = {"ok": True, "health": [{"level": "warning", "message": f"{h.get('object')}: {h.get('issue')}"} for h in health]}
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        state["bazarr"] = {"ok": False}


def utc_ms(text):
    return datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000


download_titles = {}  # SABnzbd download id -> the movie or episode it is, from Radarr and Sonarr
download_owner = {}  # SABnzbd download id -> "Radarr" or "Sonarr"


def read_activity():
    """What Radarr, Sonarr, Prowlarr and Bazarr are busy with right now, for the office."""
    act, titles, owner = {}, {}, {}
    for name, path, v in (("Radarr", RADARR_XML, "v3"), ("Sonarr", SONARR_XML, "v3"), ("Prowlarr", PROWLARR_XML, "v1")):
        c = arr_config(path)
        if not c:
            continue
        def get(p):
            return get_json(f"http://127.0.0.1:{c['port']}{c['base']}/api/{v}/{p}", {"X-Api-Key": c["key"]})
        try:
            jobs = [x.get("commandName") or x.get("name") for x in get("command") if x.get("status") in ("started", "queued")]
            if name == "Prowlarr":
                last = (get("history?pageSize=1&sortKey=date&sortDirection=descending").get("records") or [None])[0]
                if not jobs and last and time.time() * 1000 - utc_ms(last["date"]) < 90 * 1000:
                    query = (last.get("data") or {}).get("query")
                    jobs = [f"Searching for {query}" if query else "Checking RSS feeds"]
            else:
                # Their queue says which movie or episode each download is, so SABnzbd's file names can be shown properly.
                q = get("queue?pageSize=500&" + ("includeMovie=true" if name == "Radarr" else "includeSeries=true&includeEpisode=true"))
                for r in q.get("records", []):
                    if r.get("downloadId"):
                        titles[r["downloadId"].lower()] = nice_title(r, name == "Radarr")
                        owner[r["downloadId"].lower()] = name
                waiting = q.get("totalRecords", 0)
                if waiting and not jobs:
                    jobs = [f"Waiting on {waiting} download{'s' if waiting > 1 else ''}"]
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            continue
        act[name] = jobs[0] if jobs else None
    b = bazarr_config()
    if b:
        try:
            tasks = get_json(f"http://127.0.0.1:{b['port']}{b['base']}/api/system/tasks", {"X-API-KEY": b["key"]})["data"]
            act["Bazarr"] = next((t["name"] for t in tasks if t.get("job_running")), None)
        except (OSError, ValueError, KeyError, urllib.error.URLError):
            pass
    state["activity"] = act
    download_titles.clear()
    download_titles.update(titles)
    download_owner.clear()
    download_owner.update(owner)


def up_next(name, n=5):
    """The next downloads in SABnzbd's order, for the popup on a service box. Radarr and Sonarr get only their own."""
    if name not in ("SABnzbd", "Radarr", "Sonarr"):
        return []
    sab = state["sab"]
    out = []
    for s in sab.get("queue", []) if sab.get("ok") else []:
        sid = (s.get("id") or "").lower()
        if name != "SABnzbd" and download_owner.get(sid) != name:
            continue
        out.append({"title": download_titles.get(sid) or tidy(s["title"]), "pct": round(s["pct"]), "size": s.get("size")})
        if len(out) == n:
            break
    return out


def nice_title(r, movie):
    if movie:
        m = r.get("movie") or {}
        return f"{m['title']} ({m['year']})" if m.get("title") and m.get("year") else m.get("title") or tidy(r.get("title", ""))
    series, ep = r.get("series") or {}, r.get("episode") or {}
    if series.get("title") and ep:
        return f"{series['title']} S{ep.get('seasonNumber', 0):02d}E{ep.get('episodeNumber', 0):02d}"
    return tidy(r.get("title", ""))


def tidy(name):
    """A release file name made readable: 'Atlantis.The.Lost.Empire.2001.1080p...' becomes 'Atlantis The Lost Empire (2001)'."""
    n = re.sub(r"[._]+", " ", name).strip()
    ep = re.match(r"(.+?)\s+(S\d\d?E\d\d?)\b", n, re.I)
    if ep:
        return f"{ep[1].strip()} {ep[2].upper()}"
    year = re.match(r"(.+?)\s*[\(\[]?((?:19|20)\d\d)[\)\]]?(?:\s|$)", n)
    return f"{year[1].strip()} ({year[2]})" if year else n


def activity(name):
    """The task an app is busy with, or None when it has nothing to do."""
    if name == "SABnzbd":
        sab = state["sab"]
        if not sab.get("ok") or sab["paused"] or not (sab["speed"] > 0 or sab["queueTotal"]):
            return None
        top = sab["queue"][0] if sab["queue"] else None
        if not top:
            return "Downloading"
        title = download_titles.get((top.get("id") or "").lower()) or tidy(top["title"])
        return f"Downloading {title} · {round(top['pct'])}%"
    if name == "Home Cinema":
        cin = state["cinema"]
        if cin.get("streams"):
            st = cin["streams"][0]
            return f"Streaming {st['title']}" + (f" to {st['who']}" if st.get("who") else "")
        return "Converting a video" if cin.get("converting") else None
    return state["activity"].get(name)


def read_sab():
    c = sab_config()
    if not c:
        return
    def get(mode):
        return get_json(f"http://127.0.0.1:{c['port']}{c['base']}/api?output=json&apikey={c['key']}&mode={mode}")
    try:
        q = get("queue&limit=60")["queue"]  # enough to find the next few of Radarr's and of Sonarr's
        failed = get("history&limit=1&failed_only=1")["history"].get("noofslots", 0)
        st = get("server_stats")
    except (OSError, ValueError, KeyError, urllib.error.URLError):
        state["sab"] = {"ok": False}
        return
    num = lambda v: float(v or 0)
    state["sab"] = {
        "ok": True, "version": q.get("version"), "paused": bool(q.get("paused")),
        "speed": num(q.get("kbpersec")) * 1024, "left": num(q.get("mbleft")) * 1048576, "eta": q.get("timeleft"),
        "queueTotal": q.get("noofslots_total", 0),
        "queue": [{"id": s.get("nzo_id"), "title": html.unescape(s.get("filename") or ""), "pct": num(s.get("percentage")), "left": s.get("timeleft"), "size": s.get("size"), "state": s.get("status")} for s in q.get("slots", [])],
        "failed": failed,
        "totals": {k: st.get(k, 0) for k in ("day", "week", "month", "total")},
    }


# ---------- what needs attention ----------
def alerts():
    out = []
    add = lambda level, source, msg: out.append({"level": level, "source": source, "message": msg})
    for s in state["services"]:
        if not s["up"]:
            add("error", s["name"], "Not running")
        elif state[{"Home Cinema": "cinema", "SABnzbd": "sab"}.get(s["name"], s["name"].lower())].get("ok") is False:
            add("error", s["name"], "Running, but not responding")
    for d in state["cinema"].get("missing_drives", []):
        add("error", "Drives", f"{d} is not connected, so Home Cinema can't see what's on it")
    for name in ("Radarr", "Sonarr", "Bazarr", "Prowlarr"):
        s = state[name.lower()]
        if not s.get("ok"):
            continue
        for h in s.get("health", []):
            add("error" if h["level"] == "error" else "warning", name, h["message"])
        for r in s.get("roots", []):
            if not r["ok"]:
                add("error", name, f"Root folder not reachable: {r['path']}")
        if "roots" in s and not s["roots"]:
            add("warning", name, "No root folder set, so nothing can be imported")
    sab = state["sab"]
    if sab.get("ok"):
        if sab["paused"]:
            add("warning", "SABnzbd", "Downloads are paused")
        if sab["failed"]:
            add("warning", "SABnzbd", f"{sab['failed']} failed download(s) in history")
    for d in state["disks"]:
        if d["free"] / d["total"] < 0.1:
            add("warning", "Drives", f"{d['name']} is over 90% full")
    net = state["network"]
    if net and not net["online"]:
        add("error", "Network", "No internet connection")
    sysinfo = state["system"]
    if sysinfo.get("speed_limit", 100) < 100:
        add("warning", "CPU", f"Running hot: limited to {sysinfo['speed_limit']}% speed")
    if sysinfo.get("memory", {}).get("free_level", 100) < 10:
        add("warning", "Memory", "Memory is running low")
    recent = list(history["cpu"])[-30:]
    if len(recent) == 30 and min(recent) > 90:
        add("warning", "CPU", "Above 90% for the last minute")
    return out


def payload():
    upcoming = sorted(state["radarr"].get("upcoming", []) + state["sonarr"].get("upcoming", []), key=lambda u: u["when"])[:8]
    issues = alerts()
    services = [{**s, "issues": [a for a in issues if a["source"] == s["name"]], "task": activity(s["name"]) if s["up"] else None, "next": up_next(s["name"]) if s["up"] else []} for s in state["services"]]
    sab = state["sab"]
    if sab.get("queue"):  # downloads by the name they'll have in the library
        sab = {**sab, "queue": [{**q, "name": download_titles.get((q.get("id") or "").lower()) or tidy(q["title"])} for q in sab["queue"]]}
    return json.dumps({
        "title": TITLE, "now": int(time.time() * 1000), "alerts": issues, "history": {k: list(v) for k, v in history.items()},
        "upcoming": upcoming, **state, "services": services, "sab": sab,
    })


# ---------- login ----------
failures = {}  # ip -> [attempts, locked until]


def private_file(path, make):
    """A value in a file only this user can read, created the first time it's needed."""
    try:
        with open(path, encoding="utf-8") as f:
            value = f.read().strip()
        if value:
            return value
    except OSError:
        pass
    value = make()
    with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        f.write(value + "\n")
    return value


def password():
    return private_file(PASSWORD_FILE, lambda: secrets.token_urlsafe(12))


def session_token():
    return hmac.new(private_file(SECRET_FILE, lambda: secrets.token_hex(32)).encode(), password().encode(), hashlib.sha256).hexdigest()


class Handler(BaseHTTPRequestHandler):
    def authed(self):
        # The Host check stops a website in this Mac's browser getting in through a look-alike hostname.
        if self.client_address[0] == "127.0.0.1" and self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost"):
            return True
        cookies = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return "dash_auth" in cookies and hmac.compare_digest(cookies["dash_auth"].value, session_token())

    def redirect(self, to, cookie=None):
        self.send_response(303)
        self.send_header("Location", to)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def page(self, name):
        with open(os.path.join(HERE, name), "rb") as f:
            self.reply(200, f.read().replace(b"{{TITLE}}", html.escape(TITLE).encode()), "text/html; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/login":
            return self.page("login.html")
        if path == "/api/data":
            if not self.authed():
                return self.reply(401, b"Login needed", "text/plain")
            return self.reply(200, (demo.payload(TITLE) if DEMO else payload()).encode(), "application/json")
        if DEMO and path.startswith("/demo-poster/"):
            return self.reply(200, demo.poster(path), "image/svg+xml")
        if path in ("/", "/office"):
            return self.page("index.html" if path == "/" else "office.html") if self.authed() else self.redirect("/login")
        if path == "/poster":
            return self.poster() if self.authed() else self.reply(401, b"Login needed", "text/plain")
        if path in VENDOR:
            if not self.authed():
                return self.reply(401, b"Login needed", "text/plain")
            with open(os.path.join(HERE, "vendor", VENDOR[path]), "rb") as f:
                return self.reply(200, f.read(), "text/javascript; charset=utf-8")
        self.reply(404, b"Not found", "text/plain")

    def poster(self):
        """Posters for the office board, fetched here so the 3D page can draw them (the image sites don't allow that directly)."""
        url = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("u", [""])[0]
        if DEMO and url.startswith("/demo-poster/"):
            return self.reply(200, demo.poster(url), "image/svg+xml")
        if not url.startswith(POSTER_HOSTS):
            return self.reply(400, b"Not a poster", "text/plain")
        url = url.replace("/t/p/original/", "/t/p/w500/")
        if url not in poster_cache:
            try:
                with urllib.request.urlopen(url, timeout=8) as r:
                    poster_cache[url] = (r.read(2_000_000), r.headers.get("Content-Type", "image/jpeg"))
            except OSError:
                return self.reply(502, b"Poster unavailable", "text/plain")
            while len(poster_cache) > 40:
                poster_cache.pop(next(iter(poster_cache)))
        body, ctype = poster_cache[url]
        self.reply(200, body, ctype)

    def do_POST(self):
        if self.path != "/login":
            return self.reply(404, b"Not found", "text/plain")
        ip = self.client_address[0]
        fail = failures.get(ip, [0, 0])
        if fail[1] > time.time():
            return self.redirect("/login?e=locked")
        size = min(int(self.headers.get("Content-Length") or 0), 4096)
        given = urllib.parse.parse_qs(self.rfile.read(size).decode("utf-8", "replace")).get("password", [""])[0]
        if hmac.compare_digest(given.encode(), password().encode()):
            failures.pop(ip, None)
            return self.redirect("/", f"dash_auth={session_token()}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Strict")
        attempts = 1 if fail[1] else fail[0] + 1  # a finished lockout starts counting again
        failures[ip] = [attempts, time.time() + LOCKOUT if attempts >= MAX_ATTEMPTS else 0]
        time.sleep(0.8)
        self.redirect("/login?e=1")

    def reply(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if SYSTEM_PLATFORM == 'linux':
    import linux_support
    linux_support.install(sys.modules[__name__])

import jellyfin_support
jellyfin_support.install(sys.modules[__name__])

if __name__ == "__main__":
    password()  # made on first run, so it's there to look up
    print(f"{TITLE}{' (demo)' if DEMO else ''}: http://localhost:{PORT}  ·  other devices log in with the password in {PASSWORD_FILE}", flush=True)
    if DEMO:
        import demo
        ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
    read_static()
    threading.Thread(target=system_loop, daemon=True).start()
    looped(5, read_sab)
    looped(5, read_cinema)
    looped(5, read_radarr)
    looped(5, read_sonarr)
    looped(5, read_services)
    looped(30, read_disks)
    looped(30, read_network)
    looped(60, read_prowlarr)
    looped(30, read_bazarr)
    looped(5, read_activity)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
