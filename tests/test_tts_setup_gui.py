import time
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from tests.test_tts_gui import gui,wait


def test_one_button_keeps_gui_responsive_until_probe_finishes(gui,monkeypatch):
    from transcomic.tts.setup import SetupFlow
    app,window,page=gui;seen=[]
    def work(self,config,cancel,progress):
        for label in ('Đang kiểm tra thiết bị','Đang tải mô hình giọng đọc','Đang kiểm tra tạo audio'):
            progress(1,2,label);time.sleep(.06);seen.append(label)
        return dict(backend='CPUExecutionProvider',probe_seconds=1,codecs={'wav':True,'mp3':True},fallback_reason='')
    monkeypatch.setattr(SetupFlow,'run',work);page.open_settings();QTest.mouseClick(page.setup_button,Qt.LeftButton);assert not page.runtime_ready and not page.setup_button.isEnabled()
    page.settings_dialog.resize(700,600);app.processEvents();assert page.settings_dialog.width()==700
    wait(app,lambda:page.runtime_ready and not page.is_busy());assert len(seen)==3 and 'Kokoro — Sẵn sàng' in page.asset_status.text() and 'CPU' in page.asset_status.text();assert page.scheduler.prepared_backend=='CPUExecutionProvider'


def test_setup_failure_offers_retry_and_cancel_never_reports_ready(gui,monkeypatch):
    from transcomic.tts.setup import SetupFlow
    app,window,page=gui
    def fail(*a,**k):raise RuntimeError('fixture download timeout')
    monkeypatch.setattr(SetupFlow,'run',fail);page.install_models();wait(app,lambda:not page.is_busy());assert not page.runtime_ready and page.setup_button.text()=='Thử lại' and 'Không thể hoàn tất' in page.asset_status.text()
    page.error_dialog.hide()
    def cancel(*a,**k):raise InterruptedError('fixture cancelled')
    monkeypatch.setattr(SetupFlow,'run',cancel);page.install_models();wait(app,lambda:not page.is_busy());assert 'Đã hủy' in page.asset_status.text() and not page.runtime_ready


def test_queued_setup_refresh_after_safe_close_never_reads_closed_database(gui):
    app,window,page=gui;called=[];page.input_timer.start();page.history_panel.filter_timer.start();window.close();wait(app,lambda:window._closed)
    page.refresh_when_idle();page.on_task_done((lambda _:called.append(True),(True,{})));page.on_event('finished','fixture');QTest.qWait(150);app.processEvents()
    from shiboken6 import isValid
    assert not called
    if isValid(page):assert not page.input_timer.isActive() and not page.history_panel.filter_timer.isActive()


def test_setup_status_multiline_is_not_squeezed_by_diagnostic_panel(gui):
    app,window,page=gui;page.open_settings();page.settings_dialog.resize(650,590)
    for text in ('Kokoro — Sẵn sàng\nThiết bị: CPU','Đang tải mô hình giọng đọc\nĐã tải: 320.0 MB / 760.0 MB','Kokoro — Sẵn sàng\nThiết bị: CPU\nGPU chưa sử dụng được; Kokoro vẫn hoạt động bằng CPU.'):
        page.asset_status.setText(text);app.processEvents()
        assert page.asset_status.height()>=page.asset_status.heightForWidth(page.asset_status.width())


def test_auto_worker_selection_uses_sidecar_without_persisting_runtime_details(gui,monkeypatch):
    import builtins,json,onnxruntime as rt
    from transcomic.tts import concurrency
    app,window,page=gui
    monkeypatch.setattr(concurrency,'gpu_identity',lambda:'fixture-device')
    monkeypatch.setattr(concurrency,'resource_gate',lambda workers:(True,''))
    page.parallel_width.setCurrentIndex(page.parallel_width.findData(0))
    config=page.config();key=concurrency.fingerprint(config)
    page.store.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)',('parallel:'+key,json.dumps({'workers':2})))
    page.runtime_info={'engine_process':dict(runtime=rt.__version__,providers=rt.get_available_providers())}
    original=builtins.__import__
    def absent(name,*args,**kwargs):
        if name=='onnxruntime':raise ModuleNotFoundError('isolated GUI')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',absent)
    config=page.config()
    assert config['workers']==2 and '_managed_engine' not in config
