"""Explorer MIME events and one spare pair; never enumerate folder contents."""
from pathlib import Path
import pytest
from PySide6.QtCore import Qt,QMimeData,QUrl,QPointF,QPoint
from PySide6.QtGui import QDragEnterEvent,QDropEvent
from PySide6.QtWidgets import QApplication,QWidget
from transcomic.ui.capcut_import import MultiGroupDialog
from test_capcut_ui import page


def drop(field,paths):
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    enter=QDragEnterEvent(QPoint(8,8),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    QApplication.sendEvent(field,enter)
    event=QDropEvent(QPointF(8,8),Qt.CopyAction,mime,Qt.LeftButton,Qt.NoModifier)
    if enter.isAccepted():QApplication.sendEvent(field,event)
    return enter.isAccepted() and event.isAccepted()


@pytest.mark.parametrize('dark',[False,True])
@pytest.mark.parametrize('audio_first',[False,True])
def test_thirty_pairs_unicode_stable_targets_no_scan_no_focus_theft(page,tmp_path,monkeypatch,dark,audio_first):
    app,w,p=page
    if w.dark!=dark:w.toggle_theme()
    d=MultiGroupDialog(p);d.show();app.processEvents()
    assert len(d.entries)==1 and d.entries[0].blank()
    import transcomic.capcut.media as media
    monkeypatch.setattr(media,'scan_group',lambda *a,**k:pytest.fail('Drop must not scan'))
    monkeypatch.setattr(Path,'iterdir',lambda *a,**k:pytest.fail('Drop must not enumerate'))
    monkeypatch.setattr(QWidget,'activateWindow',lambda *a:pytest.fail('No focus theft'))
    monkeypatch.setattr(QWidget,'raise_',lambda *a:pytest.fail('No focus theft'))
    pairs=[]
    for i in range(30):
        image=tmp_path/f'Ảnh chương {i+1}';audio=tmp_path/f'Giọng đọc {i+1}';image.mkdir();audio.mkdir()
        entry=d.entries[-1];fields=[(entry.audio,audio),(entry.image,image)] if audio_first else [(entry.image,image),(entry.audio,audio)]
        focus=app.focusWidget()
        assert drop(*[fields[0][0],[fields[0][1]]]);app.processEvents();assert d.entries[-1] is entry
        assert drop(fields[1][0],[fields[1][1]])
        assert d.entries[-1] is entry,'Drop must finish before adding/scrolling'
        app.processEvents();app.processEvents()
        assert len(d.entries)==i+2 and d.entries[-1].blank()
        assert entry.name.text()==image.name
        assert app.focusWidget() is focus
        pairs.append((str(image.resolve()),str(audio.resolve())))
    assert d.scroll.verticalScrollBar().value()>0
    assert len(d.values())==30
    assert [(g.image_dir,g.audio_dir) for g in d.values()]==pairs
    assert not p.manager.groups
    # Editing pair 3/10 changes only that path and never a custom name.
    for index in (2,9):
        entry=d.entries[index];entry.name.setText('Tên riêng '+str(index));new=tmp_path/f'Thay thế {index}';new.mkdir()
        assert drop(entry.image,[new]);app.processEvents()
        pairs[index]=(str(new.resolve()),pairs[index][1])
        assert entry.name.text()=='Tên riêng '+str(index)
    assert [(g.image_dir,g.audio_dir) for g in d.values()]==pairs
    d.accept();assert len(d.result_groups)==30


def test_invalid_drop_preserves_paths_and_one_spare_when_deleting(page,tmp_path):
    app,w,p=page;d=MultiGroupDialog(p);d.show();app.processEvents()
    a=tmp_path/'ảnh';b=tmp_path/'voice';a.mkdir();b.mkdir();file=tmp_path/'not-folder.txt';file.write_text('fixture')
    first=d.entries[0];assert drop(first.image,[a]);before=first.image.text()
    for paths in ([file],[a,b],[tmp_path/'missing']):
        assert not drop(first.image,paths) and first.image.text()==before
    assert drop(first.audio,[b]);app.processEvents();app.processEvents()
    assert len(d.entries)==2
    for _ in range(10):assert d.add_entry() is d.entries[-1]
    assert len(d.entries)==2
    spare=d.entries[-1];d.remove_entry(spare);app.processEvents();assert len(d.entries)==2 and d.entries[-1].blank()
    d.entries[-1].audio.setText(str(b));d.accept();assert not d.result_groups and 'Cặp 2' in d.error.text()
    d.entries[-1].audio.clear();app.processEvents();assert len(d.values())==1
    d.remove_entry(first);app.processEvents();assert len(d.entries)==1 and d.entries[0].blank()
    with pytest.raises(ValueError):d.values()
    d.reject()


def test_deleting_middle_preserves_names_order_and_edit_mode_no_extra_pair(page,tmp_path):
    app,w,p=page;d=MultiGroupDialog(p)
    for i in range(3):
        path=tmp_path/str(i);path.mkdir();entry=d.entries[-1];entry.name.setText(f'Name {i}');entry.image.setText(str(path));entry.audio.setText(str(path));app.processEvents()
    middle=d.entries[1];d.remove_entry(middle);app.processEvents()
    groups=d.values();assert [g.name for g in groups]==['Name 0','Name 2']
    assert [e.heading.text() for e in d.entries]==['Cặp 01','Cặp 02','Cặp 03']
    edit=MultiGroupDialog(p,group=groups[0]);edit.entries[0].audio.setText(groups[1].audio_dir);app.processEvents()
    assert len(edit.entries)==1 and edit.values()[0].id==groups[0].id
    edit.reject();d.reject()


def test_deferred_drop_callbacks_cancel_when_dialog_is_destroyed(page,tmp_path):
    from PySide6.QtCore import QCoreApplication,QEvent
    from PySide6.QtTest import QTest
    from shiboken6 import isValid
    app,w,p=page;dialog=MultiGroupDialog(p);dialog.show();app.processEvents()
    entry=dialog.entries[0];assert drop(entry.image,[tmp_path]);assert drop(entry.audio,[tmp_path])
    dialog.deleteLater();QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    assert not isValid(dialog)
    QTest.qWait(30);app.processEvents()
