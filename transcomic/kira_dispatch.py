"""Kira dispatch phase for the existing Scheduler, with shared fair work claiming.

One event loop creates bounded HTTP tasks, not an OS thread per request. Durable
attempt UUID + inflight state + source/target revisions are the generation fence.
Recovery follows the frozen policy, including explicitly authorized uncertain
resends. No lease expiry, provider/model failover or positional matching is used.
"""
import asyncio
import json
import hashlib
import time
from collections import deque
from pathlib import Path
from .providers import BatchResult
from .prompts import messages


async def run(scheduler):
    s=scheduler; pool=s.provider; store=s.store
    s._loop=asyncio.get_running_loop()
    initial=list(getattr(s,'_phase_job_ids',s.job_ids));config=json.loads(store.job(initial[0])['config'])
    jobs={};documents={};sources={}
    from .retry import allowed_retry
    from .kira_recovery import schedule_retry,record_blocked_batch,blocked_state,reason_label
    queues={};targets={};reasons={};order=deque()
    version=config.get('kira_recovery_version',0)
    pool.completion_policy=config.get('translation_completion_policy')==1
    if config.get('kira_completion_policy') and not hasattr(s,'network_probe'):
        from .automation.adapters import network_ready
        s.network_probe=lambda:network_ready('kira')
    phase=getattr(s,'recovery_phase',0)
    def register(ids):
        for j in ids:
            if j in jobs:continue
            job=store.job(j);jobs[j]=job;documents[j]=store.document(job['document_id']);sources[j]=documents[j]['source_instance']
            queues[j]=deque();targets[j]=set()
            for b in store.batches(j):
                prior=store.attempts(b['id'])
                original=json.loads(b['original_payload']) if b.get('original_payload') else b['payload']
                targets[j].update(item['id'] for item in original)
                for attempt in prior:targets[j].update(((attempt.get('diagnostics') or {}).get('monitor') or {}).get('line_ids',()))
                if b['state']=='pending' and not prior:queues[j].append(b)
                elif b['state'] in ('error','partial','unknown') and prior and prior[-1]['state']=='finished':
                    d=prior[-1]['diagnostics'] or {};key=d.get('retry_key_id') or d.get('key_alias') or (d.get('monitor') or {}).get('key_id') or (b.get('diagnostics') or {}).get('key_alias')
                    if version in (2,3) and (not phase or d.get('recovery_phase',-1)>=phase):continue
                    if (key or version>=3) and allowed_retry(job,d,len(prior)+1):
                        if not d.get('auto_retry_scheduled'):
                            d,reason=schedule_retry(store,b['id'],d,key,time.time())
                            if reason:reasons[j]=reason
                        if d:queues[j].append(dict(b,diagnostics=d))
                    elif version>=4:
                        _,reason=schedule_retry(store,b['id'],d,key,time.time())
                        if reason:reasons[j]=reason
            if queues[j]:order.append(j)
            if j not in s.job_ids:s.job_ids.append(j)
            if j not in s._phase_job_ids:s._phase_job_ids.append(j)
    register(initial)
    active_sources=[]; inflight={}; tasks=set();unassigned_lease=None
    gate=None;certified=set(getattr(s,'loader_complete',()));last_admission=None;pending_load=[]
    async_loading=config.get('translation_completion_policy')==1 and callable(getattr(s,'job_loader',None))
    if config.get('kira_dispatch_policy')==1:
        from .kira_admission import CohortAdmission
        saved=config.get('kira_admission_state');owner=config.get('automation_owner');admission_key=str(config.get('kira_admission_key','main'))
        if owner:
            with store.lock:
                row=store.db.execute('SELECT checkpoint FROM automation_worksets WHERE id=?',(owner,)).fetchone()
                if row:saved=json.loads(row[0]).get('kira_admissions',{}).get(admission_key)
        gate=CohortAdmission(config.get('kira_dispatch_order') or list(sources.values()),saved,
            lambda event,source:store.log.emit(event,run_id=s.run_id,job_id=initial[0],source_instance=source))
        s.admission=gate
    pool.configure_gateway(next(iter(jobs.values()))['concurrency'] if version>=3 or config.get('automation_owner') else min(30,next(iter(jobs.values()))['concurrency'])*max(1,len(pool.keys)))
    interval=max(0,float(config.get('request_interval',0))); next_send=0.0
    s.active_files=0; s.key_metrics={}; s.dispatch_latencies=[];s.recovery_details={}
    s.job_block_reasons=reasons
    wait_used=sum(float(json.loads(job['config']).get('kira_wait_used',0)) for job in store.run_jobs(s.run_id)) if s.run_id else float(config.get('kira_wait_used',0))
    wait_initial=wait_used;wait_job=next(iter(jobs));wait_saved=wait_used
    waiting_since=None

    def settle(j):
        # Other documents may still run; do not leave this drained job looking
        # active when its remaining failed batches require intervention.
        if version<4 or queues[j] or j in inflight.values() or j not in reasons:return
        state=blocked_state(reasons[j]);s.dispatch_job_states[j]=state
        s.recovery_details[j]={'reason':reason_label(reasons[j]),'next_retry_at':None}
        if store.job(j)['state']!=state:store.job_state(j,state);s._notify([])

    def refuse(j,batch,reason):
        reasons[j]=reason
        if version>=4:record_blocked_batch(store,batch['id'],reason)
        settle(j)

    def certify(j):
        if not gate:return
        source=sources[j]
        if source in certified or queues[j] or j in inflight.values():return
        rows=store.units(jobs[j]['document_id'])
        from .documents import translatable
        from .status import usable
        if not all(usable(r) and r['state']=='done' for r in rows if translatable(r['source'])):return
        if any(b['state'] in ('pending','inflight') for b in store.batches(j)):return
        from .line_structure import validate_snapshot
        report=validate_snapshot(documents[j],rows)
        if not report.structural and not report.missing and not report.errors:certified.add(source)

    def admission():
        nonlocal last_admission
        if not gate:return None
        registered=set(sources.values());future=set(gate.order)-registered-certified
        ready={sources[j] for j,q in queues.items() if any(float((b.get('diagnostics') or {}).get('retry_not_before',0))<=time.time() and
            (not (b.get('diagnostics') or {}).get('auto_retry_scheduled') or s.retrying<config.get('kira_retry_concurrency',4)) for b in q)}
        available,_=pool.availability(cap)
        active=gate.refresh(certified,ready|future,{sources[j] for j in inflight.values()},can_expand=bool(available) and not pool.network_paused)
        loader=getattr(s,'job_loader',None)
        pending_load.clear()
        for source in active:
            if source not in future or loader is None:continue
            if async_loading:pending_load.append(source);continue
            try:jid=loader(source)
            except (ValueError,OSError):
                s.intervention_reason='admission_input_invalid';raise
            if jid:register([jid])
            elif source in getattr(s,'loader_complete',set()):certified.add(source)
        snapshot=gate.snapshot()
        if snapshot!=last_admission:
            with store.transaction():
                for jid,source in sources.items():
                    if source in certified:
                        s.dispatch_job_states.pop(jid,None);store.job_state(jid,'finished')
                    elif source not in gate.opened or source in gate.parked:
                        state='parked' if source in gate.parked else 'ready'
                        s.dispatch_job_states[jid]=state;store.job_state(jid,state)
                    elif s.dispatch_job_states.get(jid) in ('ready','parked'):
                        s.dispatch_job_states.pop(jid,None);store.job_state(jid,'running')
                cfg=json.loads(store.job(initial[0])['config']);cfg['kira_admission_state']=snapshot
                store.db.execute('UPDATE jobs SET config=? WHERE id=?',(json.dumps(cfg),initial[0]))
                if config.get('automation_owner'):
                    row=store.db.execute('SELECT checkpoint FROM automation_worksets WHERE id=?',(config['automation_owner'],)).fetchone()
                    cp=json.loads(row[0]);cp.setdefault('kira_admissions',{})[str(config.get('kira_admission_key','main'))]=snapshot
                    store.db.execute('UPDATE automation_worksets SET checkpoint=? WHERE id=?',(json.dumps(cp),config['automation_owner']))
            last_admission=snapshot
        s.active_files=len(gate.active)
        ready={sources[j] for j,q in queues.items() if any(float((b.get('diagnostics') or {}).get('retry_not_before',0))<=time.time() and
            (not (b.get('diagnostics') or {}).get('auto_retry_scheduled') or s.retrying<config.get('kira_retry_concurrency',4)) for b in q)}
        remaining={v:sum(len(q) for j,q in queues.items() if sources[j]==v)+sum(sources[j]==v for j in inflight.values()) for v in gate.active}
        return gate.choose(ready,remaining)

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
            if not config.get('kira_completion_policy') and wait_used>=float(config.get('rate_wait_budget',300)):
                for j,q in queues.items():
                    if q:reasons[j]='recovery_wait_budget_exhausted'
                return False
        else:waiting_since=None
        s.waiting=s.ready_batches;s.cooldown_until=now+max(0,deadline-time.time())
        if version>=4:
            from .kira_recovery import reason_label
            for j,q in queues.items():
                if not q:continue
                d=(min(q,key=lambda b:float((b.get('diagnostics') or {}).get('retry_not_before',0))).get('diagnostics') or {})
                status=d.get('http_status');due=max(deadline,float(d.get('retry_not_before',0)))
                s.recovery_details[j]={'reason':(f'HTTP {status} · ' if status else '')+reason_label(d.get('failure_kind') or state),
                    'next_retry_at':due if due>time.time() else None}
        if store.job(s.job_id)['state']!=state:s._set_state(state);s._notify([])
        return True

    def per_key():
        return max(1,min(30,int(store.setting('concurrency',str(next(iter(jobs.values()))['concurrency'])))))

    def choose():
        preferred_source=admission() if gate else None
        if gate and preferred_source is None:return None
        # RR is deliberately strict: bounded completion preference of zero avoids starvation.
        remaining={sources[j] for j,q in queues.items() if q} | {sources[j] for j in inflight.values()}
        active_sources[:]=list(gate.active) if gate else [d for d in active_sources if d in remaining]
        for j in order:
            if not gate and queues[j] and sources[j] not in active_sources and len(active_sources)<10:
                active_sources.append(sources[j])
        s.active_files=len(active_sources)
        blocked=None
        for _ in range(len(order)):
            j=order[0]; order.rotate(-1)
            if queues[j] and sources[j] in active_sources and (not gate or sources[j]==preferred_source):
                for batch in queues[j]:
                    diagnostics=batch.get('diagnostics') or {}
                    if float(diagnostics.get('retry_not_before',0))>time.time():continue
                    if version>=4 and diagnostics.get('auto_retry_scheduled') and s.retrying>=config.get('kira_retry_concurrency',4):continue
                    preferred=diagnostics.get('retry_key_id')
                    if version<3 and preferred in pool.keys and pool._reason(preferred,cap,time.time()):
                        # A pinned retry must not leave another eligible key's
                        # batch idle, including retries in the same document.
                        if blocked is None:blocked=(j,batch)
                        continue
                    return j,batch
        return blocked

    async def execute(j, batch, claimed, attempt, key_id, adapter, started, number):
        job=jobs[j]; identity={'run_id':s.run_id or j,'job_id':j,'batch_id':batch['id'],
            'payload_sha256':hashlib.sha256(json.dumps(claimed,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest(),
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
                if getattr(s,'on_dispatch',None):s.on_dispatch(j)
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
        if version>=4 and (result.diagnostics or {}).get('http_status')==503 and (result.diagnostics or {}).get('failure_kind')=='http_server_error':
            from dataclasses import replace
            result=replace(result,unknown=False)
        d={**(result.diagnostics or {}),**identity,'dispatch_state':'sent' if sent else 'not_sent',
           'elapsed_seconds':elapsed,'key_slot_limit':per_key()}
        prior=store.attempts(batch['id'])[:-1]
        d.update(recovery_phase=phase,unknown_outcome=bool(result.unknown),
                 uncertain_lineage=bool(result.unknown or any((a['diagnostics'] or {}).get('uncertain_lineage') for a in prior)))
        if version>=4 and d.get('failure_kind') in ('authentication','quota_exhausted') and not result.unknown:
            # An explicit key rejection may move to a different configured key.
            # A verified quota reset permits an in-budget translation as probe;
            # it is not evidence that the balance has already recovered.
            available,_=pool.availability(per_key())
            alternative=any(k!=key_id and not (d.get('quota_scope')=='account' and pool.scopes[k]==pool.scopes[key_id]) for k in available)
            reset=d.get('retry_after_seconds')
            reset_known=d.get('failure_kind')=='quota_exhausted' and isinstance(reset,(int,float)) and reset>=0
            d['recoverable_key_rejection']=bool(alternative or reset_known)
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
            immediate=version>=4 or version<2 or (phase==0 and number==1 and d.get('failure_kind')=='rate_limit') or split_remaining
            if (not result.unknown or version>=2) and not s._stopped.is_set() and immediate:
                planned,refused=schedule_retry(store,batch['id'],d,key_id,time.time())
                if planned:
                    queues[j].append(dict(store.batch(batch['id']),diagnostics=planned))
                    store.log.emit('retry_scheduled',**identity,reason=d.get('failure_kind'),state='retry_scheduled')
                elif refused:refuse(j,batch,refused)
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
            settle(j)
            certify(j)

    for j in reasons:settle(j)
    for j in jobs:certify(j)
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
                s.configured_concurrency=pool.gateway_maximum if version>=3 else s.key_metrics['theoretical']
                s.ready_batches=sum(len(q) for q in queues.values())
                s.waiting_retries=sum(bool((b.get('diagnostics') or {}).get('auto_retry_scheduled')) for q in queues.values() for b in q)
                pool.pending_batches=s.ready_batches
                s.monitor_checkpoint()
                if s._paused.is_set():
                    future=set(gate.order)-set(sources.values())-certified if gate else set()
                    if not tasks and not any(queues.values()) and not future:break
                    waiting_since=None;s.waiting=0
                    await asyncio.sleep(.1 if version>=4 else .01);continue
                candidate=choose()
                if pending_load and (not candidate or s.active>=max(1,s.effective_concurrency)):
                    available,_=pool.availability(cap)
                    cooling=any(k['enabled'] and k['status'] in ('COOLDOWN','TEMPORARY_ERROR') for k in pool.keys.values())
                    if not available and not cooling and not tasks:
                        s.intervention_reason='kira_keys_unavailable';break
                    source=pending_load[0]
                    try:jid=await asyncio.to_thread(s.job_loader,source)
                    except Exception:
                        if s._stopped.is_set():break
                        s.intervention_reason='admission_input_invalid';raise
                    if jid:register([jid])
                    elif source in getattr(s,'loader_complete',set()):certified.add(source)
                    continue
                if not candidate and not tasks and not any(queues.values()):break
                if not candidate and not tasks and any(queues.values()):
                    due=min(float((b.get('diagnostics') or {}).get('retry_not_before',0)) for q in queues.values() for b in q)
                    if not waiting('retry_scheduled',due):break
                if not candidate or s._paused.is_set() or time.monotonic()<next_send:
                    await asyncio.sleep(.25 if version>=4 and not tasks else .01);continue
                available,_=pool.availability(cap)
                cooling=any(k['enabled'] and k['status'] in ('COOLDOWN','TEMPORARY_ERROR') and not pool.quota_scopes.get(pool.scopes[key],False) for key,k in pool.keys.items())
                if pool.network_paused or not available and not cooling:
                    if not tasks:
                        if version>=4 and pool.network_paused:
                            if not waiting('network_waiting'):break
                            probe=getattr(s,'network_probe',None)
                            if config.get('kira_completion_policy') and probe and time.monotonic()-getattr(s,'_network_probed_at',0)>=2:
                                s._network_probed_at=time.monotonic()
                                if await asyncio.to_thread(probe):pool.network_paused=False
                            await asyncio.sleep(.25);continue
                        s.intervention_reason='network_unavailable' if pool.network_paused else 'kira_keys_unavailable'
                        break
                    await asyncio.sleep(.25 if version>=4 and not tasks else .01);continue
                j,batch=candidate
                dispatch_started=time.perf_counter()
                prior=store.attempts(batch['id']);number=len(prior)+1
                preferred=(prior[-1]['diagnostics'] or {}).get('retry_key_id') if prior else None
                payload=batch['payload']
                if prior:
                    if version>=4 and s.retrying>=config.get('kira_retry_concurrency',4):
                        await asyncio.sleep(.01);continue
                    row=pool.keys.get(preferred)
                    if version<3 and (not row or not row['enabled'] or row['status'] not in ('READY','COOLDOWN','TEMPORARY_ERROR') or pool.quota_scopes.get(pool.scopes[preferred],False)):
                        queues[j].remove(batch);refuse(j,batch,'retry_original_key_unavailable');continue
                    if (prior[-1]['diagnostics'] or {}).get('retry_model')!=jobs[j]['model']:
                        queues[j].remove(batch);refuse(j,batch,'retry_model_changed');continue
                    original=json.loads(batch['original_payload']) if batch.get('original_payload') else payload
                    payload=[item for item in original if (r:=store.line(item['id'])) and r['state'] in ('error','unknown','wrong_target_language') and r['attempt_kind']!='manual' and r['source_revision']==item['source_revision'] and r['translation_revision']==item['translation_revision']]
                    if version>=2 and sum((a['diagnostics'] or {}).get('failure_kind') in ('invalid_line_response','invalid_schema','partial_response') for a in prior)>=2:payload=payload[:1]
                    if not payload:queues[j].remove(batch);continue
                cost=len(json.dumps(messages(payload,jobs[j]['source_lang'],jobs[j]['target_lang'],pool.prompt_version),ensure_ascii=False).encode())+pool.max_tokens+128
                if cost>pool.tpm:
                    queues[j].remove(batch);refuse(j,batch,'kira_request_exceeds_tpm');continue
                from .kira_recovery import budget_reason
                refused=budget_reason(store,jobs[j],retry=number>1,cost=cost)
                if refused:
                    queues[j].remove(batch);refuse(j,batch,refused);continue
                if version>=3:preferred=None
                lease=pool.reserve(cap,cost,preferred_key=preferred)
                if not lease:
                    keys=[preferred] if preferred else list(pool.keys)
                    why=[pool._reason(k,cap,time.time(),cost) for k in keys]
                    rate=any(r in ('account_rpm','account_tpm','account_cooldown','key_cooldown','adaptive_pacing') for r in why)
                    temporary=any(pool.keys[k]['status']=='TEMPORARY_ERROR' for k in keys)
                    deadlines=[pool.cooldowns.get(pool.scopes[k],0) for k in keys]
                    if not waiting('provider_recovering' if temporary else 'waiting_rate_limit' if rate else 'running',max(deadlines,default=0),bounded=any(r in ('account_cooldown','key_cooldown','adaptive_pacing') for r in why)):break
                    await asyncio.sleep(.25 if version>=4 and not tasks else .01);continue
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
                                'payload_sha256':hashlib.sha256(json.dumps(claimed,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest(),
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
                    if number==1 and claimed or number>1:
                        reason=budget_reason(store,store.job(j),retry=number>1,cost=cost) or 'request_admission_refused'
                        refuse(j,batch,reason)
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
        store.job_state(j,'stopped' if s._stopped.is_set() and pending else s.dispatch_job_states.get(j,'needs_intervention') if pending else 'finished')
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
