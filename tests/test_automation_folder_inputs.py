"""Folder imports use real Qt drops and local synthetic media."""
from pathlib import Path
import os
import threading
import time

from docx import Document
from PIL import Image
from PySide6.QtCore import QMimeData, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QMessageBox
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


def test_supported_image_types_are_sorted_naturally(tmp_path):
    names = ['1.PNG', '2.JPG', '10.jpeg', '20.webp']
    for name in reversed(names):
        Image.new('RGB', (24,32)).save(tmp_path/name)
    result = scan_folder(tmp_path,inspection=True)
    assert [Path(p).name for p in result.images] == names
    assert [Path(p['path']).name for p in result.manifest] == names
    assert not result.error


def row_at(page, group, column=1):
    row = next(i for i, r in enumerate(page.model.rows) if r['id'] == group)
    return page.table.visualRect(page.model.index(row, column)).center()


def empty_point(page):
    rect = page.table.viewport().rect()
    point = rect.bottomRight()
    point.setX(rect.center().x())
    point.setY(rect.bottom() - 4)
    assert not page.table.indexAt(point).isValid()
    return point


def settled(page, count):
    return (page.model.rowCount() == count and not any(t.is_alive() for t in page.tasks)
            and not any(d.busy for d in page.repo.folder_drafts(page.current)))


def test_drop_multiple_folders_into_main_table(gui, tmp_path):
    app,w,p,wid = gui
    a = fixture_folder(tmp_path/'Truyen A', 100, 1)
    chosen = docx(a/'Chapter 1.DOCX', 100)
    b = fixture_folder(tmp_path/'Truyen B', 100, 3)
    c = fixture_folder(tmp_path/'Truyen C', 100, 0)
    drop(app, p.table, empty_point(p), [a,b,c])
    assert p.model.rowCount() == 3
    wait(app, lambda:settled(p,3) and p.proof is not None)
    assert not hasattr(p,'folder_inputs')
    assert len(w.store.documents()) == 1 and not w.store.jobs()
    assert w.store.documents()[0]['path'] == str(chosen)
    group, = p.repo.groups(wid)
    assert group['data']['state'] == 'waiting'
    assert [Path(im['path']).name for im in group['data']['images']] == [f'{i}.png' for i in range(1,101)]
    assert all(Path(im['path']).parent == a for im in group['data']['images'])
    assert len(group['data']['slots']) == 100 and not p.start.isEnabled()
    drafts = {d.path:d for d in p.repo.folder_drafts(wid)}
    assert set(drafts) == {b,c}
    for folder,words in ((b,3),(c,0)):
        draft = drafts[folder]
        assert len(draft.scan.images) == 100 and len(draft.scan.words) == words
        assert all(Path(path).parent == folder for path in draft.scan.images)
        row = next(i for i,r in enumerate(p.model.rows) if r['id'] == draft.id)
        assert p.model.index(row,2).data() == str(folder)
        assert p.model.index(row,3).data() == '100 ảnh'
        assert p.model.index(row,5).data() == 'Chờ Word'
        tooltip = p.model.index(row,1).data(Qt.ToolTipRole)
        assert 'kéo file DOCX' in tooltip
        assert ('3 file Word' in tooltip) == (words == 3)
        if words: assert '⚠ 3 file Word' in p.model.index(row,1).data()
    with pytest.raises(ValueError,match='chờ chọn DOCX'):
        p.controller.start(wid)
    drop(app,p.table,empty_point(p),[a,b,c,c])
    wait(app,lambda:settled(p,3))
    assert 'đã có' in p.notice.text()
    assert p.repo.groups(wid)[0]['id'] == group['id']


@pytest.mark.parametrize('words',[0,3])
def test_attach_explicit_docx_to_waiting_row(gui,tmp_path,monkeypatch,words):
    from transcomic.automation import folder_inputs,validation
    from transcomic.ui import automation_drops
    app,w,p,wid = gui
    folder = fixture_folder(tmp_path/'Photos',2,words)
    selected = docx(tmp_path/'Selected.docx')
    original = folder_inputs.scan_folder
    scans = []
    def count_scan(*args,**kwargs):
        scans.append(args[0])
        return original(*args,**kwargs)
    def unexpected_scan(*args,**kwargs):
        pytest.fail('Unchanged images should be reused before dispatch')
    monkeypatch.setattr(automation_drops,'scan_folder',count_scan)
    monkeypatch.setattr(folder_inputs,'scan_folder',count_scan)
    monkeypatch.setattr(validation,'image_manifest',unexpected_scan)

    drop(app,p.table,empty_point(p),[folder])
    wait(app,lambda:settled(p,1))
    draft, = p.repo.folder_drafts(wid)
    invalid = tmp_path/'Selected.doc';invalid.write_bytes(b'unsupported')
    drop(app,p.table,row_at(p,draft.id),[invalid])
    assert 'DOCX/TXT' in p.notice.text()
    assert not p.repo.groups(wid)

    drop(app,p.table,row_at(p,draft.id),[selected])
    wait(app,lambda:settled(p,1) and p.start.isEnabled())
    group, = p.repo.groups(wid)
    assert group['id'] == draft.id and not p.repo.folder_drafts(wid)
    assert group['data']['image_folder'] == str(folder)
    assert group['data']['image_word_count'] == words
    assert p.model.index(0,1).data() == 'Selected.docx'
    assert p.model.index(0,3).data() == '2 dòng · 2 ảnh'
    assert p.model.index(0,5).data() == 'Đợi dịch'
    if words: assert '3 file Word' in p.model.index(0,2).data(Qt.ToolTipRole)
    assert scans == [folder] and not w.store.jobs()
    assert p.proof['passed']


def test_word_drop_adopts_own_parent_and_keeps_explicit_choice(gui,tmp_path):
    app,w,p,wid = gui
    folder = fixture_folder(tmp_path/'Chapter',2,2)
    selected = docx(folder/'Choose this.docx')
    paths = {p:p.read_bytes() for p in folder.iterdir()}
    drop(app,p.table,empty_point(p),[selected])
    wait(app,lambda:settled(p,1) and p.start.isEnabled())
    group, = p.repo.group_summaries(wid)
    assert group['path'] == str(selected) and group['data']['image_folder'] == str(folder)
    assert group['data']['image_word_count'] == 3
    assert p.model.index(0,3).data() == '2 dòng · 2 ảnh'
    drop(app,p.table,row_at(p,group['id']),[folder/'Chapter 1.DOCX'])
    assert 'đã có tài liệu' in p.notice.text()
    drop(app,p.table,empty_point(p),[selected])
    wait(app,lambda:settled(p,1))
    assert len(w.store.documents()) == 1 and not w.store.jobs()
    assert all(path.read_bytes() == original for path,original in paths.items())


def test_word_then_folder_drop_can_start_mock_pipeline(gui,tmp_path,monkeypatch):
    app,w,p,wid = gui
    selected = docx(tmp_path/'Word.docx')
    folder = fixture_folder(tmp_path/'Photos',2,0)
    drop(app,p.table,empty_point(p),[selected])
    wait(app,lambda:settled(p,1) and p.proof is not None)
    group, = p.repo.groups(wid)
    assert not group['data']['image_folder'] and not p.start.isEnabled()
    drop(app,p.table,row_at(p,group['id']),[folder])
    wait(app,lambda:p.start.isEnabled())
    assert p.model.index(0,3).data() == '2 dòng · 2 ảnh'
    assert not w.store.jobs()
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.Yes)
    p.start.click()
    wait(app,lambda:not p.controller.busy)
    assert p.repo.workset(wid)['state'] == 'completed'
    assert all(path.is_file() for path in (selected,folder/'1.png',folder/'2.png'))


def test_empty_unsupported_and_word_only_folders(gui,tmp_path):
    app,w,p,wid = gui
    a = fixture_folder(tmp_path/'Empty',0,0)
    (a/'notes.doc').write_bytes(b'unsupported')
    (a/'picture.gif').write_bytes(b'unsupported')
    drop(app,p.table,empty_point(p),[a])
    wait(app,lambda:settled(p,0))
    assert 'Không tìm thấy DOCX hoặc ảnh hợp lệ' in p.notice.text()
    assert not p.repo.groups(wid)

    b = fixture_folder(tmp_path/'One Word',0,1)
    docx(b/'Chapter 1.DOCX')
    c = fixture_folder(tmp_path/'Many Word',0,3)
    drop(app,p.table,empty_point(p),[b,c])
    wait(app,lambda:settled(p,2) and p.proof is not None)
    group, = p.repo.groups(wid)
    assert not group['data']['image_folder']
    assert 'Chưa chọn thư mục ảnh' in group['data']['error']
    draft, = p.repo.folder_drafts(wid)
    assert draft.path == c and len(draft.scan.words) == 3 and not draft.scan.images
    assert not p.start.isEnabled() and not w.store.jobs()


def test_invalid_image_shows_real_count_and_blocks_start(gui,tmp_path):
    app,w,p,wid = gui
    folder = fixture_folder(tmp_path/'Images',2,1)
    docx(folder/'Chapter 1.DOCX')
    (folder/'3.png').write_bytes(b'invalid image')
    drop(app,p.table,empty_point(p),[folder])
    wait(app,lambda:settled(p,1) and p.proof is not None)
    group, = p.repo.group_summaries(wid)
    assert group['data']['image_count'] == 2
    assert '1 ảnh lỗi: 3.png' in group['data']['error']
    assert '3.png' in p.model.index(0,3).data(Qt.ToolTipRole)
    assert not p.start.isEnabled() and not w.store.jobs()


def test_duplicate_word_does_not_displace_waiting_row(gui,tmp_path):
    app,w,p,wid = gui
    existing = docx(tmp_path/'Already here.docx')
    drop(app,p.table,empty_point(p),[existing])
    wait(app,lambda:settled(p,1))
    folder = fixture_folder(tmp_path/'Images',2,0)
    drop(app,p.table,empty_point(p),[folder])
    wait(app,lambda:settled(p,2))
    draft, = p.repo.folder_drafts(wid)
    drop(app,p.table,row_at(p,draft.id),[existing])
    wait(app,lambda:settled(p,2))
    assert w.store.documents()[0]['path'] == str(existing)
    assert len(w.store.documents()) == 1
    assert 'đã có trong một dòng khác' in draft.error
    assert not p.start.isEnabled() and not w.store.jobs()


def test_waiting_row_reinspects_images_after_a_change(gui,tmp_path):
    app,w,p,wid = gui
    folder = fixture_folder(tmp_path/'Images',2,0)
    selected = docx(tmp_path/'Selected.docx',3)
    drop(app,p.table,empty_point(p),[folder])
    wait(app,lambda:settled(p,1))
    draft, = p.repo.folder_drafts(wid)
    assert len(draft.scan.images) == 2
    (folder/'3.png').write_bytes((folder/'1.png').read_bytes())
    drop(app,p.table,row_at(p,draft.id),[selected])
    wait(app,lambda:settled(p,1) and p.start.isEnabled())
    assert [Path(m['path']).name for m in p.repo.field(draft.id,'images')] == ['1.png','2.png','3.png']
    assert p.model.index(0,3).data() == '3 dòng · 3 ảnh'
    assert not w.store.jobs()


@pytest.mark.parametrize('count',[100,500,1000])
def test_background_scan_and_ui_remain_responsive(gui,tmp_path,count,request):
    app,w,p,wid=gui
    root=fixture_folder(tmp_path/'Images',count,2)
    heartbeats=[];progress=[]
    p.folder_progress.connect(lambda _,status:progress.append(status))
    timer=QTimer(w)
    timer.setInterval(10)
    timer.timeout.connect(lambda:heartbeats.append(time.perf_counter()))
    timer.start()
    started=time.perf_counter()
    drop(app,p.table,empty_point(p),[root])
    w.pages.setCurrentIndex(0)
    app.processEvents()
    w.pages.setCurrentIndex(9)
    wait(app,lambda:settled(p,1) and progress)
    timer.stop()
    request.node.user_properties.extend([('images',count),('scan_wall_seconds',round(time.perf_counter()-started,4)),('qt_ticks',len(heartbeats))])
    draft, = p.repo.folder_drafts(wid)
    assert len(draft.scan.images)==count and progress[-1]==f'Đang quét ảnh {count}/{count}'
    assert heartbeats and not w.store.documents()


def test_remove_pending_folder_discards_stale_result(gui,tmp_path,monkeypatch):
    from transcomic.ui import automation_drops as module
    from transcomic.ui.automation_page import group_button_rects
    from PySide6.QtTest import QTest
    app,w,p,wid=gui
    root=fixture_folder(tmp_path/'Images',2,2)
    entered=threading.Event()
    original=module.scan_folder

    def delayed(path, *, cancelled, progress, inspection):
        entered.set()
        deadline=time.monotonic()+6
        while not cancelled() and time.monotonic()<deadline:
            time.sleep(.005)
        return original(path,progress=progress,inspection=inspection)

    monkeypatch.setattr(module,'scan_folder',delayed)
    monkeypatch.setattr(QMessageBox,'question',lambda *args:QMessageBox.Yes)
    drop(app,p.table,empty_point(p),[root])
    wait(app,entered.is_set)
    draft, = p.repo.folder_drafts(wid)
    index=p.model.index(0,6)
    first,second,remove=group_button_rects(p.action_table.visualRect(index))
    assert p.action_table.action_at(first.center()) is None
    assert p.action_table.action_at(second.center()) is None
    assert p.action_table.action_at(remove.center())==(draft.id,'remove')
    QTest.mouseClick(p.action_table.viewport(),Qt.LeftButton,pos=remove.center())
    wait(app,lambda:settled(p,0))
    assert not p.repo.folder_drafts(wid) and not w.store.documents()
    assert (root/'1.png').is_file()


@pytest.mark.parametrize('dark',[False,True])
def test_folder_warning_layout(gui,tmp_path,dark,request):
    app,w,p,wid=gui
    if w.dark!=dark:
        w.toggle_theme()
    a=fixture_folder(tmp_path/'Chuong 01',10,3)
    b=fixture_folder(tmp_path/'Chuong 02',10,1)
    docx(b/'Chapter 1.DOCX',10)
    c=fixture_folder(tmp_path/'Chuong 03',10,0)
    drop(app,p.table,empty_point(p),[a,b,c])
    wait(app,lambda:settled(p,3) and p.proof is not None)
    draft=next(d for d in p.repo.folder_drafts(wid) if d.path==a)
    for width in (1120,1440):
        w.resize(width,940);app.processEvents()
        point=row_at(p,draft.id)
        assert p.table.indexAt(point).data(Qt.UserRole)==draft.id
        assert '⚠ 3 file Word' in p.table.indexAt(point).data()
        assert p.action_table.rowHeight(0)==p.table.rowHeight(0)
        assert not hasattr(p,'folder_inputs')
    dpr=w.devicePixelRatioF()
    request.node.user_properties.append(('device_pixel_ratio',dpr))
    if output:=os.environ.get('TRANSCOMIC_FOLDER_SCREENSHOTS'):
        folder=Path(output);folder.mkdir(parents=True,exist_ok=True)
        assert w.grab().save(str(folder/f'{"dark" if dark else "light"}-{round(dpr*100)}.png'))
