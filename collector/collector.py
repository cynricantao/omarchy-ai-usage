"""One authoritative local collector. Failed sources never erase captured history."""
import json
import time
from pathlib import Path
from core import Ledger,identity,packed
from runtime import load_settings, public_settings

class Collector:
    def __init__(self,root,config):
        self.root=Path(root);self.config=Path(config);self.ledger=Ledger(self.root/'usage.sqlite3')
        self.signatures={};self.tools=[];self.source_states={};self.settings=load_settings(config)
        self.ledger.db.executescript('''CREATE TABLE IF NOT EXISTS quota_snapshots(seq INTEGER PRIMARY KEY,observed REAL NOT NULL,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS quota_current(id TEXT PRIMARY KEY,data TEXT NOT NULL);
        INSERT OR IGNORE INTO migrations VALUES(2,unixepoch());''')
    def close(self):self.ledger.close()
    def consume_spool(self):
        changed=False
        for p in (self.root/'spool').glob('*.json'):
            try:
                from private_storage import check_file
                check_file(p)
                stat=p.stat();sig=(stat.st_mtime_ns,stat.st_size)
                if self.signatures.get(str(p))==sig:continue
                if stat.st_size>16384:raise ValueError('oversized usage spool')
                item=json.loads(p.read_text());event=item['event']
                self.ledger.ingest(events=[event],checkpoints={'spool:'+p.name:dict(size=stat.st_size,mtime=stat.st_mtime_ns)})
                self.signatures[str(p)]=sig;changed=True
            except (ValueError,KeyError,OSError,TypeError,AttributeError):
                with self.ledger.db:self.ledger.diagnose('spool:'+p.name,'malformed usage-only spool; retained for diagnosis')
        return changed
    def apply_quota(self,result):
        status=result.get('status','unavailable');now=time.time();tool=result.get('tool','codex')
        with self.ledger.db:
            current=[(key,json.loads(data)) for key,data in self.ledger.db.execute('select id,data from quota_current').fetchall()]
            current=[(key,q) for key,q in current if q.get('tool','codex')==tool]
            if status=='ok':
                unique={(identity(q['account_id'],q['label']) if tool=='codex' else identity(tool,q['account_id'],q.get('quota_id') or q['label'])):q for q in result.get('quotas',[])}
                # Legacy rows have no tool field and belong to Codex. Never
                # clear another provider's current view or retained snapshots.
                for key,q in current:self.ledger.db.execute('delete from quota_current where id=?',(key,))
                for key,q in unique.items():
                    self.ledger.db.execute('insert into quota_current values(?,?) on conflict(id) do update set data=excluded.data',(key,packed(q)))
                self.ledger.db.execute('insert into quota_snapshots(observed,data) values(?,?)',(now,packed(result)))
                self.ledger.diagnose(tool+'-quota','ok')
            else:
                for key,q in current:
                    q['status']=status
                    if status=='unauthorized':
                        # No usable credential: the retained numbers can never be
                        # refreshed by this read, so present the window as
                        # Unavailable instead of as a current percentage.
                        q['used_percent']=None;q['remaining_percent']=None
                    self.ledger.db.execute('update quota_current set data=? where id=?',(packed(q),key))
                self.ledger.diagnose(tool+'-quota',status+('; retained percentages cleared' if status=='unauthorized' else '; last valid reading retained'))
    def quotas(self,tool=None):
        rows=[json.loads(r[0]) for r in self.ledger.db.execute('select data from quota_current')]
        return rows if tool is None else [q for q in rows if q.get('tool','codex')==tool]

    def scan(self,discover,collect,force=False):
        from hermes_source import collect_home
        from observer import atomic_json
        from views import project
        now=time.time();changed=self.consume_spool()
        if force or not self.tools or now-getattr(self,'last_discovery',0)>60:
            self.settings=load_settings(self.config);self.tools=discover(self.settings);self.last_discovery=now;changed=True
        for tool in self.tools:
            tid=tool['id']
            try:
                if tid=='hermes':
                    batches=[]
                    for home in tool.get('homes',[]):
                        h=Path(home if isinstance(home,str) else home.get('path',home.get('home','')))
                        sig=[]
                        for name in ('state.db','state.db-wal'):
                            p=h/name
                            if p.exists():s=p.stat();sig.append((str(p),s.st_ino,s.st_size,s.st_mtime_ns))
                        key='source:'+str(h)
                        if force or self.signatures.get(key)!=sig:
                            batch=collect_home(h);batches.append(batch);self.signatures[key]=sig
                    batch={'events':[],'counters':[c for b in batches for c in b['counters']],'diagnostics':[]}
                else:batch=collect(tool)
                before=self.ledger.db.total_changes
                self.ledger.ingest(events=batch.get('events',[]))
                if batch.get('counters'):self.ledger.reconcile(batch['counters'])
                changed=changed or before!=self.ledger.db.total_changes
                diagnostics=batch.get('diagnostics',[])
                self.source_states[tid]='Unsupported source' if diagnostics and not batch.get('events') and not batch.get('counters') else tool.get('state','Installed')
                if diagnostics:
                    with self.ledger.db:self.ledger.diagnose(tid, '; '.join(str(x)[:240] for x in diagnostics)[:1000])
            except Exception as e:
                self.source_states[tid]='Stale'
                with self.ledger.db:self.ledger.diagnose(tid,'local source unavailable: '+type(e).__name__)
                changed=True
        activity=[]
        for p in (self.root/'activity').glob('*.json'):
            try:
                from private_storage import check_file
                check_file(p)
                if p.stat().st_size>4096:continue
                x=json.loads(p.read_text())
                if not isinstance(x,dict):continue
                stamp=x.get('observed_at');model=x.get('model')
                if type(stamp) not in (int,float) or not isinstance(model,str) or len(model)>1024:continue
                if x.get('active') is True and 0<=now-stamp<900:activity.append({'model':model,'observed_at':stamp,'active':True})
            except (OSError,ValueError):pass
        state_key=packed(activity)
        if state_key!=getattr(self,'activity_key',''):changed=True;self.activity_key=state_key
        if not changed and not force and now-getattr(self,'published',0)<30:return False
        records=self.ledger.records();tools=[]
        for tool in sorted(self.tools,key=lambda t:(t['id']!='hermes',t['id'])):
            tid=tool['id']
            # Command Code is also an API provider: usage routed through it by
            # other local tools (e.g. Hermes) is attributed to this view too.
            # The ledger already reconciled hooks against cumulative counters.
            rows=[r for r in records if r['tool']==tid or (tid=='commandcode' and (r.get('provider') or '').lower()=='commandcode')]
            view=project(rows,self.settings['timezone'],now)
            active=sorted({x['model'] for x in activity}) if tid=='hermes' else []
            last=max(rows,key=lambda e:e.get('occurred_at') or e.get('interval_end') or 0,default={})
            state=self.source_states.get(tid,tool.get('state','Installed'))
            state={'source_present':'Connected','installed':'Installed','absent':'Not detected','stale_evidence':'Stale'}.get(state,state)
            if rows and state not in ('Stale','Unsupported source'):state='Usage available'
            if (tid=='codex' or tid=='claude') and any(q.get('status')=='unauthorized' for q in self.quotas(tid)):state='Needs sign-in'
            note=tool.get('note','')
            if tid=='hermes':note='Request hooks in newly loaded default-profile processes; existing processes, other profiles and Codex runtime use reconciliation. Multi-request historical rows have unknown timing.'
            view['coverage']['note']+=' '+note
            view.update(id=tid,name=tool['name'],installed=tool.get('installed',False),state=state,capabilities=tool.get('capabilities',[]),activity='working' if active else 'unknown' if tid in ('hermes','dsh') else 'idle',active_models=active,last_model=last.get('model'),quotas=self.quotas(tid),last_source_at=max((r.get('occurred_at') or 0 for r in rows),default=None))
            tools.append(view)
        health=[dict(source=r[0],status=r[1],observed_at=r[2]) for r in self.ledger.db.execute('select source,status,observed from health')]
        atomic_json(self.root/'snapshot.json',dict(version=1,updated_at=now,timezone=self.settings['timezone'],settings=public_settings(self.settings),tools=tools,health=health))
        self.published=now;return True
