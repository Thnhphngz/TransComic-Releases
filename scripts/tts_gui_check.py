"""Native layout/DPI checks using isolated synthetic audio, never user data.

Real voice inference is tested separately by --tts-source-smoke.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--scale',default='1');parser.add_argument('--dark',action='store_true');parser.add_argument('--output',required=True);parser.add_argument('--voice-fixture');args=parser.parse_args()
    import ctypes
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    os.environ['QT_SCALE_FACTOR']=str(float(args.scale)/(ctypes.windll.user32.GetDpiForSystem()/96))
    from scripts.test_runtime import TemporaryDirectory
    from PySide6.QtWidgets import QApplication,QMessageBox,QLineEdit
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt,QTimer,QPoint
    from transcomic.storage import Store
    from transcomic.ui.main import MainWindow
    from transcomic.tts.output import Outputs
    from transcomic.tts.audio import encode
    import numpy as np
    app=QApplication([])
    def settle(ms=80):app.processEvents();QTest.qWait(ms);time.sleep(.003);app.processEvents()
    def wait(condition):
        end=time.monotonic()+20
        while not condition() and time.monotonic()<end:settle(20)
        assert condition()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=True);tag=('dark' if args.dark else 'light')+'-'+args.scale
    results=dict(scale=args.scale,dark=args.dark,fixture='synthetic audio for native GUI layout only',screenshots=[])
    with TemporaryDirectory() as temp:
        root=Path(temp);store=Store(root/'translation.sqlite3');store.set_setting('dark','1' if args.dark else '0')
        window=MainWindow(store);window.confirm_exit=lambda running:'safe' if running else 'exit';screen=app.primaryScreen().availableGeometry();window.resize(min(1380,screen.width()),min(820,screen.height()));window.show();window.pages.setCurrentIndex(7);settle();page=window.tts_page;wait(lambda:not page.is_busy())
        for name,count in [('Chapter 9',145),('Chapter 10',120)]:
            text='\n'.join(f'A calm morning. Segment {i+1}.' for i in range(count));source=root/(name+'.txt');source.write_text(text,encoding='utf8')
            page.store.add_document(page.run_id,dict(name=name,text=text,line_count=count,path=str(source)))
        config=page.config();config['device']='CPU';output=Outputs(page.store);output.confirm(page.run_id,config,output.plan(page.run_id,'custom',str(root),'wav'))
        for n in range(3):
            item=page.store.claim(page.run_id);doc=page.store.doc(item['document_id']);target=Path(doc['folder'])/(str(n)+'.part')
            audio=np.sin(np.arange(72000)*.04).astype('float32')*.1
            if args.voice_fixture:
                from scripts.test_runtime import outside
                import soundfile as sf
                audio,rate=sf.read(outside(Path(args.voice_fixture).absolute()),dtype='float32');assert rate==24000
            info=encode(target,[audio]);assert output.commit(item,target,info,'Layout fixture')
        page.store.execute('UPDATE runs SET history_accepted=1 WHERE id=?',(page.run_id,));page.store.status(page.run_id,'paused');page.refresh_files();page.load_history();page.runtime_label.setText('Kokoro ONNX · Bố cục kiểm thử ngoại tuyến');settle()
        results['dpr']=window.devicePixelRatioF();assert abs(results['dpr']-float(args.scale))<.02
        def capture(name):
            settle();path=out/(tag+'-'+name+'.png');assert window.grab().save(str(path));results['screenshots'].append(str(path))
        def geometry():
            fields=page.config_fields
            assert all(page.controls.rect().contains(f.geometry()) for f in fields)
            assert all(not a.geometry().intersects(b.geometry()) for i,a in enumerate(fields) for b in fields[i+1:])
            assert page.start_button.isVisible() and page.tabs.height()>100
            assert page.history_panel.y()==page.workspace.y() and abs(page.history_panel.height()-page.workspace.height())<=2
            actions=[page.start_button,page.pause_button,page.stop_button,page.progress_bar]
            assert all(not a.geometry().intersects(b.geometry()) for i,a in enumerate(actions) for b in actions[i+1:])
            assert all(card.listen.isHidden() for card in page.history_panel.cards.values())
        page.history_panel.show();page.splitter.setSizes([780,310]);settle();geometry();capture('files')
        from transcomic.ui.tts_models import CenterCheckDelegate
        from PySide6.QtWidgets import QStyleOptionViewItem
        index=page.document_model.index(1,0);page.file_table.setRowHeight(1,65);rect=page.file_table.visualRect(index);option=QStyleOptionViewItem();option.widget=page.file_table;option.rect=rect;check=CenterCheckDelegate.check_rect(option)
        assert abs(check.center().x()-rect.center().x())<=1 and abs(check.center().y()-rect.center().y())<=1
        QTest.mouseClick(page.file_table.viewport(),Qt.LeftButton,pos=rect.topLeft()+QPoint(2,2));assert page.document_model.checked=={page.document_model.items[1]['id']};assert not page.file_table.keyboard_focus;capture('selected-centered-checkbox')
        def capture_confirmation():
            box=next(w for w in app.topLevelWidgets() if isinstance(w,QMessageBox) and w.isVisible());assert box.grab().save(str(out/(tag+'-clear-confirm.png')));next(b for b in box.buttons() if b.text()=='Hủy').click()
        QTimer.singleShot(150,capture_confirmation);assert not page.confirm_clear_history()
        results['layout_geometry']={name:[getattr(page,name).x(),getattr(page,name).y(),getattr(page,name).width(),getattr(page,name).height()] for name in ('workspace','runtime_label','controls','tab_strip','tabs')}
        card=next(iter(page.history_panel.cards.values()));before=card.size();page.open_sentences(card.id);settle();assert card.size()==before;assert page.audio_dialog.grab().save(str(out/(tag+'-popup.png')));page.audio_dialog.reject()
        stable=(page.tabs.geometry(),page.history_panel.geometry(),card.size());first=page.store.rows("SELECT id FROM segments WHERE state='success' ORDER BY position LIMIT 1")[0]['id'];page.play_segment(first);wait(lambda:page.playing==first and page.player.player.position()>30 and page.player.player.duration()>0);settle();assert stable==(page.tabs.geometry(),page.history_panel.geometry(),card.size())
        assert not page.player.geometry().intersects(page.start_button.geometry());assert page.player.width()>min(550,page.workspace.width()-20);capture('player');page.player.close_button.click();assert page.player.player.source().isEmpty() and page.player.isHidden()
        index=page.document_model.index(1,8);page.file_table.scrollTo(index);settle();rect=page.file_table.visualRect(index)
        QTest.mouseClick(page.file_table.viewport(),Qt.LeftButton,pos=rect.center());assert page.detail_document==page.store.docs(page.run_id)[1]['id'];assert page.model.rowCount()==120;capture('details')
        edit=page.model.index(0,1);original=edit.data();page.table.setCurrentIndex(edit);page.table.edit(edit);settle();editor=page.table.findChild(QLineEdit);assert editor and editor.isVisible();editor.selectAll();QTest.keyClicks(editor,'Edited fixture text');capture('details-editing');QTest.keyClick(editor,Qt.Key_Return);settle();QTest.keyClick(page.table,Qt.Key_Z,Qt.ControlModifier);assert page.model.index(0,1).data()==original
        page.tabs.setCurrentIndex(1);page.input_text.setPlainText('Hello there.\nA new beginning!\nHow are you?');page.update_input_counts();settle();capture('input')
        stable=(page.tab_bar.geometry(),page.tab_strip.height(),page.tabs.geometry());page.split_controls.toggle.setChecked(False);settle();assert stable==(page.tab_bar.geometry(),page.tab_strip.height(),page.tabs.geometry());capture('input-off')
        page.open_settings();settle();assert page.settings_dialog.isVisible();assert page.settings_dialog.grab().save(str(out/(tag+'-settings.png')));page.settings_dialog.close()
        page.tabs.setCurrentIndex(0);window.resize(900,580);settle();assert window.size().width()==900 and window.size().height()==580;geometry();assert not page.history_panel.isHidden();capture('small');small_size=[window.width(),window.height()]
        window.showMaximized();settle();geometry();capture('maximized')
        results.update(document_rows=page.document_model.rowCount(),detail_rows=page.model.rowCount(),small_size=small_size,maximized_size=[window.width(),window.height()],no_overlap=True,details_click=True,history_fixed=True,centered_checkbox=True,committed_undo=True,output_device=page.player.output.device().description())
        page.request_stop();wait(lambda:not page.is_busy());window.close();wait(lambda:window._closed)
    (out/(tag+'.json')).write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf8');return 0


if __name__=='__main__':raise SystemExit(main())
