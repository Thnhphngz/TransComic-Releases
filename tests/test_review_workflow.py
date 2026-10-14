import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QListWidget

from transcomic.documents import decode_txt, ImportedText, TextLine
from transcomic.docx_document import import_docx, render_docx
from transcomic.prompts import messages
from transcomic.providers import KiraProvider, parse_line_response
from transcomic.quality import warnings
from transcomic.storage import Store
from transcomic.translation import Scheduler
from transcomic.ui.main import MainWindow
from transcomic.ui.model import line_label

FIXTURE = json.loads((Path(__file__).parent / "fixtures/review_7_8.json").read_text(encoding="utf-8"))


def workspace(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "workflow.db")
    doc, _ = store.import_document(tmp_path / "story.txt", decode_txt("\n".join(f"Evelyn nói, cael nghe {i}" for i in range(12)).encode()))
    window = MainWindow(store)
    window.show()
    window.open_document(doc)
    app.processEvents()
    return app, store, window, doc


def test_empty_startup_preserves_history_key_settings_and_unknown(tmp_path):
    app, store, window, doc = workspace(tmp_path)
    window.source_lang.setCurrentText("Tiếng Việt")
    window.target_lang.setCurrentText("Tiếng Anh")
    window.set_model_id("glm-5.3-flash")
    window.concurrency.setValue(7)
    store.save_key(b"offline-encrypted-fixture")
    job = store.create_job(doc, "glm-5.3-flash", "Tiếng Việt", "Tiếng Anh", 1)
    batch = store.batches(job)[0]
    store.claim_batch(batch["id"])
    store.finish_batch(batch["id"], {}, "HTTP 504", True)
    store.job_state(job, "finished")
    window.close()
    reopened_store = Store(tmp_path / "workflow.db")
    reopened = MainWindow(reopened_store)
    assert reopened.doc_id is None and reopened.model.rowCount() == 0
    assert reopened.pages.currentIndex() == 0 and reopened.scheduler is None
    assert len(reopened_store.documents()) == 1
    assert reopened_store.load_key() == b"offline-encrypted-fixture"
    assert reopened.source_lang.currentText() == "Tiếng Việt" and reopened.target_lang.currentText() == "Tiếng Anh"
    assert reopened.selected_model_id() == "glm-5.3-flash" and reopened.concurrency.value() == 7
    assert reopened_store.batches(job)[0]["state"] == "unknown"
    reopened.pages.setCurrentIndex(1)
    reopened.job_list.setCurrentRow(0)
    reopened.show_job_document()
    assert reopened.model.rowCount() == 12
    reopened.close()


def test_choice_only_and_invalid_saved_model(tmp_path):
    app, store, window, doc = workspace(tmp_path)
    for combo in (window.source_lang, window.target_lang, window.model_name):
        assert not combo.isEditable()
        before = combo.currentText()
        combo.setCurrentText(before+"dsf")
        assert combo.currentText() == before
    window.set_model_id("removed-model")
    assert window.selected_model_id() == ""
    window.source_lang.setCurrentText("Tiếng Việt")
    window.target_lang.setCurrentText("Tiếng Việt")
    assert window.source_lang.currentText() == window.target_lang.currentText()
    window.close()


@pytest.mark.parametrize("repeat", [1, 60])
def test_open_editor_caret_start_click_and_typing(tmp_path, repeat):
    app, store, window, doc = workspace(tmp_path)
    window.model.setData(window.model.index(0, 1), "Evelyn kể lại câu chuyện " * repeat)
    index = window.model.index(0, 1)
    QTest.mouseClick(window.table.viewport(), Qt.LeftButton, pos=window.table.visualRect(index).center())
    app.processEvents()
    editor = window.table.itemDelegate().active_editor
    assert editor.textCursor().position() == 0 and not editor.textCursor().hasSelection()
    QTest.keyClicks(editor, "A")
    assert editor.textCursor().position() == 1
    assert editor.toPlainText().startswith("AEvelyn")
    window.close()


def test_search_shortcuts_all_rows_no_typing_scroll_replace_and_undo(tmp_path, monkeypatch):
    app, store, window, doc = workspace(tmp_path)
    for i in range(12):
        window.model.setData(window.model.index(i, 1), f"Evelyn nghe tiếng Việt {i}")
    QTest.keyClick(window, Qt.Key_F, Qt.ControlModifier)
    app.processEvents()
    assert window.search.isVisible()
    search = window.search
    search.query.setText("tiếng Việt")
    assert len(search.results) == 12
    search.query.setText("Evelyn")
    assert len(search.results) == 24
    scroll = window.table.verticalScrollBar().value()
    search.query.setText("cael")
    assert window.table.verticalScrollBar().value() == scroll
    search.navigate(-1)
    assert window.table.currentIndex().row() == 11
    search.navigate(1)
    assert window.table.currentIndex().row() == 0
    QTest.keyClick(window, Qt.Key_H, Qt.ControlModifier)
    app.processEvents()
    assert search.replace_row.isVisible()
    search.query.setText("Evelyn")
    search.replacement.setText("Emily")
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    search.replace_all()
    assert all(r["translation"].startswith("Emily") and r["source"].startswith("Evelyn") for r in store.lines(doc))
    search.undo()
    assert all(r["translation"].startswith("Evelyn") for r in store.lines(doc))
    search.scope.setCurrentIndex(2)
    search.navigate(1)
    search.replace_current()
    assert store.lines(doc)[0]["translation"].startswith("Emily")
    assert store.lines(doc)[1]["translation"].startswith("Evelyn")
    window.table.setCurrentIndex(window.model.index(1, 1))
    search.replace_cell()
    assert store.lines(doc)[1]["translation"].startswith("Emily")
    window.close()


def test_replace_source_stale_and_late_api_protected(tmp_path):
    app, store, window, doc = workspace(tmp_path)
    row = store.lines(doc)[0]
    store.edit_line(row["id"], "translation", "Old translation")
    job = store.create_job(doc, "kira-2.5-flash", "VI", "EN", 1, [row["id"]])
    batch = store.batches(job)[0]
    store.claim_batch(batch["id"])
    window.refresh()
    search = window.search
    search.apply([(row["id"], "source", "Emily kể chuyện")])
    assert store.line(row["id"])["state"] == "stale"
    search.apply([(row["id"], "translation", "New manual text")])
    store.finish_batch(batch["id"], {row["id"]: "Late API"})
    assert store.line(row["id"])["translation"] == "New manual text"
    window.refresh()
    assert window.dirty_export and "chưa xuất" in window.export_button.toolTip()
    window.close()


def test_replace_preview_cancel_unicode_undo_groups_and_timecode(tmp_path, monkeypatch):
    app, store, window, doc = workspace(tmp_path)
    row = store.lines(doc)[0]
    search = window.search
    search.apply([(row["id"], "translation", "😀 tiếng Việt tiếng Việt")])
    search.open(True)
    search.query.setText("tiếng Việt")
    search.replacement.setText("tên riêng")
    search.scope.setCurrentIndex(2)
    assert len(search.results) == 2
    edits, count = search.plan(window.model.all_rows)
    assert len(edits) == 1 and count == 2
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    search.replace_all()
    assert store.line(row["id"])["translation"] == "😀 tiếng Việt tiếng Việt"
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    search.replace_all()
    search.undo()
    assert store.line(row["id"])["translation"] == "😀 tiếng Việt tiếng Việt"
    search.undo()
    assert store.line(row["id"])["translation"] is None
    timecode = "00:00:01,000 --> 00:00:02,000"
    store.edit_line(row["id"], "source", timecode)
    search.apply([(row["id"], "source", "tampered")])
    assert store.line(row["id"])["source"] == timecode
    window.close()


def test_search_highlight_is_painted_not_only_counted(tmp_path):
    app, store, window, doc = workspace(tmp_path)
    window.search.open()
    window.search.query.setText("Evelyn")
    app.processEvents()
    picture = window.table.viewport().grab().toImage()
    assert any(picture.pixelColor(x, y).name() == "#e2ac63" for y in range(picture.height()) for x in range(picture.width()))
    window.close()


def test_partial_finished_shows_review_status_no_eta_and_saves_versions(tmp_path):
    app, store, window, doc = workspace(tmp_path)
    selected = store.lines(doc)[:3]
    store.edit_line(selected[0]["id"], "translation", "Old")
    job = store.create_job(doc, "kira-2.5-flash", "VI", "EN", 1, [r["id"] for r in selected])
    batch = store.batches(job)[0]
    store.claim_batch(batch["id"])
    store.finish_batch(batch["id"], {selected[0]["id"]: "New"}, "Missing response line IDs")
    store.job_state(job, "finished")
    window.scheduler = Scheduler(store, KiraProvider("fake"))
    window.scheduler.job_id = job
    window.current_job_ids = {r["id"] for r in selected}
    window.refresh()
    assert "còn 2 dòng" in window.active_label.text()
    assert "ETA" not in window.stats_label.text()
    assert window.total_progress.value() == 33
    version = store.db.execute("SELECT old_value,new_value FROM line_edits WHERE line_id=? ORDER BY id DESC", (selected[0]["id"],)).fetchone()
    assert tuple(version) == ("Old", "New")
    window.close()


@pytest.mark.parametrize("content", ['Here is JSON: {"lines":[{"id":"a","text":"A"}]}', '```json\n{"lines":[{"text":"A"}]}\n```', '```json\n{"lines":[{"id":"a","text":"A"},{"id":"a","text":"B"}]}\n```'])
def test_wrapper_normalization_never_guesses_ids(content):
    result = parse_line_response(content, {"a"})
    assert not result.values and result.error


@pytest.mark.parametrize("count", [1, 3, 5])
@pytest.mark.parametrize("state", ["error", "unknown", "done", "pending"])
def test_manual_retranslation_exact_selection_old_model_and_no_retry(tmp_path, monkeypatch, count, state):
    app, store, window, doc = workspace(tmp_path)
    original = store.create_job(doc, "qwen3.8-27b", "Tiếng Việt", "Tiếng Anh", 1)
    store.job_state(original, "finished")
    selected = store.lines(doc)[:count]
    for row in selected:
        store.edit_line(row["id"], "translation", "Old valid")
        store.db.execute("UPDATE lines SET state=?,error=? WHERE id=?", (state, "HTTP 504" if state == "unknown" else "Invalid ID", row["id"]))
    window.refresh()
    window.model.set_checked(list(range(count)), True)
    window.set_model_id("glm-5.3-flash")
    captured = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    monkeypatch.setattr(window, "_key", lambda: "fake")
    monkeypatch.setattr(Scheduler, "start", lambda self, job: captured.append(job))
    window.retry_selected()
    assert len(captured) == 1
    job = store.job(captured[0])
    batches = store.batches(job["id"])
    assert job["model"] == "qwen3.8-27b"
    assert len(batches) == (count+2)//3
    assert {r["id"] for b in batches for r in b["payload"]} == {r["id"] for r in selected}
    for batch in batches:
        store.claim_batch(batch["id"])
        assert line_label(store.line(batch["payload"][0]["id"])) == "Đang dịch lại"
        store.finish_batch(batch["id"], {}, "HTTP 504", True)
    assert all(store.line(r["id"])["translation"] == "Old valid" for r in selected)
    assert all(b["state"] == "unknown" for b in store.batches(job["id"]))
    assert all(line_label(store.line(r["id"])) == "Không rõ kết quả dịch lại" for r in selected)
    window.close()


def test_retry_cancel_and_hidden_selection_never_dispatch(tmp_path, monkeypatch):
    app, store, window, doc = workspace(tmp_path)
    window.model.set_checked([0, 1], True)
    store.edit_line(window.model.rows[0]["id"], "translation", "Done")
    window.refresh()
    window.filter_combo.setCurrentIndex(3)
    captured = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.No)
    monkeypatch.setattr(window, "_key", lambda: captured.append("key") or "fake")
    window.retry_selected()
    assert not captured and not store.jobs()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    monkeypatch.setattr(Scheduler, "start", lambda self, job: captured.append(job))
    window.retry_selected()
    assert len(store.batches(captured[-1])[0]["payload"]) == 1
    window.close()


def warning_row(source, translation, state="done", error=None):
    return {"source": source, "translation": translation, "state": state, "error": error}


@pytest.mark.parametrize("source,target,expected", [("cô nghĩ, anh đã về", "She thought. He returned.", "Thêm dấu chấm"), ("xin chào", "Hello!", "Dấu câu cuối"), ("xin chào {name}", "Hello", "Placeholder"), ("Dr. Cael trả 3.5", "Dr. Cael pays 3.5", None), ("xem https://example.com/a.b", "see https://example.com/a.b", None)])
def test_punctuation_heuristics_safe(source, target, expected):
    found = warnings(warning_row(source, target))
    if expected:
        assert expected in {kind for kind, _ in found}
    else:
        assert not found


def test_warning_unique_count_revisions_navigation_and_local_edit(tmp_path):
    app, store, window, doc = workspace(tmp_path)
    row = store.lines(doc)[2]
    store.edit_line(row["id"], "translation", "She thinks. He returns.")
    store.db.execute("UPDATE lines SET state='unknown',error='HTTP 504' WHERE id=?", (row["id"],))
    window.refresh()
    warning = next(r for r in window.editorial_rows if r["id"] == row["id"])
    assert len(warning["warnings"]) >= 3
    assert len([r for r in window.editorial_rows if r["id"] == row["id"]]) == 1
    window.filter_combo.setCurrentIndex(1)
    window.navigate_to_line(row["id"])
    assert window.filter_combo.currentIndex() == 0 and window.table.currentIndex().row() == 2
    assert store.line(row["id"])["translation"] == "She thinks. He returns."
    window.model.setData(window.model.index(2, 1), "she thinks, he returns")
    QTest.qWait(200)
    assert row["id"] not in {r["id"] for r in window.editorial_rows}
    assert not store.db.execute("SELECT * FROM quality_warnings WHERE line_id=?", (row["id"],)).fetchone()
    window.close()


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: c["category"])
def test_review_fixture_prompt_context_ids_schema(case):
    line = case["line"]
    old = messages([line], "VI", "EN", "legacy-v1")
    new = messages([line], "VI", "EN")
    payload = json.loads(new[1]["content"])
    assert payload["lines"] == [{"id": line["id"], "text": line["source"]}]
    assert line["id"] not in {r["id"] for r in payload["reference_only"]}
    assert 4 <= len(payload["reference_only"]) <= 8
    assert "reference_only" not in json.loads(old[1]["content"])
    assert "final periods" in new[0]["content"]
    if case["ordinal"] == 25:
        assert line["source"] == "nói a đi"
        assert any("thìa" in r["text"] for r in payload["reference_only"])
        assert "Say ah" in case["reference_options"]
    output = {"lines": [{"id": line["id"], "text": "Say ah" if case["ordinal"] == 25 else "Mock translation"}]}
    result = parse_line_response("```json\n"+json.dumps(output)+"\n```", {line["id"]})
    assert not result.error and len(result.values) == 1


def test_actual_docx_snapshot_context_export_unchanged_original(tmp_path):
    from scripts.docx_fixture_budget import LEDGER, reserve, complete
    pass_number = reserve('pytest actual DOCX regression') if LEDGER.exists() else None
    if LEDGER.exists() and pass_number is None:
        pytest.skip('User authorized maximum three document tests; reserved budget exhausted')
    source = Path(r"D:\word 50 cach\7-8.docx")
    if not source.exists():
        pytest.skip("User Word file not present on this machine; portable fixture tests still run")
    before = source.read_bytes()
    imported = import_docx(source)
    assert hashlib.sha256(before).hexdigest() == FIXTURE["source_sha256"]
    store = Store(tmp_path / "actual.db")
    doc, _ = store.import_document(source, ImportedText(tuple(TextLine(u.text, "") for u in imported.units), "docx", imported.raw), document_format="docx", locators=[u.locator for u in imported.units])
    row = store.lines(doc)[25]
    job = store.create_job(doc, "kira-2.5-flash", "Tiếng Việt", "Tiếng Anh", 1, [row["id"]])
    batch = store.batches(job)[0]
    assert len(batch["payload"][0]["context"]) == 8
    assert any("thìa" in r["source"] for r in batch["payload"][0]["context"])
    seen = []
    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"lines": [{"id": row["id"], "text": "Say ah"}]})}}]})
    scheduler = Scheduler(store, KiraProvider("fake", transport=httpx.MockTransport(handler)))
    scheduler.start(job)
    scheduler.join(5)
    assert len(seen) == 1 and store.line(row["id"])["translation"] == "Say ah"
    result, missing = render_docx(before, store.units(doc))
    output = tmp_path / "translated.docx"
    output.write_bytes(result)
    reimported = import_docx(output)
    assert len(reimported.units) == 125 and reimported.units[25].text == "Say ah"
    assert [u.locator for u in reimported.units] == [u.locator for u in imported.units]
    assert source.read_bytes() == before
    store.close()
    if pass_number: complete(pass_number)
