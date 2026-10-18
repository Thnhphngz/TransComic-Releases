"""Final compact columns, responsive header and signal-driven preview control."""
from dataclasses import replace
import pytest
from PySide6.QtCore import Qt,QObject,Signal,QUrl,QPoint,QTimer
from PySide6.QtMultimedia import QMediaPlayer
from PySide6.QtWidgets import QMenu,QApplication
from transcomic.capcut.media import GroupScan
from transcomic.ui.theme import colors
from test_capcut_ui import page
from test_capcut_single_page import populate,settle


@pytest.mark.parametrize('largest',[9,99,184,999,1000,10000])
@pytest.mark.parametrize('dark',[False,True])
def test_stt_digits_fixed_status_flexible_names_and_created_sort(page,tmp_path,largest,dark):
    app,w,p=page
    if w.dark!=dark:w.toggle_theme()
    groups=populate(p,tmp_path);scan=p.scans[groups[0].id]
    p.scans[groups[0].id]=replace(scan,rows=(replace(scan.rows[0],number=largest),));p.render_groups();p.show_group(groups[0].id);settle(app)
    d=p.details;table=d.table;metrics=table.fontMetrics();width=table.columnWidth(0)
    expected=max(metrics.horizontalAdvance('9'*len(str(largest)))+14,table.horizontalHeader().fontMetrics().horizontalAdvance('STT')+12)
    assert width==expected and width>=metrics.horizontalAdvance(str(largest))+12
    assert table.columnWidth(5)==100 and not table.horizontalHeader().stretchLastSection()
    assert d.proxy.columnCount()==7 and not hasattr(d,'created_toggle') and not hasattr(d,'stop_button')
    assert d.proxy.index(0,5).data()=='Khớp' and d.proxy.index(0,5).data(Qt.ToolTipRole)=='Khớp theo vị trí'
    assert p.group_sort.itemData(1)=='created'
    w.resize(1600,900);settle(app);before=(table.columnWidth(0),table.columnWidth(5),table.columnWidth(2),table.columnWidth(3));left=p.workspace.sizes()[0]
    w.resize(1920,1080);settle(app)
    assert table.columnWidth(0)==before[0] and table.columnWidth(5)==before[1]
    assert table.columnWidth(2)>before[2] and table.columnWidth(3)==before[3]
    assert abs(p.workspace.sizes()[0]-left)<=1
    p.show_group(groups[1].id);assert table.columnWidth(0)<=width


@pytest.mark.parametrize('kind,label',[('image','Thiếu ảnh'),('voice','Thiếu voice'),('file','Lỗi file'),('mismatch','Cần kiểm tra')])
def test_short_status_retains_full_errors_and_warning_color(page,tmp_path,kind,label):
    app,w,p=page;group=populate(p,tmp_path,1)[0];scan=p.scans[group.id];pair=scan.rows[0]
    error='Full validation error retained in tooltip, not changed by display'
    if kind=='image':pair=replace(pair,images=(),errors=(error,))
    elif kind=='voice':pair=replace(pair,audios=(),errors=(error,))
    elif kind=='file':pair=replace(pair,audios=(replace(pair.audios[0],error='corrupt'),),errors=(error,))
    else:pair=replace(pair,errors=(error,))
    p.scans[group.id]=replace(scan,rows=(pair,));p.render_groups();p.show_group(group.id);index=p.details.proxy.index(0,5)
    assert index.data()==label and index.data(Qt.ToolTipRole)==error
    assert index.data(Qt.ForegroundRole).name().upper() in ('#FF9999','#B42323')
    assert p.scans[group.id].rows[0] is pair and not pair.valid


class PlaybackBackend(QObject):
    playbackStateChanged=Signal(object)
    def __init__(self):super().__init__();self.state=QMediaPlayer.StoppedState;self.url=QUrl()
    def playbackState(self):return self.state
    def source(self):return self.url
    def setSource(self,url):self.url=url
    def transition(self,state):self.state=state;self.playbackStateChanged.emit(state)
    def stop(self):self.transition(QMediaPlayer.StoppedState)


@pytest.mark.parametrize('missing',[True,False])
def test_audio_invalid_or_absent_disables_toggle(page,tmp_path,missing):
    app,w,p=page;g=populate(p,tmp_path,1)[0];scan=p.scans[g.id];pair=scan.rows[0]
    pair=replace(pair,audios=() if missing else (replace(pair.audios[0],error='corrupt WAV'),),errors=('invalid audio',))
    p.scans[g.id]=replace(scan,rows=(pair,));p.render_groups();p.show_group(g.id)
    p.details.table.setCurrentIndex(p.details.proxy.index(0,0));assert not p.details.action_available(pair,0)
    assert p.player is None


def test_audio_removed_after_scan_is_disabled_without_playback(page,tmp_path):
    from pathlib import Path
    app,w,p=page;g=populate(p,tmp_path,1)[0];audio=p.scans[g.id].rows[0].audios[0]
    Path(audio.path).unlink();p.show_group(g.id);p.details.table.setCurrentIndex(p.details.proxy.index(0,0))
    assert not p.details.action_available(p.scans[g.id].rows[0],0) and p.player is None


def test_header_paths_copy_geometry_and_top_space(page,tmp_path):
    from PySide6.QtTest import QTest
    app,w,p=page;g=populate(p,tmp_path,1)[0]
    long=replace(g,name='Long group '*20,image_dir=g.image_dir+'\\long'*60,audio_dir=g.audio_dir+'\\voice'*60)
    p.manager.replace(long);p.render_groups();p.show_group(g.id);w.resize(1920,1080);settle(app)
    assert p.layout().contentsMargins().top()==8 and p.page_header.y()==8
    assert p.add_button.y()-p.page_header.geometry().bottom()-1==4
    assert not p.group_header.stacked
    assert p.group_summary.mapTo(p.inspector_body,QPoint()).y()>p.group_header.geometry().bottom()
    paths=[p.group_image_path,p.group_audio_path]
    for path in paths:
        assert path.alignment()&Qt.AlignRight and path.toolTip()==path.full and path.text()!=path.full
        clipboard=QApplication.clipboard();old=clipboard.text()
        def choose():
            menu=app.activePopupWidget();assert isinstance(menu,QMenu)
            QTest.mouseClick(menu,Qt.LeftButton,pos=menu.actionGeometry(menu.actions()[0]).center())
        from PySide6.QtGui import QContextMenuEvent
        QTimer.singleShot(0,choose);path.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Mouse,path.rect().center(),path.mapToGlobal(path.rect().center())))
        assert clipboard.text()==path.copy_text and clipboard.text() in (long.image_dir,long.audio_dir);clipboard.setText(old)
    for size in ((1280,720),(1600,900),(1920,1080)):
        w.resize(*size);settle(app)
        for control in [p.group_edit,p.group_up,p.group_down,p.group_remove,*paths]:
            x=control.mapTo(p.inspector_body,QPoint()).x()
            assert x>=0 and x+control.width()<=p.inspector_body.width()
