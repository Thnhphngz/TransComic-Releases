import json
from pathlib import Path
import pytest
import httpx
from docx import Document
from transcomic.language_validator import *
from transcomic.storage import Store
from transcomic.bulk import import_many, plan_exports, write_exports
from transcomic.documents import decode_txt
from transcomic.translation import Scheduler
from transcomic.providers import KiraProvider

SOURCE='cael vội buông nó ra, ta tưởng em là kẻ đột nhập'
GOOD='Cael quickly let go of her, I thought you were an intruder'

@pytest.mark.parametrize('target,conclusion',[
    (GOOD,VALID),(SOURCE,WRONG_LANGUAGE_CONFIRMED),
    (SOURCE.replace('cael','Cael!'),WRONG_LANGUAGE_CONFIRMED),
    ('Cael let go, ta tưởng em là kẻ đột nhập',WRONG_LANGUAGE_CONFIRMED),
    ('I thought you were an intruder, cael vội buông nó ra, ta tưởng em là kẻ đột nhập, he said',WRONG_LANGUAGE_CONFIRMED),
    ('cael voi buong no ra, ta tuong em la ke dot nhap',WRONG_LANGUAGE_CONFIRMED),
    ('Cael',INSUFFICIENT_EVIDENCE),('OK',INSUFFICIENT_EVIDENCE),
    ('123',INSUFFICIENT_EVIDENCE),('!?',INSUFFICIENT_EVIDENCE),
    ('{hero} https://example.com/tech.v1',INSUFFICIENT_EVIDENCE),
    ('Evelyn walked to Cael and Karine',VALID),
])
def test_validator(target,conclusion):
    assert validator.validate(SOURCE,target,'vi','en','id').conclusion==conclusion

def test_intentionally_retained_and_ambiguous():
    assert validator.validate('Cael Evelyn Karine','Cael Evelyn Karine','vi','en').conclusion==INSUFFICIENT_EVIDENCE
    assert validator.validate('radio video hotel taxi','radio video hotel taxi','vi','en').conclusion!=WRONG_LANGUAGE_CONFIRMED
    assert validator.validate(SOURCE,'He read '+SOURCE+' on the sign','vi','en',context={'preserve_terms':[SOURCE]}).conclusion!=WRONG_LANGUAGE_CONFIRMED
    assert validator.validate('anh nói không','he said anh nói không','vi','en').conclusion==SUSPECTED_WRONG_LANGUAGE

def setup(tmp_path):
    store=Store(tmp_path/'test.db')
    doc,_=store.import_document(tmp_path/'input.txt',decode_txt(('\n'.join([SOURCE]*3)).encode()),'vi','en')
    job=store.create_job(doc,'mock','vi','en',3)
    return store,doc,job

@pytest.mark.parametrize('failures',[1,5,6])
def test_partial_retry_and_shared_attempt_limit(tmp_path,failures):
    store,doc,job=setup(tmp_path);calls=[]
    def handle(request):
        body=json.loads(request.content);rows=json.loads(body['messages'][1]['content'])['lines'];calls.append(rows)
        if len(calls)>1:
            assert len(rows)==1 and 'previous response contained' in body['messages'][0]['content']
        values=[{'id':r['id'],'text':SOURCE if (len(calls)<=failures and (len(rows)==1 or i==1)) else GOOD} for i,r in enumerate(rows)]
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':values})}}]})
    scheduler=Scheduler(store,KiraProvider('fake',transport=httpx.MockTransport(handle)))
    scheduler.start(job);scheduler.join(5)
    assert not scheduler._thread.is_alive()
    assert len(calls)==min(6,failures+1)
    rows=store.lines(doc)
    assert rows[0]['translation']==GOOD and rows[2]['translation']==GOOD
    assert rows[1]['state']==('done' if failures<6 else 'wrong_target_language')
    assert store.prepare_attempt(store.batches(job)[0]['id'],7) is None
    attempts=store.attempts(store.batches(job)[0]['id'])
    assert attempts[0]['diagnostics']['failure_kind']=='wrong_target_language'
    events=store.log.snapshot()
    assert any(e['event']=='language_checked' for e in events)
    assert SOURCE not in json.dumps(events)
    store.close()

def test_manual_late_result_and_existing_good_preserved(tmp_path):
    store,doc,job=setup(tmp_path);batch=store.batches(job)[0]
    store.job_state(job,'running');store.claim_batch(batch['id']);attempt=store.prepare_attempt(batch['id'],1)
    first=batch['payload'][0]['id'];store.edit_line(first,'translation',GOOD)
    diagnostics={};store.finish_batch(batch['id'],{r['id']:SOURCE for r in batch['payload']},diagnostics=diagnostics,expected_attempt_id=attempt)
    store.complete_attempt(attempt,diagnostics)
    assert store.line(first)['translation']==GOOD and store.line(first)['attempt_kind']=='manual'
    second=store.lines(doc)[1];store.edit_line(second['id'],'translation',SOURCE)
    store.validate_document_language(doc)
    assert store.line(second['id'])['state']=='wrong_target_language'
    next_attempt=store.prepare_attempt(batch['id'],2)
    assert next_attempt
    assert second['id'] not in [r['id'] for r in store.batch(batch['id'])['payload']]
    store.close()

@pytest.mark.parametrize('extension',['txt','docx'])
@pytest.mark.parametrize('mode',['direct','transcomic','custom'])
@pytest.mark.parametrize('fallback',[False,True])
def test_export_guard_actual_text_preserves_existing_and_other_files(tmp_path,extension,mode,fallback):
    store=Store(tmp_path/'test.db');docs=[]
    for i in range(2):
        file=tmp_path/f'{i}.{extension}'
        if extension=='txt':file.write_text(SOURCE,encoding='utf-8')
        else:
            d=Document();d.add_paragraph(SOURCE);d.save(file)
        doc=import_many(store,[file],'vi','en')['document_ids'][0];docs.append(doc)
        if not fallback or i==1:
            store.edit_line(store.lines(doc)[0]['id'],'translation',SOURCE if i==0 else GOOD)
    # Deliberately old misleading success state must never bypass guard.
    with store.transaction(): store.db.execute("UPDATE lines SET state='done'")
    plan=plan_exports(store.export_snapshot(docs),tmp_path/'exports',mode=mode)
    bad=next(p for p in plan if p['document']['id']==docs[0]);bad['target'].parent.mkdir(parents=True,exist_ok=True);bad['target'].write_bytes(b'previous export')
    results=write_exports(store,plan,existing='overwrite',allow_incomplete=True)
    assert next(r for r in results if r['document_id']==docs[0])['state']=='blocked_language'
    assert bad['target'].read_bytes()==b'previous export'
    assert next(r for r in results if r['document_id']==docs[1])['state']=='exported'
    store.close()

def test_history_local_recheck_edit_clear_and_resume_budget(tmp_path):
    store,doc,job=setup(tmp_path);batch=store.batches(job)[0]
    store.job_state(job,'running');store.claim_batch(batch['id']);attempt=store.prepare_attempt(batch['id'],1)
    # Emulate pre-validator historical success with original unchanged revisions.
    with store.transaction():
        store.db.execute("UPDATE lines SET translation=?,translation_revision=1,translation_source_revision=source_revision,state='done'",(SOURCE,))
        store.db.execute("UPDATE batches SET state='done' WHERE id=?",(batch['id'],))
    store.complete_attempt(attempt,{'http_status':200});store.job_state(job,'finished')
    store.validate_document_language(doc)
    assert all(r['translation']==SOURCE for r in store.lines(doc))
    assert len(store.attempts(batch['id']))==1
    assert Scheduler.has_work(store,job)
    assert all(r['translation_revision']==1 for r in store.batch(batch['id'])['payload'])
    line=store.lines(doc)[0];store.edit_line(line['id'],'translation',GOOD);store.warning_rows(doc)
    assert store.line(line['id'])['state']=='done'
    store.close()

def test_rejected_new_api_text_keeps_previous_valid_export(tmp_path):
    store,doc,job=setup(tmp_path)
    with store.transaction():
        store.db.execute("UPDATE lines SET translation=?,translation_source_revision=source_revision,state='done'",(GOOD,))
    store.job_state(job,'running');batch=store.batches(job)[0];store.claim_batch(batch['id']);attempt=store.prepare_attempt(batch['id'],1)
    diagnostics={};store.finish_batch(batch['id'],{r['id']:SOURCE for r in batch['payload']},diagnostics=diagnostics,expected_attempt_id=attempt)
    assert all(r['translation']==GOOD for r in store.lines(doc))
    store.warning_rows(doc)
    assert all(r['state']=='wrong_target_language' for r in store.lines(doc))
    plan=plan_exports(store.export_snapshot([doc]),tmp_path/'out',mode='custom')
    assert write_exports(store,plan)[0]['state']=='exported'
    assert SOURCE not in plan[0]['target'].read_text(encoding='utf-8')
    store.close()

def test_suspected_is_saved_warned_and_not_retried(tmp_path):
    store=Store(tmp_path/'state.db');doc,_=store.import_document(tmp_path/'input.txt',decode_txt('anh nói không'.encode()),'vi','en')
    job=store.create_job(doc,'mock','vi','en',1);calls=[]
    def handle(req):
        calls.append(req);row=json.loads(json.loads(req.content)['messages'][1]['content'])['lines'][0]
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':row['id'],'text':'he said anh nói không'}]})}}]})
    s=Scheduler(store,KiraProvider('fake',transport=httpx.MockTransport(handle)));s.start(job);s.join(3)
    assert len(calls)==1 and store.lines(doc)[0]['state']=='done'
    assert any(display_reason('possible_source_fragment') in str(r['warnings']) for r in store.warning_rows(doc))
    store.close()

@pytest.mark.parametrize('target',['id','hi','ja','fr-CA'])
def test_clear_vietnamese_source_copy_other_targets(target):
    assert validator.validate(SOURCE,SOURCE,'vi',target).conclusion==WRONG_LANGUAGE_CONFIRMED

def test_wrong_text_does_not_turn_uncertain_transport_into_retry_or_bypass_barrier(tmp_path):
    from transcomic.providers import BatchResult
    from transcomic.languages import language
    store=Store(tmp_path/'state.db');doc,_=store.import_document(tmp_path/'input.txt',decode_txt(SOURCE.encode()),'vi','en')
    run,jobs=store.create_run([doc],['en','id'],provider='kira',model='mock',source_lang='vi',concurrency=3);calls=[]
    class Fake:
        async def translate(self,rows,source,target):
            calls.append(language(target).locale)
            return BatchResult({r['id']:SOURCE for r in rows},'Network uncertain',True,diagnostics={'failure_kind':'network_error'})
    s=Scheduler(store,Fake());s.start_many(jobs,run);s.join(3)
    assert calls==['en'] and not s._thread.is_alive()
    first=store.job(jobs[0]);assert store.lines(first['document_id'])[0]['state']=='unknown'
    assert not Scheduler.has_work(store,jobs[0])
    assert store.attempts(store.batches(jobs[0])[0]['id'])[0]['diagnostics']['failure_kind']=='network_error'
    store.close()

@pytest.mark.parametrize('cap',[1,30,50])
def test_language_error_shares_global_queue_and_language_barrier(tmp_path,cap):
    import asyncio
    from transcomic.providers import BatchResult
    from transcomic.languages import language
    store=Store(tmp_path/'state.db')
    docs=[store.import_document(tmp_path/f'{n}.txt',decode_txt(('\n'.join([SOURCE]*9)).encode()),'vi','en')[0] for n in range(3)]
    run,jobs=store.create_run(docs,['en','id'],provider='kira',model='mock',source_lang='vi',concurrency=cap)
    active=peak=0;seen=set();calls=[]
    class Fake:
        async def translate(self,rows,source,target):
            nonlocal active,peak
            locale=language(target).locale
            assert not active or calls[-1]==locale
            active+=1;peak=max(peak,active);calls.append(locale);await asyncio.sleep(.005);active-=1
            bad=locale=='en' and rows[0]['id'] not in seen
            seen.update(r['id'] for r in rows)
            return BatchResult({r['id']:SOURCE if bad and i==0 else GOOD for i,r in enumerate(rows)})
    s=Scheduler(store,Fake());s.start_many(jobs,run);s.join(10)
    assert not s._thread.is_alive() and peak<=cap<=50
    assert list(dict.fromkeys(calls))==['en','id']
    assert all(r['state']=='done' for j in jobs for r in store.lines(store.job(j)['document_id']))
    assert sum(a['attempt_number']>1 for j in jobs for b in store.batches(j) for a in store.attempts(b['id']))==9
    store.close()

def test_real_old_three_paragraph_fixture():
    from transcomic.docx_document import import_docx
    source=Path('D:/word 50 cach/17-18.docx');target=source.parent/'TransComic/English/17-18_EN.docx'
    if not target.exists():pytest.skip('User historical DOCX not available')
    s,t=import_docx(source),import_docx(target)
    assert len(s.units)==len(t.units)
    bad=[i+1 for i,(a,b) in enumerate(zip(s.units,t.units)) if validator.validate(a.text,b.text,'vi','en').conclusion==WRONG_LANGUAGE_CONFIRMED]
    assert bad==[67,68,69]
