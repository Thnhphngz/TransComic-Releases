"""HTTP-dispatch regressions with synthetic data only, never real Kira."""
import json
import time
import asyncio
import httpx
import pytest
from PySide6.QtWidgets import QMessageBox
from PySide6.QtTest import QTest
from test_kira_multikey_ui import gui
from test_kira_auto_recovery import response,request_lines,fixture,start,cleanup
from transcomic.documents import decode_txt
from transcomic.kira_pool import KiraPoolProvider
from transcomic.providers import BatchResult
from transcomic.storage import Store
from transcomic.translation import Scheduler
from test_automation import setup,add_group,run,FakeEngine


@pytest.mark.parametrize('action',['file','workspace','selected'])
def test_real_manual_button_dispatches_new_cycle_after_old_review(gui,monkeypatch,tmp_path,action):
    app,store,w=gui;store.set_setting('update_auto_check','0');store.add_kira_keys('fixture-new-key-B')
    model='longcat-2.5-preview-free';w.set_model_id(model)
    doc=store.import_document(tmp_path/'synthetic.txt',decode_txt(b'Synthetic source'),'vi','en')[0]
    run,jobs=store.create_run([doc],['en'],provider='kira',model=model,source_lang='vi',concurrency=1,config={'kira_multi_key':True,'kira_recovery_version':2})
    batch=store.batches(jobs[0])[0];store.claim_batch(batch['id']);attempt=store.prepare_attempt(batch['id'],1)
    store.finish_batch(batch['id'],{},'Synthetic gateway 504',True,{'http_status':504,'failure_kind':'http_504'},expected_attempt_id=attempt)
    store.complete_attempt(attempt,{'http_status':504,'failure_kind':'http_504'})
    old=json.loads(store.job(jobs[0])['config']);old.update(kira_main_drained=True,kira_recovery_phase=2,kira_wait_used=300,kira_wait_reserved=300)
    store.db.execute('UPDATE jobs SET config=?,state=? WHERE id=?',(json.dumps(old),'completed_with_errors',jobs[0]));store.run_state(run,'completed_with_errors')
    w.workspace_ids=[doc];w.open_document(doc);w.model.selected_ids={store.lines(doc)[0]['id']};calls=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.Yes)
    monkeypatch.setattr(w,'make_provider',lambda job,key:KiraPoolProvider(store,job['model'],transport=httpx.MockTransport(lambda req:calls.append(request_lines(req)) or response(req)),rpm=100000,tpm=100000000))
    if action=='workspace':w.retry_workspace_errors()
    elif action=='file':w.retry_all_errors()
    else:w.retry_selected()
    deadline=time.monotonic()+4
    while w.scheduler and w.scheduler._thread.is_alive() and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
    assert calls,'The actual button must dispatch a new HTTP request'
    assert len(calls)==1 and calls[0][0]['id']==store.lines(doc)[0]['id']
    assert store.lines(doc)[0]['state']=='done'
    assert len(store.attempts(batch['id']))==1,'Keep historical attempts'


def test_default_gateway_cycle_has_five_bounded_requests(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=3,kira_retry_limit=4,kira_retry_backoff=0)
    calls=[];scheduler,pool=start(store,run,jobs,lambda req:calls.append(1) or httpx.Response(504))
    try:
        scheduler.join(40)
        assert not scheduler._thread.is_alive() and len(calls)==5
        assert store.run(run)['state']=='completed_with_errors' and not scheduler.quota_paused
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('switch',[False,True])
def test_504_504_200_and_live_new_key_dispatch(tmp_path,switch):
    store,docs,runid,jobs=fixture(tmp_path,kira_recovery_version=3,kira_retry_backoff=0)
    calls=[];key_a=store.kira_keys()[0]['id']
    def handler(req):
        calls.append(req.headers['authorization'])
        if len(calls)==1 and switch:
            store.change_kira_key(key_a,enabled=False);store.add_kira_keys('fixture-new-key-B')
        return httpx.Response(504) if len(calls)<3 else response(req)
    scheduler,pool=start(store,runid,jobs,handler)
    try:
        scheduler.join(14)
        assert not scheduler._thread.is_alive() and len(calls)==3
        assert store.run(runid)['state']=='finished' and not scheduler.quota_paused
        attempts=store.attempts(store.batches(jobs[0])[0]['id'])
        assert [a['diagnostics']['http_status'] for a in attempts]==[504,504,200]
        assert all(a['diagnostics']['monitor']['started_at'] for a in attempts)
        assert not any(k['status']=='QUOTA_EXHAUSTED' for k in store.kira_keys())
        if switch:assert calls[1:]==['Bearer fixture-new-key-B']*2
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('status',[429,504])
def test_retry_after_is_observed_even_with_another_ready_key(tmp_path,status):
    store,docs,runid,jobs=fixture(tmp_path,kira_recovery_version=3,kira_retry_backoff=0)
    store.add_kira_keys('fixture-independent-B');calls=[]
    def handler(req):
        calls.append(time.monotonic())
        return httpx.Response(status,headers={'Retry-After':'.12'}) if len(calls)==1 else response(req)
    scheduler,pool=start(store,runid,jobs,handler)
    try:
        scheduler.join(5)
        assert len(calls)==2 and calls[1]-calls[0]>=.11
        assert store.run(runid)['state']=='finished'
    finally:cleanup(store,scheduler)


def test_290_rows_only_24_error_rows_are_dispatched(gui,tmp_path,monkeypatch):
    app,store,w=gui;store.add_kira_keys('fixture-large-key');model='longcat-2.5-preview-free';w.set_model_id(model)
    doc=store.import_document(tmp_path/'290.txt',decode_txt('\n'.join('Synthetic source '+str(i) for i in range(290)).encode()),'vi','en')[0]
    rows=store.lines(doc)
    for row in rows[:266]:store.edit_line(row['id'],'translation','The preserved story continues')
    original=store.create_job(doc,model,'vi','en',1,[r['id'] for r in rows[266:]],config={'kira_multi_key':True,'kira_recovery_version':2})
    for batch in store.batches(original):
        store.claim_batch(batch['id']);attempt=store.prepare_attempt(batch['id'],1)
        store.finish_batch(batch['id'],{},'Synthetic 504',True,{'failure_kind':'http_504','http_status':504},expected_attempt_id=attempt)
        store.complete_attempt(attempt,{'failure_kind':'http_504','http_status':504})
    store.job_state(original,'completed_with_errors');before=store.lines(doc)[:266]
    w.workspace_ids=[doc];w.open_document(doc);seen=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.Yes)
    monkeypatch.setattr(w,'make_provider',lambda job,key:KiraPoolProvider(store,job['model'],transport=httpx.MockTransport(lambda req:seen.extend(r['id'] for r in request_lines(req)) or response(req)),rpm=100000,tpm=100000000))
    w.retry_errors_button.click()
    deadline=time.monotonic()+8
    while w.scheduler and w.scheduler._thread.is_alive() and time.monotonic()<deadline:app.processEvents();QTest.qWait(10)
    assert len(seen)==24 and set(seen)=={r['id'] for r in rows[266:]}
    assert store.lines(doc)[:266]==before
    assert all(r['state']=='done' for r in store.lines(doc))


def test_gateway_concurrency_recovers_without_changing_user_setting(tmp_path):
    store,docs,runid,jobs=fixture(tmp_path,kira_recovery_version=3)
    store.set_setting('concurrency','30');pool=KiraPoolProvider(store,'mock');pool.configure_gateway(30)
    failure=BatchResult({},'gateway',True,diagnostics={'failure_kind':'http_504','http_status':504})
    pool.gateway_feedback(failure,100);assert pool.gateway_limit==15
    for _ in range(29):pool.gateway_feedback(failure,100)
    assert pool.gateway_limit==15,'One in-flight cohort must not halve 30 times'
    for tick in range(102,252):pool.gateway_feedback(BatchResult({'x':'valid'}),tick)
    assert pool.gateway_limit==30 and store.setting('concurrency')=='30'
    assert {e['reason'] for e in pool.gateway_events}=={'gateway_timeout','stable_success'}
    store.close()


def test_live_dispatch_gateway_reduction_has_no_starvation_or_duplicate(tmp_path):
    store,docs,runid,jobs=fixture(tmp_path,count=96,kira_recovery_version=3,kira_retry_backoff=0)
    store.set_setting('concurrency','30');store.add_kira_keys('fixture-second-ready')
    store.db.execute('UPDATE jobs SET concurrency=30 WHERE id=?',(jobs[0],))
    active=0;peak=0;calls=[];live=set()
    async def handler(req):
        nonlocal active,peak
        ids=tuple(r['id'] for r in request_lines(req));assert not set(ids)&live
        live.update(ids);active+=1;peak=max(peak,active);number=len(calls);calls.append(ids)
        await asyncio.sleep(.04);active-=1;live.difference_update(ids)
        return httpx.Response(504) if number<2 else response(req)
    scheduler,pool=start(store,runid,jobs,handler)
    try:
        scheduler.join(12)
        assert not scheduler._thread.is_alive() and store.run(runid)['state']=='finished'
        assert 1<peak<=30 and len(calls)==34 and not live
        assert any(e['effective']<e['previous'] for e in pool.gateway_events)
        assert store.setting('concurrency')=='30' and all(r['state']=='done' for r in store.lines(docs[0]))
    finally:cleanup(store,scheduler)


def test_no_duplicate_processing_batch_and_restart_manual_recovery(tmp_path):
    store,docs,runid,jobs=fixture(tmp_path,kira_recovery_version=3,kira_retry_backoff=0)
    store.job_state(jobs[0],'running')
    batch=store.batches(jobs[0])[0];store.claim_batch(batch['id']);attempt=store.prepare_attempt(batch['id'],1)
    ids=[r['id'] for r in store.lines(docs[0])]
    with pytest.raises(ValueError,match='in-flight'):store.create_job(docs[0],'mock','vi','en',1,ids,allow_shared_document=True)
    path=store.path;store.close();store=Store(path)
    assert store.attempts(batch['id'])[0]['state']=='unknown'
    assert store.job(jobs[0])['state']!='running'
    from transcomic.workspace_retry import fresh_retry_config
    fresh=store.create_job(docs[0],'mock','vi','en',1,ids,config=fresh_retry_config(store,store.job(jobs[0])))
    calls=[];pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(lambda req:calls.append(1) or response(req)),rpm=100000,tpm=100000000)
    scheduler=Scheduler(store,pool);assert calls==[];scheduler.start(fresh);scheduler.join(5)
    try:
        assert len(calls)==1 and all(r['state']=='done' for r in store.lines(docs[0]))
        assert len(store.attempts(batch['id']))==1
    finally:cleanup(store,scheduler)


def test_automation_504_retries_before_tts_and_mau(setup,tmp_path):
    repo,id,services,controller=setup;gid,_,_=add_group(repo,id,tmp_path/'fixture',count=1);calls=[]
    def handler(req):
        calls.append(1)
        if len(calls)==1:
            assert FakeEngine.calls==[];return httpx.Response(504)
        return response(req)
    services.translation.provider_factory=lambda store,job:KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    run(controller,id,timeout=10)
    assert len(calls)==2 and len(FakeEngine.calls)==1 and repo.workset(id)['state']=='completed'
    mapping=repo.field(gid,'batch_jobs');assert sum(len(repo.store.attempts(b)) for ids in mapping.values() for b in repo.batch_ids(ids))==2
