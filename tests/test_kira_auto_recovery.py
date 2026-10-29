"""Synthetic data and MockTransport only; no account/API or GPU access."""
import asyncio
import json
import time
from collections import Counter

import httpx
import pytest

from transcomic.bulk import workspace_status
from transcomic.documents import decode_txt
from transcomic.kira_pool import KiraPoolProvider
from transcomic.providers import parse_line_response
from transcomic.storage import Store
from transcomic.translation import Scheduler


def request_lines(request):
    return json.loads(json.loads(request.content)['messages'][1]['content'])['lines']


def response(request, items=None):
    return httpx.Response(200, json={'choices':[{'message':{'content':json.dumps({'lines':items if items is not None else [
        {'id':r['id'],'text':'The translated story continues'} for r in request_lines(request)]})},'finish_reason':'stop'}]})


def fixture(tmp_path, count=3, files=1, **config):
    store=Store(tmp_path/'synthetic.db');store.add_kira_keys('fixture-recovery-key')
    store.set_setting('concurrency','1')
    docs=[store.import_document(tmp_path/f'synthetic-{i}.txt',decode_txt('\n'.join(f'Văn bản tổng hợp dòng {j}' for j in range(count)).encode()),'vi','en')[0] for i in range(files)]
    try:
        run,jobs=store.create_run(docs,['en'],provider='kira',model='mock',source_lang='vi',concurrency=1,
            config={'kira_multi_key':True,'kira_recovery_version':1,**config})
    except Exception:
        store.close();raise
    return store,docs,run,jobs


def start(store, run, jobs, handler, **kwargs):
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000,**kwargs)
    scheduler=Scheduler(store,pool);scheduler.start_many(jobs,run)
    return scheduler,pool


def cleanup(store,scheduler):
    scheduler.stop();scheduler.join(3)
    assert not scheduler._thread.is_alive()
    store.close()


def test_unavailable_key_never_becomes_user_pause(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,files=2)
    scheduler,pool=start(store,run,jobs,lambda req:httpx.Response(401))
    try:
        scheduler.join(.3)
        assert not scheduler._paused.is_set()
        assert not scheduler._thread.is_alive()
        assert store.run(run)['state']=='needs_intervention'
    finally:cleanup(store,scheduler)


def test_504_does_not_permanently_disable_key(tmp_path):
    store,docs,run,jobs=fixture(tmp_path)
    scheduler,pool=start(store,run,jobs,lambda req:httpx.Response(504))
    try:
        scheduler.join(2)
        assert store.kira_keys()[0]['status'] not in ('INVALID','UNKNOWN_ERROR')
        assert len(store.attempts(store.batches(jobs[0])[0]['id']))==1
        assert all(r['state']=='unknown' for r in store.lines(docs[0]))
    finally:cleanup(store,scheduler)


def test_429_then_success_auto_recovers_same_key_model(tmp_path):
    store,docs,run,jobs=fixture(tmp_path)
    calls=[]
    def handler(req):
        calls.append((req.headers['authorization'],json.loads(req.content)['model'],request_lines(req)))
        return httpx.Response(429,headers={'Retry-After':'0'},json={'error':{'code':'rate_limit'}}) if len(calls)==1 else response(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(6)
        assert not scheduler._thread.is_alive()
        assert store.run(run)['state']=='finished'
        assert len(calls)==2 and calls[0][:2]==calls[1][:2]
        assert scheduler.retry_count==1 and not scheduler._paused.is_set()
        assert all(r['state']=='done' for r in store.lines(docs[0]))
    finally:cleanup(store,scheduler)


def test_partial_response_repairs_only_missing_id(tmp_path):
    store,docs,run,jobs=fixture(tmp_path)
    calls=[]
    def handler(req):
        lines=request_lines(req);calls.append([r['id'] for r in lines])
        return response(req,[{'id':r['id'],'text':'The translated story continues'} for r in lines[:2]]) if len(calls)==1 else response(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(6)
        assert store.run(run)['state']=='finished'
        assert len(calls)==2 and calls[1]==calls[0][2:]
        assert [r['translation_revision'] for r in store.lines(docs[0])]==[1,1,1]
    finally:cleanup(store,scheduler)


def test_complete_rows_override_stale_intervention_badge():
    rows=[dict(source='Nguồn',translation='Translation',state='done',source_revision=0,translation_source_revision=0) for _ in range(121)]
    assert workspace_status(rows,'needs_intervention')['state']=='Hoàn thành đầy đủ'


def test_duplicate_values_are_valid_with_distinct_ids():
    result=parse_line_response(json.dumps({'lines':[{'id':i,'text':'Yes'} for i in ('a','b')]}),{'a','b'})
    assert result.values=={'a':'Yes','b':'Yes'} and not result.error


@pytest.mark.parametrize('raw,accepted',[
    ('{"lines":[{"id":"a","text":"Yes"},{"id":"a","text":"Again"},{"id":"b","text":"No"}]}',{'b':'No'}),
    ('{"lines":[{"id":"a","text":"Yes"}]}',{'a':'Yes'}),
    ('{"lines":[{"id":"foreign","text":"Yes"},{"id":"b","text":"No"}]}',{'b':'No'}),
    ('{"lines":[{"id":1,"text":"Yes"},{"id":"b","text":"No"}]}',{'b':'No'}),
    ('{"lines":[{"id":"a","id":"b","text":"Ambiguous"}]}',{}),
    ('{"lines":[{"id":"a","text":"one","text":"two"}]}',{}),
    ('{"lines":[{"id":"a","text":"Truncated',{}),
    ('{"lines":[{"id":"a","text":"Split\\nline"}]}',{}),
    ('{"lines":[{"id":"a","text":"Control\\u0000char"}]}',{}),
    ('{"lines":[{"id":"a","text":"Invalid\\ud800"}]}',{}),
    ('Explanation: {"lines":[]}',{}),
    ('{"lines":[{"id":"a","text":" "}]}',{}),
])
def test_invalid_response_keeps_only_proven_ids(raw,accepted):
    result=parse_line_response(raw,{'a','b'})
    assert result.error and result.values==accepted


@pytest.mark.parametrize('wrapper',['plain','data','result','fence'])
def test_wrappers_unicode_order_and_equal_values(wrapper):
    obj={'lines':[{'id':'b','text':'「はい」… 🙂'},{'id':'a','text':'「はい」… 🙂'}]}
    if wrapper in ('data','result'):obj={wrapper:obj}
    text=json.dumps(obj)
    if wrapper=='fence':text='```json\n'+text+'\n```'
    result=parse_line_response(text,{'a','b'})
    assert not result.error and result.values=={'b':'「はい」… 🙂','a':'「はい」… 🙂'}


@pytest.mark.parametrize('header,expected',[('2',2),('0',0),('NaN',None),('inf',None),('-1',None),('bad',None)])
def test_retry_after_is_finite_and_nonnegative(header,expected):
    from transcomic.providers import KiraProvider
    async def run():
        provider=KiraProvider('fixture','mock',transport=httpx.MockTransport(lambda r:httpx.Response(429,headers={'Retry-After':header})))
        return await provider.translate([{'id':'a','source':'Nguồn'}],'vi','en')
    result=asyncio.run(run())
    assert result.diagnostics['retry_after_seconds']==expected
    assert result.diagnostics['failure_kind']=='rate_limit'


def test_retry_after_http_date_and_reset_header():
    from datetime import datetime,timedelta,timezone
    from email.utils import format_datetime
    from transcomic.providers import KiraProvider
    date=format_datetime(datetime.now(timezone.utc)+timedelta(seconds=30),usegmt=True)
    async def run(headers):
        p=KiraProvider('fixture','mock',transport=httpx.MockTransport(lambda r:httpx.Response(429,headers=headers)))
        return (await p.translate([{'id':'a','source':'Nguồn'}],'vi','en')).diagnostics['retry_after_seconds']
    assert 25<=asyncio.run(run({'Retry-After':date}))<=30
    assert asyncio.run(run({'x-ratelimit-reset-requests':'500ms'}))==.5


@pytest.mark.parametrize('failure',[504,500,502,503,408,'timeout','read_error','connect_after_send'])
def test_uncertain_delivery_is_never_resent_or_invalidated(tmp_path,failure):
    store,docs,run,jobs=fixture(tmp_path);calls=[]
    async def handler(req):
        calls.append(request_lines(req))
        if failure=='timeout':raise httpx.ReadTimeout('fixture',request=req)
        if failure=='read_error':raise httpx.ReadError('fixture',request=req)
        if failure=='connect_after_send':
            await req.extensions['trace']('http11.send_request_body.complete',{})
            raise httpx.ConnectError('fixture',request=req)
        return httpx.Response(failure)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(3)
        assert not scheduler._thread.is_alive() and not scheduler._paused.is_set()
        assert len(calls)==1 and scheduler.retry_count==0
        assert all(r['state']=='unknown' for r in store.lines(docs[0]))
        assert store.kira_keys()[0]['status']=='TEMPORARY_ERROR'
    finally:cleanup(store,scheduler)


def test_confirmed_connect_failure_auto_recovers(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,kira_retry_backoff=0);calls=[]
    def handler(req):
        calls.append(request_lines(req))
        if len(calls)==1:raise httpx.ConnectError('No connection established',request=req)
        return response(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(5)
        assert not scheduler._paused.is_set() and store.run(run)['state']=='finished'
        assert len(calls)==2 and scheduler.retry_count==1
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('config,expected',[
    ({'kira_retry_limit':0},1),({'kira_retry_budget':0},1),
    ({'kira_retry_limit':2,'kira_retry_backoff':0},3),
    ({'kira_request_limit':1},1),({'rate_wait_budget':1},1),
])
def test_failure_budgets_bound_requests(tmp_path,config,expected):
    store,docs,run,jobs=fixture(tmp_path,**config);calls=[]
    def handler(req):
        calls.append(request_lines(req))
        return httpx.Response(429,headers={'Retry-After':'10' if config.get('rate_wait_budget') else '0'})
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(5)
        assert not scheduler._thread.is_alive() and not scheduler._paused.is_set()
        assert len(calls)==expected
        assert store.run(run)['state']=='needs_intervention'
        assert len(store.attempts(store.batches(jobs[0])[0]['id']))==expected
    finally:cleanup(store,scheduler)


def test_global_retry_budget_is_shared_across_files(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,files=3,kira_retry_budget=1,kira_retry_backoff=0);calls=[]
    def handler(req):
        calls.append(request_lines(req));return httpx.Response(429,headers={'Retry-After':'0'})
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(5)
        attempts=[a for j in jobs for b in store.batches(j) for a in store.attempts(b['id'])]
        assert not scheduler._thread.is_alive() and len(calls)==4
        assert sum(a['attempt_number']>1 for a in attempts)==1
        assert store.run(run)['state']=='needs_intervention'
    finally:cleanup(store,scheduler)


def test_stop_during_cooldown_never_sends_later(tmp_path):
    store,docs,run,jobs=fixture(tmp_path);calls=[]
    def handler(req):calls.append(request_lines(req));return httpx.Response(429,headers={'Retry-After':'60'})
    scheduler,pool=start(store,run,jobs,handler)
    try:
        deadline=time.monotonic()+3
        while not scheduler.waiting and time.monotonic()<deadline:time.sleep(.01)
        assert scheduler.waiting
        scheduler.stop();scheduler.join(2);time.sleep(.05)
        assert len(calls)==1 and store.run(run)['state']=='stopped' and not scheduler._thread.is_alive()
    finally:cleanup(store,scheduler)


def test_model_permission_is_specific_and_does_not_change_model(tmp_path):
    store,docs,run,jobs=fixture(tmp_path);calls=[]
    def handler(req):calls.append(json.loads(req.content)['model']);return httpx.Response(403)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(2)
        assert calls==['mock'] and store.kira_keys()[0]['status']=='PERMISSION_DENIED'
        other=KiraPoolProvider(store,'other-explicit-model')
        assert other.availability(1)[0]
        assert not pool.availability(1)[0]
    finally:cleanup(store,scheduler)


def test_parallel_files_recover_without_duplicate_inflight_batches(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,count=12,files=3,kira_retry_backoff=0)
    store.add_kira_keys('fixture-second-key');store.set_setting('concurrency','2')
    keys=store.kira_keys()
    for key in keys:store.set_kira_account_scope(key['id'],key['id'])
    calls=Counter();active=set();owners={};peak=0
    async def handler(req):
        nonlocal peak
        ids=tuple(r['id'] for r in request_lines(req));owner=(req.headers['authorization'],json.loads(req.content)['model'])
        assert ids not in active
        if ids in owners:assert owners[ids]==owner
        owners[ids]=owner;active.add(ids);peak=max(peak,len(active));calls[ids]+=1
        fail_this=calls[ids]==1 and len(calls)<=3
        await asyncio.sleep(.003);active.remove(ids)
        if fail_this:return httpx.Response(429,headers={'Retry-After':'0'})
        return response(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(8)
        assert not scheduler._thread.is_alive() and not scheduler._paused.is_set()
        assert store.run(run)['state']=='finished' and 1<peak<=4
        assert all(n in (1,2) for n in calls.values())
        assert all(r['translation_revision']==1 for d in docs for r in store.lines(d))
        snapshot=pool.monitor_snapshot(2)
        assert snapshot['failed_requests']>0 and snapshot['translated_lines']==36
        assert not any(f['failed_lines'] or f['unknown_lines'] for v in snapshot['per_key'].values() for f in v['files'])
    finally:cleanup(store,scheduler)


def test_nearly_complete_121_files_repair_last_line(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,count=121,files=2,kira_retry_backoff=0)
    failed=set();calls=[]
    def handler(req):
        rows=request_lines(req);calls.append([r['id'] for r in rows])
        if len(rows)==1 and rows[0]['id'] not in failed:
            failed.add(rows[0]['id']);return response(req,[])
        return response(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(10)
        assert store.run(run)['state']=='finished' and scheduler.retry_count==2
        assert all(store.job(j)['state']=='finished' for j in jobs)
        assert all(not b['error'] and b['state']=='done' for j in jobs for b in store.batches(j))
        assert all(workspace_status(store.lines(d),store.job(j)['state'])['done']==121 for d,j in zip(docs,jobs))
    finally:cleanup(store,scheduler)


def test_content_filter_without_content_is_not_retried(tmp_path):
    store,docs,run,jobs=fixture(tmp_path);calls=[]
    def handler(req):
        calls.append(1)
        return httpx.Response(200,json={'choices':[{'finish_reason':'content_filter','message':{'content':None}}]})
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(2)
        assert len(calls)==1 and not scheduler._thread.is_alive()
    finally:cleanup(store,scheduler)


def test_new_kira_jobs_preserve_verified_punctuation_and_legacy_policy(tmp_path):
    from transcomic.postprocess import normalize
    source='Anh ấy nói không';raw='"No. Not today!" … 🙂'
    assert normalize(source,raw,preserve_punctuation=True)[0]==raw
    assert normalize(source,raw)[0]!=raw
    store,docs,run,jobs=fixture(tmp_path,count=1)
    def handler(req):return response(req,[{'id':request_lines(req)[0]['id'],'text':raw}])
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(2)
        assert store.lines(docs[0])[0]['translation']==raw
        trace=store.db.execute('SELECT raw_text,processed_text FROM api_text_versions').fetchone()
        assert trace[0]==trace[1]==raw
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('state',['provider_recovering','network_waiting','waiting_rate_limit','retry_scheduled','user_paused'])
def test_restart_interrupts_waiting_jobs_without_network_or_budget_reset(tmp_path,state):
    store,docs,run,jobs=fixture(tmp_path,kira_retry_limit=1,kira_retry_budget=1)
    original=store.job(jobs[0]);store.job_state(jobs[0],state);store.run_state(run,state)
    store.run_language_state(run,'en',state);store.close()
    store=Store(tmp_path/'synthetic.db')
    try:
        assert store.job(jobs[0])['state']==store.run(run)['state']=='interrupted'
        assert store.run(run)['config']['language_states']['en']=='interrupted'
        assert store.job(jobs[0])['auto_retries']==original['auto_retries']==1
        assert store.job(jobs[0])['max_requests']==original['max_requests']
        assert not store.attempts(store.batches(jobs[0])[0]['id'])
    finally:store.close()


def test_retry_budget_survives_explicit_stop_restart_and_confirmation(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,kira_retry_budget=1,kira_retry_backoff=.1)
    first_done=__import__('threading').Event();holder={};calls=[]
    def handler(req):calls.append(1);return httpx.Response(429,headers={'Retry-After':'0'})
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    def changed(ids):
        if ids and not first_done.is_set():holder['s'].pause();first_done.set()
    scheduler=Scheduler(store,pool,changed);holder['s']=scheduler;scheduler.start_many(jobs,run)
    assert first_done.wait(3)
    scheduler.stop();scheduler.join(2)
    assert len(calls)==1 and not scheduler._thread.is_alive()
    budget=store.job(jobs[0])['max_requests'];store.close()
    store=Store(tmp_path/'synthetic.db')
    assert store.job(jobs[0])['max_requests']==budget
    assert len(calls)==1  # Opening storage never sends or resumes automatically.
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(5)
        attempts=store.attempts(store.batches(jobs[0])[0]['id'])
        assert not scheduler._thread.is_alive() and len(calls)==2
        assert [a['attempt_number'] for a in attempts]==[1,2]
        assert store.run(run)['state']=='needs_intervention'
    finally:cleanup(store,scheduler)


def test_legacy_unknown_key_requires_last_matching_transient_evidence(tmp_path):
    store,docs,run,jobs=fixture(tmp_path)
    key=store.kira_keys()[0]['id'];batch=store.batches(jobs[0])[0]
    store.job_state(jobs[0],'running');store.claim_batch(batch['id']);attempt=store.prepare_attempt(batch['id'],1)
    diagnostics={'failure_kind':'http_504','http_status':504,'key_alias':key}
    store.finish_batch(batch['id'],{},'HTTP 504',True,diagnostics,expected_attempt_id=attempt)
    store.complete_attempt(attempt,diagnostics);store.kira_key_status(key,'UNKNOWN_ERROR');store.close()
    store=Store(tmp_path/'synthetic.db')
    try:
        pool=KiraPoolProvider(store,'mock')
        assert store.kira_keys()[0]['status']=='TEMPORARY_ERROR' and store.kira_keys()[0]['cooldown_until']>time.time()
        assert all(r['state']=='unknown' for r in store.lines(docs[0]))
        assert len(store.attempts(batch['id']))==1
        store.add_kira_keys('unverified-fixture-key');other=store.kira_keys()[1]['id']
        store.kira_key_status(other,'UNKNOWN_ERROR');KiraPoolProvider(store,'mock')
        assert next(k for k in store.kira_keys() if k['id']==other)['status']=='TEMPORARY_ERROR'
    finally:store.close()


def test_expired_temporary_status_recovers_without_restoring_disabled_keys(tmp_path,monkeypatch):
    store,docs,run,jobs=fixture(tmp_path);key=store.kira_keys()[0]['id']
    try:
        store.kira_key_status(key,'TEMPORARY_ERROR',time.time()-1)
        assert store.kira_keys()[0]['status']=='READY'
        store.kira_key_status(key,'COOLDOWN',time.time()-1);store.change_kira_key(key,enabled=False)
        assert not KiraPoolProvider(store,'mock').availability(1)[0]
        assert store.kira_keys()[0]['status']=='DISABLED'
    finally:store.close()


def test_limiter_shares_account_and_recovers_gradually_without_herd(tmp_path,monkeypatch):
    from transcomic.providers import BatchResult
    store,docs,run,jobs=fixture(tmp_path);store.add_kira_keys('second-fixture-key')
    ids=[k['id'] for k in store.kira_keys()]
    for key in ids:store.set_kira_account_scope(key,ids[0])
    pool=KiraPoolProvider(store,'mock',account_limit=4,rpm=60,tpm=1000)
    first=pool.reserve(4,1);assert first
    try:
        pool.release(first[0],BatchResult({},'429',diagnostics={'failure_kind':'rate_limit','retry_after_seconds':10}))
        assert pool.reserve(4,1) is None
        clock=time.time()+11;monkeypatch.setattr(time,'time',lambda:clock)
        lease=pool.reserve(4,1);assert lease
        assert pool.reserve(4,1) is None  # Shared account pacing across both keys.
        assert pool.health[ids[0]]['limit']==2
        pool.release(lease[0]);clock+=1.1
        assert pool.reserve(4,1)
    finally:store.close()


def test_healthy_file_stays_complete_when_another_file_cannot_recover(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,files=2,kira_retry_limit=0)
    bad={r['id'] for r in store.lines(docs[1])}
    def handler(req):return httpx.Response(200,json={'choices':[{'message':{'content':'broken'}}]}) if request_lines(req)[0]['id'] in bad else response(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(3)
        assert store.run(run)['state']=='needs_intervention'
        assert store.job(jobs[0])['state']=='finished'
        assert store.job(jobs[1])['state']=='needs_intervention'
        assert workspace_status(store.lines(docs[0]),store.job(jobs[0])['state'])['state']=='Hoàn thành đầy đủ'
    finally:cleanup(store,scheduler)


def test_api_failure_does_not_become_success_from_old_usable_translation(tmp_path):
    store=Store(tmp_path/'synthetic.db');store.add_kira_keys('fixture')
    doc=store.import_document(tmp_path/'old.txt',decode_txt('Nguồn cũ'.encode()),'vi','en')[0]
    row=store.lines(doc)[0];store.edit_line(row['id'],'translation','Old valid translation')
    job=store.create_job(doc,'mock','vi','en',1,[row['id']],config={'kira_multi_key':True})
    scheduler,pool=start(store,None,[job],lambda req:httpx.Response(401))
    try:
        scheduler.join(2)
        assert store.job(job)['state']=='blocked_auth'
        assert store.line(row['id'])['translation']=='Old valid translation'
        assert store.batch(store.batches(job)[0]['id'])['state']=='error'
        assert workspace_status(store.lines(doc),'needs_intervention')['state']!='Hoàn thành đầy đủ'
    finally:cleanup(store,scheduler)


def test_new_kira_prompt_freezes_target_ids_without_changing_gemini_prompt(tmp_path):
    from transcomic.prompts import messages,PROMPT_VERSION,KIRA_RECOVERY_PROMPT_VERSION
    store,docs,run,jobs=fixture(tmp_path)
    try:
        job=store.job(jobs[0]);payload=store.batches(job['id'])[0]['payload']
        assert job['prompt_version']==store.run(run)['config']['prompt_version']==KIRA_RECOVERY_PROMPT_VERSION
        prompt=messages(payload,job['source_lang'],job['target_lang'],job['prompt_version'])[0]['content']
        assert 'Copy each ID verbatim' in prompt and 'Preserve source punctuation' in prompt
        assert all(r['id'] in prompt for r in payload)
        assert 'Use no internal or final periods' in messages(payload,'vi','en',PROMPT_VERSION)[0]['content']
    finally:store.close()


def test_quota_is_scoped_to_account_model_without_key_rotation_bypass(tmp_path):
    from transcomic.providers import BatchResult
    store,docs,run,jobs=fixture(tmp_path);store.add_kira_keys('fixture-other-key')
    ids=[k['id'] for k in store.kira_keys()]
    for key in ids:store.set_kira_account_scope(key,ids[0])
    try:
        pool=KiraPoolProvider(store,'mock',rpm=1000,tpm=10000)
        lease=pool.reserve(2,1);key=lease[0]
        pool.release(key,BatchResult({},'Quota exhausted',diagnostics={'failure_kind':'quota_exhausted','http_status':429,'quota_scope':'account'}))
        assert pool.reserve(2,1) is None  # Both keys share the same account.
        other=KiraPoolProvider(store,'other-explicit-model',rpm=1000,tpm=10000)
        assert other.availability(1)[0]  # User may explicitly select another model.
        ids=[k['id'] for k in store.kira_keys()]
        store.set_kira_account_scope(ids[1],ids[1])
        independent=KiraPoolProvider(store,'mock',rpm=1000,tpm=10000)
        second=independent.reserve(1,1);assert second and second[0]==ids[1]
        independent.release(second[0])
        with pytest.raises(TypeError):store.change_kira_key(key,restore=True)
        pool.refresh();assert not pool.availability(1)[0]  # Verified account quota cannot be cleared by a restore action.
    finally:store.close()


def test_provider_reported_rpm_only_lowers_configured_cap(tmp_path,monkeypatch):
    from transcomic.providers import BatchResult
    store,docs,run,jobs=fixture(tmp_path)
    try:
        pool=KiraPoolProvider(store,'mock',rpm=60,tpm=10000)
        first=pool.reserve(1,1)
        pool.release(first[0],BatchResult({},'429',diagnostics={'failure_kind':'rate_limit','retry_after_seconds':0,'rate_limit_headers':{'x-ratelimit-limit-requests':'1'}}))
        clock=time.time()+2;monkeypatch.setattr(time,'time',lambda:clock)
        assert pool.reserve(1,1) is None
        clock+=60;second=pool.reserve(1,1);assert second
        pool.release(second[0])
    finally:store.close()


def test_preparation_exception_releases_unsent_key_slot(tmp_path,monkeypatch):
    store,docs,run,jobs=fixture(tmp_path);calls=[]
    def fail(*args,**kwargs):raise RuntimeError('synthetic SQLite preparation failure')
    monkeypatch.setattr(store,'prepare_attempt',fail)
    scheduler,pool=start(store,run,jobs,lambda req:calls.append(1) or response(req))
    try:
        scheduler.join(2)
        assert not scheduler._thread.is_alive() and not calls and not any(pool.busy.values())
        assert store.run(run)['state']=='interrupted' and not scheduler._paused.is_set()
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('setting',['kira_retry_limit','rate_wait_budget','rate_backoff_max','rate_cooldown_limit'])
def test_nonfinite_recovery_settings_fail_before_creating_jobs(tmp_path,setting):
    with pytest.raises(ValueError):fixture(tmp_path,**{setting:float('nan')})


def test_editing_previously_accepted_row_during_partial_retry_stays_stale(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,kira_retry_backoff=0);calls=[]
    first=store.lines(docs[0])[0]['id']
    def handler(req):
        rows=request_lines(req);calls.append(rows)
        if len(calls)==1:return response(req,[{'id':r['id'],'text':'A verified translation'} for r in rows[:2]])
        store.edit_line(first,'source','Nguồn đã được người dùng sửa')
        return response(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(4)
        assert len(calls)==2 and len(calls[1])==1
        assert store.job(jobs[0])['state']=='needs_intervention'
        assert store.line(first)['state']=='stale' and store.line(first)['translation']=='A verified translation'
        assert len(store.lines(docs[0]))==3
    finally:cleanup(store,scheduler)


def test_untrusted_rate_limit_headers_cannot_echo_credentials():
    from transcomic.providers import KiraProvider
    secret='synthetic-private-key'
    provider=KiraProvider(secret,'mock',transport=httpx.MockTransport(lambda req:httpx.Response(
        429,headers={'Retry-After':secret,'x-ratelimit-reset-requests':secret},
        json={'error':{'code':secret}})))
    result=asyncio.run(provider.translate([{'id':'a','source':'Nguồn tổng hợp'}],'vi','en'))
    assert secret not in json.dumps(result.diagnostics)
    assert result.diagnostics['retry_after_seconds'] is None
    assert result.diagnostics['failure_kind']=='rate_limit'


def test_pinned_cooling_retry_does_not_block_other_keys_retry_in_same_file(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,count=6,kira_retry_backoff=0)
    store.add_kira_keys('fixture-second-recovery-key')
    for key in store.kira_keys():store.set_kira_account_scope(key['id'],key['id'])
    calls=[];counts=Counter()
    def handler(req):
        name='first' if req.headers['authorization']=='Bearer fixture-recovery-key' else 'second'
        counts[name]+=1;calls.append((name,counts[name]))
        if counts[name]==1:
            if name=='first':raise httpx.ConnectError('Synthetic failure before sending body',request=req)
            return httpx.Response(200,json={'choices':[]})
        return response(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(6)
        assert store.run(run)['state']=='finished'
        assert calls.index(('second',2))<calls.index(('first',2))
        assert counts=={'first':2,'second':2}
        assert all(row['state']=='done' for row in store.lines(docs[0]))
    finally:cleanup(store,scheduler)
