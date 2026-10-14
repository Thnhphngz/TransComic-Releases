"""Future migration helper; never invoked automatically in Stage A."""
from pathlib import Path
from contextlib import closing
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
        temp.rename(destination)
        return destination
    finally:temp.unlink(missing_ok=True)
