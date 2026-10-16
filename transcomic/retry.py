"""Evidence-based retry permission. No uncertainty is converted into success."""
def allowed_retry(job, diagnostics, next_attempt):
    import json
    if json.loads(job.get('config') or '{}').get('kira_multi_key'): return False
    if diagnostics.get('finish_reason') in ('SAFETY', 'RECITATION', 'content_filter'): return False
    status = diagnostics.get('http_status')
    if next_attempt > min(6, 1 + job.get('auto_retries', 0)): return False
    if status == 504:
        return job['provider'] == 'kira' and bool(job['retry_504'])
    if diagnostics.get('failure_kind') in ('client_timeout', 'connect_error', 'network_error', 'internal_error', 'http_server_error'):
        return False
    if status == 429:
        return diagnostics.get('failure_kind') == 'rate_limit'
    return diagnostics.get('failure_kind') in ('partial_response', 'invalid_line_response', 'invalid_schema', 'wrong_target_language')
