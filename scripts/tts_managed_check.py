"""Opt-in real upstream download + isolated embedded runtime acceptance."""
import argparse
import json
from pathlib import Path
import sys
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--models',required=True);parser.add_argument('--backend',choices=['cpu','cuda'],default='cpu');args=parser.parse_args()
    from scripts.test_runtime import outside
    from transcomic.tts.managed_runtime import ManagedRuntimes
    from transcomic.tts.managed_engine import ManagedEngine
    from transcomic.tts.models import ModelManager
    from transcomic.tts.audio import encode
    import httpx
    root=outside(Path(args.root).absolute());root.mkdir(parents=True,exist_ok=True);manager=ManagedRuntimes(root/'Runtime');models=ModelManager(args.models);backend='CUDAExecutionProvider' if args.backend=='cuda' else 'CPUExecutionProvider';report={'backend':backend};last=['']
    def progress(done,total,label):
        percent=str(round(100*done/max(1,total)))
        if percent!=last[0]:print(percent+'%',flush=True);last[0]=percent
    def probe(runtime):
        engine=ManagedEngine(models,dict(variant='standard'),runtime)
        try:
            engine.probe('af_heart',1,'en-us');report['runtime']=engine.runtime_info
            report['wav']=encode(root/'probe.wav',engine.synthesize('A peaceful morning.','af_heart',1,'en-us'))
            report['mp3']=encode(root/'probe.mp3',engine.synthesize('A fresh beginning.','af_heart',1,'en-us'),'mp3')
        finally:engine.close()
    try:
        with httpx.Client(timeout=90,trust_env=False) as client:runtime=manager.install(backend,client,threading.Event(),probe,progress)
        assert manager.active();report['embedded']=True;report['active']=str(runtime['python'])
    except BaseException:
        import traceback
        report['error']=traceback.format_exc();raise
    finally:(root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=True));return 0

if __name__=='__main__':raise SystemExit(main())
