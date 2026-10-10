import unittest,tempfile
from pathlib import Path
from runtime import configure,load_settings
import adapters

class IntegrationContracts(unittest.TestCase):
    def test_path_overrides_merge_and_quotas_have_actual_window(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'config.json';configure(p,{'paths':{'hermes':'/fixture/hermes'}});configure(p,{'paths':{'codex':'/fixture/codex'}})
            self.assertEqual(len(load_settings(p)['paths']),2)
        rows=adapters._quota_rows({'rateLimits':{'primary':{'usedPercent':12,'windowDurationMins':300}}},'a')
        self.assertIn('5h',rows[0]['label'])
    def test_panel_has_requested_compact_identity_and_quota_bars(self):
        p=Path(__file__).resolve().parent.parent/'Panel.qml';s=p.read_text()
        for marker in ('Last used','Multiple models','tooltipText:','id: quotaTrack','id: miniStrip','id: coverageHover'):
            self.assertIn(marker,s)

if __name__=='__main__':unittest.main()
