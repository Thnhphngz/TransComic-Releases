"""Settings card using existing V3 widgets; HTTPS work stays outside Qt thread."""
from __future__ import annotations
import threading
import sys
from datetime import datetime
from PySide6.QtCore import QObject, Signal, QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QPlainTextEdit, QProgressBar,QApplication,QDialog
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
        from ..update.internal import InternalUpdateService
        self.service=service or InternalUpdateService();self.machine=InstallMachine()
        self.item=None;self.busy=False;self.cancel_event=threading.Event();self.worker=None
        self.downloaded_path=None;self.shutdown_event=threading.Event()
        self.manual_check_pending=False;self.update_dialog=None
        self.handoff_pending=False;self.handoff_session=None;self._update_timers=[]
        self.signals=UpdateSignals(self);self.signals.result.connect(self.receive,Qt.QueuedConnection)
        self.signals.progress.connect(self.show_progress,Qt.QueuedConnection)
        layout=QVBoxLayout(self);layout.setContentsMargins(20,18,20,18)
        title=QLabel('CẬP NHẬT ỨNG DỤNG');title.setObjectName('section');layout.addWidget(title)
        self.current=QLabel(f'Hiện tại: {VERSION} · Internal');layout.addWidget(self.current)
        source=QLabel('Nguồn: '+RELEASE_REPOSITORY);source.setObjectName('muted');layout.addWidget(source)
        self.auto=QCheckBox('Tự kiểm tra — tối đa một lần mỗi 24 giờ')
        self.auto.setChecked(window.store.setting('update_auto_check','1')=='1')
        self.auto.toggled.connect(self.set_auto);layout.addWidget(self.auto)
        self.status=QLabel('Chưa kiểm tra');self.status.setWordWrap(True);layout.addWidget(self.status)
        try:
            from ..update.windows_helper import update_receipt_message
            receipt_message=update_receipt_message(self.service.directory) if getattr(sys,'frozen',False) and not self.service.testing else ''
            if receipt_message:self.status.setText(receipt_message)
        except (OSError,ValueError):pass
        self.last=QLabel('Lần kiểm tra gần nhất: chưa có');layout.addWidget(self.last)
        self.safety=QLabel('Internal · HTTPS + SHA-256 · Chỉ cài sau khi thoát an toàn')
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
        if self.busy or self.update_dialog is not None:return
        self.manual_check_pending=manual
        self.machine.state=State.CHECKING
        self.status.setText('Đang kiểm tra…');self.start_work(lambda cancel:self.service.check(manual,cancel))

    def download_now(self):
        if self.window._closed or self.window._exit_pending:return
        if not self.item or self.item.signature_status not in ('VERIFIED_ED25519','VERIFIED_INTERNAL_HTTPS_SHA256') or self.busy:return
        if self.downloaded_path is not None and not self.service.testing:
            self.begin_native_install();return
        item=self.item;self.status.setText('Đang tải…')
        self.machine.state=State.DOWNLOADING
        def run(cancel):
            path=self.service.download(item,self.emit_progress,cancel)
            return {'kind':'downloaded','path':str(path)}
        self.start_work(run)

    def receive(self,result):
        if self.window._closed:
            if isinstance(result,dict) and result.get('kind')=='handoff_ready':result['session'].abort()
            return
        manual=self.manual_check_pending;self.manual_check_pending=False
        self.busy=False;self.check.setEnabled(True);self.cancel.setEnabled(False)
        if isinstance(result,dict):
            if result['kind']=='handoff_ready':
                self.handoff_pending=False;self.window._exit_pending=False
                self.handoff_session=result['session']
                if not native_install_idle(self.window) or self.cancel_event.is_set():
                    self.abort_handoff();return
                self.window._update_exit_requested=True
                self.window.close()
                return
            if self.handoff_pending:
                self.abort_handoff()
            if result['kind']=='installed_edition_required':
                self.status.setText('Đây là EXE chạy trực tiếp hoặc bản cài không khớp. Tự cập nhật chỉ hỗ trợ bản cài bằng Installer trong thư mục mặc định. Hãy dùng bản đã cài; không tự thay EXE hoặc báo đã cài cập nhật.')
                self.download.setEnabled(False)
                return
            if result['kind']=='downloaded':
                from pathlib import Path
                self.downloaded_path=Path(result['path'])
                self.machine.state=State.READY_TO_INSTALL
                if self.cancel_event.is_set():
                    self.machine.state=State.CANCELLED
                    self.status.setText('File đã tải nhưng cài đặt đã hủy · không chạy bộ cài.')
                    self.download.setEnabled(True)
                elif self.service.testing:
                    self.status.setText('Đã tải và xác minh — mô phỏng, không chạy bộ cài')
                else:
                    self.status.setText('Đã tải và xác minh · đang kiểm tra bàn giao an toàn…')
                    self.begin_native_install()
            elif result['kind']=='cancelled':
                self.machine.state=State.CANCELLED
                self.status.setText('Đã hủy tải; dữ liệu người dùng được giữ nguyên')
            else:
                self.machine.state=State.ERROR
                self.status.setText('Tải không thành công hoặc xác minh không đạt')
        else:
            self.machine.state=State(result.state) if result.state in State._value2member_map_ else State.IDLE
            if self.item!=result.candidate:self.downloaded_path=None
            self.item=result.candidate;self.status.setText(result.message)
            if result.cached:self.status.setText(result.message+' · Kết quả từ cache')
            self.last.setText('Lần kiểm tra gần nhất: '+datetime.fromtimestamp(result.checked_at).strftime('%d/%m/%Y %H:%M'))
            self.notes.setEnabled(bool(self.item));self.download.setEnabled(False)
            if self.item:
                self.current.setText(f'Hiện tại: {VERSION} · Mới nhất: {self.item.version} · '+('Internal' if self.item.signature_status=='VERIFIED_INTERNAL_HTTPS_SHA256' else 'Signed Stable'))
                self.changelog.setPlainText(self.item.changelog)
                self.bytes.setText(f'Dung lượng: {self.item.size:,} byte · Không tự tải')
                self.safety.setText(self.item.signature_status+'\nChỉ cập nhật bản đã cài; yêu cầu đóng và lưu dữ liệu an toàn')
                self.download.setEnabled(result.state=='UPDATE_AVAILABLE' and self.item.signature_status in ('VERIFIED_ED25519','VERIFIED_INTERNAL_HTTPS_SHA256'))
                if result.state=='UPDATE_AVAILABLE' and not result.cached:
                    self.window.statusBar().showMessage('Có phiên bản TransComic mới · xem Cài đặt',8000)
            else:self.changelog.clear()
            if manual and result.state=='UPDATE_AVAILABLE' and self.item and self.item.signature_status=='VERIFIED_INTERNAL_HTTPS_SHA256':
                self.offer_update(result.cached)

    def offer_update(self,cached=False):
        if self.update_dialog is not None or self.window._closed or self.window._exit_pending or QApplication.activeModalWidget() is not None:return
        from .update_dialog import UpdateDialog
        item=self.item;dialog=UpdateDialog(self.window,item,cached);self.update_dialog=dialog
        def finished(choice):
            self.update_dialog=None
            if choice==QDialog.Accepted and not self.window._closed and not self.window._exit_pending and self.item is item:
                self.window.pages.setCurrentIndex(3);self.download_now()
        dialog.finished.connect(finished)
        dialog.open()

    def show_progress(self,p):
        if self.window._closed:return
        self.progress.setValue(int(100*p.downloaded/max(1,p.total)))
        self.bytes.setText(f'{p.downloaded:,} / {p.total:,} byte · {p.bytes_per_second/1024:.1f} KB/s')

    def begin_native_install(self):
        if self.window._closed or self.window._exit_pending or self.service.testing or self.handoff_pending or self.handoff_session is not None:return
        if not getattr(sys,'frozen',False):
            self.status.setText('Đã tải và xác minh · tự cập nhật chỉ dùng trong bản đã cài bằng bộ cài.')
            return
        if not native_install_idle(self.window):
            self.status.setText('Hãy dừng công việc, chờ request hoàn tất và kết thúc sửa ô trước khi cài cập nhật.')
            self.download.setEnabled(True);return
        from ..update.windows_helper import HelperHandoff,prepare_install_plan,current_process_identity,registered_installation
        from ..update.install import SafetySnapshot
        service,item,path=self.service,self.item,self.downloaded_path
        if item is None or path is None or item.signature_status!='VERIFIED_INTERNAL_HTTPS_SHA256':return
        self.handoff_pending=True;self.window.setEnabled(False)
        self._update_timers=[]
        for name in ('local_timer','queue_timer','refresh_timer','layout_save_timer'):
            timer=getattr(self.window,name,None)
            if timer and timer.isActive():self._update_timers.append(timer);timer.stop()
        def prepare(cancel):
            try:
                installation=registered_installation()
                from pathlib import Path
                if Path(sys.executable).resolve()!=installation/'TransComic.exe':
                    return {'kind':'installed_edition_required'}
            except (ValueError,OSError):
                return {'kind':'installed_edition_required'}
            service.confirm_install(item,cancel)
            # This plan is an intent only; the helper cannot execute until a
            # separate COMMIT sent after Store/log close and process exit.
            raw,plan=prepare_install_plan(service,item,path,installation,current_process_identity(),
                SafetySnapshot(app_closed=True,safe_exit_verified=True))
            session=HelperHandoff(service.directory,installation,None,policy='internal').launch(raw,cancel)
            if cancel.is_set():session.abort();raise Cancelled('Handoff cancelled')
            return {'kind':'handoff_ready','session':session}
        self.start_work(prepare)
        self.window._exit_pending=True

    def abort_handoff(self):
        self.cancel_event.set()
        if self.handoff_session is not None:self.handoff_session.abort();self.handoff_session=None
        self.handoff_pending=False;self.window._exit_pending=False;self.window._update_exit_requested=False
        if not self.window._closed:
            self.window.setEnabled(True)
            for timer in self._update_timers:timer.start()
            self._update_timers=[]
            self.status.setText('Chưa cài cập nhật · bàn giao chưa an toàn hoặc đã hủy; dữ liệu được giữ nguyên.')
            self.download.setEnabled(bool(self.item and self.downloaded_path))

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
        item=self.item
        installation=__import__('pathlib').Path(process.image).parent
        internal=item.signature_status=='VERIFIED_INTERNAL_HTTPS_SHA256'
        from ..update.windows_helper import prepare_install_plan
        raw,plan=prepare_install_plan(self.service,item,self.downloaded_path,installation,process,snapshot,handoff)
        helper=ProductionUpdateHelper(self.service.directory,installation,runtime,self.service.keys,policy='internal' if internal else 'signed-stable')
        result=helper.run(plan,snapshot,self.cancel_event,handoff=handoff)
        self.status.setText('Mô phỏng helper Windows thành công; chưa cài thực tế')
        return result

    def open_notes(self):
        if self.item:QDesktopServices.openUrl(QUrl(self.item.url))
    def postpone(self):
        self.cancel_event.set();self.status.setText('Để sau — không tải hoặc cài tự động')
    def shutdown(self):
        self.shutdown_event.set();self.auto_timer.stop();self.cancel_event.set()
        if self.update_dialog is not None:self.update_dialog.reject()


def native_install_idle(window):
    """No scheduling, cancellation or request fencing is permitted for install."""
    from ..update.install import window_safety
    if window._closed:return False
    snapshot=window_safety(window)
    scheduler=window.scheduler
    return not (any(getattr(snapshot,n) for n in ('translating','paused','inflight','transaction','editing')) or
        getattr(scheduler,'active_http',0) or getattr(window,'import_busy',False) or
        getattr(window,'export_busy',False) or getattr(window,'queue_clear_busy',False) or
        getattr(window,'_exit_cancelled',False) or hasattr(window,'_exit_fence_thread') or
        any(t.is_alive() for t in getattr(window,'background_threads',[])))
