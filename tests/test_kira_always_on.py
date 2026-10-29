"""Always-on recovery: synthetic sources, encrypted fixture keys, no live HTTP."""
import json
import time
import httpx
import pytest
from test_automation import setup,add_group,run,FakeEngine
from test_kira_auto_recovery import fixture,start,cleanup,response


def test_new_policy_does_not_grant_unknown_resend_by_start(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=4)
    try:
        assert store.run(run)['config']['uncertain_retry_authorized'] is False
    finally:store.close()


def test_generic_service_error_has_finite_automatic_health(tmp_path):
    store,docs,run,jobs=fixture(tmp_path)
    from transcomic.kira_pool import KiraPoolProvider
    from transcomic.providers import BatchResult
    pool=KiraPoolProvider(store,'mock')
    key=next(iter(pool.keys));pool.busy[key]=1
    try:
        pool.release(key,BatchResult({},'server error',diagnostics={'failure_kind':'http_error','http_status':520}))
        row=store.kira_keys()[0]
        assert row['status']=='TEMPORARY_ERROR' and row['cooldown_until']>time.time()
    finally:store.close()


@pytest.mark.parametrize('failure',[503,429])
def test_safe_responses_recover_in_same_job(tmp_path,failure):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=4,kira_retry_backoff=0)
    calls=[]
    def handler(req):
        calls.append(1)
        return httpx.Response(failure,headers={'Retry-After':'0'}) if len(calls)==1 else response(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(10)
        assert store.run(run)['state']=='finished' and len(calls)==2
        assert len(store.jobs())==1 and not scheduler._paused.is_set()
    finally:cleanup(store,scheduler)


def test_unknown_requires_explicit_permission(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=4,kira_retry_backoff=0)
    calls=[];scheduler,pool=start(store,run,jobs,lambda req:calls.append(1) or httpx.Response(504))
    try:
        scheduler.join(5)
        assert len(calls)==1 and store.run(run)['state']=='needs_reconciliation'
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('status,expected',[(401,'blocked_auth'),(402,'blocked_quota')])
def test_auth_and_verified_quota_stop_without_loop(tmp_path,status,expected):
    store,docs,r,jobs=fixture(tmp_path,kira_recovery_version=4)
    calls=[]
    def handler(req):
        calls.append(1)
        return httpx.Response(status,json={'error':{'code':'insufficient_quota'}})
    scheduler,pool=start(store,r,jobs,handler)
    try:
        scheduler.join(5)
        assert len(calls)==1 and store.run(r)['state']==expected
        assert not scheduler._paused.is_set()
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('state',['COOLDOWN','TEMPORARY_ERROR','UNKNOWN_ERROR'])
def test_old_soft_health_expires_without_modifying_ciphertext(tmp_path,state,monkeypatch):
    store,docs,r,jobs=fixture(tmp_path);key=store.kira_keys()[0]['id']
    original=bytes(store.db.execute('SELECT encrypted FROM kira_keys WHERE id=?',(key,)).fetchone()[0])
    try:
        store.kira_key_status(key,state,0);row=store.kira_keys()[0]
        assert row['credential_state']=='AVAILABLE' and row['cooldown_until']>0
        later=row['cooldown_until']+1;monkeypatch.setattr(time,'time',lambda:later)
        assert store.kira_keys()[0]['status']=='READY'
        assert bytes(store.db.execute('SELECT encrypted FROM kira_keys WHERE id=?',(key,)).fetchone()[0])==original
        store.change_kira_key(key,enabled=False)
        assert store.kira_keys()[0]['credential_state']=='EXPLICITLY_DISABLED_BY_USER'
    finally:store.close()


@pytest.mark.parametrize('limits',[
    {'kira_retry_budget':0},
    {'kira_request_limit':1},
    {'kira_additional_cost_limit':0,'kira_token_cost_upper_bound':1,'kira_cost_source':'fixture-verified'},
    {'kira_additional_cost_limit':1},
])
def test_recovery_caps_prevent_any_extra_http(tmp_path,limits):
    store,docs,r,jobs=fixture(tmp_path,kira_recovery_version=4,kira_retry_backoff=0,**limits)
    calls=[];scheduler,pool=start(store,r,jobs,lambda req:calls.append(1) or httpx.Response(503,headers={'Retry-After':'0'}))
    try:
        scheduler.join(5)
        assert not scheduler._thread.is_alive() and len(calls)==1
        assert store.run(r)['state']!='finished'
    finally:cleanup(store,scheduler)


def test_unknown_explicit_consent_is_frozen_and_bounded(tmp_path):
    store,docs,r,jobs=fixture(tmp_path,kira_recovery_version=4,kira_retry_backoff=0,uncertain_retry_authorized=True,kira_retry_limit=1)
    calls=[];scheduler,pool=start(store,r,jobs,lambda req:calls.append(1) or httpx.Response(504))
    try:
        scheduler.join(10)
        assert len(calls)==2 and store.run(r)['state']=='needs_reconciliation'
        assert [a['attempt_number'] for a in store.attempts(store.batches(jobs[0])[0]['id'])]==[1,2]
    finally:cleanup(store,scheduler)


def test_pause_stop_do_not_send_after_user_control(tmp_path):
    import threading
    entered=threading.Event();release=threading.Event()
    store,docs,r,jobs=fixture(tmp_path,count=9,kira_recovery_version=4,kira_retry_backoff=0)
    calls=[]
    def handler(req):
        calls.append(1);entered.set();release.wait(3)
        return httpx.Response(503,headers={'Retry-After':'0'})
    scheduler,pool=start(store,r,jobs,handler)
    try:
        assert entered.wait(2);scheduler.pause();release.set();time.sleep(.35)
        assert len(calls)==1 and scheduler._paused.is_set()
        scheduler.stop();scheduler.join(3);n=len(calls);time.sleep(.15)
        assert len(calls)==n and not scheduler._thread.is_alive()
    finally:release.set();cleanup(store,scheduler)


def test_retry_after_jitter_and_wall_clock_budget_are_durable(tmp_path,monkeypatch):
    from transcomic.kira_recovery import schedule_retry,budget_reason
    store,docs,r,jobs=fixture(tmp_path,kira_recovery_version=4,kira_retry_backoff=1,kira_recovery_seconds=10)
    try:
        job=jobs[0];store.job_state(job,'running');batch=store.batches(job)[0]
        store.claim_batch(batch['id']);attempt=store.prepare_attempt(batch['id'],1)
        d={'failure_kind':'rate_limit','http_status':429,'retry_after_seconds':3}
        store.finish_batch(batch['id'],{},'rate limit',False,d,expected_attempt_id=attempt);store.complete_attempt(attempt,d)
        monkeypatch.setattr('transcomic.kira_recovery.random.uniform',lambda a,b:.1)
        now=time.time();planned,reason=schedule_retry(store,batch['id'],d,store.kira_keys()[0]['id'],now)
        assert reason is None and planned['retry_not_before']>=now+3
        cfg=json.loads(store.job(job)['config']);assert cfg['kira_recovery_started_at']==now and cfg['kira_wait_reserved']>=3
        monkeypatch.setattr(time,'time',lambda:now+11)
        assert budget_reason(store,store.job(job),retry=True)=='recovery_wait_budget_exhausted'
    finally:store.close()


def test_restart_does_not_dispatch_unknown_or_change_old_consent(tmp_path):
    from transcomic.storage import Store
    store,docs,r,jobs=fixture(tmp_path,kira_recovery_version=4)
    calls=[];scheduler,pool=start(store,r,jobs,lambda req:calls.append(1) or httpx.Response(504))
    scheduler.join(5);before=json.loads(store.job(jobs[0])['config']);store.close()
    store=Store(tmp_path/'synthetic.db')
    try:
        assert len(calls)==1 and json.loads(store.job(jobs[0])['config'])==before
        assert len(store.attempts(store.batches(jobs[0])[0]['id']))==1
        from transcomic.kira_recovery import adopt_authorized_recovery
        adopt_authorized_recovery(store,store.job(jobs[0]));assert json.loads(store.job(jobs[0])['config'])==before
    finally:store.close()


def test_stable_workload_keeps_30_http_slots(tmp_path):
    import asyncio
    from transcomic.storage import Store
    from transcomic.documents import decode_txt
    store=Store(tmp_path/'width.sqlite3');store.add_kira_keys('synthetic-width-key');store.set_setting('concurrency','30')
    doc,_=store.import_document(tmp_path/'width.txt',decode_txt('\n'.join(f'Nguồn tổng hợp {i}' for i in range(100)).encode()),'vi','en')
    r,jobs=store.create_run([doc],['en'],provider='kira',model='mock',source_lang='vi',concurrency=30,config={'kira_multi_key':True,'kira_recovery_version':4})
    entered=active=peak=0
    async def handler(req):
        nonlocal entered,active,peak
        entered+=1;active+=1;peak=max(peak,active)
        deadline=time.monotonic()+3
        while entered<30 and time.monotonic()<deadline:await asyncio.sleep(.005)
        try:return response(req)
        finally:active-=1
    scheduler,pool=start(store,r,jobs,handler)
    try:
        scheduler.join(8);assert store.run(r)['state']=='finished' and peak==30
    finally:cleanup(store,scheduler)


def test_automation_user_pause_is_not_overridden_by_recovery(setup,tmp_path):
    import threading
    from transcomic.kira_pool import KiraPoolProvider
    repo,id,services,c=setup;gid,_,_=add_group(repo,id,tmp_path/'paused',count=9)
    entered=threading.Event();release=threading.Event();calls=[]
    def handler(req):calls.append(1);entered.set();release.wait(3);return response(req)
    services.translation.provider_factory=lambda s,j:KiraPoolProvider(s,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    repo.store.set_setting('concurrency','1')
    proof=c.validate(id);assert proof['passed'];c.start(id)
    try:
        assert entered.wait(3);c.pause();release.set();time.sleep(.4)
        assert c.paused.is_set() and len(calls)==1 and c.busy
        c.resume();c.join(12)
        assert repo.workset(id)['state']=='completed' and len(calls)==3
    finally:release.set();c.stop();c.join(5)


def test_automation_resume_does_not_reset_shared_recovery_budget(setup,tmp_path):
    from transcomic.kira_pool import KiraPoolProvider
    repo,id,services,c=setup
    add_group(repo,id,tmp_path/'first',count=3);add_group(repo,id,tmp_path/'second',count=3)
    repo.store.set_setting('kira_retry_budget','1');repo.store.set_setting('kira_retry_backoff','0')
    calls=[]
    services.translation.provider_factory=lambda s,j:KiraPoolProvider(s,'mock',transport=httpx.MockTransport(lambda req:calls.append(1) or httpx.Response(503,headers={'Retry-After':'0'})),rpm=100000,tpm=100000000)
    run(c,id,timeout=15)
    jobs=repo.store.jobs();attempts=sum(len(repo.store.attempts(b['id'])) for j in jobs for b in repo.store.batches(j['id']))
    assert len(jobs)==2 and attempts==len(calls)==3 and repo.workset(id)['state']=='needs_attention'
    anchor=repo.workset(id)['checkpoint']['kira_recovery_cycle']
    run(c,id,timeout=8)
    assert len(repo.store.jobs())==2 and len(calls)==3
    assert repo.workset(id)['checkpoint']['kira_recovery_cycle']==anchor


@pytest.mark.parametrize('status',[401,402])
def test_verified_key_rejection_uses_other_ready_key_without_global_lock(tmp_path,status):
    from collections import Counter
    store,docs,r,jobs=fixture(tmp_path,kira_recovery_version=4,kira_retry_backoff=0)
    store.add_kira_keys('second-good-key');calls=Counter()
    def handler(req):
        bad=req.headers['authorization'].endswith('fixture-recovery-key');calls[bad]+=1
        return httpx.Response(status,json={'error':{'code':'insufficient_quota'}}) if bad else response(req)
    scheduler,pool=start(store,r,jobs,handler)
    try:
        scheduler.join(6)
        assert store.run(r)['state']=='finished' and calls=={True:1,False:1}
    finally:cleanup(store,scheduler)


def test_verified_reset_deadline_is_probe_not_claimed_quota_recovery(tmp_path):
    store,docs,r,jobs=fixture(tmp_path,kira_recovery_version=4,kira_retry_backoff=0)
    calls=[]
    def handler(req):
        calls.append(1)
        return httpx.Response(402,headers={'Retry-After':'.1'},json={'error':{'code':'insufficient_quota'}}) if len(calls)==1 else response(req)
    scheduler,pool=start(store,r,jobs,handler)
    try:
        scheduler.join(5)
        assert len(calls)==2 and store.run(r)['state']=='finished'
        assert not any(k.get('quota_probe_pending') for k in pool.keys.values())
    finally:cleanup(store,scheduler)


def test_waiting_for_retry_after_is_not_a_busy_loop(tmp_path):
    from transcomic.kira_pool import KiraPoolProvider
    from transcomic.translation import Scheduler
    store,docs,r,jobs=fixture(tmp_path,kira_recovery_version=4,kira_retry_backoff=0)
    calls=[];refreshes=[]
    def handler(req):
        calls.append(time.monotonic())
        return httpx.Response(429,headers={'Retry-After':'.6'}) if len(calls)==1 else response(req)
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    original=pool.refresh
    def refresh(*a,**kw):refreshes.append(1);return original(*a,**kw)
    pool.refresh=refresh;scheduler=Scheduler(store,pool);scheduler.start_many(jobs,r)
    try:
        scheduler.join(5)
        assert store.run(r)['state']=='finished' and calls[1]-calls[0]>=.6
        assert len(refreshes)<50
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('failure',[500,502,504,'timeout'])
def test_unknown_errors_never_resend_without_consent_and_health_expires(tmp_path,failure,monkeypatch):
    store,docs,r,jobs=fixture(tmp_path,kira_recovery_version=4)
    calls=[]
    def handler(req):
        calls.append(1)
        if failure=='timeout':raise httpx.ReadTimeout('Synthetic uncertain delivery',request=req)
        return httpx.Response(failure)
    scheduler,pool=start(store,r,jobs,handler)
    try:
        scheduler.join(5)
        assert len(calls)==1 and store.run(r)['state']=='needs_reconciliation'
        row=store.kira_keys()[0]
        assert row['credential_state']=='AVAILABLE' and row['cooldown_until']>time.time()
        later=row['cooldown_until']+1;monkeypatch.setattr(time,'time',lambda:later)
        pool.refresh();assert pool.availability(1)[0]
    finally:cleanup(store,scheduler)


def test_adaptive_circuit_recovers_gradually_without_destroying_key(tmp_path,monkeypatch):
    from transcomic.kira_pool import KiraPoolProvider
    from transcomic.providers import BatchResult
    store,docs,r,jobs=fixture(tmp_path,kira_recovery_version=4)
    pool=KiraPoolProvider(store,'mock');pool.configure_gateway(30)
    key=next(iter(pool.keys));scope=pool.scopes[key]
    clock=[time.time()];monkeypatch.setattr(time,'time',lambda:clock[0])
    try:
        pool.busy[key]=1;pool.release(key,BatchResult({},'overload',diagnostics={'failure_kind':'http_server_error','http_status':503}))
        assert pool.gateway_limit==15 and pool.health[scope]['limit']==15
        assert pool.snapshot(30)['per_key'][key]['service_state']=='CIRCUIT_OPEN'
        clock[0]+=40;pool.refresh();assert pool.availability(30)[0]
        for _ in range(5):
            pool.busy[key]=1;pool.release(key,BatchResult({},diagnostics={'http_status':200}))
        assert pool.gateway_limit==16 and pool.health[scope]['limit']==16
        for _ in range(100):
            pool.busy[key]=1;pool.release(key,BatchResult({},diagnostics={'http_status':200}))
        assert pool.gateway_limit==pool.health[scope]['limit']==30
        assert store.kira_keys()[0]['credential_state']=='AVAILABLE'
    finally:store.close()


def test_retry_concurrency_is_bounded_without_reducing_fresh_dispatch(tmp_path):
    import asyncio
    from collections import Counter
    from transcomic.storage import Store
    from transcomic.documents import decode_txt
    from test_kira_auto_recovery import request_lines
    store=Store(tmp_path/'retry-width.sqlite3');store.add_kira_keys('retry-width-fixture');store.set_setting('concurrency','6')
    doc,_=store.import_document(tmp_path/'width.txt',decode_txt('\n'.join(f'Nguồn {i}' for i in range(18)).encode()),'vi','en')
    r,jobs=store.create_run([doc],['en'],provider='kira',model='mock',source_lang='vi',concurrency=6,
        config={'kira_multi_key':True,'kira_recovery_version':4,'kira_retry_concurrency':2,'kira_retry_backoff':0})
    seen=Counter();initial=active_retry=peak_retry=peak_initial=0
    async def handler(req):
        nonlocal initial,active_retry,peak_retry,peak_initial
        key=request_lines(req)[0]['id'];seen[key]+=1
        if seen[key]==1:
            initial+=1;peak_initial=max(peak_initial,initial)
            await asyncio.sleep(.06)
            initial-=1
            return httpx.Response(503,headers={'Retry-After':'0'})
        active_retry+=1;peak_retry=max(peak_retry,active_retry)
        try:await asyncio.sleep(.06);return response(req)
        finally:active_retry-=1
    scheduler,pool=start(store,r,jobs,handler)
    try:
        scheduler.join(15)
        assert store.run(r)['state']=='finished' and peak_initial==6 and peak_retry==2
        assert all(n==2 for n in seen.values())
    finally:cleanup(store,scheduler)


def test_recovery_does_not_overwrite_manual_edit_or_replay_accepted_lines(tmp_path):
    from test_kira_auto_recovery import request_lines
    store,docs,r,jobs=fixture(tmp_path,kira_recovery_version=4,kira_retry_backoff=0)
    rows=store.lines(docs[0]);sent=[]
    def handler(req):
        ids=[r['id'] for r in request_lines(req)];sent.append(ids)
        if len(sent)==1:
            store.edit_line(rows[1]['id'],'translation','A manually approved translation')
            return response(req,[{'id':rows[0]['id'],'text':'The first translation'}])
        return response(req)
    scheduler,pool=start(store,r,jobs,handler)
    try:
        scheduler.join(6)
        assert store.run(r)['state']=='finished' and sent[1]==[rows[2]['id']]
        assert store.line(rows[1]['id'])['translation']=='A manually approved translation'
        assert store.line(rows[0]['id'])['translation']=='The first translation'
        assert [(row['id'],row['source'],row['source_revision']) for row in store.lines(docs[0])]==[(row['id'],row['source'],row['source_revision']) for row in rows]
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('policy',[{'kira_additional_cost_limit':True},{'kira_token_cost_upper_bound':False},{'kira_cost_source':5},{'kira_cost_source':[]}])
def test_invalid_money_policy_is_rejected_before_job_creation(tmp_path,policy):
    with pytest.raises(ValueError):fixture(tmp_path,kira_recovery_version=4,**policy)


def test_automation_100_lines_one_start_multiple_keys_mixed_faults(setup,tmp_path):
    import asyncio,os
    from collections import Counter
    from test_kira_auto_recovery import request_lines
    from transcomic.kira_pool import KiraPoolProvider
    repo,id,services,controller=setup
    gid,_,_=add_group(repo,id,tmp_path/'hundred',count=100)
    store=repo.store;store.add_kira_keys('second-always-on-fixture')
    # This is explicit mock-only authorization, not permission for a live resend.
    store.set_setting('kira_allow_unknown_resend','1');store.set_setting('kira_retry_backoff','0')
    rows=store.lines(repo.group(gid)['document_id'])
    faults={rows[i]['id']:kind for i,kind in [(0,503),(3,429),(6,504),(9,500),(12,502),(15,'timeout'),(18,'network'),(21,'partial')]}
    seen=Counter();active=set();calls=[];by_key=Counter();peak=0
    async def handler(req):
        nonlocal peak
        batch=request_lines(req);ids={r['id'] for r in batch}
        assert not active&ids
        active.update(ids);peak=max(peak,len(active));calls.append([r['id'] for r in batch]);by_key[req.headers['authorization']]+=1
        try:
            await asyncio.sleep(.01)
            for row in batch:seen[row['id']]+=1
            bad=next((r['id'] for r in batch if r['id'] in faults and seen[r['id']]==1),None)
            kind=faults.get(bad)
            if kind=='timeout':raise httpx.ReadTimeout('Mock unknown outcome',request=req)
            if kind=='network':raise httpx.ConnectError('Mock network failure',request=req)
            if kind=='partial':return response(req,[{'id':batch[0]['id'],'text':'The translated story continues'}])
            if kind:return httpx.Response(kind,headers={'Retry-After':'0'})
            return response(req)
        finally:active.difference_update(ids)
    services.translation.provider_factory=lambda s,j:KiraPoolProvider(s,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    run(controller,id,timeout=40)
    assert repo.workset(id)['state']=='completed'
    assert all(row['state']=='done' for row in store.lines(repo.group(gid)['document_id']))
    assert len(store.jobs())==1 and len(by_key)==2 and all(n>0 for n in by_key.values())
    assert 34<len(calls)<=64 and not active
    attempts=[a for b in store.batches(store.jobs()[0]['id']) for a in store.attempts(b['id'])]
    assert all(len(a['diagnostics']['payload_sha256'])==64 for a in attempts)
    assert store.db.execute('SELECT COUNT(*) FROM api_text_versions WHERE accepted=1').fetchone()[0]==100
    evidence=dict(status='PASS',source_lines=100,completed=100,start_calls=1,continue_calls=0,restore_calls=0,jobs=len(store.jobs()),http_requests=len(calls),per_key_requests=sorted(by_key.values()),peak_active_line_ids=peak,unknown_retry_permission='explicit mock fixture only')
    path=os.environ.get('KIRA_RECOVERY_EVIDENCE')
    if path:
        from pathlib import Path
        Path(path).write_text(json.dumps(evidence,indent=2),encoding='utf-8')
