"""Workspace navigation and view state. These actions never start translation."""
from pathlib import Path
import json
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter,
    QPushButton, QLabel, QComboBox, QMessageBox, QFormLayout, QSizePolicy, QDoubleSpinBox, QScrollArea)
from .documents_panel import DocumentsPanel, DropTargetFilter, local_drop_paths
from .exit_dialog import app_icon
from ..bulk import workspace_status, LANG_CODES
from .controls import QComboBox, QDoubleSpinBox
from .glass import GlassButton as QPushButton, IconGlassButton
from ..languages import language


class WorkspaceV2Mixin:
    def retry_workspace_errors(self):
        from ..workspace_retry import retry_plan, WorkspaceRetryScheduler
        if self.scheduler and self.scheduler._thread and self.scheduler._thread.is_alive(): return
        try: plan = retry_plan(self.store, self.workspace_ids)
        except ValueError as exc:
            QMessageBox.information(self, 'Không thể dịch lại', str(exc)); return
        if not plan:
            QMessageBox.information(self, 'Dịch lại tất cả lỗi', 'Workspace không còn dòng lỗi'); return
        language_counts = {}; instances = set(); summaries = []
        for group in plan:
            j = group['original']; n = len(group['line_ids'])
            language_counts[j['target_lang']] = language_counts.get(j['target_lang'], 0)+n
            instances.add(self.store.document(j['document_id'])['source_instance'])
            summaries.append(f"{j['provider']}/{j['model']} · {j['concurrency']} luồng · {(n+2)//3} batch")
        batches = sum((len(g['line_ids'])+2)//3 for g in plan)
        message = f"{len(instances)} file · {sum(language_counts.values())} dòng lỗi · tổng {batches} batch dự kiến\n"+'\n'.join(f'{lang}: {n} dòng' for lang, n in language_counts.items())+'\n'+'\n'.join(summaries)+'\nRequest mới và retry có thể phát sinh token/chi phí. Giữ bản cũ khi lỗi; chỉnh sửa mới được ưu tiên. Không đổi provider/model. Xác nhận?'
        if QMessageBox.question(self, 'Dịch lại tất cả lỗi', message, QMessageBox.Yes|QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        kira_key = self._key() if any(g['original']['provider']=='kira' for g in plan) else None
        if any(g['original']['provider']=='kira' for g in plan) and not kira_key: return
        groups = {}; adapters = {}
        runs = {}
        try:
            with self.store.transaction():
                for g in plan:
                    j = g['original']
                    scope = (j['provider'], j['model'], j['concurrency'], j['config'])
                    if scope not in runs:
                        import uuid
                        runs[scope] = str(uuid.uuid4())
                        self.store.db.execute('INSERT INTO translation_runs(id,config) VALUES (?,?)', (runs[scope], j['config']))
                    new = self.store.create_job(j['document_id'], j['model'], j['source_lang'], j['target_lang'], j['concurrency'], g['line_ids'], j['timeout'], provider=j['provider'], config=json.loads(j['config']), allow_shared_document=True, run_id=runs[scope])
                    frozen = self.store.job(new); adapters[new] = self.make_provider(frozen, kira_key)
                    scope = (frozen['provider'], frozen['model'], frozen['concurrency'], frozen['prompt_version'], frozen['config'])
                    groups.setdefault(scope, []).append(new)
            self.scheduler = WorkspaceRetryScheduler(self.store, list(groups.values()), adapters, self.bridge.changed.emit)
            self.current_job_ids = {i for g in plan for i in g['line_ids']}
            self.scheduler.start(); self.refresh()
        except (ValueError, KeyError) as exc: QMessageBox.information(self, 'Không thể dịch lại', str(exc))

    def save_concurrency(self, value):
        if not hasattr(self, 'provider_selector') or self.provider_id() == 'kira':
            self.store.set_setting('concurrency', str(value))

    @staticmethod
    def navigation_items():
        return [('✦  Dịch', 0), ('▤  Hàng đợi', 5), ('◷  Lịch sử', 1),
                ('◆  API', 2), ('⌘  Console', 4), ('⚙  Cài đặt', 3)]

    def setup_v2(self):
        self.workspace_selections = {}; self.workspace_editor_states = {}; self.import_errors = []
        self.view_target = self.target_lang.currentText()
        self.editor_page = self.pages.widget(0)
        self.pages.removeWidget(self.editor_page)
        wrapper = QWidget(); outer = QVBoxLayout(wrapper); outer.setContentsMargins(0, 0, 0, 0)
        self.document_splitter = QSplitter(Qt.Horizontal)
        self.document_panel = DocumentsPanel(self)
        self.document_splitter.addWidget(self.document_panel); self.document_splitter.addWidget(self.editor_page)
        self.editor_page.show()
        self.document_splitter.setChildrenCollapsible(False)
        self.document_splitter.setStretchFactor(1, 1); self.document_splitter.setSizes([260, 980])
        self.document_splitter.splitterMoved.connect(lambda *_: self.adapt_v2_toolbar())
        outer.addWidget(self.document_splitter); self.pages.insertWidget(0, wrapper); self.pages.setCurrentIndex(0)
        self.editor_page.layout().setContentsMargins(6, 6, 6, 6)
        self.editor_page.layout().setSpacing(3)
        self.setup_grid.setContentsMargins(10, 6, 10, 6); self.setup_grid.setSpacing(3)
        self.editor_title.setStyleSheet('QLabel { font-size: 22px; font-weight: 700; }')
        self.stats_label.parentWidget().layout().setContentsMargins(10, 4, 10, 4)
        self.filename.setToolTip(self.filename.text())
        # Move file commands to their own visible row; leave room for filename/title.
        header = self.editor_page.layout().itemAt(0).layout()
        header.removeWidget(self.import_button); header.removeWidget(self.export_button)
        file_actions = QGridLayout(); self.file_actions = file_actions; self.editor_page.layout().insertLayout(1, file_actions)
        self.document_expand = IconGlassButton('▤'); self.document_expand.setToolTip('Mở panel tài liệu')
        self.document_expand.clicked.connect(self.toggle_documents_panel); self.document_expand.hide()
        folder = QPushButton('Nhập thư mục'); folder.clicked.connect(self.choose_folder)
        self.file_action_buttons = [self.document_expand, self.import_button, folder, self.export_button, self.export_many_button, self.folder_button]
        self.file_action_labels = [b.text() for b in self.file_action_buttons]
        for b in self.file_action_buttons: b.setToolTip(b.text())
        footer = self.editor_page.layout().itemAt(self.editor_page.layout().count()-1).layout()
        footer.removeWidget(self.folder_button)
        self.folder_button.setEnabled(False); self.notice.hide()
        # Technical configuration lives in Settings, outside the everyday toolbar.
        self.setup_grid.removeWidget(self.advanced_panel); self.advanced_panel.hide()
        technical = QWidget(); form = QFormLayout(technical)
        form.addRow('Timeout request mới', self.timeout_spin); form.addRow('Cỡ chữ bản thảo', self.font_spin)
        shutdown = QDoubleSpinBox(); shutdown.setRange(.1, 60); shutdown.setDecimals(1)
        shutdown.setValue(float(self.store.setting('shutdown_grace_seconds', '3')))
        def set_shutdown(value):
            self.shutdown_grace_seconds = value
            self.store.set_setting('shutdown_grace_seconds', str(value))
        shutdown.valueChanged.connect(set_shutdown)
        form.addRow('Thoát an toàn: chờ HTTP tối đa (giây)', shutdown)
        form.addRow(self.retry_504_check)
        self.auto_retry_combo = QComboBox(); self.auto_retry_combo.addItems(['Tắt', '1 lần', '2 lần', '3 lần', '4 lần', '5 lần'])
        self.auto_retry_combo.setCurrentIndex(int(self.store.setting('auto_retries', '5')))
        self.auto_retry_combo.currentIndexChanged.connect(lambda n: self.store.set_setting('auto_retries', str(n)))
        form.addRow('Tự động dịch lại lỗi (lượt mới)', self.auto_retry_combo)
        retry_notice = QLabel('Tối đa 5 lần thử lại sau lần đầu (6 request/batch). Retry, đặc biệt HTTP 504, có thể tiêu thụ thêm token và tiền. Không gửi lại timeout hoặc attempt mất trạng thái sau crash.')
        retry_notice.setWordWrap(True); form.addRow(retry_notice)
        for key, label, default, maximum in [('rate_wait_budget', 'Tổng thời gian chờ 429 tối đa (giây)', 300, 3600), ('rate_cooldown_limit', 'Số đợt cooldown tối đa', 10, 100), ('rate_backoff_max', 'Backoff 429 tối đa (giây)', 30, 300)]:
            box = QDoubleSpinBox(); box.setRange(1, maximum); box.setDecimals(0)
            box.setValue(float(self.store.setting(key, str(default))))
            box.valueChanged.connect(lambda value, k=key: self.store.set_setting(k, str(value)))
            form.addRow(label, box)
        self.request_interval = QDoubleSpinBox(); self.request_interval.setRange(0, 60); self.request_interval.setDecimals(2)
        self.request_interval.setValue(float(self.store.setting('request_interval', '0')))
        self.request_interval.setToolTip('Nhịp gửi do người dùng cấu hình, không phải hạn mức chính thức của API')
        self.request_interval.valueChanged.connect(lambda n: self.store.set_setting('request_interval', str(n)))
        form.addRow('Khoảng cách gửi request (giây)', self.request_interval)
        self.pages.widget(3).layout().insertWidget(2, technical)
        # The legacy target control stays as a configuration API for existing flows,
        # while the visible controls clearly separate batch targets from the view.
        self.controls_widget.hide(); self.setup_grid.removeWidget(self.controls_widget)
        self.v2_controls = QWidget(); self.v2_controls.setObjectName('toolbarControls'); self.v2_controls_grid = QGridLayout(self.v2_controls)
        self.v2_controls_grid.setContentsMargins(0, 0, 0, 0)
        self.control_columns = []
        for label, control in [('Nguồn', self.source_lang), ('Provider', self.provider_selector),
                               ('Mô hình', self.model_name), ('Luồng', self.concurrency)]:
            column = QWidget(); column.setObjectName('toolbarControls'); v = QVBoxLayout(column); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(3)
            caption = QLabel(label); caption.setObjectName('muted'); v.addWidget(caption); v.addWidget(control)
            control.setMinimumWidth(0); control.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            self.control_columns.append(column)
        self.setup_grid.addWidget(self.v2_controls, 0, 0, 1, 2)
        self.target_lang.hide()
        self.provider_selector.setMinimumWidth(100)
        self.provider_selector.setMaximumHeight(36)
        language_row = QWidget(); self.language_row = language_row
        language_row.setObjectName('toolbarControls')
        lang = QHBoxLayout(language_row); lang.setContentsMargins(0, 0, 0, 0)
        lang.addWidget(QLabel('Đích lượt dịch:'))
        self.target_chips = {}
        self._target_order=[]
        selected=set()
        from ..languages import LANGUAGES
        scroll=QScrollArea();scroll.setObjectName('chipScroll');scroll.setWidgetResizable(True);scroll.setFixedHeight(42)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        chips_widget=QWidget();chips_widget.setObjectName('toolbarControls')
        chips_layout=QHBoxLayout(chips_widget);chips_layout.setContentsMargins(0,0,0,0)
        for name in [l.name for l in LANGUAGES]:
            chip = QPushButton(LANG_CODES[name]); chip.setCheckable(True); chip.setChecked(name in selected)
            chip.setObjectName('languageChip');chip.setToolTip(name)
            chip.toggled.connect(lambda checked,n=name:self.save_target_chips(n,checked))
            self.target_chips[name] = chip; chips_layout.addWidget(chip)
        scroll.setWidget(chips_widget);lang.addWidget(scroll,1)
        lang.addStretch(); lang.addWidget(QLabel('Đang xem:'))
        self.view_language = QComboBox(); self.view_language.setMinimumWidth(155)
        self.view_language.currentTextChanged.connect(self.change_view_language); lang.addWidget(self.view_language)
        self.setup_grid.addWidget(language_row, 1, 0, 1, 2)
        self.source_lang.currentIndexChanged.connect(self.update_target_chips)
        self.target_lang.currentIndexChanged.connect(self.sync_target_chips)
        self.update_target_chips()
        for button in (self.start_button, self.pause_button, self.stop_button, self.import_button,
                       folder, self.export_button, self.export_many_button):
            button.setStyleSheet('padding: 7px 9px;')
        self.import_details = QPushButton('Chi tiết nhập…')
        self.import_details.clicked.connect(self.show_import_details); self.import_details.hide()
        footer = self.editor_page.layout().itemAt(self.editor_page.layout().count()-1).layout()
        footer.insertWidget(1, self.import_details)
        for label in (self.notice, self.stats_label):
            label.setMinimumWidth(0); label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.active_label.setMinimumWidth(140); self.active_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.active_label.setWordWrap(False)
        self.active_label.setMaximumWidth(260)
        self.retry_errors_button.setText('Dịch lại dòng lỗi')
        self.retry_workspace_button = QPushButton('Dịch lại tất cả lỗi')
        self.retry_workspace_button.clicked.connect(self.retry_workspace_errors)
        table_layout = self.table.parentWidget().layout()
        old_heading = table_layout.itemAt(0).layout(); self.heading_controls = []
        while old_heading.count():
            item = old_heading.takeAt(0)
            if item.widget(): self.heading_controls.append(item.widget())
        self.heading_controls.append(self.retry_workspace_button)
        self.heading_controls[0].setStyleSheet('font-size: 16px; font-weight: 700;')
        self.retry_errors_button.setToolTip('Dịch lại lỗi của file/ngôn ngữ đang xem')
        self.retry_workspace_button.setToolTip('Dịch lại tất cả lỗi của mọi file/ngôn ngữ trong workspace')
        table_layout.removeItem(old_heading)
        self.heading_grid = QGridLayout(); table_layout.insertLayout(0, self.heading_grid)
        for control in self.editor_page.findChildren(QPushButton):
            control.setStyleSheet('QPushButton { font-size: 13px; padding: 4px 8px; }')
            control.ensurePolished()
            control.setMinimumWidth(0)
            control.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.filter_combo.setMinimumWidth(120); self.filter_combo.setMaximumWidth(145)
        self.filter_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        table_layout = self.table.parentWidget().layout()
        old_tools = table_layout.itemAt(1).layout(); self.selection_controls = []
        while old_tools.count():
            item = old_tools.takeAt(0)
            if item.widget(): self.selection_controls.append(item.widget())
        table_layout.removeItem(old_tools)
        selection_widget = QWidget(); selection_widget.setObjectName('toolbarControls')
        self.selection_grid = QGridLayout(selection_widget); self.selection_grid.setContentsMargins(0, 0, 0, 0); self.selection_grid.setSpacing(3)
        table_layout.insertWidget(1, selection_widget)
        self.sidebar.layout().removeWidget(self.brand_label)
        brand = QWidget(); brand.setObjectName('toolbarControls'); brand_row = QHBoxLayout(brand); brand_row.setContentsMargins(0, 0, 0, 0); brand_row.setSpacing(6)
        self.brand_icon = QLabel(); brand_row.addWidget(self.brand_icon)
        self.brand_label.setStyleSheet('font-size: 18px; font-weight: 700;'); brand_row.addWidget(self.brand_label, 1)
        self.sidebar.layout().insertWidget(0, brand)
        self.brand_caption.setText('TRANSLATION STUDIO')
        self.update_branding(); self.adapt_v2_toolbar(); self.refresh_document_panel()
        self.drop_target_filter = DropTargetFilter(self)
        for target in (self.editor_page, self.table.viewport()):
            target.setAcceptDrops(True); target.installEventFilter(self.drop_target_filter)
        from .layout_state import install
        install(self)

    def adapt_v2_toolbar(self):
        if self._closed:return
        panel_width = self.document_splitter.sizes()[0] if not self.document_panel.isHidden() else 0
        available = self.width()-self.sidebar.width()-panel_width-5
        cols = 4 if available >= 520 else 2
        mode = (cols, available >= 640, available >= 780, available >= 460)
        if getattr(self, '_v2_layout_mode', None) == mode:
            self.resize_visible_rows(); return
        self._v2_layout_mode = mode
        for i, control in enumerate(self.file_action_buttons):
            control.setText(self.file_action_labels[i] if available >= 780 else ['▤', 'Nhập file', 'Nhập thư mục', 'Xuất file', 'Xuất hàng loạt', 'Thư mục xuất'][i])
            self.file_actions.removeWidget(control)
            self.file_actions.addWidget(control, 0 if available >= 460 or i < 3 else 1, i if available >= 460 else i%3)
        self.retry_errors_button.setText('Dịch lại dòng lỗi' if available >= 780 else 'Lỗi file này')
        self.retry_workspace_button.setText('Dịch lại tất cả lỗi' if available >= 780 else 'Lỗi mọi file')
        for i, control in enumerate(self.heading_controls):
            self.heading_grid.removeWidget(control)
            self.heading_grid.addWidget(control, 0 if available >= 460 or i < 2 else 1, i if available >= 460 else i%2)
        for i, column in enumerate(self.control_columns):
            self.v2_controls_grid.addWidget(column, i//cols, i%cols)
        for i, stretch in enumerate([2, 1, 3, 1] if cols == 4 else [1, 1, 0, 0]):
            self.v2_controls_grid.setColumnStretch(i, stretch)
        if hasattr(self, 'selection_grid'):
            for i, control in enumerate(self.selection_controls):
                self.selection_grid.removeWidget(control)
                if available >= 640: self.selection_grid.addWidget(control, 0, i)
                elif i < 3: self.selection_grid.addWidget(control, 0, i)
                else: self.selection_grid.addWidget(control, 1, 0 if i == 3 else 2, 1, 2 if i == 3 else 1)
        self.setup_grid.removeWidget(self.actions_widget)
        self.setup_grid.addWidget(self.actions_widget, 2, 0, 1, 2)
        self.v2_controls_grid.activate(); self.setup_grid.activate(); self.editor_page.layout().activate()
        self.resize_visible_rows()

    def update_branding(self):
        if self._closed:return
        compact = self.sidebar.width() < 100
        icon = app_icon(self.dark)
        self.setWindowIcon(icon)
        from PySide6.QtWidgets import QApplication
        QApplication.instance().setWindowIcon(icon)
        self.brand_icon.setPixmap(icon.pixmap(34, 34)); self.brand_label.setVisible(not compact)
        self.brand_label.setText('TransComic')
        self.brand_label.setToolTip('TransComic · Translation Studio')
        from PySide6.QtGui import QIcon
        for control, (title, _), asset in zip(self.nav_buttons, self.navigation_items(), ['translate', 'queue', 'history', 'key', 'console', 'settings']):
            control.setCheckable(True); control.setChecked(self.pages.currentIndex() == _)
            control.setToolTip(title[2:].strip()); control.setText('' if compact else title[2:].strip())
            control.setIcon(QIcon(str(Path(__file__).parent/'assets'/f'nav-{asset}.svg'))); control.setIconSize(QSize(19, 19))
        if self.tray: self.tray.setIcon(icon)
        self.table.viewport().update(); self.document_panel.view.viewport().update()

    def toggle_documents_panel(self):
        visible = not self.document_panel.isHidden()
        if visible: self._document_width = self.document_splitter.sizes()[0]
        self.document_panel.setVisible(not visible); self.document_expand.setVisible(visible)
        if not visible:
            width = getattr(self, '_document_width', 260)
            self.document_splitter.setSizes([width, max(1, self.document_splitter.width()-width)])
        from .layout_state import schedule
        schedule(self)
        QTimer.singleShot(0, self.adapt_v2_toolbar)

    def update_target_chips(self, *_):
        source = self.source_lang.currentText()
        for name, chip in self.target_chips.items():
            chip.blockSignals(True); chip.setEnabled(name != source)
            if name == source: chip.setChecked(False)
            chip.blockSignals(False)
        self.save_target_chips()

    def sync_target_chips(self, *_):
        # Also support existing callers that set target_lang directly.
        selected = set([self.target_lang.currentText()]+self.extra_targets)
        for name, chip in self.target_chips.items():
            chip.blockSignals(True); chip.setChecked(name in selected and chip.isEnabled()); chip.blockSignals(False)
        self._target_order=[n for n in [self.target_lang.currentText()]+self.extra_targets if n in self.target_chips and self.target_chips[n].isEnabled()]
        self.save_target_chips()

    def save_target_chips(self, *_):
        if _ and isinstance(_[0],str):
            name=_[0]
            self._target_order=[n for n in self._target_order if n!=name]
            if len(_)>1 and _[1]:self._target_order.append(name)
        selected=[name for name,chip in self.target_chips.items() if chip.isChecked() and chip.isEnabled()]
        self._target_order=[n for n in self._target_order if n in selected]+[n for n in selected if n not in self._target_order]
        targets=self._target_order
        for n,chip in self.target_chips.items():chip.setText((str(targets.index(n)+1)+' ' if n in targets else '')+LANG_CODES[n])
        self.target_lang.blockSignals(True)
        if targets: self.target_lang.setCurrentText(targets[0])
        self.target_lang.blockSignals(False)
        self.extra_targets = targets[1:]
        if targets: self.save_languages()
        if hasattr(self, 'start_button'):
            running=bool(self.scheduler and self.scheduler._thread and self.scheduler._thread.is_alive())
            self.start_button.setEnabled(bool(self.doc_id) and bool(targets) and not running)

    def sync_view_language(self):
        doc = self.store.document(self.doc_id) if self.doc_id else None
        self.view_language.blockSignals(True); self.view_language.clear()
        if doc:
            names = list(dict.fromkeys(self.store.document(d)['target_lang'] for d in self.workspace_ids
                         if self.store.document(d)['source_instance'] == doc['source_instance']))
            for name in names: self.view_language.addItem(language(name).name, name)
            self.view_language.setCurrentIndex(self.view_language.findData(doc['target_lang']))
            self.view_target = doc['target_lang']
        self.view_language.blockSignals(False)

    def change_view_language(self, name):
        if not self.doc_id or not name: return
        instance = self.store.document(self.doc_id)['source_instance']
        for d in self.workspace_ids:
            doc = self.store.document(d)
            if doc['source_instance'] == instance and language(doc['target_lang']).name == name:
                if d != self.doc_id: self.open_document(d)
                return

    def open_document_group(self, item):
        if not item: return
        ids = [d for d in item['ids'] if d in self.workspace_ids]
        if not ids: return
        preferred = next((d for d in ids if self.store.document(d)['target_lang'] == self.view_target), ids[0])
        if preferred != self.doc_id: self.open_document(preferred)

    def save_document_editor_state(self):
        index = self.table.currentIndex(); delegate = self.table.itemDelegate()
        if delegate.active_editor is not None: index = delegate.active_index
        if not index.isValid() or index.row() >= len(self.model.rows): return
        cursor = delegate.active_editor.textCursor() if delegate.active_editor is not None else None
        self.workspace_editor_states[self.doc_id] = {
            'id': self.model.rows[index.row()]['id'], 'column': index.column(),
            'cursor': cursor.position() if cursor else None,
            'horizontal': self.table.horizontalScrollBar().value()}

    def restore_document_editor_state(self, doc_id, position):
        if self._closed:return
        if self.doc_id != doc_id or self._closed: return
        state = self.workspace_editor_states.get(doc_id)
        if state and state['id'] in self.model.id_index:
            index = self.model.index(self.model.id_index[state['id']], state['column'])
            self.table.setCurrentIndex(index)
            if state['cursor'] is not None:
                self.table.edit(index)
                editor = self.table.itemDelegate().active_editor
                if editor:
                    cursor = editor.textCursor(); cursor.setPosition(min(state['cursor'], len(editor.toPlainText())))
                    editor.setTextCursor(cursor)
            self.table.horizontalScrollBar().setValue(state['horizontal'])
        self.table.verticalScrollBar().setValue(position)

    def refresh_document_panel(self, *_):
        if not hasattr(self, 'document_panel') or self._closed: return
        documents = {d['id']: d for d in self.store.documents()}
        self.workspace_ids = [d for d in self.workspace_ids if d in documents]
        groups = {}
        states = {}
        if self.scheduler:
            for j in self.scheduler.job_ids or [self.scheduler.job_id]:
                if j:
                    job = self.store.job(j)
                    if job: states[job['document_id']] = job['state']
        for d in self.workspace_ids:
            doc = documents[d]; groups.setdefault(doc['source_instance'], []).append(doc)
        items = []; query = self.document_panel.search.text().casefold()
        for instance, docs in groups.items():
            first = docs[0]; name = Path(first['path']).name
            if query not in name.casefold(): continue
            statuses = [(d, workspace_status(self.store.lines(d['id']), states.get(d['id']))) for d in docs]
            viewed, status = next(((d, s) for d, s in statuses if d['id'] == self.doc_id),
                                 next(((d, s) for d, s in statuses if d['target_lang'] == self.view_target), statuses[0]))
            details = ' · '.join(f"{LANG_CODES.get(language(d['target_lang']).name, d['target_lang'])} {s['done']}/{s['total']} !{s['errors']+s['unknown']}" for d, s in statuses)
            items.append({'instance': instance, 'ids': [d['id'] for d in docs], 'name': name,
                          'path': first['path'], 'format': first['format'].upper(), 'details': details,
                          'progress': status['progress'], 'summary': f"{LANG_CODES.get(language(viewed['target_lang']).name, '')} {status['progress']}% · {status['state']}"})
        self.document_panel.model.update_items(items)
        self.document_panel.title.setText(f'TÀI LIỆU · {len(groups)}')
        self.document_panel.view.viewport().update()
        if hasattr(self, 'view_language') and self.doc_id in documents:
            current = documents[self.doc_id]
            names = list(dict.fromkeys(d['target_lang'] for d in groups.get(current['source_instance'], [])))
            if names != [self.view_language.itemData(i) for i in range(self.view_language.count())]:
                self.sync_view_language()
        for label in (self.stats_label, self.active_label, self.notice): label.setToolTip(label.text())

    def remove_all_workspace(self):
        instances = {self.store.document(d)['source_instance'] for d in self.workspace_ids}
        if not instances: return
        if QMessageBox.question(self, 'Bỏ tất cả file', f'Bỏ {len(instances)} file khỏi workspace? Nguồn, bản xuất, lịch sử, API key và cài đặt được giữ. Job đang chạy tiếp tục lưu vào lịch sử.', QMessageBox.Yes|QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        self.remove_workspace_instances(instances, confirmed=True)

    def remove_workspace_instances(self, instances, *, confirmed=False):
        ids = [d for d in self.workspace_ids if self.store.document(d)['source_instance'] in instances]
        if not ids: return
        active = bool(self.scheduler and self.scheduler._thread and self.scheduler._thread.is_alive() and any(self.store.job(j)['document_id'] in ids for j in self.scheduler.job_ids or [self.scheduler.job_id] if j))
        translated = any(any(r.get('translation') for r in self.store.lines(d)) for d in ids)
        if (active or translated) and not confirmed:
            note = 'Job đang chạy sẽ tiếp tục trong Hàng đợi. ' if active else ''
            if QMessageBox.question(self, 'Bỏ file khỏi workspace', note+'Bản dịch và lịch sử vẫn được lưu. Bỏ các file đã chọn?', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes: return
        delegate = self.table.itemDelegate()
        if delegate.active_editor is not None:
            delegate.commitData.emit(delegate.active_editor); delegate.closeEditor.emit(delegate.active_editor)
        self.workspace_ids = [d for d in self.workspace_ids if d not in ids]
        self.document_panel.model.checked.difference_update(instances)
        if self.doc_id in ids:
            if self.workspace_ids: self.open_document(self.workspace_ids[0])
            else:
                self.doc_id = None; self.model.load(None); self.filename.setText('Nhập TXT hoặc DOCX để bắt đầu'); self.sync_view_language()
        self.refresh_document_panel(); self.refresh()

    def dragEnterEvent(self, event):
        if local_drop_paths(event.mimeData()):
            event.acceptProposedAction()
            if hasattr(self, 'document_panel'):
                self.document_panel.drop_hint.setText('Thả để thêm tài liệu')
                if getattr(self, '_drop_previous_filename', None) is None:
                    self._drop_previous_filename = self.filename.text()
                self.filename.setText('Thả để thêm tài liệu')
                self.document_panel.setProperty('dropActive', True)
                self.document_panel.style().unpolish(self.document_panel); self.document_panel.style().polish(self.document_panel)
        else: event.ignore()

    def dragMoveEvent(self, event): self.dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self.clear_drop_highlight(); event.accept()

    def clear_drop_highlight(self):
        self.document_panel.drop_hint.setText('Kéo file hoặc thư mục vào đây')
        self.document_panel.setProperty('dropActive', False)
        self.document_panel.style().unpolish(self.document_panel); self.document_panel.style().polish(self.document_panel)
        if getattr(self, '_drop_previous_filename', None) is not None:
            self.filename.setText(self._drop_previous_filename); self._drop_previous_filename = None

    def dropEvent(self, event):
        paths = local_drop_paths(event.mimeData())
        self.clear_drop_highlight()
        if paths: self.import_paths(paths); event.acceptProposedAction()
        else: event.ignore()

    def show_import_details(self):
        message = QMessageBox(self); message.setWindowTitle('Kết quả nhập tài liệu')
        message.setText(f'{len(self.import_errors)} file/thư mục chưa nhập được')
        message.setDetailedText('\n'.join(str(e.get('path', ''))+': '+e['error'] for e in self.import_errors))
        retry = message.addButton('Nhập riêng / chọn bảng mã…', QMessageBox.ActionRole)
        message.exec()
        if message.clickedButton() == retry: self.import_file()
