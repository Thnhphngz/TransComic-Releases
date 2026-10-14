"""User-invoked Internal release. No scheduler, translation API or installer execution."""
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts import release_source as source
from scripts import release_package as package
from scripts.first_internal_release import (REPO,FIRST_SCOPE,OFFICIAL_SCOPE,automatic_scope,
    FirstReleaseCommands,FirstReleasePublisher,FirstReleaseOperations,source_identity,require_current_tests)
from scripts.official_release import GATE_NAMES
from scripts.release_config import discover,static_configuration
from transcomic.release_journal import ReleaseJournal,ReleaseState
from transcomic.release_pipeline import ReleaseCoordinator
from transcomic.release_provenance import SourceIdentity
from transcomic.release_version import bumped,validate_release_version
from transcomic.release_adapters import safe_path
from transcomic.update.metadata import UpdateError,SemVer

def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,indent=2).encode('utf8')
    part=path.with_name('.w-'+uuid4().hex[:8]+'.part')
    with part.open('xb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    part.replace(path)

@contextmanager
def process_lock(root):
    """Kernel lock survives process crashes without a stale PID override."""
    path=safe_path(root/'.release-state/automatic-process.lock',root);path.parent.mkdir(exist_ok=True)
    stream=path.open('a+b');stream.seek(0)
    if path.stat().st_size==0:stream.write(b'0');stream.flush()
    stream.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        stream.close();raise UpdateError('RELEASE_PROCESS_ALREADY_ACTIVE') from None
    try:yield
    finally:stream.close()  # OS releases ownership, including after crash; no directory deletion.

def version_at(root):
    text=(root/'transcomic/version.py').read_text(encoding='utf8')
    found=re.findall(r'(?m)^VERSION\s*=\s*[\'\"]([^\'\"]+)[\'\"]',text)
    if len(found)!=1:raise UpdateError('SINGLE_VERSION_SOURCE_REQUIRED')
    validate_release_version(found[0]);return found[0]

def set_version(root,old,new):
    if version_at(root)!=old:raise UpdateError('SOURCE_VERSION_CHANGED')
    path=root/'transcomic/version.py';raw=path.read_bytes()
    raw,count=re.subn(rb'(?m)^VERSION\s*=\s*[\'\"][^\'\"]+[\'\"]',b'VERSION = '+repr(new).encode(),raw)
    if count!=1:raise UpdateError('SINGLE_VERSION_SOURCE_REQUIRED')
    path.write_bytes(raw)

class Runtime:
    def __init__(self,root=ROOT):self.root=safe_path(root);self.tools=None;self.snapshot=None

    def gh(self,endpoint):
        # Read-only inventory. Every write remains in the existing scoped publisher.
        if endpoint!='user' and endpoint!='repos/'+REPO and not endpoint.startswith('repos/'+REPO+'/'):raise UpdateError('FIXED_RELEASE_REPO_REQUIRED')
        try:
            raw=subprocess.check_output([self.tools['gh']['path'],'api',endpoint,'--method','GET'],
                cwd=self.root,stderr=subprocess.PIPE,timeout=90)
        except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired):raise UpdateError('GITHUB_READ_FAILED: '+endpoint.split('?')[0]) from None
        if len(raw)>8*1024*1024:raise UpdateError('GITHUB_INVENTORY_TOO_LARGE')
        return json.loads(raw)

    def inventory(self):
        self.tools=discover();config=static_configuration(self.root)
        if self.tools['platform']['system']!='Windows' or self.tools['platform']['bits']!=64:raise UpdateError('WINDOWS_X64_REQUIRED')
        if config['missing'] or not config['qt_windows_plugin'] or any(not self.tools[n].get('path') for n in ('git','gh','ISCC')):
            raise UpdateError('RELEASE_ENVIRONMENT_INCOMPLETE')
        for n in ('PyInstaller','pytest','PySide6','cryptography'):
            if self.tools[n]['status']!='INSTALLED':raise UpdateError('DEPENDENCY_MISSING: '+n)
        user=self.gh('user');repo=self.gh('repos/'+REPO)
        if user.get('login')!=REPO.split('/')[0] or repo.get('full_name')!=REPO or repo.get('private') is not False or repo.get('permissions',{}).get('push') is not True:
            raise UpdateError('GITHUB_ACCOUNT_REPOSITORY_PERMISSION_MISMATCH')
        releases=[];tags=[]
        for endpoint,result in (('releases',releases),('tags',tags)):
            for page in range(1,10001):
                batch=self.gh('repos/'+REPO+'/'+endpoint+'?per_page=100&page='+str(page))
                if not isinstance(batch,list):raise UpdateError('GITHUB_INVENTORY_INVALID')
                result.extend(batch)
                if len(batch)<100:break
            else:raise UpdateError('GITHUB_INVENTORY_LIMIT')
        latest=self.gh('repos/'+REPO+'/releases/latest')
        if latest.get('draft') is not False or latest.get('prerelease') is not False:raise UpdateError('LATEST_NOT_STABLE_INTERNAL')
        for t in tags:validate_release_version(t['name'].removeprefix('v'))
        head=self.gh('repos/'+REPO+'/git/ref/heads/main')['object']
        if head['type']!='commit' or not re.fullmatch('[0-9a-f]{40}',head['sha']):raise UpdateError('DISTRIBUTION_COMMIT_UNVERIFIED')
        self.snapshot={'latest':latest,'releases':releases,'tags':[t['name'] for t in tags],'distribution_commit':head['sha'],'account':user['login']}
        return self.snapshot

    def verify_previous(self,record):
        version=record['version']
        scope=FIRST_SCOPE if version=='0.1.1' else OFFICIAL_SCOPE if version=='1.0.0' and not record.get('automatic_v2') else automatic_scope(version)
        assets=[package.Asset.inspect(n,a['path'],self.root) for n,a in record['asset_inventory'].items()]
        for a in assets:
            if (a.size,a.sha256)!=(record['asset_inventory'][a.name]['size'],record['asset_inventory'][a.name]['sha256']):raise UpdateError('HISTORICAL_LOCAL_ASSET_CHANGED')
        notes=(scope.out/'release-notes.md').read_text(encoding='utf8').rstrip()+'\n\n<!-- transcomic-build-id: '+record['build_id']+' -->\n'
        commands=FirstReleaseCommands(self.tools['gh']['path'],record['source_commit'],record['distribution_commit'],record['build_id'],notes,assets,scope=scope,read_only=True)
        publisher=FirstReleasePublisher(commands);remote=publisher.read(version)
        if remote is None:raise UpdateError('JOURNALED_RELEASE_MISSING')
        publisher.verify(version,remote,assets,published=remote['draft'] is False)
        return {'tag':'v'+version,'build_id':record['build_id'],'assets_verified':True,'published':remote['draft'] is False,'draft':remote['draft'] is True}

    def baseline(self,previous):
        folder=safe_path(self.root/'releases'/previous,self.root)
        metadata=package.load(folder/'build-manifest.json');exe=folder/'TransComic.exe'
        expected=next(a for a in metadata['artifacts'] if a['name']=='TransComic.exe')
        if metadata['version']!=previous or package.sha(exe)!=expected['sha256'] or package.file_version(exe)!=previous+'.0':raise UpdateError('LATEST_BASELINE_NOT_VERIFIED')
        return exe

    def command(self,argv,log,timeout=1800,offline=False):
        print('RUN '+log.name+' — log: '+str(log),flush=True)
        env=dict(os.environ)
        if offline:env['TRANSCOMIC_RELEASE_OFFLINE_TESTS']='1'
        with log.open('wb') as stream:
            try:result=subprocess.run(argv,cwd=self.root,env=env,stdout=stream,stderr=subprocess.STDOUT,shell=False,timeout=timeout)
            except subprocess.TimeoutExpired:raise UpdateError('LOCAL_COMMAND_TIMEOUT: '+log.name) from None
        if result.returncode:raise UpdateError('LOCAL_GATE_FAILED: '+log.name)

    def prepare(self,record,work):
        version=record['version'];folder=self.root/'releases'/version
        if not (work/'build/build-report.json').exists():
            self.command([sys.executable,'-m','pytest','-q','--junitxml='+str(work/'full.xml')],work/'tests.log',offline=True)
        suite=ET.parse(work/'full.xml').getroot().find('testsuite')
        if suite is None or int(suite.get('failures')) or int(suite.get('errors')) or int(suite.get('tests'))<=0:raise UpdateError('FULL_REGRESSION_FAILED')
        if not (work/'build/build-report.json').exists():
            self.command([sys.executable,str(self.root/'scripts/build_local.py'),'--release-build','--output',str(work/'build')],work/'build.log')
        assets=package.assemble(self.root,work,version,record)
        from scripts.test_runtime import TemporaryDirectory
        helper=folder/'TransComic-UpdateHelper.exe'
        with TemporaryDirectory(prefix='TransComic-release-helper-') as temp:
            directory=Path(temp);env=dict(os.environ,LOCALAPPDATA=temp,TEMP=str(directory.parent),TMP=str(directory.parent))
            checks=[]
            for arguments,expected in ((['--self-check'],0),(['--plan',str(directory/'untrusted.json')],2)):
                result=subprocess.run([str(helper),*arguments],cwd=directory,env=env,capture_output=True,timeout=45,creationflags=0x08000000)
                if result.returncode!=expected:raise UpdateError('PACKAGED_HELPER_GATE_FAILED')
                checks.append(result.returncode)
            if (directory/'TransComic').exists():raise UpdateError('HELPER_PROBE_CREATED_USER_PROFILE')
        write(work/'helper-probe.json',{'passed':True,'sha256':package.sha(helper),'exit_codes':checks,'installer_executions':0})
        base=float(subprocess.check_output([sys.executable,str(self.root/'scripts/release_dpi.py')],cwd=self.root,timeout=30).decode().strip())
        if not 0.5<=base<=4:raise UpdateError('WINDOWS_DPR_UNVERIFIED')
        gui={}
        for label,dpr in (('100',1.0),('125',1.25),('150',1.5)):
            output=work/'windows'/(label+'-'+uuid4().hex[:8]);gui[label]=str(output.relative_to(work))
            write(work/'gui-index.json',gui)
            self.command([sys.executable,str(self.root/'scripts/local_exe_smoke.py'),'--exe',str(folder/'TransComic.exe'),'--scale',str(dpr/base),'--output',str(output)],work/('gui-'+label+'-'+uuid4().hex[:8]+'.log'))
        baseline=self.baseline(record['previous_published_version'])
        self.probe(record,work,baseline,False)
        scope=automatic_scope(version);package.save_exact(scope.out/'release-notes.md',(folder/'release-notes.md').read_bytes())
        review=source.inspect(self.root)
        proof={'version':version,'source_commit':record['source_commit'],'source_dirty':False,'source_hashes':review['source_hashes'],
            'test_evidence':{str((work/'full.xml').relative_to(scope.out)):package.sha(work/'full.xml')},
            'baseline_compatibility':True,'privacy_findings':[],'publication_notes_sha256':package.sha(scope.out/'release-notes.md'),
            'distribution_commit':record['distribution_commit'],'release_gates':dict.fromkeys(GATE_NAMES,True),
            'provider_validation':'offline integrations; zero translation API calls','work':str(work.relative_to(self.root))}
        write(work/'gates.json',proof);write(scope.out/'gates.json',proof)
        self.verify_local(record,work)
        return assets

    def probe(self,record,work,baseline,remote):
        argv=[sys.executable,str(self.root/'scripts/release_baseline_probe.py'),'--baseline',str(baseline),'--current',record['previous_published_version'],
            '--version',record['version'],'--assets',str(self.root/'releases'/record['version']),'--output',str(work)]
        if remote:argv+=['--remote']
        self.command(argv,work/('baseline-remote.log' if remote else 'baseline-offline.log'))
        proof=package.load(work/('baseline-remote.json' if remote else 'baseline-offline.json'))
        if not proof['passed'] or proof['baseline_version']!=record['previous_published_version'] or proof['candidate_version']!=record['version'] or proof['native_handoff_executions']!=0:
            raise UpdateError('BASELINE_COMPATIBILITY_FAILED')

    def verify_local(self,record,work):
        review=source.inspect(self.root)
        if review['changes'] or review['head']!=record['source_commit']:raise UpdateError('SOURCE_CHANGED_AFTER_TEST')
        scope=automatic_scope(record['version']);require_current_tests(scope)
        gui=package.load(work/'gui-index.json')
        for label,dpr in (('100',1.0),('125',1.25),('150',1.5)):
            report=package.load(safe_path(work/gui[label],work)/'report.json')
            if not (report['passed'] and report['frozen'] and report['version']==record['version'] and abs(report['dpr']-dpr)<0.01 and report['safe_exit_verified']
                    and report['safe_exit_deadline_ms']==900 and report['exit_code']==0 and report['srt_placeholder'] and report['txt_docx_fixture']
                    and report['real_http_requests']==0 and report['installer_processes']==0 and report['database_under_isolated_root'] and report.get('default_data_path_unchanged') is True):raise UpdateError('FROZEN_GUI_GATE_FAILED')
        baseline=package.load(work/'baseline-offline.json')
        if baseline.get('passed') is not True or baseline['installer_sha256']!=package.sha(self.root/'releases'/record['version']/package.names(record['version'])[0]):raise UpdateError('BASELINE_PROOF_CHANGED')
        helper=package.load(work/'helper-probe.json')
        if helper.get('passed') is not True or helper.get('exit_codes')!=[0,2] or helper['sha256']!=package.sha(self.root/'releases'/record['version']/'TransComic-UpdateHelper.exe'):
            raise UpdateError('HELPER_PROOF_CHANGED')
        return package.verify(self.root,work,record['version'],record)

    def publish(self,record,work,journal):
        scope=automatic_scope(record['version']);assets=self.verify_local(record,work)
        notes=(scope.out/'release-notes.md').read_text(encoding='utf8').rstrip()+'\n\n<!-- transcomic-build-id: '+record['build_id']+' -->\n'
        commands=FirstReleaseCommands(self.tools['gh']['path'],record['source_commit'],record['distribution_commit'],record['build_id'],notes,assets,scope=scope)
        publisher=FirstReleasePublisher(commands)
        self.reconcile_intent(record,scope,publisher)
        operations=FirstReleaseOperations(source_identity(),publisher,assets,record['build_id'],local_checker=lambda:self.verify_local(record,work))
        try:
            # Reuse the same production phases and scoped GitHub adapter, not a second publisher.
            return ReleaseCoordinator(journal)._execute(operations,current=record['previous_published_version'],choice=record['version'],
                build_id=record['build_id'],distribution_commit=record['distribution_commit'])
        finally:write(work/'command-events.json',commands.events)

    def reconcile_intent(self,record,scope,publisher):
        path=scope.out/'remote-intent.json'
        if not path.exists() or package.load(path).get('outcome')!='PENDING':return
        intent=package.load(path)
        if intent['build_id']!=record['build_id']:raise UpdateError('REMOTE_INTENT_IDENTITY_CHANGED')
        endpoint=intent['endpoint'];remote=publisher.read(record['version']);resolved=False
        if endpoint=='repos/'+REPO+'/git/refs':
            resolved=publisher.check_tag(record['version'],record['distribution_commit']) is True
        elif endpoint=='repos/'+REPO+'/releases':resolved=remote is not None
        elif endpoint.startswith('https://uploads.github.com/repos/'+REPO+'/') and remote:
            name=endpoint.rsplit('?name=',1)[-1];expected=publisher.commands.assets.get(name)
            resolved=expected is not None and any(a.get('name')==name and a.get('size')==expected.size and a.get('digest')=='sha256:'+expected.sha256 for a in remote.get('assets',[]))
        elif remote and endpoint=='repos/'+REPO+'/releases/'+str(remote['id']):resolved=remote.get('draft') is False
        if not resolved:raise UpdateError('REMOTE_INTENT_UNRESOLVED_OUTCOME_UNKNOWN: '+endpoint.split('?')[0])
        FirstReleaseCommands.acknowledge_intent(path,dict(intent,outcome='RECONCILED_READ_ONLY'))

    def verify_public(self,record,work):
        import httpx,threading
        from transcomic.update.internal import candidate,verify_checksums
        from transcomic.update.service import UpdateService
        with httpx.Client(timeout=60,trust_env=False,follow_redirects=False,headers={'User-Agent':'TransComic-Automatic-Release-Verification'}) as client:
            found=[]
            for endpoint in ('latest','tags/v'+record['version']):
                response=client.get('https://api.github.com/repos/'+REPO+'/releases/'+endpoint);response.raise_for_status()
                if len(response.content)>1024*1024:raise UpdateError('PUBLIC_RELEASE_TOO_LARGE')
                found.append(response.json())
            latest,tag=found
            if (latest['id']!=tag['id'] or latest.get('tag_name')!='v'+record['version'] or tag['tag_name']!='v'+record['version']
                    or latest.get('draft') is not False or latest.get('prerelease') is not False or tag['draft'] or tag['prerelease']):raise UpdateError('LATEST_NOT_NEW_RELEASE')
            expected={a['name']:a for a in tag['assets']}
            if set(expected)!=set(package.names(record['version'])):raise UpdateError('PUBLIC_ASSET_INVENTORY_MISMATCH')
            service=UpdateService(directory=work/'anonymous',client=client)
            raw={}
            for name,limit in (('transcomic-update.json',128*1024),('SHA256SUMS.txt',4096)):
                raw[name]=b''.join(service._stream(client,expected[name]['browser_download_url'],threading.Event(),limit))
                local=self.root/'releases'/record['version']/name
                if raw[name]!=local.read_bytes() or len(raw[name])!=expected[name]['size']:raise UpdateError('ANONYMOUS_METADATA_MISMATCH')
            item=candidate(tag,json.loads(raw['transcomic-update.json']));verify_checksums(raw['SHA256SUMS.txt'],item,raw['transcomic-update.json'])
            write(work/'anonymous-release.json',tag)
        self.probe(record,work,self.baseline(record['previous_published_version']),True)

class AutomaticSystem:
    def __init__(self,runtime):
        self.runtime=runtime;self.root=runtime.root;self.journal=ReleaseJournal(safe_path(self.root/'.release-state/journal.json',self.root))

    def save(self,record):
        with self.journal.exclusive():self.journal.save(record)
        return record

    def plan(self):
        review=source.inspect(self.root);remote=self.runtime.inventory();record=self.journal.load()
        if not record:raise UpdateError('EXISTING_RELEASE_JOURNAL_REQUIRED')
        current=version_at(self.root);latest=remote['latest']['tag_name'].removeprefix('v')
        pending=bool(record['state']!=ReleaseState.PUBLISHED or (record.get('automatic_v2') and not record.get('post_publication_verified')))
        if pending:
            if not record.get('automatic_v2'):raise UpdateError('LEGACY_PENDING_RELEASE_REQUIRES_RECONCILIATION')
            target_present='v'+record['version'] in remote['tags'] or any(r['tag_name']=='v'+record['version'] for r in remote['releases'])
            if target_present and not record.get('remote_started'):raise UpdateError('UNJOURNALED_TARGET_REMOTE_RECONCILIATION_REQUIRED')
            if latest not in (record['previous_published_version'],record['version']):raise UpdateError('JOURNAL_LATEST_CONFLICT')
            if current not in (record['previous_published_version'],record['version']):raise UpdateError('PENDING_VERSION_CHANGED')
            version=record['version'];changed=True
        else:
            if latest!=record['version'] or current!=latest:raise UpdateError('SOURCE_JOURNAL_LATEST_MISMATCH')
            evidence=self.runtime.verify_previous(record)
            if evidence.get('published') is not True:raise UpdateError('PREVIOUS_RELEASE_NOT_VERIFIED')
            baseline=record.get('released_fingerprint') or source.fingerprint(source.file_map(self.root,record['source_commit']))
            changed=review['fingerprint']!=baseline;version=bumped(latest) if changed else latest
            if changed and ('v'+version in remote['tags'] or any(r['tag_name']=='v'+version for r in remote['releases'])):
                raise UpdateError('NEXT_VERSION_ALREADY_EXISTS_RECONCILE_REQUIRED')
        if any(SemVer.parse(t,tag=True)>SemVer.parse(version) for t in remote['tags']):raise UpdateError('REMOTE_NEWER_TAG_REQUIRES_RECONCILIATION')
        return {'review':review,'remote':remote,'record':record,'current':current,'version':version,'pending':pending,'changed':changed}

    def run(self,mode):
        if mode=='check':
            plan=self.plan();self.describe(plan,mode);return plan
        with process_lock(self.root):
            plan=self.plan();self.describe(plan,mode)
            if not plan['changed']:
                return plan
            record=plan['record'];version=plan['version']
            if not plan['pending']:
                # Preserve every published journal, not an empty/reset state.
                history=safe_path(self.root/'.release-state/history'/('v'+record['version']+'.json'),self.root)
                if history.exists():
                    if package.load(history)!=record:raise UpdateError('JOURNAL_HISTORY_CONFLICT')
                else:write(history,record)
                evidence=self.runtime.verify_previous(record)
                identity=hashlib.sha256((version+plan['review']['fingerprint']).encode()).hexdigest()
                with self.journal.exclusive():
                    record=self.journal.next_release(record,evidence,identity,version)
                    record.update(automatic_v2=True,input_fingerprint=plan['review']['fingerprint'],created_at=now(),
                        distribution_policy='internal',distribution_commit=plan['remote']['distribution_commit'],post_publication_verified=False)
                    self.journal.save(record)
            remote_started=record.get('remote_started',False) or record['last_completed'] in (ReleaseState.DRAFT_CREATED,ReleaseState.ASSETS_UPLOADED,ReleaseState.REMOTE_VERIFIED,ReleaseState.PUBLISHED) or record['state']==ReleaseState.UNKNOWN_REMOTE_OUTCOME
            if plan['review']['fingerprint']!=record['input_fingerprint']:
                if remote_started:raise UpdateError('PENDING_REMOTE_SOURCE_CHANGED_REQUIRES_REVIEW')
                # A user-fixed local test/build failure reuses its reserved version.
                record.setdefault('local_attempt_history',[]).append({k:record.get(k) for k in ('source_commit','work','input_fingerprint','failure_code')})
                identity=hashlib.sha256((version+plan['review']['fingerprint']).encode()).hexdigest()
                record.update(input_fingerprint=plan['review']['fingerprint'],build_id=identity,origin_id=identity,state=ReleaseState.VERSION_SELECTED,
                    last_completed=ReleaseState.VERSION_SELECTED,source_commit=None,work=None,prepared=False)
                folder=safe_path(self.root/'releases'/version,self.root)
                if folder.exists():
                    archived=safe_path(self.root/'artifacts/automatic-release'/version/('old-'+uuid4().hex[:8]),self.root)
                    archived.parent.mkdir(parents=True,exist_ok=True)
                    folder.rename(archived)  # Preserve failed local candidate; never move a published release.
                notes=safe_path(self.root/'artifacts/automatic-release'/version/'release-notes.md',self.root)
                if notes.exists():notes.rename(notes.with_name('superseded-notes-'+uuid4().hex[:8]+'.md'))
                self.save(record)
            try:
                if not record.get('source_commit'):
                    if version_at(self.root)!=version:set_version(self.root,plan['current'],version)
                    record['source_commit']=source.commit(self.root,source.inspect(self.root),'Release TransComic '+version)
                    self.save(record)
                elif source.inspect(self.root)['head']!=record['source_commit'] or source.inspect(self.root)['changes']:
                    raise UpdateError('RESERVED_SOURCE_COMMIT_CHANGED')
                if not record.get('prepared'):
                    if remote_started:raise UpdateError('REMOTE_PENDING_LOCAL_PROOF_MISSING')
                    # New attempt preserves failed logs and partial build directories.
                    old_work=safe_path(self.root/record['work'],self.root) if record.get('work') else None
                    work=old_work if old_work and (old_work/'build/build-report.json').exists() else safe_path(self.root/'artifacts/automatic-release'/version/('attempt-'+uuid4().hex[:8]),self.root)
                    work.mkdir(parents=True,exist_ok=True)
                    record.update(work=str(work.relative_to(self.root)));self.save(record)
                    self.runtime.prepare(record,work);record.update(prepared=True,failure_code=None,state=ReleaseState.VERSION_SELECTED);self.save(record)
                work=safe_path(self.root/record['work'],self.root);self.runtime.verify_local(record,work)
                if mode=='build-only':
                    print('LOCAL BUILD VERIFIED — NO GITHUB WRITES\n'+str(self.root/'releases'/version));return record
                record['remote_started']=True;self.save(record)
                record=self.runtime.publish(record,work,self.journal)
                # PUBLISHED is not final success until independent latest/download verification.
                self.runtime.verify_public(record,work)
                record.update(post_publication_verified=True,released_fingerprint=record['input_fingerprint'],failure_code=None)
                self.save(record);write(work/'acceptance.json',record)
                print('RELEASE PUBLISHED AND VERIFIED\nhttps://github.com/'+REPO+'/releases/tag/v'+version+'\n'+str(self.root/'releases'/version))
                return record
            except Exception as exc:
                # Coordinator may have advanced the same journal before raising.
                latest=self.journal.load()
                if latest and latest['version']==version:record=latest
                record['failure_code']=type(exc).__name__+': '+str(exc)[:240]
                if record['state'] not in (ReleaseState.UNKNOWN_REMOTE_OUTCOME,ReleaseState.PUBLISHED):record['state']=ReleaseState.FAILED
                self.save(record)
                print('RELEASE STOPPED — '+record['failure_code']+'\nRecovery: giữ nguyên journal/packages; chạy --check, xem artifacts/automatic-release/'+version+'. Không xóa tag hoặc journal.')
                raise

    def describe(self,plan,mode):
        print(json.dumps({'mode':'AUTO RELEASE' if mode=='auto' else mode.upper(),'repository':str(self.root),'github_destination':REPO,
            'current_version':plan['current'],'proposed_version':plan['version'],'source_commit':plan['review']['head'],
            'source_changes':plan['review']['changes'],'resume_reserved_version':plan['pending'],
            'journal_state':plan['record']['state'],'last_completed':plan['record']['last_completed'],
            'release_readiness':'CHECKS_ONLY_TESTS_BUILD_PENDING' if mode=='check' else 'GATED_PIPELINE',
            'remote_operations':['create fixed-repo tag/draft','upload canonical installer/manifest/checksums','verify','publish','verify anonymous latest and baseline'] if mode=='auto' and plan['changed'] else [],
            'historical_acceptance':'USER CONFIRMED: install 0.1.0; native 0.1.0 → 0.1.1 → 1.0.0; history preserved. Not automated E2E evidence.',
            'new_version_native_update':'PENDING USER TEST','translation_api_calls':0},ensure_ascii=False,indent=2),flush=True)
        if not plan['changed']:print('NO RELEASEABLE CHANGES')

def main(argv=None):
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf8',errors='replace')
    parser=argparse.ArgumentParser(description='TransComic one-click Internal release. Default: test, build, publish and verify.',allow_abbrev=False)
    modes=parser.add_mutually_exclusive_group();modes.add_argument('--check',action='store_true',help='Read-only checks; no source/version/journal changes')
    modes.add_argument('--build-only',action='store_true',help='Reserve version, commit, test/build/package; no GitHub writes')
    args=parser.parse_args(argv)
    try:AutomaticSystem(Runtime()).run('check' if args.check else 'build-only' if args.build_only else 'auto');return 0
    except (UpdateError,OSError,ValueError,subprocess.SubprocessError) as exc:
        print('RELEASE BLOCKED: '+str(exc));return 2

if __name__=='__main__':raise SystemExit(main())
