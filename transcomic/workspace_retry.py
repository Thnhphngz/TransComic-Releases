"""Workspace-only retry planning and provider-scoped reuse of the shared scheduler."""
import json
import threading
import time
from collections import defaultdict
from .translation import Scheduler


def fresh_retry_config(store, original):
    """A user-confirmed cycle keeps provider policy, never execution checkpoints."""
    if original['provider']=='kira':
        # Resolve current settings and live credentials; do not carry depleted
        # counters, derived token budgets, main_drained or recovery_phase.
        return {'kira_multi_key':True,'kira_recovery_version':3}
    old=json.loads(original.get('config') or '{}')
    config={k:old[k] for k in ('rpm','tpm','rpd','auto_retries','rate_wait_budget',
        'rate_cooldown_limit','rate_backoff_max','request_interval','targets','language_order') if k in old}
    keys=[k for k in store.gemini_keys() if k['status'] not in ('invalid','disabled','authentication','permission','quota_exhausted')]
    config.update(key_ids=[k['id'] for k in keys],key_projects={k['id']:k['project'] for k in keys})
    return config


def retry_plan(store, document_ids):
    origins = {}
    wanted = {r['id']: r for d in document_ids for r in store.lines(d) if r['state'] in ('error', 'unknown', 'wrong_target_language')}
    for job in store.jobs():
        if job['document_id'] not in document_ids: continue
        for batch in store.batches(job['id']):
            for item in batch['payload']:
                if item['id'] in wanted and item['id'] not in origins: origins[item['id']] = job
    groups = {}
    for line_id, row in wanted.items():
        if line_id not in origins: raise ValueError('Error line has no original provider/model; select it explicitly')
        job = origins[line_id]
        key = (job['document_id'], job['provider'], job['model'], job['source_lang'], job['target_lang'], job['concurrency'], job['timeout'], job['config'])
        groups.setdefault(key, {'original': job, 'line_ids': []})['line_ids'].append(line_id)
    return list(groups.values())


class WorkspaceRetryScheduler:
    """Independent providers; one shared fair Scheduler per frozen configuration.

    Different models within one provider wait their turn, preserving the provider's
    global concurrency bound. Requests within each group remain concurrent/fair.
    """
    def __init__(self, store, groups, adapters, on_change):
        self.store = store; self.groups = groups; self.adapters = adapters; self.on_change = on_change
        self.job_ids = [j for group in groups for j in group]
        self.job_id = self.job_ids[0]; self.run_id = None
        self._paused = threading.Event(); self._stopped = threading.Event()
        self._thread = None; self.children = []; self.started_at = None
        self._abandoned = threading.Event()

    @property
    def active(self): return sum(c.active for c in self.children)
    @property
    def current_locale(self):return ', '.join(dict.fromkeys(c.current_locale for c in self.children if c._thread and c._thread.is_alive() and getattr(c,'current_locale',None)))
    @property
    def waiting(self): return sum(c.waiting for c in self.children)
    @property
    def retry_count(self): return sum(c.retry_count for c in self.children)
    @property
    def retrying(self): return sum(c.retrying for c in self.children)
    @property
    def cooldown_until(self): return max((c.cooldown_until for c in self.children if c._thread and c._thread.is_alive()), default=0)
    @property
    def effective_concurrency(self): return sum(c.effective_concurrency or 0 for c in self.children if c._thread and c._thread.is_alive())
    @property
    def configured_concurrency(self):
        caps = {}
        for j in self.job_ids:
            job = self.store.job(j)
            caps[job['provider']] = max(caps.get(job['provider'], 0), job['concurrency'])
        return sum(caps.values())

    def start(self, job_id=None):
        self.started_at = time.monotonic()
        def run_provider(groups):
            from .languages import language
            order=[];parts=[]
            for group in groups:
                job=self.store.job(group[0]);config=json.loads(job['config'])
                saved=config.get('language_order') or [language(t).locale for t in config.get('targets',[])]
                for locale in saved:
                    if locale not in order:order.append(locale)
                split={}
                for jid in group:
                    locale=language(self.store.job(jid)['target_lang']).locale
                    if locale not in order:order.append(locale)
                    split.setdefault(locale,[]).append(jid)
                parts.extend(split.items())
            groups=[part for locale in order for key,part in parts if key==locale]
            previous = None
            for group in groups:
                while self._paused.is_set() and not self._stopped.is_set(): time.sleep(.02)
                if self._stopped.is_set(): break
                child = Scheduler(self.store, self.adapters[group[0]], self.on_change)
                if previous:
                    child.cooldown_until = previous.cooldown_until
                    child.effective_concurrency = previous.effective_concurrency
                    child.last_rate_limit_at = previous.last_rate_limit_at
                    child.reduced_at = previous.reduced_at
                    child.recovery_reason = previous.recovery_reason
                    child.recovery_successes = previous.recovery_successes
                self.children.append(child); child.start_many(group, self.store.job(group[0])['run_id'])
                if self._stopped.is_set(): child.stop()
                elif self._paused.is_set(): child.pause()
                while child._thread.is_alive():
                    if self._abandoned.is_set(): return
                    child.join(.05)
                if child.intervention_reason:
                    # This provider scope is blocked. Independent provider threads continue.
                    for later in groups[groups.index(group)+1:]:
                        for job_id in later: self.store.job_state(job_id, 'needs_intervention')
                    break
                previous = child
        def run():
            providers = defaultdict(list)
            for group in self.groups: providers[self.store.job(group[0])['provider']].append(group)
            threads = [threading.Thread(target=run_provider, args=(groups,), daemon=True) for groups in providers.values()]
            for t in threads: t.start()
            for t in threads: t.join()
            if self._abandoned.is_set(): return
            if self._stopped.is_set():
                for j in self.job_ids:
                    if self.store.job(j)['state'] == 'ready': self.store.job_state(j, 'stopped')
            self.on_change([])
        self._thread = threading.Thread(target=run, daemon=True); self._thread.start()

    def pause(self):
        self._paused.set()
        for c in self.children:
            if c._thread and c._thread.is_alive(): c.pause()
    def resume(self):
        self._paused.clear()
        for c in self.children:
            if c._thread and c._thread.is_alive(): c.resume()
    def stop(self):
        self._stopped.set(); self._paused.clear()
        for c in self.children:
            if c._thread and c._thread.is_alive(): c.stop()
    def join(self, timeout=None):
        if self._thread: self._thread.join(timeout)
    def cancel_inflight(self):
        self.stop()
        for child in self.children: child.cancel_inflight()
    def fence_shutdown(self):
        self.stop()
        self._abandoned.set()
        for child in self.children:
            if child._thread and child._thread.is_alive(): child.fence_shutdown()
    def acknowledge(self, ids, document_id):
        for c in self.children: c.acknowledge(ids, document_id)
