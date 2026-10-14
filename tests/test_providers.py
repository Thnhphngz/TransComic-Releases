import asyncio
import json

import httpx
import pytest

from transcomic.providers import KiraProvider, parse_line_response


def test_ids_are_mapped_not_ordered():
    result = parse_line_response(json.dumps({"lines": [{"id": "b", "text": "B"}, {"id": "a", "text": "A"}]}), {"a", "b"})
    assert result.values == {"a": "A", "b": "B"}
    assert result.error is None


@pytest.mark.parametrize("body,values", [
    ({"lines": [{"id": "a", "text": "A"}]}, {"a": "A"}),
    ({"lines": [{"id": "a", "text": "A"}, {"id": "a", "text": "B"}]}, {}),
    ({"lines": [{"id": "a", "text": "A"}, {"id": "x", "text": "X"}]}, {"a": "A"}),
    ({"wrong": []}, {}),
])
def test_invalid_responses_are_never_positionally_assigned(body, values):
    result = parse_line_response(json.dumps(body), {"a", "b"})
    assert result.values == values
    assert result.error


@pytest.mark.parametrize("code,unknown", [(401, False), (429, False), (500, True), (504, True)])
def test_http_error_no_retry(code, unknown):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.url.path == "/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret"
        assert len(json.loads(request.content)["messages"]) == 2
        return httpx.Response(code, json={"error": "failure"})
    provider = KiraProvider("secret", transport=httpx.MockTransport(handler))
    result = asyncio.run(provider.translate([{"id": "a", "source": "Hello"}], "English", "Vietnamese"))
    assert len(calls) == 1
    assert result.unknown == unknown
    assert result.error


def test_valid_mock_response():
    def handler(request):
        lines = json.loads(json.loads(request.content)["messages"][1]["content"])["lines"]
        content = json.dumps({"lines": [{"id": x["id"], "text": x["text"] + " translated"} for x in reversed(lines)]})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
    provider = KiraProvider("secret", transport=httpx.MockTransport(handler))
    result = asyncio.run(provider.translate([{"id": "a", "source": "One"}, {"id": "b", "source": "Two"}], "English", "Vietnamese"))
    assert result.values == {"a": "One translated", "b": "Two translated"}


def test_test_budget_output_cap_is_sent():
    def handler(request):
        assert json.loads(request.content)["max_tokens"] == 256
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"lines":[{"id":"a","text":"A"}]}'}}], "usage": {"prompt_tokens": 24, "completion_tokens": 12, "total_tokens": 36}})
    result = asyncio.run(KiraProvider("secret", transport=httpx.MockTransport(handler), max_tokens=256).translate([{"id": "a", "source": "Hello"}], "English", "Vietnamese"))
    assert result.usage == {"prompt_tokens": 24, "completion_tokens": 12, "total_tokens": 36}


def test_timeout_unknown_no_retry():
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        raise httpx.ReadTimeout("timeout")
    provider = KiraProvider("secret", transport=httpx.MockTransport(handler))
    result = asyncio.run(provider.translate([{"id": "a", "source": "One"}], "English", "Vietnamese"))
    assert result.unknown and count == 1


def test_connection_reset_unknown_no_retry():
    count = 0
    def handler(request):
        nonlocal count
        count += 1
        raise httpx.ReadError("connection reset")
    result = asyncio.run(KiraProvider("secret", transport=httpx.MockTransport(handler)).translate([{"id": "a", "source": "One"}], "English", "Vietnamese"))
    assert result.unknown and count == 1


def test_invalid_chat_envelope_is_error():
    provider = KiraProvider("secret", transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"choices": []})))
    result = asyncio.run(provider.translate([{"id": "a", "source": "One"}], "English", "Vietnamese"))
    assert result.values == {} and result.error and not result.unknown
