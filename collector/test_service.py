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

if __name__=='__main__':unittest.main()
