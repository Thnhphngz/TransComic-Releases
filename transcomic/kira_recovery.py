"""Frozen, durable recovery policy. No timers, credentials or HTTP here."""
import json
import math
import random

REASON_LABELS={
    'kira_keys_unavailable':'Không có key khả dụng; kiểm tra trạng thái key',
    'retry_original_key_unavailable':'Key gốc không khả dụng; không đổi key cho batch thử lại',
    'kira_request_exceeds_tpm':'Batch vượt trần TPM đã cấu hình',
    'retry_budget_exhausted':'Đã hết ngân sách thử lại của lượt dịch',
    'request_or_retry_budget_exhausted':'Đã chạm trần request/thử lại đã cấu hình',
    'token_budget_exhausted':'Đã chạm trần token dự phòng của lượt dịch',
    'recovery_wait_budget_exhausted':'Đã hết thời gian chờ phục hồi cho phép',
    'rate_limit_recovery_budget_exhausted':'Đã hết số lượt phục hồi HTTP 429 cho phép',
    'batch_retry_limit_exhausted':'Đã hết số lần thử lại an toàn của batch',
    'auto_retry_disabled':'Tự thử lại đã tắt cho lượt dịch này',
    'kira_batches_need_review':'Còn dòng không thể tự phục hồi an toàn; bản dịch đã lưu được giữ',
    'unknown_request':'Có request chưa rõ kết quả; không tự gửi lại',
}

def reason_label(reason):return REASON_LABELS.get(reason,reason or '')


def adopt_authorized_recovery(store,job):
    """Explicit UI Start/Resume adopts the new risk policy, never new budgets.

    Old no-retry snapshots remain no-retry. A storage open alone never calls
    this and never sends HTTP. Historical token reservations are conservative.
    """
    config=json.loads(job['config'])
    if job['provider']!='kira' or config.get('kira_recovery_version')!=1:return
    jobs=store.run_jobs(job['run_id']) if job['run_id'] else [job]
    if any(b['state']=='inflight' for j in jobs for b in store.batches(j['id'])):return
    ceiling=int(store.setting('kira_tpm','1000000'))
    with store.transaction():
        for j in jobs:
            cfg=json.loads(j['config'])
            if cfg.get('kira_recovery_version')!=1:continue
            bound=cfg.get('max_requests') or j['max_requests']
            if bound is None:continue  # No verified finite request allowance.
            cfg.update(kira_recovery_version=2,uncertain_retry_authorized=True,
                kira_effective_token_limit=cfg.get('kira_token_limit') or bound*ceiling)
            store.db.execute('UPDATE jobs SET config=? WHERE id=?',(json.dumps(cfg),j['id']))
            store.db.execute('UPDATE request_attempts SET reserved_tokens=? WHERE reserved_tokens=0 AND original_batch_id IN (SELECT id FROM batches WHERE job_id=?)',(ceiling,j['id']))
        if job['run_id']:
            cfg=store.run(job['run_id'])['config']
            if cfg.get('kira_recovery_version')==1:
                bound=cfg.get('max_requests')
                if bound is not None:
                    cfg.update(kira_recovery_version=2,uncertain_retry_authorized=True,
                        kira_effective_token_limit=cfg.get('kira_token_limit') or bound*ceiling)
                    store.db.execute('UPDATE translation_runs SET config=? WHERE id=?',(json.dumps(cfg),job['run_id']))


def frozen_policy(store, config):
    config=dict(config)
    if not config.get('kira_multi_key'):return config
    # An explicit legacy snapshot retains its original no-retry policy.
    if config.get('kira_recovery_version')==0:
        return dict(config,auto_retries=0,retry_504=False)
    for name,default,minimum,maximum in (
        ('kira_retry_limit',2,0,5),('kira_retry_budget',30,0,10000),
        ('kira_request_limit',0,0,1000000),('kira_token_limit',0,0,1000000000000),('kira_retry_backoff',1,0,30),
        ('rate_wait_budget',300,0,3600),('rate_cooldown_limit',10,0,100),('rate_backoff_max',30,0,300)):
        value=float(config.get(name,store.setting(name,str(default))))
        if not math.isfinite(value) or not minimum<=value<=maximum:raise ValueError('Invalid Kira recovery limit: '+name)
        config[name]=value if name in ('kira_retry_backoff','rate_wait_budget','rate_backoff_max') else int(value)
    version=1 if config.get('kira_recovery_version')==1 else 2
    return dict(config,kira_recovery_version=version,auto_retries=config['kira_retry_limit'],retry_504=False,
                uncertain_retry_authorized=version>=2)


def retry_usage(store, job):
    if job['run_id']:
        return store.db.execute('SELECT COUNT(*) FROM request_attempts a JOIN batches b ON a.original_batch_id=b.id JOIN jobs j ON j.id=b.job_id WHERE j.run_id=? AND a.attempt_number>1',(job['run_id'],)).fetchone()[0]
    return store.db.execute('SELECT COUNT(*) FROM request_attempts a JOIN batches b ON a.original_batch_id=b.id WHERE b.job_id=? AND a.attempt_number>1',(job['id'],)).fetchone()[0]


def budget_reason(store,job,*,retry=False,cost=0):
    """Read-only preflight; prepare_attempt still atomically checks every limit.

    Exhausted jobs must not wait for RPM or consume rate reservations just to
    discover that no more HTTP is permitted.
    """
    cfg=json.loads(job['config'])
    if cfg.get('kira_recovery_version',0)<2:return None
    where='j.run_id=?' if job['run_id'] else 'j.id=?'
    with store.lock:
        row=store.db.execute('SELECT COUNT(*),COALESCE(SUM(a.attempt_number>1),0),COALESCE(SUM(a.reserved_tokens),0),COALESCE(SUM(j.id=?),0) FROM request_attempts a JOIN batches b ON b.id=a.original_batch_id JOIN jobs j ON j.id=b.job_id WHERE '+where,(job['id'],job['run_id'] or job['id'])).fetchone()
    if cfg.get('max_requests') is not None and row[0]>=cfg['max_requests'] or job['max_requests'] is not None and row[3]>=job['max_requests']:return 'request_or_retry_budget_exhausted'
    if retry and row[1]>=cfg['kira_retry_budget']:return 'retry_budget_exhausted'
    if row[2]+cost>cfg['kira_effective_token_limit']:return 'token_budget_exhausted'
    return None


def schedule_retry(store, batch_id, diagnostics, key_id, now):
    """Reserve bounded wait once; the later atomic attempt consumes request budget.

    Return (durable diagnostics, refusal reason). Already accepted translations
    and source/translation revisions are checked again in prepare_attempt.
    """
    from .retry import allowed_retry
    with store.transaction():
        batch=store.batch(batch_id);job=store.job(batch['job_id']);config=json.loads(job['config'])
        prior=store.attempts(batch_id)
        if batch['state'] not in ('error','partial','unknown') or not prior:return None,None
        if prior[-1]['state']!='finished':return None,None
        if not allowed_retry(job,diagnostics,len(prior)+1):
            if config.get('kira_recovery_version',0)>=1 and diagnostics.get('failure_kind') in ('rate_limit','partial_response','invalid_line_response','invalid_schema','wrong_target_language','connect_not_sent','not_sent','client_timeout','http_504','http_server_error','network_error','http_timeout') and diagnostics.get('finish_reason') not in ('SAFETY','RECITATION','content_filter'):
                return None,'auto_retry_disabled' if not job['auto_retries'] else 'batch_retry_limit_exhausted'
            return None,None
        payload=batch.get('original_payload') or batch['payload']
        if isinstance(payload,str):payload=json.loads(payload)
        if not any((row:=store.line(item['id'])) and row['state'] in ('error','unknown','wrong_target_language') and row['attempt_kind']!='manual'
                   and row['source_revision']==item['source_revision'] and row['translation_revision']==item['translation_revision'] for item in payload):return None,None
        if retry_usage(store,job)>=config['kira_retry_budget']:return None,'retry_budget_exhausted'
        maximum=float(config.get('rate_backoff_max',30))
        base=min(maximum,config['kira_retry_backoff']*2**(len(prior)-1))
        delay=max(.02,min(maximum,base+random.uniform(0,min(.25,base*.2))))
        hinted=diagnostics.get('retry_after_seconds')
        if isinstance(hinted,(int,float)) and math.isfinite(hinted):delay=max(delay,hinted)
        jobs=store.run_jobs(job['run_id']) if job['run_id'] else [job]
        rate_used=sum(int(json.loads(j['config']).get('kira_rate_recoveries',0)) for j in jobs)
        if diagnostics.get('http_status')==429:
            if rate_used>=float(config.get('rate_cooldown_limit',10)):return None,'rate_limit_recovery_budget_exhausted'
            config['kira_rate_recoveries']=config.get('kira_rate_recoveries',0)+1
        reserved=sum(float(json.loads(j['config']).get('kira_wait_reserved',0)) for j in jobs)
        if reserved+delay>float(config.get('rate_wait_budget',300)):return None,'recovery_wait_budget_exhausted'
        config['kira_wait_reserved']=config.get('kira_wait_reserved',0)+delay
        store.db.execute('UPDATE jobs SET config=? WHERE id=?',(json.dumps(config),job['id']))
        record=dict(diagnostics,retry_not_before=now+delay,retry_key_id=key_id,retry_model=job['model'],auto_retry_scheduled=True)
        store.db.execute('UPDATE request_attempts SET diagnostics=? WHERE id=?',(json.dumps(record),prior[-1]['id']))
        store.record_batch_diagnostics(batch_id,record)
        return record,None
