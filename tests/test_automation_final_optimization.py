"""Native-capable GUI evidence and focused lifecycle tests; synthetic data only."""
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import httpx
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_automation_ui import gui,wait
from test_automation import setup,add_group,FakeEngine
from test_kira_auto_recovery import fixture,response,request_lines
from test_automation_ui_stability import test_automation_100_docs_2000_units_one_start_tab_switches_and_early_completion as full_pipeline
from transcomic.storage import Store
from transcomic.automation.adapters import Translation
from transcomic.kira_pool import KiraPoolProvider


def test_sqlite_capacity_migration_preserves_history_policy_indexes_and_foreign_keys(tmp_path):
    store,docs,run,jobs=fixture(tmp_path,kira_recovery_version=4)
    batch=store.batches(jobs[0])[0];store.job_state(jobs[0],'running');store.claim_batch(batch['id']);attempt=store.prepare_attempt(batch['id'],1,reserved_tokens=123)
    store.finish_batch(batch['id'],{p['id']:'The accepted story is unchanged' for p in batch['payload']},None,False,{},expected_attempt_id=attempt)
    store.complete_attempt(attempt,{'http_status':200});store.job_state(jobs[0],'finished')
    cfg=store.job(jobs[0])['config'];versions=store.db.execute('SELECT * FROM api_text_versions').fetchall();values=[tuple(r) for r in versions]
    history=[tuple(r) for r in store.db.execute('SELECT * FROM request_attempts')];cipher=bytes(store.db.execute('SELECT encrypted FROM kira_keys').fetchone()[0]);store.close()
    db=sqlite3.connect(tmp_path/'synthetic.db');db.execute('PRAGMA foreign_keys=OFF')
    db.executescript('''CREATE TABLE old_attempts(id TEXT PRIMARY KEY,original_batch_id TEXT NOT NULL REFERENCES batches(id),attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 6),state TEXT NOT NULL,created_at TEXT NOT NULL,completed_at TEXT,diagnostics TEXT,reserved_tokens INTEGER NOT NULL DEFAULT 0,UNIQUE(original_batch_id,attempt_number));
        INSERT INTO old_attempts SELECT * FROM request_attempts;DROP TABLE request_attempts;ALTER TABLE old_attempts RENAME TO request_attempts;
        CREATE INDEX retained_attempt_index ON request_attempts(created_at);''');db.close()
    store=Store(tmp_path/'synthetic.db')
    try:
        assert [tuple(r) for r in store.db.execute('SELECT * FROM request_attempts')]==history
        assert [tuple(r) for r in store.db.execute('SELECT * FROM api_text_versions')]==values
        assert store.job(jobs[0])['config']==cfg and bytes(store.db.execute('SELECT encrypted FROM kira_keys').fetchone()[0])==cipher
        assert not store.db.execute('PRAGMA foreign_key_check').fetchall() and store.db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert store.db.execute("SELECT 1 FROM sqlite_master WHERE name='retained_attempt_index'").fetchone()
        assert 'attempt_number>=1' in store.db.execute("SELECT sql FROM sqlite_master WHERE name='request_attempts'").fetchone()[0]
    finally:store.close()


def test_tts_file_one_starts_before_nine_of_ten_are_complete(setup,tmp_path):
    import asyncio
    repo,wid,services,c=setup;cfg=repo.workset(wid)['config'];cfg.update(kira_completion_policy=1,kira_dispatch_policy=1);repo.configure(wid,cfg)
    groups=[add_group(repo,wid,tmp_path/str(i),str(i),3)[0] for i in range(10)];first=repo.group(groups[0])['document_id']
    gate=threading.Event();voice=threading.Event();voice_release=threading.Event();FakeEngine.entered=voice;FakeEngine.release=voice_release
    async def handler(req):
        doc=repo.store.line(request_lines(req)[0]['id'])['document_id']
        while doc!=first and not gate.is_set():await asyncio.sleep(.004)
        return response(req)
    services.translation=Translation(repo,lambda st,j:KiraPoolProvider(st,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000),network_probe=lambda _:True)
    assert c.validate(wid)['passed'];c.start(wid)
    try:
        assert voice.wait(8) and services.translation.scheduler.admission.frontier==0
        assert sum(g['data'].get('translation_ready_cycle')==1 for g in repo.groups(wid))==1
        gate.set();voice_release.set();c.join(15)
        assert not c.busy and repo.workset(wid)['state']=='completed' and len(FakeEngine.calls)==30
    finally:gate.set();voice_release.set()


def test_new_admission_resume_reuses_completed_rows_and_job_ids(setup,tmp_path):
    import asyncio
    repo,wid,services,c=setup;cfg=repo.workset(wid)['config'];cfg.update(kira_completion_policy=1,kira_dispatch_policy=1);repo.configure(wid,cfg)
    gids=[add_group(repo,wid,tmp_path/str(i),f'{i:02}',6)[0] for i in range(12)];docs=[repo.group(g)['document_id'] for g in gids]
    gate=threading.Event();first=threading.Event();calls={}
    async def handler(req):
        ids=[r['id'] for r in request_lines(req)]
        for rid in ids:calls[rid]=calls.get(rid,0)+1
        if repo.store.line(ids[0])['document_id']==docs[0]:first.set()
        else:
            while not gate.is_set():await asyncio.sleep(.004)
        return response(req)
    services.translation=Translation(repo,lambda st,j:KiraPoolProvider(st,'mock',transport=httpx.MockTransport(handler),rpm=100000,tpm=100000000),network_probe=lambda _:True)
    assert c.validate(wid)['passed'];c.start(wid)
    try:
        assert first.wait(5);c.stop();gate.set();c.join(12);assert not c.busy
        old_jobs={j['id'] for j in repo.store.jobs()};accepted={r['id']:dict(r) for d in docs for r in repo.store.lines(d) if r['state']=='done'}
        assert c.validate(wid)['passed'];c.start(wid);c.join(25)
        assert not c.busy and repo.workset(wid)['state']=='completed',repo.events(wid)[-3:]
        assert old_jobs<={j['id'] for j in repo.store.jobs()} and len(repo.store.jobs())==12
        assert all(repo.store.line(rid)==row for rid,row in accepted.items()) and max(calls.values())==1
    finally:gate.set();c.stop();c.join(6)


@pytest.mark.parametrize('dark',[False,True])
def test_new_full_hundred_file_pipeline_native(gui,tmp_path,monkeypatch,dark):
    app,w,p,wid=gui;cfg=p.repo.workset(wid)['config'];cfg.update(kira_completion_policy=1,kira_dispatch_policy=1);p.repo.configure(wid,cfg)
    events=[];original=w.store.log.emit;active={};peak=[0]
    def emit(event,**kw):
        if event.startswith('source_') or event=='cohort_unlocked':events.append(dict(event=event,at=time.perf_counter(),source=kw.get('source_instance')))
        doc=kw.get('document_id')
        if event=='http_started':active[doc]=active.get(doc,0)+1;peak[0]=max(peak[0],sum(v>0 for v in active.values()))
        elif event in ('body_received','failure') and doc in active:active[doc]=max(0,active[doc]-1)
        return original(event,**kw)
    monkeypatch.setattr(w.store.log,'emit',emit)
    full_pipeline(gui,tmp_path,monkeypatch,dark)
    assert peak[0]<=10 and sum(v['event']=='source_completed' for v in events)==100
    assert sum(v['event']=='cohort_unlocked' for v in events)==9
    target=os.environ.get('AUTOMATION_UI_EVIDENCE')
    if target:
        out=Path(target);out.mkdir(parents=True,exist_ok=True)
        (out/f'admission-{dark}.json').write_text(json.dumps(dict(events=events,peak_http_files=peak[0],final=p.services.translation.scheduler.admission.snapshot()),indent=2),encoding='utf8')


def test_document_import_batches_keep_selection_scroll_and_only_final_errors(gui,tmp_path,monkeypatch):
    import transcomic.ui.stage2 as stage2
    app,w,p,wid=gui;w.pages.setCurrentIndex(0)
    folders=[]
    for k in range(3):
        folder=tmp_path/str(k);folder.mkdir();folders.append(folder)
        for i in range(12):(folder/f'Chapter {k*12+i:03}.txt').write_text('Văn bản tổng hợp',encoding='utf8')
    w.import_paths([str(folders[0])]);wait(app,lambda:not w.import_busy)
    selected=w.doc_id;w.document_panel.view.scrollToBottom();app.processEvents();scroll=w.document_panel.view.verticalScrollBar().value()
    resets=[];w.document_panel.model.modelReset.connect(lambda:resets.append(1));entered=threading.Event();release=threading.Event();original=stage2.import_many
    def slow(*a,**kw):entered.set();assert release.wait(6);return original(*a,**kw)
    monkeypatch.setattr(stage2,'import_many',slow)
    w.import_paths([str(folders[1])]);assert entered.wait(2);w.import_paths([str(folders[2])]);app.processEvents()
    assert w.line_check.property('glassRole')=='secondary' and '⚠' not in w.line_check.text()
    rect=w.document_panel.geometry();signature=w.line_check.signature()
    # A stale failure must never replace the neutral import state.
    w.line_check.apply_result((signature,None,None,None,None));assert '⚠' not in w.line_check.text()
    release.set();wait(app,lambda:not w.import_busy and not getattr(w,'_pending_imports',[]),20)
    assert len(w.workspace_ids)==36 and w.doc_id==selected and not resets
    assert w.document_panel.view.verticalScrollBar().value()==scroll and w.document_panel.geometry()==rect
    assert not w.automation_controller.busy and not w.store.jobs()


def test_started_legacy_policy_is_frozen_but_new_worksets_use_completion(setup):
    from transcomic.automation.validation import defaults
    repo,wid,services,c=setup;cfg=repo.workset(wid)['config']
    repo.store.set_setting('automation_last_config',json.dumps(cfg))
    fresh=defaults(repo.store)
    assert fresh['kira_completion_policy']==fresh['kira_dispatch_policy']==1
    repo.activate(wid)
    before=repo.workset(wid)['config']
    for field in ('kira_completion_policy','kira_dispatch_policy'):
        with pytest.raises(ValueError):repo.configure(wid,{**before,field:1})
        assert repo.workset(wid)['config']==before


def test_stop_pause_and_double_start_during_lazy_preparation(setup,tmp_path,monkeypatch):
    import transcomic.automation.validation as validation
    repo,wid,services,c=setup;cfg=repo.workset(wid)['config'];cfg.update(kira_completion_policy=1,kira_dispatch_policy=1);repo.configure(wid,cfg)
    add_group(repo,wid,tmp_path/'g',count=3);assert c.validate(wid)['passed']
    entered=threading.Event();release=threading.Event();original=validation.read_source
    def held(*a,**kw):entered.set();assert release.wait(5);return original(*a,**kw)
    monkeypatch.setattr(validation,'read_source',held)
    c.start(wid)
    try:
        assert entered.wait(3) and c.preparing.is_set()
        with pytest.raises(ValueError):c.start(wid)
        c.pause();assert c.paused.is_set() and not repo.store.jobs()
        c.stop();release.set();c.join(8)
        assert not c.busy and repo.workset(wid)['state']=='stopped'
        assert not c.preparing.is_set() and repo.workset(wid)['checkpoint']['preparing'] is False
        assert not repo.store.jobs() and not FakeEngine.calls
    finally:release.set();c.stop();c.join(5)


def test_lazy_source_change_blocks_unopened_file_without_false_completion(setup,tmp_path):
    repo,wid,services,c=setup;cfg=repo.workset(wid)['config'];cfg.update(kira_completion_policy=1,kira_dispatch_policy=1);repo.configure(wid,cfg)
    groups=[add_group(repo,wid,tmp_path/str(i),f'{i:02}',3) for i in range(12)]
    assert c.validate(wid)['passed']
    # Certificate remains cached; the dispatch-time filesystem check must catch it.
    groups[10][1].write_text('A different source after validation',encoding='utf8')
    c.start(wid);c.join(20)
    assert not c.busy and repo.workset(wid)['state']=='needs_attention'
    scheduler=services.translation.scheduler
    assert scheduler.intervention_reason=='admission_input_invalid'
    for gid,path,folder in groups[10:]:
        assert all(not row['translation'] for row in repo.store.lines(repo.group(gid)['document_id']))
    assert len(repo.store.jobs())==10 and len(scheduler.admission.complete)<12
    assert scheduler.provider.monitor.state!='finished'


@pytest.mark.parametrize('dark',[False,True])
def test_native_import_real_errors_and_idle_snapshot_cannot_erase_manual_badge(gui,tmp_path,monkeypatch,dark):
    import transcomic.ui.stage2 as stage2
    app,w,p,wid=gui
    if w.dark!=dark:w.toggle_theme()
    w.pages.setCurrentIndex(0)
    first=tmp_path/'bad';first.mkdir();(first/'broken.docx').write_bytes(b'not a DOCX archive')
    second=tmp_path/'good';second.mkdir();(second/'chapter.txt').write_text('Synthetic source',encoding='utf8')
    entered=threading.Event();release=threading.Event();original=stage2.import_many
    def held(*a,**kw):entered.set();assert release.wait(5);return original(*a,**kw)
    monkeypatch.setattr(stage2,'import_many',held)
    w.import_paths([str(first)]);assert entered.wait(2)
    w.import_paths([str(second)]);w.import_paths([str(second)]);release.set()
    wait(app,lambda:not w.import_busy and not getattr(w,'_pending_imports',[]),12)
    assert len(w.workspace_ids)==1 and len(w.import_errors)==1 and w.import_details.isVisible()
    row=w.store.lines(w.doc_id)[0];w.store.edit_line(row['id'],'translation','The accepted manual translation.')
    w.refresh();wait(app,lambda:w.period_warning.count==1 and w.line_check.report and w.line_check.report.translated==1)
    serial=w.translation_updates.generation
    for _ in range(3):p.refresh();app.processEvents()
    QTest.qWait(150)
    assert w.period_warning.count==1 and w.translation_updates.generation==serial
    for width in (1440,1050):
        w.resize(width,900);app.processEvents();w.adapt_v2_toolbar()
        controls=[b for b in w.file_action_buttons if b.isVisible()]
        assert len(controls)>=5
        rects=[b.geometry() for b in controls]
        assert len({r.y() for r in rects})==1
        assert all(a.right()<b.left() for a,b in zip(rects,rects[1:]))
    target=os.environ.get('AUTOMATION_UI_EVIDENCE')
    if target:
        out=Path(target);out.mkdir(parents=True,exist_ok=True)
        w.resize(1440,940);app.processEvents();w.adapt_v2_toolbar()
        w.grab().save(str(out/f'import-stable-{dark}.png'))
        w.period_warning.open_list();app.processEvents()
        assert w.period_warning.dialog.model.rowCount()==1
        w.period_warning.dialog.grab().save(str(out/f'period-live-{dark}.png'));w.period_warning.dialog.close()
        (out/f'import-{dark}.json').write_text(json.dumps(dict(dpr=w.devicePixelRatioF(),platform=app.platformName(),import_errors=len(w.import_errors),documents=len(w.workspace_ids),period_count=w.period_warning.count)),encoding='utf8')


def test_idle_snapshot_read_before_manual_commit_is_rejected(gui,tmp_path,monkeypatch):
    from transcomic.ui.translation_updates import SnapshotReader
    app,w,p,wid=gui;path=tmp_path/'manual.txt';path.write_text('Synthetic source',encoding='utf8')
    w.import_paths([str(path)]);wait(app,lambda:not w.import_busy)
    w.pages.setCurrentIndex(0);updates=w.translation_updates
    entered=threading.Event();release=threading.Event();original=SnapshotReader.read
    def held(*a,**kw):
        result=original(*a,**kw)
        if not entered.is_set():entered.set();assert release.wait(5)
        return result
    monkeypatch.setattr(SnapshotReader,'read',held)
    updates.request(full=True);assert entered.wait(2)
    try:
        row=w.store.lines(w.doc_id)[0];text='The manual translation must survive.'
        w.store.edit_line(row['id'],'translation',text);w.refresh();release.set()
        assert updates.wait_for_idle(8)
        wait(app,lambda:w.period_warning.count==1 and w.line_check.report.translated==1)
        assert updates.last['editor']['rows'][0]['translation']==text
        assert w.store.line(row['id'])['translation']==text and w.model.rows[0]['translation']==text
    finally:release.set()


@pytest.mark.parametrize('dark',[False,True])
def test_native_final_completion_policy_and_terminal_snapshots(gui,tmp_path,monkeypatch,dark):
    from test_automation_ui_stability import test_actual_start_ab_same_sources_model_workers_and_mock_faults as pipeline
    app,w,p,wid=gui
    if w.dark!=dark:w.toggle_theme()
    cfg=p.repo.workset(wid)['config'];cfg.update(kira_completion_policy=1,kira_dispatch_policy=1);p.repo.configure(wid,cfg)
    pipeline(gui,tmp_path,monkeypatch,'automation')
    assert all(json.loads(j['config'])['kira_completion_policy']==1 for j in w.store.jobs())
    assert not p.controller.preparing.is_set() and p.repo.workset(wid)['checkpoint']['preparing'] is False
    w.pages.setCurrentIndex(9);p.refresh();app.processEvents()
    assert p.snapshots.wait_for_idle()
    target=os.environ.get('AUTOMATION_UI_EVIDENCE')
    if target:
        out=Path(target);out.mkdir(parents=True,exist_ok=True)
        assert w.grab().save(str(out/f'automation-final-{dark}.png'))
        (out/f'automation-final-{dark}.json').write_text(json.dumps(dict(dpr=w.devicePixelRatioF(),platform=app.platformName(),files=6,rows=120,requests=44,complete=True,preparing=False)),encoding='utf8')
