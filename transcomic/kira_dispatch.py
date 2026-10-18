"""Kira dispatch phase for the existing Scheduler, with shared fair work claiming.

One event loop creates bounded HTTP tasks, not an OS thread per request. Durable
attempt UUID + inflight state + source/target revisions are the generation fence.
Recovery follows the frozen policy, including explicitly authorized uncertain
resends. No lease expiry, key/model failover or positional matching is used.
"""
import asyncio
import json
import time
from collections import deque
from pathlib import Path
from .providers import BatchResult
from .prompts import messages


async def run(scheduler):
    s=scheduler; pool=s.provider; store=s.store
    s._loop=asyncio.get_running_loop()
    jobs={j:store.job(j) for j in getattr(s,'_phase_job_ids',s.job_ids)}
    documents={j:store.document(job['document_id']) for j,job in jobs.items()}
    sources={j:doc['source_instance'] for j,doc in documents.items()}
    from .retry import allowed_retry
    from .kira_recovery import schedule_retry
    queues={j:deque() for j in jobs}
    targets={j:set() for j in jobs}
    reasons={}
    version=json.loads(next(iter(jobs.values()))['config']).get('kira_recovery_version',0)
    phase=getattr(s,'recovery_phase',0)
    for j,job in jobs.items():
        for b in store.batches(j):
            prior=store.attempts(b['id'])
            original=json.loads(b['original_payload']) if b.get('original_payload') else b['payload']
            targets[j].update(item['id'] for item in original)
            for attempt in prior:
                targets[j].update(((attempt.get('diagnostics') or {}).get('monitor') or {}).get('line_ids',()))
            if b['state']=='pending' and not prior:queues[j].append(b)
            elif b['state'] in ('error','partial','unknown') and prior and prior[-1]['state']=='finished':
                d=prior[-1]['diagnostics'] or {};key=d.get('retry_key_id') or d.get('key_alias')
                if version>=2 and (not phase or d.get('recovery_phase',-1)>=phase):continue
                if key and allowed_retry(job,d,len(prior)+1):
                    if not d.get('auto_retry_scheduled'):
                        d,reason=schedule_retry(store,b['id'],d,key,time.time())
                        if reason:reasons[j]=reason
                    if d:queues[j].append(dict(b,diagnostics=d))
    order=deque(j for j,q in queues.items() if q)
    active_sources=[]; inflight={}; tasks=set();unassigned_lease=None
    config=json.loads(next(iter(jobs.values()))['config'])
    interval=max(0,float(config.get('request_interval',0))); next_send=0.0
    s.active_files=0; s.key_metrics={}; s.dispatch_latencies=[]
    wait_used=sum(float(json.loads(job['config']).get('kira_wait_used',0)) for job in store.run_jobs(s.run_id)) if s.run_id else float(config.get('kira_wait_used',0))
    wait_initial=wait_used;wait_job=next(iter(jobs));wait_saved=wait_used
    waiting_since=None

    def save_wait():
        nonlocal wait_saved
        if wait_used==wait_saved:return
        with store.transaction():
            cfg=json.loads(store.job(wait_job)['config'])
            cfg['kira_wait_used']=float(config.get('kira_wait_used',0))+wait_used-wait_initial
            store.db.execute('UPDATE jobs SET config=? WHERE id=?',(json.dumps(cfg),wait_job))
        wait_saved=wait_used

    def waiting(state, deadline=0, *, bounded=True):
        nonlocal waiting_since,wait_used
        now=time.monotonic()
        if bounded and not tasks:
            if waiting_since is not None:wait_used+=now-waiting_since
            waiting_since=now
            if wait_used-wait_saved>=1:save_wait()
            if wait_used>=float(config.get('rate_wait_budget',300)):
                for j,q in queues.items():
                    if q:reasons[j]='recovery_wait_budget_exhausted'
                return False
        else:waiting_since=None
        s.waiting=s.ready_batches;s.cooldown_until=now+max(0,deadline-time.time())
        if store.job(s.job_id)['state']!=state:s._set_state(state);s._notify([])
        return True

    def per_key():
        return max(1,min(30,int(store.setting('concurrency',str(next(iter(jobs.values()))['concurrency'])))))

    def choose():
        # RR is deliberately strict: bounded completion preference of zero avoids starvation.
        remaining={sources[j] for j,q in queues.items() if q} | {sources[j] for j in inflight.values()}
        active_sources[:]=[d for d in active_sources if d in remaining]
        for j in order:
            if queues[j] and sources[j] not in active_sources and len(active_sources)<10:
                active_sources.append(sources[j])
        s.active_files=len(active_sources)
        blocked=None
        for _ in range(len(order)):
            j=order[0]; order.rotate(-1)
            if queues[j] and sources[j] in active_sources:
                for batch in queues[j]:
                    diagnostics=batch.get('diagnostics') or {}
                    if float(diagnostics.get('retry_not_before',0))>time.time():continue
                    preferred=diagnostics.get('retry_key_id')
                    if preferred in pool.keys and pool._reason(preferred,cap,time.time()):
                        # A pinned retry must not leave another eligible key's
                        # batch idle, including retries in the same document.
                        if blocked is None:blocked=(j,batch)
                        continue
                    return j,batch
        return blocked

    async def execute(j, batch, claimed, attempt, key_id, adapter, started, number):
        job=jobs[j]; identity={'run_id':s.run_id or j,'job_id':j,'batch_id':batch['id'],
            'attempt_id':attempt,'attempt_number':number,'key_alias':key_id,
            'account_scope':pool.scopes[key_id],
            'provider':'kira','model':job['model'],'document_id':job['document_id'],
            'line_ids':[r['id'] for r in claimed]}
        s.attempt_metadata[attempt]=identity
        sent=False; http_open=False
        def observer(event, **data):
            nonlocal sent,http_open
            if event=='http_started' and not sent:
                sent=True;http_open=True;s.active_http+=1;s.request_count+=1
                if number>1:s.retry_count+=1
                s.sent_lines+=len(claimed);pool.sent(key_id,attempt)
                with store.transaction():
                    store.record_batch_diagnostics(batch['id'],{**identity,'dispatch_state':'sent'})
                    store.db.execute('UPDATE request_attempts SET diagnostics=? WHERE id=?',
                        (json.dumps({'monitor':pool.monitor.attempts[attempt]}),attempt))
            elif event in ('body_received','failure') and http_open:
                s.active_http-=1;http_open=False
                pool.monitor.received(attempt)
            store.log.emit(event,**identity,**data)
        try:
            if s._stopped.is_set() or s._paused.is_set():
                result=BatchResult({},'Paused/stopped before send',diagnostics={'failure_kind':'not_sent'})
            else:
                adapter.should_stop=s._stopped.is_set
                result=await adapter.translate(claimed,job['source_lang'],job['target_lang'],client=client,observer=observer)
        except asyncio.CancelledError:
            result=BatchResult({},'Safe Exit: outcome unknown; no automatic retry',sent,
                diagnostics={'failure_kind':'shutdown_cancelled' if sent else 'not_sent'})
        except Exception:
            result=BatchResult({},'Internal transport error; outcome unknown',sent,
                diagnostics={'failure_kind':'network_error' if sent else 'not_sent'})
        finally:
            if http_open:s.active_http-=1
        if s._abandoned.is_set():return
        elapsed=time.monotonic()-started
        d={**(result.diagnostics or {}),**identity,'dispatch_state':'sent' if sent else 'not_sent',
           'elapsed_seconds':elapsed,'key_slot_limit':per_key()}
        prior=store.attempts(batch['id'])[:-1]
        d.update(recovery_phase=phase,unknown_outcome=bool(result.unknown),
                 uncertain_lineage=bool(result.unknown or any((a['diagnostics'] or {}).get('uncertain_lineage') for a in prior)))
        if result.usage:d['usage']=result.usage
        if number>1 and d['uncertain_lineage']:d['duplicate_token_risk']=True
        d=pool.redact(d)
        try:
            # Commit attribution together with the translation transaction. HTTP 200
            # or a successful inner SAVEPOINT alone cannot increment saved lines.
            with store.transaction():
                accepted=store.finish_batch(batch['id'],result.values,pool.redact(result.error),result.unknown,d,expected_attempt_id=attempt)
                missing=set(identity['line_ids'])-set(accepted)
                wrong=set(d.get('wrong_language_ids',()))
                rejected=set()
                if not result.unknown:
                    for item in claimed:
                        if item['id'] not in missing:continue
                        current=store.line(item['id'])
                        if current['source_revision']!=item['source_revision'] or current['translation_revision']!=item['translation_revision']:
                            rejected.add(item['id'])
                request_success=not result.error and not result.unknown and not wrong and not store.batch(batch['id']).get('error')
                state=('CANCELLED' if not sent else 'UNKNOWN' if result.unknown else
                    'FAILED' if not request_success else 'REJECTED' if missing else 'SUCCEEDED_AND_COMMITTED')
                record={**pool.monitor.attempts[attempt],'state':state,'sent':sent,
                    'received':sent,'accepted_ids':accepted,'request_success':bool(request_success and sent),
                    'failed_ids':sorted(missing-rejected) if state=='FAILED' else [],
                    'unknown_ids':sorted(missing) if state=='UNKNOWN' else [],
                    'rejected_ids':sorted(rejected),'seconds':elapsed}
                d['accepted_line_count']=len(accepted)
                d['accepted_batch']=state=='SUCCEEDED_AND_COMMITTED'
                d['monitor']=record
                if version>=2 and result.usage:
                    usage={k:v for k,v in result.usage.items() if isinstance(v,int) and v>=0}
                    reported=min(1000000000000,max(usage.get('total_tokens',0),usage.get('prompt_tokens',0)+usage.get('completion_tokens',0)))
                    store.db.execute('UPDATE request_attempts SET reserved_tokens=MAX(reserved_tokens,?) WHERE id=?',(reported,attempt))
                store.complete_attempt(attempt,d)
            pool.monitor.complete(record)
            s.accepted_lines+=len(accepted)
            if request_success and sent:s.success_requests+=1
            if result.usage:s.usage_received_count+=1
            for k,v in (result.usage or {}).items():
                if isinstance(v,int):s.usage[k]=s.usage.get(k,0)+v
            if d.get('http_status')==504:s.http_504+=1
            store.log.emit('saved',**identity,accepted_ids=accepted,state='unknown' if result.unknown else 'error' if result.error else 'done')
            split_remaining=(version>=2 and phase>0 and d.get('failure_kind')=='partial_response' and
                sum((a['diagnostics'] or {}).get('failure_kind') in ('invalid_line_response','invalid_schema','partial_response') for a in prior)>=2)
            immediate=version<2 or (phase==0 and number==1 and d.get('failure_kind')=='rate_limit') or split_remaining
            if (not result.unknown or version>=2) and not s._stopped.is_set() and immediate:
                planned,refused=schedule_retry(store,batch['id'],d,key_id,time.time())
                if planned:
                    queues[j].append(dict(store.batch(batch['id']),diagnostics=planned))
                    store.log.emit('retry_scheduled',**identity,reason=d.get('failure_kind'),state='retry_scheduled')
                elif refused:reasons[j]=refused
            s._notify(identity['line_ids'],attempt)
        except Exception:
            # No accepted-line event escapes a failed commit. The scheduler's
            # existing interruption path retains the attempt for explicit recovery.
            record={**pool.monitor.attempts[attempt],'state':'FAILED' if sent else 'CANCELLED',
                'accepted_ids':[],'failed_ids':identity['line_ids'] if sent else [],
                'unknown_ids':[],'rejected_ids':[],'request_success':False,'seconds':elapsed}
            pool.monitor.complete(record)
            raise
        finally:
            pool.release(key_id,result,elapsed)
            if number>1:s.retrying-=1
            s.active-=1;inflight.pop(batch['id'],None)

    async with pool.client(max(pool.account_limit, len(pool.keys)*pool.account_limit)) as client:
        try:
            while not s._stopped.is_set():
                done={t for t in tasks if t.done()}
                for task in done:task.result()
                tasks-=done
                s._workers=list(tasks)
                cap=per_key();pool.refresh()
                s.key_metrics=pool.snapshot(cap)
                s.effective_concurrency=s.key_metrics['maximum']
                s.configured_concurrency=s.key_metrics['theoretical']
                s.ready_batches=sum(len(q) for q in queues.values())
                s.waiting_retries=sum(bool((b.get('diagnostics') or {}).get('auto_retry_scheduled')) for q in queues.values() for b in q)
                pool.pending_batches=s.ready_batches
                s.monitor_checkpoint()
                if s._paused.is_set():
                    if not tasks and not any(queues.values()):break
                    waiting_since=None;s.waiting=0
                    await asyncio.sleep(.01);continue
                candidate=choose()
                if not candidate and not tasks and not any(queues.values()):break
                if not candidate and not tasks and any(queues.values()):
                    due=min(float((b.get('diagnostics') or {}).get('retry_not_before',0)) for q in queues.values() for b in q)
                    if not waiting('retry_scheduled',due):break
                if not candidate or s._paused.is_set() or time.monotonic()<next_send:
                    await asyncio.sleep(.01);continue
                available,_=pool.availability(cap)
                cooling=any(k['enabled'] and k['status'] in ('COOLDOWN','TEMPORARY_ERROR') and not pool.quota_scopes.get(pool.scopes[key],False) for key,k in pool.keys.items())
                if pool.network_paused or not available and not cooling:
                    if not tasks:
                        s.intervention_reason='network_unavailable' if pool.network_paused else 'kira_keys_unavailable'
                        break
                    await asyncio.sleep(.01);continue
                j,batch=candidate
                dispatch_started=time.perf_counter()
                prior=store.attempts(batch['id']);number=len(prior)+1
                preferred=(prior[-1]['diagnostics'] or {}).get('retry_key_id') if prior else None
                payload=batch['payload']
                if preferred:
                    row=pool.keys.get(preferred)
                    if not row or not row['enabled'] or row['status'] not in ('READY','COOLDOWN','TEMPORARY_ERROR') or pool.quota_scopes.get(pool.scopes[preferred],False):
                        queues[j].remove(batch);reasons[j]='retry_original_key_unavailable';continue
                    if (prior[-1]['diagnostics'] or {}).get('retry_model')!=jobs[j]['model']:
                        queues[j].remove(batch);reasons[j]='retry_model_changed';continue
                    original=json.loads(batch['original_payload']) if batch.get('original_payload') else payload
                    payload=[item for item in original if (r:=store.line(item['id'])) and r['state'] in ('error','unknown','wrong_target_language') and r['attempt_kind']!='manual' and r['source_revision']==item['source_revision'] and r['translation_revision']==item['translation_revision']]
                    if version>=2 and sum((a['diagnostics'] or {}).get('failure_kind') in ('invalid_line_response','invalid_schema','partial_response') for a in prior)>=2:payload=payload[:1]
                    if not payload:queues[j].remove(batch);continue
                cost=len(json.dumps(messages(payload,jobs[j]['source_lang'],jobs[j]['target_lang'],pool.prompt_version),ensure_ascii=False).encode())+pool.max_tokens+128
                if cost>pool.tpm:
                    queues[j].remove(batch);reasons[j]='kira_request_exceeds_tpm';continue
                from .kira_recovery import budget_reason
                refused=budget_reason(store,jobs[j],retry=number>1,cost=cost)
                if refused:
                    queues[j].remove(batch);reasons[j]=refused;continue
                lease=pool.reserve(cap,cost,preferred_key=preferred)
                if not lease:
                    keys=[preferred] if preferred else list(pool.keys)
                    why=[pool._reason(k,cap,time.time(),cost) for k in keys]
                    rate=any(r in ('account_rpm','account_tpm','account_cooldown','key_cooldown','adaptive_pacing') for r in why)
                    temporary=any(pool.keys[k]['status']=='TEMPORARY_ERROR' for k in keys)
                    deadlines=[pool.cooldowns.get(pool.scopes[k],0) for k in keys]
                    if not waiting('provider_recovering' if temporary else 'waiting_rate_limit' if rate else 'running',max(deadlines,default=0),bounded=any(r in ('account_cooldown','key_cooldown','adaptive_pacing') for r in why)):break
                    await asyncio.sleep(.01);continue
                waiting_since=None;s.waiting=0;s.cooldown_until=0
                if store.job(s.job_id)['state']!='running':s._set_state('running')
                key_id,adapter=lease
                unassigned_lease=key_id
                with s._dispatch_lock:
                    if s._stopped.is_set() or s._paused.is_set():
                        pool.release(key_id);unassigned_lease=None;continue
                    # Claim and reserve attempt together, with rollback on preparation failure.
                    with store.transaction():
                        if number==1:
                            claimed=store.claim_batch(batch['id'])
                            attempt=store.prepare_attempt(batch['id'],1,reserved_tokens=cost) if claimed else None
                            if claimed and not attempt:store.release_unsent(batch['id'])
                        else:
                            attempt=store.prepare_attempt(batch['id'],number,reserved_tokens=cost)
                            claimed=store.batch(batch['id'])['payload'] if attempt else []
                        if attempt:
                            from .languages import language
                            record={'run_id':s.run_id or j,'job_id':j,'batch_id':batch['id'],
                                'attempt_id':attempt,'key_id':key_id,'account_scope':pool.scopes[key_id],
                                'attempt_number':number,
                                'key_name':pool.keys[key_id]['name'],
                                'document_id':jobs[j]['document_id'],'target_language':language(jobs[j]['target_lang']).locale,
                                'source_instance':sources[j],'file_name':Path(documents[j]['path']).name,
                                'line_ids':[r['id'] for r in claimed],
                                'revisions':{r['id']:[r['source_revision'],r['translation_revision']] for r in claimed},
                                'mode':jobs[j]['mode'],'state':'CLAIMED_NOT_SENT','sent':False,'received':False,
                                'started_at':time.time()}
                            record=pool.redact(record)
                            store.db.execute('UPDATE request_attempts SET diagnostics=? WHERE id=?',
                                (json.dumps({'monitor':record}),attempt))
                            store.record_batch_diagnostics(batch['id'],{'run_id':s.run_id or j,'attempt_id':attempt,'key_alias':key_id,'dispatch_state':'prepared'})
                queues[j].remove(batch)
                if not claimed or not attempt:
                    if number==1 and claimed or number>1:reasons[j]='request_or_retry_budget_exhausted'
                    pool.release(key_id);unassigned_lease=None;continue
                pool.monitor.claim(record)
                started=time.monotonic()
                s.dispatch_latencies.append(time.perf_counter()-dispatch_started)
                if len(s.dispatch_latencies)>1000:del s.dispatch_latencies[:500]
                inflight[batch['id']]=j;s.active+=1
                if number>1:s.retrying+=1
                task=asyncio.create_task(execute(j,batch,claimed,attempt,key_id,adapter,started,number))
                unassigned_lease=None
                tasks.add(task);s._workers=list(tasks);next_send=time.monotonic()+interval
                # Yield so a completed/error response gates the next reservation immediately.
                await asyncio.sleep(0)
        finally:
            save_wait()
            if unassigned_lease is not None:pool.release(unassigned_lease)
            s._workers=list(tasks)
            if s._cancel_requested.is_set():
                for task in tasks:task.cancel()
            if tasks:await asyncio.gather(*tasks)
    if s._abandoned.is_set():return
    s.key_metrics=pool.snapshot(per_key());s.active_files=0
    from .status import usable
    unfinished=False
    for j in jobs:
        batches=store.batches(j)
        with store.transaction():
            for b in batches:
                original=json.loads(b['original_payload']) if b.get('original_payload') else b['payload']
                if b['state'] in ('done','partial','error','unknown') and all((row:=store.line(item['id']))['state']=='done' and usable(row) for item in original):
                    diagnostics=dict(b.get('diagnostics') or {})
                    if diagnostics.get('structure_errors'):
                        diagnostics['resolved_structure_errors']=diagnostics.pop('structure_errors')
                    store.db.execute("UPDATE batches SET state='done',error=NULL,diagnostics=? WHERE id=?",(json.dumps(diagnostics),b['id']))
        pending=any(b['state'] not in ('done','superseded') or b.get('error') for b in store.batches(j))
        pending=pending or any(not (row:=store.line(line_id)) or not usable(row) for line_id in targets[j])
        unfinished=unfinished or pending
        store.job_state(j,'stopped' if s._stopped.is_set() and pending else 'needs_intervention' if pending else 'finished')
    state='stopped' if s._stopped.is_set() else 'needs_intervention' if unfinished else 'finished'
    if unfinished and not s._stopped.is_set():s.intervention_reason=s.intervention_reason or next(iter(reasons.values()),'kira_batches_need_review')
    store.log.emit('kira_distribution',run_id=s.run_id,metrics=pool.redact(s.key_metrics))
    with s._dispatch_lock:
        pool.monitor.intervention_reason=s.intervention_reason
        shared='user_paused' if s._paused.is_set() else state
        if version>=2 and not s._stopped.is_set() and not s._paused.is_set():
            shared='provider_recovering' if unfinished else 'running'
        pool.monitor.set_state(shared)
        if s.run_id:store.run_state(s.run_id,shared)
    s._event('scheduler_drained',state);s._notify([])
