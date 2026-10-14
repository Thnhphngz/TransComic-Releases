from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QAbstractItemView

from transcomic.documents import decode_txt
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.ui.model import CHECK_COLUMN


def workspace(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "editor.db")
    doc_id, _ = store.import_document(tmp_path / "chapter.txt", decode_txt("\n".join(f"Dòng {i}" for i in range(100)).encode()))
    window = MainWindow(store)
    window.resize(1600, 1000)
    window.show()
    window.open_document(doc_id)
    app.processEvents()
    return app, store, window


def test_editor_fills_cell_and_tracks_resize_and_typing(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app, store, window = workspace(tmp_path)
    index = window.model.index(0, 1)
    QTest.mouseClick(window.table.viewport(), Qt.LeftButton, pos=window.table.visualRect(index).center())
    app.processEvents()
    editor = window.table.itemDelegate().active_editor
    assert editor is not None
    assert not editor.verticalScrollBar().isVisible()
    assert editor.width() >= window.table.visualRect(index).width() - 10
    old_width = editor.width()
    window.table.horizontalHeader().resizeSection(0, window.table.columnWidth(0)+80)
    app.processEvents()
    assert editor.width() < old_width
    assert editor.width() >= window.table.visualRect(index).width() - 10
    old_width = editor.width()
    window.resize(1250, 900)
    app.processEvents()
    assert editor.width() < old_width
    assert editor.width() >= window.table.visualRect(index).width() - 10
    short_height = window.table.rowHeight(0)
    editor.setPlainText("Văn bản dài cần tự xuống dòng hiển thị. " * 20)
    app.processEvents()
    assert window.table.rowHeight(0) > short_height
    assert editor.height() >= window.table.rowHeight(0) - 4
    assert window.model.rowCount() == 100
    assert store.line(window.model.rows[0]["id"])["translation"] == editor.toPlainText()
    QTest.keyClick(editor, Qt.Key_Escape)
    app.processEvents()
    window.close()


def test_api_update_preserves_caret_and_manual_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app, store, window = workspace(tmp_path)
    job_id = store.create_job(window.doc_id, "kira-2.5-flash", "English", "Vietnamese", 1)
    batch = store.batches(job_id)[0]
    store.claim_batch(batch["id"])
    index = window.model.index(0, 1)
    window.table.edit(index)
    app.processEvents()
    editor = window.table.itemDelegate().active_editor
    editor.setPlainText("Bản dịch đã sửa tay")
    cursor = editor.textCursor()
    cursor.setPosition(4)
    editor.setTextCursor(cursor)
    store.finish_batch(batch["id"], {r["id"]: "API cũ" for r in batch["payload"]})
    window.refresh([r["id"] for r in batch["payload"]])
    app.processEvents()
    assert editor.toPlainText() == "Bản dịch đã sửa tay"
    assert editor.textCursor().position() == 4
    assert store.line(batch["payload"][0]["id"])["translation"] == "Bản dịch đã sửa tay"
    window.close()


def test_untouched_editor_does_not_overwrite_new_api_result(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app, store, window = workspace(tmp_path)
    job = store.create_job(window.doc_id, "kira-2.5-flash", "English", "Vietnamese", 1)
    batch = store.batches(job)[0]
    store.claim_batch(batch["id"])
    window.table.edit(window.model.index(0, 1))
    app.processEvents()
    editor = window.table.itemDelegate().active_editor
    store.finish_batch(batch["id"], {r["id"]: "API result" for r in batch["payload"]})
    window.refresh([r["id"] for r in batch["payload"]])
    app.processEvents()
    QTest.keyClick(editor, Qt.Key_Escape)
    app.processEvents()
    assert store.line(batch["payload"][0]["id"])["translation"] == "API result"
    window.close()


def test_shift_enter_moves_to_previous_row_without_newline(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app, store, window = workspace(tmp_path)
    window.table.edit(window.model.index(2, 1))
    app.processEvents()
    editor = window.table.itemDelegate().active_editor
    QTest.keyClicks(editor, "saved")
    QTest.keyClick(editor, Qt.Key_Return, Qt.ShiftModifier)
    app.processEvents()
    assert store.lines(window.doc_id)[2]["translation"] == "saved"
    assert window.table.currentIndex().row() == 1
    assert window.table.currentIndex().column() == 1
    assert window.model.rowCount() == 100
    window.close()


def test_font_changes_display_editor_and_restores(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app, store, window = workspace(tmp_path)
    window.table.scrollTo(window.model.index(50, 0), QAbstractItemView.PositionAtTop)
    app.processEvents()
    top = window.table.rowAt(0)
    window.table.edit(window.model.index(top, 1))
    app.processEvents()
    editor = window.table.itemDelegate().active_editor
    window.font_spin.setValue(12)
    app.processEvents()
    small = QFontMetrics(window.table.font()).height()
    assert window.table.font().pixelSize() == editor.font().pixelSize() == 12
    window.font_spin.setValue(22)
    app.processEvents()
    assert window.table.font().pixelSize() == editor.font().pixelSize() == 22
    assert QFontMetrics(window.table.font()).height() > small
    assert window.table.rowAt(0) == top
    window.close()
    reopened = MainWindow(Store(tmp_path / "editor.db"))
    reopened.show()
    app.processEvents()
    assert reopened.font_spin.value() == reopened.table.font().pixelSize() == 22
    reopened.close()


def test_checkboxes_range_header_filter_and_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app, store, window = workspace(tmp_path)
    model, table = window.model, window.table

    def click(row, modifiers=Qt.NoModifier):
        QTest.mouseClick(table.viewport(), Qt.LeftButton, modifiers, table.visualRect(model.index(row, CHECK_COLUMN)).center())

    click(1)
    click(4, Qt.ShiftModifier)
    assert len(model.selected_ids) == 4
    click(2, Qt.ControlModifier)
    assert model.rows[2]["id"] not in model.selected_ids
    model.setData(model.index(1, 1), "Một")
    window.copy_selected("translation")
    assert QApplication.clipboard().text() == "Một\n\n"
    window.copy_selected("pairs")
    assert QApplication.clipboard().text().splitlines()[0] == "Dòng 1\tMột"
    selected_ids = set(model.selected_ids)
    table.scrollToBottom()
    app.processEvents()
    assert model.selected_ids == selected_ids
    window.filter_combo.setCurrentIndex(3)  # Done: only the manually translated row.
    app.processEvents()
    assert model.rowCount() == 1
    window.copy_selected("source")
    assert QApplication.clipboard().text() == "Dòng 1"
    header = table.horizontalHeader()
    from PySide6.QtCore import QPoint
    QTest.mouseClick(header.viewport(), Qt.LeftButton, pos=QPoint(header.sectionViewportPosition(CHECK_COLUMN)+19, header.height()//2))
    assert len(model.selected_rows()) == 0
    assert len(model.selected_ids) == 2  # Hidden rows were not touched.
    model.clear_checked()
    window.filter_combo.setCurrentIndex(0)
    model.select_all_visible()
    assert len(model.selected_ids) == 100
    model.clear_checked()
    assert not model.selected_ids
    window.close()


@pytest.mark.parametrize("key,next_row,next_column", [(Qt.Key_Return, 1, 1), (Qt.Key_Tab, 1, 0), (Qt.Key_Backtab, 0, 0)])
def test_editor_keyboard_navigation(tmp_path, monkeypatch, key, next_row, next_column):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app, store, window = workspace(tmp_path)
    window.table.edit(window.model.index(0, 1))
    app.processEvents()
    editor = window.table.itemDelegate().active_editor
    QTest.keyClicks(editor, "saved")
    QTest.keyClick(editor, key)
    app.processEvents()
    assert store.lines(window.doc_id)[0]["translation"] == "saved"
    assert window.table.currentIndex().row() == next_row
    assert window.table.currentIndex().column() == next_column
    assert window.model.rowCount() == 100
    window.close()
