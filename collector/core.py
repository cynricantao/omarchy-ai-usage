"""Token activity's single-writer, usage-only durable ledger. Python stdlib only."""
import hashlib
import json
import math
import os
import sqlite3
import time
from pathlib import Path
try:
    from .private_storage import private_file, check_file
except ImportError:
    from private_storage import private_file, check_file

FIELDS=('input','output','cache_read','cache_write','total')
META=('id','tool','profile','session','provider','model','task','occurred_at','observed_at','provenance','source_key','interval_start','interval_end')

def packed(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)

def identity(*parts):
    return hashlib.sha256(packed(parts).encode()).hexdigest()

def usage(values):
    out={}
    for k in FIELDS:
        v=values.get(k)
        if v is not None and (isinstance(v,bool) or not isinstance(v,int) or v<0):
            raise ValueError('invalid token field '+k)
        out[k]=v
    return out

def safe_event(event):
    if not isinstance(event,dict) or not isinstance(event.get('usage'),dict):
        raise ValueError('invalid event object')
    e={k:event.get(k) for k in META}
    for key in ('occurred_at','observed_at','interval_start','interval_end'):
        value=e[key]
        if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0):
            raise ValueError('invalid timestamp '+key)
    e['usage']=usage(event['usage'])
    e['normalization_version']=1
    source_fields=('input_tokens','output_tokens','cache_read_tokens','cache_write_tokens','reasoning_tokens','total_tokens','cached_input_tokens','cache_read_input_tokens','cache_creation_input_tokens','api_call_count')
    e['source_usage']={k:v for k,v in event.get('source_usage',{}).items() if k in source_fields and (v is None or type(v) is int and v>=0)}
    if event.get('cumulative_usage') is not None:
        e['cumulative_usage']=usage(event['cumulative_usage'])
    for k in ('id','tool','profile','session','provider','model','task','provenance','source_key'):
        if e[k] is not None and (not isinstance(e[k],str) or len(e[k])>1024):
            raise ValueError('invalid metadata '+k)
    if not e['id'] or not e['tool']: raise ValueError('missing stable event identity')
    return e

class Ledger:
    def __init__(self,path):
        self.path=Path(path)
        fd=private_file(self.path);os.close(fd)
        for suffix in ('-wal','-shm','-journal'):
            sidecar=Path(str(self.path)+suffix)
            if sidecar.exists() or sidecar.is_symlink():check_file(sidecar)
        self.db=sqlite3.connect(self.path,timeout=5)
        self.db.execute('pragma journal_mode=WAL'); self.db.execute('pragma synchronous=FULL')
        self.db.execute('pragma foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY, applied REAL NOT NULL);
        INSERT OR IGNORE INTO migrations VALUES(1,unixepoch());
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS event_revisions(seq INTEGER PRIMARY KEY, id TEXT NOT NULL, observed REAL NOT NULL, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS checkpoints(source TEXT PRIMARY KEY,data TEXT NOT NULL,observed REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS health(source TEXT PRIMARY KEY,status TEXT NOT NULL,observed REAL NOT NULL);
        ''')
    def close(self): self.db.close()
    def ingest(self,events=(),checkpoints=None):
        with self.db:
            for raw in sorted(events,key=lambda x:x.get('occurred_at') or 0):
                e=safe_event(raw); data=packed(e)
                old=self.db.execute('select data from events where id=?',(e['id'],)).fetchone()
                if old:
                    prev=json.loads(old[0]); prev['observed_at']=e['observed_at']
                    if packed(prev)==data: continue
                if not old and e.get('cumulative_usage') is not None:
                    key='stream:'+str(e['source_key'])
                    prior=self.db.execute('select data from checkpoints where source=?',(key,)).fetchone()
                    current=e['cumulative_usage']
                    if prior:
                        previous=json.loads(prior[0])
                        if current['total'] is not None and previous['total'] is not None and current['total']<=previous['total']:
                            self.diagnose(key,'replayed/reset/late cumulative observation quarantined; no inferred new spend')
                            continue
                    self.db.execute('insert into checkpoints values(?,?,?) on conflict(source) do update set data=excluded.data,observed=excluded.observed',(key,packed(current),time.time()))
                self.db.execute('insert into event_revisions(id,observed,data) values(?,?,?)',(e['id'],time.time(),data))
                self.db.execute('insert into events values(?,?) on conflict(id) do update set data=excluded.data',(e['id'],data))
            for key,value in (checkpoints or {}).items():
                self.db.execute('insert into checkpoints values(?,?,?) on conflict(source) do update set data=excluded.data,observed=excluded.observed',(key,packed(value),time.time()))
    def diagnose(self,source,status):
        self.db.execute('insert into health values(?,?,?) on conflict(source) do update set status=excluded.status,observed=excluded.observed WHERE health.status != excluded.status',(source,status,time.time()))

    def reconcile(self,counters):
        # Checkpoint advancement and append-only delta creation share one transaction.
        with self.db:
            for raw in counters:
                c=dict(raw); u=usage(c['usage']); key=str(c['key'])
                for field in ('first_seen','last_seen'):
                    value=c.get(field)
                    if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0):
                        raise ValueError('invalid counter timestamp')
                row=self.db.execute('select data from checkpoints where source=?',('counter:'+key,)).fetchone()
                old=json.loads(row[0]) if row else None
                if old is not None and packed(c)==packed(old):continue
                if old and any(u[k] is not None and old['usage'][k] is not None and u[k]<old['usage'][k] for k in FIELDS):
                    self.diagnose(key,'counter decreased: reset/correction/replacement quarantined; prior capture retained')
                    continue
                delta={k:None if u[k] is None else u[k]-(old['usage'][k] or 0) if old else u[k] for k in FIELDS}
                changed=old is None or u!=old['usage']
                if changed:
                    calls=c.get('api_calls'); prev_calls=old.get('api_calls') if old else 0
                    precise=c.get('last_seen') if calls is not None and prev_calls is not None and calls-prev_calls==1 else None
                    e={k:c.get(k) for k in META}
                    e.update(id='counter:'+identity(key,u),source_key=key,occurred_at=precise,observed_at=time.time(),usage=delta,source_usage=c.get('source_usage',{}),interval_start=old.get('last_seen') if old else c.get('first_seen'),interval_end=c.get('last_seen'))
                    data=packed(safe_event(e))
                    self.db.execute('insert or ignore into events values(?,?)',(e['id'],data))
                    self.db.execute('insert into event_revisions(id,observed,data) values(?,?,?)',(e['id'],time.time(),data))
                c['usage']=u
                self.db.execute('insert into checkpoints values(?,?,?) on conflict(source) do update set data=excluded.data,observed=excluded.observed',('counter:'+key,packed(c),time.time()))

    def records(self):
        rows=[json.loads(r[0]) for r in self.db.execute('select data from events order by id')]
        hooks={}
        for e in rows:
            if e.get('provenance')=='hermes-hook' and e.get('source_key'):
                values=hooks.setdefault(e['source_key'],{k:0 for k in FIELDS})
                for k in FIELDS: values[k]+=e['usage'][k] or 0
        # Hooks are granular authority. Deduct their overlap from most recently
        # observed cumulative deltas, retaining raw evidence in event_revisions.
        out=[]; summaries={}
        for e in sorted(rows,key=lambda x:x.get('observed_at') or 0,reverse=True):
            if e.get('provenance')=='hermes-summary':
                group=(e['profile'],e['session']); acc=summaries.setdefault(group,dict(e,usage={k:0 for k in FIELDS}))
                for k in FIELDS:
                    acc['usage'][k]=None if acc['usage'][k] is None or e['usage'][k] is None else acc['usage'][k]+e['usage'][k]
                continue
            if e.get('provenance')=='hermes-model' and e.get('source_key') in hooks:
                left=hooks[e['source_key']]
                for k in FIELDS:
                    if e['usage'][k] is not None:
                        overlap=min(left[k],e['usage'][k]);e['usage'][k]-=overlap;left[k]-=overlap
                if all(e['usage'][k] is not None for k in FIELDS[:-1]):e['usage']['total']=sum(e['usage'][k] for k in FIELDS[:-1])
            if e['usage']['total']!=0: out.append(e)
        for group,e in summaries.items():
            main=[x for x in out if x['tool']=='hermes' and (x['profile'],x['session'])==group and not x.get('task')]
            for k in FIELDS:
                if e['usage'][k] is not None: e['usage'][k]=max(0,e['usage'][k]-sum(x['usage'][k] or 0 for x in main))
            e['model']='Unattributed';e['provider']=None;e['occurred_at']=None
            if all(e['usage'][k] is not None for k in FIELDS[:-1]):e['usage']['total']=sum(e['usage'][k] for k in FIELDS[:-1])
            if e['usage']['total']!=0: out.append(e)
        return out
