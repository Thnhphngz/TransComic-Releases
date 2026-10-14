"""Isolated terminal provisioning; release stays locked, no password in argv."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import secrets
import getpass
import sys
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from transcomic.update.keytools import test_provision,production_provision,test_backup,test_restore,production_backup,production_restore
from transcomic.update.metadata import UpdateError
from transcomic.release_adapters import locked


def main(argv=None):
    parser=argparse.ArgumentParser(description='Isolated provisioning ceremony; explicit terminal confirmation; no build/release')
    parser.add_argument('--test',action='store_true');parser.add_argument('--directory',type=Path)
    parser.add_argument('--operation',choices=('provision','backup','restore'),default='provision')
    parser.add_argument('--backup-file',type=Path)
    parser.add_argument('--interactive',action='store_true',help='Direct terminal only: confirmed production creation + backup + drill')
    parser.add_argument('--native-check',action='store_true',help='Native ACL and encrypted test-key recovery; no production key')
    args=parser.parse_args(argv)
    if args.interactive or args.native_check:
        from transcomic.provisioning import interactive_provision,native_drill
        try:
            if args.test or args.directory or args.backup_file or args.operation!='provision':raise UpdateError('Ambiguous provisioning options')
            if args.native_check:print(json.dumps(native_drill()));return 0
            return interactive_provision()
        except (UpdateError,OSError,getpass.GetPassWarning,EOFError,KeyboardInterrupt):print('PROVISIONING BLOCKED — USER ACTION REQUIRED: inspect conditions; preserve any partial keys; no release action');return 2
    if args.test:
        with TemporaryDirectory() as directory:
            password=secrets.token_bytes(32);recovery=secrets.token_bytes(32)
            original=Path(directory)/'test-key'
            info=test_provision(original,password)
            backup=Path(directory)/'recovery.tc-keybackup'
            test_backup(original,password,backup,recovery)
            restored=test_restore(backup,recovery,Path(directory)/'restored',secrets.token_bytes(32))
            assert restored.key_id==info.key_id
            info=restored
            print(json.dumps(asdict(info)))
        return 0
    try:
        locked()  # no production password prompt/RNG/file access in B2.1
        if args.directory is None:raise UpdateError('Explicit private signing directory required')
        password=getpass.getpass('Encrypted signing key passphrase: ').encode('utf8')
        if password!=getpass.getpass('Confirm passphrase: ').encode('utf8'):raise UpdateError('Passphrase mismatch')
        if args.operation=='provision':
            production_provision(args.directory,password)
        else:
            if args.backup_file is None:raise UpdateError('Explicit encrypted backup file required')
            recovery=getpass.getpass('Offline recovery passphrase: ').encode('utf8')
            if args.operation=='backup':
                if recovery!=getpass.getpass('Confirm recovery passphrase: ').encode('utf8'):raise UpdateError('Passphrase mismatch')
                production_backup(args.directory,password,args.backup_file,recovery)
            else:
                production_restore(args.backup_file,recovery,args.directory,password)
    except UpdateError:print('PRODUCTION_SIGNING_NOT_READY: B2.2 reviewed activation required; no key created');return 2


if __name__=='__main__':raise SystemExit(main())
