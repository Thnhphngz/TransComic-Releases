"""Folder imports use real Qt drops and local synthetic media."""
from pathlib import Path
import os
import threading
import time

from docx import Document
from PIL import Image
from PySide6.QtCore import QMimeData, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
import pytest

from transcomic.automation.folder_inputs import scan_folder, word_notice
from test_automation_ui import gui, wait


def fixture_folder(root, images, words):
    root.mkdir()
    # Equal file bytes at separate paths preserve the positional image order.
    if images:
        first = root / '1.png'
        Image.new('RGB', (24, 32), (30, 130, 90)).save(first)
        data = first.read_bytes()
        for i in range(images, 1, -1):
            (root / f'{i}.png').write_bytes(data)
    for i in range(words):
        # Deliberately broken DOCX: a folder scan must never open it as Word.
        (root / f'Chapter {i + 1}.DOCX').write_bytes(b'Word marker, not a document')
    return root


def docx(path, lines=2):
    doc = Document()
    for i in range(lines):
        doc.add_paragraph(f'Văn bản tổng hợp số {i + 1}')
    doc.save(path)
    return path


def drop(app, view, point, paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    enter = QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    event = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    app.sendEvent(view.viewport(), enter)
    app.sendEvent(view.viewport(), event)
    assert enter.isAccepted() and event.isAccepted()


@pytest.mark.parametrize('images,words', [(10,0),(10,1),(10,2),(100,5),(0,1),(0,3),(0,0)])
def test_scan_same_scope_and_supported_types(tmp_path, images, words):
    root = fixture_folder(tmp_path/'inputs', images, words)
    fixture_folder(root/'nested', 2, 2)
    (root/'other.doc').write_bytes(b'unsupported')
    (root/'notes.txt').write_text('Do not import', encoding='utf-8')
    (root/'logo.gif').write_bytes(b'unsupported')
    result = scan_folder(root)
    assert len(result.words) == words
    assert bool(word_notice(len(result.words))) == (words >= 2)
    assert [Path(p).name for p in result.images] == [f'{i}.png' for i in range(1, images+1)]
    assert not result.invalid


def test_invalid_image_and_duplicate_paths(tmp_path):
    root = fixture_folder(tmp_path/'inputs', 2, 2)
    (root/'3.png').write_bytes(b'broken')
    alias = root/'4.png'
    try:
        alias.symlink_to(root/'1.png')
    except OSError:
        # Windows may forbid symlinks. Use a mocked alias resolver in that case.
        alias.write_bytes((root/'1.png').read_bytes())
        from unittest.mock import patch
        from transcomic.automation.repository import source_key
        with patch('transcomic.automation.folder_inputs.source_key', side_effect=lambda p:source_key(root/'1.png' if p==alias else p)):
            result = scan_folder(root)
    else:
        result = scan_folder(root)
    assert len(result.images) == 2 and result.duplicates == 1
    assert result.invalid == ('3.png',)


def test_multiple_folders_then_explicit_word_drop_and_existing_row(gui, tmp_path):
    app,w,p,wid = gui
    a = fixture_folder(tmp_path/'Truyen A', 2, 1)
    b = fixture_folder(tmp_path/'Truyen B', 2, 2)
    point = p.table.viewport().rect().center()
    drop(app, p.table, point, [a,b])
    wait(app, lambda:len(p.folder_inputs.items)==2 and all(e.result for e in p.folder_inputs.items))
    assert not w.store.documents() and not w.store.jobs() and not p.repo.groups(wid)
    entries = {e.path:e for e in p.folder_inputs.items}
    assert '⚠' not in p.folder_inputs.items[entries[a]].text()
    assert '2 file Word · chỉ nhập ảnh' in p.folder_inputs.items[entries[b]].text()
    assert set(map(Path, entries[b].result.images)).isdisjoint(map(Path,entries[a].result.images))
    p.drop_paths([str(a), str(b), str(b)])
    assert list(p.folder_inputs.items) == list(entries.values())

    chosen = docx(b/'Chosen.docx')
    listing = p.folder_inputs.list
    item = p.folder_inputs.items[entries[b]]
    drop(app, listing, listing.visualItemRect(item).center(), [chosen])
    wait(app, lambda:len(p.repo.group_summaries(wid))==1 and p.repo.group_summaries(wid)[0]['data']['image_folder']==str(b))
    assert p.repo.group_summaries(wid)[0]['path']==str(chosen)
    assert item.text().count('2 file Word')==1 and not w.store.jobs()

    selected = docx(a/'Selected.docx')
    drop(app,p.table,p.table.viewport().rect().center(),[selected])
    wait(app, lambda:len(p.repo.group_summaries(wid))==2 and p.model.rowCount()==2)
    group = next(g for g in p.repo.groups(wid) if w.store.document(g['document_id'])['path']==str(selected))
    row = next(i for i,r in enumerate(p.model.rows) if r['id']==group['id'])
    assert not group['data']['image_folder']
    p.table.setCurrentIndex(p.model.index(row,1))
    listing.setCurrentItem(p.folder_inputs.items[entries[a]])
    assert p.folder_inputs.attach.isEnabled()
    p.folder_inputs.attach.click()
    wait(app, lambda:p.repo.group_state(group['id'])['image_folder']==str(a))
    p.folder_inputs.remove.click()
    assert set(p.folder_inputs.items)=={entries[b]} and a.is_dir() and selected.is_file()
    assert p.repo.group_state(group['id'])['image_folder']==str(a)
    unsupported = a/'Unsupported.doc'
    unsupported.write_bytes(b'unsupported')
    p.drop_paths([str(unsupported)])
    assert 'DOCX/TXT' in p.notice.text() and len(w.store.documents())==2 and not w.store.jobs()


def test_folder_only_creates_new_empty_workset_and_warns_for_word_only(gui, tmp_path, monkeypatch):
    app,w,p,wid = gui
    p.repo.delete(wid)
    p.load_worksets()
    root = fixture_folder(tmp_path/'Only Word',0,2)
    drop(app,p.table,p.table.viewport().rect().center(),[root])
    wait(app,lambda:p.current and p.folder_inputs.items and next(iter(p.folder_inputs.items)).result)
    entry,item=next(iter(p.folder_inputs.items.items()))
    assert 'Không có ảnh hợp lệ' in item.text() and '2 file Word' in item.text()
    assert not p.folder_inputs.ready(entry) and not w.store.documents() and not w.store.jobs()


@pytest.mark.parametrize('count',[100,500,1000])
def test_background_scan_and_ui_remain_responsive(gui,tmp_path,count,request):
    app,w,p,wid=gui
    root=fixture_folder(tmp_path/'Images',count,2)
    heartbeats=[]
    timer=QTimer(w)
    timer.setInterval(10)
    timer.timeout.connect(lambda:heartbeats.append(time.perf_counter()))
    timer.start()
    started=time.perf_counter()
    p.drop_paths([str(root)])
    w.pages.setCurrentIndex(0)
    app.processEvents()
    w.pages.setCurrentIndex(9)
    wait(app,lambda:p.folder_inputs.items and next(iter(p.folder_inputs.items)).result)
    timer.stop()
    request.node.user_properties.extend([('images',count),('scan_wall_seconds',round(time.perf_counter()-started,4)),('qt_ticks',len(heartbeats))])
    assert len(next(iter(p.folder_inputs.items)).result.images)==count
    assert heartbeats and not w.store.documents()


def test_remove_pending_folder_discards_stale_result(gui,tmp_path,monkeypatch):
    from transcomic.ui import automation_folders as module
    app,w,p,wid=gui
    root=fixture_folder(tmp_path/'Images',2,2)
    entered=threading.Event()
    original=module.scan_folder

    def delayed(path, *, cancelled, progress):
        entered.set()
        while not cancelled():
            time.sleep(.005)
        return original(path,progress=progress)

    monkeypatch.setattr(module,'scan_folder',delayed)
    p.drop_paths([str(root)])
    wait(app,entered.is_set)
    p.folder_inputs.list.setCurrentRow(0)
    p.folder_inputs.remove.click()
    wait(app,lambda:not any(t.is_alive() for t in p.tasks))
    assert not p.folder_inputs.items and not p.folder_inputs.isVisible()
    assert not w.store.documents()


@pytest.mark.parametrize('dark',[False,True])
def test_folder_warning_layout(gui,tmp_path,dark,request):
    app,w,p,wid=gui
    if w.dark!=dark:
        w.toggle_theme()
    a=fixture_folder(tmp_path/'Chuong 01',10,3)
    b=fixture_folder(tmp_path/'Chuong 02',10,1)
    drop(app,p.table,p.table.viewport().rect().center(),[a,b])
    wait(app,lambda:len(p.folder_inputs.items)==2 and all(e.result for e in p.folder_inputs.items))
    assert p.folder_inputs.isVisible() and p.table_shell.geometry().top()>p.folder_inputs.geometry().bottom()
    entry=next(e for e in p.folder_inputs.items if e.path==a)
    warning=p.folder_inputs.items[entry]
    assert '3 file Word · chỉ nhập ảnh' in warning.text()
    assert p.folder_inputs.list.viewport().rect().contains(p.folder_inputs.list.visualItemRect(warning).center())
    assert p.folder_inputs.attach.geometry().right()<p.folder_inputs.remove.geometry().left()
    dpr=w.devicePixelRatioF()
    request.node.user_properties.append(('device_pixel_ratio',dpr))
    if output:=os.environ.get('TRANSCOMIC_FOLDER_SCREENSHOTS'):
        folder=Path(output);folder.mkdir(parents=True,exist_ok=True)
        assert w.grab().save(str(folder/f'{"dark" if dark else "light"}-{round(dpr*100)}.png'))
