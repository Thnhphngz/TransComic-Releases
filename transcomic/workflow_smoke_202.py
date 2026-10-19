"""Small source/frozen UI checks, called only inside the isolated build smoke."""
from pathlib import Path
from PySide6.QtCore import Qt,QMimeData,QUrl,QPoint,QPointF,QTimer
from PySide6.QtGui import QDragEnterEvent,QDropEvent
from PySide6.QtWidgets import QApplication,QComboBox,QInputDialog
from PySide6.QtTest import QTest


def run(window,root):
    from .ui.capcut_import import MultiGroupDialog
    from .ui.exporting import ExportInputDialog,MODES
    from .ui.controls import GlassComboDelegate
    app=QApplication.instance();records=[]
    def drop(field,path):
        mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(path))])
        event=QDragEnterEvent(QPoint(8,8),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);app.sendEvent(field,event);assert event.isAccepted()
        event=QDropEvent(QPointF(8,8),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier);app.sendEvent(field,event);assert event.isAccepted()
    for dark in (False,True):
        if window.dark!=dark:window.toggle_theme()
        dialog=MultiGroupDialog(window);dialog.show();QTest.qWait(50)
        for i in range(10):
            image=root/f'Ảnh chương {i}';audio=root/f'Giọng chương {i}';image.mkdir(exist_ok=True);audio.mkdir(exist_ok=True)
            entry=dialog.entries[-1];focus=app.focusWidget()
            drop(entry.image,image);assert entry.audio.text()==''
            drop(entry.audio,audio);assert dialog.entries[-1] is entry
            QTest.qWait(10);assert len(dialog.entries)==i+2 and dialog.entries[-1].blank()
            assert app.focusWidget() is focus
        QTest.qWait(40);assert dialog.scroll.verticalScrollBar().value()>0
        assert len(dialog.values())==10
        dialog.grab().save(str(root/f'capcut-pairs-202-{dark}.png'))
        dialog.accept();assert len(dialog.result_groups)==10;dialog.deleteLater()
        for choice in range(3):
            faults=[]
            def pick():
                modal=app.activeModalWidget()
                try:
                    combo=modal.findChild(QComboBox);combo.showPopup();QTest.qWait(40)
                    assert isinstance(combo.itemDelegate(),GlassComboDelegate)
                    view=combo.view();popup=view.window();assert popup.isVisible()
                    assert popup.screen().availableGeometry().contains(popup.frameGeometry())
                    QTest.mouseMove(view.viewport(),view.visualRect(combo.model().index(choice,0)).center());QTest.qWait(20)
                    popup.grab().save(str(root/f'export-202-{dark}-{choice}.png'))
                    QTest.mouseClick(view.viewport(),Qt.LeftButton,pos=view.visualRect(combo.model().index(choice,0)).center())
                    assert combo.currentIndex()==choice;modal.accept()
                except BaseException as exc:
                    faults.append(type(exc).__name__)
                    if modal:modal.reject()
            QTimer.singleShot(80,pick)
            value,ok=ExportInputDialog.getItem(window,'Phương thức xuất','Chọn vị trí xuất:',[s for s,_ in MODES],1,False)
            assert not faults and ok and value==MODES[choice][0],faults
        records.append(dict(dark=dark,manual_pairs=10,spare_excluded=True,popup_choices=3,focus_preserved=True))
    window.pages.setCurrentIndex(9);app.processEvents()
    page=window.automation_page;repo=window.automation_repo
    original={w['id']:repo.workset(w['id'])['config'] for w in repo.workset_summaries()}
    getter=QInputDialog.getText
    try:
        QInputDialog.getText=lambda *a,**k:('Synthetic native workset',True)
        saved=[]
        for name in ('Native project one','Native project two'):
            page.new_workset();id=page.current
            assert page.fields['project_name'].text()=='' and repo.workset(id)['config']['part_names']=={}
            page.start_clicked();assert not page.controller.busy and page.fields['project_name'].hasFocus()
            page.fields['project_name'].setText(name);page.config_changed();saved.append((id,name))
        for id,name in saved:page.load_worksets(id);assert page.fields['project_name'].text()==name
        assert all(repo.workset(id)['config']==cfg for id,cfg in original.items())
    finally:QInputDialog.getText=getter
    return dict(passed=True,platform=app.platformName(),dpr=window.devicePixelRatioF(),themes=records,
                new_workset_blank=True,saved_project_names_restored=True,old_worksets_unchanged=True,
                drop_events='QDragEnterEvent/QDropEvent with Explorer local URL MIME; physical Explorer OLE not automated')
