"""Real-path post-publication staging and GET-only recovery regression."""
import json,os,sys
from pathlib import Path
import httpx
import pytest
from scripts import automatic_release as auto
from scripts import release_package as package
from transcomic.update.metadata import UpdateError
from transcomic.update.service import UpdateService
from transcomic.release_journal import ReleaseState
from test_automatic_release import project,change,git

def test_verification_staging_outside_actual_source_and_program():
    with auto.verification_staging(auto.ROOT) as directory:
        service=UpdateService(directory=directory/'Updates')
        assert not service.directory.is_relative_to(auto.ROOT)
        assert not service.directory.is_relative_to(Path(sys.executable).resolve().parent)
        assert directory.exists()

def test_source_and_simulated_program_directories_remain_rejected(tmp_path,monkeypatch):
    import transcomic.update.service as service
    with pytest.raises(UpdateError,match='outside source/program'):
        UpdateService(directory=auto.ROOT/'artifacts/automatic-release/test/anonymous')
    program=tmp_path/'program';program.mkdir()
    monkeypatch.setattr(service,'__file__',str(program/'transcomic/update/service.py'))
    with pytest.raises(UpdateError,match='outside source/program'):UpdateService(directory=program/'cache')
    with auto.verification_staging(auto.ROOT) as directory:UpdateService(directory=directory/'Updates')

def test_post_publish_failure_reports_public_release_and_exit_two(project,monkeypatch,capsys):
    root,runtime,system=project;change(root);runtime.public_ok=False
    monkeypatch.setattr(auto,'Runtime',lambda:runtime)
    assert auto.main([])==2
    output=capsys.readouterr().out
    assert 'PUBLISHED — POST-VERIFICATION INCOMPLETE' in output
    assert 'RELEASE BLOCKED:' not in output and 'RELEASE STOPPED' not in output
    record=system.journal.load()
    assert record['state']=='PUBLISHED' and not record['post_publication_verified']
    assert record['workflow_status']=='PUBLISHED — POST-VERIFICATION INCOMPLETE'

def test_published_recovery_after_verifier_code_change_never_builds_or_writes(project,monkeypatch,capsys):
    root,runtime,system=project;change(root);runtime.public_ok=False
    with pytest.raises(auto.PublishedVerificationIncomplete):system.run('auto')
    old=system.journal.load();counts=list(runtime.events)
    # Fix release verification code after the old payload has already shipped.
    (root/'transcomic/app.py').write_text('x = 3\n')
    runtime.public_ok=True
    recovered=system.run('recover-published')
    assert recovered['version']=='1.0.1' and recovered['post_publication_verified'] is True
    assert recovered['source_commit']==old['source_commit']
    assert runtime.events.count('publish')==1 and runtime.events.count('build')==1
    assert 'verify_recovery_inputs' in runtime.events[len(counts):]
    assert recovered['post_verification_history'][0]['read_only_github'] is True
    assert 'RELEASE PUBLISHED AND VERIFIED' in capsys.readouterr().out
    assert system.run('check')['version']=='1.0.2'  # Fix belongs to next payload, never relabel the old source.

def test_automatic_resume_public_remote_only_reconciles_and_does_not_duplicate(project,capsys):
    root,runtime,system=project;change(root);runtime.public_ok=False
    with pytest.raises(UpdateError):system.run('auto')
    runtime.public_ok=True;result=system.run('auto')
    assert result['post_publication_verified'] and runtime.events.count('publish')==1
    assert runtime.events.count('build')==1 and result['version']=='1.0.1'
    system.run('auto')
    assert runtime.events.count('publish')==1 and 'NO RELEASEABLE CHANGES' in capsys.readouterr().out

def test_interrupted_journal_with_remote_published_is_reconciled(project):
    root,runtime,system=project;change(root);runtime.public_ok=False
    with pytest.raises(UpdateError):system.run('auto')
    record=system.journal.load()
    record.update(state=ReleaseState.UNKNOWN_REMOTE_OUTCOME,last_completed=ReleaseState.REMOTE_VERIFIED)
    system.save(record);runtime.public_ok=True
    result=system.run('recover-published')
    assert result['state']=='PUBLISHED' and result['post_publication_verified']
    assert runtime.events.count('publish')==1 and runtime.events.count('build')==1

def test_recovery_without_authentic_evidence_never_marks_verified(project):
    root,runtime,system=project;change(root);runtime.public_ok=False
    with pytest.raises(UpdateError):system.run('auto')
    def rejected(record):raise UpdateError('REMOTE_DOWNLOADED_HASH_MISMATCH')
    runtime.verify_previous=rejected
    with pytest.raises(auto.PublishedVerificationIncomplete,match='HASH_MISMATCH'):system.run('recover-published')
    result=system.journal.load()
    assert result['state']=='PUBLISHED' and result['post_publication_verified'] is False
    assert runtime.events.count('publish')==1

def test_expected_version_bounds_mutations_and_never_starts_another_version(project):
    root,runtime,system=project;change(root)
    journal=system.journal.path.read_bytes();head=git(root,'rev-parse','HEAD')
    with pytest.raises(UpdateError,match='EXPECTED_VERSION_MISMATCH'):system.run('auto',expected_version='1.0.2')
    assert system.journal.path.read_bytes()==journal and git(root,'rev-parse','HEAD')==head and 'build' not in runtime.events
    record=system.run('auto',expected_version='1.0.1')
    assert record['version']=='1.0.1' and runtime.events.count('publish')==1

def test_real_verifier_with_work_inside_source_uses_external_cache(project,monkeypatch):
    import transcomic.update.service as service_module
    from transcomic.update.metadata import release_url,asset_url
    root,runtime,system=project;change(root);record=system.run('build-only');work=root/record['work']
    # Match real deployment: work is under the very source root guarded by UpdateService.
    monkeypatch.setattr(service_module,'__file__',str(root/'transcomic/update/service.py'))
    with pytest.raises(UpdateError,match='outside source/program'):UpdateService(directory=work/'anonymous')
    folder=root/'releases'/record['version'];names=package.names(record['version'])
    release={'id':7,'tag_name':'v1.0.1','draft':False,'prerelease':False,'html_url':release_url('v1.0.1'),'published_at':'2026-10-15T00:00:00Z',
        'assets':[{'name':n,'size':(folder/n).stat().st_size,'state':'uploaded','browser_download_url':asset_url('v1.0.1',n)} for n in names]}
    probes=[];directories=[];original=httpx.Client;initialize=UpdateService.__init__
    def checked(self,directory,*args,**kwargs):
        directories.append(Path(directory));return initialize(self,directory,*args,**kwargs)
    monkeypatch.setattr(UpdateService,'__init__',checked)
    def response(request):
        if request.url.host=='api.github.com':return httpx.Response(200,json=release)
        return httpx.Response(200,content=(folder/request.url.path.rsplit('/',1)[-1]).read_bytes())
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:original(transport=httpx.MockTransport(response),**kwargs))
    runtime.baseline=lambda previous:root/'baseline.exe'
    runtime.probe=lambda *args:probes.append(True)
    auto.Runtime.verify_public(runtime,record,work)
    assert probes==[True] and directories and all(not d.is_relative_to(root) for d in directories)
    assert package.load(work/'public-verification-staging.json')['outside_source']
