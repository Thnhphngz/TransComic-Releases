"""Pinned views and compact panel geometry; isolated data, mock HTTP/PCM only."""
import copy
import os
from pathlib import Path
import pytest
from PySide6.QtCore import Qt,QPoint,QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication,QAbstractItemView,QMessageBox,QFileDialog,QInputDialog
from PySide6.QtTest import QTest
from test_automation_ui import gui,wait
from test_automation import add_group,FakeEngine
from transcomic.ui.automation_page import group_button_rects


@pytest.mark.parametrize('dark',[False,True])
@pytest.mark.parametrize('expanded',[False,True])
@pytest.mark.parametrize('size',[(900,580),(1200,780),(1672,941)])
def test_pinned_actions_and_numbers_survive_sidebar_resize_scroll_and_filter(gui,tmp_path,dark,expanded,size):
    app,w,p,id=gui;w.resize(*size)
    if w.dark!=dark:w.toggle_theme()
    if (w.sidebar.width()>100)!=expanded:w.toggle_sidebar()
    gid,_,_=add_group(p.repo,id,tmp_path/'g');p.refresh();app.processEvents();p.timer.stop();assert p.snapshots.wait_for_idle()
    # Stress the view only, without creating 200 files or issuing work.
    prototype=p.model.rows[0];rows=[]
    for n in range(200):
        row=copy.deepcopy(prototype);row.update(id=f'view-{n}',position=n,sequence=n+1);rows.append(row)
    p.model.update(rows);app.processEvents()
    assert w.sidebar.width()==(200 if expanded else 72)
    assert not p.right_scroll.horizontalScrollBar().isVisible()
    for pane,column in ((p.number_table,0),(p.action_table,6)):
        assert pane.isVisible() and p.table_shell.rect().contains(pane.geometry())
        assert pane.viewport().rect().contains(pane.visualRect(p.model.index(0,column)))
    assert p.action_table.geometry().right()==p.table_shell.content.width()-1
    assert p.table.selectionModel() is p.action_table.selectionModel() is p.number_table.selectionModel()
    assert p.table.horizontalScrollMode()==QAbstractItemView.ScrollPerPixel
    bar=p.table.horizontalScrollBar();p.table.setColumnWidth(2,600);app.processEvents();bar.setValue(bar.maximum()//2)
    p.action_table.verticalScrollBar().setValue(777);app.processEvents()
    assert len({pane.verticalScrollBar().value() for pane in p.table_panes})==1
    row=p.table.rowAt(20);assert row>=0
    rect=p.action_table.visualRect(p.model.index(row,6))
    assert all(pane.visualRect(p.model.index(row,column)).top()==rect.top() for pane,column in ((p.number_table,0),(p.table,1)))
    received=[];p.action_table.action_clicked.disconnect();p.action_table.action_clicked.connect(lambda *a:received.append(a))
    for region,action in zip(group_button_rects(rect),('images','editor','remove')):
        assert p.action_table.viewport().rect().contains(region)
        QTest.mouseClick(p.action_table.viewport(),Qt.LeftButton,pos=region.center())
        assert received[-1]==(f'view-{row}',action)
    check=p.number_table.visualRect(p.model.index(row,0));QTest.mouseClick(p.number_table.viewport(),Qt.LeftButton,pos=check.center())
    assert p.number_table.selectionModel().isRowSelected(row) and p.model.index(row,0).data()==row+1
    # Model reset/filter still routes through the visible row's stable ID.
    p.model.update([rows[157],rows[12]]);app.processEvents()
    rect=p.action_table.visualRect(p.model.index(0,6));QTest.mouseClick(p.action_table.viewport(),Qt.LeftButton,pos=group_button_rects(rect)[2].center())
    assert received[-1]==('view-157','remove')


def test_pixel_shift_wheel_and_trackpad_delta_do_not_resize_headers_or_move_actions(gui,tmp_path):
    app,w,p,id=gui;add_group(p.repo,id,tmp_path/'g');p.refresh();app.processEvents()
    p.table.setColumnWidth(2,700);app.processEvents();bar=p.table.horizontalScrollBar();bar.setValue(200)
    widths=[p.table.columnWidth(i) for i in range(1,6)];action=p.action_table.geometry()
    for pixel,angle,mod,expected in ((QPoint(-17,0),QPoint(),Qt.NoModifier,217),(QPoint(),QPoint(0,-120),Qt.ShiftModifier,289)):
        event=QWheelEvent(QPointF(30,50),QPointF(30,50),pixel,angle,Qt.NoButton,mod,Qt.NoScrollPhase,False)
        QApplication.sendEvent(p.table.viewport(),event);app.processEvents()
        assert bar.value()==expected and event.isAccepted()
        assert p.action_table.geometry()==action and [p.table.columnWidth(i) for i in range(1,6)]==widths
    p.number_table.setFocus(Qt.TabFocusReason);p.number_table.setCurrentIndex(p.model.index(0,0))
    QTest.keyClick(p.number_table,Qt.Key_Tab);assert p.table.hasFocus()
    QTest.keyClick(p.table,Qt.Key_Tab);assert p.action_table.hasFocus()
    selected=[];p.action_table.action_clicked.disconnect();p.action_table.action_clicked.connect(lambda *a:selected.append(a))
    QTest.keyClick(p.action_table,Qt.Key_Right);QTest.keyClick(p.action_table,Qt.Key_Return)
    assert selected[-1][1]=='editor'
    QTest.keyClick(p.action_table,Qt.Key_Tab);assert QApplication.focusWidget() not in p.table_panes
    p.number_table.setFocus(Qt.TabFocusReason);QTest.keyClick(p.number_table,Qt.Key_Backtab)
    assert QApplication.focusWidget() not in p.table_panes


@pytest.mark.parametrize('dark',[False,True])
def test_pinned_buttons_execute_real_pair_open_and_remove_on_filtered_id(gui,tmp_path,monkeypatch,dark):
    app,w,p,id=gui;w.resize(1200,780)
    if w.dark!=dark:w.toggle_theme()
    first,path,folder=add_group(p.repo,id,tmp_path/'first',name='First')
    second,other_path,other_folder=add_group(p.repo,id,tmp_path/'second',name='Second')
    p.search.setText('Second');p.refresh();app.processEvents()
    assert p.model.rowCount()==1 and p.model.rows[0]['id']==second
    monkeypatch.setattr(QFileDialog,'getExistingDirectory',lambda *a:str(folder))
    monkeypatch.setattr(QInputDialog,'getItem',lambda *a:('Theo tên tự nhiên',True))
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    def click(action):
        rect=p.action_table.visualRect(p.model.index(0,6))
        QTest.mouseClick(p.action_table.viewport(),Qt.LeftButton,pos=group_button_rects(rect)[action].center());app.processEvents()
    click(0);wait(app,lambda:p.repo.group(second)['data']['image_folder']==str(folder.resolve()))
    click(1);assert w.doc_id==p.repo.group(second)['document_id'] and w.pages.currentIndex()==0
    w.pages.setCurrentIndex(9);app.processEvents();click(2);p.refresh()
    assert [g['id'] for g in p.repo.groups(id)]==[first]
    assert path.is_file() and other_path.is_file() and folder.is_dir() and other_folder.is_dir()
    assert not p.repo.store.jobs() and not FakeEngine.calls


@pytest.mark.parametrize('dark',[False,True])
def test_project_editor_all_modes_keep_geometry_and_do_not_export(gui,tmp_path,dark):
    app,w,p,id=gui;w.resize(1672,941)
    if w.dark!=dark:w.toggle_theme()
    for n in range(4):add_group(p.repo,id,tmp_path/str(n),name=f'{n+1}',count=1)
    p.refresh();app.processEvents();geometry=None
    for mode,count in (('separate',4),('merged',1),('split',2),('separate',4)):
        p.fields['capcut_mode'].setCurrentIndex(p.fields['capcut_mode'].findData(mode));p.refresh();app.processEvents()
        assert p.preview.isVisible() and p.preview.rowCount()==count and p.field_cells['part_count'].isVisible()
        assert p.fields['part_count'].isEnabled()==(mode=='split')
        current=(p.preview.geometry(),p.field_cells['part_count'].geometry(),p.field_cells['output'].geometry(),p.config_frame.height())
        if geometry:assert current==geometry
        geometry=current
        name=f'Edited {mode}';p.preview.item(0,0).setText(name);p.refresh()
        assert p.preview.item(0,0).text()==name
        assert not list(Path(p.output.text()).iterdir()) and not p.repo.store.jobs() and not FakeEngine.calls
    assert p.group_summary.parentWidget() is p.validation_badge.parentWidget()
    assert p.group_summary.y()>p.validation_badge.y()
    assert p.summary.geometry().center().y()==p.progress_title.geometry().center().y()
    assert '\n' not in p.summary.text() and 'Hoàn tất' not in p.summary.text()
    assert max(card.height() for card in p.stage_cards)<=100
    # Name editing remains disabled with the rest of the owned configuration.
    p.repo.activate(id);p.refresh();assert not p.preview.isEnabled() and not p.fields['part_count'].isEnabled()
    p.repo.state(id,'stopped')


@pytest.mark.parametrize('state,text',[('draft','Chưa chạy'),('running','Đang chạy'),('stopping','Đang dừng an toàn'),('stopped','Đã dừng'),('completed','Hoàn tất'),('needs_attention','Hoàn tất nhưng cần xử lý')])
def test_time_header_uses_workset_state_without_duplicate_group_summary(gui,state,text):
    app,w,p,id=gui;p.repo.state(id,state);p.refresh();app.processEvents()
    assert p.summary.text().startswith(text+' · ')
    assert 'nhóm' not in p.summary.text() and 'Hoàn tất 0/0 nhóm' in p.group_summary.text()
    assert p.progress_frame.rect().contains(p.summary.geometry().translated(p.summary.parentWidget().pos()))
