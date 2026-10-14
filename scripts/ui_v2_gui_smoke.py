"""Native Windows V2 smoke through the Python entry point. Isolated DB, mock HTTP."""
import asyncio
import json
import os
import runpy
import time
from pathlib import Path
try:
    from scripts.test_runtime import TemporaryDirectory
except ModuleNotFoundError:
    from test_runtime import TemporaryDirectory
import httpx
from docx import Document
from PySide6.QtCore import QTimer, QMimeData, QUrl, Qt, QPoint
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from transcomic.providers import KiraProvider
from transcomic.ui.main import MainWindow
from transcomic.ui.exit_dialog import ExitDialog
from transcomic.bulk import plan_exports, write_exports
import transcomic.ui.stage2 as controls
import transcomic.app as application

OUT = Path('artifacts/gui/v2')/os.environ.get('V2_DPI', '125')


def wait_until(predicate, timeout=30):
    deadline = time.monotonic()+timeout
    while not predicate():
        QApplication.instance().processEvents(); QTest.qWait(10)
        assert time.monotonic() < deadline, 'Native GUI deadline'


def exercise(w):
    app, store = QApplication.instance(), w.store
    assert app.platformName() == 'windows' and w.doc_id is None and not w.scheduler
    calls = []; active = peak = 0; heartbeat = []
    timer = QTimer(w); timer.setInterval(20); timer.timeout.connect(lambda: heartbeat.append(time.monotonic())); timer.start()
    async def handler(req):
        nonlocal active, peak
        calls.append(req); active += 1; peak = max(peak, active)
        await asyncio.sleep(.22); active -= 1
        messages = json.loads(req.content)['messages']; payload = json.loads(messages[1]['content'])
        tag = 'ID' if 'to Tiếng Indonesia' in messages[0]['content'] else 'EN'
        text = json.dumps({'lines': [{'id': r['id'], 'text': tag+' '+r['text']} for r in reversed(payload['lines'])]})
        return httpx.Response(200, json={'choices': [{'message': {'content': text}}]})
    original = controls.KiraProvider
    original_question = QMessageBox.question
    controls.KiraProvider = lambda key, model, **kw: KiraProvider(key, model, transport=httpx.MockTransport(handler), **kw)
    QMessageBox.question = lambda *a: QMessageBox.Yes
    try:
        folder = store.path.parent/'input'; folder.mkdir(); (folder/'nested').mkdir()
        for n in (1, 2, 3): (folder/f'Chapter {n}.txt').write_text('\n'.join(f'File {n} line {i}' for i in range(90)), encoding='utf-8')
        for n in (4, 5):
            doc = Document()
            for i in range(90): doc.add_paragraph(f'Word {n} line {i}')
            doc.save(folder/'nested'/f'Chapter {n}.docx')
        source_bytes = {str(p): p.read_bytes() for p in folder.rglob('*') if p.is_file()}
        mime = QMimeData(); mime.setUrls([QUrl.fromLocalFile(str(folder)), QUrl.fromLocalFile(str(folder/'Chapter 2.txt'))])
        enter = QDragEnterEvent(QPoint(100, 250), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(w.document_panel.view.viewport(), enter); assert enter.isAccepted()
        assert w.document_panel.drop_hint.text() == 'Thả để thêm tài liệu'
        drop = QDropEvent(QPoint(100, 250), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(w.document_panel.view.viewport(), drop); assert drop.isAccepted()
        wait_until(lambda: not w.import_busy)
        assert len(w.workspace_ids) == 5 and w.document_panel.model.rowCount() == 5 and not calls
        # Fake credential stays in the isolated database; no network client is used.
        from transcomic.security import protect_key
        store.save_key(protect_key('smoke-key'))
        w.source_lang.setCurrentText('Tiếng Việt'); w.target_chips['Tiếng Anh'].setChecked(True)
        w.target_chips['Tiếng Indonesia'].setChecked(True); w.concurrency.setValue(50)
        w.start_translation(); wait_until(lambda: len(calls) >= 50)
        assert peak == 50
        w.pause_or_resume(); wait_until(lambda: w.scheduler.active == 0)
        assert w.scheduler._paused.is_set()
        first = w.doc_id; w.model.setData(w.model.index(0, 1), 'Manual survives switching')
        w.view_language.setCurrentText('Tiếng Indonesia'); second = w.doc_id
        w.open_document_group(w.document_panel.model.items[1]); assert store.document(w.doc_id)['target_lang'] == 'Tiếng Indonesia'
        w.open_document(first); assert store.lines(first)[0]['translation'] == 'Manual survives switching'
        all_workspaces = list(w.workspace_ids)
        hidden_doc = all_workspaces[4]
        hidden_instance = store.document(hidden_doc)['source_instance']
        w.remove_workspace_instances({hidden_instance})
        assert len(w.workspace_ids) == 8 and w.scheduler._paused.is_set()
        w.document_splitter.setSizes([280, 800]); w.toggle_documents_panel(); assert w.document_panel.isHidden()
        w.toggle_documents_panel(); assert not w.document_panel.isHidden()
        before = len(calls); w.pause_or_resume(); wait_until(lambda: not w.scheduler._thread.is_alive())
        assert len(w.workspace_ids) == 8 and len(calls) == 300 and len(calls) > before
        assert peak <= 50 and len(heartbeat) > 10
        for d in all_workspaces:
            tag = 'ID' if store.document(d)['target_lang'] == 'Tiếng Indonesia' else 'EN'
            assert all(r['translation'].startswith(tag) or r['translation'] == 'Manual survives switching' for r in store.lines(d))
        exports = write_exports(store, plan_exports(store.export_snapshot(w.workspace_ids), store.path.parent/'export'))
        assert len(exports) == 8 and all(e['state'] == 'exported' for e in exports)
        assert all(Path(p).read_bytes() == b for p, b in source_bytes.items())
        sizing = []
        w.showNormal()
        for dark in (False, True):
            if w.dark != dark: w.toggle_theme()
            for width, height in ((1200, 720), (900, 580)):
                w.resize(width, height); QTest.qWait(100); w.adapt_v2_toolbar(); QTest.qWait(30)
                print('Requested/actual:', [width, height], [w.width(), w.height()])
                w.grab().save(str(OUT/f'{"dark" if dark else "light"}-{width}.png'))
                print('Geometry:', width, height, w.editor_page.width(), w.table.viewport().size(), w.minimumSizeHint())
                assert w.width() == width
                assert w.height() == height or (height == 720 and 680 <= w.height() < height)
                assert w.table.viewport().height() >= 110
                assert w.table.viewport().width() >= 420
                sizing.append({'dark': dark, 'requested': [width, height], 'window': [w.width(), w.height()], 'table': [w.table.viewport().width(), w.table.viewport().height()]})
                w.grab().save(str(OUT/f'{"dark" if dark else "light"}-{width}.png'))
        w.showMaximized(); QTest.qWait(100); w.grab().save(str(OUT/'maximized.png'))
        for index, name in ((5, 'queue'), (1, 'history'), (2, 'api'), (4, 'console'), (3, 'settings')):
            w.pages.setCurrentIndex(index); w.refresh(); QTest.qWait(60); w.grab().save(str(OUT/f'{name}.png'))
        dialog = ExitDialog(w, running=True, tray_available=False); dialog.show(); QTest.qWait(50)
        dialog.grab().save(str(OUT/'exit-dialog.png')); dialog.close()
        w.pages.setCurrentIndex(0)
        store.set_setting('last_import_dir', str(folder))
        def cancel_import_dialog():
            modal = app.activeModalWidget()
            assert modal is not None
            modal.grab().save(str(OUT/'import-dialog.png')); modal.reject()
        QTimer.singleShot(150, cancel_import_dialog)
        w.choose_files()
        instance = store.document(first)['source_instance']; w.remove_workspace_instances({instance})
        assert len(w.workspace_ids) == 6 and store.document(first) and store.document(second)
        report = {'platform': app.platformName(), 'device_pixel_ratio': w.devicePixelRatioF(),
                  'imports': 5, 'workspaces': 10, 'mock_requests': len(calls), 'peak': peak, 'exports': len(exports),
                  'real_api_requests': 0, 'heartbeat_ticks': len(heartbeat), 'view_switch': True,
                  'manual_preserved': True, 'source_unchanged': True, 'workspace_remove_preserves_db': True, 'sizes': sizing}
        report['hidden_job_completed'] = True
        (OUT/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8'); print(json.dumps(report))
    finally:
        controls.KiraProvider = original; QMessageBox.question = original_question
        if w.scheduler: w.scheduler.stop(); w.scheduler.join(5)
        w._exit_authorized = True; w.close(); app.quit()


class SmokeWindow(MainWindow):
    def __init__(self, store):
        super().__init__(store)
        def run():
            try: exercise(self)
            except Exception:
                import traceback
                traceback.print_exc(); self._exit_authorized = True; self.close(); QApplication.instance().exit(1)
        QTimer.singleShot(200, run)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as temporary:
        previous = os.environ.get('LOCALAPPDATA'); os.environ['LOCALAPPDATA'] = temporary
        application.MainWindow = SmokeWindow
        try: runpy.run_path('run_transcomic.py', run_name='__main__')
        finally:
            if previous is None: os.environ.pop('LOCALAPPDATA', None)
            else: os.environ['LOCALAPPDATA'] = previous


if __name__ == '__main__': main()
