"""Fail-open observer: strict usage allowlist, fsynced spool, no network or agent writes."""
import functools
import json
import os
import tempfile
import time
from pathlib import Path
try:
    from .core import identity, safe_event
    from .hermes_source import profile_id, route_key
except ImportError:
    from core import identity, safe_event
    from hermes_source import profile_id, route_key

def atomic_json(path,value):
    try:
        from .private_storage import private_dir
    except ImportError:
        from private_storage import private_dir
    path=Path(path);private_dir(path.parent)
    if path.is_symlink():raise ValueError("symlink output refused")
    fd,name=tempfile.mkstemp(prefix='.',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:
            json.dump(value,f,separators=(',',':'),allow_nan=False);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
        d=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(d)
        finally: os.close(d)
    except BaseException:
        try:os.unlink(name)
        except OSError:pass
        raise

def capture(kind,kw,root=None,home=None):
    root=Path(root or Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local/share'))/'token-activity')
    try:
        from .private_storage import private_dir
    except ImportError:
        from private_storage import private_dir
    private_dir(root)
    home=Path(home or os.environ.get('HERMES_HOME',Path.home()/'.hermes'))
    profile=profile_id(home);session=str(kw.get('session_id') or '')
    request=str(kw.get('api_request_id') or '')
    model=str(kw.get('model') or 'Unattributed');provider=str(kw.get('provider') or '')
    task=str(kw.get('aux_task') or '')
    stamp=kw.get('ended_at') or kw.get('started_at') or time.time()
    if kind in ('pre_llm_call','on_session_end','pre_auxiliary_call','post_auxiliary_call','api_request_error'):
        active=kind in ('pre_llm_call','pre_auxiliary_call')
        state=dict(profile=profile,session=session,model=model,request=request,observed_at=time.time(),active=active,error=kind=='api_request_error')
        atomic_json(root/'activity'/('h-'+identity(profile,session,request if task else '')+'.json'),state)
    if kind not in ('post_api_request','post_auxiliary_call'):return
    raw=kw.get('usage')
    if not request or not isinstance(raw,dict) or kw.get('error'):return
    # Hermes CanonicalUsage separates uncached input from cache, includes
    # reasoning in output. Missing categories stay null; no extra reasoning.
    u={k:raw.get(k+'_tokens') for k in ('input','output','cache_read','cache_write')}
    u['total']=raw.get('total_tokens')
    if u['total'] is None and all(u[k] is not None for k in ('input','output','cache_read','cache_write')):
        u['total']=sum(u[k] for k in ('input','output','cache_read','cache_write'))
    e=safe_event(dict(id='hermes-hook:'+identity(profile,request),tool='hermes',profile=profile,session=session,provider=provider or None,model=str(kw.get('response_model') or model),task=task,occurred_at=stamp,observed_at=time.time(),usage=u,provenance='hermes-hook',source_key=route_key(profile,session,model,provider,str(kw.get('base_url') or ''),task)))
    e['source_usage']={k:v for k,v in raw.items() if k in ('input_tokens','output_tokens','cache_read_tokens','cache_write_tokens','reasoning_tokens','total_tokens') and (v is None or type(v) is int and v>=0)}
    atomic_json(root/'spool'/(identity(profile,request)+'.json'),{'version':1,'event':e})

def _callback(kind,**kwargs):
    try:capture(kind,kwargs)
    except Exception:
        # No payload/error text: provider exceptions may contain credentials.
        import logging
        logging.getLogger('token-activity').warning('usage observer could not persist metadata')

def register(ctx):
    for kind in ('pre_llm_call','on_session_end','pre_auxiliary_call','post_auxiliary_call','post_api_request','api_request_error'):
        ctx.register_hook(kind,functools.partial(_callback,kind))
