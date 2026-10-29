"""Release 2.0.3 input/backup checks on synthetic, disposable databases."""
import hashlib
import json
import sqlite3

import pytest

from scripts.release_source import allowed
from test_final_readiness_migration import legacy,preserved
from transcomic.storage import Store
from transcomic.tts.storage import TtsStore
from transcomic.update import backup
from test_automation_ui import gui,wait


def test_only_the_reviewed_synthetic_json_fixture_is_allowed():
    assert allowed('tests/fixtures/deepseek_synthetic_root_type.json')
    for name in ('tests/fixtures/deepseek_root_type.json','tests/fixtures/private.json','tests/fixtures/../private.json'):
        assert not allowed(name)


def test_migration_backs_up_both_databases_before_rebuild_and_only_once(tmp_path):
    path,before=legacy(tmp_path)
    tts_path=tmp_path/'TTS/tts.sqlite3';tts=TtsStore(tts_path);run=tts.draft()
    doc=tts.add_document(run,dict(name='Synthetic',path=None,text='A preserved sentence',line_count=1))
    items=tts.items(run);tts.close()
    store=Store(path);receipt=store.migration_backup;store.close();preserved(path,before)
    manifest=json.loads(receipt.read_text(encoding='utf8'))
    assert {r['kind'] for r in manifest['databases'] if r['present']}=={'translation','tts'}
    for record in manifest['databases']:
        file=receipt.parent/record['file']
        assert hashlib.sha256(file.read_bytes()).hexdigest()==record['sha256']
        db=sqlite3.connect(file)
        try:
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
            if record['kind']=='translation':
                assert 'BETWEEN 1 AND 6' in db.execute("SELECT sql FROM sqlite_master WHERE name='request_attempts'").fetchone()[0]
                for table,rows in before.items():assert db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()==rows
            else:assert db.execute('SELECT COUNT(*) FROM segments').fetchone()[0]==len(items)
        finally:db.close()
    again=Store(path);assert again.migration_backup is None;again.close()
    assert len(list((tmp_path/'Backups').glob('*/manifest.json')))==1


@pytest.mark.parametrize('failed_kind',['translation','tts'])
def test_backup_failure_never_opens_migration_writer(tmp_path,monkeypatch,failed_kind):
    path,before=legacy(tmp_path);tts=TtsStore(tmp_path/'TTS/tts.sqlite3');tts.close();original=backup.consistent_backup
    def fail(source,destination,**kw):
        if destination.name==failed_kind+'.sqlite3':raise OSError('Synthetic backup failure')
        return original(source,destination,**kw)
    monkeypatch.setattr(backup,'consistent_backup',fail)
    with pytest.raises(OSError):Store(path)
    preserved(path,before,old=True)
    assert not list((tmp_path/'Backups').glob('*/manifest.json'))


def test_backup_rejects_foreign_key_damage(tmp_path):
    source=tmp_path/'invalid.sqlite3';db=sqlite3.connect(source)
    db.executescript('CREATE TABLE parent(id INTEGER PRIMARY KEY); CREATE TABLE child(parent_id REFERENCES parent(id)); INSERT INTO child VALUES (123);');db.close()
    with pytest.raises(Exception,match='foreign key'):backup.consistent_backup(source,tmp_path/'copy.sqlite3')
    assert not (tmp_path/'copy.sqlite3').exists()


@pytest.mark.parametrize('empty_keys',[False,True])
def test_frozen_probe(gui,tmp_path,empty_keys):
    from transcomic.release_smoke_203 import verify_admission
    app,window,page,wid=gui
    if empty_keys:window.store.db.execute('DELETE FROM kira_keys')
    result=verify_admission(window,tmp_path,lambda condition,seconds=8:wait(app,condition,seconds))
    assert result['kira']['completion_opens_next']=='nine of ten'
    assert result['deepseek']['completion_opens_next']=='one file'
    assert all(case['passed'] and case['duplicate_row_sends']==0 for case in result.values())
