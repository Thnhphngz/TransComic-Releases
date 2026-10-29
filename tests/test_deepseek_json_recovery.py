"""Offline compatibility/recovery tests. All HTTP is MockTransport."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import httpx
import pytest

import transcomic.deepseek as deepseek
from transcomic.deepseek_json import parse_translation, PARSER_VERSION
from transcomic.deepseek_recovery import recover_response
from transcomic.documents import decode_txt
from transcomic.prompts import PROMPT_VERSION
from transcomic.storage import Store
from transcomic.translation import Scheduler
from transcomic.translation_policy import VERSION,CANDIDATE_VERSION

ROWS=[dict(id='one',text='The girl returned home.'),dict(id='two',text='Her father greeted her.')]


@pytest.mark.parametrize('policy',[VERSION,CANDIDATE_VERSION])
@pytest.mark.parametrize('metadata',[False,True])
def test_only_known_root_metadata_is_compatible(policy,metadata):
    obj={'lines':ROWS}
    if metadata:obj['type']='json_object'
    content=json.dumps(obj);parsed=parse_translation(content,{'one','two'},policy)
    assert not parsed.error and len(parsed.values)==2
    assert parsed.diagnostics['parser_version']==PARSER_VERSION
    assert parsed.diagnostics['raw_content_sha256']==hashlib.sha256(content.encode()).hexdigest()
    if metadata:
        assert parsed.diagnostics['root_metadata']=={'type':'json_object'}
        assert parsed.diagnostics['metadata_decision']=='accepted'


@pytest.mark.parametrize('obj',[
    {'lines':ROWS,'type':'text'}, {'lines':ROWS,'type':None},
    {'lines':ROWS,'type':{'type':'json_object'}}, {'lines':ROWS,'translation':'replacement'},
    {'lines':ROWS,'type':'json_object','output':'replacement'}, {'type':'json_object'},
    {'lines':{}}, {'lines':[ROWS[0],ROWS[0]]}, {'lines':ROWS[:1]},
    {'lines':ROWS+[{'id':'context','text':'Not a target.'}]},
    {'lines':[dict(id='one',text=''),ROWS[1]]},
    {'lines':[dict(id='one',text='\n'),ROWS[1]]},
    {'lines':[dict(id='one',text='Two\rparts'),ROWS[1]]},
    {'lines':[dict(id='one',text='Two\u2028parts'),ROWS[1]]},
    {'lines':[dict(id='one',text=42),ROWS[1]]},
    {'lines':[dict(id='one'),ROWS[1]]},
    {'lines':[dict(id='one',text='Fine.',explanation='extra'),ROWS[1]]},
    {'result':{'lines':ROWS}},
])
def test_invalid_mapping_or_content_rejects_entire_batch(obj):
    parsed=parse_translation(json.dumps(obj),{'one','two'},VERSION)
    assert parsed.error and not parsed.values


@pytest.mark.parametrize('content',[
    '{"lines":[', '```json\n{"lines":[]}\n```',
    '{"lines":[],"type":"text","type":"json_object"}',
    '{"lines":[{"id":"one","text":"A","text":"B"}]}',
    '{"lines":[],"lines":[]}', '{"lines":[],"type":NaN}',
])
def test_malformed_duplicate_json_keys_never_repaired(content):
    parsed=parse_translation(content,{'one','two'},VERSION)
    assert parsed.error and not parsed.values


def test_legacy_policy_stays_strict_and_order_maps_by_id():
    content=json.dumps({'lines':list(reversed(ROWS)),'type':'json_object'})
    assert parse_translation(content,{'one','two'},PROMPT_VERSION).error
    parsed=parse_translation(content,{'one','two'},VERSION)
    assert not parsed.error and parsed.values['one']==ROWS[0]['text']


def test_synthetic_response_fixture_has_exactly_ten_target_results():
    fixture=json.loads((Path(__file__).parent/'fixtures/deepseek_synthetic_root_type.json').read_text(encoding='utf8'))
    parsed=parse_translation(json.dumps(fixture),{f'line-{i}' for i in range(161,171)},VERSION)
    assert not parsed.error and len(parsed.values)==10
    assert parsed.values['line-161'].endswith('"Papa."')
    assert '\n' not in ''.join(parsed.values.values())


def test_provider_logs_metadata_decision_and_raw_hash():
    events=[]
    env={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'lines':ROWS,'type':'json_object'})}}]}
    response=httpx.Response(200,json=env)
    p=deepseek.DeepSeekProvider('fixture',transport=httpx.MockTransport(lambda req:response))
    result=asyncio.run(p.translate([dict(id=r['id'],source='Cô bé trở về nhà') for r in ROWS],'vi','en',observer=lambda event,**data:events.append((event,data))))
    assert not result.error
    event=next(data for event,data in events if event=='schema_metadata')
    assert event['metadata_decision']=='accepted' and json.loads(event['root_metadata'])=={'type':'json_object'}
    assert event['raw_response_sha256']==hashlib.sha256(response.content).hexdigest()


def rejected_job(tmp_path,monkeypatch):
    store=Store(tmp_path/'s.db')
    doc,_=store.import_document(tmp_path/'source.txt',decode_txt(('Clover trở về nhà\n'*30).encode()),'vi','en')
    # Reproduce a historical rejected response for the offline recovery tool.
    job=store.create_job(doc,deepseek.MODEL,'vi','en',1,provider='deepseek',config={'deepseek_batch_size':10,'prompt_version':VERSION,'translation_completion_policy':0})
    captured=[]
    def handle(request):
        rows=json.loads(json.loads(request.content)['messages'][1]['content'])['lines']
        env={'model':deepseek.MODEL,'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'lines':[dict(id=r['id'],text='Clover returned home.') for r in rows],'type':'json_object'})}}]}
        captured.append(dict(http_status=200,line_ids=[r['id'] for r in rows],model=deepseek.MODEL,prompt_version=VERSION,envelope=env))
        return httpx.Response(200,json=env)
    with monkeypatch.context() as old:
        old.setattr(deepseek,'parse_translation',lambda content,ids,policy:parse_translation(content,ids,PROMPT_VERSION))
        s=Scheduler(store,deepseek.DeepSeekProvider('fixture',batch_size=10,transport=httpx.MockTransport(handle)))
        s.start(job);s.join(5);assert not s._thread.is_alive() and s.intervention_reason=='invalid_schema'
    b=store.batches(job)[0];a=store.attempts(b['id'])[0]
    return store,doc,job,b,a,json.dumps(captured[0]).encode()


def recover(store,b,a,raw):
    return recover_response(store,campaign='fixture',batch_id=b['id'],attempt_id=a['id'],raw_response=raw)


def test_recovery_is_native_atomic_idempotent_and_resume_never_sends_recovered(tmp_path,monkeypatch):
    store,doc,job,b,a,raw=rejected_job(tmp_path,monkeypatch)
    try:
        before=deepcopy(store.attempts(b['id']));event=recover(store,b,a,raw)
        assert len(event['stable_ids'])==10 and event['new_http_requests']==0
        assert event['raw_response_sha256']==hashlib.sha256(raw).hexdigest()
        assert event['source_attempt_id']==a['id'] and event['parser_version']==PARSER_VERSION
        assert store.attempts(b['id'])==before and before[0]['diagnostics']['failure_kind']=='invalid_schema'
        assert store.batch(b['id'])['state']=='done'
        assert store.db.execute('SELECT COUNT(*) FROM api_text_versions WHERE accepted=1').fetchone()[0]==10
        edits=store.db.execute('SELECT COUNT(*) FROM line_edits').fetchone()[0]
        assert recover(store,b,a,raw)==event
        assert store.db.execute('SELECT COUNT(*) FROM line_edits').fetchone()[0]==edits
        sent=[]
        def handle(request):
            rows=json.loads(json.loads(request.content)['messages'][1]['content'])['lines'];sent.extend(r['id'] for r in rows)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'lines':[dict(id=r['id'],text='The girl walked home.') for r in rows],'type':'json_object'})}}]})
        s=Scheduler(store,deepseek.DeepSeekProvider('fixture',batch_size=10,transport=httpx.MockTransport(handle)))
        s.start(job);s.join(5);assert not s._thread.is_alive() and not s.intervention_reason
        assert len(sent)==20 and not set(sent).intersection(event['stable_ids'])
        assert len(store.jobs())==1 and all(r['state']=='done' for r in store.lines(doc))
        assert all(store.attempts(batch['id'])[0]['attempt_number']==1 for batch in store.batches(job))
        assert store.job(job)['prompt_version']==VERSION
        # A later source-grounded manual review must also beat recovery replay.
        reviewed=event['stable_ids'][0]
        store.edit_line(reviewed,'translation','A reviewed manual correction.')
        with pytest.raises(ValueError,match='changed'):recover(store,b,a,raw)
        assert store.line(reviewed)['translation']=='A reviewed manual correction.'
        assert store.db.execute('SELECT COUNT(*) FROM deepseek_recovery_events').fetchone()[0]==1
    finally:store.close()


@pytest.mark.parametrize('failure',['write','language','changed_source','manual_edit','bad_ids'])
def test_recovery_failure_preserves_rows_batch_and_original_attempt(tmp_path,monkeypatch,failure):
    store,doc,job,b,a,raw=rejected_job(tmp_path,monkeypatch)
    try:
        if failure=='changed_source':store.edit_line(b['payload'][0]['id'],'source','Nguồn đã sửa')
        if failure=='manual_edit':store.edit_line(b['payload'][0]['id'],'translation','A manual edit wins.')
        if failure=='bad_ids':
            obj=json.loads(raw);obj['line_ids'][0]='foreign';raw=json.dumps(obj).encode()
        if failure=='language':
            obj=json.loads(raw);body=json.loads(obj['envelope']['choices'][0]['message']['content'])
            for r in body['lines']:r['text']='Cô bé trở về nhà với cha của mình và nói rằng cô rất vui khi được gặp lại mọi người trong gia đình.'
            obj['envelope']['choices'][0]['message']['content']=json.dumps(body);raw=json.dumps(obj).encode()
        if failure=='write':
            original=store.finish_batch
            def fail(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('disk fixture')
            monkeypatch.setattr(store,'finish_batch',fail)
        rows=store.lines(doc);batch=store.batch(b['id']);attempts=store.attempts(b['id'])
        with pytest.raises((ValueError,RuntimeError)):recover(store,b,a,raw)
        assert store.lines(doc)==rows and store.batch(b['id'])==batch and store.attempts(b['id'])==attempts
        assert not store.db.execute("SELECT 1 FROM sqlite_master WHERE name='deepseek_recovery_events'").fetchone()
    finally:store.close()
