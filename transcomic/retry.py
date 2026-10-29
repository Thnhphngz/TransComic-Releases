"""Evidence-based retry permission. No uncertainty is converted into success."""
def allowed_retry(job, diagnostics, next_attempt):
    import json
    config=json.loads(job.get('config') or '{}')
    from .completion import enabled,retryable
    if enabled(config):
        if config.get('kira_multi_key') and diagnostics.get('recoverable_key_rejection') is True:return True
        return retryable(diagnostics)
    if job.get('provider') == 'deepseek': return False
    multi=config.get('kira_multi_key')
    if multi and config.get('kira_recovery_version') not in (1,2,3,4):return False
    if diagnostics.get('finish_reason') in ('SAFETY', 'RECITATION', 'content_filter'): return False
    status = diagnostics.get('http_status')
    if not config.get('kira_completion_policy') and next_attempt > min(21 if config.get('kira_recovery_version')==4 else 6, 1 + job.get('auto_retries', 0)): return False
    if multi and config.get('kira_recovery_version')==4:
        kind=diagnostics.get('failure_kind')
        if kind in ('authentication','quota_exhausted') and diagnostics.get('recoverable_key_rejection') is True:return True
        if kind in ('shutdown_cancelled','authentication','permission','quota_exhausted','model_or_request'):return False
        unknown=diagnostics.get('unknown_outcome') or diagnostics.get('uncertain_lineage') or status in (408,500,502,504) or kind in ('client_timeout','network_error','connect_error','internal_error','restart_unknown')
        if unknown:return config.get('uncertain_retry_authorized') is True
        return kind in ('connect_not_sent','not_sent','rate_limit','partial_response','invalid_line_response','invalid_schema','wrong_target_language') or kind=='http_server_error' and status==503
    uncertain=diagnostics.get('unknown_outcome') or diagnostics.get('uncertain_lineage') or status in (408,500,502,503,504) or diagnostics.get('failure_kind') in ('client_timeout','connect_error','network_error','internal_error','http_server_error','http_timeout','http_504','restart_unknown')
    if multi and config.get('uncertain_retry_authorized') and uncertain:
        return next_attempt<=(5 if config.get('kira_recovery_version')==3 else 3) and diagnostics.get('failure_kind') not in ('shutdown_cancelled','authentication','permission','quota_exhausted','model_or_request')
    if status == 504:
        return not multi and job['provider'] == 'kira' and bool(job['retry_504'])
    if diagnostics.get('failure_kind') in ('client_timeout', 'connect_error', 'network_error', 'internal_error', 'http_server_error'):
        return False
    if status == 429:
        return diagnostics.get('failure_kind') == 'rate_limit'
    if multi and diagnostics.get('failure_kind') in ('connect_not_sent','not_sent'):return True
    return diagnostics.get('failure_kind') in ('partial_response', 'invalid_line_response', 'invalid_schema', 'wrong_target_language')
