"""Crash-safe asynchronous batch scheduler with explicit pause and stop."""
from __future__ import annotations

import asyncio
import threading
import time
import random
from pathlib import Path
from collections.abc import Callable
from contextlib import asynccontextmanager

from .providers import BatchResult, KiraProvider
from .storage import Store


class Scheduler:
    def __init__(self, store: Store, provider: KiraProvider, on_change: Callable[[list[str]], None] | None = None):
        self.store = store
        self.provider = provider
        self.on_change = on_change
        self._paused = threading.Event()
        self._stopped = threading.Event()
        provider.should_stop = self._stopped.is_set
        if hasattr(provider, 'wait_gate'):
            provider.should_stop = self._stopped.is_set
            provider.should_pause = self._paused.is_set
        self._thread: threading.Thread | None = None
        self.job_id: str | None = None
        self.job_ids = []
        self.run_id = None
        self.active = 0
        self.started_at: float | None = None
        self._active_lock = threading.Lock()
        self._dispatch_lock = threading.Lock()
        self.gui_pending = {}
        self.attempt_metadata = {}
        self.retry_count = 0
        self.retrying = 0
        self.waiting = 0
        self.cooldown_until = 0.0
        self.effective_concurrency = None
        self.rate_limits = 0
        self.cooldown_seconds = 0.0
        self.quota_paused = False
        self.success_requests = 0
        self.request_count = 0
        self.usage = {}
        self.cooldown_count = 0
        self.intervention_reason = None
        self.last_rate_limit_at = 0.0
        self.reduced_at = 0.0
        self.recovery_successes = 0
        self.recovery_reason = None
        self.waiting_retries = 0
        self.active_http = 0
        self.ready_batches = 0
        self.http_504 = 0
        self.gateway_streak = 0
        self.accepted_lines = 0
        self.sent_lines = 0
        self.usage_received_count = 0
        self.configured_concurrency = 0
        self._loop = None
        self._workers = []
        self._cancel_requested = threading.Event()
        self._abandoned = threading.Event()

    def fence_shutdown(self):
        """Last resort for a transport ignoring cancellation. Retire durable
        attempts under the writer lock before allowing Qt to close the store.
        A late response may never overwrite this fence or a committed result.
        """
        self.stop()
        with self.store.transaction():
            self._abandoned.set()
            for job_id in self.job_ids:
                for batch in self.store.batches(job_id, 'inflight'):
                    attempts=self.store.attempts(batch['id'])
                    if not attempts or attempts[-1]['state']=='finished': continue
                    attempt=attempts[-1]
                    diagnostics={'failure_kind':'shutdown_cancelled','state':'outcome_unknown','reason':'transport_ignored_cancellation'}
                    record=(attempt.get('diagnostics') or {}).get('monitor')
                    if record:
                        record={**record,'state':'UNKNOWN' if record.get('sent') else 'CANCELLED',
                            'accepted_ids':[],'failed_ids':[],'rejected_ids':[],
                            'unknown_ids':record['line_ids'] if record.get('sent') else [],'request_success':False}
                        diagnostics['monitor']=record
                        if record['attempt_id'] not in self.provider.monitor.attempts:
                            self.provider.monitor.claim(record)
                            if record.get('sent'):self.provider.monitor.sent(record['attempt_id'])
                        self.provider.monitor.complete(record)
                    self.store.finish_batch(batch['id'],{},'Safe-exit fence: outcome_unknown; server may have consumed tokens',True,diagnostics,expected_attempt_id=attempt['id'])
                    import json
                    self.store.db.execute("UPDATE request_attempts SET state='unknown',diagnostics=? WHERE id=?",(json.dumps(diagnostics),attempt['id']))
                self.store.job_state(job_id,'interrupted')
            if self.run_id:self.store.run_state(self.run_id,'interrupted')
            if getattr(self.provider,'multi_key',False):
                from .kira_monitor_store import save_summary
                self.provider.monitor.set_state('interrupted')
                import sqlite3
                try:save_summary(self.store,self.provider.redact(self.provider.monitor_snapshot(30)))
                except (sqlite3.Error,OSError,ValueError):self.provider.monitor.persistence_error=True

    def cancel_inflight(self):
        """Called at the safe-exit deadline, never blocks the Qt thread."""
        self.stop()
        self._cancel_requested.set()
        loop = self._loop
        if loop and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(lambda: [task.cancel() for task in self._workers if not task.done()])
            except RuntimeError:
                pass  # Phase has already closed; no request remains in that loop.

    def _event(self, event, reason=None, job_id=None, **data):
        job = self.store.job(job_id or self.job_id) if job_id or self.job_id else {}
        if job:
            data.setdefault('error_lines', sum(r['state'] in ('error', 'unknown', 'wrong_target_language') for r in self.store.lines(job['document_id'])))
            data.setdefault('queued_batches', len(self.store.batches(job['id'], 'pending')))
        self.store.log.emit(event, job_id=job.get('id'), run_id=self.run_id,
            provider=job.get('provider'), model=job.get('model'), reason=reason,
            active_batches=self.active, **data)

    def _notify(self, ids, attempt_id=None):
        if attempt_id:
            self.gui_pending[attempt_id] = (set(ids), time.monotonic())
            self.store.log.emit('gui_emitted', **{'job_id': self.job_id, **self.attempt_metadata.get(attempt_id, {}), 'attempt_id': attempt_id, 'line_ids': ids, 'gui_received': False})
        try:
            if self.on_change:
                self.on_change(ids)
        except Exception as exc:
            self.store.log.emit("gui_error", job_id=self.job_id, attempt_id=attempt_id, exception=type(exc).__name__)

    def acknowledge(self, ids, document_id):
        for attempt_id, (wanted, started) in list(self.gui_pending.items()):
            if wanted.intersection(ids):
                metadata = self.attempt_metadata.get(attempt_id, {})
                original_document = metadata.get('document_id') or self.store.job(self.job_id).get('document_id')
                self.store.log.emit('gui_received', **{'job_id': self.job_id, **metadata, 'attempt_id': attempt_id,
                    'document_id': original_document, 'display_document_id': document_id,
                    'reason': 'other_import_not_displayed' if document_id != original_document else None,
                    'gui_seconds': round(time.monotonic()-started, 6), 'line_ids': list(wanted), 'gui_received': True})
                self.gui_pending.pop(attempt_id, None)

    def start(self, job_id: str):
        self.start_many(self.job_ids if job_id in self.job_ids else [job_id], self.run_id)

    def start_many(self, job_ids, run_id=None):
        if self._thread and self._thread.is_alive():
            raise RuntimeError("Scheduler is already running")
        jobs = [self.store.job(j) for j in job_ids]
        if not jobs or any(not j for j in jobs): raise ValueError('Missing jobs')
        if len({(j['provider'], j['model'], j['concurrency'], j['prompt_version']) for j in jobs}) != 1:
            raise ValueError('A run must use one frozen provider/model/concurrency/prompt')
        self.job_ids, self.job_id, self.run_id = list(job_ids), job_ids[0], run_id
        self.configured_concurrency = jobs[0]['concurrency']
        self.started_at = time.monotonic()
        self._paused.clear()
        self._stopped.clear()
        self._set_state('running')
        self._thread = threading.Thread(target=self._run_thread, name="TransComicTranslation", daemon=True)
        self._thread.start()

    def _set_state(self, state):
        if getattr(self.provider,'multi_key',False) and self.provider.monitor.run_id:
            self.provider.monitor.intervention_reason=self.intervention_reason
            monitor_state=state
            if state=='finished':
                phase=set(getattr(self,'_phase_job_ids',self.job_ids))
                if self._paused.is_set():monitor_state='user_paused'
                elif any(self.store.job(j)['state']=='ready' for j in self.job_ids if j not in phase):monitor_state='running'
            self.provider.monitor.set_state(monitor_state)
        for job_id in getattr(self,'_phase_job_ids',self.job_ids) or ([self.job_id] if self.job_id else []): self.store.job_state(job_id, state)
        if self.run_id: self.store.run_state(self.run_id, state)
        if self.run_id and getattr(self,'current_locale',None) and state!='finished':
            self.store.run_language_state(self.run_id,self.current_locale,state)

    def pause(self):
        with self._dispatch_lock:
            self._paused.set()
        if self.job_id:
            self._set_state('user_paused')
        self._event('pause_requested_by_user', 'user')
        self._notify([])

    def resume(self):
        if getattr(self.provider,'multi_key',False):
            self.provider.network_paused=False
            self.intervention_reason=None
        if hasattr(self.provider, 'pool'):
            self.provider.pool.resume_requested = True
        with self._dispatch_lock:
            self._paused.clear()
            if self.job_id:
                phase=getattr(self,'_phase_job_ids',self.job_ids) or [self.job_id]
                # Resume may arrive after a phase drained while paused. Preserve
                # its completed DB state so the language barrier can advance.
                drained=all(self.store.job(j)['state']=='finished' for j in phase)
                self._set_state('finished' if drained else 'running')
        self._notify([])

    @staticmethod
    def has_work(store, job_id):
        from .retry import allowed_retry
        job = store.job(job_id)
        multi_key=job['provider']=='kira' and bool(store.kira_keys())
        for batch in store.batches(job_id):
            prior = store.attempts(batch['id'])
            if batch['state'] == 'pending' and not prior: return True
            if not multi_key and prior and prior[-1]['state'] == 'finished' and batch['state'] in ('error', 'partial', 'unknown') and allowed_retry(job, prior[-1]['diagnostics'] or {}, len(prior)+1):
                if any(store.line(r['id'])['state'] in ('error', 'unknown', 'wrong_target_language') and store.line(r['id'])['source_revision']==r['source_revision'] and store.line(r['id'])['translation_revision']==r['translation_revision'] for r in batch['payload']): return True
        return False

    def stop(self):
        # An Event is atomic; never wait for the dispatch lock's SQLite writer
        # on the GUI thread. The worker rechecks this after reserving an attempt.
        self._stopped.set()
        self._paused.clear()
        self._notify([])

    def join(self, timeout: float | None = None):
        if self._thread:
            self._thread.join(timeout)

    def _run_thread(self):
        try:
            import json
            from .languages import language
            if getattr(self.provider,'multi_key',False):
                from .kira_monitor_store import records_for_run
                self.provider.begin_monitor(self.run_id or self.job_id,
                    records_for_run(self.store,self.run_id or self.job_id))
                self._monitor_checkpoint_at=0
                self.monitor_checkpoint(force=True)
            groups={}
            for jid in self.job_ids:
                groups.setdefault(language(self.store.job(jid)['target_lang']).locale,[]).append(jid)
            frozen=self.store.run(self.run_id).get('config',{}) if self.run_id else {}
            saved_order=frozen.get('language_order') or [language(t).locale for t in frozen.get('targets',[])]
            order=list(dict.fromkeys(saved_order+list(groups)))
            for locale in order:
                if locale not in groups:continue
                while not self._stopped.is_set():
                    while self._paused.is_set() and not self._stopped.is_set():time.sleep(.02)
                    with self._dispatch_lock:
                        if self._paused.is_set():continue
                        if self._stopped.is_set():break
                        self._phase_job_ids=groups[locale]; self.job_id=groups[locale][0]
                        self.current_locale=locale
                        self.store.run_language_state(self.run_id,locale,'running')
                        self._set_state('running')
                        self._event('language_started',locale,target_lang=locale)
                        break
                if self._stopped.is_set():break
                asyncio.run(self._run())
                if self._abandoned.is_set(): return
                drained_states=[self.store.job(j)['state'] for j in groups[locale]]
                # A user pause must hold the language barrier, even when the last response finished.
                while self._paused.is_set() and not self._stopped.is_set():time.sleep(.02)
                if not self._stopped.is_set() and all(s=='finished' for s in drained_states):
                    for j in groups[locale]:self.store.job_state(j,'finished')
                states=[self.store.job(j)['state'] for j in groups[locale]]
                uncertain=any(a['state']!='finished' for j in groups[locale] for b in self.store.batches(j) for a in self.store.attempts(b['id']))
                unknown=any(r['state']=='unknown' and not r.get('error','').startswith('Kira gateway HTTP 504') for j in groups[locale] for r in self.store.lines(self.store.job(j)['document_id']))
                if self._stopped.is_set() or self.intervention_reason or uncertain or unknown or any(s!='finished' for s in states):
                    state='interrupted' if 'interrupted' in states else 'stopped' if self._stopped.is_set() else 'quota_exhausted' if self.quota_paused else 'needs_intervention'
                    for j in groups[locale]:self.store.job_state(j,state)
                    if state!='stopped':self.intervention_reason=self.intervention_reason or ('unknown_request' if uncertain or unknown else state)
                    self.store.run_language_state(self.run_id,locale,state)
                    if self.run_id:self.store.run_state(self.run_id,state)
                    self._event('language_blocked',state,target_lang=locale)
                    break
                from .status import usable
                missing=any(not usable(r) for j in groups[locale] for b in self.store.batches(j) for item in b['payload'] for r in [self.store.line(item['id'])])
                state='completed_with_errors' if missing else 'completed'
                self.store.run_language_state(self.run_id,locale,state)
                self._event('language_completed',state,target_lang=locale)
            if self._stopped.is_set():
                for jid in self.job_ids:
                    if self.store.job(jid)['state'] not in ('finished','interrupted'):self.store.job_state(jid,'stopped')
                if self.run_id:self.store.run_state(self.run_id,'interrupted' if any(self.store.job(j)['state']=='interrupted' for j in self.job_ids) else 'stopped')
            self._notify([])
        except Exception as exc:
            self.store.log.emit("scheduler_error", job_id=self.job_id, exception=type(exc).__name__, state="interrupted")
            if self.job_id:
                self._set_state('interrupted')
            self._notify([])
        finally:
            if getattr(self.provider,'multi_key',False) and not self._abandoned.is_set():
                state=(self.store.run(self.run_id) if self.run_id else self.store.job(self.job_id)).get('state','interrupted')
                if all(self.store.job(j)['state']=='finished' for j in self.job_ids):state='finished'
                elif self._stopped.is_set() and state!='interrupted':state='stopped'
                self.provider.monitor.set_state(state)
                self.monitor_checkpoint(force=True)

    def monitor_checkpoint(self, force=False):
        if self._abandoned.is_set():return
        now=time.monotonic()
        if not force and now-getattr(self,'_monitor_checkpoint_at',0)<1:return
        self._monitor_checkpoint_at=now
        from .kira_monitor_store import save_summary
        cap=max(1,min(30,int(self.store.setting('concurrency','30'))))
        import sqlite3
        try:
            save_summary(self.store,self.provider.redact(self.provider.monitor_snapshot(cap)))
            self.provider.monitor.persistence_error=False
        except (sqlite3.Error,OSError,ValueError):
            if not self.provider.monitor.persistence_error:
                self.store.log.emit('monitor_persistence_error',run_id=self.run_id,provider='kira')
            self.provider.monitor.persistence_error=True

    async def _run(self):
        if getattr(self.provider,'multi_key',False):
            from .kira_dispatch import run
            return await run(self)
        self._loop = asyncio.get_running_loop()
        assert self.job_id
        job = self.store.job(self.job_id)
        jobs = {j: self.store.job(j) for j in getattr(self,'_phase_job_ids',self.job_ids) or [self.job_id]}
        self.effective_concurrency = min(job['concurrency'], self.effective_concurrency or job['concurrency'])
        dispatch_gate = asyncio.Lock()
        next_send = 0.0
        import json
        interval = max(0.0, float(json.loads(job['config']).get('request_interval', 0)))
        config = json.loads(job['config'])
        backoff_base = max(.01, float(config.get('rate_backoff_base', 1)))
        backoff_max = max(backoff_base, float(config.get('rate_backoff_max', 30)))
        wait_budget = max(0, float(config.get('rate_wait_budget', 300)))
        cooldown_limit = max(1, int(config.get('rate_cooldown_limit', 10)))
        recovery_interval = max(.01, float(config.get('rate_recovery_interval', .05)))
        cooldown_announced = False
        recovery_needed = max(1, int(config.get('recovery_successes', 3)))
        recovery_step = max(1, int(config.get('recovery_step', 2)))
        recovery_quiet = max(0, float(config.get('recovery_quiet_seconds', 1)))
        queue: asyncio.Queue[dict] = asyncio.Queue()
        retry_queue: asyncio.Queue[dict] = asyncio.Queue()
        prefer_retry = True
        rejected = set()
        def ready_count():
            self.ready_batches = queue.qsize()+retry_queue.qsize()
            return self.ready_batches
        async def wait_dispatch():
            nonlocal next_send, cooldown_announced
            self.waiting += 1
            waited = time.monotonic()
            deadline_at_entry = self.cooldown_until
            cooldown_wait = semaphore_wait = 0.0
            try:
                async with dispatch_gate:
                    gate_acquired = time.monotonic()
                    gate_wait = gate_acquired-waited
                    cooldown_wait = max(0, min(gate_acquired, deadline_at_entry)-waited)
                    while not self._stopped.is_set():
                        if self.intervention_reason: return False
                        now = time.monotonic()
                        if not ready_count() and not self.active: return None
                        if cooldown_announced and now >= self.cooldown_until and not self._paused.is_set():
                            cooldown_announced = False
                            self._set_state('running')
                            self._event('rate_limit_cooldown_finished', 'deadline_reached')
                            self._event('automatic_resume', 'rate_limit_cooldown_finished')
                        if not self._paused.is_set() and now >= max(self.cooldown_until, next_send) and self.active < self.effective_concurrency:
                            next_send = now + max(interval, recovery_interval if self.last_rate_limit_at else 0)
                            return {'dispatch_wait_seconds': now-waited, 'cooldown_wait_seconds': cooldown_wait, 'semaphore_wait_seconds': semaphore_wait, 'gate_wait_seconds': gate_wait}
                        poll_started = now
                        waiting_cooldown = now < self.cooldown_until
                        waiting_semaphore = self.active >= self.effective_concurrency
                        await asyncio.sleep(0.01)
                        spent = time.monotonic()-poll_started
                        if waiting_cooldown: cooldown_wait += spent
                        elif waiting_semaphore: semaphore_wait += spent
                    return False
            finally: self.waiting -= 1
        from .retry import allowed_retry
        pending = []
        for j in jobs:
            eligible = []
            for batch in self.store.batches(j):
                prior = self.store.attempts(batch['id'])
                if batch['state'] == 'pending' and not prior:
                    batch['next_attempt'] = 1
                    eligible.append(batch)
                elif prior and prior[-1]['state'] == 'finished' and batch['state'] in ('error', 'partial', 'unknown') and allowed_retry(jobs[j], prior[-1]['diagnostics'] or {}, len(prior)+1):
                    batch['next_attempt'] = len(prior)+1
                    eligible.append(batch)
                    self._event('retry_scheduled', 'reconstructed_finished_attempt', job_id=j, batch_id=batch['id'], attempt_number=len(prior)+1)
            pending.append(eligible)
        # Round robin across file/language jobs. Larger files never monopolize the queue.
        for offset in range(max((len(p) for p in pending), default=0)):
            for group in pending:
                if offset < len(group):
                    batch = group[offset]
                    batch['queued_at'] = time.monotonic()
                    (retry_queue if batch['next_attempt'] > 1 else queue).put_nowait(batch)
        self.waiting_retries = retry_queue.qsize()

        @asynccontextmanager
        async def client_context():
            if isinstance(self.provider, KiraProvider):
                self.store.log.register_secret(self.provider.api_key)
                if hasattr(self.provider, 'pool'):
                    for key in self.provider.pool.keys: self.store.log.register_secret(key['secret'])
                async with self.provider.client(job["concurrency"]) as client:
                    yield client
            else:
                yield None

        async def worker(client):
            nonlocal cooldown_announced, prefer_retry
            while not self._stopped.is_set():
                if not ready_count():
                    if not self.active: break
                    await asyncio.sleep(.01)
                    continue
                while self._paused.is_set() and not self._stopped.is_set():
                    await asyncio.sleep(0.05)
                if self._stopped.is_set():
                    break
                dispatch_metrics = await wait_dispatch()
                if dispatch_metrics is None or dispatch_metrics is False: break
                source_queue = retry_queue if not retry_queue.empty() and (prefer_retry or queue.empty()) else queue
                prefer_retry = source_queue is queue
                try:
                    batch = source_queue.get_nowait()
                    self.waiting_retries = retry_queue.qsize()
                except asyncio.QueueEmpty:
                    break
                job = jobs[batch['job_id']]
                with self._dispatch_lock:
                    if self._paused.is_set() or self._stopped.is_set():
                        source_queue.put_nowait(batch)
                        source_queue.task_done()
                        continue
                    claimed = self.store.claim_batch(batch["id"]) if batch['next_attempt'] == 1 else batch['payload']
                if not claimed:
                    source_queue.task_done()
                    continue
                with self._active_lock:
                    self.active += 1
                    active_at_dispatch = self.active
                changed_ids = [item["id"] for item in claimed]
                started_batch = time.monotonic()
                base_diagnostics = {"batch_id": batch["id"], "model": job["model"],
                                    "configured_concurrency": job["concurrency"], "active_at_dispatch": active_at_dispatch,
                                    "configured_timeout_seconds": job["timeout"],
                                    "line_count": len(claimed), "source_chars": sum(len(r["source"]) for r in claimed),
                                    **dispatch_metrics, 'effective_concurrency': self.effective_concurrency,
                                    'queue_inserted_at': batch['queued_at'], 'ready_batch_count': ready_count(),
                                    'waiting_retry_count': retry_queue.qsize()}
                base_diagnostics['batch_created_at'] = (batch.get('diagnostics') or {}).get('batch_created_at','unknown')
                base_diagnostics['connection_pool_limit'] = job['concurrency'] if isinstance(self.provider,KiraProvider) and self.provider.transport is None else 'custom_transport'
                identity = {"provider": job["provider"], "model": job["model"], "document_id": job["document_id"],
                            'run_id': self.run_id, 'target_lang': job['target_lang'],
                            'file_name': Path(self.store.document(job['document_id'])['path']).name,
                            'source_instance': self.store.document(job['document_id'])['source_instance'],
                            "job_id": job["id"], "batch_id": batch["id"], "original_batch_id": batch["id"],
                            "configured_concurrency": job["concurrency"], "line_ids": changed_ids,
                            "ordinals": [self.store.line(line_id)["ordinal"]+1 for line_id in changed_ids]}
                self.store.log.emit("selected", **identity, queue_wait_seconds=round(time.monotonic()-batch["queued_at"], 6))
                self.store.record_batch_diagnostics(batch["id"], base_diagnostics)
                self._notify(changed_ids)
                notify_attempt_id = None
                try:
                    for number in (batch['next_attempt'],):
                        with self._dispatch_lock:
                            if self._stopped.is_set() or self._paused.is_set():
                                if number == 1:
                                    self.store.release_unsent(batch['id'])
                                if self._paused.is_set() and not self._stopped.is_set():
                                    batch['next_attempt'] = number
                                    source_queue.put_nowait(batch)
                                self.store.log.emit("retry_blocked", **identity, reason="stopped_or_paused", state="not_sent")
                                break
                            attempt_id = self.store.prepare_attempt(batch["id"], number)
                        if not attempt_id:
                            rejected.add((batch['id'], number))
                            self.store.log.emit("retry_blocked", **identity, reason="budget_policy_revision_or_attempt_limit", state="not_sent")
                            if number == 1:
                                self.store.finish_batch(batch["id"], {}, "Request budget exhausted or attempt already reserved; not sent", False)
                            break
                        if number > 1:
                            claimed = self.store.batch(batch['id'])['payload']
                            changed_ids = [item['id'] for item in claimed]
                            self.retry_count += 1
                            self.retrying += 1
                            self.store.log.emit("retry", **identity, attempt_id=attempt_id, attempt_number=number, retry_count=self.retry_count)
                        attempt_identity = {**identity, **base_diagnostics, "attempt_id": attempt_id, "attempt_number": number,
                                            'retry_reason': (self.store.attempts(batch['id'])[-2]['diagnostics'] or {}).get('failure_kind') if number>1 else None,
                                            'line_ids': changed_ids, 'line_count': len(claimed), 'source_chars': sum(len(r['source']) for r in claimed),
                                            'ordinals': [self.store.line(i)['ordinal']+1 for i in changed_ids]}
                        self.attempt_metadata[attempt_id] = attempt_identity
                        self.store.log.emit("persisted", **attempt_identity, state="prepared")
                        self._notify(changed_ids)
                        if self._stopped.is_set():
                            self.store.finish_batch(batch['id'], {}, 'Stopped before send; no HTTP call', diagnostics={'failure_kind': 'not_sent'}, expected_attempt_id=attempt_id)
                            self.store.complete_attempt(attempt_id, {'failure_kind': 'not_sent'})
                            observer_identity = {**attempt_identity, 'state': 'not_sent', 'reason': 'stopped_before_send'}
                            self.store.log.emit('retry_blocked', **observer_identity)
                            if number > 1:
                                self.retrying -= 1
                            break
                        attempt_started = time.monotonic()
                        http_open = False
                        def observer(event, **data):
                            nonlocal http_open
                            if event == 'http_started' and not http_open:
                                self.active_http += 1; http_open = True
                                self.sent_lines += len(claimed)
                                self.request_count += 1
                            elif event in ('body_received','failure') and http_open:
                                self.active_http -= 1; http_open = False
                            if event == 'saved': data['validator_seconds'] = diagnostics.get('validator_seconds')
                            self.store.log.emit(event, **attempt_identity, **data)
                        try:
                            if isinstance(self.provider, KiraProvider):
                                result = await self.provider.translate(claimed, job["source_lang"], job["target_lang"], client=client, observer=observer)
                            else:
                                observer("http_started", server_execution_known=False)
                                result = await self.provider.translate(claimed, job["source_lang"], job["target_lang"])
                        except asyncio.CancelledError:
                            result = BatchResult({}, 'Safe-exit deadline: outcome_unknown; server may have consumed tokens', True,
                                                 diagnostics={'failure_kind': 'shutdown_cancelled', 'state': 'outcome_unknown'})
                        except Exception as exc:
                            observer("failure", exception=type(exc).__name__, state="unknown")
                            result = BatchResult({}, f"Internal error ({type(exc).__name__}); request status uncertain", True,
                                                 diagnostics={"failure_kind": "internal_error"})
                        finally:
                            if http_open:
                                self.active_http -= 1; http_open = False
                        if self._abandoned.is_set(): return
                        # Fence dispatch as soon as the parsed response is known,
                        # before SQLite/log work. Publish the paused job only after
                        # its attempt diagnostics have been committed below.
                        if (result.diagnostics or {}).get('http_status') == 429 and (result.diagnostics or {}).get('failure_kind') == 'quota_exhausted':
                            self.quota_paused = True
                            self.intervention_reason = 'provider_quota_exhausted'
                        diagnostics = {**base_diagnostics, "queue_wait_seconds": round(started_batch-batch["queued_at"], 6),
                                       "elapsed_seconds": round(time.monotonic()-attempt_started, 6), **(result.diagnostics or {}),
                                       "active_at_completion": self.active, "attempt_id": attempt_id, "attempt_number": number,
                                       "original_batch_id": batch["id"]}
                        if self.quota_paused and diagnostics.get('http_status') == 429:
                            diagnostics['intervention_reason'] = self.intervention_reason
                        if not result.error and not result.unknown: self.success_requests += 1
                        if result.usage: self.usage_received_count += 1
                        for key, value in (result.usage or {}).items():
                            if isinstance(value, int): self.usage[key] = self.usage.get(key, 0)+value
                        save_started = time.monotonic()
                        try:
                            accepted = self.store.finish_batch(batch["id"], result.values, result.error, result.unknown, diagnostics, expected_attempt_id=attempt_id)
                            if self._abandoned.is_set(): return
                            diagnostics['accepted_line_count'] = len(accepted)
                            self.accepted_lines += len(accepted)
                            diagnostics['sqlite_commit_seconds'] = getattr(getattr(self.store,'transaction_timing',None),'commit_seconds','unknown')
                            diagnostics["database_seconds"] = round(time.monotonic()-save_started, 6)
                            self.store.complete_attempt(attempt_id, diagnostics)
                        except Exception as exc:
                            observer("database_error", exception=type(exc).__name__, state="save_failed")
                            self.store.job_state(job["id"], "interrupted")
                            raise
                        observer("saved", database_seconds=diagnostics["database_seconds"], accepted_ids=accepted,
                                 rejected_ids=list(set(result.values)-set(accepted)), reason="wrong_target_language" if diagnostics.get('wrong_language_ids') else "revision_changed" if set(result.values)-set(accepted) else None,
                                 state="unknown" if result.unknown else "wrong_target_language" if diagnostics.get('wrong_language_ids') else "error" if result.error else "done")
                        if diagnostics.get('http_status') == 429:
                            notify_attempt_id = attempt_id
                        else:
                            self._notify(changed_ids, attempt_id)
                        if number > 1:
                            self.retrying -= 1
                        if diagnostics.get('failure_kind') in ('authentication', 'permission', 'model_not_found'):
                            self.intervention_reason = diagnostics['failure_kind']
                            self._set_state('needs_intervention')
                            self._event('provider_quota_exhausted', self.intervention_reason)
                        if diagnostics.get('http_status') == 429:
                            self.rate_limits += 1
                            seconds = diagnostics.get('retry_after_seconds')
                            if diagnostics.get('failure_kind') == 'quota_exhausted':
                                self.quota_paused = True
                                self.intervention_reason = 'provider_quota_exhausted'
                                self._set_state('quota_exhausted')
                                self._event('provider_quota_exhausted', 'explicit_provider_quota', job_id=job['id'])
                            else:
                                if not cooldown_announced: self.cooldown_count += 1
                                if seconds is None:
                                    seconds = min(backoff_max, backoff_base * 2**min(self.cooldown_count-1, 10)) * random.uniform(1, 1.2)
                                now = time.monotonic()
                                until = max(self.cooldown_until, now+seconds)
                                additional_wait = max(0, until-max(self.cooldown_until, now))
                                if self.cooldown_count > cooldown_limit or self.cooldown_seconds+additional_wait > wait_budget:
                                    self.intervention_reason = 'rate_limit_wait_budget_exhausted'
                                    self._set_state('needs_intervention')
                                    self._event('provider_quota_exhausted', self.intervention_reason, job_id=job['id'], wait_budget=wait_budget, cooldown_limit=cooldown_limit)
                                    break
                                self.cooldown_seconds += additional_wait
                                self.cooldown_until = until
                                if self.effective_concurrency != 1: self.reduced_at = now
                                self.last_rate_limit_at = now
                                self.recovery_successes = 0
                                self.recovery_reason = 'http_429_shared_scope'
                                previous_concurrency = self.effective_concurrency
                                self.effective_concurrency = 1
                                self._event('concurrency_changed', self.recovery_reason, configured_concurrency=job['concurrency'], effective_concurrency=1, previous_concurrency=previous_concurrency, last_rate_limit_at=now, cooldown_scope=job['provider']+'/'+job['model'])
                                cooldown_announced = True
                                if not self._paused.is_set(): self._set_state('waiting_rate_limit')
                                self._event('rate_limit_cooldown_started', 'retry_after' if diagnostics.get('retry_after_seconds') is not None else 'bounded_backoff', job_id=job['id'], seconds=seconds, wait_budget=wait_budget, cooldown_limit=cooldown_limit, queued_batches=ready_count())
                                if hasattr(self.provider, 'pool') and self.provider.pool.paused_reason == 'rate_limit':
                                    self.provider.pool.resume_requested = True
                            self.store.log.emit('cooldown', **{**attempt_identity, 'effective_concurrency': self.effective_concurrency}, retry_after=diagnostics.get('retry_after'), retry_after_seconds=seconds,
                                rate_limit_headers=diagnostics.get('rate_limit_headers'), quota_type=diagnostics.get('quota_type'),
                                usage=result.usage, state='paused' if self._paused.is_set() else 'waiting')
                        if job['provider']=='kira' and diagnostics.get('failure_kind') in ('authentication','permission','model_or_request'):
                            self.intervention_reason=diagnostics['failure_kind']
                        if job['provider']=='kira' and diagnostics.get('http_status') == 504:
                            self.http_504 += 1
                            self.gateway_streak += 1
                            # Local pacing policy, not a claimed provider quota. Concurrent
                            # failures extend one shared deadline rather than add sleeps.
                            # One wave of concurrent failures is one observation window,
                            # not 30 sequential outages. Avoid inflating the delay 30x.
                            wave = (self.gateway_streak-1)//max(1,job['concurrency'])
                            delay = min(30.0, max(.01, float(config.get('gateway_backoff_base', .1))) * 2**min(wave, 9))
                            self.cooldown_until = max(self.cooldown_until, time.monotonic()+delay)
                            self._event('gateway_backoff', 'observed_http_504_shared_pacing', job_id=job['id'],
                                        batch_id=batch['id'], attempt_number=number, seconds=delay,
                                        http_seconds=diagnostics.get('http_seconds'), usage=result.usage,
                                        cooldown_scope=job['provider']+'/'+job['model'])
                        elif not result.error and not result.unknown:
                            self.gateway_streak = 0
                        if job['provider'] == 'gemini':
                            kind = (result.diagnostics or {}).get('failure_kind')
                            unavailable = getattr(getattr(self.provider, 'pool', None), 'paused_reason', None)
                            if kind in ('keys_or_quota_unavailable', 'authentication', 'permission', 'model_not_found') or (kind == 'quota_exhausted' and unavailable):
                                self.intervention_reason = kind or 'keys_or_quota_unavailable'
                                self._set_state('quota_exhausted')
                                self._event('provider_quota_exhausted', self.intervention_reason)
                        if not result.error and not result.unknown and self.last_rate_limit_at and self.effective_concurrency < job['concurrency']:
                            self.recovery_successes += 1
                            if self.recovery_successes >= recovery_needed and time.monotonic()-max(self.cooldown_until, self.last_rate_limit_at) >= recovery_quiet:
                                previous_concurrency = self.effective_concurrency
                                self.effective_concurrency = min(job['concurrency'], self.effective_concurrency+recovery_step)
                                self.recovery_successes = 0
                                self.recovery_reason = 'successful_probe_window'
                                self._event('concurrency_changed', self.recovery_reason, previous_concurrency=previous_concurrency, effective_concurrency=self.effective_concurrency, configured_concurrency=job['concurrency'], reduced_seconds=time.monotonic()-self.reduced_at, last_rate_limit_at=self.last_rate_limit_at)
                        from .retry import allowed_retry
                        if number == 6 or not allowed_retry(job, diagnostics, number+1):
                            if result.error or result.unknown or diagnostics.get('wrong_language_ids'):
                                self._event('retry_exhausted', 'attempt_budget_or_non_retryable', job_id=job['id'], batch_id=batch['id'], attempt_number=number)
                            break
                        self._event('retry_scheduled', 'eligible_finished_attempt', job_id=job['id'], batch_id=batch['id'], attempt_number=number+1)
                        batch['next_attempt'] = number+1
                        batch['queued_at'] = time.monotonic()
                        batch['payload'] = self.store.batch(batch['id'])['payload']
                        retry_queue.put_nowait(batch)
                        self.waiting_retries = retry_queue.qsize()
                except Exception as exc:
                    self.store.log.emit("scheduler_error", **identity, exception=type(exc).__name__, state="interrupted")
                    self._stopped.set()
                finally:
                    with self._active_lock:
                        self.active -= 1
                    source_queue.task_done()
                    self._notify(changed_ids, notify_attempt_id)

        async with client_context() as client:
            while True:
                self._workers = [asyncio.create_task(worker(client)) for _ in range(job["concurrency"])]
                if self._cancel_requested.is_set():
                    for task in self._workers: task.cancel()
                await asyncio.gather(*self._workers, return_exceptions=True)
                if self._stopped.is_set() or self.intervention_reason: break
                # Reconcile persisted batches before completion. Never regroup or reset attempts.
                added = 0
                for jid, frozen_job in jobs.items():
                    for batch in self.store.batches(jid):
                        prior = self.store.attempts(batch['id'])
                        number = len(prior)+1
                        if (batch['id'], number) in rejected: continue
                        if prior and prior[-1]['state']=='finished' and batch['state'] in ('error','partial','unknown') and allowed_retry(frozen_job, prior[-1]['diagnostics'] or {}, number):
                            if any(self.store.line(r['id'])['state'] in ('error','unknown','wrong_target_language') and self.store.line(r['id'])['source_revision']==r['source_revision'] and self.store.line(r['id'])['translation_revision']==r['translation_revision'] for r in batch['payload']):
                                batch.update(next_attempt=number, queued_at=time.monotonic())
                                retry_queue.put_nowait(batch); added += 1
                self._event('reconciled', 'eligible_remaining' if added else 'no_eligible_remaining', ready_batch_count=added)
                if not added: break
        if self._abandoned.is_set(): return
        state = "interrupted" if any(self.store.job(j)['state'] == 'interrupted' for j in jobs) else "stopped" if self._stopped.is_set() else 'quota_exhausted' if self.quota_paused else 'needs_intervention' if self.intervention_reason else "finished"
        self._set_state(state)
        self._event('scheduler_drained', state, queued_batches=ready_count())
        from .status import usable
        missing = sum(not usable(r) for j in jobs.values() for b in self.store.batches(j['id']) for item in b['payload'] for r in [self.store.line(item['id'])])
        if state == 'finished':
            self._event('job_completed', 'completed_with_errors' if missing else 'completed', missing_lines=missing, state=state)
        self.store.log.emit("finished", provider=job["provider"], model=job["model"], document_id=job["document_id"], job_id=job["id"], state=state,
            retry_count=self.retry_count, request_count=self.request_count, success_requests=self.success_requests,
            rate_limit_count=self.rate_limits, cooldown_seconds=round(self.cooldown_seconds, 6), usage=self.usage or None,
            elapsed_seconds=round(time.monotonic()-(self.started_at or time.monotonic()), 6))
        for attempt_id in list(self.gui_pending):
            self.store.log.emit('gui_missing', **{'job_id': self.job_id, **self.attempt_metadata.get(attempt_id, {}), 'attempt_id': attempt_id, 'gui_received': False, 'state': 'awaiting_ack'})
        self._notify([])
