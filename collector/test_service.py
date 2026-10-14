import importlib.util
import tempfile
import time
import unittest
from pathlib import Path

class ServiceTests(unittest.TestCase):
    def test_filesystem_signal_and_bounded_quota_backoff(self):
        self.assertIsNotNone(importlib.util.find_spec('service'),'service missing')
        from service import Watcher,quota_delay
        with tempfile.TemporaryDirectory() as td:
            w=Watcher([Path(td)])
            start=time.monotonic();(Path(td)/'source.json').write_text('{}');w.wait(1)
            self.assertLess(time.monotonic()-start,0.5);w.close()
        self.assertGreaterEqual(quota_delay(0),900)
        self.assertGreaterEqual(quota_delay(4),quota_delay(1))
        self.assertLessEqual(quota_delay(20),3660)

    def test_claude_credential_sig_absent_present_and_rotation(self):
        from service import claude_credential_sig
        claude=lambda installed:{'id':'claude','installed':installed,'homes':[str(self.home)]}
        self.assertEqual(claude_credential_sig([claude(True)]),[(str(self.cred),None,None)])
        self.cred.write_text('{"claudeAiOauth":{"accessToken":"a"}}')
        first=claude_credential_sig([claude(True)])
        self.assertEqual(first,[(str(self.cred),self.cred.stat().st_mtime_ns,self.cred.stat().st_size)])
        self.cred.write_text('{"claudeAiOauth":{"accessToken":"longer-token"}}')
        second=claude_credential_sig([claude(True)])
        self.assertNotEqual(second,first)
        # Other tools, uninstalled Claude and dict-shaped homes stay out of the signature.
        self.assertEqual(claude_credential_sig([{'id':'codex','installed':True,'homes':[str(self.home)]},claude(False)]),[])
        self.assertEqual(claude_credential_sig([{'id':'claude','installed':True,'homes':[{'path':str(self.home)}]}]),second)

    def test_credential_wake_only_for_missing_or_signed_out_reading(self):
        from service import credential_wake
        self.assertTrue(credential_wake([]))
        self.assertTrue(credential_wake([{'label':'5-hour limit','status':'unauthorized'}]))
        self.assertFalse(credential_wake([{'label':'5-hour limit','status':'ok','used_percent':3}]))
        self.assertTrue(credential_wake([{'label':'5-hour limit','status':'ok'},{'label':'Weekly limit','status':'unauthorized'}]))

    def setUp(self):
        self._td=tempfile.TemporaryDirectory();self.addCleanup(self._td.cleanup)
        self.home=Path(self._td.name)/'.claude';self.home.mkdir()
        self.cred=self.home/'.credentials.json'

if __name__=='__main__':unittest.main()
