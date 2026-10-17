from update_versions import CURRENT, NEXT
import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from transcomic.release_adapters import (ProductionCommands,FakeCommands,CommandResult,BuildAdapter,PackageAdapter,GitHubPublisher,Asset,inventory,safe_path)
from transcomic.release_provenance import SourceIdentity,build_identity,public_provenance
from transcomic.release_journal import ReleaseJournal,ReleaseState
from transcomic.update.metadata import UpdateError,PRODUCTION_KEYS,PRODUCTION_KEY_STATUS,canonical,MANIFEST_NAME,asset_url,release_url,verify_signature,NOT_READY
from transcomic.update.signing import sign_payload
from transcomic.update.keytools import test_provision,test_sign,production_provision,production_sign_encrypted,FakeACL,WindowsKeyACL
from transcomic.update.authenticode import AuthenticodeAdapter
from transcomic.update.windows_helper import (ProductionUpdateHelper,WindowsRuntime,FakeWindowsRuntime,InstallPlan,AppProcessIdentity)
from transcomic.update.install import SafetySnapshot
from scripts.release_environment import ReadOnlyInspector,pe_architecture

ROOT=Path(__file__).resolve().parents[1]


def source(root=ROOT,**kw):
    values=dict(root=str(root),commit='a'*40,branch='main',dirty=False,repository='private-owner/private-source',private=True,verified=True)
    values.update(kw);return SourceIdentity(**values)


@pytest.mark.parametrize('reason',['missing_git','dirty','untracked','unknown','distribution','credential'])
def test_source_release_gates(reason):
    kw={'verified':False} if reason in ('missing_git','unknown') else {'dirty':True} if reason=='dirty' else {'untracked_build_files':('secret.py',)} if reason=='untracked' else {'repository':'Thnhphngz/TransComic-Releases'}
    if reason=='credential':kw={'repository':'https://token:password@github.com/private/source'}
    with pytest.raises(UpdateError):source(**kw).require_clean()


def test_private_provenance_not_disclosed_without_policy():
    internal=build_identity(source(),'0.1.1',{'Python':'3.13.14'},'b'*64)
    public=public_provenance(internal)
    assert not {'source_commit','source_repository','root','source_private'} & set(public)
    assert 'private-owner' not in json.dumps(public)
    approved=public_provenance(internal,frozenset({'source_commit'}));assert approved['source_commit']=='a'*40
    with pytest.raises(UpdateError):public_provenance(internal,{'root'})
    with pytest.raises(UpdateError):public_provenance(dict(internal,toolchain_versions={'token':'github_pat_SECRET'}))


def test_readonly_inspection_dirty_untracked_redacts_remote():
    answers=[b'C:/project',b'a'*40,b'branch',b'?? transcomic/new.py\n M run_transcomic.py\n',b'https://token:password@github.com/private/source']
    calls=[]
    def run(argv,**kw):calls.append(argv);assert kw['shell'] is False;return subprocess.CompletedProcess(argv,0,answers.pop(0),b'')
    report=ReadOnlyInspector(ROOT,'git','gh',run).source()
    assert report['dirty'] and report['untracked_build_files']==['transcomic/new.py']
    assert report['source_remote_present'] and report['source_private'] is None
    assert 'password' not in json.dumps(report) and 'token' not in json.dumps(report)
    assert report['status']=='SOURCE_PROVENANCE_NOT_READY'


def test_distribution_empty_and_auth_redaction():
    values=[json.dumps({'full_name':'Thnhphngz/TransComic-Releases','default_branch':'main','private':False}).encode(),b'[]',b'gho_'+b'x'*40]
    def run(argv,**kw):return subprocess.CompletedProcess(argv,0,values.pop(0),b'secret')
    inspector=ReadOnlyInspector(ROOT,gh='gh',run=run)
    report=inspector.distribution();assert report['status']=='DISTRIBUTION_REPO_NEEDS_INITIAL_COMMIT' and not report['default_branch_has_commit']
    assert inspector.call('gh',['auth','status'])==(True,b'')
    assert inspector.call('gh',['release','create','v0.1.1'])==(False,b'')


@pytest.mark.parametrize('machine,expected',[(0x8664,'x64'),(0x14c,'x86'),(0xaa64,'arm64')])
def test_pe_tool_architecture_without_execution(tmp_path,machine,expected):
    import struct
    data=bytearray(128);data[:2]=b'MZ';data[60:64]=struct.pack('<I',64);data[64:68]=b'PE\0\0';data[68:70]=struct.pack('<H',machine)
    path=tmp_path/'metadata.bin';path.write_bytes(data);assert pe_architecture(path)==expected


@pytest.mark.parametrize('state',[s for s in ReleaseState if s not in (ReleaseState.PUBLISHED,ReleaseState.PRECHECK)])
def test_durable_journal_states_hold_reserved_version(tmp_path,state):
    journal=ReleaseJournal(tmp_path/'directory with spaces'/'journal.json')
    with journal.exclusive():
        record=journal.reserve('0.1.0',build_id='x');record=journal.checkpoint(record,state)
    with journal.exclusive():
        assert journal.reserve('0.1.0','major')['version']=='0.1.1'
        assert journal.load()['state']==state
    assert not list(journal.path.parent.glob('*.part'))


def test_journal_unknown_publish_reconcile_no_second_bump(tmp_path):
    journal=ReleaseJournal(tmp_path/'journal.json')
    with journal.exclusive():
        record=journal.reserve('0.1.0',build_id='identity')
        record=journal.checkpoint(record,ReleaseState.UNKNOWN_REMOTE_OUTCOME)
        with pytest.raises(UpdateError):journal.checkpoint(record,ReleaseState.PUBLISHED)
        with pytest.raises(UpdateError):journal.reconcile(record,{'tag':'v0.1.1','build_id':'identity','published':True})
        remote={'tag':'v0.1.1','build_id':'identity','published':True,'assets_verified':True}
        assert journal.reconcile(record,remote)['state']==ReleaseState.PUBLISHED
    with journal.exclusive():assert journal.reserve('0.1.0','major')['version']=='0.1.1'


def test_journal_lock_corruption_and_local_save_failure(tmp_path,monkeypatch):
    a=ReleaseJournal(tmp_path/'j.json');b=ReleaseJournal(a.path)
    with a.exclusive():
        with pytest.raises(UpdateError):
            with b.exclusive():pass
        a.reserve('0.1.0')
    a.path.write_text('{"schema":1,"state":"wrong"}')
    with pytest.raises(UpdateError):a.load()
    a.path.unlink()
    with a.exclusive():
        record=a.reserve('0.1.0');old=a.path.read_bytes()
        with monkeypatch.context() as m:
            m.setattr(Path,'replace',lambda *a:(_ for _ in ()).throw(OSError('mock disk failure')))
            with pytest.raises(OSError):a.checkpoint(record,ReleaseState.TESTED)
        assert a.path.read_bytes()==old and not list(tmp_path.glob('*.part'))


def test_build_command_staging_allowlist_overlay_and_original_unchanged(tmp_path,monkeypatch):
    # Use source copy under pytest directory; no EXE created. Tests exercise real argv through fake runner.
    # Match the simulated CPU release profile without modifying an actual CUDA env.
    import scripts.release_config as config
    original_version=config.metadata.version
    def cpu_profile_version(name):
        try:return original_version(name)
        except config.metadata.PackageNotFoundError:
            if name=='onnxruntime':return original_version('onnxruntime-gpu')
            raise
    monkeypatch.setattr(config.metadata,'version',cpu_profile_version)
    import shutil
    root=tmp_path/'source with spaces';root.mkdir()
    for name in ('run_transcomic.py','pyproject.toml','requirements-release.lock','TransComic.spec'):
        shutil.copyfile(ROOT/name,root/name)
    for directory in ('transcomic','installer','scripts'):
        (root/directory).mkdir()
    (root/'transcomic/ui/assets').mkdir(parents=True)
    shutil.copyfile(ROOT/'transcomic/version.py',root/'transcomic/version.py')
    for name in ('TransComic.iss','TransComic.ico'):shutil.copyfile(ROOT/'installer'/name,root/'installer'/name)
    shutil.copyfile(ROOT/'scripts/release_config.py',root/'scripts/release_config.py')
    shutil.copyfile(ROOT/'scripts/update_helper.py',root/'scripts/update_helper.py')
    shutil.copyfile(ROOT/'transcomic/ui/assets/transcomic-main.svg',root/'transcomic/ui/assets/transcomic-main.svg')
    (root/'personal.db').write_bytes(b'private fixture');(root/'.env').write_text('not packaged')
    original=(root/'transcomic/version.py').read_bytes();fake=FakeCommands();adapter=BuildAdapter(sys.executable,root,root/'outputs',fake)
    output=adapter.build('0.1.1',source(root))
    assert output.name=='TransComic.exe' and not output.exists()
    assert (root/'transcomic/version.py').read_bytes()==original
    assert "VERSION = '0.1.1'" in (adapter.stage/'transcomic/version.py').read_text()
    assert not (adapter.stage/'personal.db').exists() and not (adapter.stage/'.env').exists()
    assert fake.calls[0]['argv'][1:3]==['-m','PyInstaller'] and fake.calls[0]['cwd']==str(adapter.stage)
    assert output.parent==adapter.stage/'dist'
    assert fake.calls[0]['argv'][fake.calls[0]['argv'].index('--distpath')+1]==str(output.parent)
    package=PackageAdapter('C:/fake ISCC/ISCC.exe',adapter.stage,adapter.stage/'output',FakeCommands())
    assert package.package('0.1.1').name=='TransComic-Setup-0.1.1-windows-x64.exe'
    assert '/O' in package.commands.calls[0]['argv'][1]


@pytest.mark.parametrize('result',[CommandResult(1,b'secret token'),subprocess.TimeoutExpired('secret',1)])
def test_command_failure_timeout_redacted(result,tmp_path):
    adapter=BuildAdapter(sys.executable,ROOT,ROOT/'artifacts/release-stage-b2-1/no-build',FakeCommands([result]))
    with pytest.raises(UpdateError) as exc:adapter.test()
    assert 'secret' not in str(exc.value) and 'token' not in str(exc.value)


def make_assets(tmp_path):
    version='0.1.1';name=f'TransComic-Setup-{version}-windows-x64.exe';data=b'not executable; data fixture'
    key=Ed25519PrivateKey.generate();keys={'ephemeral':key.public_key().public_bytes_raw()}
    payload={'app_id':'TransComic.Desktop','version':version,'release_tag':'v'+version,'release_url':release_url('v'+version),
             'channel':'stable','os':'windows','architecture':'x64','installer_filename':name,'installer_size':len(data),
             'sha256':hashlib.sha256(data).hexdigest(),'minimum_updater_version':'0.1.0','minimum_windows':'10',
             'metadata_format':2,'signed_at':'2026-10-14T00:00:00Z'}
    files={name:data,MANIFEST_NAME:canonical(sign_payload(payload,'ephemeral',key))}
    files['SHA256SUMS.txt']=''.join(hashlib.sha256(v).hexdigest()+'  '+n+'\n' for n,v in files.items()).encode()
    assets=[]
    for i,(name,value) in enumerate(files.items()):
        path=tmp_path/(str(i)+'.testdata');path.write_bytes(value);assets.append(Asset.inspect(name,path,tmp_path))
    remote={'id':1,'draft':True,'prerelease':False,'tag_name':'v0.1.1','html_url':release_url('v0.1.1'),
            'published_at':None,'assets':[{'id':i+10,'name':a.name,'size':a.size,'state':'uploaded',
                                         'digest':'sha256:'+a.sha256,'browser_download_url':asset_url('v0.1.1',a.name)} for i,a in enumerate(assets)]}
    return assets,files,remote,keys


def test_publisher_signatures_inventory_remote_download_and_publish(tmp_path):
    assets,files,remote,keys=make_assets(tmp_path)
    published=dict(remote,draft=False,published_at='2026-10-14T00:00:05Z')
    responses=[CommandResult(stdout=json.dumps(remote).encode()),*[CommandResult(stdout=v) for v in files.values()],
               CommandResult(stdout=b'{}'),CommandResult(stdout=json.dumps(published).encode()),*[CommandResult(stdout=v) for v in files.values()]]
    commands=FakeCommands(responses);publisher=GitHubPublisher('C:/fake gh/gh.exe',tmp_path,commands,keys)
    assert publisher.publish('0.1.1',assets)['draft'] is False
    writes=[c for c in commands.calls if 'PATCH' in c['argv']];assert len(writes)==1
    assert all('Thnhphngz/TransComic-Releases' in ' '.join(c['argv']) for c in commands.calls)


@pytest.mark.parametrize('bad',['missing','hash','signature','checksum','architecture','state'])
def test_publish_invalid_assets_no_remote_write(tmp_path,bad):
    assets,files,remote,keys=make_assets(tmp_path)
    if bad=='missing':assets=assets[:-1]
    if bad=='hash':remote['assets'][0]['digest']='sha256:'+'f'*64
    if bad=='signature':keys={}
    if bad=='checksum':assets[-1].path.write_bytes(b'wrong')
    if bad=='architecture':
        envelope=json.loads(assets[1].path.read_bytes());envelope['payload']['architecture']='arm64';assets[1].path.write_bytes(canonical(envelope))
    if bad=='state':remote['draft']=False
    commands=FakeCommands([CommandResult(stdout=json.dumps(remote).encode()),*[CommandResult(stdout=v) for v in files.values()]])
    publisher=GitHubPublisher('C:/fake/gh.exe',tmp_path,commands,keys)
    with pytest.raises(UpdateError):publisher.publish('0.1.1',assets)
    assert not any('PATCH' in c['argv'] for c in commands.calls)


def test_upload_partial_timeout_existing_conflict_and_resume(tmp_path):
    assets,files,remote,keys=make_assets(tmp_path);remote['assets']=[]
    commands=FakeCommands([CommandResult(),subprocess.TimeoutExpired('fake',1)])
    publisher=GitHubPublisher('C:/fake/gh.exe',tmp_path,commands,keys)
    with pytest.raises(UpdateError,match='OUTCOME_UNKNOWN'):publisher.upload('0.1.1',remote,assets)
    assert len(commands.calls)==2
    next_dir=tmp_path/'next';next_dir.mkdir();_,_,existing,_=make_assets(next_dir)
    existing['assets'][0]['digest']='sha256:'+'f'*64
    with pytest.raises(UpdateError):publisher.upload('0.1.1',existing,assets)


def test_draft_tag_and_private_input_policy(tmp_path):
    ref={'object':{'type':'commit','sha':'b'*40}}
    runner=FakeCommands([CommandResult(stdout=json.dumps(ref).encode()),CommandResult(stdout=b'{"draft":true}')])
    publisher=GitHubPublisher('C:/fake/gh.exe',tmp_path,runner)
    assert publisher.draft('0.1.1','b'*40,{'build_id':'c'*64})['draft']
    publisher.commands=FakeCommands([CommandResult(stdout=json.dumps(ref).encode())])
    with pytest.raises(UpdateError):publisher.draft('0.1.1','b'*40,{'build_id':'c'*64,'source_repository':'private/source'})
    assert len(publisher.commands.calls)==1
    publisher.commands=FakeCommands([CommandResult(stdout=b'{"object":{"type":"commit","sha":"wrong"}}')])
    with pytest.raises(UpdateError):publisher.check_tag('0.1.1','b'*40)


def test_key_provisioning_encrypted_no_overwrite_backup_warning_and_pair(tmp_path,capsys):
    directory=tmp_path/'keys';password=b'long test password never logged'
    info=test_provision(directory,password)
    assert info.purpose=='test' and info.key_id.startswith('test-') and info.backup_warning
    raw=(directory/'encrypted.testkey').read_bytes();assert b'ENCRYPTED PRIVATE KEY' in raw
    envelope=test_sign(directory,password,{'version':'0.1.1'})
    assert verify_signature(envelope['payload'],envelope['signature'],{info.key_id:base64.b64decode(info.public_key)})=='VERIFIED_ED25519'
    with pytest.raises(UpdateError):test_provision(directory,password)
    with pytest.raises(UpdateError):test_sign(directory,b'wrong',{})
    with pytest.raises(UpdateError):test_sign(directory,password,{},FakeACL(False))
    assert capsys.readouterr().out=='' and b'long test password' not in raw


def test_key_acl_failure_and_production_guard_prevents_any_creation(tmp_path,monkeypatch):
    with pytest.raises(UpdateError):test_provision(tmp_path/'bad',b'long test password',FakeACL(False))
    monkeypatch.setattr(Ed25519PrivateKey,'generate',lambda:(_ for _ in ()).throw(AssertionError('production RNG forbidden')))
    with pytest.raises(UpdateError):production_provision(tmp_path/'production',b'long test password')
    with pytest.raises(UpdateError):production_sign_encrypted(tmp_path, b'password',{})
    assert not (tmp_path/'production').exists() and PRODUCTION_KEYS=={} and PRODUCTION_KEY_STATUS=={}
    with pytest.raises(UpdateError):WindowsKeyACL().verify(tmp_path)


def test_authenticode_validates_signer_chain_and_timestamp(tmp_path):
    proof={'status':'Valid','thumbprint':'a'*40,'subject':'CN=Approved Publisher','timestamped':True}
    fake=FakeCommands([CommandResult(),CommandResult(stdout=json.dumps(proof).encode())])
    adapter=AuthenticodeAdapter('C:/SDK/signtool.exe','C:/Windows/powershell.exe','a'*40,'CN=Approved Publisher',fake)
    assert adapter.verify(tmp_path/"quote's fixture.testdata")
    assert "quote''s" in fake.calls[-1]['argv'][-1]
    for field,value in (('status','UnknownError'),('thumbprint','b'*40),('subject','CN=Wrong'),('timestamped',False)):
        adapter.commands=FakeCommands([CommandResult(),CommandResult(stdout=json.dumps(dict(proof,**{field:value})).encode())])
        with pytest.raises(UpdateError):adapter.verify(tmp_path/'fixture.testdata')


def helper_plan(tmp_path):
    from test_updater_stage_a import fixture_release
    release,envelope,_,keys,data=fixture_release()
    updates=tmp_path/'updates';updates.mkdir();installation=tmp_path/'installed';installation.mkdir()
    path=updates/envelope['payload']['installer_filename'];path.write_bytes(data)
    identity=AppProcessIdentity(42,123,str(installation/'TransComic.exe'))
    plan=InstallPlan(release['tag_name'][1:],path,len(data),hashlib.sha256(data).hexdigest(),release,envelope,identity)
    runtime=FakeWindowsRuntime();runtime.identity=identity
    helper=ProductionUpdateHelper(updates,installation,runtime,keys)
    snapshot=SafetySnapshot(app_closed=True,process_exited=True,safe_exit_verified=True)
    return helper,plan,snapshot,runtime


@pytest.mark.parametrize('bad',['identity','running','tamper','uac','quarantine','timeout','installer','version','restart','cancel','busy','transaction','safe_exit','outside','metadata_path'])
def test_production_helper_algorithm_fake_only(tmp_path,bad):
    helper,plan,snapshot,runtime=helper_plan(tmp_path);cancel=threading.Event()
    if bad=='identity':runtime.identity=replace(plan.process,creation_time=124)
    if bad=='running':runtime.process_exited=False
    if bad=='tamper':plan.installer.write_bytes(b'x'*plan.size)
    if bad in ('uac','quarantine','timeout','installer','version','restart'):runtime.fail=bad
    if bad=='cancel':cancel.set()
    if bad=='busy':snapshot=replace(snapshot,inflight=True)
    if bad=='transaction':snapshot=replace(snapshot,transaction=True)
    if bad=='safe_exit':snapshot=replace(snapshot,safe_exit_verified=False)
    if bad=='outside':plan=replace(plan,installer=tmp_path/'outside.testdata')
    if bad=='metadata_path':plan=replace(plan,process=replace(plan.process,image='C:/Windows/notepad.exe'))
    with pytest.raises(UpdateError):helper.run(plan,snapshot,cancel)
    if bad!='restart':assert 'restart' not in runtime.calls
    if bad in ('identity','running','tamper','cancel','busy','transaction','safe_exit','outside','metadata_path'):assert 'install' not in runtime.calls


def test_helper_success_restart_preference_and_default_guard(tmp_path):
    helper,plan,snapshot,runtime=helper_plan(tmp_path)
    assert helper.run(plan,snapshot,threading.Event())=={'success':True,'simulated':True,'actual_install':False}
    runtime.calls.clear();helper.run(replace(plan,restart=False),snapshot,threading.Event());assert 'restart' not in runtime.calls
    production=ProductionUpdateHelper(tmp_path/'updates',tmp_path/'installed')
    with pytest.raises(UpdateError):production.run(plan,snapshot,threading.Event())
    with pytest.raises(UpdateError):WindowsRuntime().open_process(plan.process)


def test_all_production_commands_locked_even_environment_flags(monkeypatch,tmp_path):
    monkeypatch.setenv('TRANSCOMIC_RELEASE_PRODUCTION','1');calls=[]
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:calls.append(a))
    with pytest.raises(UpdateError):ProductionCommands()(['gh','release','create'],tmp_path)
    assert calls==[]
    with pytest.raises(UpdateError):GitHubPublisher('C:/fake/gh.exe',tmp_path).read('0.1.1')
    assert calls==[]
    with pytest.raises(UpdateError):Asset.inspect('installer.exe',tmp_path/'user.sqlite3',tmp_path)


@pytest.mark.parametrize('phase',[ReleaseState.TESTED,ReleaseState.BUILT,ReleaseState.PACKAGED,ReleaseState.SIGNED,ReleaseState.DRAFT_CREATED,ReleaseState.ASSETS_UPLOADED,ReleaseState.REMOTE_VERIFIED])
def test_coordinator_checkpoint_resume_pipeline(tmp_path,phase):
    from transcomic.release_pipeline import ReleaseCoordinator,FakeReleaseOperations
    journal=ReleaseJournal(tmp_path/'journal.json');coordinator=ReleaseCoordinator(journal);operations=FakeReleaseOperations();operations.fail=phase
    with pytest.raises(UpdateError):coordinator.simulate(operations,current='0.1.0')
    assert journal.load()['state']==ReleaseState.FAILED
    operations.fail=None
    assert coordinator.simulate(operations,current='0.1.0',choice='major')['version']=='0.1.1'
    assert journal.load()['state']==ReleaseState.PUBLISHED
    assert operations.calls.count('publish')==1
    before=len(operations.calls);assert coordinator.simulate(operations,current='0.1.0')['state']==ReleaseState.PUBLISHED
    assert operations.calls[before:]==['reconcile']


def test_coordinator_unknown_remote_outcome_local_save_failure_next_patch(tmp_path,monkeypatch):
    from transcomic.release_pipeline import ReleaseCoordinator,FakeReleaseOperations
    journal=ReleaseJournal(tmp_path/'journal.json');coordinator=ReleaseCoordinator(journal);operations=FakeReleaseOperations();operations.unknown_publish=True
    with pytest.raises(UpdateError):coordinator.simulate(operations,current='0.1.0')
    assert journal.load()['state']==ReleaseState.UNKNOWN_REMOTE_OUTCOME
    operations.unknown_publish=False;before=len(operations.calls)
    assert coordinator.simulate(operations,current='0.1.0')['state']==ReleaseState.PUBLISHED
    assert operations.calls[before:]==['reconcile']
    assert coordinator.simulate(operations,current='0.1.0',build_id='new-clean-source')['version']=='0.1.2'
    assert operations.calls.count('publish')==2
    with pytest.raises(UpdateError):coordinator.run(operations)


def test_prod_read_explicit_404_and_unknown_status(tmp_path):
    commands=FakeCommands([CommandResult(1,b'HTTP/2.0 404 Not Found\r\nX: y\r\n\r\n{"status":"404"}')])
    publisher=GitHubPublisher('C:/fake/gh.exe',tmp_path,commands)
    assert publisher.read('0.1.1') is None
    publisher.commands=FakeCommands([CommandResult(1,b'HTTP/2.0 403 Forbidden\r\n\r\n{}')])
    with pytest.raises(UpdateError):publisher.read('0.1.1')


def test_production_registry_status_never_trusts_test_namespace(monkeypatch):
    from transcomic.update import metadata
    key=Ed25519PrivateKey.generate();payload={};envelope=sign_payload(payload,'test-forbidden',key)
    monkeypatch.setitem(metadata.PRODUCTION_KEYS,'test-forbidden',key.public_key().public_bytes_raw())
    monkeypatch.setitem(metadata.PRODUCTION_KEY_STATUS,'test-forbidden','active')
    assert verify_signature(payload,envelope['signature'],metadata.PRODUCTION_KEYS)==NOT_READY
    monkeypatch.setitem(metadata.PRODUCTION_KEY_STATUS,'test-forbidden','revoked')
    with pytest.raises(UpdateError):verify_signature(payload,envelope['signature'],metadata.PRODUCTION_KEYS)


@pytest.mark.parametrize('flag',['logger_flushing','stop_requested','outcome_unknown','safe_exit_cancelled'])
def test_helper_handoff_preserves_unknown_and_logger_flush(tmp_path,flag):
    from transcomic.update.windows_helper import HandoffSafety
    helper,plan,snapshot,runtime=helper_plan(tmp_path)
    with pytest.raises(UpdateError):helper.run(plan,snapshot,threading.Event(),handoff=HandoffSafety(**{flag:True}))
    assert runtime.calls==[]


def test_locked_key_cli_no_secret_prompt_or_persistent_key(tmp_path,monkeypatch,capsys):
    from scripts.provision_release_key import main
    monkeypatch.setattr('getpass.getpass',lambda *a:(_ for _ in ()).throw(AssertionError('Prompt not permitted')))
    assert main(['--directory',str(tmp_path/'forbidden')])==2
    assert not (tmp_path/'forbidden').exists()
    assert 'no key created' in capsys.readouterr().out


def test_install_plan_json_cannot_supply_executable_or_keys(tmp_path):
    from transcomic.update.windows_helper import load_install_plan
    helper,plan,_,_=helper_plan(tmp_path)
    value={'release':plan.release,'manifest':plan.envelope,'pid':42,'creation_time':123,'restart':True,'safe_exit_verified':True}
    loaded=load_install_plan(canonical(value),helper.updates,helper.installation,helper.keys,True)
    assert loaded.installer==plan.installer and loaded.process.image==str(helper.app)
    for field in ('executable','installer_path','installation','public_key','api_key','token'):
        with pytest.raises(UpdateError):load_install_plan(canonical(dict(value,**{field:'untrusted'})),helper.updates,helper.installation,helper.keys,True)
    with pytest.raises(UpdateError):load_install_plan(canonical(dict(value,safe_exit_verified=False)),helper.updates,helper.installation,helper.keys,True)


def test_junction_attribute_and_traversal_rejected(tmp_path,monkeypatch):
    from types import SimpleNamespace
    path=tmp_path/'junction';path.mkdir()
    original=Path.lstat
    with monkeypatch.context() as m:
        m.setattr(Path,'lstat',lambda self:SimpleNamespace(st_file_attributes=0x400,st_mode=original(self).st_mode) if self==path else original(self))
        with pytest.raises(UpdateError):safe_path(path)
    with pytest.raises(UpdateError):safe_path(tmp_path/'../escape',tmp_path)


def test_helper_handoff_separates_running_binary_from_installer_targets(tmp_path,monkeypatch):
    from transcomic.update.windows_helper import HelperHandoff,registered_installation
    handoff=HelperHandoff(tmp_path/'Updates',tmp_path/'Installed',None)
    layout=handoff.preview()
    assert layout['helper'].parent!=layout['installation'] and layout['helper'].is_relative_to(tmp_path/'Updates')
    assert not layout['overwrites_running_helper']
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**kw:(_ for _ in ()).throw(AssertionError('No actual helper process')))
    with pytest.raises(UpdateError):handoff.launch(b'{}')
    with pytest.raises(UpdateError):registered_installation()
    assert not (tmp_path/'Updates').exists()
