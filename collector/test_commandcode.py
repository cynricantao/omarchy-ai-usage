"""Synthetic fixtures following command-code 1.74.1 SessionStoreV3."""
import json
from pathlib import Path
import tempfile
import unittest
import adapters as a

class CommandCodeTests(unittest.TestCase):
    def test_v3_usage_is_collected_without_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root/'projects/project/session.jsonl'
            p.parent.mkdir(parents=True)
            rows = [
                dict(type='session', version=3, id='session-a', timestamp='2026-10-05T00:00:00Z', cwd='/private'),
                dict(type='message', id='entry-a', parentId=None, timestamp='2026-10-05T00:01:00Z', model='test-model',
                     message=dict(role='assistant', content='PRIVATE CONTENT'),
                     usage=dict(inputTokens=100, outputTokens=20, cacheReadTokens=30, cacheWriteTokens=10))]
            p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            result = a.collect(dict(id='commandcode', homes=[tmp]))
            self.assertEqual(len(result['events']), 1)
            event = result['events'][0]
            self.assertEqual(event['tool'], 'commandcode')
            self.assertEqual(event['usage'], dict(input=60, output=20, cache_read=30, cache_write=10, total=120))
            self.assertEqual(event['model'], 'test-model')
            self.assertNotIn('PRIVATE', json.dumps(result))
            self.assertEqual(result['diagnostics'], [])

    def test_clone_missing_fields_and_partial_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root/'projects/p/a.jsonl'
            p.parent.mkdir(parents=True)
            header = dict(type='session', version=3, id='a')
            row = dict(type='message', id='same-entry', timestamp='2026-10-05T00:01:00Z',
                       message=dict(role='assistant', content='PRIVATE'), usage=dict(inputTokens=10, outputTokens=2))
            text = json.dumps(header)+'\n'+json.dumps(row)+'\n'
            p.write_text(text)
            clone = p.with_name('clone.jsonl')
            clone.write_text(text.replace('"id": "a"', '"id": "clone"'))
            result = a.collect(dict(id='commandcode', homes=[tmp]))
            self.assertEqual(len(result['events']), 1)
            self.assertIsNone(result['events'][0]['usage']['input'])
            self.assertEqual(result['events'][0]['usage']['total'], 12)
            with p.open('a') as f: f.write('{"type":')
            result = a.collect(dict(id='commandcode', homes=[tmp]))
            self.assertIn('partial_line', result['diagnostics'])
            self.assertEqual(len(result['events']), 1)
            p.write_text(json.dumps(dict(type='session', version=99, id='x'))+'\n'+json.dumps(row)+'\n')
            clone.unlink()
            result = a.collect(dict(id='commandcode', homes=[tmp]))
            self.assertEqual(result['events'], [])
            self.assertIn('unsupported_commandcode_schema', result['diagnostics'])

class DiscoveryTests(unittest.TestCase):
    def test_commandcode_detected_only_by_binary_and_settings_accept_it(self):
        from unittest.mock import patch
        from runtime import configure
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'.commandcode/projects').mkdir(parents=True)
            with patch('pathlib.Path.home', return_value=root), patch.object(a.shutil, 'which', return_value=None):
                tools = {t['id']: t for t in a.discover({})}
                self.assertIn('commandcode', tools)
                self.assertFalse(tools['commandcode']['installed'])
            with patch('pathlib.Path.home', return_value=root), patch.object(a.shutil, 'which', side_effect=lambda b: '/bin/cmd' if b == 'cmd' else None):
                tool = next(t for t in a.discover({}) if t['id'] == 'commandcode')
                self.assertTrue(tool['installed'])
                self.assertEqual(tool['homes'], [str(root/'.commandcode')])
                self.assertEqual(tool['capabilities'], ['tokens'])
            config = configure(root/'settings.json', {'default_tool':'commandcode', 'paths':{'commandcode':str(root/'.commandcode')}})
            self.assertEqual(config['default_tool'], 'commandcode')

if __name__ == '__main__': unittest.main()
