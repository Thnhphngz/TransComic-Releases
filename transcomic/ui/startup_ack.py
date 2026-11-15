"""Acknowledge restart after a real paint and a subsequent GUI event turn."""
from PySide6.QtCore import QObject,QEvent,QTimer


class StartupAcknowledgement(QObject):
    def __init__(self,window,callback,trace):
        super().__init__(window);self.window=window;self.callback=callback;self.trace=trace;self.queued=False;self.done=False
        window.installEventFilter(self);window.update()

    def eventFilter(self,watched,event):
        if watched is self.window and event.type()==QEvent.Paint and not self.queued:
            self.queued=True;self.trace.event('window_painted');QTimer.singleShot(0,self.after_paint)
        return False

    def after_paint(self):
        # Let queued work/UI input have another turn; no fixed startup sleep.
        QTimer.singleShot(0,self.acknowledge)

    def acknowledge(self):
        w=self.window
        if self.done or not w.isVisible() or getattr(w,'_closed',False) or getattr(w,'_exit_pending',False):return
        self.done=True
        try:
            with self.trace.span('startup_ack'):self.callback()
        except Exception:
            # Receipt remains absent: the old/new helper must not report success.
            if hasattr(w,'update_panel'):w.update_panel.status.setText('Chưa xác nhận khởi động sau cập nhật. Xem log update-timing trong thư mục Updates.')
            if hasattr(w,'store'):w.store.log.emit('shutdown_error',exception='StartupAcknowledgementFailed')
        finally:w.removeEventFilter(self)
