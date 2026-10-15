import os
import time
import json
import threading
from pathlib import Path
import pytest
from shiboken6 import isValid
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog
from transcomic.documents import decode_txt
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.ui.exporting import choose_export_plan, MODES


@pytest.fixture
def gui(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    s=Store(tmp_path/'state.db');w=MainWindow(s);w.resize(1400,900);w.show();app.processEvents()
    assert not any(e['event']=='gui_error' for e in s.log.snapshot())
    yield app,s,w
    if not w._closed:
        w._exit_authorized=True;w.close();app.processEvents()


def until(condition,seconds=5):
    deadline=time.monotonic()+seconds
    while not condition() and time.monotonic()<deadline:QTest.qWait(20)
    assert condition()


def load(gui,path,count=10):
    app,s,w=gui;raw='\n'.join('Source '+str(i) for i in range(count)).encode()
    path.write_bytes(raw);doc=s.import_document(path,decode_txt(raw),'vi','en')[0]
    w.open_document(doc);app.processEvents()
    until(lambda:w.line_check.report is not None and w.line_check.report.document_id==doc)
    return doc


def refresh(gui,condition):
    gui[2].refresh();gui[2].line_check.recount();until(condition)


def open_check(gui):
    QTest.mouseClick(gui[2].line_check,Qt.LeftButton);QApplication.processEvents()
    dialog=gui[2].line_check.dialog
    assert dialog.isVisible() and dialog.windowTitle()=='Kiểm tra số dòng'
    return dialog


def pick(dialog,row):
    index=dialog.model.index(row,0);dialog.table.scrollTo(index);QApplication.processEvents()
    QTest.mouseClick(dialog.table.viewport(),Qt.LeftButton,pos=dialog.table.visualRect(index).center())
    QTest.qWait(180)


def test_empty_neutral_three_states_live_fix_and_snapshot_counts(gui,tmp_path):
    app,s,w=gui
    assert 'Chưa có tài liệu' in w.line_check.text() and w.line_check.report is None
    dialog=open_check(gui);assert 'Chưa có kết quả' in dialog.empty.text();dialog.close()
    doc=load(gui,tmp_path/'a.txt');rows=s.lines(doc)
    assert w.line_check.report.state=='incomplete' and w.line_check.report.missing==10
    for row in rows:s.edit_line(row['id'],'translation','Translated.')
    refresh(gui,lambda:w.line_check.report.state=='complete')
    assert w.line_check.text()=='✓ Gốc 10 · Dịch 10' and w.line_check.property('glassRole')=='success'
    until(lambda:w.period_warning.count==10)
    dialog=open_check(gui);assert dialog.model.rowCount()==0 and dialog.empty.text()=='Không phát hiện lỗi cấu trúc dòng'
    with s.transaction():s.db.execute("UPDATE lines SET translation='Bad'||char(10)||'Split' WHERE id=?",(rows[3]['id'],))
    refresh(gui,lambda:w.line_check.report.state=='structure_error')
    assert w.line_check.property('glassRole')=='warning'
    assert dialog.model.index(0,0).data()=='Dòng 4' and 'xuống dòng' in dialog.model.index(0,1).data()
    s.edit_line(rows[3]['id'],'translation','Fixed')
    refresh(gui,lambda:w.line_check.report.state=='complete')
    assert dialog.model.rowCount()==0 and dialog.empty.isVisible()


def test_unfinished_popup_pick_far_filtered_stable_id_without_period(gui,tmp_path):
    app,s,w=gui;doc=load(gui,tmp_path/'long.txt',2500);target=s.lines(doc)[2004]
    w.model.set_filter({'error'});dialog=open_check(gui)
    assert dialog.model.rowCount()==2500 and dialog.model.index(2004,0).data()=='Dòng 2005'
    before=s.lines(doc);pick(dialog,2004)
    assert not dialog.isVisible()
    index=w.table.currentIndex();assert index.column()==1 and w.model.rows[index.row()]['id']==target['id']
    assert w.table.visualRect(index).intersects(w.table.viewport().rect()) and s.lines(doc)==before


def test_source_change_scope_stale_pick_and_removed_position(gui,tmp_path):
    app,s,w=gui;a=load(gui,tmp_path/'a.txt');old=s.lines(a)[0];dialog=open_check(gui)
    b=load(gui,tmp_path/'b.txt',2)
    until(lambda:dialog.model.rowCount()==2)
    w.line_check.choose((a,old['id']));assert w.doc_id==b
    row=s.lines(b)[0]
    with s.transaction():
        s.db.execute('DELETE FROM quality_warnings WHERE line_id=?',(row['id'],))
        s.db.execute('DELETE FROM lines WHERE id=?',(row['id'],))
    refresh(gui,lambda:bool(w.line_check.report.structural))
    assert any('Thiếu vị trí' in i['preview'] for i in w.line_check.rows)
    before=w.table.currentIndex();w.line_check.choose((b,row['id']))
    assert dialog.isVisible() and w.doc_id==b


def test_undo_redo_replace_and_navigation_reuse_editor(gui,tmp_path):
    app,s,w=gui;doc=load(gui,tmp_path/'a.txt',2);rows=s.lines(doc)
    w.table.edit(w.model.index(0,1));app.processEvents();editor=w.table.itemDelegate().active_editor
    editor.insertPlainText('Typed')
    refresh(gui,lambda:w.line_check.report.translated==1)
    dialog=open_check(gui)
    assert w.table.itemDelegate().active_editor is editor and editor.document().isUndoAvailable()
    pick(dialog,0)  # The only issue is the other, unfinished row.
    w.table.edit(w.model.index(0,1));app.processEvents()
    restored=w.table.itemDelegate().active_editor
    assert restored.toPlainText()=='Typed' and restored.document().isUndoAvailable()
    restored.undo();refresh(gui,lambda:w.line_check.report.translated==0)
    restored.redo();refresh(gui,lambda:w.line_check.report.translated==1)
    delegate=w.table.itemDelegate();delegate.commitData.emit(restored);delegate.closeEditor.emit(restored)
    w.search.apply([(rows[1]['id'],'translation','Replacement')])
    refresh(gui,lambda:w.line_check.report.state=='complete')
    w.search.undo();refresh(gui,lambda:w.line_check.report.missing==1)
    assert [r['id'] for r in s.lines(doc)]==[r['id'] for r in rows]


def test_export_ui_blocks_structure_and_incomplete_defaults_no_write(gui,tmp_path,monkeypatch):
    app,s,w=gui;doc=load(gui,tmp_path/'a.txt',2)
    monkeypatch.setattr(QInputDialog,'getItem',lambda *a,**k:(MODES[0][0],True))
    questions=[]
    monkeypatch.setattr(QMessageBox,'question',lambda *a:questions.append(a) or QMessageBox.No)
    assert choose_export_plan(w,[doc]) is None
    assert questions[0][-1]==QMessageBox.No and 'chưa hoàn thành' in questions[0][2]
    with s.transaction():s.db.execute("UPDATE lines SET translation='Bad'||char(13)||'Split' WHERE document_id=?",(doc,))
    warnings=[];monkeypatch.setattr(QMessageBox,'warning',lambda *a:warnings.append(a))
    assert choose_export_plan(w,[doc]) is None
    assert 'lỗi cấu trúc' in warnings[0][1] and w.line_check.dialog.isVisible()
    assert not list(tmp_path.glob('*_EN*.txt'))


@pytest.mark.parametrize('dark',[False,True])
def test_layout_both_controls_dialog_and_cached_worker_large(gui,tmp_path,monkeypatch,dark):
    app,s,w=gui;doc=load(gui,tmp_path/'large.txt',5000)
    if w.dark!=dark:w.toggle_theme()
    row=s.lines(doc)[104];s.edit_line(row['id'],'translation','Hello.')
    refresh(gui,lambda:w.line_check.report.translated==1)
    until(lambda:w.period_warning.count==1)
    for width in (1400,950):
        w.resize(width,900);app.processEvents();w.adapt_v2_toolbar()
        check=w.line_check.mapTo(w.editor_page,QPoint(0,0));period=w.period_warning.mapTo(w.editor_page,QPoint(0,0));folder=w.folder_button.mapTo(w.editor_page,QPoint(0,0))
        assert check.y()==period.y() and check.x()+w.line_check.width()<=period.x()
        assert check.y()+w.line_check.height()<=folder.y() and period.y()+w.period_warning.height()<=folder.y()
    dialog=open_check(gui)
    assert dialog.model.rowCount()==4999 and dialog.table.verticalScrollBar().maximum()>0
    QTest.qWait(300)
    until(lambda:not w.line_check._busy and w.line_check._signature==w.line_check.signature())
    before=w.line_check._signature
    for _ in range(5):dialog.table.viewport().repaint();w.line_check.recount()
    assert not w.line_check._busy and w.line_check._signature==before
    if os.environ.get('TRANSCOMIC_LINE_EVIDENCE'):
        out=Path(os.environ['TRANSCOMIC_LINE_EVIDENCE']);out.mkdir(parents=True,exist_ok=True)
        dialog.grab().save(str(out/f'popup-{dark}.png'));w.grab().save(str(out/f'editor-{dark}.png'))
        (out/'dpi.json').write_text(json.dumps({'dpr':w.devicePixelRatioF(),'platform':app.platformName()}),encoding='utf8')
    # A deliberately slow inspection still leaves Qt's event loop responsive.
    import transcomic.ui.line_check as module
    original=module.validate_snapshot;threads=[];ticks=[]
    def slow(*a,**k):threads.append(threading.get_ident());time.sleep(.15);return original(*a,**k)
    monkeypatch.setattr(module,'validate_snapshot',slow)
    beat=QTimer();beat.setInterval(10);beat.timeout.connect(lambda:ticks.append(1));beat.start()
    s.edit_line(row['id'],'translation','Changed.')
    w.line_check.recount();until(lambda:bool(threads) and not w.line_check._busy)
    beat.stop();assert ticks and all(i!=threading.get_ident() for i in threads)


def test_close_with_running_inspection_and_open_dialog(gui,tmp_path,monkeypatch):
    app,s,w=gui;doc=load(gui,tmp_path/'a.txt');dialog=open_check(gui)
    import transcomic.ui.line_check as module
    original=module.validate_snapshot
    def slow(*a,**k):time.sleep(.1);return original(*a,**k)
    monkeypatch.setattr(module,'validate_snapshot',slow)
    s.edit_line(s.lines(doc)[0]['id'],'translation','New')
    w.line_check.recount();w._exit_authorized=True;w.close();app.processEvents();QTest.qWait(180)
    assert w._closed
    if isValid(dialog):assert not dialog.isVisible() and not dialog.watch.isActive()
