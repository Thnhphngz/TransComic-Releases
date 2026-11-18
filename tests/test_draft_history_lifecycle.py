"""Isolated reopen regressions; no API, downloaded runtime or production profile."""
import json
import os
from pathlib import Path
import threading
import time

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
import pytest

from test_automation_ui import gui, wait
from test_tts_gui import add
from test_tts import FakeEngine
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.ui.tts_page import TtsPage
from transcomic.automation.validation import defaults


def completed_tts(app, w, tmp_path):
    w.pages.setCurrentIndex(7);app.processEvents();page=w.tts_page
    page.runtime_ready=True;page.scheduler.factory=FakeEngine
    doc=add(page,tmp_path/'history.txt','A completed sentence')
    page.start();wait(app,lambda:not page.is_busy())
    page.load_history()
    return page,doc,Path(page.store.doc(doc['id'])['folder'])/'0001.wav'


def test_completed_history_delete_during_startup_probe(gui,tmp_path,monkeypatch):
    app,w,p,wid=gui;page,doc,audio=completed_tts(app,w,tmp_path)
    saved=audio.read_bytes();gate=threading.Event();entered=threading.Event()
    def probe():entered.set();gate.wait(5)
    page.background(probe);assert entered.wait(1)
    try:
        card=page.history_panel.cards[doc['id']]
        action=next(a for a in card.context_menu().actions() if a.text().startswith('Xóa bản ghi'))
        assert action.isEnabled(), 'Completed history is locked by an unrelated runtime probe'
        monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.Yes)
        action.trigger();assert card.isHidden();app.processEvents()
        assert doc['id'] not in page.history_panel.cards
        assert audio.read_bytes()==saved
    finally:gate.set();wait(app,lambda:not page.is_busy())


def test_close_cancels_draft_validation(gui,tmp_path,monkeypatch):
    app,w,p,wid=gui;entered=threading.Event();exited=threading.Event()
    from transcomic.automation.validation import check_current
    def validate(id,**kwargs):
        entered.set()
        try:
            while True:check_current(kwargs['cancelled']);time.sleep(.005)
        finally:exited.set()
    monkeypatch.setattr(p.controller,'validate',validate)
    p.queue_validation(force=True);wait(app,entered.is_set)
    start=time.monotonic();w.close()
    try:
        wait(app,lambda:w._closed,seconds=1.5)
        assert exited.is_set() and time.monotonic()-start<1.5
    finally:
        # Baseline cleanup must also leave no test worker alive after a failure.
        p.validation_generation+=1
        wait(app,lambda:not any(t.is_alive() for t in p.tasks))
        if not w._closed:wait(app,lambda:w._closed)


@pytest.fixture
def lifecycle(tmp_path,monkeypatch):
    if os.environ.get('TRANSCOMIC_NATIVE_UI')!='1':monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([]);windows=[]
    monkeypatch.setattr(TtsPage,'check_runtime',lambda self:None)
    def open_window():
        store=Store(tmp_path/'profile'/'translation.sqlite3');store.set_setting('update_auto_check','0')
        w=MainWindow(store);w.resize(1280,820);w.show();w.pages.setCurrentIndex(9);windows.append(w);app.processEvents()
        return w
    yield app,open_window
    for w in windows:
        if not w._closed:
            w.close();wait(app,lambda:w._closed)


@pytest.mark.parametrize('count',[3,100])
def test_close_during_import_discards_all_accepted_inputs(lifecycle,tmp_path,monkeypatch,count):
    from transcomic.automation.repository import Repository
    from transcomic.automation.validation import check_current
    app,open_window=lifecycle;w=open_window();p=w.automation_page
    wid=p.repo.create('Draft import',defaults(w.store));p.load_worksets(wid)
    p.fields['speed'].setValue(1.25);saved_config=p.repo.workset(wid)['config']
    paths=[]
    from docx import Document
    for i in range(count):
        path=tmp_path/(f'{i:03}.docx' if i%2 else f'{i:03}.txt')
        if i%2:
            doc=Document();doc.add_paragraph('Synthetic input line');doc.save(path)
        else:path.write_text('Synthetic input line',encoding='utf8')
        paths.append(str(path))
    entered=threading.Event();original=Repository.add
    def blocked(self,id,paths,**kwargs):
        entered.set()
        while not kwargs['cancelled']():time.sleep(.005)
        check_current(kwargs['cancelled'])
    monkeypatch.setattr(Repository,'add',blocked)
    p.drop_paths(paths[:1]);p.drop_paths(paths[1:]);wait(app,entered.is_set)
    assert len(p.repo.workset(wid)['checkpoint']['draft_imports'])==2
    w.close();wait(app,lambda:w._closed,2)
    monkeypatch.setattr(Repository,'add',original)
    reopened=open_window();p=reopened.automation_page
    assert p.current is None and p.repo.worksets()==[] and not p.import_busy
    with pytest.raises(KeyError):p.repo.workset(wid)
    assert not p.controller.busy and not reopened.store.jobs() and not p.services.tts_store.history_runs()
    reopened.close();wait(app,lambda:reopened._closed)
    again=open_window();assert again.automation_repo.worksets()==[]
    assert not again.store.jobs()


def test_pairing_intent_is_discarded_on_close_and_stale_mapping_is_fenced(lifecycle,tmp_path,monkeypatch):
    from PIL import Image
    import transcomic.automation.validation as validation
    app,open_window=lifecycle;w=open_window();p=w.automation_page
    wid=p.repo.create('Draft images',defaults(w.store));p.load_worksets(wid)
    source=tmp_path/'input.txt';source.write_text('A single input line',encoding='utf8');p.drop_paths([str(source)])
    wait(app,lambda:not p.import_busy);gid=p.repo.group_summaries(wid)[0]['id']
    folders=[]
    for name in ('old','new'):
        folder=tmp_path/name;folder.mkdir();Image.new('RGB',(8,8)).save(folder/'1.png');folders.append(folder)
    entered=threading.Event();original=validation.image_manifest
    def blocked(folder,sort,*,cancelled=None):
        entered.set()
        while not cancelled():time.sleep(.005)
        validation.check_current(cancelled)
    monkeypatch.setattr(validation,'image_manifest',blocked)
    p.pair_folder(gid,folders[0]);wait(app,entered.is_set)
    p.pair_folder(gid,folders[1])
    w.close();wait(app,lambda:w._closed,2)
    monkeypatch.setattr(validation,'image_manifest',original)
    reopened=open_window();p=reopened.automation_page
    assert p.current is None and p.repo.worksets()==[] and not p.pair_pending
    with pytest.raises(KeyError):p.repo.group_state(gid)
    assert not reopened.store.jobs() and not p.controller.busy


def test_history_automation_ownership_and_write_failure(lifecycle,tmp_path,monkeypatch):
    app,open_window=lifecycle;w=open_window();page,doc,audio=completed_tts(app,w,tmp_path)
    p=w.automation_page;wid=p.repo.create('Owned history',defaults(w.store))
    source=tmp_path/'owner.txt';source.write_text('One source',encoding='utf8');gid=p.repo.add(wid,[source])[0]
    run=page.store.doc(doc['id'])['run_id'];p.repo.update_group(gid,tts_run=run)
    saved=audio.read_bytes();monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.Yes)
    original=page.store.delete_history_document
    def failed(id):raise OSError('Simulated read-only database')
    errors=[];monkeypatch.setattr(page,'report_error',lambda exc,stage:errors.append(str(exc)))
    monkeypatch.setattr(page.store,'delete_history_document',failed)
    page.guard(lambda:page.delete_history(doc['id']))
    assert errors and doc['id'] in page.history_panel.cards
    monkeypatch.setattr(page.store,'delete_history_document',original)
    page.delete_history(doc['id']);assert doc['id'] not in page.history_panel.cards
    assert page.store.doc(doc['id']) and p.repo.group_state(gid)['tts_run']==run
    page.history_panel.refresh([page.store.items(run)[0]['id']]);assert doc['id'] not in page.history_panel.cards
    w.close();wait(app,lambda:w._closed)
    reopened=open_window();reopened.pages.setCurrentIndex(7);app.processEvents()
    assert doc['id'] not in reopened.tts_page.history_panel.cards and audio.read_bytes()==saved
    assert reopened.automation_repo.worksets()==[]
    assert reopened.tts_page.store.doc(doc['id']) is not None


def test_explicit_validation_is_not_lost_behind_import(gui,tmp_path,monkeypatch):
    app,w,p,wid=gui;path=tmp_path/'queued.txt';path.write_text('A source line',encoding='utf8')
    gate=threading.Event();entered=threading.Event();original=p.repo.add
    def blocked(*args,**kwargs):entered.set();gate.wait(3);return original(*args,**kwargs)
    monkeypatch.setattr(p.repo,'add',blocked)
    p.drop_paths([str(path)]);wait(app,entered.is_set)
    p.queue_validation(force=True);gate.set();wait(app,lambda:p.proof is not None)
    assert len(p.proof['groups'])==1 and not p.controller.busy and not w.store.jobs()


def test_clear_completed_keeps_active_history_and_rolls_back_write_error(lifecycle,tmp_path):
    import sqlite3
    app,open_window=lifecycle;w=open_window();page,doc,audio=completed_tts(app,w,tmp_path)
    store=page.store;saved=audio.read_bytes();active=store.draft()
    other=store.add_document(active,dict(name='Active',text='Another line',line_count=1),'lines')
    store.execute("UPDATE runs SET state='running',history_accepted=1 WHERE id=?",(active,))
    store.execute("CREATE TRIGGER deny_history_delete BEFORE DELETE ON documents BEGIN SELECT RAISE(ABORT,'test write failure'); END")
    with pytest.raises(sqlite3.IntegrityError):store.clear_completed_history()
    assert store.doc(doc['id']) and store.doc(other) and audio.read_bytes()==saved
    store.execute('DROP TRIGGER deny_history_delete');store.clear_completed_history()
    assert not store.doc(doc['id']) and store.doc(other) and audio.read_bytes()==saved
    assert not store.can_delete_history(active)
    store.status(active,'cancelled')


def test_history_delete_does_not_invert_translation_tts_locks(lifecycle,tmp_path,monkeypatch):
    app,open_window=lifecycle;w=open_window();page,doc,audio=completed_tts(app,w,tmp_path)
    entered=threading.Event();errors=[];repo=w.automation_repo;original=repo.tts_owner
    def owner(run):entered.set();return original(run)
    monkeypatch.setattr(repo,'tts_owner',owner)
    def delete():
        try:page.store.delete_history_document(doc['id'])
        except Exception as exc:errors.append(exc)
    with w.store.lock:
        thread=threading.Thread(target=delete);thread.start();assert entered.wait(1)
        acquired=page.store.lock.acquire(timeout=.2)
        if acquired:page.store.lock.release()
    thread.join(2)
    assert acquired and not thread.is_alive() and not errors and audio.is_file()
