"""Real Qt editor input and compact panel geometry, with synthetic media only."""
import pytest
from PySide6.QtCore import Qt,QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit,QStyleOptionFrame,QStyle,QApplication
from transcomic.ui.theme import colors
from test_capcut_ui import page
from test_capcut_names_header import prepare
from test_capcut_single_page import settle


def open_editor(app,p,row=0):
    view=p.split_preview;index=p.split_model.index(row,0);view.scrollTo(index);settle(app)
    point=view.visualRect(index).center()
    QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=point)
    QTest.mouseDClick(view.viewport(),Qt.LeftButton,pos=point);settle(app)
    editors=[e for e in view.findChildren(QLineEdit) if e.isVisible()]
    assert len(editors)==1
    editor=editors[0]
    assert editor.hasFocus() and editor.objectName()=='capcutNameEditor'
    assert editor.geometry()==view.visualRect(index)
    option=QStyleOptionFrame();editor.initStyleOption(option)
    content=editor.style().subElementRect(QStyle.SE_LineEditContents,option,editor)
    assert content.height()>=editor.fontMetrics().height()
    assert 0<=content.y()<=2 and 2<=content.x()<=5
    assert editor.textMargins().isNull() and view.rowHeight(row)==23
    assert editor.alignment()&Qt.AlignVCenter
    assert editor.palette().base().color().name().upper()==colors(p)['field']
    return editor


@pytest.mark.parametrize('dark',[False,True])
@pytest.mark.parametrize('text',['A','Long project name '+('abc '*12),'Truyện tiếng Việt — 日本語 Ω'])
def test_compact_editor_real_keys_clipboard_caret_and_escape(page,tmp_path,dark,text):
    app,w,p,_=prepare(page,tmp_path)
    if w.dark!=dark:w.toggle_theme();settle(app)
    original=p.split_model.parts[0].name
    editor=open_editor(app,p)
    QTest.keyClick(editor,Qt.Key_A,Qt.ControlModifier)
    clipboard=QApplication.clipboard();saved=clipboard.text()
    try:
        clipboard.setText(text);QTest.keyClick(editor,Qt.Key_V,Qt.ControlModifier)
        assert editor.text()==text and editor.cursorPosition()==len(text)
        QTest.keyClicks(editor,'xyz');QTest.keyClick(editor,Qt.Key_Backspace)
        assert editor.text()==text+'xy'
        QTest.keyClick(editor,Qt.Key_Home);QTest.keyClick(editor,Qt.Key_Delete)
        assert editor.text()==text[1:]+'xy'
        QTest.keyClick(editor,Qt.Key_A,Qt.ControlModifier)
        assert editor.selectedText()==editor.text()
        QTest.keyClick(editor,Qt.Key_C,Qt.ControlModifier)
        assert clipboard.text()==editor.text()
        clipboard.setText(text);QTest.keyClick(editor,Qt.Key_V,Qt.ControlModifier)
        editor.setCursorPosition(min(3,len(text)));assert not editor.hasSelectedText()
        assert p.split_model.parts[0].name==original  # no keystroke commits
        QTest.keyClick(editor,Qt.Key_Return);settle(app)
        assert p.split_model.parts[0].name==text and p.manager.custom_names['1']==text
        editor=open_editor(app,p,1);QTest.keyClick(editor,Qt.Key_A,Qt.ControlModifier)
        QTest.keyClicks(editor,'Cancel me');QTest.keyClick(editor,Qt.Key_Escape);settle(app)
        assert p.split_model.parts[1].name=='vote_part2'
        assert p.split_model.parts[0].name==text
    finally:clipboard.setText(saved)


@pytest.mark.parametrize('dark',[False,True])
@pytest.mark.parametrize('width',[950,1400])
@pytest.mark.parametrize('count',[2,10])
def test_export_panel_modes_border_compact_geometry_and_busy(page,tmp_path,dark,width,count):
    app,w,p,_=prepare(page,tmp_path);w.resize(width,1000)
    if w.dark!=dark:w.toggle_theme()
    p.part_count.setValue(count);settle(app)
    panel=p.settings_frame
    assert panel.objectName()=='capcutExportPanel'
    assert panel.layout().contentsMargins().top()==6
    heights={}
    for mode in [0,1,2,1,0,2]:
        p.mode.setCurrentIndex(mode);settle(app)
        heights.setdefault(mode,panel.height());assert heights[mode]==panel.height()
        assert p.split_controls.isVisible()==(mode==2)
        assert p.output.isVisible() and p.export_button.isVisible()
        from PySide6.QtCore import QRect
        assert not QRect(p.output.mapTo(panel,QPoint()),p.output.size()).intersects(QRect(p.export_button.mapTo(panel,QPoint()),p.export_button.size()))
        for widget in (p.mode,p.project_name,p.output,p.output_browse,p.export_button,p.open_button):
            r=widget.rect();r.moveTopLeft(widget.mapTo(panel,QPoint()))
            assert panel.rect().contains(r)
        image=panel.grab().toImage();ratio=image.devicePixelRatio()
        border=image.pixelColor(round(panel.width()/2*ratio),0).name().upper()
        assert border==('#806657' if dark else '#B59B8B')
        if mode==2:
            assert p.split_model.rowCount()==count and p.split_preview.height()<=136
            editor=open_editor(app,p,count-1)
            QTest.keyClick(editor,Qt.Key_Escape);settle(app)
    assert heights[0]==heights[1] and heights[2]-heights[0]<=180
    p.busy=True;p.operation='export';p.set_busy(True);settle(app)
    assert not p.split_preview.isEnabled() and not p.output.isEnabled()
    assert not p.export_button.isEnabled() and p.cancel_button.isEnabled()
    assert panel.isVisible() and panel.height()==heights[2]
    p.busy=False;p.operation=None;p.set_busy(False);settle(app)
    assert p.split_preview.isEnabled() and p.export_button.isEnabled()


def test_theme_switch_during_edit_keeps_buffer_and_focus(page,tmp_path):
    app,w,p,_=prepare(page,tmp_path);editor=open_editor(app,p)
    editor.setText('Unsaved buffer');editor.setCursorPosition(4)
    w.toggle_theme();settle(app)
    assert editor.text()=='Unsaved buffer' and editor.cursorPosition()==4
    option=QStyleOptionFrame();editor.initStyleOption(option)
    content=editor.style().subElementRect(QStyle.SE_LineEditContents,option,editor)
    assert content.height()>=editor.fontMetrics().height()
    assert editor.palette().base().color().name().upper()==colors(p)['field']
    QTest.keyClick(editor,Qt.Key_Escape);settle(app)
    assert p.split_model.parts[0].name=='vote_part1'
