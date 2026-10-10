import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

class RuntimeTests(unittest.TestCase):
    def test_config_validation_and_single_writer(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime'),'runtime missing')
        from runtime import WriterLock,configure,load_settings
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)
            with WriterLock(p):
                with self.assertRaises(BlockingIOError):
                    with WriterLock(p): pass
            cfg=p/'settings.json';configure(cfg,{'timezone':'Asia/Dubai','daily_budget':100,'paths':{'hermes':str(p/'home')}})
            self.assertEqual(load_settings(cfg)['daily_budget'],100)
            with self.assertRaises(ValueError):configure(cfg,{'timezone':'invalid/timezone'})
            with self.assertRaises(ValueError):configure(cfg,{'paths':{'hermes':'relative/path'}})
            self.assertEqual(load_settings(cfg)['timezone'],'Asia/Dubai')
            self.assertEqual(cfg.stat().st_mode & 0o777,0o600)

if __name__=='__main__':unittest.main()
