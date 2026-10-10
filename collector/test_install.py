"""Installer regression tests: synthetic homes only; systemctl is always mocked."""
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import install


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / 'home space % dollar$ quote"'
        self.home.mkdir(mode=0o700)
        self.app = self.root / 'checkout % space' / 'collector'
        self.app.mkdir(parents=True, mode=0o700)
        (self.app / 'cli.py').write_text('import sys; print(repr(sys.argv[1:]))\n')
        self.env = {'HOME': str(self.home), 'PATH': '/usr/bin:/bin',
                    'XDG_DATA_HOME': str(self.home / 'data'),
                    'XDG_CONFIG_HOME': str(self.home / 'config'),
                    'XDG_STATE_HOME': str(self.home / 'state')}
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, self.env, clear=True).start()
        patch.object(install, 'APP', self.app).start()
        self.commands = patch.object(install, 'command', return_value='').start()
        patch('sys.stdout', new=io.StringIO()).start()

    def test_default_install_is_checkout_only_inactive_and_idempotent(self):
        (self.home / '.hermes').mkdir(mode=0o700)
        secret = self.home / '.hermes/config.yaml'
        secret.write_text('api_key: SYNTHETIC-CREDENTIAL-DO-NOT-COPY\n')
        secret.chmod(0o600)
        install.install()
        wrapper = self.home / '.local/bin/token-activity'
        unit = self.home / 'config/systemd/user/token-activity.service'
        data = self.home / 'data/token-activity'
        ledger = data / 'usage.sqlite3'
        ledger.write_bytes(b'old history'); ledger.chmod(0o600)
        before = (wrapper.read_bytes(), unit.read_bytes(), wrapper.stat().st_mtime_ns)
        install.install()
        self.assertEqual(before, (wrapper.read_bytes(), unit.read_bytes(), wrapper.stat().st_mtime_ns))
        self.assertEqual(ledger.read_bytes(), b'old history')
        self.assertFalse(any(c.args[0] in ('systemctl', 'hermes', 'omarchy', 'omarchy-shell') for c in self.commands.call_args_list))
        self.assertEqual(secret.read_text(), 'api_key: SYNTHETIC-CREDENTIAL-DO-NOT-COPY\n')
        self.assertEqual(list(self.app.parent.rglob('*')), [self.app, self.app / 'cli.py'])
        self.assertIn('%%', unit.read_text())
        self.assertIn('XDG_DATA_HOME=', unit.read_text())
        self.assertFalse((self.home / '.config/omarchy').exists())
        import subprocess
        result = subprocess.run([str(wrapper), 'argument with spaces', '$literal'], check=True, text=True, capture_output=True)
        self.assertEqual(result.stdout.strip(), "['argument with spaces', '$literal']")

    def test_conflicts_refuse_before_other_file_overwrites(self):
        install.install()
        wrapper = self.home / '.local/bin/token-activity'
        unit = self.home / 'config/systemd/user/token-activity.service'
        wrapper.write_text('private old launcher\n')
        original_unit = unit.read_bytes()
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            install.install()
        self.assertEqual(wrapper.read_text(), 'private old launcher\n')
        self.assertEqual(unit.read_bytes(), original_unit)

    def test_explicit_replace_preserves_backups_outside_checkout(self):
        install.install()
        wrapper = self.home / '.local/bin/token-activity'
        wrapper.write_bytes(b'old wrapper')
        install.install(replace=True)
        backups = list((self.home / 'state/token-activity/installer-backups').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'old wrapper')
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        install.install(replace=True)
        self.assertEqual(list(backups[0].parent.iterdir()), backups)
        self.assertFalse((self.app.parent / 'backups').exists())

    def test_symlink_destinations_and_ancestors_are_refused(self):
        external = self.root / 'external'; external.mkdir(mode=0o700)
        (self.home / 'data').symlink_to(external, target_is_directory=True)
        with self.assertRaises(ValueError):
            install.install()
        self.assertEqual(list(external.iterdir()), [])

    def test_symlink_wrapper_is_refused_even_with_replace(self):
        install.install()
        wrapper = self.home / '.local/bin/token-activity'
        target = self.root / 'target'; target.write_text('untouched'); target.chmod(0o600)
        wrapper.unlink(); wrapper.symlink_to(target)
        with self.assertRaises(ValueError):
            install.install(replace=True)
        self.assertEqual(target.read_text(), 'untouched')

    def test_permissive_storage_and_files_are_refused(self):
        install.install()
        data = self.home / 'data/token-activity'
        data.chmod(0o755)
        with self.assertRaises(ValueError):
            install.install()
        data.chmod(0o700)
        ledger = data / 'usage.sqlite3'; ledger.write_bytes(b'preserved'); ledger.chmod(0o644)
        with self.assertRaises(ValueError):
            install.install()
        self.assertEqual(ledger.read_bytes(), b'preserved')

    def test_unowned_storage_refused(self):
        install.install()
        with patch.object(install.os, 'getuid', return_value=os.getuid() + 1):
            with self.assertRaises(ValueError):
                install.install()

    def test_activation_is_opt_in_and_verified(self):
        def response(*args):
            if 'is-enabled' in args: return 'enabled\n'
            if 'is-active' in args: return 'active\n'
            return ''
        self.commands.side_effect = response
        self.assertTrue(install.install(activate=True)['activated'])
        self.assertIn(unittest.mock.call('systemctl', '--user', 'enable', '--now', install.UNIT), self.commands.call_args_list)
        self.assertIn(unittest.mock.call('systemctl', '--user', 'is-active', install.UNIT), self.commands.call_args_list)
        self.commands.side_effect = None
        self.commands.return_value = 'inactive\n'
        with self.assertRaises(ValueError):
            install.install(activate=True)

    def test_uninstall_only_disables_preserving_all_files(self):
        install.install()
        ledger = self.home / 'data/token-activity/usage.sqlite3'
        ledger.write_bytes(b'history'); ledger.chmod(0o600)
        before = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        self.commands.reset_mock()
        self.commands.side_effect = ['', 'ActiveState=inactive\nUnitFileState=disabled\n']
        install.uninstall()
        self.assertEqual({p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}, before)
        self.assertEqual(self.commands.call_count, 2)
        self.assertEqual(self.commands.call_args_list[0], unittest.mock.call('systemctl', '--user', 'disable', '--now', install.UNIT))

    def test_invalid_paths_and_release_storage_refused(self):
        for value in ('relative', str(self.home) + '/bad\npath', str(self.app.parent)):
            with self.subTest(value=value), patch.dict(os.environ, {'XDG_DATA_HOME': value}):
                with self.assertRaises(ValueError):
                    install.install()
        self.assertEqual(list(self.app.parent.rglob('*')), [self.app, self.app / 'cli.py'])

    def test_unit_quotes_percent_backslash_quote_and_dollar(self):
        self.assertEqual(install.systemd_quote(Path('/a % \\ " $'), executable=True), '"/a %% \\\\ \\" $$"')
        with self.assertRaises(ValueError):
            install.systemd_quote('bad\nvalue')

    def test_old_python_rejected_without_preparation(self):
        import subprocess
        with patch.object(install.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '3 13\n')):
            with self.assertRaisesRegex(ValueError, '3.14'):
                install.install()
        self.assertFalse((self.home / 'data').exists())

    def test_generated_unit_passes_real_systemd_syntax_verification(self):
        import shutil
        import subprocess
        if not shutil.which('systemd-analyze'):
            self.skipTest('systemd-analyze unavailable')
        install.install()
        unit = self.home / 'config/systemd/user/token-activity.service'
        runtime = self.root / 'runtime'; runtime.mkdir(mode=0o700)
        result = subprocess.run(['systemd-analyze', '--user', 'verify', str(unit)],
                                text=True, capture_output=True,
                                env=dict(os.environ, XDG_RUNTIME_DIR=str(runtime)))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_same_content_repairs_launcher_execute_mode(self):
        install.install()
        wrapper = self.home / '.local/bin/token-activity'
        wrapper.chmod(0o600)
        install.install()
        self.assertEqual(wrapper.stat().st_mode & 0o777, 0o700)


if __name__ == '__main__':
    unittest.main()
