"""Launch only app EXE, with isolated profile and compiled HTTP-guard smoke mode."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
try:
    from scripts.test_runtime import TemporaryDirectory
except ModuleNotFoundError:
    from test_runtime import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from transcomic.release_adapters import safe_path


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--exe',required=True,type=Path)
    parser.add_argument('--scale',default='1');parser.add_argument('--source',action='store_true')
    parser.add_argument('--output',type=Path,help='Evidence directory; preserve previous build smoke by selecting a new directory')
    parser.add_argument('--cpu-cache',type=Path,help='Existing isolated CPU acceptance cache, never a production profile')
    parser.add_argument('--baseline',type=Path,help='Actual v1.2.0 app EXE, read only to seed synthetic legacy data')
    args=parser.parse_args(argv)
    exe=safe_path(args.exe,ROOT)
    if exe.name!='TransComic.exe' and not (args.source and exe.name=='run_transcomic.py'):raise ValueError('Only app EXE/source smoke, never installer/helper')
    out=safe_path(args.output,ROOT) if args.output else ROOT/'artifacts/first-local-build/windows'/args.scale;out.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='TransComic-build-smoke-') as directory:
        root=Path(directory);(root/'isolated-smoke.json').write_text(json.dumps({'mode':'isolated-build-smoke'}),encoding='utf8')
        env=dict(os.environ,LOCALAPPDATA=directory,QT_SCALE_FACTOR=args.scale,QT_QPA_PLATFORM='windows',TEMP=str(root.parent),TMP=str(root.parent))
        env.update(QT_OPENGL='software',QT_QUICK_BACKEND='software',QT_SCALE_FACTOR='1',QT_SCREEN_SCALE_FACTORS=args.scale)
        if args.baseline:
            subprocess.run([sys.executable,str(ROOT/'scripts/release_baseline_data.py'),'--baseline',str(args.baseline.resolve()),'--root',directory],env=env,cwd=root,check=True,timeout=30)
        if args.cpu_cache:env['TRANSCOMIC_SMOKE_CPU_CACHE']=str(args.cpu_cache.resolve())
        argv=[sys.executable,str(exe),'--local-build-smoke'] if args.source else [str(exe),'--local-build-smoke']
        with (out/'process.log').open('wb') as log:
            result=subprocess.run(argv,env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT,shell=False,timeout=180,creationflags=0x08000000)
        for path in root.glob('*.png'):shutil.copyfile(path,out/path.name)
        if (root/'failure.txt').exists():shutil.copyfile(root/'failure.txt',out/'failure.txt')
        if result.returncode!=0 or not (root/'report.json').is_file():raise ValueError('EXE smoke failed; inspect isolated log')
        report=json.loads((root/'report.json').read_text(encoding='utf8'))
        if not report.get('passed') or not report.get('safe_exit_verified') or report.get('real_http_requests')!=0 or report.get('installer_processes')!=0:raise ValueError('Smoke proof incomplete')
        report['process_exit_observed_by_launcher']=True;report['exit_code']=result.returncode
        report['database_under_isolated_root']=Path(report['isolated_database']).is_relative_to(root)
        if not report['database_under_isolated_root']:raise ValueError('Profile isolation failed')
        env['TRANSCOMIC_SMOKE_REOPEN']='1'
        with (out/'reopen-process.log').open('wb') as log:
            reopened=subprocess.run(argv,env=env,cwd=root,stdout=log,stderr=subprocess.STDOUT,shell=False,timeout=40,creationflags=0x08000000)
        if (root/'failure.txt').exists():shutil.copyfile(root/'failure.txt',out/'failure.txt')
        if reopened.returncode or not (root/'reopen-report.json').exists():raise ValueError('EXE reopen smoke failed')
        report['reopen']=json.loads((root/'reopen-report.json').read_text(encoding='utf8'))
        (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report));return 0


if __name__=='__main__':raise SystemExit(main())
