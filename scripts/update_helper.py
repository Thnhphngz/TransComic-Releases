"""Packaged Internal helper: authenticated local IPC, never an arbitrary plan file."""
from pathlib import Path
import argparse
import os
import threading
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from transcomic.update.metadata import UpdateError
from transcomic.update.windows_helper import ProductionUpdateHelper,NativeHelperSession,require_packaged_windows
from transcomic.update.install import SafetySnapshot
from transcomic.release_adapters import safe_path

def main(argv=None):
    session=None;channel=None
    try:
        parser=argparse.ArgumentParser()
        group=parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--channel');group.add_argument('--self-check',action='store_true')
        args=parser.parse_args(argv)
        require_packaged_windows()
        if args.self_check:
            import json
            from transcomic.version import VERSION
            print(json.dumps({'helper_protocol':1,'version':VERSION,'frozen':True,'policy':'internal',
                              'arbitrary_plan_files':False,'installer_executed':False}))
            return 0
        from transcomic.update.windows_channel import WindowsChannel
        channel=WindowsChannel.connect(args.channel)
        cancel=threading.Event()
        session=NativeHelperSession.authenticate(channel,channel.receive(cancel))
        snapshot=SafetySnapshot(app_closed=True,process_exited=False,safe_exit_verified=True)
        helper=ProductionUpdateHelper(session.updates,session.installation,policy='internal')
        # JSON's safe_exit_verified is insufficient: READY/COMMIT plus the exact
        # original process handle are mandatory in the native session.
        helper.run(session.plan,snapshot,cancel,native_session=session)
        return 0
    except Exception as error:
        if session is not None:
            # Do not overwrite the durable install receipt (especially UNKNOWN).
            from transcomic.update.metadata import canonical
            from uuid import uuid4
            try:
                path=safe_path(session.updates/'helper-last-result.json',session.updates)
                temporary=safe_path(session.updates/(uuid4().hex+'.result'),session.updates)
                with temporary.open('xb') as stream:
                    stream.write(canonical({'state':'NOT_COMPLETED','version':session.plan.version,
                                            'reason_type':type(error).__name__}))
                    stream.flush();os.fsync(stream.fileno())
                os.replace(temporary,path)
            except (OSError,UpdateError):pass
        print('UPDATE_NOT_COMPLETED: inspect the local update receipt; do not replay an unknown installer outcome')
        return 2
    finally:
        if session is not None:session.close()
        elif channel is not None:channel.close()

if __name__=='__main__':raise SystemExit(main())
