import asyncio
import json
import threading
import time

import httpx
import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from transcomic.documents import decode_txt
from transcomic.providers import KiraProvider
from transcomic.storage import Store
from transcomic.translation import Scheduler
from transcomic.ui.main import MainWindow


def setup(tmp_path, concurrency=30, count=180, config=None):
    store=Store(tmp_path/'performance.db')
    doc,_=store.import_document(tmp_path/'a.txt',decode_txt('\n'.join(f'Source {i}' for i in range(count)).encode()))
    job=store.create_job(doc,'deepseek-v4.1-flash','vi','en',concurrency,config=config or {})
    return store,doc,job


def good(request):
    lines=json.loads(json.loads(request.content)['messages'][1]['content'])['lines']
    return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':r['id'],'text':'A valid English translation.'} for r in lines]})}}]})


@pytest.mark.parametrize('cap',[1,10,30,50])
def test_actual_http_parallelism_and_shared_client(tmp_path,cap):
    store,doc,job=setup(tmp_path,cap)
    active=peak=clients=0
    async def handle(request):
        nonlocal active,peak
        active+=1;peak=max(active,peak)
        await asyncio.sleep(.06)
        active-=1
        return good(request)
    class Provider(KiraProvider):
        def client(self, concurrency=1):
            nonlocal clients
            clients+=1
            client=super().client(concurrency)
            assert client._transport is self.transport
            return client
    s=Scheduler(store,Provider('mock-only',transport=httpx.MockTransport(handle)))
    s.start(job);s.join(12)
    assert not s._thread.is_alive() and peak==cap and clients==1
    assert len(store.lines(doc))==s.accepted_lines==180
    diagnostics=store.attempts(store.batches(job)[0]['id'])[0]['diagnostics']
    assert diagnostics['validator_seconds']>=0 and diagnostics['database_seconds']>=diagnostics['validator_seconds']
    assert diagnostics['headers_seconds']>=0 and diagnostics['body_seconds']>=diagnostics['headers_seconds']
    assert diagnostics['connect_seconds']=='unknown'  # Mock transport has no TCP.
    assert diagnostics['sqlite_commit_seconds']>=0
    assert diagnostics['batch_created_at']!='unknown' and diagnostics['http_started_at']!='unknown'
    assert s.active_http==0
    store.close()


@pytest.mark.parametrize('cap',[1,30])
def test_stop_safe_exit_never_responding_http_repaints_no_replay(tmp_path,monkeypatch,cap):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    store,doc,job=setup(tmp_path,cap)
    calls=[]
    async def handle(request):
        calls.append(time.monotonic())
        await asyncio.Event().wait()
    w=MainWindow(store);w.show();w.shutdown_grace_seconds=.15
    w.scheduler=Scheduler(store,KiraProvider('mock-only',transport=httpx.MockTransport(handle)),w.bridge.changed.emit)
    w.scheduler.start(job)
    deadline=time.monotonic()+3
    while len(calls)<cap and time.monotonic()<deadline:
        QTest.qWait(10); time.sleep(.005)
    assert len(calls)==cap
    ticks=[]; timer=QTimer(w);timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(time.monotonic()));timer.start()
    monkeypatch.setattr(w,'confirm_exit',lambda running:'safe')
    begin=time.monotonic();w.stop_translation();w.close();w.close()
    while not w._closed and time.monotonic()-begin<3:
        QTest.qWait(10); time.sleep(.005)
    assert w._closed and time.monotonic()-begin<1.5 and len(ticks)>=5
    assert len(calls)==cap and not w.scheduler._thread.is_alive()
    reopened=Store(tmp_path/'performance.db')
    assert sum(r['state']=='unknown' for r in reopened.lines(doc))==cap*3
    from transcomic.retry import allowed_retry
    attempts=[a for b in reopened.batches(job) for a in reopened.attempts(b['id'])]
    assert all(a['diagnostics']['failure_kind']=='shutdown_cancelled' and not allowed_retry(reopened.job(job),a['diagnostics'],2) for a in attempts)
    restarted=MainWindow(reopened)
    assert restarted.scheduler is None and not restarted.workspace_ids
    restarted._exit_authorized=True;restarted.close()


def test_stop_does_not_wait_for_sqlite_writer(tmp_path):
    store,doc,job=setup(tmp_path)
    s=Scheduler(store,KiraProvider('mock-only'))
    s.job_id=job
    locked=threading.Event();release=threading.Event()
    def writer():
        with store.transaction():
            locked.set();release.wait(2)
    t=threading.Thread(target=writer);t.start();assert locked.wait(1)
    start=time.monotonic();s.stop()
    assert time.monotonic()-start<.05
    release.set();t.join();store.close()


def test_cancellation_ignoring_transport_is_fenced_and_late_result_discarded(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    store,doc,job=setup(tmp_path,1,3)
    w=MainWindow(store);w.show();app.processEvents()
    entered=threading.Event();release=threading.Event()
    async def handle(request):
        entered.set()
        while not release.is_set():
            try: await asyncio.sleep(.01)
            except asyncio.CancelledError: continue
        return good(request)
    w.scheduler=Scheduler(store,KiraProvider('mock-only',transport=httpx.MockTransport(handle)),w.bridge.changed.emit)
    w.scheduler.start(job);assert entered.wait(2)
    w.shutdown_grace_seconds=.1;monkeypatch.setattr(w,'confirm_exit',lambda running:'safe')
    begin=time.monotonic();w.close()
    while not w._closed and time.monotonic()-begin<3:
        QTest.qWait(5);time.sleep(.005)
    assert w._closed and time.monotonic()-begin<1.5
    reopened=Store(tmp_path/'performance.db')
    assert all(r['state']=='unknown' and not r['translation'] for r in reopened.lines(doc))
    assert reopened.attempts(reopened.batches(job)[0]['id'])[0]['state']=='unknown'
    release.set();w.scheduler.join(2)
    assert not w.scheduler._thread.is_alive()
    assert all(not r['translation'] for r in reopened.lines(doc))
    assert not Scheduler.has_work(reopened,job)
    reopened.close()


def test_safe_exit_during_sqlite_commit_remains_responsive_and_preserves_result(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    store,doc,job=setup(tmp_path,1,3)
    w=MainWindow(store);w.show();app.processEvents()
    entered=threading.Event();release=threading.Event();original=store.finish_batch
    def blocked_commit(*args,**kwargs):
        with store.transaction():
            entered.set();release.wait(2)
            return original(*args,**kwargs)
    monkeypatch.setattr(store,'finish_batch',blocked_commit)
    w.scheduler=Scheduler(store,KiraProvider('mock-only',transport=httpx.MockTransport(good)),w.bridge.changed.emit)
    w.scheduler.start(job);assert entered.wait(2)
    monkeypatch.setattr(w,'confirm_exit',lambda running:'safe')
    timer=QTimer(w);ticks=[];timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(1));timer.start()
    timing={};start=time.monotonic()
    def release_on_gui():
        timing['release_ms']=(time.monotonic()-start)*1000;release.set()
    QTimer.singleShot(80,release_on_gui)
    # A refresh already queued before safe exit must not wait on the writer.
    w.automation_page.dirty=True
    QTimer.singleShot(0,w.automation_page.flush)
    w.stop_translation();timing['stop_ms']=(time.monotonic()-start)*1000
    close_started=time.monotonic();w.close();timing['close_ms']=(time.monotonic()-close_started)*1000
    while not w._closed and time.monotonic()-start<3:
        QTest.qWait(5);time.sleep(.005)
    timing.update(total_ms=(time.monotonic()-start)*1000,ticks=len(ticks))
    print('sqlite safe-exit timing',timing)
    # Counting callbacks after a two-second freeze could falsely pass. The GUI
    # itself must release the writer promptly, with a live heartbeat before exit.
    assert w._closed and ticks and timing.get('release_ms',float('inf'))<750,timing
    reopened=Store(tmp_path/'performance.db')
    assert all(r['state']=='done' and r['translation'] for r in reopened.lines(doc))
    reopened.close()


def test_console_flush_occurs_off_gui_thread(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    store,doc,job=setup(tmp_path,1,3)
    w=MainWindow(store);w.show();app.processEvents()
    owner=threading.get_ident();threads=[];original=store.log.close
    def slow_flush():
        threads.append(threading.get_ident());time.sleep(.12);original()
    monkeypatch.setattr(store.log,'close',slow_flush)
    w._exit_pending=True;w._exit_deadline=time.monotonic()+.1
    w.exit_timer.start();start=time.monotonic();ticks=[]
    heartbeat=QTimer(w);heartbeat.setInterval(10);heartbeat.timeout.connect(lambda:ticks.append(1));heartbeat.start()
    while not w._closed and time.monotonic()-start<3:
        QTest.qWait(5);time.sleep(.005)
    assert w._closed and threads[0]!=owner and len(ticks)>=5


def test_gateway_storm_is_paced_budget_and_recovery(tmp_path):
    store,doc,job=setup(tmp_path,10,60,{'gateway_backoff_base':.01})
    sent=[]; counts={}
    async def handle(request):
        key=json.loads(json.loads(request.content)['messages'][1]['content'])['lines'][0]['id']
        counts[key]=counts.get(key,0)+1;sent.append(time.monotonic())
        await asyncio.sleep(.015)
        return httpx.Response(504,json={}) if counts[key]==1 else good(request)
    s=Scheduler(store,KiraProvider('mock-only',transport=httpx.MockTransport(handle)))
    s.start(job);s.join(12)
    assert not s._thread.is_alive() and all(r['state']=='done' for r in store.lines(doc))
    assert s.http_504==20 and s.retry_count==20 and s.gateway_streak==0
    assert all(len(store.attempts(b['id']))==2 for b in store.batches(job))
    assert any(e['event']=='gateway_backoff' for e in store.log.snapshot())
    assert max(b-a for a,b in zip(sent,sent[1:]))>=.05
    store.close()


@pytest.mark.parametrize('length',[20,6000])
def test_three_long_short_lines_no_speculative_thinking_parameters(length):
    async def handle(request):
        body=json.loads(request.content)
        assert 'thinking' not in body and 'reasoning_effort' not in body
        lines=json.loads(body['messages'][1]['content'])['lines']
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':r['id'],'text':'A complete translated sentence. '*length} for r in lines]})},'finish_reason':'stop'}]})
    result=asyncio.run(KiraProvider('mock-only',transport=httpx.MockTransport(handle)).translate(
        [{'id':str(i),'source':'x '*length} for i in range(3)],'vi','en'))
    assert not result.error and len(result.values)==3
    assert all(len(text)>length for text in result.values.values())


def test_warning_cache_invalidates_manual_edit_and_export_guard(tmp_path):
    from transcomic.language_validator import export_faults
    store,doc,job=setup(tmp_path,count=3)
    row=store.lines(doc)[0]
    store.edit_line(row['id'],'source','Hôm nay tôi đã trở về nhà và gặp lại người bạn của mình')
    store.edit_line(row['id'],'translation','I came home today and met my friend again.')
    assert all(r['state']!='wrong_target_language' for r in store.warning_rows(doc))
    assert all(r['state']!='wrong_target_language' for r in store.warning_rows(doc))
    store.edit_line(row['id'],'translation',store.line(row['id'])['source'])
    assert store.warning_rows(doc) and export_faults(store.document(doc),store.lines(doc))
    store.close()


def test_sky_switch_keyboard_persist_and_button_geometry(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'ui.db');w=MainWindow(store);w.show()
    QTest.qWait(80)
    app.processEvents()
    before=w.table.height();w.sky_switch.setFocus();QTest.keyClick(w.sky_switch,Qt.Key_Space);QTest.qWait(240)
    assert w.dark and w.sky_switch.isChecked() and store.setting('dark')=='1'
    deadline=time.monotonic()+1
    while w.sky_switch.get_night()!=1 and time.monotonic()<deadline:QTest.qWait(20)
    assert w.sky_switch.get_night()==1 and w.table.height()==before
    assert w.stop_button.objectName()=='danger' and w.start_button.objectName()=='primary'
    w.resize(900,580);app.processEvents();assert w.table.viewport().height()>80
    w.toggle_sidebar();app.processEvents();assert w.sky_switch.width()<=w.sidebar.width()
    w._exit_authorized=True;w.close()
