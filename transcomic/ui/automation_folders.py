"""Session-only image folders. A document is attached by an explicit drop or click."""
from dataclasses import dataclass, field
from pathlib import Path
import threading

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QHBoxLayout, QVBoxLayout

from ..automation.folder_inputs import DOCUMENTS, WORD, FolderImages, scan_folder, word_notice
from ..automation.repository import source_key
from ..automation.validation import check_current, ValidationSuperseded
from .automation_widgets import AutomationCard
from .glass import GlassButton
from .theme import colors


@dataclass(eq=False)
class FolderEntry:
    path: Path
    cancelled: threading.Event = field(default_factory=threading.Event)
    result: FolderImages | None = None
    status: str = 'Đang quét ảnh…'


def local_paths(event):
    urls = event.mimeData().urls()
    return [Path(url.toLocalFile()) for url in urls] if all(url.isLocalFile() for url in urls) else []


class FolderList(QListWidget):
    dropped = Signal(object, object)

    def __init__(self, parent):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setWordWrap(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAccessibleName('Thư mục ảnh trong bộ công việc')

    def dragEnterEvent(self, event):
        if local_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, event):
        paths = local_paths(event)
        if not paths:
            event.ignore()
            return
        item = self.itemAt(event.position().toPoint())
        self.dropped.emit(paths, item.data(Qt.UserRole) if item else None)
        event.acceptProposedAction()


class FolderInputs(AutomationCard):
    update_entry = Signal(str, object, object)

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.entries = {}
        self.items = {}
        self.slots = threading.BoundedSemaphore(2)
        self.dark = page.owner.dark
        self.update_entry.connect(self.apply_update, Qt.QueuedConnection)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 5)
        layout.setSpacing(3)
        label = QLabel('Thư mục ảnh · Kéo DOCX đã chọn vào đúng thư mục')
        label.setWordWrap(True)
        layout.addWidget(label)
        self.list = FolderList(self)
        self.list.setFixedHeight(110)
        self.list.dropped.connect(self.drop)
        self.list.currentItemChanged.connect(lambda *_: self.update_controls())
        layout.addWidget(self.list)
        controls = QHBoxLayout()
        self.attach = GlassButton('Ghép với dòng đã chọn')
        self.attach.clicked.connect(self.attach_selected)
        self.remove = GlassButton('Bỏ thư mục')
        self.remove.clicked.connect(self.remove_selected)
        controls.addWidget(self.attach)
        controls.addWidget(self.remove)
        controls.addStretch()
        layout.addLayout(controls)
        self.hide()

    def current_entries(self):
        return self.entries.get(self.page.current, {})

    def selected(self):
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def render(self):
        self.list.clear()
        self.items.clear()
        for entry in self.current_entries().values():
            item = QListWidgetItem()
            item.setData(Qt.UserRole, entry)
            self.list.addItem(item)
            self.items[entry] = item
            self.render_entry(entry)
        self.list.setFixedHeight(55 * min(2, max(1, len(self.items))))
        self.setVisible(bool(self.items))
        self.update_controls()

    def render_entry(self, entry):
        item = self.items.get(entry)
        if item is None:
            return
        result = entry.result
        details = entry.status
        warning = ''
        tooltip = str(entry.path)
        if result:
            warning = word_notice(len(result.words))
            details = f'{len(result.images)} ảnh' if result.images else 'Không có ảnh hợp lệ'
            if result.invalid:
                details += f' · {len(result.invalid)} ảnh lỗi'
            if result.duplicates:
                details += f' · {result.duplicates} đường dẫn trùng'
            if warning:
                details += ' · ' + warning
                tooltip += '\nWord không được nhập tự động. Kéo DOCX bạn chọn vào đúng thư mục.'
            if result.words:
                tooltip += '\nWord: ' + ', '.join(result.words[:15])
        item.setText((entry.path.name or str(entry.path)) + '\n' + details)
        item.setToolTip(tooltip)
        ink = colors(self)['ink']
        item.setForeground(QColor(('#f5bb69' if self.page.owner.dark else '#81450c') if warning else ink))

    def update_controls(self):
        if self.dark != self.page.owner.dark:
            self.dark = self.page.owner.dark
            for entry in self.items:
                self.render_entry(entry)
        entry = self.selected()
        editable = not self.page.controller.busy and not self.page.draft_cancel.is_set()
        self.attach.setEnabled(bool(editable and self.ready(entry) and self.page.selected()))
        self.remove.setEnabled(bool(editable and entry))

    @staticmethod
    def ready(entry):
        # Pairing uses the existing strict validation for the selected folder.
        return bool(entry and entry.result and entry.result.images and not entry.result.invalid and not entry.result.duplicates)

    def add(self, workset, paths):
        entries = self.entries.setdefault(workset, {})
        new_entries = []
        for path in paths:
            key = source_key(path)
            if key in entries:
                continue
            entry = FolderEntry(Path(path).resolve())
            entries[key] = entry
            new_entries.append(entry)
        if not new_entries:
            return
        self.render()

        def inspect():
            for entry in new_entries:
                def cancelled():
                    return self.page.draft_cancel.is_set() or entry.cancelled.is_set()

                def progress(done, total):
                    self.update_entry.emit(workset, entry, f'Đang quét ảnh {done}/{total}…')

                try:
                    while not self.slots.acquire(timeout=.05):
                        check_current(cancelled)
                    try:
                        check_current(cancelled)
                        result = scan_folder(entry.path, cancelled=cancelled, progress=progress)
                    finally:
                        self.slots.release()
                    check_current(cancelled)
                    self.update_entry.emit(workset, entry, result)
                except ValidationSuperseded:
                    continue
                except OSError:
                    self.update_entry.emit(workset, entry, 'Không đọc được thư mục ảnh.')

        self.page.background(inspect, lambda _: None)

    def apply_update(self, workset, entry, value):
        if self.page.draft_cancel.is_set() or entry.cancelled.is_set():
            return
        if isinstance(value, FolderImages):
            entry.result = value
        else:
            entry.status = value
        if workset == self.page.current:
            self.render_entry(entry)
            self.update_controls()

    def remove_selected(self):
        entry = self.selected()
        if entry and not self.page.controller.busy:
            entry.cancelled.set()
            entries = self.current_entries()
            for key in tuple(entries):
                if entries[key] is entry:
                    del entries[key]
                    break
            self.render()

    def discard_workset(self, workset):
        for entry in self.entries.pop(workset, {}).values():
            entry.cancelled.set()

    def attach_selected(self):
        entry, group = self.selected(), self.page.selected()
        if self.ready(entry) and group and not self.page.controller.busy:
            self.page.safe(lambda: self.page.pair_folder(group, entry.path))

    def drop(self, paths, entry):
        if self.page.controller.busy or self.page.draft_cancel.is_set():
            return
        if entry and len(paths) > 1 and all(path.suffix.lower() in DOCUMENTS for path in paths):
            self.page.notice.setText('Kéo một file DOCX mỗi lần để ghép với thư mục ảnh đã chọn.')
            return
        if entry and len(paths) == 1 and paths[0].suffix.lower() in DOCUMENTS and paths[0].is_file():
            if paths[0].suffix.lower() != WORD:
                self.page.notice.setText('Kéo DOCX vào thư mục ảnh, hoặc chọn dòng tài liệu đã nhập rồi bấm Ghép.')
                return
            if not self.ready(entry):
                self.page.notice.setText('Chờ quét xong và chọn thư mục có ảnh hợp lệ trước khi ghép Word.')
                return
            workset = self.page.current
            self.page.safe(lambda: self.page.queue_documents(paths, lambda groups: self.attach_word(workset, entry, groups)))
        else:
            self.page.drop_paths([str(path) for path in paths])

    def attach_word(self, workset, entry, groups):
        if self.page.current == workset and not entry.cancelled.is_set() and len(groups) == 1:
            self.page.pair_folder(groups[0], entry.path)
