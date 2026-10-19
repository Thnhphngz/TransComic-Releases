"""No network/model inference: actual MainWindow, shared views and Qt events."""
from pathlib import Path
import threading
import json
import os
import time
import pytest
from PySide6.QtCore import Qt,QMimeData,QUrl,QPointF
from PySide6.QtGui import QDragEnterEvent,QDropEvent,QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QMessageBox,QStyleOptionViewItem,QStyle,QSplitter
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.ui.tts_page import TtsPage
from transcomic.automation.validation import defaults
from transcomic.automation.adapters import Translation,Kokoro
from test_automation import FakeEngine,add_group
from test_kira_auto_recovery import response
from transcomic.kira_pool import KiraPoolProvider
import httpx


def wait(app,predicate,seconds=8):
    deadline=time.monotonic()+seconds
    while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    app.processEvents();assert predicate()


@pytest.fixture
def gui(tmp_path,monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen');app=QApplication.instance() or QApplication([])
    # Windows offscreen QPA does not discover system fonts as the native QPA does.
    for name in ('segoeui.ttf','seguisym.ttf'):
        font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name
        if font.is_file():QFontDatabase.addApplicationFont(str(font))
    monkeypatch.setattr(TtsPage,'check_runtime',lambda self:None)
    store=Store(tmp_path/'state.sqlite3');store.set_setting('update_auto_check','0');window=MainWindow(store)
    window.resize(1440,940);window.show();window.pages.setCurrentIndex(9);app.processEvents()
    p=window.automation_page;repo=window.automation_repo;services=window.automation_services
    services.preflight=lambda cfg:None
    services.translation=Translation(repo,lambda store,job:KiraPoolProvider(store,'mock',transport=httpx.MockTransport(response),rpm=100000,tpm=100000000),network_probe=lambda provider:True)
    FakeEngine.calls=[];FakeEngine.fail=None;FakeEngine.entered=None;FakeEngine.release=None
    services.kokoro=Kokoro(repo,services.tts_store,None,engine_factory=FakeEngine)
    output=tmp_path/'projects';output.mkdir();cfg=defaults(store);cfg.update(model='mock',device='CPU',output=str(output))
    id=repo.create('Bộ truyện thử',cfg);store.add_kira_keys('automation-ui-fixture');p.load_worksets(id)
    yield app,window,p,id
    window.automation_controller.stop_event.set();services.translation.stop()
    while window.automation_controller.busy:app.processEvents();time.sleep(.01)
    window._exit_authorized=True;window.close();app.processEvents()


@pytest.mark.parametrize('dark',[False,True])
def test_layout_shared_sidebar_validation_and_real_start_lock(gui,tmp_path,monkeypatch,dark):
    app,w,p,id=gui
    if w.dark!=dark:w.toggle_theme()
    gid,path,folder=add_group(p.repo,id,tmp_path/'g',count=2);p.refresh()
    assert p.model.rowCount()==1 and not p.start.isEnabled()
    p.validate_clicked();wait(app,lambda:p.proof is not None)
    assert p.proof['passed'] and p.start.isEnabled()
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.Yes)
    QTest.mouseClick(p.start,Qt.LeftButton);app.processEvents()
    assert not p.config_frame.isEnabled() and p.config_opacity.opacity()<1
    assert 'Cấu hình đã khóa' in p.lock_note.text()
    assert not p.start.isEnabled()
    wait(app,lambda:not w.automation_controller.busy)
    p.flush();assert p.repo.workset(id)['state']=='completed'
    assert p.config_frame.isEnabled() and not p.fields['voice'].isEnabled() and not p.fields['speed'].isEnabled()
    assert p.repo.group(gid)['document_id'] in w.workspace_ids
    w.pages.setCurrentIndex(7);app.processEvents();assert w.tts_page.store is w.automation_services.tts_store
    assert p.repo.group(gid)['data']['tts_run'] in {r['id'] for r in w.tts_page.store.history_runs()}
    w.pages.setCurrentIndex(8);app.processEvents()
    assert not hasattr(w.capcut_page,'automation_mirror') and not w.capcut_page.manager.groups
    assert p.repo.group(gid)['data']['project']
    assert len(w.nav_buttons)==7 and all(not b.icon().isNull() for b in w.nav_buttons)
    assert len(FakeEngine.calls)==2
    target=os.environ.get('TRANSCOMIC_AUTOMATION_SCREENSHOTS')
    if target:
        w.pages.setCurrentIndex(9);p.refresh();app.processEvents();directory=Path(target);directory.mkdir(parents=True,exist_ok=True)
        assert w.grab().save(str(directory/('automation-dark.png' if dark else 'automation-light.png')))
        (directory/'dpr.json').write_text(json.dumps({'dpr':w.devicePixelRatioF(),'window':[w.width(),w.height()]}))
        (directory/'geometry.json').write_text(json.dumps({name:[getattr(p,name).geometry().getRect(),getattr(p,name).parentWidget().size().toTuple(),getattr(p,name).isVisible()] for name in ('worksets','new_button','delete_button','up','down','output','output_choose')}))


def test_drop_folder_requires_target_row_and_actions_use_stable_id(gui,tmp_path,monkeypatch):
    app,w,p,id=gui;gid,path,folder=add_group(p.repo,id,tmp_path/'a');other,path2,folder2=add_group(p.repo,id,tmp_path/'b','3-4');p.refresh()
    p.drop_paths([str(tmp_path/'a')],None);assert len(p.repo.groups(id))==2
    p.drop_paths([str(folder2)],gid);wait(app,lambda:p.repo.group(gid)['data']['image_folder']==str(folder2.resolve()))
    p.search.setText(str(path2));p.flush();assert p.model.rowCount()==1 and p.model.rows[0]['id']==other
    p.row_action(other,'editor');assert w.doc_id==p.repo.group(other)['document_id'] and w.pages.currentIndex()==0
    assert FakeEngine.calls==[] and p.repo.store.jobs()==[]


def test_resume_rejects_unsaved_editor_and_manual_engines_while_running(gui,tmp_path):
    app,w,p,id=gui;gid,path,folder=add_group(p.repo,id,tmp_path/'a');p.refresh()
    w.open_document(p.repo.group(gid)['document_id']);w.pages.setCurrentIndex(0);app.processEvents()
    index=w.model.index(0,1);w.table.edit(index);app.processEvents()
    assert w.table.itemDelegate().active_editor is not None
    assert w.automation_controller.validate(id)['passed']
    with pytest.raises(ValueError,match='Lưu'):w.automation_controller.start(id)
    editor=w.table.itemDelegate().active_editor;QTest.keyClick(editor,Qt.Key_Escape);app.processEvents()
    assert w.table.itemDelegate().active_editor is None
    p.repo.activate(id)
    assert not (w.model.flags(index)&Qt.ItemIsEditable)
    with pytest.raises(ValueError):w.store.create_job(p.repo.group(gid)['document_id'],'mock','vi','en',1)
    from transcomic.ui.update_panel import native_install_idle
    # Even between worker starts, durable ownership blocks conflicting engines.
    w.pages.setCurrentIndex(7);app.processEvents()
    with pytest.raises(ValueError):w.tts_page.start()
    w.pages.setCurrentIndex(8);app.processEvents()
    with pytest.raises(ValueError):w.capcut_page.start_export()
    p.repo.state(id,'stopped')


def test_painted_row_action_hit_regions_keyboard_and_real_drop_events(gui,tmp_path):
    from transcomic.ui.automation_page import group_button_rects
    app,w,p,id=gui;gid,path,folder=add_group(p.repo,id,tmp_path/'a');p.refresh()
    table=p.action_table;index=p.model.index(0,6);table.scrollTo(index);app.processEvents()
    selected=[];table.action_clicked.disconnect();table.action_clicked.connect(lambda *args:selected.append(args))
    rects=group_button_rects(table.visualRect(index))
    for rect,action in zip(rects,('images','editor','remove')):
        assert table.action_at(rect.center())==(gid,action)
        QTest.mouseMove(table.viewport(),rect.center());QTest.mouseClick(table.viewport(),Qt.LeftButton,pos=rect.center())
    assert selected==[(gid,'images'),(gid,'editor'),(gid,'remove')]
    table.setCurrentIndex(index);table.setFocus();table.keyboard_action=0
    QTest.keyClick(table,Qt.Key_Right);QTest.keyClick(table,Qt.Key_Space)
    assert selected[-1]==(gid,'editor')
    p.model.can_mutate=False
    assert table.action_at(rects[0].center()) is None and table.action_at(rects[2].center()) is None
    assert table.action_at(rects[1].center())==(gid,'editor')
    p.model.can_mutate=True
    drops=[];table.dropped.disconnect();table.dropped.connect(lambda *args:drops.append(args))
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(folder))])
    point=table.visualRect(p.model.index(0,6)).center()
    enter=QDragEnterEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    QApplication.sendEvent(table.viewport(),enter);assert enter.isAccepted()
    drop=QDropEvent(QPointF(point),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    QApplication.sendEvent(table.viewport(),drop)
    assert drop.isAccepted() and len(drops)==1 and drops[0][1]==gid
    assert [Path(value) for value in drops[0][0]]==[folder]


def test_translation_replace_undo_syncs_checkpoint_without_http_or_extra_voice(gui,tmp_path):
    app,w,p,id=gui;gid,_,_=add_group(p.repo,id,tmp_path/'a',count=2)
    c=w.automation_controller;assert c.validate(id)['passed'];c.start(id);wait(app,lambda:not c.busy)
    p.flush();group=p.repo.group(gid);run=group['data']['tts_run']
    row=w.store.lines(group['document_id'])[0];old=row['translation'];jobs=len(w.store.jobs());calls=len(FakeEngine.calls)
    w.open_document(group['document_id']);w.pages.setCurrentIndex(0);app.processEvents()
    w.search.apply([(row['id'],'translation','A manually edited sentence.')]);p.flush()
    assert w.store.line(row['id'])['translation']=='A manually edited sentence.'
    assert p.repo.group_state(gid)['state']=='stale'
    assert w.automation_services.tts_store.items(run)[0]['state']=='stale'
    w.pages.setCurrentIndex(9);p.refresh();app.processEvents()
    assert 'cập nhật' in p.model.index(0,5).data()
    w.pages.setCurrentIndex(0);w.search.undo();app.processEvents()
    assert w.store.line(row['id'])['translation']==old
    assert c.validate(id)['passed'];c.start(id);wait(app,lambda:not c.busy)
    assert p.repo.workset(id)['state']=='completed'
    assert len(w.store.jobs())==jobs and len(FakeEngine.calls)==calls


@pytest.mark.parametrize('dark',[False,True])
def test_polished_controls_modes_backend_config_and_quiet_cell_hover(gui,tmp_path,dark):
    app,w,p,id=gui
    if w.dark!=dark:w.toggle_theme()
    for n in range(2):add_group(p.repo,id,tmp_path/str(n),name=str(n+1),count=1)
    p.refresh();saved=p.repo.workset(id)['config']
    assert not {'variant','device'}&p.fields.keys()
    assert not any(hasattr(p,name) for name in ('log_frame','log_filter','log_toggle','logs','report_button'))
    assert p.kokoro_lanes.text()=='Kokoro: 1 luồng · 1 nhóm mỗi lượt'
    assert len({b.geometry().center().y() for b in (p.add,p.start,p.stop,p.validate_button)})==1
    assert max(b.height() for b in (p.add,p.start,p.stop,p.validate_button))<=36
    for mode in ('split','merged','separate','split'):
        p.fields['capcut_mode'].setCurrentIndex(p.fields['capcut_mode'].findData(mode));app.processEvents();p.flush()
        assert p.field_cells['part_count'].isVisible() and p.fields['part_count'].isEnabled()==(mode=='split')
        assert p.preview.isVisible()
    cfg=p.repo.workset(id)['config'];assert cfg['variant']==saved['variant'] and cfg['device']==saved['device']
    table=p.table;index=p.model.index(0,1);table.setCurrentIndex(index);table.setFocus();app.processEvents()
    QTest.mouseClick(table.viewport(),Qt.LeftButton,pos=table.visualRect(index).center());app.processEvents()
    assert not table.keyboard_focus
    opt=QStyleOptionViewItem();opt.state=QStyle.State_HasFocus|QStyle.State_MouseOver
    table.itemDelegate().initStyleOption(opt,index)
    assert not opt.state&(QStyle.State_HasFocus|QStyle.State_MouseOver)
    opt.state=QStyle.State_HasFocus|QStyle.State_MouseOver
    p.preview.itemDelegate().initStyleOption(opt,p.preview.model().index(0,0))
    assert not opt.state&(QStyle.State_HasFocus|QStyle.State_MouseOver)
    QTest.mouseMove(p.search);app.processEvents();bounds=table.visualRect(index).adjusted(2,2,-2,-2)
    before=table.viewport().grab(bounds).toImage()
    QTest.mouseMove(table.viewport(),table.visualRect(index).center());app.processEvents()
    assert table.viewport().grab(bounds).toImage()==before
    QTest.keyClick(table,Qt.Key_Down);assert table.keyboard_focus and table.currentIndex().row()==1
    check=p.model.index(0,0)
    QTest.mouseClick(p.number_table.viewport(),Qt.LeftButton,pos=p.number_table.visualRect(check).center())
    assert p.number_table.selectionModel().isRowSelected(0) and check.data(Qt.CheckStateRole) is None


def test_tts_manual_draft_is_preserved_but_hidden_in_running_automation_context(gui,tmp_path):
    app,w,p,id=gui;tts=w.automation_services.tts_store
    old=tts.draft();path=tmp_path/'5-6_EN.txt';path.write_text('A saved manual draft.',encoding='utf8')
    doc=tts.add_document(old,dict(name='5-6_EN',path=str(path),text='A saved manual draft.',line_count=1),'lines')
    for n in range(2):add_group(p.repo,id,tmp_path/str(n),name=f'{n*2+1}-{n*2+2}',count=1)
    FakeEngine.entered=threading.Event();FakeEngine.release=threading.Event()
    c=w.automation_controller;assert c.validate(id)['passed'];c.start(id)
    try:
        wait(app,FakeEngine.entered.is_set);w.pages.setCurrentIndex(7);app.processEvents();page=w.tts_page;page.refresh_history();page.refresh()
        assert page.run_id==old and page.automation_context.isVisible() and not page.tabs.isVisible()
        assert not page.controls.isVisible() and not page.action_strip.isVisible()
        assert not page.history_panel.clear_button.isEnabled()
        assert '1 luồng' in page.automation_context_text.text() and tts.doc(doc)['name']=='5-6_EN'
        cards=list(page.history_panel.cards.values());assert cards
        assert all('Automation · Chỉ đọc' in card.meta.text() for card in cards)
        menu=cards[0].context_menu();assert all(not action.isEnabled() for action in menu.actions() if action.text() in ('Tiếp tục lượt','Dừng / Hủy lượt','Liên kết lại'))
        target=os.environ.get('TRANSCOMIC_AUTOMATION_SCREENSHOTS')
        if target:
            directory=Path(target);directory.mkdir(parents=True,exist_ok=True);assert w.grab().save(str(directory/'tts-automation-context.png'))
    finally:FakeEngine.release.set()
    wait(app,lambda:not c.busy);page.refresh_history();page.refresh()
    assert not page.automation_context.isVisible() and page.tabs.isVisible() and page.run_id==old
    assert 'bản nháp thủ công' in page.runtime_label.text()
    page.automation_context_active=False;page.refresh()
    assert page.manual_context_note.isVisible() and 'thủ công đã lưu' in page.manual_context_note.text()
    assert len(page.history_panel.cards)==2 and tts.doc(doc)['name']=='5-6_EN'
    assert len(tts.docs(old))==1 and c.repo.workset(id)['state']=='completed'


@pytest.mark.parametrize('dark',[False,True])
def test_polish_screenshots_real_mock_pipeline_six_groups(gui,tmp_path,dark):
    app,w,p,id=gui;w.resize(1672,941)
    if w.dark!=dark:w.toggle_theme()
    cfg=p.repo.workset(id)['config'];cfg.update(capcut_mode='split',part_count=3,project_name='TransComic');p.repo.configure(id,cfg);p.load_worksets(id)
    for n in range(6):add_group(p.repo,id,tmp_path/str(n),name=f'{n*2+1}-{n*2+2}',count=2)
    c=w.automation_controller;proof=c.validate(id);assert proof['passed'];p.validated(id,proof);c.start(id);wait(app,lambda:not c.busy,seconds=15)
    p.flush();p.refresh();app.processEvents();assert p.repo.workset(id)['state']=='completed'
    assert p.completion_ring.done==6 and p.completion_ring.total==6 and p.preview.rowCount()==3
    assert p.action_table.viewport().rect().contains(p.action_table.visualRect(p.model.index(0,6)))
    target=os.environ.get('TRANSCOMIC_AUTOMATION_SCREENSHOTS')
    if target:
        directory=Path(target);directory.mkdir(parents=True,exist_ok=True)
        assert w.grab().save(str(directory/('polish-dark.png' if dark else 'polish-light.png')))
        (directory/'polish-dpr.json').write_text(json.dumps({'dpr':w.devicePixelRatioF(),'window':[w.width(),w.height()]}))


@pytest.mark.parametrize('width,height',[(900,580),(1200,780),(1640,940)])
def test_resize_config_scroll_and_no_overlapping_stage_controls(gui,width,height):
    app,w,p,id=gui;w.resize(width,height);app.processEvents()
    for a,b in zip((p.add,p.start),(p.start,p.stop)):
        assert not a.geometry().intersects(b.geometry())
    for widgets in ((p.worksets,p.new_button,p.delete_button),(p.search,p.filter,p.up,p.down),(p.output,p.output_choose)):
        for widget in widgets:
            assert widget.parentWidget().rect().contains(widget.geometry()),(widget.text() if hasattr(widget,'text') else type(widget).__name__,widget.geometry())
        for a,b in zip(widgets,widgets[1:]):assert not a.geometry().intersects(b.geometry())
    assert not p.findChildren(QSplitter) and p.table.viewport().height()>40
    assert p.left_pane.geometry().right()<p.right_scroll.geometry().left()
    scroll=p.right_scroll
    if height==580:assert scroll.verticalScrollBar().isVisible()
    else:assert scroll.widget().height()>=scroll.viewport().height() or not scroll.verticalScrollBar().isVisible()


@pytest.mark.parametrize('width,height',[(900,580),(1200,780),(1672,941),(1920,1080)])
def test_responsive_columns_have_no_drag_handle_and_toolbar_order(gui,width,height):
    app,w,p,id=gui;w.resize(width,height);app.processEvents();p.adapt_layout();app.processEvents()
    assert not p.findChildren(QSplitter)
    assert p.columns.stretch(0)==70 and p.columns.stretch(1)==30
    ratio=p.left_pane.width()/(p.left_pane.width()+p.right_scroll.width())
    if width>=1200:assert .67<=ratio<=.73
    widgets=sorted(p.toolbar_buttons,key=lambda b:(b.geometry().y(),b.geometry().x()))
    assert widgets==[p.add,p.validate_button,p.start,p.stop]
    for button in widgets:
        assert p.toolbar.rect().contains(button.geometry())
        assert button.fontMetrics().horizontalAdvance(button.text())<=button.width()-12
    assert not any(hasattr(p,name) for name in ('image_button','editor_button','folder_button','validation_frame'))
    assert p.validation_badge.parentWidget() is p.title_label.parentWidget()
    assert p.table_shell.geometry().bottom()>=p.left_pane.height()-2
    for control in p.fields.values():
        if control.isVisible():assert control.parentWidget().rect().contains(control.geometry()),(type(control).__name__,control.geometry(),control.parentWidget().rect())
    from PySide6.QtCore import QPoint
    point=QPoint(p.left_pane.geometry().right()+5,p.height()//2);before=(p.left_pane.width(),p.right_scroll.width())
    QTest.mousePress(p,Qt.LeftButton,pos=point);QTest.mouseMove(p,point+QPoint(70,0));QTest.mouseRelease(p,Qt.LeftButton,pos=point+QPoint(70,0));app.processEvents()
    assert (p.left_pane.width(),p.right_scroll.width())==before
    p.table.horizontalHeader().resizeSection(4,30)
    assert p.table.columnWidth(4)>=165 and p.action_table.columnWidth(6)>=140
    assert (p.left_pane.width(),p.right_scroll.width())==before


def test_validation_badge_opens_complete_group_errors_and_esc(gui,tmp_path):
    app,w,p,id=gui
    for n in range(2):add_group(p.repo,id,tmp_path/str(n),name=f'Bad {n}',images=n)
    p.validate_clicked();wait(app,lambda:p.proof is not None)
    assert not p.proof['passed'] and '2 nhóm' in p.validation_badge.text() and not p.start.isEnabled()
    QTest.mouseClick(p.validation_badge,Qt.LeftButton);app.processEvents()
    assert p.validation_dialog.isVisible()
    assert all(f'Bad {n}' in p.validation_detail_text.toPlainText() for n in range(2))
    QTest.keyClick(p.validation_dialog,Qt.Key_Escape);app.processEvents();assert not p.validation_dialog.isVisible()


def test_config_changes_auto_validate_without_media_rescan_or_manual_check(gui,tmp_path,monkeypatch):
    from transcomic.automation import validation as v
    app,w,p,id=gui;add_group(p.repo,id,tmp_path/'a');p.validate_clicked();wait(app,lambda:p.proof is not None)
    assert p.proof['passed']
    def forbidden(*args,**kwargs):raise AssertionError('Unchanged source/image must not be parsed again')
    monkeypatch.setattr(v,'read_source',forbidden);monkeypatch.setattr(v,'image_manifest',forbidden)
    field=p.fields['project_name'];field.setFocus();field.selectAll();QTest.keyClicks(field,'New project name')
    assert p.proof is None and not p.start.isEnabled()
    wait(app,lambda:p.proof is not None)
    assert p.proof['passed'] and p.proof['checked_sections']==['capcut'] and p.start.isEnabled()
    assert all(g['input_cached'] for g in p.proof['groups'])
    p.fields['voice'].setCurrentIndex(p.fields['voice'].findData('af_heart'));wait(app,lambda:p.proof is not None)
    assert p.proof['passed'] and p.proof['checked_sections']==['kokoro']
    p.fields['provider'].setCurrentIndex(1);wait(app,lambda:p.proof is not None)
    assert not p.proof['passed'] and not p.start.isEnabled() and 'cấu hình' in p.validation_badge.text()
    assert w.store.jobs()==[] and FakeEngine.calls==[]


def test_double_click_uses_clicked_id_and_result_is_available_in_row_menu(gui,tmp_path,monkeypatch):
    app,w,p,id=gui;a,_,_=add_group(p.repo,id,tmp_path/'a');b,_,_=add_group(p.repo,id,tmp_path/'b',name='3-4');p.refresh()
    index=p.model.index(1,1);p.table.setCurrentIndex(p.model.index(0,1));p.open_translation_index(index)
    assert w.doc_id==p.repo.group(b)['document_id']
    w.pages.setCurrentIndex(9);p.row_context_menu(p.table.visualRect(index).center());app.processEvents()
    assert 'Mở kết quả' in [action.text() for action in p.row_menu.actions()]
    p.row_menu.close()


def test_disabled_config_cannot_be_changed_programmatically(gui,tmp_path):
    app,w,p,id=gui;add_group(p.repo,id,tmp_path/'a');saved=p.repo.workset(id)['config'];p.repo.activate(id);p.refresh()
    p.fields['workers'].setValue(2);p.fields['speed'].setValue(1.5);app.processEvents()
    assert p.repo.workset(id)['config']==saved
    assert p.fields['workers'].value()==saved['workers'] and p.fields['speed'].value()==saved['speed']
    p.repo.state(id,'stopped')


def test_responsive_narrow_scroll_has_no_clipped_config_or_horizontal_panel_scroll(gui,tmp_path):
    app,w,p,id=gui;w.resize(900,580)
    for n in range(3):add_group(p.repo,id,tmp_path/str(n),name=f'{n+1}',count=2)
    p.fields['capcut_mode'].setCurrentIndex(p.fields['capcut_mode'].findData('split'));p.validate_clicked();wait(app,lambda:p.proof is not None)
    app.processEvents();p.adapt_layout();app.processEvents()
    assert p.proof['passed'] and p.right_scroll.verticalScrollBar().isVisible()
    assert not p.right_scroll.horizontalScrollBar().isVisible() and p.completion_ring.isVisible()
    for control in p.fields.values():
        if not control.isHidden():assert control.parentWidget().rect().contains(control.geometry())
    target=os.environ.get('TRANSCOMIC_AUTOMATION_SCREENSHOTS')
    if target:
        directory=Path(target);directory.mkdir(parents=True,exist_ok=True);assert w.grab().save(str(directory/'responsive-narrow.png'))


def test_late_validation_never_enables_start_with_old_config(gui,tmp_path,monkeypatch):
    from transcomic.automation.repository import fingerprint
    app,w,p,id=gui;add_group(p.repo,id,tmp_path/'a');entered=threading.Event();release=threading.Event();original=p.controller.validate;calls=[]
    def delayed(*args,**kwargs):
        proof=original(*args,**kwargs);calls.append(proof['config_fingerprint'])
        if len(calls)==1:entered.set();release.wait(4)
        return proof
    monkeypatch.setattr(p.controller,'validate',delayed);p.validate_clicked();wait(app,entered.is_set)
    try:
        edit=p.fields['project_name'];edit.setFocus();edit.selectAll();QTest.keyClicks(edit,'Latest config')
        assert p.proof is None and not p.start.isEnabled()
    finally:release.set()
    wait(app,lambda:p.proof is not None)
    assert len(calls)==2 and calls[0]!=calls[1]
    assert p.proof['config_fingerprint']==fingerprint(p.repo.workset(id)['config']) and p.start.isEnabled()
    assert w.store.jobs()==[]
