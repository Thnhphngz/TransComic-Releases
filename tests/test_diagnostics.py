import asyncio
import json

import httpx
import pytest

from transcomic.documents import decode_txt
from transcomic.models import KIRA_MODELS
from transcomic.providers import KiraProvider
from transcomic.storage import Store
from transcomic.translation import Scheduler


@pytest.mark.parametrize("model", ["coding-mimo-v2.6-flash", "deepseek-v4.1-flash", "glm-5.3-flash"])
def test_new_models_send_exact_ids(model):
    assert model in {identifier for name, identifier in KIRA_MODELS}
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body["model"])
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"lines":[{"id":"a","text":"Translated"}]}'}}]})

    result = asyncio.run(KiraProvider("test-key", model, transport=httpx.MockTransport(handler)).translate([{"id": "a", "source": "Hello"}], "English", "Vietnamese"))
    assert result.values == {"a": "Translated"} and calls == [model]


@pytest.mark.parametrize("exception", [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout])
def test_client_timeout_diagnostics(exception):
    calls = []

    def handler(request):
        calls.append(request)
        raise exception("timeout")

    result = asyncio.run(KiraProvider("private-key", "qwen3.8-27b", timeout=120, transport=httpx.MockTransport(handler)).translate([{"id": "a", "source": "Private story text"}], "English", "Vietnamese"))
    assert len(calls) == 1 and result.unknown
    metadata = result.diagnostics
    assert metadata["failure_kind"] == "client_timeout"
    assert metadata["timeout_type"] == exception.__name__
    assert metadata["timeout_seconds"]["read"] == 120
    assert metadata["timeout_seconds"]["connect"] == 10
    assert "Private story text" not in json.dumps(metadata)
    assert "private-key" not in json.dumps(metadata)


def test_slow_partial_response_records_elapsed_usage_and_request_id():
    async def handler(request):
        await asyncio.sleep(0.025)
        return httpx.Response(200, headers={"x-request-id": "gateway-request-123"}, json={
            "choices": [{"message": {"content": '{"lines":[{"id":"a","text":"One"}]}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})

    result = asyncio.run(KiraProvider("key", transport=httpx.MockTransport(handler)).translate([{"id": "a", "source": "Hello"}, {"id": "b", "source": "World"}], "English", "Vietnamese"))
    assert result.values == {"a": "One"} and result.error
    assert result.diagnostics["failure_kind"] == "partial_response"
    assert result.diagnostics["elapsed_seconds"] >= 0.02
    assert result.diagnostics["provider_request_id"] == "gateway-request-123"
    assert result.diagnostics["usage"]["total_tokens"] == 15


def test_http504_under_concurrency_is_persisted_without_retry(tmp_path):
    store = Store(tmp_path / "diagnostics.db")
    doc, _ = store.import_document(tmp_path / "a.txt", decode_txt("\n".join(f"Line {i}" for i in range(18)).encode()))
    job = store.create_job(doc, "qwen3.8-flash", "English", "Vietnamese", 3, timeout=120, retry_504=False)
    calls = []
    active = 0
    peak = 0

    async def handler(request):
        nonlocal active, peak
        calls.append(request)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.025)
        active -= 1
        return httpx.Response(504, headers={"x-request-id": "gateway-504"}, json={"error": "upstream timeout"})

    scheduler = Scheduler(store, KiraProvider("key", "qwen3.8-flash", timeout=120, transport=httpx.MockTransport(handler)))
    scheduler.start(job)
    scheduler.join(5)
    assert len(calls) == 6 and peak == 3
    assert all(row["state"] == "unknown" for row in store.lines(doc))
    store.close()
    reopened = Store(tmp_path / "diagnostics.db")
    for batch in reopened.batches(job):
        metadata = batch["diagnostics"]
        assert metadata["batch_id"] == batch["id"]
        assert metadata["model"] == "qwen3.8-flash"
        assert metadata["http_status"] == 504 and metadata["failure_kind"] == "http_504"
        assert metadata["line_count"] == 3 and metadata["source_chars"] > 0
        assert metadata["configured_concurrency"] == 3
        assert metadata["configured_timeout_seconds"] == 120
        assert metadata["provider_request_id"] == "gateway-504"
        assert not reopened.claim_batch(batch["id"])
    assert reopened.job(job)["timeout"] == 120
    reopened.close()


def test_invalid_schema_has_distinct_diagnostic_kind():
    provider = KiraProvider("key", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": []})))
    result = asyncio.run(provider.translate([{"id": "a", "source": "Hello"}], "English", "Vietnamese"))
    assert result.diagnostics["failure_kind"] == "invalid_schema"
    assert result.diagnostics["http_status"] == 200


@pytest.mark.parametrize("timeout", [0, 29, 301])
def test_job_timeout_is_bounded(tmp_path, timeout):
    store = Store(tmp_path / "timeout.db")
    doc, _ = store.import_document(tmp_path / "a.txt", decode_txt(b"Hello"))
    with pytest.raises(ValueError, match="Timeout"):
        store.create_job(doc, "kira-2.5-flash", "English", "Vietnamese", 1, timeout=timeout)
    store.close()
