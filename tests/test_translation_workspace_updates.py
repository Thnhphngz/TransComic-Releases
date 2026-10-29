"""Text tab regression: synthetic documents, HTTP mocks, no production storage."""
import asyncio
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import httpx
import pytest
from PySide6.QtCore import Qt,QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMessageBox,QSystemTrayIcon
from transcomic.documents import decode_txt
from transcomic.storage import Store
from transcomic.ui.translation_updates import document_status,SnapshotReader
from test_kira_auto_recovery import response,request_lines


def wait(app,condition,seconds=15):
    limit=time.monotonic()+seconds
    while not condition() and time.monotonic()<limit:app.processEvents();time.sleep(.003)
    app.processEvents();assert condition()


@pytest.mark.parametrize('state',['waiting_rate_limit','provider_recovering','retry_scheduled','user_paused','stopped','interrupted','blocked_quota','running','finished'])
def test_complete_file_precedes_global_state_but_not_new_work_or_invalid_revision(state):
    row=dict(id='stable',source='Nguồn',translation='A valid translation',state='done',source_revision=2,translation_source_revision=2)
    assert document_status([row],state)['state']=='Đã xong'
    assert not document_status([row],state,pending_work=True)['complete']
    assert not document_status([row],state,structural=True)['complete']
    assert not document_status([{**row,'source_revision':3}],state)['complete']
    for error in ('error','unknown','pending','processing','wrong_target_language','stale'):
        assert not document_status([{**row,'state':error}],state)['complete']


def test_reader_thread_uses_readonly_connection_and_does_not_wait_for_store_lock(tmp_path):
    store=Store(tmp_path/'source.sqlite3');doc,_=store.import_document(tmp_path/'a.txt',decode_txt('Nguồn'.encode()),'vi','en')
    key=store.lines(doc)[0]['id'];store.edit_line(key,'translation','A valid translation')
    before=store.db.total_changes;result=[];errors=[]
    def reader():
        r=SnapshotReader(store.path)
        try:
            result.append(r.read([doc],[],True,doc))
            with pytest.raises(sqlite3.OperationalError):r.db.execute("DELETE FROM lines")
        except BaseException as exc:errors.append(exc)
        finally:r.close()
    with store.lock:
        thread=threading.Thread(target=reader);thread.start();thread.join(2)
        assert not thread.is_alive() and not errors
    assert result[0]['statuses'][doc]['state']=='Đã xong' and store.db.total_changes==before
    store.close()


def test_delta_query_budget_and_mapping_proof_are_independent_from_percent(tmp_path):
    store=Store(tmp_path/'delta.sqlite3');docs=[]
    for i in range(100):docs.append(store.import_document(tmp_path/f'{i}.txt',decode_txt('Nguồn A\nNguồn B'.encode()),'vi','en')[0])
    for row in store.lines(docs[0]):store.edit_line(row['id'],'translation','A valid translation')
    reader=SnapshotReader(store.path)
    try:
        initial=reader.read(docs,[],True,docs[0]);assert initial['statuses'][docs[0]]['state']=='Đã xong'
        row=store.lines(docs[50])[0];store.edit_line(row['id'],'translation','The other file changed')
        delta=reader.read(docs,[row['id']],False,docs[0])
        assert delta['editor'] is None and delta['dirty']=={docs[50]} and len(delta['updates'])==1 and delta['sql']<=8
        assert delta['statuses'][docs[0]]==initial['statuses'][docs[0]]
        # A corrupt fixture may say 100% after deleting an original TXT unit.
        # Snapshot mapping proof must still prevent a completed label.
        rid=store.lines(docs[0])[1]['id']
        with store.transaction():
            store.db.execute('DELETE FROM line_edits WHERE line_id=?',(rid,))
            store.db.execute('DELETE FROM quality_warnings WHERE line_id=?',(rid,))
            store.db.execute('DELETE FROM lines WHERE id=?',(rid,))
        invalid=reader.read(docs,[],True,docs[0])['statuses'][docs[0]]
        assert invalid['progress']==100 and invalid['state']=='Cần kiểm tra cấu trúc' and not invalid['complete']
    finally:reader.close();store.close()


@pytest.fixture
def gui(tmp_path,monkeypatch):
    if os.environ.get('TRANSCOMIC_NATIVE_UI')!='1':monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    from transcomic.ui.main import MainWindow
    from transcomic.ui.tts_page import TtsPage
    monkeypatch.setattr(TtsPage,'check_runtime',lambda self:None)
    monkeypatch.setattr(QSystemTrayIcon,'isSystemTrayAvailable',lambda:False)
    app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
    store=Store(tmp_path/'ui.sqlite3');store.set_setting('update_auto_check','0');store.set_setting('concurrency','30');store.set_setting('kira_retry_backoff','0')
    window=MainWindow(store);window.resize(1440,900);window.setWindowTitle('TransComic — isolated mock UI test');window.show();app.processEvents()
    yield app,store,window
    if window.scheduler and not hasattr(window.scheduler,'stop'):window.scheduler=None
    if window.scheduler and window.scheduler._thread and window.scheduler._thread.is_alive():window.scheduler.stop();window.scheduler.cancel_inflight();window.scheduler.join(5)
    if not window._closed:window._exit_authorized=True;window.close();app.processEvents()


def test_active_editor_and_inactive_file_updates_do_not_reset_or_read_gui_database(gui,tmp_path):
    from types import SimpleNamespace
    app,store,w=gui
    docs=[store.import_document(tmp_path/f'{n}.txt',decode_txt('Nguồn A\nNguồn B'.encode()),'vi','en')[0] for n in range(2)]
    w.workspace_ids=docs;w.open_document(docs[0]);app.processEvents()
    fake=SimpleNamespace(job_id=None,job_ids=[],_thread=SimpleNamespace(is_alive=lambda:True),_paused=threading.Event(),_stopped=threading.Event(),active=0,retry_count=0,acknowledge=lambda *a:None)
    w.scheduler=fake;w.translation_updates.request(full=True);assert w.translation_updates.wait_for_idle()
    model_changes=[];resets=[];w.model.dataChanged.connect(lambda *a:model_changes.append(1));w.model.modelReset.connect(lambda:resets.append(1))
    w.table.edit(w.model.index(0,1));app.processEvents();editor=w.table.itemDelegate().active_editor;assert editor is not None
    editor.insertPlainText('An unfinished manual correction');text=editor.toPlainText();cursor=editor.textCursor().position()
    app.processEvents();w.automation_page.timer.stop()
    model_changes.clear();resets.clear()
    row=store.lines(docs[1])[0];store.edit_line(row['id'],'translation','The other file has changed.')
    queries=[];gui_thread=threading.get_ident()
    store.db.set_trace_callback(lambda sql:queries.append(sql) if threading.get_ident()==gui_thread else None)
    highlights=[];original=w.period_warning.update_highlight;w.period_warning.update_highlight=lambda:highlights.append(1)
    w.refresh([row['id']]);assert w.translation_updates.wait_for_idle()
    w.period_warning.update_highlight=original
    store.db.set_trace_callback(None)
    assert not queries and not model_changes and not resets and not highlights
    assert editor.toPlainText()==text and editor.textCursor().position()==cursor
    editor.undo();assert not editor.toPlainText();editor.redo();assert editor.toPlainText()==text
    w.scheduler=None


def test_existing_manual_language_validation_is_preserved_off_gui_thread(gui,tmp_path):
    from types import SimpleNamespace
    app,store,w=gui
    source='Hôm nay tôi đã trở về nhà và gặp lại người bạn của mình'
    doc,_=store.import_document(tmp_path/'manual.txt',decode_txt(source.encode()),'vi','en')
    w.workspace_ids=[doc];w.open_document(doc)
    w.scheduler=SimpleNamespace(job_id=None,job_ids=[],_thread=SimpleNamespace(is_alive=lambda:True),_paused=threading.Event(),_stopped=threading.Event(),active=0,retry_count=0,acknowledge=lambda *a:None)
    w.translation_updates.request(full=True);assert w.translation_updates.wait_for_idle()
    w.model.setData(w.model.index(0,1),source)
    wait(app,lambda:store.line(w.model.all_rows[0]['id'])['state']=='wrong_target_language')
    wait(app,lambda:w.translation_updates.last['statuses'][doc]['errors']==1)
    assert not w.translation_updates.last['statuses'][doc]['complete']
    assert w.translation_updates.thread is not None and not store.db.execute('SELECT 1 FROM request_attempts').fetchone()
    w.scheduler=None


def test_temporary_read_connection_failure_recovers_without_manual_refresh(gui,tmp_path,monkeypatch):
    from types import SimpleNamespace
    import transcomic.ui.translation_updates as module
    app,store,w=gui
    doc,_=store.import_document(tmp_path/'busy.txt',decode_txt('Văn bản tổng hợp'.encode()),'vi','en')
    w.workspace_ids=[doc];w.open_document(doc)
    w.scheduler=SimpleNamespace(job_id=None,job_ids=[],_thread=SimpleNamespace(is_alive=lambda:True),_paused=threading.Event(),_stopped=threading.Event(),active=0,retry_count=0,acknowledge=lambda *a:None)
    original=module.SnapshotReader;calls=[]
    def factory(path):
        calls.append(1)
        if len(calls)==1:raise sqlite3.OperationalError('Synthetic read connection busy')
        return original(path)
    monkeypatch.setattr(module,'SnapshotReader',factory)
    w.translation_updates.request(full=True);assert w.translation_updates.wait_for_idle()
    assert len(calls)==2 and w.translation_updates.last['statuses'][doc]['total']==1
    assert w.translation_updates.thread.is_alive()
    worker=w.translation_updates.thread;w.scheduler=None;w._exit_authorized=True;w.close();app.processEvents();worker.join(1)
    assert not worker.is_alive()


def test_100_file_controls_pause_stop_and_reopen_are_responsive(gui,tmp_path):
    from transcomic.kira_pool import KiraPoolProvider
    from transcomic.translation import Scheduler
    app,store,w=gui;docs=[]
    for i in range(100):docs.append(store.import_document(tmp_path/f'Control {i}.txt',decode_txt('\n'.join(f'Văn bản tổng hợp {n}' for n in range(7)).encode()),'vi','en')[0])
    store.add_kira_keys('synthetic-controls-key');w.workspace_ids=docs;w.open_document(docs[0])
    r,jobs=store.create_run(docs,['en'],provider='kira',model='mock',source_lang='vi',concurrency=30,config={'kira_multi_key':True})
    gate=threading.Event();calls=[]
    async def handler(req):
        calls.append(1)
        while not gate.is_set():await asyncio.sleep(.005)
        await asyncio.sleep(.03);return response(req)
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000)
    w.scheduler=Scheduler(store,pool,w.bridge.changed.emit);w.scheduler.start_many(jobs,r);w.refresh()
    try:
        wait(app,lambda:len(calls)==30)
        begin=time.perf_counter();w.pause_or_resume();pause_ms=(time.perf_counter()-begin)*1000;assert w.scheduler._paused.is_set()
        gate.set();wait(app,lambda:w.scheduler.active==0)
        assert len(calls)==30
        w.pause_or_resume();wait(app,lambda:len(calls)>30)
        begin=time.perf_counter();w.stop_translation();stop_ms=(time.perf_counter()-begin)*1000;n=len(calls)
        wait(app,lambda:not w.scheduler._thread.is_alive());assert len(calls)==n
        w.translation_updates.request(full=True);assert w.translation_updates.wait_for_idle()
        completed=sum(s['complete'] for s in w.translation_updates.last['statuses'].values());assert 10<=completed<100
        assert all(s['state']=='Đã xong' if s['complete'] else s['state']=='Đã dừng' for s in w.translation_updates.last['statuses'].values())
        assert pause_ms<750 and stop_ms<100
        db=store.path;w._exit_authorized=True;w.close();app.processEvents()
        from transcomic.ui.main import MainWindow
        reopened=MainWindow(Store(db));reopened.workspace_ids=docs;reopened.show();reopened.open_document(docs[0]);reopened.translation_updates.request(full=True)
        try:
            assert reopened.translation_updates.wait_for_idle() and reopened.scheduler is None and len(calls)==n
            assert sum(s['complete'] for s in reopened.translation_updates.last['statuses'].values())==completed
        finally:reopened._exit_authorized=True;reopened.close();app.processEvents()
        proof=dict(platform=app.platformName(),dpr=w.devicePixelRatioF() if not w._closed else app.primaryScreen().devicePixelRatio(),files=100,pause_ms=pause_ms,stop_ms=stop_ms,requests_at_stop=n,requests_after_stop=len(calls),complete_after_restart=completed,auto_requests_on_reopen=0)
        target=os.environ.get('TRANSLATION_UI_EVIDENCE')
        if target:
            folder=Path(target);folder.mkdir(parents=True,exist_ok=True);(folder/'controls.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')
    finally:gate.set()


@pytest.mark.parametrize('dark',[False,True])
def test_100_files_2000_units_one_start_40_stable_then_all_complete(gui,tmp_path,monkeypatch,dark):
    from docx import Document
    from transcomic.bulk import import_many,plan_exports,write_exports
    from transcomic.kira_pool import KiraPoolProvider
    app,store,w=gui
    if w.dark!=dark:w.toggle_theme()
    paths=[]
    for i in range(100):
        path=tmp_path/f'Chapter {i:03}{".docx" if i%2 else ".txt"}'
        texts=[f'Văn bản thử chương {i+1} dòng {j+1}' for j in range(20)]
        if i%2:
            word=Document()
            for text in texts:word.add_paragraph(text)
            word.save(path)
        else:path.write_text('\n'.join(texts),encoding='utf-8')
        paths.append(path)
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    docs=import_many(store,paths,'vi','en')['document_ids'];assert len(docs)==100
    rows={doc:store.lines(doc) for doc in docs};owners={r['id']:doc for doc,rs in rows.items() for r in rs}
    early=set(docs[:40]);gate=threading.Event();seen=Counter();active=set();peak=0;calls=[];faults={rows[docs[40]][0]['id']:429,rows[docs[41]][0]['id']:503}
    async def handler(req):
        nonlocal peak
        batch=request_lines(req);ids={r['id'] for r in batch};doc=owners[batch[0]['id']]
        assert not ids&active;active.update(ids);peak=max(peak,len(active));calls.append([r['id'] for r in batch])
        try:
            while doc not in early and not gate.is_set():await asyncio.sleep(.004)
            await asyncio.sleep(.002)
            for rid in ids:seen[rid]+=1
            bad=next((rid for rid in ids if rid in faults and seen[rid]==1),None)
            if bad:return httpx.Response(faults[bad],headers={'Retry-After':'.05'})
            return response(req)
        finally:active.difference_update(ids)
    store.add_kira_keys('synthetic-100files-key')
    monkeypatch.setattr(w,'make_provider',lambda job,key:KiraPoolProvider(store,job['model'],prompt_version=job['prompt_version'],transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000))
    monkeypatch.setattr(QMessageBox,'information',lambda *a:pytest.fail('Unexpected dialog: '+str(a[2])))
    w.workspace_ids=docs;w.open_document(docs[0]);w.source_lang.setCurrentText('Tiếng Việt');w.target_lang.setCurrentText('Tiếng Anh');w.sync_target_chips();w.concurrency.setValue(30);w.refresh();app.processEvents()
    ticks=[];timer=QTimer(w);timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(time.perf_counter()));timer.start()
    assert w.start_button.isEnabled() and w.start_button.isVisible()
    start_action=time.perf_counter();QTest.mouseClick(w.start_button,Qt.LeftButton);start_ms=(time.perf_counter()-start_action)*1000
    wait(app,lambda:w.scheduler is not None)
    try:
        wait(app,lambda:w.translation_updates.last is not None and sum(s['complete'] for s in w.translation_updates.last['statuses'].values())==40,25)
        assert all(w.translation_updates.last['statuses'][d]['state']=='Đã xong' for d in early)
        transitions=[]
        def observe(payload):
            if 'statuses' in payload:transitions.append(all(payload['statuses'][d]['state']=='Đã xong' for d in early))
        w.translation_updates.ready.connect(observe)
        # Save a fixture checkpoint only. Opening its Store must never send HTTP.
        backup=tmp_path/'partial-copy.sqlite3';dest=sqlite3.connect(backup)
        with store.lock:store.db.backup(dest)
        dest.close();copy=Store(backup);copy.close();reader=SnapshotReader(backup)
        partial=reader.read(docs,[],True,docs[0]);reader.close()
        assert sum(s['complete'] for s in partial['statuses'].values())==40
        w.document_panel.search.setText('Chapter 0');app.processEvents();w.document_panel.search.clear()
        w.resize(1100,760);app.processEvents();w.resize(1440,900);app.processEvents()
        w.model.set_checked([2],True);w.table.scrollToBottom();app.processEvents()
        index=w.model.index(12,1);w.table.setCurrentIndex(index);w.table.edit(index);app.processEvents();scroll=w.table.verticalScrollBar().value()
        editor=w.table.itemDelegate().active_editor;assert editor is not None and editor.isVisible() and editor.geometry().intersects(w.table.viewport().rect())
        editor.setFocus();app.processEvents()
        editor.insertPlainText(' Manual draft');draft=editor.toPlainText();cursor=editor.textCursor().position();selection=set(w.model.selected_ids)
        changes=[];w.model.dataChanged.connect(lambda *a:changes.append(1))
        ticks.clear();gate.set()
        wait(app,lambda:not w.scheduler._thread.is_alive(),35)
        w.translation_updates.request(full=True);assert w.translation_updates.wait_for_idle(8)
        timer.stop()
        assert len(store.jobs())==100 and len(w.document_panel.model.items)==100
        assert all(s['state']=='Đã xong' for s in w.translation_updates.last['statuses'].values())
        assert all(item['status']=='Đã xong' for item in w.document_panel.model.items)
        assert sum(r['state']=='done' for doc in docs for r in store.lines(doc))==2000
        assert store.db.execute('SELECT COUNT(*) FROM api_text_versions WHERE accepted=1').fetchone()[0]==2000
        assert peak>=60 and not active and set(seen)==set(owners) and max(seen.values())<=2
        assert editor.toPlainText()==draft and editor.textCursor().position()==cursor and w.model.selected_ids==selection
        assert w.table.verticalScrollBar().value()==scroll and transitions and all(transitions)
        assert not changes
        assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
        exports=write_exports(store,plan_exports(store.export_snapshot(docs),tmp_path/'exports'))
        assert len(exports)==100 and all(r['state']=='exported' for r in exports)
        gaps=[(b-a)*1000 for a,b in zip(ticks,ticks[1:])];timer.stop()
        proof=dict(status='PASS',platform=app.platformName(),dpr=w.devicePixelRatioF(),dark=dark,files=100,units=2000,start_calls=1,continue_calls=0,restore_calls=0,
                   requests=len(calls),retry_requests=w.scheduler.retry_count,peak_http_line_ids=peak,completed_early=40,completed_final=100,accepted_versions=2000,exports=len(exports),start_planning_ms=start_ms,max_translation_tick_gap_ms=max(gaps,default=0),
                   apply_p95_ms=sorted(w.translation_updates.apply_ms)[int((len(w.translation_updates.apply_ms)-1)*.95)],sources_unchanged=True,draft_preserved=True)
        proof.update(completion_stability_checks=len(transitions),completion_regressions=0,scroll_preserved=True,editor_visible=True)
        target=os.environ.get('TRANSLATION_UI_EVIDENCE')
        if target:
            folder=Path(target);folder.mkdir(parents=True,exist_ok=True)
            (folder/f'100files-{dark}.json').write_text(json.dumps(proof,indent=2),encoding='utf-8');assert w.grab().save(str(folder/f'100files-{dark}.png'))
        before=len(calls);db=store.path
        w._exit_authorized=True;w.close();app.processEvents()
        restarted=Store(db);reader=SnapshotReader(db);again=reader.read(docs,[],True,docs[0]);reader.close()
        assert all(s['state']=='Đã xong' for s in again['statuses'].values()) and len(calls)==before
        restarted.close()
    finally:gate.set()
