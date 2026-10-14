import unittest

class ClaudeQuotaTests(unittest.TestCase):
    def test_usage_windows_become_five_hour_and_weekly_rows(self):
        import claude_quota as q
        data={'five_hour':{'utilization':0.25,'resets_at':'2026-10-12T17:50:00.337817+00:00'},
              'seven_day':{'utilization':0.0,'resets_at':'2026-10-18T20:00:00.337838+00:00'}}
        result=q.parse_quotas(data,100,'profile')
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['tool'],'claude')
        rows=result['quotas']
        self.assertEqual([r['window_minutes'] for r in rows],[300,10080])
        self.assertEqual([r['used_percent'] for r in rows],[25.0,0.0])
        self.assertEqual([r['label'] for r in rows],['5-hour limit','Weekly limit'])
        self.assertEqual(rows[0]['source'],'readonly_oauth_usage')
        self.assertAlmostEqual(rows[0]['resets_at'],1791827400.337817,places=3)
        self.assertAlmostEqual(rows[1]['resets_at'],1792353600.337838,places=3)
        self.assertEqual(rows[1]['remaining_percent'],100)

    def test_usage_windows_fail_closed(self):
        import claude_quota as q
        self.assertEqual(q.parse_quotas(None,100,'profile')['status'],'unavailable')
        self.assertEqual(q.parse_quotas({'five_hour':'x','seven_day':None},100,'profile')['status'],'unavailable')
        row=q.parse_quotas({'five_hour':{'utilization':None,'resets_at':None}},100,'profile')['quotas'][0]
        self.assertIsNone(row['used_percent'])
        self.assertIsNone(row['resets_at'])
        # Above 1 the reading is a percentage, never a fraction to multiply:
        # the old fraction assumption is what turned 19% into a full window.
        row=q.parse_quotas({'five_hour':{'utilization':1.4}},100,'profile')['quotas'][0]
        self.assertEqual(row['used_percent'],1.4)
        row=q.parse_quotas({'five_hour':{'utilization':190.0}},100,'profile')['quotas'][0]
        self.assertEqual(row['used_percent'],100.0)

    def test_percent_payload_reads_the_same_windows_the_cli_overlay_shows(self):
        import claude_quota as q
        # Live shape: utilization is already a percentage and `limits` carries
        # the CLI overlay's own integer percent for the same windows.
        data={'five_hour':{'utilization':19.0,'resets_at':'2026-10-13T01:39:59.619598+00:00','limit_dollars':None},
              'seven_day':{'utilization':3.0,'resets_at':'2026-10-18T19:59:59.619627+00:00'},
              'seven_day_breakdown':{'as_of':'2026-10-12T21:09:17+00:00','rows':[{'key':'claude_code','display_name':'Claude Code','percent':100}]},
              'limits':[{'kind':'session','group':'session','percent':19,'severity':'normal','resets_at':'2026-10-13T01:39:59.901786+00:00','scope':None,'is_active':True},
                        {'kind':'weekly_all','group':'weekly','percent':3,'severity':'normal','resets_at':'2026-10-18T19:59:59.901812+00:00','scope':None,'is_active':False}]}
        result=q.parse_quotas(data,100,'profile')
        self.assertEqual(result['status'],'ok')
        rows=result['quotas']
        self.assertEqual([r['used_percent'] for r in rows],[19.0,3.0])
        self.assertEqual([r['remaining_percent'] for r in rows],[81.0,97.0])
        self.assertEqual([r['quota_id'] for r in rows],['five_hour','seven_day'])
        self.assertEqual([r['label'] for r in rows],['5-hour limit','Weekly limit'])
        self.assertAlmostEqual(rows[0]['resets_at'],1791855599.901786,places=3)
        self.assertAlmostEqual(rows[1]['resets_at'],1792353599.901812,places=3)

    def test_percent_shaped_payload_without_limits_does_not_multiply(self):
        import claude_quota as q
        data={'five_hour':{'utilization':1.0,'resets_at':'2026-10-13T01:39:59+00:00'},
              'seven_day':{'utilization':0.0},
              'seven_day_breakdown':{'rows':[]}}
        rows=q.parse_quotas(data,100,'profile')['quotas']
        self.assertEqual(rows[0]['used_percent'],1.0,'percent payloads keep utilization as-is, even at or below 1')
        self.assertEqual(rows[1]['used_percent'],0.0)
        legacy={'five_hour':{'utilization':1.0}}
        self.assertEqual(q.parse_quotas(legacy,100,'profile')['quotas'][0]['used_percent'],100.0,'fraction-only payloads still scale by 100')

    def test_unusable_limits_rows_fall_back_and_absent_windows_stay_absent(self):
        import claude_quota as q
        data={'limits':[{'kind':'weekly_scoped','percent':40},{'kind':'session','percent':None}],
              'five_hour':{'utilization':12.0}}
        rows=q.parse_quotas(data,100,'profile')['quotas']
        self.assertEqual([r['window_minutes'] for r in rows],[300],'unknown limit kinds never become rows')
        self.assertEqual(rows[0]['used_percent'],12.0,"a limits row without a percent falls back to the same window's utilization")
        absent=q.parse_quotas({},100,'profile')
        self.assertEqual(absent['status'],'unavailable')
        self.assertEqual(absent['quotas'],[],'a window with no reading anywhere stays absent, never 0%')
        envelope=q.parse_quotas({'limits':[{'kind':'session','percent':None}]},100,'profile')['quotas']
        self.assertEqual([r['used_percent'] for r in envelope],[None],'a reported window without a reading keeps a None percent, never 0%')

    def test_authenticated_reader_uses_fixed_origin_and_redacts_errors(self):
        import claude_quota as q
        import json, tempfile, os
        from pathlib import Path
        from unittest.mock import patch, MagicMock
        from urllib.error import HTTPError
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d:
            home=Path(d)/'.claude'; home.mkdir()
            home.joinpath('.credentials.json').write_text(json.dumps({'claudeAiOauth':{'accessToken':'fixture-only-not-a-real-token'}}))
            response=MagicMock();response.__enter__.return_value=response;response.read.return_value=json.dumps({'five_hour':{'utilization':0.5,'resets_at':'2026-10-12T17:50:00+00:00'}}).encode()
            opener=MagicMock();opener.open.return_value=response
            with patch.dict(os.environ,{},clear=True),patch.object(q,'build_opener',return_value=opener):
                result=q.quota_read(home)
            self.assertEqual(result['status'],'ok');self.assertEqual(result['quotas'][0]['used_percent'],50.0)
            request=opener.open.call_args.args[0]
            self.assertEqual(request.get_method(),'GET')
            self.assertEqual(request.full_url,'https://api.anthropic.com/api/oauth/usage')
            self.assertEqual(request.get_header('Authorization'),'Bearer fixture-only-not-a-real-token')
            self.assertNotIn('fixture-only',json.dumps(result))
            opener.open.side_effect=HTTPError('https://api.anthropic.com',401,'do not leak fixture-only',{},None)
            with patch.dict(os.environ,{},clear=True),patch.object(q,'build_opener',return_value=opener):
                result=q.quota_read(home)
            self.assertEqual(result['status'],'unauthorized');self.assertEqual(result['quotas'],[])
            with patch.dict(os.environ,{'CLAUDE_CODE_USE_BEDROCK':'1'},clear=True),patch.object(q,'build_opener') as build:
                self.assertEqual(q.quota_read(home)['status'],'unsupported_environment');build.assert_not_called()
            opener.open.side_effect=None
            with patch.dict(os.environ,{'CLAUDE_CODE_OAUTH_TOKEN':'env-fixture-token'},clear=True),patch.object(q,'build_opener',return_value=opener):
                result=q.quota_read(home)
            self.assertEqual(result['status'],'ok')
            self.assertEqual(opener.open.call_args.args[0].get_header('Authorization'),'Bearer env-fixture-token')

    def test_missing_stored_credential_fails_closed_without_a_request(self):
        import claude_quota as q
        import tempfile, os
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d:
            home=Path(d)/'.claude'; home.mkdir()
            with patch.dict(os.environ,{},clear=True),patch.object(q,'build_opener') as build:
                result=q.quota_read(home)
            self.assertEqual(result['status'],'unauthorized','a signed-out CLI must not keep a stale reading alive')
            self.assertEqual(result['quotas'],[])
            build.assert_not_called()

    def test_ledger_keeps_real_percentages_and_clears_a_signed_out_meter(self):
        import claude_quota as q
        import tempfile, os
        from pathlib import Path
        from collector import Collector
        data={'five_hour':{'utilization':19.0,'resets_at':'2026-10-13T01:39:59+00:00'},
              'seven_day':{'utilization':3.0,'resets_at':'2026-10-18T19:59:59+00:00'},
              'limits':[{'kind':'session','percent':19,'resets_at':'2026-10-13T01:39:59+00:00'},
                        {'kind':'weekly_all','percent':3,'resets_at':'2026-10-18T19:59:59+00:00'}]}
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as td:
            root=Path(td);c=Collector(root,root/'settings.json')
            c.apply_quota(q.parse_quotas(data,100,'profile'))
            rows={r['quota_id']:r for r in c.quotas('claude')}
            self.assertEqual([rows[k]['used_percent'] for k in ('five_hour','seven_day')],[19.0,3.0])
            self.assertEqual([rows[k]['remaining_percent'] for k in ('five_hour','seven_day')],[81.0,97.0])
            # A signed-out CLI must not leave the old meter standing as current.
            c.apply_quota(dict(tool='claude',status='unauthorized',quotas=[]))
            rows={r['quota_id']:r for r in c.quotas('claude')}
            self.assertEqual([rows[k]['used_percent'] for k in ('five_hour','seven_day')],[None,None])
            self.assertEqual({r['status'] for r in rows.values()},{'unauthorized'})
            self.assertAlmostEqual(rows['five_hour']['resets_at'],1791855599.0,places=1,msg='reset stays readable while the meter is unavailable')
            c.close()

if __name__=='__main__':unittest.main()
