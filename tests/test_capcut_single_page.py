"""CPU-only acceptance for the shared two-column CapCut inspector."""
from dataclasses import replace
from pathlib import Path
import threading,time
import pytest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QTabWidget
from transcomic.capcut.media import scan_group,GroupScan
from transcomic.ui.capcut_import import MultiGroupDialog
from test_capcut_ui import page,wait
from test_capcut_media import media_group


def populate(p,tmp_path,count=2):
    groups=[media_group(tmp_path/f'g{i}',3,f'Nhóm {i}') for i in range(count)]
    p.manager.add_many(groups);p.scans={g.id:scan_group(g) for g in groups};p.render_groups()
    return groups


def settle(app):
    for _ in range(5):app.processEvents();time.sleep(.005)


def click_group(app,p,id):
    row=next(i for i,item in enumerate(p.group_model.items) if item[0].id==id)
    index=p.group_proxy.mapFromSource(p.group_model.index(row,0));p.groups.scrollTo(index);settle(app)
    QTest.mouseClick(p.groups.viewport(),Qt.LeftButton,pos=p.groups.visualRect(index).center());settle(app)


@pytest.mark.parametrize('dark',[False,True])
def test_selection_search_order_navigation_and_settings(page,tmp_path,dark):
    app,w,p=page
    if w.dark!=dark:w.toggle_theme()
    a,b=populate(p,tmp_path);settle(app)
    assert not p.findChildren(QTabWidget) and p.selected_group_id is None
    assert p.details.model.rowCount()==0 and p.inspector.currentWidget() is p.inspector_empty
    scans=dict(p.scans);generation=p.generation;details=p.details
    for group in (a,b,a):
        click_group(app,p,group.id)
        assert p.selected_group_id==group.id and p.details is details and details.proxy.rowCount()==3
        assert details.scan is p.scans[group.id] and group.image_dir in p.group_image_path.toolTip()
    assert p.player is None and p.scans==scans and p.generation==generation
    p.move_group(b.id,-1);settle(app)
    assert p.group_model.index(0,0).data(Qt.UserRole)==b.id and p.selected_group_id==a.id
    p.group_search.setText(b.name);assert p.group_proxy.rowCount()==1 and p.selected_group_id is None
    click_group(app,p,b.id);p.group_search.clear()
    assert p.selected_group_id==b.id and [i[0].id for i in p.group_model.items]==[b.id,a.id]
    w.pages.setCurrentIndex(0);w.pages.setCurrentIndex(8);settle(app)
    assert p.selected_group_id==b.id and p.details is details
    assert p.export_button.isVisible() and p.settings_frame.geometry().bottom()<p.height()


def test_errors_search_preview_dates_and_filter(page,tmp_path):
    app,w,p=page;a,b=populate(p,tmp_path)
    Path(a.audio_dir,'003.wav').unlink();Path(a.image_dir,'002.png').write_bytes(b'bad image')
    p.scans[a.id]=scan_group(a);p.render_groups();p.show_group(a.id);d=p.details
    assert p.group_summary.property('scanState')=='review' and d.notice.text()
    d.errors.setCurrentIndex(1);assert d.proxy.rowCount()==3
    d.search.setText('002.png');assert d.proxy.rowCount()==1
    d.search.setText('not-present');assert d.proxy.rowCount()==0
    p.show_group(b.id);assert d.proxy.rowCount()==3 and not d.search.text() and d.errors.currentIndex()==0
    assert d.proxy.columnCount()==7 and not hasattr(d,'created_toggle')
    assert d.model.index(0,4).data()!='Không xác định'
    assert d.proxy.headerData(0,Qt.Horizontal)=='STT' and d.proxy.index(0,0).data()=='1'
    d.table.setCurrentIndex(d.proxy.index(0,0));assert d.selected_pair.group_id==b.id
    d.invoke_action(d.proxy.index(0,6),1);assert d.preview.isVisible()
    end=time.monotonic()+3
    while not d.preview.pixmap() and time.monotonic()<end:app.processEvents();time.sleep(.01)
    assert d.preview.pixmap() and not d.preview.pixmap().isNull()
    p.show_group(a.id);assert d.selected_pair is None and d.preview_file is None


def test_sort_edit_delete_preserve_stable_id_and_sources(page,tmp_path,monkeypatch):
    app,w,p=page;a,b=populate(p,tmp_path);p.show_group(a.id);d=p.details
    d.search.setText('001');p.group_sort.setCurrentIndex(1);assert p.busy and d.model.rowCount()==0
    wait(app,p);assert p.selected_group_id==a.id and d.proxy.rowCount()==1
    assert p.scans[a.id].group.image_sort=='created'
    def execute(dialog):dialog.entries[0].name.setText('Đã đổi tên');dialog.accept();return dialog.result()
    monkeypatch.setattr(MultiGroupDialog,'exec',execute);p.group_edit.click();wait(app,p)
    assert p.selected_group_id==a.id and 'Đã đổi tên' in p.group_heading.full
    image=Path(a.image_dir,'001.png');original=image.read_bytes();p.group_remove.click();settle(app)
    assert p.selected_group_id is None and p.details.model.rowCount()==0
    assert a.id not in p.scans and p.group_model.rowCount()==1
    assert image.read_bytes()==original and Path(a.audio_dir,'001.wav').exists()


def test_shared_audio_stop_switch_hide_delete_close(page,tmp_path,monkeypatch):
    from transcomic.ui.capcut_preview import CapcutPlayer
    app,w,p=page;a,b=populate(p,tmp_path);plays=[]
    monkeypatch.setattr(CapcutPlayer,'play',lambda self,entries:plays.append(entries))
    p.show_group(a.id);d=p.details;d.table.setCurrentIndex(d.proxy.index(0,0));d.invoke_action(d.proxy.index(d.table.currentIndex().row(),6),0);player=p.player
    assert plays[-1][0][0]==p.scans[a.id].rows[0].audios[0].path
    p.show_group(b.id);assert player.isHidden() and player.player.source().isEmpty() and d.selected_pair is None
    d.table.setCurrentIndex(d.proxy.index(1,0));d.invoke_action(d.proxy.index(d.table.currentIndex().row(),6),0);assert p.player is player
    assert len(p.findChildren(CapcutPlayer))==1 and plays[-1][0][0]==p.scans[b.id].rows[1].audios[0].path
    w.pages.setCurrentIndex(0);assert player.isHidden() and p.active_details is None
    w.pages.setCurrentIndex(8);p.remove_group(b.id);assert player.parent() is p and not player.entries
    p.show_group(a.id);d.table.setCurrentIndex(d.proxy.index(0,0));d.invoke_action(d.proxy.index(d.table.currentIndex().row(),6),0)
    w._exit_authorized=True;w.close();settle(app)
    from shiboken6 import isValid
    assert w._closed and p.closed and not isValid(player)
    assert p.thumbs.stop.is_set() and p.preview_cache.stop.is_set()


@pytest.mark.parametrize('count,rows',[(10,184),(20,184),(100,1000)])
def test_virtual_groups_and_media_bounded_workers(page,tmp_path,count,rows):
    app,w,p=page;groups=populate(p,tmp_path,count)
    for g in groups:
        scan=p.scans[g.id];p.scans[g.id]=GroupScan(g,tuple(replace(scan.rows[0],id=f'{g.id}:{n}',number=n) for n in range(1,rows+1)))
    p.render_groups();generation=p.generation;workers={p.thumbs.thread,p.preview_cache.thread};details=p.details
    for group in [*groups[:5],groups[-1],groups[0],groups[-1]]:
        p.show_group(group.id);settle(app)
        assert p.details is details and details.proxy.rowCount()==rows
        assert details.model.thumbs is p.thumbs and len(p.findChildren(type(details)))==1
    details.table.scrollToBottom();settle(app)
    assert details.table.rowAt(max(1,details.table.viewport().height()-20))>=rows-5
    details.search.setText(str(rows));assert details.proxy.rowCount()>=1
    assert p.generation==generation and p.player is None
    assert len(p.thumbs.cache)<=128 and len(p.thumbs.pending)<=32 and len(p.preview_cache.cache)<=2
    p.shutdown()
    for worker in workers:worker.join(1);assert not worker.is_alive()


@pytest.mark.parametrize('dark',[False,True])
@pytest.mark.parametrize('size',[(1280,720),(1600,900),(1920,1080)])
def test_two_column_geometry_sidebar_splitter_and_hit_targets(page,tmp_path,dark,size):
    app,w,p=page
    if w.dark!=dark:w.toggle_theme()
    a,b=populate(p,tmp_path);p.show_group(a.id)
    long=replace(a,name='Chương rất dài '*25,image_dir=a.image_dir+'\\long-path'*50,audio_dir=a.audio_dir+'\\long-path'*50)
    p.manager.replace(long);p.render_groups();p.mode.setCurrentIndex(2);w.resize(*size);settle(app)
    assert w.width()==size[0] and w.height()==size[1]
    assert p.group_image_path.toolTip().endswith('long-path') and p.group_image_path.text()!=p.group_image_path.full
    assert p.workspace.widget(0).geometry().right()<p.workspace.widget(1).geometry().left()
    assert p.settings_frame.geometry().top()>p.workspace.geometry().bottom()
    assert p.settings_frame.geometry().bottom()<p.height() and p.export_button.isVisible()
    assert p.details.table.height()>=100
    handle=p.workspace.handle(1)
    QTest.mousePress(handle,Qt.LeftButton,pos=handle.rect().center())
    QTest.mouseMove(handle,QPoint(65,handle.height()//2));QTest.mouseRelease(handle,Qt.LeftButton);settle(app)
    assert min(p.workspace.sizes())>=220
    p.workspace.setSizes([240,1000]);settle(app);before=p.workspace.sizes()
    p.show_group(b.id);assert p.workspace.sizes()==before
    assert len(w.nav_buttons)==9
    w.toggle_sidebar();settle(app);w.toggle_sidebar();settle(app)
    assert p.selected_group_id==b.id and p.workspace.widget(1).width()>=310
    p.settings_toggle.setChecked(False);p.settings_toggle.click();settle(app);assert not p.settings_body.isVisible() and p.export_button.isVisible()
    p.settings_toggle.click();settle(app);assert p.settings_body.isVisible()
