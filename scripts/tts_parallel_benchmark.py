"""Explicit end-to-end CUDA calibration, isolated fixtures and telemetry."""
import argparse
import json
from pathlib import Path
import sys
import subprocess
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--models',required=True);parser.add_argument('--root',required=True);parser.add_argument('--count',type=int,default=32);args=parser.parse_args()
    from scripts.test_runtime import outside
    from transcomic.tts.models import ModelManager
    from transcomic.tts.storage import TtsStore
    from transcomic.tts.output import Outputs
    from transcomic.tts.scheduler import Scheduler
    from transcomic.tts.concurrency import resource_gate,fingerprint
    import psutil
    root=outside(Path(args.root).absolute());root.mkdir(exist_ok=False);report=dict(cases=[],skipped={},count=args.count)
    fixtures=['A quiet morning.','The sun is shining and the birds are singing.','A new adventure begins today, with a long road ahead and many stories waiting to be told.','Please take your time and listen carefully to the story.']
    text='\n'.join(fixtures[i%len(fixtures)] for i in range(args.count));parent=psutil.Process()
    config=dict(language='en-us',voice='af_heart',speed=1,variant='standard',revision='1939ad2a8e416c0acfeecc08a694d14ef25f2231',device='Auto',format='wav',split='lines')
    for width in (1,2,1,2,3,4):
        if width>1:
            allowed,reason=resource_gate(width)
            if not allowed:report['skipped'][str(width)]=reason;continue
        case=root/f'workers-{width}-{len(report["cases"])}';case.mkdir();store=TtsStore(case/'tts.sqlite3');run=store.draft();store.add_document(run,dict(name='Calibration',text=text,line_count=args.count,path=None));current=dict(config,workers=width);output=Outputs(store);output.confirm(run,current,output.plan(run,'custom',str(case),'wav'))
        metrics=dict(workers=width,peak_rss_bytes=0,peak_vram_mib=0,gpu_utilization_peak=0,cpu_percent_peak=0);stop=threading.Event()
        def sample():
            previous={};last=time.monotonic()
            while not stop.is_set():
                try:
                    processes=[parent,*parent.children(recursive=True)];metrics['peak_rss_bytes']=max(metrics['peak_rss_bytes'],sum(p.memory_info().rss for p in processes))
                    now=time.monotonic();current={p.pid:p.cpu_times().user+p.cpu_times().system for p in processes};delta=sum(max(0,value-previous.get(pid,value)) for pid,value in current.items())
                    metrics['cpu_percent_peak']=max(metrics['cpu_percent_peak'],100*delta/max(.001,now-last));previous=current;last=now
                    data=subprocess.check_output(['nvidia-smi','--query-gpu=memory.used,utilization.gpu','--format=csv,noheader,nounits'],text=True,timeout=3,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).splitlines()[0].split(',')
                    metrics['peak_vram_mib']=max(metrics['peak_vram_mib'],float(data[0]));metrics['gpu_utilization_peak']=max(metrics['gpu_utilization_peak'],float(data[1]))
                except (psutil.Error,OSError,ValueError,subprocess.SubprocessError):pass
                stop.wait(.2)
        def notified(kind,value):
            if kind=='backend' and 'load_probe_seconds' not in metrics:metrics['load_probe_seconds']=time.perf_counter()-started
        monitor=threading.Thread(target=sample,daemon=True);monitor.start();scheduler=Scheduler(store,ModelManager(args.models),notify=notified);started=time.perf_counter();scheduler.start(run);scheduler.thread.join(240);elapsed=time.perf_counter()-started
        if scheduler.busy:scheduler.stop();scheduler.thread.join(10)
        stop.set();monitor.join(4);items=store.items(run);duration=sum(i['duration'] or 0 for i in items)
        active=set();peak=0
        for kind,thread,when in sorted(scheduler.parallel_timeline,key=lambda e:e[2]):
            if kind=='start':active.add(thread)
            else:active.discard(thread)
            peak=max(peak,len(active))
        metrics.update(seconds=elapsed,audio_seconds=duration,throughput=duration/elapsed,counts=store.progress(run),state=store.run(run)['state'],backends=sorted({i['backend'] for i in items}),concurrent_session_run_peak=peak,concurrency_verified=width==1 or peak>=width,timeline=scheduler.parallel_timeline,error=store.run(run)['error'])
        report['cases'].append(metrics);print(json.dumps({k:v for k,v in metrics.items() if k!='timeline'}),flush=True);store.close();(root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        if metrics['state']!='completed':report['skipped']['higher']='Previous case failed; no higher width attempted';break
    good=[c for c in report['cases'] if c['state']=='completed' and c['concurrency_verified']];medians={}
    import statistics
    for width in {c['workers'] for c in good}:medians[width]=statistics.median(c['throughput'] for c in good if c['workers']==width)
    best=max(medians,key=medians.get) if medians else 1
    if medians.get(best,0)<1.1*medians.get(1,float('inf')):best=1
    report.update(recommended_workers=best,median_throughput=medians,fingerprint=fingerprint(config),note='Session.run host intervals prove concurrent calls, not CUDA kernel overlap. End-to-end includes process/model, encode, SQLite, manifest/finalize; VRAM is whole GPU sampled, not process-only.')
    (root/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');return 0


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support();raise SystemExit(main())
