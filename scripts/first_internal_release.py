"""Explicitly scoped Internal publications using existing release machinery.

Not imported by the app or included by the build allowlist. Default is read-only.
The generic release adapters stay locked; this concrete adapter has no arbitrary
command injection, repository/version option, delete, clobber, or source push.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from transcomic.release_adapters import Asset, CommandResult, GitHubPublisher, safe_path
from transcomic.release_pipeline import ReleaseCoordinator, ProductionReleaseOperations
from transcomic.release_journal import ReleaseJournal, ReleaseState
from transcomic.release_provenance import SourceIdentity
from transcomic.update.internal import candidate, verify_checksums
from transcomic.update.metadata import UpdateError, canonical, release_url, asset_url
from scripts.release_environment import file_version, pe_architecture

VERSION = '0.1.1'
TAG = 'v0.1.1'
REPO = 'Thnhphngz/TransComic-Releases'
OUT = ROOT / 'artifacts/first-real-github-release-0.1.1'
PREPARED = ROOT / 'artifacts/two-laptop-update-test'
NAMES = ('TransComic-Setup-0.1.1-windows-x64.exe', 'transcomic-update.json', 'SHA256SUMS.txt')

@dataclass(frozen=True)
class ReleaseScope:
    version: str
    tag: str
    out: Path
    names: tuple

FIRST_SCOPE=ReleaseScope(VERSION,TAG,OUT,NAMES)
OFFICIAL_SCOPE=ReleaseScope('1.0.0','v1.0.0',ROOT/'artifacts/official-release-1.0.0',
    ('TransComic-Setup-1.0.0-windows-x64.exe','transcomic-update.json','SHA256SUMS.txt'))
_AUTOMATIC_SCOPES={}

def automatic_scope(version):
    """Per-version command boundary for the user-invoked automatic entry."""
    from transcomic.release_version import validate_release_version
    validate_release_version(version)
    if version not in _AUTOMATIC_SCOPES:
        _AUTOMATIC_SCOPES[version]=ReleaseScope(version,'v'+version,ROOT/'artifacts/automatic-release'/version,
            ('TransComic-Setup-'+version+'-windows-x64.exe','transcomic-update.json','SHA256SUMS.txt'))
    return _AUTOMATIC_SCOPES[version]

def checked_scope(scope):
    if scope is not FIRST_SCOPE and scope is not OFFICIAL_SCOPE and not any(scope is s for s in _AUTOMATIC_SCOPES.values()):
        raise UpdateError('UNAUTHORIZED_RELEASE_SCOPE')
    return scope


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode('utf8').strip()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def identity_in_notes(notes):
    found = re.findall(r'<!-- transcomic-build-id: ([0-9a-f]{64}) -->', notes or '')
    if len(found) != 1:
        raise UpdateError('RELEASE_NOTES_IDENTITY_REQUIRED')
    return found[0]


def draft_validation_identity(release,scope=FIRST_SCOPE):
    """GitHub drafts can have untagged web URLs. Verify IDs via API; only
    construct future canonical URLs for PRE-publication schema validation.
    Published releases are always verified with their actual untouched URLs.
    """
    checked_scope(scope)
    if release.get('draft') is not True:return release
    result=dict(release,html_url=release_url(scope.tag))
    result['assets']=[]
    for asset in release.get('assets',[]):
        name=asset.get('name')
        if name not in scope.names:raise UpdateError('UNEXPECTED_DRAFT_ASSET')
        actual=asset.get('browser_download_url','')
        untagged=re.escape('https://github.com/'+REPO+'/releases/download/')+r'untagged-[A-Za-z0-9_-]{1,100}/'+re.escape(name)
        if actual!=asset_url(scope.tag,name) and not re.fullmatch(untagged,actual):
            raise UpdateError('DRAFT_ASSET_URL_OUTSIDE_PINNED_REPOSITORY')
        result['assets'].append(dict(asset,browser_download_url=asset_url(scope.tag,name)))
    return result


def source_identity():
    value = SourceIdentity(str(ROOT), git('rev-parse', 'HEAD'), git('branch', '--show-current'),
                           bool(git('status', '--porcelain')), verified=True)
    value.require_clean()
    return value


def local_gates(require_clean=True):
    """Revalidate bytes and original frozen evidence; never relabel build history."""
    build = load(PREPARED / VERSION / 'build-report.json')
    baseline = load(PREPARED / '0.1.0/build-report.json')
    if build['version'] != VERSION or build['hashes'] != baseline['hashes']:
        raise UpdateError('REUSED_BUILD_IDENTITY_MISMATCH')
    for name, expected in build['hashes'].items():
        if sha(safe_path(ROOT/name, ROOT)) != expected:
            raise UpdateError('BUILD_SOURCE_DRIFT: ' + name)
        staged = PREPARED / VERSION / 'source' / name
        if sha(staged) != build['version_overlay'].get(name, expected):
            raise UpdateError('STAGED_SOURCE_DRIFT: ' + name)
    for report in (build, baseline):
        for item in report['artifacts']:
            path = safe_path(item['path'], ROOT)
            if sha(path) != item['sha256'] or file_version(path) != report['version']+'.0':
                raise UpdateError('PE_OR_ARTIFACT_DRIFT')
            if path.name.startswith('TransComic') and '-Setup-' not in path.name and pe_architecture(path) != 'x64':
                raise UpdateError('APP_HELPER_X64_REQUIRED')
    installer = PREPARED / VERSION / 'release-assets' / NAMES[0]
    if sha(installer) != build['artifacts'][2]['sha256']:
        raise UpdateError('CANONICAL_INSTALLER_CHANGED')
    assets = [Asset.inspect(n, PREPARED / VERSION / 'release-assets' / n, ROOT) for n in NAMES]
    envelope = load(assets[1].path)
    fixture = {'tag_name': TAG, 'draft': False, 'prerelease': False, 'html_url': release_url(TAG),
               'published_at': 'OFFLINE_VALIDATION_ONLY', 'body': '',
               'assets': [{'name': a.name, 'size': a.size, 'state': 'uploaded',
                           'browser_download_url': asset_url(TAG, a.name)} for a in assets]}
    item = candidate(fixture, envelope)
    verify_checksums(assets[2].path.read_bytes(), item, assets[1].path.read_bytes())
    if (item.sha256, item.size) != (assets[0].sha256, assets[0].size):
        raise UpdateError('LOCAL_METADATA_BINDING_FAILED')
    for version in ('0.1.0', '0.1.1'):
        for scale in ('0.8', '1', '1.2'):
            smoke = load(PREPARED/version/'windows'/scale/'report.json')
            if not (smoke['passed'] and smoke['frozen'] and smoke['version']==version and
                    smoke['safe_exit_verified'] and smoke['exit_code']==0 and
                    smoke['real_http_requests']==smoke['installer_processes']==0):
                raise UpdateError('ORIGINAL_FROZEN_SMOKE_NOT_VERIFIED')
    frozen = load(PREPARED/'source-final-before-regression.json')['source_hashes']
    for name, expected in frozen.items():
        if Path(name).suffix in ('.py', '.toml', '.spec', '.bat', '.iss', '.svg', '.ico', '.lock') and sha(ROOT/name)!=expected:
            # Only the reviewed release entry point is permitted to change.
            if name not in ('scripts/release_transcomic.py','release_transcomic.bat'):
                raise UpdateError('ORIGINAL_REGRESSION_SOURCE_DRIFT: '+name)
    if require_clean:
        source_identity()
    return assets, build


def require_current_tests(scope=FIRST_SCOPE):
    checked_scope(scope)
    proof = load(scope.out/'gates.json')
    if proof['source_commit'] != git('rev-parse', 'HEAD') or proof['source_dirty']:
        raise UpdateError('TEST_SOURCE_COMMIT_CHANGED')
    for name, expected in proof['source_hashes'].items():
        if sha(ROOT/name) != expected:
            raise UpdateError('TEST_SOURCE_CHANGED: '+name)
    for name, expected in proof['test_evidence'].items():
        if sha(scope.out/name) != expected:
            raise UpdateError('TEST_EVIDENCE_CHANGED')
        suite = ET.parse(scope.out/name).getroot().find('testsuite')
        if int(suite.attrib['failures']) or int(suite.attrib['errors']):
            raise UpdateError('RELEASE_TESTS_FAILED')
    if proof['baseline_compatibility'] is not True or proof['privacy_findings']:
        raise UpdateError('BASELINE_OR_PRIVACY_GATE_FAILED')
    if sha(scope.out/'release-notes.md')!=proof['publication_notes_sha256']:
        raise UpdateError('RELEASE_NOTES_CHANGED_AFTER_REVIEW')
    if scope is OFFICIAL_SCOPE or any(scope is s for s in _AUTOMATIC_SCOPES.values()):
        from scripts.official_release import GATE_NAMES
        if set(proof.get('release_gates',{}))!=set(GATE_NAMES) or not all(v is True for v in proof['release_gates'].values()):
            raise UpdateError('OFFICIAL_RELEASE_GATES_NOT_ALL_PASS')
        if scope is not OFFICIAL_SCOPE and proof.get('version')!=scope.version:
            raise UpdateError('AUTOMATIC_VERSION_PROOF_MISMATCH')
    return proof


class FirstReleaseCommands:
    """Concrete gh-only command policy; no caller-supplied command runner."""
    def __init__(self, gh, commit, distribution, build_id, notes, assets,scope=FIRST_SCOPE,read_only=False):
        self.scope=checked_scope(scope);self.read_only=read_only
        self.gh=str(safe_path(gh));self.commit=commit;self.distribution=distribution
        self.build_id=build_id;self.notes=notes;self.assets={a.name:a for a in assets}
        self.release_id=None;self.asset_ids=set();self.events=[]

    def validate(self, argv):
        if argv[:2] != [self.gh, 'api']:
            raise UpdateError('FIRST_RELEASE_GH_ONLY')
        endpoint=argv[2];tail=argv[3:];prefix='repos/'+REPO
        if endpoint==prefix+'/releases?per_page=100' and tail==['--method','GET']:
            return False
        if re.fullmatch(re.escape(prefix)+r'/releases\?per_page=100&page=[1-9][0-9]{0,3}',endpoint) and tail==['--method','GET']:
            return False
        if self.release_id is not None and endpoint==prefix+'/releases/'+str(self.release_id) and tail==['--method','GET']:
            return False
        if endpoint in (prefix+'/releases/tags/'+self.scope.tag, prefix+'/git/ref/tags/'+self.scope.tag) and tail in (['--include'], ['--method','GET']):
            return False
        if re.fullmatch(re.escape(prefix)+r'/releases/assets/[0-9]+', endpoint):
            if int(endpoint.rsplit('/',1)[1]) in self.asset_ids and tail==['-H','Accept: application/octet-stream']:
                return False
        if endpoint == prefix+'/git/refs' and tail == ['--method','POST','-F','ref=refs/tags/'+self.scope.tag,'-F','sha='+self.distribution]:
            return True
        if endpoint == prefix+'/releases':
            payload=self.scope.out/'draft-request.json'
            expected={'tag_name':self.scope.tag,'name':'TransComic '+self.scope.version,'target_commitish':self.distribution,
                      'draft':True,'prerelease':False,'body':self.notes}
            if tail==['--method','POST','--input',str(payload)] and load(payload)==expected:return True
        if self.release_id is not None:
            if endpoint==prefix+'/releases/'+str(self.release_id) and tail==['--method','PATCH','-F','draft=false']:
                return True
            for name, asset in self.assets.items():
                url='https://uploads.github.com/'+prefix+'/releases/'+str(self.release_id)+'/assets?name='+name
                if endpoint==url and tail==['--method','POST','-H','Content-Type: application/octet-stream','--input',str(asset.path)]:
                    return True
        raise UpdateError('OUTSIDE_FIRST_RELEASE_AUTHORIZATION')

    def __call__(self, argv, cwd, timeout=120, limit=1024*1024):
        write=self.validate(argv)
        if write and self.read_only:raise UpdateError('PREVIOUS_RELEASE_READ_ONLY')
        if safe_path(cwd)!=ROOT:raise UpdateError('FIXED_RELEASE_WORKSPACE_REQUIRED')
        if write:
            if source_identity().commit!=self.commit:raise UpdateError('SOURCE_CHANGED_BEFORE_WRITE')
            require_current_tests(self.scope)
            for asset in self.assets.values():
                if Asset.inspect(asset.name,asset.path,ROOT)!=asset:raise UpdateError('ASSET_CHANGED_BEFORE_WRITE')
        intent=None
        if write and any(self.scope is s for s in _AUTOMATIC_SCOPES.values()):
            intent=safe_path(self.scope.out/'remote-intent.json',ROOT)
            if intent.exists() and load(intent).get('outcome')=='PENDING':
                raise UpdateError('REMOTE_INTENT_UNRESOLVED_OUTCOME_UNKNOWN')
            receipts=self.scope.out/'mutation-receipts.json'
            if receipts.exists() and argv[2] in load(receipts):
                raise UpdateError('MUTATION_RECEIPT_PRESENT_RECONCILIATION_REQUIRED')
            self._intent(intent,{'endpoint':argv[2],'build_id':self.build_id,'outcome':'PENDING'})
        try:
            result=subprocess.run(argv,cwd=cwd,capture_output=True,shell=False,timeout=timeout,
                                  creationflags=0x08000000)
        except subprocess.TimeoutExpired:
            raise UpdateError('COMMAND_TIMEOUT_OUTCOME_UNKNOWN') from None
        if len(result.stdout)>limit:raise UpdateError('COMMAND_OUTPUT_LIMIT_OUTCOME_UNKNOWN')
        self.events.append({'endpoint':argv[2].split('?')[0],'write':write,'exit_code':result.returncode,
                            'response_sha256':hashlib.sha256(result.stdout).hexdigest()})
        if result.returncode==0 and '/releases/assets/' not in argv[2] and argv[2].endswith(('/releases','/releases/tags/'+self.scope.tag)):
            raw=result.stdout
            if raw.startswith(b'HTTP/'):
                _,sep,raw=raw.partition(b'\r\n\r\n')
                if not sep:_,sep,raw=result.stdout.partition(b'\n\n')
            self.bind_release(json.loads(raw))
        if intent is not None and result.returncode==0:
            try:
                value=json.loads(result.stdout)
                if argv[2]=='repos/'+REPO+'/git/refs':
                    if value.get('ref')!='refs/tags/'+self.scope.tag or value.get('object',{}).get('sha')!=self.distribution:raise ValueError()
                elif argv[2].startswith('https://uploads.github.com/'):
                    name=argv[2].rsplit('?name=',1)[-1];asset=self.assets[name]
                    if value.get('name')!=name or value.get('size')!=asset.size or value.get('digest')!='sha256:'+asset.sha256 or value.get('state')!='uploaded' or type(value.get('id')) is not int:raise ValueError()
                else:
                    self.bind_release(value)
                    if '--method' in argv and argv[argv.index('--method')+1]=='PATCH' and value.get('draft') is not False:raise ValueError()
            except (ValueError,KeyError,TypeError,AttributeError):raise UpdateError('REMOTE_RESPONSE_OUTCOME_UNKNOWN') from None
            self.acknowledge_intent(intent,{'endpoint':argv[2],'build_id':self.build_id,'outcome':'CONFIRMED_RESPONSE'})
        return CommandResult(result.returncode,result.stdout)

    @staticmethod
    def _intent(path,value):
        import os
        from uuid import uuid4
        part=path.with_name(path.name+'.'+uuid4().hex+'.part')
        with part.open('x',encoding='utf8') as stream:
            json.dump(value,stream);stream.flush();os.fsync(stream.fileno())
        part.replace(path)

    @classmethod
    def acknowledge_intent(cls,path,value):
        receipts=path.parent/'mutation-receipts.json'
        previous=load(receipts) if receipts.exists() else {}
        previous[value['endpoint']]={'build_id':value['build_id'],'confirmed':True}
        cls._intent(receipts,previous)
        cls._intent(path,value)

    def bind_release(self, release):
        if not isinstance(release,dict):raise UpdateError('REMOTE_RELEASE_JSON_INVALID')
        rid=release.get('id')
        if type(rid) is not int or rid<=0 or (self.release_id is not None and self.release_id!=rid):
            raise UpdateError('REMOTE_RELEASE_ID_CHANGED')
        url=release.get('html_url','')
        untagged=re.escape('https://github.com/'+REPO+'/releases/tag/')+r'untagged-[A-Za-z0-9_-]{1,100}'
        valid_url=url==release_url(self.scope.tag) or (release.get('draft') is True and re.fullmatch(untagged,url))
        if (release.get('tag_name')!=self.scope.tag or not valid_url or release.get('prerelease') is not False or
            release.get('url')!='https://api.github.com/repos/'+REPO+'/releases/'+str(rid) or
            release.get('target_commitish')!=self.distribution):
            raise UpdateError('REMOTE_RELEASE_IDENTITY_MISMATCH')
        if identity_in_notes(release.get('body'))!=self.build_id or release.get('body','').rstrip()!=self.notes.rstrip():
            raise UpdateError('CONFLICTING_RELEASE_BUILD_ID_OR_NOTES')
        self.release_id=rid;self.asset_ids={a['id'] for a in release.get('assets',[])}


class FirstReleasePublisher(GitHubPublisher):
    def __init__(self, commands):
        # Reviewed concrete activation, restricted to this one command policy.
        if type(commands) is not FirstReleaseCommands:raise UpdateError('CONCRETE_FIRST_RELEASE_COMMANDS_REQUIRED')
        super().__init__(commands.gh,ROOT,policy='internal')
        self.commands=commands;self.scope=commands.scope

    def read(self, version):
        if version!=self.scope.version:raise UpdateError('ONLY_V0_1_1_AUTHORIZED')
        if self.commands.release_id is not None:
            release=json.loads(self.api('repos/'+REPO+'/releases/'+str(self.commands.release_id)))
            self.commands.bind_release(release)
            return release
        # /releases/tags is documented for published releases; authenticated
        # list includes drafts. Never infer draft absence from tag-route 404.
        releases=[]
        for page in range(1,10001):
            endpoint='repos/'+REPO+'/releases?per_page=100'+('&page='+str(page) if page>1 else '')
            batch=json.loads(self.api(endpoint))
            if not isinstance(batch,list):raise UpdateError('RELEASE_INVENTORY_UNCERTAIN')
            releases.extend(batch)
            if len(batch)<100:break
        else:raise UpdateError('RELEASE_INVENTORY_UNCERTAIN')
        matches=[r for r in releases if r.get('tag_name')==self.scope.tag]
        if len(matches)>1:raise UpdateError('DUPLICATE_RELEASE_IDENTITY')
        if not matches:return None
        release=matches[0];self.commands.bind_release(release)
        (self.scope.out/('remote-read-'+str(len(self.commands.events))+'.json')).write_text(json.dumps(release,indent=2),encoding='utf8')
        return release

    def verify(self, version, release, assets, published=False):
        if version!=self.scope.version:raise UpdateError('ONLY_V0_1_1_AUTHORIZED')
        self.commands.bind_release(release)
        self.check_tag(version,self.commands.distribution)
        validated=release if published else draft_validation_identity(release,self.scope)
        return super().verify(version,validated,assets,published=published)

    def draft(self, version, distribution_sha, public_identity):
        if version!=self.scope.version or distribution_sha!=self.commands.distribution:
            raise UpdateError('ONLY_V0_1_1_AUTHORIZED')
        self.check_tag(version,distribution_sha)
        payload=self.scope.out/'draft-request.json'
        raw=canonical({'tag_name':self.scope.tag,'name':'TransComic '+self.scope.version,'target_commitish':distribution_sha,
                       'draft':True,'prerelease':False,'body':self.commands.notes})
        if payload.exists():
            if payload.read_bytes()!=raw:raise UpdateError('DRAFT_REQUEST_CHANGED')
        else:
            with payload.open('xb') as stream:stream.write(raw)
        result=self.commands([self.commands.gh,'api','repos/'+REPO+'/releases',
                              '--method','POST','--input',str(payload)],ROOT,90,1024*1024)
        if result.code:raise UpdateError('DRAFT_CREATION_OUTCOME_UNKNOWN')
        return json.loads(result.stdout)


class FirstReleaseOperations(ProductionReleaseOperations):
    policy='internal'
    def __init__(self, source, publisher, assets, build_id,local_checker=None,previous_verifier=None):
        self.source=source;self.publisher=publisher;self.assets=assets;self.build_id=build_id
        self.scope=publisher.scope;self.check_local=local_checker or local_gates
        self.previous_verifier=previous_verifier

    def perform(self, phase, record):
        if record['version']!=self.scope.version:raise UpdateError('ONLY_V0_1_1_AUTHORIZED')
        if phase==ReleaseState.PRECHECK:
            self.source.require_clean();self.check_local();require_current_tests(self.scope)
        elif phase==ReleaseState.TESTED:require_current_tests(self.scope)
        elif phase in (ReleaseState.BUILT,ReleaseState.PACKAGED):self.check_local()
        elif phase==ReleaseState.SIGNED:
            self.check_local()
            record['build_id']=self.build_id
            record['asset_inventory']={a.name:{'path':str(a.path),'size':a.size,'sha256':a.sha256} for a in self.assets}
            record['source_commit']=self.source.commit;record['reused_verified_build']=self.scope is FIRST_SCOPE
            record['verified_official_build']=self.scope is OFFICIAL_SCOPE
        elif phase==ReleaseState.DRAFT_CREATED:
            self.remote=self.publisher.read(self.scope.version)
            if self.remote is None:
                self.publisher.prepare_internal_tag(self.scope.version,record['distribution_commit'])
                self.remote=self.publisher.draft(self.scope.version,record['distribution_commit'],{})
            elif not self.remote.get('draft'):
                raise UpdateError('EXISTING_RELEASE_REQUIRES_RECONCILIATION')
        elif phase==ReleaseState.ASSETS_UPLOADED:
            # Always re-read after an uncertain upload; inherited upload skips
            # only assets whose server digest and size both match exactly.
            self.remote=self.publisher.read(self.scope.version)
            self.publisher.upload(self.scope.version,self.remote,self.assets)
        elif phase==ReleaseState.REMOTE_VERIFIED:
            self.remote=self.publisher.read(self.scope.version);self.publisher.verify(self.scope.version,self.remote,self.assets)

    def restore(self, record):
        if record['version']!=self.scope.version or record['origin_id']!=self.build_id:
            raise UpdateError('FIRST_RELEASE_JOURNAL_IDENTITY_CHANGED')
        require_current_tests(self.scope);self.check_local()
        self.remote=self.publisher.read(self.scope.version)

    def reconcile(self, record):
        if record['version']!=self.scope.version:
            if self.scope is not OFFICIAL_SCOPE or record['version']!='0.1.1' or self.previous_verifier is None:
                raise UpdateError('PREVIOUS_RELEASE_RECONCILIATION_REQUIRED')
            return self.previous_verifier(record)
        remote=self.publisher.read(self.scope.version)
        if remote is None:return None
        self.publisher.verify(self.scope.version,remote,self.assets,published=remote.get('draft') is False)
        if identity_in_notes(remote.get('body'))!=self.build_id:
            raise UpdateError('REMOTE_BUILD_IDENTITY_MISMATCH')
        return {'tag':self.scope.tag,'build_id':self.build_id,'assets_verified':True,
                'published':remote['draft'] is False,'draft':remote['draft'] is True}


class FirstReleaseCoordinator(ReleaseCoordinator):
    def run(self, operations):
        if type(operations) is not FirstReleaseOperations or operations.source!=source_identity():
            raise UpdateError('CONCRETE_AUTHORIZED_FIRST_RELEASE_REQUIRED')
        self.scope=operations.scope
        existing=self.journal.load()
        previous=existing and self.scope is OFFICIAL_SCOPE and existing['version']=='0.1.1' and existing['state']==ReleaseState.PUBLISHED
        if existing and not previous and (existing['version']!=self.scope.version or existing['origin_id']!=operations.build_id):
            raise UpdateError('FIRST_RELEASE_JOURNAL_CONFLICT')
        # Explicit version; never infer a next version from a published record.
        return self._execute(operations,current='0.1.1' if self.scope is OFFICIAL_SCOPE else '0.1.0',choice=self.scope.version,build_id=operations.build_id,
                             distribution_commit=operations.publisher.commands.distribution)


def main():
    OUT.mkdir(exist_ok=True,parents=True)
    assets,build=local_gates()
    proof=require_current_tests();source=source_identity()
    build_id=hashlib.sha256(canonical({'source_commit':source.commit,'assets':{a.name:a.sha256 for a in assets}})).hexdigest()
    notes=(OUT/'release-notes.md').read_text(encoding='utf8').rstrip()+'\n\n<!-- transcomic-build-id: '+build_id+' -->\n'
    distribution=proof['distribution_commit']
    commands=FirstReleaseCommands(shutil.which('gh'),source.commit,distribution,build_id,notes,assets)
    publisher=FirstReleasePublisher(commands)
    operations=FirstReleaseOperations(source,publisher,assets,build_id)
    try:
        record=FirstReleaseCoordinator(ReleaseJournal(safe_path(ROOT/'.release-state/journal.json',ROOT))).run(operations)
        (OUT/'published-journal.json').write_text(json.dumps(record,indent=2),encoding='utf8')
    finally:
        (OUT/'command-events.json').write_text(json.dumps(commands.events,indent=2),encoding='utf8')
    print('Published phase reconciled; independent anonymous /releases/latest verification still required.')
    return 0


if __name__=='__main__':
    raise SystemExit('Use release_transcomic.bat --publish-first-internal-0.1.1 after reviewed local gates')
