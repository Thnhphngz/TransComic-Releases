import asyncio
import json
import time
import sqlite3
import pytest
import httpx
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget, QVBoxLayout
from PySide6.QtTest import QTest
from transcomic.providers import KiraProvider
from transcomic.translation import Scheduler
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.bulk import import_many
from transcomic.ui.controls import QComboBox, QSpinBox


def setup(tmp_path, **kwargs):
    store = Store(tmp_path/'state.db')
    doc, _ = store.import_document(tmp_path/'file.txt', decode_txt(b'One\nTwo\nThree'))
    job = store.create_job(doc, 'mock', 'VI', 'EN', 1, **kwargs)
    return store, doc, job


def good(req):
    rows = json.loads(json.loads(req.content)['messages'][1]['content'])['lines']
    return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'lines': [{'id': r['id'], 'text': 'Valid translation'} for r in rows]})}}]})


@pytest.mark.parametrize('failures', [1, 2, 5, 6])
@pytest.mark.parametrize('status', [200, 504, 429])
def test_six_attempt_ceiling(tmp_path, failures, status):
    store, doc, job = setup(tmp_path, config={'rate_backoff_base': .01, 'rate_backoff_max': .02, 'rate_recovery_interval': .01})
    calls = []
    def handle(req):
        calls.append(req)
        return httpx.Response(status, json={}) if len(calls)<=failures else good(req)
    s = Scheduler(store, KiraProvider('fake', transport=httpx.MockTransport(handle)))
    s.start(job); s.join(5)
    assert not s._thread.is_alive() and not s._paused.is_set()
    assert len(calls) == min(6, failures+1)
    assert len(store.attempts(store.batches(job)[0]['id'])) == len(calls)
    assert store.prepare_attempt(store.batches(job)[0]['id'], 7) is None
    assert all(r['state']=='done' for r in store.lines(doc)) == (failures<6)
    store.close()


def test_resume_only_missing_finished_attempt_and_no_crash_replay(tmp_path):
    store, doc, job = setup(tmp_path)
    store.job_state(job, 'running'); batch = store.batches(job)[0]; store.claim_batch(batch['id'])
    first = store.prepare_attempt(batch['id'], 1)
    done = batch['payload'][0]['id']
    store.finish_batch(batch['id'], {done: 'Already done'}, 'Partial', diagnostics={'failure_kind': 'partial_response'}, expected_attempt_id=first)
    store.complete_attempt(first, {'failure_kind': 'partial_response'})
    store.job_state(job, 'stopped')
    assert Scheduler.has_work(store, job)
    calls=[]
    def handle(req):
        calls.append(json.loads(json.loads(req.content)['messages'][1]['content'])['lines'])
        return good(req)
    s=Scheduler(store, KiraProvider('fake', transport=httpx.MockTransport(handle))); s.start(job); s.join(3)
    assert len(calls)==1 and len(calls[0])==2 and done not in {r['id'] for r in calls[0]}
    assert store.line(done)['translation']=='Already done'
    assert all(r['state']=='done' for r in store.lines(doc))
    store.close()


@pytest.mark.parametrize('action', ['pause', 'stop'])
def test_user_action_during_cooldown(tmp_path, action):
    store, doc, job=setup(tmp_path)
    calls=[]
    def handle(req):
        calls.append(req)
        return httpx.Response(429, headers={'Retry-After': '.15'}, json={}) if len(calls)==1 else good(req)
    s=Scheduler(store, KiraProvider('fake', transport=httpx.MockTransport(handle))); s.start(job)
    deadline=time.monotonic()+2
    while not s.rate_limits and time.monotonic()<deadline: time.sleep(.005)
    getattr(s, action)(); time.sleep(.25)
    assert len(calls)==1
    if action=='pause':
        assert s._paused.is_set() and store.job(job)['state']=='user_paused'
        s.resume(); s.join(2); assert len(calls)==2
    else:
        s.join(2); assert store.job(job)['state']=='stopped'
    assert not s._thread.is_alive()
    store.close()


def test_unknown_reset_bounded_wait_and_explicit_quota(tmp_path):
    for exhausted in (False, True):
        root=tmp_path/str(exhausted); root.mkdir()
        store, doc, job=setup(root, config={'rate_wait_budget': .01})
        calls=[]
        def handle(req):
            calls.append(req)
            return httpx.Response(429, json={'error': {'code': 'insufficient_quota'}} if exhausted else {})
        s=Scheduler(store, KiraProvider('fake', transport=httpx.MockTransport(handle))); s.start(job); s.join(2)
        assert len(calls)==1 and not s._paused.is_set() and not s._thread.is_alive()
        assert store.job(job)['state']==('quota_exhausted' if exhausted else 'needs_intervention')
        store.close()


def wheel(target, delta=-120):
    app=QApplication.instance() or QApplication([])
    point=QPointF(target.rect().center())
    e=QWheelEvent(point, point, QPoint(), QPoint(0,delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    app.sendEvent(target, e); app.processEvents()


def test_real_wheel_dropdown_popup_keyboard_and_thread_spin():
    app=QApplication.instance() or QApplication([])
    area=QScrollArea(); content=QWidget(); layout=QVBoxLayout(content)
    combo=QComboBox(); combo.addItems([str(i) for i in range(100)]); layout.addWidget(combo)
    content.setMinimumHeight(1500); area.setWidget(content); area.resize(300, 200); area.show(); QTest.qWait(30)
    wheel(combo); assert combo.currentIndex()==0
    assert area.verticalScrollBar().value()>0
    area.verticalScrollBar().setValue(0)
    combo.setFocus(); QTest.keyClick(combo, Qt.Key_Down); assert combo.currentIndex()==1
    combo.showPopup(); QTest.qWait(30); view=combo.view(); before=view.verticalScrollBar().value()
    wheel(view.viewport()); assert view.verticalScrollBar().value()>before and combo.currentIndex()==1
    combo.hidePopup()
    spin=QSpinBox(); spin.setRange(1,50); spin.setValue(30); spin.setProperty('allowWheel',True)
    wheel(spin); assert spin.value()==29
    spin.setProperty('allowWheel',False); wheel(spin); assert spin.value()==29
    area.close(); spin.close()


def test_workspace_path_duplicate_changed_source_remove_reimport(tmp_path):
    store=Store(tmp_path/'state.db'); a=tmp_path/'a'; b=tmp_path/'b'; a.mkdir(); b.mkdir()
    first=a/'same.txt'; second=b/'same.txt'; first.write_text('First'); second.write_text('Second')
    r=import_many(store,[first, first.parent/'..'/'a'/'same.txt'], 'VI','EN'); assert len(r['document_ids'])==1
    old=r['document_ids'][0]; store.edit_line(store.lines(old)[0]['id'],'translation','Manual')
    first.write_text('Changed')
    r=import_many(store,[first, str(first).upper(), second], 'VI','EN', existing_ids=[old])
    assert r['duplicate_ids']==[old] and r['changed_source_ids']==[old] and len(r['document_ids'])==1
    assert store.lines(old)[0]['translation']=='Manual'
    again=import_many(store,[first], 'VI','EN')['document_ids'][0]
    assert again!=old and store.lines(again)[0]['translation'] is None and store.document(old)
    store.close()


@pytest.mark.parametrize('outcome', ['full', 'errors', 'quota'])
def test_notification_once_without_export_or_page_change(tmp_path, monkeypatch, outcome):
    from transcomic.ui.main import MainWindow
    from transcomic.ui.notifications import notify_scheduler
    import winsound
    app=QApplication.instance() or QApplication([])
    store, doc, job=setup(tmp_path)
    w=MainWindow(store); w.open_document(doc)
    w.scheduler=Scheduler(store, KiraProvider('fake')); w.scheduler.job_id=job; w.scheduler.job_ids=[job]
    if outcome=='full':
        for row in store.lines(doc): store.edit_line(row['id'],'translation','Valid')
    store.job_state(job, 'quota_exhausted' if outcome=='quota' else 'finished')
    sound=[]; monkeypatch.setattr(winsound, 'MessageBeep', lambda *args:sound.append(args))
    previous=w.pages.currentIndex()
    notify_scheduler(w); notify_scheduler(w)
    assert len(sound)==1 and w.pages.currentIndex()==previous and w.last_export is None
    assert len([e for e in store.log.snapshot() if e['event']=='notification'])==1
    assert ('3' in w.notice.text()) if outcome!='quota' else 'API' in w.notice.text()
    w._exit_authorized=True; w.close()


def test_attempt_constraint_migration_preserves_trace_foreign_keys(tmp_path):
    store, doc, job=setup(tmp_path)
    store.job_state(job,'running'); batch=store.batches(job)[0]; store.claim_batch(batch['id']); attempt=store.prepare_attempt(batch['id'],1)
    store.finish_batch(batch['id'], {batch['payload'][0]['id']:'Valid'}, 'Partial', diagnostics={'failure_kind':'partial_response'}, expected_attempt_id=attempt)
    store.complete_attempt(attempt, {'failure_kind':'partial_response'}); store.close()
    with sqlite3.connect(tmp_path/'state.db') as db:
        db.execute('PRAGMA writable_schema=ON')
        db.execute("UPDATE sqlite_master SET sql=replace(sql,'BETWEEN 1 AND 6','BETWEEN 1 AND 4') WHERE name='request_attempts'")
        db.execute('PRAGMA writable_schema=OFF')
    store=Store(tmp_path/'state.db')
    assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    assert store.attempts(batch['id'])[0]['id']==attempt
    assert store.db.execute('SELECT COUNT(*) FROM api_text_versions').fetchone()[0]==1
    assert store.job(job)['auto_retries']==5
    assert 'BETWEEN 1 AND 6' in store.db.execute("SELECT sql FROM sqlite_master WHERE name='request_attempts'").fetchone()[0]
    store.close()
