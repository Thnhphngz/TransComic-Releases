"""Fresh sessions, cancellation and preservation on isolated SQLite/media only."""
import asyncio
import json
from pathlib import Path
import threading
import time
import uuid
from types import SimpleNamespace

import httpx
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from transcomic.automation.repository import Repository, file_hash
from transcomic.automation.session import Cleanup
from transcomic.automation.validation import defaults
from transcomic.storage import Store
from transcomic.tts.storage import TtsStore
from transcomic.ui.main import MainWindow
from transcomic.ui.exit_dialog import AutomationExitDialog
from transcomic.translation import Scheduler
from test_automation import setup, add_group, run, FakeEngine
from test_automation_ui import gui, wait
from test_draft_history_lifecycle import lifecycle

REAL_CONFIRM_EXIT=MainWindow.confirm_exit


def clean(repo):
    cleanup=repo.discard_session();cleanup.thread.join(5)
    assert cleanup.done.is_set() and cleanup.error is None
    return cleanup


@pytest.mark.parametrize('count',[1,10,100])
def test_startup_scope_does_not_read_old_groups_and_cleans_in_background(tmp_path,count):
    store=Store(tmp_path/'state.sqlite3');tts=TtsStore(tmp_path/'tts.sqlite3')
    try:
        old=Repository(store);old.tts_store=tts
        path=tmp_path/'source.txt';path.write_text('A source line',encoding='utf8')
        for i in range(count):
            wid=old.create(str(i),defaults(store));old.add(wid,[path])
        old.execute('UPDATE automation_sessions SET owner_pid=-1,owner_started=0 WHERE id=?',(old.session_id,))
        queries=[];store.db.set_trace_callback(queries.append)
        fresh=Repository(store);fresh.tts_store=tts
        assert fresh.session_id!=old.session_id and fresh.worksets()==[] and fresh.active() is None
        assert not any('SELECT' in q.upper() and 'automation_groups' in q for q in queries)
        store.db.set_trace_callback(None)
        cleanup=fresh.start_stale_cleanup();cleanup.thread.join(6)
        assert cleanup.error is None and cleanup.worksets==count
        assert fresh.rows('SELECT * FROM automation_worksets')==[]
        assert len(store.documents())==count and path.read_text()=='A source line'
        assert not store.jobs()
        assert not fresh.rows('PRAGMA foreign_key_check')
    finally:tts.close();store.close()


def test_completed_audit_audio_projects_keys_settings_and_qa_survive(setup,tmp_path):
    repo,wid,s,c=setup;gid,source,images=add_group(repo,wid,tmp_path/'input',count=2)
    repo.store.set_setting('glossary','permanent-glossary')
    repo.store.set_setting('character_profile','permanent-profile')
    run(c,wid)
    meta=repo.group(gid)['data'];tts_run=meta['tts_run']
    before={str(p):file_hash(p) for p in tmp_path.rglob('*') if p.is_file() and p.suffix in ('.wav','.png','.txt','.json')}
    keys=repo.store.kira_keys();jobs=repo.store.jobs();lines=repo.store.lines(repo.group(gid)['document_id'])
    audit={table:repo.rows('SELECT * FROM '+table) for table in ('quality_warnings','api_text_versions','line_edits','request_attempts')}
    clean(repo)
    assert repo.worksets()==[] and len(repo.completed_history())==1
    history=json.loads(repo.completed_history()[0]['summary'])
    assert history['groups'][0]['id']==gid and history['artifacts']
    assert s.tts_store.run(tts_run)['state']=='completed'
    assert all(i['state']=='success' for i in s.tts_store.items(tts_run))
    assert {p:file_hash(p) for p in before}==before
    assert repo.store.kira_keys()==keys and repo.store.lines(repo.store.documents()[0]['id'])==lines
    assert len(repo.store.jobs())==len(jobs) and repo.store.history()
    assert all(repo.rows('SELECT * FROM '+table)==rows for table,rows in audit.items())
    assert repo.store.setting('glossary')=='permanent-glossary'
    assert repo.store.setting('character_profile')=='permanent-profile'
    assert not repo.rows('SELECT * FROM automation_groups')


def test_discard_removes_assignment_but_keeps_translation_and_tts_history(setup,tmp_path):
    repo,wid,s,c=setup;gid,_,_=add_group(repo,wid,tmp_path/'input',count=2)
    repo.activate(wid)
    job=repo.store.create_job(repo.group(gid)['document_id'],'mock','VI','EN',1,config={'automation_owner':wid})
    tts_run='session-test-run';s.tts_store.execute('INSERT INTO runs(id,created,state,history_accepted) VALUES (?,?,?,1)',(tts_run,time.time(),'draft'))
    doc=s.tts_store.add_document(tts_run,dict(name='Synthetic',path=None,text='One\nTwo',line_count=2),'lines')
    repo.update_group(gid,tts_run=tts_run)
    clean(repo)
    assert repo.store.job(job)['state']=='cancelled'
    assert not Scheduler.has_work(repo.store,job)
    with pytest.raises(ValueError,match='Tự động hóa'):
        Scheduler(repo.store,SimpleNamespace()).start(job)
    assert s.tts_store.run(tts_run)['state']=='cancelled'
    assert all(i['state']=='cancelled' for i in s.tts_store.items(tts_run))
    assert s.tts_store.doc(doc) is not None
    assert repo.store.documents() and repo.store.history()


def test_cleanup_is_retryable_and_never_deletes_unregistered_or_linked_files(setup,tmp_path,monkeypatch):
    import transcomic.automation.session as session
    repo,wid,s,c=setup;add_group(repo,wid,tmp_path/'a',count=1)
    other=repo.create('Other',defaults(repo.store));add_group(repo,other,tmp_path/'b',count=1)
    folder=tmp_path/'scratch';folder.mkdir();part=folder/(str(uuid.uuid4())+'.'+str(uuid.uuid4())+'.part');part.write_bytes(b'owned temporary')
    output=folder/'saved.wav';output.write_bytes(b'permanent output')
    repo.register_staging(part,folder,'audio-part')
    stage=folder/('.transcomic-capcut-'+uuid.uuid4().hex);stage.mkdir();(stage/'temp').write_bytes(b'temp')
    repo.register_staging(stage,folder,'capcut-stage')
    # A corrupt/ambiguous registration must not cause removal of permanent data.
    repo.execute('INSERT INTO automation_staging VALUES (?,?,?,?)',(repo.session_id,str(output),str(folder),'audio-part'))
    original=session._retire_jobs;calls=[]
    def interrupted(db,id):
        calls.append(id)
        if len(calls)==2:raise OSError('Synthetic process interruption')
        original(db,id)
    monkeypatch.setattr(session,'_retire_jobs',interrupted)
    failed=repo.discard_session();failed.thread.join(3)
    assert failed.error and len(repo.rows('SELECT * FROM automation_worksets'))==1
    monkeypatch.setattr(session,'_retire_jobs',original)
    retry=Cleanup(repo,s.tts_store.path,current=True).start();retry.thread.join(3)
    assert not retry.error and not repo.rows('SELECT * FROM automation_worksets')
    assert not part.exists() and not stage.exists() and output.read_bytes()==b'permanent output'
    assert retry.preserved_staging==[str(output)]


@pytest.mark.parametrize('count',[1,10,100])
def test_gui_close_reopen_always_empty(lifecycle,tmp_path,count):
    app,open_window=lifecycle;w=open_window();repo=w.automation_repo;old_session=repo.session_id
    path=tmp_path/'source.txt';path.write_text('A source line',encoding='utf8')
    for i in range(count):
        wid=repo.create('Draft '+str(i),defaults(w.store));repo.add(wid,[path])
    w.automation_page.load_worksets(wid)
    w.close();wait(app,lambda:w._closed,8)
    reopened=open_window();p=reopened.automation_page
    assert p.repo.session_id!=old_session and p.current is None and p.model.rowCount()==0
    assert p.worksets.count()==0 and not p.controller.busy and not p.tasks
    assert p.lock_note.isHidden() and not p.stop.isEnabled()
    assert reopened.workspace_ids==[] and reopened.doc_id is None
    assert reopened.store.jobs()==[] and path.exists()


def test_stay_and_escape_do_not_cancel_session(gui,monkeypatch):
    app,w,p,wid=gui
    dialog=AutomationExitDialog(w)
    assert set(dialog.buttons)=={'safe','cancel'}
    QTimer.singleShot(0,dialog.reject);dialog.exec();assert dialog.choice=='cancel'
    monkeypatch.setattr(w,'confirm_exit',lambda running:'cancel')
    w.close();app.processEvents()
    assert not w._closed and not p.repo.session_closing.is_set() and p.repo.workset(wid)
    dialog=AutomationExitDialog(w);QTimer.singleShot(0,lambda:dialog.buttons['safe'].click())
    dialog.exec();assert dialog.choice=='safe'


def test_confirmation_does_not_wait_for_database_writer(gui):
    app,w,p,wid=gui;held=threading.Event();release=threading.Event()
    def writer():
        with w.store.transaction():held.set();release.wait(3)
    thread=threading.Thread(target=writer);thread.start();assert held.wait(1)
    start=time.monotonic()
    def stay():
        modal=QApplication.activeModalWidget()
        assert isinstance(modal,AutomationExitDialog)
        modal.buttons['cancel'].click();release.set()
    QTimer.singleShot(30,stay)
    try:assert REAL_CONFIRM_EXIT(w,True)=='cancel'
    finally:release.set();thread.join(2)
    assert time.monotonic()-start<.7 and not p.repo.session_closing.is_set()


def test_completed_events_survive_reused_sqlite_row_ids(tmp_path):
    store=Store(tmp_path/'state.sqlite3');tts=TtsStore(tmp_path/'tts.sqlite3')
    try:
        source=tmp_path/'input.txt';source.write_text('Synthetic source',encoding='utf8')
        for index in range(2):
            repo=Repository(store);repo.tts_store=tts
            wid=repo.create('Completed '+str(index),defaults(store));gid=repo.add(wid,[source])[0]
            repo.update_group(gid,state='completed');repo.state(wid,'completed')
            repo.event(wid,gid,'completed','Synthetic completion');clean(repo)
        assert len(repo.completed_history())==2
        assert len(repo.rows('SELECT * FROM automation_history_events'))==2
    finally:tts.close();store.close()


def test_fresh_session_does_not_bypass_other_live_instance_guard(setup):
    repo,wid,s,c=setup;repo.activate(wid)
    fresh=Repository(repo.store);fresh.tts_store=s.tts_store
    another=fresh.create('Second instance',defaults(repo.store))
    assert fresh.worksets()[0]['id']==another and fresh.active() is None
    with pytest.raises(ValueError,match='khác đang chạy'):fresh.activate(another)


def test_cleanup_write_failure_preserves_data_and_can_retry_close(gui,tmp_path,monkeypatch):
    import transcomic.automation.session as session
    app,w,p,wid=gui;gid,source,_=add_group(p.repo,wid,tmp_path/'input',count=1)
    original=session._retire_jobs
    def fail(*args):raise OSError('Synthetic unavailable database')
    monkeypatch.setattr(session,'_retire_jobs',fail)
    w.close()
    wait(app,lambda:p.repo.session_closing.is_set() and not w._exit_pending and p.repo.cleanup is None)
    assert not w._closed and p.repo.group(gid) and source.exists()
    monkeypatch.setattr(session,'_retire_jobs',original)
    w.close();wait(app,lambda:w._closed)
    assert source.exists()


def test_empty_workspace_does_not_enumerate_historical_documents(lifecycle,tmp_path,monkeypatch):
    app,open_window=lifecycle;w=open_window();repo=w.automation_repo
    source=tmp_path/'source.txt';source.write_text('A permanent historical manuscript',encoding='utf8')
    for i in range(100):
        work=repo.create(str(i),defaults(w.store));repo.add(work,[source])
    w.close();wait(app,lambda:w._closed)
    def forbidden(*args):raise AssertionError('Startup must not enumerate every historical document')
    monkeypatch.setattr(Store,'documents',forbidden)
    reopened=open_window()
    assert reopened.workspace_ids==[] and reopened.automation_repo.worksets()==[]
    assert reopened.store.db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==100


def test_late_http_after_shutdown_fence_cannot_write_into_new_session(gui,tmp_path):
    from test_kira_auto_recovery import response
    from transcomic.automation.adapters import Translation
    from transcomic.kira_pool import KiraPoolProvider
    app,w,p,wid=gui;add_group(p.repo,wid,tmp_path/'source',count=2)
    entered=threading.Event();release=threading.Event();ignored=threading.Event()
    async def transport(request):
        entered.set()
        while not release.is_set():
            try:await asyncio.sleep(.01)
            except asyncio.CancelledError:ignored.set()
        return response(request)
    p.services.translation=Translation(p.repo,lambda store,job:KiraPoolProvider(store,'mock',transport=httpx.MockTransport(transport)),network_probe=lambda _:True)
    p.controller.validate(wid);p.controller.start(wid);wait(app,entered.is_set)
    w.shutdown_grace_seconds=.1;path=w.store.path
    try:
        w.close();wait(app,lambda:w._closed,6)
        assert ignored.is_set()
        reopened=Store(path)
        try:
            fresh=Repository(reopened);before=[reopened.lines(d['id']) for d in reopened.documents()]
            release.set()
            scheduler=p.services.translation.scheduler
            wait(app,lambda:not scheduler._thread.is_alive(),3)
            assert fresh.worksets()==[] and [reopened.lines(d['id']) for d in reopened.documents()]==before
            assert all(json.loads(j['config']).get('automation_discarded') for j in reopened.jobs())
        finally:reopened.close()
    finally:release.set()


@pytest.mark.parametrize('stage',['translation','tts','capcut'])
def test_close_running_stage_cancels_without_new_output_or_resume(gui,tmp_path,monkeypatch,stage):
    from test_kira_auto_recovery import response
    from transcomic.automation.adapters import Translation
    from transcomic.kira_pool import KiraPoolProvider
    app,w,p,wid=gui;gid,source,images=add_group(p.repo,wid,tmp_path/'input',count=2)
    entered=threading.Event();release=threading.Event()
    if stage=='translation':
        async def transport(request):
            entered.set();await asyncio.sleep(30)
            return response(request)
        p.services.translation=Translation(p.repo,lambda store,job:KiraPoolProvider(store,'mock',transport=httpx.MockTransport(transport)),network_probe=lambda provider:True)
    elif stage=='tts':
        FakeEngine.entered=entered;FakeEngine.release=release
    else:
        import transcomic.capcut.exporter as exporter
        original=exporter.write_project
        def blocked(*args,**kwargs):
            progress=kwargs.get('progress')
            def on_progress(*items):
                entered.set()
                assert p.repo.session_closing.wait(5)
                if progress:progress(*items)
            kwargs['progress']=on_progress
            return original(*args,**kwargs)
        monkeypatch.setattr(exporter,'write_project',blocked)
    p.controller.validate(wid);p.controller.start(wid);wait(app,entered.is_set)
    w.close();app.processEvents()
    assert p.repo.session_closing.is_set()
    if stage=='tts':
        assert not w._closed  # Wait for the in-process synthetic engine's safe return.
        release.set()
    wait(app,lambda:w._closed,8)
    assert source.exists() and len(list(images.glob('*.png')))==2
    assert not list((tmp_path/'projects').iterdir())
    if stage=='tts':assert not list(source.parent.rglob('*.wav'))
    # Inspect through fresh connections, not retired Qt wrappers.
    store=Store(p.repo.store.path)
    try:
        assert store.db.execute('SELECT COUNT(*) FROM automation_worksets').fetchone()[0]==0
        assert store.db.execute('SELECT COUNT(*) FROM automation_group_fields').fetchone()[0]==0
        assert all(not Scheduler.has_work(store,j['id']) for j in store.jobs())
    finally:store.close()
