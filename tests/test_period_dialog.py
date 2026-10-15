"""Real clicks on a live virtual punctuation list, isolated documents and no API."""
import json
import os
from pathlib import Path
import pytest
from shiboken6 import isValid
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QTextDocument, QAbstractTextDocumentLayout
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QAbstractItemView
from transcomic.documents import decode_txt
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.ui.period_warning import period_selections


@pytest.fixture
def gui(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    store=Store(tmp_path/'state.db'); w=MainWindow(store); w.resize(1400,900);w.show();app.processEvents()
    assert not any(e['event']=='gui_error' for e in store.log.snapshot())
    yield app,store,w
    if not w._closed:
        if w.period_warning.dialog: w.period_warning.dialog.close()
        w._exit_authorized=True;w.close()
    app.processEvents()


def document(gui,path,count=3):
    app,store,w=gui
    path.write_text('\n'.join('Nguồn. '+str(i) for i in range(count)),encoding='utf8')
    doc=store.import_document(path,decode_txt(path.read_bytes()),'vi','en')[0]
    w.open_document(doc);app.processEvents();return doc


def wait(gui):
    gui[2].refresh();QTest.qWait(200);gui[0].processEvents()


def popup(gui):
    app,_,w=gui;wait(gui)
    QTest.mouseClick(w.period_warning,Qt.LeftButton);app.processEvents()
    dialog=w.period_warning.dialog
    assert dialog and dialog.isVisible() and dialog.windowTitle()=='Các dòng dịch có dấu chấm'
    return dialog


def pick(gui,dialog,position):
    index=dialog.model.index(position,0);dialog.table.scrollTo(index);gui[0].processEvents()
    QTest.mouseClick(dialog.table.viewport(),Qt.LeftButton,pos=dialog.table.visualRect(index).center())
    QTest.qWait(180);gui[0].processEvents()


@pytest.mark.parametrize('text',['.Đầu','Ở.giữa','Cuối.','Nhiều...'])
def test_open_live_list_positions_unique_and_no_content_change(gui,tmp_path,text):
    _,store,w=gui;doc=document(gui,tmp_path/'a.txt');row=store.lines(doc)[1]
    store.edit_line(row['id'],'translation',text)
    before=store.lines(doc);dialog=popup(gui)
    assert w.period_warning.count==1 and dialog.model.rowCount()==1
    assert dialog.model.index(0,0).data()=='Dòng 2'
    assert dialog.model.index(0,1).data()==text
    assert dialog.model.index(0,2).data().startswith('a.txt')
    assert dialog.model.index(0,0).data(Qt.UserRole)==(doc,row['id'])
    QTest.keyClick(dialog.table,Qt.Key_Escape)
    assert not dialog.isVisible() and store.lines(doc)==before


def test_utf16_highlight_and_safe_long_plain_preview(gui,tmp_path):
    _,store,w=gui;doc=document(gui,tmp_path/'a.txt');row=store.lines(doc)[0]
    text='😀'+'a'*500+'<b>.One... & two</b>'
    store.edit_line(row['id'],'translation',text);dialog=popup(gui)
    excerpt=dialog.model.index(0,1).data()
    assert len(excerpt)<170 and '.' in excerpt and '<b>' in excerpt
    doc_text=QTextDocument();doc_text.setPlainText('😀a.b.')
    selections=period_selections(doc_text,'😀a.b.',QAbstractTextDocumentLayout.Selection)
    assert [s.cursor.selectionStart() for s in selections]==[3,5]
    assert all(s.cursor.selectedText()=='.' for s in selections)


def test_choose_far_stable_id_clears_filter_scrolls_and_does_not_edit(gui,tmp_path):
    app,store,w=gui;doc=document(gui,tmp_path/'long.txt',2200)
    target=store.lines(doc)[2004]
    store.edit_line(target['id'],'translation','Hello. This... is far')
    before=store.line(target['id']);w.model.set_filter({'error'});dialog=popup(gui)
    assert dialog.model.index(0,0).data()=='Dòng 2005'
    pick(gui,dialog,0)
    assert not dialog.isVisible() and w.doc_id==doc
    index=w.table.currentIndex()
    assert w.model.rows[index.row()]['id']==target['id'] and index.column()==1
    assert w.table.visualRect(index).intersects(w.table.viewport().rect())
    assert w.table.verticalScrollBar().value()>0 and w.period_warning.focus_key==(doc,target['id'])
    assert store.line(target['id'])==before


def test_exact_document_language_and_deferred_restore(gui,tmp_path):
    app,store,w=gui;a=document(gui,tmp_path/'a.txt');b=document(gui,tmp_path/'b.txt',120)
    variant=store.workspace_for_target(a,'Tiếng Indonesia');w.workspace_ids.append(variant)
    targets=[store.lines(d)[1] for d in (a,b,variant)]
    for i,row in enumerate(targets):store.edit_line(row['id'],'translation',f'Target {i}.')
    w.open_document(b);w.table.setCurrentIndex(w.model.index(90,1));w.open_document(a);w.pages.setCurrentIndex(2)
    dialog=popup(gui)
    pick(gui,dialog,2)
    assert w.doc_id==variant and w.pages.currentIndex()==0
    assert w.model.rows[w.table.currentIndex().row()]['id']==targets[2]['id']
    dialog=popup(gui);pick(gui,dialog,1)
    assert w.doc_id==b and w.model.rows[w.table.currentIndex().row()]['id']==targets[1]['id']


def test_popup_live_api_replace_empty_and_closed_scope(gui,tmp_path):
    app,store,w=gui;a=document(gui,tmp_path/'a.txt');b=document(gui,tmp_path/'b.txt')
    first=store.lines(a)[0];second=store.lines(b)[1]
    store.edit_line(first['id'],'translation','One.');dialog=popup(gui)
    store.edit_line(second['id'],'translation','Two...')
    w.bridge.changed.emit([second['id']]);QTest.qWait(250)
    assert dialog.model.rowCount()==2 and w.period_warning.count==2
    store.edit_line(first['id'],'translation','No period');QTest.qWait(220)
    assert dialog.model.rowCount()==1 and dialog.model.index(0,0).data()=='Dòng 2'
    w.remove_workspace_instances({b},confirmed=True);QTest.qWait(220)
    assert dialog.isVisible() and dialog.model.rowCount()==0 and dialog.empty.isVisible()
    assert not w.period_warning.isVisible()
    assert store.line(second['id'])['translation']=='Two...'
    # A stale saved key must not reopen closed history.
    w.period_warning.choose((b,second['id']));assert w.doc_id==a and b not in w.workspace_ids


def test_deleted_line_and_reset_between_press_release_cannot_pick_wrong_row(gui,tmp_path):
    app,store,w=gui;doc=document(gui,tmp_path/'a.txt');rows=store.lines(doc)
    for row in rows:store.edit_line(row['id'],'translation','Hello.')
    dialog=popup(gui);point=dialog.table.visualRect(dialog.model.index(0,0)).center()
    QTest.mousePress(dialog.table.viewport(),Qt.LeftButton,pos=point)
    with store.transaction():
        store.db.execute('DELETE FROM quality_warnings WHERE line_id=?',(rows[0]['id'],))
        store.db.execute('DELETE FROM line_edits WHERE line_id=?',(rows[0]['id'],))
        store.db.execute('DELETE FROM lines WHERE id=?',(rows[0]['id'],))
    w.period_warning.recount();app.processEvents()
    QTest.mouseRelease(dialog.table.viewport(),Qt.LeftButton,pos=point)
    assert dialog.isVisible() and dialog.model.rowCount()==2
    assert dialog.model.index(0,0).data()=='Dòng 2'
    w.period_warning.choose((doc,rows[0]['id']));assert dialog.isVisible()


@pytest.mark.parametrize('cross_document',[False,True])
def test_native_undo_redo_survives_popup_same_and_other_row(gui,tmp_path,cross_document):
    app,store,w=gui;doc=document(gui,tmp_path/'a.txt')
    other=document(gui,tmp_path/'b.txt') if cross_document else doc
    rows=[store.lines(doc)[0],store.lines(other)[1]];w.open_document(doc)
    store.edit_line(rows[1]['id'],'translation','Other.')
    w.model.refresh();w.table.edit(w.model.index(0,1));app.processEvents()
    editor=w.table.itemDelegate().active_editor
    editor.insertPlainText('Typed.');wait(gui);assert editor.document().isUndoAvailable()
    dialog=popup(gui);QTest.keyClick(dialog.table,Qt.Key_Escape);app.processEvents()
    assert w.table.itemDelegate().active_editor is editor and editor.document().isUndoAvailable()
    dialog=popup(gui);pick(gui,dialog,0)
    assert w.table.itemDelegate().active_editor is editor
    assert editor.document().isUndoAvailable() and len(editor.extraSelections())==1
    editor.undo();wait(gui);assert not store.line(rows[0]['id'])['translation']
    editor.redo();wait(gui);assert store.line(rows[0]['id'])['translation']=='Typed.'
    dialog=popup(gui);pick(gui,dialog,1)
    dialog=popup(gui);pick(gui,dialog,0)
    w.table.edit(w.table.currentIndex());app.processEvents()
    restored=w.table.itemDelegate().active_editor
    assert restored.document().isUndoAvailable() and restored.toPlainText()=='Typed.'
    restored.undo();wait(gui);assert not store.line(rows[0]['id'])['translation']
    restored.redo();wait(gui);assert store.line(rows[0]['id'])['translation']=='Typed.'


def test_replace_undo_and_cache_rejects_external_revision(gui,tmp_path):
    app,store,w=gui;doc=document(gui,tmp_path/'a.txt');rows=store.lines(doc)
    store.edit_line(rows[0]['id'],'translation','Hello.')
    dialog=popup(gui)
    w.search.apply([(rows[0]['id'],'translation','Hello')]);QTest.qWait(200)
    assert dialog.model.rowCount()==0 and dialog.empty.isVisible()
    w.search.undo();QTest.qWait(200)
    assert dialog.model.rowCount()==1 and dialog.isVisible()
    QTest.keyClick(dialog.table,Qt.Key_Escape)
    store.edit_line(rows[1]['id'],'translation','Other.');w.model.refresh()
    w.table.edit(w.model.index(0,1));app.processEvents()
    editor=w.table.itemDelegate().active_editor;editor.insertPlainText('Extra')
    dialog=popup(gui);pick(gui,dialog,1)
    store.edit_line(rows[0]['id'],'translation','External.');w.period_warning.recount()
    dialog=popup(gui);pick(gui,dialog,0);w.table.edit(w.table.currentIndex());app.processEvents()
    restored=w.table.itemDelegate().active_editor
    assert restored.toPlainText()=='External.' and not restored.document().isUndoAvailable()
    assert store.line(rows[0]['id'])['translation']=='External.'


@pytest.mark.parametrize('pending',[False,True])
def test_window_close_stops_open_popup_and_pending_navigation(gui,tmp_path,pending):
    app,store,w=gui;doc=document(gui,tmp_path/'a.txt')
    store.edit_line(store.lines(doc)[0]['id'],'translation','Hello.')
    dialog=popup(gui)
    warning=w.period_warning
    if pending:warning.choose((doc,store.lines(doc)[0]['id']))
    w._exit_authorized=True;w.close();app.processEvents();QTest.qWait(150)
    assert w._closed
    if isValid(dialog):assert not dialog.isVisible() and not dialog.watch.isActive()
    if isValid(warning):assert not warning.timer.isActive()


@pytest.mark.parametrize('dark',[False,True])
def test_virtual_large_list_theme_geometry_click_and_cached_paint(gui,tmp_path,dark):
    app,store,w=gui;doc=document(gui,tmp_path/'large.txt',3000)
    if w.dark!=dark:w.toggle_theme()
    # Populate a large synthetic snapshot directly. This case measures the virtual
    # warning list, without repeatedly running unrelated language-quality analysis.
    with store.transaction():
        store.db.executemany("UPDATE lines SET translation=?,state='done',translation_source_revision=source_revision WHERE id=?",
            [(f'Preview {i}. More...',row['id']) for i,row in enumerate(store.lines(doc))])
    w.model.load(doc);w.local_timer.stop();w.queue_timer.stop()
    w.period_warning.recount();QTest.mouseClick(w.period_warning,Qt.LeftButton);app.processEvents()
    dialog=w.period_warning.dialog
    assert dialog.isVisible()
    assert dialog.model.rowCount()==3000 and w.period_warning.count==3000
    area=w.screen().availableGeometry();assert dialog.height()<=area.height() and dialog.width()<=area.width()
    assert dialog.table.verticalScrollBar().maximum()>0
    assert len(dialog.table.viewport().findChildren(QWidget))<10
    traces=[];store.db.set_trace_callback(traces.append)
    for _ in range(4):dialog.table.viewport().repaint();dialog.watch.timeout.emit()
    store.db.set_trace_callback(None)
    assert not any('instr(' in q for q in traces)
    if os.environ.get('TRANSCOMIC_PERIOD_EVIDENCE'):
        out=Path(os.environ['TRANSCOMIC_PERIOD_EVIDENCE']);out.mkdir(parents=True,exist_ok=True)
        dialog.grab().save(str(out/f'popup-{dark}.png'))
        w.grab().save(str(out/f'editor-{dark}.png'))
        (out/'dpi.json').write_text(json.dumps({'dpr':w.devicePixelRatioF(),'platform':app.platformName()}),encoding='utf8')
    pick(gui,dialog,2999)
    assert w.model.rows[w.table.currentIndex().row()]['ordinal']==2999
