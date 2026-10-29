"""Metadata diagnostics viewer. Reading old events never forces autoscroll."""
import json
from datetime import datetime, timezone
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLineEdit, QListWidget, QPlainTextEdit, QPushButton, QFileDialog, QMessageBox, QApplication, QSplitter, QLabel
from ..models import KIRA_MODELS
from .controls import QComboBox
from .glass import GlassButton as QPushButton


class ConsolePage(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.window, self.log = window, window.store.log
        self.signature, self.hidden_until = None, ''
        self.rows = []
        layout = QVBoxLayout(self)
        title = QLabel("Console · nhật ký kỹ thuật đã che thông tin nhạy cảm")
        title.setObjectName("section")
        title.setWordWrap(True)
        layout.addWidget(title)
        self.performance = QLabel()
        self.performance.setWordWrap(True)
        self.performance.setObjectName('muted')
        layout.addWidget(self.performance)
        copy_perf = QPushButton('Sao chép báo cáo hiệu năng')
        copy_perf.clicked.connect(lambda: QApplication.clipboard().setText(json.dumps(self.performance_report(), ensure_ascii=False, indent=2)))
        layout.addWidget(copy_perf)
        filters = QHBoxLayout()
        self.level = QComboBox()
        self.level.addItems(["Mọi mức độ", "DEBUG", "INFO", "WARNING", "ERROR"])
        filters.addWidget(self.level)
        self.provider = QComboBox()
        self.provider.addItems(["Mọi provider", "kira", "gemini", "deepseek"])
        filters.addWidget(self.provider)
        self.model = QComboBox()
        self.model.addItem("Mọi model", "")
        for name, model_id in KIRA_MODELS:
            self.model.addItem(name, model_id)
        filters.addWidget(self.model)
        self.job = QLineEdit()
        self.job.setPlaceholderText("Job/import ID")
        filters.addWidget(self.job)
        layout.addLayout(filters)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Tìm trong metadata · không chứa nội dung truyện")
        layout.addWidget(self.search)
        split = QSplitter(Qt.Vertical)
        self.listing = QListWidget()
        split.addWidget(self.listing)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        split.addWidget(self.detail)
        split.setSizes([330, 180])
        layout.addWidget(split, 1)
        self.health = QLabel()
        layout.addWidget(self.health)
        row = QHBoxLayout()
        for text, action in [("Copy lỗi", self.copy_event), ("Sao chép báo cáo lỗi", self.copy_report), ("Xuất báo cáo", self.export_report), ("Ẩn log đang xem", self.clear_view), ("Dọn log đã lưu", self.clear_saved)]:
            b = QPushButton(text)
            b.clicked.connect(action)
            row.addWidget(b)
        layout.addLayout(row)
        self.listing.currentRowChanged.connect(self.show_detail)
        for control in (self.level, self.provider, self.model):
            control.currentIndexChanged.connect(self.reload)
        for control in (self.job, self.search):
            control.textChanged.connect(self.reload)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.poll)
        self.timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.window._closed: self.reload()

    def poll(self):
        if self.isVisible() and not self.window._closed:
            self.reload()

    def reload(self, *_):
        report = self.performance_report()
        self.performance.setText('Chẩn đoán hiệu năng · ' + ' · '.join(f'{k}: {v}' for k,v in report.items()))
        events = [e for e in self.log.snapshot() if e['time'] > self.hidden_until]
        known = {self.model.itemData(i) for i in range(self.model.count())}
        for event in events:
            if event.get('model') and event['model'] not in known:
                self.model.blockSignals(True); self.model.addItem(event['model'], event['model']); self.model.blockSignals(False)
                known.add(event['model'])
        rows = []
        for event in events:
            if self.level.currentIndex() and event["level"] != self.level.currentText():
                continue
            if self.provider.currentIndex() and event.get("provider") != self.provider.currentText():
                continue
            if self.model.currentData() and event.get("model") != self.model.currentData():
                continue
            if self.job.text() and self.job.text() not in event.get("job_id", "") and self.job.text() not in event.get("document_id", ""):
                continue
            if self.search.text().casefold() not in json.dumps(event, ensure_ascii=False).casefold():
                continue
            rows.append(event)
        signature = json.dumps(rows)
        self.health.setText(f"{len(rows)} sự kiện hiển thị · Log: {self.log.failure or 'OK'} · Rotation 2MB × 4 file")
        if signature == self.signature:
            return
        scroll = self.listing.verticalScrollBar()
        at_end = scroll.value() >= scroll.maximum()-2
        old_scroll, current = scroll.value(), self.listing.currentRow()
        self.rows, self.signature = rows, signature
        self.listing.blockSignals(True)
        self.listing.clear()
        for event in rows:
            self.listing.addItem(f"{event['time']}  {event['level']}  {event['category']}  {event.get('model','')}  {event['description']}  {event.get('http_status','')}  {event.get('state','')}")
        if rows:
            self.listing.setCurrentRow(min(max(0, current), len(rows)-1))
        self.listing.blockSignals(False)
        self.show_detail(self.listing.currentRow())
        if at_end:
            self.listing.scrollToBottom()
        else:
            scroll.setValue(old_scroll)
        self.health.setText(f"{len(rows)} sự kiện hiển thị · Log: {self.log.failure or 'OK'} · Rotation 2MB × 4 file")

    def show_detail(self, index):
        self.detail.setPlainText(json.dumps(self.rows[index], ensure_ascii=False, indent=2) if 0 <= index < len(self.rows) else "")

    def copy_event(self):
        QApplication.clipboard().setText(self.detail.toPlainText())

    def performance_report(self):
        import time
        scheduler = self.window.scheduler
        children = getattr(scheduler, 'children', [scheduler]) if scheduler else []
        events = self.log.snapshot()
        run_jobs = set(getattr(scheduler, 'job_ids', []))
        events = [e for e in events if e.get('job_id') in run_jobs] if scheduler else []
        def average(field):
            category = 'saved' if field in ('database_seconds','validator_seconds') else 'parsed' if field in ('http_seconds','parse_seconds') else 'selected'
            measured = {e.get('attempt_id',e.get('batch_id')):e[field] for e in events
                        if e.get('event') in ({'parsed','failure'} if field=='http_seconds' else {category}) and isinstance(e.get(field),(int,float))}
            values = list(measured.values())
            return round(sum(values)/len(values),4) if values else 'unknown'
        def total(name): return sum(getattr(c,name,0) or 0 for c in children)
        elapsed = max(.001,time.monotonic()-(getattr(scheduler,'started_at',None) or time.monotonic()))
        return {'configured': getattr(scheduler,'configured_concurrency',self.window.concurrency.value()),
                'effective': total('effective_concurrency'), 'active_HTTP': total('active_http'),
                'ready': total('ready_batches'), 'waiting':total('waiting'), 'waiting_retries':total('waiting_retries'),
                'reserved_workers':total('active'),'lines_at_HTTP_start':total('sent_lines'),
                'cooldown_s': round(max(0, getattr(scheduler,'cooldown_until',0)-time.monotonic()),2),
                'queue_avg_s': average('queue_wait_seconds'), 'HTTP_avg_s':average('http_seconds'),
                'validator_avg_s':average('validator_seconds'), '429':total('rate_limits'),
                'lines_per_min':round(total('accepted_lines')*60/elapsed,1),
                '504':total('http_504'), 'retry':total('retry_count'),
                'completed_without_usage':total('request_count')-total('usage_received_count'),
                'known_usage': {k:sum(c.usage.get(k,0) for c in children if hasattr(c,'usage')) for k in ('prompt_tokens','completion_tokens','total_tokens')},
                'timing_scope':'bounded current-job metadata; unobserved = unknown'}

    def report(self):
        return json.dumps({"log_health": self.log.failure or "ok", "events": self.rows}, ensure_ascii=False, indent=2)

    def copy_report(self):
        self.reload()
        QApplication.clipboard().setText(self.report())

    def export_report(self):
        path, _ = QFileDialog.getSaveFileName(self, "Xuất chẩn đoán", "transcomic-diagnostics.json", "JSON (*.json);;Text (*.txt)")
        if path:
            self.reload()
            try:
                self.log.export(path, self.rows)
            except OSError as exc:
                QMessageBox.warning(self, "Không xuất được log", type(exc).__name__)

    def clear_view(self):
        if QMessageBox.question(self, 'Ẩn log', 'Ẩn các log đang xem? Log trên đĩa vẫn được giữ.', QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.hidden_until = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
        self.signature = None
        self.reload()

    def clear_saved(self):
        if QMessageBox.question(self, "Dọn nhật ký", "Xóa các file log đã lưu? Không xóa lịch sử dịch, API key hoặc tài liệu.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            try:
                self.log.clear()
                self.hidden_until = ''
                self.signature = None
                self.reload()
            except OSError as exc:
                QMessageBox.warning(self, "Không dọn được log", type(exc).__name__)
