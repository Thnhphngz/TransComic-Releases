"""New opt-in completion/admission policy; no production keys or HTTP."""
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import threading
import time
import httpx
import pytest
from test_kira_auto_recovery import fixture,start,cleanup,response,request_lines
from transcomic.kira_pool import KiraPoolProvider
from transcomic.translation import Scheduler


@pytest.mark.parametrize('status',[429,503,504,'schema','timeout'])
def test_new_completion_survives_old_retry_time_and_count_limits(tmp_path,monkeypatch,status):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=4,kira_completion_policy=1,kira_dispatch_policy=1,
        kira_retry_limit=1,kira_retry_budget=1,kira_recovery_seconds=1,kira_retry_backoff=0,uncertain_retry_authorized=True)
    real_time=time.time;clock=[0];monkeypatch.setattr(time,'time',lambda:real_time()+clock[0]);calls=[];seen=Counter()
    def handler(req):
        ids=[r['id'] for r in request_lines(req)];calls.append(ids);seen.update(ids)
        if len(calls)<=35:
            if status=='timeout':raise httpx.ReadTimeout('Synthetic timeout',request=req)
            if status=='schema':return httpx.Response(200,json={'choices':[{'message':{'content':'invalid json'},'finish_reason':'stop'}]})
            return httpx.Response(status,headers={'Retry-After':'0'})
        return response(req)
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    original=pool.release
    def release(*args,**kw):
        value=original(*args,**kw);clock[0]+=601;return value
    pool.release=release;scheduler=Scheduler(store,pool);trace=[];original_run=scheduler._run
    async def traced():
        try:return await original_run()
        except Exception:
            import traceback
            trace.append(traceback.format_exc());print(trace[-1]);raise
    scheduler._run=traced;scheduler.start_many(jobs,run)
    try:
        scheduler.join(15);assert not scheduler._thread.is_alive()
        assert store.run(run)['state']=='finished' and len(calls)>=36,(trace,list(store.log.events)[-3:])
        assert all(r['state']=='done' for r in store.lines(docs[0]))
        cfg=json.loads(store.job(jobs[0])['config']);assert cfg['uncertain_retry_authorized'] is True
        assert cfg['kira_effective_token_limit'] is None and store.job(jobs[0])['max_requests'] is None
        assert len(store.jobs())==1 and store.db.execute('SELECT COUNT(*) FROM api_text_versions WHERE accepted=1').fetchone()[0]==3
    finally:cleanup(store,scheduler)


def test_new_completion_still_requires_unknown_consent(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=4,kira_completion_policy=1,kira_dispatch_policy=1)
    calls=[];scheduler,pool=start(store,run,jobs,lambda req:calls.append(1) or httpx.Response(504))
    try:
        scheduler.join(5);assert not scheduler._thread.is_alive()
        assert len(calls)==1 and store.run(run)['state']=='needs_reconciliation'
        assert json.loads(store.job(jobs[0])['config'])['uncertain_retry_authorized'] is False
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('limit',[{'kira_request_limit':2},{'kira_token_limit':1},
    {'kira_additional_cost_limit':0,'kira_token_cost_upper_bound':.001,'kira_cost_source':'Synthetic verified price'}])
def test_explicit_hard_limits_are_not_removed(tmp_path,limit):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=4,kira_completion_policy=1,kira_dispatch_policy=1,kira_retry_backoff=0,**limit)
    calls=[];scheduler,pool=start(store,run,jobs,lambda req:calls.append(1) or httpx.Response(503,headers={'Retry-After':'0'}))
    try:
        scheduler.join(7);assert not scheduler._thread.is_alive()
        assert len(calls)<=2 and store.run(run)['state']!='finished'
    finally:cleanup(store,scheduler)


def test_hundred_files_wait_for_nine_completions_and_carry_old_tenth(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,count=9,files=100,kira_recovery_version=4,kira_completion_policy=1,kira_dispatch_policy=1)
    store.set_setting('concurrency','30')
    with store.transaction():store.db.execute('UPDATE jobs SET concurrency=30')
    owners={r['id']:docs.index(d) for d in docs for r in store.lines(d)}
    release_nine=threading.Event();release_tenth=threading.Event();first_done=threading.Event();later=threading.Event();twentieth=threading.Event()
    seen=Counter();started=set();live=Counter();peak=0;events=[];original=store.log.emit
    def emit(event,**kw):
        if event.startswith('source_') or event=='cohort_unlocked':events.append((event,kw.get('source_instance'),time.monotonic()))
        return original(event,**kw)
    store.log.emit=emit
    async def handler(req):
        nonlocal peak
        ids=[r['id'] for r in request_lines(req)];doc=owners[ids[0]];started.add(doc);seen.update(ids);live[doc]+=1
        peak=max(peak,sum(v>0 for v in live.values()));assert peak<=10
        try:
            while 1<=doc<=8 and not release_nine.is_set() or doc==9 and not release_tenth.is_set():await asyncio.sleep(.004)
            if doc==0 and sum(seen[r['id']] for r in store.lines(docs[0]))==9:first_done.set()
            if doc>=10:later.set()
            if doc==19:twentieth.set()
            return response(req)
        finally:live[doc]-=1
    scheduler,pool=start(store,run,jobs,handler)
    try:
        assert first_done.wait(6);time.sleep(.15)
        assert started<=set(range(10)) and not later.is_set()
        release_nine.set();assert later.wait(8) and twentieth.wait(12)
        assert not release_tenth.is_set() and any(r['state']!='done' for r in store.lines(docs[9]))
        release_tenth.set();scheduler.join(30);assert not scheduler._thread.is_alive()
        assert store.run(run)['state']=='finished' and len(seen)==900 and set(seen.values())=={1}
        assert len(store.jobs())==100 and len(scheduler.admission.complete)==100
        assert sum(event=='cohort_unlocked' for event,_,_ in events)==9 and sum(event=='source_completed' for event,_,_ in events)==100
        if target:=os.environ.get('ADMISSION_EVIDENCE'):
            Path(target).mkdir(parents=True,exist_ok=True)
            (Path(target)/'hundred-source-order.json').write_text(json.dumps(dict(events=events,sources=[dict(index=i,document=d,source=store.document(d)['source_instance']) for i,d in enumerate(docs)],peak_http_files=peak,requests=sum(seen.values())//3)),encoding='utf8')
    finally:release_nine.set();release_tenth.set();cleanup(store,scheduler)


def test_temporary_retry_parks_with_limit_and_eventually_restores_every_source(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,count=3,files=30,kira_recovery_version=4,kira_completion_policy=1,kira_dispatch_policy=1,kira_retry_backoff=3)
    store.set_setting('concurrency','30')
    with store.transaction():store.db.execute('UPDATE jobs SET concurrency=30')
    owners={r['id']:i for i,d in enumerate(docs) for r in store.lines(d)};seen=Counter();parked=[];first_wave=set();original=store.log.emit
    def emit(event,**kw):
        if event in ('source_parked','source_restored'):parked.append((event,kw.get('source_instance')))
        return original(event,**kw)
    store.log.emit=emit
    async def handler(req):
        ids=[r['id'] for r in request_lines(req)];source=owners[ids[0]];seen.update(ids)
        if source<10 and seen[ids[0]]==1:
            first_wave.add(source);deadline=time.monotonic()+3
            while len(first_wave)<10 and time.monotonic()<deadline:await asyncio.sleep(.004)
        await asyncio.sleep(.01)
        if source<10 and seen[ids[0]]==1:return httpx.Response(503,headers={'Retry-After':'.8'})
        return response(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(15);assert not scheduler._thread.is_alive() and store.run(run)['state']=='finished',(len(seen),scheduler.active,scheduler.retrying,scheduler.admission.snapshot(),scheduler.key_metrics)
        assert any(e=='source_parked' for e,_ in parked) and any(e=='source_restored' for e,_ in parked)
        assert len(scheduler.admission.complete)==30 and not scheduler.admission.parked
        assert all(seen[r['id']]==(2 if i<10 else 1) for i,d in enumerate(docs) for r in store.lines(d))
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('default_probe',[False,True])
def test_network_wait_recovers_without_continue_or_restore(tmp_path,monkeypatch,default_probe):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=4,kira_completion_policy=1,kira_dispatch_policy=1,rate_wait_budget=0)
    calls=[];probes=[];pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(lambda req:calls.append(1) or response(req)),rpm=100000,tpm=100000000)
    pool.network_paused=True;scheduler=Scheduler(store,pool)
    probe=lambda:probes.append(time.monotonic()) or len(probes)>=2
    if default_probe:
        import transcomic.automation.adapters as adapters
        monkeypatch.setattr(adapters,'network_ready',lambda provider:probe())
    else:scheduler.network_probe=probe
    scheduler.start_many(jobs,run)
    try:
        scheduler.join(8);assert not scheduler._thread.is_alive()
        assert store.run(run)['state']=='finished' and len(calls)==1 and len(probes)==2
        assert probes[1]-probes[0]>=1.9
    finally:cleanup(store,scheduler)
