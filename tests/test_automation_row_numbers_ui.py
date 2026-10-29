"""Compact read-only ordinal column; stable group actions remain unchanged."""
import copy
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont,QFontMetrics
from PySide6.QtTest import QTest
from test_automation_ui import gui
from test_automation import add_group,FakeEngine


@pytest.mark.parametrize('dark',[False,True])
def test_numbers_follow_group_order_and_remain_stable_through_filter_move_delete(gui,tmp_path,dark):
    app,w,p,id=gui
    if w.dark!=dark:w.toggle_theme()
    ids=[]
    for n in range(3):ids.append(add_group(p.repo,id,tmp_path/str(n),name=f'Chapter {n+1}')[0])
    p.refresh();app.processEvents()
    assert p.model.headerData(0,Qt.Horizontal)=='STT'
    assert [p.model.index(i,0).data() for i in range(3)]==[1,2,3]
    assert p.model.index(0,1).data()=='Chapter 1.txt'
    index=p.model.index(0,0)
    assert not index.flags()&Qt.ItemIsUserCheckable and index.data(Qt.CheckStateRole) is None
    assert not p.model.setData(index,Qt.Checked,Qt.CheckStateRole)
    QTest.mouseClick(p.number_table.viewport(),Qt.LeftButton,pos=p.number_table.visualRect(index).center())
    assert p.number_table.selectionModel().isRowSelected(0) and index.data()==1
    before=p.number_table.width();p.search.setText('Chapter 3');p.flush();assert p.snapshots.wait_for_idle();app.processEvents()
    assert p.model.rowCount()==1 and p.model.index(0,0).data()==3 and p.number_table.width()==before
    p.search.clear();p.repo.move(ids[2],-1);p.refresh()
    assert [r['id'] for r in p.model.rows]==[ids[0],ids[2],ids[1]]
    assert [p.model.index(i,0).data() for i in range(3)]==[1,2,3]
    p.repo.remove_group(ids[0]);p.refresh()
    assert [p.model.index(i,0).data() for i in range(2)]==[1,2]
    assert not p.repo.store.jobs() and not FakeEngine.calls


@pytest.mark.parametrize('maximum',[1,9,10,99,100,999,1000,10000])
def test_ordinal_width_fits_header_and_digits_without_extra_stretch(gui,tmp_path,maximum):
    app,w,p,id=gui;add_group(p.repo,id,tmp_path/'g');p.refresh();p.timer.stop()
    row=copy.deepcopy(p.model.rows[0]);row['sequence']=maximum
    p.model.update([row],total=maximum);p.adapt_layout();app.processEvents()
    pane=p.number_table;font=QFont(pane.horizontalHeader().font());font.setBold(True)
    expected=max(QFontMetrics(font).horizontalAdvance('STT')+12,pane.fontMetrics().horizontalAdvance(str(maximum))+12)
    assert pane.width()==expected and pane.columnWidth(0)==expected
    assert p.model.index(0,0).data()==maximum and pane.viewport().rect().contains(pane.visualRect(p.model.index(0,0)))
    assert pane.width()<65


def test_clicking_number_does_not_limit_start_to_a_hidden_checked_subset(gui,tmp_path,monkeypatch):
    app,w,p,id=gui;add_group(p.repo,id,tmp_path/'g');p.repo.activate(id);p.repo.state(id,'stopped');p.refresh()
    p.proof={'passed':True,'errors':[],'pending':True};called=[]
    monkeypatch.setattr(p.controller,'start',lambda workset,selected=None:called.append((workset,selected)))
    index=p.model.index(0,0);QTest.mouseClick(p.number_table.viewport(),Qt.LeftButton,pos=p.number_table.visualRect(index).center())
    p.start_clicked();assert called==[(id,None)] and not hasattr(p.model,'checked')
