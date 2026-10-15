"""Toolbar geometry and native DPI evidence, using isolated synthetic documents."""
import json
import os
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest, QSignalSpy
from PySide6.QtWidgets import QApplication

from transcomic.documents import decode_txt
from transcomic.storage import Store
from transcomic.ui.main import MainWindow


def wait_for(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(20)
    assert predicate()


@pytest.fixture
def gui(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path/'isolated.db')
    window = MainWindow(store)
    raw = '\n'.join(f'Nguồn minh họa dòng {i+1}' for i in range(145)).encode()
    path = tmp_path/'Minh họa.txt'
    path.write_bytes(raw)
    doc = store.import_document(path, decode_txt(raw), 'vi', 'en')[0]
    window.open_document(doc)
    for row in store.lines(doc)[:3]:
        store.edit_line(row['id'], 'translation', 'Example translation.')
    window.refresh()
    window.resize(1400, 850)
    window.show()
    wait_for(lambda: window.period_warning.count == 3 and window.line_check.report is not None)
    yield app, store, window
    window._exit_authorized = True
    window.close()
    app.processEvents()


def rect(widget, owner):
    return QRect(widget.mapTo(owner, QPoint()), widget.size())


@pytest.mark.parametrize('dark', [False, True])
def test_capture_complete_window(gui, dark):
    app, store, window = gui
    if window.dark != dark:
        window.toggle_theme()
    available = window.screen().availableGeometry()
    window.resize(min(1500, available.width()-20), min(900, available.height()-50))
    QTest.qWait(200)
    destination = os.environ.get('TRANSCOMIC_TOOLBAR_EVIDENCE')
    if destination:
        out = Path(destination)
        out.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(out/('dark.png' if dark else 'light.png')))
        (out/'display.json').write_text(json.dumps({
            'dpr': window.devicePixelRatioF(), 'platform': app.platformName(),
            'window': [window.width(), window.height()],
        }), encoding='utf-8')


def assert_toolbar(window):
    buttons = window.file_action_buttons[1:]
    areas = [rect(b, window.editor_page) for b in buttons]
    assert all(b.isVisible() and b.width() > 35 for b in buttons)
    assert len({r.y() for r in areas}) == 1
    assert len({r.height() for r in areas}) == 1
    assert all(a.right() < b.left() for a, b in zip(areas, areas[1:]))
    assert all(window.editor_page.rect().contains(r) for r in areas)
    badges = [rect(window.line_check, window.editor_page), rect(window.period_warning, window.editor_page)]
    assert badges[0].y() == badges[1].y()
    assert badges[0].right() < badges[1].left()
    assert all(r.bottom() < areas[0].top() for r in badges)
    assert badges[-1].right() == areas[-1].right()
    assert areas[0].top() <= 55  # Original title row, then actions; no extra badge rows.
    assert window.file_actions.geometry().height() <= 50
    for widget in buttons + [window.line_check, window.period_warning]:
        target = window.childAt(widget.mapTo(window, widget.rect().center()))
        assert target is widget  # No overlapping sibling intercepts the actual center.


@pytest.mark.parametrize('dark', [False, True])
def test_single_row_order_resize_no_overlap_and_original_header_height(gui, dark):
    app, store, window = gui
    if window.dark != dark:
        window.toggle_theme()
    for panel_visible in (True, False):
        if window.document_panel.isVisible() != panel_visible:
            window.toggle_documents_panel()
        for width in (1500, 1100, 900, 1250, 950):
            window.resize(width, 850)
            QTest.qWait(60)
            app.processEvents()
            assert_toolbar(window)
    current_top = rect(window.import_button, window.editor_page).top()
    window.validation_badges.hide()
    app.processEvents()
    original_top = rect(window.import_button, window.editor_page).top()
    window.validation_badges.show()
    app.processEvents()
    assert current_top - original_top <= 4
    assert [window.file_actions.getItemPosition(window.file_actions.indexOf(b))[:2]
            for b in window.file_action_buttons[1:]] == [(0, i) for i in range(1, 6)]


@pytest.mark.parametrize('dark', [False, True])
def test_badge_hover_click_popup_and_hide_without_moving_actions(gui, dark):
    app, store, window = gui
    if window.dark != dark:
        window.toggle_theme()
    window.resize(1000, 850)
    window.raise_()
    window.activateWindow()
    QTest.qWait(100)
    before = store.lines(window.doc_id)
    positions = [rect(b, window.editor_page) for b in window.file_action_buttons[1:]]
    for badge, title in ((window.line_check, 'Kiểm tra số dòng'),
                         (window.period_warning, 'Các dòng dịch có dấu chấm')):
        assert badge.text() in badge.toolTip()
        spy = QSignalSpy(badge.clicked)
        QTest.mouseMove(badge, badge.rect().center())
        QTest.qWait(160)
        assert badge.get_light() > 0
        QTest.mouseClick(badge, Qt.LeftButton, pos=badge.rect().center())
        app.processEvents()
        assert spy.count() == 1 and badge.dialog.isVisible()
        assert badge.dialog.windowTitle() == title
        assert badge.dialog.model.rowCount() > 0
        QTest.keyClick(badge.dialog, Qt.Key_Escape)
        app.processEvents()
        assert not badge.dialog.isVisible()
    assert store.lines(window.doc_id) == before
    for row in before[:3]:
        store.edit_line(row['id'], 'translation', 'Example translation')
    window.refresh()
    wait_for(lambda: not window.period_warning.isVisible())
    app.processEvents()
    assert window.line_check.isVisible()
    assert [rect(b, window.editor_page) for b in window.file_action_buttons[1:]] == positions
    assert rect(window.line_check, window.editor_page).right() == positions[-1].right()
