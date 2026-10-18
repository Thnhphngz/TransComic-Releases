"""Compact cards, local row focus and safe workspace clearing. No real API/media."""
from dataclasses import replace
from pathlib import Path
import hashlib
import re
import threading
import time
import pytest
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QStyle, QStyleOptionViewItem
from transcomic.capcut.state import GroupManager
from transcomic.capcut.media import scan_group, GroupScan
from transcomic.ui.capcut_media import RowDelegate, display_duration
from test_capcut_ui import page, wait
from test_capcut_single_page import populate, settle
from test_capcut_media import media_group


def choose_clear(app,p,confirm=False,key=None):
    seen=[]
    def choose():
        dialog=app.activeModalWidget()
        if not isinstance(dialog,QMessageBox):return
        seen.append((dialog.defaultButton().text(),dialog.escapeButton().text(),dialog.text(),dialog.informativeText()))
        if key:QTest.keyClick(dialog,key)
        else:
            text='Xóa toàn bộ nhóm' if confirm else 'Hủy'
            next(b for b in dialog.buttons() if b.text()==text).click()
    QTimer.singleShot(0,choose);p.clear_button.click();settle(app)
    assert seen and seen[0][:2]==('Hủy','Hủy')
    assert 'workspace' in seen[0][3] and 'project CapCut' in seen[0][3]
    return seen[0]


@pytest.mark.parametrize('dark',[False,True])
@pytest.mark.parametrize('count',[1,10,20])
def test_compact_group_rows_paths_in_inspector_and_toolbar(page,tmp_path,dark,count):
    app,w,p=page
    if w.dark!=dark:w.toggle_theme()
    group=populate(p,tmp_path,count)[0];p.show_group(group.id);settle(app)
    assert p.group_model.rowCount()==count
    assert p.groups.sizeHintForRow(0)==86
    assert group.image_dir in p.group_image_path.toolTip()
    assert group.audio_dir in p.group_audio_path.toolTip()
    assert p.group_summary.property('scanState')=='ready'
    buttons=[p.add_button,p.scan_button,p.clear_button]
    assert not hasattr(p,'expand_button') and not hasattr(p,'collapse_button')
    assert all(not a.geometry().intersects(b.geometry()) for i,a in enumerate(buttons) for b in buttons[i+1:])
    scan=p.scans[group.id];p.scans[group.id]=GroupScan(scan.group,scan.rows,('invalid folder',))
    p.render_groups();settle(app)
    assert p.group_summary.property('scanState')=='review'
    assert 'invalid folder' in p.group_summary.toolTip()


@pytest.mark.parametrize('dark',[False,True])
def test_local_focus_mouse_keyboard_and_display_only_format(page,tmp_path,dark):
    app,w,p=page
    if w.dark!=dark:w.toggle_theme()
    group=populate(p,tmp_path,1)[0];scan=p.scans[group.id]
    pair=replace(scan.rows[0],audios=(replace(scan.rows[0].audios[0],duration_us=8_874_667),))
    p.scans[group.id]=replace(scan,rows=(pair,*scan.rows[1:]));p.render_groups();p.show_group(group.id);settle(app)
    d=p.details;table=d.table
    assert re.fullmatch(r'\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}',d.model.index(0,4).data())
    assert d.proxy.index(0,4).data()=='00:08.875'
    assert p.scans[group.id].rows[0].duration_us==8_874_667
    index=d.proxy.index(0,2);table.scrollTo(index);settle(app)
    QTest.mouseClick(table.viewport(),Qt.LeftButton,pos=table.visualRect(index).center());settle(app)
    assert table.selectionModel().selectedRows()[0].row()==0 and len(table.selectionModel().selectedIndexes())==7
    assert not table.keyboard_focus and isinstance(table.itemDelegate(),RowDelegate)
    option=QStyleOptionViewItem();option.state=QStyle.State_HasFocus|QStyle.State_Selected|QStyle.State_Enabled
    table.itemDelegate().initStyleOption(option,index)
    assert not (option.state&QStyle.State_HasFocus) and option.state&QStyle.State_Selected
    if dark:
        shot=table.viewport().grab().toImage();ratio=shot.devicePixelRatio();rect=table.visualRect(index)
        pixels=[shot.pixelColor(int(x*ratio),int((rect.top()+2)*ratio)) for x in range(max(1,rect.left()+3),min(rect.right()-3,table.viewport().width()-1))]
        assert pixels and sum(min(c.red(),c.green(),c.blue())>215 for c in pixels)<len(pixels)*.2
    table.clearFocus();table.setFocus(Qt.TabFocusReason);QTest.keyClick(table,Qt.Key_Down);settle(app)
    assert table.keyboard_focus and table.currentIndex().row()==1 and table.hasFocus()
    QTest.keyClick(table,Qt.Key_Up);assert table.currentIndex().row()==0
    QTest.mouseClick(table.viewport(),Qt.LeftButton,pos=table.visualRect(index).center());assert not table.keyboard_focus


@pytest.mark.parametrize('microseconds,expected',[(8_874_667,'00:08.875'),(59_999_999,'01:00.000'),(3_600_000_001,'60:00.000'),(1000,'00:00.001')])
def test_duration_display_rounding_only(microseconds,expected):assert display_duration(microseconds)==expected


@pytest.mark.parametrize('key',[Qt.Key_Escape,Qt.Key_Return,None])
def test_cancel_default_escape_enter_does_not_change_workspace(page,tmp_path,key):
    app,w,p=page;groups=populate(p,tmp_path);p.show_group(groups[0].id);settle(app)
    before=p.store.setting('capcut_workspace_v1');scans=dict(p.scans);generation=p.generation
    info=choose_clear(app,p,key=key)
    assert '2 nhóm' in info[2] and p.store.setting('capcut_workspace_v1')==before
    assert p.scans==scans and p.generation==generation and p.selected_group_id==groups[0].id


@pytest.mark.parametrize('count',[1,20])
def test_clear_preserves_media_real_export_options_and_allows_new_groups(page,tmp_path,count,monkeypatch):
    from transcomic.ui.capcut_preview import CapcutPlayer
    app,w,p=page;groups=populate(p,tmp_path,count)
    p.output.setText(str(tmp_path/'projects'));p.mode.setCurrentIndex(1);p.project_name.setText('Project giữ nguyên');p.save_options()
    p.start_export();wait(app,p)
    paths=[f for g in groups for folder in (g.image_dir,g.audio_dir) for f in Path(folder).iterdir()]
    paths.extend(f for f in (tmp_path/'projects').rglob('*') if f.is_file())
    before={f:hashlib.sha256(f.read_bytes()).hexdigest() for f in paths}
    monkeypatch.setattr(CapcutPlayer,'play',lambda *args:None)
    p.show_group(groups[0].id);d=p.details;d.search.setText('001')
    d.table.setCurrentIndex(d.proxy.index(0,0));d.invoke_action(d.proxy.index(d.table.currentIndex().row(),6),0);player=p.player
    assert p.active_details is d
    choose_clear(app,p,confirm=True)
    assert not p.manager.groups and p.group_model.rowCount()==0 and not p.scans and p.selected_group_id is None
    assert p.active_details is None and player.isHidden() and player.player.source().isEmpty() and player.entries==[]
    assert d.selected_pair is None and d.preview_file is None and d.scan is None
    assert p.totals.text().startswith('0 nhóm · 0 ảnh · 0 voice') and not p.clear_button.isEnabled()
    assert not p.thumbs.cache and not p.preview_cache.cache
    restored=GroupManager(p.store)
    assert not restored.groups and restored.mode=='merged' and restored.name=='Project giữ nguyên' and restored.output==str(tmp_path/'projects')
    assert all(f.exists() and hashlib.sha256(f.read_bytes()).hexdigest()==digest for f,digest in before.items())
    fresh=media_group(tmp_path/'new',1);p.manager.add(fresh);p.render_groups();p.scan_all();wait(app,p)
    assert p.scans[fresh.id].valid and p.clear_button.isEnabled()


def test_clear_scan_generation_rejects_late_result_and_progress(page,tmp_path,monkeypatch):
    import transcomic.ui.capcut_page as module
    app,w,p=page;groups=populate(p,tmp_path,1);old_scan=p.scans[groups[0].id]
    entered=threading.Event();release=threading.Event()
    def delayed(group,cancel):
        entered.set();release.wait(5);return old_scan  # Deliberately ignores cancellation.
    monkeypatch.setattr(module,'scan_group',delayed);p.scan_all();old_worker=p.worker;generation=p.generation
    assert entered.wait(1) and p.operation=='scan' and p.clear_button.isEnabled()
    try:
        choose_clear(app,p,confirm=True);assert p.cancel.is_set() and not p.busy
        fresh=media_group(tmp_path/'new',1);p.manager.add(fresh);p.render_groups()
        monkeypatch.setattr(module,'scan_group',scan_group);p.scan_all();wait(app,p)
        status=p.status.text();progress=p.bar.value()
        p.scan_progress.emit(generation,99,'stale scan progress');p.completed.emit(generation,('scan',(old_scan,)),'')
        release.set();old_worker.join(2);settle(app)
        assert set(p.scans)=={fresh.id} and [item[0].id for item in p.group_model.items]==[fresh.id]
        assert p.status.text()==status and p.bar.value()==progress
        assert p.generation>generation and [g.id for g in GroupManager(p.store).groups]==[fresh.id]
    finally:release.set();old_worker.join(2)


@pytest.mark.parametrize('cancel',[False,True])
def test_clear_blocked_during_export_then_reenabled(page,tmp_path,monkeypatch,cancel):
    from transcomic.capcut.media import checkpoint
    app,w,p=page;groups=populate(p,tmp_path,1);release=threading.Event()
    def export(cancel):release.wait(5);checkpoint(cancel);return ('export',(tmp_path/'existing'/'project',))
    called=[];monkeypatch.setattr(p,'confirm_clear_all',lambda:called.append(1) or True)
    p.launch(export);assert p.operation=='export' and not p.clear_button.isEnabled()
    try:
        p.clear_all();p.clear_workspace();assert not called and p.manager.groups==groups
        if cancel:p.request_stop()
        release.set();wait(app,p);assert p.clear_button.isEnabled() and p.manager.groups==groups
    finally:release.set();wait(app,p)


def test_clear_save_failure_keeps_current_state(page,tmp_path,monkeypatch):
    app,w,p=page;groups=populate(p,tmp_path,1);p.show_group(groups[0].id);scans=dict(p.scans)
    before=p.store.setting('capcut_workspace_v1');generation=p.generation
    def fail():raise OSError('simulated save failure')
    monkeypatch.setattr(p.manager,'save',fail);choose_clear(app,p,confirm=True)
    assert p.manager.groups==groups and p.scans==scans and p.generation==generation
    assert p.store.setting('capcut_workspace_v1')==before and 'save failure' in p.status.text()


def test_restart_does_not_restore_cleared_groups(page,tmp_path):
    from transcomic.storage import Store
    from transcomic.ui.main import MainWindow
    app,w,p=page;populate(p,tmp_path,1);choose_clear(app,p,confirm=True);path=p.store.path
    w._exit_authorized=True;w.close();settle(app)
    restored=MainWindow(Store(path));restored.show();restored.pages.setCurrentIndex(8);settle(app)
    try:assert not restored.capcut_page.manager.groups and restored.capcut_page.group_model.rowCount()==0 and not restored.capcut_page.clear_button.isEnabled()
    finally:restored._exit_authorized=True;restored.close();settle(app)
