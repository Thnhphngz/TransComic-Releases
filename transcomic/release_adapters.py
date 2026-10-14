"""Production command construction and responses, behind an unconditional execution lock.

Mocks can exercise the exact argv/response paths. No CLI/env activation exists.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import re
import subprocess
import shutil
from uuid import uuid4
import threading
import time
from .release import version_outputs
from .version import RELEASE_REPOSITORY
from .update.metadata import UpdateError, MAX_DOWNLOAD, MANIFEST_NAME, strict_json, candidate, PRODUCTION_KEYS
from .release_provenance import validate_public_provenance


def locked():
    raise UpdateError('STAGE_A_B1_LOCKED: B2.2 requires reviewed source activation')


@dataclass(frozen=True)
class CommandResult:
    code:int=0
    stdout:bytes=b''


class ProductionCommands:
    def __init__(self):self.events=[]
    def __call__(self,argv,cwd,timeout=120,limit=1024*1024):
        locked()  # before subprocess or any build/network/install side effect
        started=time.monotonic();data=bytearray();overflow=threading.Event()
        process=subprocess.Popen(argv,cwd=cwd,shell=False,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                 creationflags=0x08000000 if __import__('os').name=='nt' else 0)
        def capture():
            try:
                while True:
                    chunk=process.stdout.read(65536)
                    if not chunk:break
                    if len(data)+len(chunk)>limit:
                        overflow.set();process.kill();break  # owns this tool child only, never the app/installer
                    data.extend(chunk)
            finally:process.stdout.close()
        reader=threading.Thread(target=capture,daemon=True);reader.start()
        try:
            code=process.wait(timeout=timeout);reader.join(timeout=5)
            if overflow.is_set() or reader.is_alive():raise UpdateError('COMMAND_OUTPUT_LIMIT_OUTCOME_UNKNOWN')
            return CommandResult(code,bytes(data))
        except subprocess.TimeoutExpired:
            process.kill();process.wait(timeout=5);reader.join(timeout=5)
            raise UpdateError('COMMAND_TIMEOUT_OUTCOME_UNKNOWN') from None
        finally:
            self.events.append({'program':Path(argv[0]).name,'duration':time.monotonic()-started,
                                'exit_code':process.poll(),'captured_bytes':len(data),'output_digest':hashlib.sha256(data).hexdigest()})
            # No argv, key, body, stdout/stderr or personal paths are recorded in the audit event.


class FakeCommands:
    def __init__(self,responses=()):self.responses=list(responses);self.calls=[]
    def __call__(self,argv,cwd,timeout=120,limit=1024*1024):
        self.calls.append({'argv':list(argv),'cwd':str(cwd),'timeout':timeout})
        response=self.responses.pop(0) if self.responses else CommandResult()
        if isinstance(response,Exception):raise response
        if len(response.stdout)>limit:raise UpdateError('COMMAND_OUTPUT_LIMIT')
        return response


def commands_or_default(commands):
    if commands is not None and type(commands) is not FakeCommands:
        raise UpdateError('Only concrete fake command injection allowed in B2.1')
    return commands or ProductionCommands()


def safe_path(path,base=None):
    path=Path(path).absolute()
    for part in (path,*path.parents):
        try:stat=part.lstat()
        except FileNotFoundError:continue
        if part.is_symlink() or getattr(stat,'st_file_attributes',0)&0x400:raise UpdateError('Reparse path rejected')
    resolved=path.resolve()
    if base is not None and not resolved.is_relative_to(Path(base).resolve()):raise UpdateError('Path outside approved workspace')
    return resolved


def execute(commands,argv,cwd,timeout=120,limit=1024*1024):
    try:result=commands(argv,cwd,timeout,limit)
    except subprocess.TimeoutExpired:raise UpdateError('COMMAND_TIMEOUT_OUTCOME_UNKNOWN') from None
    except OSError:raise UpdateError('COMMAND_UNAVAILABLE') from None
    if result.code:raise UpdateError('COMMAND_FAILED_'+str(result.code))
    return result.stdout  # caller parses; never log stdout/stderr containing credentials


class BuildAdapter:
    def __init__(self,python,root,output,commands=None):
        self.python=safe_path(python);self.root=safe_path(root);self.output=safe_path(output,self.root)
        self.commands=commands_or_default(commands)

    def build(self,version,source):
        source.require_clean();version_outputs(version)
        if Path(source.root).resolve()!=self.root:raise UpdateError('BUILD_SOURCE_ROOT_MISMATCH')
        from scripts.release_config import static_configuration
        config=static_configuration(self.root)
        if config['missing'] or not config['qt_windows_plugin']:raise UpdateError('BUILD_INPUTS_NOT_READY')
        for path in [self.root/'run_transcomic.py',*list((self.root/'transcomic').rglob('*.py'))]:
            path=safe_path(path,self.root)
            if re.search(rb'gh[oopsu]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{25,}|sk-[A-Za-z0-9_-]{24,}',path.read_bytes()):raise UpdateError('CREDENTIAL_IN_BUILD_INPUT')
        stage=self.prepare_checkout(version,source)
        argv=[str(self.python),'-m','PyInstaller','--noconfirm','--clean','--distpath',str(stage/'dist'),
              '--workpath',str(self.output/'work'),str(stage/'TransComic.spec')]
        execute(self.commands,argv,stage,1800)
        return stage/'dist/TransComic.exe'

    def prepare_checkout(self,version,source):
        source.require_clean();info=version_outputs(version)
        if type(self.commands) is ProductionCommands:locked()
        stage=safe_path(self.output/('stage-'+uuid4().hex),self.root);stage.mkdir(parents=True)
        files=[self.root/'run_transcomic.py',self.root/'pyproject.toml',self.root/'requirements-release.lock',self.root/'TransComic.spec',
               self.root/'scripts/release_config.py',self.root/'installer/TransComic.iss',self.root/'installer/TransComic.ico',
               self.root/'scripts/update_helper.py',
               *list((self.root/'transcomic').rglob('*.py')),*list((self.root/'transcomic/ui/assets').glob('*.svg'))]
        for path in files:
            path=safe_path(path,self.root);target=stage/path.relative_to(self.root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
        version_file=stage/'transcomic/version.py';text=version_file.read_text(encoding='utf8')
        text,count=re.subn(r"(?m)^VERSION\s*=\s*['\"][^'\"]+['\"]",'VERSION = '+repr(version),text)
        if count!=1:raise UpdateError('SINGLE_VERSION_SOURCE_REQUIRED')
        version_file.write_text(text,encoding='utf8');(stage/'installer/generated-version.iss').write_text(info['iss'],encoding='utf8')
        self.build_provenance={'source_commit':source.commit,'source_tree_state':'clean_source_with_declared_generated_version_overlay',
                               'generated_version':version,'generated_version_sha256':hashlib.sha256(version_file.read_bytes()).hexdigest()}
        self.stage=stage
        return stage

    def test(self):
        execute(self.commands,[str(self.python),'-m','pytest','-q'],self.root,1200)


class PackageAdapter:
    def __init__(self,iscc,root,output,commands=None):
        self.iscc=safe_path(iscc);self.root=safe_path(root);self.output=safe_path(output,self.root)
        self.commands=commands_or_default(commands)

    def package(self,version):
        info=version_outputs(version)
        include=self.root/'installer/generated-version.iss'
        if not include.is_file() or include.read_text(encoding='utf8')!=info['iss']:raise UpdateError('INSTALLER_VERSION_INCLUDE_REQUIRED')
        execute(self.commands,[str(self.iscc),'/O'+str(self.output),'/F'+Path(info['installer']).stem,
                              str(self.root/'installer/TransComic.iss')],self.root,900)
        return self.output/info['installer']


@dataclass(frozen=True)
class Asset:
    name:str
    path:Path
    size:int
    sha256:str

    @classmethod
    def inspect(cls,name,path,base):
        path=safe_path(path,base)
        if path.suffix.lower() not in ('.exe','.json','.txt','.testdata'):raise UpdateError('PRIVATE_DATA_NOT_AN_ASSET')
        if not path.is_file() or not 0<path.stat().st_size<=MAX_DOWNLOAD:raise UpdateError('INVALID_ASSET')
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        return cls(name,path,path.stat().st_size,digest)


def inventory(version,assets):
    required={version_outputs(version)['installer'],MANIFEST_NAME,'SHA256SUMS.txt'}
    if len(assets)!=3 or {a.name for a in assets}!=required:raise UpdateError('ASSET_INVENTORY_MISMATCH')
    if any(a.size<=0 or not re.fullmatch('[0-9a-f]{64}',a.sha256) for a in assets):raise UpdateError('ASSET_HASH_SIZE_INVALID')
    return {a.name:a for a in assets}


class GitHubPublisher:
    repository=RELEASE_REPOSITORY

    def __init__(self,gh,work,commands=None,keys=None,approved_source_fields=frozenset()):
        self.gh=safe_path(gh);self.work=safe_path(work);self.commands=commands_or_default(commands)
        if commands is None and keys is not None:raise UpdateError('Production trust must be pinned')
        self.keys=PRODUCTION_KEYS if keys is None else keys
        self.approved_source_fields=approved_source_fields

    def api(self,endpoint,method='GET',fields=(),limit=1024*1024):
        if not endpoint.startswith('repos/'+RELEASE_REPOSITORY+'/'):raise UpdateError('FIXED_RELEASE_REPO_REQUIRED')
        argv=[str(self.gh),'api',endpoint,'--method',method]
        for field in fields:argv+=['-F',field]
        return execute(self.commands,argv,self.work,90,limit)

    def read(self,version):
        tag=version_outputs(version)['tag']
        endpoint='repos/'+self.repository+'/releases/tags/'+tag
        try:result=self.commands([str(self.gh),'api',endpoint,'--include'],self.work,90,1024*1024)
        except subprocess.TimeoutExpired:raise UpdateError('REMOTE_READ_OUTCOME_UNKNOWN') from None
        raw=result.stdout
        if raw.startswith(b'HTTP/'):
            header,separator,body=raw.partition(b'\r\n\r\n')
            if not separator:header,separator,body=raw.partition(b'\n\n')
            match=re.match(rb'HTTP/[^ ]+ (\d{3})',header)
            if not match or not separator:raise UpdateError('REMOTE_HTTP_RESPONSE_INVALID')
            status=int(match[1]);raw=body
            if status==404:return None
            if status!=200:raise UpdateError('REMOTE_READ_FAILED')
        elif type(self.commands) is not FakeCommands:raise UpdateError('REMOTE_HTTP_STATUS_REQUIRED')
        if result.code:raise UpdateError('REMOTE_READ_FAILED')
        try:return json.loads(raw)
        except ValueError:raise UpdateError('REMOTE_JSON_INVALID') from None

    def check_tag(self,version,distribution_sha):
        if not re.fullmatch('[0-9a-f]{40}',distribution_sha):raise UpdateError('DISTRIBUTION_COMMIT_REQUIRED')
        raw=self.api('repos/'+self.repository+'/git/ref/tags/'+version_outputs(version)['tag'])
        try:ref=json.loads(raw)
        except ValueError:raise UpdateError('REMOTE_TAG_INVALID') from None
        if ref.get('object',{}).get('type')!='commit' or ref['object'].get('sha')!=distribution_sha:raise UpdateError('DISTRIBUTION_TAG_COMMIT_MISMATCH')
        return True

    def draft(self,version,distribution_sha,public_identity):
        self.check_tag(version,distribution_sha)  # no auto-create/move tag, never use private source SHA
        info=version_outputs(version)
        validate_public_provenance(public_identity,self.approved_source_fields)
        fields=['tag_name='+info['tag'],'name='+info['name'],'target_commitish='+distribution_sha,
                'draft=true','prerelease=false','body='+json.dumps(public_identity,sort_keys=True)]
        return json.loads(self.api('repos/'+self.repository+'/releases','POST',fields))

    def upload(self,version,release,assets):
        expected=inventory(version,assets);self._identity(version,release,True)
        existing={a['name']:a for a in release.get('assets',[])}
        for name,asset in expected.items():
            rechecked=Asset.inspect(name,asset.path,asset.path.parent)
            if rechecked!=asset:raise UpdateError('ASSET_CHANGED_BEFORE_UPLOAD')
            if name in existing:
                if existing[name].get('size')!=asset.size or existing[name].get('digest')!='sha256:'+asset.sha256:raise UpdateError('EXISTING_ASSET_CONFLICT')
                continue
            endpoint=f'https://uploads.github.com/repos/{self.repository}/releases/{release["id"]}/assets?name={name}'
            execute(self.commands,[str(self.gh),'api',endpoint,'--method','POST','-H','Content-Type: application/octet-stream',
                                  '--input',str(asset.path)],self.work,300)

    def _identity(self,version,release,draft):
        if release.get('tag_name')!=version_outputs(version)['tag'] or release.get('draft') is not draft or release.get('prerelease') is not False:
            raise UpdateError('REMOTE_RELEASE_IDENTITY_MISMATCH')
        if type(release.get('id')) is not int or release['id']<=0:raise UpdateError('REMOTE_RELEASE_ID_INVALID')

    def verify(self,version,release,assets,published=False):
        expected=inventory(version,assets);self._identity(version,release,not published)
        if published and not release.get('published_at'):raise UpdateError('PUBLISHED_REMOTE_TIMESTAMP_REQUIRED')
        for name,asset in expected.items():
            if Asset.inspect(name,asset.path,asset.path.parent)!=asset:raise UpdateError('LOCAL_ASSET_CHANGED_BEFORE_VERIFICATION')
        remote=release.get('assets',[])
        if len(remote)!=3 or {a.get('name') for a in remote}!=set(expected):raise UpdateError('REMOTE_ASSET_INVENTORY_MISMATCH')
        manifest=expected[MANIFEST_NAME]
        if manifest.size>128*1024:raise UpdateError('MANIFEST_SIZE_LIMIT')
        envelope=strict_json(manifest.path.read_bytes())
        public=envelope.get('payload',{}).get('provenance')
        if public is not None:
            validate_public_provenance(public,self.approved_source_fields)
            try:notes=json.loads(release.get('body','{}'))
            except ValueError:raise UpdateError('REMOTE_PROVENANCE_INVALID') from None
            if notes.get('build_id')!=public.get('build_id'):raise UpdateError('REMOTE_BUILD_IDENTITY_MISMATCH')
        # Verify the local signed envelope against a published-shape identity before allowing draft publication.
        identity=dict(release,draft=False,published_at=release.get('published_at') or 'PREPUBLICATION_VERIFICATION')
        item=candidate(identity,envelope,self.keys)
        installer=expected[version_outputs(version)['installer']]
        if item.signature_status!='VERIFIED_ED25519' or item.sha256!=installer.sha256 or item.size!=installer.size:raise UpdateError('SIGNED_ASSET_BINDING_INVALID')
        sums=''.join(expected[n].sha256+'  '+n+'\n' for n in (installer.name,MANIFEST_NAME)).encode()
        if expected['SHA256SUMS.txt'].path.read_bytes()!=sums:raise UpdateError('CHECKSUM_FILE_MISMATCH')
        for item in remote:
            asset=expected[item['name']]
            if item.get('state')!='uploaded' or item.get('size')!=asset.size or type(item.get('id')) is not int:raise UpdateError('REMOTE_ASSET_NOT_VERIFIED')
            if item.get('digest') not in (None,'sha256:'+asset.sha256):raise UpdateError('REMOTE_DIGEST_MISMATCH')
            raw=execute(self.commands,[str(self.gh),'api',f'repos/{self.repository}/releases/assets/{item["id"]}',
                                      '-H','Accept: application/octet-stream'],self.work,300,asset.size)
            if len(raw)!=asset.size or hashlib.sha256(raw).hexdigest()!=asset.sha256:raise UpdateError('REMOTE_DOWNLOADED_HASH_MISMATCH')
        return True

    def publish(self,version,assets):
        release=self.read(version)
        if release is None:raise UpdateError('DRAFT_RELEASE_MISSING')
        if release.get('draft') is False:
            self.verify(version,release,assets,published=True);return release
        self.verify(version,release,assets)
        self.api(f'repos/{self.repository}/releases/{release["id"]}','PATCH',['draft=false'])
        confirmed=self.read(version);self.verify(version,confirmed,assets,published=True)
        return confirmed
