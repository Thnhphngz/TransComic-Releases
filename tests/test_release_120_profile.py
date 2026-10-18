"""The explicit short release contract cannot bypass a failed required gate."""
import hashlib,json
import pytest
from scripts import first_internal_release as release
from transcomic.update.metadata import UpdateError


@pytest.fixture
def proof(tmp_path,monkeypatch):
    monkeypatch.setattr(release,'ROOT',tmp_path)
    monkeypatch.setattr(release,'_AUTOMATIC_SCOPES',{})
    monkeypatch.setattr(release,'git',lambda *args:'a'*40)
    scope=release.automatic_scope('1.2.0');scope.out.mkdir(parents=True)
    (tmp_path/'source.py').write_bytes(b'fixture')
    (scope.out/'focused.xml').write_bytes(b'<testsuites><testsuite tests="1" failures="0" errors="0"/></testsuites>')
    (scope.out/'release-notes.md').write_bytes(b'fixture notes')
    data=dict(source_commit='a'*40,source_dirty=False,source_hashes={'source.py':hashlib.sha256(b'fixture').hexdigest()},
              test_evidence={'focused.xml':release.sha(scope.out/'focused.xml')},baseline_compatibility=True,
              privacy_findings=[],publication_notes_sha256=release.sha(scope.out/'release-notes.md'),
              gate_profile='packaging_smoke_120',version='1.2.0',prior_regression_accepted_by_user=True,
              release_gates={name:True for name in release.PACKAGING_120_GATES})
    def save(): (scope.out/'gates.json').write_text(json.dumps(data))
    save();return scope,data,save


def test_explicit_user_contract_passes(proof):
    scope,data,save=proof
    assert release.require_current_tests(scope)==data


@pytest.mark.parametrize('problem',['failed_gate','missing_gate','missing_acceptance','source_changed'])
def test_short_contract_still_blocks_unverified_release(proof,problem):
    scope,data,save=proof
    if problem=='failed_gate':data['release_gates']['MUTAGEN_PASS']=False
    elif problem=='missing_gate':del data['release_gates']['PORTABLE_MAU_PASS']
    elif problem=='missing_acceptance':data['prior_regression_accepted_by_user']=False
    else:data['source_hashes']['source.py']='0'*64
    save()
    with pytest.raises(UpdateError):release.require_current_tests(scope)
