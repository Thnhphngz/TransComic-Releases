"""Software-only captures of the real MainWindow, isolated synthetic workspace."""
import os,sys,json,time,wave,argparse
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['QT_OPENGL']='software';os.environ['QT_QUICK_BACKEND']='software';os.environ['TRANSCOMIC_RELEASE_OFFLINE_TESTS']='1'
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage,QColor,QPainter,QFontDatabase,QFont
from PySide6.QtWidgets import QApplication,QLineEdit
from PySide6.QtTest import QTest
from transcomic.capcut.media import MediaGroup
from transcomic.storage import Store


def settle(app):
    for _ in range(8):app.processEvents();time.sleep(.015)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--theme',choices=['light','dark'],default='dark');parser.add_argument('--output-dir',default='artifacts/capcut-two-column');parser.add_argument('--baseline-zip');args=parser.parse_args()
    if args.baseline_zip:
        import zipfile,types
        with zipfile.ZipFile(args.baseline_zip) as snapshot:
            for name in ('capcut_cards','capcut_workspace','capcut_page'):
                key='transcomic.ui.'+name;filename='transcomic/ui/'+name+'.py'
                module=types.ModuleType(key);module.__package__='transcomic.ui';module.__file__=str(Path(filename).resolve());sys.modules[key]=module
                exec(compile(snapshot.read(filename).decode('utf8'),module.__file__,'exec'),module.__dict__)
    from transcomic.ui.main import MainWindow
    app=QApplication([]);app.setCursorFlashTime(0)
    for filename in ('segoeui.ttf','segoeuib.ttf','seguisb.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/filename))
    app.setFont(QFont('Segoe UI',10))
    root=Path(args.output_dir);root.mkdir(parents=True,exist_ok=True);groups=[]
    for i in range(10):
        images=root/'synthetic-media'/str(i+1)/'images';voice=images.parent/'voice';images.mkdir(parents=True,exist_ok=True);voice.mkdir(exist_ok=True)
        for n in range(1,13):
            image_file=images/f'{n:04}.png';audio_file=voice/f'{n:04}.wav'
            if not image_file.exists():
                image=QImage(400,220,QImage.Format_RGB32);image.fill(QColor.fromHsv((i*37+n*11)%360,100,180))
                painter=QPainter(image);painter.setPen(Qt.white);painter.setFont(QFont('Segoe UI',24));painter.drawText(image.rect(),Qt.AlignCenter,f'GROUP {i+1}\nPANEL {n}');painter.end();assert image.save(str(image_file))
            if not audio_file.exists():
                with wave.open(str(audio_file),'wb') as f:f.setparams((1,2,8000,0,'NONE','not compressed'));f.writeframes(b'\0\0'*(4000+n*100))
        groups.append(MediaGroup.create(f'{i*2+1}–{i*2+2}',images.resolve(),voice.resolve(),'name'))
    scale=float(os.environ.get('QT_SCALE_FACTOR','1'));suffix=f'{args.theme}-{round(scale*100)}'
    store=Store(root/f'capture-{suffix}.sqlite3')
    store.set_setting('dark','1' if args.theme=='dark' else '0')
    store.set_setting('capcut_workspace_v1',json.dumps({'groups':[g.__dict__ for g in groups],'mode':'split','name':'vote','part_count':4,'output':str((root/'synthetic-output').resolve())},ensure_ascii=False))
    window=MainWindow(store);window.resize(1600,900);window.show();window.pages.setCurrentIndex(8);p=window.capcut_page;settle(app)
    end=time.monotonic()+15
    while p.busy and time.monotonic()<end:app.processEvents();time.sleep(.01)
    assert not p.busy and len(p.scans)==10
    if window.sidebar.width()<100:window.toggle_sidebar()
    p.show_group(groups[0].id);p.details.table.setCurrentIndex(p.details.proxy.index(0,0));settle(app)
    metrics=[]
    for width,height in [(1280,720),(1600,900),(1920,1080)]:
        window.resize(width,height);settle(app)
        image=window.grab();path=root/f'{suffix}-{width}x{height}.png';assert image.save(str(path))
        assert p.details.table.grab().save(str(root/f'{suffix}-{width}x{height}-table.png'))
        has_actions=hasattr(p.details,'playing_pair_id')
        metrics.append({'logical_size':[window.width(),window.height()],'physical_size':[image.width(),image.height()],'sidebar_width':window.sidebar.width(),'splitter_sizes':p.workspace.sizes(),'table_height':p.details.table.height(),'table_viewport_height':p.details.table.viewport().height(),'settings_height':p.settings_frame.height(),'capture':path.name,'stt_width':p.details.table.columnWidth(0),'status_width':p.details.table.columnWidth(5 if has_actions else 6),'actions_width':p.details.table.columnWidth(6) if has_actions else None,'image_width':p.details.table.columnWidth(2),'audio_width':p.details.table.columnWidth(3),'page_top_margin':p.layout().contentsMargins().top(),'header_y':p.page_header.y(),'header_toolbar_gap':p.add_button.y()-p.page_header.geometry().bottom()-1,'group_header_height':p.group_header.height() if hasattr(p,'group_header') else 0})
    if hasattr(p.details,'playing_pair_id'):
        # Capture the stop icon using an isolated backend; never play audio on the host.
        from PySide6.QtCore import QObject,Signal,QUrl
        from PySide6.QtMultimedia import QMediaPlayer
        from transcomic.ui.capcut_preview import CapcutPlayer
        from transcomic.capcut.exporter import reference
        class CapturedPlayback(QObject):
            playbackStateChanged=Signal(object)
            def __init__(self):super().__init__();self.state=QMediaPlayer.PlayingState;self.url=QUrl()
            def playbackState(self):return self.state
            def source(self):return self.url
            def stop(self):self.state=QMediaPlayer.StoppedState;self.playbackStateChanged.emit(self.state)
            def setSource(self,url):self.url=url
        p.player=CapcutPlayer(p,compact=True);p.player.hide();p.player.native_backend=p.player.player;p.player.player=CapturedPlayback()
        p.player.player.playbackStateChanged.connect(p.details.sync_audio)
        pair=p.scans[groups[0].id].rows[0];p.details.audio_pair=pair;p.active_details=p.details
        p.player.player.setSource(QUrl.fromLocalFile(reference(pair.audios[0].path)));p.details.sync_audio();settle(app)
        assert p.details.playing_pair_id==pair.id
        assert p.details.table.grab().save(str(root/f'{suffix}-row-playing-table.png'))
        assert window.grab().save(str(root/f'{suffix}-row-playing-full.png'));p.stop_audio()
    window.resize(1600,900);window.toggle_sidebar();settle(app)
    assert window.grab().save(str(root/f'{suffix}-sidebar-collapsed.png'))
    p.settings_toggle.click();settle(app);assert window.grab().save(str(root/f'{suffix}-settings-collapsed.png'));p.settings_toggle.click()
    index=p.split_model.index(0,0);p.split_preview.edit(index);settle(app)
    editor=next(e for e in p.split_preview.findChildren(QLineEdit) if e.isVisible());editor.deselect();editor.setCursorPosition(4);editor.setFocus();settle(app)
    assert window.grab().save(str(root/f'{suffix}-name-editor.png'));QTest.keyClick(editor,Qt.Key_Escape)
    from dataclasses import replace
    first=groups[0].id;original=p.scans[first];p.scans[first]=replace(original,errors=('Fixture: nhóm cần kiểm tra trước khi xuất.',));p.render_groups();settle(app)
    assert window.grab().save(str(root/f'{suffix}-validation-error.png'))
    p.scans[first]=original;p.render_groups();p.busy=True;p.operation='export';p.set_busy(True);settle(app)
    assert window.grab().save(str(root/f'{suffix}-export-locked.png'))
    p.busy=False;p.operation=None;p.set_busy(False)
    window.resize(1280,720);p.settings_toggle.setChecked(False);settle(app)
    assert window.grab().save(str(root/f'{suffix}-720-settings-open.png'))
    (root/f'metrics-{suffix}.json').write_text(json.dumps(metrics,indent=2),encoding='utf8')
    window._exit_authorized=True;window.close();app.processEvents();print(json.dumps(metrics))


if __name__=='__main__':main()
