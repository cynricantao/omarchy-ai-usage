#!/usr/bin/env python3
"""Prepare the collector backend for an Omarchy plugin checkout.

Omarchy owns plugin placement, bar layout and UI enablement. This installer does
not copy plugins, edit shell/Hermes configuration, install packages or use the
network. Service activation requires --activate. Hermes observer hook installation
is deliberately not included: hooks require separate, profile-scoped manual setup.
Uninstall only disables the service; history, settings and installed files remain.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile

APP = Path(__file__).resolve().parent
PYTHON = Path('/usr/bin/python3')
UNIT = 'token-activity.service'
DEFAULTS = dict(timezone='UTC', default_tool='hermes', daily_budget=None,
                reduced_motion=False, remote_quotas=False, paths={})


def command(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def safe_path(value):
    path = Path(value)
    if not path.is_absolute() or any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        raise ValueError('paths must be absolute and contain no control characters')
    if '..' in path.parts:
        raise ValueError('parent traversal is not supported')
    return path


def check_directory(path, private=False):
    """Check every ancestor without following links; never chmod existing paths."""
    path = safe_path(path)
    for node in reversed((path, *path.parents)):
        if not node.exists() and not node.is_symlink():
            continue
        info = node.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.getuid()):
            raise ValueError('unsafe directory owner or type: ' + str(node))
        if info.st_mode & 0o022:
            raise ValueError('writable shared directory refused: ' + str(node))
        if node == path and (info.st_uid != os.getuid() or (private and info.st_mode & 0o077)):
            raise ValueError('storage directory must be owned and private: ' + str(node))


def check_file(path, private=True):
    if not path.exists() and not path.is_symlink():
        return
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & (0o077 if private else 0o022) or info.st_nlink != 1):
        raise ValueError('unsafe file owner, type, links or permissions: ' + str(path))


def make_directory(path, private=False):
    check_directory(path, private)
    if not path.exists():
        if not path.parent.exists():
            make_directory(path.parent)
        path.mkdir(mode=0o700)
    check_directory(path, private)


def check_storage(path):
    check_directory(path, private=True)
    if path.exists():
        for entry in path.iterdir():
            if entry.is_dir() and not entry.is_symlink():
                check_storage(entry)
            else:
                check_file(entry)


def locations():
    home = safe_path(Path.home())
    data = safe_path(os.environ.get('XDG_DATA_HOME') or home / '.local/share')
    config = safe_path(os.environ.get('XDG_CONFIG_HOME') or home / '.config')
    state = safe_path(os.environ.get('XDG_STATE_HOME') or home / '.local/state')
    return home, data, config, state


def systemd_quote(value, executable=False):
    value = str(safe_path(value)) if isinstance(value, Path) else str(value)
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('control characters are not allowed in unit values')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    if executable:
        value = value.replace('$', '$$')
    return '"' + value + '"'


def payloads(home, data, config, state):
    cli = safe_path(APP / 'cli.py')
    if not cli.is_file():
        raise ValueError('collector cli.py missing from checkout')
    wrapper = home / '.local/bin/token-activity'
    launcher = '#!/bin/sh\nexec ' + shlex.quote(str(PYTHON)) + ' ' + shlex.quote(str(cli)) + ' "$@"\n'
    environment = '\n'.join('Environment=' + systemd_quote(k + '=' + str(v)) for k, v in
                            [('XDG_DATA_HOME', data), ('XDG_CONFIG_HOME', config), ('XDG_STATE_HOME', state)])
    unit = ('[Unit]\nDescription=Token activity local usage collector\n'
            'After=default.target\nStartLimitIntervalSec=300\nStartLimitBurst=3\n\n'
            '[Service]\nType=simple\nExecStart=' + systemd_quote(PYTHON) + ' ' + systemd_quote(cli, executable=True) + ' serve\n' +
            environment + '\nUMask=0077\nNoNewPrivileges=true\nProtectSystem=full\n'
            'Restart=on-failure\nRestartSec=5\nTimeoutStopSec=20\nMemoryMax=512M\n'
            'LogRateLimitIntervalSec=300\nLogRateLimitBurst=30\n\n[Install]\nWantedBy=default.target\n')
    return [(wrapper, launcher.encode(), 0o700),
            (config / 'systemd/user' / UNIT, unit.encode(), 0o600)]


def write_exclusive(path, content, mode):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def write_atomic(path, content, mode):
    fd, temporary = tempfile.mkstemp(prefix='.token-activity-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        check_file(path)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(activate=False, replace=False):
    if sys.version_info < (3, 14):
        raise ValueError('Python 3.14 or newer is required')
    version = subprocess.run([str(PYTHON), '-c', 'import sys; print(sys.version_info.major, sys.version_info.minor)'],
                             check=True, text=True, capture_output=True).stdout.split()
    if tuple(map(int, version)) < (3, 14):
        raise ValueError('/usr/bin/python3 must be Python 3.14 or newer')
    home, data, config, state = locations()
    files = payloads(home, data, config, state)
    stores = [data / 'token-activity', config / 'token-activity', state / 'token-activity']
    for destination in [*stores, *(p.parent for p, _, _ in files)]:
        if destination.is_relative_to(APP.parent):
            raise ValueError('installation storage must be outside the plugin checkout')
        check_directory(destination)
    for store in stores:
        check_storage(store)
    changes = []
    for path, content, mode in files:
        check_file(path)
        old = path.read_bytes() if path.exists() else None
        if old is not None and old != content and not replace:
            raise ValueError('conflicting installed file; use --replace to back up: ' + str(path))
        changes.append((path, content, mode, old))
    settings = config / 'token-activity/settings.json'
    check_file(settings)
    for store in stores:
        make_directory(store, private=True)
    for path, content, mode, old in changes:
        make_directory(path.parent)
        if old == content and stat.S_IMODE(path.lstat().st_mode) == mode:
            continue
        if old is not None and old != content:
            backups = state / 'token-activity/installer-backups'
            make_directory(backups, private=True)
            name = path.name + '.' + os.urandom(16).hex() + '.bak'
            write_exclusive(backups / name, old, 0o600)
        # Refuse a concurrent change rather than replacing a different file.
        check_file(path)
        if (path.read_bytes() if path.exists() else None) != old:
            raise ValueError('installed file changed during preparation')
        write_atomic(path, content, mode)
    if not settings.exists():
        write_exclusive(settings, (json.dumps(DEFAULTS, indent=2) + '\n').encode(), 0o600)
    unit = files[1][0]
    command('systemd-analyze', '--user', 'verify', str(unit))
    if activate:
        command('systemctl', '--user', 'daemon-reload')
        command('systemctl', '--user', 'enable', '--now', UNIT)
        if command('systemctl', '--user', 'is-enabled', UNIT).strip() != 'enabled':
            raise ValueError('service enablement verification failed')
        if command('systemctl', '--user', 'is-active', UNIT).strip() != 'active':
            raise ValueError('service activation verification failed')
    result = dict(installed=True, activated=activate, ledger=str(data / 'token-activity/usage.sqlite3'), observer_installed=False)
    print(json.dumps(result))
    return result


def uninstall():
    command('systemctl', '--user', 'disable', '--now', UNIT)
    state = command('systemctl', '--user', 'show', UNIT, '--property=ActiveState', '--property=UnitFileState')
    properties = dict(line.split('=', 1) for line in state.splitlines() if '=' in line)
    if properties.get('ActiveState') not in ('inactive', 'failed') or properties.get('UnitFileState') not in ('disabled', 'not-found', 'masked'):
        raise ValueError('service disablement verification failed')
    print('Collector disabled. Ledger, spool, settings, launcher, unit and backups preserved. Omarchy owns UI enablement; no Hermes hooks were installed.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'uninstall'])
    parser.add_argument('--activate', action='store_true', help='explicitly enable and start the user service')
    parser.add_argument('--replace', action='store_true', help='back up conflicting owned files outside the checkout before replacing')
    args = parser.parse_args(argv)
    if args.action == 'uninstall':
        if args.activate or args.replace:
            parser.error('install options cannot be used with uninstall')
        uninstall()
    else:
        install(activate=args.activate, replace=args.replace)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print('Installer refused: ' + str(error), file=sys.stderr)
        sys.exit(1)
