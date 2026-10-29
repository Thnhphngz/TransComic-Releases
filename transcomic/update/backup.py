"""Future migration helper; never invoked automatically in Stage A."""
from pathlib import Path
from contextlib import closing
from datetime import datetime,timezone
import hashlib
import json
import os
import sqlite3
import time
import uuid
from .metadata import UpdateError

def consistent_backup(source, destination, timeout=5):
    source=Path(source);destination=Path(destination)
    if not source.is_file() or source.resolve()==destination.resolve() or destination.exists():
        raise UpdateError('Invalid backup destination/source')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temp=destination.parent/(uuid.uuid4().hex+'.backup-part')
    deadline=time.monotonic()+timeout
    def progress(*_):
        if time.monotonic()>deadline:raise UpdateError('Backup timed out')
    try:
        with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as src:
            with closing(sqlite3.connect(temp)) as dst:
                src.backup(dst,pages=128,progress=progress,sleep=.01)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise UpdateError('Backup integrity check failed')
                if dst.execute('PRAGMA foreign_key_check').fetchone() is not None:raise UpdateError('Backup foreign key check failed')
        temp.rename(destination)
        return destination
    finally:temp.unlink(missing_ok=True)


def before_attempt_migration(source):
    """Back up the v2.0.2 data pair before opening the writer for attempt v7.

    No Store is opened here: backup failure leaves the original schema/data
    untouched. Reopening an already migrated database creates no new backup.
    Ciphertext/settings/checkpoints are copied by SQLite, never decrypted.
    """
    source=Path(source)
    if not source.is_file() or not source.stat().st_size:return None
    with closing(sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute("SELECT sql FROM sqlite_master WHERE name='request_attempts' AND type='table'").fetchone()
        if row is None or 'attempt_number>=1' in row[0].replace(' ',''):return None
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=source.parent/'Backups'/('pre-attempt-v7-'+stamp+'-'+uuid.uuid4().hex)
    folder.mkdir(parents=True,exist_ok=False)
    records=[]
    for kind,path in (('translation',source),('tts',source.parent/'TTS/tts.sqlite3')):
        if not path.is_file():
            records.append(dict(kind=kind,present=False));continue
        target=consistent_backup(path,folder/(kind+'.sqlite3'),timeout=60)
        with closing(sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone() is not None:
                raise UpdateError('Migration backup verification failed')
        with target.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        records.append(dict(kind=kind,present=True,file=target.name,bytes=target.stat().st_size,sha256=digest,
                            integrity='ok',foreign_key_errors=0))
    receipt=folder/'manifest.json'
    pending=folder/'manifest.json.part'
    with pending.open('x',encoding='utf8') as stream:
        json.dump(dict(schema=1,migration='attempt_constraint_v7',created_utc=stamp,databases=records),stream,indent=2)
        stream.flush();os.fsync(stream.fileno())
    pending.rename(receipt)
    return receipt
