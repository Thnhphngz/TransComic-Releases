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
from .metadata import UpdateError, strict_json, canonical
from .signing import sign_payload


class FakeACL:
    def __init__(self,restricted=True):self.restricted=restricted;self.calls=[]
    def restrict(self,path):self.calls.append(str(path))
    def verify(self,path):return self.restricted


class WindowsKeyACL:
    """Owner-only DACL; native opt-in is for isolated provisioning, not release."""
    def __init__(self,*,native=False):self.native=native
    def restrict(self,path):
        if not self.native:locked()
        path=safe_path(path)
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
        if not self.native:locked()
        path=safe_path(path)
        import ctypes
        from ctypes import wintypes as w
        advapi=ctypes.WinDLL('advapi32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        advapi.GetNamedSecurityInfoW.argtypes=[w.LPWSTR,ctypes.c_int,w.DWORD,ctypes.POINTER(w.LPVOID),w.LPVOID,ctypes.POINTER(w.LPVOID),w.LPVOID,ctypes.POINTER(w.LPVOID)]
        advapi.GetSecurityDescriptorControl.argtypes=[w.LPVOID,ctypes.POINTER(w.WORD),ctypes.POINTER(w.DWORD)]
        advapi.GetAce.argtypes=[w.LPVOID,w.DWORD,ctypes.POINTER(w.LPVOID)]
        advapi.EqualSid.argtypes=[w.LPVOID,w.LPVOID];kernel.LocalFree.argtypes=[w.LPVOID]
        kernel.GetCurrentProcess.restype=w.HANDLE
        advapi.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,ctypes.POINTER(w.HANDLE)]
        advapi.GetTokenInformation.argtypes=[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD,ctypes.POINTER(w.DWORD)]
        kernel.CloseHandle.argtypes=[w.HANDLE]
        owner=w.LPVOID();dacl=w.LPVOID();descriptor=w.LPVOID()
        if advapi.GetNamedSecurityInfoW(str(path),1,1|4,ctypes.byref(owner),None,ctypes.byref(dacl),None,ctypes.byref(descriptor))!=0:return False
        try:
            token=w.HANDLE();needed=w.DWORD()
            if not advapi.OpenProcessToken(kernel.GetCurrentProcess(),8,ctypes.byref(token)):return False
            try:
                advapi.GetTokenInformation(token,1,None,0,ctypes.byref(needed))
                buffer=ctypes.create_string_buffer(needed.value)
                if not advapi.GetTokenInformation(token,1,buffer,needed,ctypes.byref(needed)):return False
                sid=ctypes.cast(buffer,ctypes.POINTER(w.LPVOID))[0]
                if not owner or not advapi.EqualSid(owner,sid):return False
            finally:kernel.CloseHandle(token)
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
    directory=production_storage(directory)
    return _provision(directory,password,WindowsKeyACL(),'production')


def test_provision(directory,password,acl=None):
    acl=acl or FakeACL()
    if type(acl) is not FakeACL:raise UpdateError('Test provisioning requires fake ACL')
    return _provision(directory,password,acl,'test')
test_provision.__test__=False


def production_storage(directory):
    """Pure path policy; no mkdir, ACL, DPAPI or key generation."""
    directory=safe_path(directory)
    local=os.environ.get('LOCALAPPDATA')
    if not local or not directory.is_relative_to(safe_path(Path(local)/'TransComicSigning')):
        raise UpdateError('PRODUCTION_SIGNING_STORAGE_NOT_READY: dedicated local profile required')
    if directory.is_relative_to(Path(__file__).resolve().parents[2]) or any((p/'.git').exists() for p in (directory,*directory.parents)):
        raise UpdateError('Private signing keys must be outside program/source/Git')
    for name in ('OneDrive','OneDriveConsumer','OneDriveCommercial'):
        if os.environ.get(name) and directory.is_relative_to(safe_path(os.environ[name])):
            raise UpdateError('Cloud signing key storage prohibited')
    return directory


def test_sign(directory,password,payload,acl=None):
    directory=safe_path(directory);acl=acl or FakeACL()
    if type(acl) is not FakeACL:raise UpdateError('Test signing requires fake ACL')
    key,info=_load_pair(directory,password,acl,'test')
    return sign_payload(payload,info['key_id'],key)
test_sign.__test__=False


def _load_pair(directory,password,acl,purpose):
    directory=safe_path(directory)
    private=safe_path(directory/('encrypted.testkey' if purpose=='test' else 'encrypted-private.pem'),directory)
    public=safe_path(directory/'public-key.json',directory)
    if not acl.verify(directory) or not acl.verify(private):raise UpdateError('KEY_FILE_PERMISSIONS_UNVERIFIED')
    try:
        if private.stat().st_size>16384 or public.stat().st_size>4096:raise ValueError()
        info=strict_json(public.read_bytes())
        key=load_pem_private_key(private.read_bytes(),password=password)
        if not isinstance(key,Ed25519PrivateKey):raise ValueError()
        pub=key.public_key().public_bytes_raw()
        key_id=('test-' if purpose=='test' else 'ed25519-')+hashlib.sha256(pub).hexdigest()[:24]
        if info!={'purpose':purpose,'key_id':key_id,'public_key':base64.b64encode(pub).decode()}:raise ValueError()
        proof=key.sign(b'TransComic recovery pair check')
        key.public_key().verify(proof,b'TransComic recovery pair check')
        return key,info
    except Exception:raise UpdateError('ENCRYPTED_KEY_LOAD_OR_PAIR_FAILED') from None


def _recovery_key(password,salt):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    if not isinstance(password,bytes) or len(password)<16:raise UpdateError('Strong recovery passphrase required')
    return Scrypt(salt=salt,length=32,n=2**17,r=8,p=1).derive(password)


def _backup(directory,password,destination,recovery_password,acl,purpose):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key,info=_load_pair(directory,password,acl,purpose)
    destination=safe_path(destination)
    if destination.exists():raise UpdateError('BACKUP_EXISTS_NO_OVERWRITE')
    if not destination.parent.is_dir():raise UpdateError('BACKUP_PARENT_REQUIRED')
    # Portable recovery encryption: no Windows identity dependency, no plaintext file.
    salt=os.urandom(16);nonce=os.urandom(12)
    encrypted=key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,BestAvailableEncryption(recovery_password))
    header={'format':1,'kdf':'scrypt-131072-8-1','cipher':'AES-256-GCM',**info,
            'salt':base64.b64encode(salt).decode(),'nonce':base64.b64encode(nonce).decode()}
    ciphertext=AESGCM(_recovery_key(recovery_password,salt)).encrypt(nonce,encrypted,canonical(header))
    data=canonical(dict(header,ciphertext=base64.b64encode(ciphertext).decode()))
    with destination.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    acl.restrict(destination)
    if not acl.verify(destination):raise UpdateError('KEY_FILE_PERMISSIONS_UNVERIFIED')
    return PublicKeyInfo(info['key_id'],info['public_key'],purpose,'RESTORE_DRILL_REQUIRED')


def _restore(backup,recovery_password,directory,password,acl,purpose):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    backup=safe_path(backup);directory=safe_path(directory)
    if directory.exists():raise UpdateError('KEY_DIRECTORY_EXISTS_NO_OVERWRITE')
    if not isinstance(password,bytes) or len(password)<16:raise UpdateError('Strong nonempty key passphrase required')
    try:
        if not acl.verify(backup) or backup.stat().st_size>32768:raise ValueError()
        header=strict_json(backup.read_bytes())
        if set(header)!={'format','kdf','cipher','purpose','key_id','public_key','salt','nonce','ciphertext'}:raise ValueError()
        if header['format']!=1 or header['kdf']!='scrypt-131072-8-1' or header['cipher']!='AES-256-GCM' or header['purpose']!=purpose:raise ValueError()
        ciphertext=base64.b64decode(header.pop('ciphertext'),validate=True)
        salt=base64.b64decode(header['salt'],validate=True);nonce=base64.b64decode(header['nonce'],validate=True)
        if len(salt)!=16 or len(nonce)!=12:raise ValueError()
        encrypted=AESGCM(_recovery_key(recovery_password,salt)).decrypt(nonce,ciphertext,canonical(header))
        key=load_pem_private_key(encrypted,password=recovery_password)
        if not isinstance(key,Ed25519PrivateKey):raise ValueError()
        pub=key.public_key().public_bytes_raw()
        key_id=('test-' if purpose=='test' else 'ed25519-')+hashlib.sha256(pub).hexdigest()[:24]
        if key_id!=header['key_id'] or base64.b64encode(pub).decode()!=header['public_key']:raise ValueError()
        output=key.private_bytes(Encoding.PEM,PrivateFormat.PKCS8,BestAvailableEncryption(password))
    except Exception:raise UpdateError('PRODUCTION_KEY_RECOVERY_NOT_READY: backup verification failed') from None
    # All cryptographic validation happens before creating the destination.
    directory.mkdir(parents=True,mode=0o700)
    try:
        acl.restrict(directory)
        if not acl.verify(directory):raise ValueError()
        private=directory/('encrypted.testkey' if purpose=='test' else 'encrypted-private.pem')
        with private.open('xb') as stream:stream.write(output);stream.flush();os.fsync(stream.fileno())
        acl.restrict(private)
        if not acl.verify(private):raise ValueError()
        with (directory/'public-key.json').open('x',encoding='utf8') as stream:
            json.dump({name:header[name] for name in ('purpose','key_id','public_key')},stream)
        _load_pair(directory,password,acl,purpose)
    except Exception:raise UpdateError('KEY_RESTORE_FAILED_PRESERVE_FOR_REVIEW') from None
    return PublicKeyInfo(key_id,header['public_key'],purpose,None)


def test_backup(directory,password,destination,recovery_password,acl=None):
    acl=acl or FakeACL()
    if type(acl) is not FakeACL:raise UpdateError('Test backup requires fake ACL')
    return _backup(directory,password,destination,recovery_password,acl,'test')
test_backup.__test__=False


def test_restore(backup,recovery_password,directory,password,acl=None):
    acl=acl or FakeACL()
    if type(acl) is not FakeACL:raise UpdateError('Test recovery requires fake ACL')
    return _restore(backup,recovery_password,directory,password,acl,'test')
test_restore.__test__=False


def production_backup(directory,password,destination,recovery_password):
    locked()  # never read production key without separate reviewed activation
    directory=production_storage(directory)
    destination=safe_path(destination)
    if destination.is_relative_to(Path(__file__).resolve().parents[2]) or any((p/'.git').exists() for p in (destination.parent,*destination.parents)):
        raise UpdateError('Encrypted backup must be outside source/Git/release artifacts')
    return _backup(directory,password,destination,recovery_password,WindowsKeyACL(),'production')


def production_restore(backup,recovery_password,directory,password):
    locked()  # before decrypt/mkdir/ACL; production recovery needs its own approval
    directory=production_storage(directory)
    return _restore(backup,recovery_password,directory,password,WindowsKeyACL(),'production')


def production_sign_encrypted(directory,password,payload):
    locked()
    directory=production_storage(directory)
    key,info=_load_pair(directory,password,WindowsKeyACL(),'production')
    from .metadata import PRODUCTION_KEYS,PRODUCTION_KEY_STATUS
    if (PRODUCTION_KEYS.get(info['key_id'])!=key.public_key().public_bytes_raw() or
            PRODUCTION_KEY_STATUS.get(info['key_id'])!='active'):raise UpdateError('PRODUCTION_SIGNING_NOT_READY')
    return sign_payload(payload,info['key_id'],key)
