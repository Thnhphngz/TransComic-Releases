"""No network or release side effects: verify the one-release activation boundary."""
from pathlib import Path
import pytest
from scripts.first_internal_release import (FirstReleaseCommands,FirstReleaseCoordinator,
    identity_in_notes,REPO,TAG,ROOT)
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
