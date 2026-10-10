"""Bounded, read-only DSH v4 accounting. Only usage/route metadata survives parsing.

Session logs are authoritative; projection caches and subscription credentials are
not sources. Plain JSONL and concatenated Zstandard frames are both supported.
"""
import json
import re
from pathlib import Path

_CACHE = {}
_FIELDS = dict(input='inputTokens', output='outputTokens',
               cache_read='cacheReadTokens', cache_write='cacheWriteTokens')


def _count(value):
    return type(value) is int and 0 <= value <= 9007199254740991


def _usage(raw, diagnostics):
    if not isinstance(raw, dict):
        return None
    keys = list(_FIELDS.values()) + ['totalTokens', 'reasoningTokens']
    if any(key in raw and not _count(raw[key]) for key in keys):
        diagnostics.add('invalid_usage'); return None
    if any(key not in raw for key in ('inputTokens', 'outputTokens')):
        diagnostics.add('invalid_usage'); return None
    usage = {key: raw.get(field) for key, field in _FIELDS.items()}
    recorded = sum(value for value in usage.values() if value is not None)
    total = raw.get('totalTokens', recorded)
    if not _count(total) or total < recorded or raw.get('reasoningTokens', 0) > usage['output']:
        diagnostics.add('invalid_usage'); return None
    if 'totalTokens' in raw and all(v is not None for v in usage.values()) and total != recorded:
        diagnostics.add('invalid_usage'); return None
    usage['total'] = total
    # Preserve source fields without copying arbitrary payload or content.
    source = {field: raw.get(key) for field, key in dict(
        input_tokens='inputTokens', output_tokens='outputTokens',
        cache_read_tokens='cacheReadTokens', cache_write_tokens='cacheWriteTokens',
        reasoning_tokens='reasoningTokens', total_tokens='totalTokens').items() if key in raw}
    return usage, source


def _sample(data, kind):
    if kind == 'assistant/message' and 'usage' in data:
        return data['usage']
    stream = data.get('stream', [])
    if isinstance(stream, list):
        # AssistantStream records wrap native chunks in {type:'chunk',chunk:...}.
        for record in reversed(stream):
            chunk = record.get('chunk') if isinstance(record, dict) and record.get('type') == 'chunk' else None
            if isinstance(chunk, dict) and chunk.get('type') == 'usage':
                return chunk.get('usage')
    return None


def _rows(path, diagnostics, budget):
    """Bound the decompressed bytes as well as each line, including torn tails."""
    import adapters as a
    try:
        if path.name.endswith('.zstd'):
            try:
                from compression import zstd
            except ImportError:
                diagnostics.add('zstd_unavailable'); return
            stream = zstd.open(path, 'rb')
        else:
            stream = path.open('rb')
        with stream:
            while budget[0] < a.MAX_BYTES:
                limit = min(a.MAX_LINE + 1, a.MAX_BYTES - budget[0] + 1)
                line = stream.readline(limit)
                if not line:return
                budget[0] += len(line)
                if budget[0] > a.MAX_BYTES:
                    diagnostics.add('byte_limit'); return
                if len(line) > a.MAX_LINE:
                    diagnostics.add('line_limit'); return
                if not line.endswith(b'\n'):
                    diagnostics.add('partial_line'); return
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):raise ValueError()
                    yield row
                except (ValueError, UnicodeError):
                    diagnostics.add('invalid_json'); return
            diagnostics.add('byte_limit')
    except (OSError, EOFError):
        diagnostics.add('source_unreadable')
    except Exception as error:
        # compression.zstd is optional on Python <3.14. Do not swallow unrelated
        # programming errors; never expose raw source content in diagnostics.
        if error.__class__.__module__.startswith(('compression.zstd', '_zstd')):
            diagnostics.add('invalid_zstd')
        else:
            raise


def _read(path, home, budget):
    import adapters as a
    diagnostics = set(); rows = _rows(path, diagnostics, budget)
    header = next(rows, None)
    if not header:
        return [], diagnostics
    if (header.get('type') != 'session' or header.get('version') != 4
            or not isinstance(header.get('id'), str) or not header['id']
            or type(header.get('isSeeded')) is not bool
            or not _count(header.get('createdAt')) or not _count(header.get('delegationDepth'))):
        diagnostics.add('unsupported_session_format'); return [], diagnostics
    session = header['id']; expected = 0; inherited_cut = None
    metadata = []; route = (None, None)
    for row in rows:
        if not _count(row.get('seq')) or row['seq'] != expected:
            diagnostics.add('noncontiguous_log'); break
        expected += 1
        if expected > a.MAX_ROWS:
            diagnostics.add('row_limit'); break
        kind = row.get('type'); data = row.get('data')
        if not isinstance(data, dict):
            diagnostics.add('invalid_event'); break
        if kind == 'session/end-seed' and data.get('inherited') is True:
            inherited_cut = row['seq']
        if kind == 'request/context':
            route = (a._label(data.get('provider')), a._label(data.get('model')))
        elif kind == 'request/header':
            request_header = data.get('header')
            config = request_header.get('config') if isinstance(request_header, dict) else None
            if isinstance(config, dict):
                route = (a._label(config.get('provider')), a._label(config.get('model')))
        if kind == 'llm/retry-started':
            metadata.append((kind, data.get('turn'), data.get('step'), (row['seq'], None))); continue
        if kind not in ('assistant/message', 'assistant/attempt'):
            continue
        raw = _sample(data, kind)
        if raw is None:continue
        normalized = _usage(raw, diagnostics)
        if not normalized:continue
        turn, step = data.get('turn'), data.get('step')
        if not _count(turn) or not _count(step):
            diagnostics.add('invalid_attempt_identity'); continue
        provider, model = route
        source = data.get('message', {}).get('source') if isinstance(data.get('message'), dict) else None
        if isinstance(source, dict) and source.get('kind') == 'model':
            provider, model = a._label(source.get('provider')), a._label(source.get('model'))
        stamp = row.get('time')
        if not _count(stamp):
            diagnostics.add('invalid_event_time'); stamp = None
        else:
            stamp = stamp / 1000
        usage, source_usage = normalized
        e = a._event('dsh', home, session, row['seq'], usage, stamp, provider, model)
        e['source_usage'] = source_usage
        metadata.append((kind, turn, step, (row['seq'], e)))
    if header['isSeeded'] and inherited_cut is None:
        diagnostics.add('missing_inherited_cut'); return [], diagnostics
    if not header['isSeeded'] and inherited_cut is not None:
        diagnostics.add('invalid_seed_boundary'); return [], diagnostics
    cut = inherited_cut if header['isSeeded'] else 0
    events = []; last = None
    for kind, turn, step, sample in metadata:
        seq, e = sample
        if seq < cut:continue
        coordinates = (turn, step)
        if kind == 'llm/retry-started':
            if last is not None and last[0] == coordinates:last = None
            continue
        # A terminal message may supersede a durable attempt at the same step.
        # Keep its first sample's stable ledger identity; retries are separate.
        if last is not None and last[0] == coordinates:
            index = last[1]; e['id'] = events[index]['id']; events[index] = e
        else:
            events.append(e); last = (coordinates, len(events)-1)
    return events, diagnostics


def collect(tool):
    import adapters as a
    diagnostics = set(); budget = [0]; generations = {}; events = {}
    homes = tool.get('homes', [])
    pattern = re.compile(r'^session(?:\.v([1-9][0-9]*))?\.jsonl(\.zstd)?$')
    for home in homes:
        for suffix in ('.jsonl.zstd', '.jsonl'):
            for path in a._files([Path(home)/'sessions'], suffix, diagnostics):
                match = pattern.fullmatch(path.name)
                if not match:continue
                parent = str(path.parent.resolve())
                if parent not in generations and len(generations) >= a.MAX_FILES:
                    diagnostics.add('scan_limit'); continue
                generations.setdefault(parent, {})[path.name] = (int(match[1] or 0), bool(match[2]), path, home)
    selected = []
    for candidates in generations.values():
        variants = list(candidates.values())
        if len({variant[1] for variant in variants}) != 1:
            diagnostics.add('mixed_compression'); continue
        version, _, path, home = max(variants, key=lambda variant: variant[0])
        if version != 4:
            diagnostics.add('unsupported_session_format'); continue
        selected.append((path, home))
    for path, home in selected:
        try:
            stat = path.stat()
            if stat.st_size > a.MAX_BYTES:
                diagnostics.add('byte_limit'); continue
            limits = (a.MAX_BYTES, a.MAX_LINE, a.MAX_ROWS)
            signature = (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size, limits)
            key = (str(path), str(home)); previous = _CACHE.get(key)
            if previous and previous[0] == signature:
                rows, notes, size = previous[1:]; budget[0] += size
                if budget[0] > a.MAX_BYTES:
                    diagnostics.add('byte_limit'); break
            else:
                before = budget[0]; rows, notes = _read(path, home, budget)
                after = path.stat()
                # Do not freeze an incomplete snapshot racing an active append.
                if (after.st_mtime_ns, after.st_size) == (stat.st_mtime_ns, stat.st_size) and not notes:
                    if len(_CACHE) >= a.MAX_FILES:_CACHE.clear()
                    _CACHE[key] = (signature, rows, notes, budget[0]-before)
            diagnostics.update(notes)
            for e in rows:events[e['id']] = e
            if budget[0] >= a.MAX_BYTES:
                diagnostics.add('byte_limit'); break
        except OSError:
            diagnostics.add('source_unreadable')
    return dict(events=list(events.values()), counters=[], diagnostics=sorted(diagnostics))
