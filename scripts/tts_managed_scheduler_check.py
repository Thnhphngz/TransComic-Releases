"""Real existing scheduler against the installed standalone CUDA runtime."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--runtime',required=True);p.add_argument('--models',required=True);args=p.parse_args()
    from scripts.test_runtime import outside
    from transcomic.tts.storage import TtsStore
    from transcomic.tts.output import Outputs
    from transcomic.tts.models import ModelManager
    from transcomic.tts.managed_runtime import ManagedRuntimes
    from transcomic.tts.scheduler import Scheduler
    from transcomic.tts.concurrency import resource_gate
    root=outside(Path(args.root).absolute());root.mkdir(parents=True,exist_ok=False);store=TtsStore(root/'tts.sqlite3');models=ModelManager(args.models);packs=ManagedRuntimes(args.runtime);report={'resource_gate':resource_gate(2)}
    width=2 if report['resource_gate'][0] else 1;config=dict(variant='standard',language='en-us',voice='af_heart',speed=1,format='wav',device='Auto',workers=width)
    scheduler=Scheduler(store,models);scheduler.packs=packs;scheduler.prepared_backend='CUDAExecutionProvider'
    def prepare(text,name):
        run=store.draft();store.add_document(run,dict(name=name,text=text,line_count=len(text.splitlines()),path=None));output=Outputs(store);output.confirm(run,config,output.plan(run,'custom',str(root),'wav'));return run
    def wait(condition,seconds=180):
        end=time.monotonic()+seconds
        while not condition() and time.monotonic()<end:time.sleep(.01)
        assert condition(),'scheduler acceptance timeout'
    try:
        run=prepare('\n'.join(['A peaceful morning brings a new beginning beside the quiet river.']*20),'Twenty');scheduler.start(run);wait(lambda:store.progress(run).get('success',0)>=2);scheduler.pause();wait(lambda:not scheduler.busy);assert store.run(run)['state']=='paused';saved={i['id']:i['sha256'] for i in store.items(run) if i['state']=='success'};timeline=list(scheduler.parallel_timeline)
        scheduler.start(run);wait(lambda:not scheduler.busy);assert store.run(run)['state']=='completed' and store.progress(run)=={'success':20};assert all(store.segment(id)['sha256']==sha for id,sha in saved.items())
        active=set();peak=0
        for kind,thread,when in sorted([*timeline,*scheduler.parallel_timeline],key=lambda x:x[2]):
            if kind=='start':active.add(thread)
            else:active.discard(thread)
            peak=max(peak,len(active))
        report.update(twenty=20,preserved=len(saved),width=width,concurrent_session_run_peak=peak)
        if width==2:assert peak==2
        run=prepare('\n'.join(['A new beginning.']+['A long story for cancellation. '*20]*19),'Cancel');scheduler.start(run);wait(lambda:store.progress(run).get('success',0)>=1 and bool(scheduler.active));saved={i['id']:i['sha256'] for i in store.items(run) if i['state']=='success'};pids=[e.process.pid for e in scheduler.engines];start=time.monotonic();scheduler.stop();wait(lambda:not scheduler.busy,10);assert store.run(run)['state']=='cancelled';assert all(store.segment(id)['sha256']==sha for id,sha in saved.items())
        import psutil
        wait(lambda:all(not psutil.pid_exists(pid) for pid in pids),3);report.update(cancel_seconds=time.monotonic()-start,no_orphan=True,cancelled=True,worker_pids=pids)
    except BaseException:
        import traceback
        report['error']=traceback.format_exc();raise
    finally:
        scheduler.stop();wait(lambda:not scheduler.busy,10);store.close();(root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report));return 0

if __name__=='__main__':raise SystemExit(main())
