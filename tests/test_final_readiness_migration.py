"""Fault/crash injection on disposable SQLite fixtures, never production."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from transcomic.storage import Store
from test_kira_auto_recovery import fixture


def legacy(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=4)
    batch=store.batches(jobs[0])[0];store.job_state(jobs[0],'running');store.claim_batch(batch['id']);aid=store.prepare_attempt(batch['id'],1)
    store.finish_batch(batch['id'],{r['id']:'The accepted story continues' for r in batch['payload']},None,False,{},expected_attempt_id=aid)
    store.complete_attempt(aid,{'http_status':200});store.job_state(jobs[0],'finished')
    store.close();path=tmp_path/'synthetic.db';db=sqlite3.connect(path)
    db.executescript('''PRAGMA foreign_keys=OFF;
        CREATE TABLE old_attempts(id TEXT PRIMARY KEY,original_batch_id TEXT NOT NULL REFERENCES batches(id),attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 6),state TEXT NOT NULL,created_at TEXT NOT NULL,completed_at TEXT,diagnostics TEXT,reserved_tokens INTEGER NOT NULL DEFAULT 0,UNIQUE(original_batch_id,attempt_number));
        INSERT INTO old_attempts SELECT * FROM request_attempts;DROP TABLE request_attempts;ALTER TABLE old_attempts RENAME TO request_attempts;
        CREATE INDEX retained_index ON request_attempts(created_at);''')
    before={table:db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall() for table in ('request_attempts','api_text_versions','lines','jobs','batches','kira_keys','translation_runs')}
    db.close();return path,before


def preserved(path,before,*,old=False):
    db=sqlite3.connect(path)
    try:
        for table,rows in before.items():assert db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()==rows,table
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='attempts_v7'").fetchone()
        sql=db.execute("SELECT sql FROM sqlite_master WHERE name='request_attempts'").fetchone()[0]
        assert ('BETWEEN 1 AND 6' in sql) if old else ('attempt_number>=1' in sql)
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='retained_index'").fetchone()
    finally:db.close()


@pytest.mark.parametrize('step',['CREATE TABLE attempts_v7','INSERT INTO attempts_v7','DROP TABLE request_attempts','ALTER TABLE attempts_v7'])
def test_attempt_migration_failure_rolls_back_all_history(tmp_path,monkeypatch,step):
    path,before=legacy(tmp_path);original=sqlite3.connect
    class Fault(sqlite3.Connection):
        def execute(self,sql,*args):
            if sql.startswith(step):raise sqlite3.OperationalError('Injected disposable migration fault')
            return super().execute(sql,*args)
    with monkeypatch.context() as patch:
        patch.setattr(sqlite3,'connect',lambda *a,**kw:original(*a,**kw,factory=Fault))
        with pytest.raises(sqlite3.OperationalError):Store(path)
    preserved(path,before,old=True)
    store=Store(path);store.close();preserved(path,before)


@pytest.mark.parametrize('step',['INSERT INTO attempts_v7','DROP TABLE request_attempts','ALTER TABLE attempts_v7'])
def test_process_exit_during_migration_recovers_old_schema_then_reopens(tmp_path,step):
    path,before=legacy(tmp_path)
    code='''import os,sqlite3,sys
from transcomic.storage import Store
original=sqlite3.connect
class Crash(sqlite3.Connection):
 def execute(self,sql,*args):
  result=super().execute(sql,*args)
  if sql.startswith(sys.argv[2]):os._exit(73)
  return result
sqlite3.connect=lambda *a,**kw:original(*a,**kw,factory=Crash)
Store(sys.argv[1])
'''
    result=subprocess.run([sys.executable,'-c',code,str(path),step],capture_output=True,timeout=15)
    assert result.returncode==73,result.stderr
    preserved(path,before,old=True)
    for _ in range(2):
        store=Store(path);store.close();preserved(path,before)


def test_attempt_seven_cannot_be_copied_back_into_legacy_constraint(tmp_path):
    path,before=legacy(tmp_path);store=Store(path);store.close()
    db=sqlite3.connect(path,isolation_level=None)
    try:
        row=db.execute('SELECT * FROM request_attempts').fetchone();new=list(row);new[0]='synthetic-seventh-attempt';new[2]=7
        db.execute('INSERT INTO request_attempts VALUES (?,?,?,?,?,?,?,?)',new)
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE downgrade_copy AS SELECT * FROM request_attempts WHERE 0')
        db.execute('DROP TABLE downgrade_copy')
        db.execute('CREATE TABLE downgrade_copy(id TEXT,original_batch_id TEXT,attempt_number INTEGER CHECK(attempt_number BETWEEN 1 AND 6),state TEXT,created_at TEXT,completed_at TEXT,diagnostics TEXT,reserved_tokens INTEGER)')
        with pytest.raises(sqlite3.IntegrityError):db.execute('INSERT INTO downgrade_copy SELECT * FROM request_attempts')
        db.execute('ROLLBACK')
        assert db.execute('SELECT COUNT(*) FROM request_attempts WHERE attempt_number=7').fetchone()[0]==1
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    finally:db.close()


def test_legacy_tts_records_survive_history_flag_migration_and_reopen(tmp_path):
    from transcomic.tts.storage import TtsStore
    path=tmp_path/'legacy-tts.sqlite3';store=TtsStore(path);run=store.draft()
    doc=store.add_document(run,dict(name='Synthetic',path=None,text='One\nTwo',line_count=2))
    store.execute("UPDATE runs SET state='completed',started=1,ended=2 WHERE id=?",(run,))
    store.execute("UPDATE segments SET state='success',sha256='synthetic-pcm-digest',duration=0.1,rate=24000,backend='fixture' WHERE document_id=?",(doc,))
    segments=store.items(run);documents=store.docs(run);store.close()
    db=sqlite3.connect(path);db.execute('ALTER TABLE runs DROP COLUMN history_accepted');db.commit();db.close()
    for _ in range(2):
        store=TtsStore(path)
        try:
            assert store.items(run)==segments and store.docs(run)==documents
            assert store.run(run)['state']=='completed' and store.run(run)['history_accepted']==1
            assert store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
        finally:store.close()


def test_two_concurrent_migration_openers_do_not_duplicate_or_lose_records(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    path,before=legacy(tmp_path);gate=threading.Barrier(2)
    def open_store():
        gate.wait(timeout=5);store=Store(path)
        try:assert store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        finally:store.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks=[pool.submit(open_store) for _ in range(2)]
        for task in tasks:task.result(timeout=12)
    preserved(path,before)
