"""Same-process ownership, shutdown and 429 publication regressions; mock only."""
import asyncio
import json
import threading
import time
from pathlib import Path
import httpx
import pytest
from PySide6.QtCore import QEvent, QCoreApplication, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid
from transcomic.ui.main import MainWindow
from transcomic.ui.glass import GlassSkin
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.translation import Scheduler
from transcomic.providers import KiraProvider
from test_retry_speed_workspace_search import window
from test_window_lifecycle import test_cancel_and_safe_exit_do_not_resend_inflight as existing_exit_test
from test_final_workflow import setup

def test_search_many_windows_snapshots_reentry_and_owned_cleanup(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    for iteration in range(12):
        path=tmp_path/str(iteration);path.mkdir()
        app,store,w,ids=window(path);s=w.search;s.open(True)
        s.document_scope.setCurrentIndex(1);s.query.setText('Evelyn')
        model=s.result_list.model();assert model.parent() is s.result_list
        index=model.index(0,0);s.result_clicked(index)
        assert s.current==0
        children=len(s.result_list.children())
        for i in range(50):
            s.query.setText('Evelyn' if i%2 else '')
            s.rebuild();assert s.result_list.model() is model
            assert s.result_list.count()==len(s.results)
        assert len(s.result_list.children())==children
        assert len([c for c in app.children() if isinstance(c,GlassSkin)])==1
        # Nested change during model reset must publish the latest query once,
        # rather than clear native items recursively in a signal callback.
        once=[]
        def change_query():
            if not once:once.append(1);s.query.setText('one')
        model.modelReset.connect(change_query)
        s.query.setText('translated')
        assert s.query.text()=='one' and s.results and all(r[1]=='source' for r in s.results)
        model.modelReset.disconnect(change_query)
        s.query.setText('Evelyn');s.replacement.setText('Emily');s.replace_current();s.undo()
        w.source_lang.showPopup();w.toggle_theme();w.source_lang.hidePopup()
        s.close_bar();s.open();w.open_document(ids[1]);s.rebuild()
        if iteration%2:w.source_lang.showPopup()
        w._exit_authorized=True;w.close();w.close()
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete);app.processEvents()
        assert not isValid(w) and not isValid(s) and not isValid(model)
        assert store.log.closed and not store.log.thread.is_alive()

def test_original_900ms_exit_repeated_same_process(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    for i in range(10):
        path=tmp_path/str(i);path.mkdir()
        # Calls the unchanged original assertions/deadline and real Scheduler.
        existing_exit_test(path,monkeypatch)
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)

@pytest.mark.parametrize('cap',[3,30])
def test_quota_reason_fences_before_slow_commit_and_publishes_after(tmp_path,cap):
    store,doc,job=setup(tmp_path,lines=cap*3,concurrency=cap)
    entered=threading.Event();release=threading.Event();calls=[];observed=[]
    original=store.finish_batch
    def slow_save(*args,**kwargs):
        if not entered.is_set():entered.set();assert release.wait(3)
        return original(*args,**kwargs)
    store.finish_batch=slow_save
    async def handle(req):
        calls.append(req);await asyncio.sleep(.01)
        return httpx.Response(429,headers={'Retry-After':'.01'},json={'error':{'code':'insufficient_quota'}})
    def changed(ids):
        finished=[a for b in store.batches(job) for a in store.attempts(b['id']) if a['state']=='finished']
        if finished:
            observed.append((scheduler.intervention_reason,store.job(job)['state'],finished[-1]['diagnostics'].get('intervention_reason')))
    scheduler=Scheduler(store,KiraProvider('mock-only',transport=httpx.MockTransport(handle)),changed)
    scheduler.start(job);assert entered.wait(2)
    assert scheduler.intervention_reason=='provider_quota_exhausted' and scheduler.quota_paused
    count=len(calls);time.sleep(.04);assert len(calls)==count<=cap
    release.set();scheduler.join(5)
    assert not scheduler._thread.is_alive() and observed
    assert all(reason==stored=='provider_quota_exhausted' and state=='quota_exhausted' for reason,state,stored in observed)
    assert all(len(store.attempts(b['id']))<=1 for b in store.batches(job))
    scheduler.resume();time.sleep(.02);assert len(calls)==count
    store.close()

def test_real_entry_process_exits_after_safe_cancel(tmp_path):
    import subprocess,sys,os
    # Separate process is only for proving OS process termination, not search stability.
    result=subprocess.run([sys.executable,'scripts/stability_windows_stress.py','--exit-only'],
        env=dict(os.environ,LOCALAPPDATA=str(tmp_path),QT_SCALE_FACTOR='1'),capture_output=True,timeout=20)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    assert b'process_exit_verified_by_parent' in result.stdout
