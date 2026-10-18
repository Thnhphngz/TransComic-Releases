"""Synthetic keys only: no account ownership may be inferred from a failure."""
import asyncio
import time

import httpx
import pytest

from transcomic.storage import Store
from transcomic.kira_pool import KiraPoolProvider
from transcomic.providers import BatchResult, KiraProvider


def make(tmp_path, grouped=False):
    store=Store(tmp_path/'state.db')
    store.add_kira_keys('synthetic-a synthetic-b synthetic-c',name='Similar name')
    ids=[k['id'] for k in store.kira_keys()]
    if grouped:
        for key in ids:store.set_kira_account_scope(key,ids[0])
    return store,ids


@pytest.mark.parametrize('kind',['quota_exhausted','rate_limit','permission','http_error','client_timeout'])
def test_unverified_accounts_failure_isolated(tmp_path,kind):
    store,ids=make(tmp_path)
    try:
        pool=KiraPoolProvider(store,'mock')
        lease=pool.reserve(30,10); assert lease[0]==ids[0]
        pool.release(ids[0],BatchResult({},'synthetic',kind=='client_timeout',diagnostics={
            'failure_kind':kind,'retry_after_seconds':30,'quota_scope':'account'}))
        assert pool._reason(ids[1],30,time.time()) is None
        assert pool._reason(ids[2],30,time.time()) is None
        assert pool.reserve(30,10)[0]==ids[1]
    finally:store.close()


def test_verified_group_requires_provider_account_scope(tmp_path):
    store,ids=make(tmp_path,True)
    try:
        pool=KiraPoolProvider(store,'mock')
        key=pool.reserve(30,10)[0]
        pool.release(key,BatchResult({},'quota',diagnostics={'failure_kind':'quota_exhausted'}))
        assert pool.availability(30)[0]==ids[1:]
        key=pool.reserve(30,10)[0]
        pool.release(key,BatchResult({},'quota',diagnostics={'failure_kind':'quota_exhausted','quota_scope':'account'}))
        assert not pool.availability(30)[0]
        assert KiraPoolProvider(store,'explicit-new-model').availability(30)[0]==ids
    finally:store.close()


def test_legacy_group_lock_ignored_restart_preserves_actual_key_block(tmp_path):
    store,ids=make(tmp_path)
    try:
        store.set_setting('kira_model_quota:shared:mock','1')
        store.kira_key_status(ids[0],'QUOTA_EXHAUSTED',model='mock',reason='quota_exhausted')
        pool=KiraPoolProvider(store,'mock')
        assert pool.availability(30)[0]==ids[1:]
        assert store.setting('kira_model_quota:shared:mock')=='1'
        assert KiraPoolProvider(store,'other').availability(30)[0]==ids
        store.close();store=Store(tmp_path/'state.db')
        assert KiraPoolProvider(store,'mock').availability(30)[0]==ids[1:]
    finally:store.close()


@pytest.mark.parametrize('status,body,kind',[
    (402,{'error':{'message':'quota balance limit'}},'http_error'),
    (402,{'error':{'code':'vnd_balance_exhausted'}},'quota_exhausted'),
    (402,{'error':{'code':'pro_membership_required'}},'permission'),
    (429,{'error':{'message':'quota limit balance'}},'rate_limit'),
    (429,{'error':{'code':'insufficient_quota','scope':'account'}},'quota_exhausted'),
    (401,{},'authentication'),(403,{},'permission'),(404,{},'model_or_request'),
    (500,{},'http_server_error'),(504,{},'http_504'),
])
def test_structured_classification(status,body,kind):
    async def run():
        p=KiraProvider('synthetic','mock',transport=httpx.MockTransport(lambda _:httpx.Response(status,json=body)))
        return await p.translate([{'id':'a','source':'xin chao'}],'vi','en')
    r=asyncio.run(run())
    assert r.diagnostics['failure_kind']==kind


def test_quota_reset_restart(tmp_path):
    store,ids=make(tmp_path,True)
    try:
        pool=KiraPoolProvider(store,'mock')
        key=pool.reserve(30,10)[0]
        pool.release(key,BatchResult({},'quota',diagnostics={'failure_kind':'quota_exhausted',
            'quota_scope':'account','retry_after_seconds':.03}))
        assert not pool.availability(30)[0]
        time.sleep(.05)
        assert KiraPoolProvider(store,'mock').availability(30)[0]==ids
    finally:store.close()


def test_unknown_default_independent_capacity_and_confirmed_shared_limit(tmp_path):
    store,ids=make(tmp_path)
    try:
        pool=KiraPoolProvider(store,'mock')
        leases=[pool.reserve(30,1) for _ in range(91)]
        assert all(leases[:90]) and leases[90] is None
        assert list(pool.busy.values())==[30,30,30]
        for key,_ in leases[:90]:pool.release(key)
        for key in ids:store.set_kira_account_scope(key,ids[0])
        shared=KiraPoolProvider(store,'mock',rpm=1000)
        assert sum(shared.reserve(30,1) is not None for _ in range(31))==30
    finally:store.close()


def test_probe_budget_atomic_and_restart(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from scripts.probe_kira_false_quota import Budget
    path=tmp_path/'budget.db'
    budget=Budget(path,['a','b','c'])
    def reserve(_):
        try:budget.reserve(1,'a',3);return True
        except ValueError:return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(reserve,range(40)))==10
    budget=Budget(path,['a','b','c'])
    for round in (1,2,3):
        for key in ('a','b','c'):
            if round==1 and key=='a':continue
            for _ in range(10):budget.reserve(round,key,3)
    with pytest.raises(ValueError):budget.reserve(3,'c',1)
    with pytest.raises(ValueError):budget.reserve(4,'a',1)
    with pytest.raises(ValueError):Budget(path,['a','b','different'])


@pytest.mark.parametrize('header',[{}, {'retry-after':'5'}])
def test_429_without_quota_code_is_temporary(header):
    async def run():
        p=KiraProvider('synthetic','mock',transport=httpx.MockTransport(
            lambda _:httpx.Response(429,headers=header,json={'error':{'message':'balance quota exhausted'}})))
        return await p.translate([{'id':'a','source':'xin chao'}],'vi','en')
    result=asyncio.run(run())
    assert result.diagnostics['failure_kind']=='rate_limit'
    assert result.diagnostics['retry_after_seconds']==(5 if header else None)


def test_invalid_json_does_not_spread_quota(tmp_path):
    store,ids=make(tmp_path)
    try:
        pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(lambda _:httpx.Response(402,text='quota balance')))
        key,p=pool.reserve(30,1)
        result=asyncio.run(p.translate([{'id':'a','source':'xin chao'}],'vi','en'))
        pool.release(key,result)
        assert result.diagnostics['failure_kind']=='http_error'
        assert pool.availability(30)[0]==ids[1:]
    finally:store.close()


def test_unconfirmed_legacy_named_group_is_not_ownership_proof(tmp_path):
    store,ids=make(tmp_path)
    try:
        for key in ids:store.set_setting('kira_account:'+key,ids[0])
        pool=KiraPoolProvider(store,'mock')
        assert len(set(pool.scopes.values()))==3
    finally:store.close()


def test_three_independent_keys_real_dispatch_fair_and_parallel(tmp_path):
    import json
    from collections import Counter
    from transcomic.documents import decode_txt
    from transcomic.translation import Scheduler
    store,ids=make(tmp_path)
    counts=Counter();active=Counter();peak=0;gate=None
    async def handler(request):
        nonlocal peak,gate
        if gate is None:gate=asyncio.Event()
        key=request.headers['authorization']
        counts[key]+=1;active[key]+=1
        peak=max(peak,sum(active.values()))
        assert active[key]<=30 and sum(active.values())<=90
        if sum(active.values())>=30:gate.set()
        await asyncio.wait_for(gate.wait(),5)
        payload=json.loads(json.loads(request.content)['messages'][1]['content'])['lines']
        active[key]-=1
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({
            'lines':[{'id':r['id'],'text':'The translated story continues'} for r in payload]})}}]})
    doc=store.import_document(tmp_path/'synthetic.txt',decode_txt(('\n'.join(['Văn bản tổng hợp']*121)).encode()),'vi','en')[0]
    run,jobs=store.create_run([doc],['en'],provider='kira',model='mock',source_lang='vi',concurrency=30,
        config={'kira_multi_key':True,'kira_recovery_version':2})
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler),rpm=10000,tpm=100000000)
    scheduler=Scheduler(store,pool)
    try:
        scheduler.start_many(jobs,run);scheduler.join(10)
        assert not scheduler._thread.is_alive()
        assert store.run(run)['state']=='finished'
        assert sorted(counts.values())==[13,14,14]
        assert 30<=peak<=41 and not any(active.values())
        assert all(r['state']=='done' for r in store.lines(doc))
    finally:
        scheduler.stop();scheduler.join(6);store.close()
