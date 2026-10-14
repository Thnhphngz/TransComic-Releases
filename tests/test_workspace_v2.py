import json
import time
import asyncio
import threading
import httpx
import pytest
from PySide6.QtCore import Qt, QMimeData, QUrl, QPoint
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QComboBox, QPushButton
from transcomic.ui.main import MainWindow
from transcomic.ui.documents_panel import local_drop_paths
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.bulk import import_many, discover_files
from transcomic.providers import KiraProvider
from transcomic.translation import Scheduler


def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path/'state.db'); window = MainWindow(store)
    window.resize(1200, 720); window.show(); app.processEvents()
    return app, store, window


def settle():
    QApplication.instance().processEvents(); QTest.qWait(30)


def test_groups_independent_views_selections_and_manual_edit(tmp_path, monkeypatch):
    app, store, w = workspace(tmp_path, monkeypatch)
    base = [store.import_document(tmp_path/f'{i}.txt', decode_txt(('\n'.join(f'Line {n}' for n in range(100))).encode()), 'Tiếng Việt', 'Tiếng Anh')[0] for i in range(2)]
    run, jobs = store.create_run(base, ['Tiếng Anh', 'Tiếng Indonesia'], provider='kira', model='mock', source_lang='Tiếng Việt', concurrency=50)
    w.workspace_ids = [store.job(j)['document_id'] for j in jobs]; w.open_document(base[0]); settle()
    assert w.document_panel.model.rowCount() == 2 and not hasattr(w, 'workspace_combo')
    w.model.set_checked([1], True); w.table.scrollToBottom(); settle()
    position = w.table.verticalScrollBar().value()
    w.model.setData(w.model.index(1, 1), 'Manual EN')
    w.view_language.setCurrentText('Tiếng Indonesia'); settle(); id_doc = w.doc_id
    assert store.document(id_doc)['target_lang'] == 'Tiếng Indonesia'
    assert not w.model.selected_ids and not store.lines(id_doc)[1]['translation']
    w.model.setData(w.model.index(1, 1), 'Manual ID')
    w.open_document_group(w.document_panel.model.items[1]); settle()
    assert store.document(w.doc_id)['target_lang'] == 'Tiếng Indonesia'
    w.open_document(base[0]); settle()
    assert w.table.verticalScrollBar().value() == position
    assert store.lines(base[0])[1]['id'] in w.model.selected_ids
    assert store.lines(base[0])[1]['translation'] == 'Manual EN'
    assert store.lines(id_doc)[1]['translation'] == 'Manual ID'
    assert w.scheduler is None and not store.attempts(store.batches(jobs[0])[0]['id'])
    w.close()


def test_remove_confirmation_workspace_only_and_history_reopen(tmp_path, monkeypatch):
    app, store, w = workspace(tmp_path, monkeypatch)
    doc, _ = store.import_document(tmp_path/'a.txt', decode_txt(b'Source'), 'Tiếng Việt', 'Tiếng Anh')
    job = store.create_job(doc, 'mock', 'Tiếng Việt', 'Tiếng Anh', 1)
    w.open_document(doc); store.edit_line(store.lines(doc)[0]['id'], 'translation', 'Saved')
    instance = store.document(doc)['source_instance']
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.No)
    w.remove_workspace_instances({instance}); assert w.doc_id == doc
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    w.remove_workspace_instances({instance}); settle()
    assert not w.workspace_ids and w.doc_id is None and w.model.rowCount() == 0
    assert store.job(job) and store.lines(doc)[0]['translation'] == 'Saved'
    w.open_document(doc); settle(); assert w.model.rows[0]['translation'] == 'Saved'
    w.close()


def test_120_files_virtual_search_dedup_and_reimport(tmp_path, monkeypatch):
    app, store, w = workspace(tmp_path, monkeypatch)
    folder = tmp_path/'files'; folder.mkdir(); (folder/'empty').mkdir()
    for i in range(120): (folder/f'Chapter {i}.txt').write_text('Source', encoding='utf-8')
    (folder/'bad.docx').write_bytes(b'not a zip'); (folder/'ignore.bin').write_bytes(b'ignored')
    monkeypatch.setattr(QMessageBox, 'information', lambda *a: pytest.fail('Import must not open a popup'))
    w.import_paths([folder, folder/'Chapter 2.txt'])
    deadline = time.monotonic()+15
    while w.import_busy:
        app.processEvents(); QTest.qWait(10)
        # qWait can retain the GIL on Windows; give the I/O worker a Python turn.
        time.sleep(.001)
        assert time.monotonic() < deadline
    assert len(w.workspace_ids) == 120 and w.document_panel.model.rowCount() == 120
    assert w.document_panel.model.items[2]['name'] == 'Chapter 2.txt'
    assert len(w.import_errors) == 3 and w.import_details.isVisible()
    assert not w.document_panel.view.findChildren(QPushButton)
    w.document_panel.search.setText('Chapter 119'); assert w.document_panel.model.rowCount() == 1
    w.document_panel.search.clear(); first = set(w.workspace_ids)
    result = import_many(store, [folder/'Chapter 2.txt'], 'Tiếng Việt', 'Tiếng Anh')
    w.workspace_ids += result['document_ids']; w.refresh_document_panel()
    assert w.document_panel.model.rowCount() == 121 and first.isdisjoint(result['document_ids'])
    w.close()


def test_local_url_filter_and_no_target_validation(tmp_path, monkeypatch):
    app, store, w = workspace(tmp_path, monkeypatch)
    mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(tmp_path/'a.txt')), QUrl('https://example.org/a.txt'), QUrl('file://server/a.txt')])
    assert local_drop_paths(mime) == [str(tmp_path/'a.txt').replace('\\', '/')]
    assert w.source_lang.count() == 11
    for chip in w.target_chips.values(): chip.setChecked(False)
    calls = []; monkeypatch.setattr(QMessageBox, 'information', lambda *a: calls.append(a))
    w.start_translation(); assert calls and w.scheduler is None
    assert not w.target_chips[w.source_lang.currentText()].isEnabled()
    w.close()


def test_kira_saved_limit_provider_switch_and_gemini_cap(tmp_path, monkeypatch):
    app, store, w = workspace(tmp_path, monkeypatch)
    assert w.concurrency.maximum() == 50 and w.concurrency.value() == 30
    w.concurrency.setValue(40); w.provider_selector.setCurrentIndex(1)
    assert w.concurrency.maximum() == 1
    w.provider_selector.setCurrentIndex(0); assert w.concurrency.value() == 40
    assert store.setting('concurrency') == '40'
    w.toggle_theme(); assert store.setting('dark') == '1' and not w.windowIcon().isNull()
    assert [p for _, p in w.navigation_items()] == [0, 5, 1, 2, 4, 3]
    w.close()


@pytest.mark.parametrize('provider,limit', [('kira', 50), ('gemini', 30)])
def test_store_provider_limits(tmp_path, provider, limit):
    store = Store(tmp_path/'state.db'); doc, _ = store.import_document(tmp_path/'a.txt', decode_txt(b'A'))
    with pytest.raises(ValueError): store.create_job(doc, 'mock', 'vi', 'en', limit+1, provider=provider)
    job = store.create_job(doc, 'mock', 'vi', 'en', limit, provider=provider)
    assert store.job(job)['concurrency'] == limit
    store.close()


@pytest.mark.parametrize('concurrency', [1, 10, 30, 40, 50])
def test_stop_preserves_inflight_results_and_leaves_unsent_pending(tmp_path, concurrency):
    store = Store(tmp_path/'state.db')
    doc, _ = store.import_document(tmp_path/'a.txt', decode_txt('\n'.join(f'Line {i}' for i in range(360)).encode()))
    job = store.create_job(doc, 'mock', 'vi', 'en', concurrency)
    gate = threading.Event(); calls = []
    async def handler(req):
        rows = json.loads(json.loads(req.content)['messages'][1]['content'])['lines']; calls.append(rows)
        while not gate.is_set(): await asyncio.sleep(.005)
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'lines': [{'id': r['id'], 'text': 'Translated'} for r in rows]})}}]})
    scheduler = Scheduler(store, KiraProvider('fake', transport=httpx.MockTransport(handler)))
    scheduler.start(job)
    deadline = time.monotonic()+10
    try:
        while len(calls) < concurrency:
            time.sleep(.005); assert time.monotonic() < deadline
        scheduler.stop(); gate.set(); scheduler.join(10)
        assert not scheduler._thread.is_alive() and len(calls) == concurrency
        rows = store.lines(doc)
        assert sum(r['state'] == 'done' for r in rows) == concurrency*3
        assert sum(r['state'] == 'pending' for r in rows) == 360-concurrency*3
        assert store.job(job)['state'] == 'stopped'
    finally:
        gate.set(); scheduler.stop(); scheduler.join(10); store.close()


def test_editor_cursor_and_coalesced_signals(tmp_path, monkeypatch):
    app, store, w = workspace(tmp_path, monkeypatch)
    ids = [store.import_document(tmp_path/f'{i}.txt', decode_txt(b'First\nSecond'), 'vi', 'en')[0] for i in range(2)]
    w.open_document(ids[0]); settle(); w.table.edit(w.model.index(0, 1)); settle()
    editor = w.table.itemDelegate().active_editor; editor.setPlainText('Edited before switch')
    cursor = editor.textCursor(); cursor.setPosition(5); editor.setTextCursor(cursor)
    w.open_document(ids[1]); settle(); w.open_document(ids[0]); settle()
    assert store.lines(ids[0])[0]['translation'] == 'Edited before switch'
    assert w.table.itemDelegate().active_editor.textCursor().position() == 5
    updates = []; monkeypatch.setattr(w, 'refresh', lambda ids=None: updates.append(ids))
    line = store.lines(ids[0])[0]['id']
    for _ in range(50): w.bridge.changed.emit([line])
    QTest.qWait(70)
    assert updates == [[line]]
    w.close()


def test_directory_junction_loop_deduplicates_without_recursion(tmp_path):
    import os
    import subprocess
    folder = tmp_path/'chapters'; folder.mkdir(); (folder/'one.txt').write_text('Source')
    loop = folder/'loop'
    if os.name == 'nt':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(loop), str(folder)], capture_output=True)
        assert result.returncode == 0, result.stderr
    else: loop.symlink_to(folder, target_is_directory=True)
    files, errors = discover_files([folder, folder/'one.txt'])
    assert files == [(folder/'one.txt').resolve()] and not errors


def test_drop_on_main_empty_editor_and_manuscript(tmp_path, monkeypatch):
    app, store, w = workspace(tmp_path, monkeypatch)
    path = tmp_path/'chapter.txt'; path.write_text('Source', encoding='utf-8')
    mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(path))])
    for count, target in enumerate((w, w.editor_page, w.table.viewport()), 1):
        enter = QDragEnterEvent(QPoint(50, 50), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(target, enter); assert enter.isAccepted()
        assert w.filename.text() == 'Thả để thêm tài liệu'
        drop = QDropEvent(QPoint(50, 50), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(target, drop); assert drop.isAccepted()
        deadline = time.monotonic()+10
        while w.import_busy:
            app.processEvents(); QTest.qWait(10); assert time.monotonic() < deadline
        assert len(w.workspace_ids) == 1 and w.scheduler is None
    w.close()
