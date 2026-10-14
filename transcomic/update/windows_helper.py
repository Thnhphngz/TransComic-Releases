"""Windows external installer, gated by installed identity and local Safe Exit IPC.

Trusted paths belong to helper configuration, never JSON update metadata.
"""
from dataclasses import dataclass
import ctypes
from ctypes import wintypes as w
import hashlib
from pathlib import Path
import subprocess
import time
import os
import sys
import threading
from contextlib import contextmanager
from uuid import uuid4
from ..release_adapters import safe_path
from ..version import VERSION
from .metadata import UpdateError, candidate as validate_candidate, PRODUCTION_KEYS, strict_json,SemVer,canonical
from .install import SafetySnapshot

INSTALL_APP_ID = '{CB58C770-47B7-42DC-A2CA-409DDF456487}'
APPLICATION_MUTEX = 'TransComic.Desktop.Running'


@contextmanager
def system_dll_search():
    """External Inno must not inherit the frozen helper's private DLL folder."""
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetDllDirectoryW.argtypes=[w.DWORD,w.LPWSTR];kernel.GetDllDirectoryW.restype=w.DWORD
    kernel.SetDllDirectoryW.argtypes=[w.LPCWSTR];kernel.SetDllDirectoryW.restype=w.BOOL
    length=kernel.GetDllDirectoryW(0,None)
    previous=ctypes.create_unicode_buffer(length+1)
    if length:kernel.GetDllDirectoryW(len(previous),previous)
    if not kernel.SetDllDirectoryW(None):raise UpdateError('INSTALLER_DLL_ENVIRONMENT_UNVERIFIED')
    try:yield
    finally:
        if not kernel.SetDllDirectoryW(previous.value or None):raise UpdateError('HELPER_DLL_ENVIRONMENT_RESTORE_FAILED')


def update_receipt_message(directory):
    """Read bounded local results; never turn a receipt into execution authority."""
    directory=safe_path(directory)
    messages=[]
    for path in list(directory.glob('install-*.json'))[:32]:
        try:
            safe_path(path,directory)
            if path.stat().st_size>4096:continue
            value=strict_json(path.read_bytes());version=str(SemVer.parse(value['version']))
            if path.name!='install-'+version+'.json' or value.get('policy')!='internal' or value.get('simulated') is not False:continue
            state=value.get('state')
            if state=='COMPLETED' and version==VERSION:
                messages.append((SemVer.parse(version),'Đã cập nhật lên '+version+' · phiên bản sau cài đặt đã được xác minh.'))
            elif state in ('INSTALL_OUTCOME_UNKNOWN','INSTALLED_RESTART_PENDING','INSTALL_FAILED'):
                messages.append((SemVer.parse(version),'Cập nhật '+version+' chưa hoàn tất hoặc cần kiểm tra kết quả · không chạy lại bộ cài khi chưa rõ.'))
        except (OSError,UpdateError,KeyError,TypeError):continue
    if messages:return max(messages,key=lambda pair:pair[0])[1]
    error=safe_path(directory/'helper-last-result.json',directory)
    try:
        if error.stat().st_size<=4096 and strict_json(error.read_bytes()).get('state')=='NOT_COMPLETED':
            return 'Lần cập nhật trước chưa hoàn tất · xem kết quả trong thư mục Updates; không tự chạy lại bộ cài.'
    except (OSError,UpdateError,TypeError):pass
    return ''


def check_previous_install(updates,plan,policy,testing=False,lock_owned=False):
    lock=safe_path(updates/('install-'+plan.version+'.lock'),updates)
    if lock.exists() and not lock_owned:raise UpdateError('INSTALL_BUSY_OR_RECOVERY_REQUIRED')
    path=safe_path(updates/('install-'+plan.version+'.json'),updates)
    if not path.exists():return
    try:
        if path.stat().st_size>4096:raise ValueError()
        previous=strict_json(path.read_bytes())
        if not isinstance(previous,dict) or (previous.get('version'),previous.get('sha256'),previous.get('policy'),previous.get('simulated'))!=(plan.version,plan.sha256,policy,testing):
            raise ValueError()
        state=previous['state']
        if state not in ('INSTALL_OUTCOME_UNKNOWN','INSTALLED_RESTART_PENDING','INSTALL_FAILED','COMPLETED'):raise ValueError()
    except (ValueError,KeyError,TypeError):raise UpdateError('INSTALL_RECEIPT_REQUIRES_MANUAL_RECONCILIATION') from None
    if state in ('INSTALL_OUTCOME_UNKNOWN','INSTALLED_RESTART_PENDING'):
        raise UpdateError('INSTALL_OUTCOME_REQUIRES_MANUAL_RECONCILIATION')
    if state=='COMPLETED' and not testing:raise UpdateError('INSTALL_ALREADY_COMPLETED')


def require_packaged_windows():
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise UpdateError('PACKAGED_WINDOWS_APPLICATION_REQUIRED')


def installed_directory():
    from .service import update_directory
    directory = safe_path(Path(os.environ['LOCALAPPDATA'])/'Programs/TransComic')
    if directory == safe_path(update_directory()):
        raise UpdateError('INSTALLATION_PATH_INVALID')
    return directory


def registered_installation(expected_version=VERSION):
    require_packaged_windows()
    import winreg
    key='Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\'+INSTALL_APP_ID+'_is1'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key) as handle:
            location=winreg.QueryValueEx(handle,'InstallLocation')[0]
            version=winreg.QueryValueEx(handle,'DisplayVersion')[0]
    except OSError:raise UpdateError('REGISTERED_PER_USER_INSTALLATION_REQUIRED') from None
    directory=safe_path(location)
    if directory!=installed_directory() or version!=expected_version:
        raise UpdateError('PER_USER_INSTALLATION_LOCATION_OR_VERSION_UNVERIFIED')
    if WindowsRuntime().installed_version(directory/'TransComic.exe')!=expected_version:
        raise UpdateError('INSTALLED_APPLICATION_VERSION_UNVERIFIED')
    return directory


class HelperHandoff:
    """Copy a verified helper away from files the installer will replace."""
    def __init__(self,updates,installation,authenticode,commands=None,policy='signed-stable'):
        from ..release_adapters import commands_or_default
        self.updates=safe_path(updates);self.installation=safe_path(installation)
        self.authenticode=authenticode;self.commands=commands_or_default(commands)
        if policy not in ('internal','signed-stable'):raise UpdateError('UNKNOWN_UPDATE_POLICY')
        self.policy=policy

    def launch(self,plan_bytes,cancel=None):
        require_packaged_windows()
        cancel=cancel or threading.Event()
        from .service import update_directory
        if self.policy!='internal':raise UpdateError('SIGNED_NATIVE_ACTIVATION_NOT_CONFIGURED')
        if self.installation!=registered_installation() or self.updates!=safe_path(update_directory()):
            raise UpdateError('FIXED_INSTALLATION_AND_UPDATES_REQUIRED')
        if safe_path(sys.executable)!=self.installation/'TransComic.exe':
            raise UpdateError('INSTALLED_APPLICATION_REQUIRED')
        plan=load_install_plan(plan_bytes,self.updates,self.installation,policy=self.policy)
        if plan.process!=current_process_identity():raise UpdateError('HANDOFF_APP_IDENTITY_MISMATCH')
        check_previous_install(self.updates,plan,self.policy)
        if cancel.is_set():raise UpdateError('UPDATE_CANCELLED')
        original=safe_path(self.installation/'TransComic-UpdateHelper.exe',self.installation)
        if self.policy=='signed-stable':
            if self.authenticode is None:raise UpdateError('AUTHENTICODE_NOT_CONFIGURED')
            self.authenticode.verify(original)
        self.updates.mkdir(parents=True,exist_ok=True)
        directory=safe_path(self.updates/('handoff-'+uuid4().hex),self.updates);directory.mkdir()
        copied=directory/original.name
        runtime=WindowsRuntime()
        with runtime.hold_installer(original) as stream:
            digest=hashlib.file_digest(stream,'sha256').hexdigest();stream.seek(0)
            with copied.open('xb') as target:
                while chunk:=stream.read(65536):target.write(chunk)
                target.flush();os.fsync(target.fileno())
        with copied.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=digest:raise UpdateError('HELPER_COPY_HASH_MISMATCH')
        if self.policy=='signed-stable':self.authenticode.verify(copied)
        from .windows_channel import WindowsChannel
        nonce=os.urandom(32).hex();channel=WindowsChannel.listen(nonce)
        try:
            with runtime.hold_installer(copied) as pinned:
                if hashlib.file_digest(pinned,'sha256').hexdigest()!=digest:raise UpdateError('HELPER_COPY_HASH_MISMATCH')
                # Named-pipe identity survives the one-file bootloader's child.
                # Keep the verified copy non-writable until READY as well.
                process=subprocess.Popen([str(copied),'--channel',nonce],cwd=directory,shell=False,creationflags=0x08000000,close_fds=True,
                                         env=dict(os.environ,PYINSTALLER_RESET_ENVIRONMENT='1'))
                channel.accept(cancel)
                peer=process_identity(channel.peer_pid())
                if safe_path(peer.image)!=copied or peer.creation_time<plan.process.creation_time:
                    raise UpdateError('HANDOFF_HELPER_IDENTITY_MISMATCH')
                channel.send(plan_bytes,cancel)
                if channel.receive(cancel)!=b'READY':raise UpdateError('HANDOFF_NOT_READY')
                return HandoffSession(channel,process,plan)
        except BaseException:
            channel.close()  # EOF aborts helper; never terminate an app/installer.
            raise

    def preview(self,nonce='test-handoff'):
        if not nonce.isalnum() and nonce!='test-handoff':raise UpdateError('Invalid handoff directory identity')
        return {'helper':self.updates/('handoff-'+nonce)/'TransComic-UpdateHelper.exe',
                'installation':self.installation,'overwrites_running_helper':False}


@dataclass(frozen=True)
class AppProcessIdentity:
    pid:int
    creation_time:int
    image:str


def process_identity(pid):
    require_packaged_windows()
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE]
    kernel.GetProcessTimes.argtypes=[w.HANDLE,*([ctypes.POINTER(w.FILETIME)]*4)]
    kernel.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:raise UpdateError('PROCESS_IDENTITY_UNAVAILABLE')
    try:
        created=w.FILETIME();exited=w.FILETIME();kt=w.FILETIME();ut=w.FILETIME();length=w.DWORD(32768);image=ctypes.create_unicode_buffer(length.value)
        if not kernel.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(kt),ctypes.byref(ut)) or not kernel.QueryFullProcessImageNameW(handle,0,image,ctypes.byref(length)):
            raise UpdateError('PROCESS_IDENTITY_UNVERIFIED')
        return AppProcessIdentity(pid,(created.dwHighDateTime<<32)|created.dwLowDateTime,str(safe_path(image.value)))
    finally:kernel.CloseHandle(handle)


def current_process_identity():
    return process_identity(os.getpid())


def parent_process_id(pid):
    require_packaged_windows()
    class Entry(ctypes.Structure):
        _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',ctypes.c_size_t),
                  ('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),('priority',w.LONG),('flags',w.DWORD),('name',w.WCHAR*260)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD];kernel.CreateToolhelp32Snapshot.restype=w.HANDLE
    kernel.Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
    kernel.Process32NextW.argtypes=[w.HANDLE,ctypes.POINTER(Entry)]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    handle=kernel.CreateToolhelp32Snapshot(2,0)
    if handle==ctypes.c_void_p(-1).value:raise UpdateError('PROCESS_PARENT_UNVERIFIED')
    try:
        entry=Entry();entry.size=ctypes.sizeof(Entry)
        valid=kernel.Process32FirstW(handle,ctypes.byref(entry))
        while valid:
            if entry.pid==pid:return entry.parent
            valid=kernel.Process32NextW(handle,ctypes.byref(entry))
        raise UpdateError('PROCESS_PARENT_UNVERIFIED')
    finally:kernel.CloseHandle(handle)


def acquire_application_mutex():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[w.LPVOID,w.BOOL,w.LPCWSTR];kernel.CreateMutexW.restype=w.HANDLE
    handle=kernel.CreateMutexW(None,False,APPLICATION_MUTEX)
    if not handle:raise UpdateError('APPLICATION_MUTEX_UNAVAILABLE')
    return handle  # caller retains until OS process exit


def check_application_start():
    """Prevent an old app opening its DB midway through a native upgrade."""
    from .service import update_directory
    if not getattr(sys,'frozen',False):return
    updates=safe_path(update_directory())
    for lock in updates.glob('install-*.lock'):
        safe_path(lock,updates)
        if lock.name!='install-'+VERSION+'.lock':raise UpdateError('UPDATE_IN_PROGRESS_OR_RECOVERY_REQUIRED')
        receipt=safe_path(updates/('install-'+VERSION+'.json'),updates)
        if not receipt.exists() or receipt.stat().st_size>4096:raise UpdateError('UPDATE_IN_PROGRESS_OR_RECOVERY_REQUIRED')
        value=strict_json(receipt.read_bytes())
        if value.get('version')!=VERSION or value.get('policy')!='internal' or value.get('state') not in ('INSTALLED_RESTART_PENDING','COMPLETED'):
            raise UpdateError('UPDATE_IN_PROGRESS_OR_RECOVERY_REQUIRED')


def acknowledge_restart(arguments):
    """Only an installed app with its UI/DB initialized emits a startup receipt."""
    tokens=[arg.split('=',1)[1] for arg in arguments if arg.startswith('--update-startup-token=')]
    if not tokens:return
    require_packaged_windows()
    from .windows_channel import channel_name
    from .service import update_directory
    if len(tokens)!=1:raise UpdateError('INVALID_STARTUP_TICKET')
    token=tokens[0];channel_name(token)  # same bounded, path-free nonce grammar
    installation=registered_installation()
    identity=current_process_identity()
    if safe_path(identity.image)!=installation/'TransComic.exe':raise UpdateError('STARTUP_IDENTITY_MISMATCH')
    updates=safe_path(update_directory());updates.mkdir(parents=True,exist_ok=True)
    path=safe_path(updates/('startup-'+token+'.json'),updates)
    temporary=safe_path(updates/('startup-'+token+'.tmp'),updates)
    if path.exists():raise UpdateError('STARTUP_RECEIPT_ALREADY_EXISTS')
    with temporary.open('xb') as stream:
        stream.write(canonical({'version':VERSION,'pid':identity.pid,'creation_time':identity.creation_time,'image':identity.image}))
        stream.flush();os.fsync(stream.fileno())
    safe_path(path,updates);safe_path(temporary,updates)
    temporary.rename(path)  # Windows does not overwrite an existing receipt.


class HandoffSession:
    """App owns COMMIT. Closing without COMMIT makes helper abort without install."""
    def __init__(self,channel,process,plan):
        self.channel=channel;self.process=process;self.plan=plan;self.committed=False

    def commit(self,snapshot,logger_closed):
        require_handoff_ready(snapshot)
        if logger_closed is not True or self.committed or self.channel is None:
            raise UpdateError('SAFE_EXIT_COMMIT_REJECTED')
        try:
            self.channel.send(b'COMMIT_SAFE_EXIT',threading.Event(),timeout=2)
            if self.channel.receive(threading.Event(),timeout=2)!=b'COMMIT_ACK':
                raise UpdateError('SAFE_EXIT_COMMIT_ACK_UNVERIFIED')
            self.committed=True
        finally:self.abort()

    def abort(self):
        if self.channel is not None:
            channel,self.channel=self.channel,None
            channel.close()


_NATIVE_SESSION_SEAL=object()


class NativeHelperSession:
    def __init__(self,seal,channel,plan,updates,installation,handle):
        if seal is not _NATIVE_SESSION_SEAL:raise UpdateError('NATIVE_HANDOFF_REQUIRED')
        self.channel=channel;self.plan=plan;self.updates=updates;self.installation=installation
        self.handle=handle;self.committed=False;self.exited=False;self.consumed=False
        self.launcher_handle=None

    @classmethod
    def authenticate(cls,channel,raw):
        require_packaged_windows()
        from .service import update_directory
        updates=safe_path(update_directory());installation=registered_installation()
        copied=safe_path(sys.executable,updates)
        import re
        if copied.name!='TransComic-UpdateHelper.exe' or copied.parent.parent!=updates or not re.fullmatch('handoff-[0-9a-f]{32}',copied.parent.name):
            raise UpdateError('VERIFIED_HELPER_COPY_REQUIRED')
        plan=load_install_plan(raw,updates,installation,policy='internal')
        if channel.peer_pid()!=plan.process.pid:raise UpdateError('HANDOFF_SERVER_PID_MISMATCH')
        from .internal import InternalUpdateService,candidate as internal_candidate
        InternalUpdateService(updates).confirm_install(internal_candidate(plan.release,plan.envelope))
        runtime=WindowsRuntime()
        with runtime.hold_installer(installation/copied.name) as original, runtime.hold_installer(copied) as running:
            if hashlib.file_digest(original,'sha256').digest()!=hashlib.file_digest(running,'sha256').digest():
                raise UpdateError('HELPER_COPY_HASH_MISMATCH')
        handle=runtime.open_process(plan.process)
        session=cls(_NATIVE_SESSION_SEAL,channel,plan,updates,installation,handle)
        try:
            parent=process_identity(parent_process_id(plan.process.pid))
            if parent.image==plan.process.image and parent.creation_time<=plan.process.creation_time:
                session.launcher_handle=runtime.open_process(parent)
            return session
        except BaseException:
            session.close();raise

    def require(self,helper,plan):
        if self.consumed or self.handle is None or helper.policy!='internal' or self.plan!=plan or helper.updates!=self.updates or helper.installation!=self.installation:
            raise UpdateError('NATIVE_HANDOFF_CONTEXT_MISMATCH')

    def ready_and_wait(self,cancel):
        self.consumed=True
        self.channel.send(b'READY',cancel)
        if self.channel.receive(cancel,timeout=60)!=b'COMMIT_SAFE_EXIT':
            raise UpdateError('SAFE_EXIT_COMMIT_REQUIRED')
        self.committed=True
        self.channel.send(b'COMMIT_ACK',cancel)

    def close(self):
        if self.handle is not None:
            WindowsRuntime().close_process(self.handle);self.handle=None
        if self.launcher_handle is not None:
            WindowsRuntime().close_process(self.launcher_handle);self.launcher_handle=None
        self.channel.close()


@dataclass(frozen=True)
class InstallPlan:
    version:str
    installer:Path
    size:int
    sha256:str
    release:dict
    envelope:dict
    process:AppProcessIdentity
    restart:bool=True
    mode:str='per_user'


@dataclass(frozen=True)
class HandoffSafety:
    logger_flushing:bool=False
    stop_requested:bool=False
    outcome_unknown:bool=False
    safe_exit_cancelled:bool=False

    def blocked(self):
        return self.logger_flushing or self.stop_requested or self.outcome_unknown or self.safe_exit_cancelled


def require_handoff_ready(snapshot):
    # Caller has closed/committed its data, but its OS process must still exist so
    # the helper can acquire the exact creation-time/image handle before exit.
    if not isinstance(snapshot,SafetySnapshot) or not snapshot.app_closed or not snapshot.safe_exit_verified or any(
        getattr(snapshot,name) for name in ('translating','paused','inflight','transaction','editing')):
        raise UpdateError('SAFE_EXIT_BUSY_OR_UNVERIFIED')


def load_install_plan(raw,updates,installation,keys=None,testing=False,policy='signed-stable'):
    if len(raw)>128*1024:raise UpdateError('INSTALL_PLAN_SIZE_LIMIT')
    value=strict_json(raw)
    if not isinstance(value,dict) or set(value)!={'release','manifest','pid','creation_time','restart','safe_exit_verified'}:
        raise UpdateError('INSTALL_PLAN_FIELDS_REJECTED')
    if type(value['pid']) is not int or type(value['creation_time']) is not int or type(value['restart']) is not bool or value['safe_exit_verified'] is not True:raise UpdateError('INSTALL_PLAN_SAFETY_OR_PROCESS_INVALID')
    if policy=='internal':
        from .internal import candidate as internal_candidate
        item=internal_candidate(value['release'],value['manifest'],testing=testing)
    elif policy=='signed-stable':
        item=validate_candidate(value['release'],value['manifest'],PRODUCTION_KEYS if keys is None else keys,testing=testing)
        if item.signature_status!='VERIFIED_ED25519':raise UpdateError('PRODUCTION_SIGNING_NOT_READY')
    else:raise UpdateError('UNKNOWN_UPDATE_POLICY')
    if SemVer.parse(item.version)<=SemVer.parse(VERSION):raise UpdateError('UPDATE_VERSION_NOT_NEWER')
    # No JSON installer path, executable path, install directory or public key is accepted.
    process=AppProcessIdentity(value['pid'],value['creation_time'],str(safe_path(installation)/'TransComic.exe'))
    return InstallPlan(item.version,safe_path(Path(updates)/item.filename,updates),item.size,item.sha256,
                       value['release'],value['manifest'],process,value['restart'])


class WindowsRuntime:
    def __init__(self):
        self._native_session=None;self._plan=None

    def open_process(self,identity):
        require_packaged_windows()
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
        kernel.GetProcessTimes.argtypes=[w.HANDLE,*([ctypes.POINTER(w.FILETIME)]*4)]
        kernel.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)]
        kernel.CloseHandle.argtypes=[w.HANDLE]
        handle=kernel.OpenProcess(0x1000|0x100000,False,identity.pid)
        if not handle:raise UpdateError('ORIGINAL_PROCESS_HANDLE_UNAVAILABLE')
        created=w.FILETIME();exited=w.FILETIME();kt=w.FILETIME();ut=w.FILETIME();length=w.DWORD(32768);image=ctypes.create_unicode_buffer(length.value)
        if not kernel.GetProcessTimes(handle,ctypes.byref(created),ctypes.byref(exited),ctypes.byref(kt),ctypes.byref(ut)) or not kernel.QueryFullProcessImageNameW(handle,0,image,ctypes.byref(length)):
            kernel.CloseHandle(handle);raise UpdateError('PROCESS_IDENTITY_UNVERIFIED')
        creation=(created.dwHighDateTime<<32)|created.dwLowDateTime
        if creation!=identity.creation_time or Path(image.value).resolve()!=Path(identity.image).resolve():
            kernel.CloseHandle(handle);raise UpdateError('PROCESS_IDENTITY_MISMATCH')
        return handle

    def wait_exit(self,handle,timeout,cancel):
        require_packaged_windows()
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if cancel.is_set():raise UpdateError('UPDATE_CANCELLED')
            result=kernel.WaitForSingleObject(handle,100)
            if result==0:return
            if result!=258:raise UpdateError('PROCESS_WAIT_FAILED')
        raise UpdateError('PROCESS_EXIT_TIMEOUT')

    def close_process(self,handle):
        require_packaged_windows()
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle(handle)

    def hold_installer(self,path):
        require_packaged_windows()
        path=safe_path(path)
        # Deny write/delete while verification AND installer launch/wait use the same path.
        import msvcrt
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE]
        kernel.CreateFileW.restype=w.HANDLE
        handle=kernel.CreateFileW(str(path),0x80000000,1,None,3,0x00200000,None)
        if handle==ctypes.c_void_p(-1).value:raise UpdateError('INSTALLER_FILE_LOCK_UNAVAILABLE')
        # safe_path rejects all ancestor reparse points; handle identity is checked before execution.
        kernel.GetFinalPathNameByHandleW.argtypes=[w.HANDLE,w.LPWSTR,w.DWORD,w.DWORD]
        final=ctypes.create_unicode_buffer(32768)
        import os
        if not kernel.GetFinalPathNameByHandleW(handle,final,len(final),0) or os.path.normcase(os.path.normpath(final.value.removeprefix('\\\\?\\')))!=os.path.normcase(os.path.normpath(str(path))):
            kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle(handle);raise UpdateError('INSTALLER_HANDLE_PATH_MISMATCH')
        return os.fdopen(msvcrt.open_osfhandle(handle,os.O_RDONLY),'rb')

    def install(self,path,install_directory,timeout):
        self.require_execution(path,install_directory)
        try:
            with system_dll_search():
                process=subprocess.Popen([str(path),'/VERYSILENT','/NORESTART','/SP-','/SUPPRESSMSGBOXES',
                                   '/DIR='+str(install_directory)],cwd=install_directory,shell=False,
                                  stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=0x08000000)
            code=process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:raise UpdateError('INSTALLER_TIMEOUT_MANUAL_RECOVERY') from None
        except OSError:raise UpdateError('INSTALLER_LAUNCH_DENIED_OR_UAC_CANCELLED') from None
        return code

    def require_execution(self,path,install_directory):
        require_packaged_windows()
        session=self._native_session;plan=self._plan
        if type(session) is not NativeHelperSession or not session.committed or not session.exited or plan is None:
            raise UpdateError('SAFE_EXIT_NATIVE_AUTHORIZATION_REQUIRED')
        if safe_path(path,session.updates)!=plan.installer or safe_path(install_directory)!=session.installation or registered_installation()!=session.installation:
            raise UpdateError('FIXED_VERIFIED_INSTALLER_REQUIRED')

    def installed_version(self,app):
        require_packaged_windows()
        dll=ctypes.WinDLL('version',use_last_error=True)
        dll.GetFileVersionInfoSizeW.argtypes=[w.LPCWSTR,ctypes.POINTER(w.DWORD)]
        dll.GetFileVersionInfoW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID]
        dll.VerQueryValueW.argtypes=[w.LPVOID,w.LPCWSTR,ctypes.POINTER(w.LPVOID),ctypes.POINTER(w.UINT)]
        unused=w.DWORD();size=dll.GetFileVersionInfoSizeW(str(app),ctypes.byref(unused))
        if not 0<size<=1024*1024:raise UpdateError('INSTALLED_VERSION_UNVERIFIED')
        buffer=ctypes.create_string_buffer(size)
        if not dll.GetFileVersionInfoW(str(app),0,size,buffer):raise UpdateError('INSTALLED_VERSION_UNVERIFIED')
        pointer=w.LPVOID();length=w.UINT()
        if not dll.VerQueryValueW(buffer,'\\',ctypes.byref(pointer),ctypes.byref(length)):raise UpdateError('INSTALLED_VERSION_UNVERIFIED')
        if length.value<52 or not pointer:raise UpdateError('INSTALLED_VERSION_UNVERIFIED')
        fields=ctypes.cast(pointer,ctypes.POINTER(w.DWORD));ms,ls=fields[2],fields[3]
        if fields[0]!=0xFEEF04BD or ls&65535:raise UpdateError('INSTALLED_VERSION_UNVERIFIED')
        return f'{ms>>16}.{ms&65535}.{ls>>16}'

    def restart(self,app):
        require_packaged_windows()
        session=self._native_session;plan=self._plan
        if type(session) is not NativeHelperSession or not session.committed or not session.exited or plan is None or safe_path(app)!=session.installation/'TransComic.exe' or registered_installation(plan.version)!=session.installation:
            raise UpdateError('VERIFIED_NEW_APPLICATION_REQUIRED')
        ticket=os.urandom(32).hex()
        receipt=safe_path(session.updates/('startup-'+ticket+'.json'),session.updates)
        process=subprocess.Popen([str(app),'--update-startup-token='+ticket],cwd=app.parent,shell=False,creationflags=0x08000000,
                                 env=dict(os.environ,PYINSTALLER_RESET_ENVIRONMENT='1'))
        launcher=process_identity(process.pid)
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if process.poll() is not None:raise UpdateError('NEW_APP_START_FAILED')
            if receipt.exists():
                safe_path(receipt,session.updates)
                if receipt.stat().st_size>4096:raise UpdateError('NEW_APP_STARTUP_RECEIPT_INVALID')
                value=strict_json(receipt.read_bytes())
                if set(value)!={'version','pid','creation_time','image'} or value['version']!=plan.version or type(value['pid']) is not int or type(value['creation_time']) is not int:
                    raise UpdateError('NEW_APP_STARTUP_RECEIPT_INVALID')
                identity=process_identity(value['pid'])
                if identity!=AppProcessIdentity(value['pid'],value['creation_time'],value['image']) or safe_path(identity.image)!=app or identity.creation_time<launcher.creation_time:
                    raise UpdateError('NEW_APP_STARTUP_IDENTITY_MISMATCH')
                if identity.pid!=process.pid and parent_process_id(identity.pid)!=process.pid:
                    raise UpdateError('NEW_APP_STARTUP_PARENT_MISMATCH')
                return identity.pid
            time.sleep(.05)
        raise UpdateError('NEW_APP_STARTUP_NOT_ACKNOWLEDGED')


class FakeWindowsRuntime:
    def __init__(self):
        from ..release_version import bumped
        self.identity=None;self.process_exited=True;self.fail=None;self.version=bumped(VERSION,'minor');self.calls=[]
    def open_process(self,identity):
        self.calls.append('open')
        if self.identity!=identity:raise UpdateError('PROCESS_IDENTITY_MISMATCH')
        return object()
    def wait_exit(self,handle,timeout,cancel):
        self.calls.append('wait')
        if cancel.is_set():raise UpdateError('UPDATE_CANCELLED')
        if not self.process_exited or self.fail=='wait':raise UpdateError('PROCESS_EXIT_TIMEOUT')
    def close_process(self,handle):self.calls.append('close')
    def hold_installer(self,path):
        if self.fail=='file_lock':raise UpdateError('INSTALLER_FILE_LOCK_UNAVAILABLE')
        return path.open('rb')
    def install(self,path,directory,timeout):
        self.calls.append('install')
        if self.fail in ('uac','quarantine','timeout'):raise UpdateError('MOCK_INSTALL_'+self.fail.upper())
        return 1 if self.fail=='installer' else 0
    def installed_version(self,app):
        self.calls.append('version')
        if self.fail=='version':raise UpdateError('INSTALLED_VERSION_UNVERIFIED')
        return self.version
    def restart(self,app):
        self.calls.append('restart')
        if self.fail=='restart':raise UpdateError('NEW_APP_START_FAILED')
        return 123


class ProductionUpdateHelper:
    def __init__(self,updates,installation,runtime=None,keys=None,policy='signed-stable'):
        if runtime is not None and type(runtime) is not FakeWindowsRuntime:raise UpdateError('Concrete mock runtime required')
        if runtime is None and keys is not None:raise UpdateError('Production trust cannot come from install plan')
        self.runtime=runtime or WindowsRuntime();self.testing=type(self.runtime) is FakeWindowsRuntime
        self.keys=keys if self.testing else PRODUCTION_KEYS
        if policy not in ('internal','signed-stable'):raise UpdateError('UNKNOWN_UPDATE_POLICY')
        self.policy=policy
        self.updates=safe_path(updates);self.installation=safe_path(installation)
        self.app=self.installation/'TransComic.exe'

    def validate(self,plan):
        if self.policy=='internal':
            from .internal import candidate as internal_candidate
            item=internal_candidate(plan.release,plan.envelope,testing=self.testing)
        else:item=validate_candidate(plan.release,plan.envelope,self.keys,testing=self.testing)
        path=safe_path(plan.installer,self.updates)
        if SemVer.parse(item.version)<=SemVer.parse(VERSION):raise UpdateError('UPDATE_VERSION_NOT_NEWER')
        if self.policy=='signed-stable' and item.signature_status!='VERIFIED_ED25519':raise UpdateError('PRODUCTION_SIGNING_NOT_READY')
        if (plan.version,path.name,plan.size,plan.sha256)!=(item.version,item.filename,item.size,item.sha256):raise UpdateError('INSTALL_PLAN_SIGNATURE_BINDING_MISMATCH')
        if plan.mode!='per_user' or Path(plan.process.image).resolve()!=self.app.resolve():raise UpdateError('FIXED_APP_INSTALL_LOCATION_REQUIRED')
        if type(plan.process.pid) is not int or plan.process.pid<=0 or plan.process.creation_time<=0:raise UpdateError('INVALID_PROCESS_IDENTITY')
        return path,item

    def receipt(self,item,state):
        # Write only fixed identity/state; no process argv, user manuscript or tokens.
        path=safe_path(self.updates/('install-'+item.version+'.json'),self.updates)
        self.updates.mkdir(parents=True,exist_ok=True)
        temporary=safe_path(self.updates/(uuid4().hex+'.receipt'),self.updates)
        with temporary.open('xb') as stream:
            stream.write(canonical({'version':item.version,'sha256':item.sha256,'policy':self.policy,'state':state,'simulated':self.testing}));stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)

    def run(self,plan,snapshot,cancel,timeout=60,handoff=None,native_session=None):
        if not self.testing:
            if type(native_session) is not NativeHelperSession:raise UpdateError('NATIVE_HANDOFF_REQUIRED')
            native_session.require(self,plan)
        require_handoff_ready(snapshot)
        self.validate(plan)
        self.updates.mkdir(parents=True,exist_ok=True)
        lock=safe_path(self.updates/('install-'+plan.version+'.lock'),self.updates)
        try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:raise UpdateError('INSTALL_BUSY_OR_RECOVERY_REQUIRED') from None
        try:
            os.close(fd)
            self._native_install_started=False;self._native_install_returned=False
            return self._run(plan,snapshot,cancel,timeout,handoff,native_session)
        finally:
            self.runtime._native_session=None
            self.release_lock(lock,plan)

    def release_lock(self,lock,plan):
        if not self.testing:
            if getattr(self,'_native_install_started',False) and not getattr(self,'_native_install_returned',False):return
            receipt=safe_path(self.updates/('install-'+plan.version+'.json'),self.updates)
            if receipt.exists():
                try:
                    value=strict_json(receipt.read_bytes()) if receipt.stat().st_size<=4096 else None
                    if not isinstance(value,dict) or value.get('state') not in ('COMPLETED','INSTALL_FAILED','INSTALLED_RESTART_PENDING'):
                        return  # Installer may still be alive; also block app startup.
                except (OSError,ValueError,TypeError):return
        safe_path(lock,self.updates).unlink(missing_ok=True)

    def _run(self,plan,snapshot,cancel,timeout,handoff,native_session):
        if handoff is not None and (not isinstance(handoff,HandoffSafety) or handoff.blocked()):raise UpdateError('SAFE_EXIT_HANDOFF_UNRESOLVED')
        require_handoff_ready(snapshot)
        path,item=self.validate(plan)
        check_previous_install(self.updates,plan,self.policy,self.testing,lock_owned=True)
        if self.testing:handle=self.runtime.open_process(plan.process)
        else:
            native_session.ready_and_wait(cancel)
            handle=native_session.handle
            self.runtime._native_session=native_session;self.runtime._plan=plan
        try:self.runtime.wait_exit(handle,timeout,cancel)
        finally:
            self.runtime.close_process(handle)
            if native_session is not None:native_session.handle=None
        if native_session is not None:
            if native_session.launcher_handle is not None:
                launcher=native_session.launcher_handle
                try:self.runtime.wait_exit(launcher,timeout,cancel)
                finally:self.runtime.close_process(launcher);native_session.launcher_handle=None
            native_session.exited=True
        if cancel.is_set():raise UpdateError('UPDATE_CANCELLED')
        # Recheck crypto/path after wait; holding the no-write/delete handle narrows TOCTOU for Windows.
        path,item=self.validate(plan)
        with self.runtime.hold_installer(path) as stream:
            if path.stat().st_size!=item.size or hashlib.file_digest(stream,'sha256').hexdigest()!=item.sha256:raise UpdateError('INSTALLER_TAMPERED_AFTER_DOWNLOAD')
            if cancel.is_set():raise UpdateError('UPDATE_CANCELLED')
            self.receipt(item,'INSTALL_OUTCOME_UNKNOWN')
            self._native_install_started=True
            code=self.runtime.install(path,self.installation,900)
            self._native_install_returned=True
            if code!=0:
                self.receipt(item,'INSTALL_FAILED');raise UpdateError('INSTALLER_FAILED_'+str(code))
        if self.runtime.installed_version(self.app)!=plan.version:raise UpdateError('INSTALLED_VERSION_MISMATCH')
        if not self.testing and registered_installation(plan.version)!=self.installation:raise UpdateError('UPGRADED_REGISTRATION_UNVERIFIED')
        self.receipt(item,'INSTALLED_RESTART_PENDING')
        if plan.restart:self.runtime.restart(self.app)
        self.receipt(item,'COMPLETED')
        return {'success':True,'simulated':self.testing,'actual_install':not self.testing}


def prepare_install_plan(service,item,downloaded,installation,identity,snapshot,handoff=None,restart=True):
    """Shared app→helper binding after safe shutdown; native launch stays locked."""
    require_handoff_ready(snapshot)
    if handoff is not None and (not isinstance(handoff,HandoffSafety) or handoff.blocked()):raise UpdateError('SAFE_EXIT_HANDOFF_UNRESOLVED')
    if type(identity) is not AppProcessIdentity or identity.pid<=0 or identity.creation_time<=0 or type(restart) is not bool:raise UpdateError('INVALID_PROCESS_IDENTITY')
    service.verify_file(downloaded,item)
    cache=service._cache()
    verified=service.validate_candidate(cache.get('release'),cache.get('envelope'))
    if verified!=item:raise UpdateError('VERIFIED_CANDIDATE_CHANGED')
    raw=canonical({'release':cache['release'],'manifest':cache['envelope'],'pid':identity.pid,
                   'creation_time':identity.creation_time,'restart':restart,'safe_exit_verified':True})
    policy='internal' if item.signature_status=='VERIFIED_INTERNAL_HTTPS_SHA256' else 'signed-stable'
    plan=load_install_plan(raw,service.directory,installation,service.keys,service.testing,policy)
    if plan.process!=identity or safe_path(downloaded,service.directory)!=plan.installer:raise UpdateError('FIXED_APP_INSTALL_LOCATION_REQUIRED')
    return raw,plan
