"""Record V3's backend hashes and UI changes without relying on installed Git."""
import hashlib
import json
import copy
import xml.etree.ElementTree as ET
from pathlib import Path

root=Path('artifacts/liquid-glass-v3')
before=json.loads((root/'backend-before.json').read_text(encoding='utf-8'))
after={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in before}
changed=[name for name in before if before[name]!=after[name]]
ui_changes=[]
for source in Path('transcomic/ui').glob('*.py'):
    baseline=root/'baseline-ui'/source.name
    if baseline.exists() and source.read_bytes()!=baseline.read_bytes():ui_changes.append(str(source))
report={'backend_files_compared':len(before),'backend_changes':changed,'ui_changes':sorted(ui_changes)}
(root/'scope-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
assert not changed,'V3 must leave every backend file unchanged'

regression=root/'regression.xml'
if regression.exists():
    suites=ET.parse(regression).getroot()
    cases=list(suites.iter('testcase'))
    failed=[c for c in cases if c.find('failure') is not None or c.find('error') is not None]
    skipped=[c for c in cases if c.find('skipped') is not None]
    gui=[c for c in cases if c.get('classname','').endswith('test_liquid_glass_v3')]
    subset=ET.Element('testsuite',name='Liquid Glass V3',tests=str(len(gui)),
                      failures=str(sum(c.find('failure') is not None for c in gui)),
                      errors=str(sum(c.find('error') is not None for c in gui)),
                      skipped=str(sum(c.find('skipped') is not None for c in gui)))
    for case in gui:subset.append(copy.deepcopy(case))
    ET.ElementTree(subset).write(root/'gui-tests.xml',encoding='utf-8',xml_declaration=True)
    native=[]
    for scale in ('0.8','1','1.2'):
        path=root/'after'/scale/'report.json'
        if path.exists():native.append(json.loads(path.read_text(encoding='utf-8')))
    acceptance={'tests':len(cases),'passed':len(cases)-len(failed)-len(skipped),
                'failed':len(failed),'skipped':len(skipped),'new_gui_tests':len(gui),
                'backend_files_unchanged':len(before),'native_windows':native}
    (root/'acceptance.json').write_text(json.dumps(acceptance,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in acceptance.items() if k!='native_windows'}))
