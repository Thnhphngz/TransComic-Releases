"""Explicit terminal-only production ceremony. Release/sign/install stay locked."""
from dataclasses import asdict
import getpass
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import warnings
from tempfile import TemporaryDirectory
from .release_adapters import safe_path
from .update.keytools import (WindowsKeyACL,production_storage,_provision,_backup,_restore,_load_pair)
from .update.metadata import UpdateError,verify_signature
from .update.signing import sign_payload


def native_drill():
    """No production key; encrypted test pair, backup and restore with real ACL."""
    acl=WindowsKeyACL(native=True)
    with TemporaryDirectory(prefix='TransComicSigning-native-') as directory:
        root=safe_path(directory);acl.restrict(root)
        password=secrets.token_bytes(32);recovery=secrets.token_bytes(32)
        info=_provision(root/'key',password,acl,'test')
        _backup(root/'key',password,root/'fixture.tc-keybackup',recovery,acl,'test')
        recovered=_restore(root/'fixture.tc-keybackup',recovery,root/'restored',password,acl,'test')
        if recovered.key_id!=info.key_id:raise UpdateError('PRODUCTION_KEY_RECOVERY_NOT_READY')
        key,pub=_load_pair(root/'restored',password,acl,'test')
        envelope=sign_payload({'fixture':'native recovery'},pub['key_id'],key)
        if verify_signature(envelope['payload'],envelope['signature'],{pub['key_id']:key.public_key().public_bytes_raw()})!='VERIFIED_ED25519':raise UpdateError('PRODUCTION_KEY_ACL_NOT_READY')
        return {'native_acl':True,'encrypted_test_recovery':True,'production_created':False}


def locations():
    local=os.environ.get('LOCALAPPDATA')
    if not local or os.name!='nt':raise UpdateError('PRODUCTION_KEY_ACL_NOT_READY')
    production=production_storage(Path(local)/'TransComicSigning/production')
    drill=production_storage(Path(local)/'TransComicSigning/recovery-drill')
    backup=safe_path(Path('D:/TransComic-SecureBackup/release-key.tc-keybackup'))
    if backup.is_relative_to(Path(__file__).resolve().parents[1]) or any((p/'.git').exists() for p in backup.parents):raise UpdateError('BACKUP_PATH_UNSAFE')
    if any(p.exists() for p in (production,drill,backup)):raise UpdateError('EXISTING_KEY_OR_BACKUP_PRESERVE_FOR_REVIEW')
    if production.parent.exists() and not WindowsKeyACL(native=True).verify(production.parent):raise UpdateError('STORAGE_PARENT_ACL_REQUIRES_REVIEW')
    if shutil.disk_usage(backup.anchor).free<10*1024*1024:raise UpdateError('BACKUP_DISK_SPACE_NOT_READY')
    if backup.parent.exists() and not WindowsKeyACL(native=True).verify(backup.parent):raise UpdateError('BACKUP_DIRECTORY_ACL_REQUIRES_REVIEW')
    return production,drill,backup


def interactive_provision():
    # No TTY / getpass fallback: never read a password from a pipe, environment or Codex.
    if not sys.stdin.isatty() or not sys.stdout.isatty():raise UpdateError('PROVISIONING BLOCKED — USER ACTION REQUIRED: direct terminal required; no key created')
    native_drill()
    production,drill,backup=locations()
    print(json.dumps({'production_directory':str(production),'encrypted_backup':str(backup),
                      'recovery_drill':str(drill),'overwrite':False,'release_locked':True},indent=2))
    if input('Type CREATE PRODUCTION KEY to confirm this one-time ceremony: ')!='CREATE PRODUCTION KEY':raise UpdateError('CONFIRMATION_REQUIRED: no key created')
    def password(prompt):
        def hidden(prompt):
            with warnings.catch_warnings():
                warnings.simplefilter('error',getpass.GetPassWarning)
                return getpass.getpass(prompt).encode('utf8')
        value=hidden(prompt)
        if len(value)<16:raise UpdateError('Passphrase must contain at least 16 UTF-8 bytes; no key created')
        if value!=hidden('Confirm passphrase: '):raise UpdateError('Passphrase confirmation mismatch; no key created')
        return value
    storage=password('Storage passphrase (password manager): ')
    recovery=password('Different offline recovery passphrase: ')
    if storage==recovery:raise UpdateError('Recovery and storage passphrases must differ; no key created')
    restored_password=password('Recovery drill storage passphrase: ')
    # Recheck every reservation immediately before effects. Partial results are never deleted/replaced.
    production,drill,backup=locations();acl=WindowsKeyACL(native=True)
    try:
        if not production.parent.exists():production.parent.mkdir();acl.restrict(production.parent)
        if not acl.verify(production.parent):raise UpdateError('PRODUCTION_KEY_ACL_NOT_READY')
        if not backup.parent.exists():backup.parent.mkdir();acl.restrict(backup.parent)
        if not acl.verify(backup.parent):raise UpdateError('PRODUCTION_KEY_ACL_NOT_READY')
        # Check actual encrypted/nonsecret write and ACL in backup location before key generation.
        probe=backup.parent/('write-check-'+secrets.token_hex(8)+'.tmp')
        with probe.open('xb') as stream:stream.write(b'TransComic nonsecret write check');stream.flush();os.fsync(stream.fileno())
        acl.restrict(probe)
        if not acl.verify(probe):raise UpdateError('PRODUCTION_KEY_ACL_NOT_READY')
        probe.unlink()
        info=_provision(production,storage,acl,'production')
        key,pub=_load_pair(production,storage,acl,'production')
        _backup(production,storage,backup,recovery,acl,'production')
        restored=_restore(backup,recovery,drill,restored_password,acl,'production')
        restored_key,restored_pub=_load_pair(drill,restored_password,acl,'production')
        if restored_pub!=pub or restored.key_id!=info.key_id:raise UpdateError('PRODUCTION_KEY_RECOVERY_NOT_READY')
        fixture={'fixture':'production recovery drill','version':'0.1.0'}
        signed=sign_payload(fixture,info.key_id,restored_key)
        verify_signature(fixture,signed['signature'],{info.key_id:key.public_key().public_bytes_raw()})
        result={'public':asdict(restored),'backup_verified':True,'recovery_drill_verified':True,
                'status':'OFFLINE_BACKUP_PENDING','pin_approved':False,'release_locked':True}
        (production/'provisioning-public-receipt.json').write_text(json.dumps(result,indent=2),encoding='utf8')
        print(json.dumps(result,indent=2))
        print('Copy release-key.tc-keybackup to USB and verify it; store recovery password separately. Public pin requires separate approval.')
        return 0
    except Exception:raise UpdateError('PROVISIONING BLOCKED — USER ACTION REQUIRED: preserve all partial key/backup/drill directories; do not generate another key') from None
