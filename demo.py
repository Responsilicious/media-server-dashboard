"""Made-up data for `python3 server.py --demo`: the same shape as the real thing, nothing read from this Mac.

Everything moves with the clock, so the graphs scroll and the workers come and go like they would for real.
"""
import html
import json
import math
import time

GB = 1024 ** 3
MOVIES = [
    ("The Last Lighthouse", 2024, "#1d3557", "#e9c46a"), ("Neon Harbor", 2023, "#3a0ca3", "#f72585"),
    ("Paper Moons", 2025, "#264653", "#2a9d8f"), ("Copper Sky", 2022, "#6a040f", "#f48c06"),
    ("Midnight Orchard", 2024, "#081c15", "#74c69d"), ("Glass Mountain", 2021, "#22223b", "#9a8c98"),
]
SHOWS = [
    ("Harbor Lights", "S02E05", "#003049", "#fcbf49"), ("The Quiet Office", "S01E08", "#2b2d42", "#8d99ae"),
    ("Starfield Kitchen", "S03E02", "#5f0f40", "#fb8b24"), ("North Line", "S01E03", "#012a4a", "#61a5c2"),
]
PEOPLE = ["Alex", "Sam", "Jordan"]


def wave(t, period, lo, hi, seed=0):
    """A smooth but uneven value between lo and hi."""
    v = (math.sin(t / period + seed) + 0.5 * math.sin(t / (period * 0.37) + seed * 2) + 0.25 * math.sin(t / (period * 0.11) + seed * 3)) / 1.75
    return lo + (hi - lo) * (v + 1) / 2


def iso(ms):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))


def payload(title):
    now = time.time()
    ms = int(now * 1000)
    ts = [now - (149 - i) * 2 for i in range(150)]
    cpu = [round(wave(t, 40, 8, 78, 1)) for t in ts]
    mem = [round(wave(t, 300, 61, 72, 2), 1) for t in ts]
    rx = [round(wave(t, 25, 0.5, 11, 3) * 1048576) for t in ts]
    tx = [round(wave(t, 30, 0.05, 1.2, 4) * 1048576) for t in ts]
    disk = [wave(t, 15, 0, 40, 5) * 1048576 for t in ts]
    sab = [r * 0.9 for r in rx]

    phase = int(now // 45) % 4  # every 45 seconds someone else is busy
    queue = [
        {"id": f"demo{i}", "title": f"{n}.{y}.1080p.WEB-DL", "name": f"{n} ({y})", "pct": max(0.0, round(wave(now, 20, 20, 95, i) - i * 25, 1)),
         "left": f"0:{12 + i * 7:02d}:00", "size": f"{3 + i}.{i} GB", "state": "Downloading" if i == 0 else "Queued"}
        for i, (n, y, *_ ) in enumerate(MOVIES[:5])
    ]
    watching = PEOPLE[phase % len(PEOPLE)] if phase != 3 else None
    streams = [{"title": f"{MOVIES[phase][0]} ({MOVIES[phase][1]})", "who": watching, "pct": round(wave(now, 200, 10, 90))}] if watching else []
    watched = [{"who": PEOPLE[i % 3], "title": f"{SHOWS[i % 4][0]} {SHOWS[i % 4][1]}", "year": None, "pct": 100 - i * 13,
                "when": ms - (i + 1) * 3_600_000, "now": False} for i in range(5)]

    # Jellyfin: always two to four things playing, so the TV's slideshow has something to flip through.
    # Every 45 seconds a different mix, and people pause and resume as they go.
    pick = lambda i, n: (phase + i) % n
    jf_all = [
        {"title": SHOWS[0][0], "sub": f"{SHOWS[0][1]} · The Long Tide", "kind": "Episode", "who": "Alex", "device": "Living Room TV", "client": "Jellyfin Android TV",
         "pct": round(wave(now, 150, 5, 95, 1)), "paused": False, "poster": "/demo-poster/s0.svg", "method": "Direct play"},
        {"title": MOVIES[2][0], "sub": str(MOVIES[2][1]), "kind": "Movie", "who": "Sam", "device": "iPad", "client": "Jellyfin Mobile",
         "pct": round(wave(now, 260, 10, 90, 2)), "paused": phase == 1, "poster": "/demo-poster/m2.svg", "method": "Transcoding"},
        {"title": SHOWS[2][0], "sub": f"{SHOWS[2][1]} · Sourdough Season", "kind": "Episode", "who": "Jordan", "device": "Chrome", "client": "Jellyfin Web",
         "pct": round(wave(now, 120, 5, 95, 3)), "paused": False, "poster": "/demo-poster/s2.svg", "method": "Direct play"},
        {"title": MOVIES[4][0], "sub": str(MOVIES[4][1]), "kind": "Movie", "who": "Riley", "device": "Bedroom Apple TV", "client": "Swiftfin",
         "pct": round(wave(now, 300, 15, 85, 4)), "paused": phase == 3, "poster": "/demo-poster/m4.svg", "method": "Direct play"},
        {"title": MOVIES[5][0], "sub": str(MOVIES[5][1]), "kind": "Movie", "who": "Alex", "device": "MacBook", "client": "Jellyfin Media Player",
         "pct": round(wave(now, 220, 5, 60, 5)), "paused": False, "poster": "/demo-poster/m5.svg", "method": "Direct play"},
    ]
    jf = [jf_all[pick(i, len(jf_all))] for i in range((2, 3, 4, 3)[phase])]

    activity = {
        "Radarr": "Waiting on 3 downloads" if phase in (0, 1) else None,
        "Sonarr": "RefreshMonitoredDownloads" if phase in (1, 2) else None,
        "Prowlarr": "Searching for Paper Moons" if phase == 2 else None,
        "Bazarr": "Search for missing subtitles" if phase == 3 else None,
    }
    names = ["Home Cinema", "Radarr", "Sonarr", "Bazarr", "Prowlarr", "SABnzbd"]
    tasks = {**activity, "SABnzbd": f"Downloading {queue[0]['name']} · {round(queue[0]['pct'])}%",
             "Home Cinema": f"Streaming {streams[0]['title']} to {watching}" if streams else None}
    nxt = [{"title": q["name"], "pct": round(q["pct"]), "size": q["size"]} for q in queue]
    services = [{"name": n, "up": True, "issues": [], "task": tasks.get(n), "next": nxt if n in ("SABnzbd", "Radarr") else []} for n in names]

    poster = lambda kind, i: f"/demo-poster/{kind}{i}.svg"
    return json.dumps({
        "title": title, "now": ms, "alerts": [],
        "history": {"t": [int(t * 1000) for t in ts], "cpu": cpu, "mem": mem, "rx": rx, "tx": tx, "disk": disk, "sab": sab},
        "upcoming": [{"kind": "Episode", "title": f"{SHOWS[i][0]} S0{i + 1}E0{i + 4}", "when": iso(ms + (i + 1) * 86_400_000)} for i in range(3)]
        + [{"kind": "Movie", "title": MOVIES[5][0], "when": iso(ms + 5 * 86_400_000)}],
        "system": {"host": "demo", "cpu_name": "Apple M2", "cores": 8, "macos": "15.0", "model": "Mac14,3", "booted": ms - 3 * 86_400_000 - 7_200_000,
                   "speed_limit": 100, "cpu": {"user": cpu[-1] * 0.7, "system": cpu[-1] * 0.3, "idle": 100 - cpu[-1]}, "load": [2.1, 1.8, 1.6],
                   "memory": {"total": 16 * GB, "used": int(mem[-1] / 100 * 16 * GB), "free_level": 40, "swap_total": 0, "swap_used": 0}},
        "services": services,
        "cinema": {"enabled": True, "ok": True, "converting": 0, "profiles": PEOPLE, "streams": streams, "watched": watched, "missing_drives": []},
        "jellyfin": {"enabled": True, "ok": True, "streams": jf},
        "sab": {"ok": True, "version": "4.3.3", "paused": False, "speed": sab[-1], "left": 21 * GB, "eta": "0:34:10", "queueTotal": 12, "queue": queue, "failed": 0,
                "totals": {"day": 38 * GB, "week": 212 * GB, "month": 840 * GB, "total": 9800 * GB}},
        "radarr": {"ok": True, "version": "5.0", "library": {"total": 412, "have": 398, "size": 3900 * GB}, "missing": 14,
                   "recent": [{"title": n, "year": y, "poster": poster("m", i), "size": 8 * GB, "quality": "Bluray-1080p", "when": iso(ms - (i + 1) * 5_400_000)} for i, (n, y, *_) in enumerate(MOVIES)],
                   "upcoming": [], "health": [], "roots": [{"path": "/Volumes/Media/Movies", "ok": True}]},
        "sonarr": {"ok": True, "version": "4.0", "library": {"total": 64, "have": 2210, "episodes": 2380, "size": 5100 * GB}, "missing": 30,
                   "recent": [{"title": n, "sub": e, "poster": poster("s", i), "quality": "WEBDL-1080p", "when": iso(ms - (i + 1) * 7_200_000)} for i, (n, e, *_) in enumerate(SHOWS)],
                   "upcoming": [], "health": [], "roots": [{"path": "/Volumes/Media/TV", "ok": True}]},
        "prowlarr": {"ok": True, "version": "1.0", "indexers": 6, "enabled": 6, "health": []},
        "bazarr": {"ok": True, "health": []},
        "activity": activity,
        "network": {"lan": "", "vpn": False, "online": True, "ping": 14.0},
        "disks": [{"name": "Macintosh HD", "total": 494 * GB, "free": 180 * GB}, {"name": "Media", "total": 8000 * GB, "free": 2700 * GB}],
    })


# Each made-up title gets a little scene, so the demo posters read like real one-sheets.
def _stars(seed, n=40, top=0, bottom=380):
    return "".join(f'<circle cx="{(seed * 37 + i * 97) % 500}" cy="{top + (seed * 53 + i * 61) % (bottom - top)}" r="{1 + (i % 3) * 0.6}" fill="#fff" opacity="{0.35 + (i % 4) * 0.15:.2f}"/>' for i in range(n))


def _hills(color, y, amp, seed, opacity=1):
    pts = " ".join(f"{x},{y - amp * (0.5 + 0.5 * math.sin(x / 70 + seed))}" for x in range(0, 501, 25))
    return f'<polygon points="0,750 {pts} 500,750" fill="{color}" opacity="{opacity}"/>'


def _sea(y, color):
    lines = "".join(f'<rect x="{(i * 83) % 420}" y="{y + 12 + i * 14}" width="{60 + (i * 29) % 90}" height="2" fill="#fff" opacity=".18"/>' for i in range(10))
    return f'<rect y="{y}" width="500" height="{750 - y}" fill="{color}"/>{lines}'


SCENES = {
    "The Last Lighthouse": lambda a, b: _stars(1, 30, 0, 300) + '<polygon points="250,250 -60,170 -60,330" fill="#fff6c8" opacity=".22"/>' + _sea(430, "#0b1d33")
        + '<polygon points="228,430 272,430 262,250 238,250" fill="#f1ece4"/><rect x="236" y="300" width="28" height="22" fill="#c0392b"/><rect x="240" y="360" width="22" height="22" fill="#c0392b"/>'
        + f'<rect x="232" y="226" width="36" height="26" rx="4" fill="{b}"/><circle cx="250" cy="239" r="9" fill="#fffbe0"/><polygon points="226,226 274,226 250,206" fill="#2b2b2b"/>',
    "Neon Harbor": lambda a, b: _stars(2, 20, 0, 200) + "".join(f'<rect x="{x}" y="{430 - h}" width="{w}" height="{h}" fill="#140a2e"/>' + "".join(f'<rect x="{x + 6 + (k % 3) * 12}" y="{440 - h + (k // 3) * 22}" width="6" height="10" fill="{b if (k + x) % 4 else "#4cc9f0"}" opacity=".85"/>' for k in range(min(18, h // 22 * 3))) for x, w, h in [(10, 50, 180), (70, 44, 250), (124, 60, 150), (194, 40, 300), (244, 70, 210), (324, 46, 270), (380, 60, 160), (446, 50, 230)])
        + _sea(430, "#0d0628") + f'<rect y="440" width="500" height="120" fill="{b}" opacity=".12"/>',
    "Paper Moons": lambda a, b: f'<circle cx="250" cy="250" r="120" fill="#fdf1d6"/><circle cx="300" cy="215" r="105" fill="{a}"/>' + _hills("#1b4332", 470, 70, 1, 0.9) + _hills(b, 520, 60, 3, 0.8) + _hills("#081c15", 580, 50, 5),
    "Copper Sky": lambda a, b: '<circle cx="250" cy="400" r="130" fill="#ffd166" opacity=".9"/>' + "".join(f'<rect x="100" y="{330 + i * 22}" width="300" height="6" fill="{a}" opacity=".55"/>' for i in range(4)) + _hills("#9d0208", 470, 50, 2) + _hills("#370617", 540, 40, 4),
    "Midnight Orchard": lambda a, b: _stars(5, 60, 0, 420) + '<circle cx="380" cy="130" r="40" fill="#f1faee"/>' + _hills("#0b2b1f", 560, 30, 1)
        + "".join(f'<rect x="{x - 4}" y="{560 - h * 0.6}" width="8" height="{h * 0.6}" fill="#02110b"/><circle cx="{x}" cy="{560 - h * 0.6}" r="{h * 0.32}" fill="#02110b"/>' for x, h in [(60, 150), (150, 190), (250, 170), (350, 200), (440, 160)]),
    "Glass Mountain": lambda a, b: _stars(6, 30, 0, 260) + '<polygon points="250,150 480,560 20,560" fill="#c9d6ea" opacity=".9"/><polygon points="250,150 300,240 260,230 230,260 205,230" fill="#fff"/>'
        + f'<polygon points="120,300 290,560 -40,560" fill="{b}" opacity=".85"/><polygon points="390,330 540,560 240,560" fill="{a}" opacity=".9"/>',
    "Harbor Lights": lambda a, b: _stars(7, 25, 0, 260) + _sea(400, "#00243a") + "".join(f'<polygon points="{x},{y} {x + 70},{y} {x + 58},{y + 18} {x + 12},{y + 18}" fill="#111"/><rect x="{x + 33}" y="{y - 60}" width="3" height="60" fill="#111"/><polygon points="{x + 37},{y - 56} {x + 37},{y - 6} {x + 66},{y - 6}" fill="#eee" opacity=".85"/><circle cx="{x + 34}" cy="{y - 62}" r="4" fill="{b}"/><rect x="{x + 30}" y="{y + 22}" width="8" height="40" fill="{b}" opacity=".35"/>' for x, y in [(60, 420), (250, 450), (380, 410)]),
    "The Quiet Office": lambda a, b: f'<rect x="90" y="140" width="320" height="260" fill="{a}" stroke="#d9d9e3" stroke-width="10"/><rect x="245" y="140" width="10" height="260" fill="#d9d9e3"/><rect x="90" y="265" width="320" height="10" fill="#d9d9e3"/>'
        + '<rect y="470" width="500" height="20" fill="#3d405b"/><polygon points="330,330 400,330 380,380 350,380" fill="#f4d35e"/><rect x="362" y="380" width="6" height="90" fill="#22223b"/><polygon points="300,470 430,470 365,390" fill="#f4d35e" opacity=".18"/>',
    "Starfield Kitchen": lambda a, b: _stars(9, 70, 0, 600) + f'<circle cx="250" cy="300" r="110" fill="{b}"/><ellipse cx="250" cy="300" rx="190" ry="34" fill="none" stroke="#fff" stroke-width="6" opacity=".6"/><circle cx="215" cy="265" r="22" fill="#fff" opacity=".25"/>',
    "North Line": lambda a, b: _stars(10, 30, 0, 280) + _hills("#01497c", 380, 40, 2, 0.8) + '<polygon points="235,380 265,380 420,750 80,750" fill="#1d1d1d"/>'
        + "".join(f'<rect x="{250 - 20 - i * 26}" y="{390 + i * i * 6 + i * 12}" width="{40 + i * 52}" height="{3 + i}" fill="#6c584c"/>' for i in range(8))
        + f'<circle cx="250" cy="372" r="10" fill="{b}"/><polygon points="250,372 120,750 380,750" fill="{b}" opacity=".08"/>',
}
TAGLINES = {"The Last Lighthouse": "SOME LIGHTS NEVER GO OUT", "Neon Harbor": "THE CITY NEVER SLEEPS", "Paper Moons": "EVERY NIGHT, A NEW ONE",
            "Copper Sky": "THE DESERT KEEPS ITS SECRETS", "Midnight Orchard": "WHAT GROWS IN THE DARK", "Glass Mountain": "THE CLIMB IS ONLY HALF OF IT",
            "Harbor Lights": "A NEW SEASON", "The Quiet Office": "NOTHING HAPPENS. BEAUTIFULLY.", "Starfield Kitchen": "COOKING, BUT IN SPACE", "North Line": "LAST TRAIN NORTH"}


def poster(path):
    """A made-up poster for a made-up title: a little scene, a tagline, the title and a billing block."""
    key = path.rsplit("/", 1)[-1].removesuffix(".svg")
    items = MOVIES if key[:1] == "m" else SHOWS
    try:
        name, extra, top, bottom = items[int(key[1:]) % len(items)]
    except ValueError:
        name, extra, top, bottom = "Demo", "", "#333", "#777"
    words, lines = name.upper().split(), []
    for w in words:
        if lines and len(lines[-1]) + len(w) < 11:
            lines[-1] += " " + w
        else:
            lines.append(w)
    y0 = 640 - (len(lines) - 1) * 62
    text = "".join(f'<text x="250" y="{y0 + i * 62}" font-size="60" text-anchor="middle" fill="#fff" font-family="Georgia, \'Times New Roman\', serif" font-weight="700" letter-spacing="3">{html.escape(t)}</text>' for i, t in enumerate(lines))
    scene = SCENES.get(name, lambda a, b: "")(top, bottom)
    tag = html.escape(TAGLINES.get(name, ""))
    foot = html.escape(f"IN CINEMAS {extra}" if key[:1] == "m" else f"STREAMING NOW · {extra}")
    billing = "".join(f'<rect x="{70 + (i * 41) % 60}" y="{698 + (i // 4) * 9}" width="{70 + (i * 23) % 50}" height="4" fill="#fff" opacity=".35"/>' for i in range(8))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="500" height="750" viewBox="0 0 500 750">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{top}"/><stop offset="1" stop-color="{bottom}"/></linearGradient>
<linearGradient id="f" x1="0" y1="0" x2="0" y2="1"><stop offset=".55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".85"/></linearGradient></defs>
<rect width="500" height="750" fill="url(#g)"/>{scene}<rect width="500" height="750" fill="url(#f)"/>
<text x="250" y="58" font-size="17" text-anchor="middle" fill="#fff" opacity=".85" font-family="Helvetica, Arial, sans-serif" letter-spacing="4">{tag}</text>
{text}<text x="250" y="{y0 + len(lines) * 62 - 22}" font-size="15" text-anchor="middle" fill="#fff" opacity=".8" font-family="Helvetica, Arial, sans-serif" letter-spacing="5">{foot}</text>{billing}</svg>'''.encode()
