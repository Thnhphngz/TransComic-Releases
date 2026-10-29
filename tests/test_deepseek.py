"""All DeepSeek traffic here uses MockTransport, never the network."""
import asyncio
import json
import threading
import time
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import httpx
import pytest
from transcomic.deepseek import DeepSeekProvider, MODEL, URL, save_key, read_key, provider_for, settings
from transcomic.deepseek_pricing import DEFAULT, VN, period, estimate, validate, load
from transcomic.documents import decode_txt
from transcomic.storage import Store
from transcomic.translation import Scheduler
from transcomic.retry import allowed_retry

LINES = [{'id':str(i), 'source':f'Nội dung {i}'} for i in range(1,4)]


def envelope(content=None, reason='stop', usage=True):
    data = dict(choices=[dict(finish_reason=reason, message=dict(content=content if content is not None else json.dumps({'lines':[dict(id=r['id'], text='The traveler returns home') for r in LINES]})))])
    if usage: data['usage']=dict(prompt_tokens=100, completion_tokens=20, total_tokens=120, prompt_cache_hit_tokens=30,
                               prompt_cache_miss_tokens=70, prompt_tokens_details={'cached_tokens':30})
    return data


def run_response(data, status=200):
    calls=[]
    def handler(request): calls.append(request); return httpx.Response(status, json=data)
    provider=DeepSeekProvider('synthetic-secret', transport=httpx.MockTransport(handler))
    result=asyncio.run(provider.translate(LINES, 'vi', 'en'))
    assert len(calls)==1
    assert 'synthetic-secret' not in repr(result)
    return provider,result,calls[0]


def test_request_contract_context_and_usage():
    provider,result,request=run_response(envelope())
    assert not result.error and list(result.values)==['1','2','3']
    data=json.loads(request.content)
    assert str(request.url)==URL and request.method=='POST'
    assert request.headers['authorization']=='Bearer synthetic-secret'
    assert data['model']==MODEL and data['thinking']=={'type':'disabled'}
    assert data['response_format']=={'type':'json_object'} and data['stream'] is False
    assert data['max_tokens']==2048 and 'reasoning_effort' not in data
    assert 'JSON' in data['messages'][0]['content']
    assert result.usage['prompt_tokens']==100 and result.diagnostics['cost_estimate']['cached_tokens']==30
    rows=deepcopy(LINES);rows[0]['context']=[dict(id='neighbor', source='Lan là chị gái của Nam')]
    body=provider.request_body(rows,'vi','id')
    assert json.loads(body['messages'][1]['content'])['reference_only'][0]['id']=='neighbor'


@pytest.mark.parametrize('content', [
    '', ' ', '{"lines":[', '```json\n{"lines":[]}\n```', '{}', '[]', '{"result":{"lines":[]}}',
    '{"lines":[],"lines":[]}', '{"lines":[{"id":"1","id":"1","text":"hello"}]}',
    json.dumps({'lines':[{'id':'1','text':'hello'}]}),
    json.dumps({'lines':[{'id':r['id'],'text':'hello'} for r in LINES]+[{'id':'4','text':'extra'}]}),
    json.dumps({'lines':[{'id':'1','text':'hello'}]*3}),
    json.dumps({'lines':[{'text':'missing id'}]*3}),
    json.dumps({'lines':[{'id':r['id'],'text':''} for r in LINES]}),
    json.dumps({'lines':[{'id':r['id'],'text':'two\nlines'} for r in LINES]}),
    json.dumps({'lines':[{'id':r['id'],'text':'hello','extra':1} for r in LINES]}),
])
def test_strict_invalid_json_never_partial_or_retry(content):
    _,result,_=run_response(envelope(content))
    assert result.error and result.values=={}


@pytest.mark.parametrize('reason',['length','content_filter','aborted','insufficient_system_resource',None])
def test_finish_reason_rejected(reason):
    _,result,_=run_response(envelope(reason=reason));assert result.error and not result.values


@pytest.mark.parametrize('status,kind',[(400,'model_or_request'),(401,'authentication'),(402,'quota_exhausted'),(429,'rate_limit'),(500,'http_server_error'),(504,'http_server_error')])
def test_http_errors_safe_and_single_send(status,kind):
    _,result,_=run_response({'error':{'message':'synthetic-secret'}},status)
    assert result.error and result.diagnostics['failure_kind']==kind and result.unknown==(status>=500)


@pytest.mark.parametrize('error',[httpx.ConnectError, httpx.ReadError, httpx.ReadTimeout])
def test_network_failure_no_retry(error):
    calls=[]
    def handler(request): calls.append(1);raise error('synthetic-secret')
    provider=DeepSeekProvider('synthetic-secret',transport=httpx.MockTransport(handler))
    result=asyncio.run(provider.translate(LINES,'vi','en'))
    assert len(calls)==1 and result.error and 'synthetic-secret' not in repr(result)
    assert result.unknown==(error is not httpx.ConnectError)


class Keepalive(httpx.AsyncByteStream):
    async def __aiter__(self):
        for _ in range(500):
            await asyncio.sleep(.005);yield b'\n'


def test_total_deadline_cannot_be_reset_by_keepalive():
    p=DeepSeekProvider('synthetic-secret',timeout=.04,transport=httpx.MockTransport(lambda r:httpx.Response(200,stream=Keepalive())))
    start=time.monotonic();result=asyncio.run(p.translate(LINES,'vi','en'))
    assert time.monotonic()-start < .7 and result.unknown and result.diagnostics['failure_kind']=='client_timeout'


@pytest.mark.parametrize('hour,minute,weekend,expected',[(7,59,False,'offpeak'),(8,0,False,'peak'),(10,59,False,'peak'),(11,0,False,'offpeak'),(12,59,False,'offpeak'),(13,0,False,'peak'),(16,59,False,'peak'),(17,0,False,'offpeak'),(9,0,True,'offpeak')])
def test_vietnam_price_boundaries(hour,minute,weekend,expected):
    now=datetime(2026,10,31 if weekend else 26,hour,minute,tzinfo=VN)
    assert period(DEFAULT,now)[0]==expected
    if expected=='peak':assert 'Chưa xác minh' in period(DEFAULT,now)[1]


def test_verified_holiday_and_cache_cost():
    cfg=deepcopy(DEFAULT);cfg.update(holiday_years=[2026],holidays=['2026-10-26'])
    assert period(cfg,datetime(2026,10,26,9,tzinfo=VN))[0]=='offpeak'
    assert period(cfg,datetime(2026,10,27,9,tzinfo=VN))==('peak','Giờ cao điểm')
    cost=estimate(envelope()['usage'],cfg['peak'])
    assert Decimal(cost['usd'])==(Decimal(70)*Decimal('.30')+Decimal(30)*Decimal('.006')+Decimal(20)*Decimal('1.20'))/1000000
    assert estimate(None,cfg['peak']) is None
    assert estimate({'prompt_tokens':100},cfg['peak']) is None
    assert estimate({'prompt_tokens':100,'completion_tokens':20},cfg['peak'])['conservative']
    for invalid in ('NaN','-1','Infinity'):
        broken=deepcopy(cfg);broken['peak']['input']=invalid
        with pytest.raises(ValueError):validate(broken)


def test_cache_alias_unknown_usage_and_utc_timezone():
    rates=DEFAULT['peak']
    data=dict(prompt_tokens=100,completion_tokens=20,prompt_tokens_details={'cached_tokens':30})
    assert estimate(data,rates)['cached_tokens']==30
    data.update(prompt_cache_hit_tokens=30,prompt_cache_miss_tokens=70)
    assert estimate(data,rates)['cached_tokens']==30
    assert period(DEFAULT,datetime.fromisoformat('2026-10-26T01:00:00+00:00'))[0]=='peak'
    data['prompt_cache_hit_tokens']=101;assert estimate(data,rates) is None
    _,result,_=run_response(envelope(usage=False));assert result.diagnostics['cost_estimate'] is None


def test_stop_before_send_and_cancel_during_request():
    p=DeepSeekProvider('fixture',transport=httpx.MockTransport(lambda r:pytest.fail('Stopped request must not be sent')))
    p.should_stop=lambda:True
    result=asyncio.run(p.translate(LINES,'vi','en'))
    assert not result.unknown and result.diagnostics['delivery_state']=='not_sent'
    async def run():
        entered=asyncio.Event()
        async def handler(request):entered.set();await asyncio.Event().wait()
        provider=DeepSeekProvider('fixture',transport=httpx.MockTransport(handler))
        task=asyncio.create_task(provider.translate(LINES,'vi','en'))
        await entered.wait();task.cancel();return await task
    result=asyncio.run(run());assert result.unknown and result.diagnostics['failure_kind']=='shutdown_cancelled'


def make_job(tmp_path, concurrency=1, count=12):
    store=Store(tmp_path/'state.db')
    doc,_=store.import_document(tmp_path/'synthetic.txt',decode_txt('\n'.join('Người lữ khách trở về nhà' for _ in range(count)).encode()),'vi','en')
    # These cases cover the historical frozen single-attempt contract.
    job=store.create_job(doc,MODEL,'vi','en',concurrency,provider='deepseek',config={'translation_completion_policy':0})
    return store,doc,job


def test_keys_settings_provider_identity_and_redaction(tmp_path):
    store,doc,job=make_job(tmp_path)
    try:
        save_key(store,'deepseek-private-fixture');assert read_key(store)=='deepseek-private-fixture'
        store.log.emit('failure', provider='deepseek',reason='deepseek-private-fixture')
        store.log.flush()
        assert 'deepseek-private-fixture' not in store.log.path.read_text(encoding='utf8')
        assert store.load_key() is None
        assert not store.gemini_keys() and not store.kira_keys()
        blob=store.db.execute("SELECT encrypted FROM secrets WHERE key='deepseek'").fetchone()[0]
        assert b'deepseek-private-fixture' not in blob
        assert provider_for(store,store.job(job)).api_key=='deepseek-private-fixture'
        assert store.job(job)['auto_retries']==0 and not store.job(job)['retry_504']
        config=settings(store);config['deepseek_pricing']['peak']['input']='.5'
        store.set_setting('deepseek_pricing',json.dumps(config['deepseek_pricing']))
        assert load(store)['peak']['input']=='.5'
        for status in (429,500,504):assert not allowed_retry(dict(provider='deepseek',auto_retries=5),{'http_status':status},2)
    finally:store.close()


@pytest.mark.parametrize('status',[200,400,401,402,429,500,504])
def test_scheduler_no_hidden_retry_and_durable_attempts(tmp_path,status):
    store,doc,job=make_job(tmp_path)
    calls=[]
    def handler(request):
        rows=json.loads(json.loads(request.content)['messages'][1]['content'])['lines'];calls.append([r['id'] for r in rows])
        return httpx.Response(status,json=envelope(json.dumps({'lines':[dict(id=r['id'],text='The traveler returns home') for r in rows]})))
    p=DeepSeekProvider('synthetic-secret',transport=httpx.MockTransport(handler));scheduler=Scheduler(store,p)
    try:
        scheduler.start(job);scheduler.join(5)
        assert not scheduler._thread.is_alive()
        assert len(calls)==(4 if status==200 else 1)
        assert len({i for ids in calls for i in ids})==len(calls)*3
        attempts=[a for b in store.batches(job) for a in store.attempts(b['id'])]
        assert len(attempts)==len(calls) and all(a['state']=='finished' for a in attempts)
        if status!=200:
            assert scheduler.intervention_reason
            # Restart only dispatches previously unsent batches; failed IDs cannot be replayed.
            scheduler=Scheduler(store,p);scheduler.start(job);scheduler.join(5)
            assert len(calls)==2 and not set(calls[0])&set(calls[1])
        else:assert all(r['translation']=='The traveler returns home' for r in store.lines(doc))
    finally:store.close()


def test_pause_stop_resume_checkpoint_and_cap(tmp_path):
    store,doc,job=make_job(tmp_path,2,30)
    entered=threading.Event();release=threading.Event();calls=[];active=0;peak=0
    async def handler(request):
        nonlocal active,peak
        rows=json.loads(json.loads(request.content)['messages'][1]['content'])['lines'];calls.append([r['id'] for r in rows])
        active+=1;peak=max(active,peak);entered.set()
        while not release.is_set():await asyncio.sleep(.005)
        active-=1
        return httpx.Response(200,json=envelope(json.dumps({'lines':[dict(id=r['id'],text='The traveler returns home') for r in rows]})))
    p=DeepSeekProvider('fixture',transport=httpx.MockTransport(handler));s=Scheduler(store,p)
    try:
        s.start(job);assert entered.wait(2);s.pause();release.set();time.sleep(.1)
        count=len(calls);time.sleep(.08);assert len(calls)==count
        s.stop();s.join(3);assert not s._thread.is_alive() and peak<=2
        store.close();store=Store(tmp_path/'state.db');s=Scheduler(store,p);s.start(job);s.join(5)
        assert not s._thread.is_alive() and len(calls)==10
        assert len({i for call in calls for i in call})==30
    finally:release.set();s.stop();s.join(3);store.close()


@pytest.mark.parametrize('workers',[1,3,30])
def test_deepseek_thirty_worker_ceiling_and_no_duplicate_batches(tmp_path,workers):
    store,doc,job=make_job(tmp_path,workers,90);calls=[];active=0;peak=0
    async def handler(request):
        nonlocal active,peak
        rows=json.loads(json.loads(request.content)['messages'][1]['content'])['lines']
        calls.append([r['id'] for r in rows]);active+=1;peak=max(active,peak)
        await asyncio.sleep(.025);active-=1
        return httpx.Response(200,json=envelope(json.dumps({'lines':[dict(id=r['id'],text='The traveler returns home safely') for r in rows]})))
    s=Scheduler(store,DeepSeekProvider('fixture',transport=httpx.MockTransport(handler)))
    try:
        s.start(job);s.join(5)
        assert not s._thread.is_alive() and peak==workers and len(calls)==30
        assert len({i for call in calls for i in call})==90
        with pytest.raises(ValueError):store.create_job(doc,MODEL,'vi','en',31,provider='deepseek')
    finally:store.close()
