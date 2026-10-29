"""DeepSeek batch snapshots and one-shot budget safety, never real HTTP."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading
from decimal import Decimal
import httpx
import pytest
from PySide6.QtWidgets import QComboBox
from transcomic.deepseek import DeepSeekProvider,MODEL,provider_for,save_key
from transcomic.deepseek_models import PRO_MODEL
from transcomic.documents import decode_txt
from transcomic.storage import Store
from transcomic.translation import Scheduler
from transcomic.workspace_retry import fresh_retry_config
from transcomic.deepseek_batch import BATCH_SIZES
from transcomic.automation.adapters import Translation
from transcomic.automation.repository import Repository
from transcomic.automation.validation import defaults
from deepseek_budget_fixture import BudgetLedger,BudgetStop
from deepseek_budget_fixture import PrepaidTransport
from test_deepseek_integration import gui,response
from test_automation_ui import gui as automation_gui
from test_automation import add_group


@pytest.mark.parametrize('size',BATCH_SIZES)
@pytest.mark.parametrize('model',[MODEL,PRO_MODEL])
def test_snapshot_correct_batches_parser_and_remainder(tmp_path,size,model):
    store=Store(tmp_path/'s.db');save_key(store,'batch-fixture')
    # 34 eligible lines, a blank and a punctuation-only line are not sent.
    raw='\n'.join(['Người lữ khách trở về nhà']*34+['','...'])
    doc,_=store.import_document(tmp_path/'synthetic.txt',decode_txt(raw.encode()),'vi','en')
    job=store.create_job(doc,model,'vi','en',2,provider='deepseek',config={'deepseek_batch_size':size})
    calls=[]
    def handler(r):calls.append(r);return response(r)
    p=provider_for(store,store.job(job));p.transport=httpx.MockTransport(handler);s=Scheduler(store,p)
    try:
        s.start(job);s.join(5);assert not s._thread.is_alive()
        assert len(calls)==(34+size-1)//size
        groups=[json.loads(json.loads(r.content)['messages'][1]['content'])['lines'] for r in calls]
        assert sum(map(len,groups))==34 and len({r['id'] for g in groups for r in g})==34
        assert all(len(g)<=size for g in groups) and sorted(len(g) for g in groups)[0]==(34%size or size)
        assert all(json.loads(r.content)['model']==model for r in calls)
        assert all(json.loads(r.content)['thinking']=={'type':'disabled'} for r in calls)
        assert all(128<=json.loads(r.content)['max_tokens']<=8192 for r in calls)
        store.set_setting('deepseek_batch_size','15' if size!=15 else '3')
        assert fresh_retry_config(store,store.job(job))['deepseek_batch_size']==size
        # A restart with all batches complete cannot reissue them.
        s=Scheduler(store,provider_for(store,store.job(job)));s.provider.transport=httpx.MockTransport(lambda r:pytest.fail('Completed batch replay'))
        s.start(job);s.join(3);assert not s._thread.is_alive()
    finally:store.close()


def test_legacy_job_and_other_providers_stay_three(tmp_path):
    store=Store(tmp_path/'s.db');store.set_setting('deepseek_batch_size','15')
    try:
        for provider,model in (('kira','mock'),('gemini','models/mock'),('deepseek',MODEL)):
            doc,_=store.import_document(tmp_path/f'{provider}.txt',decode_txt(b'one\ntwo\nthree\nfour'),'vi','en')
            cfg={'deepseek_batch_size':3} if provider=='deepseek' else {}
            job=store.create_job(doc,model,'vi','en',1,provider=provider,config=cfg)
            assert [len(b['payload']) for b in store.batches(job)]==[3,1]
            if provider=='deepseek':
                data=json.loads(store.job(job)['config']);data.pop('deepseek_batch_size')
                with store.transaction():store.db.execute('UPDATE jobs SET config=? WHERE id=?',(json.dumps(data),job))
                save_key(store,'fixture');assert provider_for(store,store.job(job)).batch_size==3
                assert fresh_retry_config(store,store.job(job))['deepseek_batch_size']==3
        with pytest.raises(ValueError):DeepSeekProvider('fixture',batch_size=4)
    finally:store.close()


@pytest.mark.parametrize('size',BATCH_SIZES)
def test_automation_boundaries_and_frozen_workset(tmp_path,size):
    store=Store(tmp_path/'s.db');repo=Repository(store);cfg=defaults(store)
    cfg.update(provider='deepseek',model=MODEL,workers=1,deepseek_batch_size=size)
    id=repo.create('synthetic batch',cfg);gid,_,_=add_group(repo,id,tmp_path/'g',count=19)
    calls=[]
    def factory(s,j):
        p=DeepSeekProvider('fixture',batch_size=json.loads(j['config'])['deepseek_batch_size'])
        def handler(r):calls.append(r);return response(r)
        p.transport=httpx.MockTransport(handler);return p
    try:
        with store.transaction():store.db.execute("UPDATE automation_worksets SET state='running',started=1 WHERE id=?",(id,))
        adapter=Translation(repo,factory);adapter.run(id,repo.groups(id),cfg,threading.Event(),lambda:None)
        assert len(calls)==(19+size-1)//size
        assert all(len(json.loads(json.loads(r.content)['messages'][1]['content'])['lines'])<=size for r in calls)
        with store.transaction():store.db.execute("UPDATE automation_worksets SET state='stopped' WHERE id=?",(id,))
        changed=dict(cfg,deepseek_batch_size=5 if size!=5 else 10)
        with pytest.raises(ValueError):repo.configure(id,changed)
    finally:store.close()


def test_ui_batch_only_in_translation_persists(gui):
    app,store,w=gui
    w.provider_selector.setCurrentIndex(w.provider_selector.findData('deepseek'));app.processEvents()
    assert w.deepseek_batch.currentData()==3 and w.deepseek_batch_column.isVisible()
    w.deepseek_batch.setCurrentIndex(w.deepseek_batch.findData(10))
    for p in ('gemini','kira'):
        w.provider_selector.setCurrentIndex(w.provider_selector.findData(p));app.processEvents()
        assert not w.deepseek_batch_column.isVisible()
    w.provider_selector.setCurrentIndex(w.provider_selector.findData('deepseek'));app.processEvents()
    assert w.deepseek_batch.currentData()==10 and store.setting('deepseek_batch_size')=='10'
    assert w.deepseek_batch not in w.pages.widget(2).findChildren(QComboBox)


def test_automation_batch_ui_persists(automation_gui):
    app,w,p,id=automation_gui
    p.fields['provider'].setCurrentIndex(p.fields['provider'].findData('deepseek'))
    p.fields['deepseek_batch_size'].setCurrentIndex(p.fields['deepseek_batch_size'].findData(15));app.processEvents()
    assert p.repo.workset(id)['config']['deepseek_batch_size']==15
    p.load_worksets(id);assert p.fields['deepseek_batch_size'].currentData()==15


def test_ledger_reserves_inflight_and_blocks_parallel_overspend(tmp_path):
    ledger=BudgetLedger(tmp_path/'ledger.db',operating=100)
    try:
        def reserve(i):
            try:return ledger.reserve(str(i),MODEL,3,3,1000,128)
            except BudgetStop:return None
        with ThreadPoolExecutor(max_workers=8) as pool:ids=list(pool.map(reserve,range(10)))
        state=ledger.snapshot();assert Decimal(state['conservative_vnd'])<=100
        assert Decimal(state['uncertain_reserved_vnd'])==Decimal(state['conservative_vnd'])
        assert any(id is None for id in ids)
        # Unknown outcome retains its entire reservation and stops future calls.
        id=next(id for id in ids if id is not None);reserved=ledger.rows()[0]['reserved_vnd']
        assert not ledger.settle(id,status=504)
        assert ledger.rows()[0]['accounted_vnd']==reserved
        with pytest.raises(BudgetStop):reserve_result=ledger.reserve('next',MODEL,3,3,1,128)
    finally:ledger.close()


def test_ledger_boundary_replay_and_known_usage(tmp_path):
    path=tmp_path/'ledger.db';ledger=BudgetLedger(path)
    try:
        id=ledger.reserve('first',PRO_MODEL,15,15,5000,2048)
        before=Decimal(ledger.snapshot()['conservative_vnd'])
        assert ledger.settle(id,usage={'prompt_tokens':1000,'completion_tokens':100,'prompt_cache_hit_tokens':300},status=200)
        assert Decimal(ledger.snapshot()['conservative_vnd'])<before
        with pytest.raises(BudgetStop):ledger.reserve('first',PRO_MODEL,15,15,5000,2048)
        with pytest.raises(BudgetStop):ledger.reserve('overspend',PRO_MODEL,15,15,1000000,8192)
        assert len(ledger.rows())==1
    finally:ledger.close()
    with pytest.raises(FileExistsError):BudgetLedger(path)


def test_ledger_usage_bounds_no_zero_for_missing_usage(tmp_path):
    ledger=BudgetLedger(tmp_path/'ledger.db')
    try:
        id=ledger.reserve('first',MODEL,3,3,100,128)
        assert not ledger.settle(id,usage={'prompt_tokens':101,'completion_tokens':1},status=200)
        assert ledger.snapshot()['usage_estimated_usd'] is None
        assert Decimal(ledger.snapshot()['uncertain_reserved_vnd'])>0
    finally:ledger.close()


@pytest.mark.parametrize('size',[5,10,15])
def test_pause_stop_resume_uses_saved_boundaries(tmp_path,size):
    store=Store(tmp_path/'s.db');save_key(store,'pause-fixture')
    doc,_=store.import_document(tmp_path/'source.txt',decode_txt(('\n'.join(['Người lữ khách trở về nhà']*34)).encode()),'vi','en')
    job=store.create_job(doc,PRO_MODEL,'vi','en',1,provider='deepseek',config={'deepseek_batch_size':size})
    entered=threading.Event();release=threading.Event();calls=[]
    async def handler(r):
        calls.append(r);entered.set()
        while not release.is_set():await asyncio.sleep(.005)
        return response(r)
    p=provider_for(store,store.job(job));p.transport=httpx.MockTransport(handler);s=Scheduler(store,p)
    try:
        s.start(job);assert entered.wait(2);s.pause();release.set()
        import time
        time.sleep(.12);assert len(calls)==1;s.stop();s.join(3)
        store.close();store=Store(tmp_path/'s.db');store.set_setting('deepseek_batch_size','3')
        p=provider_for(store,store.job(job));assert p.batch_size==size
        p.transport=httpx.MockTransport(handler);s=Scheduler(store,p);s.start(job);s.join(5)
        groups=[json.loads(json.loads(r.content)['messages'][1]['content'])['lines'] for r in calls]
        assert len(calls)==(34+size-1)//size and len({r['id'] for g in groups for r in g})==34
    finally:release.set();s.stop();s.join(3);store.close()


@pytest.mark.parametrize('size',[5,10,15])
@pytest.mark.parametrize('kind',['missing_ids','http504'])
def test_large_batch_failure_never_retries(tmp_path,size,kind):
    store=Store(tmp_path/'s.db');doc,_=store.import_document(tmp_path/'source.txt',decode_txt(('\n'.join(['Người lữ khách trở về nhà']*30)).encode()),'vi','en')
    # This regression freezes the historical single-pass policy explicitly.
    job=store.create_job(doc,PRO_MODEL,'vi','en',1,provider='deepseek',config={'deepseek_batch_size':size,'translation_completion_policy':0});calls=[]
    def handler(r):
        calls.append(r)
        return httpx.Response(504,json={}) if kind=='http504' else httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'{"lines":[]}'}}]})
    s=Scheduler(store,DeepSeekProvider('fixture',PRO_MODEL,batch_size=size,transport=httpx.MockTransport(handler)))
    try:
        s.start(job);s.join(4);assert not s._thread.is_alive() and len(calls)==1 and s.intervention_reason
        assert len([a for b in store.batches(job) for a in store.attempts(b['id'])])==1
    finally:s.stop();s.join(5);store.close()


@pytest.mark.parametrize('operating,status',[(1,200),(4000,504),(4000,200)])
def test_transport_reserves_before_send_or_blocks_without_http(tmp_path,monkeypatch,operating,status):
    from types import SimpleNamespace
    import deepseek_budget_fixture as benchmark
    from test_deepseek import LINES,envelope
    monkeypatch.setattr(benchmark,'OUT',tmp_path)
    ledger=BudgetLedger(tmp_path/'ledger.db',operating=operating);gate=SimpleNamespace(_stopped=threading.Event())
    transport=PrepaidTransport(ledger,MODEL,3,gate);calls=[]
    def handler(r):
        calls.append(r);assert ledger.rows()[0]['state']=='reserved_before_http'
        assert Decimal(ledger.snapshot()['conservative_vnd'])>0
        return httpx.Response(status,json=envelope())
    transport.inner=httpx.MockTransport(handler)
    provider=DeepSeekProvider('fixture',transport=transport);provider.should_stop=gate._stopped.is_set
    try:
        result=asyncio.run(provider.translate(LINES,'vi','en'))
        assert len(calls)==(0 if operating==1 else 1)
        assert Decimal(ledger.snapshot()['conservative_vnd'])<=operating
        if operating==1:assert result.error and not ledger.rows()
    finally:ledger.close()
