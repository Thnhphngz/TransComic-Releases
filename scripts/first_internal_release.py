"""One authorized Internal v0.1.1 publication using existing release machinery.

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


def require_current_tests():
    proof = load(OUT/'gates.json')
    if proof['source_commit'] != git('rev-parse', 'HEAD') or proof['source_dirty']:
        raise UpdateError('TEST_SOURCE_COMMIT_CHANGED')
    for name, expected in proof['source_hashes'].items():
        if sha(ROOT/name) != expected:
            raise UpdateError('TEST_SOURCE_CHANGED: '+name)
    for name, expected in proof['test_evidence'].items():
        if sha(OUT/name) != expected:
            raise UpdateError('TEST_EVIDENCE_CHANGED')
        suite = ET.parse(OUT/name).getroot().find('testsuite')
        if int(suite.attrib['failures']) or int(suite.attrib['errors']):
            raise UpdateError('RELEASE_TESTS_FAILED')
    if proof['baseline_compatibility'] is not True or proof['privacy_findings']:
        raise UpdateError('BASELINE_OR_PRIVACY_GATE_FAILED')
    if sha(OUT/'release-notes.md')!=proof['publication_notes_sha256']:
        raise UpdateError('RELEASE_NOTES_CHANGED_AFTER_REVIEW')
    return proof


class FirstReleaseCommands:
    """Concrete gh-only command policy; no caller-supplied command runner."""
    def __init__(self, gh, commit, distribution, build_id, notes, assets):
        self.gh=str(safe_path(gh));self.commit=commit;self.distribution=distribution
        self.build_id=build_id;self.notes=notes;self.assets={a.name:a for a in assets}
        self.release_id=None;self.asset_ids=set();self.events=[]

    def validate(self, argv):
        if argv[:2] != [self.gh, 'api']:
            raise UpdateError('FIRST_RELEASE_GH_ONLY')
        endpoint=argv[2];tail=argv[3:];prefix='repos/'+REPO
        if endpoint in (prefix+'/releases/tags/'+TAG, prefix+'/git/ref/tags/'+TAG) and tail in (['--include'], ['--method','GET']):
            return False
        if re.fullmatch(re.escape(prefix)+r'/releases/assets/[0-9]+', endpoint):
            if int(endpoint.rsplit('/',1)[1]) in self.asset_ids and tail==['-H','Accept: application/octet-stream']:
                return False
        if endpoint == prefix+'/git/refs' and tail == ['--method','POST','-F','ref=refs/tags/'+TAG,'-F','sha='+self.distribution]:
            return True
        if endpoint == prefix+'/releases':
            payload=OUT/'draft-request.json'
            expected={'tag_name':TAG,'name':'TransComic '+VERSION,'target_commitish':self.distribution,
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
        if safe_path(cwd)!=ROOT:raise UpdateError('FIXED_RELEASE_WORKSPACE_REQUIRED')
        if write:
            if source_identity().commit!=self.commit:raise UpdateError('SOURCE_CHANGED_BEFORE_WRITE')
            require_current_tests()
            for asset in self.assets.values():
                if Asset.inspect(asset.name,asset.path,ROOT)!=asset:raise UpdateError('ASSET_CHANGED_BEFORE_WRITE')
        try:
            result=subprocess.run(argv,cwd=cwd,capture_output=True,shell=False,timeout=timeout,
                                  creationflags=0x08000000)
        except subprocess.TimeoutExpired:
            raise UpdateError('COMMAND_TIMEOUT_OUTCOME_UNKNOWN') from None
        if len(result.stdout)>limit:raise UpdateError('COMMAND_OUTPUT_LIMIT_OUTCOME_UNKNOWN')
        self.events.append({'endpoint':argv[2].split('?')[0],'write':write,'exit_code':result.returncode,
                            'response_sha256':hashlib.sha256(result.stdout).hexdigest()})
        if result.returncode==0 and '/releases/assets/' not in argv[2] and argv[2].endswith(('/releases','/releases/tags/'+TAG)):
            raw=result.stdout
            if raw.startswith(b'HTTP/'):
                _,sep,raw=raw.partition(b'\r\n\r\n')
                if not sep:_,sep,raw=result.stdout.partition(b'\n\n')
            release=json.loads(raw)
            if release.get('tag_name')!=TAG or release.get('html_url')!=release_url(TAG):
                raise UpdateError('REMOTE_RELEASE_IDENTITY_MISMATCH')
            if identity_in_notes(release.get('body'))!=self.build_id:
                raise UpdateError('CONFLICTING_RELEASE_BUILD_ID')
            self.release_id=release['id']
            self.asset_ids={a['id'] for a in release.get('assets',[])}
        return CommandResult(result.returncode,result.stdout)


class FirstReleasePublisher(GitHubPublisher):
    def __init__(self, commands):
        # Reviewed concrete activation, restricted to this one command policy.
        if type(commands) is not FirstReleaseCommands:raise UpdateError('CONCRETE_FIRST_RELEASE_COMMANDS_REQUIRED')
        super().__init__(commands.gh,ROOT,policy='internal')
        self.commands=commands

    def draft(self, version, distribution_sha, public_identity):
        if version!=VERSION or distribution_sha!=self.commands.distribution:
            raise UpdateError('ONLY_V0_1_1_AUTHORIZED')
        self.check_tag(version,distribution_sha)
        payload=OUT/'draft-request.json'
        raw=canonical({'tag_name':TAG,'name':'TransComic '+VERSION,'target_commitish':distribution_sha,
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
    def __init__(self, source, publisher, assets, build_id):
        self.source=source;self.publisher=publisher;self.assets=assets;self.build_id=build_id

    def perform(self, phase, record):
        if record['version']!=VERSION:raise UpdateError('ONLY_V0_1_1_AUTHORIZED')
        if phase==ReleaseState.PRECHECK:
            self.source.require_clean();local_gates();require_current_tests()
        elif phase==ReleaseState.TESTED:require_current_tests()
        elif phase in (ReleaseState.BUILT,ReleaseState.PACKAGED):local_gates()
        elif phase==ReleaseState.SIGNED:
            local_gates()
            record['build_id']=self.build_id
            record['asset_inventory']={a.name:{'path':str(a.path),'size':a.size,'sha256':a.sha256} for a in self.assets}
            record['source_commit']=self.source.commit;record['reused_verified_build']=True
        elif phase==ReleaseState.DRAFT_CREATED:
            self.remote=self.publisher.read(VERSION)
            if self.remote is None:
                self.publisher.prepare_internal_tag(VERSION,record['distribution_commit'])
                self.remote=self.publisher.draft(VERSION,record['distribution_commit'],{})
            elif not self.remote.get('draft'):
                raise UpdateError('EXISTING_RELEASE_REQUIRES_RECONCILIATION')
        elif phase==ReleaseState.ASSETS_UPLOADED:
            # Always re-read after an uncertain upload; inherited upload skips
            # only assets whose server digest and size both match exactly.
            self.remote=self.publisher.read(VERSION)
            self.publisher.upload(VERSION,self.remote,self.assets)
        elif phase==ReleaseState.REMOTE_VERIFIED:
            self.remote=self.publisher.read(VERSION);self.publisher.verify(VERSION,self.remote,self.assets)

    def restore(self, record):
        if record['version']!=VERSION or record['origin_id']!=self.build_id:
            raise UpdateError('FIRST_RELEASE_JOURNAL_IDENTITY_CHANGED')
        require_current_tests();local_gates()
        self.remote=self.publisher.read(VERSION)

    def reconcile(self, record):
        remote=self.publisher.read(VERSION)
        if remote is None:return None
        self.publisher.verify(VERSION,remote,self.assets,published=remote.get('draft') is False)
        if identity_in_notes(remote.get('body'))!=self.build_id:
            raise UpdateError('REMOTE_BUILD_IDENTITY_MISMATCH')
        return {'tag':TAG,'build_id':self.build_id,'assets_verified':True,
                'published':remote['draft'] is False,'draft':remote['draft'] is True}


class FirstReleaseCoordinator(ReleaseCoordinator):
    def run(self, operations):
        if type(operations) is not FirstReleaseOperations or operations.source!=source_identity():
            raise UpdateError('CONCRETE_AUTHORIZED_FIRST_RELEASE_REQUIRED')
        existing=self.journal.load()
        if existing and (existing['version']!=VERSION or existing['origin_id']!=operations.build_id):
            raise UpdateError('FIRST_RELEASE_JOURNAL_CONFLICT')
        # Explicit version; never infer a next version from a published record.
        return self._execute(operations,current='0.1.0',choice=VERSION,build_id=operations.build_id,
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
