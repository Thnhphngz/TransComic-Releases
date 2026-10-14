import json
from pathlib import Path
import pytest
from transcomic.release_version import bumped, validate_release_version, preview_version
from transcomic.release import version_outputs
from transcomic.release_journal import ReleaseJournal, ReleaseState
from transcomic.update.metadata import SemVer, UpdateError, verify_signature, PRODUCTION_KEYS
from transcomic.update.keytools import (test_provision, test_sign, test_backup, test_restore,
                                       production_backup, production_restore, FakeACL)


@pytest.mark.parametrize('old,new',[
    ('0.1.0','0.1.1'),('0.1.8','0.1.9'),('0.1.9','0.2.0'),('0.9.9','1.0.0'),
    ('1.0.1','1.0.2'),('1.0.8','1.0.9'),('1.0.9','1.1.0'),('1.1.9','1.2.0'),
    ('1.9.9','2.0.0'),('2.9.9','3.0.0'),('9.9.9','10.0.0')])
def test_carry(old,new):
    assert bumped(old)==new
    out=version_outputs(new)
    assert out['tag']=='v'+new and out['name']=='TransComic '+new
    assert out['installer']==f'TransComic-Setup-{new}-windows-x64.exe'
    assert out['exe_tuple']==tuple(map(int,new.split('.')))+(0,)
    assert f'"{new}"' in out['iss']


@pytest.mark.parametrize('old,choice,new',[
    ('1.2.4','minor','1.3.0'),('1.9.4','minor','2.0.0'),('1.2.4','major','2.0.0'),
    ('1.0.9','1.2.3','1.2.3')])
def test_explicit_and_manual(old,choice,new):assert bumped(old,choice)==new


@pytest.mark.parametrize('bad',['1.0.10','1.0.100','1.10.0','1.0.1+local','1.1.0-rc.1','01.1.0'])
def test_reject_release_only(bad):
    with pytest.raises(UpdateError):validate_release_version(bad)
    with pytest.raises(UpdateError):version_outputs(bad)
    with pytest.raises(UpdateError):bumped('1.0.0',bad)


def test_generic_semver_unchanged():
    from transcomic.update.metadata import bumped as generic
    assert generic('1.0.9','patch')=='1.0.10'
    assert sorted(map(SemVer.parse,['10.0.0','1.10.0','1.0.100','1.0.9']))==list(map(SemVer.parse,['1.0.9','1.0.100','1.10.0','10.0.0']))


@pytest.mark.parametrize('state',[ReleaseState.FAILED,ReleaseState.UNKNOWN_REMOTE_OUTCOME])
def test_reserved_boundary_no_double_bump(tmp_path,state):
    journal=ReleaseJournal(tmp_path/'journal.json')
    with journal.exclusive():
        record=journal.reserve('1.0.8',build_id='first')
        journal.checkpoint(record,state)
    with journal.exclusive():
        assert journal.reserve('1.0.8',build_id='first')['version']=='1.0.9'
        with pytest.raises(UpdateError,match='RELEASE_STATE_UNCERTAIN'):
            journal.next_release(record,{'tag':'v1.0.9','build_id':'first','assets_verified':False,'published':True},'second')
        remote={'tag':'v1.0.9','build_id':'first','assets_verified':True,'published':True}
        assert journal.next_release(record,remote,'second')['version']=='1.1.0'


def test_preview_readonly_and_uncertainty():
    record={'state':'FAILED','version':'1.0.9','build_id':'abc'}
    before=dict(record)
    assert preview_version('1.0.8',record=record)=='1.0.9'
    assert record==before
    for remote in ({'tag':'v1.0.9'}, {'tag':'v1.0.10','build_id':'abc','assets_verified':True,'published':True}):
        with pytest.raises(UpdateError,match='RELEASE_STATE_UNCERTAIN'):preview_version('1.0.8',record=record,remote=remote)
    with pytest.raises(UpdateError):preview_version('1.0.8',remote_known=False)
    with pytest.raises(UpdateError):preview_version('1.0.9',record=record)


def test_encrypted_portable_recovery(tmp_path,capsys):
    password=b'original-password-123';recovery=b'offline-password-456';new_password=b'new-machine-password-789'
    original=tmp_path/'original'; restored=tmp_path/'new-machine'
    info=test_provision(original,password)
    backup=tmp_path/'offline.tc-keybackup'
    test_backup(original,password,backup,recovery)
    assert b'BEGIN ENCRYPTED PRIVATE KEY' in (original/'encrypted.testkey').read_bytes()
    assert b'PRIVATE KEY' not in backup.read_bytes()
    recovered=test_restore(backup,recovery,restored,new_password)
    assert recovered.key_id==info.key_id and recovered.backup_warning is None
    payload={'version':'1.1.0','nested':{'b':2,'a':1}}
    signed=test_sign(restored,new_password,payload)
    import base64
    verify_signature(payload,signed['signature'],{info.key_id:base64.b64decode(info.public_key)})
    assert verify_signature(payload,signed['signature'],PRODUCTION_KEYS)=='NOT_READY_FOR_PRODUCTION_INSTALL'
    with pytest.raises(UpdateError):test_sign(restored,password,payload)
    with pytest.raises(UpdateError):test_restore(backup,recovery,restored,new_password)
    with pytest.raises(UpdateError):test_backup(original,password,backup,recovery)
    assert capsys.readouterr().out==''


@pytest.mark.parametrize('failure',['wrong-password','metadata-tamper','ciphertext-tamper','purpose','acl','truncated','missing'])
def test_recovery_fail_closed(tmp_path,failure):
    password=b'test-password-123456';recovery=b'recovery-password-123456'
    original=tmp_path/'key';test_provision(original,password)
    backup=tmp_path/'offline.tc-keybackup';test_backup(original,password,backup,recovery)
    data=json.loads(backup.read_text())
    if failure=='metadata-tamper':data['key_id']='test-other'
    if failure=='ciphertext-tamper':data['ciphertext']='AAAA'
    if failure=='purpose':data['purpose']='production'
    backup.write_text(json.dumps(data))
    if failure=='truncated':backup.write_bytes(b'{')
    if failure=='missing':backup.unlink()
    target=tmp_path/'restored'
    with pytest.raises(UpdateError):test_restore(backup,b'wrong-password-1234' if failure=='wrong-password' else recovery,target,password,FakeACL(failure!='acl'))
    assert not target.exists()


def test_production_recovery_locked_before_any_io(tmp_path):
    with pytest.raises(UpdateError,match='LOCKED'):production_backup(tmp_path/'absent',b'x',tmp_path/'backup',b'x')
    with pytest.raises(UpdateError,match='LOCKED'):production_restore(tmp_path/'absent',b'x',tmp_path/'new',b'x')
    assert list(tmp_path.iterdir())==[]


def test_preflight_reservation_readonly(tmp_path,monkeypatch):
    from scripts import release_transcomic as script
    from test_updater_stage_a import fake_commands
    monkeypatch.setattr(script,'VERSION','1.0.8')
    journal=ReleaseJournal(tmp_path/'journal.json')
    with journal.exclusive():record=journal.reserve('1.0.8',build_id='intent')
    before=journal.path.read_bytes()
    def commands(args):
        if 'api' in args:return False,'HTTP/2.0 404 Not Found\n{}'
        return fake_commands(args)
    report=script.preflight(commands=commands,journal_path=journal.path)
    assert report['proposed_version']=='1.0.9' and report['journal_mutated'] is False
    assert journal.path.read_bytes()==before and not journal.lock.exists()
    with journal.exclusive():journal.checkpoint(record,ReleaseState.UNKNOWN_REMOTE_OUTCOME)
    report=script.preflight(commands=commands,journal_path=journal.path)
    assert report['proposed_version']=='1.0.9'
    assert 'RELEASE_STATE_UNCERTAIN' in report['blocked_by']


def test_mock_publish_unknown_carry(tmp_path):
    from transcomic.release_pipeline import ReleaseCoordinator,FakeReleaseOperations
    journal=ReleaseJournal(tmp_path/'journal.json');coordinator=ReleaseCoordinator(journal)
    operations=FakeReleaseOperations();operations.unknown_publish=True
    with pytest.raises(UpdateError):coordinator.simulate(operations,current='1.0.8',build_id='first')
    assert journal.load()['version']=='1.0.9'
    published=coordinator.simulate(operations,current='1.0.8',build_id='first')
    assert published['version']=='1.0.9' and operations.calls.count('publish')==1
    operations.unknown_publish=False
    assert coordinator.simulate(operations,current='1.0.9',build_id='second')['version']=='1.1.0'


def test_updater_accepts_external_standard_semver():
    from test_updater_stage_a import fixture_release
    from transcomic.update.metadata import candidate,asset_url,release_url
    from transcomic.update.signing import sign_payload
    release,envelope,manifest,keys,data=fixture_release()
    # Keep the updater's signed external metadata path independent of release validation.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key=Ed25519PrivateKey.generate();version='1.0.100';tag='v'+version
    release['tag_name']=tag;release['html_url']=release_url(tag)
    name=f'TransComic-Setup-{version}-windows-x64.testdata'
    payload=envelope['payload'];payload.update(version=version,release_tag=tag,release_url=release_url(tag),installer_filename=name)
    for asset in release['assets']:
        if asset['name'].endswith('.testdata'):asset['name']=name
        asset['browser_download_url']=asset_url(tag,asset['name'])
    signed=sign_payload(payload,'external-test',key)
    result=candidate(release,signed,keys={'external-test':key.public_key().public_bytes_raw()},testing=True)
    assert result.version==version


def test_storage_policy(tmp_path,monkeypatch):
    from transcomic.update.keytools import production_storage
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    assert production_storage(tmp_path/'TransComicSigning'/'production')==tmp_path/'TransComicSigning'/'production'
    with pytest.raises(UpdateError):production_storage(tmp_path/'other')
    monkeypatch.setenv('OneDrive',str(tmp_path/'TransComicSigning'))
    with pytest.raises(UpdateError):production_storage(tmp_path/'TransComicSigning'/'production')


def test_latest_present_with_empty_list_is_uncertain(tmp_path):
    from scripts import release_transcomic as script
    from test_updater_stage_a import fake_commands
    def commands(args):
        if 'api' in args:return True,'HTTP/2.0 200 OK\n{}'
        return fake_commands(args)
    report=script.preflight(commands=commands,journal_path=tmp_path/'absent.json')
    assert report['latest_release_status']=='PRESENT_RECONCILIATION_REQUIRED'
    assert 'RELEASE_STATE_UNCERTAIN' in report['blocked_by']
