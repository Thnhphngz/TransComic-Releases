"""Virtual manuscript table, stable row selection and full-cell editing."""
from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QEvent, QModelIndex, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPen, QTextDocument, QTextOption
from PySide6.QtWidgets import (
    QAbstractItemView, QHeaderView, QPlainTextEdit, QStyle, QStyledItemDelegate,
    QStyleOptionButton, QStyleOptionViewItem, QTableView,
)

from ..storage import Store
from ..status import matches_filter
from .theme import DARK, LIGHT

LABELS = {"wrong_target_language": "Sai ngôn ngữ đích","pending": "Chờ", "processing": "Đang dịch", "done": "Hoàn tất", "error": "Lỗi", "unknown": "Không rõ kết quả", "skip": "Giữ nguyên", "stale": "Có thể đã cũ"}


def line_label(row):
    if row.get("attempt_kind") == "retranslation":
        return {"processing": "Đang dịch lại", "done": "Dịch lại thành công", "error": "Dịch lại thất bại", "unknown": "Không rõ kết quả dịch lại"}.get(row["state"], LABELS.get(row["state"], row["state"]))
    return LABELS.get(row["state"], row["state"])
CHECK_COLUMN = 2  # Moved to the left visually; text columns retain their public indexes.


def draw_checkbox(painter, rect, widget, checked=False, mixed=False):
    colors = DARK if getattr(widget.window(), "dark", False) else LIGHT
    box = rect.adjusted(0, 0, 0, 0)
    box.setSize(QSize(16, 16))
    box.moveCenter(rect.center())
    painter.save()
    painter.setRenderHint(painter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(colors["accent"] if checked or mixed else colors["border"]), 1))
    painter.setBrush(QColor(colors["accent"] if checked or mixed else colors["panel"]))
    painter.drawRoundedRect(box.adjusted(1, 1, -1, -1), 3, 3)
    painter.setPen(QPen(Qt.white, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if mixed:
        painter.drawLine(box.left()+4, box.center().y(), box.right()-4, box.center().y())
    elif checked:
        from PySide6.QtCore import QPoint
        painter.drawPolyline([QPoint(box.left()+4, box.top()+8), QPoint(box.left()+7, box.top()+11), QPoint(box.left()+12, box.top()+5)])
    painter.restore()


class LineModel(QAbstractTableModel):
    selectionChanged = Signal()

    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.doc_id = None
        self.all_rows: list[dict] = []
        self.rows: list[dict] = []
        self.id_index: dict[str, int] = {}
        self.selected_ids: set[str] = set()
        self.filter_states: set[str] | None = None
        self.editing_id: str | None = None

    def load(self, doc_id):
        if doc_id != self.doc_id:
            self.selected_ids.clear()
        self.doc_id = doc_id
        self.all_rows = self.store.lines(doc_id) if doc_id else []
        self._rebuild_filter(force=True)

    def _rebuild_filter(self, force=False):
        visible = [r for r in self.all_rows if matches_filter(r, self.filter_states)]
        if force or [r["id"] for r in visible] != [r["id"] for r in self.rows]:
            self.beginResetModel()
            self.rows = visible
            self.id_index = {r["id"]: i for i, r in enumerate(visible)}
            self.endResetModel()
        self.selectionChanged.emit()

    def set_filter(self, states: set[str] | None):
        self.filter_states = states
        self._rebuild_filter(force=True)

    def refresh(self, changed_ids=None):
        if not self.doc_id or getattr(self.parent(), "_closed", False):
            return
        old = {r["id"]: r for r in self.rows}
        if changed_ids is None:
            self.all_rows = self.store.lines(self.doc_id)
        else:
            own_ids = {r["id"] for r in self.all_rows}
            updates = {line_id: self.store.line(line_id) for line_id in changed_ids if line_id in own_ids}
            self.all_rows = [updates.get(r["id"], r) for r in self.all_rows]
        latest = {r["id"]: r for r in self.all_rows}
        self.rows = [latest.get(r["id"], r) for r in self.rows]
        if not self.editing_id:
            self._rebuild_filter()
        for row_index, row in enumerate(self.rows):
            previous = old.get(row["id"])
            if previous != row:
                self.dataChanged.emit(self.index(row_index, 0), self.index(row_index, 1))
                self.headerDataChanged.emit(Qt.Vertical, row_index, row_index)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 3

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return ["VĂN BẢN NGUỒN", "BẢN DỊCH", ""][section]
        if role == Qt.DisplayRole and orientation == Qt.Vertical and section < len(self.rows):
            status = {"wrong_target_language": "!","pending": "·", "processing": "◌", "done": "✓", "error": "!", "unknown": "?", "skip": "–", "stale": "↻"}.get(self.rows[section]["state"], "·")
            return f"{self.rows[section]['ordinal'] + 1} {status}"
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if index.column() == CHECK_COLUMN:
            if role == Qt.CheckStateRole:
                return Qt.Checked if row["id"] in self.selected_ids else Qt.Unchecked
            return None
        if role in (Qt.DisplayRole, Qt.EditRole):
            return row["source"] if index.column() == 0 else row["translation"] or ""
        if role == Qt.ToolTipRole:
            return f"Dòng {row['ordinal'] + 1} · {line_label(row)}" + (f"\n{row['error']}" if row["error"] else "")
        if role == Qt.ForegroundRole and index.column() == 1:
            if row["state"] in ("error", "unknown"):
                return QColor("#C54D42")
            if row["state"] == "stale":
                return QColor("#B77723")
        if role == Qt.TextAlignmentRole:
            return int(Qt.AlignLeft | Qt.AlignTop)
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        if index.column() == CHECK_COLUMN:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
        return super().flags(index) | Qt.ItemIsEditable

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or getattr(self.parent(), "_closed", False):
            return False
        if index.column() == CHECK_COLUMN and role == Qt.CheckStateRole:
            self.set_checked([index.row()], value == Qt.Checked or value == Qt.Checked.value)
            return True
        if role != Qt.EditRole or index.column() not in (0, 1) or not isinstance(value, str) or "\n" in value or "\r" in value:
            return False
        row = self.rows[index.row()]
        field = "source" if index.column() == 0 else "translation"
        if (row[field] or "") == value:
            return True
        self.store.edit_line(row["id"], field, value)
        fresh = self.store.line(row["id"])
        self.rows[index.row()] = fresh
        self.all_rows = [fresh if r["id"] == fresh["id"] else r for r in self.all_rows]
        self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), 1))
        return True

    def set_checked(self, row_indexes, checked):
        for row_index in row_indexes:
            if not 0 <= row_index < len(self.rows):
                continue
            line_id = self.rows[row_index]["id"]
            if checked:
                self.selected_ids.add(line_id)
            else:
                self.selected_ids.discard(line_id)
            self.dataChanged.emit(self.index(row_index, CHECK_COLUMN), self.index(row_index, CHECK_COLUMN), [Qt.CheckStateRole])
        self.headerDataChanged.emit(Qt.Horizontal, CHECK_COLUMN, CHECK_COLUMN)
        self.selectionChanged.emit()

    def select_all_visible(self, checked=True):
        self.set_checked(range(len(self.rows)), checked)

    def clear_checked(self):
        self.selected_ids.clear()
        if self.rows:
            self.dataChanged.emit(self.index(0, CHECK_COLUMN), self.index(len(self.rows)-1, CHECK_COLUMN), [Qt.CheckStateRole])
        self.selectionChanged.emit()

    def selected_rows(self):
        return [r for r in self.rows if r["id"] in self.selected_ids]


class CheckHeader(QHeaderView):
    def __init__(self, parent):
        super().__init__(Qt.Horizontal, parent)
        self.setSectionsMovable(False)

    def paintSection(self, painter, rect, logical):
        super().paintSection(painter, rect, logical)
        if logical != CHECK_COLUMN:
            return
        model = self.model()
        selected = len(model.selected_rows())
        draw_checkbox(painter, rect, self, checked=bool(selected and selected == model.rowCount()), mixed=bool(selected and selected != model.rowCount()))

    def mousePressEvent(self, event):
        if self.logicalIndexAt(event.position().toPoint()) == CHECK_COLUMN:
            model = self.model()
            model.select_all_visible(len(model.selected_rows()) != model.rowCount())
            self.viewport().update()
            event.accept()
            return
        super().mousePressEvent(event)


class ManuscriptTable(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.check_anchor_id = None
        self.column_ratio = 0.5
        self._column_layout_enabled = False
        self._adjusting_columns = False
        self.setHorizontalHeader(CheckHeader(self))
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)

    def enable_column_resize(self):
        self._column_layout_enabled = True
        self.horizontalHeader().sectionResized.connect(self.column_resized)
        self.fit_columns()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._column_layout_enabled:
            self.fit_columns()

    def fit_columns(self):
        if self._adjusting_columns:
            return
        available = max(160, self.viewport().width()-self.columnWidth(CHECK_COLUMN)-2)
        left = max(80, min(available-80, int(available*self.column_ratio)))
        self._adjusting_columns = True
        self.setColumnWidth(0, left)
        self.setColumnWidth(1, available-left)
        self._adjusting_columns = False

    def column_resized(self, logical, old_size, new_size):
        if self._adjusting_columns or logical not in (0, 1):
            return
        available = max(160, self.viewport().width()-self.columnWidth(CHECK_COLUMN)-2)
        self.column_ratio = min(0.9, max(0.1, new_size/available if logical == 0 else 1-new_size/available))
        self.fit_columns()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            self.model().select_all_visible()
            event.accept()
            return
        if event.key() == Qt.Key_Space and self.currentIndex().isValid():
            row = self.currentIndex().row()
            self.model().set_checked([row], self.model().rows[row]["id"] not in self.model().selected_ids)
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        index = self.indexAt(event.position().toPoint())
        if index.isValid() and event.button() == Qt.LeftButton:
            modifiers = event.modifiers()
            if index.column() == CHECK_COLUMN or modifiers & (Qt.ShiftModifier | Qt.ControlModifier):
                model = self.model()
                target = model.rows[index.row()]
                if modifiers & Qt.ShiftModifier and self.check_anchor_id in model.id_index:
                    anchor = model.id_index[self.check_anchor_id]
                    model.set_checked(range(min(anchor, index.row()), max(anchor, index.row()) + 1), True)
                else:
                    model.set_checked([index.row()], target["id"] not in model.selected_ids)
                    self.check_anchor_id = target["id"]
                event.accept()
                return
        super().mousePressEvent(event)
        if index.isValid() and index.column() in (0, 1) and event.button() == Qt.LeftButton and self.state() != QAbstractItemView.EditingState:
            self.edit(index)


class OneLineEditor(QPlainTextEdit):
    def insertFromMimeData(self, source):
        text = source.text()
        if "\n" in text or "\r" in text:
            from PySide6.QtGui import QCursor
            from PySide6.QtWidgets import QToolTip
            QToolTip.showText(QCursor.pos(), "Chỉ dán một dòng vào mỗi ô.")
            return
        self.insertPlainText(text)


def text_document(text, font, width):
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    document.setDefaultTextOption(option)
    document.setPlainText(text or " ")
    document.setTextWidth(max(24, width))
    return document


class LineDelegate(QStyledItemDelegate):
    def __init__(self, table):
        super().__init__(table)
        self.active_editor = None
        self.active_index = None

    def sizeHint(self, option, index):
        if index.column() == CHECK_COLUMN:
            return QSize(38, 28)
        table = self.parent()
        text = index.data(Qt.DisplayRole) or " "
        if self.active_editor is not None and self.active_index == index:
            text = self.active_editor.toPlainText()
        width = max(24, table.columnWidth(index.column()) - 16)
        height = int(text_document(text, table.font(), width).size().height()) + 10
        return QSize(width, min(max(28, height), max(120, table.viewport().height()-24)))

    def paint(self, painter, option, index):
        if index.column() == CHECK_COLUMN:
            draw_checkbox(painter, option.rect, self.parent(), checked=index.data(Qt.CheckStateRole) == Qt.Checked)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = opt.text
        opt.text = ""
        self.parent().style().drawControl(QStyle.CE_ItemViewItem, opt, painter, self.parent())
        rect = option.rect.adjusted(8, 4, -8, -4)
        document = text_document(text, self.parent().font(), rect.width())
        from PySide6.QtGui import QAbstractTextDocumentLayout, QPalette
        context = QAbstractTextDocumentLayout.PaintContext()
        from PySide6.QtGui import QTextCursor, QTextCharFormat
        row = index.model().rows[index.row()]
        field = "source" if index.column() == 0 else "translation"
        selections = []
        for start, end in getattr(self.parent(), "search_ranges", {}).get((row["id"], field), []):
            cursor = QTextCursor(document)
            cursor.setPosition(len(text[:start].encode("utf-16-le"))//2)
            cursor.setPosition(len(text[:end].encode("utf-16-le"))//2, QTextCursor.KeepAnchor)
            selection = QAbstractTextDocumentLayout.Selection()
            selection.cursor = cursor
            selection.format = QTextCharFormat()
            selection.format.setBackground(QColor("#E2AC63"))
            selection.format.setForeground(QColor("#241A12"))
            selections.append(selection)
        context.selections = selections
        if field == 'translation' and getattr(self.parent(), 'period_focus_key', None) == (index.model().doc_id, row['id']):
            from .period_warning import period_selections
            context.selections += period_selections(document, text, QAbstractTextDocumentLayout.Selection)
        context.palette.setColor(QPalette.Text, index.data(Qt.ForegroundRole) or option.palette.color(QPalette.Text))
        painter.save()
        painter.setClipRect(rect)
        painter.translate(rect.topLeft())
        document.documentLayout().draw(painter, context)
        painter.restore()

    def createEditor(self, parent, option, index):
        if index.column() == CHECK_COLUMN:
            return None
        warning = getattr(self.parent().window(), 'period_warning', None)
        editor = warning.take_editor(parent, index) if warning is not None else None
        restored = editor is not None
        if editor is None: editor = OneLineEditor(parent)
        editor.setObjectName("cellEditor")
        editor.setFrameStyle(0)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        editor.setTabChangesFocus(True)
        editor.document().setDocumentMargin(2)
        editor._initialized = restored
        editor._dirty = False
        editor._period_keep = False
        self.active_editor = editor
        self.active_index = index
        self.parent().model().editing_id = self.parent().model().rows[index.row()]["id"]
        self.apply_editor_font()
        editor._save_connection = lambda: self._save_typing(editor, index)
        editor.textChanged.connect(editor._save_connection)
        return editor

    def apply_editor_font(self):
        if self.active_editor is not None:
            size = self.parent().font().pixelSize()
            self.active_editor.setFont(self.parent().font())
            self.active_editor.setStyleSheet(f"QPlainTextEdit#cellEditor {{ font-size: {size}px; padding: 0; border: 0; border-radius: 0; }}")

    def _save_typing(self, editor, index):
        if editor._initialized and index.isValid():
            editor._dirty = True
            self.parent().model().setData(index, editor.toPlainText())

    def setEditorData(self, editor, index):
        # API refreshes must not replace an open editor's buffer or reset its caret.
        if editor._initialized:
            warning = getattr(self.parent().window(), 'period_warning', None)
            if warning is not None: warning.update_highlight()
            return
        editor.setPlainText(index.data(Qt.EditRole) or "")
        cursor = editor.textCursor()
        cursor.setPosition(0)
        editor.setTextCursor(cursor)
        editor._initialized = True
        warning = getattr(self.parent().window(), 'period_warning', None)
        if warning is not None: warning.update_highlight()

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect.adjusted(4, 1, -4, -1))

    def setModelData(self, editor, model, index):
        if editor._dirty:
            model.setData(index, editor.toPlainText())

    def destroyEditor(self, editor, index):
        self.active_editor = None
        self.active_index = None
        self.parent().model().editing_id = None
        if getattr(editor, '_period_keep', False):
            editor.textChanged.disconnect(editor._save_connection)
            editor.hide(); editor.setParent(self.parent().window().period_warning)
        else: super().destroyEditor(editor, index)
        QTimer.singleShot(0, self.parent().model().refresh)

    def eventFilter(self, editor, event):
        if isinstance(editor, OneLineEditor) and event.type() == QEvent.FocusOut:
            for name in ('period_warning','line_check'):
                warning = getattr(self.parent().window(), name, None)
                if warning is not None and warning.dialog is not None and warning.dialog.isVisible():
                    return False  # Preserve native undo while choosing in either review dialog.
        if isinstance(editor, OneLineEditor) and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab, Qt.Key_Backtab):
                index = self.active_index
                if index is None:
                    return True
                table = self.parent()
                if event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
                    backward = event.key() == Qt.Key_Backtab or bool(event.modifiers() & Qt.ShiftModifier)
                    row, column = index.row(), index.column()
                    if backward:
                        row, column = (row, 0) if column == 1 else (max(0, row-1), 1)
                    else:
                        row, column = (row, 1) if column == 0 else (min(table.model().rowCount()-1, row+1), 0)
                else:
                    direction = -1 if event.modifiers() & Qt.ShiftModifier else 1
                    row, column = max(0, min(table.model().rowCount()-1, index.row()+direction)), index.column()
                next_id = table.model().rows[row]["id"]
                self.commitData.emit(editor)
                self.closeEditor.emit(editor)
                def navigate():
                    model = table.model()
                    if not model.rowCount():
                        return
                    target = model.id_index.get(next_id, min(row, model.rowCount()-1))
                    next_index = model.index(target, column)
                    table.setCurrentIndex(next_index)
                    table.edit(next_index)
                QTimer.singleShot(0, navigate)
                return True
            if event.key() == Qt.Key_Escape:
                self.commitData.emit(editor)
                self.closeEditor.emit(editor)
                return True
        return super().eventFilter(editor, event)
