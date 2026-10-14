"""Nonblocking metadata-only JSONL diagnostics with bounded rotation and export."""
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import re
import threading

FIELDS = set("provider model document_id job_id batch_id original_batch_id attempt_id attempt_number correlation_id elapsed_seconds queue_wait_seconds http_seconds parse_seconds database_seconds gui_seconds http_status exception state line_ids ordinals line_count accepted_ids rejected_ids source_chars request_chars context_lines timeout_seconds configured_concurrency active_at_dispatch active_at_completion prompt_version usage max_tokens reason retry_count sent_body_observed server_execution_known gui_received".split())
FIELDS.update({'display_document_id', 'finish_reason', 'content_chars', 'content_json_start', 'content_json_end', 'reasoning_tokens'})
FIELDS.update({'run_id', 'target_lang', 'key_alias', 'request_kind', 'file_name'})
FIELDS.update({'retry_after', 'retry_after_seconds', 'rate_limit_headers', 'quota_type', 'effective_concurrency'})
FIELDS.update({'request_count', 'success_requests', 'rate_limit_count', 'cooldown_seconds'})
FIELDS.update({'active_batches', 'queued_batches', 'error_lines', 'missing_lines', 'affected_files', 'seconds', 'wait_budget', 'cooldown_limit'})
FIELDS.update({'dispatch_wait_seconds', 'cooldown_wait_seconds', 'semaphore_wait_seconds', 'queue_inserted_at', 'ready_batch_count', 'waiting_retry_count', 'source_instance', 'retry_reason', 'previous_concurrency', 'last_rate_limit_at', 'cooldown_scope', 'reduced_seconds'})
FIELDS.update({'gate_wait_seconds', 'accepted_line_count'})
FIELDS.update({'source_locale','target_locale','check','conclusion','confidence'})
FIELDS.update({'validator_seconds','connect_seconds','headers_seconds','body_seconds','http_started_at','connection_pool_limit','http_version','stack_trace'})
FIELDS.update({'batch_created_at','sqlite_commit_seconds'})
EVENTS = {
    'gateway_backoff': ('WARNING','SCHEDULER','Observed HTTP 504; bounded shared pacing, not provider quota'),
    'shutdown_error': ('ERROR','UI','Safe exit failed; committed results retained, inspect redacted stack frames'),
    'language_checked': ('INFO','QUALITY','Offline target-language check; not semantic certification'),
    'language_started': ('INFO','SCHEDULER','Sequential target language started'),
    'language_completed': ('INFO','SCHEDULER','Target language reconciled; inspect remaining errors'),
    'language_blocked': ('WARNING','SCHEDULER','Language barrier requires intervention'),
    'concurrency_changed': ('INFO', 'SCHEDULER', 'Effective concurrency changed; inspect evidence and recovery reason'),
    'reconciled': ('INFO', 'SCHEDULER', 'Persisted missing results reconciled before completion'),
    'pause_requested_by_user': ('INFO', 'SCHEDULER', 'User requested pause'),
    'rate_limit_cooldown_started': ('WARNING', 'SCHEDULER', 'Shared bounded rate-limit cooldown started'),
    'rate_limit_cooldown_finished': ('INFO', 'SCHEDULER', 'Shared cooldown finished'),
    'automatic_resume': ('INFO', 'SCHEDULER', 'Scheduler resumed after cooldown'),
    'retry_scheduled': ('INFO', 'SCHEDULER', 'Eligible missing lines scheduled under frozen retry budget'),
    'retry_exhausted': ('WARNING', 'SCHEDULER', 'Retry budget exhausted or response not safely retryable'),
    'provider_quota_exhausted': ('WARNING', 'SCHEDULER', 'Provider scope requires intervention; inspect reason'),
    'scheduler_drained': ('INFO', 'SCHEDULER', 'Scheduler stopped dispatching queued work'),
    'job_completed': ('INFO', 'SCHEDULER', 'Job completed; inspect missing line count'),
    'notification': ('INFO', 'UI', 'Completion or intervention notification emitted once'),
    'cooldown': ('WARNING', 'SCHEDULER', 'Provider response requires shared cooldown or user intervention; charging is unknown'),
    'model_list': ('INFO', 'API', 'Explicit Gemini model-list metadata request'),
    'key_state': ('WARNING', 'API', 'Gemini key availability updated from response evidence'),
    "queued": ("INFO", "SCHEDULER", "Batch queued"),
    "selected": ("DEBUG", "SCHEDULER", "Worker selected batch"),
    "persisted": ("INFO", "DATABASE", "Attempt persisted before HTTP dispatch"),
    "http_started": ("INFO", "API", "HTTP call started; server execution unknown"),
    "body_sent": ("DEBUG", "NETWORK", "HTTP transport completed sending request body"),
    "headers": ("INFO", "NETWORK", "Response headers received"),
    "body_received": ("DEBUG", "NETWORK", "Full response received"),
    "parsed": ("INFO", "PARSER", "Response parsed and line IDs validated"),
    "failure": ("ERROR", "API", "Request failed or response unusable"),
    "saved": ("INFO", "DATABASE", "Batch result committed"),
    "database_error": ("ERROR", "DATABASE", "Database save failed; result cannot be assumed persisted"),
    "gui_emitted": ("DEBUG", "UI", "GUI notification emitted; receipt not yet confirmed"),
    "gui_received": ("INFO", "UI", "GUI notification received"),
    "gui_missing": ("WARNING", "UI", "No GUI acknowledgment observed"),
    "gui_error": ("ERROR", "UI", "GUI update failed"),
    "retry": ("WARNING", "SCHEDULER", "Automatic retry reserved under frozen job policy; may incur additional cost"),
    "retry_blocked": ("WARNING", "SCHEDULER", "Retry not dispatched"),
    "finished": ("INFO", "SCHEDULER", "Job execution ended"),
    "scheduler_error": ("ERROR", "SCHEDULER", "Scheduler exception; job interrupted"),
    "imported": ("INFO", "IMPORT", "New independent import instance saved"),
    "deleted": ("INFO", "DATABASE", "Selected history data deleted in transaction"),
    "exported": ("INFO", "EXPORT", "Document export completed"),
    "export_error": ("ERROR", "EXPORT", "Export failed"),
    "import_error": ("ERROR", "IMPORT", "Import failed"),
    "rotation": ("WARNING", "DATABASE", "Older diagnostics rotated or queue overflowed"),
}


class DiagnosticLog:
    def __init__(self, directory, max_bytes=2_000_000, backups=3, max_events=2000):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "console.jsonl"
        self.max_bytes, self.backups = max_bytes, backups
        self.events = deque(maxlen=max_events)
        self.lock = threading.RLock()
        self.io_lock = threading.Lock()
        self.secrets = set()
        self.failure = None
        self.pending = queue.Queue(maxsize=5000)
        self.closed = False
        self.cleared_before = ''
        for path in [self.directory / f"console.{i}.jsonl" for i in range(backups, 0, -1)] + [self.path]:
            if path.exists():
                try:
                    with path.open(encoding="utf-8") as file:
                        for line in file:
                            value = json.loads(line)
                            if value.get("event") in EVENTS:
                                self.events.append(value)
                except (OSError, ValueError):
                    self.failure = "log_read_error"
        self.thread = threading.Thread(target=self._write, daemon=True, name="TransComicDiagnostics")
        self.thread.start()

    def register_secret(self, value):
        if value:
            with self.lock:
                self.secrets.add(value)

    def clean(self, value):
        if isinstance(value, dict):
            return {k: self.clean(v) for k, v in value.items() if k in FIELDS or k in {"connect", "read", "write", "pool", "prompt_tokens", "completion_tokens", "total_tokens"} or k.lower().startswith(('x-ratelimit-', 'ratelimit-'))}
        if isinstance(value, (list, tuple)):
            return [self.clean(v) for v in value[:100]]
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[redacted]")
            value = re.sub(r"(?i)bearer\s+\S+|sk-[A-Za-z0-9_-]+", "[redacted]", value)
            return value[:512]
        return value if isinstance(value, (int, float, bool)) or value is None else type(value).__name__

    def emit(self, event, **metadata):
        if self.closed or event not in EVENTS:
            return
        level, category, description = EVENTS[event]
        if event == 'gui_received' and metadata.get('reason') == 'other_import_not_displayed': level = 'DEBUG'
        with self.lock:
            record = {"time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "level": level,
                      "category": category, "event": event, "description": description, **self.clean(metadata)}
            self.events.append(record)
        try:
            self.pending.put_nowait(record)
        except queue.Full:
            self.failure = "log_queue_full"

    def snapshot(self):
        with self.lock:
            # Re-redact when a key was registered after loading previous files.
            return [{k: v if k in ("time", "level", "category", "event", "description") else self.clean(v) for k, v in row.items() if k in FIELDS or k in ("time", "level", "category", "event", "description")} for row in self.events]

    def _write(self):
        while True:
            row = self.pending.get()
            try:
                if row is None:
                    return
                with self.io_lock:
                    if row['time'] <= self.cleared_before:
                        continue
                    if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                        for i in range(self.backups, 0, -1):
                            source = self.path if i == 1 else self.directory / f"console.{i-1}.jsonl"
                            if source.exists():
                                source.replace(self.directory / f"console.{i}.jsonl")
                    with self.path.open("a", encoding="utf-8") as file:
                        file.write(json.dumps(row, ensure_ascii=False) + "\n")
                        file.flush()
            except OSError:
                self.failure = "log_write_error"
            finally:
                self.pending.task_done()

    def flush(self):
        self.pending.join()

    def clear(self):
        self.flush()
        with self.io_lock, self.lock:
            self.cleared_before = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
            for path in [self.path] + [self.directory / f"console.{i}.jsonl" for i in range(1, self.backups+1)]:
                path.unlink(missing_ok=True)
            self.events.clear()

    def export(self, path, rows=None):
        rows = self.snapshot() if rows is None else rows
        report = {"log_health": self.failure or "ok", "events": rows}
        path = Path(path)
        content = json.dumps(report, ensure_ascii=False, indent=2)
        path.write_text(content, encoding="utf-8")

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.pending.put(None, timeout=1)
            except queue.Full:
                self.failure = 'shutdown_log_queue_full'
                return
            self.thread.join(5)
