"""Inotify wakeups, one-second stat fallback, independently paced native quota reads."""
import concurrent.futures
import ctypes
import os
import random
import select
import signal
import time
from pathlib import Path
from collector import Collector
from runtime import WriterLock

class Watcher:
    def __init__(self,paths):
        self.lib=ctypes.CDLL(None,use_errno=True)
        self.fd=self.lib.inotify_init1(os.O_NONBLOCK|os.O_CLOEXEC)
        if self.fd<0:raise OSError('inotify unavailable')
        self.paths=set();self.add(paths)
    def add(self,paths):
        for p in paths:
            p=str(p)
            if p in self.paths or not Path(p).is_dir():continue
            if self.lib.inotify_add_watch(self.fd,os.fsencode(p),0x00000008|0x00000002|0x00000080|0x00000100)>=0:self.paths.add(p)
    def wait(self,timeout):
        ready,_,_=select.select([self.fd],[],[],timeout)
        if ready:
            try:os.read(self.fd,65536)
            except BlockingIOError:pass
    def close(self):os.close(self.fd)

def quota_delay(failures):return min(3600,900*(2**min(failures,2)))+random.uniform(0,60)

def quota_batch(tools,consent=False):
    if consent is not True:return []
    from adapters import quota_read
    from antigravity_source import quota_read as agy_quota_read
    from commandcode_quota import quota_read as cmd_quota_read
    results=[]
    for tool in tools:
        tid=tool['id']
        if not tool.get('installed') or tid not in ('codex','antigravity','commandcode'):continue
        try:
            if tid=='codex':
                if not tool.get('homes'):continue
                home=tool['homes'][0];home=home if isinstance(home,str) else home.get('path',home.get('home',''))
                result=quota_read(home)
            elif tid=='antigravity':result=agy_quota_read()
            else:
                home=tool.get('homes',[None])[0] if tool.get('homes') else None
                if isinstance(home,dict):home=home.get('path',home.get('home'))
                result=cmd_quota_read(home)
            results.append(dict(result,tool=tid))
        except Exception:
            results.append(dict(tool=tid,status='unavailable',quotas=[]))
    return results

def run(root,config,once=False):
    from adapters import discover,collect
    root=Path(root);stop=False
    def end(*args):
        nonlocal stop
        stop=True
    if not once:
        signal.signal(signal.SIGTERM,end);signal.signal(signal.SIGINT,end)
    with WriterLock(root):
        c=Collector(root,config)
        from private_storage import private_dir
        for name in ('spool','activity'):private_dir(root/name)
        c.scan(discover,collect,force=True)
        if once:c.close();return
        watcher=Watcher([root/'spool',root/'activity',Path(config).parent])
        pool=concurrent.futures.ThreadPoolExecutor(max_workers=1,thread_name_prefix='native-quota')
        pending=None;next_quota=max((q.get('observed_at',0)+900 for q in c.quotas()),default=0);failures=0;rescan_sig=None
        try:
            while not stop:
                start=time.monotonic();force=False
                marker=root/'rescan.json'
                signature=marker.stat().st_mtime_ns if marker.exists() else None
                if signature!=rescan_sig:force=True;rescan_sig=signature
                now=time.time()
                if pending and pending.done():
                    try:results=pending.result()
                    except Exception:results=[]
                    for result in results:c.apply_quota(result)
                    failures=0 if results and all(r.get('status')=='ok' for r in results) else failures+1
                    next_quota=now+max(quota_delay(failures),max((float(r.get('retry_after') or 0) for r in results),default=0));pending=None;force=True
                if pending is None and now>=next_quota and c.settings.get('remote_quotas',False):
                    if any(t.get('installed') and t['id'] in ('codex','antigravity','commandcode') for t in c.tools):
                        pending=pool.submit(quota_batch,list(c.tools),True)
                    else:next_quota=now+900
                c.scan(discover,collect,force=force)
                watcher.add([h if isinstance(h,str) else h.get('path','') for t in c.tools for h in t.get('homes',[])])
                # Coalesce bursts; no endless history/remote scans or busy loop.
                elapsed=time.monotonic()-start
                if elapsed<0.15:time.sleep(0.15-elapsed)
                watcher.wait(0.85)
        finally:
            watcher.close();pool.shutdown(wait=True,cancel_futures=True);c.close()
