"""Read-only adapter contract tests; all source data are synthetic fixtures."""
import copy
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
try:
    import adapters as a
except ImportError:
    a = None


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'HOME': str(self.root), 'XDG_DATA_HOME': str(self.root/'data'), 'XDG_CONFIG_HOME': str(self.root/'config'), 'CODEX_HOME': str(self.root/'env-codex'), 'CLAUDE_CONFIG_DIR': str(self.root/'env-claude'), 'HERMES_HOME': str(self.root/'.hermes')})
        self.env.start()
        self.addCleanup(self.env.stop)

    def put(self, path, rows):
        p = self.root/path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(''.join(json.dumps(x)+'\n' for x in rows))
        return p

    def tool(self, name):
        return {'id': name, 'homes': [str(self.root/name)]}

    def test_discovery_metadata_only_custom_and_standard(self):
        self.assertIsNotNone(a, 'adapter implementation missing')
        for p in ['.hermes/profiles/work', '.codex/sessions', 'env-codex', 'chosen', '.claude/projects', 'config/Claude', '.gemini/antigravity-cli', 'data/opencode']:
            (self.root/p).mkdir(parents=True)
        (self.root/'data/opencode/opencode.db').touch()
        with patch.object(a.shutil, 'which', side_effect=lambda name: '/bin/'+name if name in ('ag y', 'ag y'.replace(' ', ''), 'codex') else None):
            rows = {r['id']: r for r in a.discover({'paths': {'codex': str(self.root/'chosen')}})}
        self.assertEqual(list(rows), ['hermes','codex','claude','antigravity','opencode','commandcode','dsh'])
        self.assertIn(str(self.root/'chosen'), rows['codex']['homes'])
        self.assertIn(str(self.root/'.codex'), rows['codex']['homes'])
        self.assertIn(str(self.root/'env-codex'), rows['codex']['homes'])
        self.assertIn(str(self.root/'.hermes/profiles/work'), rows['hermes']['homes'])
        self.assertIn('Native CLI generation usage', rows['antigravity']['note'])
        self.assertIn('tokens', rows['antigravity']['capabilities'])
        self.assertFalse(rows['opencode']['installed'])
        self.assertEqual(a.collect(rows['antigravity'])['events'], [])
        self.assertEqual(a.collect({'id':'unknown'})['diagnostics'], ['unsupported_adapter'])

    def test_codex_cumulative_replay_rotation_reset_and_provenance(self):
        def usage(i, o, cache=None):
            return {'input_tokens': i, 'output_tokens': o, 'cached_input_tokens': cache, 'reasoning_output_tokens': 3, 'total_tokens': i+o}
        def count(total, last, stamp='2026-10-05T00:00:00Z'):
            return {'timestamp': stamp, 'type': 'event_msg', 'payload': {'type':'token_count', 'info': {'total_token_usage': total, 'last_token_usage': last}}}
        meta = {'type':'session_meta','payload':{'id':'s1','originator':'codex_cli_rs','source':'cli','model_provider':'openai'}}
        context = {'type':'turn_context','payload':{'model':'gpt-test','turn_id':'t1'}}
        first = count(usage(100,10,40), usage(100,10,40))
        second = count(usage(150,20,60), usage(50,10,20),'2026-10-05T00:01:00Z')
        reset = count(usage(20,5,5), usage(20,5,5),'2026-10-05T00:02:00Z')
        p = self.put('codex/sessions/a.jsonl', [meta,context,first,first,second,reset])
        with p.open('a') as f: f.write('{"type":')
        self.put('codex/archived_sessions/rotated.jsonl',[meta,context,first,first,second,reset])
        excluded = copy.deepcopy(meta); excluded['payload']['id']='hermes-s'; excluded['payload']['originator']='hermes'
        self.put('codex/sessions/hermes.jsonl',[excluded,context,first])
        result = a.collect(self.tool('codex'))
        self.assertEqual(len(result['events']),2)
        self.assertEqual(sum(e['usage']['total'] for e in result['events']),170)
        self.assertEqual(result['events'][0]['usage'],{'input':60,'output':10,'cache_read':40,'cache_write':None,'total':110})
        self.assertEqual({e['session'] for e in result['events']},{'s1'})
        self.assertIn('hermes_origin_excluded',result['diagnostics'])
        self.assertIn('cumulative_reset',result['diagnostics'])
        self.assertIn('partial_line',result['diagnostics'])
        self.assertEqual({e['id'] for e in result['events']},{e['id'] for e in a.collect(self.tool('codex'))['events']})
        ambiguous = copy.deepcopy(meta); ambiguous['payload']={'id':'unknown','source':'appServer'}
        self.put('codex/sessions/unknown.jsonl',[ambiguous,context,count(None,{'input_tokens':10,'output_tokens':None})])
        result=a.collect(self.tool('codex'))
        self.assertIn('ambiguous_origin_overlap',result['diagnostics'])
        event=next(e for e in result['events'] if e['session']=='unknown')
        self.assertIsNone(event['usage']['total'])
        self.assertIsNone(event['usage']['input'])
        self.assertIsNone(event['usage']['cache_read'])

    def test_claude_stream_revisions_native_semantics_and_no_content(self):
        row={'type':'assistant','sessionId':'session-a','timestamp':'2026-10-05T02:00:00Z','message':{'id':'msg-a','role':'assistant','model':'claude-test','content':[{'text':'SECRET RAW CONTENT'}], 'usage':{'input_tokens':10,'output_tokens':1,'cache_read_input_tokens':30,'cache_creation_input_tokens':5}}}
        final=copy.deepcopy(row); final['message']['usage']['output_tokens']=9; final['message']['stop_reason']='end_turn'
        self.put('claude/projects/proj/session.jsonl',[row,final,row,final])
        result=a.collect(self.tool('claude'))
        self.assertEqual(len(result['events']),1)
        self.assertEqual(result['events'][0]['usage'],{'input':10,'output':9,'cache_read':30,'cache_write':5,'total':54})
        self.assertIsNone(result['events'][0]['provider'])
        self.assertNotIn('SECRET',json.dumps(result))
        self.assertEqual(result['events'][0]['id'],a.collect(self.tool('claude'))['events'][0]['id'])
        final['message']['id']='msg-b'; final['message']['usage']['cache_creation_input_tokens']=None
        self.put('claude/projects/proj/null.jsonl',[final])
        event=next(e for e in a.collect(self.tool('claude'))['events'] if e['id']!=result['events'][0]['id'])
        self.assertIsNone(event['usage']['total'])
        self.assertIsNone(event['usage']['cache_write'])

    def test_opencode_readonly_projected_schema(self):
        path=self.root/'opencode/opencode.db'; path.parent.mkdir()
        db=sqlite3.connect(path)
        db.execute('CREATE TABLE message(id TEXT PRIMARY KEY, session_id TEXT, data TEXT)')
        data={'role':'assistant','modelID':'test-model','providerID':'test-provider','time':{'created':1791158400000},'tokens':{'input':10,'output':20,'reasoning':9,'cache':{'read':30,'write':5}},'content':'SECRET RAW CONTENT'}
        db.execute('INSERT INTO message VALUES (?,?,?)',('msg-1','sess-1',json.dumps(data)))
        db.commit(); db.close()
        before=path.read_bytes()
        result=a.collect(self.tool('opencode'))
        self.assertEqual(len(result['events']),1)
        event=result['events'][0]
        self.assertEqual(event['usage'],{'input':10,'output':20,'cache_read':30,'cache_write':5,'total':65})
        self.assertEqual(event['provider'],'test-provider')
        self.assertEqual(event['occurred_at'],1791158400)
        self.assertNotIn('SECRET',json.dumps(result))
        self.assertEqual(path.read_bytes(),before)
        db=sqlite3.connect(path); db.execute('DROP TABLE message'); db.execute('CREATE TABLE message(other TEXT)'); db.commit(); db.close()
        self.assertIn('unsupported_opencode_schema',a.collect(self.tool('opencode'))['diagnostics'])

    def fake_codex(self, error=None, stall=False):
        script=self.root/'fake-codex'
        script.write_text('#!/usr/bin/env python3\nimport json,sys,time\n'+
            'for line in sys.stdin:\n'+
            ' q=json.loads(line)\n'+
            ' with open('+repr(str(self.root/'requests'))+',"a") as f: f.write(json.dumps(q)+"\\n")\n'+
            ' if "id" not in q: continue\n'+
            (' time.sleep(2)\n' if stall else '')+
            ' method=q["method"]\n'+
            ' data={"initialize":{},"account/read":{"account":{"type":"chatgpt","email":"PRIVATE_EMAIL","accountId":"PRIVATE_ID"}},"account/rateLimits/read":{"rateLimits":{"primary":{"usedPercent":99}},"rateLimitsByLimitId":{"codex":{"primary":{"usedPercent":25,"resetsAt":1791158400,"windowDurationMins":300},"secondary":None}}},"account/usage/read":{"summary":{"lifetimeTokens":1234,"email":"SECRET"},"dailyUsageBuckets":[{"startDate":"2026-10-05","tokens":12}],"threadUsage":{"secret":"SECRET"}}}[method]\n'+
            ' response={"id":q["id"],"result":data}\n'+
            (' if method=="account/rateLimits/read": response={"id":q["id"],"error":{"code":'+str(error)+',"message":"PRIVATE ERROR"}}\n' if error else '')+
            ' print(json.dumps(response),flush=True)\n')
        script.chmod(0o700)
        return script

    def test_quota_native_stdio_readonly_schema_and_redaction(self):
        self.assertTrue(hasattr(a,'quota_read'),'quota adapter missing')
        binary=self.fake_codex()
        with patch.object(a.shutil,'which',return_value=str(binary)):
            result=a.quota_read(str(self.root/'codex'))
        self.assertEqual(result['status'],'ok')
        self.assertEqual(len(result['quotas']),1)
        quota=result['quotas'][0]
        self.assertEqual(quota['used_percent'],25)
        self.assertEqual(quota['remaining_percent'],75)
        self.assertTrue(quota['account_id'].startswith('account:'))
        self.assertEqual(result['account_usage']['summary']['lifetimeTokens'],1234)
        self.assertNotIn('PRIVATE',json.dumps(result)); self.assertNotIn('SECRET',json.dumps(result))
        requests=[json.loads(x) for x in (self.root/'requests').read_text().splitlines()]
        self.assertEqual([x['method'] for x in requests],['initialize','initialized','account/read','account/rateLimits/read','account/usage/read'])
        self.assertEqual(requests[2]['params'],{'refreshToken':False})
        self.assertEqual(requests[3]['params'],{'excludeResetCreditDetails':True,'supportsLunaReserve':False})
        self.assertEqual(requests[4]['params'],{})
        for code, expected in [(401,'unauthorized'),(429,'rate_limited'),(-32603,'offline')]:
            with self.subTest(code=code):
                binary=self.fake_codex(error=code)
                with patch.object(a.shutil,'which',return_value=str(binary)):
                    self.assertEqual(a.quota_read(str(self.root/'codex'))['status'],expected)
        binary=self.fake_codex(stall=True)
        with patch.object(a.shutil,'which',return_value=str(binary)), patch.object(a,'QUOTA_TIMEOUT',0.05):
            self.assertEqual(a.quota_read(str(self.root/'codex'))['status'],'timeout')
        with patch.object(a.shutil,'which',return_value=None):
            self.assertEqual(a.quota_read(str(self.root/'codex'))['status'],'offline')

    def test_cumulative_only_stays_undated_and_claude_route_unknown(self):
        meta={'type':'session_meta','payload':{'id':'cumulative','originator':'codex_cli_rs','source':'cli'}}
        def count(i):
            return {'type':'event_msg','timestamp':'2026-10-05T00:00:00Z','payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':i,'output_tokens':10,'cached_input_tokens':0,'total_tokens':i+10}}}}
        self.put('codex/sessions/a.jsonl',[meta,count(100),count(200)])
        result=a.collect(self.tool('codex'))
        self.assertEqual(result['events'],[])
        self.assertEqual(len(result['counters']),1)
        self.assertEqual(result['counters'][0]['usage']['total'],210)
        self.assertIsNone(result['counters'][0]['occurred_at'])
        row={'type':'assistant','sessionId':'s','message':{'id':'m','role':'assistant','model':'claude-on-unknown-route','usage':{'input_tokens':1,'output_tokens':1,'cache_read_input_tokens':0,'cache_creation_input_tokens':0}}}
        self.put('claude/projects/p/a.jsonl',[row])
        self.assertIsNone(a.collect(self.tool('claude'))['events'][0]['provider'])

    def test_stale_desktop_only_and_scan_caps(self):
        path=self.root/'data/applications/claude-desktop.desktop'; path.parent.mkdir(parents=True); path.touch()
        with patch.object(a.shutil,'which',return_value=None):
            tool=next(x for x in a.discover({}) if x['id']=='claude')
        self.assertFalse(tool['installed'])
        self.assertEqual(tool['state'],'stale_evidence')
        self.put('claude/projects/p/a.jsonl',[{'type':'noise'}])
        with patch.object(a,'MAX_BYTES',0):
            result=a.collect(self.tool('claude'))
        self.assertIn('byte_limit',result['diagnostics'])
        self.assertEqual(result['events'],[])

    def test_quota_fallback_nulls_and_process_group_cleanup(self):
        binary=self.fake_codex()
        script=binary.read_text().replace(',"accountId":"PRIVATE_ID"','').replace('"usedPercent":25','"usedPercent":null').replace('"resetsAt":1791158400','"resetsAt":null')
        # Script source uses Python dictionaries, not JSON literals.
        binary.write_text(script.replace(':null',':None'))
        with patch.object(a.shutil,'which',return_value=str(binary)), patch.object(a.os,'killpg',wraps=os.killpg) as kill:
            result=a.quota_read(str(self.root/'codex'))
        self.assertEqual(result['status'],'ok')
        self.assertIsNone(result['quotas'][0]['used_percent'])
        self.assertIsNone(result['quotas'][0]['remaining_percent'])
        self.assertIsNone(result['quotas'][0]['resets_at'])
        self.assertTrue(result['quotas'][0]['account_id'].startswith('local-profile-unverified:'))
        self.assertEqual(result['identity_scope'],'local_profile_unverified_cross_tool')
        self.assertTrue(kill.called,'entire native process group must be reaped')

    def test_truncated_cumulative_prefix_not_double_counted(self):
        meta={'type':'session_meta','payload':{'id':'s','source':'cli'}}
        last={'input_tokens':10,'output_tokens':2,'cached_input_tokens':0,'total_tokens':12}
        total={'input_tokens':100,'output_tokens':20,'cached_input_tokens':0,'total_tokens':120}
        row={'type':'event_msg','timestamp':'2026-10-05T00:00:00Z','payload':{'type':'token_count','info':{'total_token_usage':total,'last_token_usage':last}}}
        self.put('codex/sessions/truncated.jsonl',[meta,row])
        result=a.collect(self.tool('codex'))
        self.assertEqual(result['counters'],[])
        self.assertEqual(result['events'][0]['usage']['total'],12)
        self.assertIn('unobserved_cumulative_prefix',result['diagnostics'])


    def test_codex_replacement_is_not_new_consumption(self):
        from core import Ledger
        meta={'type':'session_meta','payload':{'id':'replaced','source':'cli'}}
        def row(n,stamp):return {'type':'event_msg','timestamp':stamp,'payload':{'type':'token_count','info':{'total_token_usage':{'input_tokens':n,'output_tokens':2,'cached_input_tokens':0,'total_tokens':n+2},'last_token_usage':{'input_tokens':n,'output_tokens':2,'cached_input_tokens':0,'total_tokens':n+2}}}}
        p=self.put('codex/sessions/a.jsonl',[meta,row(100,'2026-10-05T00:00:00Z')])
        db=Ledger(self.root/'ledger.db');self.addCleanup(db.close)
        db.ingest(events=a.collect(self.tool('codex'))['events'])
        self.put('codex/sessions/a.jsonl',[meta,row(20,'2026-10-05T00:01:00Z')])
        db.ingest(events=a.collect(self.tool('codex'))['events'])
        self.assertEqual(sum(e['usage']['total'] for e in db.records()),102)

    def test_unchanged_source_is_not_reparsed(self):
        self.put('claude/projects/p/a.jsonl',[{'type':'noise'}])
        with patch.object(a,'_lines',wraps=a._lines) as reader:
            a.collect(self.tool('claude'));a.collect(self.tool('claude'))
            self.assertEqual(reader.call_count,1)

if __name__ == '__main__':
    unittest.main()
