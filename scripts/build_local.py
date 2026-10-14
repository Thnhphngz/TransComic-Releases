"""Authorized BUILD_LOCAL only; dirty devtest staging, no install or GitHub actions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.release_config import discover,static_configuration
from scripts.release_environment import pe_architecture,file_version
from transcomic.release_adapters import safe_path
from transcomic.version import VERSION


def input_files(root):
    files=[root/name for name in ('run_transcomic.py','pyproject.toml','requirements-release.lock','TransComic.spec','installer/TransComic.iss','installer/TransComic.ico','scripts/release_config.py','scripts/update_helper.py')]
    files += list((root/'transcomic').rglob('*.py'))+list((root/'transcomic/ui/assets').glob('*.svg'))
    return sorted(safe_path(p,root) for p in files)


def prepare(root,output,version=None):
    from transcomic.release_version import validate_release_version
    version=version or VERSION;validate_release_version(version)
    from transcomic.update.metadata import SemVer
    if SemVer.parse(version)<SemVer.parse(VERSION):raise ValueError('Local overlay cannot downgrade source version')
    root=safe_path(root);output=safe_path(output,root)
    if output.exists():raise ValueError('Build output exists; no overwrite')
    config=static_configuration(root)
    if config['missing'] or not config['qt_windows_plugin']:raise ValueError('Build dependencies/resources not verified')
    files=input_files(root)
    for p in files:
        if p.suffix=='.py' and re.search(rb'gh[oopsu]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{25,}|sk-[A-Za-z0-9_-]{24,}',p.read_bytes()):raise ValueError('Credential in build input')
    hashes={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    output.mkdir(parents=True);stage=output/'source';stage.mkdir()
    for p in files:
        dst=stage/p.relative_to(root);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dst)
        if hashlib.sha256(dst.read_bytes()).hexdigest()!=hashes[p.relative_to(root).as_posix()]:raise ValueError('Build staging changed')
    from transcomic.release import version_outputs
    overlay={}
    if version!=VERSION:
        file=stage/'transcomic/version.py';text,count=re.subn(r"(?m)^VERSION\s*=\s*['\"][^'\"]+['\"]",'VERSION = '+repr(version),file.read_text(encoding='utf8'))
        if count!=1:raise ValueError('Single version source required')
        file.write_text(text,encoding='utf8');overlay={'transcomic/version.py':hashlib.sha256(file.read_bytes()).hexdigest()}
    (stage/'installer/generated-version.iss').write_text(version_outputs(version)['iss'],encoding='utf8')
    (stage/'.build-local.json').write_text(json.dumps({'permission':'BUILD_LOCAL','version':version,'source_hashes':hashes}),encoding='utf8')
    report={'permission':'BUILD_LOCAL','version':version,'source_version':VERSION,'version_overlay':overlay,'status':'LOCAL RELEASE CANDIDATE — NOT PUBLISHED' if overlay else 'LOCAL DEVTEST — NOT PUBLISHED','source_tree_state':'dirty_devtest_snapshot','hashes':hashes,
            'head':subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD']).decode().strip(),
            'branch':subprocess.check_output(['git','-C',str(root),'branch','--show-current']).decode().strip(),
            'git_status':subprocess.check_output(['git','-C',str(root),'status','--porcelain']).decode('utf8'),
            'install_allowed':False,'remote_release_allowed':False,'source_version_modified':False}
    (output/'build-inputs.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return stage,report


def run_tool(argv,cwd,log,timeout):
    # There is no generic execution, publisher, installer or update activation in this script.
    with log.open('w',encoding='utf8') as stream:
        result=subprocess.run(argv,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,shell=False,timeout=timeout)
    if result.returncode:raise ValueError('Build tool failed; inspect '+log.name)


def main(argv=None):
    parser=argparse.ArgumentParser(description='BUILD_LOCAL devtest only; never install/release')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--candidate-version',help='Staging-only devtest version overlay; never changes source/journal')
    args=parser.parse_args(argv)
    output=args.output or ROOT/'artifacts/first-local-build'/('build-'+uuid4().hex)
    try:
        inventory=discover();compiler=inventory['ISCC']['path']
        if not compiler or inventory['platform']['system']!='Windows' or inventory['platform']['bits']!=64:raise ValueError('Windows x64 / Inno compiler missing')
        stage,report=prepare(ROOT,output,args.candidate_version);output=safe_path(output,ROOT);version=report['version']
        report['tools']=inventory
        run_tool([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(stage/'dist'),'--workpath',str(output/'work'),str(stage/'TransComic.spec')],stage,output/'pyinstaller.log',1800)
        for name in ('TransComic.exe','TransComic-UpdateHelper.exe'):
            p=stage/'dist'/name
            if not p.is_file() or pe_architecture(p)!='x64' or file_version(p)!=version+'.0':raise ValueError('EXE architecture/version mismatch')
        filename=f'TransComic-Setup-{version}-devtest-windows-x64.exe'
        run_tool([str(safe_path(compiler)),'/DBUILD_LOCAL','/O'+str(output/'installer'),'/F'+Path(filename).stem,str(stage/'installer/TransComic.iss')],stage,output/'iscc.log',900)
        installer=output/'installer'/filename
        if not installer.is_file() or pe_architecture(installer) not in ('x86','x64') or file_version(installer)!=version+'.0':raise ValueError('Installer metadata mismatch')
        # Inno bootstrapper may be x86; ISS payload/target is Windows x64.
        products=[stage/'dist/TransComic.exe',stage/'dist/TransComic-UpdateHelper.exe',installer]
        report['artifacts']=[{'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'pe_arch':pe_architecture(p),'version':file_version(p)} for p in products]
        report['installer_executed']=False
        (output/'build-report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps({'build_output':str(output),'artifacts':report['artifacts']},indent=2));return 0
    except Exception as exc:
        print('BUILD_LOCAL FAILED: '+str(exc));return 2


if __name__=='__main__':raise SystemExit(main())
