"""Linux system collectors; media API collectors remain in server.py."""
import json
import os
import re
import shutil
import socket
import time
from pathlib import Path


def install(d):
    state, history = d.state, d.history

    def memory():
        values = {k: int(v.split()[0]) * 1024 for k, v in
                  (line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())}
        total = values['MemTotal']
        available = values.get('MemAvailable', values['MemFree'])
        return dict(total=total, used=total-available, free_level=round(available/total*100),
                    swap_total=values['SwapTotal'], swap_used=values['SwapTotal']-values['SwapFree'])

    def network_bytes():
        rx = tx = 0
        for line in Path('/proc/net/dev').read_text().splitlines()[2:]:
            name, counters = line.split(':')
            if name.strip() == 'lo':
                continue
            values = counters.split()
            rx += int(values[0])
            tx += int(values[8])
        return rx, tx

    def cpu_ticks():
        return list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))

    def disk_bytes():
        sectors = 0
        for line in Path('/proc/diskstats').read_text().splitlines():
            p = line.split()
            # Whole virtual and physical disks, excluding partitions and device-mapper duplicates.
            if re.fullmatch(r'(?:sd[a-z]+|vd[a-z]+|nvme\d+n\d+)', p[2]):
                sectors += int(p[5]) + int(p[9])
        return sectors * 512

    def system_loop():
        previous = cpu_ticks(), network_bytes(), disk_bytes(), time.monotonic()
        while True:
            time.sleep(d.TICK)
            try:
                cpu, net, disk, now = cpu_ticks(), network_bytes(), disk_bytes(), time.monotonic()
                old_cpu, old_net, old_disk, before = previous
                dt = now-before
                delta = [max(0, a-b) for a, b in zip(cpu, old_cpu)]
                total = max(1, sum(delta))
                idle = (delta[3]+delta[4])/total*100
                mem = memory()
                state['system'].update(cpu=dict(user=(delta[0]+delta[1])/total*100,
                    system=(delta[2]+delta[5]+delta[6])/total*100, idle=idle),
                    memory=mem, load=list(os.getloadavg()))
                sample = dict(t=int(time.time()*1000), cpu=round(100-idle, 1),
                    mem=round(mem['used']/mem['total']*100, 1),
                    rx=round(max(0, net[0]-old_net[0])/dt), tx=round(max(0, net[1]-old_net[1])/dt),
                    disk=max(0, disk-old_disk)/dt, sab=state['sab'].get('speed', 0))
                for key, value in sample.items():
                    history[key].append(value)
                previous = cpu, net, disk, now
            except (OSError, ValueError, KeyError) as exc:
                print('Linux sample:', type(exc).__name__, flush=True)

    def read_static():
        info = Path('/proc/cpuinfo').read_text()
        brand = re.search(r'model name\s*:\s*(.*)', info)
        uptime = float(Path('/proc/uptime').read_text().split()[0])
        state['system'].update(host=socket.gethostname(), cpu_name=brand[1] if brand else 'Linux CPU',
            cores=os.cpu_count(), model='Linux server', macos='',
            booted=int((time.time()-uptime)*1000), speed_limit=100)

    def read_disks():
        disks = []
        mounts = json.loads(d.sh('findmnt', '--json', '--list', '--output', 'TARGET,SOURCE,FSTYPE'))
        seen = set()
        for mount in mounts.get('filesystems', []):
            target, source = mount['target'], mount['source']
            if mount['fstype'] in ('squashfs', 'iso9660') or not (source.startswith('/dev/') or mount['fstype'] in ('nfs', 'nfs4', 'cifs')):
                continue
            try:
                device = os.stat(target).st_dev
                if device in seen:
                    continue
                usage = shutil.disk_usage(target)
                disks.append(dict(name=target, total=usage.total, free=usage.free))
                seen.add(device)
            except OSError:
                pass
        state['disks'] = disks

    def read_network():
        route = json.loads(d.sh('ip', '-j', 'route', 'get', '1.1.1.1') or '[]')
        entry = route[0] if route else {}
        ping = d.sh('ping', '-c', '1', '-W', '2', '1.1.1.1', timeout=4)
        ms = re.search(r'time[=<]([\d.]+)', ping)
        state['network'] = dict(lan=entry.get('prefsrc', ''),
            vpn=entry.get('dev', '').startswith(('tun', 'wg')), online=bool(ms),
            ping=float(ms[1]) if ms else None)

    def read_services():
        wanted = []
        for name, config in [('Radarr', d.arr_config(d.RADARR_XML)),
                ('Sonarr', d.arr_config(d.SONARR_XML)), ('Prowlarr', d.arr_config(d.PROWLARR_XML)),
                ('Bazarr', d.bazarr_config()), ('SABnzbd', d.sab_config())]:
            if config:
                try:
                    with socket.create_connection(('127.0.0.1', config['port']), timeout=1):
                        up = True
                except OSError:
                    up = False
                wanted.append(dict(name=name, up=up))
        state['services'] = wanted

    for name, fn in locals().copy().items():
        if name in ('system_loop', 'read_static', 'read_disks', 'read_network', 'read_services'):
            setattr(d, name, fn)
