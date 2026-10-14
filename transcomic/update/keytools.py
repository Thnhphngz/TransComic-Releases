"""Encrypted Ed25519 provisioning implementation; production entry always locked.

Test keys have a distinct purpose and ID namespace. No secret is logged.
"""
import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (Encoding, PrivateFormat, BestAvailableEncryption, load_pem_private_key)
from ..release_adapters import locked, safe_path
from .metadata import UpdateError, strict_json
from .signing import sign_payload


class FakeACL:
    def __init__(self,restricted=True):self.restricted=restricted;self.calls=[]
    def restrict(self,path):self.calls.append(str(path))
    def verify(self,path):return self.restricted


class WindowsKeyACL:
    """Owner-only DACL on directory and encrypted key. Native execution locked."""
    def restrict(self,path):
        locked()
        import ctypes
        from ctypes import wintypes as w
        advapi=ctypes.WinDLL('advapi32',use_last_error=True)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetCurrentProcess.restype=w.HANDLE
        token=w.HANDLE();needed=w.DWORD()
        advapi.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,ctypes.POINTER(w.HANDLE)]
        advapi.GetTokenInformation.argtypes=[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD)]
        advapi.ConvertSidToStringSidW.argtypes=[w.LPVOID,ctypes.POINTER(w.LPWSTR)]
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes=[w.LPCWSTR,w.DWORD,ctypes.POINTER(w.LPVOID),ctypes.POINTER(w.DWORD)]
        advapi.SetFileSecurityW.argtypes=[w.LPCWSTR,w.DWORD,w.LPVOID]
        kernel.CloseHandle.argtypes=[w.HANDLE];kernel.LocalFree.argtypes=[w.LPVOID]
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(token)):raise UpdateError('KEY_ACL_TOKEN_UNAVAILABLE')
        sid_string=w.LPWSTR();descriptor=w.LPVOID()
        try:
            advapi.GetTokenInformation(token,1,None,0,ctypes.byref(needed))
            buffer=ctypes.create_string_buffer(needed.value)
            if not advapi.GetTokenInformation(token,1,buffer,needed,ctypes.byref(needed)):raise UpdateError('KEY_ACL_IDENTITY_UNAVAILABLE')
            sid=ctypes.cast(buffer,ctypes.POINTER(w.LPVOID))[0]
            if not advapi.ConvertSidToStringSidW(sid,ctypes.byref(sid_string)):raise UpdateError('KEY_ACL_SID_UNAVAILABLE')
            sddl='O:'+sid_string.value+'D:P(A;OICI;FA;;;'+sid_string.value+')'
            if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,ctypes.byref(descriptor),None):raise UpdateError('KEY_ACL_DESCRIPTOR_INVALID')
            if not advapi.SetFileSecurityW(str(path),1|4|0x80000000,descriptor):raise UpdateError('KEY_ACL_SET_FAILED')
        finally:
            if descriptor:kernel.LocalFree(descriptor)
            if sid_string:kernel.LocalFree(sid_string)
            kernel.CloseHandle(token)

    def verify(self,path):
        locked()
        import ctypes
        from ctypes import wintypes as w
        advapi=ctypes.WinDLL('advapi32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        advapi.GetNamedSecurityInfoW.argtypes=[w.LPWSTR,ctypes.c_int,w.DWORD,ctypes.POINTER(w.LPVOID),w.LPVOID,ctypes.POINTER(w.LPVOID),w.LPVOID,ctypes.POINTER(w.LPVOID)]
        advapi.GetSecurityDescriptorControl.argtypes=[w.LPVOID,ctypes.POINTER(w.WORD),ctypes.POINTER(w.DWORD)]
        advapi.GetAce.argtypes=[w.LPVOID,w.DWORD,ctypes.POINTER(w.LPVOID)]
        advapi.EqualSid.argtypes=[w.LPVOID,w.LPVOID];kernel.LocalFree.argtypes=[w.LPVOID]
        owner=w.LPVOID();dacl=w.LPVOID();descriptor=w.LPVOID()
        if advapi.GetNamedSecurityInfoW(str(path),1,1|4,ctypes.byref(owner),None,ctypes.byref(dacl),None,ctypes.byref(descriptor))!=0:return False
        try:
            control=w.WORD();revision=w.DWORD()
            if not owner or not dacl or not advapi.GetSecurityDescriptorControl(descriptor,ctypes.byref(control),ctypes.byref(revision)) or not control.value&0x1000:return False
            count=ctypes.cast(dacl,ctypes.POINTER(w.WORD))[2]
            if not 1<=count<=2:return False
            for i in range(count):
                ace=w.LPVOID()
                if not advapi.GetAce(dacl,i,ctypes.byref(ace)):return False
                if ctypes.cast(ace,ctypes.POINTER(w.BYTE))[0]!=0:return False
                mask=ctypes.cast(ace,ctypes.POINTER(w.DWORD))[1]
                if mask!=0x1f01ff or not advapi.EqualSid(owner,ctypes.c_void_p(ace.value+8)):return False
            return True
        finally:kernel.LocalFree(descriptor)


@dataclass(frozen=True)
class PublicKeyInfo:
    key_id:str
    public_key:str
    purpose:str
    backup_warning:str|None


def _provision(directory,password,acl,purpose):
    directory=safe_path(directory)
    if not isinstance(password,bytes) or len(password)<16:raise UpdateError('Strong nonempty key passphrase required')
    if directory.exists():raise UpdateError('KEY_DIRECTORY_EXISTS_NO_OVERWRITE')
    directory.mkdir(parents=True,mode=0o700)
    try:
        acl.restrict(directory)
        if not acl.verify(directory):raise UpdateError('KEY_FILE_PERMISSIONS_UNVERIFIED')
        key=Ed25519PrivateKey.generate();pub=key.public_key().public_bytes_raw()
        key_id=('test-' if purpose=='test' else 'ed25519-')+hashlib.sha256(pub).hexdigest()[:24]
        encrypted=key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,BestAvailableEncryption(password))
        private=directory/'encrypted.testkey' if purpose=='test' else directory/'encrypted-private.pem'
        with private.open('xb') as stream:stream.write(encrypted);stream.flush();os.fsync(stream.fileno())
        acl.restrict(private)
        if not acl.verify(private):raise UpdateError('KEY_FILE_PERMISSIONS_UNVERIFIED')
        info=PublicKeyInfo(key_id,base64.b64encode(pub).decode(),purpose,'ENCRYPTED_OFFLINE_BACKUP_NOT_VERIFIED')
        with (directory/'public-key.json').open('x',encoding='utf8') as stream:
            json.dump({'key_id':key_id,'public_key':info.public_key,'purpose':purpose},stream)
        # Match private/public via a signature rather than exposing private serialization.
        proof=key.sign(b'TransComic provisioning pair check');key.public_key().verify(proof,b'TransComic provisioning pair check')
        return info
    except Exception:
        # Preserve incomplete directory for explicit review, never overwrite/retry new key silently.
        raise UpdateError('KEY_PROVISIONING_FAILED_PRESERVE_FOR_REVIEW') from None


def production_provision(directory,password):
    locked()  # before mkdir, RNG, serialization, ACL changes
    if safe_path(directory).is_relative_to(Path(__file__).resolve().parents[2]):raise UpdateError('Private signing keys must be outside program/source')
    return _provision(directory,password,WindowsKeyACL(),'production')


def test_provision(directory,password,acl=None):
    acl=acl or FakeACL()
    if type(acl) is not FakeACL:raise UpdateError('Test provisioning requires fake ACL')
    return _provision(directory,password,acl,'test')
test_provision.__test__=False


def test_sign(directory,password,payload,acl=None):
    directory=safe_path(directory);acl=acl or FakeACL()
    info=strict_json((directory/'public-key.json').read_bytes())
    private=directory/'encrypted.testkey'
    if info.get('purpose')!='test' or not info.get('key_id','').startswith('test-') or not acl.verify(private):raise UpdateError('TEST_KEY_PURPOSE_OR_ACL_INVALID')
    try:key=load_pem_private_key(private.read_bytes(),password=password)
    except (ValueError,TypeError):raise UpdateError('ENCRYPTED_KEY_LOAD_FAILED') from None
    if not isinstance(key,Ed25519PrivateKey) or base64.b64encode(key.public_key().public_bytes_raw()).decode()!=info['public_key']:raise UpdateError('KEY_PAIR_MISMATCH')
    return sign_payload(payload,info['key_id'],key)
test_sign.__test__=False


def production_sign_encrypted(directory,password,payload):
    locked()
    directory=safe_path(directory);private=directory/'encrypted-private.pem'
    if not WindowsKeyACL().verify(private):raise UpdateError('KEY_FILE_PERMISSIONS_UNVERIFIED')
    info=strict_json((directory/'public-key.json').read_bytes())
    if info.get('purpose')!='production' or info.get('key_id','').startswith('test-'):raise UpdateError('PRODUCTION_SIGNING_NOT_READY')
    key=load_pem_private_key(private.read_bytes(),password=password)
    if not isinstance(key,Ed25519PrivateKey) or base64.b64encode(key.public_key().public_bytes_raw()).decode()!=info['public_key']:raise UpdateError('KEY_PAIR_MISMATCH')
    return sign_payload(payload,info['key_id'],key)
