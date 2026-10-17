from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QFileDialog,QMenu
from tests.test_tts_gui import gui,add,wait
from tests.test_tts import FakeEngine,wave


def test_checkbox_header_remove_selected_and_clear_preserves_history(gui,tmp_path):
    app,window,page=gui;first=add(page,tmp_path/'One.txt');second=add(page,tmp_path/'Two.txt')
    page.document_model.setData(page.document_model.index(0,0),Qt.Checked,Qt.CheckStateRole);page.remove_files()
    assert [i['id'] for i in page.document_model.items]==[second['id']]
    header=page.file_table.horizontalHeader()
    from PySide6.QtCore import QPoint
    QTest.mouseClick(header.viewport(),Qt.LeftButton,pos=QPoint(18,header.height()//2));assert page.document_model.checked=={second['id']}
    page.start();wait(app,lambda:not page.is_busy());folder=Path(page.store.doc(second['id'])['folder']);old=page.run_id
    page.clear_all();assert page.run_id!=old and not page.store.docs(page.run_id) and page.store.doc(second['id']) and (folder/'0001.wav').exists()


def test_none_input_one_audio_and_shared_player(gui,tmp_path,monkeypatch):
    import numpy as np
    class Tone(FakeEngine):
        def synthesize(self,*args):yield np.tile(wave(),30)
    app,window,page=gui;page.scheduler.factory=Tone;page.tabs.setCurrentIndex(1);page.input_text.setPlainText('First.\nSecond!');page.split.setCurrentIndex(page.split.findData('none'));page.resplit()
    assert '1 đoạn' in page.input_counts.text();monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *a:str(tmp_path));page.start();wait(app,lambda:not page.is_busy())
    doc=page.store.docs(page.run_id)[0];assert len(list(Path(doc['folder']).glob('*.wav')))==1
    card=page.history_panel.cards[doc['id']];assert card.listen.isVisible() and page.player.isHidden()
    QTest.mouseClick(card.listen,Qt.LeftButton);wait(app,lambda:not page.is_busy());wait(app,lambda:page.playing is not None)
    assert page.player.parentWidget()!=card and page.player.isVisible() and card.listen.text()=='Dừng'
    QTest.mouseClick(card.listen,Qt.LeftButton);assert page.player.isHidden() and page.player.player.source().isEmpty() and page.store.run(page.run_id)['state']=='completed'


def test_bulk_sentences_show_pending_and_fixed_history(gui,tmp_path):
    app,window,page=gui;doc=add(page,tmp_path/'Chapter.txt');assert not page.history_panel.cards
    page.store.execute('UPDATE runs SET history_accepted=1 WHERE id=?',(page.run_id,));page.load_history();card=page.history_panel.cards[doc['id']]
    assert not card.listen.isVisible() and not page.history_panel.isHidden() and not hasattr(page,'history_toggle')
    QTest.mouseClick(card.sentences,Qt.LeftButton);assert page.audio_dialog.model.rowCount()==2
    assert all(page.audio_dialog.model.data(page.audio_dialog.model.index(n,6))=='' for n in range(2))
    window.resize(900,580);app.processEvents();assert not page.history_panel.isHidden()


def test_error_copy_traceback_redaction_and_deduplication(gui):
    app,window,page=gui
    def fail():raise RuntimeError('Missing dependency fixture; api_key=sk-1234567890abcdef password=fake-password')
    page.guard(fail);assert page.error_dialog.isVisible();page.error_dialog.copy()
    copied=QApplication.clipboard().text();assert 'Traceback' in copied and 'api_key=' in copied and 'sk-1234567890abcdef' not in copied and 'fake-password' not in copied
    count=len(page.error_dialog.seen);page.error_dialog.close();page.guard(fail);assert len(page.error_dialog.seen)==count and not page.error_dialog.isVisible()


def test_missing_history_folder_disables_open_and_offers_relink(gui,tmp_path,monkeypatch):
    app,window,page=gui;doc=add(page,tmp_path/'One.txt');captured=[]
    page.store.execute('UPDATE runs SET history_accepted=1 WHERE id=?',(page.run_id,));page.load_history()
    menu=page.history_panel.cards[doc['id']].context_menu();captured=[(i.text(),i.isEnabled()) for i in menu.actions()]
    assert ('Mở thư mục',False) in captured and ('Liên kết lại',True) in captured and page.store.doc(doc['id'])


def test_open_history_sentences_follow_resplit_without_replacing_card(gui,tmp_path):
    app,window,page=gui;doc=add(page,tmp_path/'Chapter.txt')
    page.store.execute('UPDATE runs SET history_accepted=1 WHERE id=?',(page.run_id,));page.load_history();card=page.history_panel.cards[doc['id']]
    page.open_sentences(doc['id']);assert page.audio_dialog.model.rowCount()==2
    page.split.setCurrentIndex(page.split.findData('none'));page.resplit()
    assert page.history_panel.cards[doc['id']]==card and page.audio_dialog.model.rowCount()==1
    assert page.audio_dialog.model.items[0]['text']==page.store.doc(doc['id'])['text']


def test_history_progress_updates_only_affected_card(gui,tmp_path,monkeypatch):
    app,window,page=gui;first=add(page,tmp_path/'First.txt');second=add(page,tmp_path/'Second.txt')
    page.store.execute('UPDATE runs SET history_accepted=1 WHERE id=?',(page.run_id,));page.load_history()
    card=page.history_panel.cards[first['id']];other=page.history_panel.cards[second['id']];page.open_sentences(first['id'])
    def unexpected(*args):raise AssertionError('Unchanged card must not refresh on another document progress')
    item=page.store.rows('SELECT * FROM segments WHERE document_id=? ORDER BY position',(first['id'],))[0]
    with monkeypatch.context() as scoped:
        scoped.setattr(other,'update_data',unexpected)
        page.store.execute("UPDATE segments SET state='running' WHERE id=?",(item['id'],));page.refresh_history([item['id']])
        assert page.audio_dialog.model.items[0]['state']=='running' and page.history_panel.cards[second['id']]==other
    page.store.execute("UPDATE segments SET state='pending' WHERE id=?",(item['id'],))


def test_continuous_playback_skips_unfinished_segments(gui,tmp_path):
    import numpy as np
    class Tone(FakeEngine):
        def synthesize(self,*args):yield np.tile(wave(),30)
    app,window,page=gui;page.scheduler.factory=Tone;doc=add(page,tmp_path/'Chapter.txt')
    page.start();wait(app,lambda:not page.is_busy())
    items=page.store.rows('SELECT * FROM segments WHERE document_id=? ORDER BY position',(doc['id'],))
    page.store.execute("UPDATE segments SET state='pending' WHERE id=?",(items[1]['id'],))
    page.play_document(doc['id']);wait(app,lambda:not page.is_busy());wait(app,lambda:page.playing is not None)
    assert len(page.player.entries)==1 and page.playing==items[0]['id']
    page.stop_playback()
