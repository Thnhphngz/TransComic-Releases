"""Offline native Qt screenshots; never loads the user's DB or calls an API."""
from __future__ import annotations

import argparse
import json
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from transcomic.documents import decode_txt
from transcomic.storage import Store
from transcomic.providers import BatchResult
from transcomic.translation import Scheduler
from transcomic.ui.exit_dialog import ExitDialog
from transcomic.ui.main import MainWindow
from transcomic.ui.window_state import monitor_inches, show_initial


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("artifacts/gui"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    with TemporaryDirectory() as temporary:
        store = Store(Path(temporary) / "smoke.sqlite3")
        source = "\n".join(f"Dòng {i}: một câu truyện ngắn." for i in range(100))
        doc, _ = store.import_document(Path(temporary) / "chapter.txt", decode_txt(source.encode()))
        window = MainWindow(store)
        show_initial(window)
        window.open_document(doc)
        QTest.qWait(80)
        report = {"screen": app.primaryScreen().name(), "device_pixel_ratio": window.devicePixelRatioF(),
                  "edid_inches": monitor_inches(window.screen()), "startup_reason": window.startup_reason,
                  "system_tray_available": QSystemTrayIcon.isSystemTrayAvailable(), "views": []}

        def snapshot(name):
            QTest.qWait(80)
            window.grab().save(str(args.output / f"{name}.png"))
            delegate = window.table.itemDelegate()
            editor = delegate.active_editor
            report["views"].append({"name": name, "window": [window.width(), window.height()],
                "viewport": [window.table.viewport().width(), window.table.viewport().height()],
                "visible_rows": [window.table.rowAt(0), window.table.rowAt(window.table.viewport().height()-1)],
                "font_px": window.table.font().pixelSize(), "editor_width": editor.width() if editor else None,
                "cell_width": window.table.visualRect(delegate.active_index).width() if editor else None})

        window.showMaximized()
        window.model.set_checked([1, 2, 3], True)
        snapshot("light_maximized")
        window.table.edit(window.model.index(3, 1))
        QTest.qWait(20)
        window.table.itemDelegate().active_editor.setPlainText("Bản dịch đang chỉnh sửa trực tiếp trên toàn bộ chiều rộng ô.")
        snapshot("light_editor")
        window.font_spin.setValue(22)
        snapshot("font_22px")
        window.toggle_theme()
        snapshot("dark_editor")
        window.showNormal()
        window.resize(1200, 720)
        snapshot("dark_1200")
        window.resize(900, 580)
        snapshot("dark_900")
        if QSystemTrayIcon.isSystemTrayAvailable():
            class MockProvider:
                async def translate(self, lines, source_lang, target_lang):
                    await asyncio.sleep(0.2)
                    return BatchResult({line["id"]: "Bản dịch mock" for line in lines})
            job_id = store.create_job(doc, "qwen3.8-flash", "English", "Vietnamese", 1)
            window.scheduler = Scheduler(store, MockProvider(), window.bridge.changed.emit)
            window.scheduler.start(job_id)
            QTest.qWait(30)
            report["tray_smoke"] = window.minimize_to_tray() and not window.isVisible() and window.scheduler._thread.is_alive()
            window.restore_from_tray()
            window.scheduler.stop()
            window.scheduler.join(2)
            QTest.qWait(30)
        dialog = ExitDialog(window, running=True, tray_available=QSystemTrayIcon.isSystemTrayAvailable())
        def capture_dialog():
            dialog.grab().save(str(args.output / "exit_dialog.png"))
            dialog.choose("cancel")
        QTimer.singleShot(80, capture_dialog)
        dialog.exec()
        window._exit_authorized = True  # Smoke harness teardown only.
        window.close()
        (args.output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
