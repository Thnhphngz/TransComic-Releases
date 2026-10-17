"""V4.1 regressions: accepted history, safe routing and committed edit identity."""
import json
import sqlite3
from pathlib import Path
import pytest
from PySide6.QtCore import Qt,QTimer,QPoint
from PySide6.QtWidgets import QApplication,QMessageBox,QLineEdit,QStyleOptionViewItem
from PySide6.QtTest import QTest
from tests.test_tts_gui import gui,add,wait
from tests.test_tts import prepare,FakeEngine
from transcomic.tts.storage import TtsStore
from transcomic.tts.scheduler import Scheduler
from transcomic.ui.tts_models import CenterCheckDelegate


def test_drafts_never_enter_history_and_prestart_failures(gui,tmp_path,monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from transcomic.tts.output import Outputs
    app,window,page=gui;doc=add(page,tmp_path/'Import.txt');page.open_details(doc['id'])
    assert page.model.setData(page.model.index(0,1),'Draft edited')
    page.voice.setCurrentIndex(1);page.load_history();assert not page.history_panel.cards
    page.mode.setCurrentIndex(page.mode.findData('custom'));monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *a:'');page.start();assert not page.history_panel.cards
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *a:str(tmp_path))
    monkeypatch.setattr(Outputs,'confirm',lambda *a:(_ for _ in ()).throw(OSError('fixture destination lost')))
    with pytest.raises(OSError):page.start()
    assert not page.store.history_runs();page.load_history();assert not page.history_panel.cards
    page.clear_history();assert page.store.doc(doc['id'])  # drafts neither block nor get deleted


def test_start_acceptance_retains_runtime_failure_and_invalid_voice_is_hidden(tmp_path):
    store,run,output,root=prepare(tmp_path)
    class Broken(FakeEngine):
        def probe(self,*a):raise RuntimeError('fixture runtime failure')
    scheduler=Scheduler(store,None,engine_factory=Broken)
    config=json.loads(store.run(run)['config']);config['voice']='';store.execute('UPDATE runs SET config=? WHERE id=?',(json.dumps(config),run))
    with pytest.raises(ValueError):scheduler.start(run)
    assert not store.history_runs()
    config['voice']='af_heart';store.execute('UPDATE runs SET config=? WHERE id=?',(json.dumps(config),run));scheduler.start(run);scheduler.thread.join(10)
    assert not scheduler.busy and store.history_runs()[0]['id']==run and store.run(run)['error']
    store.close()


def test_legacy_history_migration_preserves_audio_and_is_idempotent(tmp_path):
    store,run,output,root=prepare(tmp_path);doc=store.docs(run)[0];item=store.items(run)[0]
    store.execute("UPDATE runs SET state='draft' WHERE id=?",(run,));store.execute("UPDATE segments SET state='success',sha256='fixture' WHERE id=?",(item['id'],))
    # Legacy ready checkpoints have no explicit Start event. Preserve them
    # conservatively rather than silently dropping a user's recovery record.
    store.execute("INSERT INTO runs(id,state,created) VALUES ('legacy-ready','ready',0)");store.close()
    db=sqlite3.connect(tmp_path/'state.sqlite3');db.execute('ALTER TABLE runs DROP COLUMN history_accepted');db.commit();db.close()
    for _ in range(2):
        store=TtsStore(tmp_path/'state.sqlite3');assert store.history_runs()[0]['id']==run;assert store.doc(doc['id']);assert store.run('legacy-ready')['history_accepted']==1;store.close()


def test_direct_clear_cancel_then_confirm_durable_preserves_drafts_and_files(gui,tmp_path,monkeypatch):
    from transcomic.ui.tts_page import TtsPage
    app,window,page=gui;source=tmp_path/'Completed.txt';doc=add(page,source);page.start();wait(app,lambda:not page.is_busy());audio=Path(page.store.doc(doc['id'])['folder'])/'0001.wav';saved=audio.read_bytes();source_saved=source.read_bytes()
    page.new_run();draft=add(page,tmp_path/'Draft.txt');page.history_panel.search.setText('No matches');page.history_panel.filter_changed()
    monkeypatch.setattr(page,'confirm_clear_history',lambda:TtsPage.confirm_clear_history(page))
    def answer(label):
        def choose():
            dialog=next(d for d in app.topLevelWidgets() if isinstance(d,QMessageBox) and d.isVisible())
            assert dialog.windowTitle()=='Xóa toàn bộ lịch sử TTS?';assert 'không thể hoàn tác' in dialog.text();assert 'ngoài' in dialog.informativeText()
            next(b for b in dialog.buttons() if b.text()==label).click()
        QTimer.singleShot(25,choose)
    assert page.history_panel.clear_button.text()=='Xóa lịch sử' and page.history_panel.clear_button.toolTip()=='Xóa toàn bộ lịch sử TTS'
    answer('Hủy');QTest.mouseClick(page.history_panel.clear_button,Qt.LeftButton);assert page.store.doc(doc['id'])
    answer('Xóa lịch sử');QTest.mouseClick(page.history_panel.clear_button,Qt.LeftButton)
    assert not page.store.doc(doc['id']) and page.store.doc(draft['id']);assert audio.read_bytes()==saved and source.read_bytes()==source_saved
    other=sqlite3.connect(page.store.path);assert not other.execute('SELECT id FROM documents WHERE id=?',(doc['id'],)).fetchone();other.close()


def test_center_checkbox_whole_cell_row_height_and_keyboard_focus(gui,tmp_path):
    app,window,page=gui;one=add(page,tmp_path/'One.txt');two=add(page,tmp_path/'Two.txt');view=page.file_table
    for height in (38,80):
        view.setRowHeight(1,height);index=page.document_model.index(1,0);view.scrollTo(index);app.processEvents();rect=view.visualRect(index)
        option=QStyleOptionViewItem();option.rect=rect;option.widget=view;check=CenterCheckDelegate.check_rect(option)
        assert abs(check.center().x()-rect.center().x())<=1 and abs(check.center().y()-rect.center().y())<=1
        QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=rect.topLeft()+QPoint(2,2))
        assert page.document_model.checked==({two['id']} if height==38 else set()) and not view.keyboard_focus
    view.setFocus();QTest.keyClick(view,Qt.Key_Down);assert view.keyboard_focus and view.focusPolicy()!=Qt.NoFocus


def test_native_editor_undo_and_committed_undo_revision_scope(gui,tmp_path):
    app,window,page=gui;one=add(page,tmp_path/'One.txt');two=add(page,tmp_path/'Two.txt');page.open_details(one['id']);model=page.model;view=page.table
    index=model.index(0,1);id=index.data(Qt.UserRole);original=page.store.segment(id)['text'];view.setCurrentIndex(index);view.edit(index);app.processEvents()
    editor=view.findChild(QLineEdit);assert editor and editor.isVisible();editor.selectAll();QTest.keyClicks(editor,'Changed text');QTest.keyClick(editor,Qt.Key_Z,Qt.ControlModifier);assert editor.text()==original
    editor.selectAll();QTest.keyClicks(editor,'Committed text');QTest.keyClick(editor,Qt.Key_Return);app.processEvents();assert page.store.segment(id)['text']=='Committed text'
    QTest.keyClick(view,Qt.Key_Z,Qt.ControlModifier);assert page.store.segment(id)['text']==original and page.store.segment(id)['revision']==2
    assert model.setData(model.index(0,1),'Next edit');page.open_details(two['id']);QTest.keyClick(view,Qt.Key_Z,Qt.ControlModifier);assert page.store.segment(id)['text']=='Next edit'
    page.open_details(one['id']);page.store.edit(id,'External revision');assert not model.undo_last_edit();assert page.store.segment(id)['text']=='External revision'
    page.store.status(page.run_id,'running');assert not model.setData(model.index(0,1),'During inference');assert not model.undo_last_edit()
    page.store.status(page.run_id,'draft')


def test_output_refresh_on_each_play_resume_device_loss_no_overlap(gui,tmp_path,monkeypatch):
    import numpy as np
    from PySide6.QtMultimedia import QMediaDevices,QMediaPlayer
    from transcomic.tts.audio import encode
    from tests.test_tts import wave
    # A 100 ms tone may end before Qt's position notification under full-suite
    # load; use a real three-second source so this asserts active playback.
    app,window,page=gui;bar=page.player;path=tmp_path/'fixture.wav';encode(path,[np.tile(wave(),30)]);messages=[];bar.error.connect(messages.append)
    old=bar.output;bar.play([(str(path),'fixture')]);assert bar.output is not old
    wait(app,lambda:bar.player.duration()>0);bar.player.pause();old=bar.output;bar.toggle();assert bar.output is old
    wait(app,lambda:bar.player.position()>10)
    monkeypatch.setattr(bar,'output_signature',lambda:(b'new-headphones',()))
    bar.devices.audioOutputsChanged.emit();wait(app,lambda:bar.player.source().isEmpty());assert any('thay đổi' in m for m in messages)
    # No auto restart when Bluetooth disappears or returns.
    assert bar.player.playbackState()==QMediaPlayer.StoppedState
    from PySide6.QtMultimedia import QAudioDevice
    monkeypatch.setattr(QMediaDevices,'defaultAudioOutput',lambda:QAudioDevice());bar.play([(str(path),'fixture')]);assert bar.player.source().isEmpty() and any('Không có thiết bị' in m for m in messages)
    assert not page.scheduler.busy
