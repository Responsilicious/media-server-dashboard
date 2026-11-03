"""Run with python3 -m unittest -v test_support (standard library only)."""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import jellyfin_support
import linux_support


class PlatformTests(unittest.TestCase):
    def load(self, platform, config):
        original_open = open

        def config_open(path, *args, **kwargs):
            if str(path).endswith('config.json'):
                return io.StringIO(json.dumps(config))
            return original_open(path, *args, **kwargs)

        spec = importlib.util.spec_from_file_location('dashboard_test', Path(__file__).with_name('server.py'))
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, dashboard_test=module), patch('sys.platform', platform), patch('builtins.open', config_open):
            spec.loader.exec_module(module)
        return module

    def test_auto_and_overrides_select_all_collectors(self):
        for platform, setting, expected in [('linux', 'auto', 'linux'), ('darwin', 'auto', 'macos'),
                ('linux', 'macos', 'macos'), ('darwin', 'linux', 'linux')]:
            with self.subTest(platform=platform, setting=setting):
                module = self.load(platform, {'system_platform': setting})
                self.assertEqual(module.SYSTEM_PLATFORM, expected)
                for name in ('read_disks', 'system_loop', 'read_static', 'read_services', 'read_network'):
                    self.assertEqual(getattr(module, name).__module__, 'linux_support' if expected == 'linux' else 'dashboard_test')

    def test_invalid_platform_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'system_platform'):
            self.load('linux', {'system_platform': 'typo'})

    def test_linux_disks_skip_images_and_duplicate_mounts(self):
        mounts = [dict(target='/', source='/dev/sda', fstype='ext4'),
                  dict(target='/bind', source='/dev/sda[/folder]', fstype='ext4'),
                  dict(target='/snap/a', source='/dev/loop0', fstype='squashfs'),
                  dict(target='/media', source='server:/media', fstype='nfs4')]
        d = SimpleNamespace(state={}, history={}, sh=lambda *args: json.dumps({'filesystems': mounts}))
        linux_support.install(d)
        usage = SimpleNamespace(total=1000, free=400)
        with patch.object(linux_support.os, 'stat', side_effect=lambda path: SimpleNamespace(st_dev=2 if path == '/media' else 1)), patch.object(linux_support.shutil, 'disk_usage', return_value=usage):
            d.read_disks()
        self.assertEqual([x['name'] for x in d.state['disks']], ['/', '/media'])


class JellyfinTests(unittest.TestCase):
    def test_sessions_keep_devices_and_pause_progress(self):
        session = dict(Id='one', UserName='Viewer', DeviceName='TV',
            NowPlayingItem=dict(Id='a'*32, Name='Episode', SeriesName='Show', ParentIndexNumber=1,
                                IndexNumber=2, RunTimeTicks=1000, SeriesId='b'*32),
            PlayState=dict(PositionTicks=500, IsPaused=True))
        streams = jellyfin_support.playback([{}, session, {**session, 'Id': 'two', 'DeviceName': 'Phone'}])
        self.assertEqual(len(streams), 2)
        self.assertNotEqual(streams[0]['id'], streams[1]['id'])
        self.assertEqual(streams[0]['title'], 'Show S01E02 · Episode')
        self.assertEqual(streams[0]['pct'], 50)
        self.assertTrue(streams[0]['paused'])
        self.assertEqual(streams[0]['artwork_ids'], ['a'*32, 'b'*32])

    def test_missing_duration_and_idle(self):
        self.assertEqual(jellyfin_support.playback([{}]), [])
        stream = jellyfin_support.playback([{'NowPlayingItem': {'Name': 'Movie'}}])[0]
        self.assertEqual(stream['pct'], 0)
        self.assertIsNone(stream['artwork'])

    def test_key_relative_to_server_and_failure_clears_state(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'test-key').write_text('test-token')
            calls = []

            def get_json(url, headers):
                calls.append((url, headers))
                return [{'Id': 'one', 'UserName': 'Viewer', 'NowPlayingItem': {'Id': 'a'*32, 'Name': 'Movie'}}]

            d = SimpleNamespace(HERE=temp, CONFIG={'jellyfin_url': 'http://jellyfin/prefix/', 'jellyfin_key_file': 'test-key'},
                state={}, get_json=get_json, Handler=type('Handler', (), {'do_GET': lambda self: None}))
            jellyfin_support.install(d)
            d.read_cinema()
            self.assertTrue(d.state['cinema']['ok'])
            self.assertEqual(calls[0][0], 'http://jellyfin/prefix/Sessions')
            self.assertIn('test-token', calls[0][1]['Authorization'])
            self.assertNotIn('test-token', json.dumps(d.state))
            self.assertNotIn('artwork_ids', d.state['cinema']['streams'][0])
            Path(temp, 'test-key').unlink()
            d.read_cinema()
            self.assertFalse(d.state['cinema']['ok'])
            self.assertEqual(d.state['cinema']['streams'], [])


if __name__ == '__main__':
    unittest.main()
