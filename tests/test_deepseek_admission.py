"""DeepSeek Automation rolling and legacy gates; synthetic inputs and HTTP only."""
import asyncio
from collections import Counter
import json
import os
import threading
import time

import httpx
import pytest

from test_automation import setup,add_group,FakeEngine
from test_automation_ui import gui
from test_kira_auto_recovery import request_lines,response
from transcomic.automation.adapters import Translation
from transcomic.deepseek import DeepSeekProvider,MODEL


def configure(repo,wid):
    cfg=repo.workset(wid)['config'];cfg.update(provider='deepseek',model=MODEL,workers=30,deepseek_batch_size=5,translation_completion_policy=1)
    repo.configure(wid,cfg);return cfg


def test_nine_completed_unlocks_next_cohort_and_tts_does_not_wait(setup,tmp_path):
    repo,wid,services,c=setup;configure(repo,wid)
    # Simulate a workset created before the versioned policy was introduced.
    repo.execute("UPDATE automation_worksets SET checkpoint='{}' WHERE id=?",(wid,))
    gids=[add_group(repo,wid,tmp_path/str(i),f'{i:03}',3)[0] for i in range(30)]
    docs=[repo.group(g)['document_id'] for g in gids];owners={r['id']:i for i,d in enumerate(docs) for r in repo.store.lines(d)}
    nine=threading.Event();tenth=threading.Event();next_group=threading.Event();voice=threading.Event();FakeEngine.entered=voice;FakeEngine.release=threading.Event();FakeEngine.release.set()
    seen=Counter();started=set();active=Counter();peak=0;events=[];emit=repo.store.log.emit
    def log(event,**kw):
        if event in ('cohort_unlocked','source_completed'):events.append(event)
        return emit(event,**kw)
    repo.store.log.emit=log
    async def handler(req):
        nonlocal peak
        lines=request_lines(req);n=owners[lines[0]['id']];started.add(n);seen.update(r['id'] for r in lines);active[n]+=1;peak=max(peak,len(active))
        try:
            while 1<=n<=8 and not nine.is_set() or n==9 and not tenth.is_set():await asyncio.sleep(.003)
            if n>=10:next_group.set()
            return response(req)
        finally:
            active[n]-=1
            if not active[n]:del active[n]
    services.translation=Translation(repo,lambda st,j:DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler),batch_size=5),network_probe=lambda _:True)
    assert c.validate(wid)['passed'];c.start(wid)
    try:
        assert voice.wait(10),'File one must reach TTS before its cohort completes'
        assert not next_group.is_set() and started<=set(range(10))
        nine.set();assert next_group.wait(10) and not tenth.is_set()
        assert any(r['state']!='done' for r in repo.store.lines(docs[9]))
        tenth.set();c.join(40)
        assert not c.busy and repo.workset(wid)['state']=='completed',[(e['stage'],e['message']) for e in repo.events(wid)[:8]]
        assert peak<=10 and len(seen)==90 and set(seen.values())=={1}
        assert len(repo.store.jobs())==30 and len(FakeEngine.calls)==90
        assert events.count('cohort_unlocked')==2 and events.count('source_completed')==30
        saved=repo.workset(wid)['checkpoint']['deepseek_admissions']['1']
        assert len(saved['complete'])==30
    finally:nine.set();tenth.set();c.stop();c.join(8)


def test_temporary_errors_park_restore_without_duplicate_rows(setup,tmp_path):
    repo,wid,services,c=setup;configure(repo,wid)
    docs=[]
    for i in range(25):
        gid,_,_=add_group(repo,wid,tmp_path/str(i),f'{i:03}',3);docs.append(repo.group(gid)['document_id'])
    owners={r['id']:i for i,d in enumerate(docs) for r in repo.store.lines(d)};seen=Counter();wave=set();events=[];emit=repo.store.log.emit
    def log(event,**kw):
        if event in ('source_parked','source_restored'):events.append(event)
        return emit(event,**kw)
    repo.store.log.emit=log
    async def handler(req):
        lines=request_lines(req);n=owners[lines[0]['id']];seen.update(r['id'] for r in lines)
        if n<10 and seen[lines[0]['id']]==1:
            wave.add(n)
            while len(wave)<10:await asyncio.sleep(.003)
            return httpx.Response(503,headers={'Retry-After':'.7'})
        return response(req)
    services.translation=Translation(repo,lambda st,j:DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler),batch_size=5),network_probe=lambda _:True)
    assert c.validate(wid)['passed'];c.start(wid);c.join(35)
    try:
        assert not c.busy and repo.workset(wid)['state']=='completed',repo.events(wid)[:3]
        assert 'source_parked' in events and 'source_restored' in events
        assert all(seen[r['id']]==(2 if i<10 else 1) for i,d in enumerate(docs) for r in repo.store.lines(d))
        assert len(services.translation.scheduler.admission.complete)==25
    finally:c.stop();c.join(8)


@pytest.mark.parametrize('dark',[False,True])
def test_deepseek_hundred_files_native_pipeline(gui,tmp_path,monkeypatch,dark):
    import test_automation_ui_stability as stability
    app,w,p,wid=gui;cfg=configure(p.repo,wid);cfg['deepseek_batch_size']=3;p.repo.configure(wid,cfg)
    def provider(*args,transport=None,**kw):return DeepSeekProvider('synthetic',transport=transport,batch_size=3)
    monkeypatch.setattr(stability,'KiraPoolProvider',provider)
    active={};peak=0;events=[];original=w.store.log.emit
    def emit(event,**kw):
        nonlocal peak
        attempt=kw.get('attempt_id')
        if event=='http_started':active[attempt]=kw.get('document_id');peak=max(peak,len(set(active.values())))
        elif event in ('body_received','failure'):active.pop(attempt,None)
        if event in ('cohort_unlocked','source_completed'):events.append(event)
        return original(event,**kw)
    monkeypatch.setattr(w.store.log,'emit',emit)
    stability.test_automation_100_docs_2000_units_one_start_tab_switches_and_early_completion(gui,tmp_path,monkeypatch,dark)
    assert peak<=10 and events.count('source_completed')==100 and events.count('cohort_unlocked')==0
    assert p.repo.workset(wid)['checkpoint']['deepseek_admissions']['1']['admission_policy']['mode']=='rolling'
    assert len(p.services.translation.scheduler.admission.complete)==100


@pytest.mark.parametrize('dark',[False,True])
def test_rolling_admission_preserves_automation_selection_and_scroll(gui,tmp_path,monkeypatch,dark):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox
    from test_automation_ui import wait
    app,w,p,wid=gui;configure(p.repo,wid)
    if w.dark!=dark:w.toggle_theme()
    gids=[add_group(p.repo,wid,tmp_path/str(i),f'{i:03}',3)[0] for i in range(20)]
    docs=[p.repo.group(g)['document_id'] for g in gids]
    owners={r['id']:i for i,d in enumerate(docs) for r in w.store.lines(d)}
    started=set();release=threading.Event()
    async def handler(req):
        n=owners[request_lines(req)[0]['id']];started.add(n)
        while n!=2 and not release.is_set():await asyncio.sleep(.005)
        return response(req)
    p.services.translation=Translation(p.repo,lambda st,j:DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler)),network_probe=lambda _:True)
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    p.load_worksets(wid);p.validate_clicked();wait(app,lambda:p.proof is not None,15);assert p.proof['passed']
    p.table.setCurrentIndex(p.model.index(12,1));p.table.scrollTo(p.model.index(12,1));app.processEvents()
    selected=p.selected();scroll=p.table.verticalScrollBar().value();reset=[]
    p.model.modelReset.connect(lambda:reset.append(1))
    QTest.mouseClick(p.start,Qt.LeftButton)
    try:
        wait(app,lambda:10 in started,20);QTest.qWait(500)
        assert p.selected()==selected and p.table.verticalScrollBar().value()==scroll and not reset
        assert started==set(range(11))
        release.set();wait(app,lambda:not p.controller.busy,25)
        assert p.repo.workset(wid)['state']=='completed'
        assert p.selected()==selected and p.table.verticalScrollBar().value()==scroll and not reset
        if target:=os.environ.get('AUTOMATION_UI_EVIDENCE'):
            from pathlib import Path
            Path(target).mkdir(parents=True,exist_ok=True)
            (Path(target)/f'selection-{dark}.json').write_text(json.dumps(dict(status='PASS',platform=app.platformName(),dpr=w.devicePixelRatioF(),dark=dark,
                        selection_preserved=True,scroll_preserved=True,model_resets=0,completed=20)),encoding='utf8')
    finally:release.set();p.controller.stop();p.controller.join(8)


def test_stop_resume_reuses_job_and_attempt_history_and_accepted_rows(setup,tmp_path):
    repo,wid,services,c=setup;configure(repo,wid)
    docs=[]
    for i in range(25):
        gid,_,_=add_group(repo,wid,tmp_path/str(i),f'{i:03}',10);docs.append(repo.group(gid)['document_id'])
    first=repo.store.lines(docs[0])[0]['id'];saved=threading.Event();release=threading.Event();seen=Counter();emit=repo.store.log.emit
    def log(event,**kw):
        if event=='saved' and first in kw.get('accepted_ids',()):saved.set()
        return emit(event,**kw)
    repo.store.log.emit=log
    async def handler(req):
        ids=[r['id'] for r in request_lines(req)];seen.update(ids)
        while first not in ids and not release.is_set():await asyncio.sleep(.003)
        return response(req)
    services.translation=Translation(repo,lambda st,j:DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler),batch_size=5),network_probe=lambda _:True)
    assert c.validate(wid)['passed'];c.start(wid)
    try:
        assert saved.wait(8);c.pause();assert c.paused.is_set();c.stop();release.set();c.join(12);assert not c.busy
        accepted={r['id']:dict(r) for d in docs for r in repo.store.lines(d) if r['state']=='done'}
        jobs={j['id'] for j in repo.store.jobs()};attempts={r[0] for r in repo.store.db.execute('SELECT id FROM request_attempts')}
        assert accepted and c.validate(wid)['passed'];c.start(wid);c.join(40)
        assert not c.busy and repo.workset(wid)['state']=='completed'
        assert len(repo.store.jobs())==25 and jobs<={j['id'] for j in repo.store.jobs()}
        assert attempts<={r[0] for r in repo.store.db.execute('SELECT id FROM request_attempts')}
        assert all(repo.store.line(rid)==row for rid,row in accepted.items()) and max(seen.values())==1
    finally:release.set();c.stop();c.join(8)


def test_first_http_finishes_while_second_file_input_validation_is_blocked(setup,tmp_path,monkeypatch):
    from pathlib import Path
    import transcomic.automation.validation as validation
    repo,wid,services,c=setup;configure(repo,wid)
    groups=[add_group(repo,wid,tmp_path/str(i),f'{i:03}',3) for i in range(12)]
    first=repo.group(groups[0][0])['document_id'];assert c.validate(wid)['passed']
    entered=threading.Event();release=threading.Event();saved=threading.Event();original=validation.read_source;emit=repo.store.log.emit
    def read(path):
        if Path(path)==groups[1][1]:entered.set();assert release.wait(6)
        return original(path)
    def log(event,**kw):
        if event=='saved' and kw.get('document_id')==first:saved.set()
        return emit(event,**kw)
    monkeypatch.setattr(validation,'read_source',read);monkeypatch.setattr(repo.store.log,'emit',log)
    async def handler(req):await asyncio.sleep(.05);return response(req)
    services.translation=Translation(repo,lambda st,j:DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler),batch_size=5),network_probe=lambda _:True)
    c.start(wid)
    try:
        assert entered.wait(5) and saved.wait(1)
        release.set();c.join(25);assert not c.busy and repo.workset(wid)['state']=='completed'
    finally:release.set();c.stop();c.join(8)


@pytest.mark.parametrize('provider,legacy',[('kira',True),('deepseek',True),('deepseek',False)])
def test_restart_recovers_unknown_attempts_in_later_lazy_files(setup,tmp_path,provider,legacy):
    from transcomic.automation.repository import fingerprint
    from transcomic.completion import authorize
    from transcomic.kira_pool import KiraPoolProvider
    repo,wid,services,c=setup;cfg=configure(repo,wid);cfg.update(provider=provider,model=MODEL if provider=='deepseek' else 'mock',kira_completion_policy=1,kira_dispatch_policy=1);repo.configure(wid,cfg)
    if legacy:repo.execute("UPDATE automation_worksets SET checkpoint='{}' WHERE id=?",(wid,))
    groups=[add_group(repo,wid,tmp_path/str(i),f'{i:03}',3)[0] for i in range(12)]
    docs=[repo.group(g)['document_id'] for g in groups];order=[repo.store.document(d)['source_instance'] for d in docs];old=[]
    for index in (0,10):
        gid,doc=groups[index],docs[index]
        rows=repo.store.lines(doc);jobcfg=authorize(provider);jobcfg.update(automation_owner=wid,automation_cycle=1,kira_dispatch_order=order,kira_initial_completed=[],kira_admission_key='1',deepseek_batch_size=5)
        if provider=='deepseek' and not legacy:jobcfg['deepseek_admission_policy']={'version':1,'mode':'rolling'}
        jid=repo.store.create_job(doc,cfg['model'],cfg['source_lang'],cfg['target_lang'],30,provider=provider,config=jobcfg,allow_shared_document=True)
        repo.store.job_state(jid,'running');batch=repo.store.batches(jid)[0];repo.store.claim_batch(batch['id']);attempt=repo.store.prepare_attempt(batch['id'],1)
        repo.store.finish_batch(batch['id'],{},'Synthetic retired process',True,{'failure_kind':'shutdown_cancelled'},expected_attempt_id=attempt)
        repo.execute("UPDATE request_attempts SET state='unknown' WHERE id=?",(attempt,));repo.store.job_state(jid,'interrupted');old.append(attempt)
        signature=fingerprint([(r['id'],r['source_revision']) for r in rows]);repo.update_group(gid,batch_jobs={f'1:completion1:{signature}':[jid]})
    def make(st,j):
        return DeepSeekProvider('synthetic',transport=httpx.MockTransport(response),batch_size=5) if provider=='deepseek' else KiraPoolProvider(st,'mock',transport=httpx.MockTransport(response),rpm=100000,tpm=100000000)
    services.translation=Translation(repo,make,network_probe=lambda _:True)
    assert c.validate(wid)['passed'];c.start(wid);c.join(25)
    try:
        assert not c.busy and repo.workset(wid)['state']=='completed',[(e['stage'],e['message']) for e in repo.events(wid)[:3]]
        assert len(repo.store.jobs())==12 and len(FakeEngine.calls)==36
        for aid in old:
            record=repo.rows('SELECT state,diagnostics FROM request_attempts WHERE id=?',(aid,))[0]
            assert record['state']=='finished' and json.loads(record['diagnostics'])['failure_kind']=='restart_unknown'
    finally:c.stop();c.join(8)


@pytest.mark.parametrize('size',[5,10,15])
@pytest.mark.parametrize('failure',['schema',504])
def test_new_large_batch_recovers_without_reverting_legacy_policy(tmp_path,size,failure):
    from transcomic.storage import Store
    from transcomic.documents import decode_txt
    from transcomic.translation import Scheduler
    store=Store(tmp_path/'state.sqlite3');doc=store.import_document(tmp_path/'source.txt',decode_txt(('\n'.join(['Người lữ khách trở về nhà']*size)).encode()),'vi','en')[0]
    job=store.create_job(doc,MODEL,'vi','en',1,provider='deepseek',config={'deepseek_batch_size':size});calls=[]
    def handler(req):
        calls.append(1)
        if len(calls)==1:
            return httpx.Response(504) if failure==504 else httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"lines":[]}'}}]})
        return response(req)
    scheduler=Scheduler(store,DeepSeekProvider('synthetic',batch_size=size,transport=httpx.MockTransport(handler)));scheduler.start(job)
    try:
        scheduler.join(8);assert not scheduler._thread.is_alive() and len(calls)==2 and store.job(job)['state']=='finished'
        assert all(r['state']=='done' for r in store.lines(doc))
        assert store.db.execute('SELECT COUNT(*) FROM api_text_versions WHERE accepted=1').fetchone()[0]==size
    finally:scheduler.stop();scheduler.join(5);store.close()
