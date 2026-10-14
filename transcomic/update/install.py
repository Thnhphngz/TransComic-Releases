"""Stage A install state machine; only a concrete data-only fake adapter exists."""
from dataclasses import dataclass
from enum import StrEnum
from .metadata import UpdateError, NOT_READY

class State(StrEnum):
    IDLE='IDLE'
    CHECKING='CHECKING'
    UP_TO_DATE='UP_TO_DATE'
    UPDATE_AVAILABLE='UPDATE_AVAILABLE'
    DOWNLOADING='DOWNLOADING'
    VERIFYING='VERIFYING'
    READY_TO_INSTALL='READY_TO_INSTALL'
    WAITING_FOR_SAFE_EXIT='WAITING_FOR_SAFE_EXIT'
    INSTALLING='INSTALLING'
    INSTALL_FAILED='INSTALL_FAILED'
    COMPLETED='COMPLETED'
    CANCELLED='CANCELLED'
    ERROR='ERROR'

@dataclass(frozen=True)
class SafetySnapshot:
    translating: bool=False
    paused: bool=False
    inflight: bool=False
    transaction: bool=False
    editing: bool=False
    app_closed: bool=False
    process_exited: bool=False
    safe_exit_verified: bool=False

    def reasons(self):
        return [name for name in ('translating','paused','inflight','transaction','editing') if getattr(self,name)] + ([] if self.app_closed and self.process_exited and self.safe_exit_verified else ['safe_exit_unverified'])

class FakeInstaller:
    """No executable or subprocess; simulation flag is mandatory in its result."""
    def __init__(self,succeeds=True): self.succeeds=succeeds;self.calls=0
    def run(self,path):
        if path.suffix!='.testdata': raise UpdateError('Simulation requires a data fixture')
        self.calls+=1
        return {'simulated':True,'success':self.succeeds}

def window_safety(window):
    """Read existing status only. Window closure cannot prove process termination."""
    scheduler=window.scheduler
    thread=getattr(scheduler,'_thread',None)
    editing=getattr(window.table.itemDelegate(),'active_editor',None) is not None
    return SafetySnapshot(translating=bool(thread and thread.is_alive()),
        paused=bool(scheduler and scheduler._paused.is_set()),
        inflight=bool(scheduler and getattr(scheduler,'active',0)),
        transaction=bool(not window._closed and window.store.db.in_transaction),editing=editing,
        app_closed=window._closed,process_exited=False,safe_exit_verified=False)

class InstallMachine:
    def __init__(self): self.state=State.IDLE;self.simulated=False

    def install(self,*args,**kwargs):
        # No env/CLI/UI bypass and no production process adapter in Stage A.
        raise UpdateError(NOT_READY+': Stage A production install is locked')

    def simulate(self,path,snapshot,adapter,verify,cancelled=False):
        if type(adapter) is not FakeInstaller: raise UpdateError('Only built-in fake installer allowed')
        if cancelled: self.state=State.CANCELLED;return {'simulated':True,'success':False}
        self.state=State.VERIFYING
        try:verify(path)
        except Exception:
            self.state=State.ERROR
            raise
        self.state=State.WAITING_FOR_SAFE_EXIT
        if snapshot.reasons(): return {'simulated':True,'success':False,'blocked_by':snapshot.reasons()}
        self.state=State.READY_TO_INSTALL
        self.state=State.INSTALLING;self.simulated=True
        try:result=adapter.run(path)
        except Exception:
            self.state=State.INSTALL_FAILED
            raise
        self.state=State.COMPLETED if result['success'] else State.INSTALL_FAILED
        return result
