import asyncio
import json
import sqlite3
import httpx
import pytest
from transcomic.gemini import GeminiProvider, GeminiKeyPool, KeyUnavailable, QuotaLimiter, classify_error, model_name
from transcomic.storage import Store

KEYS = [{'id': 'first', 'secret': 'private-first', 'project': 'project-a'}, {'id': 'second', 'secret': 'private-second', 'project': 'project-b'}]
LINES = [{'id': 'line-id', 'source': 'Hôm nay trời rất đẹp', 'context': [{'id': 'context', 'source': 'Reference'}]}]


def response(request, *, missing=False):
    body = json.loads(request.content)
    payload = json.loads(body['contents'][0]['parts'][0]['text'])
    lines = payload['lines']
    content = json.dumps({'lines': [{'id': r['id'], 'text': 'Today the weather is beautiful'} for r in lines[1:] if missing] if missing else [{'id': r['id'], 'text': 'Today the weather is beautiful'} for r in lines]})
    return {'candidates': [{'content': {'parts': [{'text': content}]}, 'finishReason': 'STOP'}],
            'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 20, 'totalTokenCount': 120}}


def test_official_request_shape_context_and_result_no_retry():
    calls, events = [], []
    def handle(req):
        calls.append(req)
        assert str(req.url) == 'https://generativelanguage.googleapis.com/v1beta/models/mock-gemini:generateContent'
        assert req.headers['x-goog-api-key'] == 'private-first'
        assert 'key=' not in str(req.url) and 'authorization' not in req.headers
        body = json.loads(req.content)
        assert body['generationConfig'] == {'responseMimeType': 'application/json', 'maxOutputTokens': 256}
        payload = json.loads(body['contents'][0]['parts'][0]['text'])
        assert payload['lines'][0]['id'] == 'line-id'
        assert payload['reference_only'][0]['id'] == 'context'
        return httpx.Response(200, json=response(req))
    provider = GeminiProvider(KEYS, 'models/mock-gemini', max_tokens=256, transport=httpx.MockTransport(handle))
    result = asyncio.run(provider.translate(LINES, 'Tiếng Việt', 'Tiếng Anh', observer=lambda e, **d: events.append((e, d))))
    assert result.values == {'line-id': 'Today the weather is beautiful'} and len(calls) == 1
    assert result.usage['total_tokens'] == 120 and result.diagnostics['key_alias'] == 'first'
    assert 'private-first' not in json.dumps(events)


@pytest.mark.parametrize('code,kind', [(401, 'authentication'), (403, 'permission'), (429, 'rate_limit'), (404, 'model_not_found'), (500, 'http_server_error'), (502, 'http_server_error'), (503, 'http_server_error'), (504, 'http_server_error')])
def test_http_errors_do_not_retry_or_fallback(code, kind):
    calls = []
    def handle(req): calls.append(req); return httpx.Response(code, json={'error': {'message': 'private-first private story'}})
    provider = GeminiProvider(KEYS, 'mock-gemini', transport=httpx.MockTransport(handle))
    result = asyncio.run(provider.translate(LINES, 'vi', 'en'))
    assert len(calls) == 1 and provider.pool.index == 0
    assert result.diagnostics['failure_kind'] == kind
    assert 'private' not in result.error and 'private' not in json.dumps(result.diagnostics)
    assert result.unknown == (code >= 500)


@pytest.mark.parametrize('exception', [httpx.ReadTimeout, httpx.ConnectTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.ConnectError])
def test_network_unknown_does_not_rotate_or_retry(exception):
    calls = []
    def handle(req): calls.append(req); raise exception('private-first', request=req)
    provider = GeminiProvider(KEYS, 'mock', transport=httpx.MockTransport(handle))
    result = asyncio.run(provider.translate(LINES, 'vi', 'en'))
    assert len(calls) == 1 and result.unknown and provider.pool.index == 0 and not provider.pool.paused_reason
    assert 'private-first' not in result.error


@pytest.mark.parametrize('obj,kind', [({}, 'invalid_schema'), ({'candidates': []}, 'invalid_schema'),
    ({'candidates': [{'content': {'parts': [{'text': 'prose instead of JSON'}]}}]}, 'invalid_line_response'),
    ({'candidates': [{'content': {'parts': [{'text': '{"lines":[{"id":"wrong","text":"Data"}]}'}]}}]}, 'invalid_line_response')])
def test_invalid_schema_and_ids_no_guess(obj, kind):
    result = asyncio.run(GeminiProvider(KEYS, 'mock', transport=httpx.MockTransport(lambda r: httpx.Response(200, json=obj))).translate(LINES, 'vi', 'en'))
    assert not result.values and result.error and result.diagnostics['failure_kind'] == kind and not result.unknown


def test_model_list_get_only_explicit_bounded_cache_eligible_models():
    calls = []
    def handle(req):
        calls.append(req)
        assert req.method == 'GET'
        return httpx.Response(200, json={'models': [
            {'name': 'models/text-real', 'displayName': 'Text real', 'supportedGenerationMethods': ['generateContent']},
            {'name': 'models/embedding-real', 'supportedGenerationMethods': ['embedContent']},
            {'name': 'models/image-real', 'supportedGenerationMethods': ['generateContent']},
            {'name': 'models/nano-banana-pro-preview', 'supportedGenerationMethods': ['generateContent']},
            {'name': 'models/lyria-3.5', 'supportedGenerationMethods': ['generateContent']},
            {'name': 'models/gemini-3.5-transcribe', 'supportedGenerationMethods': ['generateContent']}], 'nextPageToken': 'next'})
    provider = GeminiProvider(KEYS, 'mock', transport=httpx.MockTransport(handle))
    assert not calls
    listed = asyncio.run(provider.list_models(max_pages=1))
    assert len(calls) == 1 and listed['pages'] == 1 and listed['nextPageToken'] == 'next'
    assert [r['name'] for r in listed['models']] == ['models/text-real']


@pytest.mark.parametrize('project', ['project-a', '', 'project-b'])
def test_sequential_quota_rotation_requires_independent_known_project(project):
    async def run():
        pool = GeminiKeyPool([KEYS[0], dict(KEYS[1], project=project)])
        first, also_first = await pool.acquire(), await pool.acquire()
        assert first['id'] == also_first['id'] == 'first'
        await pool.release(first, 'quota_exhausted')
        assert pool.index == 0
        await pool.release(also_first)
        if project == 'project-b':
            assert (await pool.acquire())['id'] == 'second'; assert pool.active == 1
        else:
            with pytest.raises(KeyUnavailable): await pool.acquire()
    asyncio.run(run())


def test_structured_daily_quota_only_not_any429_or_message():
    daily = {'error': {'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}}
    temporary = {'error': {'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]}]}}
    assert classify_error(429, daily) == 'quota_exhausted'
    assert classify_error(429, temporary) == 'rate_limit'
    assert classify_error(429, {'error': {'message': 'daily quota exhausted'}}) == 'rate_limit'


def test_quota_rejection_rotates_next_batch_never_resends_original():
    calls = []
    daily = {'error': {'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', 'violations': [{'quotaId': 'GenerateRequestsPerDayPerProjectPerModel'}]}]}}
    def handle(req):
        calls.append(req.headers['x-goog-api-key'])
        return httpx.Response(429, json=daily) if len(calls) == 1 else httpx.Response(200, json=response(req))
    async def run():
        provider = GeminiProvider(KEYS, 'mock', transport=httpx.MockTransport(handle))
        first = await provider.translate(LINES, 'vi', 'en')
        assert first.error and len(calls) == 1
        second = await provider.translate([{'id': 'other', 'source': 'Other'}], 'vi', 'en')
        assert second.values == {'other': 'Today the weather is beautiful'}
    asyncio.run(run()); assert calls == ['private-first', 'private-second']


def test_verified_quota_limiter_blocks_too_large_and_daily_budget():
    async def run():
        limiter = QuotaLimiter(2, 1000, 1)
        with pytest.raises(KeyUnavailable): await limiter.reserve(1001)
        await limiter.reserve(100)
        with pytest.raises(KeyUnavailable): await limiter.reserve(100)
        assert len(limiter.minute) == len(limiter.day) == 1
    asyncio.run(run())


def test_keys_dpapi_duplicates_priority_delete_and_no_plaintext(tmp_path):
    store = Store(tmp_path/'keys.db')
    assert store.add_gemini_keys(' private-first \n\nprivate-first\nprivate-second ', 'project') == (2, 0)
    assert store.add_gemini_keys('private-first') == (0, 1)
    keys = store.gemini_keys()
    assert len(keys) == 2 and all('secret' not in k and 'encrypted' not in k for k in keys)
    assert [k['secret'] for k in store.gemini_keys(True)] == ['private-first', 'private-second']
    store.change_gemini_key(keys[1]['id'], direction=-1)
    assert store.gemini_keys()[0]['id'] == keys[1]['id']
    store.change_gemini_key(keys[0]['id'], delete=True)
    store.log.flush()
    assert b'private-first' not in store.path.read_bytes() and b'private-second' not in store.path.read_bytes()
    assert all('private-first' not in p.read_text(encoding='utf-8') for p in store.log.directory.glob('*.jsonl'))
    store.close()


@pytest.mark.parametrize('value', ['../unsafe', 'models/a?key=secret', 'models/a/b', '', 'https://bad'])
def test_model_resource_validation(value):
    with pytest.raises(ValueError): model_name(value)
