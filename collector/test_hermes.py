import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from core import Ledger

class HermesTests(unittest.TestCase):
    def test_model_switch_aux_and_summary_not_added_twice(self):
        self.assertIsNotNone(importlib.util.find_spec('hermes_source'),'Hermes adapter missing')
        from hermes_source import collect_home
        with tempfile.TemporaryDirectory() as td:
            h=Path(td); c=sqlite3.connect(h/'state.db')
            c.executescript('''CREATE TABLE sessions(id TEXT,input_tokens INT,output_tokens INT,cache_read_tokens INT,cache_write_tokens INT,reasoning_tokens INT,api_call_count INT);
            CREATE TABLE session_model_usage(session_id TEXT,model TEXT,billing_provider TEXT,billing_base_url TEXT,billing_mode TEXT,task TEXT,input_tokens INT,output_tokens INT,cache_read_tokens INT,cache_write_tokens INT,reasoning_tokens INT,api_call_count INT,first_seen REAL,last_seen REAL);
            INSERT INTO sessions VALUES('s',30,6,100,0,2,2);
            INSERT INTO session_model_usage VALUES('s','a','provider-a','https://a/v1','','',10,2,40,0,1,1,100,100);
            INSERT INTO session_model_usage VALUES('s','b','provider-b','https://b/v1','','',20,4,60,0,1,1,200,200);
            INSERT INTO session_model_usage VALUES('s','aux','other','https://aux/v1','','title',5,1,0,0,1,1,250,250);''');c.close()
            db=Ledger(h/'ledger.db');db.reconcile(collect_home(h)['counters'])
            r=db.records();self.assertEqual(sum(x['usage']['total'] for x in r),142)
            self.assertEqual({x['model'] for x in r},{'a','b','aux'})
            (h/'state.db').unlink();db.close();db=Ledger(h/'ledger.db');self.assertEqual(sum(x['usage']['total'] for x in db.records()),142);db.close()

if __name__=='__main__':unittest.main()
