"""Authorized bounded uncertain-outcome recovery; synthetic data, MockTransport only."""
import json
from collections import Counter
import httpx
import pytest
from test_kira_auto_recovery import fixture,start,cleanup,response,request_lines
from transcomic.line_structure import validate_snapshot
from transcomic.bulk import plan_exports,write_exports


@pytest.mark.parametrize('failure',['timeout',504,500,502,503])
def test_uncertain_once_recovers_without_user_action(tmp_path,failure):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=2,kira_retry_backoff=0)
    calls=[]
    def handler(req):
        calls.append((req.headers['authorization'],json.loads(req.content)['model'],request_lines(req)))
        if len(calls)==1:
            if failure=='timeout':raise httpx.ReadTimeout('Synthetic timeout',request=req)
            return httpx.Response(failure)
        return response(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(10)
        assert not scheduler._thread.is_alive()
        assert store.run(run)['state']=='finished'
        assert len(calls)==2 and calls[0][:2]==calls[1][:2]
        assert all(r['state']=='done' for r in store.lines(docs[0]))
        history=store.attempts(store.batches(jobs[0])[0]['id'])
        assert history[0]['diagnostics']['monitor']['state']=='UNKNOWN'
        assert history[-1]['diagnostics']['monitor']['state']=='SUCCEEDED_AND_COMMITTED'
        assert not scheduler._paused.is_set()
    finally:cleanup(store,scheduler)


def test_two_final_reviews_are_global_and_do_not_repeat_successful_rows(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,count=6,files=2,kira_recovery_version=2,kira_retry_backoff=0)
    bad=store.lines(docs[0])[-1]['id'];seen=Counter();phases=[]
    def handler(req):
        rows=request_lines(req);phases.append(getattr(scheduler,'recovery_phase',0))
        for r in rows:seen[r['id']]+=1
        if bad in [r['id'] for r in rows] and seen[bad]<3:
            return response(req,[{'id':r['id'],'text':'A valid translation'} for r in rows if r['id']!=bad])
        return response(req)
    # Handler runs on worker; assign scheduler before starting.
    from transcomic.kira_pool import KiraPoolProvider
    from transcomic.translation import Scheduler
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    scheduler=Scheduler(store,pool);scheduler.start_many(jobs,run)
    try:
        scheduler.join(7)
        assert store.run(run)['state']=='finished'
        assert phases==[0,0,0,0,1,2]
        assert seen[bad]==3 and all(n==1 for key,n in seen.items() if key!=bad)
        assert store.run(run)['config']['kira_recovery_phase']==2
    finally:cleanup(store,scheduler)


def test_verified_rows_clear_stale_structure_without_whitespace_edit(tmp_path):
    store,docs,run,jobs=fixture(tmp_path)
    batch=store.batches(jobs[0])[0];payload=store.claim_batch(batch['id'])
    try:
        store.finish_batch(batch['id'],{r['id']:'A valid translated sentence.' for r in payload},
            error='Duplicate or invalid line IDs/values',diagnostics={'structure_errors':[{'code':'extra_id','line_ids':[]}]})
        before=store.lines(docs[0]);document,rows=store.export_snapshot(docs)[0]
        assert not validate_snapshot(document,rows).structural
        result=write_exports(store,plan_exports([(document,rows)],tmp_path/'out'))[0]
        assert result['state']=='exported'
        assert store.lines(docs[0])==before
    finally:store.close()


@pytest.mark.parametrize('failure',['timeout',504,503])
def test_uncertain_retries_capped_at_two_even_with_larger_generic_limit(tmp_path,failure):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=2,kira_retry_limit=5,kira_retry_backoff=0)
    calls=[]
    def handler(req):
        calls.append(1)
        if failure=='timeout':raise httpx.ReadTimeout('Synthetic timeout',request=req)
        return httpx.Response(failure)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(12)
        assert not scheduler._thread.is_alive() and len(calls)==3
        assert store.run(run)['state']=='completed_with_errors'
        assert [a['attempt_number'] for a in store.attempts(store.batches(jobs[0])[0]['id'])]==[1,2,3]
        assert all(r['state']=='unknown' for r in store.lines(docs[0]))
    finally:cleanup(store,scheduler)


def test_stop_and_restart_preserve_uncertain_resend_budget(tmp_path):
    from transcomic.storage import Store
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=2,kira_retry_backoff=0)
    path=store.path;calls=[]
    for lap in range(3):
        def handler(req):calls.append(1);return httpx.Response(504)
        scheduler,pool=start(store,run,jobs,handler)
        if lap<2:
            import time
            deadline=time.monotonic()+8
            while len(calls)<lap+1 and time.monotonic()<deadline:time.sleep(.005)
            scheduler.stop()
        scheduler.join(12)
        assert not scheduler._thread.is_alive()
        assert len(calls)==lap+1
        store.close();store=Store(path)
        assert len(calls)==lap+1  # Merely opening storage never sends HTTP.
    try:
        attempts=store.attempts(store.batches(jobs[0])[0]['id'])
        assert len(attempts)==3 and [a['attempt_number'] for a in attempts]==[1,2,3]
        assert store.run(run)['state']=='completed_with_errors'
    finally:store.close()


@pytest.mark.parametrize('policy',[{'kira_retry_budget':0},{'kira_request_limit':1},{'kira_token_limit':1}])
def test_request_retry_and_token_budgets_block_extra_network(tmp_path,policy):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=2,kira_retry_backoff=0,**policy);calls=[]
    scheduler,pool=start(store,run,jobs,lambda req:calls.append(1) or httpx.Response(504))
    try:
        scheduler.join(5)
        assert len(calls)==(0 if policy.get('kira_token_limit') else 1)
        assert store.run(run)['state'] in ('blocked','completed_with_errors')
        assert not scheduler._paused.is_set()
        reserved=store.db.execute('SELECT COALESCE(SUM(reserved_tokens),0) FROM request_attempts').fetchone()[0]
        assert reserved<=store.run(run)['config']['kira_effective_token_limit']
    finally:cleanup(store,scheduler)


def test_multilingual_main_pass_drains_before_global_review(tmp_path):
    from transcomic.storage import Store
    from transcomic.documents import decode_txt
    store=Store(tmp_path/'multi.db');store.add_kira_keys('synthetic-multi-key')
    docs=[store.import_document(tmp_path/f'{i}.txt',decode_txt('Nguồn truyện tổng hợp'.encode()),'vi','en')[0] for i in range(2)]
    run,jobs=store.create_run(docs,['en','de'],provider='kira',model='mock',source_lang='vi',concurrency=1,config={'kira_multi_key':True,'kira_retry_backoff':0,'kira_recovery_version':3})
    from transcomic.languages import language
    targets={r['id']:language(store.job(j)['target_lang']).code.lower() for j in jobs for r in store.lines(store.job(j)['document_id'])}
    bad=store.lines(store.job(jobs[0])['document_id'])[0]['id'];seen=Counter();calls=[]
    def handler(req):
        rows=request_lines(req);target=targets[rows[0]['id']];calls.append(target)
        for row in rows:seen[row['id']]+=1
        if rows[0]['id']==bad and seen[bad]==1:return httpx.Response(200,json={'choices':[]})
        return response(req,[{'id':row['id'],'text':'Eine gültige Übersetzung der Geschichte' if target=='de' else 'The translated story continues'} for row in rows])
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(8)
        assert store.run(run)['state']=='finished'
        assert calls==['en','en','de','de','en']
        assert seen[bad]==2 and all(n==1 for key,n in seen.items() if key!=bad)
    finally:cleanup(store,scheduler)


def test_repeated_malformed_batch_can_split_within_existing_budget(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=2,kira_retry_limit=5,kira_retry_backoff=0)
    calls=[]
    def handler(req):
        rows=request_lines(req);calls.append([r['id'] for r in rows])
        return httpx.Response(200,json={'choices':[]}) if len(rows)>1 else response(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(6)
        assert store.run(run)['state']=='finished'
        assert [len(rows) for rows in calls]==[3,3,1,1,1]
        assert len({rows[0] for rows in calls[2:]})==3
        assert scheduler.retry_count==4 and store.run(run)['config']['kira_recovery_phase']==2
        assert all(r['state']=='done' for r in store.lines(docs[0]))
    finally:cleanup(store,scheduler)


def test_punctuation_only_response_is_retried_without_editing_periods(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=2,kira_retry_backoff=0);calls=[]
    def handler(req):
        calls.append(1)
        return response(req,[{'id':r['id'],'text':'...' if len(calls)==1 else 'A valid sentence...'} for r in request_lines(req)])
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(6)
        assert len(calls)==2 and store.run(run)['state']=='finished'
        assert all(r['translation']=='A valid sentence...' for r in store.lines(docs[0]))
    finally:cleanup(store,scheduler)


def test_same_inflight_outage_cohort_does_not_amplify_cooldown_30_times(tmp_path,monkeypatch):
    import time
    from transcomic.kira_pool import KiraPoolProvider
    from transcomic.providers import BatchResult
    store,docs,run,jobs=fixture(tmp_path)
    monkeypatch.setattr(time,'time',lambda:1000)
    pool=KiraPoolProvider(store,'mock',account_limit=30,rpm=10000,tpm=100000)
    try:
        leases=[pool.reserve(30,1) for _ in range(30)]
        assert all(leases)
        for key,adapter in leases:pool.release(key,BatchResult({},'Synthetic uncertain failure',True,diagnostics={'failure_kind':'http_server_error'}))
        assert pool.health[store.kira_keys()[0]['id']]['strikes']==1
        assert pool.cooldowns[store.kira_keys()[0]['id']]==1002
        assert not any(pool.busy.values())
    finally:store.close()


def test_explicit_resume_never_grants_unknown_permission_or_changes_snapshot(tmp_path):
    from transcomic.kira_recovery import adopt_authorized_recovery
    store,docs,run,jobs=fixture(tmp_path,kira_wait_used=7)
    batch=store.batches(jobs[0])[0];store.claim_batch(batch['id']);attempt=store.prepare_attempt(batch['id'],1)
    key=store.kira_keys()[0]['id'];d={'http_status':504,'failure_kind':'http_504','unknown_outcome':True,'key_alias':key}
    store.finish_batch(batch['id'],{},'Synthetic 504',True,d,expected_attempt_id=attempt)
    store.complete_attempt(attempt,d);store.job_state(jobs[0],'needs_intervention')
    before=json.loads(store.job(jobs[0])['config'])
    adopt_authorized_recovery(store,store.job(jobs[0]))
    after=json.loads(store.job(jobs[0])['config'])
    assert after==before and after['kira_recovery_version']==1
    assert all(before[k]==after[k] for k in ('max_requests','kira_retry_budget','kira_wait_used','auto_retries'))
    assert len(store.attempts(batch['id']))==1
    scheduler,pool=start(store,run,jobs,response)
    try:
        scheduler.join(6)
        assert store.run(run)['state']!='finished' and len(store.attempts(batch['id']))==1
    finally:cleanup(store,scheduler)


def test_exhausted_request_budget_does_not_wait_for_low_rpm(tmp_path):
    from transcomic.kira_pool import KiraPoolProvider
    from transcomic.translation import Scheduler
    store,docs,run,jobs=fixture(tmp_path,count=121,kira_recovery_version=2,kira_request_limit=1)
    calls=[]
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(lambda req:calls.append(1) or response(req)),rpm=1,tpm=1000000)
    scheduler=Scheduler(store,pool);scheduler.start_many(jobs,run)
    try:
        scheduler.join(2)
        assert not scheduler._thread.is_alive() and calls==[1]
        assert store.run(run)['state']=='blocked'
        assert len(pool.requests)==1
    finally:cleanup(store,scheduler)


def test_user_pause_during_uncertain_recovery_sends_nothing_until_resume(tmp_path):
    import time
    from transcomic.kira_pool import KiraPoolProvider
    from transcomic.translation import Scheduler
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=2,kira_retry_backoff=0);calls=[];paused_once=[]
    def handler(req):calls.append(1);return httpx.Response(504) if len(calls)==1 else response(req)
    def changed(ids):
        if len(calls)==1 and not paused_once and any(r['state']=='unknown' for r in store.lines(docs[0])):
            paused_once.append(True);scheduler.pause()
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=10000,tpm=100000)
    scheduler=Scheduler(store,pool,changed);scheduler.start_many(jobs,run)
    try:
        deadline=time.monotonic()+3
        while not scheduler._paused.is_set() and time.monotonic()<deadline:time.sleep(.005)
        assert scheduler._paused.is_set();time.sleep(.1);assert calls==[1]
        scheduler.resume();scheduler.join(8)
        assert calls==[1,1] and store.run(run)['state']=='finished'
    finally:cleanup(store,scheduler)


def test_stale_warning_after_restart_exports_without_modifying_data(tmp_path):
    from transcomic.storage import Store
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=2)
    scheduler,pool=start(store,run,jobs,response);scheduler.join(5)
    assert store.run(run)['state']=='finished'
    batch=store.batches(jobs[0])[0]
    store.record_batch_diagnostics(batch['id'],{'structure_errors':[{'code':'extra_id','line_ids':[]}]})
    before=store.lines(docs[0]);path=store.path;store.close();store=Store(path)
    try:
        doc,rows=store.export_snapshot(docs)[0]
        assert validate_snapshot(doc,rows).state=='complete'
        assert write_exports(store,plan_exports([(doc,rows)],tmp_path/'out'))[0]['state']=='exported'
        assert store.lines(docs[0])==before
    finally:store.close()


def test_observed_usage_above_estimate_blocks_further_sends(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,count=6,kira_recovery_version=2,kira_token_limit=50000);calls=[]
    def handler(req):
        calls.append(1);body=json.loads(response(req).content)
        body['usage']={'prompt_tokens':90000,'completion_tokens':10000,'total_tokens':100000}
        return httpx.Response(200,json=body)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        scheduler.join(3)
        assert calls==[1] and store.run(run)['state']=='blocked'
        assert store.db.execute('SELECT reserved_tokens FROM request_attempts').fetchone()[0]==100000
        assert sum(r['state']=='done' for r in store.lines(docs[0]))==3
    finally:cleanup(store,scheduler)


def test_parent_run_never_completes_between_local_phases_or_for_subset(tmp_path):
    from transcomic.kira_pool import KiraPoolProvider
    from transcomic.translation import Scheduler
    store,docs,run,jobs=fixture(tmp_path,files=2,kira_recovery_version=2)
    wrong=[]
    def observe(ids):
        if store.run(run)['state']=='finished' and any(j['state']!='finished' for j in store.run_jobs(run)):wrong.append(True)
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(response),rpm=10000,tpm=100000)
    scheduler=Scheduler(store,pool,observe);scheduler.start_many(jobs[:1],run)
    try:
        scheduler.join(5)
        assert not wrong and store.job(jobs[0])['state']=='finished'
        assert store.job(jobs[1])['state']=='ready'
        assert store.run(run)['state']!='finished' and pool.monitor.state!='finished'
        assert store.run(run)['config']['language_states']['en']!='completed'
    finally:cleanup(store,scheduler)


def test_user_stop_at_last_commit_does_not_grant_pipeline_completion(tmp_path):
    from transcomic.kira_pool import KiraPoolProvider
    from transcomic.translation import Scheduler
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=2)
    def changed(ids):
        if ids and all(r['state']=='done' for r in store.lines(docs[0])):scheduler.stop()
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(response),rpm=10000,tpm=100000)
    scheduler=Scheduler(store,pool,changed);scheduler.start_many(jobs,run)
    try:
        scheduler.join(4)
        assert all(r['state']=='done' for r in store.lines(docs[0]))
        assert store.run(run)['state']=='stopped' and pool.monitor.state=='stopped'
    finally:cleanup(store,scheduler)


def test_five_docx_30_workers_mixed_recovery_and_export(tmp_path):
    import asyncio
    from docx import Document
    from transcomic.bulk import import_many
    from transcomic.storage import Store
    store=Store(tmp_path/'five.db');store.add_kira_keys('synthetic-account-A synthetic-account-B')
    ids=[k['id'] for k in store.kira_keys()]
    for key in ids:store.set_kira_account_scope(key,ids[0])
    store.set_setting('concurrency','30');paths=[]
    for i in range(5):
        word=Document()
        for n in range(121):word.add_paragraph(f'Nguồn chương {i} dòng {n}')
        path=tmp_path/f'chapter-{i}.docx';word.save(path);paths.append(path)
    docs=import_many(store,paths,'vi','en')['document_ids']
    run,jobs=store.create_run(docs,['en'],provider='kira',model='mock',source_lang='vi',concurrency=30,config={'kira_multi_key':True,'kira_retry_backoff':0,'kira_recovery_version':3})
    errors={store.lines(docs[d])[n]['id']:kind for d,n,kind in [(0,0,429),(0,3,500),(1,6,502),(1,9,503),(2,12,'timeout'),(2,15,504),(3,120,'json'),(4,117,'duplicate'),(4,114,'missing')]}
    seen=Counter();active_ids=set();active=peak=entered=0
    async def handler(req):
        nonlocal active,peak,entered
        rows=request_lines(req);ids={r['id'] for r in rows}
        assert not ids&active_ids
        active_ids.update(ids);active+=1;entered+=1;peak=max(peak,active)
        try:
            while entered<30:await asyncio.sleep(.001)
            await asyncio.sleep(.003)
            for r in rows:seen[r['id']]+=1
            bad=next((r['id'] for r in rows if r['id'] in errors),None)
            kind=errors.get(bad)
            if bad and seen[bad]<=(2 if kind=='json' else 1):
                if kind=='timeout':raise httpx.ReadTimeout('Synthetic timeout',request=req)
                if kind=='json':return httpx.Response(200,json={'choices':[{'message':{'content':'not JSON'}}]})
                if kind=='duplicate':return response(req,[{'id':bad,'text':'A translation'},{'id':bad,'text':'Another translation'}]+[{'id':r['id'],'text':'A valid translation'} for r in rows if r['id']!=bad])
                if kind=='missing':return response(req,[{'id':r['id'],'text':'A valid translation'} for r in rows if r['id']!=bad])
                return httpx.Response(kind,headers={'Retry-After':'0'})
            return response(req)
        finally:active_ids.difference_update(ids);active-=1
    scheduler,pool=start(store,run,jobs,handler,account_limit=30)
    try:
        scheduler.join(25)
        assert not scheduler._thread.is_alive() and store.run(run)['state']=='finished'
        assert peak==30 and not active_ids and not any(pool.busy.values())
        assert all(len(store.lines(d))==121 and all(r['state']=='done' for r in store.lines(d)) for d in docs)
        snapshots=store.export_snapshot(docs)
        assert all(not validate_snapshot(d,r).structural for d,r in snapshots)
        results=write_exports(store,plan_exports(snapshots,tmp_path/'export'))
        assert len(results)==5 and all(r['state']=='exported' for r in results)
        assert scheduler.retry_count<=30 and not scheduler._paused.is_set()
        assert seen[next(key for key,value in errors.items() if value=='json')]==3
    finally:cleanup(store,scheduler)
