"""Windows DPAPI storage. No plaintext fallback."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _crypt(data: bytes, decrypt: bool) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Windows DPAPI is required for API key storage")
    source, keepalive = _blob(data)
    output = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    fn = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    if decrypt:
        ok = fn(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output))
    else:
        ok = fn(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(output.pbData)


def protect_key(key: str) -> bytes:
    return _crypt(key.encode("utf-8"), False)


def unprotect_key(value: bytes) -> str:
    return _crypt(value, True).decode("utf-8")
