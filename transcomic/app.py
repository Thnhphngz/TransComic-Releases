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
    if os.name == 'nt':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('TransComic.Desktop')
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    app = QApplication(sys.argv)
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
    window = MainWindow(Store(data_path()))
    show_initial(window)
    if getattr(sys,'frozen',False):
        def startup_ack():
            if not window.isVisible() or window._closed:return
            from .update.windows_helper import acknowledge_restart
            try:acknowledge_restart(sys.argv[1:])
            except Exception:window.store.log.emit('shutdown_error',exception='StartupAcknowledgementFailed')
        QTimer.singleShot(0,startup_ack)
    window.update_panel.start_auto()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
