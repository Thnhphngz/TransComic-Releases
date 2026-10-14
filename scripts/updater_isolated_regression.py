"""Diagnostic full collection by file; preserves the separate single-process crash."""
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/updater-stage-a/isolated'
def main():
    OUT.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen')
    results=[];aggregate=ET.Element('testsuites')
    for test in sorted((ROOT/'tests').glob('test_*.py')):
        xml=OUT/(test.stem+'.xml')
        with (OUT/(test.stem+'.log')).open('w',encoding='utf-8') as log:
            run=subprocess.run([sys.executable,'-m','pytest','-q',str(test),'--tb=short','--junitxml='+str(xml)],
                cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240,shell=False)
        record={'file':test.name,'exit_code':run.returncode}
        if xml.exists():
            root=ET.parse(xml).getroot()
            cases=list(root.iter('testcase'))
            record.update(tests=len(cases),failed=sum(c.find('failure') is not None or c.find('error') is not None for c in cases),
                          skipped=sum(c.find('skipped') is not None for c in cases))
            for suite in root:aggregate.append(suite)
        results.append(record);print(json.dumps(record),flush=True)
    ET.ElementTree(aggregate).write(OUT/'all.xml',encoding='utf-8',xml_declaration=True)
    summary={'mode':'one subprocess per test file, diagnostic only','files':len(results),
             'tests':sum(r.get('tests',0) for r in results),'failed':sum(r.get('failed',0) for r in results),
             'skipped':sum(r.get('skipped',0) for r in results),'incomplete_files':[r['file'] for r in results if 'tests' not in r],
             'results':results}
    summary['passed']=summary['tests']-summary['failed']-summary['skipped']
    (OUT/'report.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True)
    return int(any(r['exit_code']!=0 for r in results))
if __name__=='__main__':raise SystemExit(main())
