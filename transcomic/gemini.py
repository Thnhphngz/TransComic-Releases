"""Official Gemini REST API. No implicit list calls, retries, or model fallback."""
from __future__ import annotations
import asyncio
from collections import deque
import json
import re
import time
import httpx
from .providers import KiraProvider, BatchResult, parse_line_response
from .prompts import messages

BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'


def text_model_eligible(name):
    """Conservatively exclude dedicated modalities/agents from translation."""
    return not any(s in name.lower() for s in ('image', 'tts', 'embedding', 'veo', 'aqa', 'live', 'audio',
        'nano-banana', 'lyria', 'transcribe', 'robotics', 'computer-use', 'antigravity', 'deep-research', 'customtools'))


def model_name(value):
    value = value.removeprefix('models/')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value):
        raise ValueError('Invalid Gemini model resource name')
    return 'models/'+value


def classify_error(status, envelope):
    if status == 401: return 'authentication'
    if status == 403: return 'permission'
    if status == 404: return 'model_not_found'
    if status == 429:
        error = envelope.get('error', {}) if isinstance(envelope, dict) else {}
        details = error.get('details', []) if isinstance(error, dict) else []
        # Only structured daily quota evidence; don't infer permanent exhaustion from prose.
        violations = [v for d in details if isinstance(d, dict) and d.get('@type') == 'type.googleapis.com/google.rpc.QuotaFailure'
                      for v in d.get('violations', []) if isinstance(v, dict)]
        identifiers = [str(v.get('quotaId', '')) for v in violations]
        if identifiers and all('PerDay' in i or 'per_day' in i.lower() for i in identifiers):
            return 'quota_exhausted'
        return 'rate_limit'
    if status >= 500: return 'http_server_error'
    return 'http_error'


class KeyUnavailable(RuntimeError):
    pass


class GeminiKeyPool:
    """Frozen priority snapshot; never use different keys concurrently."""
    def __init__(self, keys, on_status=None):
        self.keys = [dict(k) for k in keys]
        if not self.keys: raise KeyUnavailable('No Gemini key configured')
        self.on_status = on_status
        self.index = 0
        self.active = 0
        self.condition = asyncio.Condition()
        self.blocked_projects = set()
        self.paused_reason = None
        self.resume_requested = False
        self.key_failures = {}

    async def acquire(self):
        async with self.condition:
            if self.resume_requested and self.paused_reason == 'rate_limit' and not self.active:
                self.paused_reason = None
                self.resume_requested = False
                self.key_failures.pop(self.keys[self.index]['id'], None)
            while self.paused_reason and self.active:
                await self.condition.wait()
            if self.paused_reason:
                raise KeyUnavailable(self.paused_reason)
            self.active += 1
            return self.keys[self.index]

    async def release(self, key, kind=None):
        async with self.condition:
            self.active -= 1
            if kind in ('authentication', 'permission', 'quota_exhausted', 'rate_limit'):
                priority = {'rate_limit': 1, 'authentication': 2, 'permission': 2, 'quota_exhausted': 3}
                previous = self.key_failures.get(key['id'])
                if previous and priority[previous] > priority[kind]: kind = previous
                self.key_failures[key['id']] = kind
                if self.on_status: self.on_status(key['id'], kind)
                if kind == 'quota_exhausted':
                    self.blocked_projects.add(key.get('project') or 'unknown')
                    self.paused_reason = kind
                else:
                    self.paused_reason = kind
            elif kind is None and self.on_status and key['id'] not in self.key_failures:
                self.on_status(key['id'], 'available')
            elif kind == 'model_not_found':
                self.paused_reason = kind
            if self.active == 0 and self.paused_reason == 'quota_exhausted':
                # Unknown project affiliation cannot establish an independent quota.
                old_project = key.get('project')
                for i in range(self.index+1, len(self.keys)):
                    project = self.keys[i].get('project')
                    if old_project and project and project not in self.blocked_projects:
                        self.index = i
                        self.paused_reason = None
                        break
            self.condition.notify_all()


class QuotaLimiter:
    """One project/model limiter shared by all file/language jobs in a run."""
    def __init__(self, rpm, tpm, rpd, clock=time.monotonic, reservation=None):
        if min(rpm, tpm, rpd) < 1: raise ValueError('Verified positive RPM/TPM/RPD required')
        self.rpm, self.tpm, self.rpd = rpm, tpm, rpd
        self.clock = clock
        self.minute, self.day = deque(), deque()
        self.lock = asyncio.Lock()
        self.reservation = reservation
        self.wait_gate = None

    async def reserve(self, input_upper_bound):
        if input_upper_bound > self.tpm: raise KeyUnavailable('request_exceeds_verified_tpm')
        async with self.lock:
            while True:
                if self.wait_gate: await self.wait_gate()
                if self.reservation:
                    delay = self.reservation(input_upper_bound, self.rpm, self.tpm, self.rpd)
                    if delay == 0: return
                    await asyncio.sleep(min(1, max(.01, delay)))
                    continue
                now = self.clock()
                while self.minute and self.minute[0][0] <= now-60: self.minute.popleft()
                while self.day and self.day[0] <= now-86400: self.day.popleft()
                if len(self.day) >= self.rpd: raise KeyUnavailable('verified_daily_budget_exhausted')
                if len(self.minute) < self.rpm and sum(t for _, t in self.minute)+input_upper_bound <= self.tpm:
                    self.minute.append((now, input_upper_bound)); self.day.append(now)
                    return
                # Accounted rate-window delay, not an HTTP retry or speculative backoff.
                await asyncio.sleep(min(1, max(.01, self.minute[0][0]+60-now)))


class GeminiProvider(KiraProvider):
    def __init__(self, keys, model, *, limiter=None, on_status=None, **kwargs):
        self.pool = GeminiKeyPool(keys, on_status)
        self.resource = model_name(model)
        super().__init__(keys[0]['secret'], model, **kwargs)
        self.limiter = limiter
        self.should_stop = lambda: False
        self.should_pause = lambda: False
        if limiter: limiter.wait_gate = self.wait_gate

    async def wait_gate(self):
        while self.should_pause() and not self.should_stop(): await asyncio.sleep(.05)
        if self.should_stop(): raise KeyUnavailable('stopped_before_send')

    async def list_models(self, *, max_pages=1, observer=None):
        """Explicit authorized metadata GET; bounded pages, no fallback key or retry."""
        result, token = [], None
        async with self.client() as client:
            for page in range(max_pages):
                response = await client.get(BASE_URL+'/models', headers={'x-goog-api-key': self.api_key},
                                            params={'pageSize': 1000, **({'pageToken': token} if token else {})})
                if observer: observer('model_list', http_status=response.status_code, request_kind='model_list', key_alias=self.pool.keys[0]['id'])
                if response.status_code != 200: raise KeyUnavailable('model_list_http_'+str(response.status_code))
                obj = response.json()
                for model in obj.get('models', []):
                    if isinstance(model, dict) and 'generateContent' in model.get('supportedGenerationMethods', []):
                        name = model_name(model.get('name', ''))
                        # Exclude dedicated image/audio/embedding/video models from text translation.
                        if text_model_eligible(name):
                            result.append({'name': name, 'displayName': model.get('displayName', name),
                                           'inputTokenLimit': model.get('inputTokenLimit'), 'outputTokenLimit': model.get('outputTokenLimit')})
                token = obj.get('nextPageToken')
                if not token: break
        return {'models': result, 'nextPageToken': token, 'pages': page+1}

    async def translate(self, lines, source_lang, target_lang, *, client=None, observer=None):
        if not 1 <= len(lines) <= 3: raise ValueError('Each request must contain 1–3 lines')
        prompt = messages(lines, source_lang, target_lang, self.prompt_version)
        body = {'systemInstruction': {'parts': [{'text': prompt[0]['content']}]},
                'contents': [{'role': 'user', 'parts': [{'text': prompt[1]['content']}]}],
                'generationConfig': {'responseMimeType': 'application/json'}}
        if self.max_tokens is not None: body['generationConfig']['maxOutputTokens'] = self.max_tokens
        diagnostics = {'model': self.model, 'line_count': len(lines), 'source_chars': sum(len(r['source']) for r in lines),
                       'request_chars': len(json.dumps(body, ensure_ascii=False)), 'prompt_version': self.prompt_version,
                       'request_kind': 'translation', 'server_execution_known': False, 'sent_body_observed': False,
                       'timeout_seconds': {k: getattr(self.http_timeout, k) for k in ('connect', 'read', 'write', 'pool')}, 'max_tokens': self.max_tokens}
        expected = {r['id'] for r in lines}
        started = time.monotonic()
        usage = None
        key = None
        kind = None
        def done(values, error=None, unknown=False):
            diagnostics['elapsed_seconds'] = round(time.monotonic()-started, 6)
            diagnostics['failure_kind'] = kind
            if usage: diagnostics['usage'] = usage
            if observer:
                observer('failure' if error else 'parsed', http_status=diagnostics.get('http_status'), reason=kind,
                         state='unknown' if unknown else 'error' if error else 'valid', accepted_ids=list(values),
                         rejected_ids=list(expected-values.keys()), key_alias=diagnostics.get('key_alias'), usage=usage,
                         elapsed_seconds=diagnostics['elapsed_seconds'], http_seconds=diagnostics.get('http_seconds'), parse_seconds=diagnostics.get('parse_seconds'))
            return BatchResult(values, error, unknown, usage, dict(diagnostics))
        async def send(active_client):
            async def trace(name, _):
                if name.endswith('send_request_body.complete'):
                    diagnostics['sent_body_observed'] = True
                    if observer: observer('body_sent', sent_body_observed=True, key_alias=key['id'])
            req = active_client.build_request('POST', BASE_URL+'/'+self.resource+':generateContent', headers={'x-goog-api-key': key['secret']}, json=body)
            req.extensions.update({'trace': trace, 'diagnostic_observer': observer})
            if observer: observer('http_started', **{k: diagnostics[k] for k in ('request_kind', 'request_chars', 'timeout_seconds', 'max_tokens', 'server_execution_known', 'key_alias')})
            return await active_client.send(req)
        try:
            if self.limiter:
                await self.limiter.reserve(len(json.dumps(body, ensure_ascii=False).encode('utf-8'))+128)
            await self.wait_gate()
            key = await self.pool.acquire()
            diagnostics['key_alias'] = key['id']
            http_start = time.monotonic()
            if client:
                response = await send(client)
            else:
                async with self.client() as own: response = await send(own)
            diagnostics['http_seconds'] = round(time.monotonic()-http_start, 6)
            diagnostics['http_status'] = response.status_code
            if observer: observer('body_received', http_status=response.status_code, http_seconds=diagnostics['http_seconds'], key_alias=key['id'])
            parse_start = time.monotonic()
            try: obj = response.json()
            except ValueError: obj = None
            if response.status_code != 200:
                kind = classify_error(response.status_code, obj)
                if response.status_code == 429:
                    diagnostics['retry_after'] = response.headers.get('retry-after')
                    seconds = None
                    try: seconds = max(0.0, float(response.headers['retry-after']))
                    except (KeyError, ValueError): pass
                    details = obj.get('error', {}).get('details', []) if isinstance(obj, dict) and isinstance(obj.get('error'), dict) else []
                    for d in details:
                        if isinstance(d, dict) and d.get('@type') == 'type.googleapis.com/google.rpc.RetryInfo':
                            try: seconds = max(seconds or 0, float(d['retryDelay'].removesuffix('s')))
                            except (KeyError, ValueError, AttributeError): pass
                    diagnostics['retry_after_seconds'] = seconds
                    diagnostics['quota_type'] = 'exhausted' if kind == 'quota_exhausted' else 'temporary' if seconds is not None else 'unverified'
                return done({}, 'Gemini HTTP '+str(response.status_code)+' ('+kind+'); no automatic resend', response.status_code >= 500)
            measured = obj.get('usageMetadata', {}) if isinstance(obj, dict) else {}
            if not isinstance(measured, dict): measured = {}
            usage = {ours: measured[theirs] for ours, theirs in [('prompt_tokens', 'promptTokenCount'), ('completion_tokens', 'candidatesTokenCount'), ('total_tokens', 'totalTokenCount'), ('reasoning_tokens', 'thoughtsTokenCount')] if isinstance(measured.get(theirs), int)}
            try:
                candidate = obj['candidates'][0]
                parts = candidate['content']['parts']
                text = ''.join(p['text'] for p in parts if isinstance(p, dict) and not p.get('thought') and isinstance(p.get('text'), str))
                diagnostics['finish_reason'] = candidate.get('finishReason') if candidate.get('finishReason') in ('STOP', 'MAX_TOKENS', 'SAFETY', 'RECITATION') else 'unknown'
                parsed = parse_line_response(text, expected)
                kind = 'invalid_line_response' if parsed.error else None
                diagnostics['returned_valid_ids'] = len(parsed.values)
                diagnostics['parse_seconds'] = round(time.monotonic()-parse_start, 6)
                return done(parsed.values, parsed.error)
            except (KeyError, IndexError, TypeError):
                kind = 'invalid_schema'
                return done({}, 'Invalid Gemini response schema or blocked content')
        except KeyUnavailable:
            kind = 'keys_or_quota_unavailable'
            return done({}, 'Gemini paused: keys/quota unavailable; request not sent')
        except httpx.TimeoutException as exc:
            kind = 'client_timeout'; diagnostics['timeout_type'] = type(exc).__name__
            return done({}, 'Gemini client timeout; execution uncertain; no retry or key switch', True)
        except httpx.RequestError as exc:
            kind = 'network_error'; diagnostics['timeout_type'] = type(exc).__name__
            return done({}, 'Gemini network error; execution uncertain; no retry or key switch', True)
        finally:
            if key: await self.pool.release(key, kind)
