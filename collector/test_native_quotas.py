import json
import os
import tempfile
import unittest
from pathlib import Path

import antigravity_source


class AntigravityQuotaTests(unittest.TestCase):
    def test_native_usage_preserves_shared_model_group_and_provider_windows(self):
        self.assertTrue(hasattr(antigravity_source, 'quota_read'), 'native AGY quota reader missing')
        payload = dict(status='SUCCESS', num_turns=0, command=dict(name='usage', data=dict(groups=[
            dict(name='Claude and GPT models', description='Models within this group: Claude Opus, Claude Sonnet, GPT-OSS', buckets=[
                dict(id='3p-5h', window='5h', remaining_fraction=0.75, reset_time='2026-10-06T14:00:00Z'),
                dict(id='3p-weekly', window='weekly', remaining_fraction=0.5, reset_time='2026-10-13T09:00:00Z')])])),
            response='DO NOT EXPORT', conversation_id='DO NOT EXPORT')
        with tempfile.TemporaryDirectory() as td:
            binary = Path(td)/'agy'
            binary.write_text('#!/usr/bin/env python3\nimport json,sys\nassert sys.argv[1:] == ["--print", "/usage", "--output-format", "json", "--print-timeout", "10s"]\nprint('+repr(json.dumps(payload))+')\n')
            binary.chmod(0o700)
            result = antigravity_source.quota_read(binary=str(binary))
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(result['tool'], 'antigravity')
        rows = result['quotas']
        self.assertEqual([q['window_minutes'] for q in rows], [300, 10080])
        self.assertEqual([q['remaining_percent'] for q in rows], [75, 50])
        self.assertEqual(rows[0]['model'], 'Claude and GPT models')
        self.assertEqual(rows[0]['model_scope'], 'shared_group')
        self.assertEqual(rows[0]['source'], 'native_cli_usage')
        self.assertEqual(rows[0]['models_description'], payload['command']['data']['groups'][0]['description'])
        self.assertNotIn('DO NOT EXPORT', json.dumps(result))


    def test_provider_scoped_updates_preserve_codex_and_publish_agy_only(self):
        from collector import Collector
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            c = Collector(root, root/'settings.json')
            codex = dict(account_id='a', label='5h', used_percent=20, remaining_percent=80, resets_at=200, observed_at=100, status='ok')
            agy = dict(codex, tool='antigravity', model='Claude and GPT models', window_minutes=300, observed_at=110)
            c.apply_quota(dict(status='ok', quotas=[codex]))
            c.apply_quota(dict(tool='antigravity', status='ok', quotas=[agy]))
            self.assertEqual(len(c.quotas()), 2, 'AGY must not delete Codex current quotas')
            c.apply_quota(dict(tool='antigravity', status='timeout', quotas=[]))
            def discover(settings):
                return [dict(id=tid, name=tid, homes=[], installed=True) for tid in ('codex', 'antigravity', 'commandcode')]
            c.scan(discover, lambda t: dict(events=[], counters=[], diagnostics=[]), force=True)
            snap = json.loads((root/'snapshot.json').read_text())
            tools = {t['id']: t for t in snap['tools']}
            self.assertEqual(tools['codex']['quotas'], [codex])
            self.assertEqual(tools['antigravity']['quotas'], [dict(agy, status='timeout')])
            self.assertEqual(tools['commandcode']['quotas'], [])
            self.assertEqual(c.ledger.db.execute('select count(*) from quota_snapshots').fetchone()[0], 2)
            c.close()
            c = Collector(root, root/'settings.json')
            self.assertEqual(len(c.quotas()), 2)
            c.apply_quota(dict(status='ok', quotas=[dict(codex, used_percent=30)]))
            self.assertEqual(len(c.quotas()), 2, 'Codex refresh must not delete AGY current quotas')
            c.close()


    def test_service_dispatches_installed_quota_readers_without_commandcode_prompts(self):
        import service
        from unittest.mock import patch
        self.assertTrue(hasattr(service, 'quota_batch'), 'service native quota dispatch missing')
        tools = [dict(id='codex', installed=True, homes=['/fixture/codex']),
                 dict(id='antigravity', installed=True, homes=['/fixture/agy']),
                 dict(id='commandcode', installed=True, homes=['/fixture/cmd']),
                 dict(id='claude', installed=True, homes=['/fixture/claude'])]
        with patch('adapters.quota_read', return_value=dict(status='ok', quotas=[])) as codex, patch('antigravity_source.quota_read', return_value=dict(tool='antigravity', status='ok', quotas=[])) as agy, patch('commandcode_quota.quota_read', return_value=dict(tool='commandcode',status='ok',quotas=[])) as cmd, patch('claude_quota.quota_read', return_value=dict(tool='claude',status='ok',quotas=[])) as claude:
            result = service.quota_batch(tools,consent=True)
            codex.assert_called_once_with('/fixture/codex')
            agy.assert_called_once_with()
            cmd.assert_called_once_with('/fixture/cmd')
            claude.assert_called_once_with('/fixture/claude')
            self.assertEqual([r['tool'] for r in result], ['codex', 'antigravity', 'commandcode', 'claude'])
        with patch('adapters.quota_read', side_effect=OSError('secret: not for logs')), patch('antigravity_source.quota_read', return_value=dict(tool='antigravity', status='ok', quotas=[])), patch('commandcode_quota.quota_read', return_value=dict(tool='commandcode',status='ok',quotas=[])), patch('claude_quota.quota_read', return_value=dict(tool='claude',status='ok',quotas=[])):
            result = service.quota_batch(tools,consent=True)
            self.assertEqual(result[0], dict(tool='codex', status='unavailable', quotas=[]))
            self.assertEqual(result[1]['status'], 'ok')
        with patch('antigravity_source.quota_read') as agy:
            self.assertEqual(service.quota_batch([dict(id='antigravity', installed=False)]), [])
            agy.assert_not_called()


    def test_native_reader_fails_closed_when_provider_quotas_are_missing(self):
        from unittest.mock import patch
        import subprocess
        for payload in [dict(status='SUCCESS', num_turns=0, command=dict(name='usage', data=dict(groups=[]))),
                        dict(status='SUCCESS', num_turns=1, command=dict(name='usage', data=dict(groups=[]))),
                        dict(status='SUCCESS', num_turns=0, command=dict(name='usage', data=dict(groups=[dict(name='group', buckets=[dict(window='5h', remaining_fraction=1.5)])])))]:
            with patch('bounded_process.bounded_run', return_value=subprocess.CompletedProcess([], 0, json.dumps(payload).encode())):
                result = antigravity_source.quota_read(binary='/fixture/agy')
                self.assertEqual(result['status'], 'unavailable', 'missing or invalid quotas must retain prior readings')
                self.assertEqual(result['quotas'], [])
        with patch('bounded_process.bounded_run', side_effect=subprocess.TimeoutExpired('native', 15)):
            self.assertEqual(antigravity_source.quota_read(binary='/fixture/agy')['status'], 'timeout')


if __name__ == '__main__':
    unittest.main()
