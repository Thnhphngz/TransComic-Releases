import asyncio
import json
import sqlite3
import threading

import httpx
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from transcomic.documents import decode_txt
from transcomic.providers import KiraProvider
from transcomic.storage import Store
from transcomic.translation import Scheduler
from transcomic.ui.main import MainWindow
from test_console_policy import setup, envelope


def test_database_failure_is_not_success_or_retry(tmp_path, monkeypatch):
    store, doc, job = setup(tmp_path)
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('private story must not leak')
    monkeypatch.setattr(store, 'finish_batch', fail)
    calls = []
    scheduler = Scheduler(store, KiraProvider('key', transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, json=envelope(r)))))
    scheduler.start(job); scheduler.join(5)
    assert len(calls) == 1 and store.job(job)['state'] == 'interrupted'
    events = store.log.snapshot()
    assert any(e['event'] == 'database_error' and e['exception'] == 'OperationalError' for e in events)
    assert not any(e['event'] == 'saved' for e in events)
    assert 'private story' not in json.dumps(events)
    assert all(r['translation'] is None for r in store.lines(doc))
    store.close()


def test_http_trace_parse_commit_gui_order_and_timings(tmp_path):
    store, doc, job = setup(tmp_path)
    scheduler = None
    def update(ids):
        if scheduler:
            scheduler.acknowledge(ids, doc)
    scheduler = Scheduler(store, KiraProvider('key', transport=httpx.MockTransport(lambda r: httpx.Response(200, headers={'x-request-id': 'trace-id'}, json=envelope(r)))), update)
    scheduler.start(job); scheduler.join(5)
    events = store.log.snapshot()
    stages = [e['event'] for e in events]
    wanted = ['queued', 'selected', 'persisted', 'http_started', 'headers', 'body_received', 'parsed', 'saved', 'gui_emitted', 'gui_received']
    assert [stages.index(s) for s in wanted] == sorted(stages.index(s) for s in wanted)
    assert next(e for e in events if e['event'] == 'parsed')['correlation_id'] == 'trace-id'
    for field, stage in [('queue_wait_seconds', 'selected'), ('http_seconds', 'body_received'), ('parse_seconds', 'parsed'), ('database_seconds', 'saved'), ('gui_seconds', 'gui_received')]:
        assert next(e for e in events if e['event'] == stage)[field] >= 0
    assert not any(e['event'] == 'body_sent' for e in events)  # Mock transport cannot observe real socket sends.
    store.close()


def test_response_other_import_is_saved_only_to_original(tmp_path):
    store, original, job = setup(tmp_path)
    current, _ = store.import_document(tmp_path/'source.txt', decode_txt(b'Line 0\nLine 1\nLine 2'))
    scheduler = None
    def update(ids):
        if scheduler: scheduler.acknowledge(ids, current)
    scheduler = Scheduler(store, KiraProvider('key', transport=httpx.MockTransport(lambda r: httpx.Response(200, json=envelope(r)))), update)
    scheduler.start(job); scheduler.join(5)
    assert all(r['translation'] == 'Translation' for r in store.lines(original))
    assert all(r['translation'] is None for r in store.lines(current))
    assert any(e['event'] == 'gui_received' and e['reason'] == 'other_import_not_displayed' and e['document_id'] == original for e in store.log.snapshot())
    store.close()


def test_stop_after_reservation_sends_nothing(tmp_path):
    store, doc, job = setup(tmp_path)
    calls = []
    scheduler = None
    def update(ids):
        if ids and store.attempts(store.batches(job)[0]['id']): scheduler.stop()
    scheduler = Scheduler(store, KiraProvider('key', transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(504))), update)
    scheduler.start(job); scheduler.join(5)
    assert not calls and scheduler.retry_count == 0
    assert store.attempts(store.batches(job)[0]['id'])[0]['diagnostics']['failure_kind'] == 'not_sent'
    assert store.job(job)['state'] == 'stopped'
    store.close()


def test_pause_before_reservation_retains_pending_then_resumes(tmp_path):
    store, doc, job = setup(tmp_path)
    calls, paused = [], threading.Event()
    scheduler = None
    first = True
    def update(ids):
        nonlocal first
        if ids and first:
            first = False; scheduler.pause(); paused.set()
    scheduler = Scheduler(store, KiraProvider('key', transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200, json=envelope(r)))), update)
    scheduler.start(job)
    assert paused.wait(3)
    scheduler.resume(); scheduler.join(5)
    assert len(calls) == 1 and all(r['state'] == 'done' for r in store.lines(doc))
    store.close()


def test_missing_gui_receipt_is_observed_without_claiming_server_execution(tmp_path):
    store, doc, job = setup(tmp_path)
    scheduler = Scheduler(store, KiraProvider('key', transport=httpx.MockTransport(lambda r: httpx.Response(200, json=envelope(r)))))
    scheduler.start(job); scheduler.join(5)
    events = store.log.snapshot()
    assert any(e['event'] == 'gui_missing' for e in events)
    assert not any(e['event'] == 'gui_received' for e in events)
    assert next(e for e in events if e['event'] == 'http_started')['server_execution_known'] is False
    store.close()


def test_actual_live_failure_shape_with_reported_overcap_is_rejected_offline(tmp_path):
    events = []
    provider = KiraProvider('key', 'glm-5.3-flash', max_tokens=512, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={
        'choices': [{'message': {'content': '{"lines":['}, 'finish_reason': 'length'}],
        'usage': {'prompt_tokens': 413, 'completion_tokens': 564, 'total_tokens': 977, 'completion_tokens_details': {'reasoning_tokens': 500}}})))
    result = asyncio.run(provider.translate([{'id': 'target', 'source': 'Data'}], 'Vietnamese', 'English', observer=lambda event, **meta: events.append((event, meta))))
    assert result.diagnostics['http_status'] == 200 and result.error == 'Model response is not JSON'
    assert not result.values and result.usage['completion_tokens'] == 564
    assert result.diagnostics['finish_reason'] == 'length' and result.diagnostics['reasoning_tokens'] == 500
    assert result.diagnostics['content_json_start'] and not result.diagnostics['content_json_end']
    assert not result.unknown


def test_gui_refresh_failure_is_logged_not_silently_lost(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    store, doc, job = setup(tmp_path)
    window = MainWindow(store); window.open_document(doc)
    def broken(ids): raise sqlite3.OperationalError('private text')
    monkeypatch.setattr(window.model, 'refresh', broken)
    window.refresh([store.lines(doc)[0]['id']])
    assert any(e['event'] == 'gui_error' and e['state'] == 'refresh_failed' for e in store.log.snapshot())
    assert 'private text' not in json.dumps(store.log.snapshot())
    window._exit_authorized = True; window.close()


def test_delete_completed_scheduler_job_with_shared_document_ui(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    store, doc, first = setup(tmp_path)
    store.job_state(first, 'finished')
    second = store.create_job(doc, 'glm-5.3-flash', 'Vietnamese', 'English', 1)
    window = MainWindow(store); window.open_document(doc)
    window.scheduler = Scheduler(store, KiraProvider('offline'))
    window.scheduler.job_id = first
    window.pages.setCurrentIndex(1); window.refresh()
    for i in range(window.job_list.count()):
        if window.job_list.item(i).data(Qt.UserRole) == first: window.job_list.setCurrentRow(i)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    window.delete_history(False)
    assert window.scheduler is None and window.doc_id == doc and store.job(second)
    assert not any(e['event'] == 'gui_error' for e in store.log.snapshot())
    window._exit_authorized = True; window.close()
