"""Test-only demo or locked production provisioning; never accepts password in argv."""
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
from transcomic.update.keytools import test_provision,production_provision
from transcomic.update.metadata import UpdateError
from transcomic.release_adapters import locked


def main(argv=None):
    parser=argparse.ArgumentParser(description='B2.1 provisioning: production locked; test keys never pinned')
    parser.add_argument('--test',action='store_true');parser.add_argument('--directory',type=Path)
    args=parser.parse_args(argv)
    if args.test:
        with TemporaryDirectory() as directory:
            info=test_provision(Path(directory)/'test-key',secrets.token_bytes(32))
            print(json.dumps(asdict(info)))
        return 0
    try:
        locked()  # no production password prompt/RNG/file access in B2.1
        if args.directory is None:raise UpdateError('Explicit private signing directory required')
        password=getpass.getpass('Encrypted signing key passphrase: ').encode('utf8')
        if password!=getpass.getpass('Confirm passphrase: ').encode('utf8'):raise UpdateError('Passphrase mismatch')
        production_provision(args.directory,password)
    except UpdateError:print('PRODUCTION_SIGNING_NOT_READY: B2.2 reviewed activation required; no key created');return 2


if __name__=='__main__':raise SystemExit(main())
