"""External helper entry prepared but execution locked, including arbitrary JSON plans."""
from pathlib import Path
import argparse
import os
import threading
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from transcomic.release_adapters import locked
from transcomic.update.metadata import UpdateError
from transcomic.update.windows_helper import ProductionUpdateHelper,load_install_plan,registered_installation
from transcomic.update.install import SafetySnapshot
from transcomic.release_adapters import safe_path

def main(argv=None):
    try:
        locked()  # before parsing/reading any untrusted install plan or acquiring Windows handles
        parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True,type=Path);args=parser.parse_args(argv)
        updates=safe_path(Path(os.environ['LOCALAPPDATA'])/'TransComic/Updates')
        plan_path=safe_path(args.plan,updates)
        if plan_path.stat().st_size>128*1024:raise UpdateError('INSTALL_PLAN_SIZE_LIMIT')
        # The helper is a verified temporary copy; only the fixed Inno AppId determines app location.
        if not getattr(sys,'frozen',False):raise UpdateError('PACKAGED_HELPER_REQUIRED')
        if not Path(sys.executable).resolve().is_relative_to(updates):raise UpdateError('HELPER_MUST_RUN_FROM_UPDATE_COPY')
        installation=registered_installation()
        plan=load_install_plan(plan_path.read_bytes(),updates,installation)
        snapshot=SafetySnapshot(app_closed=True,process_exited=True,safe_exit_verified=True)
        helper=ProductionUpdateHelper(updates,installation)
        helper.run(plan,snapshot,threading.Event())
        return 0
    except UpdateError:
        print('STAGE_A_B1_LOCKED_OR_INSTALL_UNVERIFIED: production update helper is not activated');return 2

if __name__=='__main__':raise SystemExit(main())
