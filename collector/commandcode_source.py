"""Read-only Command Code v3 JSONL usage; schema inspected in npm 1.74.1.

Never retain messages, cwd, credentials or inferred provider/quota data.
AI SDK inputTokens includes cache details; total is input + output.
"""
from pathlib import Path
from adapters import _files, _lines, _number, _sum, _event, _hash


def collect(tool):
    events, diagnostics, budget = {}, set(), [0]
    for home in tool.get('homes', []):
        for path in _files([Path(home)/'projects'], '.jsonl', diagnostics):
            if any(part in path.name for part in ('.checkpoints.', '.prompts.', '.v2.bak')):
                continue
            session = None
            for row in _lines(path, diagnostics, budget):
                if row.get('type') == 'session':
                    session = row.get('id') if row.get('version') == 3 and isinstance(row.get('id'), str) else None
                    if session is None:
                        diagnostics.add('unsupported_commandcode_schema')
                    continue
                message, raw = row.get('message'), row.get('usage')
                if row.get('type') != 'message' or not isinstance(message, dict) or message.get('role') != 'assistant' or not isinstance(raw, dict):
                    continue
                mid = row.get('id')
                if not session or not isinstance(mid, str):
                    diagnostics.add('missing_message_identity')
                    continue
                i, o, read, write = (_number(raw.get(k)) for k in ('inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens'))
                caches = _sum(read, write)
                usage = dict(input=i-caches if i is not None and caches is not None and i >= caches else None,
                             output=o, cache_read=read, cache_write=write, total=_sum(i, o))
                if i is not None and caches is not None and i < caches:
                    diagnostics.add('inconsistent_cache_usage')
                event = _event('commandcode', home, session, mid, usage, row.get('timestamp'), model=row.get('model'))
                # Fork/clone transcripts preserve entry IDs and timestamps. Count once
                # across sessions and rotated files; don't charge copied history again.
                event['id'] = _hash('commandcode', mid, row.get('timestamp'))
                events[event['id']] = event
    return dict(events=list(events.values()), counters=[], diagnostics=sorted(diagnostics))
