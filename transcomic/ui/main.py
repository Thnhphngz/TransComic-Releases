"""Desktop workspace for TXT and DOCX editing, translation and export."""
from __future__ import annotations

import time
import json
import hashlib
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QFileDialog, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSpinBox, QStackedWidget, QDialog, QPlainTextEdit,
    QSizePolicy, QTableView, QVBoxLayout, QWidget, QMenu, QSystemTrayIcon, QCheckBox, QButtonGroup,
)
from .controls import QComboBox, QSpinBox
from .glass import GlassButton as QPushButton, SkySwitch, install_glass_skin

from ..documents import EncodingChoiceRequired, ImportedText, TextLine, atomic_export, import_txt, render_export, translatable
from ..docx_document import UnsafeDocx, import_docx, render_docx
from ..models import KIRA_MODELS
from ..providers import KiraProvider
from ..security import protect_key, unprotect_key
from ..storage import Store
from ..translation import Scheduler
from .model import CHECK_COLUMN, LABELS, LineDelegate, LineModel, ManuscriptTable
from .theme import stylesheet
from .exit_dialog import ExitDialog, app_icon
from .window_state import save_window_state
from .editing import SearchBar
from .console import ConsolePage
from .stage2 import Stage2Mixin
from .workspace_v2 import WorkspaceV2Mixin
from ..status import usable


class Bridge(QObject):
    changed = Signal(list)
    stage2 = Signal(object)


def button(label: str, primary=False) -> QPushButton:
    control = QPushButton(label)
    if primary:
        control.setObjectName("primary")
    control.setCursor(Qt.PointingHandCursor)
    return control


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 18, 20, 18)
    layout.setSpacing(12)
    return frame, layout


class MainWindow(WorkspaceV2Mixin, Stage2Mixin, QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.setAttribute(Qt.WA_DeleteOnClose,True)
        self.store = store
        self.bridge = Bridge()
        self.pending_changed_ids = set()
        self.refresh_timer = QTimer(self); self.refresh_timer.setSingleShot(True); self.refresh_timer.setInterval(40)
        self.refresh_timer.timeout.connect(self.flush_api_updates)
        self.bridge.changed.connect(self.queue_api_updates,Qt.QueuedConnection)
        self.scheduler: Scheduler | None = None
        self.current_job_ids: set[str] = set()
        self.doc_id: str | None = None
        self.last_export: Path | None = None
        self._exit_authorized = False
        self._exit_pending = False
        self._closed = False
        self.shutdown_grace_seconds = max(.1, min(60, float(store.setting('shutdown_grace_seconds', '3'))))
        self.tray = None
        self.exit_timer = QTimer(self)
        self.exit_timer.setInterval(10)
        self.exit_timer.timeout.connect(self.finish_safe_exit)
        self.dark = store.setting("dark", "0") == "1"
        self.glass_skin = install_glass_skin(self)
        self.setWindowTitle("TransComic · Dịch truyện bằng AI")
        self.setWindowIcon(app_icon())
        quit_action = QAction("Thoát…", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)
        self.resize(1440, 900)
        self.setMinimumSize(900, 580)
        self.setStyleSheet(stylesheet(self.dark))
        shell = QWidget()
        self.setCentralWidget(shell)
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(200)
        nav = QVBoxLayout(self.sidebar)
        nav.setContentsMargins(16, 22, 16, 18)
        nav.setSpacing(9)
        brand = QLabel("◈  TransComic")
        self.brand_label = brand
        brand.setObjectName("title")
        brand.setStyleSheet("font-size: 21px")
        nav.addWidget(brand)
        caption = QLabel("STUDIO · GIAI ĐOẠN 2")
        self.brand_caption = caption
        caption.setObjectName("muted")
        nav.addWidget(caption)
        nav.addSpacing(22)
        self.nav_buttons = []
        self.navigation_group = QButtonGroup(self)
        self.navigation_group.setExclusive(True)
        for title, index in self.navigation_items():
            control = button(title)
            control.setCheckable(True); self.navigation_group.addButton(control,index)
            control.setMinimumHeight(46)
            control.clicked.connect(lambda _=False, i=index: self.pages.setCurrentIndex(i))
            nav.addWidget(control)
            self.nav_buttons.append(control)
        nav.addStretch()
        self.collapse_button = button("‹  Thu gọn")
        self.collapse_button.clicked.connect(self.toggle_sidebar)
        nav.addWidget(self.collapse_button)
        self.sky_switch = SkySwitch(self.dark, self.sidebar)
        self.sky_switch.clicked.connect(self.toggle_theme)
        nav.addWidget(self.sky_switch, alignment=Qt.AlignHCenter)
        root.addWidget(self.sidebar)
        self.pages = QStackedWidget()
        self.pages.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        root.addWidget(self.pages, 1)
        self.pages.addWidget(self.build_editor())
        self.pages.addWidget(self.build_queue())
        self.pages.addWidget(self.build_api())
        self.pages.addWidget(self.build_settings())
        self.console = ConsolePage(self)
        self.pages.addWidget(self.console)
        self.pages.currentChanged.connect(lambda _: self.refresh())
        self.pages.setCurrentIndex(0)
        self.setup_stage2()
        self.setup_v2()
        srt_page=QWidget();srt_layout=QVBoxLayout(srt_page)
        srt_layout.addStretch()
        for text in ('Dịch file SRT','Chức năng đang được cập nhật','Tính năng dịch phụ đề SRT sẽ được bổ sung trong phiên bản tiếp theo.'):
            label=QLabel(text);label.setAlignment(Qt.AlignCenter);label.setWordWrap(True)
            label.setObjectName('section' if text=='Dịch file SRT' else 'muted');srt_layout.addWidget(label)
        srt_layout.addStretch();self.pages.addWidget(srt_page)
        self.pages.currentChanged.connect(lambda _: self.update_branding())
        self.change_font(self.font_spin.value())
        for shortcut, replace in [("Ctrl+F", False), ("Ctrl+H", True)]:
            action = QAction(self)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda _=False, r=replace: self.search.open(r))
            self.addAction(action)
        if self.model_name.currentIndex() < 0:
            self.notice.setText("Model đã lưu không còn trong danh sách. Hãy chọn model hợp lệ trước khi dịch.")
        self.refresh()

        # Install after the existing V3/technical settings composition is finished.
        from .update_panel import UpdatePanel
        from PySide6.QtWidgets import QScrollArea
        settings_page=self.pages.widget(3)
        self.update_panel=UpdatePanel(self)
        settings_page.layout().insertWidget(2,self.update_panel)
        self.pages.removeWidget(settings_page)
        settings_scroll=QScrollArea();settings_scroll.setWidgetResizable(True)
        settings_scroll.setFrameShape(QScrollArea.NoFrame);settings_scroll.setWidget(settings_page)
        self.pages.insertWidget(3,settings_scroll)
        self.pages.setCurrentIndex(0)

    def toggle_sidebar(self):
        compact = self.sidebar.width() > 100
        self.sidebar.setFixedWidth(72 if compact else 200)
        self.sidebar.layout().setContentsMargins(5 if compact else 16, 22, 5 if compact else 16, 18)
        self.brand_label.setText("◈" if compact else "◈  TransComic")
        self.brand_caption.setVisible(not compact)
        self.collapse_button.setText("›" if compact else "‹  Thu gọn")
        for control, (title, _) in zip(self.nav_buttons, self.navigation_items()):
            control.setText(title[:1] if compact else title)
        if hasattr(self, "brand_icon"): self.update_branding()
        from .layout_state import schedule
        schedule(self)
        QTimer.singleShot(0, self.adapt_editor_toolbar)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "setup_grid") and hasattr(self, "pages"):
            if self.width() < 1100 and self.sidebar.width() > 100:
                self.toggle_sidebar()
            self.adapt_editor_toolbar()
            QTimer.singleShot(0, self.adapt_editor_toolbar)
            QTimer.singleShot(0, self.resize_visible_rows)

    def adapt_editor_toolbar(self):
        if getattr(self,'_closed',False):return
        if hasattr(self, "v2_controls_grid"):
            self.adapt_v2_toolbar(); return
        wide = False
        if getattr(self, "_wide_toolbar", None) == wide:
            return
        self.setup_grid.removeWidget(self.actions_widget)
        if wide:
            self.setup_grid.addWidget(self.actions_widget, 0, 1)
        else:
            self.setup_grid.addWidget(self.actions_widget, 1, 0, 1, 2)
        self.setup_grid.invalidate()
        self.setup_grid.activate()
        self.controls_widget.parentWidget().updateGeometry()
        self.pages.widget(0).layout().invalidate()
        self.pages.widget(0).layout().activate()
        self._wide_toolbar = wide
        QTimer.singleShot(0, self.resize_visible_rows)

    def build_editor(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 14, 20, 12)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        text = QHBoxLayout()
        text.setSpacing(14)
        title = QLabel("Dịch văn bản")
        self.editor_title = title
        title.setObjectName("title")
        text.addWidget(title)
        self.filename = QLabel("Nhập TXT hoặc DOCX để bắt đầu")
        self.filename.setObjectName("muted")
        self.filename.setMinimumWidth(0)
        self.filename.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text.addWidget(self.filename, 1)
        heading.addLayout(text, 1)
        self.import_button = button("＋  Nhập tài liệu", True)
        self.import_button.clicked.connect(self.import_file)
        heading.addWidget(self.import_button)
        self.export_button = button("⇩  Xuất tài liệu")
        self.export_button.clicked.connect(self.export_file)
        heading.addWidget(self.export_button)
        layout.addLayout(heading)
        setup_card = QFrame()
        setup_card.setObjectName("card")
        setup = QGridLayout(setup_card)
        setup.setContentsMargins(14, 8, 14, 8)
        setup.setSpacing(5)
        self.setup_grid = setup
        self.controls_widget = QWidget()
        self.controls_widget.setObjectName("toolbarControls")
        controls = QHBoxLayout(self.controls_widget)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        self.source_lang = QComboBox()
        self.source_lang.setEditable(False)
        from ..languages import LANGUAGES
        languages = [(l.locale,l.name) for l in LANGUAGES]
        for code, name in languages:
            self.source_lang.addItem(name, code)
        self.target_lang = QComboBox()
        self.target_lang.setEditable(False)
        for code in ('en','id','vi')+tuple(l.locale for l in LANGUAGES if l.locale not in ('en','id','vi')):
            self.target_lang.addItem(dict(languages)[code], code)
        self.model_name = QComboBox()
        self.model_name.setEditable(False)
        for display, model_id in KIRA_MODELS:
            self.model_name.addItem(display, model_id)
        self.set_model_id(self.store.setting("kira_model", "kira-2.5-flash"))
        self.model_name.currentIndexChanged.connect(lambda _: self.save_model_choice())
        for widget, key, default in [(self.source_lang, "source_language", "Tiếng Việt"), (self.target_lang, "target_language", "Tiếng Anh")]:
            saved = self.store.setting(key, default)
            code_index = widget.findData(self.store.setting(key+"_id"))
            widget.setCurrentIndex(code_index if code_index >= 0 else max(0, widget.findText(saved)))
            widget.currentIndexChanged.connect(self.save_languages)
        self.concurrency = QSpinBox()
        self.concurrency.setProperty('allowWheel', True)
        self.concurrency.setRange(1, 50)
        self.concurrency.setValue(int(self.store.setting("concurrency", "30")))
        self.concurrency.valueChanged.connect(self.save_concurrency)
        for control in (self.source_lang, self.target_lang, self.model_name, self.concurrency):
            control.setMaximumHeight(36)
        for label, widget in [("Nguồn", self.source_lang), ("Đích", self.target_lang), ("Mô hình Kira", self.model_name), ("Luồng", self.concurrency)]:
            column = QVBoxLayout()
            caption = QLabel(label)
            if label == 'Mô hình Kira': self.model_caption = caption
            caption.setObjectName("muted")
            column.addWidget(caption)
            column.addWidget(widget)
            controls.addLayout(column, 2 if label == "Mô hình Kira" else 1)
        setup.addWidget(self.controls_widget, 0, 0)
        self.actions_widget = QWidget()
        self.actions_widget.setObjectName("toolbarActions")
        actions = QHBoxLayout(self.actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        self.start_button = button("▶  Bắt đầu dịch", True)
        self.start_button.clicked.connect(self.start_translation)
        actions.addWidget(self.start_button)
        self.pause_button = button("Ⅱ  Tạm dừng")
        self.pause_button.clicked.connect(self.pause_or_resume)
        actions.addWidget(self.pause_button)
        self.stop_button = button("■  Dừng")
        self.stop_button.setObjectName('danger')
        self.stop_button.clicked.connect(self.stop_translation)
        actions.addWidget(self.stop_button)
        actions.addStretch()
        for control in (self.start_button, self.pause_button, self.stop_button):
            control.setMaximumHeight(36)
        setup.addWidget(self.actions_widget, 1, 0, 1, 2)
        self.advanced_panel = QWidget()
        self.advanced_panel.setObjectName("advancedPanel")
        advanced = QHBoxLayout(self.advanced_panel)
        advanced.setContentsMargins(0, 2, 0, 0)
        self.retry_button = button("↻  Dịch lại dòng đã chọn (0)")
        self.retry_button.clicked.connect(self.retry_selected)
        advanced.addStretch()
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(30, 300)
        self.timeout_spin.setValue(int(self.store.setting("request_timeout", "90")))
        self.timeout_spin.setSuffix(" s")
        self.timeout_spin.valueChanged.connect(lambda value: self.store.set_setting("request_timeout", str(value)))
        self.timeout_spin.setToolTip("Read timeout của lượt dịch mới. HTTP 504 là lỗi gateway, không được sửa chỉ bằng tăng timeout.")
        advanced.addWidget(QLabel("Timeout"))
        advanced.addWidget(self.timeout_spin)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(12, 22)
        self.font_spin.setValue(int(self.store.setting("font_size", "14")))
        self.font_spin.setSuffix(" px")
        self.font_spin.valueChanged.connect(self.change_font)
        advanced.addWidget(QLabel("Cỡ chữ"))
        advanced.addWidget(self.font_spin)
        self.retry_504_check = QCheckBox("Tự thử lại HTTP 504 theo giới hạn retry · có thể tốn thêm token/tiền")
        self.retry_504_check.setChecked(self.store.setting("retry_504", "1") == "1")
        self.retry_504_check.setToolTip("Bật mặc định. Request 504 trước có thể đã tiêu thụ token; các lần thử lại có thể phát sinh chi phí. Chỉ áp dụng lượt mới, không retry timeout/crash.")
        self.retry_504_check.toggled.connect(lambda checked: self.store.set_setting("retry_504", "1" if checked else "0"))
        advanced.addWidget(self.retry_504_check)
        self.advanced_panel.hide()
        setup.addWidget(self.advanced_panel, 2, 0, 1, 2)
        layout.addWidget(setup_card)
        progress_card, progress = card()
        progress.setContentsMargins(14, 8, 14, 8)
        progress.setSpacing(4)
        stats = QHBoxLayout()
        self.stats_label = QLabel("0 dòng cần dịch · 0 hoàn tất · 0 đang xử lý · 0 lỗi")
        stats.addWidget(self.stats_label, 1)
        self.active_label = QLabel("0 luồng hoạt động")
        self.active_label.setObjectName("muted")
        stats.addWidget(self.active_label)
        progress.addLayout(stats)
        self.total_progress = QProgressBar()
        self.total_progress.setTextVisible(True)
        self.file_progress = QProgressBar()
        self.file_progress.setTextVisible(True)
        bars = QHBoxLayout()
        bars.addWidget(QLabel("Lượt"))
        bars.addWidget(self.total_progress, 1)
        bars.addWidget(QLabel("Tài liệu"))
        bars.addWidget(self.file_progress, 1)
        progress.addLayout(bars)
        layout.addWidget(progress_card)
        table_card, table_layout = card()
        table_layout.setContentsMargins(10, 8, 10, 8)
        table_layout.setSpacing(5)
        table_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        table_heading = QHBoxLayout()
        table_heading.addWidget(self.section("BẢN THẢO SONG SONG"))
        table_heading.addStretch()
        self.warning_button = button("Cần kiểm tra: 0 dòng")
        self.warning_button.clicked.connect(self.show_warnings)
        table_heading.addWidget(self.warning_button)
        self.retry_errors_button = button("Dịch lại tất cả dòng lỗi")
        self.retry_errors_button.clicked.connect(self.retry_all_errors)
        table_heading.addWidget(self.retry_errors_button)
        self.edit_hint = QLabel("Nhấp ô để sửa · Tự lưu · Enter/Shift+Enter chuyển dòng")
        self.edit_hint.setMinimumWidth(0)
        self.edit_hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.edit_hint.setToolTip(self.edit_hint.text())
        self.edit_hint.hide()
        table_layout.addLayout(table_heading)
        self.model = LineModel(self.store, self)
        selection_tools = QHBoxLayout()
        self.selection_count = QLabel("Đã chọn 0 dòng")
        self.selection_count.setFixedWidth(96)
        selection_tools.addWidget(self.selection_count)
        self.filter_combo = QComboBox()
        for name, states in [("Tất cả dòng", None), ("Chưa dịch", "untranslated"), ("Cần xem lại", "review"), ("Đã dịch", "translated"), ("Lỗi API", "api_errors"), ("Sai ngôn ngữ đích", "wrong_target_language"), ("Không rõ kết quả", "unknown"), ("Đã sửa", "edited"), ("Nguồn đã đổi", "stale")]:
            self.filter_combo.addItem(name, states)
        self.filter_combo.currentIndexChanged.connect(lambda _: self.model.set_filter(self.filter_combo.currentData()))
        selection_tools.addWidget(self.filter_combo)
        selection_tools.addStretch()
        find = button("Tìm / Thay")
        find.setToolTip('Tìm / Thay thế · Ctrl+F / Ctrl+H')
        find.clicked.connect(lambda: self.search.open())
        selection_tools.addWidget(find)
        selection_tools.addWidget(self.retry_button)
        clear = button("Bỏ chọn")
        clear.clicked.connect(self.model.clear_checked)
        selection_tools.addWidget(clear)
        table_layout.addLayout(selection_tools)
        self.search = SearchBar(self)
        table_layout.addWidget(self.search)
        self.table = ManuscriptTable()
        self.table.setToolTip(self.edit_hint.text())
        self.table.setModel(self.model)
        table_font = self.table.font()
        table_font.setPixelSize(self.font_spin.value())
        self.table.setFont(table_font)
        self.table.setStyleSheet(f"QTableView {{ font-size: {self.font_spin.value()}px; }}")
        self.model.selectionChanged.connect(self.update_selection_count)
        self.model.dataChanged.connect(lambda *_: self.resize_visible_rows())
        self.local_timer = QTimer(self)
        self.local_timer.setSingleShot(True)
        self.local_timer.setInterval(150)
        self.local_timer.timeout.connect(self.update_editorial)
        self.model.dataChanged.connect(lambda *_: self.local_timer.start())
        self.table.setItemDelegate(LineDelegate(self.table))
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(CHECK_COLUMN, QHeaderView.Fixed)
        header.resizeSection(CHECK_COLUMN, 38)
        header.moveSection(header.visualIndex(CHECK_COLUMN), 0)
        self.table.enable_column_resize()
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.model.modelReset.connect(self.update_row_gutter)
        self.table.verticalHeader().setObjectName("rowHeader")
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.verticalScrollBar().valueChanged.connect(self.resize_visible_rows)
        self.table.horizontalHeader().sectionResized.connect(lambda *_: self.resize_visible_rows())
        table_layout.addWidget(self.table, 1)
        layout.addWidget(table_card, 1)
        footer = QHBoxLayout()
        self.notice = QLabel("Chỉnh sửa tự lưu nội bộ. Tệp đầu ra chỉ được tạo khi bạn bấm Xuất tài liệu.")
        self.notice.setObjectName("muted")
        footer.addWidget(self.notice, 1)
        self.folder_button = button("Mở thư mục xuất")
        self.folder_button.clicked.connect(self.open_export_folder)
        footer.addWidget(self.folder_button)
        layout.addLayout(footer)
        return page

    def update_selection_count(self):
        visible = len(self.model.selected_rows())
        hidden = len(self.model.selected_ids) - visible
        self.selection_count.setText(f"Đã chọn {visible} dòng")
        self.selection_count.setToolTip(f"Đã chọn {visible} dòng đang hiển thị; {hidden} dòng ẩn không thao tác.")
        self.table.horizontalHeader().viewport().update()
        eligible = sum(translatable(r["source"]) and r["state"] != "processing" for r in self.model.selected_rows())
        self.retry_button.setText(f"↻  Dịch lại chọn ({eligible})")
        self.retry_button.setToolTip('Dịch lại các dòng đã chọn')
        running = bool(self.scheduler and self.scheduler._thread and self.scheduler._thread.is_alive())
        from .notifications import notify_scheduler
        notify_scheduler(self)
        self.retry_button.setEnabled(eligible > 0 and not running)

    def copy_selected(self, kind):
        rows = self.model.selected_rows()
        if not rows:
            self.notice.setText("Chọn checkbox của các dòng cần sao chép.")
            return
        if kind == "pairs":
            text = "\n".join(r["source"] + "\t" + (r["translation"] or "") for r in rows)
        else:
            text = "\n".join(r[kind] or "" for r in rows)
        QApplication.clipboard().setText(text)
        self.notice.setText(f"Đã sao chép {len(rows)} dòng đang hiển thị.")

    def section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("section")
        return label

    def selected_model_id(self) -> str:
        index = self.model_name.currentIndex()
        if index >= 0 and self.model_name.currentText() == self.model_name.itemText(index):
            return str(self.model_name.itemData(index))
        return ""

    def set_model_id(self, model_id: str):
        index = self.model_name.findData(model_id)
        if index >= 0:
            self.model_name.setCurrentIndex(index)
        else:
            self.model_name.setCurrentIndex(-1)
            self.model_name.setPlaceholderText("Model không khả dụng — chọn lại")

    def save_languages(self, *_):
        for key, widget in [("source_language", self.source_lang), ("target_language", self.target_lang)]:
            if widget.currentIndex() >= 0:
                self.store.set_setting(key, widget.currentText())
                self.store.set_setting(key+"_id", widget.currentData())
        if self.source_lang.currentData() != self.target_lang.currentData():
            from ..languages import language
            targets=[language(t).locale for t in self.target_languages()] if hasattr(self,'extra_targets') else [self.target_lang.currentData()]
            self.store.set_setting("translation_language_profile", json.dumps({"source": self.source_lang.currentData(), "targets": targets}))

    def valid_languages(self):
        if self.source_lang.currentText() == self.target_lang.currentText():
            QMessageBox.information(self, "Chọn ngôn ngữ", "Ngôn ngữ nguồn và đích không được trùng nhau.")
            return False
        return self.source_lang.currentIndex() >= 0 and self.target_lang.currentIndex() >= 0

    def navigate_to_line(self, line_id, column=1):
        delegate = self.table.itemDelegate()
        if delegate.active_editor is not None:
            delegate.commitData.emit(delegate.active_editor)
            delegate.closeEditor.emit(delegate.active_editor)
        if line_id not in self.model.id_index:
            self.filter_combo.setCurrentIndex(0)
        row = self.model.id_index.get(line_id)
        if row is not None:
            index = self.model.index(row, column)
            self.table.setCurrentIndex(index)
            self.table.scrollTo(index, QAbstractItemView.PositionAtCenter)
            self.resize_visible_rows()
            self.table.viewport().update()

    def update_editorial(self):
        if self._closed or self._exit_pending:
            return
        self.editorial_rows = self.store.warning_rows(self.doc_id) if self.doc_id else []
        states = {r['id']:r['state'] for r in self.store.lines(self.doc_id)} if self.doc_id else {}
        changed=[r['id'] for r in self.model.all_rows if states.get(r['id'])!=r['state']] if self.doc_id else []
        if changed: self.model.refresh(changed)
        wrong=sum(r['state']=='wrong_target_language' for r in self.editorial_rows)
        self.warning_button.setText(f"Cần kiểm tra: {len(self.editorial_rows)}" + (f" · {wrong} sai ngôn ngữ" if wrong else ''))
        self.warning_button.setEnabled(bool(self.editorial_rows))
        if self.doc_id:
            from ..quality import language_evidence
            doc=self.store.document(self.doc_id)
            evidence=[language_evidence(r['source'],r.get('translation') or '',doc['source_lang'],doc['target_lang'])[0] for r in self.model.all_rows if r.get('translation')]
            self.warning_button.setToolTip(f"Kiểm tra ngôn ngữ cục bộ: {evidence.count('suspected')} nghi vấn · {evidence.count('insufficient')} không đủ bằng chứng. Không bảo đảm ngữ nghĩa; locale gần nhau cần người đọc kiểm tra.")
        self.search.rebuild()
        self.update_selection_count()
        self.dirty_export = bool(self.doc_id and any(r["source_revision"] or r["translation_revision"] for r in self.model.all_rows)
                                 and self.export_revision() != self.store.setting("export_revision_"+self.doc_id))
        compact = hasattr(self, '_v2_layout_mode') and not self._v2_layout_mode[2]
        self.export_button.setText(('Xuất file' if compact else '⇩  Xuất tài liệu') + (' •' if self.dirty_export else ''))
        self.export_button.setToolTip("Có thay đổi chưa xuất" if self.dirty_export else "Xuất tài liệu")

    def export_revision(self):
        revisions = [(r["id"], r["source_revision"], r["translation_revision"], r["state"]) for r in self.model.all_rows]
        return hashlib.sha256(json.dumps(revisions).encode()).hexdigest()

    def show_warnings(self):
        self.update_editorial()
        dialog = QDialog(self)
        dialog.setWindowTitle("Các dòng cần kiểm tra · cảnh báo không tự sửa")
        layout = QVBoxLayout(dialog)
        listing = QListWidget()
        for row in self.editorial_rows:
            listing.addItem(f"Dòng {row['ordinal']+1} · {LABELS.get(row['state'], row['state'])}\n" + " · ".join(f"{kind}: {summary}" for kind, summary in row["warnings"]))
            listing.item(listing.count()-1).setData(Qt.UserRole, row["id"])
            original=self.store.line(row["id"])
            listing.item(listing.count()-1).setToolTip("Nguồn: "+original["source"]+"\nBản dịch: "+(original["translation"] or ""))
        layout.addWidget(listing)
        retry=button("Dịch lại các dòng sai ngôn ngữ")
        wrong_ids={r["id"] for r in self.editorial_rows if r["state"]=="wrong_target_language"}
        retry.setEnabled(bool(wrong_ids))
        def request_retry():
            dialog.accept()
            self.filter_combo.setCurrentIndex(0)
            self.model.selected_ids=wrong_ids
            self.model.selectionChanged.emit()
            self.retry_selected()
        retry.clicked.connect(request_retry)
        layout.addWidget(retry)
        listing.itemClicked.connect(lambda item: (self.navigate_to_line(item.data(Qt.UserRole)), dialog.accept()))
        dialog.resize(min(800, self.width()-40), min(500, self.height()-60))
        dialog.exec()

    def save_model_choice(self):
        model_id = self.selected_model_id()
        if model_id:
            self.store.set_setting('gemini_model' if self.provider_id() == 'gemini' else 'kira_model', model_id)

    def build_queue(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addWidget(self.heading("Hàng đợi & lịch sử", "Các lượt dịch được lưu bền vững trong SQLite."))
        queue_card, queue = card()
        queue.addWidget(self.section("LƯỢT DỊCH"))
        self.job_list = QListWidget()
        queue.addWidget(self.job_list, 1)
        row = QHBoxLayout()
        self.resume_job_button = button("▶  Tiếp tục batch chưa gửi", True)
        self.resume_job_button.clicked.connect(self.resume_job)
        row.addWidget(self.resume_job_button)
        details = button("Chẩn đoán batch")
        details.clicked.connect(self.show_batch_diagnostics)
        row.addWidget(details)
        remove = button("Xóa mục hiện tại")
        remove.clicked.connect(lambda: self.delete_history(False))
        row.addWidget(remove)
        remove_many = button("Xóa các mục đã chọn")
        remove_many.clicked.connect(lambda: self.delete_history(True))
        row.addWidget(remove_many)
        self.clear_all_jobs_button=button('Xóa toàn bộ')
        self.clear_all_jobs_button.clicked.connect(self.clear_all_queue)
        # A second row keeps deletion actions visible on narrow windows.
        delete_row=QHBoxLayout()
        row.removeWidget(remove);row.removeWidget(remove_many)
        delete_row.addWidget(remove);delete_row.addWidget(remove_many)
        delete_row.addWidget(self.clear_all_jobs_button);delete_row.addStretch()
        self.clear_all_jobs_button.setEnabled(False)
        queue.addLayout(row)
        queue.addLayout(delete_row)
        layout.addWidget(queue_card, 1)
        self.job_list.itemDoubleClicked.connect(lambda _: self.show_job_document())
        return page

    def confirm_clear_all(self,count):
        from .queue_clear import ClearDialog
        return ClearDialog(self,count).exec()==QDialog.Accepted

    def clear_all_queue(self):
        from .queue_clear import clear_all
        clear_all(self)

    def delete_history(self, checked=True):
        if getattr(self,'queue_clear_busy',False):return
        if getattr(self, 'export_busy', False) or getattr(self, 'import_busy', False):
            QMessageBox.information(self, 'Đang xử lý tài liệu', 'Chờ nhập/xuất hoàn tất trước khi xóa lịch sử.'); return
        entries = [self.job_list.item(i).data(Qt.UserRole) for i in range(self.job_list.count()) if self.job_list.item(i).checkState() == Qt.Checked] if checked else [self.job_list.currentItem().data(Qt.UserRole)] if self.job_list.currentItem() else []
        if not entries:
            return
        if QMessageBox.question(self, "Xóa lịch sử", f"Xóa {len(entries)} mục lịch sử và dữ liệu nội bộ liên quan? Không xóa file nguồn, file xuất, key hoặc cấu hình. Snapshot còn được lượt khác dùng sẽ được giữ.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        try:
            self.store.delete_history(entries)
        except (ValueError, KeyError) as exc:
            QMessageBox.information(self, "Không thể xóa", str(exc))
            return
        if self.scheduler and self.scheduler.job_id in entries:
            self.scheduler = None
            self.current_job_ids.clear()
        if self.doc_id and not any(d["id"] == self.doc_id for d in self.store.documents()):
            delegate = self.table.itemDelegate()
            if delegate.active_editor is not None:
                # The deleted document cannot receive a deferred editor commit.
                delegate.active_editor._dirty = False
                delegate.closeEditor.emit(delegate.active_editor)
            self.doc_id = None
            self.model.load(None)
            self.filename.setText("Nhập TXT hoặc DOCX để bắt đầu")
            self.scheduler = None
            self.current_job_ids.clear()
            self.last_export = None
        self.refresh()

    def build_api(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addWidget(self.heading("Quản lý API", "Khóa Kira được mã hóa bằng Windows DPAPI theo tài khoản Windows hiện tại."))
        api_card, content = card()
        content.addWidget(self.section("KẾT NỐI KIRA AI"))
        self.key_status = QLabel()
        content.addWidget(self.key_status)
        form = QFormLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setPlaceholderText("Dán API key mới; khóa đã lưu không được hiện lại")
        form.addRow("API key", self.api_key_input)
        content.addLayout(form)
        save = button("Lưu khóa an toàn", True)
        save.clicked.connect(self.save_api_key)
        content.addWidget(save, alignment=Qt.AlignLeft)
        detail = QLabel("Endpoint: https://kiraai.vn/api/v1/chat/completions\nModel mặc định: kira-2.5-flash\nKiểm tra kết nối sử dụng một request thật và có thể tốn token, nên ứng dụng không tự gửi request thử.")
        detail.setWordWrap(True)
        detail.setObjectName("muted")
        content.addWidget(detail)
        layout.addWidget(api_card)
        layout.addStretch()
        return page

    def build_settings(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.addWidget(self.heading("Cài đặt", "Điều chỉnh không gian làm việc."))
        settings_card, content = card()
        content.addWidget(self.section("GIAO DIỆN"))
        reset_window = button("Khôi phục cách mở cửa sổ theo màn hình")
        reset_window.clicked.connect(self.reset_window_preferences)
        content.addWidget(reset_window, alignment=Qt.AlignLeft)
        note = QLabel("Lần mở đầu: dưới 21 inch mở maximized; từ 21 inch mở cửa sổ ở giữa màn hình. Khi không đọc được EDID đáng tin cậy, dùng maximized. Kích thước và trạng thái khi bạn thoát được ghi nhớ.")
        note.setWordWrap(True)
        content.addWidget(note)
        layout.addWidget(settings_card)
        layout.addStretch()
        return page

    def heading(self, title: str, subtitle: str) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 12)
        title_label = QLabel(title)
        title_label.setObjectName("title")
        layout.addWidget(title_label)
        sub = QLabel(subtitle)
        sub.setObjectName("muted")
        layout.addWidget(sub)
        return widget

    def open_document(self, doc_id: str):
        if self.doc_id != doc_id and hasattr(self, 'workspace_positions'):
            if self.doc_id:
                self.workspace_positions[self.doc_id] = self.table.verticalScrollBar().value()
                self.workspace_selections[self.doc_id] = set(self.model.selected_ids)
                self.save_document_editor_state()
            delegate = self.table.itemDelegate()
            if delegate.active_editor is not None:
                delegate.commitData.emit(delegate.active_editor)
                delegate.closeEditor.emit(delegate.active_editor)
        doc = self.store.document(doc_id)
        self.doc_id = doc_id
        self.store.validate_document_language(doc_id)
        self.model.load(doc_id)
        if hasattr(self, "workspace_selections"):
            self.model.selected_ids = set(self.workspace_selections.get(doc_id, set()))
            self.model.selectionChanged.emit()
        QTimer.singleShot(0, self.resize_visible_rows)
        kind = "DOCX" if doc["format"] == "docx" else doc["encoding"]
        self.filename.setText(f"{Path(doc['path']).name}  ·  {len(self.model.rows):,} dòng  ·  {kind}")
        self.store.set_setting("recent_document", doc_id)
        if hasattr(self, 'workspace_ids'):
            if doc_id not in self.workspace_ids: self.workspace_ids.append(doc_id)
            self.refresh_workspace_choices()
            position = self.workspace_positions.get(doc_id, 0)
            QTimer.singleShot(0, lambda: self.restore_document_editor_state(doc_id, position))
        if hasattr(self, "view_language"): self.sync_view_language()
        self.refresh()

    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Nhập tài liệu", self.store.setting("last_import_dir", ""), "Tài liệu (*.txt *.docx *.doc);;Text files (*.txt);;Word (*.docx *.doc)")
        if not path:
            return
        if Path(path).suffix.lower() == ".doc":
            QMessageBox.information(self, "Định dạng Word cũ", "File .doc chưa được hỗ trợ. Hãy mở bằng Word hoặc LibreOffice và lưu thành .docx trước khi nhập.")
            return
        try:
            if Path(path).suffix.lower() == ".docx":
                imported = import_docx(path)
                data = ImportedText(tuple(TextLine(unit.text, "") for unit in imported.units), "docx", imported.raw)
                doc_id, created = self.store.import_document(path, data, self.source_lang.currentText(), self.target_lang.currentText(), document_format="docx", locators=[unit.locator for unit in imported.units])
            elif Path(path).suffix.lower() == ".txt":
                try:
                    data = import_txt(path)
                except EncodingChoiceRequired as warning:
                    choices = [x for x in [warning.suggestion, "cp1258", "cp1252", "cp932", "gb18030", "utf-16-le"] if x]
                    encoding, accepted = QInputDialog.getItem(self, "Xác nhận bảng mã", "Không xác định chắc chắn bảng mã. Chọn encoding để nhập:", list(dict.fromkeys(choices)), 0, True)
                    if not accepted:
                        return
                    data = import_txt(path, encoding)
                doc_id, created = self.store.import_document(path, data, self.source_lang.currentText(), self.target_lang.currentText())
            else:
                raise ValueError("Chỉ hỗ trợ TXT và DOCX.")
            self.store.set_setting("last_import_dir", str(Path(path).parent))
            self.open_document(doc_id)
            self.notice.setText("Đã tạo lần nhập mới · bản dịch trống · lịch sử cũ được giữ.")
        except (OSError, UnicodeError, ValueError) as exc:
            self.store.log.emit("import_error", exception=type(exc).__name__, state="not_imported")
            QMessageBox.warning(self, "Không thể nhập tài liệu", str(exc))

    def _key(self) -> str | None:
        encrypted = self.store.load_key()
        if not encrypted:
            QMessageBox.information(self, "Cần API key", "Hãy lưu Kira API key trong mục Quản lý API trước khi dịch.")
            self.pages.setCurrentIndex(2)
            return None
        try:
            return unprotect_key(encrypted)
        except Exception as exc:
            QMessageBox.warning(self, "Không thể đọc API key", f"DPAPI không giải mã được khóa: {type(exc).__name__}")
            return None

    def start_translation(self):
        if getattr(self,'queue_clear_busy',False):return
        if hasattr(self, "target_chips") and not any(c.isChecked() and c.isEnabled() for c in self.target_chips.values()):
            QMessageBox.information(self, "Ngôn ngữ đích", "Chọn ít nhất một ngôn ngữ đích khác nguồn."); return
        if not self.doc_id:
            self.import_file()
            return
        if self.scheduler and self.scheduler._thread and self.scheduler._thread.is_alive():
            QMessageBox.information(self, "Đang dịch", "Hãy dừng hoặc hoàn thành lượt dịch đang chạy.")
            return
        changed_target = self.store.document(self.doc_id)['target_lang'] != self.target_lang.currentText() and any(j['document_id'] == self.doc_id for j in self.store.jobs())
        if self.provider_id() == 'gemini' or len(self.target_languages()) > 1 or len(self.workspace_ids) > 1 or changed_target:
            self.start_stage2()
            return
        if not self.valid_languages():
            return
        key = self._key()
        if not key:
            return
        model = self.selected_model_id()
        if not model:
            return
        try:
            job_id = self.store.create_job(self.doc_id, model, self.source_lang.currentText(), self.target_lang.currentText(), self.concurrency.value(), timeout=self.timeout_spin.value())
        except ValueError as exc:
            QMessageBox.information(self, "Không thể bắt đầu", "Không còn dòng chưa gửi đủ điều kiện. Chọn checkbox rồi dùng Dịch lại dòng đã chọn để xử lý lỗi hoặc tạo bản mới." if "No lines" in str(exc) else str(exc))
            return
        self.store.set_setting("concurrency", str(self.concurrency.value()))
        self.scheduler = Scheduler(self.store, KiraProvider(key, model, timeout=self.store.job(job_id)["timeout"], prompt_version=self.store.job(job_id)["prompt_version"]), self.bridge.changed.emit)
        self.current_job_ids = {item["id"] for batch in self.store.batches(job_id) for item in batch["payload"]}
        self.scheduler.start(job_id)
        self.refresh()

    def pause_or_resume(self):
        if getattr(self,'queue_clear_busy',False):return
        if not self.scheduler or not self.scheduler._thread or not self.scheduler._thread.is_alive():
            return
        if self.scheduler._paused.is_set():
            self.scheduler.resume()
        else:
            self.scheduler.pause()
        self.refresh()

    def stop_translation(self):
        if self.scheduler:
            self.scheduler.stop()
        self.stop_button.setEnabled(False)
        self.notice.setText('Đã dừng cấp request mới · request đang chạy có thể vẫn tiêu thụ token.')

    def retry_all_errors(self):
        self.retry_selected(all_errors=True)

    def retry_selected(self, _checked=False, *, all_errors=False):
        if getattr(self,'queue_clear_busy',False):return
        if not self.doc_id:
            return
        selected = [r for r in self.model.all_rows if r["state"] in ("error", "unknown", "wrong_target_language")] if all_errors else self.model.selected_rows()
        if self.scheduler and self.scheduler._thread and self.scheduler._thread.is_alive():
            return
        selected = [r for r in selected if translatable(r["source"]) and r["state"] != "processing"]
        ids = [row["id"] for row in selected]
        if not ids:
            QMessageBox.information(self, "Chọn dòng", "Chọn checkbox dòng có văn bản, đang hiển thị và không xử lý để dịch lại.")
            return
        origins = {}
        for j in self.store.jobs():
            if j["document_id"] == self.doc_id:
                for batch in self.store.batches(j["id"]):
                    for item in batch["payload"]:
                        if item["id"] in ids and item["id"] not in origins:
                            origins[item["id"]] = j
        original = next(iter(origins.values()), None)
        if len({(j["provider"], j["model"], j["source_lang"], j["target_lang"]) for j in origins.values()}) > 1:
            QMessageBox.information(self, "Khác cấu hình gốc", "Các dòng được chọn thuộc nhiều model/ngôn ngữ gốc. Chọn các dòng cùng cấu hình để dịch lại đúng model gốc.")
            return
        if original and original["provider"] not in ('kira', 'gemini'):
            QMessageBox.information(self, "Nhà cung cấp gốc", "Không hỗ trợ tự chuyển nhà cung cấp của lượt dịch gốc.")
            return
        model = original["model"] if original else self.selected_model_id()
        source = original["source_lang"] if original else self.source_lang.currentText()
        target = original["target_lang"] if original else self.target_lang.currentText()
        invalid_old_languages = source not in {self.source_lang.itemText(i) for i in range(self.source_lang.count())} or target not in {self.target_lang.itemText(i) for i in range(self.target_lang.count())}
        if invalid_old_languages:
            if not self.valid_languages():
                return
            source, target = self.source_lang.currentText(), self.target_lang.currentText()
        provider = original['provider'] if original else self.provider_id()
        allowed = {m for _, m in KIRA_MODELS} if provider == 'kira' else {m['name'] for m in json.loads(self.store.setting('gemini_models', '{"models":[]}')).get('models', [])}
        if model not in allowed:
            if provider != self.provider_id():
                QMessageBox.information(self, 'Model gốc không khả dụng', 'Chọn đúng provider và làm mới danh sách model trước khi dịch lại.'); return
            model = self.selected_model_id()
            if not model:
                self.notice.setText("Model gốc không khả dụng. Chọn model thay thế rồi xác nhận dịch lại.")
                return
        if source == target:
            self.valid_languages()
            return
        message = f"Dịch lại {'tất cả dòng lỗi trong lần nhập này' if all_errors else 'dòng đã chọn đang hiển thị'}: {len(ids)} dòng, {(len(ids)+2)//3} batch, {self.concurrency.value()} luồng, {model}, {source} → {target}? Request mới có thể tốn thêm token. Bản cũ được giữ nếu lỗi."
        if any(r["state"] == "unknown" for r in selected):
            message += "\nRequest timeout/504 trước có thể đã tiêu thụ token; gửi mới có thể tốn thêm token."
        if original and model != original["model"]:
            message += "\nModel gốc không khả dụng; đây là xác nhận dùng model thay thế đã chọn."
        if invalid_old_languages:
            message += "\nTên ngôn ngữ trong lượt cũ không hợp lệ; xác nhận dùng hai lựa chọn hợp lệ hiện tại."
        if QMessageBox.question(self, "Xác nhận dịch lại", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        key = self._key() if provider == 'kira' else None
        if provider == 'kira' and not key: return
        config = json.loads(original['config']) if original else {}
        if provider == 'gemini' and not config:
            QMessageBox.information(self, 'Cấu hình Gemini', 'Bắt đầu một lượt có snapshot key/quota trước khi dịch lại.'); return
        try:
            job_id = self.store.create_job(self.doc_id, model, source, target, original['concurrency'] if provider == 'gemini' and original else self.concurrency.value(), ids, self.timeout_spin.value(), provider=provider, config=config)
        except ValueError as exc:
            QMessageBox.information(self, "Không thể dịch lại", str(exc))
            return
        job = self.store.job(job_id)
        if all_errors:
            with self.store.transaction():
                self.store.db.execute("UPDATE jobs SET mode='retry_errors' WHERE id=?", (job_id,))
        self.scheduler = Scheduler(self.store, self.make_provider(job, key) if provider == 'gemini' else KiraProvider(key, job['model'], timeout=job['timeout'], prompt_version=job['prompt_version']), self.bridge.changed.emit)
        self.current_job_ids = {item["id"] for batch in self.store.batches(job_id) for item in batch["payload"]}
        self.scheduler.start(job_id)
        self.refresh()

    def export_file(self):
        if self.doc_id:
            self.export_documents([self.doc_id])

    def open_export_folder(self):
        if self.last_export and self.last_export.parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_export.parent)))

    def save_api_key(self):
        key = self.api_key_input.text().strip()
        if not key:
            return
        try:
            encrypted = protect_key(key)
            self.store.save_key(encrypted)
            self.api_key_input.clear()
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Không lưu được khóa", f"Windows DPAPI không khả dụng: {type(exc).__name__}")

    def toggle_theme(self):
        self.dark = not self.dark
        self.store.set_setting("dark", "1" if self.dark else "0")
        self.setStyleSheet(stylesheet(self.dark))
        self.sky_switch.set_dark(self.dark)
        self.update_branding()
        from .controls import install_combo_popup
        for combo in self.findChildren(QComboBox): install_combo_popup(combo)

    def update_row_gutter(self):
        header = self.table.verticalHeader()
        size = getattr(self, '_manuscript_font_size', self.font_spin.value())
        maximum = max((r['ordinal'] + 1 for r in self.model.all_rows), default=1)
        key = (self.model.doc_id, maximum, size)
        if getattr(self, '_row_gutter_key', None) == key: return
        self._row_gutter_key = key
        font = self.table.font(); font.setPixelSize(size); font.setBold(True)
        header.setStyleSheet(f'QHeaderView, QHeaderView::section {{ font-size: {size}px; }}')
        header.setFont(font); header.ensurePolished()
        metrics = QFontMetrics(font)
        # Reserve the widest status once for the entire document, including filtered rows.
        status = max(metrics.horizontalAdvance(s) for s in ('✓', '!', '?', '◌', '·', '–', '↻'))
        header.setFixedWidth(metrics.horizontalAdvance(str(maximum)+' ') + status + 12)

    def change_font(self, size: int):
        row = self.table.rowAt(0)
        anchor_id = self.model.rows[row]["id"] if row >= 0 else None
        offset = self.table.visualRect(self.model.index(row, 0)).top() if row >= 0 else 0
        font = self.table.font()
        font.setPixelSize(size)
        self._manuscript_font_size = size
        self.table.setFont(font)
        self.table.setStyleSheet(f"QTableView {{ font-size: {size}px; }}")
        self.update_row_gutter()
        self.table.itemDelegate().apply_editor_font()
        for row in getattr(self, "_measured_rows", set()):
            if row < self.model.rowCount():
                self.table.setRowHeight(row, max(28, size + 14))
        self._measured_rows = set()
        self.store.set_setting("font_size", str(size))
        self.resize_visible_rows()
        if anchor_id in self.model.id_index:
            self.table.scrollTo(self.model.index(self.model.id_index[anchor_id], 0), QAbstractItemView.PositionAtTop)
            self.table.verticalScrollBar().setValue(self.table.verticalScrollBar().value()-offset)
        self.table.viewport().update()

    def resize_visible_rows(self):
        if self._closed:return
        if getattr(self, "_resizing_rows", False) or not hasattr(self, "table") or self.model.rowCount() == 0:
            return
        self._resizing_rows = True
        try:
            # Settle Qt's scrollbar bounds now: deferred row geometry can otherwise
            # clamp a bottom scroll twice on the next API repaint.
            for _ in range(3):
                previous = (self.table.rowAt(0), self.table.verticalScrollBar().maximum())
                self._resize_visible_rows_inner()
                self.table.doItemsLayout()
                if previous == (self.table.rowAt(0), self.table.verticalScrollBar().maximum()): break
        finally:
            self._resizing_rows = False

    def _resize_visible_rows_inner(self):
        top = max(0, self.table.rowAt(0))
        bottom = self.table.rowAt(self.table.viewport().height() - 1)
        if bottom < 0:
            bottom = min(top + 15, self.model.rowCount() - 1)
        delegate = self.table.itemDelegate()
        from PySide6.QtWidgets import QStyleOptionViewItem
        for row in range(top, min(bottom + 2, self.model.rowCount())):
            heights = []
            for col in (0, 1):
                index = self.model.index(row, col)
                option = QStyleOptionViewItem()
                option.font = self.table.font()
                option.rect = self.table.visualRect(index)
                heights.append(delegate.sizeHint(option, index).height())
            height = max(heights)
            if self.table.rowHeight(row) != height:
                self.table.setRowHeight(row, height)
            if not hasattr(self, "_measured_rows"):
                self._measured_rows = set()
            self._measured_rows.add(row)

    def refresh(self, changed_ids: list[str] | None = None):
        if self._exit_pending: return
        try:
            self._refresh(changed_ids)
        except Exception as exc:
            if not self._closed:
                self.store.log.emit('gui_error', document_id=self.doc_id, job_id=self.scheduler.job_id if self.scheduler else None, exception=type(exc).__name__, state='refresh_failed')
                self.notice.setText('Không cập nhật được giao diện; xem Console để chẩn đoán.')

    @Slot(list)
    def queue_api_updates(self, ids):
        if self._closed or self._exit_pending:return
        self.pending_changed_ids.update(ids)
        if not self.refresh_timer.isActive(): self.refresh_timer.start()

    def flush_api_updates(self):
        ids = list(self.pending_changed_ids); self.pending_changed_ids.clear()
        self.refresh(ids)

    def _refresh(self, changed_ids: list[str] | None = None):
        if self._closed or self._exit_pending or not hasattr(self, "model"):
            return
        if changed_ids and self.scheduler:
            self.scheduler.acknowledge(changed_ids, self.doc_id)
        scroll = self.table.verticalScrollBar().value() if hasattr(self, "table") else 0
        self.model.refresh(changed_ids)
        if changed_ids is not None and self.table.verticalScrollBar().value() != scroll:
            self.table.verticalScrollBar().setValue(scroll)
        rows = self.model.all_rows
        if changed_ids:
            for line_id in changed_ids:
                row = next((r for r in rows if r["id"] == line_id), None)
                if row is not None and row["state"] in ("error", "unknown", "wrong_target_language"):
                    error = row["error"]
                    if error:
                        self.notice.setText('Có dòng cần kiểm tra · xem Console')
                        break
        total = sum(translatable(r["source"]) for r in rows)
        done = sum(usable(r) for r in rows)
        processing = sum(r["state"] == "processing" for r in rows)
        errors = sum(r["state"] in ("error", "unknown", "stale", "wrong_target_language") for r in rows)
        speed = "đang đo"
        eta = ""
        job_percent = 0
        if self.scheduler and self.scheduler.job_id:
            job_rows = [r for r in rows if r["id"] in self.current_job_ids]
            job_done = sum(r["state"] == "done" for r in job_rows)
            job_percent = int(job_done * 100 / len(job_rows)) if job_rows else 0
            elapsed = time.monotonic() - (self.scheduler.started_at or time.monotonic())
            if elapsed >= 5 and job_done:
                per_minute = job_done * 60 / elapsed
                speed = f"{per_minute:.1f} dòng/phút"
                if elapsed >= 10 and job_done >= 3 and per_minute > 0:
                    eta = f"   ·   ETA ~{int((len(job_rows) - job_done) / per_minute + 0.99)} phút"
        self.stats_label.setText(f"{total:,} dòng cần dịch   ·   {done:,} hoàn tất   ·   {processing:,} đang xử lý   ·   {errors:,} cần xem lại   ·   {speed}{eta}")
        self.active_label.setText(f"{self.scheduler.active if self.scheduler else 0} luồng hoạt động")
        running = bool(self.scheduler and self.scheduler._thread and self.scheduler._thread.is_alive())
        if not running and self.scheduler and self.scheduler.job_id:
            job_state = self.store.job(self.scheduler.job_id)["state"]
            missing = total-done
            finished = f"Đã xử lý lượt dịch · còn {errors} dòng lỗi/cũ · {missing} dòng chưa có bản dịch · {self.scheduler.retry_count} retry"
            self.active_label.setText({"finished": finished, "stopped": "Đã dừng — không tự gửi lại", "interrupted": "Bị gián đoạn — chưa tự tiếp tục"}.get(job_state, job_state))
            self.stats_label.setText(f"{total:,} dòng cần dịch · {done:,} hoàn tất · {errors:,} cần xem lại")
        elif running and self.scheduler._paused.is_set():
            self.active_label.setText(f"Đã tạm dừng · {self.scheduler.active} request đang hoàn tất")
        elif running and self.scheduler._stopped.is_set():
            self.active_label.setText(f"Đang dừng an toàn · {self.scheduler.active} request đang hoàn tất")
        elif running and getattr(self.scheduler, 'cooldown_until', 0) > time.monotonic():
            self.active_label.setText(f"Chờ API · {max(0, self.scheduler.cooldown_until-time.monotonic()):.1f}s · {self.scheduler.effective_concurrency}/{self.store.job(self.scheduler.job_id)['concurrency']} luồng")
        elif running and self.scheduler.retrying:
            self.active_label.setText(f"Đang thử lại · {self.scheduler.retry_count} retry · có thể tốn thêm token")
        elif running:
            mode = self.store.job(self.scheduler.job_id).get("mode")
            self.active_label.setText(("Đang dịch lại tất cả dòng lỗi" if mode == "retry_errors" else "Đang dịch lại dòng đã chọn" if mode == "retranslation" else "Đang dịch") + f" · {self.scheduler.active} request")
        if running and getattr(self.scheduler,'current_locale',None):
            self.active_label.setText(self.scheduler.current_locale+' · '+self.active_label.text())
        percent = int(done * 100 / total) if total else 0
        self.file_progress.setValue(percent)
        self.total_progress.setValue(job_percent)
        running = bool(self.scheduler and self.scheduler._thread and self.scheduler._thread.is_alive())
        self.start_button.setEnabled(bool(self.doc_id) and bool(self.target_languages()) and not running)
        self.pause_button.setEnabled(running)
        self.pause_button.setText("▶  Tiếp tục" if running and self.scheduler._paused.is_set() else "Ⅱ  Tạm dừng")
        self.stop_button.setEnabled(running)
        self.export_button.setEnabled(bool(self.doc_id))
        self.folder_button.setEnabled(self.last_export is not None and self.last_export.parent.is_dir())
        if hasattr(self, 'retry_workspace_button'):
            self.retry_workspace_button.setEnabled(not running and any(r['state'] in ('error', 'unknown', 'wrong_target_language') for d in self.workspace_ids for r in self.store.lines(d)))
        if self.scheduler and getattr(self.scheduler, 'waiting', 0) and not self.scheduler._paused.is_set() and getattr(self.scheduler, 'cooldown_until', 0) <= time.monotonic():
            configured = self.store.job(self.scheduler.job_id)['concurrency']
            configured = getattr(self.scheduler, 'configured_concurrency', configured)
            self.active_label.setText(f'{self.scheduler.active} request · {self.scheduler.waiting} chờ · {self.scheduler.retry_count} retry · giới hạn {self.scheduler.effective_concurrency}/{configured}')
            self.active_label.setToolTip(self.active_label.text())
        self.update_editorial()
        self.retry_errors_button.setEnabled(any(r['state'] in ('error', 'unknown', 'wrong_target_language') for r in rows) and not running)
        self.key_status.setText("●  API key đã lưu bằng Windows DPAPI" if self.store.load_key() else "○  Chưa cấu hình API key")
        if hasattr(self, 'workspace_ids'): self.refresh_stage2()
        if self.pages.currentIndex() == 1:
            selected_job = self.job_list.currentItem().data(Qt.UserRole) if self.job_list.currentItem() else None
            checked = {self.job_list.item(i).data(Qt.UserRole) for i in range(self.job_list.count()) if self.job_list.item(i).checkState() == Qt.Checked}
            self.job_list.clear()
            for entry in self.store.history():
                name = Path(entry["path"]).name
                self.job_list.addItem(f"{name} · {entry['source_lang']} → {entry['target_lang']} · {entry['model']} · {entry['done']}/{entry['total']} dùng được · {entry['state']} · {entry['created_at']}\nImport: {entry['id']} · Mục: {entry['entry_id']}")
                item = self.job_list.item(self.job_list.count()-1)
                item.setData(Qt.UserRole, entry["entry_id"])
                item.setCheckState(Qt.Checked if entry["entry_id"] in checked else Qt.Unchecked)
                if entry["entry_id"] == selected_job:
                    self.job_list.setCurrentRow(self.job_list.count()-1)
            self.clear_all_jobs_button.setEnabled(self.job_list.count()>0 and not getattr(self,'queue_clear_busy',False))

    def show_job_document(self):
        item = self.job_list.currentItem()
        if item:
            entry_id = item.data(Qt.UserRole)
            job = None if entry_id.startswith('import:') else self.store.job(entry_id)
            self.open_document(entry_id[7:] if job is None else job['document_id'])
            if job:
                self.provider_selector.setCurrentIndex(self.provider_selector.findData(job['provider']))
                self.source_lang.setCurrentText(job['source_lang']); self.target_lang.setCurrentText(job['target_lang'])
                self.set_model_id(job['model'])
            self.pages.setCurrentIndex(0)

    def resume_job(self):
        if getattr(self,'queue_clear_busy',False):return
        item = self.job_list.currentItem()
        if not item:
            return
        job = self.store.job(item.data(Qt.UserRole))
        if not job:
            QMessageBox.information(self, "Chưa có lượt dịch", "Mở lần nhập này và bấm Bắt đầu dịch.")
            return
        if not Scheduler.has_work(self.store, job['id']):
            missing = sum(r['state'] in ('error', 'unknown', 'wrong_target_language') for r in self.store.lines(job['document_id']))
            QMessageBox.information(self, "Không có batch chờ", f"Còn {missing} dòng lỗi — đã dùng hết số lần tự thử lại hoặc kết quả không chắc chắn. Có thể chủ động dịch lại lỗi.")
            return
        key = self._key() if job['provider'] == 'kira' else None
        if job['provider'] == 'kira' and not key: return
        if self.scheduler and self.scheduler._thread and self.scheduler._thread.is_alive():
            QMessageBox.information(self, "Đang dịch", "Hãy hoàn thành lượt dịch đang chạy.")
            return
        self.open_document(job["document_id"])
        try: adapter = self.make_provider(job, key)
        except Exception as exc: QMessageBox.information(self, 'Không phục hồi được cấu hình key', type(exc).__name__); return
        self.scheduler = Scheduler(self.store, adapter, self.bridge.changed.emit)
        if job['run_id']:
            # Include finished/unknown phases so the saved language barrier cannot be bypassed.
            self.scheduler.job_ids = [j['id'] for j in self.store.run_jobs(job['run_id'])]
            self.scheduler.run_id = job['run_id']
            self.workspace_ids = [j['document_id'] for j in self.store.run_jobs(job['run_id'])]
        self.current_job_ids = {entry['id'] for jid in self.scheduler.job_ids or [job['id']] for batch in self.store.batches(jid) for entry in batch['payload']}
        self.refresh_workspace_choices()
        self.scheduler.start(job["id"])
        self.pages.setCurrentIndex(0)

    def show_batch_diagnostics(self):
        item = self.job_list.currentItem()
        if not item:
            return
        job_id = item.data(Qt.UserRole)
        sections = []
        for batch in self.store.batches(job_id):
            metadata = batch["diagnostics"] or {"note": "Batch cũ chưa có metadata chẩn đoán."}
            metadata = {**metadata, 'request_attempts': self.store.attempts(batch['id'])}
            sections.append(f"Batch {batch['id']} · {batch['state']}\n{batch['error'] or ''}\n" + json.dumps(metadata, ensure_ascii=False, indent=2))
        dialog = QDialog(self)
        dialog.setWindowTitle("Chẩn đoán request · không chứa nội dung truyện hoặc API key")
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText("\n\n".join(sections))
        layout.addWidget(text)
        close = button("Đóng")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.resize(min(800, self.screen().availableGeometry().width()-40), min(600, self.screen().availableGeometry().height()-60))
        dialog.exec()

    def close(self):
        # Qt deletes the accepted window; repeated close requests stay idempotent
        # without calling a C++ QWidget through an already retired wrapper.
        if self._closed:return True
        return super().close()

    def closeEvent(self, event):
        try:
            self._close_event(event)
        except Exception as exc:
            panel=getattr(self,'update_panel',None)
            if panel and (panel.handoff_pending or panel.handoff_session is not None):
                panel.abort_handoff();self._exit_authorized=False
            import traceback
            frames=[{'file_name':Path(f.filename).name,'reason':f.name,'line_count':f.lineno} for f in traceback.extract_tb(exc.__traceback__)]
            self.store.log.emit('shutdown_error',exception=type(exc).__name__,stack_trace=frames)
            self.statusBar().showMessage('Không hoàn tất đóng ứng dụng · xem Console; không gửi lại request.')
            self.exit_timer.stop()
            event.ignore()

    def _close_event(self, event):
        panel=getattr(self,'update_panel',None)
        if panel and panel.handoff_pending:
            panel.cancel_event.set()
            self.statusBar().showMessage('Đang hủy bàn giao cập nhật; chờ helper dừng an toàn…')
            event.ignore();return
        update_exit=bool(getattr(self,'_update_exit_requested',False) and panel and panel.handoff_session)
        update_close_started=time.monotonic() if update_exit else None
        if update_exit:
            from .update_panel import native_install_idle
            if not native_install_idle(self):
                panel.abort_handoff();event.ignore();return
        if getattr(self,'_exit_dialog_active',False):
            event.ignore(); return
        if self._closed:
            event.accept()
            return
        running = bool(self.scheduler and self.scheduler._thread and self.scheduler._thread.is_alive()) or any(t.is_alive() for t in getattr(self, 'background_threads', []))
        if self._exit_pending and not self._exit_authorized:
            event.ignore()
            return
        if not self._exit_authorized:
            choice = 'safe' if update_exit else self.confirm_exit(running)
            if choice == "cancel":
                event.ignore()
                return
            if choice == "background":
                if self.minimize_to_tray():
                    event.ignore()
                    return
                event.ignore()
                return
            if running and choice in ("safe", "exit"):
                self._exit_pending = True
                self.statusBar().showMessage('Đang thoát an toàn · ngừng cấp request mới, chờ lưu kết quả…')
                for timer_name in ('local_timer','queue_timer','refresh_timer','layout_save_timer'):
                    timer = getattr(self,timer_name,None)
                    if timer: timer.stop()
                self._exit_deadline = time.monotonic()+self.shutdown_grace_seconds
                if self.scheduler: self.scheduler.stop()
                self.notice.setText("Đang thoát an toàn: chờ request đang chạy lưu kết quả…")
                self.exit_timer.start()
                event.ignore()
                return
            self._exit_authorized = True
        if not getattr(self, "_reset_window_state", False):
            save_window_state(self)
        if hasattr(self, 'layout_save_timer'):
            self.layout_save_timer.stop()
            from .layout_state import capture
            capture(self)
        if self.tray:
            self.tray.hide()
        self.exit_timer.stop()
        for name in ('local_timer','queue_timer','refresh_timer','layout_save_timer'):
            timer=getattr(self,name,None)
            if timer:timer.stop()
        if hasattr(self,'update_panel'):self.update_panel.shutdown()
        if hasattr(self,'period_warning'):self.period_warning.shutdown()
        if hasattr(self,'line_check'):self.line_check.shutdown()
        self.store.close()
        self._closed = True
        if update_exit:
            from ..update.install import SafetySnapshot
            logger=self.store.log
            try:
                panel.handoff_session.commit(SafetySnapshot(app_closed=True,safe_exit_verified=True),
                    logger.closed and not logger.thread.is_alive() and not logger.failure and
                    time.monotonic()-update_close_started<=.9)
            except Exception:
                # EOF prevents execution. Safe Exit failure never becomes a
                # successful installer authorization, even after DB close.
                panel.handoff_session.abort()
        super().closeEvent(event)

    def confirm_exit(self, running):
        self._exit_dialog_active=True
        try:
            dialog = ExitDialog(self, running, QSystemTrayIcon.isSystemTrayAvailable())
            dialog.exec()
            return dialog.choice
        finally:
            self._exit_dialog_active=False

    def reset_window_preferences(self):
        self._reset_window_state = True
        self.store.set_setting("window_state", "")
        self.notice.setText("Lần mở tiếp theo sẽ chọn kích thước cửa sổ theo màn hình.")

    def finish_safe_exit(self):
        try:
            self._finish_safe_exit()
        except Exception as exc:
            import traceback
            frames = [{'file_name':Path(frame.filename).name, 'reason':frame.name, 'line_count':frame.lineno}
                      for frame in traceback.extract_tb(exc.__traceback__)]
            self.store.log.emit('shutdown_error', exception=type(exc).__name__, stack_trace=frames)
            self.notice.setText('Lỗi khi đóng · kết quả đã commit được giữ; xem Console.')
            self.exit_timer.stop()

    def _finish_safe_exit(self):
        # A zero-duration Windows yield may immediately return to Qt's event pump.
        # Give the Python/asyncio cleanup thread a bounded scheduling opportunity;
        # this is not a worker join or an extension of the shutdown deadline.
        import time
        time.sleep(.001)
        if not getattr(self, '_exit_cancelled', False) and time.monotonic() >= getattr(self, '_exit_deadline', float('inf')):
            self._exit_cancelled = True
            if self.scheduler and hasattr(self.scheduler, 'cancel_inflight'): self.scheduler.cancel_inflight()
            self.notice.setText('Đã hết hạn chờ HTTP · đang lưu outcome_unknown và đóng kết nối…')
            self.statusBar().showMessage('Hết hạn chờ HTTP · đang lưu outcome_unknown và đóng kết nối…')
        if any(t.is_alive() for t in getattr(self, 'background_threads', [])): return
        if self.scheduler and self.scheduler._thread and self.scheduler._thread.is_alive():
            if not self._fence_active_scheduler(): return
        # Console I/O is not allowed to freeze Qt while flushing on exit.
        import threading
        if not hasattr(self, '_exit_log_thread'):
            self._exit_log_thread = threading.Thread(target=self.store.log.close, daemon=True)
            self._exit_log_thread.start()
        if self._exit_log_thread.is_alive(): return
        self._exit_authorized = True
        self.exit_timer.stop()
        self.close()

    def _fence_active_scheduler(self):
        if time.monotonic() < getattr(self,'_exit_deadline',float('inf'))+.5: return False
        import threading
        if not hasattr(self,'_exit_fence_thread'):
            self._exit_fence_done = False
            def fence():
                try:
                    self.scheduler.fence_shutdown()
                    self._exit_fence_done = True
                except Exception as exc:
                    import traceback
                    frames=[{'file_name':Path(f.filename).name,'reason':f.name,'line_count':f.lineno} for f in traceback.extract_tb(exc.__traceback__)]
                    self.store.log.emit('shutdown_error',exception=type(exc).__name__,stack_trace=frames)
            self._exit_fence_thread=threading.Thread(target=fence,daemon=True)
            self._exit_fence_thread.start()
            self.statusBar().showMessage('HTTP không chịu hủy · giữ outcome_unknown; kết quả đã commit được bảo toàn.')
            return False
        return not self._exit_fence_thread.is_alive() and self._exit_fence_done

    def minimize_to_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            QMessageBox.information(self, "Không thể chạy nền", "System tray không khả dụng. Hãy giữ cửa sổ mở để công việc tiếp tục.")
            return False
        if self.tray is None:
            self.tray = QSystemTrayIcon(self.windowIcon(), self)
        if self.tray.contextMenu() is None:
            self.tray.setToolTip("TransComic · Công việc tiếp tục chạy")
            menu = QMenu(self)
            show = QAction("Mở TransComic", menu)
            show.triggered.connect(self.restore_from_tray)
            menu.addAction(show)
            exit_action = QAction("Thoát…", menu)
            exit_action.triggered.connect(self.close)
            menu.addAction(exit_action)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: self.restore_from_tray() if reason == QSystemTrayIcon.DoubleClick else None)
        self.tray.show()
        self.hide()
        return True

    def restore_from_tray(self):
        self.show()
        self.raise_()
        self.activateWindow()
