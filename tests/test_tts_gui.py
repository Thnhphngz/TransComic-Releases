"""File-first GUI workflows; all network/model inference mocked here.

Real entrypoint/inference/playback coverage lives in the opt-in source smoke.
"""
import json
import time
import threading
from pathlib import Path
import pytest
from PySide6.QtCore import Qt,QMimeData,QUrl,QPointF
from PySide6.QtGui import QDropEvent,QDragEnterEvent
from PySide6.QtWidgets import QApplication,QFileDialog,QMessageBox,QPushButton
from PySide6.QtTest import QTest
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.ui.tts_page import TtsPage
from tests.test_tts import FakeEngine,wave


def wait(app,predicate,seconds=20):
    end=time.monotonic()+seconds
    while not predicate() and time.monotonic()<end:app.processEvents();QTest.qWait(10);time.sleep(.003)
    app.processEvents();assert predicate()


@pytest.fixture
def gui(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(TtsPage,'check_runtime',lambda self:setattr(self,'runtime_ready',True))
    window=MainWindow(Store(tmp_path/'translation.sqlite3'));window.resize(1200,780);window.show();window.pages.setCurrentIndex(7);app.processEvents();page=window.tts_page
    page.scheduler.factory=FakeEngine;monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.Yes)
    monkeypatch.setattr(page,'confirm_clear_history',lambda:True)
    yield app,window,page
    if not window._closed:page.request_stop();wait(app,lambda:not page.is_busy());window.close();wait(app,lambda:window._closed)


def add(page,path,text='First\nSecond'):
    path.write_text(text,encoding='utf8');page.import_paths([path]);wait(QApplication.instance(),lambda:not page.is_busy());return page.store.docs(page.run_id)[-1]


def test_files_are_documents_details_scoped_and_removed_buttons(gui,tmp_path):
    app,window,page=gui
    one=add(page,tmp_path/'One.txt','\n'.join(f'Line {i}' for i in range(2000)));two=add(page,tmp_path/'Two.txt')
    assert page.document_model.rowCount()==2 and page.model.rowCount()==0
    assert page.document_model.data(page.document_model.index(0,3))==2000
    page.open_details(two['id']);assert page.model.rowCount()==2 and page.tabs.currentIndex()==2
    assert all(i['document_id']==two['id'] for i in page.model.items)
    page.tabs.setCurrentIndex(0);assert page.document_model.rowCount()==2
    removed={'Gộp','Chia','Tên thư mục / sửa nguồn','Mẫu tên','Dán văn bản','Tiếp tục CPU','Xem trước / Xác nhận','Bắt đầu / Tiếp tục'}
    assert not removed.intersection(b.text() for b in page.findChildren(QPushButton))
    assert [page.tabs.tabText(i) for i in range(3)]==['TTS Hàng Loạt','Nhập văn bản','Chi tiết']
    assert page.mode.count()==2 and not hasattr(page,'device') and page.player.isHidden()


def test_beside_start_no_picker_and_frozen_config(gui,tmp_path,monkeypatch):
    app,window,page=gui;add(page,tmp_path/'Chapter.txt')
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *args:pytest.fail('Beside must not open picker'))
    assert page.start_button.isEnabled() and page.start_button.text()=='Bắt đầu'
    QTest.mouseClick(page.start_button,Qt.LeftButton);config=page.store.run(page.run_id)['config'];page.speed.setValue(2)
    wait(app,lambda:not page.is_busy());page.refresh();assert (tmp_path/'Chapter_2tts'/'0002.wav').exists()
    assert json.loads(config)['speed']==1 and page.store.run(page.run_id)['config']==config
    assert page.start_button.text()=='Hoàn tất' and not page.start_button.isEnabled()


def test_custom_cancel_no_writes_then_start(gui,tmp_path,monkeypatch):
    app,window,page=gui;add(page,tmp_path/'Chapter.txt');page.mode.setCurrentIndex(page.mode.findData('custom'))
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *args:'');page.start()
    assert page.store.run(page.run_id)['state']=='draft' and not list(tmp_path.glob('*inprogress'))
    root=tmp_path/'chosen';root.mkdir();monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *args:str(root));page.start();wait(app,lambda:not page.is_busy())
    assert (root/'Chapter_2tts'/'0001.wav').is_file() and not (tmp_path/'Chapter_2tts').exists()


def test_input_counts_literal_split_cancel_and_output(gui,tmp_path,monkeypatch):
    app,window,page=gui;page.tabs.setCurrentIndex(1);page.input_text.setPlainText('Mr. Smith 3.14!\nNext?');page.input_name.setText('Pasted')
    page.split.setCurrentIndex(page.split.findData('sentences'));page.resplit();assert '4 đoạn' in page.input_counts.text()
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *args:'');page.start();assert not page.store.docs(page.run_id)
    root=tmp_path/'paste';root.mkdir();monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *args:str(root));page.start();wait(app,lambda:not page.is_busy())
    assert len(list((root/'Pasted_4tts').glob('*.wav')))==4


def test_painted_detail_click_exact_document(gui,tmp_path):
    app,window,page=gui;add(page,tmp_path/'One.txt');two=add(page,tmp_path/'Two.txt');page.tabs.setCurrentIndex(0);app.processEvents()
    index=page.document_model.index(1,8);page.file_table.scrollTo(index);app.processEvents();rect=page.file_table.visualRect(index)
    QTest.mouseClick(page.file_table.viewport(),Qt.LeftButton,pos=rect.center());assert page.detail_document==two['id']


def test_history_audio_without_tab_switch_collapse_stops(gui,tmp_path,monkeypatch):
    # A 100 ms tone may already have ended by the time a loaded full suite
    # processes this assertion. Test actual PlayingState with a long fixture;
    # a nonempty source alone does not mean playback is still active.
    class LongAudio(FakeEngine):
        def synthesize(self,*args):
            import numpy as np
            yield np.tile(wave(),30)
    app,window,page=gui;page.scheduler.factory=LongAudio;doc=add(page,tmp_path/'Chapter.txt');page.start();wait(app,lambda:not page.is_busy());page.load_history()
    assert page.history_document==doc['id'] and page.audio_model.rowCount()==2 and '2/2 audio' in page.history_panel.cards[doc['id']].meta.text()
    ids=[i['id'] for i in page.audio_model.items]
    page.play_segment(ids[0]);wait(app,lambda:not page.is_busy());wait(app,lambda:not page.player.player.source().isEmpty())
    wait(app,lambda:page.playing==ids[0])
    assert page.tabs.currentIndex()==0 and page.audio_model.data(page.audio_model.index(0,2))=='Dừng'
    page.play_segment(ids[0]);assert page.player.player.source().isEmpty()
    page.play_segment(ids[1]);wait(app,lambda:not page.is_busy());page.stop_playback();assert page.player.isHidden() and page.player.player.source().isEmpty()
    assert not page.history_panel.isHidden() and not hasattr(page,'history_toggle')
    folder=Path(page.store.doc(doc['id'])['folder']);page.delete_history();assert (folder/'0001.wav').exists()


def test_paused_old_without_confirmation_can_start(gui,tmp_path):
    app,window,page=gui;doc=add(page,tmp_path/'Legacy.txt');run=page.run_id
    page.store.execute("UPDATE runs SET state='paused',error='No module named onnxruntime' WHERE id=?",(run,))
    ids=[i['id'] for i in page.store.items(run)];page.start();wait(app,lambda:not page.is_busy())
    assert page.store.run(run)['state']=='completed' and [i['id'] for i in page.store.items(run)]==ids
    assert (tmp_path/'Legacy_2tts'/'0001.wav').is_file()


def test_drag_drop_many_and_invalid_format(gui,tmp_path):
    app,window,page=gui;folder=tmp_path/'inputs';folder.mkdir()
    for n in range(12):(folder/f'{n}.txt').write_text('Hello',encoding='utf8')
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(folder))]);view=page.file_table.viewport()
    drag=QDragEnterEvent(view.rect().center(),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(view,drag);assert drag.isAccepted()
    drop=QDropEvent(QPointF(view.rect().center()),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(view,drop);assert drop.isAccepted()
    wait(app,lambda:not page.is_busy());assert page.document_model.rowCount()==12
    page.import_paths([folder]);wait(app,lambda:not page.is_busy());assert page.document_model.rowCount()==12
    bad=tmp_path/'bad.pdf';bad.write_bytes(b'fixture');page.import_paths([bad]);wait(app,lambda:not page.is_busy());assert 'Chỉ hỗ trợ' in page.notice.text()


def test_split_job_snapshot_and_edit_details(gui,tmp_path):
    app,window,page=gui;doc=add(page,tmp_path/'Split.txt','Mr. Smith 3.14!\nNext?')
    assert page.document_model.data(page.document_model.index(0,4))==2
    page.split.setCurrentIndex(page.split.findData('sentences'));page.resplit();assert page.document_model.data(page.document_model.index(0,4))==4
    page.open_details(doc['id']);index=page.model.index(0,1);assert page.model.setData(index,'Edited',Qt.EditRole)
    page.start();wait(app,lambda:not page.is_busy());ids=[i['id'] for i in page.store.items(page.run_id)]
    page.split.setCurrentIndex(page.split.findData('lines'));page.resplit();assert [i['id'] for i in page.store.items(page.run_id)]==ids


def test_missing_runtime_message_and_frozen_repair(gui,monkeypatch):
    app,window,page=gui;page.runtime_ready=False;page.start();assert 'Cài đặt' in page.notice.text() and page.settings_dialog.isVisible()
    monkeypatch.setattr('sys.frozen',True,raising=False);page.repair_runtime();assert 'Bộ cài thiếu runtime' in page.notice.text()


def test_read_error_stays_visible_and_retry_keeps_other_documents(gui,tmp_path):
    app,window,page=gui;good=add(page,tmp_path/'Good.txt');bad=tmp_path/'Broken.docx';bad.write_bytes(b'not a zip')
    page.import_paths([bad]);wait(app,lambda:not page.is_busy());assert page.document_model.rowCount()==2
    issue=page.document_model.items[-1];assert issue['import_error'] and page.document_model.data(page.document_model.index(1,8))=='Đọc lại'
    from docx import Document
    fixed=Document();fixed.add_paragraph('Now readable');fixed.save(bad)
    page.open_details(issue['id']);wait(app,lambda:not page.is_busy());assert page.document_model.rowCount()==2
    assert not any(i.get('import_error') for i in page.document_model.items) and page.store.doc(good['id'])


def test_progress_does_not_reload_all_segments(gui,tmp_path,monkeypatch):
    app,window,page=gui;doc=add(page,tmp_path/'Large.txt','\n'.join(f'Line {i}' for i in range(2000)));page.open_details(doc['id'])
    page.model.items[100]['text']='Visible editor snapshot';id=page.model.items[0]['id'];page.pending_items.add(id)
    original=page.store.rows;queries=[]
    def rows(sql,args=()):queries.append(sql);return original(sql,args)
    monkeypatch.setattr(page.store,'rows',rows);page.flush_items()
    assert not any('SELECT * FROM segments WHERE document_id=? ORDER BY' in q or 'SELECT s.*' in q for q in queries)
    assert page.model.items[100]['text']=='Visible editor snapshot'


def test_history_insert_out_of_order_keeps_persistent_row(gui):
    from PySide6.QtCore import QPersistentModelIndex
    app,window,page=gui;model=page.audio_model;model.replace([dict(id='two',filename='0002.wav',duration=1,text='Two')])
    stable=QPersistentModelIndex(model.index(0,0));resets=[];model.modelReset.connect(lambda:resets.append(True))
    model.replace([dict(id='one',filename='0001.wav',duration=1,text='One'),dict(id='two',filename='0002.wav',duration=1,text='Two'),dict(id='three',filename='0003.wav',duration=1,text='Three')])
    assert not resets and stable.isValid() and stable.row()==1 and stable.data()=='0002.wav'
