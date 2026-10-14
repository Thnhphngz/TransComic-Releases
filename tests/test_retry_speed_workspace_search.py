import asyncio
import json
import time
from pathlib import Path
import httpx
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.providers import KiraProvider
from transcomic.translation import Scheduler
from transcomic.ui.main import MainWindow
from transcomic.ui.window_state import show_initial


def window(tmp_path):
    app=QApplication.instance() or QApplication([]);store=Store(tmp_path/'state.db');w=MainWindow(store);w.resize(1400,800);w.show();app.processEvents();QTest.qWait(20)
    ids=[]
    for n in range(3):
        d,_=store.import_document(tmp_path/f'{n}.txt',decode_txt(b'Evelyn one\nEvelyn two'),'Tiếng Việt','Tiếng Anh');ids.append(d)
    run,jobs=store.create_run(ids,['Tiếng Anh','Tiếng Indonesia'],provider='kira',model='mock',source_lang='Tiếng Việt',concurrency=30)
    w.workspace_ids=[store.job(j)['document_id'] for j in jobs]
    for d in w.workspace_ids:
        for r in store.lines(d):store.edit_line(r['id'],'translation','Evelyn translated')
    w.open_document(ids[0]);return app,store,w,ids


def test_multi_search_files_columns_languages_navigation_and_preview_undo(tmp_path):
    app,store,w,ids=window(tmp_path);s=w.search;s.open(True);s.document_scope.setCurrentIndex(1);s.query.setText('Evelyn')
    assert len(s.results)==18  # Six unique source lines and twelve translations.
    s.scope.setCurrentIndex(2);assert len(s.results)==12
    s.language_scope.setCurrentIndex(1);assert len(s.results)==6
    s.document_scope.setCurrentIndex(2)
    for i in range(2):s.file_checks.item(i).setCheckState(Qt.Checked)
    assert len(s.results)==4
    s.navigate(-1);assert w.doc_id==ids[1]
    s.navigate(1);assert w.doc_id==ids[0]
    s.replacement.setText('Emily');s.replace_all();assert len(s.preview_changes)==4
    # Exclude the entire second file in preview.
    s.preview.topLevelItem(1).setCheckState(0,Qt.Unchecked);s.confirm_preview()
    assert all('Emily' in r['translation'] for r in store.lines(ids[0]))
    assert all('Evelyn' in r['translation'] for r in store.lines(ids[1]))
    other=next(d for d in w.workspace_ids if store.document(d)['source_instance']==ids[0] and d!=ids[0])
    assert all('Evelyn' in r['translation'] for r in store.lines(other))
    s.undo();assert all('Evelyn' in r['translation'] for r in store.lines(ids[0]))
    s.scope.setCurrentIndex(1);s.replace_scope.setCurrentIndex(1);s.language_scope.setCurrentIndex(0)
    assert len(s.results)==4
    s.replace_all();s.confirm_preview()
    assert all(r['source'].startswith('Emily') and r['state']=='stale' for d in (ids[0],other) for r in store.lines(d))
    assert len(s.undo_stack[-1])==8 # Two selected sources * two rows * two language revisions.
    s.undo();assert all(r['source'].startswith('Evelyn') for d in (ids[0],other) for r in store.lines(d))
    w._exit_authorized=True;w.close()


def test_preview_revision_change_aborts_entire_transaction_and_late_api_loses(tmp_path):
    app,store,w,ids=window(tmp_path);s=w.search;s.open(True);s.document_scope.setCurrentIndex(1);s.scope.setCurrentIndex(2);s.query.setText('Evelyn');s.replacement.setText('Emily');s.replace_all()
    row=store.lines(ids[0])[0];store.edit_line(row['id'],'translation','New API revision')
    s.confirm_preview();assert store.line(row['id'])['translation']=='New API revision'
    assert not any('Emily' in r['translation'] for d in w.workspace_ids for r in store.lines(d))
    # Removed history entries stay outside every workspace search scope.
    w.remove_workspace_instances({ids[2]},confirmed=True);s.rebuild();assert len(s.results)==7
    w._exit_authorized=True;w.close()


def test_layout_restore_panel_sidebar_theme_font_and_empty_workspace(tmp_path):
    app,store,w,ids=window(tmp_path);w.toggle_sidebar();w.document_splitter.setSizes([245,900]);w.dark=True;store.set_setting('dark','1');w.font_spin.setValue(18)
    w.document_splitter.splitterMoved.emit(245,1);QTest.qWait(300);sizes=w.document_splitter.sizes();w._exit_authorized=True;w.close()
    store=Store(tmp_path/'state.db');restored=MainWindow(store);restored.resize(1400,800);restored.show();app.processEvents();QTest.qWait(30)
    assert restored.sidebar.width()==72 and abs(restored.document_splitter.sizes()[0]-sizes[0])<=3
    assert restored.dark and restored.font_spin.value()==18 and not restored.workspace_ids and restored.doc_id is None and restored.scheduler is None
    assert len(store.documents())==6
    restored.toggle_documents_panel();restored._exit_authorized=True;restored.close()
    store=Store(tmp_path/'state.db');again=MainWindow(store);again.resize(900,580);again.show();app.processEvents();QTest.qWait(30)
    assert again.document_panel.isHidden() and again.sidebar.width()==72
    again.toggle_documents_panel();app.processEvents();assert again.table.viewport().width()>400
    again._exit_authorized=True;again.close()


def test_retry_fairness_early_start_and_controlled_concurrency_recovery(tmp_path):
    store=Store(tmp_path/'state.db');jobs=[];attempts={};timeline=[];active=peak=0
    for n in range(3):
        doc,_=store.import_document(tmp_path/f'{n}.txt',decode_txt(('\n'.join('Source '+str(i) for i in range(90))).encode()))
        jobs.append(store.create_job(doc,'mock','VI','EN',30,config={'recovery_successes':2,'recovery_step':3,'recovery_quiet_seconds':.02,'rate_recovery_interval':.01}))
    async def handle(req):
        nonlocal active,peak
        rows=json.loads(json.loads(req.content)['messages'][1]['content'])['lines'];key=rows[0]['id'];attempts[key]=attempts.get(key,0)+1;timeline.append((time.monotonic(),key,attempts[key]));active+=1;peak=max(peak,active)
        await asyncio.sleep(.015);active-=1
        if attempts[key]==1 and len(timeline)<=30:return httpx.Response(429,headers={'Retry-After':'.04'},json={})
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':r['id'],'text':'Valid'} for r in rows]})}}]})
    s=Scheduler(store,KiraProvider('fake',transport=httpx.MockTransport(handle)));s.start_many(jobs);s.join(12)
    assert not s._thread.is_alive() and peak<=30 and s.effective_concurrency==30
    assert min(t for t,k,n in timeline if n>1)<max(t for t,k,n in timeline if n==1)
    events=store.log.snapshot();changes=[e for e in events if e['event']=='concurrency_changed' and e['reason']=='successful_probe_window']
    assert changes and all(e['effective_concurrency']-e['previous_concurrency']<=3 for e in changes)
    assert all(r['state']=='done' for j in jobs for r in store.lines(store.job(j)['document_id']))
    assert all(e['semaphore_wait_seconds']>=0 and e['cooldown_wait_seconds']>=0 for e in events if e['event']=='persisted')
    store.close()
