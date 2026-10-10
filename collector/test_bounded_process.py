"""Actual isolated process-boundary regressions; no native accounts invoked."""
import subprocess
import sys
import unittest
from bounded_process import bounded_run

class BoundedProcessTests(unittest.TestCase):
    def test_complete_output(self):
        result = bounded_run([sys.executable, '-c', 'print("fixture")'], timeout=2, limit=32)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'fixture\n')

    def test_oversized_output_is_stopped_while_streaming(self):
        with self.assertRaises(ValueError):
            bounded_run([sys.executable, '-c', 'import os;\nwhile True: os.write(1,b"x"*65536)'], timeout=2, limit=1024)

    def test_timeout_reaps_owned_child(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            bounded_run([sys.executable, '-c', 'import time; time.sleep(10)'], timeout=0.05)

if __name__ == '__main__':
    unittest.main()
