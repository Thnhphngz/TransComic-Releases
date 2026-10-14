import threading
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication
from qt_wait import wait_until
from test_first_local_build import window
from test_internal_queue_clear import fixture, service


def test_result_delivery_is_on_gui_thread_and_rapid_clicks_share_check(tmp_path):
    app, w = window(tmp_path)
    release, envelope, contents = fixture()
    panel = w.update_panel
    panel.service = service(tmp_path, release, contents)
    checks = []
    received = []
    original = panel.service.check
    def check(*args):
        checks.append(threading.get_ident())
        return original(*args)
    panel.service.check = check
    panel.signals.result.connect(lambda result: received.append(QThread.currentThread() == app.thread()))
    try:
        for _ in range(30):
            panel.check_now(True)
        assert wait_until(lambda: panel.update_dialog is not None and bool(received), 3000)
        assert len(checks) == 1 and checks[0] != threading.get_ident()
        assert received == [True]
        assert panel.update_dialog.parent() is w
        panel.update_dialog.reject()
    finally:
        w._exit_authorized = True
        w.close()


def test_close_while_check_completes_suppresses_late_dialog(tmp_path):
    app, w = window(tmp_path)
    release, envelope, contents = fixture()
    panel = w.update_panel
    panel.service = service(tmp_path, release, contents)
    entered = threading.Event()
    gate = threading.Event()
    original = panel.service.check
    def check(*args):
        entered.set()
        assert gate.wait(3)
        return original(*args)
    panel.service.check = check
    panel.check_now(True)
    worker = panel.worker
    try:
        assert entered.wait(1)
        w._exit_authorized = True
        w.close()
        assert w._closed and panel.shutdown_event.is_set()
    finally:
        gate.set()
        worker.join(3)
    assert not worker.is_alive()
    app.processEvents()
    assert panel.update_dialog is None
