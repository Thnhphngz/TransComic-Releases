"""Real development IPC test, NOT an embedded/portable distribution test."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--models',required=True);args=parser.parse_args()
    from scripts.test_runtime import outside
    from transcomic.tts.pack_engine import PackEngine
    from transcomic.tts.models import ModelManager
    from transcomic.tts.audio import encode
    from transcomic.tts.process_engine import Stopped
    root=outside(Path(args.root).absolute());root.mkdir(exist_ok=False);source=Path(__file__).resolve().parents[1];package=root/'transcomic'/'tts';package.mkdir(parents=True)
    (root/'transcomic'/'__init__.py').write_text('');(package/'__init__.py').write_text('')
    for name in ('engine.py','models.py','catalog.py','adapters.py','japanese.py','output.py','audio.py'):shutil.copyfile(source/'transcomic'/'tts'/name,package/name)
    shutil.copyfile(source/'transcomic'/'tts'/'pack_worker.py',root/'worker.py')
    # Reuse this development env's site-packages explicitly. No portable
    # runtime is created here; the raw base executable avoids venv redirectors.
    libraries=Path(sys.prefix)/'Lib'/'site-packages';bootstrap=root/'bootstrap.py';bootstrap.write_text(f'import sys,runpy\nsys.path.insert(0,{str(libraries)!r})\nsys.path.insert(0,{str(root)!r})\nrunpy.run_path({str(root/"worker.py")!r},run_name="__main__")\n',encoding='utf8')
    runtime=dict(python=Path(getattr(sys,'_base_executable',sys.executable)),worker=bootstrap,folder=root);engine=PackEngine(ModelManager(args.models),dict(variant='standard'),runtime)
    report=dict(portable_distribution=False,note='Development IPC only, dependencies reused from project .venv')
    try:
        engine.probe('af_heart',1,'en-us');report['runtime']=engine.runtime_info;report['wav']=encode(root/'one.wav',engine.synthesize('Hello there.','af_heart',1,'en-us'));report['mp3']=encode(root/'two.mp3',engine.synthesize('A new beginning.','af_heart',1,'en-us'),'mp3')
        entered=threading.Event();outcome=[]
        def long_work():
            try:
                entered.set();encode(root/'cancel.part',engine.synthesize('A long sentence for cancelling. '*50,'af_heart',1,'en-us'))
            except Stopped:outcome.append('stopped')
        thread=threading.Thread(target=long_work);thread.start();assert entered.wait(3);time.sleep(.2);start=time.monotonic();engine.cancel();engine.close();thread.join(5)
        report.update(stop_seconds=time.monotonic()-start,child_exited=engine.process.poll() is not None,thread_stopped=not thread.is_alive(),outcome=outcome)
        assert report['child_exited'] and report['thread_stopped']
    finally:
        if engine.process.poll() is None:engine.close()
        (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report));return 0


if __name__=='__main__':raise SystemExit(main())
