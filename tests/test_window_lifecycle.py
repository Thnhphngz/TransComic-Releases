import asyncio
import json
import threading

import pytest
from PySide6.QtCore import QRect, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from transcomic.documents import decode_txt
from transcomic.providers import BatchResult
from transcomic.storage import Store
from transcomic.translation import Scheduler
from transcomic.ui.exit_dialog import ExitDialog
from transcomic.ui.main import MainWindow
from transcomic.ui.window_state import edid_inches, window_plan
from transcomic.ui import window_state


class Screen:
    def __init__(self, name, rect):
        self._name, self._rect = name, rect

    def name(self):
        return self._name

    def availableGeometry(self):
        return self._rect


@pytest.mark.parametrize("inches,maximized", [(15.6, True), (20.9, True), (21.0, False), (27.0, False), (None, True)])
def test_screen_startup_policy(inches, maximized):
    screen = Screen("laptop", QRect(0, 0, 1920, 1040))
    plan = window_plan([screen], screen, measure=lambda s: inches)
    assert plan.maximized is maximized
    assert screen.availableGeometry().contains(plan.geometry)


def test_saved_window_uses_correct_monitor_and_clamps_geometry():
    first = Screen("first", QRect(0, 0, 1920, 1040))
    second = Screen("second", QRect(1920, -200, 2560, 1400))
    saved = json.dumps({"screen": "second", "rect": [9999, -9999, 1500, 900], "maximized": False})
    plan = window_plan([first, second], first, saved, measure=lambda s: 13)
    assert plan.screen is second and plan.reason == "saved" and not plan.maximized
    assert second.availableGeometry().contains(plan.geometry)
    disconnected = window_plan([first], first, saved, measure=lambda s: None)
    assert disconnected.screen is first and first.availableGeometry().contains(disconnected.geometry)


def test_edid_requires_valid_checksum_and_physical_dimensions():
    data = bytearray(128)
    data[:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    data[21], data[22] = 60, 34
    data[127] = (-sum(data)) % 256
    assert 27 < edid_inches(bytes(data)) < 28
    data[21] = 0
    assert edid_inches(bytes(data)) is None
    assert edid_inches(b"invalid") is None


@pytest.mark.parametrize("inches,maximized", [(15.6, True), (27.0, False), (None, True)])
def test_startup_applies_window_state_in_qt(tmp_path, monkeypatch, inches, maximized):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "startup.db")
    window = MainWindow(store)
    monkeypatch.setattr(window_state, "monitor_inches", lambda screen: inches)
    window_state.show_initial(window)
    app.processEvents()
    assert window.isMaximized() is maximized
    window.close()


def make_window(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "lifecycle.db")
    doc, _ = store.import_document(tmp_path / "a.txt", decode_txt("\n".join(f"Line {i}" for i in range(9)).encode()))
    window = MainWindow(store)
    window.show()
    window.open_document(doc)
    app.processEvents()
    return app, store, window, doc


def test_exit_dialog_idle_cancel_default_and_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app, store, window, doc = make_window(tmp_path)
    dialog = ExitDialog(window)
    assert dialog.buttons["cancel"].isDefault()
    QTimer.singleShot(0, dialog.buttons["cancel"].click)
    dialog.exec()
    assert dialog.choice == "cancel"
    monkeypatch.setattr(window, "confirm_exit", lambda running: "cancel")
    window.close()
    assert window.isVisible() and store.lines(doc)
    monkeypatch.setattr(window, "confirm_exit", lambda running: "exit")
    window.resize(1000, 650)
    window.close()
    reopened = Store(tmp_path / "lifecycle.db")
    state = json.loads(reopened.setting("window_state"))
    assert state["rect"][2:] == [1000, 650]
    assert len(reopened.lines(doc)) == 9
    reopened.close()


@pytest.mark.parametrize("tray", [False, True])
def test_working_dialog_offers_only_available_actions(tmp_path, monkeypatch, tray):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app, store, window, doc = make_window(tmp_path)
    dialog = ExitDialog(window, running=True, tray_available=tray)
    assert ("background" in dialog.buttons) is tray
    assert "safe" in dialog.buttons and "cancel" in dialog.buttons
    QTimer.singleShot(0, dialog.buttons["safe"].click)
    dialog.exec()
    assert dialog.choice == "safe"
    window.close()


def test_cancel_and_safe_exit_do_not_resend_inflight(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app, store, window, doc = make_window(tmp_path)
    dispatched = threading.Event()
    release = threading.Event()
    calls = []

    class SlowProvider:
        async def translate(self, lines, source_lang, target_lang):
            calls.append([r["id"] for r in lines])
            dispatched.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
            return BatchResult({r["id"]: "Translated" for r in lines})

    job = store.create_job(doc, "qwen3.8-flash", "English", "Vietnamese", 1)
    window.scheduler = Scheduler(store, SlowProvider(), window.bridge.changed.emit)
    window.scheduler.start(job)
    assert dispatched.wait(2)
    monkeypatch.setattr(window, "confirm_exit", lambda running: "cancel")
    window.close()
    assert not window.scheduler._stopped.is_set()
    assert window.isVisible()
    confirmations = []
    monkeypatch.setattr(window, "confirm_exit", lambda running: confirmations.append(running) or "safe")
    window.close()
    assert window._exit_pending and window.scheduler._stopped.is_set()
    release.set()
    for _ in range(30):
        QTest.qWait(30)
        if window._closed:
            break
    assert window._closed and confirmations == [True]
    assert len(calls) == 1
    reopened = Store(tmp_path / "lifecycle.db")
    assert reopened.job(job)["state"] == "stopped"
    assert len(reopened.batches(job, "pending")) == 2
    assert len(reopened.batches(job, "done")) == 1
    reopened.close()
