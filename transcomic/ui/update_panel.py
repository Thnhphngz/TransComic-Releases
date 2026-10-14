"""Settings card using existing V3 widgets; HTTPS work stays outside Qt thread."""
from __future__ import annotations
import threading
from datetime import datetime
from PySide6.QtCore import QObject, Signal, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPlainTextEdit, QProgressBar
from .glass import GlassButton, PrimaryGlassButton
from ..version import VERSION, RELEASE_REPOSITORY
from ..update.service import UpdateService, Cancelled
from ..update.metadata import NOT_READY
from ..update.install import InstallMachine, State
from ..update.helper import ExternalHelper

class UpdateSignals(QObject):
    result=Signal(object)
    progress=Signal(object)

class UpdatePanel(QFrame):
    def __init__(self,window,service=None):
        super().__init__(window);self.window=window;self.setObjectName('card')
        self.service=service or UpdateService();self.machine=InstallMachine()
        self.item=None;self.busy=False;self.cancel_event=threading.Event();self.worker=None
        self.downloaded_path=None;self.shutdown_event=threading.Event()
        self.signals=UpdateSignals(self);self.signals.result.connect(self.receive,Qt.QueuedConnection)
        self.signals.progress.connect(self.show_progress,Qt.QueuedConnection)
        layout=QVBoxLayout(self);layout.setContentsMargins(20,18,20,18)
        title=QLabel('CẬP NHẬT ỨNG DỤNG');title.setObjectName('section');layout.addWidget(title)
        self.current=QLabel(f'Hiện tại: {VERSION} · Kênh Stable');layout.addWidget(self.current)
        source=QLabel('Nguồn: '+RELEASE_REPOSITORY);source.setObjectName('muted');layout.addWidget(source)
        self.auto=QCheckBox('Tự kiểm tra — tối đa một lần mỗi 24 giờ')
        self.auto.setChecked(window.store.setting('update_auto_check','1')=='1')
        self.auto.toggled.connect(self.set_auto);layout.addWidget(self.auto)
        self.status=QLabel('Chưa kiểm tra');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.last=QLabel('Lần kiểm tra gần nhất: chưa có');layout.addWidget(self.last)
        self.safety=QLabel('Chế độ phát triển — Chưa hỗ trợ cài đặt thực tế\n'+NOT_READY)
        self.safety.setWordWrap(True);layout.addWidget(self.safety)
        self.changelog=QPlainTextEdit();self.changelog.setReadOnly(True);self.changelog.setMaximumHeight(85)
        self.changelog.setPlaceholderText('Ghi chú phát hành sẽ xuất hiện tại đây');layout.addWidget(self.changelog)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);layout.addWidget(self.progress)
        self.bytes=QLabel('Không tự tải hoặc cài đặt');layout.addWidget(self.bytes)
        row=QHBoxLayout()
        self.check=GlassButton('Kiểm tra cập nhật');self.check.clicked.connect(lambda:self.check_now(True))
        self.notes=GlassButton('Ghi chú phát hành');self.notes.clicked.connect(self.open_notes);self.notes.setEnabled(False)
        self.download=PrimaryGlassButton('Tải và cài đặt');self.download.clicked.connect(self.download_now);self.download.setEnabled(False)
        self.cancel=GlassButton('Hủy tải');self.cancel.clicked.connect(lambda:self.cancel_event.set());self.cancel.setEnabled(False)
        self.later=GlassButton('Để sau');self.later.clicked.connect(self.postpone)
        for b in (self.check,self.notes,self.download,self.cancel,self.later):row.addWidget(b)
        layout.addLayout(row)
        self.auto_timer=QTimer(self);self.auto_timer.setInterval(60000);self.auto_timer.timeout.connect(self.auto_tick)

    def set_auto(self,checked):
        if not self.window._closed:self.window.store.set_setting('update_auto_check','1' if checked else '0')
        if not checked:self.cancel_event.set()

    def start_auto(self):
        self.auto_timer.start();QTimer.singleShot(2500,self.auto_tick)

    def auto_tick(self):
        if self.window._closed or self.window._exit_pending or not self.auto.isChecked() or self.busy:return
        scheduler=self.window.scheduler
        if scheduler and scheduler._thread and scheduler._thread.is_alive():return
        if any(t.is_alive() for t in getattr(self.window,'background_threads',[])):return
        # Cache I/O and the due check also happen in the worker.
        self.check_now(False)

    def start_work(self,fn):
        if self.busy or self.window._closed or self.window._exit_pending:return
        self.busy=True;self.cancel_event=threading.Event();cancel=self.cancel_event
        self.check.setEnabled(False);self.download.setEnabled(False);self.cancel.setEnabled(True)
        signal=self.signals
        def run():
            try: result=fn(cancel)
            except Cancelled:result={'kind':'cancelled'}
            except Exception:result={'kind':'error'}
            if not self.shutdown_event.is_set():
                try:signal.result.emit(result)
                except RuntimeError:pass  # Qt owner was destroyed during worker cancellation.
        self.worker=threading.Thread(target=run,daemon=True,name='TransComicUpdate');self.worker.start()

    def check_now(self,manual=True):
        if self.busy:return
        self.machine.state=State.CHECKING
        self.status.setText('Đang kiểm tra…');self.start_work(lambda cancel:self.service.check(manual,cancel))

    def download_now(self):
        if not self.item or self.item.signature_status!='VERIFIED_ED25519' or self.busy:return
        item=self.item;self.status.setText('Đang tải…')
        self.machine.state=State.DOWNLOADING
        def run(cancel):
            path=self.service.download(item,self.emit_progress,cancel)
            return {'kind':'downloaded','path':str(path)}
        self.start_work(run)

    def receive(self,result):
        if self.window._closed:return
        self.busy=False;self.check.setEnabled(True);self.cancel.setEnabled(False)
        if isinstance(result,dict):
            if result['kind']=='downloaded':
                from pathlib import Path
                self.downloaded_path=Path(result['path'])
                self.machine.state=State.READY_TO_INSTALL
                self.status.setText('Đã tải và xác minh — Stage A không chạy bộ cài')
            elif result['kind']=='cancelled':
                self.machine.state=State.CANCELLED
                self.status.setText('Đã hủy tải; dữ liệu người dùng được giữ nguyên')
            else:
                self.machine.state=State.ERROR
                self.status.setText('Tải không thành công hoặc xác minh không đạt')
        else:
            self.machine.state=State(result.state) if result.state in State._value2member_map_ else State.IDLE
            self.item=result.candidate;self.status.setText(result.message)
            self.last.setText('Lần kiểm tra gần nhất: '+datetime.fromtimestamp(result.checked_at).strftime('%d/%m/%Y %H:%M'))
            self.notes.setEnabled(bool(self.item));self.download.setEnabled(False)
            if self.item:
                self.current.setText(f'Hiện tại: {VERSION} · Mới nhất: {self.item.version} · Stable')
                self.changelog.setPlainText(self.item.changelog)
                self.bytes.setText(f'Dung lượng: {self.item.size:,} byte · Không tự tải')
                self.safety.setText(self.item.signature_status+'\nChế độ phát triển — Chưa hỗ trợ cài đặt thực tế')
                self.download.setEnabled(result.state=='UPDATE_AVAILABLE' and self.item.signature_status=='VERIFIED_ED25519')
                if result.state=='UPDATE_AVAILABLE' and not result.cached:
                    self.window.statusBar().showMessage('Có phiên bản TransComic mới · xem Cài đặt',8000)
            else:self.changelog.clear()

    def show_progress(self,p):
        if self.window._closed:return
        self.progress.setValue(int(100*p.downloaded/max(1,p.total)))
        self.bytes.setText(f'{p.downloaded:,} / {p.total:,} byte · {p.bytes_per_second/1024:.1f} KB/s')

    def emit_progress(self,p):
        if not self.shutdown_event.is_set():
            try:self.signals.progress.emit(p)
            except RuntimeError:pass

    def simulate_helper(self,identity,process,snapshot,installer,environment,**kwargs):
        """Test-only handoff through the same downloaded file/verifier; no UI install activation."""
        if not self.downloaded_path or not self.item:raise ValueError('Verified mock download required')
        if not self.service.testing:raise ValueError('B1 requires mock update service')
        helper=ExternalHelper()
        result=helper.simulate_update(self.downloaded_path,identity,process,snapshot,installer,
            lambda p:self.service.verify_file(p,self.item),self.item.version,environment,**kwargs)
        self.machine.state=helper.state
        self.status.setText('Mô phỏng helper: '+('thành công; chưa cài thực tế' if result['success'] else 'đang chặn hoặc thất bại; chưa cài thực tế'))
        return result

    def simulate_production_helper(self,process,snapshot,runtime,handoff=None):
        """Exercise production helper algorithm using the same verified mock download/cache."""
        from ..update.windows_helper import ProductionUpdateHelper,InstallPlan,FakeWindowsRuntime
        if not self.service.testing or type(runtime) is not FakeWindowsRuntime or not self.item or not self.downloaded_path:
            raise ValueError('Verified mock update and concrete mock runtime required')
        release=self.service._cache()['release'];item=self.item
        installation=__import__('pathlib').Path(process.image).parent
        helper=ProductionUpdateHelper(self.service.directory,installation,runtime,self.service.keys)
        plan=InstallPlan(item.version,self.downloaded_path,item.size,item.sha256,release,
                         {'payload':item.payload,'signature':item.signature},process)
        result=helper.run(plan,snapshot,self.cancel_event,handoff=handoff)
        self.status.setText('Mô phỏng helper Windows thành công; chưa cài thực tế')
        return result

    def open_notes(self):
        if self.item:QDesktopServices.openUrl(QUrl(self.item.url))
    def postpone(self):
        self.cancel_event.set();self.status.setText('Để sau — không tải hoặc cài tự động')
    def shutdown(self):
        self.shutdown_event.set();self.auto_timer.stop();self.cancel_event.set()
