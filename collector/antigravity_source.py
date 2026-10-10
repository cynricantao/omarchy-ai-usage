"""Antigravity CLI 1.2.14 native SQLite metadata; never exports prompt content.
Field numbers verified against the installed CLI's embedded protobuf descriptors.
Count gen_metadata.chat_model.usage once per generation, not per duplicated step.
"""
from pathlib import Path
import sqlite3

MAX_BLOB = 4 * 1024 * 1024

def _varint(data, pos):
    value = 0
    for shift in range(0, 70, 7):
        if pos >= len(data):
            raise ValueError('truncated varint')
        byte = data[pos]; pos += 1
        value |= (byte & 127) << shift
        if byte < 128:
            return value, pos
    raise ValueError('oversized varint')

def _fields(data):
    if not isinstance(data, bytes) or len(data) > MAX_BLOB:
        raise ValueError('invalid metadata size')
    pos = 0
    while pos < len(data):
        tag, pos = _varint(data, pos)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise ValueError('invalid tag')
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 2:
            size, pos = _varint(data, pos)
            value = data[pos:pos+size]; pos += size
        elif wire in (1, 5):
            size = 8 if wire == 1 else 4
            value = data[pos:pos+size]; pos += size
        else:
            raise ValueError('unsupported wire type')
        if pos > len(data):
            raise ValueError('truncated field')
        yield number, wire, value

def collect(tool):
    from adapters import _event, _files, MAX_ROWS
    events, diagnostics = {}, set()
    paths = _files([Path(h)/'conversations' for h in tool.get('homes', [])], '.db', diagnostics)
    for path in paths:
        db = None
        try:
            db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=0.2)
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda: 1, 10000000)
            stamps = {}
            for idx, raw in db.execute('SELECT idx,metadata FROM steps LIMIT ?', (MAX_ROWS,)):
                try:
                    metadata = {n:v for n,w,v in _fields(raw or b'') if w==2 and n in (1,7,8)}
                    stamp = metadata.get(7) or metadata.get(8) or metadata.get(1)
                    if stamp:
                        ts = {n:v for n,w,v in _fields(stamp) if w==0}
                        stamps[idx] = ts.get(1,0)+ts.get(2,0)/1e9
                except ValueError:
                    diagnostics.add('invalid_antigravity_metadata')
            for idx, raw in db.execute('SELECT idx,data FROM gen_metadata LIMIT ?', (MAX_ROWS,)):
                try:
                    generation = list(_fields(raw))
                    chat = next((v for n,w,v in generation if n==1 and w==2), None)
                    if chat is None:
                        continue
                    selected = {n:v for n,w,v in _fields(chat) if n in (4,19,21,22) and w==2}
                    if 4 not in selected:
                        continue
                    usage = {n:v for n,w,v in _fields(selected[4]) if w==0 and n in (2,3,4,5)}
                    if not usage:
                        continue
                    # Protobuf scalar omission means zero within a present usage message.
                    inp, out, cache = usage.get(2,0), usage.get(3,0), usage.get(5,0)
                    step_ids=[]
                    for n,w,v in generation:
                        if n==2 and w==0:step_ids.append(v)
                        elif n==2 and w==2:
                            p=0
                            while p<len(v):s,p=_varint(v,p);step_ids.append(s)
                    stamp = max((stamps[s] for s in step_ids if s in stamps), default=None)
                    model = next((selected[n].decode('utf-8') for n in (22,19,21) if selected.get(n)), None)
                    metrics={'input':inp-cache if inp>=cache else None,'output':out,'cache_read':cache,'cache_write':usage.get(4),'total':inp+out}
                    event=_event('antigravity',path.parent.parent,path.stem,['generation',idx],metrics,stamp,model=model)
                    events[event['id']]=event
                except (ValueError,UnicodeError):
                    diagnostics.add('invalid_antigravity_metadata')
        except (sqlite3.Error,OSError):
            diagnostics.add('antigravity_source_unavailable')
        finally:
            if db is not None:db.close()
    return {'events':list(events.values()),'counters':[],'diagnostics':sorted(diagnostics)}


def quota_read(binary=None):
    """Read provider quotas via AGY's native, zero-turn /usage command.

    Provider groups are shared budgets, NOT independent per-model allowances.
    The CLI owns authentication; neither credentials nor response text are read.
    """
    import json
    import os
    import shutil
    import subprocess
    import tempfile
    import time
    from adapters import _hash, _label, _number, _stamp

    result = dict(tool='antigravity', status='unavailable', quotas=[])
    binary = binary or shutil.which('agy')
    if not binary:
        return result
    try:
        with tempfile.TemporaryDirectory(prefix='token-activity-quota-', dir=os.environ.get('TMPDIR')) as cwd:
            from bounded_process import bounded_run
            process = bounded_run(
                [binary, '--print', '/usage', '--output-format', 'json', '--print-timeout', '10s'],
                cwd=cwd, timeout=15, limit=1024*1024)
        if process.returncode or len(process.stdout) > 1024*1024:
            result['status'] = 'offline'
            return result
        data = json.loads(process.stdout)
        command = data.get('command') if isinstance(data, dict) else None
        if not isinstance(data,dict) or data.get('status') != 'SUCCESS' or data.get('num_turns') != 0 or not isinstance(command, dict) or command.get('name') != 'usage':
            return result
        summary = command.get('data')
        groups = summary.get('groups') if isinstance(summary, dict) else None
        if not isinstance(groups, list):
            return result
        observed = time.time()
        account = 'local-profile-unverified:'+_hash('antigravity', str(Path.home()))
        for group in groups[:128]:
            if not isinstance(group, dict) or not isinstance(group.get('buckets'), list):
                continue
            # Human-readable provider group names contain spaces; identifier
            # validation remains strict for bucket IDs and window keys.
            name = group.get('name')
            model = name[:160] if isinstance(name, str) and name.isprintable() else None
            description = group.get('description')
            description = description[:500] if isinstance(description, str) and description.isprintable() else None
            for bucket in group['buckets'][:128]:
                if not isinstance(bucket, dict) or bucket.get('disabled'):
                    continue
                window = _label(bucket.get('window'))
                if not window:
                    continue
                fraction = _number(bucket.get('remaining_fraction'))
                if fraction is not None and not 0 <= fraction <= 1:
                    continue
                remaining = fraction*100 if fraction is not None else None
                result['quotas'].append(dict(
                    account_id=account, tool='antigravity', source='native_cli_usage',
                    label=(model or 'Antigravity')+' · '+window,
                    quota_id=_label(bucket.get('id')), model=model, model_scope='shared_group',
                    models_description=description, window=window,
                    window_minutes={'5h':300, 'weekly':10080}.get(window),
                    remaining_percent=remaining, used_percent=100-remaining if remaining is not None else None,
                    resets_at=_stamp(bucket.get('reset_time')), observed_at=observed, status='ok'))
        result['status'] = 'ok' if result['quotas'] else 'unavailable'
        result['identity_scope'] = 'local_profile_unverified_cross_tool'
    except subprocess.TimeoutExpired:
        result['status'] = 'timeout'
    except (OSError, ValueError, TypeError, AttributeError):
        result['status'] = 'offline'
    return result
