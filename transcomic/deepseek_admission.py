"""Automation-only DeepSeek admission with frozen rolling/legacy cohort policy."""
import asyncio
from collections import Counter
import json
import time

from .kira_admission import CohortAdmission
from .deepseek_rolling import RollingAdmission,admission_policy,validate_checkpoint
from .documents import translatable
from .status import usable
from .line_structure import validate_snapshot


class DeepSeekAdmission:
    def __init__(self,scheduler,jobs,enqueue):
        self.s=scheduler;self.store=scheduler.store;self.jobs=jobs;self.enqueue=enqueue
        self.cfg=json.loads(next(iter(jobs.values()))['config'])
        self.owner=self.cfg.get('automation_owner');self.key=str(getattr(scheduler,'admission_key','main'))
        saved=None
        if self.owner:
            with self.store.lock:
                row=self.store.db.execute('SELECT checkpoint FROM automation_worksets WHERE id=?',(self.owner,)).fetchone()
                if row:saved=json.loads(row[0]).get('deepseek_admissions',{}).get(self.key)
        self.policy=admission_policy(self.cfg.get('deepseek_admission_policy'));self.pending_admitted=set()
        if any(admission_policy(json.loads(job['config']).get('deepseek_admission_policy'))!=self.policy for job in jobs.values()):
            raise ValueError('DeepSeek admission job policies differ')
        validate_checkpoint(scheduler.source_order,saved,self.policy)
        gate=RollingAdmission if self.policy['mode']=='rolling' else CohortAdmission
        self.gate=gate(scheduler.source_order,saved,self.emit)
        scheduler.admission=self.gate
        self.sources={j:self.store.document(job['document_id'])['source_instance'] for j,job in jobs.items()}
        self.complete=set(scheduler.loader_complete);self.inflight=Counter();self.lock=asyncio.Lock();self.last=None

    def emit(self,event,source):
        # Attribute source events to the actual file job, not the scheduler anchor.
        jid=next((j for j,s in self.sources.items() if s==source),None)
        if event=='source_admitted' and jid is None:
            self.pending_admitted.add(source);return
        self.store.log.emit(event,provider='deepseek',source_instance=source,job_id=jid)

    def unfinished_loading(self):
        return self.lock.locked() or bool(set(self.gate.order)-set(self.sources.values())-self.complete)

    def persist(self):
        snapshot=self.gate.snapshot()
        snapshot['admission_policy']=dict(self.policy)
        if snapshot==self.last:return
        if self.owner:
            with self.store.transaction():
                row=self.store.db.execute('SELECT checkpoint FROM automation_worksets WHERE id=?',(self.owner,)).fetchone()
                cp=json.loads(row[0]);cp.setdefault('deepseek_admissions',{})[self.key]=snapshot
                self.store.db.execute('UPDATE automation_worksets SET checkpoint=? WHERE id=?',(json.dumps(cp),self.owner))
        for jid,source in self.sources.items():
            state='finished' if source in self.complete else 'parked' if source in self.gate.parked else 'running' if source in self.gate.active else 'ready'
            self.s.dispatch_job_states[jid]=state
            if self.store.job(jid)['state']!=state:self.store.job_state(jid,state)
        self.last=snapshot;self.s.active_files=len(self.gate.active)

    async def refresh(self,queues):
        # One disk loader; other workers and response commits keep running.
        if self.lock.locked() or self.s._stopped.is_set() or self.s._paused.is_set():return
        async with self.lock:
            queued=list(queues[0]._queue)+list(queues[1]._queue)
            busy={self.sources[j] for j,n in self.inflight.items() if n}
            for jid,job in list(self.jobs.items()):
                source=self.sources[jid]
                if source in self.complete or self.inflight[jid] or any(b['job_id']==jid for b in queued):continue
                rows=self.store.units(job['document_id'])
                if all(usable(r) and r['state']=='done' for r in rows if translatable(r['source'])):
                    report=validate_snapshot(self.store.document(job['document_id']),rows)
                    if not report.structural and not report.missing and not report.errors:self.complete.add(source)
            self.complete.update(self.s.loader_complete)
            future=set(self.gate.order)-set(self.sources.values())-self.complete
            ready={self.sources[b['job_id']] for b in queued if b.get('retry_not_before',0)<=time.monotonic()}
            active=self.gate.refresh(self.complete,ready|future,busy)
            self.persist()
            source=next((v for v in active if v in future),None)
            if source is None:return
            try:jid=await asyncio.to_thread(self.s.job_loader,source)
            except Exception:
                if self.s._stopped.is_set():return
                self.s.intervention_reason='admission_input_invalid';raise
            if jid and jid not in self.jobs:
                job=self.store.job(jid)
                first=next(iter(self.jobs.values()))
                if any(job[k]!=first[k] for k in ('provider','model','concurrency','prompt_version')):raise ValueError('Admission job snapshot mismatch')
                if admission_policy(json.loads(job['config']).get('deepseek_admission_policy'))!=self.policy:raise ValueError('Admission job policy mismatch')
                self.jobs[jid]=job;self.sources[jid]=source
                if source in self.pending_admitted:
                    self.pending_admitted.remove(source);self.emit('source_admitted',source)
                if jid not in self.s.job_ids:self.s.job_ids.append(jid)
                if jid not in self.s._phase_job_ids:self.s._phase_job_ids.append(jid)
                self.store.job_state(jid,'running');self.enqueue(jid)

    def take(self,queue,retry_queue,prefer_retry):
        queued=list(queue._queue)+list(retry_queue._queue);now=time.monotonic()
        ready={self.sources[b['job_id']] for b in queued if b.get('retry_not_before',0)<=now}
        remaining=Counter(self.sources[b['job_id']] for b in queued)
        source=self.gate.choose(ready,remaining)
        if source is None:return None,None
        for q in ((retry_queue,queue) if prefer_retry or queue.empty() else (queue,retry_queue)):
            for _ in range(q.qsize()):
                batch=q.get_nowait()
                if self.sources[batch['job_id']]==source and batch.get('retry_not_before',0)<=now:return q,batch
                q.put_nowait(batch);q.task_done()
        return None,None
