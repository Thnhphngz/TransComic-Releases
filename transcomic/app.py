"""Application entry point."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from .storage import Store
from .ui.main import MainWindow
from .ui.window_state import show_initial


def data_path() -> Path:
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(root) / "TransComic" / "transcomic.sqlite3"


def main() -> int:
    if os.name == 'nt':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('TransComic.Desktop')
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    app = QApplication(sys.argv)
    app.setApplicationName("TransComic")
    window = MainWindow(Store(data_path()))
    show_initial(window)
    window.update_panel.start_auto()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
