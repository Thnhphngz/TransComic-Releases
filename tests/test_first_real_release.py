"""No network or release side effects: verify the one-release activation boundary."""
from pathlib import Path
import pytest
from scripts.first_internal_release import (FirstReleaseCommands,FirstReleaseCoordinator,
    identity_in_notes,draft_validation_identity,REPO,TAG,ROOT,NAMES)
from transcomic.update.metadata import UpdateError
from transcomic.release_pipeline import FakeReleaseOperations,ReleaseCoordinator
from transcomic.release_journal import ReleaseJournal


def commands(tmp_path):
    return FirstReleaseCommands(tmp_path/'gh.exe','a'*40,'b'*40,'c'*64,
                                '<!-- transcomic-build-id: '+'c'*64+' -->',[])


@pytest.mark.parametrize('endpoint,tail',[
    ('repos/'+REPO+'/releases/tags/v0.1.2',['--include']),
    ('repos/other/repo/releases/tags/'+TAG,['--include']),
    ('repos/'+REPO+'/releases/1',['--method','DELETE']),
    ('repos/'+REPO+'/contents/source.py',['--method','PUT']),
    ('repos/'+REPO+'/git/refs',['--method','POST','-F','ref=refs/tags/v0.1.2','-F','sha='+'b'*40]),
    ('repos/'+REPO+'/releases/1',['--method','PATCH','-F','draft=false']),
    ('repos/'+REPO+'/releases/assets/1',['-H','Accept: application/octet-stream']),
])
def test_first_release_scope_rejects_other_writes_and_unbound_ids(tmp_path,endpoint,tail):
    c=commands(tmp_path)
    with pytest.raises(UpdateError):c.validate([c.gh,'api',endpoint,*tail])


def test_first_release_scope_only_bound_tag_and_publish(tmp_path):
    c=commands(tmp_path)
    assert not c.validate([c.gh,'api','repos/'+REPO+'/releases/tags/'+TAG,'--include'])
    assert c.validate([c.gh,'api','repos/'+REPO+'/git/refs','--method','POST',
                       '-F','ref=refs/tags/'+TAG,'-F','sha='+'b'*40])
    c.release_id=42
    assert c.validate([c.gh,'api','repos/'+REPO+'/releases/42','--method','PATCH','-F','draft=false'])


def test_first_release_does_not_accept_shell_or_alternative_program(tmp_path):
    c=commands(tmp_path)
    for argv in (['cmd','/c','echo'],[c.gh,'release','create',TAG],['git','push']):
        with pytest.raises(UpdateError):c.validate(argv)


def test_first_release_cannot_use_fake_or_generic_unlock(tmp_path):
    journal=ReleaseJournal(tmp_path/'journal.json')
    with pytest.raises(UpdateError):FirstReleaseCoordinator(journal).run(FakeReleaseOperations())
    with pytest.raises(UpdateError):ReleaseCoordinator(journal).run(FakeReleaseOperations())
    assert not journal.path.exists()


@pytest.mark.parametrize('notes',['', '<!-- transcomic-build-id: invalid -->',
    '<!-- transcomic-build-id: '+'c'*64+' -->\n<!-- transcomic-build-id: '+'c'*64+' -->'])
def test_release_notes_need_exactly_one_build_identity(notes):
    with pytest.raises(UpdateError):identity_in_notes(notes)


def draft(c):
    return {'id':42,'url':'https://api.github.com/repos/'+REPO+'/releases/42',
            'html_url':'https://github.com/'+REPO+'/releases/tag/untagged-123abc',
            'tag_name':TAG,'target_commitish':c.distribution,'body':c.notes,'draft':True,
            'prerelease':False,'assets':[]}


def test_authenticated_draft_identity_allows_untagged_web_url_but_not_after_publish(tmp_path):
    c=commands(tmp_path);release=draft(c)
    c.bind_release(release);assert c.release_id==42
    release['draft']=False
    with pytest.raises(UpdateError):c.bind_release(release)


@pytest.mark.parametrize('field,value',[
    ('tag_name','v0.1.2'),('id',43),('target_commitish','d'*40),
    ('url','https://api.github.com/repos/other/repo/releases/42'),
    ('html_url','https://github.com/other/repo/releases/tag/untagged-123abc'),
    ('prerelease',True),('body','changed notes'),
])
def test_draft_identity_rejects_conflicts(tmp_path,field,value):
    c=commands(tmp_path);release=draft(c);c.bind_release(release)
    release[field]=value
    with pytest.raises(UpdateError):c.bind_release(release)


def test_draft_future_schema_urls_do_not_change_raw_remote_or_published_urls(tmp_path):
    c=commands(tmp_path);release=draft(c)
    url='https://github.com/'+REPO+'/releases/download/untagged-123abc/'+NAMES[0]
    release['assets']=[{'name':NAMES[0],'id':7,'browser_download_url':url}]
    checked=draft_validation_identity(release)
    assert checked['assets'][0]['browser_download_url'].endswith('/'+TAG+'/'+NAMES[0])
    assert release['assets'][0]['browser_download_url']==url
    release['draft']=False
    assert draft_validation_identity(release) is release


def test_draft_asset_url_cannot_leave_repository(tmp_path):
    release=draft(commands(tmp_path))
    release['assets']=[{'name':NAMES[0],'browser_download_url':'https://example.com/'+NAMES[0]}]
    with pytest.raises(UpdateError):draft_validation_identity(release)
