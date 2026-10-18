"""Small CPU-only source acceptance and screenshots using synthetic media.

Does not launch CapCut, TTS, API requests, a build, or the production database.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
os.environ.setdefault('QT_OPENGL','software')
os.environ.setdefault('QT_QUICK_BACKEND','software')
os.environ['TRANSCOMIC_RELEASE_OFFLINE_TESTS']='1'
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QPainter,QColor,QFontDatabase,QFont
from PySide6.QtCore import Qt
from transcomic.capcut.media import MediaGroup,scan_group
from transcomic.capcut.exporter import export_projects,validate_content,load_template
from transcomic.storage import Store
from transcomic.ui.main import MainWindow


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--theme',choices=('light','dark'),default='light');parser.add_argument('--screenshots-only',action='store_true');parser.add_argument('--output-dir',default='artifacts/capcut');parser.add_argument('--group-count',type=int,default=3);parser.add_argument('--split-count',type=int);parser.add_argument('--custom-names',action='store_true');args=parser.parse_args()
    if not 1<=args.group_count<=20:parser.error('group-count must be 1..20')
    if args.split_count is not None and not 2<=args.split_count<=args.group_count:parser.error('split-count must be 2..group-count')
    if args.custom_names and args.split_count!=4:parser.error('custom-names demo uses split-count 4')
    custom_names={'1':'vote_1-6','2':'vote_7-12','3':'vote_13-16','4':'vote_17-20'} if args.custom_names else {}
    editor_captures=os.environ.get('TRANSCOMIC_CAPTURE_EDITOR')=='1'
    app=QApplication([])
    # Offscreen Windows does not enumerate installed fonts on every Qt backend.
    # Register the same existing system font for faithful captures only.
    for filename in ('segoeui.ttf','segoeuib.ttf','seguisb.ttf'):
        path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/filename
        if path.is_file():QFontDatabase.addApplicationFont(str(path))
    app.setFont(QFont('Segoe UI',10))
    root=Path(__file__).resolve().parents[1]/args.output_dir;root.mkdir(exist_ok=True,parents=True)
    groups=[]
    for i,count in enumerate((2,3,4) if args.group_count==3 else [2]*args.group_count):
        folder=root/'demo-media-readable'/f'group-{i+1}';images=folder/'images';audio=folder/'audio';images.mkdir(parents=True,exist_ok=True);audio.mkdir(exist_ok=True)
        for n in range(1,count+1):
            image_path=images/f'{n:03}.png'
            if not image_path.exists():
                image=QImage(640,400,QImage.Format_RGB32);image.fill(QColor((50+30*i)%256,(85+15*n)%256,(110+20*i)%256))
                painter=QPainter(image);painter.setPen(QColor('#fff4e5'));font=painter.font();font.setPointSize(24);painter.setFont(font);painter.drawText(image.rect(),Qt.AlignCenter,f'GROUP {i+1} / PANEL {n}');painter.end();assert image.save(str(image_path))
            audio_path=audio/f'{n:03}.wav'
            if not audio_path.exists():
                with wave.open(str(audio_path),'wb') as w:w.setparams((1,2,8000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*(4000+n*800))
        groups.append(MediaGroup.create(f'Chương {i+1:02}',images,audio,'created' if i%2 else 'name'))
    originals={p:hashlib.sha256(p.read_bytes()).hexdigest() for g in groups for folder in (g.image_dir,g.audio_dir) for p in Path(folder).iterdir()}
    scans=[scan_group(g) for g in groups];assert all(s.valid for s in scans)
    scale=os.environ.get('QT_SCALE_FACTOR','1');suffix=f'{args.theme}-{round(float(scale)*100)}'
    # Dedicated state per capture; no source or production user state is touched.
    state=root/f'acceptance-{suffix}.sqlite3';store=Store(state)
    store.set_setting('capcut_workspace_v1',json.dumps({'groups':[g.__dict__ for g in groups],'mode':'split' if args.split_count else 'merged','part_count':args.split_count or 2,'custom_names':custom_names,'name':'vote' if args.split_count else 'TransComic · MAU demo','output':str(root/'demo-projects')},ensure_ascii=False))
    store.set_setting('dark','1' if args.theme=='dark' else '0')
    window=MainWindow(store);window.resize(1400,1000);window.show();window.pages.setCurrentIndex(8);app.processEvents();page=window.capcut_page
    if window.sidebar.width()<=100:window.toggle_sidebar();app.processEvents()
    deadline=time.monotonic()+10
    while page.is_busy() and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    assert not page.is_busy() and all(s.valid for s in page.scans.values())
    page.settings_toggle.setChecked(False)
    shots=[];app.processEvents();collapsed_height=page.groups.sizeHintForRow(0)
    font=page.group_heading.font();viewport=page.groups.viewport()
    typography={'pixel_size':font.pixelSize(),'point_size':font.pointSizeF(),'weight':int(font.weight()),'group_row_height':collapsed_height,'viewport_height':viewport.height()}
    if editor_captures:
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLineEdit,QStyleOptionFrame,QStyle
        app.setCursorFlashTime(0)
        page.mode.setCurrentIndex(2);app.processEvents()
        index=page.split_model.index(0,0);view=page.split_preview
        QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=view.visualRect(index).center())
        QTest.mouseDClick(view.viewport(),Qt.LeftButton,pos=view.visualRect(index).center());app.processEvents()
        editor=next(e for e in view.findChildren(QLineEdit) if e.isVisible())
        editor.setText('Truyện phần 1 — vote');editor.deselect();editor.setCursorPosition(12);editor.setFocus();app.processEvents()
        option=QStyleOptionFrame();editor.initStyleOption(option)
        content=editor.style().subElementRect(QStyle.SE_LineEditContents,option,editor)
        measurements={'editor_rect':editor.geometry().getRect(),'cell_rect':view.visualRect(index).getRect(),'text_content_rect':content.getRect(),'font_height':editor.fontMetrics().height(),'row_height':view.rowHeight(0),'editor_size_hint':editor.sizeHint().toTuple(),'has_focus':editor.hasFocus(),'caret':editor.cursorPosition(),'dpr':editor.devicePixelRatioF()}
        for widget,label in ((window,'editing-full'),(page.settings_frame,'editing-panel')):
            path=root/f'{suffix}-{label}.png';assert widget.grab().save(str(path));shots.append(path.name)
        editor.setSelection(0,10);app.processEvents()
        path=root/f'{suffix}-editing-selection.png';assert page.settings_frame.grab().save(str(path));shots.append(path.name)
        QTest.keyClick(editor,Qt.Key_Escape);app.processEvents()
        for mode in range(3):
            page.mode.setCurrentIndex(mode)
            for _ in range(5):app.processEvents();time.sleep(.01)
            path=root/f'{suffix}-settings-{mode}.png';assert page.settings_frame.grab().save(str(path));shots.append(path.name)
        page.busy=True;page.operation='export';page.set_busy(True);app.processEvents()
        path=root/f'{suffix}-settings-disabled.png';assert page.settings_frame.grab().save(str(path));shots.append(path.name)
        page.busy=False;page.operation=None;page.set_busy(False)
        window.resize(950,620)
        for _ in range(5):app.processEvents();time.sleep(.01)
        path=root/f'{suffix}-settings-narrow.png';assert page.settings_frame.grab().save(str(path));shots.append(path.name)
        (root/f'editor-{suffix}.json').write_text(json.dumps(measurements,indent=2),encoding='utf8')
        window._exit_authorized=True;window.close();app.processEvents();print(json.dumps(measurements));return
    for selected,label in ((False,'empty-inspector'),(True,'selected-group')):
        if selected:
            page.show_group(groups[0].id);details=page.details
            details.table.setCurrentIndex(details.proxy.index(0,0))
        for _ in range(20):app.processEvents();time.sleep(.01)
        path=root/f'{suffix}-{label}.png';assert window.grab().save(str(path));shots.append(path.name)
    # Inspect mouse and keyboard focus with the actual table delegate.
    from PySide6.QtTest import QTest
    details=page.details;index=details.proxy.index(0,2);details.table.scrollTo(index);app.processEvents()
    QTest.mouseClick(details.table.viewport(),Qt.LeftButton,pos=details.table.visualRect(index).center());app.processEvents()
    path=root/f'{suffix}-mouse-focus.png';assert window.grab().save(str(path));shots.append(path.name)
    QTest.keyClick(details.table,Qt.Key_Down);app.processEvents()
    path=root/f'{suffix}-keyboard-focus.png';assert window.grab().save(str(path));shots.append(path.name)
    page.show_group(groups[-1].id);app.processEvents()
    path=root/f'{suffix}-last-group.png';assert window.grab().save(str(path));shots.append(path.name)
    window.resize(950,620);app.processEvents()
    page.groups.verticalScrollBar().setValue(0)
    for _ in range(5):app.processEvents();time.sleep(.01)
    path=root/f'{suffix}-narrow.png';assert window.grab().save(str(path));shots.append(path.name)
    if hasattr(page,'clear_button'):
        from PySide6.QtCore import QTimer
        def capture_confirmation():
            dialog=app.activeModalWidget();path=root/f'{suffix}-clear-confirmation.png'
            assert dialog.grab().save(str(path));shots.append(path.name)
            dialog.defaultButton().click()  # Cancel; screenshot run never clears groups.
        QTimer.singleShot(0,capture_confirmation);page.clear_all();assert len(page.manager.groups)==len(groups)
    from transcomic.ui.capcut_import import MultiGroupDialog
    dialog=MultiGroupDialog(page)
    for _ in range(19):dialog.add_entry()
    for i,entry in enumerate(dialog.entries):
        group=groups[i%len(groups)];entry.name.setText(f'Chương {i+1:02}');entry.image.setText(group.image_dir);entry.audio.setText(group.audio_dir)
    dialog.show();app.processEvents();dialog_path=root/f'{suffix}-import-dialog.png';assert dialog.grab().save(str(dialog_path));shots.append(dialog_path.name);dialog.reject()
    result={'theme':args.theme,'dpi_scale':float(scale),'screenshots':shots,'groups':len(groups),'pairs':sum(len(s.rows) for s in scans),'media_copied':False,'collapsed_card_height':collapsed_height,'typography':typography}
    receipt=root/f'acceptance-{suffix}.json'
    if receipt.exists():result={**json.loads(receipt.read_text(encoding='utf8')),**result}
    if args.theme=='light' and scale=='1' and not args.screenshots_only:
        paths=[]
        for mode in (('split',) if args.split_count else ('separate','merged')):
            paths.extend(export_projects(scans,root/'demo-projects'/mode,mode=mode,name='vote' if args.split_count else 'MAU demo merged',part_count=args.split_count or 2,custom_names=custom_names))
        for path in paths:
            content=json.loads((path/'draft_content.json').read_text(encoding='utf8'));manifest=json.loads((path/'transcomic_mapping.json').read_text(encoding='utf8'))['pairs'];validate_content(content,manifest)
        result['projects']=[str(p) for p in paths]
        assert all(hashlib.sha256(p.read_bytes()).hexdigest()==d for p,d in originals.items())
        template,_,_=load_template();effects=[a for m in template['materials']['material_animations'] for a in m['animations']]
        result['template_effect_resources']=len(effects);result['template_effect_directories_existing']=sum(Path(e['path']).is_dir() for e in effects)
        result['source_hashes_unchanged']=True
    (root/f'acceptance-{suffix}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    window._exit_authorized=True;window.close();app.processEvents();print(json.dumps(result,ensure_ascii=True))


if __name__=='__main__':main()
