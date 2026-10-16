"""Kira dispatch phase for the existing Scheduler, with shared fair work claiming.

One event loop creates bounded HTTP tasks, not an OS thread per request. Durable
attempt UUID + inflight state + source/target revisions are the generation fence.
No automatic retries, lease expiry, key failover or positional result matching.
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
    queues={j:deque(b for b in store.batches(j) if b['state']=='pending' and not store.attempts(b['id'])) for j in jobs}
    order=deque(j for j,q in queues.items() if q)
    active_sources=[]; inflight={}; tasks=set()
    config=json.loads(next(iter(jobs.values()))['config'])
    interval=max(0,float(config.get('request_interval',0))); next_send=0.0
    s.active_files=0; s.key_metrics={}; s.dispatch_latencies=[]

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
        for _ in range(len(order)):
            j=order[0]; order.rotate(-1)
            if queues[j] and sources[j] in active_sources:return j,queues[j][0]
        return None

    async def execute(j, batch, claimed, attempt, key_id, adapter, started):
        job=jobs[j]; identity={'run_id':s.run_id or j,'job_id':j,'batch_id':batch['id'],
            'attempt_id':attempt,'attempt_number':1,'key_alias':key_id,
            'account_scope':pool.scopes[key_id],
            'provider':'kira','model':job['model'],'document_id':job['document_id'],
            'line_ids':[r['id'] for r in claimed]}
        s.attempt_metadata[attempt]=identity
        sent=False; http_open=False
        def observer(event, **data):
            nonlocal sent,http_open
            if event=='http_started' and not sent:
                sent=True;http_open=True;s.active_http+=1;s.request_count+=1
                s.sent_lines+=len(claimed);pool.sent(key_id,attempt)
                store.record_batch_diagnostics(batch['id'],{**identity,'dispatch_state':'sent'})
                with store.transaction():
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
                store.complete_attempt(attempt,d)
            pool.monitor.complete(record)
            s.accepted_lines+=len(accepted)
            if not result.error and not result.unknown:s.success_requests+=1
            if result.usage:s.usage_received_count+=1
            for k,v in (result.usage or {}).items():
                if isinstance(v,int):s.usage[k]=s.usage.get(k,0)+v
            if d.get('http_status')==504:s.http_504+=1
            store.log.emit('saved',**identity,accepted_ids=accepted,state='unknown' if result.unknown else 'error' if result.error else 'done')
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
                pool.pending_batches=s.ready_batches
                s.monitor_checkpoint()
                candidate=choose()
                if not candidate and not tasks:break
                if not candidate or s._paused.is_set() or time.monotonic()<next_send:
                    await asyncio.sleep(.01);continue
                available,_=pool.availability(cap)
                cooling=any(k['enabled'] and k['status']=='COOLDOWN' for k in pool.keys.values())
                if pool.network_paused or not available and not cooling:
                    if not tasks:
                        s.intervention_reason='network_unavailable' if pool.network_paused else 'kira_keys_unavailable'
                        s._paused.set();s._set_state('user_paused');s._notify([])
                    await asyncio.sleep(.01);continue
                j,batch=candidate
                dispatch_started=time.perf_counter()
                cost=len(json.dumps(messages(batch['payload'],jobs[j]['source_lang'],jobs[j]['target_lang'],pool.prompt_version),ensure_ascii=False).encode())+pool.max_tokens+128
                if cost>pool.tpm:
                    s.intervention_reason='kira_request_exceeds_tpm';s._paused.set();s._set_state('user_paused');s._notify([])
                    await asyncio.sleep(.01);continue
                lease=pool.reserve(cap,cost)
                if not lease:
                    await asyncio.sleep(.01);continue
                key_id,adapter=lease
                with s._dispatch_lock:
                    if s._stopped.is_set() or s._paused.is_set():
                        pool.release(key_id);continue
                    # Claim and reserve attempt together, with rollback on preparation failure.
                    with store.transaction():
                        claimed=store.claim_batch(batch['id'])
                        attempt=store.prepare_attempt(batch['id'],1) if claimed else None
                        if claimed and not attempt:store.release_unsent(batch['id'])
                        if attempt:
                            from .languages import language
                            record={'run_id':s.run_id or j,'job_id':j,'batch_id':batch['id'],
                                'attempt_id':attempt,'key_id':key_id,'account_scope':pool.scopes[key_id],
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
                queues[j].popleft()
                if not claimed or not attempt:
                    pool.release(key_id);continue
                pool.monitor.claim(record)
                started=time.monotonic()
                s.dispatch_latencies.append(time.perf_counter()-dispatch_started)
                if len(s.dispatch_latencies)>1000:del s.dispatch_latencies[:500]
                store.record_batch_diagnostics(batch['id'],{'run_id':s.run_id or j,'attempt_id':attempt,'key_alias':key_id,'dispatch_state':'prepared'})
                inflight[batch['id']]=j;s.active+=1
                task=asyncio.create_task(execute(j,batch,claimed,attempt,key_id,adapter,started))
                tasks.add(task);s._workers=list(tasks);next_send=time.monotonic()+interval
                # Yield so a completed/error response gates the next reservation immediately.
                await asyncio.sleep(0)
        finally:
            s._workers=list(tasks)
            if s._cancel_requested.is_set():
                for task in tasks:task.cancel()
            if tasks:await asyncio.gather(*tasks)
    if s._abandoned.is_set():return
    s.key_metrics=pool.snapshot(per_key());s.active_files=0
    unfinished=any(b['state'] not in ('done','superseded') or b.get('error') for j in jobs for b in store.batches(j))
    state='stopped' if s._stopped.is_set() else 'needs_intervention' if unfinished else 'finished'
    if unfinished and not s._stopped.is_set():s.intervention_reason='kira_batches_need_review'
    store.log.emit('kira_distribution',run_id=s.run_id,metrics=pool.redact(s.key_metrics))
    with s._dispatch_lock:s._set_state(state)
    s._event('scheduler_drained',state);s._notify([])
