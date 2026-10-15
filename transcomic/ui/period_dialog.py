"""A bounded, virtual table of live punctuation warnings, with stable row keys."""
from html import escape
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHeaderView, QLabel,
    QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableView, QVBoxLayout, QHBoxLayout)
from .glass import GlassButton
from .model import text_document
from .period_warning import period_selections


class PeriodRows(QAbstractTableModel):
    def __init__(self, parent):
        super().__init__(parent); self.rows = ()

    def rowCount(self, parent=QModelIndex()): return 0 if parent.isValid() else len(self.rows)
    def columnCount(self, parent=QModelIndex()): return 0 if parent.isValid() else 3

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows): return None
        row = self.rows[index.row()]
        if role == Qt.UserRole: return (row['document_id'], row['id'])
        if role == Qt.DisplayRole:
            return (f"Dòng {row['ordinal']+1}" if isinstance(row['ordinal'],int) else 'Tài liệu', row['preview'], row['document']+' · '+row['language'])[index.column()]
        if role == Qt.ToolTipRole:
            return '<p>'+escape(f"{row['document']} · {row['language']}")+\
                '</p><p>'+escape(row['preview'])+'</p>'

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return ('Dòng gốc', 'Bản dịch', 'Tài liệu · Ngôn ngữ')[section]

    def replace(self, rows):
        rows = tuple(rows)
        if self.rows == rows: return
        self.beginResetModel(); self.rows = rows; self.endResetModel()


class PeriodPreview(QStyledItemDelegate):
    def paint(self, painter, option, index):
        if index.column() != 1: return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option); self.initStyleOption(opt, index)
        text = opt.text; opt.text = ''
        self.parent().style().drawControl(QStyle.CE_ItemViewItem, opt, painter, self.parent())
        rect = option.rect.adjusted(8, 4, -8, -4)
        document = text_document(text, option.font, rect.width())
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette.setColor(QPalette.Text, opt.palette.color(QPalette.HighlightedText if opt.state & QStyle.State_Selected else QPalette.Text))
        context.selections = period_selections(document, text, QAbstractTextDocumentLayout.Selection)
        painter.save(); painter.setClipRect(rect); painter.translate(rect.topLeft())
        document.documentLayout().draw(painter, context); painter.restore()


class PeriodTable(QTableView):
    picked = Signal(object)

    def __init__(self, parent):
        super().__init__(parent); self._pressed_key = None

    def mousePressEvent(self, event):
        self._pressed_key = self.indexAt(event.position().toPoint()).data(Qt.UserRole) if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        key = self._pressed_key; self._pressed_key = None
        current = self.indexAt(event.position().toPoint()).data(Qt.UserRole)
        super().mouseReleaseEvent(event)
        if event.button() == Qt.LeftButton and key and key == current: self.picked.emit(key)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape: self.window().reject(); return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            key = self.currentIndex().data(Qt.UserRole)
            if key: self.picked.emit(key)
            return
        super().keyPressEvent(event)


class PeriodDialog(QDialog):
    def __init__(self, warning, *, structure=False):
        super().__init__(warning.owner)
        self.warning = warning; self.structure = structure
        self.setWindowTitle('Kiểm tra số dòng' if structure else 'Các dòng dịch có dấu chấm')
        self.setWindowModality(Qt.NonModal)
        layout = QVBoxLayout(self)
        self.summary = QLabel(); self.summary.setWordWrap(True); layout.addWidget(self.summary)
        self.empty = QLabel('Không còn dòng dịch chứa dấu chấm trong workspace đang mở.')
        self.empty.setWordWrap(True); layout.addWidget(self.empty)
        self.table = PeriodTable(self); self.model = PeriodRows(self.table); self.table.setModel(self.model)
        self.table.setItemDelegate(QStyledItemDelegate(self.table) if structure else PeriodPreview(self.table)); self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(54)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(2, 190)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.picked.connect(warning.choose); layout.addWidget(self.table, 1)
        footer = QHBoxLayout(); footer.addStretch()
        close = GlassButton('Đóng'); close.clicked.connect(self.reject); footer.addWidget(close); layout.addLayout(footer)
        self.watch = QTimer(self); self.watch.setInterval(120); self.watch.timeout.connect(warning.recount)

    def fit_screen(self):
        area = self.warning.owner.screen().availableGeometry()
        self.setMaximumSize(max(1, area.width()-24), max(1, area.height()-24))
        self.resize(min(760, self.maximumWidth()), min(460, int(area.height()*.65), self.maximumHeight()))

    def update_rows(self, rows):
        key = self.table.currentIndex().data(Qt.UserRole)
        scroll = self.table.verticalScrollBar().value()
        self.model.replace(rows)
        if key:
            position = next((i for i, row in enumerate(rows) if (row['document_id'], row['id']) == key), None)
            if position is not None: self.table.setCurrentIndex(self.model.index(position, 1))
        self.table.verticalScrollBar().setValue(scroll)
        self.summary.setText(self.warning.dialog_summary() if self.structure else f'{len(rows)} dòng · Chọn dòng để mở bản dịch. Tài liệu và ngôn ngữ được ghi ở từng mục.')
        if self.structure: self.empty.setText(self.warning.dialog_empty_text())
        self.empty.setVisible(not rows)

    def showEvent(self, event):
        super().showEvent(event); self.watch.start()

    def hideEvent(self, event):
        self.watch.stop(); super().hideEvent(event)
