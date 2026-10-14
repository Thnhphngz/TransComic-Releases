"""Review the already saved public-line result in native UI, without HTTP."""
import json
from pathlib import Path
import httpx
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from transcomic.storage import Store
from transcomic.ui.main import MainWindow


def main():
    out = Path('artifacts/live_gemini_stage2')
    app = QApplication([])
    # A screenshot/review can never consume another API request.
    async def no_http(*args, **kwargs): raise AssertionError('Result review must be offline')
    httpx.AsyncClient.send = no_http
    store = Store(out/'verification.sqlite3')
    store.set_setting('gemini_models', (out/'models.json').read_text(encoding='utf-8'))
    job = store.jobs()[0]
    store.set_setting('provider', 'gemini'); store.set_setting('gemini_model', job['model'])
    window = MainWindow(store)
    window.open_document(job['document_id'])
    window.source_lang.setCurrentText(job['source_lang']); window.target_lang.setCurrentText(job['target_lang'])
    window.notice.setText('Phép thử thật: 1 GET + 1 POST · HTTP 404 · không retry/đổi key/model · bản dịch chưa được xác minh')
    window.resize(1080, 700); window.show()
    def capture():
        try:
            assert store.lines(job['document_id'])[0]['error'].startswith('Gemini HTTP 404')
            window.grab().save(str(out/'windows-result-404.png'))
            window.pages.setCurrentIndex(4); window.console.reload(); app.processEvents()
            window.grab().save(str(out/'windows-console-404.png'))
            print(json.dumps({'platform': app.platformName(), 'real_result_http': 404, 'review_api_requests': 0}))
        finally:
            window._exit_authorized = True; window.close(); app.quit()
    QTimer.singleShot(200, capture)
    return app.exec()


if __name__ == '__main__': raise SystemExit(main())
