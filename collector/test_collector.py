import importlib.util
import tempfile
import unittest
from pathlib import Path
from observer import capture

class CollectorTests(unittest.TestCase):
    def test_spool_restart_checkpoint_and_quota_staleness(self):
        self.assertIsNotNone(importlib.util.find_spec('collector'),'collector missing')
        from collector import Collector
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);c=Collector(root,root/'settings.json')
            kw=dict(api_request_id='r',session_id='s',model='a',provider='p',usage=dict(input_tokens=10,output_tokens=2,cache_read_tokens=0,cache_write_tokens=0,total_tokens=12),ended_at=100)
            capture('post_api_request',kw,root,root/'hermes')
            c.consume_spool();c.consume_spool();self.assertEqual(sum(x['usage']['total'] for x in c.ledger.records()),12)
            q=dict(account_id='shared',label='5 hours',used_percent=20,remaining_percent=80,resets_at=200,observed_at=100,status='ok')
            c.apply_quota({'status':'ok','quotas':[q,q]});c.apply_quota({'status':'timeout','quotas':[]})
            self.assertEqual(len(c.quotas()),1);self.assertEqual(c.quotas()[0]['observed_at'],100);self.assertEqual(c.quotas()[0]['status'],'timeout');c.close()
            c=Collector(root,root/'settings.json');c.consume_spool();self.assertEqual(sum(x['usage']['total'] for x in c.ledger.records()),12);self.assertEqual(len(c.quotas()),1);c.close()

    def test_local_scan_publishes_archived_usage_without_popup(self):
        from collector import Collector
        self.assertTrue(hasattr(Collector,'scan'),'local scan missing')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);c=Collector(root,root/'settings.json')
            def discover(settings):return [dict(id='hermes',name='Hermes',installed=True,homes=[],state='Installed',capabilities=['tokens'],note='fixture')]
            kw=dict(api_request_id='r',session_id='s',model='a',provider='p',usage=dict(input_tokens=10,output_tokens=2,cache_read_tokens=0,cache_write_tokens=0,total_tokens=12),ended_at=100)
            capture('post_api_request',kw,root,root/'hermes')
            c.scan(discover,lambda tool:{'events':[],'counters':[],'diagnostics':[]},force=True)
            import json
            snap=json.loads((root/'snapshot.json').read_text())
            self.assertEqual(snap['tools'][0]['totals']['all'],12)
            self.assertEqual(snap['tools'][0]['id'],'hermes');c.close()

    def test_commandcode_view_includes_provider_attributed_usage(self):
        from collector import Collector
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);c=Collector(root,root/'settings.json')
            def discover(settings):return [
                dict(id='hermes',name='Hermes',installed=True,homes=[],state='Installed',capabilities=['tokens'],note='fixture'),
                dict(id='commandcode',name='Command Code',installed=True,homes=[],state='source_present',capabilities=['tokens'],note='fixture')]
            c.ledger.ingest(events=[
                dict(id='h1',tool='hermes',profile='p',session='s',provider='commandcode',model='deepseek/deepseek-v4.1-flash',occurred_at=100,observed_at=100,provenance='hermes-hook',source_key='k1',usage=dict(input=10,output=2,cache_read=0,cache_write=0,total=12)),
                dict(id='h2',tool='hermes',profile='p',session='s',provider='openai-codex',model='gpt-6',occurred_at=101,observed_at=101,provenance='hermes-hook',source_key='k2',usage=dict(input=5,output=1,cache_read=0,cache_write=0,total=6)),
                dict(id='c1',tool='commandcode',profile='p',session='s',provider=None,model='some-cli-model',occurred_at=102,observed_at=102,provenance='commandcode_native_local',source_key='k3',usage=dict(input=3,output=1,cache_read=0,cache_write=0,total=4))])
            c.scan(discover,lambda tool:{'events':[],'counters':[],'diagnostics':[]},force=True)
            import json
            snap=json.loads((root/'snapshot.json').read_text())
            views={t['id']:t for t in snap['tools']}
            self.assertEqual(views['commandcode']['totals']['all'],16,'provider-attributed Hermes usage plus local CLI usage')
            self.assertEqual(views['hermes']['totals']['all'],18,'Hermes keeps its full history')
            models=[m['model'] for m in views['commandcode']['ranges']['all']['models']]
            self.assertIn('deepseek/deepseek-v4.1-flash',models)
            self.assertIn('some-cli-model',models)
            self.assertNotIn('gpt-6',models)
            c.close()

if __name__=='__main__':unittest.main()
