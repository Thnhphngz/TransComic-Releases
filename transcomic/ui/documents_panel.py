"""Virtual document navigator: one painted row per imported source instance."""
from PySide6.QtCore import Qt, QSize, QRect, QAbstractListModel, QObject, QEvent
from PySide6.QtGui import QColor, QPen, QLinearGradient
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListView, QStyledItemDelegate, QStyle)
from .theme import LIGHT, DARK
from .glass import GlassButton as QPushButton, IconGlassButton


def local_drop_paths(mime):
    # A remote URL, including file://remote-host/share, never becomes a disk path.
    return [u.toLocalFile() for u in mime.urls()
            if u.isLocalFile() and u.scheme() == 'file' and not u.host()
            and u.toLocalFile() and '\x00' not in u.toLocalFile()]


class DropTargetFilter(QObject):
    def eventFilter(self, target, event):
        owner = self.parent()
        if event.type() in (QEvent.DragEnter, QEvent.DragMove):
            owner.dragEnterEvent(event); return True
        if event.type() == QEvent.DragLeave:
            owner.dragLeaveEvent(event); return True
        if event.type() == QEvent.Drop:
            owner.dropEvent(event); return True
        return False


class DocumentListModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.checked = set()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        item = self.items[index.row()]
        if role == Qt.DisplayRole: return item['name']
        if role == Qt.UserRole: return item
        if role == Qt.ToolTipRole: return item['path']+'\n'+item['details']
        if role == Qt.CheckStateRole: return Qt.Checked if item['instance'] in self.checked else Qt.Unchecked

    def update_items(self, items):
        if [i['instance'] for i in items] != [i['instance'] for i in self.items]:
            self.beginResetModel(); self.items = items; self.endResetModel()
        elif self.items != items:
            self.items = items
            if items: self.dataChanged.emit(self.index(0), self.index(len(items)-1))


class DocumentDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index): return QSize(230, 112)

    @staticmethod
    def close_rect(rect):
        return QRect(rect.right()-38, rect.top()+6, 32, 32)

    @staticmethod
    def check_rect(rect):
        return QRect(rect.left()+5, rect.top()+6, 30, 32)

    def paint(self, painter, option, index):
        item = index.data(Qt.UserRole); owner = self.parent().owner
        c = DARK if owner.dark else LIGHT
        painter.save(); painter.setRenderHint(painter.RenderHint.Antialiasing)
        r = option.rect.adjusted(3, 3, -3, -3)
        active = owner.doc_id in item['ids']
        base = QColor(c['field'] if active else c['panel'])
        gradient = QLinearGradient(r.topLeft(), r.bottomLeft())
        gradient.setColorAt(0, base.lighter(110 if owner.dark else 103))
        gradient.setColorAt(.4, base); gradient.setColorAt(1, base.darker(107 if owner.dark else 103))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(c['accent'] if active else c['border']), 2 if active else 1))
        painter.drawRoundedRect(r, 10, 10)
        painter.setPen(QColor(c['accent']))
        painter.drawText(self.check_rect(option.rect), Qt.AlignCenter,
                         '☑' if item['instance'] in self.parent().model.checked else '☐')
        close = self.close_rect(option.rect)
        if self.parent().view.hover_close == item['instance']:
            painter.setBrush(QColor(c['field'])); painter.setPen(QPen(QColor(c['border']), 1))
            painter.drawRoundedRect(close.adjusted(2,2,-2,-2), 7, 7)
        painter.setPen(QColor(c['accent']))
        painter.drawText(close, Qt.AlignCenter, '×')
        font = painter.font(); font.setBold(True); painter.setFont(font)
        name = option.fontMetrics.elidedText(item['name'], Qt.ElideMiddle, max(20, r.width()-76))
        painter.setPen(QColor(c['ink'])); painter.drawText(r.x()+35, r.y()+25, name)
        font.setBold(False); painter.setFont(font); painter.setPen(QColor(c['muted']))
        line = item['format']+' · '+item['summary']
        painter.drawText(r.x()+12, r.y()+49, option.fontMetrics.elidedText(line, Qt.ElideRight, r.width()-24))
        painter.drawText(r.x()+12, r.y()+68, option.fontMetrics.elidedText(item['details'], Qt.ElideRight, r.width()-24))
        painter.setPen(Qt.NoPen); painter.setBrush(QColor(c['border']))
        painter.drawRoundedRect(QRect(r.x()+12, r.y()+80, r.width()-24, 5), 2, 2)
        painter.setBrush(QColor(c['accent']))
        painter.drawRoundedRect(QRect(r.x()+12, r.y()+80, int((r.width()-24)*item['progress']/100), 5), 2, 2)
        painter.restore()

class DropList(QListView):
    def __init__(self, panel):
        super().__init__(panel); self.panel = panel
        self.setAcceptDrops(True); self.viewport().setAcceptDrops(True)
        self.setMouseTracking(True)
        self.hover_close = None; self._pressed_action = None

    def hit_action(self, point):
        index = self.indexAt(point)
        if not index.isValid(): return None
        rect = self.visualRect(index); delegate = self.itemDelegate()
        instance = index.data(Qt.UserRole)['instance']
        if delegate.close_rect(rect).contains(point): return ('close', instance)
        if delegate.check_rect(rect).contains(point): return ('check', instance)
        return None

    def mousePressEvent(self, event):
        self._pressed_action = self.hit_action(event.position().toPoint()) if event.button() == Qt.LeftButton else None
        if self._pressed_action:
            event.accept(); return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        action = self._pressed_action; self._pressed_action = None
        if action:
            if event.button() == Qt.LeftButton and action == self.hit_action(event.position().toPoint()):
                kind, instance = action
                if kind == 'close': self.panel.owner.remove_workspace_instances({instance})
                else:
                    checked = self.panel.model.checked
                    if instance in checked: checked.remove(instance)
                    else: checked.add(instance)
                    self.viewport().update()
            event.accept(); return
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        action = self.hit_action(event.position().toPoint())
        hover = action[1] if action and action[0] == 'close' else None
        if hover != self.hover_close:
            self.hover_close = hover; self.viewport().update()
            self.viewport().setCursor(Qt.PointingHandCursor if hover else Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def viewportEvent(self, event):
        if event.type() == QEvent.ToolTip:
            action = self.hit_action(event.pos())
            if action and action[0] == 'close':
                from PySide6.QtWidgets import QToolTip
                QToolTip.showText(event.globalPos(), 'Bỏ file khỏi workspace · giữ nguồn và lịch sử', self)
                return True
        return super().viewportEvent(event)

    def leaveEvent(self, event):
        self.hover_close = None; self.viewport().update()
        super().leaveEvent(event)

    def dragEnterEvent(self, event): self.panel.owner.dragEnterEvent(event)
    def dragMoveEvent(self, event): self.panel.owner.dragEnterEvent(event)
    def dragLeaveEvent(self, event): self.panel.owner.dragLeaveEvent(event)
    def dropEvent(self, event): self.panel.owner.dropEvent(event)


class DocumentsPanel(QWidget):
    def __init__(self, owner):
        super().__init__(); self.owner = owner; self.setObjectName('documentPanel')
        self.setMinimumWidth(220)
        layout = QVBoxLayout(self); layout.setContentsMargins(8, 14, 8, 10); layout.setSpacing(8)
        header = QHBoxLayout(); self.title = QLabel('TÀI LIỆU'); header.addWidget(self.title, 1)
        collapse = IconGlassButton('‹'); collapse.setToolTip('Thu gọn panel tài liệu')
        collapse.clicked.connect(owner.toggle_documents_panel); header.addWidget(collapse); layout.addLayout(header)
        self.search = QLineEdit(); self.search.setPlaceholderText('Tìm tên file…')
        self.search.textChanged.connect(owner.refresh_document_panel); layout.addWidget(self.search)
        remove = QPushButton('Bỏ các file đã chọn'); remove.clicked.connect(lambda: owner.remove_workspace_instances(set(self.model.checked)))
        layout.addWidget(remove)
        self.remove_all = QPushButton('Bỏ tất cả file')
        self.remove_all.clicked.connect(owner.remove_all_workspace)
        layout.addWidget(self.remove_all)
        self.drop_hint = QLabel('Kéo file hoặc thư mục vào đây'); self.drop_hint.setWordWrap(True)
        self.drop_hint.setObjectName('muted'); layout.addWidget(self.drop_hint)
        self.view = DropList(self); self.view.setUniformItemSizes(True)
        self.model = DocumentListModel(self.view); self.view.setModel(self.model)
        self.view.setItemDelegate(DocumentDelegate(self))
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.clicked.connect(lambda index: owner.open_document_group(index.data(Qt.UserRole)))
        self.view.activated.connect(lambda index: owner.open_document_group(index.data(Qt.UserRole)))
        layout.addWidget(self.view, 1)
