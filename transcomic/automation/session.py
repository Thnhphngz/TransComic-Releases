"""Disposable Automation state. Durable manuscripts, audit and outputs survive.

Old sessions are hidden by indexed session scope before cleanup starts. Cleanup
uses its own connections, one workset per transaction, and can be retried after
process death. It never opens source documents or walks output directories.
"""
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import uuid

SCHEMA = '''
CREATE TABLE IF NOT EXISTS automation_sessions(
 id TEXT PRIMARY KEY, owner_pid INTEGER, owner_started REAL, state TEXT NOT NULL,
 created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS automation_history(
 workset_id TEXT PRIMARY KEY, name TEXT NOT NULL, created REAL NOT NULL,
 summary TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS automation_history_events(
 id INTEGER NOT NULL, workset_id TEXT NOT NULL, group_id TEXT, created REAL NOT NULL,
 stage TEXT NOT NULL, message TEXT NOT NULL, PRIMARY KEY(workset_id,id));
CREATE TABLE IF NOT EXISTS automation_staging(
 session_id TEXT NOT NULL, path TEXT PRIMARY KEY, root TEXT NOT NULL, kind TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS automation_staging_session ON automation_staging(session_id);
CREATE INDEX IF NOT EXISTS automation_groups_workset ON automation_groups(workset_id);
CREATE INDEX IF NOT EXISTS automation_groups_tts ON automation_groups(json_extract(data,'$.tts_run'));
CREATE INDEX IF NOT EXISTS automation_events_workset ON automation_events(workset_id);
CREATE INDEX IF NOT EXISTS automation_artifacts_workset ON automation_artifacts(workset_id);
CREATE INDEX IF NOT EXISTS automation_jobs_owner ON jobs(json_extract(config,'$.automation_owner'));
CREATE INDEX IF NOT EXISTS automation_sessions_state ON automation_sessions(state);
'''


def path_identity(path):
    text=str(Path(path).resolve())
    if text.startswith('\\\\?\\UNC\\'):text='\\\\'+text[8:]
    elif text.startswith('\\\\?\\'):text=text[4:]
    return os.path.normcase(text)


def initialize(store):
    import psutil
    sid = str(uuid.uuid4())
    with store.transaction():
        if 'session_id' not in {r[1] for r in store.db.execute('PRAGMA table_info(automation_worksets)')}:
            store.db.execute("ALTER TABLE automation_worksets ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
        store.db.execute('CREATE INDEX IF NOT EXISTS automation_worksets_session ON automation_worksets(session_id,created)')
        # A legacy running checkpoint must never block a fresh session's Start.
        store.db.execute('DROP INDEX IF EXISTS automation_one_active')
        store.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS automation_session_active ON automation_worksets(session_id) WHERE state IN ('running','stopping')")
    with store.lock:store.db.executescript(SCHEMA)
    store.db.execute('INSERT INTO automation_sessions VALUES (?,?,?,?,?)',
                     (sid, os.getpid(), psutil.Process().create_time(), 'open', time.time()))
    return sid


def archive(db, wid):
    """Keep completed work only, without resumable checkpoints or manifests."""
    work = db.execute('SELECT id,name,state,created,checkpoint FROM automation_worksets WHERE id=?', (wid,)).fetchone()
    if not work:return
    groups = [dict(r) for r in db.execute("""SELECT g.id,g.document_id,g.position,d.path,
        json_extract(g.data,'$.tts_run') tts_run,json_extract(g.data,'$.project') project,
        json_extract(g.data,'$.audio_folder') audio_folder FROM automation_groups g
        JOIN documents d ON d.id=g.document_id WHERE g.workset_id=?
        AND json_extract(g.data,'$.state')='completed' ORDER BY g.position,g.id""", (wid,))]
    artifacts = [dict(r) for r in db.execute("SELECT kind,unit,path,sha256 FROM automation_artifacts WHERE workset_id=? AND state='complete'", (wid,))]
    if work['state'] != 'completed' and not groups and not artifacts:return
    cp = json.loads(work['checkpoint'])
    data = dict(state=work['state'], groups=groups, artifacts=artifacts, reports=cp.get('reports'), ended=cp.get('ended'))
    db.execute('INSERT OR REPLACE INTO automation_history VALUES (?,?,?,?)',
               (wid,work['name'],work['created'],json.dumps(data,ensure_ascii=False)))
    db.execute("""INSERT OR IGNORE INTO automation_history_events SELECT e.* FROM automation_events e
        WHERE e.workset_id=? AND (?='completed' OR e.group_id IN
        (SELECT id FROM automation_groups WHERE workset_id=? AND json_extract(data,'$.state')='completed'))""",(wid,work['state'],wid))


def _connection(path):
    db = sqlite3.connect(path, timeout=5, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def _retire_tts(tts, run):
    # Idempotent across the two databases; commit TTS before deleting its link.
    tts.execute('BEGIN IMMEDIATE')
    try:
        tts.execute("UPDATE runs SET state=CASE WHEN state IN ('completed','failed','cancelled') THEN state ELSE 'cancelled' END, ended=COALESCE(ended,?), config=json_set(config,'$.automation_discarded',1) WHERE id=?", (time.time(),run))
        tts.execute("UPDATE segments SET state='cancelled',attempt=NULL,error='' WHERE state!='success' AND document_id IN (SELECT id FROM documents WHERE run_id=?)", (run,))
        tts.commit()
    except BaseException:tts.rollback();raise


def _retire_jobs(db, wid):
    # Request/QA/accepted-text audit is permanent; pending assignment is not.
    db.execute("""UPDATE batches SET state='discarded' WHERE state!='done' AND job_id IN
        (SELECT id FROM jobs WHERE json_extract(config,'$.automation_owner')=?)""", (wid,))
    db.execute("""UPDATE request_attempts SET state='unknown' WHERE state!='finished' AND
        original_batch_id IN (SELECT b.id FROM batches b JOIN jobs j ON j.id=b.job_id
        WHERE json_extract(j.config,'$.automation_owner')=?)""", (wid,))
    db.execute("""UPDATE jobs SET state=CASE WHEN state='finished' THEN state ELSE 'cancelled' END,
        config=json_set(json_remove(config,'$.automation_boundaries'),'$.automation_discarded',1)
        WHERE json_extract(config,'$.automation_owner')=?""", (wid,))


def _remove_staging(row):
    path, root = Path(row['path']), Path(row['root'])
    # Only a registered direct child, never a source/output directory or link.
    if path.is_symlink() or getattr(path,'is_junction',lambda:False)():return False
    if path_identity(path.parent)!=path_identity(root) or path_identity(path)==path_identity(root):return False
    if not path.exists():return True
    if row['kind']=='audio-part' and path.is_file() and re.fullmatch(r'[0-9a-f-]{36}\.[0-9a-f-]{36}\.part',path.name):
        path.unlink();return True
    if row['kind']=='capcut-stage' and path.is_dir() and re.fullmatch(r'\.transcomic-capcut-[0-9a-f]{32}',path.name):
        for parent, dirs, files in os.walk(path, followlinks=False):
            if any((Path(parent)/n).is_symlink() or getattr(Path(parent)/n,'is_junction',lambda:False)() for n in dirs+files):return False
        shutil.rmtree(path);return True
    return False


class Cleanup:
    def __init__(self, repo, tts_path, *, current=False):
        self.repo=repo;self.tts_path=tts_path;self.current=current;self.error=None
        self.done=threading.Event();self.worksets=0;self.preserved_staging=[]
        self.elapsed_seconds=0
        self.thread=threading.Thread(target=self.run,daemon=True,name='AutomationSessionCleanup')
    def start(self):self.thread.start();return self
    def run(self):
        db=tts=None;started=time.perf_counter()
        try:
            db=_connection(self.repo.store.path);tts=_connection(self.tts_path)
            if self.current:
                db.execute("UPDATE automation_sessions SET state='discarding' WHERE id=?",(self.repo.session_id,))
                candidates=[self.repo.session_id]
            else:
                import psutil
                candidates=['']  # Pre-session releases: metadata only, no restoration.
                for row in db.execute('SELECT * FROM automation_sessions WHERE id!=? AND state!=?',(self.repo.session_id,'closed')):
                    alive=False
                    try:alive=abs(psutil.Process(row['owner_pid']).create_time()-row['owner_started'])<.1
                    except psutil.AccessDenied:alive=True
                    except (psutil.Error,TypeError,ValueError):pass
                    if not alive or row['state']=='discarding':candidates.append(row['id'])
            for sid in candidates:
                # Never clean another live session or the new session on startup.
                while True:
                    row=db.execute('SELECT id FROM automation_worksets WHERE session_id=? LIMIT 1',(sid,)).fetchone()
                    if not row:break
                    wid=row['id']
                    for run in db.execute("SELECT DISTINCT json_extract(data,'$.tts_run') FROM automation_groups WHERE workset_id=?",(wid,)):
                        if run[0]:_retire_tts(tts,run[0])
                    db.execute('BEGIN IMMEDIATE')
                    try:
                        archive(db,wid);_retire_jobs(db,wid)
                        db.execute('DELETE FROM automation_worksets WHERE id=? AND session_id=?',(wid,sid))
                        db.commit();self.worksets+=1
                    except BaseException:db.rollback();raise
                for row in db.execute('SELECT * FROM automation_staging WHERE session_id=?',(sid,)).fetchall():
                    if _remove_staging(row):db.execute('DELETE FROM automation_staging WHERE path=? AND session_id=?',(row['path'],sid))
                    else:self.preserved_staging.append(row['path'])
                db.execute("UPDATE automation_sessions SET state='closed' WHERE id=?",(sid,))
        except Exception as exc:
            self.error=type(exc).__name__
            self.repo.store.log.emit('gui_error',reason='automation_session_cleanup_failed',exception=self.error)
        finally:
            if tts:tts.close()
            if db:db.close()
            self.elapsed_seconds=time.perf_counter()-started
            self.done.set()
