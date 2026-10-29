"""Explicit offline recovery of a previously rejected DeepSeek response.

No HTTP or new request attempt is created. The original finished attempt and
its rejection diagnostics stay untouched; a separate durable event explains
why its text was subsequently accepted under the compatibility parser.
"""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from .deepseek_json import PARSER_VERSION, parse_translation
from .translation_policy import SEMANTIC_VERSIONS

TABLE='''CREATE TABLE IF NOT EXISTS deepseek_recovery_events (
 id TEXT PRIMARY KEY, campaign TEXT NOT NULL, batch_id TEXT NOT NULL,
 source_attempt_id TEXT NOT NULL, raw_response_sha256 TEXT NOT NULL,
 parser_version TEXT NOT NULL, event TEXT NOT NULL,
 UNIQUE(campaign,batch_id,source_attempt_id,raw_response_sha256,parser_version))'''


def recover_response(store, *, campaign, batch_id, attempt_id, raw_response):
    """Validate the saved recorder envelope and atomically adopt all its lines.

    Revision guards protect manual edits. Any language/mapping/write failure
    rolls back the entire operation. Replaying the same recovery is read-only.
    """
    raw_hash=hashlib.sha256(raw_response).hexdigest()
    with store.transaction():
        batch=store.batch(batch_id);job=store.job(batch['job_id'])
        attempts=store.attempts(batch_id)
        if not attempts or attempts[-1]['id']!=attempt_id:raise ValueError('Source attempt is not latest')
        source_attempt=attempts[-1]
        if job['provider']!='deepseek' or job['prompt_version'] not in SEMANTIC_VERSIONS:
            raise ValueError('Unsupported recovery policy/provider')
        if source_attempt['state']!='finished' or source_attempt['diagnostics'].get('http_status')!=200 or source_attempt['diagnostics'].get('failure_kind')!='invalid_schema':
            raise ValueError('Only a known finished schema rejection can be recovered')
        payload=json.loads(batch['original_payload']);ids=[r['id'] for r in payload]
        if len(set(ids))!=len(ids):raise ValueError('Duplicate original IDs')
        raw=json.loads(raw_response)
        if raw.get('http_status')!=200 or raw.get('line_ids')!=ids or raw.get('prompt_version')!=job['prompt_version'] or raw.get('model')!=job['model']:
            raise ValueError('Saved response does not match original batch')
        envelope=raw['envelope'];choice=envelope['choices'][0]
        if envelope.get('model')!=job['model'] or choice.get('finish_reason')!='stop' or choice['message'].get('reasoning_content'):
            raise ValueError('Incomplete or incompatible response')
        parsed=parse_translation(choice['message']['content'],ids,job['prompt_version'])
        if parsed.error:raise ValueError(parsed.error)
        store.db.execute(TABLE)
        previous=store.db.execute('SELECT event FROM deepseek_recovery_events WHERE campaign=? AND batch_id=? AND source_attempt_id=? AND raw_response_sha256=? AND parser_version=?',
            (campaign,batch_id,attempt_id,raw_hash,PARSER_VERSION)).fetchone()
        if previous:
            event=json.loads(previous[0])
            if batch['state']!='done' or any(store.line(r['id'])!=r for r in event['after']):
                raise ValueError('Recovered rows changed; replay cannot overwrite them')
            return event
        if batch['state']!='error' or batch['payload']!=payload:raise ValueError('Batch no longer matches rejected request')
        before=[store.line(id) for id in ids]
        for item,row in zip(payload,before):
            if row['document_id']!=job['document_id'] or row['state']!='error' or row['translation'] is not None or row['attempt_kind']=='manual' or any(row[k]!=item[k] for k in ('source','source_revision','translation_revision')):
                raise ValueError('Source/translation changed; recovery cannot overwrite')
        # Reuse native normalization, language checks, revision history and
        # api_text_versions with the existing source attempt. This transition
        # is inside the outer recovery transaction, never a dispatch claim.
        store.db.execute("UPDATE batches SET state='inflight' WHERE id=?",(batch_id,))
        diagnostics={**parsed.diagnostics,'recovery':True,'source_attempt_id':attempt_id,'raw_response_sha256':raw_hash,'http_sent_in_this_job':False}
        accepted=store.finish_batch(batch_id,parsed.values,diagnostics=diagnostics,expected_attempt_id=attempt_id)
        if set(accepted)!=set(ids) or store.batch(batch_id)['state']!='done':
            raise ValueError('Native validation rejected recovery; transaction rolled back')
        after=[store.line(id) for id in ids]
        if any(r['translation']!=parsed.values[r['id']].strip() for r in after):raise ValueError('Recovery altered text unexpectedly')
        event=dict(id=str(uuid4()),campaign=campaign,document_id=job['document_id'],batch_id=batch_id,source_attempt_id=attempt_id,
            raw_response_sha256=raw_hash,parser_version=PARSER_VERSION,timestamp=datetime.now(timezone.utc).isoformat(),
            status='recovered',validation=diagnostics,stable_ids=ids,before=before,after=after,
            original_batch_error=batch['error'],original_batch_diagnostics=batch['diagnostics'],new_http_requests=0)
        store.db.execute('INSERT INTO deepseek_recovery_events VALUES (?,?,?,?,?,?,?)',
            (event['id'],campaign,batch_id,attempt_id,raw_hash,PARSER_VERSION,json.dumps(event,ensure_ascii=False)))
        if store.attempts(batch_id)!=attempts:raise ValueError('Recovery must preserve request history')
    store.log.emit('deepseek_response_recovered',provider='deepseek',document_id=job['document_id'],batch_id=batch_id,
        attempt_id=attempt_id,recovery_event_id=event['id'],raw_response_sha256=raw_hash,parser_version=PARSER_VERSION,
        root_metadata=json.dumps(parsed.diagnostics.get('root_metadata',{})),metadata_decision='accepted',line_ids=ids)
    return event
