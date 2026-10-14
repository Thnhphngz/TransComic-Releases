import asyncio
import json
import time
import httpx
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.gemini import GeminiProvider, GeminiKeyPool, QuotaLimiter, KeyUnavailable
from transcomic.ui.main import MainWindow
import transcomic.ui.stage2 as controls


def wait_for(predicate):
    deadline = time.monotonic()+10
    while not predicate():
        QApplication.instance().processEvents(); QTest.qWait(5)
        assert time.monotonic() < deadline


def window_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path/'state.db')
    store.add_gemini_keys('private-ui-key', 'declared-project')
    store.set_setting('gemini_models', json.dumps({'models': [{'name': 'models/mock-text', 'displayName': 'Mock'}]}))
    store.set_setting('gemini_model', 'models/mock-text')
    window = MainWindow(store)
    window.provider_selector.setCurrentIndex(1)
    return app, store, window


def test_cached_models_masked_keys_and_no_implicit_http(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(httpx.AsyncClient, 'send', lambda *a, **k: calls.append(a))
    app, store, window = window_fixture(tmp_path, monkeypatch)
    assert window.selected_model_id() == 'models/mock-text'
    assert 'private-ui-key' not in window.gemini_keys_list.item(0).text()
    window.gemini_key_input.setText('private-extra-key'); window.add_gemini_keys()
    window.provider_selector.setCurrentIndex(0); window.provider_selector.setCurrentIndex(1)
    app.processEvents()
    assert len(store.gemini_keys()) == 2 and not calls
    window.close()


@pytest.mark.parametrize('accepted,status', [(False, 200), (True, 200), (True, 403)])
def test_model_refresh_explicit_one_get_preserves_cache_and_selection(tmp_path, monkeypatch, accepted, status):
    app, store, window = window_fixture(tmp_path, monkeypatch)
    calls = []
    original = GeminiProvider
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={'models': [{'name': 'models/mock-text', 'displayName': 'Updated', 'supportedGenerationMethods': ['generateContent']}]})
    monkeypatch.setattr(controls, 'GeminiProvider', lambda keys, model, **kwargs: original(keys, model, transport=httpx.MockTransport(handle), **kwargs))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Yes if accepted else QMessageBox.No)
    window.refresh_gemini_models()
    wait_for(lambda: not window.metadata_busy)
    assert len(calls) == int(accepted)
    assert all(r.method == 'GET' and r.url.path.endswith('/models') for r in calls)
    assert window.selected_model_id() == 'models/mock-text'
    cache = json.loads(store.setting('gemini_models'))
    assert cache['models'][0]['displayName'] == ('Updated' if accepted and status == 200 else 'Mock')
    window.close()


def test_gui_to_gemini_database_manual_edit_and_frozen_run(tmp_path, monkeypatch):
    app, store, window = window_fixture(tmp_path, monkeypatch)
    source = tmp_path/'chapter.txt'; source.write_text('First\nSecond', encoding='utf-8')
    doc, _ = store.import_document(source, decode_txt(source.read_bytes()), 'Tiếng Việt', 'Tiếng Anh')
    window.open_document(doc)
    window.source_lang.setCurrentText('Tiếng Việt'); window.target_chips['Tiếng Anh'].click()
    for k, v in {'rpm': 100, 'tpm': 100000, 'rpd': 100, 'concurrency': 1}.items(): window.gemini_limit_controls[k].setValue(v)
    window.concurrency.setValue(1); window.gemini_verified.setChecked(True)
    calls = []
    async def handle(request):
        calls.append(request); await asyncio.sleep(.15)
        rows = json.loads(json.loads(request.content)['contents'][0]['parts'][0]['text'])['lines']
        return httpx.Response(200, json={'usageMetadata': None, 'candidates': [{'content': {'parts': [{'text': json.dumps({'lines': [{'id': r['id'], 'text': 'Translated'} for r in reversed(rows)]})}]}}]})
    monkeypatch.setattr(controls, 'GeminiProvider', lambda keys, model, **kwargs: GeminiProvider(keys, model, transport=httpx.MockTransport(handle), **kwargs))
    window.start_translation(); wait_for(lambda: bool(calls))
    window.model.setData(window.model.index(0, 1), 'Manual')
    window.provider_selector.setCurrentIndex(0); window.target_lang.setCurrentText('Tiếng Indonesia'); window.concurrency.setValue(30)
    wait_for(lambda: not window.scheduler._thread.is_alive()); app.processEvents()
    job = store.job(window.scheduler.job_id)
    assert (job['provider'], job['model'], job['target_lang'], job['concurrency']) == ('gemini', 'models/mock-text', 'Tiếng Anh', 1)
    rows = store.lines(doc)
    assert rows[0]['translation'] == 'Manual' and rows[1]['translation'] == 'Translated'
    assert len(calls) == 1 and all(r['state'] == 'done' for r in rows)
    assert store.attempts(store.batches(job['id'])[0]['id'])[0]['state'] != 'prepared'
    window.close()


def test_durable_quota_survives_restart_and_rate_window(tmp_path):
    path = tmp_path/'state.db'; store = Store(path)
    assert store.reserve_gemini_quota('model', 100, 1, 1000, 2, now=1000) == 0
    assert store.reserve_gemini_quota('model', 100, 1, 1000, 2, now=1010) == 50
    store.close(); store = Store(path)
    assert store.reserve_gemini_quota('model', 100, 1, 1000, 2, now=1061) == 0
    with pytest.raises(KeyUnavailable): store.reserve_gemini_quota('model', 100, 1, 1000, 2, now=1122)
    assert store.reserve_gemini_quota('model', 100, 1, 1000, 2, now=87400) == 0
    store.close()


def test_stop_interrupts_waiting_quota_without_another_http():
    async def run():
        limiter = QuotaLimiter(1, 1000, 10)
        await limiter.reserve(100)
        provider = GeminiProvider([{'id': 'key', 'secret': 'secret', 'project': 'p'}], 'mock', limiter=limiter)
        stopped = False
        provider.should_stop = lambda: stopped
        task = asyncio.create_task(limiter.reserve(100))
        await asyncio.sleep(.02); stopped = True
        with pytest.raises(KeyUnavailable): await asyncio.wait_for(task, 1.5)
        assert len(limiter.day) == 1
    asyncio.run(run())


def test_quota_failure_evidence_not_overwritten_by_inflight_success():
    async def run():
        statuses = []
        pool = GeminiKeyPool([{'id': 'key', 'secret': 'secret', 'project': ''}], lambda key, status: statuses.append(status))
        a, b = await pool.acquire(), await pool.acquire()
        await pool.release(a, 'quota_exhausted'); await pool.release(b)
        assert statuses == ['quota_exhausted']
        assert pool.paused_reason == 'quota_exhausted'
    asyncio.run(run())
