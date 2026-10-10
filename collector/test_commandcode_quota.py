import unittest

class CommandCodeQuotaTests(unittest.TestCase):
    def test_window_limits_are_not_monthly_credits(self):
        import commandcode_quota as q
        result=q.parse_quotas({'credits':{'monthlyCredits':999},'windowLimits':{'fiveHour':{'used':25,'cap':100,'resetAt':1800000000000},'weekly':{'used':0,'cap':200,'resetAt':1800100000000}}},100,'profile')
        self.assertEqual(result['status'],'ok')
        self.assertEqual([r['window_minutes'] for r in result['quotas']],[300,10080])
        self.assertEqual([r['used_percent'] for r in result['quotas']],[25,0])
        self.assertEqual(result['quotas'][0]['resets_at'],1800000000)
        self.assertEqual(q.parse_quotas({'credits':{'monthlyCredits':999}},100,'profile')['status'],'unavailable')
        r=q.parse_quotas({'windowLimits':{'fiveHour':{'used':None,'cap':0}}},100,'profile')['quotas'][0]
        self.assertIsNone(r['used_percent'])
        self.assertIsNone(r['resets_at'])
        r=q.parse_quotas({'windowLimits':{'fiveHour':{'used':0,'cap':100,'resetAt':0}}},100,'profile')['quotas'][0]
        self.assertIsNone(r['resets_at'],'provider zero means no active reset, not the Unix epoch')

    def test_authenticated_reader_only_gets_allowlisted_origin_and_redacts_errors(self):
        import commandcode_quota as q
        import json, tempfile, os
        from pathlib import Path
        from unittest.mock import patch, MagicMock
        from urllib.error import HTTPError
        with tempfile.TemporaryDirectory(dir=os.environ['TMPDIR']) as d:
            home=Path(d); home.joinpath('auth.json').write_text(json.dumps({'apiKey':'fixture-only-not-a-real-key'}))
            responses=[]
            for data in [{'org':{'id':'fixture-org'}},{'windowLimits':{'weekly':{'used':12,'cap':100,'resetAt':1800000000000}}}]:
                response=MagicMock();response.__enter__.return_value=response;response.read.return_value=json.dumps(data).encode();responses.append(response)
            opener=MagicMock();opener.open.side_effect=responses
            with patch.dict(os.environ,{},clear=True),patch.object(q,'build_opener',return_value=opener):
                result=q.quota_read(home)
            self.assertEqual(result['status'],'ok');self.assertEqual(result['quotas'][0]['used_percent'],12)
            self.assertEqual(opener.open.call_count,2)
            for call in opener.open.call_args_list:
                request=call.args[0];self.assertEqual(request.get_method(),'GET');self.assertTrue(request.full_url.startswith('https://api.commandcode.ai/alpha/'))
            self.assertNotIn('fixture-only',json.dumps(result));self.assertNotIn('fixture-org',json.dumps(result))
            opener.open.side_effect=HTTPError('https://api.commandcode.ai',401,'do not leak fixture-only',{},None)
            with patch.dict(os.environ,{},clear=True),patch.object(q,'build_opener',return_value=opener):result=q.quota_read(home)
            self.assertEqual(result['status'],'unauthorized');self.assertEqual(result['quotas'],[])
            with patch.dict(os.environ,{'COMMANDCODE_API_ENV':'staging'},clear=True),patch.object(q,'build_opener') as build:
                self.assertEqual(q.quota_read(home)['status'],'unsupported_environment');build.assert_not_called()

if __name__=='__main__':unittest.main()
