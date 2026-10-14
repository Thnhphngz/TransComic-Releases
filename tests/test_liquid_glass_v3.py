"""V3 interaction checks: no network and no per-card widgets."""
import types
import pytest
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent, QFontMetrics, QStandardItemModel, QStandardItem
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QStyleOptionViewItem, QStyle, QDialog, QDialogButtonBox, QVBoxLayout
from transcomic.documents import decode_txt
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.ui.glass import GlassButton, SkySwitch
from transcomic.ui.controls import GlassComboDelegate
from transcomic.ui.controls import QComboBox
from transcomic.ui.documents_panel import DocumentDelegate
from transcomic.languages import language


@pytest.fixture
def gui(tmp_path, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path/'state.db'); w = MainWindow(store)
    w.resize(1200,720); w.show(); app.processEvents()
    yield app, store, w
    w.scheduler = None; w._exit_authorized = True; w.close()
    if not w._closed: app.processEvents()


def import_doc(store, w, path, count=3):
    path.write_text('\n'.join(f'Source {i}' for i in range(count)), encoding='utf-8')
    doc = store.import_document(path, decode_txt(path.read_bytes()), 'vi', 'en')[0]
    w.open_document(doc); QApplication.instance().processEvents()
    return doc


def click_close(w, row):
    view = w.document_panel.view; index = view.model().index(row)
    view.scrollTo(index); QApplication.instance().processEvents()
    rect = DocumentDelegate.close_rect(view.visualRect(index))
    assert rect.width() == 32 and rect.height() == 32
    QTest.mouseMove(view.viewport(), rect.center())
    QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=rect.center())
    QApplication.instance().processEvents()


@pytest.mark.parametrize('row', [0, 5, 11])
def test_x_exact_file_scrolled_no_card_click_preserves_source_history(gui,tmp_path,monkeypatch,row):
    app,store,w = gui
    docs = [import_doc(store,w,tmp_path/f'{i}.txt') for i in range(12)]
    job = store.create_job(docs[row], 'mock', 'vi', 'en', 1)
    exported = tmp_path/'export.txt'; exported.write_text('Retained',encoding='utf-8')
    opened = []; monkeypatch.setattr(w,'open_document_group', lambda item: opened.append(item))
    click_close(w,row)
    assert docs[row] not in w.workspace_ids and len(w.workspace_ids) == 11
    assert store.job(job) and store.document(docs[row]) and (tmp_path/f'{row}.txt').exists()
    assert exported.read_text(encoding='utf-8') == 'Retained' and not opened
    assert not w.document_panel.view.findChildren(QPushButton)


@pytest.mark.parametrize('active', [False,True])
def test_x_cancel_confirm_and_current_file_switch(gui,tmp_path,monkeypatch,active):
    app,store,w = gui
    first = import_doc(store,w,tmp_path/'a.txt'); second = import_doc(store,w,tmp_path/'b.txt')
    w.open_document(first)
    job = store.create_job(first,'mock','vi','en',1)
    store.edit_line(store.lines(first)[0]['id'],'translation','Saved')
    if active:
        w.scheduler = types.SimpleNamespace(_thread=types.SimpleNamespace(is_alive=lambda:True),job_ids=[job],job_id=job)
    monkeypatch.setattr(QMessageBox,'question',lambda *a: QMessageBox.No)
    click_close(w,0); assert w.doc_id == first and first in w.workspace_ids
    w.scheduler = None if not active else w.scheduler
    monkeypatch.setattr(QMessageBox,'question',lambda *a: QMessageBox.Yes)
    click_close(w,0)
    assert first not in w.workspace_ids and w.doc_id == second
    assert store.lines(first)[0]['translation'] == 'Saved' and store.job(job)


def test_press_outside_release_does_not_remove_or_open(gui,tmp_path,monkeypatch):
    app,store,w = gui; doc=import_doc(store,w,tmp_path/'a.txt')
    view=w.document_panel.view; rect=view.visualRect(view.model().index(0))
    pos=DocumentDelegate.close_rect(rect).center(); opened=[]
    monkeypatch.setattr(w,'open_document_group',lambda item:opened.append(item))
    QTest.mousePress(view.viewport(),Qt.LeftButton,pos=pos)
    QTest.mouseRelease(view.viewport(),Qt.LeftButton,pos=QPoint(rect.left()+80,rect.bottom()-10))
    assert doc in w.workspace_ids and not opened


def test_empty_start_target_order_session_theme_and_restart(gui,tmp_path):
    app,store,w=gui; doc=import_doc(store,w,tmp_path/'a.txt')
    assert not w.start_button.isEnabled() and not w.target_languages()
    assert w.setup_grid.getItemPosition(w.setup_grid.indexOf(w.language_row))[0] == 1
    assert w.setup_grid.getItemPosition(w.setup_grid.indexOf(w.actions_widget))[0] == 2
    for name in ('Tiếng Anh','Tiếng Indonesia'):w.target_chips[name].click()
    assert [c.text() for c in (w.target_chips['Tiếng Anh'],w.target_chips['Tiếng Indonesia'])] == ['1 EN','2 ID']
    assert w.start_button.isEnabled()
    run,jobs=store.create_run([doc],['en','id'],provider='kira',model='mock',source_lang='vi',concurrency=1)
    w.sky_switch.click(); app.processEvents()
    import_doc(store,w,tmp_path/'b.txt');w.pages.setCurrentIndex(2);w.pages.setCurrentIndex(0)
    assert w.target_languages()==['Tiếng Anh','Tiếng Indonesia']
    assert len(w.findChildren(SkySwitch))==1
    assert not hasattr(w,'sidebar_theme') and not hasattr(w,'theme_button')
    dark=w.dark; path=tmp_path/'state.db';w._exit_authorized=True;w.close();app.processEvents()
    other=MainWindow(Store(path))
    assert other.dark==dark and other.target_languages()==[] and not other.start_button.isEnabled()
    assert [language(other.store.job(j)['target_lang']).locale for j in jobs]==['en','id']
    other._exit_authorized=True;other.close()


@pytest.mark.parametrize('dark',[False,True])
def test_actual_en_id_popup_select_and_wheel(gui,tmp_path,dark):
    app,store,w=gui;doc=import_doc(store,w,tmp_path/'a.txt')
    _,jobs=store.create_run([doc],['en','id'],provider='kira',model='mock',source_lang='vi',concurrency=1)
    w.workspace_ids=[store.job(j)['document_id'] for j in jobs];w.open_document(doc)
    if w.dark!=dark:w.toggle_theme()
    combo=w.view_language
    assert [combo.itemText(i) for i in range(combo.count())]==['Tiếng Anh','Tiếng Indonesia']
    combo.showPopup();app.processEvents();view=combo.view()
    assert isinstance(combo.itemDelegate(),GlassComboDelegate)
    assert view.height()<130 and view.visualRect(view.model().index(0,0)).height()>20
    selected=view.model().index(0,0);hover=view.visualRect(selected).center()
    QTest.mouseMove(view.viewport(),hover)
    assert combo.currentText()=='Tiếng Anh' and combo.itemText(0)=='Tiếng Anh'
    # Paint the selected item and verify a contrasting foreground exists inside its text region.
    image=view.viewport().grab().toImage();rect=view.visualRect(selected)
    ink = '#30231d' if dark else '#fffcf9'
    assert any(image.pixelColor(x,y).name()==ink for x in range(30,min(rect.right()-10,image.width())) for y in range(max(0,rect.top()),min(rect.bottom(),image.height())))
    QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=view.visualRect(view.model().index(1,0)).center())
    assert language(store.document(w.doc_id)['target_lang']).locale=='id' and combo.currentText()=='Tiếng Indonesia'
    combo.showPopup();app.processEvents();assert combo.count()==2;combo.hidePopup()
    previous=combo.currentIndex()
    wheel=QWheelEvent(QPointF(8,8),QPointF(combo.mapToGlobal(QPoint(8,8))),QPoint(),QPoint(0,120),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
    app.sendEvent(combo,wheel);assert combo.currentIndex()==previous
    assert not store.attempts(store.batches(jobs[0])[0]['id']) and w.scheduler is None


@pytest.mark.parametrize('count',[9,99,999,9999])
@pytest.mark.parametrize('size',[12,22])
def test_font_metrics_gutter_all_digits_status_filter(gui,tmp_path,count,size):
    app,store,w=gui;import_doc(store,w,tmp_path/'a.txt',count)
    w.change_font(size); header=w.table.verticalHeader();font=header.font();font.setBold(True);m=QFontMetrics(font)
    expected=m.horizontalAdvance(str(count)+' ')+max(m.horizontalAdvance(s) for s in ('✓','!','?','◌','·','–','↻'))+12
    assert header.width()==expected and w.table.columnWidth(2)==38
    w.model.set_filter({'error'});assert header.width()==expected


def test_shared_buttons_mouse_keyboard_focus_and_switch_fit(gui):
    app,store,w=gui
    buttons=w.findChildren(QPushButton)
    assert all(isinstance(b,GlassButton) for b in buttons)
    QTest.mouseClick(w.nav_buttons[0],Qt.LeftButton)
    assert w.nav_buttons[0].isChecked()
    QTest.mouseClick(w.nav_buttons[1],Qt.LeftButton)
    assert w.nav_buttons[1].isChecked() and not w.nav_buttons[0].isChecked()
    QTest.mouseClick(w.nav_buttons[0],Qt.LeftButton)
    button=w.collapse_button
    QTest.mouseClick(button,Qt.LeftButton);app.processEvents()
    assert not button.property('keyboardFocus')
    assert w.sky_switch.geometry().left()>=0 and w.sky_switch.geometry().right()<w.sidebar.width()
    button.clearFocus();button.setFocus(Qt.TabFocusReason);app.processEvents()
    assert button.property('keyboardFocus') and button.focusPolicy()!=Qt.NoFocus
    QTest.keyClick(button,Qt.Key_Tab);assert w.sky_switch.property('keyboardFocus')
    QTest.keyClick(w.sky_switch,Qt.Key_Tab,Qt.ShiftModifier);assert button.hasFocus()
    before=button.grab().toImage();button.setDown(True);assert button.grab().toImage()!=before
    button.setDown(False);button.setEnabled(False);assert button.grab().toImage()!=before
    for dark in (False,True):
        if w.dark!=dark:w.toggle_theme()
        w.source_lang.showPopup();app.processEvents()
        assert w.source_lang.count()==11 and w.source_lang.view().height()<500
        w.source_lang.hidePopup()


@pytest.mark.parametrize('dark',[False,True])
def test_native_dialog_buttons_use_glass_disabled_items_and_popup_wheel(gui,dark):
    app,store,w=gui
    if w.dark!=dark:w.toggle_theme()
    dialog=QDialog(w);layout=QVBoxLayout(dialog)
    combo=QComboBox();combo.addItems([f'Locale {i}' for i in range(25)])
    combo.model().item(2).setEnabled(False);layout.addWidget(combo)
    box=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);layout.addWidget(box)
    dialog.show();app.processEvents()
    ok=box.button(QDialogButtonBox.Ok)
    assert ok.property('glassRole')=='primary'
    image=ok.grab().toImage()
    # The confirmation surface differs from the secondary Cancel surface.
    assert image.pixelColor(12,image.height()//2)!=box.button(QDialogButtonBox.Cancel).grab().toImage().pixelColor(12,image.height()//2)
    # Check the ancestor-render path as well as a direct button grab: Qt caches
    # stylesheet colors for buttons it creates inside QDialogButtonBox.
    whole=dialog.grab().toImage();origin=ok.mapTo(dialog,QPoint())
    ratio=whole.devicePixelRatio();left=int((origin.x()+10)*ratio);top=int((origin.y()+6)*ratio)
    right=int((origin.x()+ok.width()-10)*ratio);bottom=int((origin.y()+ok.height()-6)*ratio)
    ink='#30231d' if dark else '#fffcf9'
    assert any(whole.pixelColor(x,y).name()==ink for x in range(left,right) for y in range(top,bottom))
    combo.showPopup();app.processEvents();view=combo.view();before=combo.currentIndex()
    disabled=view.visualRect(view.model().index(2,0))
    QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=disabled.center())
    assert combo.currentIndex()==before
    combo.showPopup();app.processEvents();bar=view.verticalScrollBar()
    wheel=QWheelEvent(QPointF(8,8),QPointF(view.viewport().mapToGlobal(QPoint(8,8))),QPoint(),QPoint(0,-120),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
    app.sendEvent(view.viewport(),wheel);assert bar.value()>0 and combo.currentIndex()==before
    combo.hidePopup();dialog.close()
    previous=w.concurrency.value()
    wheel=QWheelEvent(QPointF(8,8),QPointF(w.concurrency.mapToGlobal(QPoint(8,8))),QPoint(),QPoint(0,120),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
    app.sendEvent(w.concurrency,wheel);assert w.concurrency.value()==previous+1


def test_glass_application_filter_shared_without_retaining_closed_windows(gui,tmp_path):
    app,store,w=gui
    skin=w.glass_skin
    assert skin.parent() is app and not hasattr(skin,'owner')
    w._exit_authorized=True;w.close();app.processEvents()
    other=MainWindow(Store(tmp_path/'other.db'));other.show();app.processEvents()
    assert other.glass_skin is skin
    other.collapse_button.setFocus(Qt.TabFocusReason)
    assert other.collapse_button.property('keyboardFocus')
    other._exit_authorized=True;other.close()


def test_focus_popup_theme_and_repeated_search_rebuild(gui,tmp_path):
    app,store,w=gui;import_doc(store,w,tmp_path/'a.txt',10)
    w.search.open(False)
    for i in range(20):
        w.source_lang.setFocus(Qt.TabFocusReason)
        QTest.keyClick(w.source_lang,Qt.Key_Tab)
        QTest.keyClick(app.focusWidget(),Qt.Key_Tab,Qt.ShiftModifier)
        w.source_lang.showPopup();app.processEvents()
        w.toggle_theme();w.source_lang.hidePopup()
        assert isinstance(w.source_lang.itemDelegate(),GlassComboDelegate)
        w.search.query.setText('Source' if i%2 else 'Source 1')
        app.processEvents()
        assert len(w.search.results)==(10 if i%2 else 1)
        assert w.search.result_list.count()==len(w.search.results)
