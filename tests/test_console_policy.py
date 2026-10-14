import asyncio
import json
from pathlib import Path

import httpx
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from transcomic.diagnostics import DiagnosticLog
from transcomic.documents import decode_txt, render_export, ImportedText, TextLine
from transcomic.docx_document import import_docx
from transcomic.providers import KiraProvider
from transcomic.storage import Store
from transcomic.status import usable, matches_filter
from transcomic.translation import Scheduler
from transcomic.ui.main import MainWindow


def setup(tmp_path, count=3, **options):
    store = Store(tmp_path/'state.db')
    store.set_setting('auto_retries', str(options.pop('retries', 1)))  # Frozen run budget.
    doc, _ = store.import_document(tmp_path/'source.txt', decode_txt('\n'.join(f'Line {i}' for i in range(count)).encode()))
    job = store.create_job(doc, 'glm-5.3-flash', 'Vietnamese', 'English', options.pop('concurrency', 1), **options)
    return store, doc, job


def envelope(request):
    data = json.loads(json.loads(request.content)['messages'][1]['content'])
    return {'choices': [{'message': {'content': json.dumps({'lines': [{'id': r['id'], 'text': 'Translation'} for r in data['lines']]})}}], 'usage': {'prompt_tokens': 12, 'completion_tokens': 15, 'total_tokens': 27}}


@pytest.mark.parametrize('second', [200, 504])
def test_actual_504_exactly_one_retry_persisted(tmp_path, second):
    store, doc, job = setup(tmp_path)
    calls = []
    def handler(request):
        batch = store.batches(job)[0]
        attempts = store.attempts(batch['id'])
        assert attempts[-1]['state'] == 'prepared'
        calls.append(attempts[-1]['id'])
        status = 504 if len(calls) == 1 else second
        return httpx.Response(status, json=envelope(request) if status == 200 else {'error': 'private secret story'})
    scheduler = Scheduler(store, KiraProvider('secret-key', transport=httpx.MockTransport(handler)))
    scheduler.start(job); scheduler.join(5)
    assert len(calls) == len(set(calls)) == 2
    assert scheduler.retry_count == 1
    assert [a['attempt_number'] for a in store.attempts(store.batches(job)[0]['id'])] == [1, 2]
    assert all(r['state'] == ('done' if second == 200 else 'unknown') for r in store.lines(doc))
    report = json.dumps(store.log.snapshot())
    assert 'secret-key' not in report and 'private secret story' not in report
    store.close()


@pytest.mark.parametrize('kind', [401, 403, 429, 500, 200, 'timeout', 'network'])
def test_no_retry_for_non504(tmp_path, kind):
    store, doc, job = setup(tmp_path, retries=0)
    calls = []
    def handler(request):
        calls.append(request)
        if kind == 'timeout':
            raise httpx.ReadTimeout('private secret', request=request)
        if kind == 'network':
            raise httpx.ConnectError('private secret', request=request)
        return httpx.Response(kind, json={'choices': [{'message': {'content': 'invalid JSON'}}]})
    scheduler = Scheduler(store, KiraProvider('key', transport=httpx.MockTransport(handler)))
    scheduler.start(job); scheduler.join(5)
    assert len(calls) == 1 and scheduler.retry_count == 0
    assert 'private secret' not in json.dumps(store.log.snapshot())
    assert len(store.attempts(store.batches(job)[0]['id'])) == 1
    if kind == 200:
        assert any(e['event'] == 'parsed' and e['state'] == 'invalid' for e in store.log.snapshot())
    store.close()


@pytest.mark.parametrize('options', [{'retry_504': False}, {'max_requests': 1}])
def test_retry_policy_and_request_budget(tmp_path, options):
    store, doc, job = setup(tmp_path, **options)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(504)
    scheduler = Scheduler(store, KiraProvider('key', transport=httpx.MockTransport(handler)))
    scheduler.start(job); scheduler.join(5)
    assert len(calls) == 1 and scheduler.retry_count == 0
    assert all(r['state'] == 'unknown' for r in store.lines(doc))
    store.close()


@pytest.mark.parametrize('concurrency', [1, 3, 10, 30, 40, 50])
def test_retry_workers_stay_parallel_and_bounded(tmp_path, concurrency):
    store, doc, job = setup(tmp_path, count=150, concurrency=concurrency)
    active = peak = 0
    calls = {}
    async def handler(request):
        nonlocal active, peak
        ids = tuple(r['id'] for r in json.loads(json.loads(request.content)['messages'][1]['content'])['lines'])
        calls[ids] = calls.get(ids, 0)+1
        active += 1; peak = max(peak, active)
        await asyncio.sleep(.015)
        active -= 1
        return httpx.Response(504 if calls[ids] == 1 else 200, json=envelope(request))
    scheduler = Scheduler(store, KiraProvider('key', transport=httpx.MockTransport(handler)))
    scheduler.start(job); scheduler.join(10)
    assert peak == concurrency and len(calls) == 50 and set(calls.values()) == {2}
    assert sum(usable(r) for r in store.lines(doc)) == 150
    assert scheduler.retry_count == 50
    store.close()


def reserve_retry(store, job):
    store.job_state(job, 'running')
    batch = store.batches(job)[0]
    store.claim_batch(batch['id'])
    first = store.prepare_attempt(batch['id'], 1)
    store.finish_batch(batch['id'], {}, 'HTTP 504', True, {'http_status': 504}, expected_attempt_id=first)
    store.complete_attempt(first, {'http_status': 504})
    return batch, first


def test_crash_attempt2_no_replay_and_late_attempt1_rejected(tmp_path):
    store, doc, job = setup(tmp_path)
    batch, first = reserve_retry(store, job)
    second = store.prepare_attempt(batch['id'], 2)
    values = {r['id']: 'Late first' for r in batch['payload']}
    assert store.finish_batch(batch['id'], values, expected_attempt_id=first) == []
    assert all(r['translation'] is None for r in store.lines(doc))
    store.close()
    store = Store(tmp_path/'state.db')
    store.set_setting('auto_retries', '0')  # Legacy policy cases; new retry policy has separate tests.
    assert store.attempts(batch['id'])[-1]['state'] == 'unknown'
    assert store.prepare_attempt(batch['id'], 2) is None
    calls = []
    scheduler = Scheduler(store, KiraProvider('key', transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(504))))
    scheduler.start(job); scheduler.join(5)
    assert not calls and len(store.attempts(batch['id'])) == 2
    store.close()


def test_manual_edits_during_retry_win(tmp_path):
    store, doc, job = setup(tmp_path)
    batch, first = reserve_retry(store, job)
    row = store.lines(doc)[0]
    store.edit_line(row['id'], 'translation', 'Manual')
    second = store.prepare_attempt(batch['id'], 2)
    payload = store.batches(job)[0]['payload']
    assert row['id'] not in {r['id'] for r in payload}
    other = payload[0]
    store.edit_line(other['id'], 'source', 'Changed source')
    store.finish_batch(batch['id'], {r['id']: 'API' for r in payload}, expected_attempt_id=second)
    assert store.line(row['id'])['translation'] == 'Manual'
    assert store.line(other['id'])['translation'] is None
    store.close()


@pytest.mark.parametrize('state', ['pending', 'processing', 'error', 'unknown', 'stale'])
def test_untranslated_state_and_old_valid_export(tmp_path, state):
    store, doc, job = setup(tmp_path)
    row = store.lines(doc)[0]
    store.db.execute('UPDATE lines SET state=? WHERE id=?', (state, row['id']))
    assert matches_filter(store.line(row['id']), 'untranslated')
    store.edit_line(row['id'], 'translation', 'Old valid')
    store.db.execute('UPDATE lines SET state=? WHERE id=?', (state, row['id']))
    assert usable(store.line(row['id']))
    assert not matches_filter(store.line(row['id']), 'untranslated')
    assert b'Old valid' in render_export(store.lines(doc))[0]
    store.edit_line(row['id'], 'source', 'New source')
    assert matches_filter(store.line(row['id']), 'untranslated')
    store.close()


def test_history_transaction_references_files_keys_and_independent_imports(tmp_path):
    store, doc, first = setup(tmp_path)
    source = tmp_path/'source.txt'; source.write_text('Original')
    exported = tmp_path/'export.txt'; exported.write_text('Export')
    store.save_key(b'encrypted')
    store.set_setting('theme', 'light')
    row = store.lines(doc)[0]
    store.edit_line(row['id'], 'translation', 'Keep')
    store.job_state(first, 'finished')
    second = store.create_job(doc, 'glm-5.3-flash', 'Vietnamese', 'English', 1, line_ids=[row['id']])
    other, _ = store.import_document(source, decode_txt(b'Original'))
    store.job_state(second, 'running')
    with pytest.raises(ValueError): store.delete_history([first, second])
    assert store.job(first) and store.job(second)
    store.job_state(second, 'stopped')
    store.delete_history([first])
    assert store.document(doc) and store.line(row['id'])['translation'] == 'Keep'
    store.delete_history([second])
    assert not any(d['id'] == doc for d in store.documents())
    assert store.document(other) and store.lines(other)[0]['translation'] is None
    assert source.read_text() == 'Original' and exported.read_text() == 'Export'
    assert store.load_key() == b'encrypted' and store.setting('theme') == 'light'
    assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    store.close()


def test_log_rotation_restart_privacy_and_bounded_memory(tmp_path):
    log = DiagnosticLog(tmp_path/'logs', max_bytes=1000, backups=2, max_events=10)
    log.register_secret('secret-value')
    for i in range(80): log.emit('failure', exception='secret-value', reason='fixed_code', raw_response='private story', Authorization='secret-value')
    log.flush()
    assert len(log.snapshot()) == 10
    assert len(list((tmp_path/'logs').glob('*.jsonl'))) <= 3
    log.export(tmp_path/'report.txt')
    for file in list((tmp_path/'logs').glob('*.jsonl'))+[tmp_path/'report.txt']:
        text = file.read_text(encoding='utf-8')
        assert 'secret-value' not in text and 'private story' not in text and 'Authorization' not in text
    log.close()
    log = DiagnosticLog(tmp_path/'logs', max_bytes=1000, backups=2, max_events=10)
    assert log.snapshot()
    log.clear(); assert not log.snapshot()
    log.close()


def test_console_filters_copy_clear_and_new_events(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    store, doc, job = setup(tmp_path)
    window = MainWindow(store)
    console = window.console
    store.log.emit('failure', model='glm-5.3-flash', provider='kira', job_id=job, http_status=504)
    store.log.emit('saved', model='other', job_id='other')
    console.job.setText(job); console.reload()
    assert console.rows and all(r.get('job_id') == job for r in console.rows)
    console.level.setCurrentText('ERROR')
    assert len(console.rows) == 1
    console.copy_report(); assert '504' in app.clipboard().text()
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.No)
    console.clear_view(); assert len(console.rows) == 1
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    console.clear_view(); assert not console.rows
    from PySide6.QtTest import QTest
    QTest.qWait(3)
    store.log.emit('failure', model='glm-5.3-flash', provider='kira', job_id=job, http_status=401)
    console.reload(); assert len(console.rows) == 1 and console.rows[0]['http_status'] == 401
    console.clear_saved(); assert not store.log.snapshot() and store.document(doc)
    window._exit_authorized = True; window.close()


def test_three_docx_import_instances_original_unchanged(tmp_path):
    source = Path(r'D:\word 50 cach\7-8.docx')
    if not source.exists(): pytest.skip('User DOCX unavailable')
    data = import_docx(source)
    store = Store(tmp_path/'docx.db')
    docs = [store.import_document(source, ImportedText(tuple(TextLine(u.text, '') for u in data.units), 'docx', data.raw), document_format='docx', locators=[u.locator for u in data.units])[0] for _ in range(3)]
    assert len(set(docs)) == 3 and all(len(store.units(d)) == 125 for d in docs)
    store.edit_line(store.lines(docs[0])[0]['id'], 'translation', 'Only first')
    assert all(r['translation'] is None for d in docs[1:] for r in store.lines(d))
    store.delete_history(['import:'+docs[1]])
    assert store.document(docs[0]) and store.document(docs[2])
    assert source.read_bytes() == data.raw
    store.close()
