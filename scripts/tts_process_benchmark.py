"""Explicit local process-engine benchmark; no model download or application DB."""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--models',required=True);parser.add_argument('--device',choices=['CPU','GPU'],required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
    from transcomic.tts.process_engine import ProcessEngine
    from transcomic.tts.models import ModelManager
    from transcomic.tts.devices import backend_plan
    from transcomic.tts.catalog import LANGUAGES
    import psutil
    result=dict(executable=sys.executable,device=args.device,fixture=LANGUAGES['en-us'][2],repeats=4,voice='af_heart',speed=1,language='en-us',peak_sampled_rss_bytes=0,vram_bytes=None,sample_interval_seconds=.05)
    engine=None;stop=threading.Event();parent=psutil.Process()
    def sample():
        while not stop.is_set():
            try:result['peak_sampled_rss_bytes']=max(result['peak_sampled_rss_bytes'],parent.memory_info().rss+sum(p.memory_info().rss for p in parent.children(recursive=True) if p.is_running()))
            except psutil.Error:pass
            stop.wait(.05)
    monitor=threading.Thread(target=sample,daemon=True);monitor.start()
    try:
        start=time.perf_counter();backend=backend_plan(args.device)[0];engine=ProcessEngine(ModelManager(args.models),'standard',backend);engine.probe('af_heart',1,'en-us');result['load_probe_seconds']=time.perf_counter()-start;result['runtime']=engine.runtime_info;result['backend']=backend
        start=time.perf_counter();duration=sum(len(block)/24000 for _ in range(4) for block in engine.synthesize(result['fixture'],'af_heart',1,'en-us'));elapsed=time.perf_counter()-start
        result.update(audio_seconds=duration,seconds=elapsed,throughput=duration/elapsed)
    except Exception as exc:result['error']=str(exc);raise
    finally:
        if engine:engine.close()
        stop.set();monitor.join(1);output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
