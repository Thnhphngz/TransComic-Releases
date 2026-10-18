import os,time
import pytest
from PySide6.QtWidgets import QApplication
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from test_capcut_media import media_group


@pytest.fixture
def page(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'state.db');window=MainWindow(store);window.resize(1200,850);window.show()
    window.pages.setCurrentIndex(8);app.processEvents();p=window.capcut_page
    yield app,window,p
    from shiboken6 import isValid
    if isValid(window):
        p.request_stop()
        while p.is_busy():app.processEvents();time.sleep(.01)
        window._exit_authorized=True;window.close();app.processEvents()


def wait(app,p):
    end=time.monotonic()+10
    while p.is_busy() and time.monotonic()<end:app.processEvents();time.sleep(.005)
    app.processEvents();assert not p.is_busy()


@pytest.mark.parametrize('dark',[False,True])
def test_page_pair_details_filter_preview_and_order(page,tmp_path,dark):
    app,w,p=page
    if w.dark!=dark:w.toggle_theme()
    a=media_group(tmp_path/'a',3,'Nhóm A');b=media_group(tmp_path/'b',2,'Nhóm B')
    p.manager.add(a);p.manager.add(b);p.render_groups();p.scan_all();wait(app,p)
    assert p.group_model.rowCount()==2 and p.selected_group_id is None
    p.show_group(b.id);d=p.details;assert d.proxy.rowCount()==2
    d.table.setCurrentIndex(d.proxy.index(0,0));app.processEvents();assert d.selected_pair.group_id==b.id
    p.move_group(b.id,-1);assert p.manager.groups[0].id==b.id
    d.errors.setCurrentIndex(1);assert d.proxy.rowCount()==0
    p.remove_group(a.id);assert p.group_model.rowCount()==1
    assert len(w.nav_buttons)==9 and p.thumbs.limit==128
    assert p.player is None  # Selection never automatically starts audio/TTS.


def test_cancel_scan_keeps_groups(page,tmp_path):
    app,w,p=page;p.manager.add(media_group(tmp_path/'a',30));p.render_groups();p.scan_all();p.request_stop();wait(app,p)
    assert len(p.manager.groups)==1 and 'hủy' in p.status.text()


@pytest.mark.parametrize('mode',['separate','merged'])
def test_real_export_button_and_async_worker(page,tmp_path,mode):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    app,w,p=page
    for i in range(3):p.manager.add(media_group(tmp_path/f'g{i}',2,f'Nhóm {i}'))
    p.render_groups();p.scan_all();wait(app,p)
    p.output.setText(str(tmp_path/'project output'));p.mode.setCurrentIndex(1 if mode=='merged' else 0)
    QTest.mouseClick(p.export_button,Qt.LeftButton)
    assert p.is_busy() and not p.add_button.isEnabled()
    wait(app,p)
    outputs=list((tmp_path/'project output').glob('*/draft_content.json'))
    assert len(outputs)==(1 if mode=='merged' else 3)
    assert p.bar.value()==100 and 'Đã xuất' in p.status.text()


def test_lazy_thumbnails_and_user_triggered_audio(page,tmp_path,monkeypatch):
    from transcomic.tts.player import AudioPlayer
    app,w,p=page;p.manager.add(media_group(tmp_path/'a',3));p.render_groups();p.scan_all();wait(app,p);p.show_group(p.manager.groups[0].id);d=p.details
    d.table.setCurrentIndex(d.proxy.index(0,0));app.processEvents()
    end=time.monotonic()+3
    while not d.preview.pixmap() and time.monotonic()<end:app.processEvents();time.sleep(.01)
    assert d.preview.pixmap() and not d.preview.pixmap().isNull()
    observed=[];monkeypatch.setattr(AudioPlayer,'play',lambda self,entries,index=0:observed.extend(entries))
    assert not observed;d.invoke_action(d.proxy.index(d.table.currentIndex().row(),6),0);assert len(observed)==1
    assert observed[0][0]==d.selected_pair.audios[0].path;p.stop_audio()


def test_virtual_thousands_filter_and_bounded_cache(page,tmp_path):
    from dataclasses import replace
    from transcomic.capcut.media import scan_group,GroupScan
    app,w,p=page;group=media_group(tmp_path/'a',1);scan=scan_group(group)
    pairs=tuple(replace(scan.rows[0],id=f'{group.id}:{i}',number=i) for i in range(1,3001))
    p.manager.add(group);p.scans[group.id]=GroupScan(group,pairs);p.render_groups();p.refresh_details();p.show_group(group.id);d=p.details
    assert d.proxy.rowCount()==3000
    d.search.setText('2999');assert d.proxy.rowCount()==1
    d.search.clear();d.table.scrollToBottom();app.processEvents()
    assert len(p.thumbs.cache)<=128 and len(p.thumbs.pending)<=32
    w.resize(950,620);app.processEvents()
    assert w.height()<=620 and p.width()<=w.width()
