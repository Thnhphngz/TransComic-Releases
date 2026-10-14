import json
import sqlite3
from dataclasses import replace
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from transcomic.release import (Provenance, MockLedger, FakePublisher, FakePipeline, ReleaseWorkflow, version_outputs)
from transcomic.update.metadata import UpdateError, bumped, PRODUCTION_KEYS
from transcomic.update.signing import TrustPolicy, sign_payload, production_sign
from transcomic.update.helper import ExternalHelper, ProcessIdentity, FakeProcess, FakeEnvironment
from transcomic.update.install import SafetySnapshot, FakeInstaller, State
from transcomic.update.backup import consistent_backup
from transcomic.update.compatibility import schema_compatible, rollback_policy
from scripts.release_config import static_configuration, exe_version_resource, discover


def workflow(tmp_path):
    provenance=Provenance('PrivateOwner/TransComicSource','a'*40,'b'*40)
    ledger=MockLedger(tmp_path/'directory with spaces'/'mock-ledger.json')
    remote=FakePublisher();pipeline=FakePipeline()
    return ReleaseWorkflow(ledger,remote,pipeline),provenance


@pytest.mark.parametrize('choice,expected',[('patch','0.1.1'),('minor','0.2.0'),('major','1.0.0'),('0.3.2','0.3.2')])
def test_version_and_all_consumers(choice,expected):
    info=version_outputs(bumped('0.1.0',choice))
    assert info['version']==expected and info['tag']=='v'+expected
    assert info['installer']==f'TransComic-Setup-{expected}-windows-x64.exe'
    assert expected in info['iss'] and expected in exe_version_resource(expected)


@pytest.mark.parametrize('phase',['preflight','test','build','package','sign','verify','draft','upload','remote_verify','publish'])
def test_failure_resume_same_version_no_double_bump(tmp_path,phase):
    flow,source=workflow(tmp_path)
    adapter=flow.pipeline if phase in ('preflight','test','build','package','sign','verify') else flow.publisher
    adapter.fail=phase
    with pytest.raises(UpdateError):flow.simulate(source,current='0.1.0')
    assert flow.ledger.load()['version']=='0.1.1'
    assert flow.ledger.load()['state']!='RELEASED'
    adapter.fail=None
    result=flow.simulate(source,current='0.1.0',choice='major')
    assert result['state']=='RELEASED' and result['version']=='0.1.1'
    assert sum(x[0]=='draft' for x in flow.publisher.calls)==(2 if phase=='draft' else 1)
    count=sum(x[0]=='publish' for x in flow.publisher.calls)
    assert flow.simulate(source,current='0.1.0')==result
    assert sum(x[0]=='publish' for x in flow.publisher.calls)==count


@pytest.mark.parametrize('failure',['unknown','save'])
def test_remote_published_local_unknown_readonly_reconcile(tmp_path,failure):
    flow,source=workflow(tmp_path)
    flow.publisher.publish_unknown=failure=='unknown';flow.ledger.fail_final=failure=='save'
    with pytest.raises((UpdateError,OSError)):flow.simulate(source,current='0.1.0')
    assert not flow.publisher.releases['v0.1.1']['draft']
    assert flow.ledger.load()['state']=='PUBLISH_PENDING'
    flow.publisher.publish_unknown=False;flow.ledger.fail_final=False
    before=len(flow.publisher.calls)
    assert flow.simulate(source,current='0.1.0')['state']=='RELEASED'
    assert all(x[0]=='read' for x in flow.publisher.calls[before:])


def test_next_release_patch_only_after_confirmed_prior_publish(tmp_path):
    flow,source=workflow(tmp_path)
    assert flow.simulate(source,current='0.1.0')['version']=='0.1.1'
    next_source=replace(source,source_commit='c'*40)
    with pytest.raises(UpdateError):flow.simulate(next_source,current='0.1.0')
    result=flow.simulate(next_source,current='0.1.1')
    assert result['version']=='0.1.2' and result['state']=='RELEASED'
    assert set(flow.publisher.releases)=={'v0.1.1','v0.1.2'}


@pytest.mark.parametrize('corrupt',['manifest_version','signature','provenance','data'])
def test_local_asset_binding_before_any_remote_write(tmp_path,corrupt):
    flow,source=workflow(tmp_path);flow.pipeline.corrupt=corrupt
    with pytest.raises(UpdateError):flow.simulate(source,current='0.1.0')
    assert flow.publisher.calls==[] and flow.ledger.load()['state']=='PENDING'


@pytest.mark.parametrize('kind',['provenance','tag','size','name','bytes','published_missing'])
def test_remote_conflicts_fail_closed(tmp_path,kind):
    flow,source=workflow(tmp_path)
    assert flow.simulate(source,current='0.1.0')['state']=='RELEASED'
    remote=flow.publisher.releases['v0.1.1']
    if kind=='provenance':remote['provenance']['source_commit']='c'*40
    if kind=='tag':flow.publisher.tags['v0.1.1']='c'*40
    if kind=='size':remote['assets'][next(iter(remote['assets']))]+=b'x'
    if kind=='bytes':
        key=next(iter(remote['assets']));remote['assets'][key]=b'x'*len(remote['assets'][key])
    if kind=='name':remote['assets']['rogue']=b'x'
    if kind=='published_missing':del flow.publisher.releases['v0.1.1']
    with pytest.raises(UpdateError):flow.simulate(source,current='0.1.0')
    assert sum(x[0]=='publish' for x in flow.publisher.calls)==1


def test_pending_source_cannot_change_and_unknown_read_does_not_write(tmp_path):
    flow,source=workflow(tmp_path);flow.publisher.fail='upload'
    with pytest.raises(UpdateError):flow.simulate(source,current='0.1.0')
    with pytest.raises(UpdateError):flow.simulate(replace(source,source_commit='c'*40),current='0.1.0')
    flow.publisher.fail='read';count=len(flow.publisher.calls)
    with pytest.raises(UpdateError):flow.simulate(source,current='0.1.0')
    assert all(c[0]=='read' for c in flow.publisher.calls[count:])


@pytest.mark.parametrize('tag',['v0.1.1','v1.0.0'])
def test_duplicate_older_remote_version(tmp_path,tag):
    flow,source=workflow(tmp_path);flow.publisher.releases[tag]={'draft':False}
    with pytest.raises(UpdateError):flow.simulate(source,current='0.1.0')
    assert not flow.ledger.path.exists()


def test_existing_tag_wrong_commit_and_resume_artifact_change(tmp_path):
    flow,source=workflow(tmp_path);flow.publisher.tags['v0.1.1']='c'*40
    with pytest.raises(UpdateError):flow.simulate(source,current='0.1.0')
    assert not flow.publisher.releases
    flow.publisher.tags.clear();flow.publisher.fail='upload'
    with pytest.raises(UpdateError):flow.simulate(source,current='0.1.0')
    flow.pipeline=FakePipeline();flow.publisher.fail=None
    with pytest.raises(UpdateError,match='artifacts changed'):flow.simulate(source,current='0.1.0')


@pytest.mark.parametrize('repo,sha',[('Thnhphngz/TransComic-Releases','a'*40),('https://token@github.com/a/b','a'*40),('a/b','main'),('a/b','c'*39)])
def test_source_identity_required(repo,sha):
    with pytest.raises(UpdateError):Provenance(repo,sha,'b'*40).validate()


def test_mock_adapters_only_and_bad_ledger(tmp_path):
    with pytest.raises(UpdateError):ReleaseWorkflow(MockLedger(tmp_path/'x'),object(),FakePipeline())
    flow,source=workflow(tmp_path);flow.ledger.path.parent.mkdir()
    flow.ledger.path.write_text('{"mock":false}')
    with pytest.raises(UpdateError):flow.simulate(source,current='0.1.0')
    assert not flow.publisher.calls


def test_signing_rotation_revocation_and_tampering():
    old=Ed25519PrivateKey.generate();new=Ed25519PrivateKey.generate()
    pins={'old':old.public_key().public_bytes_raw(),'new':new.public_key().public_bytes_raw()}
    payload={'version':'0.1.1'};a=sign_payload(payload,'old',old);b=sign_payload(payload,'new',new)
    assert TrustPolicy(pins).verify(a) and TrustPolicy(pins).verify(b)
    with pytest.raises(UpdateError):TrustPolicy(pins,frozenset({'old'})).verify(a)
    assert TrustPolicy(pins,frozenset({'old'})).verify(b)
    with pytest.raises(UpdateError):TrustPolicy({'old':pins['new']}).verify(a)
    with pytest.raises(UpdateError):TrustPolicy({'new':pins['new']}).verify(a)
    a['payload']['version']='9.0.0'
    with pytest.raises(UpdateError):TrustPolicy(pins).verify(a)
    assert PRODUCTION_KEYS=={}
    with pytest.raises(UpdateError):production_sign(payload)


def helper_fixture(tmp_path):
    path=tmp_path/'installer.testdata';path.write_bytes(b'verified data')
    identity=ProcessIdentity(42,'created-1');process=FakeProcess(identity,True)
    snapshot=SafetySnapshot(app_closed=True,process_exited=True,safe_exit_verified=True)
    installer=FakeInstaller();env=FakeEnvironment(installed_version='0.1.1')
    def verify(p):
        if p.read_bytes()!=b'verified data':raise UpdateError('Tampered between download and install')
    return path,identity,process,snapshot,installer,verify,'0.1.1',env


@pytest.mark.parametrize('reason',['translating','paused','inflight','transaction','editing','safe_exit_cancel','safe_exit_error','unknown','running','pid_reuse'])
def test_helper_safe_exit_and_exact_process_identity(tmp_path,reason):
    args=list(helper_fixture(tmp_path));kw={}
    if reason in ('translating','paused','inflight','transaction','editing'):args[3]=replace(args[3],**{reason:True})
    if reason.startswith('safe_exit'):args[3]=replace(args[3],safe_exit_verified=False)
    if reason=='unknown':kw['unknown']=True
    if reason=='running':args[2].exited=False
    if reason=='pid_reuse':args[2].identity=ProcessIdentity(42,'created-2')
    helper=ExternalHelper();result=helper.simulate_update(*args,**kw)
    assert result['blocked_by'] and args[4].calls==0 and args[7].restarts==0
    assert helper.state==State.WAITING_FOR_SAFE_EXIT


@pytest.mark.parametrize('reason',['locked','elevation','uac_cancelled','power_loss','version','restart','installer','tamper','cancel'])
def test_helper_install_failure_recovery_no_restart(tmp_path,reason):
    args=list(helper_fixture(tmp_path));kw={}
    if reason in ('locked','elevation','uac_cancelled','power_loss'):setattr(args[7],reason,True)
    if reason=='version':args[7].installed_version='0.1.0'
    if reason=='restart':args[7].restart_success=False
    if reason=='installer':args[4].succeeds=False
    if reason=='tamper':args[0].write_bytes(b'altered');
    if reason=='cancel':kw['cancelled']=True
    helper=ExternalHelper()
    if reason=='tamper':
        with pytest.raises(UpdateError):helper.simulate_update(*args)
        assert args[4].calls==0
    else:assert not helper.simulate_update(*args,**kw)['success']
    assert args[7].restarts==(1 if reason=='restart' else 0)
    assert helper.state!=State.COMPLETED


def test_helper_success_only_simulated_and_install_locked(tmp_path):
    helper=ExternalHelper();args=helper_fixture(tmp_path);result=helper.simulate_update(*args)
    assert result=={'simulated':True,'success':True,'actual_install':False}
    assert helper.state==State.COMPLETED and args[-1].restarts==1
    with pytest.raises(UpdateError):helper.install(*args)


def test_sqlite_backup_migration_and_schema_rollback_limits(tmp_path):
    source=tmp_path/'fixture.sqlite3';db=sqlite3.connect(source)
    db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA user_version=1')
    db.execute('CREATE TABLE protected(data BLOB)');db.execute('INSERT INTO protected VALUES(?)',(b'opaque fixture',));db.commit()
    backup=consistent_backup(source,tmp_path/'backup.sqlite3')
    with sqlite3.connect(backup) as copy:
        assert copy.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert copy.execute('SELECT data FROM protected').fetchone()[0]==b'opaque fixture'
    db.execute('BEGIN');db.execute('ALTER TABLE protected ADD COLUMN added TEXT');db.execute('PRAGMA user_version=2');db.rollback()
    assert db.execute('PRAGMA user_version').fetchone()[0]==1
    assert schema_compatible(1,1,2) and schema_compatible(2,1,2)
    with pytest.raises(UpdateError):schema_compatible(3,1,2)
    with pytest.raises(UpdateError):schema_compatible(0,1,2)
    db.execute('PRAGMA user_version=2');db.commit();db.close()
    assert rollback_policy(False)=='previous_binary_with_compatible_schema'
    assert rollback_policy(True)=='manual_recovery_from_verified_backup'
    with sqlite3.connect(backup) as copy:assert copy.execute('PRAGMA user_version').fetchone()[0]==1


def test_static_allowlist_plugins_resources_lock_and_b1_label():
    root=Path(__file__).resolve().parents[1];report=static_configuration(root)
    assert report['missing']==[] and report['qt_windows_plugin']
    spec=(root/'TransComic.spec').read_text();iss=(root/'installer/TransComic.iss').read_text(encoding='utf8')
    assert 'raise RuntimeError' in spec and '#error Stage A locked' in iss
    assert 'qt_plugins' in spec and "'platforms','imageformats','styles'" in spec
    assert 'icon=' in spec and 'version=' in spec and (root/'installer/TransComic.ico').read_bytes()[:6]==b'\0\0\1\0\1\0'
    assert not any(x in spec for x in ('*.db','*.docx','*.pem','collect_all(','datas=[(str(root)'))
    assert 'PrivilegesRequired=lowest' in iss and 'UsePreviousAppDir=yes' in iss
    assert '[UninstallDelete]' not in iss and 'Flags: unchecked' in iss
    assert 'STAGE B1 — PREFLIGHT ONLY' in (root/'release_transcomic.bat').read_text(encoding='utf8')
    inventory=discover();assert inventory['platform']['bits']==64
    assert 'PySide6==' in (root/'requirements-release.lock').read_text()


def test_configuration_missing_asset_and_dependency(tmp_path,monkeypatch):
    assert static_configuration(tmp_path)['missing']
    import scripts.release_config as config
    def missing(name):raise config.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(config.metadata,'version',missing)
    assert 'dependency:PyInstaller' in static_configuration(tmp_path)['missing']


@pytest.mark.parametrize('kind',['v2','timestamp','unknown_format','tamper'])
def test_manifest_format2_prepublication_signing(kind):
    from test_updater_stage_a import fixture_release
    from transcomic.update.metadata import candidate
    release,envelope,_,_,_=fixture_release()
    key=Ed25519PrivateKey.generate();payload=envelope['payload']
    del payload['published_at'];payload['metadata_format']=2;payload['signed_at']='2026-10-14T00:00:00Z'
    release['published_at']='2026-10-14T00:00:03Z'
    if kind=='timestamp':payload['signed_at']='invalid'
    if kind=='unknown_format':payload['metadata_format']=3
    envelope=sign_payload(payload,'test',key)
    if kind=='tamper':payload['signed_at']='2026-10-15T00:00:00Z'
    if kind=='v2':assert candidate(release,envelope,{'test':key.public_key().public_bytes_raw()},testing=True).signature_status=='VERIFIED_ED25519'
    else:
        with pytest.raises(UpdateError):candidate(release,envelope,{'test':key.public_key().public_bytes_raw()},testing=True)


def test_exe_version_resource_parses_without_build():
    from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct
    value=eval(exe_version_resource('0.1.1'))
    assert isinstance(value,VSVersionInfo)
    assert value.ffi.fileVersionMS==1 and value.ffi.fileVersionLS==65536
