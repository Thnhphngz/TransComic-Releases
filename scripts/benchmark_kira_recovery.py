"""Bounded synthetic CPU/MockTransport benchmark; never contacts an API or GPU."""
import argparse
import asyncio
from collections import Counter
import cProfile
import json
from pathlib import Path
import pstats
import statistics
import threading
import time

import httpx

from scripts.test_runtime import TemporaryDirectory
from transcomic.documents import decode_txt
from transcomic.kira_pool import KiraPoolProvider
from transcomic.storage import Store
from transcomic.translation import Scheduler


class MeasuredLock:
    """Diagnostic-only proxy; delegates locking and records outer hold/wait."""
    def __init__(self,base):
        self.base=base;self.local=threading.local();self.metrics={}
    def __getattr__(self,name):return getattr(self.base,name)
    def __enter__(self):
        started=time.perf_counter();self.base.acquire();now=time.perf_counter()
        row=self.metrics.setdefault(threading.current_thread().name,dict(acquires=0,wait_seconds=0.,max_wait_seconds=0.,hold_seconds=0.))
        waited=now-started;row['acquires']+=1;row['wait_seconds']+=waited;row['max_wait_seconds']=max(row['max_wait_seconds'],waited)
        depth=getattr(self.local,'depth',0)
        if not depth:self.local.started=now
        self.local.depth=depth+1;return self
    def __exit__(self,*args):
        self.local.depth-=1
        if not self.local.depth:self.metrics[threading.current_thread().name]['hold_seconds']+=time.perf_counter()-self.local.started
        self.base.release()


def measure(workers, keys=1, files=5, lines=123, delay=.03, profile=False, measure_locks=False):
    with TemporaryDirectory(prefix='kira-benchmark-') as folder:
        store=Store(Path(folder)/'synthetic.db')
        store.add_kira_keys(' '.join(f'synthetic-benchmark-key-{i}' for i in range(keys)))
        cap=min(30,max(1,(workers+keys-1)//keys))
        store.set_setting('concurrency',str(cap))
        docs=[store.import_document(Path(folder)/f'chapter-{i}.txt',decode_txt(
            '\n'.join(f'Nguồn kiểm thử tổng hợp dòng {j}' for j in range(lines)).encode()),'vi','en')[0] for i in range(files)]
        run,jobs=store.create_run(docs,['en'],provider='kira',model='mock',source_lang='vi',concurrency=cap,config={'kira_multi_key':True})
        if measure_locks:store.lock=MeasuredLock(store.lock)
        active=peak=0;sent=[];latencies=[];per_key=Counter()
        async def handler(req):
            nonlocal active,peak
            started=time.perf_counter();active+=1;peak=max(peak,active)
            assert not store.lock._is_owned() and not pool.monitor.lock._is_owned() and not pool._reservation_lock._is_owned()
            per_key[req.headers['authorization']]+=1;sent.append(started)
            try:
                await asyncio.sleep(delay)
                payload=json.loads(json.loads(req.content)['messages'][1]['content'])['lines']
                return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[
                    {'id':r['id'],'text':'The translated story continues'} for r in payload]})},'finish_reason':'stop'}]})
            finally:active-=1;latencies.append(time.perf_counter()-started)
        pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),account_limit=workers,rpm=100000,tpm=1000000000)
        profiler=cProfile.Profile()
        class ProfiledScheduler(Scheduler):
            def _run_thread(self):
                if profile:profiler.runcall(super()._run_thread)
                else:super()._run_thread()
        scheduler=ProfiledScheduler(store,pool)
        started=time.perf_counter()
        try:
            scheduler.start_many(jobs,run);scheduler.join(45)
            if scheduler._thread.is_alive():
                scheduler.stop();scheduler.join(10)
                raise RuntimeError('Bounded mock benchmark did not drain')
            seconds=time.perf_counter()-started
            result=dict(workers=workers,keys=keys,files=files,lines=files*lines,delay=delay,
                seconds=seconds,requests=len(sent),peak_http=peak,requests_per_key=sorted(per_key.values()),
                lines_per_second=files*lines/seconds,effective_rpm=len(sent)*60/seconds,
                mean_http_seconds=statistics.mean(latencies) if latencies else 0,
                mean_dispatch_seconds=statistics.mean(scheduler.dispatch_latencies) if scheduler.dispatch_latencies else 0,
                max_dispatch_seconds=max(scheduler.dispatch_latencies,default=0),
                state=store.run(run)['state'],remaining=sum(r['state']!='done' for d in docs for r in store.lines(d)),
                mock_only=True,sqlite_lock=store.lock.metrics if measure_locks else None,
                wait_reasons={key:dict(value['wait_reasons']) for key,value in enumerate(pool.stats.values())})
            if profile:
                stats=pstats.Stats(profiler)
                result['profile']=[{'function':f'{k[0]}:{k[1]} {k[2]}','calls':v[1],'own_seconds':v[2],'cumulative_seconds':v[3]}
                    for k,v in sorted(stats.stats.items(),key=lambda item:item[1][2],reverse=True)[:25]]
            return result
        finally:
            scheduler.stop();scheduler.join(10)
            if scheduler._thread.is_alive():raise RuntimeError('Mock worker still alive; database retained')
            store.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',nargs='+',type=int,default=[1,5,10,20,30])
    parser.add_argument('--keys',nargs='+',type=int,default=[1,3])
    parser.add_argument('--files',type=int,default=5);parser.add_argument('--lines',type=int,default=123)
    parser.add_argument('--delay',type=float,default=.03);parser.add_argument('--profile',action='store_true')
    parser.add_argument('--output',required=True)
    parser.add_argument('--gui-slots',action='store_true',help='Profile the existing 150-slot, 15-second GUI gate')
    parser.add_argument('--cooperative-wait',action='store_true')
    parser.add_argument('--measure-locks',action='store_true')
    args=parser.parse_args()
    if any(not 1<=n<=150 for n in args.workers) or any(not 1<=n<=10 for n in args.keys) or not 1<=args.files<=10 or not 1<=args.lines<=130 or not 0<=args.delay<=.2:
        parser.error('Synthetic benchmark bounds exceeded')
    if args.gui_slots:
        target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps(measure_gui_slots(args.cooperative_wait),indent=2),encoding='utf-8');return
    result=[]
    for keys in args.keys:
        for workers in args.workers:
            if workers>keys*30:continue
            item=measure(workers,keys,args.files,args.lines,args.delay,args.profile,args.measure_locks);result.append(item)
            print(json.dumps({k:v for k,v in item.items() if k!='profile'}),flush=True)
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')


def measure_gui_slots(cooperative_wait=False):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from transcomic.ui.main import MainWindow
    app=QApplication.instance() or QApplication([])
    with TemporaryDirectory(prefix='kira-gui-benchmark-') as folder:
        store=Store(Path(folder)/'state.db');window=MainWindow(store)
        window.resize(1400,850);window.show();app.processEvents()
        store.add_kira_keys(' '.join(f'synthetic-gui-key-{i}' for i in range(5)))
        store.set_setting('concurrency','30');docs=[]
        for i in range(10):
            doc=store.import_document(Path(folder)/f'{i}'/'same-name.txt',decode_txt(
                '\n'.join(f'Nguồn kiểm thử giao diện {j}' for j in range(60)).encode()),'vi','en')[0]
            docs.append(doc);window.open_document(doc)
        window.open_document(docs[0]);window.refresh_kira_keys();app.processEvents()
        run,jobs=store.create_run(docs,['en'],provider='kira',model='mock',source_lang='vi',concurrency=30,config={'kira_multi_key':True})
        gate=threading.Event();calls=[];profile=cProfile.Profile()
        async def handler(req):
            calls.append(time.perf_counter())
            while not gate.is_set():await asyncio.sleep(.002)
            payload=json.loads(json.loads(req.content)['messages'][1]['content'])['lines']
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[
                {'id':r['id'],'text':'The translated story continues'} for r in payload]})}}]})
        class Profiled(Scheduler):
            def _run_thread(self):profile.runcall(super()._run_thread)
        pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),account_limit=150,rpm=100000,tpm=1000000000)
        scheduler=Profiled(store,pool,window.bridge.changed.emit);window.scheduler=scheduler
        start=time.perf_counter();scheduler.start_many(jobs,run)
        try:
            while len(calls)<150 and time.perf_counter()-start<15:
                app.processEvents()
                if cooperative_wait:time.sleep(.01)
                else:QTest.qWait(10)
            elapsed=time.perf_counter()-start
            result={'mock_only':True,'threshold_seconds':15,'reached_slots':len(calls),
                'fill_seconds':elapsed,'passed':len(calls)==150,'profile_included':True,'cooperative_wait':cooperative_wait}
        finally:
            gate.set()
            deadline=time.perf_counter()+25
            while scheduler._thread.is_alive() and time.perf_counter()<deadline:
                app.processEvents();time.sleep(.005)
            if scheduler._thread.is_alive():scheduler.stop();scheduler.join(5)
            window._exit_authorized=True;window.close();app.processEvents()
        stats=pstats.Stats(profile)
        result['profile']=[{'function':f'{k[0]}:{k[1]} {k[2]}','calls':v[1],'own_seconds':v[2],'cumulative_seconds':v[3]}
            for k,v in sorted(stats.stats.items(),key=lambda item:item[1][2],reverse=True)[:25]]
        print(json.dumps({k:v for k,v in result.items() if k!='profile'}),flush=True)
        return result


if __name__=='__main__':main()
