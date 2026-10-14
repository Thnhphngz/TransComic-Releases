import asyncio
import json
import time
import threading
import pytest
from docx import Document
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from transcomic.languages import LANGUAGES,language,validate_pair,export_name
from transcomic.prompts import messages,PROMPT_VERSION
from transcomic.quality import language_evidence,language_warnings
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.bulk import plan_exports,write_exports,import_many
from transcomic.providers import BatchResult
from transcomic.translation import Scheduler

def setup(tmp_path,targets,files=2,lines=9,cap=3):
    store=Store(tmp_path/'state.db')
    docs=[store.import_document(tmp_path/f'{i}.txt',decode_txt(('\n'.join(f'Nguồn {i} dòng {n}' for n in range(lines))).encode()),'vi',targets[0])[0] for i in range(files)]
    run,jobs=store.create_run(docs,targets,provider='kira',model='mock',source_lang='vi',concurrency=cap)
    return store,run,jobs

@pytest.mark.parametrize('targets,files,cap',[(['en'],1,1),(['en','id'],10,30),(['ja','de','en'],10,50)])
def test_language_barrier_retry_and_file_fairness(tmp_path,targets,files,cap):
    store,run,jobs=setup(tmp_path,targets,files,18,cap)
    active=peak=0;calls=[];ends=[];seen={}
    class Fake:
        async def translate(self,rows,source,target):
            nonlocal active,peak
            locale=language(target).locale
            assert not active or calls[-1][0]==locale
            active+=1;peak=max(peak,active);calls.append((locale,time.monotonic(),rows[0]['id']))
            await asyncio.sleep(.01)
            active-=1;ends.append((locale,time.monotonic()))
            seen[rows[0]['id']]=seen.get(rows[0]['id'],0)+1
            if seen[rows[0]['id']]==1:return BatchResult({},'invalid',diagnostics={'failure_kind':'invalid_line_response'})
            return BatchResult({r['id']:'translated '+r['source'] for r in rows})
    scheduler=Scheduler(store,Fake());scheduler.start_many(jobs,run)
    store.set_setting('target_order',json.dumps(list(reversed(targets))))
    scheduler.join(15)
    assert not scheduler._thread.is_alive() and peak<=cap
    for before,after in zip(targets,targets[1:]):
        assert max(t for l,t in ends if l==before)<min(t for l,t,_ in calls if l==after)
    assert list(dict.fromkeys(c[0] for c in calls))==targets
    assert all(r['state']=='done' for j in jobs for r in store.lines(store.job(j)['document_id']))
    saved=store.run(run)['config'];assert saved['language_order']==targets
    assert all(saved['language_states'][l]=='completed' for l in targets)
    store.close()

@pytest.mark.parametrize('mode',['exhausted','unknown','quota','stop','pause'])
def test_barrier_terminal_states_and_controls(tmp_path,mode):
    store,run,jobs=setup(tmp_path,['en','id'],1,3,1)
    entered=threading.Event();release=threading.Event();calls=[]
    class Fake:
        async def translate(self,rows,source,target):
            calls.append(language(target).locale);entered.set()
            while not release.is_set():await asyncio.sleep(.005)
            if mode=='exhausted':return BatchResult({},'invalid',diagnostics={'failure_kind':'invalid_line_response'})
            if mode=='unknown':return BatchResult({},'Network uncertain',True,diagnostics={'failure_kind':'network_error'})
            if mode=='quota':return BatchResult({},'quota',diagnostics={'http_status':429,'quota_type':'exhausted','failure_kind':'quota_exhausted'})
            return BatchResult({r['id']:'done' for r in rows})
    scheduler=Scheduler(store,Fake());scheduler.start_many(jobs,run);assert entered.wait(3)
    if mode=='stop':scheduler.stop()
    if mode=='pause':scheduler.pause()
    release.set()
    if mode=='pause':
        time.sleep(.1);assert calls==['en'] and scheduler._thread.is_alive();scheduler.resume()
    scheduler.join(5);assert not scheduler._thread.is_alive()
    if mode in ('quota','unknown','stop'):assert calls==['en']
    elif mode=='exhausted':assert calls==['en']*6+['id']*6
    else:assert calls==['en','id']
    store.close()

@pytest.mark.parametrize('entry',LANGUAGES,ids=lambda e:e.locale)
@pytest.mark.parametrize('fmt',['txt','docx'])
def test_registry_prompt_exports_three_modes(tmp_path,entry,fmt):
    assert len(LANGUAGES)==11 and len({l.locale for l in LANGUAGES})==11 and len({l.code for l in LANGUAGES})==11
    assert language(entry.name)==entry
    with pytest.raises(ValueError):validate_pair(entry.locale,entry.name)
    source='en' if entry.locale=='vi' else 'vi'
    text=messages([{'id':'a','source':'Nguồn'}],source,entry.locale)[0]['content']
    assert entry.prompt in text and entry.locale in text and 'reference_only' in text
    path=tmp_path/f'Chapter.01.{fmt}'
    if fmt=='txt':path.write_bytes(b'Source\r\n')
    else:
        word=Document();word.add_paragraph('Source');word.save(path)
    original=path.read_bytes();store=Store(tmp_path/'state.db')
    doc=import_many(store,[path],language(source).name,entry.name)['document_ids'][0]
    store.edit_line(store.lines(doc)[0]['id'],'translation','Translated')
    for mode in ('direct','transcomic','custom'):
        plan=plan_exports(store.export_snapshot([doc]),tmp_path/'out',mode=mode)
        assert plan[0]['target'].name==f'Chapter.01_{entry.code}.{fmt}'
        assert all(r['state']=='exported' for r in write_exports(store,plan))
        if mode=='transcomic':assert entry.folder in plan[0]['target'].parts
    assert path.read_bytes()==original
    assert export_name(path,entry.locale,True)==f'Chapter.01_{entry.code}_INCOMPLETE.{fmt}'
    store.close()

@pytest.mark.parametrize('target,text,status',[
    ('hi','She was in the room and he was standing with her','suspected'),
    ('ja','She was in the room and he was standing with her','suspected'),
    ('zh-CN','這個國家的學生們說這個學校讓他們學會愛','suspected'),
    ('de','những người đã ở trong một căn phòng của họ với người này','suspected'),
    ('ms','karena dia bisa pergi dengan seorang teman karena dia bisa','suspected'),
    ('fil','She was in the room and he was standing with her','suspected'),
    ('en','Cael','insufficient'),('ja','1234','insufficient'),
    ('en-CA','Evelyn and Cael','insufficient'),
    ('hi','वह कमरे में थी और वह उसके साथ खड़ा था','compatible'),
    ('ja','彼女は部屋にいて、彼は彼女と一緒に立っていた','compatible'),
    ('zh-CN','她在房间里面，而他站在她的身边','compatible'),
])
def test_local_language_evidence(target,text,status):
    assert language_evidence('Nguồn tiếng Việt',text,'vi',target)[0]==status

def test_user_supplied_semantic_failures_are_warnings_only():
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures/multilingual_review_failures.json').read_text(encoding='utf-8'))
    assert fixture['semantic_ground_truth'] is False
    cases=[(c['source'],c['reported_bad_output'],c['warning']) for c in fixture['cases']]
    for source,target,kind in cases:
        assert kind in {k for k,_ in language_warnings(source,target,'vi','id')}
    validate_pair('en','en-CA')
    assert language_evidence('The room was quiet','The room was quiet','en','en-CA')[0]!='suspected'

def test_technical_links_placeholder_and_fullwidth_question_preserved():
    from transcomic.postprocess import normalize
    raw='See https://example.com/a.b?x=1.2 {{user.name}} <tag.id> 00:00:01.500.'
    output,_=normalize(raw,raw)
    assert output=='See https://example.com/a.b?x=1.2 {{user.name}} <tag.id> 00:00:01.500'
    assert normalize(raw,output)[0]==output
    assert 'Sắc thái câu hỏi' not in {k for k,_ in language_warnings('cael bị mù màu sao','カエルは色覚異常なの？','vi','ja')}

def test_actual_canadian_english_pronoun_candidate_is_warning_not_rewrite():
    source='cậu ta giọng điệu đầy ẩn ý quanh sang phía damian, evelyn bực bội lườm cậu ta'
    target='she spoke with a loaded tone, turning toward Damian, Evelyn glared at her in annoyance'
    assert 'Đại từ' in {k for k,_ in language_warnings(source,target,'vi','en-CA')}
    assert 'Đại từ' not in {k for k,_ in language_warnings(source,'he spoke, Evelyn glared at him','vi','en-CA')}
    assert 'Đại từ' not in {k for k,_ in language_warnings('anh ta nói, cô ấy trả lời','he spoke, she replied','vi','en')}

def test_chip_order_persistence_hover_and_search_registry(tmp_path):
    from transcomic.ui.main import MainWindow
    from transcomic.ui.theme import stylesheet
    app=QApplication.instance() or QApplication([]);store=Store(tmp_path/'state.db');w=MainWindow(store);w.show();app.processEvents()
    for chip in w.target_chips.values():chip.setChecked(False)
    for locale in ('ja','de','en'):w.target_chips[language(locale).name].click()
    assert [language(t).locale for t in w.target_languages()]==['ja','de','en']
    w.target_chips[language('de').name].click();w.target_chips[language('de').name].click()
    assert [language(t).locale for t in w.target_languages()]==['ja','en','de']
    assert w.target_chips[language('de').name].text()=='3 DE'
    assert w.source_lang.count()==11 and w.search.language_scope.count()==12
    for dark in (False,True):
        assert '#languageChip:checked:hover' in stylesheet(dark)
        QTest.mouseMove(w.target_chips[language('en').name]);app.processEvents()
        assert w.target_chips[language('en').name].isChecked()
    w._exit_authorized=True;w.close()
    # V3 replaces target persistence with an empty selection on a fresh startup.
    w=MainWindow(Store(tmp_path/'state.db'));assert w.target_languages()==[]
    assert not any(chip.isChecked() for chip in w.target_chips.values())
    assert not w.start_button.isEnabled()
    assert not w.workspace_ids and w.scheduler is None
    w._exit_authorized=True;w.close()

@pytest.mark.parametrize('unknown',[False,True])
def test_workspace_retry_provider_barrier_across_config_groups(tmp_path,unknown):
    from transcomic.workspace_retry import WorkspaceRetryScheduler
    store=Store(tmp_path/'state.db');groups=[];calls=[];adapters={}
    class Fake:
        async def translate(self,rows,source,target):
            calls.append(language(target).locale);await asyncio.sleep(.01)
            if unknown:return BatchResult({},'Network uncertain',True,diagnostics={'failure_kind':'network_error'})
            return BatchResult({r['id']:'done' for r in rows})
    for i in range(2):
        d=store.import_document(tmp_path/f'{i}.txt',decode_txt(b'Source'),'vi','en')[0]
        _,jobs=store.create_run([d],['en','id'],provider='kira',model=f'm{i}',source_lang='vi',concurrency=1)
        groups.append(jobs)
        for j in jobs:adapters[j]=Fake()
    scheduler=WorkspaceRetryScheduler(store,groups,adapters,lambda ids:None)
    scheduler.start();scheduler.join(5);assert not scheduler._thread.is_alive()
    assert calls==(['en'] if unknown else ['en','en','id','id'])
    store.close()

def test_gemini_sequential_language_phases_share_rate_limiter(tmp_path):
    import httpx
    from transcomic.gemini import GeminiProvider,QuotaLimiter
    from tests.test_stage2_gemini import response
    store=Store(tmp_path/'state.db');d=store.import_document(tmp_path/'a.txt',decode_txt(b'A\nB\nC\nD'),'vi','en')[0]
    run,jobs=store.create_run([d],['en','id'],provider='gemini',model='models/mock',source_lang='vi',concurrency=2)
    limiter=QuotaLimiter(1000,100000,10);calls=[]
    def handle(req):
        body=json.loads(req.content);instruction=body['systemInstruction']['parts'][0]['text']
        calls.append('en' if 'Target locale: en;' in instruction else 'id')
        return httpx.Response(200,json=response(req))
    provider=GeminiProvider([{'id':'mock','secret':'mock-only','project':'mock'}],'models/mock',limiter=limiter,transport=httpx.MockTransport(handle))
    scheduler=Scheduler(store,provider);scheduler.start_many(jobs,run);scheduler.join(5)
    assert not scheduler._thread.is_alive() and calls==['en','en','id','id']
    assert provider.limiter is limiter
    store.close()

def test_crash_preserves_order_current_phase_and_barrier(tmp_path):
    store,run,jobs=setup(tmp_path,['ja','de','en'],1,6,1)
    store.run_language_state(run,'ja','waiting_rate_limit');store.run_state(run,'waiting_rate_limit')
    batch=store.batches(jobs[0])[0];store.claim_batch(batch['id']);store.prepare_attempt(batch['id'],1)
    store.close();store=Store(tmp_path/'state.db');saved=store.run(run)
    assert saved['state']=='interrupted' and saved['config']['language_order']==['ja','de','en']
    assert saved['config']['current_locale']=='ja' and saved['config']['language_states']['ja']=='interrupted'
    calls=[]
    class Fake:
        async def translate(self,rows,source,target):
            calls.append(language(target).locale);return BatchResult({r['id']:'done' for r in rows})
    scheduler=Scheduler(store,Fake());scheduler.start_many(jobs,run);scheduler.join(3)
    assert calls==['ja'] and store.run(run)['state']=='needs_intervention'
    assert len(store.attempts(batch['id']))==1
    store.close()
