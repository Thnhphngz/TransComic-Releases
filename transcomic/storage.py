"""Transactional document and translation persistence."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
import time
from contextlib import contextmanager
from pathlib import Path

from .documents import ImportedText, TextLine, translatable
from .quality import collect
from .diagnostics import DiagnosticLog


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, path TEXT NOT NULL, digest TEXT NOT NULL, snapshot BLOB NOT NULL,
 encoding TEXT NOT NULL, source_lang TEXT NOT NULL, target_lang TEXT NOT NULL,
 format TEXT NOT NULL DEFAULT 'txt',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS source_identity ON documents(path, digest);
CREATE TABLE IF NOT EXISTS lines (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id), ordinal INTEGER NOT NULL,
 source TEXT NOT NULL, ending TEXT NOT NULL, translation TEXT, state TEXT NOT NULL,
 source_revision INTEGER NOT NULL DEFAULT 0, translation_revision INTEGER NOT NULL DEFAULT 0,
 error TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE(document_id, ordinal));
CREATE INDEX IF NOT EXISTS lines_by_document ON lines(document_id, ordinal);
CREATE TABLE IF NOT EXISTS document_units (
 document_id TEXT NOT NULL REFERENCES documents(id), line_id TEXT NOT NULL UNIQUE REFERENCES lines(id),
 locator TEXT NOT NULL, PRIMARY KEY(document_id, locator));
CREATE TABLE IF NOT EXISTS line_edits (
 id INTEGER PRIMARY KEY AUTOINCREMENT, line_id TEXT NOT NULL REFERENCES lines(id),
 field TEXT NOT NULL, old_value TEXT, new_value TEXT, revision INTEGER NOT NULL,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS line_edits_by_line ON line_edits(line_id, id);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id), provider TEXT NOT NULL,
 model TEXT NOT NULL, source_lang TEXT NOT NULL, target_lang TEXT NOT NULL,
 concurrency INTEGER NOT NULL, state TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS batches (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), state TEXT NOT NULL,
 payload TEXT NOT NULL, error TEXT, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS batches_by_job ON batches(job_id);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quality_warnings (
 line_id TEXT PRIMARY KEY REFERENCES lines(id), source_revision INTEGER NOT NULL,
 translation_revision INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS secrets (key TEXT PRIMARY KEY, encrypted BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS request_attempts (
 id TEXT PRIMARY KEY, original_batch_id TEXT NOT NULL REFERENCES batches(id),
 attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 6), state TEXT NOT NULL,
 created_at TEXT NOT NULL, completed_at TEXT, diagnostics TEXT,
 UNIQUE(original_batch_id,attempt_number));
CREATE TABLE IF NOT EXISTS translation_runs (
 id TEXT PRIMARY KEY, config TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'ready',
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS gemini_keys (
 id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE, encrypted BLOB NOT NULL,
 priority INTEGER NOT NULL, project TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'unverified',
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS api_text_versions (
 attempt_id TEXT NOT NULL REFERENCES request_attempts(id), line_id TEXT NOT NULL REFERENCES lines(id),
 raw_text TEXT NOT NULL, processed_text TEXT NOT NULL, normalization TEXT NOT NULL,
 warnings TEXT NOT NULL, accepted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(attempt_id,line_id));
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA busy_timeout=5000")
            self.db.executescript(SCHEMA)
            attempt_sql = self.db.execute("SELECT sql FROM sqlite_master WHERE name='request_attempts'").fetchone()[0]
            if 'BETWEEN 1 AND 6' not in attempt_sql:
                # Keep the original table name and foreign key targets while rebuilding.
                self.db.execute('PRAGMA foreign_keys=OFF')
                self.db.execute('BEGIN IMMEDIATE')
                try:
                    self.db.execute('CREATE TABLE attempts_v7 (id TEXT PRIMARY KEY, original_batch_id TEXT NOT NULL REFERENCES batches(id), attempt_number INTEGER NOT NULL CHECK(attempt_number BETWEEN 1 AND 6), state TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT, diagnostics TEXT, UNIQUE(original_batch_id,attempt_number))')
                    self.db.execute('INSERT INTO attempts_v7 SELECT * FROM request_attempts')
                    self.db.execute('DROP TABLE request_attempts')
                    self.db.execute('ALTER TABLE attempts_v7 RENAME TO request_attempts')
                    self.db.execute('COMMIT')
                except BaseException:
                    self.db.execute('ROLLBACK'); raise
                finally:
                    self.db.execute('PRAGMA foreign_keys=ON')
            if 'auto_retries' not in {r['name'] for r in self.db.execute('PRAGMA table_info(jobs)')}:
                self.db.execute('ALTER TABLE jobs ADD COLUMN auto_retries INTEGER NOT NULL DEFAULT 0')
            self.db.execute("DROP INDEX IF EXISTS document_identity")
            columns = {row["name"] for row in self.db.execute("PRAGMA table_info(documents)")}
            if "format" not in columns:
                self.db.execute("ALTER TABLE documents ADD COLUMN format TEXT NOT NULL DEFAULT 'txt'")
            for table, column, definition in [("jobs", "timeout", "REAL NOT NULL DEFAULT 90"), ("batches", "diagnostics", "TEXT"), ("jobs", "prompt_version", "TEXT NOT NULL DEFAULT 'legacy-v1'"), ("jobs", "mode", "TEXT NOT NULL DEFAULT 'translation'"), ("lines", "attempt_kind", "TEXT NOT NULL DEFAULT 'translation'"), ("jobs", "retry_504", "INTEGER NOT NULL DEFAULT 0"), ("jobs", "max_requests", "INTEGER"), ("lines", "translation_source_revision", "INTEGER")]:
                existing = {row["name"] for row in self.db.execute(f"PRAGMA table_info({table})")}
                if column not in existing:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                    if table == "lines" and column == "translation_source_revision":
                        self.db.execute("UPDATE lines SET translation_source_revision=source_revision WHERE translation IS NOT NULL AND state!='stale'")
            self.db.execute("INSERT INTO meta(key,value) VALUES ('schema_version','5') ON CONFLICT(key) DO UPDATE SET value='5'")
            for table, column, definition in [('documents', 'source_instance', "TEXT NOT NULL DEFAULT ''"), ('jobs', 'run_id', 'TEXT REFERENCES translation_runs(id)'), ('jobs', 'config', "TEXT NOT NULL DEFAULT '{}'" )]:
                if column not in {r['name'] for r in self.db.execute(f'PRAGMA table_info({table})')}:
                    self.db.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
            self.db.execute("UPDATE documents SET source_instance=id WHERE source_instance=''")
            self.db.execute("UPDATE translation_runs SET state='interrupted' WHERE state IN ('running','pausing','stopping','user_paused','waiting_rate_limit','retry_scheduled')")
            for saved in self.db.execute("SELECT id,config FROM translation_runs WHERE state='interrupted'").fetchall():
                snapshot=json.loads(saved['config'])
                states=snapshot.get('language_states',{})
                changed=False
                for locale,state in list(states.items()):
                    if state in ('running','user_paused','waiting_rate_limit','stopping'):
                        states[locale]='interrupted';changed=True
                if changed:self.db.execute('UPDATE translation_runs SET config=? WHERE id=?',(json.dumps(snapshot,ensure_ascii=False),saved['id']))
            self.db.execute("UPDATE meta SET value='8' WHERE key='schema_version'")
            # A crash after dispatch cannot be distinguished from an unfinished request.
            self.db.execute("UPDATE batches SET state='unknown', error='Ứng dụng đóng khi request đang chạy' WHERE state='inflight'")
            self.db.execute("UPDATE jobs SET state='interrupted' WHERE state IN ('running','pausing','stopping','user_paused','waiting_rate_limit','retry_scheduled')")
            self.db.execute("UPDATE lines SET state='unknown', error='Ứng dụng đóng khi request đang chạy' WHERE state='processing'")
            self.db.execute("UPDATE request_attempts SET state='unknown' WHERE state IN ('prepared','inflight')")
        self.log = DiagnosticLog(self.path.parent / (self.path.stem + "_logs"))

    def close(self):
        if not self.log.closed: self.log.close()
        with self.lock:
            self.db.close()

    @contextmanager
    def transaction(self):
        with self.lock:
            nested = self.db.in_transaction
            savepoint = "edit_" + uuid.uuid4().hex
            self.db.execute(f"SAVEPOINT {savepoint}" if nested else "BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.db.execute(f"ROLLBACK TO {savepoint}" if nested else "ROLLBACK")
                if nested:
                    self.db.execute(f"RELEASE {savepoint}")
                raise
            else:
                try:
                    commit_started = time.perf_counter()
                    self.db.execute(f"RELEASE {savepoint}" if nested else "COMMIT")
                    if not nested:
                        if not hasattr(self,'transaction_timing'): self.transaction_timing=threading.local()
                        self.transaction_timing.commit_seconds=time.perf_counter()-commit_started
                except BaseException:
                    if self.db.in_transaction:
                        self.db.execute(f"ROLLBACK TO {savepoint}" if nested else "ROLLBACK")
                        if nested:
                            self.db.execute(f"RELEASE {savepoint}")
                    raise

    def import_document(self, path: str | Path, data: ImportedText, source_lang="Tự động", target_lang="Tiếng Việt",
                        document_format: str = "txt", locators: list[str] | None = None) -> tuple[str, bool]:
        if document_format not in ("txt", "docx"):
            raise ValueError("Unsupported document format")
        if document_format == "docx" and (locators is None or len(locators) != len(data.lines) or len(set(locators)) != len(locators)):
            raise ValueError("DOCX requires one stable locator per unit")
        identity = str(Path(path).resolve())
        digest = hashlib.sha256(data.raw).hexdigest()
        with self.transaction():
            doc_id = str(uuid.uuid4())
            self.db.execute("INSERT INTO documents(id,path,digest,snapshot,encoding,source_lang,target_lang,format) VALUES (?,?,?,?,?,?,?,?)",
                            (doc_id, identity, digest, data.raw, data.encoding, source_lang, target_lang, document_format))
            self.db.execute('UPDATE documents SET source_instance=? WHERE id=?', (doc_id, doc_id))
            line_rows = [(str(uuid.uuid4()), doc_id, i, line.text, line.ending, "pending" if translatable(line.text) else "skip")
                         for i, line in enumerate(data.lines)]
            self.db.executemany("INSERT INTO lines(id,document_id,ordinal,source,ending,state) VALUES (?,?,?,?,?,?)", line_rows)
            if document_format == "docx":
                self.db.executemany("INSERT INTO document_units(document_id,line_id,locator) VALUES (?,?,?)",
                                    [(doc_id, line_rows[i][0], locator) for i, locator in enumerate(locators or [])])
        self.log.emit("imported", document_id=doc_id, line_count=len(line_rows), state="new")
        return doc_id, True

    def documents(self) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT id,path,format,source_lang,target_lang,created_at,source_instance FROM documents ORDER BY created_at DESC,rowid DESC")]

    def document(self, doc_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
            if row is None:
                raise KeyError(doc_id)
            return dict(row)

    def lines(self, doc_id: str) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT * FROM lines WHERE document_id=? ORDER BY ordinal", (doc_id,))]

    def units(self, doc_id: str) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute(
                "SELECT l.*,u.locator FROM lines l JOIN document_units u ON u.line_id=l.id WHERE l.document_id=? ORDER BY l.ordinal", (doc_id,))]

    def line(self, line_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
            if row is None:
                raise KeyError(line_id)
            return dict(row)

    def edit_line(self, line_id: str, column: str, value: str):
        if column not in ("source", "translation") or "\n" in value or "\r" in value:
            raise ValueError("Only one logical line may be edited")
        with self.transaction():
            row = self.db.execute("SELECT * FROM lines WHERE id=?", (line_id,)).fetchone()
            if row is None:
                raise KeyError(line_id)
            if column == "source":
                state = "skip" if not translatable(value) else "stale" if row["translation"] else "pending"
                self.db.execute("UPDATE lines SET source=?, source_revision=source_revision+1, state=?, error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                (value, state, line_id))
                revision = row["source_revision"] + 1
            else:
                self.db.execute("UPDATE lines SET translation=?, translation_revision=translation_revision+1, state=?, error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                (value or None, "done" if value else "pending", line_id))
                self.db.execute("UPDATE lines SET translation_source_revision=source_revision WHERE id=?", (line_id,))
                revision = row["translation_revision"] + 1
            self.db.execute("INSERT INTO line_edits(line_id,field,old_value,new_value,revision) VALUES (?,?,?,?,?)",
                            (line_id, column, row[column], value, revision))
            self.db.execute("UPDATE lines SET attempt_kind='manual' WHERE id=?", (line_id,))
            self.db.execute("DELETE FROM quality_warnings WHERE line_id=?", (line_id,))

    def create_job(self, doc_id: str, model: str, source_lang: str, target_lang: str, concurrency: int, line_ids: list[str] | None = None, timeout: float = 90, *, retry_504: bool | None = None, max_requests: int | None = None, provider='kira', run_id=None, config=None, allow_shared_document=False) -> str:
        if provider not in ('kira', 'gemini'): raise ValueError('Unsupported provider')
        from .languages import validate_pair
        source_entry,target_entry=validate_pair(source_lang,target_lang)
        source_lang,target_lang=source_entry.name,target_entry.name
        maximum = 50 if provider == "kira" else 30
        if not 1 <= concurrency <= maximum:
            raise ValueError(f"Concurrency must be between 1 and {maximum}")
        if not 30 <= timeout <= 300:
            raise ValueError("Timeout must be between 30 and 300 seconds")
        if max_requests is not None and max_requests < 1:
            raise ValueError("Request budget must be positive")
        retry_504 = self.setting("retry_504", "1") == "1" if retry_504 is None else retry_504
        if provider == 'gemini': retry_504 = False
        with self.transaction():
            existing = self.db.execute("SELECT id FROM jobs WHERE document_id=? AND state IN ('ready','running','paused','pausing','stopping','user_paused','waiting_rate_limit','retry_scheduled')", (doc_id,)).fetchone()
            if existing and not allow_shared_document:
                raise ValueError("A translation job already exists for this document")
            rows = self.lines(doc_id)
            from .status import usable
            wanted = set(line_ids) if line_ids is not None else None
            eligible = [r for r in rows if translatable(r["source"]) and (wanted is None and r["state"] == "pending" and not usable(r) or wanted is not None and r["id"] in wanted)]
            if not eligible:
                raise ValueError("No lines need translation")
            if not self.db.execute('SELECT 1 FROM jobs WHERE document_id=?', (doc_id,)).fetchone() and not any(r['translation'] for r in rows):
                self.db.execute('UPDATE documents SET source_lang=?,target_lang=? WHERE id=?', (source_lang, target_lang, doc_id))
            job_id = str(uuid.uuid4())
            self.db.execute("INSERT INTO jobs(id,document_id,provider,model,source_lang,target_lang,concurrency,state,timeout,prompt_version,mode,retry_504,max_requests) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (job_id, doc_id, provider, model, source_lang, target_lang, concurrency, "ready", timeout, "review-v2", "retranslation" if line_ids is not None else "translation", int(retry_504), max_requests))
            retries = int(self.setting('auto_retries', '5'))
            if not 0 <= retries <= 5: raise ValueError('Invalid automatic retry setting')
            from .prompts import PROMPT_VERSION
            frozen = {**(config or {}), 'request_interval': float(self.setting('request_interval', '0')), 'auto_retries': retries, 'prompt_version': PROMPT_VERSION,
                      'source_locale':source_entry.locale,'target_locale':target_entry.locale}
            for key, default in [('rate_wait_budget', 300), ('rate_cooldown_limit', 10), ('rate_backoff_max', 30)]:
                frozen.setdefault(key, float(self.setting(key, str(default))))
            self.db.execute('UPDATE jobs SET run_id=?,config=?,auto_retries=?,prompt_version=? WHERE id=?', (run_id, json.dumps(frozen), retries, PROMPT_VERSION, job_id))
            for offset in range(0, len(eligible), 3):
                chunk = eligible[offset:offset + 3]
                payload = [{"id": r["id"], "source": r["source"], "source_revision": r["source_revision"], "translation_revision": r["translation_revision"]} for r in chunk]
                # Four neighbors on each side, at most eight reference lines and 4000 characters.
                candidates = {r["id"]: r for x in chunk for r in rows[max(0, x["ordinal"]-4):x["ordinal"]+5]}
                neighbors = [r for r in candidates.values() if r["id"] not in {x["id"] for x in chunk}]
                neighbors = sorted(neighbors, key=lambda r: min(abs(r["ordinal"]-x["ordinal"]) for x in chunk))[:8]
                context, budget = [], 4000
                for r in sorted(neighbors, key=lambda r: r["ordinal"]):
                    if len(r["source"]) <= budget:
                        context.append({"id": r["id"], "source": r["source"]})
                        budget -= len(r["source"])
                payload[0]["context"] = context
                from datetime import datetime, timezone
                created = datetime.now(timezone.utc).isoformat(timespec='microseconds')
                self.db.execute("INSERT INTO batches(id,job_id,state,payload,diagnostics) VALUES (?,?,?,?,?)", (str(uuid.uuid4()), job_id, "pending", json.dumps(payload, ensure_ascii=False), json.dumps({'batch_created_at':created})))
        for batch in self.batches(job_id):
            self.log.emit("queued", provider=provider, model=model, document_id=doc_id, job_id=job_id, run_id=run_id, target_lang=target_lang, batch_id=batch["id"], line_ids=[r["id"] for r in batch["payload"]], line_count=len(batch["payload"]), state="pending")
        return job_id

    def job(self, job_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return dict(row) if row else {}

    def jobs(self) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC")]

    def batches(self, job_id: str, state: str | None = None) -> list[dict]:
        with self.lock:
            sql = "SELECT * FROM batches WHERE job_id=?" + (" AND state=?" if state else "") + " ORDER BY rowid"
            rows = self.db.execute(sql, (job_id, state) if state else (job_id,))
            return [{**dict(r), "payload": json.loads(r["payload"]), "diagnostics": json.loads(r["diagnostics"]) if r["diagnostics"] else None} for r in rows]

    def batch(self, batch_id):
        with self.lock:
            row = self.db.execute('SELECT * FROM batches WHERE id=?', (batch_id,)).fetchone()
            if row is None: raise KeyError(batch_id)
            return {**dict(row), 'payload': json.loads(row['payload']), 'diagnostics': json.loads(row['diagnostics']) if row['diagnostics'] else None}

    def job_state(self, job_id: str, state: str):
        with self.transaction():
            self.db.execute("UPDATE jobs SET state=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (state, job_id))

    def claim_batch(self, batch_id: str) -> list[dict]:
        with self.transaction():
            batch = self.db.execute("SELECT payload FROM batches WHERE id=? AND state='pending'", (batch_id,)).fetchone()
            if batch is None:
                return []
            valid = []
            for item in json.loads(batch["payload"]):
                row = self.db.execute("SELECT source_revision,translation_revision,source,translation FROM lines WHERE id=?", (item["id"],)).fetchone()
                if row and row["source_revision"] == item["source_revision"] and row["translation_revision"] == item["translation_revision"] and row["source"] == item["source"]:
                    valid.append(item)
                    self.db.execute("UPDATE lines SET state='processing', attempt_kind=(SELECT j.mode FROM jobs j JOIN batches b ON b.job_id=j.id WHERE b.id=?) WHERE id=?", (batch_id, item["id"]))
                elif row:
                    state = ("done" if row["translation"] else "pending") if row["translation_revision"] != item["translation_revision"] else ("stale" if row["translation"] else "pending")
                    self.db.execute("UPDATE lines SET state=? WHERE id=?", (state, item["id"]))
            original_payload = json.loads(batch["payload"])
            if valid and original_payload:
                valid[0]["context"] = original_payload[0].get("context", [])
            self.db.execute("UPDATE batches SET state=?, payload=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                            ("inflight" if valid else "superseded", json.dumps(valid, ensure_ascii=False), batch_id))
            return valid

    def release_unsent(self, batch_id):
        with self.transaction():
            row = self.db.execute("SELECT payload FROM batches WHERE id=? AND state='inflight'", (batch_id,)).fetchone()
            if row and not self.attempts(batch_id):
                self.db.execute("UPDATE batches SET state='pending' WHERE id=?", (batch_id,))
                self.db.executemany("UPDATE lines SET state='pending' WHERE id=? AND state='processing'", [(r['id'],) for r in json.loads(row['payload'])])

    def finish_batch(self, batch_id: str, results: dict[str, str] | None, error: str | None = None, unknown: bool = False, diagnostics: dict | None = None, *, expected_attempt_id=None):
        with self.transaction():
            if expected_attempt_id:
                attempts = self.attempts(batch_id)
                if not attempts or attempts[-1]['id'] != expected_attempt_id:
                    return []
            row = self.db.execute("SELECT payload FROM batches WHERE id=? AND state='inflight'", (batch_id,)).fetchone()
            if row is None:
                return []
            payload = json.loads(row["payload"])
            expected = {item["id"] for item in payload}
            results = results or {}
            diagnostics = diagnostics if diagnostics is not None else {}
            rejected_language = {}
            if any(key not in expected for key in results):
                results = {}
                error = "Response contains an unexpected line ID"
            if expected_attempt_id:
                from .postprocess import normalize, VERSION
                processed_results = {}
                for item in payload:
                    if item['id'] not in results: continue
                    raw = results[item['id']]
                    processed, notes = normalize(item['source'], raw)
                    self.db.execute('INSERT OR REPLACE INTO api_text_versions VALUES (?,?,?,?,?,?,0)', (expected_attempt_id, item['id'], raw, processed, VERSION, json.dumps(notes)))
                    if processed.strip(): processed_results[item['id']] = processed
                    else: error = 'Normalization left no ordinary text; review required'
                results = processed_results
            from .language_validator import validator, WRONG_LANGUAGE_CONFIRMED
            job = self.job(self.batch(batch_id)['job_id'])
            validation_started = time.perf_counter()
            for item in payload:
                if item['id'] not in results: continue
                check = validator.validate(item['source'], results[item['id']], job['source_lang'], job['target_lang'], item['id'])
                from .languages import language
                self.log.emit('language_checked', source_locale=language(job['source_lang']).locale, target_locale=language(job['target_lang']).locale, batch_id=batch_id, line_ids=[item['id']], check='offline_language', conclusion=check.conclusion, confidence=check.confidence, reason=check.reason, attempt_id=expected_attempt_id, attempt_number=self.attempts(batch_id)[-1]['attempt_number'] if expected_attempt_id else None)
                if check.conclusion == WRONG_LANGUAGE_CONFIRMED:
                    rejected_language[item['id']] = check.reason
            diagnostics['validator_seconds'] = time.perf_counter()-validation_started
            if rejected_language:
                results = {k:v for k,v in results.items() if k not in rejected_language}
                if unknown:
                    diagnostics.setdefault('failure_kind','network_error')
                elif diagnostics.get('failure_kind') in (None,'partial_response','invalid_line_response','invalid_schema','wrong_target_language'):
                    diagnostics['failure_kind'] = 'wrong_target_language'
                diagnostics['wrong_language_ids'] = list(rejected_language)
            state = "unknown" if unknown else "done" if len(results) == len(expected) else "partial" if results else "error"
            self.db.execute("UPDATE batches SET state=?, error=?, diagnostics=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (state, error, json.dumps(diagnostics, ensure_ascii=False) if diagnostics else None, batch_id))
            accepted = []
            for item in payload:
                current = self.db.execute("SELECT * FROM lines WHERE id=?", (item["id"],)).fetchone()
                if current["translation_revision"] != item["translation_revision"]:
                    # A manual edit always wins, even if the source changed too.
                    self.db.execute("UPDATE lines SET state=? WHERE id=?", ("done" if current["translation"] else "pending", item["id"]))
                elif current["source_revision"] != item["source_revision"]:
                    self.db.execute("UPDATE lines SET state=? WHERE id=?", ("stale" if current["translation"] else "pending", item["id"]))
                elif item["id"] in results:
                    if expected_attempt_id:
                        self.db.execute('UPDATE api_text_versions SET accepted=1 WHERE attempt_id=? AND line_id=?', (expected_attempt_id, item['id']))
                    accepted.append(item['id'])
                    self.db.execute("INSERT INTO line_edits(line_id,field,old_value,new_value,revision) VALUES (?,?,?,?,?)",
                                    (item["id"], "translation", current["translation"], results[item["id"]], current["translation_revision"]+1))
                    self.db.execute("UPDATE lines SET translation=?, translation_revision=translation_revision+1, state='done', error=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                    (results[item["id"]], item["id"]))
                    self.db.execute("UPDATE lines SET translation_source_revision=source_revision WHERE id=?", (item["id"],))
                else:
                    self.db.execute("UPDATE lines SET state=?, error=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                                    ("unknown" if unknown else "wrong_target_language" if item['id'] in rejected_language else "error", error if unknown and error else rejected_language.get(item['id']) or error or "Missing valid response for line ID", item["id"]))
                self.db.execute("DELETE FROM quality_warnings WHERE line_id=?", (item["id"],))
            return accepted

    def warning_rows(self, doc_id):
        with self.transaction():
            doc=self.document(doc_id)
            rows_before = self.lines(doc_id)
            # Include text, locale, state and revisions: old history, manual edits,
            # source changes and retry failures must all invalidate the cache.
            signature = (doc['source_lang'], doc['target_lang'], tuple(tuple(r.get(k) for k in
                         ('id','source','translation','source_revision','translation_revision','translation_source_revision','state','error','attempt_kind')) for r in rows_before))
            cache = getattr(self, '_warning_cache', {})
            if cache.get(doc_id, (None,))[0] == signature:
                import copy
                return copy.deepcopy(cache[doc_id][1])
            self.validate_document_language(doc_id)
            rows = collect([{**r,'source_lang':doc['source_lang'],'target_lang':doc['target_lang']} for r in self.lines(doc_id)])
            for row in self.lines(doc_id):
                if row['attempt_kind'] == 'manual': continue
                trace = self.db.execute('SELECT v.* FROM api_text_versions v JOIN request_attempts a ON a.id=v.attempt_id WHERE v.line_id=? AND v.accepted=1 ORDER BY a.created_at DESC LIMIT 1', (row['id'],)).fetchone()
                if trace and trace['processed_text'] == row['translation']:
                    notes = json.loads(trace['warnings'])
                    if notes:
                        existing_row = next((r for r in rows if r['id']==row['id']), None)
                        if existing_row is None:
                            existing_row = {**row, 'warnings': []}; rows.append(existing_row)
                        existing_row['warnings'].extend(('Hậu xử lý', note) for note in notes)
            existing = {r["line_id"]: (r["source_revision"], r["translation_revision"], r["payload"]) for r in self.db.execute("SELECT q.* FROM quality_warnings q JOIN lines l ON l.id=q.line_id WHERE l.document_id=?", (doc_id,))}
            latest = {r["id"]: (r["source_revision"], r["translation_revision"], json.dumps(r["warnings"], ensure_ascii=False)) for r in rows}
            for line_id in existing.keys()-latest.keys():
                self.db.execute("DELETE FROM quality_warnings WHERE line_id=?", (line_id,))
            for line_id, value in latest.items():
                if existing.get(line_id) != value:
                    self.db.execute("INSERT OR REPLACE INTO quality_warnings VALUES (?,?,?,?)", (line_id, *value))
            import copy
            self._warning_cache = {doc_id: (signature, copy.deepcopy(rows))}
            return rows

    def validate_document_language(self, doc_id):
        """Local history/edit check; retain text and revisions, never send requests."""
        from .language_validator import validator, WRONG_LANGUAGE_CONFIRMED
        with self.transaction():
            doc=self.document(doc_id)
            for row in self.lines(doc_id):
                if not row['translation'] or row['state'] == 'processing': continue
                check=validator.validate(row['source'],row['translation'],doc['source_lang'],doc['target_lang'],row['id'])
                if check.conclusion==WRONG_LANGUAGE_CONFIRMED:
                    self.db.execute("UPDATE lines SET state='wrong_target_language',error=?,translation_source_revision=NULL WHERE id=?",(check.reason,row['id']))
                    if row['attempt_kind'] != 'manual':
                        for job in self.jobs():
                            if job['document_id'] != doc_id: continue
                            for batch in self.batches(job['id']):
                                attempts=self.attempts(batch['id'])
                                if batch['state'] not in ('done','partial') or not attempts or attempts[-1]['state']!='finished': continue
                                if batch['state']=='partial' and (batch['diagnostics'] or {}).get('failure_kind')!='wrong_target_language': continue
                                item=next((r for r in batch['payload'] if r['id']==row['id']),None)
                                if not item or item['source_revision']!=row['source_revision'] or item['translation_revision']+1!=row['translation_revision']: continue
                                item['translation_revision']=row['translation_revision']
                                diagnostics={**(attempts[-1]['diagnostics'] or {}),'failure_kind':'wrong_target_language'}
                                self.db.execute("UPDATE batches SET state='partial',payload=?,diagnostics=? WHERE id=?",(json.dumps(batch['payload']),json.dumps(diagnostics),batch['id']))
                                self.db.execute("UPDATE request_attempts SET diagnostics=? WHERE id=?",(json.dumps(diagnostics),attempts[-1]['id']))

    def replace_edits(self, edits, expected=None):
        """Atomic grouped editing; each change increments revisions to reject late API results."""
        with self.transaction():
            if expected and any(self.line(line_id)[field+'_revision'] != revision for (line_id, field), revision in expected.items()):
                raise ValueError('Content changed since preview; refresh and confirm again')
            before = [(line_id, field, self.line(line_id)[field] or "", value) for line_id, field, value in edits]
            for line_id, field, _, value in before:
                self.edit_line(line_id, field, value)
            return before

    def record_batch_diagnostics(self, batch_id: str, diagnostics: dict):
        with self.transaction():
            self.db.execute("UPDATE batches SET diagnostics=? WHERE id=?", (json.dumps(diagnostics, ensure_ascii=False), batch_id))

    def attempts(self, batch_id):
        with self.lock:
            return [{**dict(r), "diagnostics": json.loads(r["diagnostics"]) if r["diagnostics"] else None} for r in self.db.execute("SELECT * FROM request_attempts WHERE original_batch_id=? ORDER BY attempt_number", (batch_id,))]

    def prepare_attempt(self, batch_id, number):
        from datetime import datetime, timezone
        with self.transaction():
            job = dict(self.db.execute("SELECT j.* FROM jobs j JOIN batches b ON b.job_id=j.id WHERE b.id=?", (batch_id,)).fetchone())
            budget = json.loads(job['config']).get('max_requests')
            if budget is not None and job['run_id']:
                used = self.db.execute('SELECT COUNT(*) FROM request_attempts a JOIN batches b ON a.original_batch_id=b.id JOIN jobs j ON j.id=b.job_id WHERE j.run_id=?', (job['run_id'],)).fetchone()[0]
                if used >= budget: return None
            if job["max_requests"] is not None:
                used = self.db.execute("SELECT COUNT(*) FROM request_attempts a JOIN batches b ON b.id=a.original_batch_id WHERE b.job_id=?", (job["id"],)).fetchone()[0]
                if used >= job["max_requests"]:
                    return None
            if self.db.execute("SELECT 1 FROM request_attempts WHERE original_batch_id=? AND attempt_number=?", (batch_id, number)).fetchone():
                return None
            batch = self.db.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone()
            if number > 1:
                prior = self.attempts(batch_id)
                from .retry import allowed_retry
                if not 2 <= number <= 6 or job['state'] not in ('running', 'waiting_rate_limit', 'retry_scheduled') or len(prior) != number-1 or prior[-1]['state'] != 'finished' or not allowed_retry(job, prior[-1]['diagnostics'] or {}, number):
                    return None
                valid = []
                for r in json.loads(batch["payload"]):
                    current = self.line(r["id"])
                    if current["source_revision"] == r["source_revision"] and current["translation_revision"] == r["translation_revision"] and current["state"] in ('unknown', 'error', 'wrong_target_language'):
                        if current['attempt_kind']=='manual': continue
                        if current['state']=='wrong_target_language': r['retry_wrong_language']=True
                        valid.append(r)
                if not valid:
                    return None
                valid[0]["context"] = json.loads(batch["payload"])[0].get("context", [])
                self.db.execute("UPDATE batches SET state='inflight',payload=? WHERE id=?", (json.dumps(valid, ensure_ascii=False), batch_id))
                self.db.executemany("UPDATE lines SET state='processing' WHERE id=?", [(r["id"],) for r in valid])
            elif number != 1 or batch["state"] != "inflight":
                return None
            attempt_id = str(uuid.uuid4())
            self.db.execute("INSERT INTO request_attempts(id,original_batch_id,attempt_number,state,created_at) VALUES (?,?,?,'prepared',?)", (attempt_id, batch_id, number, datetime.now(timezone.utc).isoformat(timespec="milliseconds")))
            return attempt_id

    def complete_attempt(self, attempt_id, diagnostics):
        from datetime import datetime, timezone
        with self.transaction():
            self.db.execute("UPDATE request_attempts SET state='finished',completed_at=?,diagnostics=? WHERE id=?", (datetime.now(timezone.utc).isoformat(timespec="milliseconds"), json.dumps(diagnostics, ensure_ascii=False), attempt_id))

    def history(self):
        """Each import instance appears even before an API job is created."""
        result = []
        for doc in self.documents():
            jobs = [j for j in self.jobs() if j["document_id"] == doc["id"]]
            from .status import usable
            rows = self.lines(doc["id"])
            for latest in jobs or [None]:
                if latest is None and self.setting('queue_hidden_'+doc['id'])=='1':continue
                result.append({**doc, "entry_id": latest["id"] if latest else "import:"+doc["id"], "job_id": latest["id"] if latest else None, "model": latest["model"] if latest else "—", "state": latest["state"] if latest else "imported", "source_lang": latest["source_lang"] if latest else doc["source_lang"], "target_lang": latest["target_lang"] if latest else doc["target_lang"], "done": sum(usable(r) for r in rows), "total": sum(translatable(r["source"]) for r in rows), "created_at": latest["created_at"] if latest else doc["created_at"]})
        return result

    def clear_queue_history(self,expected_entries,safe=lambda:False):
        """Delete the confirmed queue graph; documents/manuscripts/credentials survive."""
        if not self.lock.acquire(blocking=False):raise ValueError('SQLite đang ghi; hãy thử lại sau.')
        try:
            if self.db.in_transaction or not safe():raise ValueError('Hãy dừng quá trình dịch và chờ các tác vụ hiện tại kết thúc trước khi xóa toàn bộ.')
            actual={item['entry_id'] for item in self.history()}
            if actual!=set(expected_entries):raise ValueError('Danh sách đã thay đổi; hãy xác nhận lại.')
            if not actual:return 0
            with self.transaction():
                if not safe():raise ValueError('Tác vụ đang chạy; không thể xóa.')
                if self.db.execute("SELECT 1 FROM jobs WHERE state IN ('running','pausing','stopping') LIMIT 1").fetchone() or self.db.execute("SELECT 1 FROM batches WHERE state='inflight' LIMIT 1").fetchone():raise ValueError('Request chưa kết thúc; không thể xóa.')
                if self.db.execute("SELECT 1 FROM request_attempts WHERE state!='finished' LIMIT 1").fetchone():raise ValueError('Attempt chưa kết thúc; không thể xóa.')
                jobs={item['job_id'] for item in self.history() if item['job_id']}
                docs={item['id'] for item in self.history()}
                runs={self.job(job_id)['run_id'] for job_id in jobs if self.job(job_id)['run_id']}
                for job_id in jobs:
                    self.db.execute('DELETE FROM api_text_versions WHERE attempt_id IN (SELECT a.id FROM request_attempts a JOIN batches b ON b.id=a.original_batch_id WHERE b.job_id=?)',(job_id,))
                    self.db.execute('DELETE FROM request_attempts WHERE original_batch_id IN (SELECT id FROM batches WHERE job_id=?)',(job_id,))
                    self.db.execute('DELETE FROM batches WHERE job_id=?',(job_id,))
                    self.db.execute('DELETE FROM jobs WHERE id=?',(job_id,))
                for run_id in runs:
                    self.db.execute('DELETE FROM translation_runs WHERE id=? AND NOT EXISTS (SELECT 1 FROM jobs WHERE run_id=?)',(run_id,run_id))
                for doc_id in docs:self.db.execute('INSERT OR REPLACE INTO settings(key,value) VALUES (?,?)',('queue_hidden_'+doc_id,'1'))
                if self.db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Foreign key integrity check failed')
            return len(actual)
        finally:self.lock.release()

    def delete_history(self, entry_ids):
        wanted = set(entry_ids)
        with self.transaction():
            documents, jobs = set(), set()
            for entry_id in wanted:
                if entry_id.startswith("import:"):
                    doc_id = entry_id[7:]
                    if self.db.execute("SELECT 1 FROM jobs WHERE document_id=?", (doc_id,)).fetchone():
                        raise ValueError("Lần nhập đã có lượt dịch; hãy làm mới và chọn đúng công việc.")
                    self.document(doc_id)
                    documents.add(doc_id)
                    continue
                job = self.job(entry_id)
                if not job:
                    raise ValueError("Mục lịch sử không còn tồn tại.")
                documents.add(job["document_id"])
                jobs.add(entry_id)
                active = job["state"] in ("running", "pausing", "stopping")
                inflight = self.db.execute("SELECT 1 FROM batches WHERE job_id=? AND state='inflight'", (entry_id,)).fetchone()
                if active or inflight:
                    raise ValueError("Công việc đang xử lý request; hãy dừng an toàn trước khi xóa.")
            for job_id in jobs:
                self.db.execute('DELETE FROM api_text_versions WHERE attempt_id IN (SELECT a.id FROM request_attempts a JOIN batches b ON b.id=a.original_batch_id WHERE b.job_id=?)', (job_id,))
                self.db.execute("DELETE FROM request_attempts WHERE original_batch_id IN (SELECT id FROM batches WHERE job_id=?)", (job_id,))
                self.db.execute("DELETE FROM batches WHERE job_id=?", (job_id,))
                self.db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            for doc_id in documents:
                if self.db.execute("SELECT 1 FROM jobs WHERE document_id=?", (doc_id,)).fetchone():
                    continue  # Shared snapshot/current manuscript still belongs to another job.
                for table in ("quality_warnings", "line_edits"):
                    self.db.execute(f"DELETE FROM {table} WHERE line_id IN (SELECT id FROM lines WHERE document_id=?)", (doc_id,))
                self.db.execute("DELETE FROM document_units WHERE document_id=?", (doc_id,))
                self.db.execute("DELETE FROM lines WHERE document_id=?", (doc_id,))
                self.db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
                self.db.execute("DELETE FROM settings WHERE key=?", ("export_revision_"+doc_id,))
                self.db.execute("DELETE FROM settings WHERE key=?", ("export_path_"+doc_id,))
            if self.db.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("Foreign key integrity check failed")
            self.db.execute('DELETE FROM translation_runs WHERE id NOT IN (SELECT run_id FROM jobs WHERE run_id IS NOT NULL)')
        self.log.emit("deleted", line_count=len(wanted), state="deleted")

    def gemini_keys(self, decrypt=False):
        from .security import unprotect_key
        with self.lock:
            rows = [dict(r) for r in self.db.execute('SELECT * FROM gemini_keys ORDER BY priority,rowid')]
        for r in rows:
            encrypted = r.pop('encrypted')
            r.pop('fingerprint')
            if decrypt: r['secret'] = unprotect_key(encrypted)
        return rows

    def add_gemini_keys(self, text, project=''):
        from .security import protect_key
        keys = list(dict.fromkeys(text.split()))
        added, duplicate = 0, 0
        with self.transaction():
            priority = self.db.execute('SELECT COALESCE(MAX(priority),0) FROM gemini_keys').fetchone()[0]
            for key in keys:
                fingerprint = hashlib.sha256(key.encode()).hexdigest()
                if self.db.execute('SELECT 1 FROM gemini_keys WHERE fingerprint=?', (fingerprint,)).fetchone():
                    duplicate += 1; continue
                priority += 1
                self.db.execute('INSERT INTO gemini_keys(id,fingerprint,encrypted,priority,project) VALUES (?,?,?,?,?)',
                                (uuid.uuid4().hex[:12], fingerprint, protect_key(key), priority, project.strip()))
                self.log.register_secret(key)
                added += 1
        return added, duplicate

    def gemini_key_status(self, key_id, status):
        if status not in ('unverified', 'available', 'authentication', 'permission', 'rate_limit', 'quota_exhausted'): raise ValueError('Invalid status')
        with self.transaction():
            self.db.execute('UPDATE gemini_keys SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?', (status, key_id))

    def change_gemini_key(self, key_id, *, delete=False, direction=0):
        with self.transaction():
            if self.db.execute("SELECT 1 FROM jobs WHERE provider='gemini' AND state IN ('running','pausing','stopping','user_paused','waiting_rate_limit','retry_scheduled')").fetchone():
                raise ValueError('Gemini run is active; stop safely before changing key priority/deleting')
            rows = self.gemini_keys()
            index = next((i for i, r in enumerate(rows) if r['id'] == key_id), None)
            if index is None: raise ValueError('Key no longer exists')
            if delete:
                self.db.execute('DELETE FROM gemini_keys WHERE id=?', (key_id,))
            else:
                other = max(0, min(len(rows)-1, index+direction))
                rows[index], rows[other] = rows[other], rows[index]
                self.db.executemany('UPDATE gemini_keys SET priority=? WHERE id=?', [(i, r['id']) for i, r in enumerate(rows)])

    def workspace_for_target(self, doc_id, target):
        doc = self.document(doc_id)
        with self.transaction():
            row = self.db.execute('SELECT id FROM documents WHERE source_instance=? AND target_lang=? ORDER BY rowid LIMIT 1', (doc['source_instance'], target)).fetchone()
            if row: return row['id']
            rows = self.lines(doc_id)
            data = ImportedText(tuple(TextLine(r['source'], r['ending']) for r in rows), doc['encoding'], doc['snapshot'])
            new_id, _ = self.import_document(doc['path'], data, doc['source_lang'], target, document_format=doc['format'],
                                             locators=[r['locator'] for r in self.units(doc_id)] if doc['format'] == 'docx' else None)
            self.db.execute('UPDATE documents SET source_instance=? WHERE id=?', (doc['source_instance'], new_id))
            return new_id

    def create_run(self, document_ids, targets, *, provider, model, source_lang, concurrency, timeout=90, config=None):
        from .status import usable
        from .languages import language,validate_pair
        source_lang=language(source_lang).name
        targets = list(dict.fromkeys(language(t).name for t in targets))
        if not targets: raise ValueError('Select targets different from source')
        for target in targets: validate_pair(source_lang,target)
        run_id = str(uuid.uuid4())
        jobs, instances = [], set()
        from .prompts import PROMPT_VERSION
        snapshot = {**(config or {}), 'provider': provider, 'model': model, 'source_lang': source_lang,
                    'targets': targets, 'target_locales':[language(t).locale for t in targets], 'source_locale':language(source_lang).locale,
                    'language_order': [language(t).locale for t in targets], 'current_locale':None, 'language_states':{},
                    'concurrency': concurrency, 'timeout': timeout, 'prompt_version': PROMPT_VERSION,
                    'auto_retries': int(self.setting('auto_retries', '5')), 'request_interval': float(self.setting('request_interval', '0')),
                    'retry_504': provider == 'kira' and self.setting('retry_504', '1') == '1'}
        with self.transaction():
            self.db.execute('INSERT INTO translation_runs(id,config) VALUES (?,?)', (run_id, json.dumps(snapshot, ensure_ascii=False)))
            for doc_id in document_ids:
                doc = self.document(doc_id)
                instance = doc['source_instance']
                if instance in instances: continue
                instances.add(instance)
                if doc['target_lang'] not in targets and not self.db.execute('SELECT 1 FROM jobs WHERE document_id=?', (doc_id,)).fetchone() and not any(r['translation'] for r in self.lines(doc_id)) and self.db.execute('SELECT COUNT(*) FROM documents WHERE source_instance=?', (instance,)).fetchone()[0] == 1:
                    self.db.execute('UPDATE documents SET target_lang=?,source_lang=? WHERE id=?', (targets[0], source_lang, doc_id))
                for target in targets:
                    workspace = self.workspace_for_target(doc_id, target)
                    eligible = any(r['state'] == 'pending' and translatable(r['source']) and not usable(r) for r in self.lines(workspace))
                    if eligible:
                        jobs.append(self.create_job(workspace, model, source_lang, target, concurrency, timeout=timeout, provider=provider, run_id=run_id, config=snapshot))
            if not jobs: raise ValueError('No lines need translation')
        return run_id, jobs

    def run(self, run_id):
        with self.lock:
            row = self.db.execute('SELECT * FROM translation_runs WHERE id=?', (run_id,)).fetchone()
            return {**dict(row), 'config': json.loads(row['config'])} if row else {}

    def run_jobs(self, run_id):
        return [j for j in self.jobs() if j['run_id'] == run_id]

    def run_state(self, run_id, state):
        with self.transaction():
            self.db.execute('UPDATE translation_runs SET state=? WHERE id=?', (state, run_id))

    def run_language_state(self, run_id, locale, state):
        if not run_id:return
        with self.transaction():
            snapshot=self.run(run_id)['config']
            snapshot['current_locale']=locale
            snapshot.setdefault('language_states',{})[locale]=state
            self.db.execute('UPDATE translation_runs SET config=? WHERE id=?',(json.dumps(snapshot,ensure_ascii=False),run_id))

    def export_snapshot(self, document_ids):
        """One short read transaction, detached snapshots rendered outside the lock."""
        with self.transaction():
            return [(self.document(d), self.units(d) if self.document(d)['format'] == 'docx' else self.lines(d)) for d in document_ids]

    def reserve_gemini_quota(self, scope, cost, rpm, tpm, rpd, now=None):
        """Durable conservative rolling 24h budget, including uncertain requests."""
        import time
        from .gemini import KeyUnavailable
        now = time.time() if now is None else now
        name = 'gemini_quota:'+scope
        with self.transaction():
            history = [r for r in json.loads(self.setting(name, '[]')) if r[0] > now-86400]
            if len(history) >= rpd: raise KeyUnavailable('verified_daily_budget_exhausted')
            minute = [r for r in history if r[0] > now-60]
            if len(minute) >= rpm or sum(r[1] for r in minute)+cost > tpm:
                return max(.01, minute[0][0]+60-now)
            history.append([now, cost])
            self.db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (name, json.dumps(history)))
            return 0

    def setting(self, key: str, default: str = "") -> str:
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self.transaction():
            self.db.execute("INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def save_key(self, encrypted: bytes):
        with self.transaction():
            self.db.execute("INSERT INTO secrets VALUES ('kira',?) ON CONFLICT(key) DO UPDATE SET encrypted=excluded.encrypted", (encrypted,))

    def load_key(self) -> bytes | None:
        with self.lock:
            row = self.db.execute("SELECT encrypted FROM secrets WHERE key='kira'").fetchone()
            return row["encrypted"] if row else None
