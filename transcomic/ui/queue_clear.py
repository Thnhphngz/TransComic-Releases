"""Confirmed background queue deletion, owning thread retained through Safe Exit."""
import threading
from PySide6.QtCore import QObject,Signal,Qt
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel
from .glass import GlassButton

BUSY='Hãy dừng quá trình dịch và chờ các tác vụ hiện tại kết thúc trước khi xóa toàn bộ.'


def idle(window):
    scheduler=window.scheduler
    thread=getattr(scheduler,'_thread',None)
    return not (window._closed or window._exit_pending or
        getattr(window,'import_busy',False) or getattr(window,'export_busy',False) or
        (thread and thread.is_alive()) or getattr(scheduler,'active',0) or getattr(scheduler,'active_http',0) or
        any(t.is_alive() for t in getattr(window,'background_threads',[]) if t is not threading.current_thread()))


class ClearDialog(QDialog):
    def __init__(self,parent,count):
        super().__init__(parent);self.setWindowTitle('Xóa toàn bộ lượt dịch?')
        layout=QVBoxLayout(self)
        label=QLabel(f'Thao tác này sẽ xóa {count} lượt dịch và các thông tin hàng đợi/lịch sử liên quan. Không thể hoàn tác.\nTài liệu, bản dịch đã lưu, file xuất, API key và cấu hình được giữ lại.')
        label.setWordWrap(True);layout.addWidget(label)
        row=QHBoxLayout();cancel=GlassButton('Hủy');confirm=GlassButton('Xóa toàn bộ')
        cancel.clicked.connect(self.reject);confirm.clicked.connect(self.accept)
        row.addStretch();row.addWidget(cancel);row.addWidget(confirm);layout.addLayout(row)
        cancel.setDefault(True);cancel.setFocus();self.resize(500,180)


class ClearSignals(QObject):
    done=Signal(bool,str)


def clear_all(window):
    if getattr(window,'queue_clear_busy',False):return
    if not idle(window):window.notice.setText(BUSY);window.statusBar().showMessage(BUSY,10000);return
    entries={r['entry_id'] for r in window.store.history()}
    if not entries:window.clear_all_jobs_button.setEnabled(False);return
    window.queue_clear_busy=True;window.clear_all_jobs_button.setEnabled(False)
    if not window.confirm_clear_all(len(entries)):
        window.queue_clear_busy=False;window.clear_all_jobs_button.setEnabled(True);return
    if not idle(window):
        window.queue_clear_busy=False;window.notice.setText(BUSY);window.clear_all_jobs_button.setEnabled(True);return
    signals=ClearSignals(window);window.queue_clear_signals=signals
    def done(ok,message):
        window.queue_clear_busy=False
        if window._closed:return
        if ok:
            window.scheduler=None;window.current_job_ids.clear()
            window.job_list.clear();window.job_list.setCurrentRow(-1)
        window.refresh();window.notice.setText(message);window.statusBar().showMessage(message,10000)
    signals.done.connect(done,Qt.QueuedConnection)
    def run():
        try:
            count=window.store.clear_queue_history(entries,lambda:idle(window))
            ok=True;message=f'Đã xóa {count} lượt dịch; tài liệu và bản dịch được giữ lại.'
        except Exception:
            ok=False;message='Không thể xóa: tác vụ/danh sách đã thay đổi hoặc SQLite chưa sẵn sàng. Dữ liệu được giữ lại.'
        try:signals.done.emit(ok,message)
        except RuntimeError:pass
    worker=threading.Thread(target=run,name='TransComicQueueClear',daemon=True)
    window.background_threads=getattr(window,'background_threads',[])+[worker]
    worker.start()
