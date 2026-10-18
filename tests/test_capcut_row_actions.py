"""Real row hit targets and virtual controls, synthetic files and signal backend."""
from dataclasses import replace
from pathlib import Path
import time
import pytest
from PySide6.QtCore import Qt,QPoint,QPointF,QUrl,QEvent,QModelIndex
from PySide6.QtGui import QHelpEvent,QMouseEvent
from PySide6.QtWidgets import QWidget,QLineEdit,QToolTip
from PySide6.QtTest import QTest
from PySide6.QtMultimedia import QMediaPlayer
from transcomic.capcut.media import GroupScan
from transcomic.ui.capcut_actions import button_rects
from transcomic.ui.capcut_preview import CapcutPlayer
from test_capcut_ui import page
from test_capcut_single_page import populate,settle
from test_capcut_final_polish import PlaybackBackend


@pytest.fixture
def playback(monkeypatch):
    original=CapcutPlayer.__init__;plays=[]
    def init(player,*args,**kwargs):
        original(player,*args,**kwargs);player.native_backend=player.player;player.player=PlaybackBackend()
    def play(player,entries,index=0):
        player.stop();player.entries=list(entries);player.index=index
        player.player.setSource(QUrl.fromLocalFile(entries[index][0]));player.player.transition(QMediaPlayer.PlayingState);plays.append(entries)
    monkeypatch.setattr(CapcutPlayer,'__init__',init);monkeypatch.setattr(CapcutPlayer,'play',play)
    return plays


def click(app,d,row,action):
    index=d.proxy.index(row,6);d.table.scrollTo(index);settle(app)
    rect=button_rects(d.table.visualRect(index))[action]
    assert d.table.viewport().rect().contains(rect)
    QTest.mouseMove(d.table.viewport(),rect.center());QTest.mouseClick(d.table.viewport(),Qt.LeftButton,pos=rect.center());settle(app)


def move(app,table,point,buttons=Qt.NoButton):
    # QTest.mouseMove moves the OS cursor, which can be outside the offscreen
    # virtual screen at 150%. Deliver the same Qt viewport event in logical coords.
    app.sendEvent(table.viewport(),QMouseEvent(QEvent.MouseMove,QPointF(point),QPointF(table.viewport().mapToGlobal(point)),Qt.NoButton,buttons,Qt.NoModifier))


@pytest.mark.parametrize('reason',[Qt.MouseFocusReason,Qt.ActiveWindowFocusReason,Qt.OtherFocusReason])
def test_mouse_focus_preserves_current_and_selection(page,tmp_path,playback,reason):
    app,w,p=page;group=populate(p,tmp_path,1)[0];p.show_group(group.id);d=p.details
    for row in (None,1):
        d.search.setFocus(Qt.OtherFocusReason);settle(app)
        current=QModelIndex() if row is None else d.proxy.index(row,0)
        # Setting even an invalid current index tells Qt a user chose it and
        # masks its automatic first-focus selection on a fresh model.
        if row is not None:d.table.setCurrentIndex(current)
        assert d.table.currentIndex()==current
        before=d.table.selectionModel().selection()
        d.table.setFocus(reason);settle(app)
        assert d.table.hasFocus()
        assert d.table.currentIndex()==current
        assert d.table.selectionModel().selection()==before
        click(app,d,0,0)
        assert d.table.currentIndex()==current
        assert d.table.selectionModel().selection()==before


def test_click_audio_row_without_selection_switch_end_error_filter_hide_close(page,tmp_path,playback):
    app,w,p=page;groups=populate(p,tmp_path);p.show_group(groups[0].id);d=p.details
    assert not d.table.currentIndex().isValid() and not hasattr(d,'play_button') and not hasattr(d,'preview_toggle')
    resets=[];d.model.modelReset.connect(lambda:resets.append(1));changed=[]
    d.model.dataChanged.connect(lambda a,b,*_:changed.append((a.row(),a.column(),b.row(),b.column())))
    first,second=p.scans[groups[0].id].rows[:2]
    click(app,d,0,0);player=p.player
    assert d.playing_pair_id==first.id and playback[-1][0][0]==first.audios[0].path
    assert not d.table.currentIndex().isValid() and not d.table.selectionModel().selectedRows()
    assert 'Dừng' in d.proxy.index(0,6).data(Qt.AccessibleTextRole) and 'Phát' in d.proxy.index(1,6).data(Qt.AccessibleTextRole)
    click(app,d,0,0);assert d.playing_pair_id is None and player.player.source().isEmpty()
    click(app,d,0,0);click(app,d,1,0)
    assert d.playing_pair_id==second.id and p.player is player and playback[-1][0][0]==second.audios[0].path
    assert 'Phát' in d.proxy.index(0,6).data(Qt.AccessibleTextRole)
    player.media_status(QMediaPlayer.EndOfMedia);assert d.playing_pair_id is None
    click(app,d,0,0);player.error.emit('fixture error');assert d.playing_pair_id is None and player.player.source().isEmpty()
    click(app,d,0,0);d.search.setText('002');assert d.playing_pair_id is None and player.player.source().isEmpty()
    assert d.proxy.rowCount()==1;click(app,d,0,0);assert d.playing_pair_id==second.id
    controls=[a for a in changed if a[1]==7]
    assert not resets and controls and all(a[1]==a[3]==7 and a[0]==a[2] for a in controls)
    assert all(a[1] in (1,7) for a in changed)  # asynchronous thumbnails are independent
    p.show_group(groups[1].id);assert d.playing_pair_id is None and player.player.source().isEmpty()
    click(app,d,0,0);w.pages.setCurrentIndex(0);assert d.playing_pair_id is None
    w.pages.setCurrentIndex(8);click(app,d,0,0);assert len(p.findChildren(CapcutPlayer))==1
    w._exit_authorized=True;w.close();settle(app);assert p.closed


def test_image_buttons_exact_file_without_selection_and_close(page,tmp_path):
    app,w,p=page;group=populate(p,tmp_path,1)[0];p.show_group(group.id);d=p.details
    for row in (0,1):
        click(app,d,row,1)
        assert d.preview.isVisible() and d.preview_file.path==p.scans[group.id].rows[row].images[0].path
        assert not d.table.currentIndex().isValid() and p.player is None
        end=time.monotonic()+3
        while not d.preview.pixmap() and time.monotonic()<end:app.processEvents();time.sleep(.01)
        assert d.preview.pixmap() and not d.preview.pixmap().isNull()
        d.preview.close_button.click();assert not d.preview.isVisible()


@pytest.mark.parametrize('action',[0,1])
@pytest.mark.parametrize('problem',['absent','error','removed','changed'])
def test_disabled_row_actions_do_not_play_or_preview(page,tmp_path,action,problem,playback):
    app,w,p=page;g=populate(p,tmp_path,1)[0];scan=p.scans[g.id];pair=scan.rows[0]
    attr='audios' if action==0 else 'images';files=getattr(pair,attr)
    if problem=='absent':pair=replace(pair,**{attr:()})
    elif problem=='error':pair=replace(pair,**{attr:(replace(files[0],error='fixture corruption'),)})
    elif problem=='removed':Path(files[0].path).unlink()
    else:Path(files[0].path).write_bytes(b'changed fixture')
    p.scans[g.id]=replace(scan,rows=(pair,*scan.rows[1:]));p.render_groups();p.show_group(g.id);d=p.details
    assert not d.action_available(pair,action)
    click(app,d,0,action);assert not playback and p.player is None and not d.preview.isVisible()


def test_image_decode_failure_in_preview_safe(page,tmp_path,monkeypatch):
    from PySide6.QtGui import QPixmap
    app,w,p=page;g=populate(p,tmp_path,1)[0];p.show_group(g.id);d=p.details
    monkeypatch.setattr(p.preview_cache,'get',lambda f:QPixmap())
    click(app,d,0,1);assert d.preview.isVisible() and 'Không thể đọc ảnh' in d.preview.text()
    assert not d.action_available(p.scans[g.id].rows[0],1)


def test_long_audio_filename_elides_middle_retains_extension_and_tooltip(page,tmp_path):
    app,w,p=page;g=populate(p,tmp_path,1)[0];scan=p.scans[g.id];pair=scan.rows[0]
    original=pair.audios[0];name='Narration chapter '+('very long '*12)+'.wav'
    # Display metadata fixture only; source file is neither renamed nor copied.
    replacement=replace(original,path=str(Path(original.path).parent/name))
    p.scans[g.id]=replace(scan,rows=(replace(pair,audios=(replacement,)),));p.render_groups();p.show_group(g.id)
    d=p.details;index=d.proxy.index(0,3)
    assert index.data()==name and name in index.data(Qt.ToolTipRole)
    assert d.table.textElideMode()==Qt.ElideMiddle
    elided=d.table.fontMetrics().elidedText(name,Qt.ElideMiddle,d.table.columnWidth(3)-8)
    assert elided.endswith('.wav') and elided!=name


@pytest.mark.parametrize('dark',[False,True])
def test_hover_press_cancel_tooltip_keyboard_and_no_edit(page,tmp_path,dark,playback):
    app,w,p=page
    if w.dark!=dark:w.toggle_theme()
    g=populate(p,tmp_path,1)[0];p.show_group(g.id);d=p.details;table=d.table;index=d.proxy.index(0,6)
    table.scrollTo(index);settle(app);rects=button_rects(table.visualRect(index));pair=p.scans[g.id].rows[0]
    move(app,table,rects[0].center());assert table.hover==(pair.id,0)
    QTest.mousePress(table.viewport(),Qt.LeftButton,pos=rects[0].center());assert table.pressed==(pair.id,0)
    move(app,table,rects[1].center(),Qt.LeftButton);QTest.mouseRelease(table.viewport(),Qt.LeftButton,pos=rects[1].center())
    assert not playback and not table.pressed and not d.preview.isVisible()
    help_event=QHelpEvent(QEvent.ToolTip,rects[1].center(),table.viewport().mapToGlobal(rects[1].center()))
    app.sendEvent(table.viewport(),help_event);assert 'Xem ảnh' in QToolTip.text();QToolTip.hideText()
    table.setCurrentIndex(index);table.setFocus(Qt.TabFocusReason)
    QTest.keyClick(table,Qt.Key_Left);QTest.keyClick(table,Qt.Key_Space);assert d.playing_pair_id==pair.id
    QTest.keyClick(table,Qt.Key_Return);assert d.playing_pair_id is None
    QTest.keyClick(table,Qt.Key_Right);QTest.keyClick(table,Qt.Key_Space);assert d.preview_file.path==pair.images[0].path
    assert not table.findChildren(QLineEdit) and not table.model().flags(index)&Qt.ItemIsEditable


@pytest.mark.parametrize('rows',[10,184,1000])
def test_virtual_actions_columns_resize_sort_and_widget_bound(page,tmp_path,rows,playback):
    app,w,p=page;groups=populate(p,tmp_path);scan=p.scans[groups[0].id]
    p.scans[groups[0].id]=replace(scan,rows=tuple(replace(scan.rows[0],id=f'{groups[0].id}:{i}',number=i) for i in range(1,rows+1)))
    p.render_groups();p.show_group(groups[0].id);d=p.details;settle(app)
    count=len(d.findChildren(QWidget));models=d.model;workers=(p.thumbs.thread,p.preview_cache.thread)
    assert [d.proxy.headerData(i,Qt.Horizontal) for i in range(7)]==['STT','Ảnh','Tên ảnh','File audio','Thời lượng','Trạng thái','Thao tác']
    assert not hasattr(d,'play_button') and not hasattr(d,'preview_toggle')
    for size in [(1280,720),(1600,900),(1920,1080)]:
        w.resize(*size);settle(app)
        index=d.proxy.index(0,6);assert d.table.visualRect(index).right()<=d.table.viewport().rect().right()
        assert d.table.columnWidth(3)==140 and d.table.columnWidth(5)==100
    d.table.horizontalHeader().resizeSection(3,175);assert d.table.columnWidth(3)==175
    click(app,d,rows-1,0);id=d.playing_pair_id;assert id==f'{groups[0].id}:{rows}'
    d.proxy.sort(0,Qt.DescendingOrder);settle(app)
    assert d.playing_pair_id in (None,id)
    assert d.model is models and len(d.findChildren(QWidget))<=count and len(d.availability)<=256
    assert (p.thumbs.thread,p.preview_cache.thread)==workers and len(p.findChildren(CapcutPlayer))==1
    assert len(p.thumbs.cache)<=128 and len(p.thumbs.pending)<=32
