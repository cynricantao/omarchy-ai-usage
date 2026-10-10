"""Isolated service acceptance: synthetic usage, real OS process, no native clients/model calls."""
import json,os,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from observer import capture
from core import Ledger

class ServiceAcceptance(unittest.TestCase):
    def test_real_service_restart_source_latency_and_permissions(self):
        with tempfile.TemporaryDirectory(prefix='token-activity-acceptance-') as td:
            h=Path(td);root=h/'data/token-activity';config=h/'config';home=h/'hermes';home.mkdir()
            env=dict(os.environ,HOME=str(h),XDG_DATA_HOME=str(h/'data'),XDG_STATE_HOME=str(h/'state'),XDG_CONFIG_HOME=str(config),HERMES_HOME=str(home),CODEX_HOME=str(h/'codex'),CLAUDE_CONFIG_DIR=str(h/'claude'),DSH_HOME=str(h/'dsh'),PATH='/usr/bin:/bin')
            cmd=[sys.executable,str(Path(__file__).with_name('cli.py')),'serve']
            def start():return subprocess.Popen(cmd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            def snapshot():
                p=root/'snapshot.json'
                return json.loads(p.read_text()) if p.exists() else {}
            def wait_total(expected):
                end=time.monotonic()+5
                while time.monotonic()<end:
                    d=snapshot();t=next((x for x in d.get('tools',[]) if x['id']=='hermes'),None)
                    if t and t['totals']['all']==expected:return d
                    time.sleep(.03)
                self.fail('service did not publish expected total')
            proc=start()
            try:
                end=time.monotonic()+5
                while not (root/'snapshot.json').exists() and time.monotonic()<end:time.sleep(.03)
                before=time.monotonic()
                kw=dict(api_request_id='synthetic-request',session_id='fixture-session',model='fixture-model',provider='fixture-route',ended_at=time.time(),usage=dict(input_tokens=100,output_tokens=20,cache_read_tokens=30,cache_write_tokens=0,reasoning_tokens=10,total_tokens=150))
                capture('post_api_request',kw,root,home);wait_total(150)
                latency=time.monotonic()-before;self.assertLess(latency,2)
                capture('post_api_request',kw,root,home)
            finally:
                proc.terminate();out,err=proc.communicate(timeout=20)
            self.assertEqual(proc.returncode,0,err.decode())
            restart_at=time.time();proc=start()
            try:
                end=time.monotonic()+5
                while snapshot().get('updated_at',0)<=restart_at and time.monotonic()<end:time.sleep(.03)
                self.assertGreater(snapshot().get('updated_at',0),restart_at)
                wait_total(150)
            finally:proc.terminate();out,err=proc.communicate(timeout=20)
            self.assertEqual(proc.returncode,0,err.decode())
            db=Ledger(root/'usage.sqlite3');self.assertEqual(len(db.records()),1);db.close()
            self.assertEqual((root/'usage.sqlite3').stat().st_mode&0o777,0o600)
            print('ACCEPTANCE '+json.dumps({'fixture_source_to_snapshot_seconds':round(latency,3),'restart_total':150,'permissions':'0600'}))

if __name__=='__main__':unittest.main()
