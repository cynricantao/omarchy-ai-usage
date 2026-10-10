import importlib.util
import tempfile
import unittest
from pathlib import Path

class LedgerTests(unittest.TestCase):
    def test_captured_event_survives_source_deletion_and_restart(self):
        self.assertIsNotNone(importlib.util.find_spec('core'), 'durable ledger implementation missing')
        from core import Ledger
        with tempfile.TemporaryDirectory() as td:
            p=Path(td); source=p/'session.json'; source.write_text('fixture only')
            event=dict(id='request-1',tool='hermes',profile='default',session='s',provider='openai-codex',model='model-a',task='',occurred_at=1791158400,observed_at=1791158401,usage=dict(input=10,output=3,cache_read=20,cache_write=0,total=33),provenance='hook',source_key='route')
            db=Ledger(p/'ledger.db'); db.ingest(events=[event]); db.close(); source.unlink()
            db=Ledger(p/'ledger.db'); db.ingest(events=[event]); self.assertEqual(sum(x['usage']['total'] for x in db.records()),33)
            self.assertEqual(db.db.execute('select count(*) from event_revisions').fetchone()[0],1)
            self.assertEqual(db.db.execute('pragma integrity_check').fetchone()[0],'ok'); db.close()

class ReconciliationTests(unittest.TestCase):
    def test_counters_replay_reset_and_hook_precedence(self):
        from core import Ledger
        self.assertTrue(hasattr(Ledger,'reconcile'), 'counter reconciliation missing')
        with tempfile.TemporaryDirectory() as td:
            db=Ledger(Path(td)/'ledger.db')
            def counter(n,calls=3):
                return dict(key='route',tool='hermes',profile='default',session='s',provider='route-a',model='a',task='',first_seen=100,last_seen=200,api_calls=calls,usage=dict(input=n,output=5,cache_read=0,cache_write=0,total=n+5),provenance='hermes-model')
            db.reconcile([counter(100)]);db.reconcile([counter(100)])
            self.assertEqual(sum(e['usage']['total'] for e in db.records()),105)
            db.reconcile([counter(120,4)])
            self.assertEqual(sum(e['usage']['total'] for e in db.records()),125)
            db.reconcile([counter(4,1)])
            self.assertEqual(sum(e['usage']['total'] for e in db.records()),125)
            self.assertTrue(db.db.execute('select count(*) from health').fetchone()[0])
            hook=dict(id='h1',tool='hermes',profile='default',session='s',provider='route-a',model='a',task='',occurred_at=200,observed_at=201,usage=dict(input=20,output=0,cache_read=0,cache_write=0,total=20),provenance='hermes-hook',source_key='route')
            db.ingest(events=[hook]); db.reconcile([counter(120,4)])
            self.assertEqual(sum(e['usage']['total'] for e in db.records()),125)
            db.close()

    def test_concurrent_sessions_and_transaction_rollback(self):
        from core import Ledger
        with tempfile.TemporaryDirectory() as td:
            db=Ledger(Path(td)/'ledger.db')
            def event(i):
                return dict(id='r'+str(i),tool='hermes',profile='p',session='s'+str(i),provider='p',model='model-'+str(i%2),task='',occurred_at=100,observed_at=100,usage=dict(input=10,output=2,cache_read=3,cache_write=0,total=15),provenance='hook',source_key='k'+str(i))
            db.ingest(events=[event(i) for i in range(10)])
            self.assertEqual(sum(e['usage']['total'] for e in db.records()),150)
            broken=event(12);broken['usage']['total']=-1
            with self.assertRaises(ValueError):db.ingest(events=[event(11),broken],checkpoints={'batch':1})
            self.assertEqual(db.db.execute('select count(*) from events').fetchone()[0],10)
            self.assertEqual(db.db.execute('select count(*) from checkpoints').fetchone()[0],0)
            corrected=event(0);corrected['usage']['input']=8;corrected['usage']['total']=13
            db.ingest(events=[corrected]);self.assertEqual(sum(e['usage']['total'] for e in db.records()),148)
            self.assertEqual(db.db.execute('select count(*) from event_revisions').fetchone()[0],11);db.close()

    def test_hermes_overlap_keeps_disjoint_math_consistent(self):
        from core import Ledger
        with tempfile.TemporaryDirectory() as td:
            db=Ledger(Path(td)/'ledger.db')
            c=dict(key='k',tool='hermes',profile='p',session='s',provider='p',model='m',task='',usage=dict(input=100,output=20,cache_read=0,cache_write=0,total=120),provenance='hermes-model')
            db.reconcile([c])
            e=dict(id='h',source_key='k',tool='hermes',profile='p',session='s',provider='p',model='m',task='',occurred_at=200,observed_at=201,usage=dict(input=200,output=1,cache_read=0,cache_write=0,total=201),source_usage={'reasoning_tokens':1},provenance='hermes-hook')
            db.ingest(events=[e]);rows=db.records()
            self.assertEqual(sum(r['usage']['total'] for r in rows),220)
            self.assertEqual(next(r for r in rows if r['id']=='h')['source_usage']['reasoning_tokens'],1)
            db.close()

if __name__=='__main__': unittest.main()
