"""Windows external installer implementation; OS execution is locked in B2.1.

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
from uuid import uuid4
from ..release_adapters import locked, safe_path
from ..version import VERSION
from .metadata import UpdateError, candidate as validate_candidate, PRODUCTION_KEYS, strict_json
from .install import SafetySnapshot


def registered_installation():
    locked()
    import winreg
    key=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{CB58C770-47B7-42DC-A2CA-409DDF456487}_is1'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key) as handle:
            location=winreg.QueryValueEx(handle,'InstallLocation')[0]
    except OSError:raise UpdateError('REGISTERED_PER_USER_INSTALLATION_REQUIRED') from None
    directory=safe_path(location)
    if not directory.is_relative_to(Path.home().resolve()):raise UpdateError('PER_USER_INSTALLATION_LOCATION_UNVERIFIED')
    return directory


class HelperHandoff:
    """Copy a verified helper away from files the installer will replace."""
    def __init__(self,updates,installation,authenticode,commands=None):
        from ..release_adapters import commands_or_default
        self.updates=safe_path(updates);self.installation=safe_path(installation)
        self.authenticode=authenticode;self.commands=commands_or_default(commands)

    def launch(self,plan_bytes):
        locked()  # before temp directory/copy/Popen or signature commands
        from ..release_adapters import execute
        original=safe_path(self.installation/'TransComic-UpdateHelper.exe',self.installation)
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
        self.authenticode.verify(copied)
        load_install_plan(plan_bytes,self.updates,self.installation)
        plan_path=directory/'install-plan.json'
        with plan_path.open('xb') as stream:stream.write(plan_bytes);stream.flush();os.fsync(stream.fileno())
        # Helper opens original process handle before the caller performs final process exit.
        process=subprocess.Popen([str(copied),'--plan',str(plan_path)],cwd=directory,shell=False,creationflags=0x08000000)
        return process.pid

    def preview(self,nonce='test-handoff'):
        if not nonce.isalnum() and nonce!='test-handoff':raise UpdateError('Invalid handoff directory identity')
        return {'helper':self.updates/('handoff-'+nonce)/'TransComic-UpdateHelper.exe',
                'installation':self.installation,'overwrites_running_helper':False}


@dataclass(frozen=True)
class AppProcessIdentity:
    pid:int
    creation_time:int
    image:str


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


def load_install_plan(raw,updates,installation,keys=None,testing=False):
    if len(raw)>128*1024:raise UpdateError('INSTALL_PLAN_SIZE_LIMIT')
    value=strict_json(raw)
    if not isinstance(value,dict) or set(value)!={'release','manifest','pid','creation_time','restart','safe_exit_verified'}:
        raise UpdateError('INSTALL_PLAN_FIELDS_REJECTED')
    if type(value['pid']) is not int or type(value['creation_time']) is not int or type(value['restart']) is not bool or value['safe_exit_verified'] is not True:raise UpdateError('INSTALL_PLAN_SAFETY_OR_PROCESS_INVALID')
    item=validate_candidate(value['release'],value['manifest'],PRODUCTION_KEYS if keys is None else keys,testing=testing)
    if item.signature_status!='VERIFIED_ED25519':raise UpdateError('PRODUCTION_SIGNING_NOT_READY')
    # No JSON installer path, executable path, install directory or public key is accepted.
    process=AppProcessIdentity(value['pid'],value['creation_time'],str(safe_path(installation)/'TransComic.exe'))
    return InstallPlan(item.version,safe_path(Path(updates)/item.filename,updates),item.size,item.sha256,
                       value['release'],value['manifest'],process,value['restart'])


class WindowsRuntime:
    def open_process(self,identity):
        locked()
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
        locked()
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD]
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if cancel.is_set():raise UpdateError('UPDATE_CANCELLED')
            result=kernel.WaitForSingleObject(handle,100)
            if result==0:return
            if result!=258:raise UpdateError('PROCESS_WAIT_FAILED')
        raise UpdateError('PROCESS_EXIT_TIMEOUT')

    def close_process(self,handle):
        locked()
        kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle(handle)

    def hold_installer(self,path):
        locked()
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
        locked()
        try:
            result=subprocess.run([str(path),'/VERYSILENT','/NORESTART','/SP-',
                                   '/DIR='+str(install_directory)],cwd=install_directory,shell=False,
                                  timeout=timeout,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:raise UpdateError('INSTALLER_TIMEOUT_MANUAL_RECOVERY') from None
        except OSError:raise UpdateError('INSTALLER_LAUNCH_DENIED_OR_UAC_CANCELLED') from None
        return result.returncode

    def installed_version(self,app):
        locked()
        dll=ctypes.WinDLL('version',use_last_error=True)
        dll.GetFileVersionInfoSizeW.argtypes=[w.LPCWSTR,ctypes.POINTER(w.DWORD)]
        dll.GetFileVersionInfoW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID]
        dll.VerQueryValueW.argtypes=[w.LPVOID,w.LPCWSTR,ctypes.POINTER(w.LPVOID),ctypes.POINTER(w.UINT)]
        unused=w.DWORD();size=dll.GetFileVersionInfoSizeW(str(app),ctypes.byref(unused))
        if not size:raise UpdateError('INSTALLED_VERSION_UNVERIFIED')
        buffer=ctypes.create_string_buffer(size)
        if not dll.GetFileVersionInfoW(str(app),0,size,buffer):raise UpdateError('INSTALLED_VERSION_UNVERIFIED')
        pointer=w.LPVOID();length=w.UINT()
        if not dll.VerQueryValueW(buffer,'\\',ctypes.byref(pointer),ctypes.byref(length)):raise UpdateError('INSTALLED_VERSION_UNVERIFIED')
        fields=ctypes.cast(pointer,ctypes.POINTER(w.DWORD));ms,ls=fields[2],fields[3]
        return f'{ms>>16}.{ms&65535}.{ls>>16}'

    def restart(self,app):
        locked()
        process=subprocess.Popen([str(app)],cwd=app.parent,shell=False,creationflags=0x08000000)
        time.sleep(1)
        if process.poll() is not None:raise UpdateError('NEW_APP_START_FAILED')
        return process.pid


class FakeWindowsRuntime:
    def __init__(self):
        self.identity=None;self.process_exited=True;self.fail=None;self.version='0.2.0';self.calls=[]
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
    def __init__(self,updates,installation,runtime=None,keys=None):
        if runtime is not None and type(runtime) is not FakeWindowsRuntime:raise UpdateError('Concrete mock runtime required')
        if runtime is None and keys is not None:raise UpdateError('Production trust cannot come from install plan')
        self.runtime=runtime or WindowsRuntime();self.testing=type(self.runtime) is FakeWindowsRuntime
        self.keys=keys if self.testing else PRODUCTION_KEYS
        self.updates=safe_path(updates);self.installation=safe_path(installation)
        self.app=self.installation/'TransComic.exe'

    def validate(self,plan):
        item=validate_candidate(plan.release,plan.envelope,self.keys,testing=self.testing)
        path=safe_path(plan.installer,self.updates)
        if item.signature_status!='VERIFIED_ED25519':raise UpdateError('PRODUCTION_SIGNING_NOT_READY')
        if (plan.version,path.name,plan.size,plan.sha256)!=(item.version,item.filename,item.size,item.sha256):raise UpdateError('INSTALL_PLAN_SIGNATURE_BINDING_MISMATCH')
        if plan.mode!='per_user' or Path(plan.process.image).resolve()!=self.app.resolve():raise UpdateError('FIXED_APP_INSTALL_LOCATION_REQUIRED')
        if type(plan.process.pid) is not int or plan.process.pid<=0 or plan.process.creation_time<=0:raise UpdateError('INVALID_PROCESS_IDENTITY')
        return path,item

    def run(self,plan,snapshot,cancel,timeout=60,handoff=None):
        if not self.testing:locked()  # before native handle acquisition or executable execution
        if handoff is not None and (not isinstance(handoff,HandoffSafety) or handoff.blocked()):raise UpdateError('SAFE_EXIT_HANDOFF_UNRESOLVED')
        if not isinstance(snapshot,SafetySnapshot) or snapshot.reasons():raise UpdateError('SAFE_EXIT_BUSY_OR_UNVERIFIED')
        path,item=self.validate(plan)
        handle=self.runtime.open_process(plan.process)
        try:self.runtime.wait_exit(handle,timeout,cancel)
        finally:self.runtime.close_process(handle)
        if cancel.is_set():raise UpdateError('UPDATE_CANCELLED')
        # Recheck crypto/path after wait; holding the no-write/delete handle narrows TOCTOU for Windows.
        path,item=self.validate(plan)
        with self.runtime.hold_installer(path) as stream:
            if path.stat().st_size!=item.size or hashlib.file_digest(stream,'sha256').hexdigest()!=item.sha256:raise UpdateError('INSTALLER_TAMPERED_AFTER_DOWNLOAD')
            if cancel.is_set():raise UpdateError('UPDATE_CANCELLED')
            code=self.runtime.install(path,self.installation,900)
            if code!=0:raise UpdateError('INSTALLER_FAILED_'+str(code))
        if self.runtime.installed_version(self.app)!=plan.version:raise UpdateError('INSTALLED_VERSION_MISMATCH')
        if plan.restart:self.runtime.restart(self.app)
        return {'success':True,'simulated':self.testing,'actual_install':not self.testing}
