"""Kira's documented OpenAI-compatible chat endpoint."""
from __future__ import annotations

import json
import time
import re
import math
from .prompts import messages, PROMPT_VERSION
from dataclasses import dataclass

import httpx


KIRA_CHAT_URL = "https://kiraai.vn/api/v1/chat/completions"


@dataclass(frozen=True)
class BatchResult:
    values: dict[str, str]
    error: str | None = None
    unknown: bool = False
    usage: dict[str, int] | None = None
    diagnostics: dict | None = None


def validate_request_lines(lines):
    if not 1 <= len(lines) <= 3: raise ValueError('Each request must contain 1–3 lines')
    ids = [r.get('id') for r in lines]
    if any(not isinstance(i,str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Request line IDs must be unique and nonempty')
    if any(not isinstance(r.get('source'),str) or '\r' in r['source'] or '\n' in r['source'] for r in lines):
        raise ValueError('Each request source must be one logical unit')


def parse_line_response(content: str, expected: set[str]) -> BatchResult:
    """Reject ambiguous IDs; never pair by order."""
    try:
        if isinstance(content, str):
            fenced = re.fullmatch(r"\s*```(?:json)?\s*\n?(.*?)\n?```\s*", content, re.S | re.I)
            if fenced:
                content = fenced.group(1)
        def pairs(items):
            result={};duplicate_keys=[]
            for key,value in items:
                if key in result:duplicate_keys.append(key)
                result[key]=value
            if duplicate_keys:result['__duplicate_protocol_keys__']=duplicate_keys
            return result
        obj = json.loads(content,object_pairs_hook=pairs)
    except (json.JSONDecodeError, TypeError):
        return BatchResult({}, "Model response is not JSON", diagnostics={'structure_errors':[{'code':'invalid_json','line_ids':sorted(expected)}]})
    # Only a single known wrapper is unambiguous; never extract arbitrary prose
    # or infer IDs from list positions. Conflicting/duplicated JSON keys fail.
    if isinstance(obj,dict) and set(obj) in ({'data'},{'result'}):obj=next(iter(obj.values()))
    if not isinstance(obj, dict) or '__duplicate_protocol_keys__' in obj or not isinstance(obj.get("lines"), list):
        return BatchResult({}, "Response must contain a lines array", diagnostics={'structure_errors':[{'code':'invalid_schema','line_ids':sorted(expected)}]})
    values: dict[str, str] = {}
    seen: set[str] = set()
    invalid = False
    duplicate = False
    structure = []
    for entry in obj["lines"]:
        if not isinstance(entry, dict) or '__duplicate_protocol_keys__' in entry or not isinstance(entry.get("id"), str) or not isinstance(entry.get("text"), str):
            invalid = True
            structure.append({'code':'invalid_entry','line_ids':[entry['id']] if isinstance(entry,dict) and isinstance(entry.get('id'),str) and entry['id'] in expected else []})
            if isinstance(entry,dict) and isinstance(entry.get('id'),str):
                values.pop(entry['id'], None)
                seen.add(entry['id'])
            continue
        line_id, value = entry["id"], entry["text"]
        controls=bool(re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff]',value))
        if line_id not in expected or line_id in seen or "\n" in value or "\r" in value or controls or not value.strip():
            invalid = True
            duplicate = duplicate or line_id in seen
            code = 'unexpected_id' if line_id not in expected else 'duplicate_id' if line_id in seen else 'linebreak' if '\n' in value or '\r' in value else 'control_character' if controls else 'empty_value'
            structure.append({'code':code,'line_ids':[line_id] if line_id in expected else []})
            if line_id in values:
                values.pop(line_id, None)
            seen.add(line_id)
            continue
        seen.add(line_id)
        values[line_id] = value
    missing = expected - values.keys()
    if missing: structure.append({'code':'missing_id','line_ids':sorted(missing)})
    error = "Duplicate or invalid line IDs/values" if invalid or duplicate else "Missing response line IDs" if missing else None
    return BatchResult(values, error, diagnostics={'structure_errors':structure} if structure else None)


class KiraProvider:
    def __init__(self, api_key: str, model: str = "kira-2.5-flash", timeout: float = 90.0,
                 transport: httpx.AsyncBaseTransport | None = None, max_tokens: int | None = None, prompt_version: str = PROMPT_VERSION):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.transport = transport
        self.max_tokens = max_tokens
        self.prompt_version = prompt_version
        self.http_timeout = httpx.Timeout(timeout, connect=min(10.0, timeout), write=min(30.0, timeout), pool=min(10.0, timeout))

    def client(self, concurrency=1):
        async def headers(response):
            timing = response.request.extensions.get('performance_timing')
            if timing is not None: timing['headers_seconds'] = time.monotonic()-timing['started']
            observer = response.request.extensions.get("diagnostic_observer")
            if observer:
                observer("headers", http_status=response.status_code)
        return httpx.AsyncClient(timeout=self.http_timeout, transport=self.transport, follow_redirects=False,
                                 limits=httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency),
                                 event_hooks={"response": [headers]})

    async def translate(self, lines: list[dict], source_lang: str, target_lang: str, *, client=None, observer=None) -> BatchResult:
        if getattr(self,'should_stop',lambda:False)():
            return BatchResult({}, 'Stopped before HTTP send', diagnostics={'failure_kind':'not_sent'})
        validate_request_lines(lines)
        expected = {x["id"] for x in lines}
        body = {"model": self.model, "stream": False,
                "messages": messages(lines, source_lang, target_lang, self.prompt_version)}
        if self.max_tokens is not None:
            body["max_tokens"] = self.max_tokens
        started = time.monotonic()
        measured = None
        parsing_started = None
        diagnostics = {
            'http_started_at': 'unknown',
            "model": self.model, "line_count": len(lines), "source_chars": sum(len(x["source"]) for x in lines),
            "request_chars": len(json.dumps(body, ensure_ascii=False)), "configured_timeout_seconds": self.timeout,
            "timeout_seconds": {"connect": self.http_timeout.connect, "read": self.http_timeout.read,
                                "write": self.http_timeout.write, "pool": self.http_timeout.pool},
            "max_tokens": self.max_tokens,
            "prompt_version": self.prompt_version,
            "context_lines": len({r["id"] for line in lines for r in line.get("context", [])}),
            "sent_body_observed": False,
            "server_execution_known": False,
            "connect_seconds": "unknown", "headers_seconds": "unknown", "body_seconds": "unknown",
        }

        def result(values, error=None, unknown=False, usage=None, kind=None):
            usage = usage or measured
            diagnostics["elapsed_seconds"] = round(time.monotonic()-started, 3)
            if parsing_started is not None:
                diagnostics['parse_seconds'] = round(time.monotonic()-parsing_started, 6)
            else:
                diagnostics['http_seconds'] = diagnostics['elapsed_seconds']
            diagnostics["failure_kind"] = kind
            if usage:
                diagnostics["usage"] = usage
            if observer:
                observer("failure" if error else "parsed", http_status=diagnostics.get("http_status"),
                         exception=diagnostics.get("timeout_type"), reason=kind, elapsed_seconds=diagnostics["elapsed_seconds"],
                         http_seconds=diagnostics.get("http_seconds"), parse_seconds=diagnostics.get("parse_seconds"),
                         accepted_ids=list(values), rejected_ids=list(expected-values.keys()), usage=usage,
                         correlation_id=diagnostics.get("provider_request_id"), state="unknown" if unknown else "error" if error else "valid",
                         finish_reason=diagnostics.get('finish_reason'), content_chars=diagnostics.get('content_chars'),
                         content_json_start=diagnostics.get('content_json_start'), content_json_end=diagnostics.get('content_json_end'),
                         reasoning_tokens=diagnostics.get('reasoning_tokens'))
                if diagnostics.get('http_status') == 200 and error:
                    observer('parsed', state='invalid' if error else 'valid', finish_reason=diagnostics.get('finish_reason'),
                             reason=kind, accepted_ids=list(values), rejected_ids=list(expected-values.keys()), parse_seconds=diagnostics.get('parse_seconds'),
                             content_chars=diagnostics.get('content_chars'), content_json_start=diagnostics.get('content_json_start'),
                             content_json_end=diagnostics.get('content_json_end'), reasoning_tokens=diagnostics.get('reasoning_tokens'))
            return BatchResult(values, error, unknown, usage, dict(diagnostics))

        async def send(active_client):
            from datetime import datetime, timezone
            diagnostics['http_started_at'] = datetime.now(timezone.utc).isoformat(timespec='microseconds')
            timing = {'started': time.monotonic()}
            async def trace(name, info):
                if name.endswith('connect_tcp.started'): timing['connect_started'] = time.monotonic()
                if name.endswith('connect_tcp.complete') and 'connect_started' in timing:
                    diagnostics['connect_seconds'] = time.monotonic()-timing['connect_started']
                if name.endswith("send_request_body.complete"):
                    diagnostics["sent_body_observed"] = True
                    if observer:
                        observer("body_sent", sent_body_observed=True)
            request = active_client.build_request("POST", KIRA_CHAT_URL, headers={"Authorization": f"Bearer {self.api_key}"}, json=body)
            request.extensions.update({"trace": trace, "diagnostic_observer": observer, 'performance_timing': timing})
            if observer:
                observer("http_started", request_chars=diagnostics["request_chars"], context_lines=diagnostics["context_lines"], timeout_seconds=diagnostics["timeout_seconds"], max_tokens=self.max_tokens, server_execution_known=False)
            response = await active_client.send(request)
            diagnostics['headers_seconds'] = timing.get('headers_seconds', 'unknown')
            diagnostics['body_seconds'] = time.monotonic()-timing['started']
            diagnostics['http_version'] = response.http_version
            return response

        try:
            if client is not None:
                response = await send(client)
            else:
                async with self.client() as own_client:
                    response = await send(own_client)
        except httpx.TimeoutException as exc:
            diagnostics["timeout_type"] = type(exc).__name__
            return result({}, f"Client timeout ({type(exc).__name__}): request may have consumed tokens; no automatic retry", True, kind="client_timeout")
        except httpx.ConnectError:
            # ConnectError means establishing the connection failed. A transport
            # reporting a completed body is still treated as uncertain.
            if not diagnostics['sent_body_observed']:
                return result({}, "Cannot connect to Kira; no request body sent", kind="connect_not_sent")
            return result({}, "Cannot connect to Kira; delivery status is uncertain", True, kind="connect_error")
        except httpx.RequestError as exc:
            return result({}, f"Network error ({type(exc).__name__}); delivery status is uncertain", True, kind="network_error")
        diagnostics["http_seconds"] = round(time.monotonic()-started, 3)
        if observer:
            observer("body_received", http_seconds=diagnostics["http_seconds"], http_status=response.status_code)
        parsing_started = time.monotonic()
        diagnostics["http_status"] = response.status_code
        request_id = next((response.headers.get(name) for name in ("x-request-id", "request-id", "x-correlation-id", "cf-ray") if response.headers.get(name)), None)
        if request_id:
            diagnostics["provider_request_id"] = request_id[:256].replace(self.api_key, "[redacted]") if self.api_key else request_id[:256]
        try:
            envelope = response.json()
        except ValueError:
            envelope = None
        usage = envelope.get("usage") if isinstance(envelope, dict) else None
        error_body=envelope.get('error') if isinstance(envelope,dict) else None
        code=error_body.get('code') if isinstance(error_body,dict) else None
        if isinstance(code,str) and re.fullmatch(r'[a-zA-Z0-9_.:-]{1,80}',code):
            diagnostics['provider_error_code']=code.replace(self.api_key,'[redacted]') if self.api_key else code
        measured = {key: int(usage[key]) for key in ("prompt_tokens", "completion_tokens", "total_tokens") if isinstance(usage, dict) and isinstance(usage.get(key), int)}
        details = usage.get('completion_tokens_details') if isinstance(usage, dict) else None
        if isinstance(details, dict) and isinstance(details.get('reasoning_tokens'), int):
            diagnostics['reasoning_tokens'] = details['reasoning_tokens']
        if not request_id and isinstance(envelope, dict) and isinstance(envelope.get("id"), str):
            diagnostics["provider_request_id"] = envelope["id"][:256].replace(self.api_key, "[redacted]") if self.api_key else envelope["id"][:256]
        if response.status_code in (408,500,502,503,504):
            hint=response.headers.get('retry-after')
            if hint:
                diagnostics['retry_after']=hint.replace(self.api_key,'[redacted]') if self.api_key else hint
                try:seconds=float(hint)
                except ValueError:
                    from email.utils import parsedate_to_datetime
                    try:seconds=parsedate_to_datetime(hint).timestamp()-time.time()
                    except (ValueError,TypeError,OverflowError):seconds=None
                if isinstance(seconds,(int,float)) and math.isfinite(seconds):diagnostics['retry_after_seconds']=max(0,seconds)
        if response.status_code == 504:
            return result({}, "Kira gateway HTTP 504: request may have consumed tokens; retry is controlled by job policy", True, measured or None, "http_504")
        if response.status_code == 401:
            return result({}, "Kira rejected the API key (HTTP 401)", kind="authentication")
        if response.status_code == 403:
            return result({}, f"Kira denied access to model {self.model} (HTTP 403); check account permissions", kind="permission")
        quota_codes=('insufficient_quota','quota_exhausted','billing_hard_limit_reached','vnd_balance_exhausted')
        quota_confirmed=isinstance(error_body,dict) and any(value in quota_codes for value in (code,error_body.get('type')))
        if isinstance(error_body,dict) and error_body.get('scope') in ('key','model','account'):
            diagnostics['quota_scope']=error_body['scope']
        if response.status_code==402 and code in ('pro_membership_required','model_permission_denied','model_access_denied'):
            return result({},'Kira model permission required (HTTP 402)',kind='permission')
        if response.status_code==402:
            diagnostics['quota_type']='exhausted' if quota_confirmed else 'unverified'
            reset=response.headers.get('retry-after')
            try:
                value=float(reset)
                if math.isfinite(value) and value>=0:diagnostics['retry_after_seconds']=value
            except (ValueError,TypeError):
                if reset:
                    from email.utils import parsedate_to_datetime
                    try:
                        value=parsedate_to_datetime(reset).timestamp()-time.time()
                        if math.isfinite(value):diagnostics['retry_after_seconds']=max(0,value)
                    except (ValueError,TypeError,OverflowError):pass
            return result({},'Kira HTTP 402: provider confirmed quota' if quota_confirmed else 'Kira HTTP 402: billing/access requires verification',kind='quota_exhausted' if quota_confirmed else 'http_error')
        if response.status_code == 429:
            from email.utils import parsedate_to_datetime
            from datetime import datetime, timezone
            retry_after = response.headers.get('retry-after')
            diagnostics['retry_after'] = retry_after.replace(self.api_key,'[redacted]') if retry_after and self.api_key else retry_after
            diagnostics['rate_limit_headers'] = {k: v.replace(self.api_key,'[redacted]') if self.api_key else v for k, v in response.headers.items() if k.lower().startswith(('x-ratelimit-', 'ratelimit-'))}
            seconds = None
            if retry_after:
                try:
                    value=float(retry_after)
                    if math.isfinite(value) and value>=0:seconds=value
                except ValueError:
                    try: seconds = max(0.0, (parsedate_to_datetime(retry_after)-datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError, OverflowError): pass
            if seconds is None:
                reset=response.headers.get('x-ratelimit-reset-requests') or response.headers.get('ratelimit-reset')
                if reset:
                    try:
                        value=float(reset)
                        if math.isfinite(value) and value>=0:seconds=max(0,value-time.time()) if value>1000000000 else value
                    except ValueError:
                        match=re.fullmatch(r'(\d+(?:\.\d+)?)(ms|s|m)',reset)
                        if match:seconds=float(match[1])*{'ms':.001,'s':1,'m':60}[match[2]]
            diagnostics['retry_after_seconds'] = seconds
            exhausted = quota_confirmed
            diagnostics['quota_type'] = 'exhausted' if exhausted else 'temporary' if seconds is not None else 'unverified'
            return result({}, 'HTTP 429: quota exhausted' if exhausted else 'HTTP 429: cooldown required' if seconds is not None else 'HTTP 429: reset time unknown; bounded backoff required', kind='quota_exhausted' if exhausted else 'rate_limit')
        if response.status_code >= 500:
            return result({}, f"Kira HTTP {response.status_code}: request may have consumed tokens", True, kind="http_server_error")
        if response.status_code==408:
            return result({},'Kira HTTP 408: delivery status uncertain',True,kind='http_timeout')
        if response.status_code in (400, 404):
            return result({}, f"Kira rejected model {self.model} (HTTP {response.status_code}); check model ID and account access", kind="model_or_request")
        if response.status_code >= 400:
            return result({}, f"Kira HTTP {response.status_code} for model {self.model}", kind="http_error")
        try:
            finish_reason=envelope['choices'][0].get('finish_reason')
            diagnostics['finish_reason']=finish_reason if finish_reason in ('stop','length','content_filter','tool_calls','function_call') else 'unknown'
            content = envelope["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("content is not text")
        except (ValueError, KeyError, IndexError, TypeError):
            return result({}, "Invalid chat-completions response structure", kind="invalid_schema")
        finish_reason = envelope['choices'][0].get('finish_reason')
        diagnostics['finish_reason'] = finish_reason if finish_reason in ('stop', 'length', 'content_filter', 'tool_calls', 'function_call') else 'unknown'
        diagnostics['content_chars'] = len(content)
        diagnostics['content_json_start'] = content.lstrip().startswith(('{', '```'))
        diagnostics['content_json_end'] = content.rstrip().endswith(('}', '```'))
        parsed = parse_line_response(content, expected)
        diagnostics.update(parsed.diagnostics or {})
        kind = ("partial_response" if parsed.values else "invalid_line_response") if parsed.error else None
        diagnostics["returned_valid_ids"] = len(parsed.values)
        diagnostics["parse_seconds"] = round(time.monotonic()-parsing_started, 6)
        return result(parsed.values, parsed.error, parsed.unknown, measured or None, kind)
