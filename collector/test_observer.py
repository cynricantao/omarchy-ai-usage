import importlib.util
import tempfile
import unittest
import json
from pathlib import Path

class ObserverTests(unittest.TestCase):
    def test_usage_only_durable_spool_replay_and_unknowns(self):
        self.assertIsNotNone(importlib.util.find_spec('observer'),'observer missing')
        from observer import capture
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            kw=dict(api_request_id='stable-id',session_id='s',model='a',provider='p',base_url='https://provider/v1',ended_at=100,usage={'input_tokens':10,'output_tokens':3,'cache_read_tokens':2,'total_tokens':15},request={'secret':'must not persist'},response={'content':'must not persist'})
            capture('post_api_request',kw,p,p/'home');capture('post_api_request',kw,p,p/'home')
            files=list((p/'spool').glob('*.json'));self.assertEqual(len(files),1)
            text=files[0].read_text();self.assertNotIn('must not persist',text)
            e=json.loads(text)['event'];self.assertIsNone(e['usage']['cache_write']);self.assertEqual(e['usage']['total'],15)
            self.assertEqual(files[0].stat().st_mode & 0o777,0o600)

if __name__=='__main__':unittest.main()
