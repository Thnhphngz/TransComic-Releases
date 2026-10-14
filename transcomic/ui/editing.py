"""Compact manuscript search/replace with revision-safe grouped undo."""
import re
from PySide6.QtCore import Qt, QAbstractListModel, QModelIndex, QThread, Slot, QSignalBlocker
from shiboken6 import isValid
from pathlib import Path
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QComboBox, QPushButton, QLabel, QMessageBox, QSizePolicy, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QListView
from .controls import QComboBox
from .glass import GlassButton as QPushButton


def matches(rows, query, fields):
    if not query:
        return []
    pattern = re.compile(re.escape(query), re.I)
    return [(r["id"], field, m.start(), m.end()) for r in rows for field in fields for m in pattern.finditer(r[field] or "")]


class SearchResultModel(QAbstractListModel):
    """One owned model, immutable snapshots; no native item destruction in slots."""
    def __init__(self,parent):
        super().__init__(parent);self.rows=()
    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.rows)
    def data(self,index,role=Qt.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.rows):return None
        if role==Qt.DisplayRole:return self.rows[index.row()][0]
        if role==Qt.UserRole:return index.row()
        if role==Qt.UserRole+1:return self.rows[index.row()][1]
    def replace(self,rows):
        assert QThread.currentThread()==self.thread(),'Search model must stay on GUI thread'
        rows=tuple(rows)
        if rows==self.rows:return
        self.beginResetModel();self.rows=rows;self.endResetModel()

class SearchResultView(QListView):
    def __init__(self,parent):
        super().__init__(parent);self.snapshot=SearchResultModel(self);self.setModel(self.snapshot)
    def count(self):return self.snapshot.rowCount()

class SearchBar(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.results, self.current, self.undo_stack = [], -1, []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setMinimumWidth(30)
        self.query.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.query.setPlaceholderText("Tìm từ/cụm từ · không phân biệt hoa/thường")
        row.addWidget(self.query, 1)
        self.scope = QComboBox()
        self.scope.addItems(["Cả hai cột", "Chỉ nguồn", "Chỉ bản dịch"])
        row.addWidget(self.scope)
        self.count = QLabel("0/0")
        row.addWidget(self.count)
        for text, action in [("↑", lambda: self.navigate(-1)), ("↓", lambda: self.navigate(1)), ("Thay…", self.show_replace), ("×", self.close_bar)]:
            b = QPushButton(text)
            b.clicked.connect(action)
            row.addWidget(b)
        layout.addLayout(row)
        self.replace_row = QWidget()
        second = QHBoxLayout(self.replace_row)
        second.setContentsMargins(0, 0, 0, 0)
        self.replacement = QLineEdit()
        self.replacement.setMinimumWidth(30)
        self.replacement.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.replacement.setPlaceholderText("Thay bằng")
        second.addWidget(self.replacement, 1)
        self.replace_scope = QComboBox()
        self.replace_scope.addItems(["Bản dịch", "Nguồn"])
        second.addWidget(self.replace_scope)
        for text, action in [("Hiện tại", self.replace_current), ("Trong ô", self.replace_cell), ("Tất cả", self.replace_all), ("Hoàn tác", self.undo)]:
            b = QPushButton(text)
            b.clicked.connect(action)
            second.addWidget(b)
        layout.addWidget(self.replace_row)
        extended = QHBoxLayout()
        self.document_scope = QComboBox(); self.document_scope.addItems(['File đang mở', 'Tất cả file workspace', 'Các file được chọn'])
        from ..languages import LANGUAGES
        self.language_scope = QComboBox(); self.language_scope.addItem('Tất cả ngôn ngữ')
        for l in sorted(LANGUAGES,key=lambda l:({'en':0,'id':1,'vi':2}.get(l.locale,3))):self.language_scope.addItem(l.name,l.name)
        extended.addWidget(self.document_scope); extended.addWidget(self.language_scope)
        self.advanced_button = QPushButton('Phạm vi nhiều file…'); extended.addWidget(self.advanced_button); extended.addStretch()
        layout.addLayout(extended)
        self.advanced_panel = QWidget(); advanced = QVBoxLayout(self.advanced_panel); advanced.setContentsMargins(0,0,0,0)
        self.file_tools=QWidget();tools=QHBoxLayout(self.file_tools);tools.setContentsMargins(0,0,0,0)
        for text, action in [('Chọn mọi file',lambda:self.check_files(True)), ('Bỏ chọn',lambda:self.check_files(False))]:
            b=QPushButton(text); b.clicked.connect(action);tools.addWidget(b)
        tools.addStretch();advanced.addWidget(self.file_tools)
        self.listing_widget=QWidget();listing=QHBoxLayout(self.listing_widget);listing.setContentsMargins(0,0,0,0)
        self.file_checks=QListWidget();self.file_checks.setMaximumWidth(220)
        self.result_list=SearchResultView(self);listing.addWidget(self.file_checks);listing.addWidget(self.result_list,1);advanced.addWidget(self.listing_widget)
        self.preview=QTreeWidget();self.preview.setHeaderLabels(['File / dòng / cột', 'Trước → Sau']);advanced.addWidget(self.preview);self.preview.hide()
        self.confirm_replace=QPushButton('Xác nhận thay các mục đã chọn');self.confirm_replace.clicked.connect(self.confirm_preview);advanced.addWidget(self.confirm_replace);self.confirm_replace.hide()
        self.advanced_panel.setMaximumHeight(210);layout.addWidget(self.advanced_panel);self.advanced_panel.hide()
        self.selected_instances=set();self.result_metadata={};self.preview_changes=[];self._syncing_files=False
        self.file_checks.itemChanged.connect(self.file_checked)
        self.result_list.clicked.connect(self.result_clicked)
        self._rebuilding=False;self._rebuild_pending=False
        self.document_scope.currentIndexChanged.connect(self.change_document_scope)
        self.language_scope.currentIndexChanged.connect(self.rebuild)
        self.advanced_button.clicked.connect(lambda:self.advanced_panel.setVisible(self.advanced_panel.isHidden()))
        self.replace_row.hide()
        self.query.textChanged.connect(self.rebuild)
        self.query.returnPressed.connect(lambda: self.navigate(1))
        self.scope.currentIndexChanged.connect(self.rebuild)
        self.hide()

    def open(self, replace=False):
        self.show()
        self.replace_row.setVisible(replace)
        self.query.setFocus()

    def show_replace(self):
        self.replace_row.show()

    def close_bar(self):
        self.hide()
        self.window.table.search_ranges = {}
        self.window.table.viewport().update()

    @Slot(QModelIndex)
    def result_clicked(self,index):
        # Capture before navigation can reset the model and invalidate this index.
        key=index.data(Qt.UserRole+1)
        if key in self.results:self.select_result(self.results.index(key))

    @Slot()
    @Slot(str)
    @Slot(int)
    def rebuild(self, *_):
        if self.window._closed or self.window._exit_pending or not isValid(self):return
        assert QThread.currentThread()==self.thread(),'Search rebuild must stay on GUI thread'
        if self._rebuilding:
            self._rebuild_pending=True;return
        self._rebuilding=True
        try:
            while True:
                self._rebuild_pending=False;self._rebuild()
                if not self._rebuild_pending:break
        finally:self._rebuilding=False

    def _rebuild(self):
        previous = self.results[self.current] if 0 <= self.current < len(self.results) else None
        if not self.query.text():
            self.results=[];self.current=-1;self.result_metadata={};self.count.setText('0/0')
            self.window.table.search_ranges={};self.window.table.viewport().update();self.result_list.snapshot.replace(())
            if self.document_scope.currentIndex()!=0:self.sync_files()
            return
        fields = [("source", "translation"), ("source",), ("translation",)][self.scope.currentIndex()]
        self.sync_files()
        rows = self.scoped_rows()
        self.results = []
        self.result_metadata = {}
        for field in fields:
            selected = self.unique_sources(rows) if field=='source' else rows
            by_id={r['id']:r for r in selected}
            for result in matches(selected, self.query.text(), (field,)):
                self.results.append(result)
                self.result_metadata[result] = by_id[result[0]]
        self.current = self.results.index(previous) if previous in self.results else -1
        self.count.setText(f"{self.current+1}/{len(self.results)}")
        ranges = {}
        for line_id, field, start, end in self.results:
            ranges.setdefault((line_id, field), []).append((start, end))
        self.window.table.search_ranges = ranges if not self.isHidden() else {}
        self.window.table.viewport().update()
        listing=[]
        occurrences={}
        for result in self.results:occurrences[result[:2]]=occurrences.get(result[:2],0)+1
        for i, result in enumerate(self.results):
            row=self.result_metadata[result];doc=self.window.store.document(row['document_id']);field=result[1]
            listing.append((f"{Path(doc['path']).name} · {doc['target_lang'] if field=='translation' else 'Nguồn'} · dòng {row['ordinal']+1} · {occurrences[result[:2]]} khớp · {row[field] or ''}",result))
        self.result_list.snapshot.replace(listing)

    def navigate(self, step):
        self.rebuild()
        if not self.results:
            return
        self.current = ((0 if step > 0 else len(self.results)-1) if self.current < 0 else (self.current + step) % len(self.results))
        line_id, field, _, _ = self.results[self.current]
        row=self.result_metadata[self.results[self.current]]
        if row['document_id']!=self.window.doc_id:self.window.open_document(row['document_id'])
        self.window.navigate_to_line(line_id, 0 if field == "source" else 1)
        self.count.setText(f"{self.current+1}/{len(self.results)}")

    def apply(self, edits, expected=None):
        edits = [(line_id, field, value) for line_id, field, value in edits if not re.fullmatch(r"\s*\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}.*", self.window.store.line(line_id)["source"])]
        if any("\n" in value or "\r" in value for _, _, value in edits):
            QMessageBox.information(self, "Không thể thay thế", "Không được thêm dòng logic.")
            return
        if not edits:
            return
        delegate = self.window.table.itemDelegate()
        if delegate.active_editor is not None:
            delegate.commitData.emit(delegate.active_editor)
            delegate.closeEditor.emit(delegate.active_editor)
        edits=self.expand_sources(edits)
        try: before = self.window.store.replace_edits(edits, expected=expected)
        except ValueError:
            self.window.notice.setText('Nội dung thay đổi trong lúc xem trước. Kiểm tra và xác nhận lại.')
            self.window.statusBar().showMessage(self.window.notice.text(),8000);self.rebuild();return
        self.undo_stack.append([(line_id, field, old, new, self.window.store.line(line_id)[field+"_revision"]) for line_id, field, old, new in before])
        self.window.refresh([r[0] for r in edits])
        self.rebuild()

    def replace_current(self):
        if not 0 <= self.current < len(self.results):
            return
        line_id, field, start, end = self.results[self.current]
        if field != self.field:
            self.window.notice.setText("Kết quả hiện tại nằm ngoài cột thay thế đã chọn.")
            return
        text = self.window.store.line(line_id)[field] or ""
        # Recheck the occurrence after any intervening edit/API result.
        if text[start:end].casefold() != self.query.text().casefold():
            self.rebuild()
            return
        self.apply([(line_id, field, text[:start]+self.replacement.text()+text[end:])])

    @property
    def field(self):
        return "translation" if self.replace_scope.currentIndex() == 0 else "source"

    def plan(self, rows):
        if not self.query.text():
            return [], 0
        pattern = re.compile(re.escape(self.query.text()), re.I)
        edits, count = [], 0
        for r in rows:
            if re.fullmatch(r"\s*\d{2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[,.]\d{3}.*", r["source"]):
                continue
            value, n = pattern.subn(lambda _: self.replacement.text(), r[self.field] or "")
            if n:
                edits.append((r["id"], self.field, value))
                count += n
        return edits, count

    def replace_all(self):
        rows=self.scoped_rows()
        if self.field=='source':rows=self.unique_sources(rows)
        edits, count = self.plan(rows)
        if self.document_scope.currentIndex()!=0:
            self.show_preview(edits,count);return
        expected = {(line_id,field):self.window.store.line(line_id)[field+'_revision'] for line_id,field,_ in self.expand_sources(edits)}
        if edits and QMessageBox.question(self, "Xem trước thay thế", f"Thay {count} lần trong {len(edits)} dòng của cột {self.replace_scope.currentText()}?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            if any(self.window.store.line(line_id)[field+"_revision"] != revision for (line_id,field), revision in expected.items()):
                self.window.notice.setText("Nội dung thay đổi trong lúc xem trước. Kiểm tra kết quả rồi xác nhận lại.")
                self.rebuild()
                return
            self.apply(edits,expected=expected)

    def replace_cell(self):
        delegate = self.window.table.itemDelegate()
        index = delegate.active_index if delegate.active_editor is not None else self.window.table.currentIndex()
        if index is None or not index.isValid() or index.column() != (1 if self.field == "translation" else 0):
            self.window.notice.setText("Chọn ô thuộc cột thay thế.")
            return
        edits, _ = self.plan([self.window.model.rows[index.row()]])
        self.apply(edits)

    def undo(self):
        if not self.undo_stack:
            return
        group = self.undo_stack[-1]
        if any(self.window.store.line(line_id)[field+"_revision"] != revision for line_id, field, old, new, revision in group):
            QMessageBox.information(self, "Không thể hoàn tác", "Nội dung đã thay đổi sau lần thay thế; giữ phiên bản mới.")
            return
        self.undo_stack.pop()
        try:
            self.window.store.replace_edits([(line_id, field, old) for line_id, field, old, new, revision in group], expected={(line_id,field):revision for line_id,field,old,new,revision in group})
        except ValueError:
            self.undo_stack.append(group)
            self.window.statusBar().showMessage('Nội dung đã thay đổi; giữ phiên bản mới.',8000)
            return
        # A second undo may follow the first while still rejecting unrelated edits.
        restored = {(line_id, field): old for line_id, field, old, new, revision in group}
        for i, earlier in enumerate(self.undo_stack):
            self.undo_stack[i] = [(line_id, field, old, new, self.window.store.line(line_id)[field+"_revision"] if restored.get((line_id, field)) == new else revision) for line_id, field, old, new, revision in earlier]
        self.window.refresh([r[0] for r in group])
        self.rebuild()

    def sync_files(self):
        if not hasattr(self.window,'workspace_ids'):return
        groups={}
        for doc_id in self.window.workspace_ids:
            doc=self.window.store.document(doc_id);groups.setdefault(doc['source_instance'],doc)
        existing={self.file_checks.item(i).data(Qt.UserRole) for i in range(self.file_checks.count())}
        if existing==set(groups):return
        blocker=QSignalBlocker(self.file_checks)
        self._syncing_files=True;self.file_checks.clear()
        self.selected_instances.intersection_update(groups)
        for instance,doc in groups.items():
            item=QListWidgetItem(Path(doc['path']).name);item.setToolTip(doc['path']);item.setData(Qt.UserRole,instance)
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked if instance in self.selected_instances else Qt.Unchecked);self.file_checks.addItem(item)
        self._syncing_files=False

    def file_checked(self,item):
        if self._syncing_files:return
        instance=item.data(Qt.UserRole)
        if item.checkState()==Qt.Checked:self.selected_instances.add(instance)
        else:self.selected_instances.discard(instance)
        self.rebuild()

    def check_files(self,checked):
        self._syncing_files=True
        for i in range(self.file_checks.count()):self.file_checks.item(i).setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self.selected_instances={self.file_checks.item(i).data(Qt.UserRole) for i in range(self.file_checks.count())} if checked else set()
        self._syncing_files=False;self.rebuild()

    def change_document_scope(self,*_):
        self.advanced_panel.setVisible(self.document_scope.currentIndex()!=0);self.rebuild()

    def scoped_rows(self):
        if self.document_scope.currentIndex()==0:
            if not self.window.doc_id:return []
            current=self.window.store.document(self.window.doc_id);language=self.language_scope.currentData()
            ids=[d for d in self.window.workspace_ids if self.window.store.document(d)['source_instance']==current['source_instance']]
            if not ids:ids=[self.window.doc_id]
            return [r for d in ids if not language or self.window.store.document(d)['target_lang']==language for r in self.window.store.lines(d)]
        selected=[];language=self.language_scope.currentData()
        for doc_id in self.window.workspace_ids:
            doc=self.window.store.document(doc_id)
            if self.document_scope.currentIndex()==2 and doc['source_instance'] not in self.selected_instances:continue
            if language and doc['target_lang']!=language:continue
            selected.extend(self.window.store.lines(doc_id))
        return selected

    def unique_sources(self,rows):
        seen=set();unique=[];instances={}
        for row in rows:
            if row['document_id'] not in instances:instances[row['document_id']]=self.window.store.document(row['document_id'])['source_instance']
            key=(instances[row['document_id']],row['ordinal'])
            if key not in seen:seen.add(key);unique.append(row)
        return unique

    def expand_sources(self,edits):
        expanded={}
        for line_id,field,value in edits:
            expanded[(line_id,field)]=value
            if field!='source':continue
            row=self.window.store.line(line_id);doc=self.window.store.document(row['document_id'])
            for doc_id in self.window.workspace_ids:
                other=self.window.store.document(doc_id)
                if other['source_instance']==doc['source_instance']:
                    sibling=next((r for r in self.window.store.lines(doc_id) if r['ordinal']==row['ordinal']),None)
                    if sibling:expanded[(sibling['id'],field)]=value
        return [(line_id,field,value) for (line_id,field),value in expanded.items()]

    def select_result(self,index):
        if not isinstance(index,int) or not 0<=index<len(self.results):return
        self.current=index;result=self.results[index];row=self.result_metadata[result]
        if self.window.doc_id!=row['document_id']:self.window.open_document(row['document_id'])
        self.window.navigate_to_line(result[0],0 if result[1]=='source' else 1)
        self.count.setText(f'{self.current+1}/{len(self.results)}')

    def show_preview(self,edits,count):
        self.advanced_panel.show();self.preview.clear();self.preview_changes=[];parents={}
        for line_id,field,new in edits:
            row=self.window.store.line(line_id);doc=self.window.store.document(row['document_id']);instance=doc['source_instance']
            if instance not in parents:
                parent=QTreeWidgetItem([Path(doc['path']).name,'']);parent.setFlags(parent.flags()|Qt.ItemIsUserCheckable|Qt.ItemIsAutoTristate);self.preview.addTopLevelItem(parent);parents[instance]=parent
            item=QTreeWidgetItem(parents[instance],[f"{doc['target_lang'] if field=='translation' else 'Nguồn'} · {row['ordinal']+1} · {field}",(row[field] or '')+' → '+new])
            item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(0,Qt.Checked)
            expanded=self.expand_sources([(line_id,field,new)])
            expected={(i,f):self.window.store.line(i)[f+'_revision'] for i,f,_ in expanded}
            self.preview_changes.append((item,expanded,expected))
        self.preview.expandAll();self.preview.show();self.confirm_replace.setVisible(bool(edits))
        self.listing_widget.hide();self.file_tools.hide()
        self.preview.setColumnWidth(0,250)
        self.confirm_replace.setText(f'Xác nhận · {len(parents)} file · {len(edits)} dòng · {count} vị trí · cột {self.replace_scope.currentText()}')

    def confirm_preview(self):
        edits=[];expected={}
        for item,changes,revisions in self.preview_changes:
            if item.checkState(0)==Qt.Checked:edits.extend(changes);expected.update(revisions)
        self.apply(edits,expected=expected)
        self.preview.hide();self.confirm_replace.hide();self.listing_widget.show();self.file_tools.show()
