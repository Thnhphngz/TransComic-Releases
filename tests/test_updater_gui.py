import threading
import time
import httpx
import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.update.service import UpdateService, LATEST_URL
from transcomic.update.install import State, window_safety
from test_updater_stage_a import fixture_release

def wait(app,condition,ms=4000):
    end=time.monotonic()+ms/1000
    while not condition() and time.monotonic()<end:app.processEvents();QTest.qWait(10)
    assert condition()

@pytest.fixture
def gui(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    app=QApplication.instance() or QApplication([]);store=Store(tmp_path/'ui.db')
    window=MainWindow(store);window.show();app.processEvents()
    yield app,window,tmp_path
    window._exit_authorized=True;window.close();app.processEvents()

@pytest.mark.parametrize('dark',[False,True])
def test_update_settings_empty_workspace_v3_and_no_release(gui,dark):
    app,w,tmp=gui
    if w.dark!=dark:w.toggle_theme()
    panel=w.update_panel
    assert not w.workspace_ids and not w.target_languages() and not w.start_button.isEnabled()
    panel.service=UpdateService(tmp/'Updates',httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(404))))
    w.pages.setCurrentIndex(3);panel.check.click();wait(app,lambda:not panel.busy)
    assert 'Chưa có bản cập nhật' in panel.status.text()
    assert not panel.download.isEnabled() and panel.auto.isChecked()
    assert not window_safety(w).process_exited
    panel.auto.setChecked(False)
    assert w.store.setting('update_auto_check')=='0'
    calls=[]
    panel.service.check=lambda *a:calls.append(a)
    panel.auto_tick();app.processEvents();assert not calls
    assert w.sky_switch.isVisible() and w.target_languages()==[]

def test_background_check_download_progress_no_installer(gui):
    app,w,tmp=gui;r,e,m,keys,data=fixture_release(b'fixture'*20000)
    calls=[];ready=threading.Event();release=threading.Event()
    def send(req):
        calls.append((str(req.url),threading.get_ident()))
        if str(req.url)==LATEST_URL:
            ready.set();release.wait(2);return httpx.Response(200,json=r)
        return httpx.Response(200,content=m if req.url.path.endswith('json') else data)
    panel=w.update_panel;panel.service=UpdateService(tmp/'Updates',httpx.Client(transport=httpx.MockTransport(send)),keys=keys,testing=True)
    ticks=[];timer=QTimer();timer.setInterval(10);timer.timeout.connect(lambda:ticks.append(1));timer.start()
    panel.check.click();wait(app,ready.is_set);QTest.qWait(80)
    assert ticks and panel.busy and panel.machine.state==State.CHECKING
    release.set();wait(app,lambda:not panel.busy)
    assert panel.download.isEnabled() and panel.changelog.toPlainText()=='Fixture changelog'
    assert all(tid!=threading.get_ident() for _,tid in calls)
    panel.download.click();wait(app,lambda:not panel.busy)
    assert panel.progress.value()==100 and panel.machine.state==State.READY_TO_INSTALL
    assert 'không chạy bộ cài' in panel.status.text() and not panel.machine.simulated
    assert list((tmp/'Updates').glob('*.testdata'))
    assert not list((tmp/'Updates').glob('*.exe'))
    assert not w.workspace_ids and not w.target_languages();timer.stop()

def test_unsigned_update_disabled_and_auto_defers_active_scheduler(gui):
    app,w,tmp=gui;r,e,m,_,_=fixture_release(signed=False)
    panel=w.update_panel
    panel.service=UpdateService(tmp/'Updates',httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=r) if str(req.url)==LATEST_URL else httpx.Response(200,content=m))),testing=True)
    panel.check.click();wait(app,lambda:not panel.busy)
    assert not panel.download.isEnabled() and 'NOT_READY' in panel.safety.text()
    class Scheduler:
        _thread=type('Thread',(),{'is_alive':lambda self:True})()
    w.scheduler=Scheduler();calls=[];panel.service.check=lambda *a:calls.append(a)
    panel.auto_tick();assert not calls;w.scheduler=None

def test_cancel_download_and_shutdown_do_not_touch_db(gui):
    app,w,tmp=gui;r,e,m,keys,data=fixture_release(b'x'*150000)
    started=threading.Event();release=threading.Event()
    class Slow(httpx.SyncByteStream):
        def __iter__(self):
            yield data[:65536];started.set();release.wait(3);yield data[65536:]
    def send(req):
        if str(req.url)==LATEST_URL:return httpx.Response(200,json=r)
        if req.url.path.endswith('json'):return httpx.Response(200,content=m)
        return httpx.Response(200,stream=Slow())
    panel=w.update_panel;panel.service=UpdateService(tmp/'Updates',httpx.Client(transport=httpx.MockTransport(send)),keys=keys,testing=True)
    panel.check.click();wait(app,lambda:not panel.busy)
    panel.download.click();wait(app,started.is_set)
    panel.cancel.click();release.set();wait(app,lambda:not panel.busy)
    assert panel.machine.state==State.CANCELLED
    assert not list((tmp/'Updates').glob('*.part')) and not list((tmp/'Updates').glob('*.testdata'))
    w.store.set_setting('sentinel','kept');panel.shutdown()
    assert w.store.setting('sentinel')=='kept'


def test_shutdown_pending_worker_never_emits_to_deleted_qobject(gui):
    app,w,tmp=gui
    started=threading.Event();release=threading.Event();errors=[]
    def send(req):
        started.set();release.wait(3);return httpx.Response(404)
    panel=w.update_panel
    panel.service=UpdateService(tmp/'Updates',httpx.Client(transport=httpx.MockTransport(send)))
    old_hook=threading.excepthook
    try:
        threading.excepthook=lambda args:errors.append(args.exc_value)
        panel.check.click();wait(app,started.is_set)
        worker=panel.worker
        w._exit_authorized=True;w.close();app.processEvents()
        release.set();worker.join(2);QTest.qWait(20)
        assert not worker.is_alive() and errors==[]
    finally:threading.excepthook=old_hook;release.set()
