"""Round-robin key slots and explicitly grouped account budgets; no key work queues."""
import time
import uuid
import json
import math
import threading
from collections import deque
from .providers import KiraProvider
from .kira_telemetry import KiraTelemetry, counters


def quota_deadline(value):
    try:
        value=float(value)
        return value if math.isfinite(value) and value>0 else 0
    except (TypeError,ValueError):return 0


class KiraPoolProvider(KiraProvider):
    multi_key = True

    def __init__(self, store, model, *, timeout=90, prompt_version=None, transport=None,
                 account_limit=None, rpm=None, tpm=None, max_tokens=4096):
        kwargs = {'timeout':timeout, 'transport':transport, 'max_tokens':max_tokens}
        from .prompts import KIRA_RECOVERY_PROMPT_VERSION
        kwargs['prompt_version'] = prompt_version or KIRA_RECOVERY_PROMPT_VERSION
        super().__init__('', model, **kwargs)
        self.store = store
        self.account_limit = max(1, int(account_limit or store.setting('kira_account_limit','30')))
        self.rpm = max(1, int(rpm or store.setting('kira_rpm','60')))
        self.tpm = max(1, int(tpm or store.setting('kira_tpm','1000000')))
        if model == 'qwen3.8-max-free': self.rpm = 1
        self.keys = {}; self.busy = {}; self.stats = {}; self._order = deque()
        self.monitor = KiraTelemetry(self.stats)
        self.scopes = {}; self.cooldowns = {}; self.budget_wait = {}; self.pending_batches = None
        self.requests = deque(); self.account_cooldown = float(store.setting('kira_cooldown_until','0')); self.network_paused = False
        self._reservation_lock=threading.RLock()
        self.health={}
        self.quota_scopes={}
        store.recover_kira_transient_statuses(legacy=True)
        self.refresh(force=True)

    def refresh(self, force=False):
        # Same lock order as shutdown fencing: SQLite, then telemetry.
        with self.store.lock,self.monitor.lock:
            return self._refresh_keys(force)

    def _refresh_keys(self, force=False):
        # DPAPI only for new/replaced blobs. Disabled/deleted keys immediately stop new leases.
        with self.store.lock:
            rows = self.store.db.execute('SELECT * FROM kira_keys ORDER BY rowid').fetchall()
            settings=dict(self.store.db.execute("SELECT key,value FROM settings WHERE key LIKE 'kira_%'"))
        existing = set()
        for record in rows:
            row = dict(record); key_id = row['id']; existing.add(key_id)
            if row['status'] in ('COOLDOWN','TEMPORARY_ERROR') and 0<row['cooldown_until']<=time.time():
                self.store.kira_key_status(key_id,'READY');row.update(status='READY',cooldown_until=0)
            blocked=settings.get('kira_model_status:'+key_id+':'+self.model,'')
            if blocked=='QUOTA_EXHAUSTED':
                reset=quota_deadline(settings.get('kira_quota_reset:'+key_id+':'+self.model,'0'))
                if reset>0 and reset<=time.time():
                    self.store.set_setting('kira_model_status:'+key_id+':'+self.model,'')
                    self.store.kira_key_status(key_id,'READY'); row.update(status='READY',cooldown_until=0);blocked=''
            if blocked:row['status']=blocked
            elif row['status'] in ('PERMISSION_DENIED','MODEL_UNAVAILABLE') or (row['status']=='QUOTA_EXHAUSTED' and settings.get('kira_key_status_model:'+key_id,'') not in ('',self.model)):
                row['status']='READY'
            old = self.keys.get(key_id)
            if old and old['encrypted'] == row['encrypted'] and (old['adapter'] is not None or not row['enabled'] or row['status']!='READY'):
                row['adapter'] = old['adapter']
            elif row['enabled']:
                from .security import unprotect_key
                try:
                    secret = unprotect_key(row['encrypted']); self.store.log.register_secret(secret)
                    row['adapter'] = KiraProvider(secret, self.model, timeout=self.timeout,
                        prompt_version=self.prompt_version, transport=self.transport, max_tokens=self.max_tokens)
                except (OSError, ValueError, RuntimeError):
                    row['adapter']=None;row['status']='CREDENTIAL_ERROR'
                    self.store.kira_key_status(key_id,'CREDENTIAL_ERROR',reason='credential_unavailable')
            else: row['adapter'] = None
            self.keys[key_id] = row
            if key_id not in self._order: self._order.append(key_id)
            self.busy.setdefault(key_id,0)
            self.stats.setdefault(key_id, counters())
            # Freeze account ownership for this provider's lifetime. Reassigning a
            # key while HTTP is in flight must never move its reservation/busy slots.
            if key_id not in self.scopes:
                declared = settings.get('kira_account:'+key_id,'shared')
                scope = declared if declared != 'shared' and settings.get('kira_account_confirmed:'+key_id) == declared else key_id
                self.scopes[key_id] = scope
                setting = 'kira_cooldown_until' if scope=='shared' else 'kira_cooldown:' + scope
                self.cooldowns.setdefault(scope, float(settings.get(setting,'0')))
                try:health=json.loads(settings.get('kira_health:'+scope,'{}'))
                except ValueError:health={}
                self.health.setdefault(scope,dict(limit=min(self.account_limit,max(1,int(health.get('limit',self.account_limit)))),
                    next_send=float(health.get('next_send',0)),spacing=float(health.get('spacing',0)),
                    rpm=min(self.rpm,max(1,int(health.get('rpm',self.rpm)))),
                    last_error=float(health.get('last_error',0)),successes=0,strikes=int(health.get('strikes',0))))
            if row['status'] in ('COOLDOWN','TEMPORARY_ERROR'):
                scope=self.scopes[key_id]
                self.cooldowns[scope]=max(self.cooldowns.get(scope,0),row['cooldown_until'])
            scope=self.scopes[key_id]
            group_reset=quota_deadline(settings.get('kira_verified_quota_reset:'+scope+':'+self.model,'0'))
            self.quota_scopes[scope]=settings.get('kira_verified_quota:'+scope+':'+self.model,'')=='1' and (group_reset<=0 or group_reset>time.time())
        for key_id in set(self.keys)-existing: del self.keys[key_id]
        self._order = deque(k for k in self._order if k in existing)

    def availability(self, per_key):
        now = time.time()
        available = [k for k,v in list(self.keys.items()) if v['enabled'] and v['adapter'] is not None and
                     not self.quota_scopes.get(self.scopes[k],False) and (v['status']=='READY' or v['status']=='COOLDOWN' and 0 < v['cooldown_until'] <= now)]
        groups = {}
        for key_id in available:
            scope = self.scopes[key_id]
            groups[scope] = groups.get(scope,0) + per_key
        return available, sum(min(n,self.account_limit,self.health[scope]['limit']) for scope,n in groups.items())

    def _reason(self, key_id, per_key, now, cost=None):
        row = self.keys.get(key_id)
        if row is None: return 'removed'
        if not row['enabled']: return 'disabled'
        if row['adapter'] is None: return 'credential_unavailable'
        if row['status'] not in ('READY','COOLDOWN','TEMPORARY_ERROR'): return row['status'].lower()
        scope = self.scopes[key_id]
        if self.quota_scopes.get(scope):return 'account_quota_exhausted'
        if self.network_paused: return 'network_paused'
        if now < self.cooldowns.get(scope,0): return 'account_cooldown'
        if row['status'] in ('COOLDOWN','TEMPORARY_ERROR') and not 0 < row['cooldown_until'] <= now: return 'key_cooldown'
        if self.busy[key_id] >= per_key: return 'key_slots_full'
        account_busy = sum(n for k,n in list(self.busy.items()) if self.scopes[k]==scope)
        health=self.health[scope]
        if account_busy >= min(self.account_limit,health['limit']): return 'account_slots_full'
        if now<health['next_send']:return 'adaptive_pacing'
        waiting = self.budget_wait.get(scope)
        if waiting and now < waiting[1]:
            # A smaller unsent batch can fit the remaining TPM even when the
            # previous candidate did not. RPM is independent of request size.
            if cost is None or waiting[0]=='account_rpm' or cost>=waiting[2]:
                return waiting[0]
        return None

    def _wait(self, key_id, reason):
        with self.monitor.lock:
            reasons = self.stats[key_id]['wait_reasons']
            reasons[reason] = reasons.get(reason,0) + 1

    def reserve(self, per_key, cost, preferred_key=None):
        with self._reservation_lock:return self._reserve(per_key,cost,preferred_key)

    def _reserve(self, per_key, cost, preferred_key):
        self.refresh()
        now = time.time()
        while self.requests and self.requests[0][0] <= now-60: self.requests.popleft()
        for _ in range(len(self._order)):
            key_id = self._order[0]; self._order.rotate(-1)
            if preferred_key is not None and key_id!=preferred_key:continue
            reason = self._reason(key_id, per_key, now, cost)
            if reason:
                self._wait(key_id,reason); continue
            scope = self.scopes[key_id]
            with self.store.transaction():
                self.store.db.execute('DELETE FROM kira_reservations WHERE created_at<=?',(now-60,))
                members=[k for k,v in self.scopes.items() if v==scope]
                placeholders=','.join('?' for _ in members)
                # Regrouping must not reset the last minute's budget. Legacy rows
                # without key ownership conservatively count against every group.
                used=self.store.db.execute(f'SELECT COUNT(*),COALESCE(SUM(tokens),0),MIN(created_at) FROM kira_reservations WHERE account_scope=? OR key_alias IN ({placeholders}) OR key_alias IS NULL',(scope,*members)).fetchone()
                reason = 'request_exceeds_tpm' if cost>self.tpm else 'account_rpm' if used[0]>=min(self.rpm,self.health[scope]['rpm']) else 'account_tpm' if used[1]+cost>self.tpm else None
                if reason:
                    self._wait(key_id,reason)
                    self.budget_wait[scope] = (reason, (used[2]+60) if used[2] else now+60, cost)
                    # Only this account is blocked; consider other READY accounts.
                    continue
                self.budget_wait.pop(scope,None)
                self.store.db.execute('INSERT INTO kira_reservations(id,created_at,tokens,account_scope,key_alias) VALUES (?,?,?,?,?)',(str(uuid.uuid4()),now,cost,scope,key_id))
            row = self.keys[key_id]
            if row['status']=='COOLDOWN':
                self.store.kira_key_status(key_id,'READY'); row['status']='READY'
            with self.monitor.lock:
                self.busy[key_id]+=1
                stats=self.stats[key_id]; stats['peak']=max(stats['peak'],self.busy[key_id])
            # Reservation consumed conservatively even if pause occurs just before send.
            self.requests.append((now,cost))
            health=self.health[scope]
            if health['spacing']:
                health['next_send']=now+health['spacing']
                self.store.set_setting('kira_health:'+scope,json.dumps(health))
            return key_id,row['adapter']
        return None

    def sent(self, key_id, attempt_id=None):
        if attempt_id:return self.monitor.sent(attempt_id)
        self.stats[key_id]['requests']+=1

    def begin_monitor(self, run_id, records):
        with self.monitor.lock:
            # A key deleted after contributing remains identifiable in this run.
            for record in records:
                key=record['key_id']
                self.busy.setdefault(key,0);self.scopes.setdefault(key,record['account_scope'])
                self.stats.setdefault(key,counters())
            self.monitor.begin(run_id,records)

    def monitor_snapshot(self, per_key):
        # RLock guards a detached snapshot; no SQLite or HTTP in this read path.
        with self.monitor.lock:return self.monitor.snapshot(self.snapshot(per_key))

    def completed(self, key_id, result, accepted, expected, seconds, diagnostics=None):
        """Called once after a sent request has been validated and committed."""
        stats = self.stats[key_id]
        stats['completed_requests'] += 1
        stats['latency_samples'] += 1
        stats['seconds'] += seconds
        failed = bool(result.error or result.unknown or (diagnostics or result.diagnostics or {}).get('wrong_language_ids'))
        stats['errors'] += failed
        stats['successful_requests'] += not failed
        stats['translated_lines'] += accepted
        stats['batches'] += not failed and accepted==expected

    def release(self, key_id, result=None, seconds=0):
        with self.monitor.lock:self.busy[key_id]-=1
        if result is None: return
        d=result.diagnostics or {}; kind=d.get('failure_kind'); state=None; until=0
        scope=self.scopes[key_id];health=self.health[scope];now=time.time()
        if kind=='authentication': state='INVALID'
        elif kind=='quota_exhausted':
            state='QUOTA_EXHAUSTED'
            # A structured quota error proves this key/model only. Account
            # propagation also requires explicit membership AND provider scope.
            if d.get('quota_scope')=='account' and self.store.kira_effective_scope(key_id)==scope:
                self.store.set_setting('kira_verified_quota:'+scope+':'+self.model,'1')
                self.quota_scopes[scope]=True
            reset=d.get('retry_after_seconds')
            if isinstance(reset,(int,float)) and math.isfinite(reset) and reset>=0:
                until=now+max(.02,reset)
            self.store.set_setting('kira_quota_reset:'+key_id+':'+self.model,str(until))
            if self.quota_scopes.get(scope):self.store.set_setting('kira_verified_quota_reset:'+scope+':'+self.model,str(until))
        elif kind=='rate_limit':
            delay=d.get('retry_after_seconds')
            delay=float(delay) if isinstance(delay,(int,float)) and math.isfinite(delay) and delay>=0 else min(30,2**min(health['strikes'],4))
            state='COOLDOWN'; until=now+max(.02,delay)
            # A wave of in-flight 429s reduces capacity once, without cancelling
            # accepted requests or applying one account's limits to another.
            if self.cooldowns.get(scope,0)<=now:
                health['limit']=max(1,health['limit']//2);health['strikes']+=1
            headers=d.get('rate_limit_headers') or {}
            cap=headers.get('x-ratelimit-limit-requests') or headers.get('ratelimit-limit')
            try:verified_rpm=max(1,min(self.rpm,int(cap))) if cap is not None else self.rpm
            except (ValueError,TypeError):verified_rpm=self.rpm
            health.update(rpm=min(health['rpm'],verified_rpm),spacing=max(health['spacing'],60/verified_rpm),next_send=max(health['next_send'],until),last_error=now,successes=0)
            self.cooldowns[scope] = max(self.cooldowns.get(scope,0),until)
            if scope=='shared': self.account_cooldown=self.cooldowns[scope]
        elif kind=='permission':state='PERMISSION_DENIED'
        elif kind=='model_or_request':state='MODEL_UNAVAILABLE'
        elif result.unknown or kind=='connect_not_sent':
            state='TEMPORARY_ERROR'
            # Responses from the same already-inflight cohort are one outage,
            # not 30 consecutive failed recovery attempts. Never shorten a
            # provider Retry-After already attached to this account.
            if self.cooldowns.get(scope,0)<=now:
                health['strikes']+=1
                until=now+min(30,2**min(health['strikes'],5))
            else:until=self.cooldowns[scope]
            health.update(last_error=now,successes=0)
            self.cooldowns[scope]=max(self.cooldowns.get(scope,0),until)
        elif kind=='http_error':state='UNKNOWN_ERROR'
        elif not result.error:
            health['successes']+=1
            if health['successes']>=5 and now-health['last_error']>=10:
                health['limit']=min(self.account_limit,health['limit']+1)
                health['strikes']=max(0,health['strikes']-1)
                health['spacing']*=.8;health['successes']=0
                if health['limit']==self.account_limit and health['spacing']<.02:health['spacing']=0
        if state:
            self.store.kira_key_status(key_id,state,until,reason=kind,model=self.model)
            self.store.log.emit('key_state',provider='kira',key_alias=key_id,state=state,reason=kind)
        if state in ('COOLDOWN','TEMPORARY_ERROR'):
            scope = self.scopes[key_id]
            setting = 'kira_cooldown_until' if scope=='shared' else 'kira_cooldown:' + scope
            self.store.set_setting(setting,str(self.cooldowns[scope]))
        self.store.set_setting('kira_health:'+scope,json.dumps(health))
        self.refresh()

    def snapshot(self, per_key):
        with self.monitor.lock:return self._snapshot(per_key)

    def _snapshot(self, per_key):
        available, capacity=self.availability(per_key)
        return {'keys':len(available),'enabled':sum(bool(k['enabled']) for k in list(self.keys.values())),
                'queued_batches':self.pending_batches or 0,
                'next_send_at':max((h['next_send'] for h in self.health.values()),default=0),
                'busy':sum(self.busy.values()),'maximum':capacity,
                'theoretical':len(available)*per_key,'account_limit':self.account_limit,
                'accounts':len({self.scopes[k] for k in available}),
                'per_key':{k:{**s,'wait_reasons':dict(s['wait_reasons']),
                    'busy':self.busy[k],'account_scope':self.scopes[k],
                    'name':self.keys[k]['name'] if k in self.keys else self.monitor.key_names.get(k,'Removed key'),
                    'status':self.keys[k]['status'] if k in self.keys else 'REMOVED',
                    'enabled':bool(self.keys[k]['enabled']) if k in self.keys else False,
                    'slot_limit':min(per_key,self.account_limit),
                    'wait_reason':self._reason(k,per_key,time.time()) or ('no_pending_work' if self.pending_batches==0 else 'ready'),
                    'error_rate':s['errors']/s['requests'] if s['requests'] else 0,
                    'mean_seconds':s['seconds']/s['latency_samples'] if s['latency_samples'] else 0}
                    for k,s in list(self.stats.items())}}

    def redact(self, value):
        if isinstance(value,str):
            with self.store.log.lock:secrets=tuple(self.store.log.secrets)
            for secret in secrets:value=value.replace(secret,'[redacted]')
            return value
        if isinstance(value,dict):return {self.redact(k):self.redact(v) for k,v in value.items()}
        if isinstance(value,list):return [self.redact(v) for v in value]
        return value
