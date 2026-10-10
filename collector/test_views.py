import importlib.util
import unittest
from datetime import datetime,timezone

class ViewTests(unittest.TestCase):
    def test_calendar_boundaries_timezone_and_unknown(self):
        self.assertIsNotNone(importlib.util.find_spec('views'),'timezone projections missing')
        from views import project
        def ts(s):return datetime.fromisoformat(s).timestamp()
        def event(s,n,model='a'):
            return dict(tool='hermes',model=model,provider='route',occurred_at=ts(s) if s else None,usage=dict(input=n,output=1,cache_read=None,cache_write=None,total=n+1))
        rows=[event('2026-10-04T19:59:59+00:00',10),event('2026-10-04T20:00:00+00:00',20),event('2026-09-28T20:00:00+00:00',30),event('2026-09-28T19:59:59+00:00',40),event(None,50)]
        x=project(rows,'Asia/Dubai',ts('2026-10-05T10:00:00+00:00'))
        self.assertEqual(x['totals'],dict(today=21,week=63,all=155))
        self.assertEqual(x['coverage']['undated_tokens'],51)
        self.assertEqual(len(x['days']),7)
        self.assertIsNone(x['ranges']['today']['buckets'][0]['cache_read'])
        self.assertEqual(project(rows,'UTC',ts('2026-10-05T10:00:00+00:00'))['totals']['today'],None)
        self.assertEqual(project(rows,'Asia/Dubai',ts('2026-10-05T20:00:00+00:00'))['totals']['today'],None)

if __name__=='__main__':unittest.main()
