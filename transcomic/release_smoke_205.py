"""Windows frozen acceptance using the existing isolated smoke entry point."""
import hashlib
import json
from pathlib import Path

from docx import Document
from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage
from PySide6.QtWidgets import QApplication

from .version import VERSION


def drop(view, point, paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
    enter = QDragEnterEvent(point, Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    event = QDropEvent(QPointF(point), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(view.viewport(), enter)
    QApplication.sendEvent(view.viewport(), event)
    assert enter.isAccepted() and event.isAccepted()


def run(window, root, wait):
    page = window.automation_page
    window.pages.setCurrentIndex(9)
    assert not page.repo.worksets()
    seen = root / 'folder-seed.json'
    if not seen.exists():
        media = root / 'Image group'
        media.mkdir()
        image = QImage(16, 20, QImage.Format_RGB32)
        image.fill(Qt.darkGreen)
        for number in (1, 2):
            assert image.save(str(media / f'{number}.png'))
        for name in ('Unused 1.docx', 'Unused 2.docx'):
            (media / name).write_bytes(b'Must never be opened as a DOCX')
        document = Document()
        document.add_paragraph('Synthetic source A')
        document.add_paragraph('Synthetic source B')
        selected = root / 'Chosen.docx'
        document.save(selected)
        identity = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (*media.iterdir(), selected)}
        drop(page.table, page.table.viewport().rect().center(), [media])
        wait(lambda: page.model.rowCount() == 1 and page.repo.folder_drafts(page.current)
             and '⚠ 2 file Word' in page.model.index(0, 1).data())
        entry, = page.repo.folder_drafts(page.current)
        assert len(entry.scan.images) == 2 and len(entry.scan.words) == 2
        index = page.model.index(0, 1)
        assert '⚠ 2 file Word' in index.data() and not window.store.documents()
        window.grab().save(str(root / 'folder-warning.png'))
        drop(page.table, page.table.visualRect(index).center(), [selected])
        wait(lambda: bool(page.repo.group_summaries(page.current)) and
             not page.repo.folder_drafts(page.current) and
             page.model.index(0, 1).data() == selected.name)
        rows = page.repo.group_summaries(page.current)
        assert len(rows) == 1 and rows[0]['id'] == entry.id and rows[0]['path'] == str(selected)
        assert rows[0]['data']['image_folder'] == str(media)
        assert rows[0]['data']['image_word_count'] == 2 and not window.store.jobs()
        waiting = root / 'Waiting group'
        waiting.mkdir()
        assert image.save(str(waiting / '1.png'))
        blank = page.table.viewport().rect().bottomLeft()
        blank.setY(blank.y() - 3)
        assert not page.table.indexAt(blank).isValid()
        drop(page.table, blank, [waiting])
        wait(lambda: page.model.rowCount() == 2 and page.repo.folder_drafts(page.current)
             and not page.repo.folder_drafts(page.current)[0].busy)
        result = dict(version=VERSION, images=2, detected_word=2, explicit_import=1,
                      pending_folder_at_close=True, translation_requests=0, sources=identity)
        marker = seen
    else:
        previous = json.loads(seen.read_text(encoding='utf-8'))
        assert not page.repo.folder_drafts(page.current) and page.model.rowCount()==0
        assert len(window.store.documents()) == 1 and not window.store.jobs()
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==sha
                   for path,sha in previous['sources'].items())
        result = dict(version=VERSION, fresh_session=True, permanent_document_preserved=True,
                      sources_unchanged=True, translation_requests=0)
        marker = root / 'folder-reopen.json'
    window.confirm_exit = lambda _: 'safe'
    window.close()
    wait(lambda: window._closed)
    marker.write_text(json.dumps(result,indent=2),encoding='utf-8')
