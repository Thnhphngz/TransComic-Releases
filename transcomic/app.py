"""Application entry point."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt,QTimer

from .storage import Store
from .ui.main import MainWindow
from .ui.window_state import show_initial


def data_path() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(root) / "TransComic" / "transcomic.sqlite3"


def main() -> int:
    if '--tts-distribution-smoke' in sys.argv:
        from .distribution_smoke import main as smoke
        return smoke()
    if '--tts-v4-smoke' in sys.argv:
        if getattr(sys,'frozen',False):return 2
        from .tts.v4_smoke import main as smoke
        return smoke()
    if '--tts-crash-smoke' in sys.argv:
        if getattr(sys,'frozen',False):return 2
        from .tts.crash_smoke import main as smoke
        return smoke()
    if '--tts-source-smoke' in sys.argv:
        if getattr(sys,'frozen',False):return 2  # Developer-only isolated harness.
        from .tts.source_smoke import main as smoke
        return smoke()
    if '--local-build-smoke' in sys.argv:
        from .local_build_smoke import main as smoke
        return smoke()
    from .update.timing import startup_trace
    trace=getattr(sys,'_transcomic_startup_trace',None) or startup_trace(sys.argv[1:],data_path().parent/'Updates')
    if os.name == 'nt':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('TransComic.Desktop')
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    app = QApplication(sys.argv)
    trace.event('qt_ready')
    app.setApplicationName("TransComic")
    if os.name=='nt':
        from .update.windows_helper import check_application_start,acquire_application_mutex
        from .update.metadata import UpdateError
        try:
            check_application_start()
            # Inno checks this same mutex; another live instance must block
            # replacement rather than be force-closed by the installer.
            app._transcomic_install_mutex=acquire_application_mutex()
        except UpdateError:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(None,'Cập nhật chưa hoàn tất','Đang cập nhật hoặc cần kiểm tra kết quả cài đặt. Không chạy lại bộ cài khi kết quả chưa rõ. Xem thư mục Updates trong dữ liệu TransComic.')
            return 2
    trace.event('startup_guard_finished')
    with trace.span('database_open'):store=Store(data_path())
    with trace.span('window_create'):window=MainWindow(store)
    if getattr(sys,'frozen',False):
        from .ui.startup_ack import StartupAcknowledgement
        from .update.windows_helper import acknowledge_restart
        window._startup_ack=StartupAcknowledgement(window,lambda:acknowledge_restart(sys.argv[1:]),trace)
    trace.event('window_show_requested')
    show_initial(window)
    window.update_panel.start_auto()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
