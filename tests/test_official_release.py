"""Official version, exact scope, standalone guard and all thirteen gates."""
import json,sys
from types import SimpleNamespace
import pytest
from scripts.first_internal_release import (FirstReleaseCommands,OFFICIAL_SCOPE,FIRST_SCOPE,
    require_current_tests,ReleaseScope)
from scripts.official_release import GATE_NAMES
from transcomic.version import VERSION
from transcomic.update.metadata import UpdateError

def test_official_version_and_release_scope_are_fixed(tmp_path):
    assert VERSION=='1.0.0'
    c=FirstReleaseCommands(tmp_path/'gh.exe','a'*40,'b'*40,'c'*64,'notes',[],scope=OFFICIAL_SCOPE)
    assert not c.validate([c.gh,'api','repos/Thnhphngz/TransComic-Releases/releases/tags/v1.0.0','--include'])
    for tag in ('v0.1.1','v1.0.1','v2.0.0'):
        with pytest.raises(UpdateError):c.validate([c.gh,'api','repos/Thnhphngz/TransComic-Releases/git/refs',
            '--method','POST','-F','ref=refs/tags/'+tag,'-F','sha='+'b'*40])
    with pytest.raises(UpdateError):FirstReleaseCommands(tmp_path/'gh.exe','a'*40,'b'*40,'c'*64,'notes',[],
        scope=ReleaseScope('1.0.1','v1.0.1',tmp_path,()))

def test_previous_release_verifier_cannot_write(tmp_path):
    c=FirstReleaseCommands(tmp_path/'gh.exe','a'*40,'b'*40,'c'*64,'notes',[],read_only=True)
    with pytest.raises(UpdateError,match='READ_ONLY'):
        c([c.gh,'api','repos/Thnhphngz/TransComic-Releases/git/refs','--method','POST',
           '-F','ref=refs/tags/v0.1.1','-F','sha='+'b'*40],tmp_path)

@pytest.mark.parametrize('value',[False,None,'BLOCKED','UNKNOWN',1])
def test_every_official_gate_requires_literal_pass(monkeypatch,value):
    import scripts.first_internal_release as release
    proof={'source_commit':'a'*40,'source_dirty':False,'source_hashes':{},'test_evidence':{},
           'baseline_compatibility':True,'privacy_findings':[],'publication_notes_sha256':'digest',
           'release_gates':dict.fromkeys(GATE_NAMES,True)}
    proof['release_gates']['KIRA_GEMINI_VALIDATION_PASS']=value
    monkeypatch.setattr(release,'load',lambda p:proof)
    monkeypatch.setattr(release,'git',lambda *args:'a'*40)
    monkeypatch.setattr(release,'sha',lambda p:'digest')
    with pytest.raises(UpdateError,match='GATES_NOT_ALL_PASS'):require_current_tests(OFFICIAL_SCOPE)

def test_direct_exe_explains_installed_edition_without_handoff(tmp_path,monkeypatch):
    from test_first_local_build import window
    from test_two_laptop_update import installed_fixture
    from qt_wait import wait_until
    import transcomic.update.windows_helper as native
    app,w=window(tmp_path);p=w.update_panel;p.service=installed_fixture(tmp_path)
    p.item=p.service.check(True).candidate;p.downloaded_path=p.service.download(p.item)
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    def unavailable():raise UpdateError('NOT_INSTALLED')
    monkeypatch.setattr(native,'registered_installation',unavailable)
    calls=[];monkeypatch.setattr(native.HelperHandoff,'launch',lambda *a:calls.append(a))
    p.begin_native_install()
    assert wait_until(lambda:not p.busy and not p.handoff_pending,3000)
    assert not calls and not w._closed and 'EXE chạy trực tiếp' in p.status.text()
    assert not w._exit_pending and not p.download.isEnabled()
    w._exit_authorized=True;w.close();app.processEvents()


def test_native_dpapi_protects_fixture_keys_across_database_reopen(tmp_path):
    import os,uuid
    if os.name!='nt':pytest.skip('Native Windows DPAPI required')
    from transcomic.security import protect_key,unprotect_key
    from transcomic.storage import Store
    fake='TransComic-fixture-'+uuid.uuid4().hex
    encrypted=protect_key(fake)
    assert isinstance(encrypted,bytes) and fake.encode() not in encrypted
    store=Store(tmp_path/'dpapi-fixture.sqlite3')
    store.save_key(encrypted);store.add_gemini_keys(fake);store.close()
    reopened=Store(tmp_path/'dpapi-fixture.sqlite3')
    try:
        assert unprotect_key(reopened.load_key())==fake
        assert reopened.gemini_keys(decrypt=True)[0]['secret']==fake
        assert 'secret' not in reopened.gemini_keys(decrypt=False)[0]
        assert fake.encode() not in reopened.db.execute('SELECT encrypted FROM gemini_keys').fetchone()[0]
    finally:reopened.close()
