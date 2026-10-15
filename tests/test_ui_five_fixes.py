"""Isolated UI regressions. Can also run with QT_QPA_PLATFORM=windows per DPI."""
import os
import json
from pathlib import Path
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from transcomic.documents import decode_txt
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.models import KIRA_MODELS


@pytest.fixture
def gui(tmp_path):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path/'state.db'); w = MainWindow(store)
    assert not any(e['event']=='gui_error' for e in store.log.snapshot())
    w.resize(1400, 900); w.show(); app.processEvents()
    yield app, store, w
    w.scheduler = None; w._exit_authorized = True; w.close(); app.processEvents()


def add_doc(gui, path, text='Nguồn có dấu.\nNguồn thứ hai'):
    app, store, w = gui
    path.write_text(text, encoding='utf8')
    doc = store.import_document(path, decode_txt(path.read_bytes()), 'vi', 'en')[0]
    w.open_document(doc); app.processEvents()
    return doc


def settle(gui):
    app, _, w = gui
    w.refresh(); QTest.qWait(120); app.processEvents()


@pytest.mark.parametrize('text,expected', [('',0), ('Chưa có',0), ('.Đầu',1),
    ('Ở.giữa',1), ('Cuối.',1), ('Nhiều...',1), ('Ôi!',0), ('Sao?',0), ('Dấu …',0)])
def test_period_positions_source_only_and_empty(gui, tmp_path, text, expected):
    _, store, w = gui; doc = add_doc(gui, tmp_path/'source.txt')
    store.edit_line(store.lines(doc)[0]['id'], 'translation', text)
    settle(gui)
    assert w.period_warning.count == expected
    assert w.period_warning.isVisible() == bool(expected)
    assert store.lines(doc)[0]['translation'] == (text or None)


def test_period_workspace_variants_closed_history_filter_and_api_mock(gui, tmp_path, monkeypatch):
    app, store, w = gui
    first = add_doc(gui, tmp_path/'a.txt'); second = add_doc(gui, tmp_path/'b.txt')
    alternate = store.workspace_for_target(first, 'Tiếng Indonesia'); w.workspace_ids.append(alternate)
    closed = store.import_document(tmp_path/'closed.txt', decode_txt(b'Closed'), 'vi', 'en')[0]
    store.edit_line(store.lines(closed)[0]['id'], 'translation', 'Closed.')
    # Simulate the queued update sent by either provider, including a nonvisible document.
    ids = [store.lines(d)[0]['id'] for d in (first, alternate)]
    for line_id in ids: store.edit_line(line_id, 'translation', 'API.mock')
    w.bridge.changed.emit(ids); QTest.qWait(160); settle(gui)
    assert w.period_warning.count == 2
    w.open_document(second); w.model.set_filter({'error'}); settle(gui)
    assert w.period_warning.count == 2  # Scope is the open workspace, not current filter.
    w.remove_workspace_instances({first}, confirmed=True); settle(gui)
    assert w.period_warning.count == 0 and not w.period_warning.isVisible()
    assert store.lines(closed)[0]['translation'] == 'Closed.'
    # Cached count avoids repeating the content query on unchanged progress polls.
    queries = []; store.db.set_trace_callback(queries.append)
    for _ in range(5): w.period_warning.schedule(); w.period_warning.recount()
    store.db.set_trace_callback(None)
    assert not any('instr(' in q for q in queries)


def test_period_manual_replace_undo_redo_reload(gui, tmp_path):
    app, store, w = gui; doc = add_doc(gui, tmp_path/'a.txt')
    index = w.model.index(0,1)
    assert w.model.setData(index, 'Hello')
    QTest.qWait(120); assert w.period_warning.count == 0
    # Native editor undo/redo emits textChanged and persists via LineModel.setData.
    w.table.edit(w.model.index(0,1)); app.processEvents()
    editor=w.table.itemDelegate().active_editor
    editor.insertPlainText('.')
    QTest.qWait(120); assert w.period_warning.count == 1
    editor.undo(); QTest.qWait(120)
    assert store.lines(doc)[0]['translation']=='Hello' and w.period_warning.count == 0
    editor.redo(); QTest.qWait(120)
    assert store.lines(doc)[0]['translation']=='.Hello' and w.period_warning.count == 1
    delegate=w.table.itemDelegate();delegate.commitData.emit(editor);delegate.closeEditor.emit(editor)
    w.search.apply([(store.lines(doc)[0]['id'],'translation','Hello')])
    settle(gui);assert w.period_warning.count==0
    w.search.undo();settle(gui);assert w.period_warning.count==1
    w.model.setData(w.model.index(0,1), 'Hello'); settle(gui)
    assert w.period_warning.count == 0
    store.edit_line(store.lines(doc)[1]['id'], 'translation', '.Reloaded')
    w.open_document(doc); settle(gui); assert w.period_warning.count == 1


@pytest.mark.parametrize('dark', [False, True])
def test_sidebar_center_and_badge_layout_both_sizes(gui, tmp_path, dark):
    app, store, w = gui
    if w.dark != dark: w.toggle_theme()
    doc = add_doc(gui, tmp_path/'a.txt')
    store.edit_line(store.lines(doc)[0]['id'],'translation','A.')
    if w.sidebar.width() > 100: w.toggle_sidebar()
    settle(gui)
    # Actual raster icon bounds, not just the button's geometry.
    for control in w.nav_buttons:
        assert not control.text()
        image = control.grab().toImage(); dpr = image.devicePixelRatio()
        from PySide6.QtGui import QIcon
        saved=control.icon();control.setIcon(QIcon());blank=control.grab().toImage();control.setIcon(saved)
        pixels=[]
        for x in range(image.width()):
            for y in range(int(8*dpr), min(image.height(),int(38*dpr))):
                if image.pixelColor(x,y)!=blank.pixelColor(x,y):pixels.append(x)
        assert pixels and abs((min(pixels)+max(pixels))/2-image.width()/2) <= 2*dpr, (control.toolTip(), min(pixels), max(pixels), image.width())
    icon = w.brand_icon
    center = icon.mapTo(w.sidebar, icon.rect().center()).x()
    assert abs(center-w.sidebar.rect().center().x()) <= 1
    for width in (1400, 950):
        w.resize(width,900); app.processEvents(); w.adapt_v2_toolbar(); settle(gui)
        badge=w.period_warning; folder=w.folder_button
        b=badge.mapTo(w.editor_page, QPoint(0,0)); f=folder.mapTo(w.editor_page,QPoint(0,0))
        assert b.y()+badge.height() <= f.y()
        assert b.x()+badge.width() <= f.x()+folder.width()+1
        assert badge.isVisible() and w.table.height()>100
        if os.environ.get('TRANSCOMIC_UI_EVIDENCE'):
            out=Path(os.environ['TRANSCOMIC_UI_EVIDENCE']);out.mkdir(parents=True,exist_ok=True)
            w.grab().save(str(out/f'{dark}-{width}.png'))
            (out/'dpi.json').write_text(json.dumps({'dpr':w.devicePixelRatioF(),'platform':app.platformName()}),encoding='utf8')
    w.toggle_sidebar(); app.processEvents()
    assert w.brand_label.isVisible() and all(b.text() for b in w.nav_buttons)


@pytest.mark.parametrize('dark', [False, True])
@pytest.mark.parametrize('row', [0, 6])
def test_close_at_painted_top_right_after_scroll_resize(gui, tmp_path, monkeypatch, dark, row):
    app, store, w = gui
    if w.dark != dark: w.toggle_theme()
    docs=[add_doc(gui,tmp_path/f'{i}.txt') for i in range(8)]
    view=w.document_panel.view; index=view.model().index(row)
    w.document_splitter.setSizes([310,900]); view.scrollTo(index); app.processEvents()
    QTest.qWait(80);app.processEvents()
    rect=view.visualRect(index)
    # Independently locate the rendered cross in a raster crop of the top right.
    image=view.viewport().grab().toImage(); ratio=image.devicePixelRatio()
    xs=[];ys=[]
    for x in range(int((rect.right()-32)*ratio),int((rect.right()-12)*ratio)):
        for y in range(max(0,int((rect.top()+12)*ratio)),int((rect.top()+32)*ratio)):
            c=image.pixelColor(x,y)
            background=image.pixelColor(int((rect.right()-60)*ratio),y)
            if sum(abs(a-b) for a,b in zip(c.getRgb()[:3],background.getRgb()[:3]))>30:
                xs.append(x);ys.append(y)
    assert xs and ys, (rect.getRect(),image.size(),ratio)
    point=QPoint(round((min(xs)+max(xs))/2/ratio),round((min(ys)+max(ys))/2/ratio))
    assert view.hit_action(point)==('close',docs[row])
    opened=[];monkeypatch.setattr(w,'open_document_group',lambda item:opened.append(item))
    QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=point);app.processEvents()
    assert docs[row] not in w.workspace_ids and not opened
    assert (tmp_path/f'{row}.txt').exists() and store.document(docs[row])


def test_gemini_modal_refresh_reentrancy_selection_and_persistence(gui, monkeypatch):
    app,store,w=gui
    store.add_gemini_keys('fake-first\nfake-second\nfake-third')
    w.refresh_gemini_keys();w.gemini_keys_list.setCurrentRow(1)
    ids=[k['id'] for k in store.gemini_keys()]; selected=ids[1]
    def confirmation(*_):
        w.refresh_gemini_keys()  # Destroys original item inside the modal loop.
        w.gemini_keys_list.setCurrentRow(0)
        w.edit_gemini_key(delete=True)  # Ignore reentrant delete and add/reorder.
        w.edit_gemini_key(direction=1)
        w.gemini_key_input.setText('fake-nested');w.add_gemini_keys()
        return QMessageBox.Yes
    monkeypatch.setattr(QMessageBox,'question',confirmation)
    w.edit_gemini_key(delete=True)
    assert [k['id'] for k in store.gemini_keys()] == [ids[0],ids[2]]
    w.gemini_keys_list.setCurrentRow(1);w.edit_gemini_key(direction=-1)
    assert store.gemini_keys()[0]['id']==ids[2]
    w.edit_gemini_key(direction=1); assert store.gemini_keys()[1]['id']==ids[2]
    w.gemini_keys_list.setCurrentRow(-1);w.edit_gemini_key(delete=True)
    with store.lock:
        import sqlite3
        with sqlite3.connect(store.path) as db:
            assert {r[0] for r in db.execute('SELECT id FROM gemini_keys')}=={ids[0],ids[2]}
    reopened=MainWindow(Store(store.path))
    try:
        assert {reopened.gemini_keys_list.item(i).data(Qt.UserRole)
                for i in range(reopened.gemini_keys_list.count())}=={ids[0],ids[2]}
    finally: reopened._exit_authorized=True;reopened.close()


def test_gemini_stale_empty_cancel_add(gui,monkeypatch):
    _,store,w=gui
    w.edit_gemini_key(delete=True)
    w.gemini_key_input.setText('fake-one'); w.add_gemini_keys()
    w.gemini_keys_list.setCurrentRow(0)
    monkeypatch.setattr(QMessageBox,'question',lambda *_:QMessageBox.No)
    w.edit_gemini_key(delete=True); assert len(store.gemini_keys())==1
    def stale(*_):
        store.change_gemini_key(store.gemini_keys()[0]['id'],delete=True)
        w.refresh_gemini_keys();return QMessageBox.Yes
    monkeypatch.setattr(QMessageBox,'question',stale)
    monkeypatch.setattr(QMessageBox,'information',lambda *_:None)
    w.edit_gemini_key(delete=True); assert not store.gemini_keys()


def test_mimo_registry_and_saved_selection(gui):
    _,store,w=gui
    assert len({id for _,id in KIRA_MODELS})==len(KIRA_MODELS)
    assert ('Coding MiMo V2.6 Flash','coding-mimo-v2.6-flash') in KIRA_MODELS
    w.set_model_id('mimo-v2.6-flash')
    assert w.selected_model_id()=='mimo-v2.6-flash'
    other=MainWindow(Store(store.path))
    try: assert other.selected_model_id()=='mimo-v2.6-flash'
    finally: other._exit_authorized=True;other.close()


@pytest.mark.parametrize('response', ['valid', 'partial', '504', 'timeout'])
def test_mimo_batch_parsing_timeout_single_send(response):
    import asyncio
    import httpx
    from transcomic.providers import KiraProvider
    calls=[]
    def transport(request):
        calls.append(request)
        body=json.loads(request.content)
        assert body['model']=='mimo-v2.6-flash' and body['max_tokens']==128
        if response=='timeout': raise httpx.ReadTimeout('synthetic',request=request)
        if response=='504': return httpx.Response(504)
        lines=[{'id':'a','text':'Hello'}]
        if response=='valid': lines.append({'id':'b','text':'Thank you'})
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':lines})}}]})
    result=asyncio.run(KiraProvider('fake','mimo-v2.6-flash',max_tokens=128,
        transport=httpx.MockTransport(transport)).translate(
            [{'id':'a','source':'Xin chào'},{'id':'b','source':'Cảm ơn'}],'vi','en'))
    assert len(calls)==1
    if response=='valid': assert not result.error and len(result.values)==2
    elif response=='partial': assert result.error and result.values=={'a':'Hello'}
    else: assert result.error and result.unknown and not result.values
