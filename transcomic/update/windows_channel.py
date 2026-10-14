"""Local, bounded, overlapped IPC for the existing external update helper.

Only bytes are transported (never pickle). OS pipe peer PIDs are authenticated
against installed executable identities by windows_helper. No installer lives here.
"""
import ctypes
from ctypes import wintypes as w
import os
import re
import time
from .metadata import UpdateError

LIMIT = 128 * 1024


def channel_name(nonce):
    if not isinstance(nonce, str) or not re.fullmatch('[0-9a-f]{64}', nonce):
        raise UpdateError('INVALID_HANDOFF_CHANNEL')
    return '\\\\.\\pipe\\TransComic-Update-' + nonce


def _security():
    """DACL limited to this token's user and SYSTEM, no inherited handles."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    advapi = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [w.LPVOID]
    advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    advapi.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD, ctypes.POINTER(w.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [w.LPVOID, ctypes.POINTER(w.LPWSTR)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(w.LPVOID), w.LPVOID]
    token = w.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
        raise UpdateError('HANDOFF_TOKEN_UNAVAILABLE')
    sid_text = w.LPWSTR()
    descriptor = w.LPVOID()
    try:
        size = w.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not 0 < size.value < 65536:
            raise UpdateError('HANDOFF_TOKEN_INVALID')
        data = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, data, size, ctypes.byref(size)):
            raise UpdateError('HANDOFF_TOKEN_INVALID')
        sid = ctypes.cast(data, ctypes.POINTER(w.LPVOID))[0]
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(sid_text)):
            raise UpdateError('HANDOFF_SID_INVALID')
        sddl = 'D:P(A;;GA;;;SY)(A;;GA;;;' + sid_text.value + ')'
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None):
            raise UpdateError('HANDOFF_DACL_INVALID')
        return descriptor
    finally:
        kernel.CloseHandle(token)
        if sid_text:
            kernel.LocalFree(ctypes.cast(sid_text, w.LPVOID))


class WindowsChannel:
    def __init__(self, handle, server):
        self.handle = handle
        self.server = server

    @classmethod
    def listen(cls, nonce):
        if os.name != 'nt':
            raise UpdateError('WINDOWS_HANDOFF_REQUIRED')
        class Attributes(ctypes.Structure):
            _fields_ = [('length', w.DWORD), ('descriptor', w.LPVOID), ('inherit', w.BOOL)]
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateNamedPipeW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, w.DWORD, ctypes.POINTER(Attributes)]
        kernel.CreateNamedPipeW.restype = w.HANDLE
        kernel.LocalFree.argtypes = [w.LPVOID]
        descriptor = _security()
        try:
            attrs = Attributes(ctypes.sizeof(Attributes), descriptor, False)
            # Duplex, overlapped, first instance; message mode and reject remote.
            handle = kernel.CreateNamedPipeW(channel_name(nonce), 3 | 0x40000000 | 0x80000,
                                            4 | 2 | 8, 1, LIMIT, LIMIT, 0, ctypes.byref(attrs))
            if handle == ctypes.c_void_p(-1).value:
                raise UpdateError('HANDOFF_CHANNEL_UNAVAILABLE')
            return cls(handle, True)
        finally:
            kernel.LocalFree(descriptor)

    @classmethod
    def connect(cls, nonce):
        if os.name != 'nt':
            raise UpdateError('WINDOWS_HANDOFF_REQUIRED')
        import _winapi as api
        handle=None
        try:
            handle = api.CreateFile(channel_name(nonce), api.GENERIC_READ | api.GENERIC_WRITE,
                                    0, api.NULL, api.OPEN_EXISTING, api.FILE_FLAG_OVERLAPPED, api.NULL)
            api.SetNamedPipeHandleState(handle, api.PIPE_READMODE_MESSAGE, None, None)
            return cls(handle, False)
        except OSError:
            if handle is not None:api.CloseHandle(handle)
            raise UpdateError('HANDOFF_CHANNEL_UNAVAILABLE') from None

    def _wait(self, operation, cancel, timeout):
        import _winapi as api
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if cancel.is_set():
                    raise UpdateError('UPDATE_CANCELLED')
                if api.WaitForMultipleObjects([operation.event], False, 25) == 0:
                    # ConnectNamedPipe may synthesize a signalled event when
                    # the client connected first. Complete collection with
                    # wait=True, as CPython's PipeListener does; False can
                    # return ERROR_IO_INCOMPLETE on this already-connected path.
                    return operation.GetOverlappedResult(True)
            raise UpdateError('HANDOFF_TIMEOUT')
        except BaseException:
            operation.cancel()
            operation.GetOverlappedResult(True)
            raise

    def accept(self, cancel, timeout=30):
        import _winapi as api
        operation = api.ConnectNamedPipe(self.handle, overlapped=True)
        _, error = self._wait(operation, cancel, timeout)
        if error:
            raise UpdateError('HANDOFF_CONNECT_FAILED')

    def peer_pid(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        method = kernel.GetNamedPipeClientProcessId if self.server else kernel.GetNamedPipeServerProcessId
        method.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        pid = w.DWORD()
        if not method(self.handle, ctypes.byref(pid)) or not pid.value:
            raise UpdateError('HANDOFF_PEER_UNVERIFIED')
        return pid.value

    def send(self, raw, cancel, timeout=15):
        if not isinstance(raw, bytes) or not 0 < len(raw) <= LIMIT:
            raise UpdateError('HANDOFF_MESSAGE_SIZE')
        import _winapi as api
        operation, error = api.WriteFile(self.handle, raw, overlapped=True)
        count, error = self._wait(operation, cancel, timeout) if error==api.ERROR_IO_PENDING else operation.GetOverlappedResult(True)
        if error or count != len(raw):
            raise UpdateError('HANDOFF_WRITE_FAILED')

    def receive(self, cancel, timeout=30):
        import _winapi as api
        operation, error = api.ReadFile(self.handle, LIMIT, overlapped=True)
        count, error = self._wait(operation, cancel, timeout) if error==api.ERROR_IO_PENDING else operation.GetOverlappedResult(True)
        if error or not 0 < count <= LIMIT:
            raise UpdateError('HANDOFF_READ_FAILED_OR_OVERSIZE')
        return bytes(operation.getbuffer())[:count]

    def close(self):
        if self.handle is not None:
            import _winapi as api
            handle, self.handle = self.handle, None
            api.CloseHandle(handle)
