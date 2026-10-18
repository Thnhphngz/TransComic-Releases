"""One attempt ledger backing the pool's existing counters and monitor snapshots.

Only identifiers/revisions and file metadata are retained. No source, translation,
credential or context text enters telemetry. UI never handles worker-owned dicts.
"""
from copy import deepcopy
import threading
import time


TERMINAL = {'SUCCEEDED_AND_COMMITTED', 'FAILED', 'UNKNOWN', 'CANCELLED', 'REJECTED'}


def counters():
    return dict(requests=0, successful_requests=0, batches=0, translated_lines=0,
        completed_requests=0, errors=0, seconds=0.0, latency_samples=0, peak=0, wait_reasons={},
        failed_requests=0, unknown_requests=0, unknown_batches=0,
        claimed_not_sent=0,committing_requests=0,retranslation_requests=0)


class KiraTelemetry:
    def __init__(self, stats):
        self.stats = stats
        self.lock = threading.RLock()
        self.run_id = None
        self.state = 'not_started'
        self.attempts = {}
        self.files = {}
        self.unique = set()
        self.key_unique = {}
        self.key_names = {}
        self.started_at = self.ended_at = None
        self.version = 0
        self.persistence_error = False
        self.intervention_reason = None

    def begin(self, run_id, records=()):
        with self.lock:
            self.run_id = run_id; self.state = 'running'
            self.persistence_error = False
            self.intervention_reason = None
            self.recovery_phase=0
            self.attempts.clear(); self.files.clear(); self.unique.clear(); self.key_unique.clear();self.key_names.clear()
            self.started_at = time.time(); self.ended_at = None
            for stats in self.stats.values():stats.clear(); stats.update(counters())
            for record in records:
                self.claim(record)
                if record.get('sent'):self.sent(record['attempt_id'])
                if record.get('received'):self.received(record['attempt_id'])
                if record['state'] in TERMINAL:self.complete(record)
                self.started_at = min(self.started_at,record.get('started_at',self.started_at))
            self.version += 1

    def claim(self, record):
        with self.lock:
            aid = record['attempt_id']
            if aid in self.attempts:return False
            record = deepcopy(record)
            record.update(state='CLAIMED_NOT_SENT',sent=False,received=False)
            self.attempts[aid] = record
            key = record['key_id']; self.stats.setdefault(key,counters())
            self.key_names.setdefault(key,record.get('key_name','Key lịch sử'))
            self.stats[key]['claimed_not_sent'] += 1
            self.key_unique.setdefault(key,set())
            fid = (record['document_id'],record['target_language'])
            self.files.setdefault(key,{})
            self.files[key].setdefault(fid,dict(document_id=fid[0],target_language=fid[1],
                name=record['file_name'],source_instance=record['source_instance'],
                in_flight_lines=0,in_flight_requests=0,translated_lines=0,failed_lines=0,
                unknown_lines=0,rejected_lines=0,requests=0,successful_requests=0,
                saved_ids=set(),failed_ids=set(),unknown_ids=set(),rejected_ids=set()))
            self.version += 1
            return True

    def _file(self, record):
        return self.files[record['key_id']][(record['document_id'],record['target_language'])]

    def sent(self, attempt_id):
        with self.lock:
            r = self.attempts[attempt_id]
            if r['sent'] or r['state'] in TERMINAL:return False
            r.update(sent=True,state='IN_FLIGHT')
            stats = self.stats[r['key_id']]; stats['requests'] += 1
            stats['claimed_not_sent'] -= 1
            stats['retranslation_requests'] += r.get('mode')=='retranslation'
            f = self._file(r); f['requests'] += 1
            f['in_flight_requests'] += 1; f['in_flight_lines'] += len(r['line_ids'])
            self.version += 1
            return True

    def received(self, attempt_id):
        with self.lock:
            r = self.attempts[attempt_id]
            if not r['sent'] or r['received'] or r['state'] in TERMINAL:return False
            r.update(received=True,state='COMMITTING')
            self.stats[r['key_id']]['committing_requests'] += 1
            f = self._file(r)
            f['in_flight_requests'] -= 1; f['in_flight_lines'] -= len(r['line_ids'])
            self.version += 1
            return True

    def complete(self, record):
        with self.lock:
            aid = record['attempt_id']; r = self.attempts[aid]
            if r['state'] in TERMINAL:return False
            if r['sent']:self.received(aid)
            # Membership validation is deliberately independent of callback order.
            accepted = set(record.get('accepted_ids',())) & set(r['line_ids'])
            unknown = set(record.get('unknown_ids',())) & set(r['line_ids']) - accepted
            failed = set(record.get('failed_ids',())) & set(r['line_ids']) - accepted - unknown
            rejected = set(record.get('rejected_ids',())) & set(r['line_ids']) - accepted - unknown - failed
            r.update(deepcopy(record))
            r['accepted_ids'] = sorted(accepted)
            f = self._file(r); stats = self.stats[r['key_id']]
            if r['sent']:stats['committing_requests'] -= 1
            else:stats['claimed_not_sent'] -= 1
            if r['sent']:
                stats['completed_requests'] += 1
                if isinstance(r.get('seconds'),(int,float)):
                    stats['seconds'] += r['seconds'];stats['latency_samples'] += 1
                is_unknown = r['state']=='UNKNOWN'
                is_failed = r['state']=='FAILED'
                stats['unknown_requests'] += is_unknown; stats['unknown_batches'] += is_unknown
                stats['failed_requests'] += is_failed
                stats['errors'] += is_unknown or is_failed
                stats['successful_requests'] += bool(r.get('request_success'))
                f['successful_requests'] += bool(r.get('request_success'))
                stats['batches'] += r['state']=='SUCCEEDED_AND_COMMITTED'
            stats['translated_lines'] += len(accepted); f['translated_lines'] += len(accepted)
            f['failed_ids'].update(failed);f['unknown_ids'].update(unknown);f['rejected_ids'].update(rejected)
            f['saved_ids'].update(accepted)
            # Keep failed request counters as history, but unresolved line counts
            # must fall when a later, verified attempt commits those exact IDs.
            for files in self.files.values():
                other=files.get((r['document_id'],r['target_language']))
                if other is None:continue
                for field in ('failed_ids','unknown_ids','rejected_ids'):other[field].difference_update(accepted)
                other['failed_lines']=len(other['failed_ids']);other['unknown_lines']=len(other['unknown_ids']);other['rejected_lines']=len(other['rejected_ids'])
            positions = {(r['document_id'],r['target_language'],i) for i in accepted}
            self.unique.update(positions); self.key_unique[r['key_id']].update(positions)
            self.version += 1
            return True

    def set_state(self, state):
        with self.lock:
            self.state = state
            self.ended_at = time.time() if state in ('finished','stopped','interrupted','needs_intervention','quota_exhausted','blocked','completed_with_errors') else None
            self.version += 1

    def snapshot(self, pool_metrics):
        with self.lock:
            metrics = deepcopy(pool_metrics)
            now = self.ended_at or time.time()
            elapsed = max(.001,now-(self.started_at or now))
            active_files = set()
            for key,stats in metrics['per_key'].items():
                rows = []
                for value in self.files.get(key,{}).values():
                    f = {k:v for k,v in value.items() if k not in ('saved_ids','failed_ids','unknown_ids','rejected_ids')}
                    f['unique_translated_lines'] = len(value['saved_ids'])
                    if f['in_flight_requests']:active_files.add(f['source_instance'])
                    rows.append(f)
                stats['files'] = rows
                stats['unique_translated_lines'] = len(self.key_unique.get(key,()))
                stats['lines_per_minute'] = stats['translated_lines']*60/elapsed
                stats['in_flight_lines'] = sum(f['in_flight_lines'] for f in rows)
                stats['in_flight_requests'] = sum(f['in_flight_requests'] for f in rows)
            metrics.update(run_id=self.run_id,state=self.state,version=self.version,
                started_at=self.started_at,ended_at=self.ended_at,active_files=len(active_files),
                unique_translated_lines=len(self.unique),detail_available=bool(self.attempts))
            metrics['persistence_error']=self.persistence_error
            metrics['intervention_reason']=self.intervention_reason
            metrics['recovery_phase']=getattr(self,'recovery_phase',0)
            for name in ('requests','successful_requests','failed_requests','unknown_requests','errors','translated_lines'):
                metrics[name] = sum(s.get(name,0) for s in metrics['per_key'].values())
            metrics['effective_rpm']=metrics['requests']*60/elapsed
            return metrics
