"""Hermes 0.21.5 usage-only SQLite adapter; never imports the agent runtime."""
import sqlite3
from contextlib import closing
from pathlib import Path
try:
    from .core import identity
except ImportError:
    from core import identity

TOKEN_COLUMNS=('input_tokens','output_tokens','cache_read_tokens','cache_write_tokens')

def profile_id(home): return str(Path(home).expanduser().resolve())

def route_key(profile,session,model,provider,base_url,task=''):
    # Base URL is an identity ingredient only, never emitted or stored verbatim.
    return identity('hermes',profile,session,model or 'Unattributed',provider or '',base_url or '',task or '')

def normalize(row):
    vals=[row[x] if x in row.keys() else None for x in TOKEN_COLUMNS]
    return dict(zip(('input','output','cache_read','cache_write','total'),vals+[sum(vals) if all(x is not None for x in vals) else None]))

def collect_home(home):
    home=Path(home).expanduser().resolve(); profile=profile_id(home)
    p=home/'state.db'; result={'events':[],'counters':[],'diagnostics':[]}
    if not p.exists(): return result
    with closing(sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=1)) as db:
        db.execute('pragma query_only=ON');db.row_factory=sqlite3.Row
        db.execute('BEGIN')  # coherent WAL-aware read transaction across both tables
        cols={r[1] for r in db.execute('pragma table_info(session_model_usage)')}
        required={'session_id','model','billing_provider','billing_base_url','task','api_call_count','first_seen','last_seen',*TOKEN_COLUMNS}
        if not required<=cols: raise ValueError('unsupported Hermes accounting schema')
        # Billing-mode splits retain distinct consumption but share hook identity.
        query='SELECT session_id,model,billing_provider,billing_base_url,task,SUM(api_call_count) AS api_call_count,MIN(first_seen) AS first_seen,MAX(last_seen) AS last_seen,'+','.join('SUM('+c+') AS '+c for c in TOKEN_COLUMNS+('reasoning_tokens',))+' FROM session_model_usage GROUP BY session_id,model,billing_provider,billing_base_url,task'
        for r in db.execute(query):
            result['counters'].append(dict(key=route_key(profile,r['session_id'],r['model'],r['billing_provider'],r['billing_base_url'],r['task']),tool='hermes',profile=profile,session=r['session_id'],provider=r['billing_provider'] or None,model=r['model'] or 'Unattributed',task=r['task'],first_seen=r['first_seen'],last_seen=r['last_seen'],api_calls=r['api_call_count'],usage=normalize(r),provenance='hermes-model'))
            result['counters'][-1]['source_usage']={k:r[k] for k in TOKEN_COLUMNS+('reasoning_tokens','api_call_count')}
        for r in db.execute('SELECT id,api_call_count,'+','.join(TOKEN_COLUMNS)+' FROM sessions'):
            result['counters'].append(dict(key=identity('hermes-summary',profile,r['id']),tool='hermes',profile=profile,session=r['id'],provider=None,model='Unattributed',task='',first_seen=None,last_seen=None,api_calls=r['api_call_count'],usage=normalize(r),provenance='hermes-summary'))
    return result
