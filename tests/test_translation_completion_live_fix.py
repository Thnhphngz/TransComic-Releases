"""Kira/DeepSeek completion and UI liveness; HTTP mocks, isolated Stores."""
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import threading
import time

import httpx
import pytest
from PySide6.QtCore import QTimer,Qt
from PySide6.QtTest import QTest
from transcomic.completion import authorize
from transcomic.deepseek import DeepSeekProvider,MODEL,settings
from transcomic.documents import decode_txt
from transcomic.translation import Scheduler
from test_kira_auto_recovery import fixture,response,request_lines,cleanup
from test_automation_ui import gui,wait
from test_automation import setup,add_group,FakeEngine


@pytest.mark.parametrize('failure',[429,503,504,'timeout','json','partial'])
def test_deepseek_retries_beyond_six_attempts_without_replaying_saved_rows(tmp_path,failure):
    from transcomic.storage import Store
    store=Store(tmp_path/'state.db');doc=store.import_document(tmp_path/'source.txt',decode_txt(b'Source one\nSource two\nSource three'),'vi','en')[0]
    cfg=settings(store);cfg.update(completion_backoff_base=.001,completion_backoff_max=.001)
    job=store.create_job(doc,MODEL,'vi','en',2,provider='deepseek',config=cfg)
    calls=[];seen=Counter()
    def handler(req):
        lines=request_lines(req);calls.append([r['id'] for r in lines]);seen.update(calls[-1])
        if len(calls)<=9:
            if failure=='timeout':raise httpx.ReadTimeout('Synthetic timeout')
            if failure=='json':return httpx.Response(200,json={'choices':[{'message':{'content':'bad JSON'},'finish_reason':'stop'}]})
            if failure=='partial':return response(req,[{'id':lines[0]['id'],'text':'The accepted story continues'}])
            return httpx.Response(failure,headers={'Retry-After':'.001'})
        return response(req)
    scheduler=Scheduler(store,DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler)))
    scheduler.start_many([job])
    try:
        scheduler.join(12);assert not scheduler._thread.is_alive()
        assert all(r['state']=='done' for r in store.lines(doc)),(store.job(job),list(store.log.snapshot())[-2:])
        assert store.job(job)['state']=='finished' and len(store.jobs())==1
        if failure!='partial':assert len(calls)>=10
        assert store.db.execute('SELECT COUNT(*) FROM api_text_versions WHERE accepted=1').fetchone()[0]==3
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('status',[401,402])
def test_deepseek_permanent_key_or_balance_failure_does_not_loop(tmp_path,status):
    from transcomic.storage import Store
    store=Store(tmp_path/'state.db');doc=store.import_document(tmp_path/'source.txt',decode_txt(b'Synthetic source'),'vi','en')[0]
    job=store.create_job(doc,MODEL,'vi','en',1,provider='deepseek',config=settings(store));calls=[]
    scheduler=Scheduler(store,DeepSeekProvider('synthetic',transport=httpx.MockTransport(lambda req:calls.append(1) or httpx.Response(status))))
    scheduler.start_many([job]);scheduler.join(4)
    try:
        assert not scheduler._thread.is_alive() and len(calls)==1 and store.job(job)['state']!='finished'
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('provider',['kira','deepseek'])
def test_new_start_recovers_failed_and_unsent_rows_without_touching_accepted(tmp_path,provider):
    from transcomic.storage import Store
    from transcomic.kira_pool import KiraPoolProvider
    store=Store(tmp_path/'state.db');store.add_kira_keys('synthetic')
    doc=store.import_document(tmp_path/'source.txt',decode_txt(b'One\nTwo\nThree\nFour\nFive\nSix\nSeven'),'vi','en')[0]
    cfg={'translation_completion_policy':0,'kira_multi_key':True,'kira_recovery_version':4,'kira_retry_limit':0} if provider=='kira' else {'translation_completion_policy':0}
    model='mock' if provider=='kira' else MODEL
    run,jobs=store.create_run([doc],['en'],provider=provider,model=model,source_lang='vi',concurrency=1,config=cfg)
    calls=[]
    def first(req):calls.append(1);return httpx.Response(503) if len(calls)==2 else response(req)
    def make(handler):return KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000) if provider=='kira' else DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler))
    scheduler=Scheduler(store,make(first));scheduler.start_many(jobs,run);scheduler.join(10)
    try:
        assert not scheduler._thread.is_alive()
        saved={r['id']:dict(r) for r in store.lines(doc) if r['state']=='done'}
        assert saved and any(r['state']!='done' for r in store.lines(doc))
        retry_calls=[];run,jobs=store.create_run([doc],['en'],provider=provider,model=model,source_lang='vi',concurrency=2,config=authorize(provider))
        scheduler=Scheduler(store,make(lambda req:retry_calls.extend(r['id'] for r in request_lines(req)) or response(req)))
        scheduler.start_many(jobs,run);scheduler.join(10)
        assert not scheduler._thread.is_alive() and store.run(run)['state']=='finished'
        assert all(r['state']=='done' for r in store.lines(doc)) and not set(saved)&set(retry_calls)
        assert all(store.line(rid)==old for rid,old in saved.items())
    finally:cleanup(store,scheduler)


def test_stop_during_preparation_rolls_back_new_jobs_and_sends_no_http(gui,tmp_path,monkeypatch):
    app,w,p,wid=gui;path=tmp_path/'file.txt';path.write_text('Synthetic source',encoding='utf8')
    w.import_paths([str(path)]);wait(app,lambda:not w.import_busy);w.pages.setCurrentIndex(0)
    w.source_lang.setCurrentText('Tiếng Việt');w.target_lang.setCurrentText('Tiếng Anh');w.sync_target_chips()
    w.provider_selector.setCurrentIndex(w.provider_selector.findData('deepseek'))
    import transcomic.deepseek as deepseek
    monkeypatch.setattr(deepseek,'read_key',lambda store:'synthetic')
    entered=threading.Event();release=threading.Event();original=w.store.create_run
    def hold(*a,**kw):entered.set();assert release.wait(4);return original(*a,**kw)
    monkeypatch.setattr(w.store,'create_run',hold)
    monkeypatch.setattr(w,'make_provider',lambda *a:DeepSeekProvider('synthetic',transport=httpx.MockTransport(lambda req:pytest.fail('Cancelled preparation sent HTTP'))))
    w.start_stage2()
    try:
        assert entered.wait(2);w.stop_translation();release.set()
        wait(app,lambda:not w.translation_preparing)
        assert not w.store.jobs() and w.scheduler is None
    finally:release.set()


def test_automation_view_opens_first_document_and_keeps_initial_dirty_updates(gui,tmp_path,monkeypatch):
    app,w,p,wid=gui;gid,_,_=add_group(p.repo,wid,tmp_path/'g',count=3);doc=p.repo.group(gid)['document_id']
    p.refresh();assert w.doc_id is None
    requested=[];original=w.translation_updates.request
    def track(*a,**kw):requested.append(kw.get('full'));return original(*a,**kw)
    monkeypatch.setattr(w.translation_updates,'request',track)
    p.mark_group_dirty(gid);w.pages.setCurrentIndex(0);p.sync_views()
    assert w.doc_id==doc and any(requested)
    assert w.translation_updates.wait_for_idle() and len(w.model.rows)==3


def test_deepseek_retry_after_and_waiting_status_are_durable(tmp_path):
    from transcomic.storage import Store
    from transcomic.ui.translation_updates import SnapshotReader
    store=Store(tmp_path/'state.db');doc=store.import_document(tmp_path/'s.txt',decode_txt(b'Synthetic source'),'vi','en')[0]
    job=store.create_job(doc,MODEL,'vi','en',1,provider='deepseek');times=[]
    def handler(req):times.append(time.monotonic());return httpx.Response(429,headers={'Retry-After':'.35'}) if len(times)==1 else response(req)
    scheduler=Scheduler(store,DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler)));scheduler.start(job)
    try:
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and not (store.batches(job)[0].get('diagnostics') or {}).get('auto_retry_scheduled'):time.sleep(.005)
        reader=SnapshotReader(store.path)
        try:payload=reader.read([doc],[],True,doc)
        finally:reader.close()
        assert payload['statuses'][doc]['state']!='Cần đối chiếu kết quả' and not payload['statuses'][doc]['complete']
        scheduler.join(5);assert not scheduler._thread.is_alive() and len(times)==2 and times[1]-times[0]>=.34
    finally:cleanup(store,scheduler)


def test_deepseek_pause_stop_resume_keeps_successful_attempts(tmp_path):
    from transcomic.storage import Store
    store=Store(tmp_path/'state.db');doc=store.import_document(tmp_path/'s.txt',decode_txt('\n'.join(f'Synthetic source {n}' for n in range(60)).encode()),'vi','en')[0]
    job=store.create_job(doc,MODEL,'vi','en',3,provider='deepseek');entered=threading.Event();gate=threading.Event();seen=Counter()
    async def handler(req):
        seen.update(r['id'] for r in request_lines(req))
        if sum(seen.values())>=9:entered.set()
        while not gate.is_set():await asyncio.sleep(.003)
        return response(req)
    provider=DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler));scheduler=Scheduler(store,provider);scheduler.start(job)
    try:
        assert entered.wait(3);scheduler.pause();gate.set();time.sleep(.1)
        assert sum(seen.values())==9
        scheduler.stop();scheduler.join(5);assert not scheduler._thread.is_alive()
        saved={r['id']:dict(r) for r in store.lines(doc) if r['state']=='done'};assert len(saved)==9
        scheduler=Scheduler(store,provider);scheduler.start(job);scheduler.join(10)
        assert not scheduler._thread.is_alive() and all(r['state']=='done' for r in store.lines(doc))
        assert max(seen.values())==1 and all(store.line(rid)==old for rid,old in saved.items())
    finally:gate.set();cleanup(store,scheduler)


def test_deepseek_restart_preserves_persisted_retry_after_deadline(tmp_path):
    from transcomic.storage import Store
    store=Store(tmp_path/'state.db');doc=store.import_document(tmp_path/'s.txt',decode_txt(b'Synthetic source'),'vi','en')[0]
    job=store.create_job(doc,MODEL,'vi','en',1,provider='deepseek');times=[]
    def handler(req):times.append(time.time());return httpx.Response(429,headers={'Retry-After':'.7'}) if len(times)==1 else response(req)
    provider=DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler));scheduler=Scheduler(store,provider);scheduler.start(job)
    try:
        until=time.monotonic()+3
        while time.monotonic()<until and not (store.batches(job)[0].get('diagnostics') or {}).get('auto_retry_scheduled'):time.sleep(.003)
        due=store.batches(job)[0]['diagnostics']['retry_not_before']
        scheduler.stop();scheduler.join(3);assert len(times)==1
        scheduler=Scheduler(store,provider);scheduler.start(job);scheduler.join(5)
        assert not scheduler._thread.is_alive() and len(times)==2 and times[1]>=due-.015
        assert store.job(job)['state']=='finished'
    finally:cleanup(store,scheduler)


def test_deepseek_restart_retries_retired_unknown_attempt_without_replacing_history(tmp_path):
    from transcomic.storage import Store
    store=Store(tmp_path/'state.db');doc=store.import_document(tmp_path/'s.txt',decode_txt(b'Synthetic source'),'vi','en')[0]
    job=store.create_job(doc,MODEL,'vi','en',1,provider='deepseek');batch=store.batches(job)[0]
    store.job_state(job,'running');store.claim_batch(batch['id']);attempt=store.prepare_attempt(batch['id'],1)
    retired=Scheduler(store,DeepSeekProvider('synthetic'));retired.job_ids=[job];retired.job_id=job;retired.fence_shutdown()
    calls=[];scheduler=Scheduler(store,DeepSeekProvider('synthetic',transport=httpx.MockTransport(lambda req:calls.append(1) or response(req))));scheduler.start(job);scheduler.join(6)
    try:
        history=store.attempts(batch['id'])
        assert not scheduler._thread.is_alive() and len(calls)==1 and store.job(job)['state']=='finished'
        assert len(history)==2 and history[0]['id']==attempt and history[0]['diagnostics']['failure_kind']=='restart_unknown'
        assert history[1]['attempt_number']==2 and all(r['state']=='done' for r in store.lines(doc))
    finally:cleanup(store,scheduler)


def test_pairing_reads_each_image_once_and_reuses_unchanged_runtime_checks(gui,tmp_path,monkeypatch):
    import shutil
    import transcomic.automation.validation as validation
    app,w,p,wid=gui;gid,source,folder=add_group(p.repo,wid,tmp_path/'g',count=30)
    p.refresh();p.validate_clicked();wait(app,lambda:p.proof is not None)
    assert p.proof['passed'];other=tmp_path/'new-images';shutil.copytree(folder,other)
    scans=[];probes=[];sections=[];scan=validation.image_manifest;probe=validation.probe;preflight=p.services.preflight_section
    def tracked(*a,**kw):scans.append(str(a[0]));return scan(*a,**kw)
    def image(*a,**kw):probes.append(str(a[0]));return probe(*a,**kw)
    def config(*a,**kw):sections.append(a[0]);return preflight(*a,**kw)
    monkeypatch.setattr(validation,'image_manifest',tracked);monkeypatch.setattr(validation,'probe',image);monkeypatch.setattr(p.services,'preflight_section',config)
    p.pair_folder(gid,other);wait(app,lambda:not p.pair_pending and p.proof is not None and not p.validation_busy,15)
    assert p.proof['passed'] and len(scans)==1 and len(probes)==30 and not sections
    assert p.repo.group(gid)['data']['image_folder']==str(other.resolve())
    assert p.controller.validate(wid,reuse_inputs=False)['passed']
    assert len(scans)==2 and len(probes)==60 # Dispatch still performs fresh validation.
    (other/'0001.png').write_bytes(b'broken image')
    p.controller.start(wid);wait(app,lambda:not p.controller.busy,10)
    assert p.repo.workset(wid)['state']=='needs_attention' and not w.store.jobs() and not FakeEngine.calls


def test_many_folder_drops_bound_image_decoding_and_finish_every_mapping(gui,tmp_path,monkeypatch):
    import transcomic.automation.validation as validation
    app,w,p,wid=gui;groups=[add_group(p.repo,wid,tmp_path/str(n),str(n),3) for n in range(3)]
    p.refresh();p.validate_clicked();wait(app,lambda:p.proof is not None)
    gate=threading.Event();lock=threading.Lock();active=0;peak=0;original=validation.image_manifest
    def held(*a,**kw):
        nonlocal active,peak
        with lock:active+=1;peak=max(peak,active)
        try:assert gate.wait(5);return original(*a,**kw)
        finally:
            with lock:active-=1
    monkeypatch.setattr(validation,'image_manifest',held)
    for gid,source,folder in groups:p.pair_folder(gid,folder)
    try:
        wait(app,lambda:peak==2);QTest.qWait(40);assert peak==2 and len(p.pair_pending)==3
    finally:gate.set()
    wait(app,lambda:not p.pair_pending and p.proof is not None and not p.validation_busy,12)
    assert p.proof['passed'] and peak==2 and all(p.repo.group(g)['data']['image_folder']==str(f.resolve()) for g,s,f in groups)


def test_slow_next_file_validation_does_not_block_first_http_or_response(setup,tmp_path,monkeypatch):
    import transcomic.automation.validation as validation
    from transcomic.automation.adapters import Translation
    from transcomic.kira_pool import KiraPoolProvider
    repo,wid,services,c=setup;cfg=repo.workset(wid)['config'];cfg.update(translation_completion_policy=1,kira_completion_policy=1,kira_dispatch_policy=1);repo.configure(wid,cfg)
    groups=[add_group(repo,wid,tmp_path/str(n),f'{n:02}',3) for n in range(12)]
    first=repo.group(groups[0][0])['document_id'];assert c.validate(wid)['passed']
    entered=threading.Event();gate=threading.Event();saved=threading.Event();original=validation.read_source;emit=repo.store.log.emit
    def held(path):
        if Path(path)==groups[1][1]:entered.set();assert gate.wait(5)
        return original(path)
    def observed(event,**kw):
        if event=='saved' and kw.get('document_id')==first:saved.set()
        return emit(event,**kw)
    async def handler(req):await asyncio.sleep(.05);return response(req)
    monkeypatch.setattr(validation,'read_source',held);monkeypatch.setattr(repo.store.log,'emit',observed)
    services.translation=Translation(repo,lambda store,job:KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000),network_probe=lambda _:True)
    c.start(wid)
    try:
        assert entered.wait(5)
        assert saved.wait(1),'Disk validation blocked HTTP completion on the async event loop'
        assert all(r['state']=='done' for r in repo.store.lines(first))
        gate.set();c.join(25);assert not c.busy and repo.workset(wid)['state']=='completed'
        assert len(repo.store.jobs())==12 and len(FakeEngine.calls)==36
    finally:gate.set();c.stop();c.join(8)


def test_kira_new_command_authorizes_unknown_and_does_not_inherit_artificial_caps(tmp_path,monkeypatch):
    from transcomic.kira_pool import KiraPoolProvider
    store,docs,run,jobs=fixture(tmp_path,**authorize('kira'))
    clock=[0];real=time.time;monkeypatch.setattr(time,'time',lambda:real()+clock[0]);calls=[]
    def handler(req):calls.append(1);return httpx.Response(504) if len(calls)<26 else response(req)
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    old=pool.release
    def release(*a,**kw):value=old(*a,**kw);clock[0]+=5;return value
    pool.release=release;scheduler=Scheduler(store,pool);scheduler.start_many(jobs,run)
    try:
        scheduler.join(12);assert not scheduler._thread.is_alive() and store.run(run)['state']=='finished'
        cfg=json.loads(store.job(jobs[0])['config'])
        assert len(calls)==26 and cfg['uncertain_retry_authorized'] is True
        assert cfg['max_requests'] is None and cfg['kira_effective_token_limit'] is None and cfg['kira_additional_cost_limit'] is None
    finally:cleanup(store,scheduler)


@pytest.mark.parametrize('dark',[False,True])
@pytest.mark.parametrize('provider',['kira','deepseek'])
def test_automation_start_without_document_click_updates_all_three_tabs(gui,tmp_path,monkeypatch,dark,provider):
    from PySide6.QtWidgets import QMessageBox
    from transcomic.automation.adapters import Translation
    from transcomic.kira_pool import KiraPoolProvider
    app,w,p,wid=gui
    if w.dark!=dark:w.toggle_theme()
    cfg=p.repo.workset(wid)['config'];cfg.update(provider=provider,model=MODEL if provider=='deepseek' else 'mock',translation_completion_policy=1,kira_completion_policy=1,kira_dispatch_policy=1);p.repo.configure(wid,cfg)
    groups=[add_group(p.repo,wid,tmp_path/str(n),f'{n:02}',3) for n in range(12)]
    entered=threading.Event();release=threading.Event();calls=[]
    async def handler(req):
        calls.append(1);entered.set()
        while not release.is_set():await asyncio.sleep(.004)
        return response(req)
    def make(store,job):
        return DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler)) if provider=='deepseek' else KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    p.services.translation=Translation(p.repo,make,network_probe=lambda _:True)
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    p.refresh();p.validate_clicked();wait(app,lambda:p.proof is not None)
    assert p.proof['passed'] and w.doc_id is None
    QTest.mouseClick(p.start,Qt.LeftButton)
    try:
        wait(app,entered.is_set,8) # First HTTP precedes entering Text or selecting a file.
        w.pages.setCurrentIndex(0);p.sync_views();wait(app,lambda:w.doc_id is not None)
        assert w.doc_id==p.repo.group(groups[0][0])['document_id']
        assert w.translation_updates.handles_scheduler()
        release.set();wait(app,lambda:not p.controller.busy,35)
        p.flush();assert p.snapshots.wait_for_idle()
        assert p.repo.workset(wid)['state']=='completed' and len(calls)==12
        assert len(FakeEngine.calls)==36
        w.translation_updates.request(full=True);assert w.translation_updates.wait_for_idle()
        assert all(s['complete'] for s in w.translation_updates.last['statuses'].values())
        w.pages.setCurrentIndex(7);app.processEvents()
        runs={r['id'] for r in w.tts_page.store.history_runs()}
        assert all(p.repo.group(gid)['data']['tts_run'] in runs for gid,_,_ in groups)
        w.pages.setCurrentIndex(8);app.processEvents()
        assert all(Path(p.repo.group(gid)['data']['project']).is_dir() for gid,_,_ in groups)
    finally:release.set();p.controller.stop()


@pytest.mark.parametrize('provider',['kira','deepseek'])
@pytest.mark.parametrize('historical',[False,True])
def test_automation_http_starts_without_opening_or_selecting_any_document(setup,tmp_path,provider,historical):
    from transcomic.automation.adapters import Translation
    from transcomic.kira_pool import KiraPoolProvider
    repo,wid,services,c=setup;cfg=repo.workset(wid)['config'];cfg.update(provider=provider,model=MODEL if provider=='deepseek' else 'mock',translation_completion_policy=1,kira_completion_policy=1,kira_dispatch_policy=1);repo.configure(wid,cfg)
    if historical:
        cfg.pop('translation_completion_policy')
        repo.execute('UPDATE automation_worksets SET config=? WHERE id=?',(json.dumps(cfg),wid))
    for n in range(3):add_group(repo,wid,tmp_path/str(n),str(n),3)
    http=threading.Event();counts=Counter()
    def handler(req):
        key=request_lines(req)[0]['id'];counts[key]+=1;http.set()
        return __import__('test_kira_auto_recovery',fromlist=['response']).response(req) if counts[key]>1 else __import__('httpx').Response(503,headers={'Retry-After':'.001'})
    def make(store,job):
        return DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler)) if provider=='deepseek' else KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    services.translation=Translation(repo,make,network_probe=lambda _:True)
    assert c.validate(wid)['passed'];c.start(wid)
    try:
        assert http.wait(5) # No Qt event loop or text document selection exists here.
        c.join(20);assert not c.busy and repo.workset(wid)['state']=='completed',repo.events(wid)[-4:]
        assert len(repo.store.jobs())==3 and len(FakeEngine.calls)==9
        assert all(json.loads(j['config'])['translation_completion_policy']==1 for j in repo.store.jobs())
    finally:c.stop();c.join(6)


@pytest.mark.parametrize('dark',[False,True])
def test_deepseek_preparation_and_live_updates_leave_qt_responsive(gui,tmp_path,monkeypatch,dark):
    app,w,p,wid=gui;docs=[]
    if w.dark!=dark:w.toggle_theme()
    for n in range(40):
        path=tmp_path/f'Chapter{n:02}.txt';doc=w.store.import_document(path,decode_txt(('\n'.join('Synthetic source '+str(i) for i in range(60))).encode()),'vi','en')[0];docs.append(doc)
    w.workspace_ids=docs;w.open_document(docs[0]);w.pages.setCurrentIndex(0)
    w.source_lang.setCurrentText('Tiếng Việt');w.target_lang.setCurrentText('Tiếng Anh');w.sync_target_chips()
    w.provider_selector.setCurrentIndex(w.provider_selector.findData('deepseek'))
    w.concurrency.setValue(30)
    monkeypatch.setattr(w,'selected_model_id',lambda:MODEL)
    import transcomic.deepseek as deepseek
    monkeypatch.setattr(deepseek,'read_key',lambda store:'synthetic')
    gate=threading.Event();entered=threading.Event();original=w.store.create_run;requests=[]
    def create(*a,**kw):entered.set();assert gate.wait(5);return original(*a,**kw)
    monkeypatch.setattr(w.store,'create_run',create)
    inflight=[0,0]
    async def handler(req):
        requests.append(1);inflight[0]+=1;inflight[1]=max(inflight[1],inflight[0])
        try:await asyncio.sleep(.006);return response(req)
        finally:inflight[0]-=1
    monkeypatch.setattr(w,'make_provider',lambda job,key:DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler)))
    # A direct DeepSeek run must never enter the synchronous warning/refresh path.
    original_refresh=w._refresh
    def legacy(*a,**kw):
        if w.scheduler and w.scheduler._thread and w.scheduler._thread.is_alive():pytest.fail('DeepSeek entered synchronous GUI refresh')
        return original_refresh(*a,**kw)
    monkeypatch.setattr(w,'_refresh',legacy)
    ticks=[];timer=QTimer(w);timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(time.monotonic()));timer.start()
    start=time.monotonic();w.start_stage2();dispatch_ms=(time.monotonic()-start)*1000
    try:
        assert entered.wait(2);wait(app,lambda:len(ticks)>=4,1)
        assert getattr(w,'translation_preparing',False)
        w.start_stage2();gate.set();wait(app,lambda:w.scheduler is not None or not w.translation_preparing,15)
        assert w.scheduler is not None,w.notice.text()
        assert w.scheduler.configured_concurrency==30
        assert w.translation_updates.handles_scheduler()
        wait(app,lambda:not w.scheduler._thread.is_alive(),35)
        w.translation_updates.request(full=True);assert w.translation_updates.wait_for_idle(12)
        assert len(w.store.jobs())==40 and requests and all(s['complete'] for s in w.translation_updates.last['statuses'].values())
        assert dispatch_ms<200 and len(ticks)>10
        target=os.environ.get('TRANSLATION_HANG_EVIDENCE')
        if target:
            out=Path(target);out.mkdir(parents=True,exist_ok=True);w.grab().save(str(out/f'deepseek-40files-{dark}.png'))
            (out/f'deepseek-40files-{dark}.json').write_text(json.dumps(dict(files=40,rows=2400,requests=len(requests),workers=w.scheduler.configured_concurrency,peak_http=inflight[1],start_dispatch_ms=dispatch_ms,ticks=len(ticks),dpr=w.devicePixelRatioF(),platform=app.platformName())),encoding='utf8')
    finally:
        gate.set();timer.stop()
        if w.scheduler:w.scheduler.stop();w.scheduler.join(6)
