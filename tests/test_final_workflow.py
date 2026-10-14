import asyncio
import json
import time
import sqlite3
from pathlib import Path
import httpx
import pytest
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.providers import KiraProvider
from transcomic.translation import Scheduler
from transcomic.postprocess import normalize
from transcomic.bulk import plan_exports, write_exports
from transcomic.workspace_retry import retry_plan, WorkspaceRetryScheduler


def setup(tmp_path, lines=3, concurrency=1, retries=3, max_requests=None):
    store = Store(tmp_path/'state.db'); store.set_setting('auto_retries', str(retries))
    source = tmp_path/'chapter.txt'; source.write_text('\n'.join('Source '+str(i) for i in range(lines)))
    doc, _ = store.import_document(source, decode_txt(source.read_bytes()), 'VI', 'Tiếng Anh')
    job = store.create_job(doc, 'model', 'VI', 'Tiếng Anh', concurrency, max_requests=max_requests)
    return store, doc, job


def body(request): return json.loads(json.loads(request.content)['messages'][1]['content'])['lines']
def success(lines):
    return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps({'lines': [{'id': r['id'], 'text': 'Mr.P arrived. Then left.'} for r in lines]})}}]})


@pytest.mark.parametrize('retries', [0, 1, 2, 3, 4, 5])
def test_frozen_retry_limit_and_partial_success(tmp_path, retries):
    store, doc, job = setup(tmp_path, retries=retries)
    store.set_setting('auto_retries', '0' if retries else '3')
    sent = []
    def handler(req):
        rows = body(req); sent.append([r['id'] for r in rows])
        return success(rows[:1]) if len(sent)==1 else httpx.Response(200, json={'choices': [{'message': {'content': 'bad'}}]})
    scheduler = Scheduler(store, KiraProvider('fake', transport=httpx.MockTransport(handler)))
    scheduler.start(job); scheduler.join(5)
    assert not scheduler._thread.is_alive()
    batch = store.batches(job)[0]
    assert len(sent) == 1+retries
    assert [a['attempt_number'] for a in store.attempts(batch['id'])] == list(range(1, 2+retries))
    assert all(sent[0][0] not in ids for ids in sent[1:])
    assert store.lines(doc)[0]['translation'] == 'Mr P arrived, Then left'
    assert store.lines(doc)[0]['source'] == 'Source 0'
    trace = store.db.execute('SELECT * FROM api_text_versions').fetchone()
    assert trace['raw_text'] == 'Mr.P arrived. Then left.' and trace['accepted']==1
    assert store.prepare_attempt(batch['id'], 7) is None
    store.close()


@pytest.mark.parametrize('error', ['timeout', 'network', '401', '403', '504'])
def test_uncertain_and_auth_do_not_gain_three_retries(tmp_path, error):
    store, doc, job = setup(tmp_path); calls = []
    def handler(req):
        calls.append(req)
        if error=='timeout': raise httpx.ReadTimeout('private', request=req)
        if error=='network': raise httpx.ConnectError('private', request=req)
        return httpx.Response(int(error), json={})
    scheduler = Scheduler(store, KiraProvider('fake', transport=httpx.MockTransport(handler)))
    scheduler.start(job); scheduler.join(5)
    assert len(calls)==(4 if error=='504' else 1)
    store.close()


def test_shared_cooldown_recovery_single_effective_worker(tmp_path):
    store, doc, job = setup(tmp_path, lines=90, concurrency=50)
    sent = []; active = peak = 0; limited = set()
    async def handler(req):
        nonlocal active, peak
        rows=body(req); started=time.monotonic(); sent.append((started, rows[0]['id']))
        active+=1; peak=max(peak, active); await asyncio.sleep(.02); active-=1
        if not limited:
            limited.add(rows[0]['id'])
            return httpx.Response(429, headers={'Retry-After': '.15', 'X-RateLimit-Remaining': '0'}, json={'error': {'code': 'rate_limit'}})
        return success(rows)
    scheduler = Scheduler(store, KiraProvider('fake', transport=httpx.MockTransport(handler)))
    scheduler.start(job); scheduler.join(8)
    assert not scheduler._thread.is_alive()
    assert peak<=50 and scheduler.effective_concurrency==1
    assert scheduler.rate_limits==scheduler.retry_count==1
    assert len(sent)==31 and all(r['state']=='done' for r in store.lines(doc))
    assert sent[-1][0]-sent[0][0]>=.15
    event=next(e for e in store.log.snapshot() if e['event']=='cooldown')
    assert event['retry_after_seconds']==.15 and event['rate_limit_headers']['x-ratelimit-remaining']=='0'
    store.close()


@pytest.mark.parametrize('envelope,headers', [({'error': {'code': 'insufficient_quota'}}, {'Retry-After': '.01'}), ({}, {})])
def test_unknown_reset_or_exhaustion_pauses_without_hammering(tmp_path, envelope, headers):
    store, doc, job = setup(tmp_path, lines=30, concurrency=3); calls=[]
    async def handler(req):
        calls.append(req); await asyncio.sleep(.01)
        return httpx.Response(429, headers=headers, json=envelope)
    scheduler=Scheduler(store, KiraProvider('fake', transport=httpx.MockTransport(handler)))
    scheduler.start(job); time.sleep(.12)
    assert not scheduler._paused.is_set() and len(calls)<=3
    assert scheduler.intervention_reason if envelope else scheduler.cooldown_until > time.monotonic()
    count=len(calls); time.sleep(.12); assert len(calls)==count
    scheduler.stop(); scheduler.join(5); assert not scheduler._thread.is_alive()
    store.close()


def test_request_budget_blocks_additional_retry(tmp_path):
    store, doc, job=setup(tmp_path, max_requests=2); calls=[]
    def handler(req):
        calls.append(req); return httpx.Response(200, json={})
    scheduler=Scheduler(store, KiraProvider('fake', transport=httpx.MockTransport(handler)))
    scheduler.start(job); scheduler.join(5)
    assert len(calls)==2
    assert len(store.attempts(store.batches(job)[0]['id']))==2
    store.close()


@pytest.mark.parametrize('raw,expected', [
    ('Mr. P met Mrs. Florence. Then mr.p left.', 'Mr P met Mrs Florence, Then mr p left'),
    ('Ia datang. Lalu pergi.', 'Ia datang, Lalu pergi'),
    ('Đến rồi. Sau đó đi.', 'Đến rồi, Sau đó đi'),
    ('Value 3.14. See https://a.b/c.', 'Value 3 14, See https://a.b/c'),
    ('{{user.name}} met <tag.id> Mr.P.', '{{user.name}} met <tag.id> Mr P'),
])
def test_normalization_idempotent_and_protected(raw, expected):
    processed, notes=normalize(raw, raw)
    assert processed==expected
    assert normalize(raw, processed)[0]==processed
    if '{{' in raw: assert any('conflicts' in n for n in notes)


def test_quote_warning_preserves_names_clauses_and_quotes():
    source='emily whispered, karine thought, evelyn replied'
    raw='Emily whispered, "Hello." Karine thought, I heard you. Evelyn replied, "Stay."'
    processed, notes=normalize(source, raw)
    assert '.' not in processed
    assert all(name in processed for name in ('Emily','Karine','Evelyn'))
    assert processed.count('"')==4
    assert any('quotation' in n for n in notes)
    assert not any('quotation' in n for n in normalize('"Hello"', '"Hello"')[1])


@pytest.mark.parametrize('mode', ['direct','transcomic','custom'])
def test_three_modes_atomic_collisions_and_source_unchanged(tmp_path, mode):
    store, doc, job=setup(tmp_path)
    store.job_state(job, 'stopped')
    for r in store.lines(doc): store.edit_line(r['id'],'translation','Manual.period.')
    source=Path(store.document(doc)['path']); original=source.read_bytes()
    snapshot=store.export_snapshot([doc]); root=tmp_path/'custom' if mode=='custom' else None
    plan=plan_exports(snapshot, root, mode=mode); target=plan[0]['target']
    assert target.parent==(source.parent if mode=='direct' else source.parent/'TransComic'/'English' if mode=='transcomic' else root)
    assert write_exports(store,plan)[0]['state']=='exported'
    assert target.read_text()=='\n'.join(['Manual.period.']*3)
    assert write_exports(store,plan)[0]['state']=='cancelled'
    assert Path(write_exports(store,plan,existing='version')[0]['path'])!=target
    assert source.read_bytes()==original
    if mode=='direct': assert not (source.parent/'TransComic').exists()
    source.unlink()
    if mode!='custom':
        with pytest.raises(ValueError): plan_exports(snapshot,mode=mode)
    store.close()


def test_workspace_scope_three_files_two_languages_and_hidden_history(tmp_path):
    store=Store(tmp_path/'w.db'); ids=[]
    for n in range(4):
        source=tmp_path/f'{n}.txt'; source.write_text('one\ntwo\nthree')
        doc,_=store.import_document(source,decode_txt(source.read_bytes()),'VI','Tiếng Anh')
        for lang in ('Tiếng Anh','Tiếng Indonesia'):
            target=store.workspace_for_target(doc,lang)
            job=store.create_job(target,'model','VI',lang,50)
            batch=store.batches(job)[0]; store.claim_batch(batch['id']); store.finish_batch(batch['id'],{},'failed'); store.job_state(job,'finished')
            if n<3: ids.append(target)
    plan=retry_plan(store,ids)
    assert len(plan)==6 and sum(len(g['line_ids']) for g in plan)==18
    assert len(retry_plan(store,[]))==0
    jobs=[]; calls=[]
    for g in plan:
        j=g['original']; jobs.append(store.create_job(j['document_id'],'model','VI',j['target_lang'],50,g['line_ids']))
    async def handler(req): calls.append(body(req)); await asyncio.sleep(.01); return success(body(req))
    adapter=KiraProvider('fake',transport=httpx.MockTransport(handler))
    scheduler=WorkspaceRetryScheduler(store,[jobs],{j:adapter for j in jobs},lambda ids:None)
    scheduler.start(); scheduler.join(5)
    assert not scheduler._thread.is_alive() and len(calls)==6
    assert not retry_plan(store,ids)
    assert sum(r['state']=='error' for d in store.documents() if d['id'] not in ids for r in store.lines(d['id']))==6
    store.close()


def test_fifty_simultaneous_429_share_cooldown_without_retry_storm(tmp_path):
    store, doc, job=setup(tmp_path, lines=150, concurrency=50)
    calls={}; starts=[]; rejects=[]; recovery=[]; active=peak_recovery=0
    async def handler(req):
        nonlocal active, peak_recovery
        rows=body(req); key=rows[0]['id']; calls[key]=calls.get(key,0)+1
        starts.append((time.monotonic(),calls[key])); active+=1
        if calls[key]>1:
            peak_recovery=max(peak_recovery,active)
            recovery.append((active,scheduler.effective_concurrency))
        await asyncio.sleep(.01); active-=1
        if calls[key]==1:
            rejects.append(time.monotonic())
            return httpx.Response(429, headers={'Retry-After': '.08'}, json={})
        return success(rows)
    scheduler=Scheduler(store,KiraProvider('fake',transport=httpx.MockTransport(handler)))
    scheduler.start(job); scheduler.join(12)
    assert not scheduler._thread.is_alive()
    assert len(calls)==50 and all(n==2 for n in calls.values())
    assert recovery[0]==(1,1)  # First probe is serial; later successful probes may restore capacity.
    assert all(1<=active<=cap<=50 for active,cap in recovery)
    assert peak_recovery<=scheduler.effective_concurrency<=50
    assert min(t for t,n in starts if n>1)>=max(rejects)+.075
    assert all(r['state']=='done' for r in store.lines(doc))
    store.close()


def test_new_parser_retry_cannot_overwrite_manual_edit(tmp_path):
    store,doc,job=setup(tmp_path); calls=[]
    def handler(req):
        rows=body(req); calls.append(rows)
        if len(calls)==1:
            store.edit_line(rows[1]['id'],'translation','User.period.')
            return success(rows[:1])
        return success(rows)
    scheduler=Scheduler(store,KiraProvider('fake',transport=httpx.MockTransport(handler)))
    scheduler.start(job); scheduler.join(5)
    assert len(calls)==2 and len(calls[1])==1
    assert store.lines(doc)[1]['translation']=='User.period.'
    store.close()


def test_crash_after_reserved_retry_is_not_replayed(tmp_path):
    store,doc,job=setup(tmp_path); store.job_state(job,'running')
    batch=store.batches(job)[0]; store.claim_batch(batch['id'])
    attempt=store.prepare_attempt(batch['id'],1)
    diag={'http_status':200,'failure_kind':'invalid_line_response'}
    store.finish_batch(batch['id'],{},'invalid',diagnostics=diag,expected_attempt_id=attempt); store.complete_attempt(attempt,diag)
    assert store.prepare_attempt(batch['id'],2)
    store.close(); reopened=Store(tmp_path/'state.db')
    assert reopened.job(job)['state']=='interrupted'
    assert reopened.prepare_attempt(batch['id'],3) is None
    assert reopened.attempts(batch['id'])[-1]['state']=='unknown'
    assert all(r['state']=='unknown' for r in reopened.lines(doc))
    reopened.close()


def test_native_controls_remove_all_and_confirmation_preserves_history(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication,QMessageBox
    from transcomic.ui.main import MainWindow
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    store,doc,job=setup(tmp_path); store.job_state(job,'stopped')
    w=MainWindow(store); w.workspace_ids=[doc]; w.open_document(doc); w.show(); w.resize(900,580); app.processEvents()
    assert w.width()==900 and not w.notice.isVisible()
    assert w.file_actions.indexOf(w.folder_button)>=0
    assert w.folder_button.geometry().right()<w.editor_page.width()
    assert w.auto_retry_combo.currentIndex()==3
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.No)
    w.remove_all_workspace(); assert w.workspace_ids==[doc]
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    w.remove_all_workspace()
    assert not w.workspace_ids and w.doc_id is None and w.model.rowCount()==0
    assert store.document(doc) and store.job(job) and Path(store.document(doc)['path']).is_file()
    w.close()


def test_export_cannot_overwrite_another_workspace_source(tmp_path):
    store,doc,job=setup(tmp_path)
    second=tmp_path/'chapter_EN_INCOMPLETE.txt'; second.write_text('protected')
    other,_=store.import_document(second,decode_txt(second.read_bytes()),'VI','Tiếng Anh')
    with pytest.raises(ValueError): plan_exports(store.export_snapshot([doc,other]),mode='direct')
    assert second.read_text()=='protected'
    store.close()


def test_v6_attempt_migration_keeps_reserved_requests_and_keys(tmp_path):
    store,doc,job=setup(tmp_path); store.job_state(job,'running')
    batch=store.batches(job)[0]; store.claim_batch(batch['id']); reserved=store.prepare_attempt(batch['id'],1)
    store.save_key(b'encrypted-key'); store.close()
    db=sqlite3.connect(tmp_path/'state.db')
    db.execute('CREATE TABLE old_attempts (id TEXT PRIMARY KEY, original_batch_id TEXT NOT NULL REFERENCES batches(id), attempt_number INTEGER NOT NULL CHECK(attempt_number IN (1,2)), state TEXT NOT NULL, created_at TEXT NOT NULL, completed_at TEXT, diagnostics TEXT, UNIQUE(original_batch_id,attempt_number))')
    db.execute('INSERT INTO old_attempts SELECT * FROM request_attempts'); db.execute('DROP TABLE request_attempts'); db.execute('ALTER TABLE old_attempts RENAME TO request_attempts')
    db.execute('ALTER TABLE jobs DROP COLUMN auto_retries'); db.commit(); db.close()
    reopened=Store(tmp_path/'state.db')
    assert reopened.attempts(batch['id'])[0]['id']==reserved
    assert reopened.attempts(batch['id'])[0]['state']=='unknown'
    assert reopened.job(job)['auto_retries']==0
    assert reopened.load_key()==b'encrypted-key'
    assert not list(reopened.db.execute('PRAGMA foreign_key_check'))
    reopened.close()


def test_gemini_retry_after_keeps_same_key_and_normalizes(tmp_path):
    from transcomic.gemini import GeminiProvider
    store,doc,old=setup(tmp_path); store.job_state(old,'stopped')
    job=store.create_job(doc,'gemini-test','VI','Tiếng Anh',3,provider='gemini')
    calls=[]
    def handler(req):
        calls.append(req)
        if len(calls)==1: return httpx.Response(429,headers={'Retry-After':'.02'},json={'error':{}})
        payload=json.loads(json.loads(req.content)['contents'][0]['parts'][0]['text'])
        return httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':json.dumps({'lines':[{'id':r['id'],'text':'Mrs. Florence arrived.'} for r in payload['lines']]})}]}}]})
    provider=GeminiProvider([{'id':'key','secret':'fake','project':'p'}],'gemini-test',transport=httpx.MockTransport(handler))
    scheduler=Scheduler(store,provider); scheduler.start(job); scheduler.join(5)
    assert not scheduler._thread.is_alive() and len(calls)==2
    assert all(r.headers['x-goog-api-key']=='fake' for r in calls)
    assert all(r['translation']=='Mrs Florence arrived' for r in store.lines(doc))
    store.close()


def test_multiple_providers_are_separate_and_bounded(tmp_path):
    store=Store(tmp_path/'multi.db'); groups=[]; adapters={}; peak={}; active={}; calls=[]
    for provider,limit in [('kira',50),('gemini',30)]:
        ids=[]
        for n in range(3):
            source=tmp_path/f'{provider}{n}.txt'; source.write_text('\n'.join('source'+str(i) for i in range(60)))
            doc,_=store.import_document(source,decode_txt(source.read_bytes()),'VI','Tiếng Anh')
            job=store.create_job(doc,provider+'-model','VI','Tiếng Anh',limit,provider=provider); ids.append(job)
            async def handler(req,scope=provider):
                active[scope]=active.get(scope,0)+1; peak[scope]=max(peak.get(scope,0),active[scope])
                calls.append(scope); await asyncio.sleep(.01); active[scope]-=1
                return success(body(req))
            adapters[job]=KiraProvider('fake',transport=httpx.MockTransport(handler))
        groups.append(ids)
    scheduler=WorkspaceRetryScheduler(store,groups,adapters,lambda ids:None)
    scheduler.start(); scheduler.join(10)
    assert not scheduler._thread.is_alive()
    assert calls.count('kira')==calls.count('gemini')==60
    assert peak['kira']<=50 and peak['gemini']<=30
    assert all(store.job(j)['provider']==p for p,g in zip(['kira','gemini'],groups) for j in g)
    store.close()


def test_timecodes_quotes_and_urls_in_docx_metadata_are_protected(tmp_path):
    import zipfile
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from transcomic.bulk import import_many
    from transcomic.docx_document import import_docx
    raw='At 00:00:01.500 {{user.name}} said "Hello." Then left.'
    text,notes=normalize(raw,raw)
    assert '00:00:01.500' in text and '{{user.name}}' in text and '"Hello", Then left' in text
    assert any('conflicts' in n for n in notes)
    source=tmp_path/'hyper.docx'; document=Document(); paragraph=document.add_paragraph('Mr.P arrived.')
    rel=paragraph.part.relate_to('https://example.com/a.b','http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink',is_external=True)
    # Relationship metadata is copied byte-for-byte. Inline hyperlink text remains
    # unsupported by the existing conservative importer (covered by DOCX tests).
    document.save(source); before=source.read_bytes()
    store=Store(tmp_path/'docx.db'); doc=import_many(store,[source],'VI','Tiếng Anh')['document_ids'][0]
    job=store.create_job(doc,'model','VI','Tiếng Anh',1)
    scheduler=Scheduler(store,KiraProvider('fake',transport=httpx.MockTransport(lambda req:success(body(req)))))
    scheduler.start(job); scheduler.join(5)
    result=write_exports(store,plan_exports(store.export_snapshot([doc]),mode='direct'))[0]
    assert result['state']=='exported' and source.read_bytes()==before
    with zipfile.ZipFile(result['path']) as exported,zipfile.ZipFile(source) as original:
        assert exported.read('word/_rels/document.xml.rels')==original.read('word/_rels/document.xml.rels')
    assert len(import_docx(result['path']).units)==len(import_docx(source).units)
    store.close()


def test_explicit_history_deletion_cleans_new_trace_foreign_keys(tmp_path):
    store,doc,job=setup(tmp_path)
    scheduler=Scheduler(store,KiraProvider('fake',transport=httpx.MockTransport(lambda req:success(body(req)))))
    scheduler.start(job); scheduler.join(5)
    assert store.db.execute('SELECT COUNT(*) FROM api_text_versions').fetchone()[0]==3
    store.delete_history([job])
    assert not store.documents() and not list(store.db.execute('PRAGMA foreign_key_check'))
    store.close()


def test_exact_emily_fixture_preserves_all_raw_words_and_flags_unfounded_quotes():
    import re
    from transcomic.prompts import messages
    case=json.loads((Path(__file__).parent/'fixtures'/'emily_review.json').read_text(encoding='utf-8'))
    result,notes=normalize(case['source'],case['raw'])
    assert '.' not in result
    assert re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?",result)==re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?",case['raw'])
    assert all(name in result for name in ['Emily','Karine','Evelyn'])
    assert any('quotation' in n for n in notes) and any('segments' in n for n in notes)
    prompt=messages([{'id':'original-line-id','source':case['source'],'context':[{'id':'context-id','source':'reference only'}]}],'VI','EN')
    assert 'Do not add quotation marks' in prompt[0]['content']
    assert json.loads(prompt[1]['content'])['lines']==[{'id':'original-line-id','text':case['source']}]
    assert len(result.splitlines())==1


def test_remove_all_while_paused_new_import_does_not_receive_old_results(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication,QMessageBox
    from transcomic.ui.main import MainWindow
    monkeypatch.setenv('QT_QPA_PLATFORM','offscreen')
    app=QApplication.instance() or QApplication([])
    store=Store(tmp_path/'paused.db'); w=MainWindow(store); documents=[]
    for n in range(2):
        file=tmp_path/f'{n}.txt'; file.write_text('one\ntwo\nthree\nfour\nfive\nsix')
        documents.append(store.import_document(file,decode_txt(file.read_bytes()),'VI','Tiếng Anh')[0])
    run,jobs=store.create_run(documents,['Tiếng Anh','Tiếng Indonesia'],provider='kira',model='mock',source_lang='VI',concurrency=3)
    w.workspace_ids=[store.job(j)['document_id'] for j in jobs]; w.open_document(w.workspace_ids[0])
    calls=[]
    async def handler(req): calls.append(req); await asyncio.sleep(.08); return success(body(req))
    adapter=KiraProvider('fake',transport=httpx.MockTransport(handler))
    w.scheduler=WorkspaceRetryScheduler(store,[jobs],{j:adapter for j in jobs},w.bridge.changed.emit)
    w.scheduler.start(); deadline=time.monotonic()+3
    while len(calls)<3 and time.monotonic()<deadline: app.processEvents(); time.sleep(.005)
    assert len(calls)==3
    w.scheduler.pause(); old_ids=list(w.workspace_ids)
    monkeypatch.setattr(QMessageBox,'question',lambda *a:QMessageBox.Yes)
    w.remove_all_workspace(); assert w.doc_id is None and not w.workspace_ids
    new,_=store.import_document(tmp_path/'new.txt',decode_txt(b'new source'),'VI','Tiếng Anh')
    w.workspace_ids=[new]; w.open_document(new)
    time.sleep(.15); assert len(calls)==3
    w.scheduler.resume(); w.scheduler.join(5); app.processEvents()
    assert not w.scheduler._thread.is_alive() and len(calls)==8
    assert all(r['state']=='done' for d in old_ids for r in store.lines(d))
    assert store.lines(new)[0]['translation'] is None and w.doc_id==new
    w.close()
