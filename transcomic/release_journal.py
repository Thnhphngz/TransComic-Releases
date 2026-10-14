"""Durable internal journal; never used by the B1/B2.1 BAT to release."""
from contextlib import contextmanager
from enum import StrEnum
import json
import os
from pathlib import Path
from uuid import uuid4
from .release import version_outputs
from .update.metadata import UpdateError, bumped, strict_json


class ReleaseState(StrEnum):
    PRECHECK='PRECHECK'
    VERSION_SELECTED='VERSION_SELECTED'
    TESTED='TESTED'
    BUILT='BUILT'
    PACKAGED='PACKAGED'
    SIGNED='SIGNED'
    DRAFT_CREATED='DRAFT_CREATED'
    ASSETS_UPLOADED='ASSETS_UPLOADED'
    REMOTE_VERIFIED='REMOTE_VERIFIED'
    PUBLISHED='PUBLISHED'
    FAILED='FAILED'
    UNKNOWN_REMOTE_OUTCOME='UNKNOWN_REMOTE_OUTCOME'


class ReleaseJournal:
    def __init__(self,path):
        self.path=Path(path).absolute();self.lock=self.path.with_suffix('.lock')
        self._locked=False

    @contextmanager
    def exclusive(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.parent.is_symlink() or self.path.is_symlink():raise UpdateError('Unsafe journal path')
        try:fd=os.open(self.lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:raise UpdateError('JOURNAL_LOCKED_OR_RECOVERY_REQUIRED') from None
        self._locked=True
        try:
            os.write(fd,str(os.getpid()).encode());os.close(fd);fd=None
            yield self
        finally:
            if fd is not None:os.close(fd)
            self._locked=False;self.lock.unlink(missing_ok=True)

    def load(self):
        if not self.path.exists():return None
        try:
            record=strict_json(self.path.read_bytes());ReleaseState(record['state'])
            version_outputs(record['version'])
            if record['schema']!=1:raise ValueError()
            return record
        except (ValueError,KeyError,TypeError):raise UpdateError('JOURNAL_CORRUPT_RECONCILIATION_REQUIRED') from None

    def save(self,record):
        if not self._locked:raise UpdateError('Journal requires exclusive ownership')
        part=self.path.with_name(self.path.name+'.'+uuid4().hex+'.part')
        try:
            with part.open('x',encoding='utf8') as stream:
                json.dump(record,stream,sort_keys=True);stream.flush();os.fsync(stream.fileno())
            part.replace(self.path)
        finally:part.unlink(missing_ok=True)

    def reserve(self,current,choice='patch',build_id=''):
        record=self.load()
        if record:return record  # reconciliation is mandatory before resolving/reserving next version
        version=bumped(current,choice);version_outputs(version)
        record={'schema':1,'state':ReleaseState.VERSION_SELECTED,'version':version,
                'build_id':build_id,'origin_id':build_id,'last_completed':ReleaseState.VERSION_SELECTED,'failure_code':None}
        self.save(record);return record

    def checkpoint(self,record,state):
        state=ReleaseState(state)
        if state==ReleaseState.PUBLISHED:raise UpdateError('Published checkpoint requires verified remote evidence')
        record=dict(record,state=state)
        if state not in (ReleaseState.FAILED,ReleaseState.UNKNOWN_REMOTE_OUTCOME):record['last_completed']=state
        self.save(record);return record

    def reconcile(self,record,remote):
        # A successful CLI return alone is not evidence. Independent remote verification supplies these fields.
        if not remote or remote.get('tag')!='v'+record['version'] or remote.get('build_id')!=record['build_id'] or remote.get('assets_verified') is not True:
            raise UpdateError('REMOTE_OUTCOME_UNRESOLVED')
        if remote.get('published') is True:
            record=dict(record,state=ReleaseState.PUBLISHED,last_completed=ReleaseState.PUBLISHED)
        elif remote.get('draft') is True:
            record=dict(record,state=ReleaseState.DRAFT_CREATED,last_completed=ReleaseState.DRAFT_CREATED)
        else:raise UpdateError('REMOTE_OUTCOME_UNRESOLVED')
        self.save(record);return record

    def next_release(self,record,remote,build_id,choice='patch'):
        record=self.reconcile(record,remote)
        if record['state']!=ReleaseState.PUBLISHED:raise UpdateError('PREVIOUS_RELEASE_NOT_PUBLISHED')
        if record.get('origin_id')==build_id:return record
        version=bumped(record['version'],choice);version_outputs(version)
        new={'schema':1,'state':ReleaseState.VERSION_SELECTED,'version':version,'build_id':build_id,'origin_id':build_id,
             'last_completed':ReleaseState.VERSION_SELECTED,'failure_code':None,'previous_published_version':record['version']}
        self.save(new);return new
