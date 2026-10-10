#!/usr/bin/env python3
"""Optional local static analysis; never activates plugins or stores path reports."""
import collections
import json
import os
from pathlib import Path
import subprocess
import tempfile

base = Path(__file__).resolve().parent.parent
subprocess.run(['node', '--test', *map(str, sorted((base / 'tests').glob('*.test.cjs')))], check=True)
with tempfile.TemporaryDirectory(prefix='ai-usage-qmllint-', dir=os.environ.get('TMPDIR')) as td:
    imports = Path(td)
    (imports / 'qs').symlink_to('/usr/share/omarchy/shell')
    result = subprocess.run(['/usr/lib/qt6/bin/qmllint', '-I', str(imports), '--json', '-',
                             str(base / 'Panel.qml'), str(base / 'ActivityChart.qml'), str(base / 'Tabs.qml')],
                            capture_output=True, text=True)
    report = json.loads(result.stdout)
    errors = [w for f in report['files'] for w in f['warnings'] if w['type'] == 'error']
    for f in report['files']:
        print(Path(f['filename']).name, dict(collections.Counter(w['id'] for w in f['warnings'])))
    if errors:
        raise SystemExit('QML static errors detected; review local qmllint output')
    print('QML syntax: no errors; native dynamic-type warnings are not runtime acceptance')
subprocess.run(['omarchy', 'plugin', 'validate', str(base)], check=True)
print('Omarchy manifest validation: PASS')
