"""Live workspace punctuation list; navigation uses document and line IDs."""
from pathlib import Path
from PySide6.QtCore import QTimer, Qt, QItemSelectionModel
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QAbstractItemView, QTextEdit
from .glass import CompactStatusButton as GlassButton


def period_selections(document, text, selection_type):
    """QTextDocument offsets are UTF-16, unlike Python string offsets."""
    selections = []; offset = 0
    for char in text:
        if char == '.':
            selection = selection_type(); selection.cursor = QTextCursor(document)
            selection.cursor.setPosition(offset)
            selection.cursor.setPosition(offset+1, QTextCursor.KeepAnchor)
            selection.format = QTextCharFormat()
            selection.format.setForeground(QColor('#E54848'))
            selection.format.setBackground(QColor(229, 72, 72, 48))
            selections.append(selection)
        offset += 2 if ord(char) > 0xFFFF else 1
    return selections


def preview(text):
    start = max(0, text.index('.')-24)
    return ('…' if start else '')+text[start:start+160]+('…' if len(text)>start+160 else '')


class PeriodWarning(GlassButton):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setObjectName('periodWarning'); self.setProperty('glassRole', 'warning')
        self.setFocusPolicy(Qt.NoFocus)
        self.setToolTip('Xem và chọn dòng dịch chứa dấu chấm ASCII . trong các file/ngôn ngữ đang mở; không quét lịch sử.')
        self.hide(); self.count = 0; self.rows = (); self.dialog = None
        self.focus_key = None; self._navigation = 0; self._editor_documents = {}; self._signature = None
        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(80)
        self.timer.timeout.connect(self.recount); self.clicked.connect(self.open_list)

    def shutdown(self):
        self.timer.stop(); self._navigation += 1
        if self.dialog is not None: self.dialog.close()
        active = self.owner.table.itemDelegate().active_editor
        for editor, _ in self._editor_documents.values():
            editor._period_keep = False
            if editor is not active: editor.deleteLater()
        self._editor_documents.clear()

    def schedule(self, *_):
        if self.owner._closed or self.owner._exit_pending: return
        with self.owner.store.lock:
            signature = (self.owner.store.db.total_changes, tuple(sorted(set(self.owner.workspace_ids))))
        if signature != self._signature and not self.timer.isActive(): self.timer.start()

    def recount(self):
        owner = self.owner
        if owner._closed or owner._exit_pending: return
        ids = tuple(dict.fromkeys(owner.workspace_ids)); rows = []
        with owner.store.lock:
            signature = (owner.store.db.total_changes, tuple(sorted(ids)))
            if signature == self._signature: return
            for start in range(0, len(ids), 500):
                chunk = ids[start:start+500]
                for row in owner.store.db.execute(
                    'SELECT l.id,l.document_id,l.ordinal,l.translation,d.path,d.target_lang '
                    'FROM lines l JOIN documents d ON d.id=l.document_id WHERE l.document_id IN ('+
                    ','.join('?' for _ in chunk)+") AND instr(l.translation, '.') > 0 ORDER BY l.ordinal", chunk):
                    rows.append({'id': row['id'], 'document_id': row['document_id'], 'ordinal': row['ordinal'],
                                 'preview': preview(row['translation']), 'document': Path(row['path']).name,
                                 'language': row['target_lang']})
        order = {doc: i for i, doc in enumerate(ids)}
        rows.sort(key=lambda r: (order[r['document_id']], r['ordinal'], r['id']))
        self._signature = signature; self.rows = tuple(rows); self.count = len(rows)
        self.setText(f'⚠\ufe0e {self.count} dòng dịch có dấu chấm'); self.setAccessibleName(self.text())
        self.setVisible(self.count > 0)
        if self.focus_key and self.focus_key[0] not in ids: self.focus_key = None
        for key in list(self._editor_documents):
            if key[0] not in ids:
                editor, _ = self._editor_documents.pop(key)
                editor._period_keep = False
                if editor is not owner.table.itemDelegate().active_editor: editor.deleteLater()
        if self.dialog is not None: self.dialog.update_rows(self.rows)
        self.update_highlight()

    def open_list(self):
        from .period_dialog import PeriodDialog
        if self.owner._closed or self.owner._exit_pending: return
        self.recount()
        if self.dialog is None: self.dialog = PeriodDialog(self)
        self.dialog.update_rows(self.rows); self.dialog.fit_screen()
        self.dialog.show(); self.dialog.raise_(); self.dialog.activateWindow()

    def remember_editor(self):
        """Keep the whole native editor; moving its document alone is unsafe in Qt."""
        owner = self.owner; delegate = owner.table.itemDelegate()
        editor = delegate.active_editor; index = delegate.active_index
        if editor is None or index is None or not index.isValid(): return
        row = owner.model.rows[index.row()]; field = 'source' if index.column() == 0 else 'translation'
        fresh = owner.store.line(row['id']); key = (owner.doc_id, row['id'], field)
        previous = self._editor_documents.get(key)
        if previous and previous[0] is not editor: previous[0].deleteLater()
        editor._period_keep = True
        self._editor_documents[key] = (editor, fresh[field+'_revision'])

    def take_editor(self, parent, index):
        owner = self.owner; row = owner.model.rows[index.row()]
        field = 'source' if index.column() == 0 else 'translation'
        saved = self._editor_documents.pop((owner.doc_id, row['id'], field), None)
        if saved:
            editor, revision = saved; fresh = owner.store.line(row['id'])
            editor._period_keep = False
            if revision == fresh[field+'_revision'] and editor.toPlainText() == (fresh[field] or ''):
                editor.setParent(parent)
                return editor
            editor.deleteLater()
        return None

    def update_highlight(self):
        owner = self.owner; owner.table.period_focus_key = self.focus_key; owner.table.viewport().update()
        delegate = owner.table.itemDelegate(); editor = delegate.active_editor; index = delegate.active_index
        if editor is not None and index is not None and index.isValid():
            row = owner.model.rows[index.row()]
            selected = self.focus_key == (owner.doc_id, row['id']) and index.column() == 1
            editor.setExtraSelections(period_selections(editor.document(), editor.toPlainText(), QTextEdit.ExtraSelection) if selected else [])

    def choose(self, key):
        self.navigate_key(key, self.dialog, require_period=True)

    def navigate_key(self, key, dialog, *, require_period=False):
        """Shared ID navigation for punctuation and structure review dialogs."""
        owner = self.owner
        if owner._closed or owner._exit_pending: return
        doc_id, line_id = key
        try: row = owner.store.line(line_id)
        except KeyError:
            self._signature = None; self.recount()
            if dialog is not self.dialog and hasattr(owner,'line_check'):owner.line_check.recount()
            return
        if doc_id not in owner.workspace_ids or row['document_id'] != doc_id or (require_period and '.' not in (row['translation'] or '')):
            self._signature = None; self.recount(); return
        delegate = owner.table.itemDelegate(); active = delegate.active_index
        same_editor = (owner.doc_id == doc_id and active is not None and active.isValid() and active.column() == 1 and
                       owner.model.rows[active.row()]['id'] == line_id)
        if not same_editor: self.remember_editor()
        if dialog is not None: dialog.hide()
        owner.pages.setCurrentIndex(0)
        if owner.doc_id != doc_id: owner.open_document(doc_id)
        self._navigation += 1; navigation = self._navigation
        def finish():
            if owner._closed or owner._exit_pending or navigation != self._navigation: return
            if owner.doc_id != doc_id or doc_id not in owner.workspace_ids: return
            try: fresh = owner.store.line(line_id)
            except KeyError: return
            if fresh['document_id'] != doc_id: return
            active = delegate.active_index
            same = (delegate.active_editor is not None and active is not None and active.isValid() and
                    active.column() == 1 and owner.model.rows[active.row()]['id'] == line_id)
            if not same and delegate.active_editor is not None:
                self.remember_editor()
                delegate.commitData.emit(delegate.active_editor); delegate.closeEditor.emit(delegate.active_editor)
            if line_id not in owner.model.id_index:
                owner.filter_combo.setCurrentIndex(0); owner.model.set_filter(None)
            owner.model.refresh([line_id]); position = owner.model.id_index.get(line_id)
            if position is None: return
            self.focus_key = key if require_period else None; index = owner.model.index(position, 1)
            if same:
                owner.table.selectionModel().select(index, QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Rows)
            else:
                owner.table.selectRow(position); owner.table.setCurrentIndex(index)
            owner.resize_visible_rows()
            owner.table.scrollTo(index, QAbstractItemView.PositionAtCenter)
            if same and delegate.active_editor is not None: delegate.active_editor.setFocus()
            else: owner.table.setFocus()
            self.update_highlight()
        QTimer.singleShot(0, finish)
