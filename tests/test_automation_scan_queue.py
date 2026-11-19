"""Measure real scan entries and exercise cancellation through the Automation table."""
import threading
import time

import pytest
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QMessageBox

from transcomic.ui import automation_drops
from test_automation_folder_inputs import docx, drop, empty_point, fixture_folder, row_at, settled
from test_automation_ui import gui, wait


class HeldScans:
    def __init__(self, folders):
        self.release = {path: threading.Event() for path in folders}
        self.lock = threading.Lock()
        self.started = []
        self.active = set()
        self.peak = 0
        self.original = automation_drops.scan_folder

    def scan(self, path, *, cancelled, progress, inspection):
        with self.lock:
            self.started.append(path)
            self.active.add(path)
            self.peak = max(self.peak, len(self.active))
        try:
            result = self.original(path, progress=progress, inspection=inspection)
            deadline = time.monotonic() + 10
            while not (self.release[path].wait(.005) or cancelled()):
                if time.monotonic() >= deadline:
                    raise TimeoutError(f'Test did not release {path}')
            # Even a late successful result after cancellation must be discarded.
            return result
        finally:
            with self.lock:
                self.active.remove(path)

    def snapshot(self):
        with self.lock:
            return list(self.started), set(self.active), self.peak

    def release_all(self):
        for event in self.release.values():
            event.set()


def row_status(page):
    return {row['path']: page.model.index(i, 5).data() for i, row in enumerate(page.model.rows)}


@pytest.mark.parametrize('count', [5, 10, 15, 30])
def test_actual_scan_limit_and_rolling_fifo(gui, tmp_path, monkeypatch, request, count):
    app, _, page, workset = gui
    folders = [fixture_folder(tmp_path / f'Chapter {i:02}', i % 3 + 1, 0) for i in range(count)]
    scans = HeldScans(folders)
    monkeypatch.setattr(automation_drops, 'scan_folder', scans.scan)
    try:
        drop(app, page.table, empty_point(page), folders)
        first = min(count, 10)
        wait(app, lambda: len(scans.snapshot()[1]) == first)
        assert set(scans.snapshot()[0]) == set(folders[:first])
        by_path = {str(path): f'Đang quét ảnh {i % 3 + 1}/{i % 3 + 1}' if i < first else 'Chờ quét'
                   for i, path in enumerate(folders)}
        wait(app, lambda: row_status(page) == by_path)

        for i in range(10, count):
            scans.release[folders[i - 10]].set()
            wait(app, lambda: len(scans.snapshot()[0]) == i + 1)
            started, active, peak = scans.snapshot()
            assert started[-1] == folders[i] and active == set(folders[i - 9:i + 1])
            assert peak == 10
    finally:
        scans.release_all()

    wait(app, lambda: settled(page, count) and not page.folder_scans_active())
    started, active, peak = scans.snapshot()
    assert not active and peak == first and set(started) == set(folders)
    assert len(started) == count
    assert all(draft.status == 'Đã quét xong' and len(draft.scan.images) == folders.index(draft.path) % 3 + 1
               for draft in page.repo.folder_drafts(workset))
    wait(app, lambda: all(page.model.index(i, 4).data() == 'Đã quét xong' for i in range(count)))
    request.node.user_properties.extend([('folders', count), ('actual_peak', peak), ('finished', len(started))])


def test_add_delete_and_cancel_share_the_same_queue(gui, tmp_path, monkeypatch):
    app, window, page, workset = gui
    folders = [fixture_folder(tmp_path / f'Chapter {i:02}', 1, 0) for i in range(17)]
    for i in (1, 3):
        docx(folders[i] / 'Word.docx', 1)
    scans = HeldScans(folders)
    monkeypatch.setattr(automation_drops, 'scan_folder', scans.scan)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    try:
        drop(app, page.table, empty_point(page), folders[:12])
        wait(app, lambda: len(scans.snapshot()[1]) == 10)
        extra_drop = page.table.visualRect(page.model.index(0, 2)).center()
        drop(app, page.table, extra_drop, folders[12:])
        ids = {draft.path: draft.id for draft in page.repo.folder_drafts(workset)}
        page.row_action(ids[folders[10]], 'remove')
        page.row_action(ids[folders[13]], 'remove')
        page.row_action(ids[folders[14]], 'cancel_scan')
        page.row_action(ids[folders[1]], 'remove')
        wait(app, lambda: folders[11] in scans.snapshot()[1])
        point = row_at(page, ids[folders[3]])
        event = QContextMenuEvent(QContextMenuEvent.Mouse, point, page.table.viewport().mapToGlobal(point))
        app.sendEvent(page.table.viewport(), event)
        cancel = next(action for action in page.row_menu.actions() if action.text() == 'Hủy quét ảnh')
        assert cancel.isEnabled()
        cancel.trigger()
        page.row_menu.close()
        wait(app, lambda: folders[12] in scans.snapshot()[1])
        assert scans.snapshot()[1] == (set(folders[:10]) - {folders[1], folders[3]}) | {folders[11], folders[12]}
        assert scans.snapshot()[2] == 10
        wait(app, lambda: all(row_status(page).get(str(folders[i])) == 'Đã hủy' for i in (3, 14)))
    finally:
        scans.release_all()

    wait(app, lambda: settled(page, 14) and not page.folder_scans_active())
    started, active, peak = scans.snapshot()
    assert set(started) == set(folders) - {folders[10], folders[13], folders[14]}
    assert not active and peak == 10
    assert not page.repo.groups(workset) and not window.store.documents()
    assert all((folder / '1.png').is_file() for folder in folders)


def test_failed_scan_keeps_status_and_releases_worker(gui, tmp_path, monkeypatch):
    app, _, page, workset = gui
    folders = [fixture_folder(tmp_path / f'Chapter {i:02}', 1, 0) for i in range(11)]
    scans = HeldScans(folders)

    def scan(path, **kwargs):
        result = scans.scan(path, **kwargs)
        if path == folders[0]:
            raise PermissionError('Thư mục không đọc được')
        return result

    monkeypatch.setattr(automation_drops, 'scan_folder', scan)
    try:
        drop(app, page.table, empty_point(page), folders)
        wait(app, lambda: len(scans.snapshot()[1]) == 10)
        scans.release[folders[0]].set()
        wait(app, lambda: folders[10] in scans.snapshot()[1])
        wait(app, lambda: row_status(page).get(str(folders[0])) == 'Quét lỗi')
        failure = next(draft for draft in page.repo.folder_drafts(workset) if draft.path == folders[0])
        assert 'không đọc được' in failure.error
    finally:
        scans.release_all()


def test_parallel_word_import_preserves_each_folder_mapping(gui, tmp_path, monkeypatch):
    app, window, page, workset = gui
    folders = [fixture_folder(tmp_path / f'Chapter {i:02}', i + 1, 0) for i in range(12)]
    for i, folder in enumerate(folders, 1):
        docx(folder / 'Word.docx', i)
    skipped = fixture_folder(tmp_path / 'Cancel this scan', 1, 0)
    scans = HeldScans([skipped])

    def scan(path, **kwargs):
        return (scans.scan if path == skipped else scans.original)(path, **kwargs)

    monkeypatch.setattr(automation_drops, 'scan_folder', scan)
    try:
        drop(app, page.table, empty_point(page), [skipped, *folders])
        wait(app, lambda: skipped in scans.snapshot()[1])
        draft = next(d for d in page.repo.folder_drafts(workset) if d.path == skipped)
        page.row_action(draft.id, 'cancel_scan')
        wait(app, lambda: settled(page, 13) and page.start.isEnabled())
    finally:
        scans.release_all()
    assert len(window.store.documents()) == 12
    assert page.repo.folder_drafts(workset) == (draft,) and draft.status == 'Đã hủy'
    for group in page.repo.groups(workset):
        folder = tmp_path / f"Chapter {group['data']['slot_count'] - 1:02}"
        assert group['data']['image_folder'] == str(folder)
        assert group['data']['image_count'] == group['data']['slot_count']
        assert all(image['path'].startswith(str(folder)) for image in group['data']['images'])


def test_close_discards_queued_scans_and_waits_for_running_workers(gui, tmp_path, monkeypatch):
    app, window, page, _ = gui
    folders = [fixture_folder(tmp_path / f'Chapter {i:02}', 1, 0) for i in range(15)]
    docx(folders[0] / 'Word.docx', 1)
    scans = HeldScans(folders)
    cancelling = threading.Event()

    def scan(path, *, cancelled, progress, inspection):
        result = scans.scan(path, cancelled=cancelled, progress=progress, inspection=inspection)
        if cancelled():
            cancelling.set()
            scans.release[path].wait(5)
        return result

    monkeypatch.setattr(automation_drops, 'scan_folder', scan)
    try:
        drop(app, page.table, empty_point(page), folders)
        wait(app, lambda: len(scans.snapshot()[1]) == 10)
        window._exit_authorized = True
        window.close()
        wait(app, cancelling.is_set)
        assert page.folder_scans_active() and not window._closed
        assert not window.store.documents()
        assert set(scans.snapshot()[0]) == set(folders[:10])
    finally:
        scans.release_all()
    wait(app, lambda: window._closed)
    assert not page.folder_scans_active()
    assert set(scans.snapshot()[0]) == set(folders[:10])
    assert all((folder / '1.png').is_file() for folder in folders)
