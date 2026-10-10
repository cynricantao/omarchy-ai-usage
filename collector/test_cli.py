import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from core import Ledger

class CliTests(unittest.TestCase):
    def test_status_export_backup_are_real_read_only_commands(self):
        self.assertIsNotNone(importlib.util.find_spec('cli'),'CLI missing')
        with tempfile.TemporaryDirectory() as td:
            h=Path(td);root=h/'data/token-activity';db=Ledger(root/'usage.sqlite3');db.close()
            env=dict(os.environ,XDG_DATA_HOME=str(h/'data'),XDG_CONFIG_HOME=str(h/'config'))
            script=str(Path(__file__).with_name('cli.py'))
            for cmd in ('status','export','backup'):
                result=subprocess.run([sys.executable,script,cmd],env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(len(list((root/'backups').glob('usage-*.sqlite3'))),1)

if __name__=='__main__':unittest.main()
