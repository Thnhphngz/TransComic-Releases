"""Stage A preflight: no production action implementation or activation switch."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from transcomic.version import VERSION, RELEASE_REPOSITORY, APP_ID
from transcomic.release_version import bumped, validate_release_version, preview_version
from transcomic.release_journal import ReleaseJournal
from transcomic.update.metadata import SemVer, UpdateError, MANIFEST_NAME
from scripts.release_config import discover, static_configuration

PHASES=('preflight','test','build','package','verify','draft release','upload assets','verify remote assets','publish','final report')

def production_action(*args,**kwargs):
    raise RuntimeError('STAGE_A_LOCKED: a reviewed Stage B source change is required')

class ReadOnlyCommands:
    def __init__(self,run=subprocess.run): self.run=run
    def __call__(self,args):
        allowed=[['gh','auth','status'],['gh','repo','view',RELEASE_REPOSITORY,'--json','nameWithOwner,visibility,url'],
                 ['git','-C',str(ROOT),'status','--porcelain'],['git','-C',str(ROOT),'rev-parse','HEAD'],
                 ['gh','release','list','--repo',RELEASE_REPOSITORY,'--json','tagName','--limit','1000'],
                 ['gh','api','--include','repos/'+RELEASE_REPOSITORY+'/releases/latest'],
                 ['git','-C',str(ROOT),'remote','get-url','origin']]
        if args not in allowed: production_action()
        try:
            executable=discover().get(args[0],{}).get('path') or args[0]
            result=self.run([executable,*args[1:]],capture_output=True,text=True,encoding='utf-8',timeout=25,shell=False,cwd=ROOT)
            return result.returncode==0,'' if args==allowed[0] else result.stdout
        except (OSError,UnicodeError,subprocess.TimeoutExpired): return False,''

def scan_sensitive(root=ROOT):
    risk={name:0 for name in ('user_data','old_artifacts','credential_files','source_secret_literals')}
    for p in root.iterdir():
        n=p.name.lower()
        if p.suffix.lower() in ('.docx','.txt','.db','.sqlite3'): risk['user_data']+=1
        if n in ('build','dist','artifacts') or n.startswith('.pytest'): risk['old_artifacts']+=1
        if n.startswith('.env') or any(x in n for x in ('credential','private-key','.pem')): risk['credential_files']+=1
    import re
    for p in [root/'run_transcomic.py',*list((root/'transcomic').rglob('*.py'))]:
        if p.is_symlink(): raise UpdateError('Symlink in packaged source')
        if re.search(r'(?:gh[oopsu]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{25,})',p.read_text(encoding='utf-8')):
            risk['source_secret_literals']+=1
    return risk

def verify_release_plan(current,new,tags,tests_ok,assets,commit):
    validate_release_version(new)
    if SemVer.parse(new)<=SemVer.parse(current): raise UpdateError('Duplicate/downgrade version')
    if 'v'+new in tags: raise UpdateError('Release version already exists')
    if any(SemVer.parse(t,tag=True)>=SemVer.parse(new) for t in tags): raise UpdateError('Version is not newer than remote')
    if not tests_ok: raise UpdateError('Tests failed or not run')
    if set(assets)!={f'TransComic-Setup-{new}-windows-x64.exe',MANIFEST_NAME,'SHA256SUMS.txt'}: raise UpdateError('Missing mandatory assets')
    import re
    if not re.fullmatch('[0-9a-f]{40}',commit or ''): raise UpdateError('Exact build commit required')
    return {'tag':'v'+new,'commit':commit,'repository':RELEASE_REPOSITORY,'production_locked':True}

def preflight(choice='patch',commands=None,which=shutil.which,find_spec=importlib.util.find_spec,journal_path=None):
    commands=commands or ReadOnlyCommands()
    tools={k:bool(which(k)) for k in ('python','git','gh','ISCC')}
    tools['PyInstaller']=find_spec('PyInstaller') is not None
    inventory=discover(which)
    for name in ('git','gh','ISCC'):
        tools[name]=bool(inventory[name]['path'])
    if not tools['ISCC']:
        tools['ISCC']=any((Path(os.environ.get(env,''))/'Inno Setup 6'/'ISCC.exe').is_file() for env in ('ProgramFiles','ProgramFiles(x86)'))
    auth,_=commands(['gh','auth','status']) if tools['gh'] else (False,'')
    repo_ok,repo_raw=commands(['gh','repo','view',RELEASE_REPOSITORY,'--json','nameWithOwner,visibility,url']) if auth else (False,'')
    try:
        repo=json.loads(repo_raw);repo_ok=repo_ok and repo['nameWithOwner']==RELEASE_REPOSITORY and repo['visibility']=='PUBLIC'
    except (ValueError,KeyError,TypeError): repo_ok=False
    git_ok,dirty=commands(['git','-C',str(ROOT),'status','--porcelain']) if tools['git'] else (False,'')
    commit_ok,commit=commands(['git','-C',str(ROOT),'rev-parse','HEAD']) if git_ok else (False,'')
    version=bumped(VERSION,choice);tags=[];remote_known=False
    if repo_ok:
        ok,raw=commands(['gh','release','list','--repo',RELEASE_REPOSITORY,'--json','tagName','--limit','1000'])
        try: tags=[r['tagName'] for r in json.loads(raw)];remote_known=ok and len(tags)<1000
        except (ValueError,KeyError,TypeError): pass
    latest_status='UNVERIFIED'
    if repo_ok:
        ok,raw=commands(['gh','api','--include','repos/'+RELEASE_REPOSITORY+'/releases/latest'])
        # 404 is absence only when an independently successful, complete list is empty.
        if ok and raw.startswith('HTTP/') and ' 200 ' in raw.splitlines()[0]:latest_status='PRESENT_RECONCILIATION_REQUIRED'
        elif remote_known and not tags and raw.startswith('HTTP/') and ' 404 ' in raw.splitlines()[0]:latest_status='NO_PUBLISHED_RELEASE'
    risk=scan_sensitive();gates=[]
    if latest_status!='NO_PUBLISHED_RELEASE':gates.append('RELEASE_STATE_UNCERTAIN')
    reservation=None
    try:
        path=Path(journal_path) if journal_path is not None else ROOT/'.release-state'/'journal.json'
        from transcomic.release_adapters import safe_path
        reservation=ReleaseJournal(safe_path(path)).load()  # read only; no exclusive()/reserve()
        if reservation:
            version=reservation['version']
            preview_version(VERSION,choice,reservation,remote_known=remote_known)
            # CLI tag/list evidence cannot verify signed assets or manual remote edits.
            if 'v'+version in tags:gates.append('RELEASE_STATE_UNCERTAIN')
        elif tags:
            gates.append('RELEASE_STATE_UNCERTAIN')  # latest remote requires independent reconciliation
        elif not remote_known:gates.append('RELEASE_STATE_UNCERTAIN')
    except (UpdateError,OSError,KeyError,TypeError):gates.append('RELEASE_STATE_UNCERTAIN')
    required_files=['run_transcomic.py','pyproject.toml','TransComic.spec','installer/TransComic.iss','transcomic/version.py','docs/release-workflow.md','docs/updater-stage-a.md']
    project_files={name:(ROOT/name).is_file() for name in required_files}
    if not all(project_files.values()):gates.append('PROJECT_FILES_MISSING')
    if not all(tools.values()): gates.append('MISSING_TOOLS')
    if not auth: gates.append('GH_NOT_AUTHENTICATED')
    if not repo_ok: gates.append('RELEASE_REPOSITORY_UNVERIFIED')
    if not git_ok or not commit_ok: gates.append('SOURCE_COMMIT_UNVERIFIED')
    if dirty.strip(): gates.append('SOURCE_HAS_UNCOMMITTED_CHANGES')
    if not remote_known: gates.append('REMOTE_VERSIONS_UNVERIFIED')
    try:
        if any(SemVer.parse(t,tag=True)>=SemVer.parse(version) for t in tags): gates.append('DUPLICATE_OR_OLDER_VERSION')
    except UpdateError: gates.append('REMOTE_TAG_INVALID')
    if risk['source_secret_literals']: gates.append('SOURCE_SECRET_DETECTED')
    configuration=static_configuration(ROOT)
    if configuration['missing'] or not configuration['qt_windows_plugin']:gates.append('STATIC_CONFIGURATION_INCOMPLETE')
    origin_ok,origin=commands(['git','-C',str(ROOT),'remote','get-url','origin']) if commit_ok else (False,'')
    # Do not log raw remote URLs: they can embed credentials. Provenance needs reviewed repository identity.
    if inventory['platform']['system']!='Windows' or inventory['platform']['bits']!=64:gates.append('WINDOWS_X64_REQUIRED')
    gates+=['SOURCE_REPOSITORY_IDENTITY_REQUIRES_REVIEW','WHEEL_HASH_LOCK_REQUIRES_B2_VERIFICATION','TESTS_NOT_RUN_IN_PREFLIGHT','PRODUCTION_SIGNATURE_NOT_CONFIGURED','STAGE_A_LOCKED']
    return {'stage':'B1','dry_run':True,'production_locked':True,'repository':RELEASE_REPOSITORY,
        'current_version':VERSION,'proposed_version':version,'version_modified':False,'python':sys.version.split()[0],
        'version_policy':'TransComic MINOR/PATCH 0..9 carry; generic SemVer unchanged',
        'journal_reserved_version':reservation.get('version') if reservation else None,
        'journal_mutated':False,'remote_tags':tags,
        'latest_release_status':latest_status,
        'virtual_environment':sys.prefix!=sys.base_prefix,'tools':tools,'tool_inventory':inventory,'static_configuration':configuration,'source_origin_present':bool(origin_ok and origin.strip()),'gh_authenticated':auth,'repository_verified':repo_ok,
        'source_git_repository':git_ok,'source_dirty':bool(dirty.strip()),'build_commit':commit.strip() if commit_ok else None,
        'remote_versions_checked':remote_known,'sensitive_file_risks':risk,'packaging_policy':'explicit program/SVG allowlist; no user data, tests, logs, artifacts or credentials',
        'user_data_path':'%LOCALAPPDATA%/TransComic','blocked_by':gates,
        'phases':{p:'LOCKED' if p not in ('preflight','test','final report') else 'SIMULATION_ONLY' for p in PHASES},
        'manifest_template':{'app_id':APP_ID,'version':version,'release_tag':'v'+version,'channel':'stable','os':'windows','architecture':'x64',
          'installer_filename':f'TransComic-Setup-{version}-windows-x64.exe','installer_size':'REQUIRED_FROM_VERIFIED_BUILD','sha256':'REQUIRED_FROM_VERIFIED_BUILD','signature':'REQUIRED_PRODUCTION_SIGNATURE'},
        'required_files':project_files}

def main(argv=None):
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    parser=argparse.ArgumentParser(description='Read-only preflight or explicitly scoped first v0.1.1 release',allow_abbrev=False)
    parser.add_argument('--bump',default='patch',help='patch/minor/major or explicit higher stable version (simulation only)')
    parser.add_argument('--maintenance',choices=('dry-run','cache'),help='After preflight: review cache, or apply verified cache cleanup only')
    parser.add_argument('--policy',choices=('internal','signed-stable'),default='internal')
    parser.add_argument('--output',type=Path,help='Read-only preflight report directory within workspace')
    parser.add_argument('--publish-first-internal-0.1.1',dest='publish_first',action='store_true',
                        help='Only the explicitly authorized first v0.1.1 Internal release; requires clean source and gates')
    parser.add_argument('--publish-official-1.0.0',dest='publish_official',action='store_true',help='Publish only v1.0.0 after all thirteen official gates pass')
    args=parser.parse_args(argv)
    if args.publish_official:
        if args.publish_first or args.bump!='patch' or args.maintenance or args.policy!='internal' or args.output:
            parser.error('Official publication does not accept other actions or version/policy overrides')
        from scripts.official_release import main as official_release
        return official_release()
    if args.publish_first:
        if args.bump!='patch' or args.maintenance or args.policy!='internal' or args.output:
            parser.error('First release does not accept version, maintenance, policy or output overrides')
        from scripts.first_internal_release import main as first_release
        return first_release()
    print('STAGE B1 — PREFLIGHT ONLY\nKhông build hoặc phát hành trong giai đoạn này\nDRY RUN')
    try: report=preflight(args.bump)
    except (UpdateError,OSError): print('Preflight failed safely; no production action executed');return 2
    from scripts.release_environment import environment_report
    report['stage']='B2.1'
    report['environment']=environment_report(ROOT)
    report['distribution_policy']=args.policy
    if args.policy=='signed-stable':
        report['blocked_by']+=['PRODUCTION_SIGNING_NOT_READY','AUTHENTICODE_CERTIFICATE_NOT_READY','PRODUCTION_KEY_RECOVERY_NOT_READY']
    else:
        report['blocked_by']=[g for g in report['blocked_by'] if g!='PRODUCTION_SIGNATURE_NOT_CONFIGURED']
        report['environment']['tools']['SignTool']['blocks_b2_2']=False
        report['environment']['tools']['SignTool']['required_action']='Optional for future Signed Stable; not required for Internal'
        report['manifest_template'].update(distribution_policy='internal',channel='internal',metadata_format=2)
        report['manifest_template'].pop('signature',None)
    report['first_build_requires_separate_approval']=False
    report['local_build_authorized']=True
    report['remote_writes_authorized']=False
    report['native_install_verified']=False
    report['native_update_verified']=False
    report['blocked_by']+=['NATIVE_INSTALL_NOT_VERIFIED','NATIVE_UPDATE_NOT_VERIFIED','REMOTE_WRITE_APPROVAL_REQUIRED']
    for item in ('source','distribution'):
        state=report['environment'][item]['status']
        if state in ('SOURCE_PROVENANCE_NOT_READY','DISTRIBUTION_REPO_NEEDS_INITIAL_COMMIT','DISTRIBUTION_STATE_UNVERIFIED'):report['blocked_by'].append(state)
    from transcomic.release_adapters import safe_path
    folder=safe_path(args.output,ROOT) if args.output else ROOT/'artifacts'/'release-stage-b2-1';folder.mkdir(parents=True,exist_ok=True)
    (folder/'preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))
    if args.maintenance:
        from scripts.cleanup_project import main as maintenance
        return maintenance(['--apply'] if args.maintenance=='cache' else [])
    return 0

if __name__=='__main__': raise SystemExit(main())
