"""Read Jellyfin playback sessions without exposing its token to the browser."""
from pathlib import Path
import re
import urllib.request
import urllib.parse


def playback(sessions):
    streams = []
    for session in sessions:
        item = session.get('NowPlayingItem')
        if not item:
            continue
        title = item.get('Name') or 'Unknown title'
        if item.get('SeriesName'):
            season, episode = item.get('ParentIndexNumber'), item.get('IndexNumber')
            number = f' S{season:02d}E{episode:02d}' if isinstance(season, int) and isinstance(episode, int) else ''
            title = f"{item['SeriesName']}{number} · {title}"
        play = session.get('PlayState') or {}
        duration = item.get('RunTimeTicks') or 0
        position = play.get('PositionTicks') or 0
        who = session.get('UserName') or session.get('DeviceName') or 'Viewer'
        item_id = item.get('Id', '')
        art_ids = [item_id, item.get('SeriesId'), item.get('ParentPrimaryImageItemId')]
        art_ids = list(dict.fromkeys(str(i) for i in art_ids if i and re.fullmatch(r'[a-fA-F0-9-]{32,36}', str(i))))
        streams.append(dict(title=title, who=who,
            id=session.get('Id') or f'{who}:{session.get("DeviceId", "")}:{item_id}',
            artwork='/jellyfin-art?id=' + urllib.parse.quote(item_id) if item_id in art_ids else None,
            artwork_ids=art_ids,
            pct=min(100, max(0, round(position / duration * 100))) if duration else 0,
            paused=bool(play.get('IsPaused')), device=session.get('DeviceName') or '',
            service='Jellyfin'))
    return streams


def install(d):
    url = d.CONFIG.get('jellyfin_url', '').rstrip('/')
    if not url:
        return
    allowed = {}
    cache = {}

    def auth_headers():
        path = Path(d.CONFIG.get('jellyfin_key_file', 'jellyfin-api-key')).expanduser()
        if not path.is_absolute():
            path = Path(d.HERE) / path
        key = path.read_text().strip()
        if not key or any(c in key for c in ('"', '\r', '\n')):
            raise ValueError('Invalid key file')
        return {'Authorization': f'MediaBrowser Client="Arr Dashboard", Device="Arr Server", DeviceId="arr-dashboard", Version="1.0", Token="{key}"'}

    def read_cinema():
        result = dict(enabled=True, source='Jellyfin', ok=False, profiles=[], streams=[],
                      watched=[], missing_drives=[], converting=0)
        try:
            sessions = d.get_json(url + '/Sessions', auth_headers())
            streams = playback(sessions)
            current = {}
            for stream in streams:
                ids = stream.pop('artwork_ids')
                if ids:
                    current[ids[0]] = ids
            allowed.clear()
            allowed.update(current)
            result.update(ok=True, streams=streams,
                          profiles=list(dict.fromkeys(s['who'] for s in streams)),
                          converting=sum(bool(s.get('TranscodingInfo')) for s in sessions if s.get('NowPlayingItem')))
        except (OSError, ValueError, TypeError, KeyError):
            allowed.clear()
            result['error'] = 'Jellyfin playback unavailable'
        d.state['cinema'] = result

    d.read_cinema = read_cinema

    original_get = d.Handler.do_GET

    def do_GET(self):
        if self.path.split('?')[0] != '/jellyfin-art':
            return original_get(self)
        if not self.authed():
            return self.reply(401, b'Login needed', 'text/plain')
        item_id = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get('id', [''])[0]
        ids = allowed.get(item_id)
        if not ids:
            return self.reply(404, b'Artwork unavailable', 'text/plain')
        if item_id in cache:
            return self.reply(200, *cache[item_id])
        for candidate in ids:
            try:
                req = urllib.request.Request(url + f'/Items/{candidate}/Images/Primary?maxWidth=400&quality=85', headers=auth_headers())
                with urllib.request.urlopen(req, timeout=6) as response:
                    body = response.read(2_000_001)
                    content_type = response.headers.get('Content-Type', '').split(';')[0]
                if len(body) > 2_000_000 or content_type not in ('image/jpeg', 'image/png', 'image/webp'):
                    continue
                cache[item_id] = (body, content_type)
                while len(cache) > 24:
                    cache.pop(next(iter(cache)))
                return self.reply(200, body, content_type)
            except (OSError, ValueError):
                continue
        return self.reply(404, b'Artwork unavailable', 'text/plain')

    d.Handler.do_GET = do_GET
