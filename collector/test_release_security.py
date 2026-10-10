"""Synthetic privacy/storage release regressions; never use live accounts."""
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from core import Ledger, safe_event
from observer import atomic_json
from runtime import WriterLock, load_settings, configure

class ReleaseSecurityTests(unittest.TestCase):
    def test_invalid_timestamps_cannot_persist_private_objects(self):
        for field in ('occurred_at', 'observed_at', 'interval_start', 'interval_end'):
            for value in ({'content': 'SENTINEL_PRIVATE'}, 'SENTINEL_PRIVATE', True, math.inf, math.nan, -1):
                with self.subTest(field=field, kind=type(value).__name__):
                    event = dict(id='fixture', tool='hermes', usage={}, **{field: value})
                    with self.assertRaises(ValueError):
                        safe_event(event)

    def test_unknown_settings_never_enter_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'settings.json'
            p.write_text(json.dumps({'private_note': 'SENTINEL_PRIVATE'}))
            with self.assertRaises(ValueError):
                load_settings(p)
            p.write_text(json.dumps({'remote_quotas': 'yes'}))
            with self.assertRaises(ValueError):
                load_settings(p)

    def test_neutral_default_and_remote_quota_consent(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'settings.json'
            self.assertEqual(load_settings(p)['timezone'], 'UTC')
            self.assertIs(load_settings(p)['remote_quotas'], False)
            configure(p, {'remote_quotas': True})
            self.assertIs(load_settings(p)['remote_quotas'], True)

    def test_symlink_lock_and_ledger_targets_unchanged(self):
        for name, action in [('collector.lock', lambda p: WriterLock(p).__enter__()), ('usage.sqlite3', lambda p: Ledger(p / 'usage.sqlite3'))]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as td:
                root = Path(td) / 'private'; root.mkdir(mode=0o700)
                target = Path(td) / 'target'; target.write_bytes(b'SENTINEL_PRIVATE'); target.chmod(0o640)
                (root / name).symlink_to(target)
                before = target.stat().st_mode
                with self.assertRaises((OSError, ValueError)):
                    action(root)
                self.assertEqual(target.read_bytes(), b'SENTINEL_PRIVATE')
                self.assertEqual(target.stat().st_mode, before)

    def test_symlink_and_world_writable_output_directories_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); target = root / 'target'; target.mkdir(mode=0o700)
            link = root / 'spool'; link.symlink_to(target, target_is_directory=True)
            with self.assertRaises((OSError, ValueError)):
                atomic_json(link / 'event.json', {'usage': 1})
            self.assertFalse((target / 'event.json').exists())
            target.chmod(0o777)
            with self.assertRaises((OSError, ValueError)):
                atomic_json(target / 'event.json', {})
            self.assertEqual(target.stat().st_mode & 0o777, 0o777)

    def test_malformed_activity_is_ignored(self):
        from collector import Collector
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); (root / 'activity').mkdir(mode=0o700)
            c = Collector(root, root / 'settings.json')
            try:
                for value in ([], {'active': True, 'observed_at': 'SENTINEL_PRIVATE'}, {'active': True, 'observed_at': 1, 'model': {'content': 'SENTINEL_PRIVATE'}}):
                    atomic_json(root / 'activity' / 'fixture.json', value)
                    c.scan(lambda settings: [], lambda tool: {}, force=True)
                    self.assertNotIn('SENTINEL_PRIVATE', (root / 'snapshot.json').read_text())
            finally:
                c.close()

    def test_quota_batch_without_consent_never_reads_credentials(self):
        from service import quota_batch
        tools = [{'id': 'codex', 'installed': True, 'homes': ['/fixture']}, {'id': 'antigravity', 'installed': True}, {'id': 'commandcode', 'installed': True}]
        with patch('adapters.quota_read') as codex, patch('antigravity_source.quota_read') as agy, patch('commandcode_quota.quota_read') as cmd:
            self.assertEqual(quota_batch(tools), [])
            codex.assert_not_called(); agy.assert_not_called(); cmd.assert_not_called()

if __name__ == '__main__':
    unittest.main()
