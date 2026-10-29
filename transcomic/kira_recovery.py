"""Frozen, durable recovery policy. No timers, credentials or HTTP here."""
import json
import math
import random

REASON_LABELS={
    'admission_input_invalid':'Đầu vào của file không còn hợp lệ; giữ tiến độ và kiểm tra nguồn/ảnh',
    'kira_sources_incomplete':'Còn file chưa hoàn tất; giữ checkpoint và các bản dịch đã lưu',
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
    'request_admission_refused':'Chưa cấp được request; giữ checkpoint để kiểm tra',
    'recovery_cost_unverified':'Chưa xác minh được giá trần; không gửi thêm request',
    'recovery_cost_budget_exhausted':'Đã đạt trần chi phí phục hồi đã cấu hình',
    'legacy_checkpoint_requires_review':'Checkpoint cũ cần đối chiếu; giữ nguyên quyền và ngân sách đã lưu',
    'provider_recovering':'Đang chờ cooldown dịch vụ',
    'retry_scheduled':'Đã lên lịch thử lại trong ngân sách',
    'waiting_rate_limit':'Chờ giới hạn tốc độ của tài khoản',
    'network_waiting':'Chờ kết nối mạng phục hồi',
    'user_paused':'Người dùng đã tạm dừng',
    'http_server_error':'Lỗi dịch vụ tạm thời',
    'rate_limit':'Tài khoản đang bị giới hạn tốc độ',
    'connect_not_sent':'Không kết nối được; chưa gửi nội dung request',
    'client_timeout':'Hết thời gian chờ; chưa rõ kết quả',
    'http_504':'Gateway timeout; chưa rõ kết quả',
    'network_error':'Mất kết nối; chưa rõ kết quả',
}

def reason_label(reason):return REASON_LABELS.get(reason,reason or '')


def adopt_authorized_recovery(store,job):
    """Compatibility hook: Start/Resume never changes frozen retry consent."""
    return


def frozen_policy(store, config):
    config=dict(config)
    if config.get('kira_multi_key') and config.get('translation_completion_policy')==1:
        from .completion import authorize
        config=authorize('kira',config)
    if not config.get('kira_multi_key'):return config
    # An explicit legacy snapshot retains its original no-retry policy.
    if config.get('kira_recovery_version')==0:
        return dict(config,auto_retries=0,retry_504=False)
    version=config.get('kira_recovery_version',4)
    # New commands opt in; explicit legacy snapshots retain their finite policy.
    completion=config.get('kira_completion_policy',int('kira_recovery_version' not in config))
    admission=config.get('kira_dispatch_policy',completion)
    if type(completion) is not int or completion not in (0,1) or type(admission) is not int or admission not in (0,1):raise ValueError('Invalid Kira completion/admission policy')
    config.update(kira_completion_policy=completion,kira_dispatch_policy=admission)
    if version not in (1,2,3,4):raise ValueError('Unsupported Kira recovery policy')
    if (completion or admission) and version<4:raise ValueError('Completion/admission policy requires Kira recovery v4')
    for name,default,minimum,maximum in (
        ('kira_retry_limit',4 if version>=3 else 2,0,20 if version>=4 else 5),('kira_retry_budget',30,0,10000),
        ('kira_request_limit',0,0,1000000),('kira_token_limit',0,0,1000000000000),('kira_retry_backoff',1,0,30),
        ('rate_wait_budget',300,0,3600),('rate_cooldown_limit',10,0,100),('rate_backoff_max',30,0,300)):
        value=float(config.get(name,store.setting(name,str(default))))
        if not math.isfinite(value) or not minimum<=value<=maximum:raise ValueError('Invalid Kira recovery limit: '+name)
        config[name]=value if name in ('kira_retry_backoff','rate_wait_budget','rate_backoff_max') else int(value)
    if version==3:config['kira_retry_limit']=min(4,config['kira_retry_limit'])
    if version>=4:
        try:cost_policy=json.loads(store.setting('kira_recovery_cost_policy','{}'))
        except (TypeError,ValueError):raise ValueError('Invalid Kira recovery cost policy') from None
        if not isinstance(cost_policy,dict):raise ValueError('Invalid Kira recovery cost policy')
        for name in ('kira_additional_cost_limit','kira_token_cost_upper_bound','kira_cost_source'):
            if name not in config and name in cost_policy:config[name]=cost_policy[name]
        for name,default,maximum in (('kira_recovery_seconds',600,86400),('kira_retry_concurrency',4,30)):
            value=float(config.get(name,store.setting(name,str(default))))
            if not math.isfinite(value) or not 1<=value<=maximum:raise ValueError('Invalid Kira recovery limit: '+name)
            config[name]=int(value)
        # Monetary caps require a verified per-reserved-token upper bound.
        for name in ('kira_additional_cost_limit','kira_token_cost_upper_bound'):
            value=config.get(name)
            if value is not None and (type(value) not in (int,float) or not math.isfinite(value) or value<0):raise ValueError('Invalid recovery cost limit')
        source=config.get('kira_cost_source','')
        if not isinstance(source,str) or len(source)>1000:raise ValueError('Invalid recovery cost source')
        config['kira_cost_source']=source.strip()
        authorized=config.get('uncertain_retry_authorized',store.setting('kira_allow_unknown_resend','0')=='1') is True
    else:authorized=version>=2
    return dict(config,kira_recovery_version=version,auto_retries=config['kira_retry_limit'],retry_504=False,
                uncertain_retry_authorized=authorized)


def retry_usage(store, job):
    cfg=json.loads(job['config'])
    with store.lock:
        if cfg.get('kira_recovery_version',0)>=4 and cfg.get('automation_owner'):
            return store.db.execute("SELECT COUNT(*) FROM request_attempts a JOIN batches b ON a.original_batch_id=b.id JOIN jobs j ON j.id=b.job_id WHERE json_extract(j.config,'$.automation_owner')=? AND json_extract(j.config,'$.automation_cycle')=? AND a.attempt_number>1",(cfg['automation_owner'],cfg['automation_cycle'])).fetchone()[0]
        if job['run_id']:
            return store.db.execute('SELECT COUNT(*) FROM request_attempts a JOIN batches b ON a.original_batch_id=b.id JOIN jobs j ON j.id=b.job_id WHERE j.run_id=? AND a.attempt_number>1',(job['run_id'],)).fetchone()[0]
        return store.db.execute('SELECT COUNT(*) FROM request_attempts a JOIN batches b ON a.original_batch_id=b.id WHERE b.job_id=? AND a.attempt_number>1',(job['id'],)).fetchone()[0]


def budget_reason(store,job,*,retry=False,cost=0):
    """Read-only preflight; prepare_attempt still atomically checks every limit.

    Exhausted jobs must not wait for RPM or consume rate reservations just to
    discover that no more HTTP is permitted.
    """
    cfg=json.loads(job['config'])
    if cfg.get('translation_completion_policy')==1:return None
    if cfg.get('kira_recovery_version',0)<2:return None
    # A recovery deadline fences additional attempts, never a batch's first
    # request. Pending first-pass work must survive an older retry's deadline.
    if retry and cfg.get('kira_recovery_version',0)>=4 and not cfg.get('kira_completion_policy'):
        current=json.loads(store.job(job['id'])['config'])
        began=current.get('kira_recovery_started_at')
        if began is not None and __import__('time').time()-began>=cfg['kira_recovery_seconds']:return 'recovery_wait_budget_exhausted'
    where='j.run_id=?' if job['run_id'] else 'j.id=?'
    with store.lock:
        row=store.db.execute('SELECT COUNT(*),COALESCE(SUM(a.attempt_number>1),0),COALESCE(SUM(a.reserved_tokens),0),COALESCE(SUM(j.id=?),0) FROM request_attempts a JOIN batches b ON b.id=a.original_batch_id JOIN jobs j ON j.id=b.job_id WHERE '+where,(job['id'],job['run_id'] or job['id'])).fetchone()
    if cfg.get('max_requests') is not None and row[0]>=cfg['max_requests'] or job['max_requests'] is not None and row[3]>=job['max_requests']:return 'request_or_retry_budget_exhausted'
    if retry and not cfg.get('kira_completion_policy') and row[1]>=cfg['kira_retry_budget']:return 'retry_budget_exhausted'
    if retry and cfg.get('kira_recovery_version',0)>=4:
        if not cfg.get('kira_completion_policy') and retry_usage(store,job)>=cfg['kira_retry_budget']:return 'retry_budget_exhausted'
        cap=cfg.get('kira_additional_cost_limit')
        if cap is not None:
            price=cfg.get('kira_token_cost_upper_bound')
            if price is None or not cfg.get('kira_cost_source'):return 'recovery_cost_unverified'
            if job['run_id']:scope,args='j.run_id=?',(job['run_id'],)
            elif cfg.get('automation_owner'):scope,args="json_extract(j.config,'$.automation_owner')=? AND json_extract(j.config,'$.automation_cycle')=?",(cfg['automation_owner'],cfg['automation_cycle'])
            else:scope,args='j.id=?',(job['id'],)
            with store.lock:
                tokens=store.db.execute('SELECT COALESCE(SUM(a.reserved_tokens),0) FROM request_attempts a JOIN batches b ON b.id=a.original_batch_id JOIN jobs j ON j.id=b.job_id WHERE a.attempt_number>1 AND '+scope,args).fetchone()[0]
            if (tokens+cost)*price>cap:return 'recovery_cost_budget_exhausted'
    if cfg.get('kira_effective_token_limit') is not None and row[2]+cost>cfg['kira_effective_token_limit']:return 'token_budget_exhausted'
    return None


def record_blocked_batch(store,batch_id,reason):
    """Retain a durable explanation without changing payload, attempts or rows."""
    with store.transaction():
        batch=store.batch(batch_id);diagnostics=dict(batch.get('diagnostics') or {})
        if diagnostics.get('dispatch_block_reason')==reason:return
        diagnostics['dispatch_block_reason']=reason
        store.record_batch_diagnostics(batch_id,diagnostics)
        store.log.emit('dispatch_blocked',job_id=batch['job_id'],batch_id=batch_id,reason=reason)


def blocked_state(reason):
    if reason=='unknown_request':return 'needs_reconciliation'
    if any(part in reason for part in ('budget','exhausted','cost_unverified')):return 'blocked_budget'
    return 'blocked'


def schedule_retry(store, batch_id, diagnostics, key_id, now):
    """Reserve bounded wait once; the later atomic attempt consumes request budget.

    Return (durable diagnostics, refusal reason). Already accepted translations
    and source/translation revisions are checked again in prepare_attempt.
    """
    from .retry import allowed_retry
    with store.transaction():
        batch=store.batch(batch_id);job=store.job(batch['job_id']);config=json.loads(job['config'])
        def blocked(reason):
            if config.get('kira_recovery_version',0)>=4:record_blocked_batch(store,batch_id,reason)
            return None,reason
        prior=store.attempts(batch_id)
        if batch['state'] not in ('error','partial','unknown') or not prior:return None,None
        if prior[-1]['state']!='finished':return None,None
        if not allowed_retry(job,diagnostics,len(prior)+1):
            if config.get('kira_recovery_version',0)>=4 and (diagnostics.get('unknown_outcome') or diagnostics.get('uncertain_lineage') or diagnostics.get('http_status')==504):
                return blocked('unknown_request')
            if config.get('kira_recovery_version',0)>=1 and diagnostics.get('failure_kind') in ('rate_limit','partial_response','invalid_line_response','invalid_schema','wrong_target_language','connect_not_sent','not_sent','client_timeout','http_504','http_server_error','network_error','http_timeout') and diagnostics.get('finish_reason') not in ('SAFETY','RECITATION','content_filter'):
                return blocked('auto_retry_disabled' if not job['auto_retries'] else 'batch_retry_limit_exhausted')
            return None,None
        payload=batch.get('original_payload') or batch['payload']
        if isinstance(payload,str):payload=json.loads(payload)
        if not any((row:=store.line(item['id'])) and row['state'] in ('error','unknown','wrong_target_language') and row['attempt_kind']!='manual'
                   and row['source_revision']==item['source_revision'] and row['translation_revision']==item['translation_revision'] for item in payload):return None,None
        completion=config.get('kira_completion_policy')==1
        if not completion and retry_usage(store,job)>=config['kira_retry_budget']:return blocked('retry_budget_exhausted')
        if config.get('kira_recovery_version',0)>=4:
            began=config.setdefault('kira_recovery_started_at',now)
            if not completion and now-began>=config['kira_recovery_seconds']:return blocked('recovery_wait_budget_exhausted')
        maximum=float(config.get('rate_backoff_max',30))
        base=min(maximum,config['kira_retry_backoff']*2**min(len(prior)-1,20))
        delay=max(.02,min(maximum,base+random.uniform(0,min(.25,base*.2))))
        hinted=diagnostics.get('retry_after_seconds')
        if isinstance(hinted,(int,float)) and math.isfinite(hinted):delay=max(delay,hinted)
        if not completion and config.get('kira_recovery_version',0)>=4 and now+delay-config['kira_recovery_started_at']>config['kira_recovery_seconds']:return blocked('recovery_wait_budget_exhausted')
        jobs=store.run_jobs(job['run_id']) if job['run_id'] else [job]
        rate_used=sum(int(json.loads(j['config']).get('kira_rate_recoveries',0)) for j in jobs)
        if diagnostics.get('http_status')==429:
            if not completion and rate_used>=float(config.get('rate_cooldown_limit',10)):return blocked('rate_limit_recovery_budget_exhausted')
            config['kira_rate_recoveries']=config.get('kira_rate_recoveries',0)+1
        reserved=sum(float(json.loads(j['config']).get('kira_wait_reserved',0)) for j in jobs)
        if not completion and reserved+delay>float(config.get('rate_wait_budget',300)):return blocked('recovery_wait_budget_exhausted')
        config['kira_wait_reserved']=config.get('kira_wait_reserved',0)+delay
        store.db.execute('UPDATE jobs SET config=? WHERE id=?',(json.dumps(config),job['id']))
        record=dict(diagnostics,retry_not_before=now+delay,retry_key_id=key_id,retry_model=job['model'],auto_retry_scheduled=True)
        store.db.execute('UPDATE request_attempts SET diagnostics=? WHERE id=?',(json.dumps(record),prior[-1]['id']))
        store.record_batch_diagnostics(batch_id,record)
        return record,None
