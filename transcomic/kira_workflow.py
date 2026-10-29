"""Main translation then bounded, durable review passes from the frozen policy."""
import asyncio
from datetime import datetime,timezone
import json
import time

from .languages import language
from .retry import allowed_retry
from .status import usable
from .line_structure import validate_snapshot


def _remaining(store,jobs):
    for jid in jobs:
        job=store.job(jid)
        from .kira_recovery import budget_reason
        if budget_reason(store,job,retry=True):continue
        for batch in store.batches(jid):
            prior=store.attempts(batch['id'])
            if not prior or prior[-1]['state']!='finished':continue
            if batch['state'] not in ('partial','error','unknown'):continue
            if not allowed_retry(job,prior[-1]['diagnostics'] or {},len(prior)+1):continue
            payload=json.loads(batch['original_payload']) if batch.get('original_payload') else batch['payload']
            if any((r:=store.line(p['id']))['state'] in ('error','unknown','wrong_target_language') and r['attempt_kind']!='manual'
                   and r['source_revision']==p['source_revision'] and r['translation_revision']==p['translation_revision'] for p in payload):
                yield jid,batch


def _save(s,**values):
    store=s.store
    with store.transaction():
        if s.run_id:
            config=store.run(s.run_id)['config'];config.update(values)
            store.db.execute('UPDATE translation_runs SET config=? WHERE id=?',(json.dumps(config),s.run_id))
        for jid in s.job_ids:
            config=json.loads(store.job(jid)['config']);config.update(values)
            store.db.execute('UPDATE jobs SET config=? WHERE id=?',(json.dumps(config),jid))


def run(s):
    store=s.store
    # This function runs only after explicit Start/Resume, never during Store open.
    # A crash leaves no live local worker; close its durable attempt as UNKNOWN
    # before granting a new attempt, retaining its token reservation and identity.
    for jid in s.job_ids:
        for batch in store.batches(jid):
            for attempt in store.attempts(batch['id']):
                if attempt['state']!='unknown':continue
                d=attempt['diagnostics'] or {};record=d.get('monitor') or {}
                d.update(failure_kind='restart_unknown',unknown_outcome=True,uncertain_lineage=True)
                if record:
                    record.update(state='UNKNOWN',accepted_ids=[],unknown_ids=record.get('line_ids',[]),request_success=False)
                    d['monitor']=record
                with store.transaction():
                    store.db.execute("UPDATE request_attempts SET state='finished',completed_at=?,diagnostics=? WHERE id=?",(datetime.now(timezone.utc).isoformat(),json.dumps(d),attempt['id']))
    frozen=store.run(s.run_id)['config'] if s.run_id else json.loads(store.job(s.job_ids[0])['config'])
    groups={}
    for jid in s.job_ids:groups.setdefault(language(store.job(jid)['target_lang']).locale,[]).append(jid)
    order=list(dict.fromkeys((frozen.get('language_order') or [])+list(groups)))
    start_phase=int(frozen.get('kira_recovery_phase',0)) if frozen.get('kira_main_drained') else 0
    for phase in range(start_phase,1 if frozen.get('kira_recovery_version',0)>=4 else 5 if frozen.get('kira_recovery_version',0)>=3 else 3):
        if phase and not list(_remaining(store,s.job_ids)):break
        if s._stopped.is_set():break
        s.recovery_phase=phase;s.provider.monitor.recovery_phase=phase
        _save(s,kira_recovery_phase=phase)
        s._event('recovery_phase','main' if not phase else f'review_{phase}',phase_index=phase)
        for locale in order:
            if locale not in groups:continue
            while s._paused.is_set() and not s._stopped.is_set():time.sleep(.02)
            if s._stopped.is_set():break
            s._phase_job_ids=groups[locale];s.job_id=groups[locale][0];s.current_locale=locale
            s.intervention_reason=None
            s._set_state('running');store.run_language_state(s.run_id,locale,'running')
            asyncio.run(s._run())
            if s._abandoned.is_set():return
        if s._stopped.is_set():break
        if phase==0:_save(s,kira_main_drained=True)
    while s._paused.is_set() and not s._stopped.is_set():time.sleep(.02)
    if s._abandoned.is_set():return
    states=[]
    for jid in s.job_ids:
        job=store.job(jid);doc,rows=store.export_snapshot([job['document_id']])[0]
        report=validate_snapshot(doc,rows)
        pending=any(b['state'] in ('pending','inflight') for b in store.batches(jid))
        unsettled=any(a['state']!='finished' for b in store.batches(jid) for a in store.attempts(b['id']))
        complete=not report.structural and not report.missing and not report.errors and not pending and not unsettled
        state='finished' if complete else 'stopped' if s._stopped.is_set() else 'completed_with_errors'
        if not complete and not s._stopped.is_set():
            if frozen.get('kira_recovery_version',0)>=4:
                reason=getattr(s,'job_block_reasons',{}).get(jid) or s.intervention_reason
                state=('needs_reconciliation' if any((a['diagnostics'] or {}).get('unknown_outcome') or (a['diagnostics'] or {}).get('failure_kind')=='restart_unknown' for b in store.batches(jid) if b['state']!='done' for a in store.attempts(b['id'])) else
                       'blocked_budget' if reason and any(x in reason for x in ('budget','exhausted','cost_unverified')) else
                       'blocked_auth' if any(k['status']=='INVALID' for k in s.provider.keys.values()) else
                       'blocked_quota' if any(k['status']=='QUOTA_EXHAUSTED' for k in s.provider.keys.values()) else 'blocked')
                store.job_state(jid,state);states.append(state);continue
            kinds={(b.get('diagnostics') or {}).get('failure_kind') for b in store.batches(jid) if b['state']!='done'}
            if kinds & {'authentication','permission','quota_exhausted','model_or_request'} or pending:state='blocked'
        store.job_state(jid,state);states.append(state)
    for locale,jobs in groups.items():
        if s.run_id:jobs=[j['id'] for j in store.run_jobs(s.run_id) if language(j['target_lang']).locale==locale]
        st=[store.job(j)['state'] for j in jobs]
        store.run_language_state(s.run_id,locale,'completed' if all(x=='finished' for x in st) else 'stopped' if s._stopped.is_set() else 'completed_with_errors')
    final='stopped' if s._stopped.is_set() else 'finished' if all(x=='finished' for x in states) else next((x for x in states if x.startswith('blocked') or x=='needs_reconciliation'),'completed_with_errors')
    admission=getattr(s,'admission',None)
    if final=='finished' and admission and len(admission.complete)<len(admission.order):
        final='needs_intervention';s.intervention_reason=s.intervention_reason or 'kira_sources_incomplete'
    if final=='finished' and s.run_id and any(j['state']!='finished' for j in store.run_jobs(s.run_id)):
        final='completed_with_errors'  # A resumed subset cannot complete the parent run.
    if final=='finished':s.intervention_reason=None
    else:s.intervention_reason=s.intervention_reason or 'kira_batches_need_review'
    if s.run_id:store.run_state(s.run_id,final)
    s.provider.monitor.intervention_reason=s.intervention_reason;s.provider.monitor.set_state(final)
    s._event('scheduler_drained',final);s._notify([])
