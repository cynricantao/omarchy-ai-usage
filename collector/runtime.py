"""Service and CLI helpers. All ledger writes require the same process lock."""
import fcntl
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from observer import atomic_json
from private_storage import private_file

DEFAULTS = dict(timezone='UTC', default_tool='hermes', daily_budget=None,
                reduced_motion=False, remote_quotas=False, paths={})
TOOLS = ('hermes', 'codex', 'claude', 'antigravity', 'opencode', 'commandcode', 'dsh')

class WriterLock:
    def __init__(self, root):
        self.path = Path(root) / 'collector.lock'
        self.file = None
    def __enter__(self):
        self.file = os.fdopen(private_file(self.path), 'r+')
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.file.close()
            raise
        return self
    def __exit__(self, *args):
        self.file.close()


def validate_settings(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('unsupported settings key')
    data = dict(DEFAULTS, **value)
    try:
        ZoneInfo(data['timezone'])
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ValueError('invalid timezone') from None
    if data['default_tool'] not in TOOLS:
        raise ValueError('unsupported default tool')
    budget = data['daily_budget']
    if budget is not None and (type(budget) is not int or budget <= 0):
        raise ValueError('daily budget must be a positive integer or null')
    if type(data['reduced_motion']) is not bool or type(data['remote_quotas']) is not bool:
        raise ValueError('motion and remote quota settings must be boolean')
    paths = data['paths']
    if not isinstance(paths, dict) or set(paths) - set(TOOLS):
        raise ValueError('unsupported source path')
    for value in paths.values():
        if not isinstance(value, str) or not Path(value).is_absolute() or '\x00' in value or len(value) > 4096:
            raise ValueError('source paths must be absolute')
    return dict(data, paths=dict(paths))


def load_settings(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('settings symlinks are unsupported')
    if not path.exists():
        return validate_settings({})
    if path.stat().st_size > 65536:
        raise ValueError('oversized settings')
    return validate_settings(json.loads(path.read_text()))


def public_settings(data):
    validated = validate_settings(data)
    return {key: validated[key] for key in DEFAULTS}


def configure(path, changes):
    if not isinstance(changes, dict) or set(changes) - set(DEFAULTS):
        raise ValueError('unsupported settings key')
    data = load_settings(path)
    if 'paths' in changes and isinstance(changes['paths'], dict):
        changes = dict(changes, paths=dict(data['paths'], **changes['paths']))
    data.update(changes)
    data = validate_settings(data)
    atomic_json(path, data)
    return data
