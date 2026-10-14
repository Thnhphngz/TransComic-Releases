"""External helper contract, tested with data-only process/installer adapters.

No OS process launch, termination or executable path supplied by metadata.
"""
from dataclasses import dataclass
from .install import InstallMachine, FakeInstaller, State
from .metadata import UpdateError


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    creation_id: str  # production must hold original Windows process handle


@dataclass
class FakeProcess:
    identity: ProcessIdentity
    exited: bool = False


@dataclass
class FakeEnvironment:
    locked: bool = False
    elevation: bool = False
    uac_cancelled: bool = False
    power_loss: bool = False
    installed_version: str = ''
    restart_success: bool = True
    restarts: int = 0


class ExternalHelper(InstallMachine):
    def simulate_update(self, path, expected_identity, process, snapshot, installer,
                        verify, version, environment, cancelled=False, unknown=False):
        if type(process) is not FakeProcess or type(environment) is not FakeEnvironment or type(installer) is not FakeInstaller:
            raise UpdateError('B1 accepts concrete fake adapters only')
        self.simulated = True
        if cancelled:
            self.state = State.CANCELLED
            return {'simulated': True, 'success': False, 'reason': 'cancelled'}
        self.state = State.WAITING_FOR_SAFE_EXIT
        reasons = snapshot.reasons()
        if process.identity != expected_identity or not process.exited:
            reasons.append('original_process_not_exited')
        if unknown:
            reasons.append('unknown_work_unresolved')
        if reasons:
            return {'simulated': True, 'success': False, 'blocked_by': reasons}
        # Reverify after exit and immediately before mock installer.
        self.state = State.VERIFYING
        try:
            verify(path)
        except Exception:
            self.state = State.ERROR
            raise
        if environment.locked or environment.elevation or environment.uac_cancelled:
            self.state = State.INSTALL_FAILED
            return {'simulated': True, 'success': False, 'reason': 'file_lock_or_elevation'}
        result = self.simulate(path, snapshot, installer, verify)
        if not result['success'] or environment.power_loss or environment.installed_version != version:
            self.state = State.INSTALL_FAILED
            return {'simulated': True, 'success': False, 'reason': 'install_or_version_unverified'}
        environment.restarts += 1
        self.state = State.COMPLETED if environment.restart_success else State.INSTALL_FAILED
        return {'simulated': True, 'success': environment.restart_success, 'actual_install': False}
