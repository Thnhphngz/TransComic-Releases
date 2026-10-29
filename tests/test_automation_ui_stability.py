"""Isolated Automation/UI integration; HTTP MockTransport and tiny PCM only."""
import asyncio
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import httpx
import pytest
from PySide6.QtCore import Qt,QTimer,QPointF,QMimeData,QUrl
from PySide6.QtGui import QDragEnterEvent,QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMessageBox
from test_automation_ui import gui,wait
from test_automation import add_group,FakeEngine
from test_kira_auto_recovery import request_lines,response
from transcomic.automation.adapters import Translation
from transcomic.automation.validation import ValidationSuperseded
from transcomic.kira_pool import KiraPoolProvider
from transcomic.ui.automation_snapshots import AutomationReader


def evidence(w,name,proof):
    target=os.environ.get('AUTOMATION_UI_EVIDENCE')
    if target:
        out=Path(target);out.mkdir(parents=True,exist_ok=True)
        proof.update(platform=QApplication.platformName(),dpr=w.devicePixelRatioF())
        (out/(name+'.json')).write_text(json.dumps(proof,indent=2),encoding='utf8')
        assert w.grab().save(str(out/(name+'.png')))


def test_detached_automation_reads_noop_events_and_stale_snapshot(gui,tmp_path):
    app,w,p,wid=gui;gid,_,_=add_group(p.repo,wid,tmp_path/'g');p.refresh()
    writes=w.store.db.total_changes;events=[];p.repo.group_listeners.append(events.append)
    for _ in range(100):p.repo.update_group(gid,state='draft',error='')
    assert not events and w.store.db.total_changes==writes
    p.repo.update_group(gid,state='waiting');assert events==[gid]
    p.repo.progress(gid);assert events==[gid,gid]
    result=[]
    def read():
        r=AutomationReader(w.store.path,p.services.tts_store.path)
        try:result.append(r.read(wid))
        finally:r.close()
    with w.store.lock:
        thread=threading.Thread(target=read);thread.start();thread.join(2)
        assert not thread.is_alive()
    assert result[0]['sql']<=8 and result[0]['groups'][0]['translation_total']==3
    p.refresh();last=p.snapshots.last;old={**last,'serial':last['serial']-1,'groups':[]}
    p.snapshots.apply(old);assert p.snapshots.last is last and p.model.rowCount()==1
    assert w.store.db.total_changes==writes+1


def test_automation_scope_replaces_old_direct_scope_and_controls_target_controller(gui,tmp_path,monkeypatch):
    app,w,p,wid=gui;docs=[]
    for i in range(3):
        gid,_,_=add_group(p.repo,wid,tmp_path/str(i),str(i),1);docs.append(p.repo.group(gid)['document_id'])
    row=w.store.lines(docs[0])[0];w.store.edit_line(row['id'],'translation','The story continues')
    w.current_job_ids={row['id']};w.workspace_ids=docs;w.open_document(docs[0]);w.pages.setCurrentIndex(0)
    p.controller.current=wid;p.controller.thread=SimpleNamespace(is_alive=lambda:True);p.repo.activate(wid)
    try:
        p.snapshots.read_now();assert w.translation_updates.wait_for_idle()
        assert w.translation_updates.context()['kind']=='automation' and w.total_progress.value()==33
        for _ in range(5):
            p.refresh();w.refresh();w.refresh_stage2()
            assert p.snapshots.wait_for_idle() and w.translation_updates.wait_for_idle()
            assert w.total_progress.value()==33 and w.file_progress.value()==100
        # An obsolete scope cannot paint an arbitrary percent or status.
        last=w.translation_updates.last;old={**last,'generation':last['generation']+100,'scope':{**last['scope'],'key':('direct','obsolete')}}
        w.translation_updates.apply(old)
        assert w.translation_updates.last is last and w.total_progress.value()==33
        w.pause_or_resume();assert p.controller.paused.is_set()
        w.pause_or_resume();assert not p.controller.paused.is_set()
        # Browsing another workset must keep deltas/controls on the active one.
        other=p.repo.create('Other workset',p.repo.workset(wid)['config'])
        add_group(p.repo,other,tmp_path/'other','Other',1);p.load_worksets(other);p.snapshots.read_now()
        sent=[];original=w.translation_updates.request
        def track(changed=(),**kwargs):sent.extend(changed);return original(changed,**kwargs)
        monkeypatch.setattr(w.translation_updates,'request',track)
        p.mark_group_dirty(p.repo.groups(wid)[0]['id']);p.sync_views()
        assert row['id'] in sent and w.translation_updates.context()['docs']==tuple(docs)
        w.stop_translation();assert p.controller.stop_event.is_set()
        assert not w.store.jobs()
    finally:p.controller.thread=None;p.repo.state(wid,'stopped')


@pytest.mark.parametrize('dark',[False,True])
def test_contextual_name_warning_has_stable_drop_geometry_and_remains_required(gui,tmp_path,dark):
    app,w,p,wid=gui
    if w.dark!=dark:w.toggle_theme()
    gid,_,_=add_group(p.repo,wid,tmp_path/'g');p.refresh()
    p.fields['project_name'].setText('');p.config_changed();app.processEvents()
    assert not p.project_warning.text() and not p.notice.text()
    p.validate_clicked();wait(app,lambda:p.proof is not None)
    assert not p.proof['passed'] and not p.start.isEnabled() and p.project_warning.text()
    app.processEvents();rect=p.table_shell.geometry();drop=p.table.viewport().geometry();geometries=[]
    for name in ('Ready','','Ready again',''):
        p.fields['project_name'].setText(name);p.config_changed();app.processEvents()
        geometries.append(p.table_shell.geometry().getRect())
        assert p.table_shell.geometry()==rect and p.table.viewport().geometry()==drop
        assert bool(p.project_warning.text())==(not bool(name))
    evidence(w,f'name-warning-empty-{dark}',dict(status='PASS',table_rectangles=geometries,name_still_required=True))
    p.show_validation_details();app.processEvents();assert p.validation_dialog.isVisible()
    QTest.keyClick(p.validation_dialog,Qt.Key_Escape);assert not p.validation_dialog.isVisible()
    for width,height in ((950,650),(1440,940)):
        w.resize(width,height);app.processEvents()
        buttons=[p.add,p.validate_button,p.start,p.stop]
        assert all(b.isVisible() and b.rect().width()>0 for b in buttons)
        assert all(not a.geometry().intersects(b.geometry()) for a,b in zip(buttons,buttons[1:]))
    p.fields['project_name'].setText('Final');p.config_changed();wait(app,lambda:p.proof is not None)
    assert p.proof['passed'] and p.start.isEnabled() and not p.project_warning.text()
    evidence(w,f'name-warning-{dark}',dict(status='PASS',table_rectangles=geometries,name_still_required=True))


def test_100_file_batched_drop_cancels_obsolete_validation_without_overlap_or_reset(gui,tmp_path,monkeypatch):
    import transcomic.automation.validation as validation
    app,w,p,wid=gui
    for i in range(20):add_group(p.repo,wid,tmp_path/f'old{i}',f'Chapter {i:03}',count=1)
    p.refresh();p.validate_clicked();wait(app,lambda:p.proof is not None)
    p.table.setCurrentIndex(p.model.index(12,1));p.table.scrollTo(p.model.index(12,1));app.processEvents()
    selected=p.selected();scroll=p.table.verticalScrollBar().value();reset=[];p.model.modelReset.connect(lambda:reset.append(1))
    entered=threading.Event();gate=threading.Event();original=validation.input_stamp;live=0;peak=0;cancelled=0;main=threading.get_ident();threads=[]
    def slow(*args):
        threads.append(threading.get_ident())
        if not entered.is_set():entered.set();assert gate.wait(8)
        return original(*args)
    monkeypatch.setattr(validation,'input_stamp',slow)
    original_validate=p.controller.validate
    def counted(*args,**kwargs):
        nonlocal live,peak,cancelled
        live+=1;peak=max(peak,live)
        try:return original_validate(*args,**kwargs)
        except ValidationSuperseded:cancelled+=1;raise
        finally:live-=1
    monkeypatch.setattr(p.controller,'validate',counted)
    p.validate_clicked();wait(app,entered.is_set)
    files=[]
    for i in range(20,100):
        path=tmp_path/f'Chapter {i:03}.txt';path.write_text('Văn bản tổng hợp',encoding='utf8');files.append(path)
    rect=p.table_shell.geometry();point=p.table.viewport().rect().center()
    try:
        for offset in range(0,80,20):
            mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(x)) for x in files[offset:offset+20]])
            enter=QDragEnterEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(p.table.viewport(),enter)
            drop=QDropEvent(QPointF(point),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(p.table.viewport(),drop)
            assert enter.isAccepted() and drop.isAccepted();app.processEvents()
            assert p.table_shell.geometry()==rect
    finally:gate.set()
    wait(app,lambda:not p.import_busy and not p.import_queue and p.proof is not None and len(p.proof['groups'])==100,30)
    assert peak==1 and cancelled>=1 and all(t!=main for t in threads)
    assert p.selected()==selected and p.table.verticalScrollBar().value()==scroll and not reset
    assert len(p.repo.groups(wid))==100 and len({g['document_id'] for g in p.repo.groups(wid)})==100
    assert len(p.proof['groups'])==100 and not p.proof['passed'] # New files still require matching image folders.
    evidence(w,'batched-import',dict(status='PASS',files=100,validation_peak=peak,obsolete_cancelled=cancelled,model_resets=len(reset),selection_preserved=True,scroll_preserved=True))


@pytest.mark.parametrize('dark',[False,True])
def test_automation_100_docs_2000_units_one_start_tab_switches_and_early_completion(gui,tmp_path,monkeypatch,dark):
    app,w,p,wid=gui
    if w.dark!=dark:w.toggle_theme()
    cfg=p.repo.workset(wid)['config'];cfg.update(capcut_mode='split',part_count=4,project_name='Synthetic',workers=30)
    p.repo.configure(wid,cfg);paths=[]
    for i in range(100):
        gid,path,_=add_group(p.repo,wid,tmp_path/f'g{i}',f'Chapter {i:03}',20);paths.append(path)
    hashes={path:hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    groups=p.repo.groups(wid);docs=[g['document_id'] for g in groups];rows={d:w.store.lines(d) for d in docs};owners={r['id']:d for d,rs in rows.items() for r in rs};early=set(docs[:40])
    active=set();peak=0;seen=Counter();calls=[];gate=threading.Event();faults={rows[docs[40]][0]['id']:429,rows[docs[41]][0]['id']:503}
    async def handler(req):
        nonlocal peak
        batch=request_lines(req);ids={r['id'] for r in batch};doc=owners[batch[0]['id']]
        assert 1<=len(batch)<=3 and not active&ids;active.update(ids);peak=max(peak,len(active));calls.append(tuple(ids))
        try:
            while doc not in early and not gate.is_set():await asyncio.sleep(.004)
            await asyncio.sleep(.002)
            for rid in ids:seen[rid]+=1
            bad=next((rid for rid in ids if rid in faults and seen[rid]==1),None)
            if bad:return httpx.Response(faults[bad],headers={'Retry-After':'.05'})
            return response(req)
        finally:active.difference_update(ids)
    p.services.translation=Translation(p.repo,lambda store,job:KiraPoolProvider(store,job['model'],transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000),network_probe=lambda _:True)
    p.load_worksets(wid);validation_started=time.perf_counter();p.validate_clicked();validation_dispatch_ms=(time.perf_counter()-validation_started)*1000
    wait(app,lambda:p.proof is not None,25);validation_ms=(time.perf_counter()-validation_started)*1000;assert p.proof['passed']
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox,'information',lambda *a:pytest.fail('Unexpected information dialog'))
    ticks=[];timer=QTimer(w);timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(time.perf_counter()));timer.start()
    QTest.mouseClick(p.start,Qt.LeftButton);wait(app,lambda:p.controller.busy)
    try:
        w.open_document(docs[0]);w.pages.setCurrentIndex(0)
        wait(app,lambda:w.translation_updates.last and sum(s['complete'] for s in w.translation_updates.last['statuses'].values())==40,40)
        early_ids={r['id'] for d in early for r in rows[d]};accepted_early={r['id']:dict(r) for d in early for r in w.store.lines(d)}
        values=[];w.total_progress.valueChanged.connect(values.append);stable=[]
        def observe(payload):
            if 'statuses' in payload:stable.append(all(payload['statuses'][d]['complete'] for d in early))
        w.translation_updates.ready.connect(observe)
        w.pages.setCurrentIndex(7);app.processEvents();w.pages.setCurrentIndex(8);app.processEvents();w.pages.setCurrentIndex(0);app.processEvents()
        hidden_tts=[];hidden_capcut=[]
        original_tts=w.tts_page.refresh;original_capcut=w.capcut_page.set_busy
        monkeypatch.setattr(w.tts_page,'refresh',lambda *a:(hidden_tts.append(w.pages.currentIndex()),original_tts(*a))[1])
        monkeypatch.setattr(w.capcut_page,'set_busy',lambda *a:(hidden_capcut.append(w.pages.currentIndex()),original_capcut(*a))[1])
        ticks.clear();switch_ms=[]
        for page in (2,7,9,0,2,7,9,0):
            start=time.perf_counter();w.pages.setCurrentIndex(page);app.processEvents();switch_ms.append((time.perf_counter()-start)*1000)
            p.table.scrollToBottom();w.table.scrollToBottom();w.resize(1100,760);app.processEvents();w.resize(1440,940);QTest.qWait(30)
        assert all(page==7 for page in hidden_tts) and all(page==8 for page in hidden_capcut)
        w.pause_or_resume();assert p.controller.paused.is_set();w.pause_or_resume();assert not p.controller.paused.is_set()
        w.pages.setCurrentIndex(0);steady_start=len(ticks);gate.set();wait(app,lambda:not p.controller.busy,120)
        w.translation_updates.request(full=True);assert w.translation_updates.wait_for_idle(10)
        assert p.repo.workset(wid)['state']=='completed',p.repo.events(wid)[-5:]
        assert len(w.store.jobs())==100 and len(calls)==702 and peak>=60 and peak<=90
        assert max(seen.values())==2 and all(seen[rid]==1 for rid in early_ids)
        assert all(w.store.line(rid)['translation']==r['translation'] for rid,r in accepted_early.items())
        assert all(s['complete'] for s in w.translation_updates.last['statuses'].values()) and w.total_progress.value()==100
        assert all(stable) and stable and not any(b<a for a,b in zip(values,values[1:]))
        assert len(FakeEngine.calls)==2000 and len([a for a in p.repo.artifacts(wid) if a['kind']=='capcut' and a['state']=='complete'])==4
        assert w.store.db.execute('SELECT COUNT(*) FROM api_text_versions WHERE accepted=1').fetchone()[0]==2000
        assert all(hashlib.sha256(path.read_bytes()).hexdigest()==digest for path,digest in hashes.items())
        gaps=[(b-a)*1000 for a,b in zip(ticks,ticks[1:])];steady=[(b-a)*1000 for a,b in zip(ticks[steady_start:],ticks[steady_start+1:])];timer.stop();w.pages.setCurrentIndex(9);p.refresh();wait(app,lambda:p.proof is not None,20);assert p.snapshots.wait_for_idle()
        evidence(w,f'automation-100files-{dark}',dict(status='PASS',files=100,units=2000,requests=len(calls),start_calls=1,continue_calls=0,restore_calls=0,concurrency=30,peak_http_lines=peak,early_complete=40,completed=100,completion_checks=len(stable),progress_regressions=0,tts_calls=2000,capcut_parts=4,tab_switch_ms=switch_ms,max_tick_gap_ms=max(gaps,default=0),steady_tick_p95_ms=sorted(steady)[int((len(steady)-1)*.95)] if steady else 0,steady_tick_max_ms=max(steady,default=0),snapshot_apply_max_ms=max(p.snapshots.apply_ms,default=0),validation_wall_ms=validation_ms,validation_gui_dispatch_ms=validation_dispatch_ms,sources_unchanged=True))
    finally:gate.set();timer.stop()


@pytest.mark.parametrize('mode',['direct','automation'])
def test_actual_start_ab_same_sources_model_workers_and_mock_faults(gui,tmp_path,monkeypatch,mode):
    app,w,p,wid=gui;paths=[]
    for i in range(6):paths.append(add_group(p.repo,wid,tmp_path/str(i),f'Chapter {i:03}',20)[1])
    docs=[g['document_id'] for g in p.repo.groups(wid)];rows={d:w.store.lines(d) for d in docs}
    digest=hashlib.sha256(b''.join(path.read_bytes() for path in paths)).hexdigest()
    faults={rows[docs[4]][0]['id']:429,rows[docs[5]][0]['id']:503};seen=Counter();requests=[]
    async def handler(req):
        batch=request_lines(req);requests.append([r['id'] for r in batch]);await asyncio.sleep(.01)
        for r in batch:seen[r['id']]+=1
        bad=next((r['id'] for r in batch if r['id'] in faults and seen[r['id']]==1),None)
        if bad:return httpx.Response(faults[bad],headers={'Retry-After':'.05'})
        return response(req)
    def provider(store,job):return KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox,'information',lambda *a:pytest.fail('Unexpected information dialog'))
    p.services.translation=Translation(p.repo,provider,network_probe=lambda _:True)
    w.workspace_ids=docs;w.open_document(docs[0]);w.source_lang.setCurrentText('Tiếng Việt');w.target_lang.setCurrentText('Tiếng Anh');w.sync_target_chips();w.concurrency.setValue(30)
    monkeypatch.setattr(w,'selected_model_id',lambda:'mock');monkeypatch.setattr(w,'make_provider',lambda job,key:provider(w.store,job))
    if mode=='direct':
        w.pages.setCurrentIndex(0);w.refresh();app.processEvents();QTest.mouseClick(w.start_button,Qt.LeftButton)
        wait(app,lambda:w.scheduler is not None);wait(app,lambda:not w.scheduler._thread.is_alive(),20)
    else:
        p.load_worksets(wid);p.validate_clicked();wait(app,lambda:p.proof is not None);assert p.proof['passed']
        w.pages.setCurrentIndex(9);p.refresh();app.processEvents();QTest.mouseClick(p.start,Qt.LeftButton)
        wait(app,lambda:p.controller.busy);wait(app,lambda:not p.controller.busy,25)
        assert p.repo.workset(wid)['state']=='completed'
    w.pages.setCurrentIndex(0);w.translation_updates.request(full=True);assert w.translation_updates.wait_for_idle()
    jobs=w.store.jobs();assert len(jobs)==6 and len({j['id'] for j in jobs})==6 and len(requests)==44
    assert all(j['model']=='mock' and j['provider']=='kira' and j['concurrency']==30 for j in jobs)
    assert all(s['complete'] for s in w.translation_updates.last['statuses'].values())
    assert sum(s['done'] for s in w.translation_updates.last['statuses'].values())==120 and w.total_progress.value()==100
    evidence(w,f'actual-ab-{mode}',dict(status='PASS',mode=mode,files=6,units=120,input_sha256=digest,model='mock',provider='kira',workers=30,batch=3,start_calls=1,continue_calls=0,restore_calls=0,requests=len(requests),jobs=[j['id'] for j in jobs],job_states=[j['state'] for j in jobs]))
