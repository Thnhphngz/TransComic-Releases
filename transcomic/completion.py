"""Explicit completion policy for newly started Kira/DeepSeek commands."""
import random


def enabled(config):return config.get('translation_completion_policy')==1


def pending(row,config):
    from .status import usable
    states=('pending','error','unknown','wrong_target_language','stale') if enabled(config) else ('pending',)
    return row['state'] in states and not usable(row) and (not enabled(config) or row.get('attempt_kind')!='manual')


def authorize(provider,config=None):
    value=dict(config or {})
    if provider not in ('kira','deepseek'):return value
    value.update(translation_completion_policy=1,uncertain_retry_authorized=True,
                 max_requests=None,request_interval=0,completion_backoff_base=.25,completion_backoff_max=3)
    if provider=='kira':
        value.update(kira_multi_key=True,kira_recovery_version=4,kira_completion_policy=1,kira_dispatch_policy=1,
                     kira_request_limit=0,kira_token_limit=0,kira_additional_cost_limit=None,
                     kira_retry_concurrency=30,kira_retry_backoff=.25,rate_backoff_max=3)
    return value


def retryable(diagnostics):
    if diagnostics.get('finish_reason') in ('SAFETY','RECITATION','content_filter'):return False
    kind=diagnostics.get('failure_kind');status=diagnostics.get('http_status')
    if kind in ('authentication','permission','model_or_request','model_not_found','quota_exhausted','shutdown_cancelled'):return False
    return status in (408,429,500,502,503,504) or diagnostics.get('unknown_outcome') or kind in (
        'rate_limit','http_server_error','client_timeout','connect_error','connect_not_sent','not_sent','network_error',
        'internal_error','restart_unknown','partial_response','invalid_line_response','invalid_schema','truncated_response','wrong_target_language') or bool(diagnostics.get('wrong_language_ids'))


def delay(config,number,diagnostics):
    base=max(.01,float(config.get('completion_backoff_base',.25)))
    maximum=max(base,float(config.get('completion_backoff_max',3)))
    wait=min(maximum,base*2**min(max(0,number-1),16))*random.uniform(.9,1.1)
    hint=diagnostics.get('retry_after_seconds')
    if isinstance(hint,(int,float)) and __import__('math').isfinite(hint):wait=max(wait,hint)
    return max(.01,wait)


def retry_after(value):
    if not value:return None
    import math
    try:seconds=float(value)
    except (TypeError,ValueError):
        from datetime import datetime,timezone
        from email.utils import parsedate_to_datetime
        try:
            date=parsedate_to_datetime(value)
            if date.tzinfo is None:date=date.replace(tzinfo=timezone.utc)
            seconds=(date-datetime.now(timezone.utc)).total_seconds()
        except (TypeError,ValueError,OverflowError):return None
    return max(0,seconds) if math.isfinite(seconds) else None


def reconcile_unknown(store,jobs):
    """An explicit restart may resend a retired unknown attempt, with history."""
    import json
    for jid in jobs:
        if not enabled(json.loads(store.job(jid)['config'])):continue
        for batch in store.batches(jid):
            if batch['state']!='unknown':continue
            prior=store.attempts(batch['id'])
            if not prior or prior[-1]['state']!='unknown':continue
            attempt=prior[-1];diagnostics=dict(attempt.get('diagnostics') or {})
            diagnostics.update(failure_kind='restart_unknown',unknown_outcome=True,uncertain_lineage=True)
            with store.transaction():
                store.complete_attempt(attempt['id'],diagnostics)
                store.record_batch_diagnostics(batch['id'],diagnostics)
