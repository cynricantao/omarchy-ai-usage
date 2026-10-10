"""Bounded, read-only secondary sources. No content leaves this module."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import sqlite3
import subprocess
import time

MAX_FILES = 2048
MAX_ENTRIES = 20000
MAX_BYTES = 64 * 1024 * 1024
MAX_LINE = 4 * 1024 * 1024
MAX_ROWS = 100000
REGISTRY = {
    'hermes': {'name': 'Hermes', 'binary': 'hermes', 'env': 'HERMES_HOME', 'default': '.hermes', 'capabilities': ['tokens']},
    'codex': {'name': 'Codex', 'binary': 'codex', 'env': 'CODEX_HOME', 'default': '.codex', 'capabilities': ['tokens', 'quota']},
    'claude': {'name': 'Claude Code', 'binary': 'claude', 'env': 'CLAUDE_CONFIG_DIR', 'default': '.claude', 'capabilities': ['tokens']},
    'antigravity': {'name': 'Antigravity', 'binary': 'agy', 'default': '.gemini/antigravity-cli', 'capabilities': ['tokens']},
    'opencode': {'name': 'OpenCode', 'binary': 'opencode', 'default': None, 'capabilities': ['tokens']},
    'commandcode': {'name': 'Command Code', 'binary': 'cmd', 'aliases': ['commandcode', 'command-code', 'cmdc'], 'default': '.commandcode', 'capabilities': ['tokens']},
    'dsh': {'name': 'DSH', 'binary': 'dsh', 'env': 'DSH_HOME', 'default': '.dsh', 'capabilities': ['tokens']},
}


def _npx_dsh_binary(home):
    """Detect an actual cached npx executable, not leftover DSH history."""
    try:
        with os.scandir(home/'.npm/_npx') as entries:
            for index, entry in enumerate(entries):
                if index >= 128:break
                if not entry.is_dir(follow_symlinks=False):continue
                binary=Path(entry.path)/'node_modules/.bin/dsh'
                if binary.is_file() and os.access(binary,os.X_OK):return str(binary)
    except OSError:
        pass
    return None


def discover(settings):
    """Inspect bounded directory metadata only, never config/auth contents."""
    home = Path.home()
    data = Path(os.environ.get('XDG_DATA_HOME', str(home/'.local/share')))
    config = Path(os.environ.get('XDG_CONFIG_HOME', str(home/'.config')))
    paths = settings.get('paths', {}) if isinstance(settings, dict) else {}
    result = []
    for key, spec in REGISTRY.items():
        candidates = [paths.get(key), os.environ.get(spec.get('env', '')),
                      str(home/spec['default']) if spec['default'] else str(data/'opencode')]
        homes = []
        for p in candidates:
            if p and Path(p).is_absolute() and str(Path(p)) not in homes:
                homes.append(str(Path(p)))
        if key == 'hermes':
            for root in list(homes):
                try:
                    with os.scandir(Path(root)/'profiles') as entries:
                        for n, entry in enumerate(entries):
                            if n >= 128:
                                break
                            if not entry.name.startswith('.') and entry.is_dir(follow_symlinks=False):
                                homes.append(entry.path)
                except OSError:
                    pass
        binary = next((found for name in [spec['binary']]+spec.get('aliases', []) if (found := shutil.which(name))), None)
        if key == 'dsh' and not binary:
            binary = _npx_dsh_binary(home)
        present = any(Path(p).is_dir() for p in homes)
        desktop = key == 'claude' and (any((config/p).exists() for p in ('Claude', 'claude-desktop')) or any((data/'applications'/p).is_file() for p in ('claude.desktop', 'claude-desktop.desktop')))
        note = 'Bounded local source discovery; missing metrics are unknown.'
        if key == 'dsh':
            note = 'Read-only DSH v4 session usage, including subagents; inherited fork history excluded. Totals sum recorded disjoint token buckets (matching DSH token meter) unless an exact provider total is present. Unreported cache buckets remain unknown; subscription quotas and live activity are not collected.'
        if key == 'commandcode':
            note = 'Local v3 session usage only; GOAT account credit limits are not collected.'
        if key == 'antigravity':
            note = 'Native CLI generation usage from read-only SQLite metadata; provider quota is not collected.'
        elif desktop and not present and not binary:
            note = 'Stale desktop evidence only; no supported Claude Code source.'
        result.append({'id': key, 'name': spec['name'], 'installed': bool(binary),
                       'homes': homes, 'state': 'source_present' if present else ('installed' if binary else ('stale_evidence' if desktop else 'absent')),
                       'capabilities': list(spec['capabilities']), 'note': note})
    return result


def _hash(*parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _label(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:/+@-]{1,160}', value) else None


def _stamp(value):
    if _number(value) is not None:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo else None
    except (TypeError, ValueError, AttributeError):
        return None


def _sum(*values):
    return sum(values) if all(v is not None for v in values) else None


def _usage(raw, kind):
    raw = raw if isinstance(raw, dict) else {}
    i, o = _number(raw.get('input_tokens')), _number(raw.get('output_tokens'))
    cache = _number(raw.get('cached_input_tokens' if kind == 'codex' else 'cache_read_input_tokens'))
    write = None if kind == 'codex' else _number(raw.get('cache_creation_input_tokens'))
    total = _number(raw.get('total_tokens')) if kind == 'codex' else None
    if kind == 'codex':
        total = total if total is not None else _sum(i, o)
        i = i-cache if i is not None and cache is not None and i >= cache else None
    else:
        total = _sum(i, o, cache, write)
    return {'input': i, 'output': o, 'cache_read': cache, 'cache_write': write, 'total': total}


def _files(roots, suffix, diagnostics):
    pending = [(Path(p), 0) for p in roots]
    seen, count, entries = set(), 0, 0
    while pending:
        directory, depth = pending.pop(0)
        try:
            if directory.is_symlink():
                continue
            with os.scandir(directory) as scan:
                batch = []
                for item in scan:
                    entries += 1
                    if entries > MAX_ENTRIES:
                        diagnostics.add('scan_limit'); return
                    batch.append(item)
            for item in sorted(batch, key=lambda x: x.name):
                if item.is_dir(follow_symlinks=False) and depth < 8:
                    pending.append((Path(item.path), depth+1))
                elif item.is_file(follow_symlinks=False) and item.name.endswith(suffix):
                    stat = item.stat(follow_symlinks=False)
                    identity = (stat.st_dev, stat.st_ino)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    count += 1
                    if count > MAX_FILES:
                        diagnostics.add('scan_limit'); return
                    yield Path(item.path)
        except OSError:
            if directory.exists():
                diagnostics.add('source_unreadable')


def _lines(path, diagnostics, budget):
    try:
        with path.open('rb') as f:
            while budget[0] < MAX_BYTES:
                line = f.readline(MAX_LINE+1)
                if not line:
                    return
                budget[0] += len(line)
                if len(line) > MAX_LINE:
                    diagnostics.add('line_limit'); return
                if not line.endswith(b'\n'):
                    diagnostics.add('partial_line'); return
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        yield row
                except (ValueError, UnicodeError):
                    diagnostics.add('invalid_json')
            diagnostics.add('byte_limit')
    except OSError:
        diagnostics.add('source_unreadable')


def _event(tool, home, session, identity, usage, stamp, provider=None, model=None, task=None):
    source = _hash(tool, session)
    return {'id': _hash(tool, session, identity), 'tool': tool,
            'profile': 'local-profile:'+_hash(str(Path(home).resolve()))[:24],
            'session': _label(session) or _hash(session), 'provider': _label(provider),
            'model': _label(model), 'task': _label(task), 'occurred_at': _stamp(stamp),
            'observed_at': time.time(), 'usage': usage, 'provenance': tool+'_native_local', 'source_key': source}


def _codex(tool):
    events, counters, diagnostics, budget = {}, {}, set(), [0]
    keys = ('input_tokens', 'output_tokens', 'cached_input_tokens', 'total_tokens')
    for home in tool.get('homes', []):
        for path in _files([Path(home)/'sessions', Path(home)/'archived_sessions'], '.jsonl', diagnostics):
            session = None
            provider = model = task = None
            previous = None
            cumulative_mode = None
            generation = 0
            excluded = False
            seen_counts = set()
            for row in _lines(path, diagnostics, budget):
                payload = row.get('payload')
                if not isinstance(payload, dict):
                    continue
                if row.get('type') == 'session_meta':
                    session = payload.get('id')
                    provider = payload.get('model_provider')
                    excluded = payload.get('originator') == 'hermes'
                    if excluded:
                        diagnostics.add('hermes_origin_excluded')
                    elif payload.get('source') not in ('cli', 'vscode') and payload.get('originator') not in ('codex_cli_rs', 'codex_vscode'):
                        diagnostics.add('ambiguous_origin_overlap')
                elif row.get('type') == 'turn_context':
                    model = payload.get('model')
                    provider = payload.get('model_provider') or provider
                    task = payload.get('turn_id')
                elif row.get('type') == 'event_msg' and payload.get('type') == 'token_count' and not excluded:
                    info = payload.get('info')
                    if not isinstance(info, dict):
                        continue
                    if not isinstance(session, str):
                        diagnostics.add('missing_session_identity'); continue
                    total = info.get('total_token_usage')
                    last = info.get('last_token_usage')
                    total = {k: _number(total.get(k)) for k in keys} if isinstance(total, dict) else None
                    last = {k: _number(last.get(k)) for k in keys} if isinstance(last, dict) else None
                    identity = [row.get('timestamp'), total, last, task]
                    fingerprint = _hash(identity)
                    if fingerprint in seen_counts:
                        continue
                    seen_counts.add(fingerprint)
                    raw = last
                    counter = False
                    if cumulative_mode is None:
                        cumulative_mode = total is not None and last is None
                    if cumulative_mode and total is not None:
                        if previous is not None and any(total[k] is not None and previous[k] is not None and total[k] < previous[k] for k in keys):
                            diagnostics.add('cumulative_reset')
                            continue  # retain high-water; replacement is not new spend
                        e = _event('codex', home, session, ['cumulative', generation], _usage(total, 'codex'), None, provider)
                        e.update(key=e['id'], first_seen=None, last_seen=None)
                        old = counters.get(e['id'])
                        if old is None or (e['usage']['total'] or 0) >= (old['usage']['total'] or 0):
                            counters[e['id']] = e
                        previous = total
                        diagnostics.add('undated_cumulative_baseline')
                        continue
                    if total is not None:
                        if previous == total:
                            continue
                        reset = previous is not None and any(total[k] is not None and previous[k] is not None and total[k] < previous[k] for k in keys)
                        if reset:
                            diagnostics.add('cumulative_reset')
                            continue  # no inferred new generation without proven identity
                        if previous is not None and not reset:
                            raw = {k: total[k]-previous[k] if total[k] is not None and previous[k] is not None else None for k in keys}
                        elif raw is None:
                            raw = total
                            counter = True
                            diagnostics.add('undated_cumulative_baseline')
                        elif any(total[k] is not None and raw[k] is not None and total[k] > raw[k] for k in keys):
                            # A truncated prefix may already be in the ledger or another
                            # rotated source. Do not re-add it as an anonymous total.
                            diagnostics.add('unobserved_cumulative_prefix')
                        previous = total
                    if raw is None:
                        continue
                    event = _event('codex', home, session, identity, _usage(raw, 'codex'), None if counter else row.get('timestamp'), provider, model, task)
                    if total is not None:
                        event['cumulative_usage'] = _usage(total, 'codex')
                    event['source_usage'] = dict(raw)
                    if counter:
                        event.update(key=event['id'], first_seen=None, last_seen=None)
                        counters[event['id']] = event
                    else:
                        events[event['id']] = event
    return {'events': list(events.values()), 'counters': list(counters.values()), 'diagnostics': sorted(diagnostics)}


def _claude(tool):
    events, ranks, diagnostics, budget = {}, {}, set(), [0]
    for home in tool.get('homes', []):
        for path in _files([Path(home)/'projects'], '.jsonl', diagnostics):
            for row in _lines(path, diagnostics, budget):
                message = row.get('message')
                if row.get('type') != 'assistant' or not isinstance(message, dict) or message.get('role') != 'assistant':
                    continue
                session, mid = row.get('sessionId'), message.get('id')
                if not isinstance(session, str) or not isinstance(mid, str):
                    diagnostics.add('missing_message_identity'); continue
                if not isinstance(message.get('usage'), dict):
                    continue
                event = _event('claude', home, session, mid, _usage(message['usage'], 'claude'), row.get('timestamp'), None, message.get('model'))
                event['source_usage'] = {k:v for k,v in message['usage'].items() if k in ('input_tokens','output_tokens','cache_read_input_tokens','cache_creation_input_tokens')}
                # Stop-marked final messages outrank earlier streaming fragments;
                # otherwise later timestamps win, with output progress breaking ties.
                rank = (bool(message.get('stop_reason')), event['occurred_at'] or 0, event['usage']['output'] or 0)
                if rank >= ranks.get(event['id'], (-1, -1, -1)):
                    events[event['id']] = event
                    ranks[event['id']] = rank
    return {'events': list(events.values()), 'counters': [], 'diagnostics': sorted(diagnostics)}


def _opencode(tool):
    events, diagnostics = {}, set()
    for home in tool.get('homes', []):
        path = Path(home)/'opencode.db'
        if not path.is_file():
            continue
        db = None
        try:
            db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=1)
            db.execute('PRAGMA query_only=ON')
            deadline = time.monotonic()+5
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            columns = {row[1] for row in db.execute('PRAGMA table_info(message)')}
            if not {'id', 'session_id', 'data'} <= columns:
                diagnostics.add('unsupported_opencode_schema'); continue
            # Never materialize entire JSON messages or join content/part tables.
            rows = db.execute("""SELECT id, session_id,
                json_extract(data,'$.modelID'), json_extract(data,'$.providerID'),
                json_extract(data,'$.time.created'), json_extract(data,'$.tokens.input'),
                json_extract(data,'$.tokens.output'), json_extract(data,'$.tokens.cache.read'),
                json_extract(data,'$.tokens.cache.write')
                FROM message WHERE CASE WHEN json_valid(data) THEN
                json_extract(data,'$.role')='assistant' ELSE 0 END ORDER BY id LIMIT ?""", (MAX_ROWS+1,))
            for n, row in enumerate(rows):
                if n >= MAX_ROWS:
                    diagnostics.add('row_limit'); break
                mid, session, model, provider, stamp, i, o, cache, write = row
                if not isinstance(mid, str) or not isinstance(session, str):
                    diagnostics.add('missing_message_identity'); continue
                usage = _usage({'input_tokens': i, 'output_tokens': o, 'cache_read_input_tokens': cache, 'cache_creation_input_tokens': write}, 'opencode')
                event = _event('opencode', home, session, mid, usage, stamp/1000 if _number(stamp) is not None else None, provider, model)
                events[event['id']] = event
        except sqlite3.Error:
            diagnostics.add('opencode_read_failed')
        finally:
            if db is not None:
                db.close()
    return {'events': list(events.values()), 'counters': [], 'diagnostics': sorted(diagnostics)}


REGISTRY['codex']['collect'] = _codex
REGISTRY['opencode']['collect'] = _opencode
REGISTRY['claude']['collect'] = _claude


QUOTA_TIMEOUT = 15.0


class _QuotaError(Exception):
    def __init__(self, status):
        self.status = status


def _error_status(error):
    error = error if isinstance(error, dict) else {}
    code = error.get('code')
    message = str(error.get('message', '')).lower()
    if code in (401, 403) or any(x in message for x in ('unauthorized', 'not authenticated', 'not logged in', 'requires authentication', 'authentication required')):
        return 'unauthorized'
    if code == 429 or 'rate limit' in message or 'too many requests' in message:
        return 'rate_limited'
    return 'offline'


class _NativeRPC:
    """A deadline-bounded, line-delimited native client; never logs wire data."""
    def __init__(self, binary, home):
        self.deadline = time.monotonic()+QUOTA_TIMEOUT
        env = {k: v for k, v in os.environ.items() if k in ('HOME', 'PATH', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR', 'LANG', 'SSL_CERT_FILE', 'SSL_CERT_DIR')}
        env['CODEX_HOME'] = str(home)
        self.process = subprocess.Popen([binary, 'app-server', '--listen', 'stdio://'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env,
                                        start_new_session=True, bufsize=0)
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.buffer = b''
        self.received = 0
        self.seq = 0

    def send(self, message):
        self.process.stdin.write((json.dumps(message)+'\n').encode())
        self.process.stdin.flush()

    def request(self, method, params):
        self.seq += 1
        self.send({'id': self.seq, 'method': method, 'params': params})
        while True:
            remaining = self.deadline-time.monotonic()
            if remaining <= 0:
                raise _QuotaError('timeout')
            if b'\n' not in self.buffer:
                if not self.selector.select(remaining):
                    raise _QuotaError('timeout')
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    raise _QuotaError('offline')
                self.received += len(chunk)
                if self.received > 4*1024*1024:
                    raise _QuotaError('offline')
                self.buffer += chunk
                continue
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                message = json.loads(line)
            except (ValueError, UnicodeError):
                raise _QuotaError('offline') from None
            if not isinstance(message, dict) or message.get('id') != self.seq or 'method' in message:
                continue
            if 'error' in message:
                raise _QuotaError(_error_status(message['error']))
            if not isinstance(message.get('result'), dict):
                raise _QuotaError('offline')
            return message['result']

    def close(self):
        self.selector.close()
        try:
            # Codex may be a JS launcher wrapping a native child process.
            os.killpg(self.process.pid, 9)
        except ProcessLookupError:
            pass
        self.process.wait(timeout=1)
        self.process.stdin.close()
        self.process.stdout.close()


def _quota_rows(data, account_id):
    by_id = data.get('rateLimitsByLimitId')
    groups = list(by_id.items())[:128] if isinstance(by_id, dict) and by_id else [('codex', data.get('rateLimits'))]
    rows = []
    for group, limits in groups:
        if not isinstance(limits, dict):
            continue
        for window in ('primary', 'secondary'):
            value = limits.get(window)
            if not isinstance(value, dict):
                continue
            used = _number(value.get('usedPercent'))
            minutes = _number(value.get('windowDurationMins'))
            span = ('7 days' if minutes == 10080 else str(int(minutes/60))+'h' if minutes and minutes % 60 == 0 else str(int(minutes))+'m') if minutes is not None else window+' (duration unknown)'
            rows.append({'account_id': account_id, 'label': (_label(group) or 'quota')+' · '+span,
                         'used_percent': used, 'remaining_percent': max(0, 100-used) if used is not None else None,
                         'resets_at': _stamp(value.get('resetsAt')), 'observed_at': time.time(), 'status': 'ok'})
    return rows


def _account_usage(data):
    summary = data.get('summary')
    if not isinstance(summary, dict):
        return None
    clean = {k: _number(summary.get(k)) for k in ('lifetimeTokens', 'currentStreakDays', 'longestRunningTurnSec', 'longestStreakDays', 'peakDailyTokens')}
    buckets = data.get('dailyUsageBuckets')
    days = None
    if isinstance(buckets, list):
        days = []
        for bucket in buckets[:10000]:
            if isinstance(bucket, dict) and isinstance(bucket.get('startDate'), str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', bucket['startDate']):
                days.append({'startDate': bucket['startDate'], 'tokens': _number(bucket.get('tokens'))})
    return {'summary': clean, 'dailyUsageBuckets': days}


def quota_read(codex_home):
    """Only native account reads. No auth file reads, refresh, turns or tools."""
    result = {'quotas': [], 'status': 'offline', 'account_usage': None}
    binary = shutil.which('codex')
    if not binary or not Path(codex_home).is_absolute():
        return result
    rpc = None
    try:
        rpc = _NativeRPC(binary, codex_home)
        rpc.request('initialize', {'clientInfo': {'name': 'token_activity', 'title': 'Token Activity', 'version': '1.0'},
                                   'capabilities': {'experimentalApi': True}})
        rpc.send({'method': 'initialized', 'params': {}})
        account = rpc.request('account/read', {'refreshToken': False}).get('account')
        if not isinstance(account, dict):
            raise _QuotaError('unauthorized')
        aid = account.get('accountId') or account.get('id')
        account_id = 'account:'+_hash('codex', aid) if isinstance(aid, str) and aid else 'local-profile-unverified:'+_hash(str(Path(codex_home).resolve()))
        limits = rpc.request('account/rateLimits/read', {'excludeResetCreditDetails': True, 'supportsLunaReserve': False})
        result['quotas'] = _quota_rows(limits, account_id)
        result['status'] = 'ok'
        result['identity_scope'] = 'account' if account_id.startswith('account:') else 'local_profile_unverified_cross_tool'
        try:
            usage = rpc.request('account/usage/read', {})
            result['account_usage'] = _account_usage(usage)
        except _QuotaError as error:
            result['account_usage_status'] = error.status
    except _QuotaError as error:
        result['status'] = error.status
    except (OSError, ValueError, subprocess.SubprocessError):
        result['status'] = 'offline'
    finally:
        if rpc is not None:
            rpc.close()
    return result


_COLLECTION_CACHE = {}

def collect(tool):
    key = tool.get('id')
    if key == 'dsh':
        from dsh_source import collect as collect_dsh
        return collect_dsh(tool)
    if key == 'commandcode':
        from commandcode_source import collect as collect_commandcode
        return collect_commandcode(tool)
    if key == 'antigravity':
        from antigravity_source import collect as collect_antigravity
        return collect_antigravity(tool)
    parser = REGISTRY.get(key, {}).get('collect')
    if parser:
        homes=tool.get('homes',[]);diagnostics=set()
        if key in ('codex','claude'):
            roots=[Path(h)/part for h in homes for part in (('sessions','archived_sessions') if key=='codex' else ('projects',))]
            files=list(_files(roots,'.jsonl',diagnostics))
        else:files=[Path(h)/name for h in homes for name in ('opencode.db','opencode.db-wal') if (Path(h)/name).exists()]
        signature=[]
        for p in files:
            try:
                s=p.stat();signature.append((str(p),s.st_dev,s.st_ino,s.st_mtime_ns,s.st_size))
            except OSError:signature.append((str(p),'unavailable'))
        cache_key=(key,tuple(homes),MAX_FILES,MAX_BYTES,MAX_ROWS)
        previous=_COLLECTION_CACHE.get(cache_key)
        if previous and previous[0]==signature:return previous[1]
        result=parser(tool)
        result['diagnostics']=sorted(set(result['diagnostics'])|diagnostics)
        if len(_COLLECTION_CACHE)>32:_COLLECTION_CACHE.clear()
        _COLLECTION_CACHE[cache_key]=(signature,result)
        return result
    return {'events': [], 'counters': [], 'diagnostics': ['unsupported_source_token_accounting' if key == 'antigravity' else 'unsupported_adapter']}
