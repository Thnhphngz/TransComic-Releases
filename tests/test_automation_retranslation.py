"""Patch 2.0.2: actual mock dispatch through the single Automation owner."""
from collections import Counter
from pathlib import Path
import json
import threading
import time
import httpx
import pytest
from transcomic.providers import KiraProvider
from transcomic.automation.adapters import Translation
from transcomic.automation.repository import file_hash
from test_automation import setup, add_group, run, FakeEngine
from test_automation_ui import gui, wait
from test_kira_auto_recovery import response, request_lines


def until(predicate, timeout=6):
    end=time.monotonic()+timeout
    while not predicate() and time.monotonic()<end:time.sleep(.01)
    assert predicate()


def block_other(services, other, release):
    original=services.kokoro.run
    def kokoro(group,*args,**kwargs):
        if group['id']==other:assert release.wait(15)
        return original(group,*args,**kwargs)
    services.kokoro.run=kokoro


@pytest.mark.parametrize('action',['file','selected','workspace'])
def test_203_rows_200_success_three_errors_real_ui_enqueues_and_dispatches(gui,tmp_path,monkeypatch,action):
    app,w,p,id=gui;repo=p.repo;s=p.services;c=p.controller
    gid,source,_=add_group(repo,id,tmp_path/'story',count=203)
    other,_,_=add_group(repo,id,tmp_path/'other',count=1)
    doc=repo.group(gid)['document_id'];rows=repo.store.lines(doc);failed={r['id'] for r in rows[198:201]}
    for row in rows:
        if row['id'] not in failed:repo.store.edit_line(row['id'],'translation','The translated story continues')
    release=threading.Event();block_other(s,other,release)
    calls=[];allow=threading.Event();normal_done=threading.Event();instances=[];live=[]
    def http(req):
        ids=[r['id'] for r in request_lines(req)];calls.append(ids)
        if set(ids)&failed and not allow.is_set():return httpx.Response(200,json={'choices':[{'message':{'content':'not JSON'}}]})
        return response(req)
    from transcomic.translation import Scheduler
    class Tracked(Scheduler):
        def start_many(self,*args,**kwargs):
            assert not any(s._thread and s._thread.is_alive() for s in instances)
            instances.append(self);live.append(len([s for s in instances if s._thread and s._thread.is_alive()])+1)
            return super().start_many(*args,**kwargs)
    s.translation=Translation(repo,lambda store,job:KiraProvider('synthetic','mock',transport=httpx.MockTransport(http)),scheduler_factory=Tracked,network_probe=lambda _:True)
    s.translation.backoff=lambda _:0
    original=c.normal_translation
    def normal(*args):
        try:return original(*args)
        finally:normal_done.set()
    monkeypatch.setattr(c,'normal_translation',normal)
    try:
        assert c.validate(id)['passed'];c.start(id)
        wait(app,normal_done.is_set)
        assert Counter(i for ids in calls for i in ids if i in failed)==Counter({i:5 for i in failed})
        assert sum(r['state']=='done' for r in repo.store.lines(doc))==200
        w.workspace_ids=[doc];w.open_document(doc);w.model.selected_ids=failed;w.refresh()
        monkeypatch.setattr(w,'make_provider',lambda *a:pytest.fail('Manual scheduler must not start'))
        if action=='file':w.retry_all_errors()
        elif action=='workspace':w.retry_workspace_errors()
        else:w.retry_selected()
        assert '3 dòng lỗi' in w.notice.text()
        assert w.scheduler is None
        assert c.enqueue_retry(failed)==0
        allow.set();release.set()
        wait(app,lambda:not c.busy,seconds=15)
        assert repo.workset(id)['state']=='completed',repo.events(id)[:4]
        assert Counter(i for ids in calls for i in ids if i in failed)==Counter({i:6 for i in failed})
        assert set(i for ids in calls for i in ids)&{r['id'] for r in rows if r['id'] not in failed}==set()
        assert max(live)==1
        assert len(c.retry_requests(id))==1 and c.retry_requests(id)[0]['state']=='done'
        assert len(s.tts_store.items(repo.group(gid)['data']['tts_run']))==203
        assert source.read_text(encoding='utf8').count('\n')==202
        print(f'{action}: 200 preserved; failed IDs 5 automatic + 1 explicit request each; peak scheduler=1; WAV=203; MAU=complete')
    finally:release.set()


@pytest.mark.parametrize('inflight',[False,True])
def test_stop_persists_requested_ids_and_resume_never_repeats_success(setup,tmp_path,monkeypatch,inflight):
    repo,id,s,c=setup;gid,_,_=add_group(repo,id,tmp_path/'g',count=3);other,_,_=add_group(repo,id,tmp_path/'other',count=1)
    doc=repo.group(gid)['document_id'];ids=[r['id'] for r in repo.store.lines(doc)]
    for i in ids:repo.store.edit_line(i,'translation','The translated story continues')
    release=threading.Event();block_other(s,other,release);entered=threading.Event();http_release=threading.Event();calls=[]
    def http(req):
        payload=request_lines(req);calls.append([r['id'] for r in payload])
        if payload[0]['id'] in ids:entered.set();assert http_release.wait(10)
        return response(req)
    s.translation=Translation(repo,lambda store,job:KiraProvider('synthetic','mock',transport=httpx.MockTransport(http)),network_probe=lambda _:True);s.translation.backoff=lambda _:0
    assert c.validate(id)['passed'];c.start(id)
    until(lambda:s.translation.scheduler and s.translation.scheduler._thread and not s.translation.scheduler._thread.is_alive())
    if not inflight:
        # Own stage still references this group's snapshot: the retry must wait.
        original=s.kokoro.run;blocked=threading.Event()
        # The other group already holds the serial lane, so pending request stays
        # queued by temporarily retaining the joined translation future below.
        original_retry=c.run_retry
        def hold(*args):blocked.set();assert http_release.wait(10);return original_retry(*args)
        monkeypatch.setattr(c,'run_retry',hold)
    try:
        assert c.enqueue_retry(ids)==3
        assert c.enqueue_retry(ids)==0
        if inflight:until(entered.is_set)
        else:until(blocked.is_set)
        c.stop()
        with pytest.raises(ValueError,match='dừng'):c.enqueue_retry(ids)
        http_release.set();release.set();c.join(12);assert not c.busy
        assert repo.active() is None and repo.workset(id)['state']=='stopped'
        pending=c.retry_requests(id)[0];assert pending['state']=='pending'
        before=Counter(i for payload in calls for i in payload)
        if not inflight:monkeypatch.setattr(c,'run_retry',original_retry)
        assert c.validate(id)['passed'];c.start(id);c.join(12);assert not c.busy
        assert repo.workset(id)['state']=='completed',repo.events(id)[:4]
        after=Counter(i for payload in calls for i in payload)
        assert all(after[i]==1 for i in ids)
        assert all(after[i]==n for i,n in before.items())
        assert c.retry_requests(id)[0]['state']=='done'
        # Ownership release retains the existing standalone manual path.
        assert repo.store.create_job(doc,'mock','vi','en',1,[ids[0]])
    finally:release.set();http_release.set()


def test_valid_wavs_stop_resume_and_reopen_status_no_resynthesis(setup,tmp_path,monkeypatch):
    repo,id,s,c=setup;gid,_,_=add_group(repo,id,tmp_path/'g',count=3)
    original=s.capcut.run;entered=threading.Event();release=threading.Event()
    def capcut(*args):
        entered.set();assert release.wait(10)
        from transcomic.automation.adapters import Stopped
        if c.stop_event.is_set():raise Stopped()
        return original(*args)
    monkeypatch.setattr(s.capcut,'run',capcut)
    assert c.validate(id)['passed'];c.start(id);until(entered.is_set)
    assert repo.group(gid)['data']['state']=='exporting'
    c.stop();release.set();c.join(10)
    group=repo.group(gid);assert group['data']['state']=='waiting_capcut'
    folder=Path(s.tts_store.docs(group['data']['tts_run'])[0]['folder']);before={p.name:(file_hash(p),p.stat().st_mtime_ns) for p in folder.glob('*.wav')}
    assert len(before)==3
    repo.update_group(gid,state='waiting_tts');c.reconcile_stages(id)
    assert repo.group(gid)['data']['state']=='waiting_capcut'
    calls=len(FakeEngine.calls);monkeypatch.setattr(s.kokoro,'run',lambda *a,**k:pytest.fail('Valid WAV must bypass Kokoro'))
    monkeypatch.setattr(s.capcut,'run',original);run(c,id)
    assert repo.group(gid)['data']['state']=='completed'
    assert len(FakeEngine.calls)==calls
    assert {p.name:(file_hash(p),p.stat().st_mtime_ns) for p in folder.glob('*.wav')}==before
    # Reconciliation checks project content, not a progress percentage or path alone.
    (Path(repo.group(gid)['data']['project'])/'synthetic-external-change.txt').write_text('external')
    c.reconcile_stages(id);assert repo.group(gid)['data']['state']=='waiting_capcut'
    wav=next(folder.glob('*.wav'));wav.write_bytes(b'synthetic-corrupt')
    c.reconcile_stages(id);assert repo.group(gid)['data']['state']=='waiting_tts'


def test_retry_existing_wav_invalidates_exact_slot_and_versions_project(setup,tmp_path):
    repo,id,s,c=setup;gid,_,_=add_group(repo,id,tmp_path/'g',count=3);run(c,id)
    group=repo.group(gid);doc=group['document_id'];rows=repo.store.lines(doc);old_project=Path(group['data']['project'])
    folder=Path(s.tts_store.docs(group['data']['tts_run'])[0]['folder']);old={p.name:file_hash(p) for p in folder.glob('*.wav')};old_project_hash=file_hash(old_project/'draft_content.json')
    other,_,_=add_group(repo,id,tmp_path/'other',count=1);release=threading.Event();block_other(s,other,release)
    calls=[]
    def http(req):
        payload=request_lines(req);calls.extend(r['id'] for r in payload)
        return response(req,[dict(id=r['id'],text='The hero returns to the village today') for r in payload])
    s.translation.provider_factory=lambda store,job:KiraProvider('synthetic','mock',transport=httpx.MockTransport(http))
    try:
        assert c.validate(id)['passed'];c.start(id)
        until(lambda:s.translation.scheduler and s.translation.scheduler._thread and not s.translation.scheduler._thread.is_alive())
        assert c.enqueue_retry([rows[1]['id']])==1
        release.set();c.join(12);assert not c.busy
        assert repo.workset(id)['state']=='completed',repo.events(id)[:5]
        assert calls.count(rows[1]['id'])==1 and rows[0]['id'] not in calls and rows[2]['id'] not in calls
        current=repo.group(gid);newfolder=Path(s.tts_store.docs(current['data']['tts_run'])[0]['folder'])
        assert newfolder!=folder
        assert all(file_hash(folder/name)==digest for name,digest in old.items())
        assert file_hash(newfolder/'0001.wav')==old['0001.wav'] and file_hash(newfolder/'0003.wav')==old['0003.wav']
        assert Path(current['data']['project'])!=old_project
        assert file_hash(old_project/'draft_content.json')==old_project_hash
    finally:release.set()


def test_single_selected_error_line_uses_the_same_automation_owner(gui,tmp_path):
    app,w,p,id=gui;repo=p.repo;s=p.services;c=p.controller
    gid,_,_=add_group(repo,id,tmp_path/'g',count=3);other,_,_=add_group(repo,id,tmp_path/'other',count=1)
    doc=repo.group(gid)['document_id'];rows=repo.store.lines(doc);line=rows[1]['id']
    for row in (rows[0],rows[2]):repo.store.edit_line(row['id'],'translation','The translated story continues')
    release=threading.Event();block_other(s,other,release);allow=threading.Event();done=threading.Event();calls=[]
    def http(req):
        ids=[r['id'] for r in request_lines(req)];calls.extend(ids)
        return response(req,[]) if line in ids and not allow.is_set() else response(req)
    s.translation=Translation(repo,lambda store,job:KiraProvider('synthetic','mock',transport=httpx.MockTransport(http)),network_probe=lambda _:True);s.translation.backoff=lambda _:0
    original=c.normal_translation
    def normal(*args):
        try:return original(*args)
        finally:done.set()
    c.normal_translation=normal
    try:
        assert c.validate(id)['passed'];c.start(id);wait(app,done.is_set)
        w.workspace_ids=[doc];w.open_document(doc);w.model.selected_ids={line};w.refresh()
        w.retry_selected();assert '1 dòng lỗi' in w.notice.text() and w.scheduler is None
        allow.set();release.set();wait(app,lambda:not c.busy)
        assert repo.workset(id)['state']=='completed'
        assert calls.count(line)==6 and not {rows[0]['id'],rows[2]['id']}.intersection(calls)
    finally:release.set()
