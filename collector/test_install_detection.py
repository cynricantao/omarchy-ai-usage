import unittest
from unittest.mock import patch
import adapters

class InstallationDetection(unittest.TestCase):
    def test_leftover_sources_are_not_installations(self):
        with patch('adapters.shutil.which', return_value=None), patch('adapters.Path.is_dir', return_value=True), patch('adapters.Path.exists', return_value=True), patch('adapters.Path.is_file', return_value=True), patch('adapters.os.access', return_value=False):
            tools=adapters.discover({})
        self.assertFalse(any(t['installed'] for t in tools))
        self.assertTrue(all(t['homes'] for t in tools))

    def test_executable_installed_without_history(self):
        with patch('adapters.shutil.which', side_effect=lambda name: '/bin/codex' if name=='codex' else None), patch('adapters.Path.is_dir', return_value=False), patch('adapters.Path.exists', return_value=False), patch('adapters.Path.is_file', return_value=False):
            tools=adapters.discover({})
        self.assertEqual([t['id'] for t in tools if t['installed']], ['codex'])

if __name__=='__main__': unittest.main()
