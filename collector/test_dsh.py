"""DSH v4 usage-only fixtures; no credentials or live model requests."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from compression import zstd
import adapters
from core import Ledger
from runtime import configure


def event(seq, kind, data, stamp=1791469800000):
    return dict(seq=seq, type=kind, time=stamp, data=data)


def message(seq, usage, turn=1, step=1):
    return event(seq, 'assistant/message', dict(turn=turn, step=step,
        message=dict(source=dict(kind='model', provider='codex', model='gpt-test'), content='SECRET RESPONSE'),
        usage=usage, stream=[dict(type='chunk', chunk=dict(type='usage', usage=usage))]))


class DshTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)
        self.tool=dict(id='dsh', homes=[str(self.home)])
        self.usage=dict(inputTokens=100, outputTokens=20, cacheReadTokens=50, cacheWriteTokens=5, reasoningTokens=10, totalTokens=175)

    def put(self, rows, session='s1', seeded=False, compressed=True):
        p=self.home/'sessions'/'workspace'/session/('session.v4.jsonl.zstd' if compressed else 'session.v4.jsonl')
        p.parent.mkdir(parents=True, exist_ok=True)
        header=dict(type='session', version=4, id=session, createdAt=1791469700000, isSeeded=seeded, delegationDepth=0)
        lines=[(json.dumps(r)+'\n').encode() for r in [header]+rows]
        # Persistence appends independent zstd frames, not one monolithic stream.
        p.write_bytes(b''.join(zstd.compress(line) for line in lines) if compressed else b''.join(lines))
        return p

    def test_discovery_npx_executable_and_custom_home(self):
        binary=self.home/'.npm/_npx/install/node_modules/.bin/dsh'
        binary.parent.mkdir(parents=True);binary.write_text('#!/bin/sh\n');binary.chmod(0o700)
        with patch('adapters.Path.home', return_value=self.home), patch('adapters.shutil.which', return_value=None), patch.dict(os.environ, {'DSH_HOME':str(self.home/'custom')}):
            tool=next(t for t in adapters.discover({}) if t['id']=='dsh')
        self.assertTrue(tool['installed']);self.assertIn(str(self.home/'custom'),tool['homes'])
        self.assertIn(str(self.home/'.dsh'),tool['homes'])

    def test_compressed_native_usage_is_disjoint_readonly_and_idempotent(self):
        p=self.put([event(0,'user/message',dict(content='SECRET PROMPT')),message(1,self.usage)])
        before=p.read_bytes();result=adapters.collect(self.tool)
        self.assertEqual(result['diagnostics'],[])
        self.assertEqual(len(result['events']),1)
        e=result['events'][0]
        self.assertEqual(e['usage'],dict(input=100,output=20,cache_read=50,cache_write=5,total=175))
        self.assertEqual((e['provider'],e['model'],e['occurred_at']),('codex','gpt-test',1791469800))
        self.assertNotIn('SECRET',str(result));self.assertEqual(p.read_bytes(),before)
        ledger=Ledger(self.home/'ledger.sqlite3');self.addCleanup(ledger.close)
        ledger.ingest(events=result['events']);ledger.ingest(events=adapters.collect(self.tool)['events'])
        self.assertEqual(len(ledger.records()),1)

    def test_replacement_retry_attempt_and_request_route(self):
        rows=[event(0,'request/context',dict(provider='deepseek-official',model='deepseek-test')),
            event(1,'assistant/attempt',dict(turn=1,step=1,stream=[dict(type='chunk',chunk=dict(type='usage',usage=self.usage))])),
            message(2,dict(self.usage,inputTokens=110,totalTokens=185)),
            event(3,'llm/retry-started',dict(turn=1,step=1)),message(4,self.usage)]
        self.put(rows)
        result=adapters.collect(self.tool)
        self.assertEqual([e['usage']['total'] for e in result['events']],[185,175])
        self.put(rows[:2])
        e=adapters.collect(self.tool)['events'][0]
        self.assertEqual((e['provider'],e['model']),('deepseek-official','deepseek-test'))

    def test_seeded_history_excluded_and_independent_children_included(self):
        rows=[message(0,self.usage),event(1,'session/end-seed',dict(inherited=True)),message(2,self.usage,turn=2)]
        self.put(rows,seeded=True)
        self.put([message(0,self.usage)],session='child',seeded=False)
        result=adapters.collect(self.tool)
        self.assertEqual(len(result['events']),2)
        self.assertEqual(sum(e['usage']['total'] for e in result['events']),350)
        self.put([message(0,self.usage)],seeded=True)
        self.assertIn('missing_inherited_cut',adapters.collect(self.tool)['diagnostics'])

    def test_plaintext_partial_tail_invalid_and_missing_metrics(self):
        p=self.put([message(0,dict(inputTokens=100,outputTokens=20,cacheReadTokens=0)),
            message(1,dict(inputTokens=True,outputTokens=10),step=2)],compressed=False)
        with p.open('ab') as f:f.write(b'{"type":')
        result=adapters.collect(self.tool)
        self.assertEqual(len(result['events']),1)
        self.assertIsNone(result['events'][0]['usage']['cache_write'])
        self.assertEqual(result['events'][0]['usage']['total'],120)  # Recorded buckets, matching DSH token meter.
        self.assertIn('partial_line',result['diagnostics']);self.assertIn('invalid_usage',result['diagnostics'])

    def test_decompression_budget_and_unchanged_cache(self):
        self.put([message(0,self.usage)])
        import dsh_source
        with patch.object(dsh_source,'_rows',wraps=dsh_source._rows) as reader:
            adapters.collect(self.tool);adapters.collect(self.tool)
            self.assertEqual(reader.call_count,1)
        with patch('adapters.MAX_BYTES',32):
            self.assertIn('byte_limit',adapters.collect(self.tool)['diagnostics'])

    def test_replacement_keeps_ledger_identity_and_moves_route_and_timestamp(self):
        rows=[message(0,self.usage)]
        self.put(rows)
        ledger=Ledger(self.home/'ledger.sqlite3');self.addCleanup(ledger.close)
        ledger.ingest(events=adapters.collect(self.tool)['events'])
        replacement=message(1,dict(self.usage,totalTokens=185,inputTokens=110))
        replacement['data']['message']['source']['model']='new-model'
        replacement['time']+=86400000
        self.put(rows+[replacement]);ledger.ingest(events=adapters.collect(self.tool)['events'])
        self.assertEqual(len(ledger.records()),1)
        e=ledger.records()[0]
        self.assertEqual((e['model'],e['usage']['total'],e['occurred_at']),('new-model',185,1791556200))

    def test_request_header_route_and_last_nested_inherited_boundary(self):
        rows=[message(0,self.usage),event(1,'session/end-seed',dict(inherited=True)),
              message(2,self.usage,turn=2),event(3,'request/header',dict(header=dict(config=dict(provider='resolved',model='actual')))),
              event(4,'session/end-seed',dict(inherited=True)),
              event(5,'assistant/attempt',dict(turn=3,step=1,stream=[dict(type='chunk',chunk=dict(type='usage',usage=self.usage))]))]
        self.put(rows,seeded=True)
        events=adapters.collect(self.tool)['events']
        self.assertEqual(len(events),1)
        self.assertEqual((events[0]['provider'],events[0]['model']),('resolved','actual'))

    def test_corrupt_compression_and_incompatible_generations_fail_closed(self):
        p=self.put([message(0,self.usage)])
        p.with_name('session.v5.jsonl.zstd').write_bytes(p.read_bytes())
        result=adapters.collect(self.tool)
        self.assertEqual(result['events'],[]);self.assertIn('unsupported_session_format',result['diagnostics'])
        self.put([message(0,self.usage)],session='broken').write_bytes(b'invalid zstd')
        self.assertIn('invalid_zstd',adapters.collect(self.tool)['diagnostics'])

    def test_unseeded_inherited_marker_and_mixed_compression_rejected(self):
        p=self.put([message(0,self.usage),event(1,'session/end-seed',dict(inherited=True))])
        result=adapters.collect(self.tool)
        self.assertEqual(result['events'],[]);self.assertIn('invalid_seed_boundary',result['diagnostics'])
        self.put([message(0,self.usage)],compressed=False)
        self.assertIn('mixed_compression',adapters.collect(self.tool)['diagnostics'])

    def test_out_of_range_timestamp_does_not_crash_collector(self):
        row=message(0,self.usage);row['time']=10**400
        self.put([row])
        result=adapters.collect(self.tool)
        self.assertEqual(len(result['events']),1)
        self.assertIsNone(result['events'][0]['occurred_at'])
        self.assertIn('invalid_event_time',result['diagnostics'])

    def test_settings_accept_dsh_default_and_source_path(self):
        data=configure(self.home/'settings.json',dict(default_tool='dsh',paths=dict(dsh=str(self.home))))
        self.assertEqual(data['default_tool'],'dsh')


if __name__=='__main__':unittest.main()
