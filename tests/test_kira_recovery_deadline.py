"""Recovery deadline must not discard first-pass work; isolated HTTP mocks."""
from collections import Counter
import asyncio
import json
import time
import httpx
import pytest
from test_kira_auto_recovery import fixture,start,cleanup,response,request_lines
from transcomic.kira_recovery import budget_reason,schedule_retry
from transcomic.storage import Store
from transcomic.ui.translation_updates import document_status
from transcomic.kira_pool import KiraPoolProvider
from transcomic.translation import Scheduler
from test_automation import setup,add_group,run as run_automation,FakeEngine


def expired(store,job,now=None):
    cfg=json.loads(store.job(job)['config']);cfg['kira_recovery_started_at']=(time.time() if now is None else now)-601
    with store.transaction():store.db.execute('UPDATE jobs SET config=? WHERE id=?',(json.dumps(cfg),job))
    return cfg


def test_expired_recovery_allows_fresh_attempt_but_not_retry(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,count=6,kira_recovery_version=4)
    try:
        cfg=expired(store,jobs[0]);job=store.job(jobs[0]);batch=store.batches(jobs[0])[0]
        assert budget_reason(store,job,retry=False) is None
        assert budget_reason(store,job,retry=True)=='recovery_wait_budget_exhausted'
        store.job_state(job['id'],'running');assert store.claim_batch(batch['id'])
        assert store.prepare_attempt(batch['id'],1,reserved_tokens=100)
        assert json.loads(store.job(job['id'])['config'])==cfg
    finally:store.close()


@pytest.mark.parametrize('limit,reason',[
    ({'kira_request_limit':1},'request_or_retry_budget_exhausted'),
    ({'kira_token_limit':1},'token_budget_exhausted'),
])
def test_first_pass_still_obeys_actual_request_and_token_limits(tmp_path,limit,reason):
    store,docs,run,jobs=fixture(tmp_path,count=6,kira_recovery_version=4,**limit)
    try:
        expired(store,jobs[0]);job=store.job(jobs[0])
        if 'kira_request_limit' in limit:
            batch=store.batches(job['id'])[0];store.job_state(job['id'],'running');store.claim_batch(batch['id']);assert store.prepare_attempt(batch['id'],1,reserved_tokens=0)
        assert budget_reason(store,store.job(job['id']),retry=False,cost=2)==reason
    finally:store.close()


@pytest.mark.parametrize('status',[429,503,504])
@pytest.mark.parametrize('consent',[False,True])
def test_expiry_during_dispatch_preserves_all_unsent_batches(tmp_path,monkeypatch,status,consent):
    store,docs,run,jobs=fixture(tmp_path,count=9,files=2,kira_recovery_version=4,kira_retry_backoff=0,uncertain_retry_authorized=consent)
    first=store.batches(jobs[0])[0];first_ids={p['id'] for p in first['payload']}
    calls=[];seen=Counter();real_time=time.time;clock=[0]
    cfg=json.loads(store.job(jobs[0])['config']);cfg['kira_recovery_started_at']=real_time()
    with store.transaction():store.db.execute('UPDATE jobs SET config=? WHERE id=?',(json.dumps(cfg),jobs[0]))
    monkeypatch.setattr(time,'time',lambda:real_time()+clock[0])
    def handler(req):
        ids={r['id'] for r in request_lines(req)};calls.append(ids);seen.update(ids)
        if ids==first_ids and seen[next(iter(ids))]==1:return httpx.Response(status,headers={'Retry-After':'0'})
        return response(req)
    # Advance only after the failed request is committed and retry considered.
    # Normal wall time keeps flowing so cooldown tests never busy-wait forever.
    def changed(ids):
        if len(calls)==1:clock[0]=601
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    scheduler=Scheduler(store,pool,changed);scheduler.start_many(jobs,run)
    try:
        scheduler.join(8);assert not scheduler._thread.is_alive()
        assert len(calls)==6 and all(count==1 for count in seen.values())
        assert len(seen)==18 and len(store.jobs())==2
        assert sum(r['state']=='done' for r in store.lines(docs[0]))==6
        assert all(r['state']=='done' for r in store.lines(docs[1]))
        assert not any(b['state']=='pending' for j in jobs for b in store.batches(j))
        assert store.job(jobs[0])['state']!='running' and store.job(jobs[1])['state']=='finished'
        assert json.loads(store.job(jobs[0])['config'])['uncertain_retry_authorized']==consent
        assert len(store.attempts(first['id']))==1
        expected='unknown_request' if status==504 and not consent else 'recovery_wait_budget_exhausted'
        assert store.batch(first['id'])['diagnostics']['dispatch_block_reason']==expected
    finally:cleanup(store,scheduler)


def test_resume_expired_checkpoint_sends_only_never_sent_batches_same_job(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,count=9,kira_recovery_version=4)
    job=jobs[0];batch=store.batches(job)[0];store.job_state(job,'running');store.claim_batch(batch['id'])
    attempt=store.prepare_attempt(batch['id'],1,reserved_tokens=100)
    values={p['id']:'The accepted story remains unchanged' for p in batch['payload']}
    store.finish_batch(batch['id'],values,None,False,{},expected_attempt_id=attempt);store.complete_attempt(attempt,{'http_status':200})
    cfg=expired(store,job);accepted={rid:dict(store.line(rid)) for rid in values};store.close()
    store=Store(tmp_path/'synthetic.db');calls=[]
    try:
        assert json.loads(store.job(job)['config'])==cfg
        assert len(store.jobs())==1 and len(store.attempts(batch['id']))==1
        scheduler,pool=start(store,run,jobs,lambda req:calls.append({r['id'] for r in request_lines(req)}) or response(req))
        try:
            scheduler.join(8);assert not scheduler._thread.is_alive()
            assert store.job(job)['state']=='finished' and len(calls)==2
            assert not set.union(*calls)&values.keys() and all(store.line(rid)==row for rid,row in accepted.items())
            assert len(store.jobs())==1 and len(store.attempts(batch['id']))==1
            final=json.loads(store.job(job)['config'])
            assert {key:final[key] for key in cfg}==cfg
        finally:cleanup(store,scheduler)
    except BaseException:
        store.close();raise


def test_unknown_rows_do_not_hide_active_unsent_work():
    rows=[dict(id='unknown',source='Nguồn lỗi',translation='',state='unknown',source_revision=0,translation_source_revision=None),
          dict(id='new',source='Nguồn mới',translation='',state='pending',source_revision=0,translation_source_revision=None)]
    active=document_status(rows,'running',pending_work=True)
    assert active['state']=='Đang dịch' and active['unknown']==1 and not active['complete']
    assert document_status(rows,'needs_reconciliation')['state']=='Cần đối chiếu kết quả'


def test_drained_job_stays_blocked_while_another_document_keeps_running(tmp_path,monkeypatch):
    store,docs,run,jobs=fixture(tmp_path,count=6,files=2,kira_recovery_version=4,kira_retry_backoff=0)
    expired(store,jobs[0]);first=store.batches(jobs[0])[0];failed_ids={r['id'] for r in first['payload']}
    calls=[];observed=[]
    async def handler(req):
        ids={r['id'] for r in request_lines(req)};calls.append(ids)
        await asyncio.sleep(.01)
        return httpx.Response(503,headers={'Retry-After':'0'}) if ids==failed_ids else response(req)
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    scheduler=Scheduler(store,pool)
    def changed(ids):
        if getattr(scheduler,'dispatch_job_states',{}).get(jobs[0]):
            scheduler._set_state('user_paused')
            scheduler._set_state('running') # Another document's normal global transition.
            observed.append(store.job(jobs[0])['state'])
    scheduler.on_change=changed;scheduler.start_many(jobs,run)
    try:
        scheduler.join(8);assert not scheduler._thread.is_alive()
        assert observed and set(observed)=={'blocked_budget'}
        assert store.job(jobs[1])['state']=='finished' and len(calls)==4
        assert store.batch(first['id'])['diagnostics']['dispatch_block_reason']=='recovery_wait_budget_exhausted'
    finally:cleanup(store,scheduler)


def test_twenty_documents_keep_first_pass_after_ten_minute_deadline(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,count=9,files=20,kira_recovery_version=4,kira_retry_backoff=0)
    store.set_setting('concurrency','30')
    with store.transaction():store.db.execute('UPDATE jobs SET concurrency=30')
    for job in jobs[:3]:expired(store,job)
    owners={r['id']:d for d in docs for r in store.lines(d)};seen=Counter();calls=[];live=peak=0
    async def handler(req):
        nonlocal live,peak
        ids={r['id'] for r in request_lines(req)};seen.update(ids);calls.append(ids);live+=1;peak=max(peak,live)
        try:
            deadline=time.monotonic()+4
            while len(calls)<30 and time.monotonic()<deadline:await asyncio.sleep(.005)
            await asyncio.sleep(.005)
            return response(req)
        finally:live-=1
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(12);assert not scheduler._thread.is_alive()
        assert len(calls)==60 and set(seen)==set(owners) and set(seen.values())=={1}
        assert len(store.jobs())==20 and store.run(run)['state']=='finished'
        assert all(r['state']=='done' for doc in docs for r in store.lines(doc))
        assert peak==30 and not live
        assert all(not store.batch(b['id'])['diagnostics'].get('dispatch_block_reason') for j in jobs for b in store.batches(j))
    finally:cleanup(store,scheduler)


def test_automation_keeps_unsent_work_and_does_not_label_completed_group_blocked(setup,tmp_path):
    repo,wid,services,controller=setup
    cfg=repo.workset(wid)['config'];cfg['workers']=1;repo.configure(wid,cfg);repo.store.set_setting('concurrency','1')
    first,_,_=add_group(repo,wid,tmp_path/'first','First',6)
    second,_,_=add_group(repo,wid,tmp_path/'second','Second',6)
    doc=repo.group(first)['document_id'];calls=[];deadline=[]
    def handler(req):
        ids=[r['id'] for r in request_lines(req)];calls.append(ids)
        if repo.store.line(ids[0])['document_id']==doc and not deadline:
            job=next(j for j in repo.store.jobs() if j['document_id']==doc)
            deadline.append(expired(repo.store,job['id'])['kira_recovery_started_at'])
            return httpx.Response(503,headers={'Retry-After':'0'})
        return response(req)
    services.translation.provider_factory=lambda store,job:KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    run_automation(controller,wid,timeout=15)
    assert repo.workset(wid)['state']=='needs_attention' and len(calls)==4 and len(repo.store.jobs())==2
    assert sum(r['state']=='done' for r in repo.store.lines(doc))==3
    failed=repo.group(first)['data'];complete=repo.group(second)['data']
    assert failed['translation_recovery_state']=='blocked_budget'
    assert failed['translation_recovery_reason']=='recovery_wait_budget_exhausted'
    assert complete['state']=='completed' and complete['translation_recovery_state']=='finished'
    assert complete['translation_recovery_reason']=='' and complete['next_retry_at'] is None
    assert len(FakeEngine.calls)==6
    job=next(j for j in repo.store.jobs() if j['document_id']==doc)
    assert json.loads(job['config'])['kira_recovery_started_at']==deadline[0]
