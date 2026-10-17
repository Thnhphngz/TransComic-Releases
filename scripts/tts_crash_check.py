"""Crash only a newly created isolated GUI fixture process; never a user GUI."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--models',required=True);args=parser.parse_args()
    from scripts.test_runtime import outside
    import psutil
    root=outside(Path(args.root).absolute());root.mkdir(exist_ok=False);(root/'isolated-crash-fixture').write_text('Owned synthetic fixture only')
    command=[sys.executable,str(Path(__file__).resolve().parents[1]/'run_transcomic.py'),'--tts-crash-smoke','--root',str(root),'--models',args.models]
    with (root/'crash.log').open('w',encoding='utf8') as stream:
        process=subprocess.Popen([*command,'--phase','crash'],stdout=stream,stderr=stream,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        end=time.monotonic()+90
        while not (root/'ready.json').exists() and time.monotonic()<end:
            if process.poll() is not None:raise RuntimeError('Crash fixture exited before ready')
            time.sleep(.05)
        assert (root/'ready.json').exists(),'Crash fixture did not become ready'
        info=json.loads((root/'ready.json').read_text());target=psutil.Process(info['pid']);arguments=target.cmdline()
        assert '--tts-crash-smoke' in arguments and str(root) in arguments and 'crash' in arguments
        target.kill();process.wait(10)
    end=time.monotonic()+8
    while any(psutil.pid_exists(p) for p in info['worker_pids']) and time.monotonic()<end:time.sleep(.1)
    assert not any(psutil.pid_exists(p) for p in info['worker_pids']),'Orphan inference process'
    with (root/'resume.log').open('w',encoding='utf8') as stream:subprocess.run([*command,'--phase','resume'],stdout=stream,stderr=stream,check=True,timeout=100,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    report=dict(crash=info,no_orphan=True,resume=json.loads((root/'resume-report.json').read_text()))
    (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report));return 0


if __name__=='__main__':raise SystemExit(main())
