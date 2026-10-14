"""Recoverability and no-follow boundaries of the authorized test archive."""
import json
import os
from pathlib import Path
import pytest
from scripts import archive_pytest_outputs as archive

def test_snapshot_preserves_only_internal_pytest_alias(tmp_path):
    source=tmp_path/'source';source.mkdir();target=source/'test_fixture0';target.mkdir();(target/'book.txt').write_text('fixture')
    alias=source/'test_fixturecurrent';alias.symlink_to(target,target_is_directory=True)
    contents=archive.snapshot(source)
    assert contents['files'][0]['path']=='test_fixture0/book.txt' and len(contents['files'])==1
    assert contents['links']==[{'path':'test_fixturecurrent','target':os.readlink(alias)}]
    alias.unlink();alias.symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError,match='external alias'):archive.snapshot(source)

def plan(root):
    source=root/'.pytest_old';source.mkdir();(source/'book.txt').write_text('generated fixture')
    return {'git_before':{'head':'fixture'},'directories':[{'path':source.name,'classification':'B','created_at':'fixture',
      'reason':'test output','inventory':archive.snapshot(source)}]}

def setup(tmp_path,monkeypatch):
    root=tmp_path/'workspace';root.mkdir();monkeypatch.setattr(archive,'ROOT',root)
    monkeypatch.setattr(archive,'active_work',lambda:[]);monkeypatch.setattr(archive,'source_state',lambda:{'head':'fixture'})
    monkeypatch.setattr(archive,'idle',lambda:None)
    monkeypatch.setattr(archive,'git',lambda args:'')
    return root

def test_archive_keeps_verified_copy_original_and_restore_proof(tmp_path,monkeypatch):
    root=setup(tmp_path,monkeypatch);request=plan(root);result=archive.archive(request,tmp_path/'outside')
    entry=result['entries'][0]
    assert entry['state']=='moved_verified' and not (root/'.pytest_old').exists()
    for key in ('verified_copy','archived_path'):
        assert archive.snapshot(Path(entry[key]),root/'.pytest_old')==request['directories'][0]['inventory']
    assert result['restore_test']['hash_verified'] and result['source_preserved']
    assert json.loads((Path(result['archive'])/'manifest.json').read_text())['entries'][0]['state']=='moved_verified'

def test_changed_source_retained_without_copy_or_move(tmp_path,monkeypatch):
    root=setup(tmp_path,monkeypatch);request=plan(root);(root/'.pytest_old/book.txt').write_text('changed')
    result=archive.archive(request,tmp_path/'outside');entry=result['entries'][0]
    assert entry['state']=='error' and (root/'.pytest_old/book.txt').read_text()=='changed'
    assert not Path(entry['archived_path']).exists()

def test_archive_rejects_destination_inside_workspace(tmp_path,monkeypatch):
    root=setup(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='outside workspace'):archive.archive(plan(root),root/'archive')

def test_native_junction_copy_does_not_follow_or_change_target(tmp_path):
    import subprocess
    source=tmp_path/'source';target=source/'test_directory_junction_loop_d0/chapters';target.mkdir(parents=True)
    sentinel=target/'one.txt';sentinel.write_bytes(b'fixture target unchanged')
    link=target/'loop'
    result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(target)],capture_output=True)
    assert result.returncode==0
    native=archive.read_reparse(link,exclusive=True)
    assert native['tag']==0xA0000003 and link.lstat().st_ino!=target.lstat().st_ino
    before=archive.snapshot(source);backup=tmp_path/'backup'
    archive.copy_no_follow(source,backup,before)
    assert archive.snapshot(backup,source)==before
    assert len(before['files'])==1 and sentinel.read_bytes()==b'fixture target unchanged'
    assert archive.read_reparse(backup/'test_directory_junction_loop_d0/chapters/loop')['raw_hex']==native['raw_hex']

def test_native_external_junction_is_rejected_target_untouched(tmp_path):
    import subprocess
    source=tmp_path/'source';link=source/'test_directory_junction_loop_d0/chapters/loop';link.parent.mkdir(parents=True)
    target=tmp_path/'external';target.mkdir();sentinel=target/'keep.txt';sentinel.write_bytes(b'keep')
    result=subprocess.run(['cmd','/c','mklink','/J',str(link),str(target)],capture_output=True)
    assert result.returncode==0
    with pytest.raises(ValueError,match='Unverified junction target'):archive.snapshot(source)
    assert sentinel.read_bytes()==b'keep' and link.exists()
