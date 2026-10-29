"""DeepSeek HTTP/JSON adapter; the durable scheduler owns automatic recovery."""
import asyncio
import json
import time
import hashlib
from datetime import datetime, timezone
import httpx
from .providers import KiraProvider, BatchResult, validate_request_lines
from .prompts import messages, PROMPT_VERSION
from .translation_policy import VERSION as SEMANTIC_VERSION, SEMANTIC_VERSIONS
from .deepseek_pricing import load, period, estimate, validate as validate_pricing
from .deepseek_models import MODEL, MODELS, validate_model
from .deepseek_batch import validate_size, output_limit
from .deepseek_json import parse_translation

URL = 'https://api.deepseek.com/chat/completions'


def save_key(store, key):
    from .security import protect_key
    key = key.strip()
    if not key or any(c.isspace() for c in key): raise ValueError('API key DeepSeek không hợp lệ')
    encrypted = protect_key(key)
    store.log.register_secret(key)
    with store.transaction():
        from .api_credentials import ensure_idle
        ensure_idle(store, 'deepseek')
        store.db.execute('INSERT OR REPLACE INTO secrets(key,encrypted) VALUES (?,?)', ('deepseek', encrypted))


def delete_key(store):
    from .api_credentials import ensure_idle
    with store.transaction():
        ensure_idle(store, 'deepseek')
        store.db.execute("DELETE FROM secrets WHERE key='deepseek'")


def read_key(store):
    from .security import unprotect_key
    row = store.db.execute('SELECT encrypted FROM secrets WHERE key=?', ('deepseek',)).fetchone()
    if not row: return None
    try: key = unprotect_key(row[0]).strip()
    except Exception: raise ValueError('Không đọc được key DeepSeek bằng DPAPI; lưu lại trong trang API') from None
    if not key: return None
    store.log.register_secret(key)
    return key


def key_identity(store):
    row = store.db.execute('SELECT encrypted FROM secrets WHERE key=?', ('deepseek',)).fetchone()
    return hashlib.sha256(row[0]).hexdigest() if row else None


def selected_prompt(store):
    selected=store.setting('deepseek_prompt_version',SEMANTIC_VERSION)
    return selected if selected in SEMANTIC_VERSIONS else SEMANTIC_VERSION


def settings(store, model=MODEL, batch_size=None):
    from .completion import authorize
    return authorize('deepseek',dict(auto_retries=0, retry_504=False,
                prompt_version=selected_prompt(store),
                deepseek_batch_size=validate_size(int(store.setting('deepseek_batch_size','3')) if batch_size is None else batch_size),
                deepseek_max_tokens=max(128, min(8192, int(store.setting('deepseek_max_tokens', '2048')))),
                deepseek_pricing=load(store, model)))


def provider_for(store, job):
    config = json.loads(job.get('config') or '{}')
    key = read_key(store)
    if not key: raise ValueError('Chưa có key DeepSeek; mở trang API để cấu hình')
    provider = DeepSeekProvider(key, job['model'], timeout=job['timeout'], prompt_version=job['prompt_version'],
                            max_tokens=config.get('deepseek_max_tokens', 2048),
                            batch_size=config.get('deepseek_batch_size', 3),
                            pricing=config.get('deepseek_pricing') or load(store, job['model']))
    provider.stored_identity = key_identity(store)
    return provider


class DeepSeekProvider(KiraProvider):
    """Reuse the existing HTTP-provider interface, never Kira's endpoint or pool."""
    def __init__(self, api_key, model=MODEL, timeout=90, transport=None, max_tokens=2048,
                 prompt_version=SEMANTIC_VERSION, pricing=None, batch_size=3):
        validate_model(model)
        if not api_key: raise ValueError('Chưa có key DeepSeek; mở trang API')
        if type(max_tokens) is not int or not 128 <= max_tokens <= 8192: raise ValueError('max_tokens phải từ 128 đến 8192')
        if not 0 < timeout <= 300: raise ValueError('Timeout không hợp lệ')
        super().__init__(api_key, model, timeout, transport, max_tokens, prompt_version)
        self.batch_size = validate_size(batch_size)
        self.pricing = validate_pricing(pricing) if pricing is not None else load(model=model)

    def client(self, concurrency=1):
        if not 1 <= concurrency <= 30: raise ValueError('DeepSeek hỗ trợ 1–30 worker')
        limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
        return httpx.AsyncClient(timeout=self.http_timeout, follow_redirects=False,
                                transport=self.transport or httpx.AsyncHTTPTransport(retries=0, limits=limits), limits=limits)

    def request_body(self, lines, source, target):
        validate_request_lines(lines, max_lines=self.batch_size)
        if any(not r['source'].strip() for r in lines): raise ValueError('Không gửi dòng trống tới DeepSeek')
        return dict(model=self.model, messages=messages(lines, source, target, self.prompt_version),
                    thinking={'type':'disabled'}, response_format={'type':'json_object'},
                    stream=False, max_tokens=output_limit(lines, self.max_tokens))

    async def translate(self, lines, source_lang, target_lang, *, client=None, observer=None):
        body = self.request_body(lines, source_lang, target_lang)
        expected = {r['id'] for r in lines}
        started = time.monotonic()
        price_period, _ = period(self.pricing)
        diag = dict(model=self.model, max_tokens=body['max_tokens'], configured_max_tokens=self.max_tokens,
                    batch_size=self.batch_size, line_count=len(lines), sent_body_observed=False,
                    server_execution_known=False, price_period=price_period,
                    pricing=self.pricing, request_chars=len(json.dumps(body)),
                    http_started_at=datetime.now(timezone.utc).isoformat())
        usage = None
        def result(error=None, kind=None, unknown=False, values=None):
            diag.update(failure_kind=kind, elapsed_seconds=round(time.monotonic()-started, 3),
                        usage=usage,
                        cost_estimate=estimate(usage, self.pricing[price_period]),
                        delivery_state='unknown' if unknown else 'not_sent' if kind=='not_sent' else 'error' if error else 'success')
            if observer: observer('failure' if error else 'parsed', reason=kind, state=diag['delivery_state'], usage=usage)
            return BatchResult(values or {}, error, unknown, usage, dict(diag))
        async def send(active):
            nonlocal usage
            if getattr(self, 'should_stop', lambda:False)(): return result('Dừng trước khi gửi HTTP', 'not_sent')
            async def trace(name, info):
                if name.endswith('send_request_body.complete'):
                    diag['sent_body_observed'] = True
                    if observer: observer('body_sent', sent_body_observed=True)
            request = active.build_request('POST', URL, headers={'Authorization':'Bearer '+self.api_key}, json=body)
            request.extensions['trace'] = trace
            response = None
            try:
                # Covers headers AND all body chunks. Blank-line keepalives cannot reset this deadline.
                async with asyncio.timeout(self.timeout):
                    if observer: observer('http_started', max_tokens=body['max_tokens'], batch_size=self.batch_size, server_execution_known=False)
                    response = await active.send(request, stream=True)
                    diag['http_status'] = response.status_code
                    if observer: observer('headers', http_status=response.status_code)
                    if response.status_code != 200:
                        status = response.status_code
                        from .completion import retry_after
                        hint=retry_after(response.headers.get('retry-after'))
                        if hint is not None:diag['retry_after_seconds']=hint
                        kind, message = {
                            400:('model_or_request','Yêu cầu DeepSeek không hợp lệ (400)'),
                            401:('authentication','API key DeepSeek không hợp lệ (401)'),
                            402:('quota_exhausted','DeepSeek không đủ số dư (402)'),
                            403:('permission','DeepSeek từ chối quyền truy cập (403)'),
                            429:('rate_limit','DeepSeek đang bị giới hạn tốc độ API (429)'),
                        }.get(status, ('http_server_error' if status >= 500 else 'http_error', f'DeepSeek HTTP {status}'))
                        return result(message, kind, unknown=status >= 500)
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > 2*1024*1024: return result('Phản hồi DeepSeek quá lớn', 'invalid_schema')
                    if observer: observer('body_received', http_status=response.status_code)
                    diag['raw_response_sha256']=hashlib.sha256(chunks).hexdigest()
                    try:
                        envelope = json.loads(chunks)
                        if isinstance(envelope.get('model'),str):diag['response_model']=envelope['model'].replace(self.api_key,'[redacted]')[:128]
                        raw_usage = envelope.get('usage')
                        if isinstance(raw_usage, dict):
                            usage = {k:v for k,v in raw_usage.items() if k in ('prompt_tokens','completion_tokens','total_tokens','prompt_cache_hit_tokens','prompt_cache_miss_tokens') and type(v) is int and v >= 0}
                            detail = raw_usage.get('prompt_tokens_details')
                            if isinstance(detail, dict) and type(detail.get('cached_tokens')) is int and detail['cached_tokens'] >= 0:
                                usage['prompt_tokens_details'] = {'cached_tokens':detail['cached_tokens']}
                            diag['server_execution_known'] = bool(usage)
                        choice = envelope['choices'][0]
                        diag['finish_reason'] = choice.get('finish_reason')
                        if choice.get('finish_reason') != 'stop': return result('Phản hồi chưa hoàn tất hoặc bị cắt', 'truncated_response')
                        message = choice['message']
                        if message.get('reasoning_content'): return result('DeepSeek trả reasoning ngoài chế độ Non-thinking', 'invalid_schema')
                        content = message.get('content')
                        parsed = parse_translation(content, expected, self.prompt_version)
                        # Metadata diagnostics contain no translation content. Redact
                        # any accidental credential echo before persisting values.
                        diag.update(json.loads(json.dumps(parsed.diagnostics or {},ensure_ascii=True).replace(self.api_key,'[redacted]')))
                        if observer and 'extra_root_keys' in diag:
                            observer('schema_metadata',parser_version=diag['parser_version'],
                                extra_root_keys=diag['extra_root_keys'],root_metadata=json.dumps(diag.get('root_metadata',{}),ensure_ascii=True),
                                metadata_decision=diag['metadata_decision'],reason=diag['metadata_reason'],
                                raw_response_sha256=diag['raw_response_sha256'])
                        if parsed.error:
                            return result(parsed.error, diag['failure_kind'])
                        return result(values=parsed.values)
                    except (ValueError, TypeError, KeyError, IndexError, AttributeError, UnicodeError):
                        return result('Phản hồi DeepSeek rỗng hoặc JSON không hợp lệ', 'invalid_schema')
            except (TimeoutError, httpx.TimeoutException):
                return result('DeepSeek timeout; chưa rõ chi phí, không tự gửi lại', 'client_timeout', True)
            except httpx.ConnectError:
                return result('Không kết nối được DeepSeek', 'connect_error' if diag['sent_body_observed'] else 'not_sent', diag['sent_body_observed'])
            except httpx.HTTPError:
                return result('Lỗi mạng DeepSeek; chưa rõ máy chủ đã xử lý hay chưa', 'network_error', True)
            except asyncio.CancelledError:
                return result('Đã hủy yêu cầu DeepSeek; không tự gửi lại', 'shutdown_cancelled', True)
            finally:
                if response is not None: await response.aclose()
        if client is not None: return await send(client)
        async with self.client() as own: return await send(own)
