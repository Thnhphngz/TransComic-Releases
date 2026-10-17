from pathlib import Path
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog,QMessageBox,QTableView
from tests.test_tts_gui import gui,add,wait
from tests.test_tts import FakeEngine,wave


class Tone(FakeEngine):
    def synthesize(self,*args):yield np.tile(wave(),50)


def test_history_full_height_popup_search_and_stable_card(gui,tmp_path):
    app,window,page=gui;doc=add(page,tmp_path/'Chapter.txt','\n'.join('Sentence '+str(i) for i in range(2000)))
    assert not page.history_panel.cards
    page.store.execute('UPDATE runs SET history_accepted=1 WHERE id=?',(page.run_id,));page.load_history();QTest.qWait(80);app.processEvents();card=page.history_panel.cards[doc['id']];before=card.size();assert not card.findChildren(QTableView)
    assert page.history_panel.geometry().top()==page.workspace.geometry().top() and abs(page.history_panel.height()-page.workspace.height())<=2
    QTest.mouseClick(card.sentences,Qt.LeftButton);dialog=page.audio_dialog;app.processEvents()
    assert dialog.isVisible() and dialog.model.rowCount()==2000 and card.size()==before and dialog.table.columnWidth(1)>200
    dialog.search.setText('Sentence 1999');app.processEvents();assert dialog.proxy.rowCount()==1 and dialog.proxy.index(0,0).data()=='2000'
    dialog.reject();assert not dialog.isVisible() and card.size()==before
    page.history_panel.search.setText('no matching fixture');wait(app,lambda:not page.history_panel.cards);assert page.history_panel.empty.text()=='Không tìm thấy lịch sử phù hợp'


def test_input_none_new_jobs_after_edit_shared_player_close_and_no_clear(gui,tmp_path,monkeypatch):
    app,window,page=gui;page.scheduler.factory=Tone;monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *a:str(tmp_path))
    page.tabs.setCurrentIndex(1);page.split_controls.toggle.setChecked(False);page.input_text.setPlainText('First.\nSecond!');page.input_name.setText('First take');page.start();wait(app,lambda:not page.is_busy())
    old=page.run_id;doc=page.store.docs(old)[0];folder=Path(doc['folder']);content=(folder/'0001.wav').read_bytes();card=page.history_panel.cards[doc['id']]
    assert not card.sentences.isVisible() and card.listen.isVisible();assert not any(b.text()=='Xóa toàn bộ' for b in page.input_page.findChildren(type(card.listen)))
    QTest.mouseClick(card.listen,Qt.LeftButton);wait(app,lambda:page.playing is not None);assert page.player.parentWidget()!=card and page.player.isVisible()
    page.player.output.setVolume(.25);page.player.toggle();assert page.playing is not None
    QTest.mouseClick(page.player.close_button,Qt.LeftButton);assert page.player.isHidden() and page.player.player.source().isEmpty() and page.store.run(old)['state']=='completed'
    page.input_name.setText('Second take');page.input_text.setPlainText('Changed text.');app.processEvents();assert page.start_button.isEnabled() and page.start_button.text()=='Bắt đầu'
    page.start();wait(app,lambda:not page.is_busy());assert page.run_id!=old and page.store.run(old)['state']=='completed' and content==(folder/'0001.wav').read_bytes()
    (folder/'0001.wav').unlink();wait(app,lambda:not page.history_panel.checking);page.history_panel.check_presence();wait(app,lambda:not card.listen.isEnabled());assert 'Thiếu file' in card.meta.text() and page.store.run(old)['state']=='completed'


def test_input_split_toggle_geometry_and_preview_unicode(gui):
    app,window,page=gui;page.tabs.setCurrentIndex(1);page.input_text.setPlainText('Hello.\n\n最後? End!');page.update_input_counts();QTest.qWait(80);app.processEvents();before=(page.tab_bar.geometry(),page.tab_strip.height(),page.tabs.geometry())
    QTest.mouseClick(page.split_controls.sentence,Qt.LeftButton);app.processEvents();assert page.split.currentData()=='sentences' and page.split_controls.count.text()=='3 câu'
    QTest.mouseClick(page.split_controls.toggle,Qt.LeftButton);app.processEvents();assert page.split.currentData()=='none' and page.split_controls.count.text()=='1 đoạn'
    assert before==(page.tab_bar.geometry(),page.tab_strip.height(),page.tabs.geometry())
    page.input_text.clear();page.update_input_counts();assert page.split_controls.count.text()=='0 câu'


def test_history_clear_all_cancel_confirm_keeps_audio_not_filtered_only(gui,tmp_path,monkeypatch):
    app,window,page=gui;page.scheduler.factory=Tone;first=add(page,tmp_path/'Alpha.txt');page.start();wait(app,lambda:not page.is_busy());audio=Path(page.store.doc(first['id'])['folder'])/'0001.wav';saved=audio.read_bytes()
    page.new_run();second=add(page,tmp_path/'Beta.txt');page.start();wait(app,lambda:not page.is_busy());page.history_panel.search.setText('Alpha');page.history_panel.filter_changed()
    monkeypatch.setattr(page,'confirm_clear_history',lambda:False);page.clear_history();assert page.store.doc(first['id']) and page.store.doc(second['id'])
    page.open_sentences(first['id']);assert page.audio_dialog.isVisible()
    monkeypatch.setattr(page,'confirm_clear_history',lambda:True);page.clear_history();assert not page.store.doc(first['id']) and not page.store.doc(second['id']) and audio.read_bytes()==saved and not page.audio_dialog.isVisible()


def test_cancelled_history_has_no_resume_and_does_not_reactivate(gui,tmp_path):
    app,window,page=gui;doc=add(page,tmp_path/'Canceled.txt');old=page.run_id;page.stop();assert page.store.run(old)['state']=='cancelled'
    assert doc['id'] not in page.history_panel.cards  # cancelling a draft is not a started job
    page.open_details(doc['id']);page.start();wait(app,lambda:not page.is_busy());assert page.run_id!=old and page.store.run(old)['state']=='cancelled' and page.store.run(page.run_id)['state']=='completed'


def test_popup_live_progress_playback_independent_from_cancel(gui,tmp_path):
    import time
    class SlowTone(Tone):
        def synthesize(self,*args):time.sleep(.06);yield np.tile(wave(),50)
    app,window,page=gui;page.scheduler.factory=SlowTone;doc=add(page,tmp_path/'Progress.txt','\n'.join('Sentence '+str(i) for i in range(20)))
    page.start();wait(app,lambda:page.store.progress(page.run_id).get('success',0)>=1);page.open_sentences(doc['id']);dialog=page.audio_dialog;assert dialog.model.rowCount()==20
    id=page.store.rows("SELECT id FROM segments WHERE document_id=? AND state='success' ORDER BY position",(doc['id'],))[0]['id'];page.play_segment(id);wait(app,lambda:page.playing==id)
    page.stop();wait(app,lambda:not page.scheduler.busy);assert page.store.run(page.run_id)['state']=='cancelled' and page.playing==id
    page.flush_items();assert any(i['state']=='cancelled' for i in dialog.model.items)
    dialog.reject();assert not page.player.player.source().isEmpty();QTest.mouseClick(page.player.close_button,Qt.LeftButton);assert page.playing is None


def test_popup_external_missing_audio_is_soft_and_reopening_reuses_controller(gui,tmp_path):
    app,window,page=gui;page.scheduler.factory=Tone;doc=add(page,tmp_path/'Missing.txt');page.start();wait(app,lambda:not page.is_busy());page.open_sentences(doc['id']);dialog=page.audio_dialog
    first,second=[i['id'] for i in dialog.model.items];page.play_segment(first);wait(app,lambda:page.playing==first);page.play_segment(second);assert page.player.player.source().isEmpty();wait(app,lambda:page.playing==second);page.player.close_button.click()
    wait(app,lambda:not dialog.checking);item=dialog.model.items[0];path=Path(page.store.doc(doc['id'])['folder'])/item['filename'];path.unlink()  # only this test's generated audio
    dialog.check_presence(all_rows=True);wait(app,lambda:bool(dialog.model.items[0].get('missing')));assert dialog.model.data(dialog.model.index(0,3))=='Thiếu file' and dialog.model.data(dialog.model.index(0,6))==''
    for _ in range(3):dialog.reject();page.open_sentences(doc['id']);assert page.audio_dialog is dialog
    assert page.store.segment(item['id'])['state']=='success'  # UI check does not rewrite persisted history


def test_history_delete_is_blocked_for_paused_and_input_split_does_not_change_bulk(gui,tmp_path):
    import pytest
    app,window,page=gui;doc=add(page,tmp_path/'Original.txt','One. Two!\nThird.');before=[i['text'] for i in page.store.items(page.run_id)]
    page.tabs.setCurrentIndex(1);page.split_controls.choose('sentences');page.input_text.setPlainText('Other. New!');page.update_input_counts();assert [i['text'] for i in page.store.items(page.bulk_run)]==before
    page.store.execute('UPDATE runs SET history_accepted=1 WHERE id=?',(page.bulk_run,));page.store.status(page.bulk_run,'paused')
    with pytest.raises(ValueError):page.clear_history()
    assert page.store.doc(doc['id'])
