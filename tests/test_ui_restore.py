"""Manual CapCut isolation, navigation and Automation drop UX; no real API/inference."""
import copy
import os
from pathlib import Path
import threading
import pytest
from PySide6.QtCore import Qt,QPoint,QPointF,QMimeData,QUrl
from PySide6.QtGui import QColor,QDragEnterEvent,QDragMoveEvent,QDragLeaveEvent,QDropEvent
from PySide6.QtWidgets import QApplication,QHeaderView,QWidget
from PySide6.QtTest import QTest
from test_automation_ui import gui,wait
from test_automation import add_group,FakeEngine
from test_capcut_media import media_group
from transcomic.ui.theme import colors


def settle(app,p):
    wait(app,lambda:not p.pair_pending and not p.validation_busy and not p.validation_again and not any(t.is_alive() for t in p.tasks))
    p.flush();app.processEvents()


def send_folder(app,p,folder,row=0,column=2,view=None,finish=True):
    view=view or p.table;index=p.model.index(row,column);view.scrollTo(index);app.processEvents();point=view.visualRect(index).center()
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(folder))])
    enter=QDragEnterEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(view.viewport(),enter)
    if not finish:return enter,point,mime
    drop=QDropEvent(QPointF(point),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(view.viewport(),drop)
    app.processEvents();return enter,drop


@pytest.mark.parametrize('dark',[False,True])
def test_sidebar_navigation_and_transparent_backgrounds(gui,dark):
    app,w,p,id=gui;w.resize(1672,941)
    if w.dark!=dark:w.toggle_theme()
    expected=[0,7,8,9,1,2,3]
    assert [i for title,i in w.navigation_items()]==expected and len(w.nav_buttons)==7
    assert not any(word in b.toolTip() for b in w.nav_buttons for word in ('SRT','Hàng đợi','Console'))
    for compact in (False,True,False):
        if (w.sidebar.width()<100)!=compact:w.toggle_sidebar()
        app.processEvents()
        for button,index in zip(w.nav_buttons,expected):
            QTest.mouseClick(button,Qt.LeftButton);app.processEvents()
            assert w.pages.currentIndex()==index and button.isChecked()
            assert sum(b.isChecked() for b in w.nav_buttons)==1 and not button.icon().isNull()
        assert all(b.text() for b in w.nav_buttons) if not compact else all(not b.text() for b in w.nav_buttons)
    # Old stack IDs still resolve safely; internals are not removed/reindexed.
    for index in (4,5,6):
        w.pages.setCurrentIndex(index);app.processEvents();assert w.pages.currentWidget() is not None
        assert not any(b.isChecked() for b in w.nav_buttons)
    w.pages.setCurrentIndex(9);app.processEvents()
    point=w.navigation_scroll.mapTo(w,QPoint(4,w.navigation_scroll.height()-6));pixel=w.grab().toImage().pixelColor(round(point.x()*w.devicePixelRatioF()),round(point.y()*w.devicePixelRatioF()))
    assert pixel==QColor(colors(w)['sidebar'])
    wrapper=p.output.parentWidget();assert wrapper.objectName()=='automationField'
    assert 'background: transparent' in p.styleSheet()


@pytest.mark.parametrize('dark',[False,True])
def test_empty_filter_state_and_real_file_drop_without_overlay_blocking(gui,tmp_path,dark):
    app,w,p,id=gui
    if w.dark!=dark:w.toggle_theme()
    p.refresh();app.processEvents()
    assert p.empty_state.isVisible() and p.empty_state.text()=='Thêm hoặc kéo thả file văn bản vào đây'
    assert p.empty_state.testAttribute(Qt.WA_TransparentForMouseEvents) and not p.empty_state.acceptDrops()
    assert not p.notice.isVisible()
    path=tmp_path/'Added by drop.txt';path.write_text('A synthetic source line',encoding='utf-8')
    point=QPoint(60,80);mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(path))])
    enter=QDragEnterEvent(point,Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(p.table.viewport(),enter)
    drop=QDropEvent(QPointF(point),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);QApplication.sendEvent(p.table.viewport(),drop)
    wait(app,lambda:len(p.repo.groups(id))==1);p.refresh();app.processEvents()
    assert enter.isAccepted() and drop.isAccepted() and not p.empty_state.isVisible() and not p.notice.isVisible()
    p.search.setText('no match');p.flush();assert p.empty_state.isVisible() and p.empty_state.text()=='Không tìm thấy tài liệu phù hợp'
    p.search.clear();p.flush();assert not p.empty_state.isVisible() and p.model.rowCount()==1
    assert not p.repo.store.jobs() and not FakeEngine.calls


@pytest.mark.parametrize('size',[(900,580),(1200,780),(1672,941)])
def test_all_headers_fixed_drag_does_not_resize_but_layout_and_font_do(gui,tmp_path,size):
    app,w,p,id=gui;add_group(p.repo,id,tmp_path/'g');p.refresh();w.resize(*size);app.processEvents()
    for expanded in (True,False):
        if (w.sidebar.width()>100)!=expanded:w.toggle_sidebar()
        app.processEvents()
        for pane in p.table_panes:
            header=pane.horizontalHeader();columns=[c for c in range(7) if not pane.isColumnHidden(c)]
            assert all(header.sectionResizeMode(c)==QHeaderView.Fixed for c in columns)
            widths=[pane.columnWidth(c) for c in columns]
            edge=header.sectionViewportPosition(columns[0])+header.sectionSize(columns[0])-1
            point=QPoint(edge,header.height()//2);QTest.mouseMove(header.viewport(),point);app.processEvents()
            assert header.viewport().cursor().shape()!=Qt.SplitHCursor
            QTest.mousePress(header.viewport(),Qt.LeftButton,pos=point);QTest.mouseMove(header.viewport(),point+QPoint(100,0));QTest.mouseRelease(header.viewport(),Qt.LeftButton,pos=point+QPoint(100,0));app.processEvents()
            assert [pane.columnWidth(c) for c in columns]==widths
        rect=p.action_table.visualRect(p.model.index(0,6));assert p.action_table.viewport().rect().contains(rect)
    before=p.table.columnWidth(1);w.resize(1800,941);app.processEvents();assert p.table.columnWidth(1)>=before
    font=p.table.font();font.setPixelSize(18)
    for pane in p.table_panes:pane.setFont(font)
    p.adapt_layout();app.processEvents()
    assert len({pane.verticalHeader().defaultSectionSize() for pane in p.table_panes})==1
    assert p.table.columnWidth(3)>=p.table.fontMetrics().horizontalAdvance('999 dòng · 999 ảnh')+16


@pytest.mark.parametrize('column',[0,1,2,3,4,5,6])
def test_folder_drop_any_cell_uses_filtered_stable_group_id_and_preserves_sort(gui,tmp_path,column):
    app,w,p,id=gui;a,_,_=add_group(p.repo,id,tmp_path/'a','First',count=2);b,_,_=add_group(p.repo,id,tmp_path/'b','Second',count=2)
    replacement=media_group(tmp_path/'new',2);p.repo.update_group(b,image_sort='created');p.search.setText('Second');p.refresh();app.processEvents()
    view=p.number_table if column==0 else p.action_table if column==6 else p.table
    enter,drop=send_folder(app,p,replacement.image_dir,column=column,view=view);assert enter.isAccepted() and drop.isAccepted()
    settle(app,p)
    assert p.repo.group(b)['data']['image_folder']==str(Path(replacement.image_dir).resolve())
    assert p.repo.group(b)['data']['image_sort']=='created' and p.repo.group(a)['data']['image_folder']!=str(Path(replacement.image_dir).resolve())
    assert p.repo.group(b)['data']['image_count']==2 and p.repo.group(b)['data']['slot_count']==2
    assert p.proof is not None and p.proof['passed'] and p.model.drop_group_id is None
    assert not p.repo.store.jobs() and not FakeEngine.calls


def test_bad_folder_blank_drop_and_active_drop_preserve_mapping(gui,tmp_path):
    app,w,p,id=gui;gid,_,folder=add_group(p.repo,id,tmp_path/'a',count=2);p.validated(id,w.automation_controller.validate(id));p.refresh();app.processEvents()
    original=copy.deepcopy(p.repo.group(gid)['data']);empty=tmp_path/'empty';empty.mkdir()
    send_folder(app,p,empty);settle(app,p)
    assert 'không có ảnh hợp lệ' in p.notice.text() and p.repo.group(gid)['data']==original
    corrupt=tmp_path/'corrupt';corrupt.mkdir();(corrupt/'001.png').write_bytes(b'not an image')
    send_folder(app,p,corrupt);settle(app,p);assert p.repo.group(gid)['data']==original
    p.drop_paths([str(empty)],None);assert 'đúng hàng' in p.notice.text() and p.repo.group(gid)['data']==original
    # A rejected folder must not bubble into the main window's document importer.
    (empty/'unrelated.txt').write_text('Do not import this folder',encoding='utf-8');count=p.repo.rows('SELECT COUNT(*) n FROM documents')[0]['n']
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(empty))]);event=QDragEnterEvent(QPoint(400,400),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    QApplication.sendEvent(w,event);assert not event.isAccepted()
    w.dropEvent(QDropEvent(QPointF(400,400),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier))
    assert p.repo.rows('SELECT COUNT(*) n FROM documents')[0]['n']==count
    p.repo.activate(id);p.refresh();app.processEvents()
    enter,_,_=send_folder(app,p,folder,finish=False);assert not enter.isAccepted()
    assert 'dừng an toàn' in p.notice.text() and p.model.drop_group_id is None
    p.drop_paths([str(empty)],gid);assert p.repo.group(gid)['data']==original
    p.repo.state(id,'stopped')


def test_stopped_folder_change_then_resume_reuses_voice_and_keeps_sources(gui,tmp_path):
    app,w,p,id=gui;gid,source,folder=add_group(p.repo,id,tmp_path/'g',count=2);c=w.automation_controller
    p.validated(id,c.validate(id));c.start(id);wait(app,lambda:not c.busy);p.refresh()
    original=p.repo.group(gid)['data'];old_project=Path(original['project']);old_audio=Path(original['audio_folder']);old_calls=len(FakeEngine.calls);old_source=source.read_bytes()
    replacement=media_group(tmp_path/'replacement',2)
    p.repo.state(id,'stopped');p.refresh();send_folder(app,p,replacement.image_dir);settle(app,p)
    assert p.proof['passed'] and old_project.is_dir() and old_audio.is_dir()
    c.start(id);wait(app,lambda:not c.busy);p.refresh()
    assert p.repo.workset(id)['state']=='completed' and source.read_bytes()==old_source
    assert len(FakeEngine.calls)==old_calls and old_project.is_dir() and old_audio.is_dir()
    assert Path(p.repo.group(gid)['data']['project'])!=old_project


def test_drop_race_does_not_commit_if_workset_started_while_scan_pending(gui,tmp_path,monkeypatch):
    from transcomic.automation import validation
    app,w,p,id=gui;gid,_,folder=add_group(p.repo,id,tmp_path/'g');replacement=media_group(tmp_path/'new');p.refresh()
    original=copy.deepcopy(p.repo.group(gid)['data']);entered=threading.Event();release=threading.Event();real=validation.image_manifest
    def delayed(*a,**k):entered.set();release.wait(4);return real(*a,**k)
    monkeypatch.setattr(validation,'image_manifest',delayed)
    try:
        p.drop_paths([replacement.image_dir],gid);wait(app,entered.is_set);assert not p.start.isEnabled()
        p.repo.activate(id);release.set();wait(app,lambda:not p.pair_pending);p.flush()
        assert p.repo.group(gid)['data']==original and 'Dừng an toàn' in p.notice.text()
    finally:release.set();p.repo.state(id,'stopped')


def test_mismatched_folder_updates_counts_and_blocks_start_without_running(gui,tmp_path):
    app,w,p,id=gui;gid,_,_=add_group(p.repo,id,tmp_path/'g',count=2);new=media_group(tmp_path/'one-image',1);p.refresh();app.processEvents()
    send_folder(app,p,new.image_dir);settle(app,p)
    data=p.repo.group(gid)['data']
    assert data['image_count']==1 and data['slot_count']==2
    assert not p.proof['passed'] and not p.start.isEnabled() and data['error']
    assert not p.repo.store.jobs() and not FakeEngine.calls


def test_latest_folder_drop_wins_when_prechecks_finish_out_of_order(gui,tmp_path,monkeypatch):
    from transcomic.automation import validation
    app,w,p,id=gui;gid,_,_=add_group(p.repo,id,tmp_path/'g',count=2);first=media_group(tmp_path/'first',2);last=media_group(tmp_path/'last',2);p.refresh()
    entered=threading.Event();release=threading.Event();real=validation.image_manifest
    def delayed(folder,sort):
        if str(folder)==first.image_dir:entered.set();release.wait(4)
        return real(folder,sort)
    monkeypatch.setattr(validation,'image_manifest',delayed)
    try:
        p.drop_paths([first.image_dir],gid);wait(app,entered.is_set);p.drop_paths([last.image_dir],gid)
        wait(app,lambda:p.repo.group(gid)['data']['image_folder']==str(Path(last.image_dir).resolve()))
        release.set();settle(app,p)
        assert p.repo.group(gid)['data']['image_folder']==str(Path(last.image_dir).resolve())
        assert p.proof['passed'] and not p.repo.store.jobs() and not FakeEngine.calls
    finally:release.set()


@pytest.mark.parametrize('dark',[False,True])
def test_acceptance_screenshots_manual_capcut_empty_many_and_drag(gui,tmp_path,dark):
    app,w,p,id=gui;w.resize(1672,941)
    if w.dark!=dark:w.toggle_theme()
    if w.sidebar.width()<100:w.toggle_sidebar()
    target=os.environ.get('TRANSCOMIC_RESTORE_SCREENSHOTS');directory=Path(target or tmp_path/'shots');directory.mkdir(parents=True,exist_ok=True);theme='dark' if dark else 'light'
    p.refresh();app.processEvents();assert w.grab().save(str(directory/f'automation-empty-{theme}.png'))
    for n in range(6):add_group(p.repo,id,tmp_path/str(n),name=f'{n*2+1}-{n*2+2}',count=2)
    p.validated(id,w.automation_controller.validate(id));p.refresh();app.processEvents();assert w.grab().save(str(directory/f'automation-many-{theme}.png'))
    folder=p.repo.groups(id)[2]['data']['image_folder'];table_position=p.table_shell.geometry();enter,point,mime=send_folder(app,p,folder,row=2,finish=False)
    assert enter.isAccepted() and p.model.drop_group_id==p.model.rows[2]['id']
    assert p.table_shell.geometry()==table_position
    app.processEvents();assert w.grab().save(str(directory/f'automation-drag-{theme}.png'))
    QApplication.sendEvent(p.table.viewport(),QDragLeaveEvent());assert p.model.drop_group_id is None
    before=p.repo.workset(id)['checkpoint'];w.pages.setCurrentIndex(8);app.processEvents();cap=w.capcut_page
    assert not hasattr(cap,'automation_mirror') and not cap.manager.groups
    for n in range(3):cap.manager.add(media_group(tmp_path/f'manual{n}',2,f'Manual {n+1}'))
    cap.render_groups();cap.scan_all();wait(app,lambda:not cap.busy);cap.show_group(cap.manager.groups[0].id)
    cap.mode.setCurrentIndex(cap.mode.findData('split'));cap.part_count.setValue(2);cap.project_name.setText('Manual');cap.output.setText(str(tmp_path/'manual projects'));cap.save_options()
    cap.details.table.viewport().update();app.processEvents();wait(app,lambda:len(cap.thumbs.cache)>=2)
    app.processEvents();assert w.grab().save(str(directory/f'capcut-manual-{theme}.png'))
    assert len(cap.manager.groups)==3 and p.repo.workset(id)['checkpoint']==before and not p.repo.store.jobs() and not FakeEngine.calls
