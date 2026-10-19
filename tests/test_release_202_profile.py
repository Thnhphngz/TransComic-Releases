"""All twelve explicit v2 gates remain mandatory and bound to reviewed bytes."""
import hashlib,json
import pytest
from scripts import first_internal_release as release
from transcomic.update.metadata import UpdateError


@pytest.fixture
def proof(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'ROOT',tmp_path);monkeypatch.setattr(release,'_AUTOMATIC_SCOPES',{})
    monkeypatch.setattr(release,'git',lambda *args:'a'*40)
    scope=release.automatic_scope('2.0.2');scope.out.mkdir(parents=True)
    (tmp_path/'source.py').write_bytes(b'fixture')
    (scope.out/'focused.xml').write_bytes(b'<testsuites><testsuite tests="1" failures="0" errors="0"/></testsuites>')
    (scope.out/'release-notes.md').write_bytes(b'fixture notes')
    data=dict(source_commit='a'*40,source_dirty=False,source_hashes={'source.py':hashlib.sha256(b'fixture').hexdigest()},
        test_evidence={'focused.xml':release.sha(scope.out/'focused.xml')},baseline_compatibility=True,
        privacy_findings=[],publication_notes_sha256=release.sha(scope.out/'release-notes.md'),version='2.0.2',
        gate_profile='workflow_202',release_gates={n:True for n in release.WORKFLOW_202_GATES})
    def save():(scope.out/'gates.json').write_text(json.dumps(data))
    save();return scope,data,save


def test_exact_authorized_contract(proof):
    scope,data,save=proof
    assert release.require_current_tests(scope)==data
    assert release.release_title(scope).startswith('TransComic v2.0.2')


@pytest.mark.parametrize('gate',release.WORKFLOW_202_GATES)
@pytest.mark.parametrize('value',[False,None])
def test_every_gate_is_mandatory(proof,gate,value):
    scope,data,save=proof
    if value is None:del data['release_gates'][gate]
    else:data['release_gates'][gate]=value
    save()
    with pytest.raises(UpdateError):release.require_current_tests(scope)


@pytest.mark.parametrize('problem',['source','notes','profile','version','privacy','baseline'])
def test_drift_blocks_publication(proof,problem):
    scope,data,save=proof
    if problem=='source':data['source_hashes']['source.py']='0'*64
    elif problem=='notes':(scope.out/'release-notes.md').write_bytes(b'changed')
    elif problem=='profile':data['gate_profile']='packaging_smoke_120'
    elif problem=='version':data['version']='1.2.0'
    elif problem=='privacy':data['privacy_findings']=['fixture finding']
    else:data['baseline_compatibility']=False
    save()
    with pytest.raises(UpdateError):release.require_current_tests(scope)
