"""Native Windows review tools smoke with the supplied DOCX and a temporary database."""
import json
from pathlib import Path
try:
    from scripts.test_runtime import TemporaryDirectory
except ModuleNotFoundError:
    from test_runtime import TemporaryDirectory
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidget
from transcomic.documents import ImportedText, TextLine
from transcomic.docx_document import import_docx
from transcomic.storage import Store
from transcomic.ui.main import MainWindow
from transcomic.ui.window_state import show_initial


def main():
    app = QApplication([])
    output = Path("artifacts/gui/review")
    output.mkdir(parents=True, exist_ok=True)
    imported = import_docx(r"D:\word 50 cach\7-8.docx")
    with TemporaryDirectory() as temporary:
        store = Store(Path(temporary) / "review.db")
        window = MainWindow(store)
        show_initial(window)
        QTest.qWait(80)
        window.grab().save(str(output / "empty_startup.png"))
        doc, _ = store.import_document(r"D:\word 50 cach\7-8.docx", ImportedText(tuple(TextLine(u.text, "") for u in imported.units), "docx", imported.raw), document_format="docx", locators=[u.locator for u in imported.units])
        window.open_document(doc)
        row = store.lines(doc)[25]
        store.edit_line(row["id"], "translation", "Say ah.")  # Intentionally wrong punctuation, not real model output.
        store.db.execute("UPDATE lines SET state='unknown',error='HTTP 504 (offline mock)' WHERE id=?", (row["id"],))
        window.refresh()
        window.navigate_to_line(row["id"])
        window.model.set_checked([25], True)
        window.search.open(True)
        window.search.query.setText("evelyn")
        window.search.replacement.setText("Evelyn")
        window.search.navigate(1)
        QTest.qWait(80)
        window.grab().save(str(output / "light_search_replace.png"))
        window.toggle_theme()
        window.resize(1000, 700)
        QTest.qWait(80)
        window.grab().save(str(output / "dark_1000_search.png"))
        window.resize(900, 580)
        QTest.qWait(80)
        window.grab().save(str(output / "dark_900_search.png"))
        def capture_warnings():
            dialog = app.activeModalWidget()
            dialog.grab().save(str(output / "warnings.png"))
            listing = dialog.findChild(QListWidget)
            item = next(listing.item(i) for i in range(listing.count()) if listing.item(i).data(Qt.UserRole) == row["id"])
            listing.itemClicked.emit(item)
        QTimer.singleShot(80, capture_warnings)
        window.show_warnings()
        assert window.table.currentIndex().row() == 25
        report = {"actual_dpr": window.devicePixelRatioF(), "units": len(imported.units), "search_occurrences": len(window.search.results),
                  "warning_unique_rows": len(window.editorial_rows), "navigated_line": window.table.currentIndex().row()+1,
                  "small_window": [window.width(), window.height()], "api_requests": 0, "semantic_translation_verified": False}
        window._exit_authorized = True
        window.close()
        (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
