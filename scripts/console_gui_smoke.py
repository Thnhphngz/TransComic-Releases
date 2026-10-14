"""Run run_transcomic.py natively, using an isolated DB and HTTP mocks only."""
import json
import os
from pathlib import Path
import runpy
try:
    from scripts.test_runtime import TemporaryDirectory
except ModuleNotFoundError:
    from test_runtime import TemporaryDirectory

import httpx
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from transcomic.documents import ImportedText, TextLine
from transcomic.docx_document import import_docx
from transcomic.providers import KiraProvider
from transcomic.ui.main import MainWindow
import transcomic.ui.main as ui
import transcomic.app as application

OUT = Path('artifacts/gui/console')


def exercise(window):
    app = QApplication.instance()
    store = window.store
    assert window.doc_id is None and window.model.rowCount() == 0
    source = Path(r'D:\word 50 cach\7-8.docx')
    imported = import_docx(source)
    def new_import():
        return store.import_document(source, ImportedText(tuple(TextLine(u.text, '') for u in imported.units), 'docx', imported.raw),
                                     'Tiếng Việt', 'Tiếng Anh', document_format='docx', locators=[u.locator for u in imported.units])[0]
    old = new_import()
    store.edit_line(store.lines(old)[25]['id'], 'translation', 'Old import only')
    doc = new_import(); window.open_document(doc)
    assert all(r['translation'] is None for r in window.model.all_rows)
    rows = store.lines(doc)
    for ordinal in (30, 31, 72):
        store.db.execute("UPDATE lines SET state='unknown',error='Offline HTTP 504 fixture' WHERE id=?", (rows[ordinal]['id'],))
    store.edit_line(rows[25]['id'], 'translation', 'Say ah.')
    window.source_lang.setCurrentText('Tiếng Việt'); window.target_lang.setCurrentText('Tiếng Anh')
    window.model_name.setCurrentIndex(window.model_name.findData('glm-5.3-flash'))
    window.concurrency.setValue(3)
    window.refresh(); window.filter_combo.setCurrentIndex(3)
    confirmations = []
    original_question = QMessageBox.question
    QMessageBox.question = lambda *args: confirmations.append(args[2]) or QMessageBox.Yes
    original_provider = ui.KiraProvider
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(504)
        payload = json.loads(json.loads(request.content)['messages'][1]['content'])
        return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'lines': [{'id': r['id'], 'text': 'Mock translation'} for r in payload['lines']]})}}]})
    ui.KiraProvider = lambda key, model, **kwargs: KiraProvider(key, model, transport=httpx.MockTransport(handler), **kwargs)
    window._key = lambda: 'offline-key'
    try:
        window.retry_all_errors()
        while window.scheduler._thread.is_alive():
            app.processEvents(); QTest.qWait(10)
        app.processEvents(); window.refresh()
        assert len(calls) == 2 and window.scheduler.retry_count == 1
        assert all(store.line(rows[o]['id'])['state'] == 'done' for o in (30, 31, 72))
        assert '3 dòng' in confirmations[0] and '1 batch' in confirmations[0]
        window.filter_combo.setCurrentIndex(0)
        window.grab().save(str(OUT/'light-manuscript.png'))
        window.pages.setCurrentIndex(4); window.console.reload(); QTest.qWait(60)
        window.grab().save(str(OUT/'light-console.png'))
        for i in range(150): store.log.emit('headers', http_status=200, model='glm-5.3-flash')
        window.console.reload(); app.processEvents()
        scroll = window.console.listing.verticalScrollBar()
        scroll.setValue(0)
        store.log.emit('failure', http_status=504)
        window.console.reload(); assert scroll.value() == 0
        scroll.setValue(scroll.maximum())
        store.log.emit('failure', http_status=401)
        window.console.reload(); assert scroll.value() == scroll.maximum()
        window.console.copy_report(); assert 'offline-key' not in app.clipboard().text()
        window.toggle_theme(); QTest.qWait(60)
        window.grab().save(str(OUT/'dark-console.png'))
        window.resize(1000, 700); QTest.qWait(60)
        window.grab().save(str(OUT/'dark-console-1000.png'))
        window.pages.setCurrentIndex(1); window.refresh(); QTest.qWait(40)
        window.grab().save(str(OUT/'dark-history.png'))
        for i in range(window.job_list.count()):
            item = window.job_list.item(i)
            if item.data(Qt.UserRole) == 'import:'+old:
                window.job_list.setCurrentRow(i)
        window.delete_history(False)
        assert not any(d['id'] == old for d in store.documents()) and store.document(doc)
        assert source.read_bytes() == imported.raw
        store.log.flush(); store.log.export(OUT/'offline-console-report.json')
        report = {'entry_point': 'python run_transcomic.py', 'qt_platform': app.platformName(), 'dpr': window.devicePixelRatioF(),
                  'units': len(rows), 'new_import_empty': True, 'all_errors_hidden_filter': True, 'mock_http_requests': len(calls),
                  'mock_504_retries': window.scheduler.retry_count, 'history_delete_confirmed': True,
                  'scroll_old_preserved': True, 'scroll_end_followed': True, 'source_unchanged': True, 'paid_requests': 0}
        (OUT/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps(report))
    finally:
        QMessageBox.question = original_question; ui.KiraProvider = original_provider
        window._exit_authorized = True; window.close(); app.quit()


class SmokeWindow(MainWindow):
    def __init__(self, store):
        super().__init__(store)
        def run():
            try:
                exercise(self)
            except Exception:
                import traceback
                traceback.print_exc()
                self._exit_authorized = True
                self.close()
                QApplication.instance().exit(1)
        QTimer.singleShot(100, run)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as temporary:
        previous = os.environ.get('LOCALAPPDATA')
        os.environ['LOCALAPPDATA'] = temporary
        application.MainWindow = SmokeWindow
        try:
            runpy.run_path('run_transcomic.py', run_name='__main__')
        finally:
            if previous is None: os.environ.pop('LOCALAPPDATA', None)
            else: os.environ['LOCALAPPDATA'] = previous


if __name__ == '__main__':
    main()
