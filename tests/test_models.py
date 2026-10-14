import asyncio
import json
import time
from pathlib import Path

import httpx
import pytest
from PySide6.QtWidgets import QApplication

from transcomic.documents import decode_txt
from transcomic.models import KIRA_MODELS
from transcomic.providers import KiraProvider
from transcomic.storage import Store
from transcomic.translation import Scheduler
from transcomic.ui.main import MainWindow


def test_model_selection_persists_and_job_snapshot(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "models.db")
    window = MainWindow(store)
    assert {"kira-2.5-flash", "kira-auto", "kira-mini-1.0", "qwen3.8-27b", "qwen3.8-flash"} <= {model for _, model in KIRA_MODELS}
    assert {window.model_name.itemData(i) for i in range(window.model_name.count())} == {model for _, model in KIRA_MODELS}
    window.set_model_id("qwen3.8-27b")
    assert window.selected_model_id() == "qwen3.8-27b"
    assert store.setting("kira_model") == "qwen3.8-27b"
    doc_id, _ = store.import_document(tmp_path / "chapter.txt", decode_txt(b"Hello"))
    job_id = store.create_job(doc_id, window.selected_model_id(), "English", "Vietnamese", 1)
    provider = KiraProvider("secret", store.job(job_id)["model"])
    window.set_model_id("qwen3.8-flash")
    assert store.setting("kira_model") == "qwen3.8-flash"
    assert store.job(job_id)["model"] == provider.model == "qwen3.8-27b"
    window.close()
    reopened_store = Store(tmp_path / "models.db")
    reopened = MainWindow(reopened_store)
    assert reopened.selected_model_id() == "qwen3.8-flash"
    reopened.close()


@pytest.mark.parametrize("status", [400, 403, 404])
def test_exact_model_request_and_no_fallback(status: int):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(status, json={"error": {"message": "unknown model"}})

    result = asyncio.run(KiraProvider("secret", "qwen3.8-flash", transport=httpx.MockTransport(handler)).translate(
        [{"id": "line-1", "source": "Hello"}], "English", "Vietnamese"))
    assert len(seen) == 1
    assert seen[0]["model"] == "qwen3.8-flash"
    assert "qwen3.8-flash" in result.error and str(status) in result.error
    assert not result.values and not result.unknown


def test_running_job_keeps_model_when_dropdown_changes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "running.db")
    doc_id, _ = store.import_document(tmp_path / "chapter.txt", decode_txt("\n".join(f"Line {i}" for i in range(9)).encode()))
    window = MainWindow(store)
    window.set_model_id("qwen3.8-27b")
    job_id = store.create_job(doc_id, window.selected_model_id(), "English", "Vietnamese", 1)
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body["model"])
        time.sleep(0.03)
        payload = json.loads(body["messages"][1]["content"])
        lines = [{"id": row["id"], "text": "VI " + row["text"]} for row in payload["lines"]]
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"lines": lines})}}]})

    scheduler = Scheduler(store, KiraProvider("fake", store.job(job_id)["model"], transport=httpx.MockTransport(handler)))
    scheduler.start(job_id)
    window.set_model_id("qwen3.8-flash")
    scheduler.join(5)
    assert seen == ["qwen3.8-27b"] * 3
    assert all(row["state"] == "done" for row in store.lines(doc_id))
    window.close()
