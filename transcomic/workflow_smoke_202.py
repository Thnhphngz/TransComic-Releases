"""Small source/frozen UI checks, called only inside the isolated build smoke."""
from pathlib import Path
import time
from PySide6.QtCore import Qt,QMimeData,QUrl,QPoint,QPointF,QTimer
from PySide6.QtGui import QDragEnterEvent,QDropEvent
from PySide6.QtWidgets import QApplication,QComboBox,QInputDialog,QDialogButtonBox
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
            deadline=time.monotonic()+1
            while time.monotonic()<deadline:
                QTest.qWait(10)
                if len(dialog.entries)!=i+2:continue
                spare=dialog.entries[-1];viewport=dialog.scroll.viewport()
                if spare.isVisible() and viewport.rect().contains(spare.mapTo(viewport,QPoint(0,0))) and viewport.rect().contains(spare.mapTo(viewport,QPoint(spare.width()-1,spare.height()-1))):break
            assert len(dialog.entries)==i+2 and dialog.entries[-1].blank()
            spare=dialog.entries[-1];viewport=dialog.scroll.viewport()
            assert viewport.rect().contains(spare.mapTo(viewport,QPoint(0,0))), (i,spare.geometry(),viewport.rect(),spare.mapTo(viewport,QPoint(0,0)))
            assert viewport.rect().contains(spare.mapTo(viewport,QPoint(spare.width()-1,spare.height()-1))), (i,spare.geometry(),viewport.rect())
            assert app.focusWidget() is focus
        QTest.qWait(40);assert dialog.scroll.verticalScrollBar().value()>0
        assert len(dialog.values())==10
        dialog.grab().save(str(root/f'capcut-pairs-202-{dark}.png'))
        dialog.accept();assert len(dialog.result_groups)==10;dialog.deleteLater()
        popup_timings=[]
        for choice in range(3):
            faults=[];deadline=[0.];input_methods=[]
            def fail(exc):
                modal=app.activeModalWidget()
                faults.append(dict(exception=type(exc).__name__,message=str(exc),choice=choice))
                if modal:modal.reject()
            def choose_visible():
                # Windows animates the native popup. Return to the modal event
                # loop between polls instead of asserting after a fixed 40 ms.
                modal=app.activeModalWidget()
                try:
                    assert isinstance(modal,ExportInputDialog)
                    combo=modal.findChild(QComboBox);view=combo.view();popup=view.window()
                    if not (popup.isVisible() and view.isVisible()):
                        assert time.monotonic()<deadline[0],'Export popup did not become visible'
                        QTimer.singleShot(20,choose_visible);return
                    assert isinstance(combo.itemDelegate(),GlassComboDelegate)
                    assert popup.screen().availableGeometry().contains(popup.frameGeometry())
                    assert combo.count()==3 and [combo.itemText(i) for i in range(3)]==[s for s,_ in MODES]
                    rect=view.visualRect(combo.model().index(choice,0))
                    assert rect.height()>20 and view.viewport().rect().contains(rect.center())
                    popup_timings.append(dict(choice=choice,visible_ms=round((time.monotonic()-deadline[0]+4)*1000)))
                    popup.grab().save(str(root/f'export-202-{dark}-{choice}.png'))
                    from .release_ui_probe import click
                    input_methods.append(click(view.viewport(),rect.center()))
                    QTimer.singleShot(40,confirm_selection)
                except BaseException as exc:fail(exc)
            def confirm_selection():
                modal=app.activeModalWidget()
                try:
                    assert isinstance(modal,ExportInputDialog)
                    combo=modal.findChild(QComboBox)
                    if combo.view().window().isVisible() or combo.currentIndex()!=choice:
                        assert time.monotonic()<deadline[0],'Native popup click did not select the requested mode'
                        QTimer.singleShot(20,confirm_selection);return
                    from .release_ui_probe import click
                    input_methods.append(click(modal.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)))
                    QTimer.singleShot(300,lambda:fail(AssertionError('Native OK click did not accept export dialog')) if app.activeModalWidget() is modal else None)
                except BaseException as exc:fail(exc)
            def pick():
                modal=app.activeModalWidget()
                try:
                    assert isinstance(modal,ExportInputDialog)
                    combo=modal.findChild(QComboBox)
                    from .release_ui_probe import click
                    deadline[0]=time.monotonic()+4
                    input_methods.append(click(combo,QPoint(combo.width()-14,combo.height()//2)))
                    QTimer.singleShot(20,choose_visible)
                except BaseException as exc:fail(exc)
            QTimer.singleShot(200,pick)
            value,ok=ExportInputDialog.getItem(window,'Phương thức xuất','Chọn vị trí xuất:',[s for s,_ in MODES],1,False)
            assert not faults and ok and value==MODES[choice][0],faults
        records.append(dict(dark=dark,manual_pairs=10,spare_excluded=True,popup_choices=3,focus_preserved=True,
                            input_method=sorted(set(input_methods)),popup_timings=popup_timings))
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
