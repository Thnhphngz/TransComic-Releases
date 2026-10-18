"""Bounded summary reads; attempt diagnostics are the durable attribution ledger."""
import json
import time
from .kira_telemetry import KiraTelemetry, TERMINAL, counters


def save_summary(store, snapshot):
    if not snapshot.get('run_id'):return
    with store.transaction():
        store.db.execute('INSERT INTO kira_monitor_runs(run_id,updated_at,snapshot) VALUES (?,?,?) '
            'ON CONFLICT(run_id) DO UPDATE SET updated_at=excluded.updated_at,snapshot=excluded.snapshot',
            (snapshot['run_id'],time.time(),json.dumps(snapshot,ensure_ascii=False)))


def records_for_run(store, run_id):
    with store.lock:
        rows=store.db.execute('SELECT a.state,a.diagnostics FROM request_attempts a '
            'JOIN batches b ON b.id=a.original_batch_id JOIN jobs j ON j.id=b.job_id '
            'WHERE j.run_id=? OR j.id=? ORDER BY a.created_at,a.id',(run_id,run_id)).fetchall()
    records=[]
    for row in rows:
        record=json.loads(row['diagnostics'] or '{}').get('monitor')
        if not record or record.get('run_id')!=run_id:continue
        if record['state'] not in TERMINAL:
            # Opening/recovery never dispatches. A persisted HTTP start is uncertain.
            record.update(state='UNKNOWN' if record.get('sent') else 'CANCELLED',
                unknown_ids=record['line_ids'] if record.get('sent') else [],
                accepted_ids=[],request_success=False)
        records.append(record)
    return records


def load_latest(store):
    with store.lock:
        row=store.db.execute('SELECT snapshot FROM kira_monitor_runs ORDER BY updated_at DESC LIMIT 1').fetchone()
    if row is None:return None
    snapshot=json.loads(row[0]); records=records_for_run(store,snapshot['run_id'])
    if not records:
        snapshot.update(archived=True,detail_available=False,busy=0,active_files=0)
        if snapshot['state'] in ('running','user_paused','waiting_rate_limit','retry_scheduled','network_waiting','provider_recovering'):snapshot['state']='interrupted'
        for stats in snapshot['per_key'].values():
            stats.update(busy=0,in_flight_lines=0,in_flight_requests=0,files=[])
        return snapshot
    stats={k:counters() for k in snapshot['per_key']}
    telemetry=KiraTelemetry(stats);telemetry.begin(snapshot['run_id'],records)
    for record in records:
        key=record['key_id']
        snapshot['per_key'].setdefault(key,dict(name=record.get('key_name','Key lịch sử'),
            account_scope=record['account_scope'],busy=0,peak=0,wait_reason='no_pending_work',
            enabled=False,status='REMOVED',slot_limit=0))
    for key,s in snapshot['per_key'].items():
        stats[key]['peak']=s.get('peak',0)
        stats[key]['wait_reasons']=s.get('wait_reasons',{})
        s.update(stats[key]);s['busy']=0
        s['mean_seconds']=s['seconds']/s['latency_samples'] if s['latency_samples'] else 0
        s['error_rate']=s['errors']/s['requests'] if s['requests'] else 0
    state=snapshot['state']
    if state not in ('finished','stopped','interrupted','needs_intervention','quota_exhausted','blocked','completed_with_errors'):
        state='interrupted'
    telemetry.set_state(state)
    telemetry.recovery_phase=snapshot.get('recovery_phase',0)
    if snapshot.get('ended_at'):telemetry.ended_at=snapshot['ended_at']
    snapshot['busy']=0
    result=telemetry.snapshot(snapshot)
    result['archived']=True
    result['detail_available']=bool(records)
    return result
