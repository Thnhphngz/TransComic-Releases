import asyncio
from collections import Counter
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time

import httpx
import pytest

from transcomic.documents import decode_txt
from transcomic.kira_pool import KiraPoolProvider
from transcomic.kira_telemetry import KiraTelemetry, counters
from transcomic.kira_monitor_store import load_latest, save_summary
from transcomic.storage import Store
from transcomic.translation import Scheduler
from test_kira_multikey import setup, start, wait_for, lines, success
from test_kira_distribution import fixture_docx


def record(aid='attempt',key='key',doc='doc',target='en',ids=('one','two','three')):
    return dict(run_id='run',job_id='job',batch_id='batch-'+aid,attempt_id=aid,key_id=key,
        account_scope='shared',document_id=doc,target_language=target,source_instance=doc,
        file_name='same.docx',key_name='Kira fixture',line_ids=list(ids),
        revisions={i:[0,0] for i in ids},mode='translation',started_at=time.time(),
        sent=False,received=False,state='CLAIMED_NOT_SENT')


def finish(telemetry,r,**changes):
    value={**r,'state':'SUCCEEDED_AND_COMMITTED','sent':True,'received':True,
        'accepted_ids':r['line_ids'],'request_success':True,'seconds':.1,**changes}
    telemetry.complete(value)
    return value


def test_one_ledger_idempotent_events_unique_positions_and_context_excluded():
    stats={'key':counters()};t=KiraTelemetry(stats);t.begin('run')
    r=record();assert t.claim(r) and not t.claim(r)
    assert stats['key']['claimed_not_sent']==1 and stats['key']['requests']==0
    assert t.sent(r['attempt_id']) and not t.sent(r['attempt_id'])
    assert t.received(r['attempt_id']) and not t.received(r['attempt_id'])
    done=finish(t,r,accepted_ids=['one','two','three','foreign-context'])
    assert not t.complete(done)
    assert stats['key']['translated_lines']==3 and stats['key']['requests']==1
    assert stats['key']['claimed_not_sent']==stats['key']['committing_requests']==0
    r2=record('intentional-new-attempt');r2['mode']='retranslation'
    t.claim(r2);t.sent(r2['attempt_id']);finish(t,r2)
    assert stats['key']['translated_lines']==6 and len(t.unique)==3
    assert stats['key']['retranslation_requests']==1
    assert t.files['key'][('doc','en')]['saved_ids']=={'one','two','three'}


def test_file_and_locale_ids_never_merge_even_when_names_and_line_ids_match():
    stats={};t=KiraTelemetry(stats);t.begin('run')
    for i,(key,doc,locale) in enumerate([('a','doc-a','en'),('a','doc-b','en'),('a','doc-a','id'),('b','doc-a','en')]):
        r=record(str(i),key,doc,locale);t.claim(r);t.sent(r['attempt_id']);finish(t,r)
    assert len(t.files['a'])==3 and len(t.files['b'])==1
    assert len(t.unique)==9 and sum(s['translated_lines'] for s in stats.values())==12


@pytest.mark.parametrize('key_count,file_count,batch_count',[(1,1,1),(2,2,3),(3,10,5),(5,10,32)])
def test_actual_http_attribution_and_load(tmp_path,key_count,file_count,batch_count):
    store,docs,run,jobs=setup(tmp_path,key_count,30,files=file_count,batches=batch_count)
    keys=[k['id'] for k in store.kira_keys()]
    for key in keys:store.set_kira_account_scope(key,key)
    doc_of={r['id']:store.job(j)['document_id'] for j in jobs for b in store.batches(j) for r in b['payload']}
    sent=Counter();saved=Counter();seen=set();gate=threading.Event();busy=0;peak=0
    expected=sum(len(store.batches(j)) for j in jobs);barrier=min(expected,key_count*30)
    queries=[];store.db.set_trace_callback(queries.append)
    async def handler(req):
        nonlocal busy,peak
        index=int(req.headers['authorization'].split('-')[-3]);key=keys[index]
        ids=tuple(r['id'] for r in lines(req));assert ids not in seen;seen.add(ids)
        sent[key]+=1;saved[(key,doc_of[ids[0]])]+=len(ids)
        busy+=1;peak=max(peak,busy)
        while not gate.is_set():await asyncio.sleep(.002)
        await asyncio.sleep(.002);busy-=1;return success(req)
    scheduler,pool=start(store,run,jobs,handler,account_limit=30)
    try:
        wait_for(lambda:busy==barrier,timeout=12)
        active=pool.monitor_snapshot(30)
        assert sum(s['in_flight_requests'] for s in active['per_key'].values())==barrier
        assert sum(s['in_flight_lines'] for s in active['per_key'].values())==sum(sum(len(x) for x in seen if doc_of[x[0]]==doc) for doc in docs)
        assert active['active_files']<=10
    finally:gate.set()
    scheduler.join(25);assert not scheduler._thread.is_alive()
    snapshot=pool.monitor_snapshot(30)
    assert snapshot['state']=='finished' and snapshot['busy']==0
    assert snapshot['requests']==expected==len(seen)
    for key,stats in snapshot['per_key'].items():
        assert stats['requests']==sent[key]
        assert stats['translated_lines']==sum(count for (k,d),count in saved.items() if k==key)
        for f in stats['files']:
            assert f['translated_lines']==saved[key,f['document_id']]
            assert f['failed_lines']==f['unknown_lines']==f['in_flight_lines']==0
    assert snapshot['translated_lines']==sum(bool(r['translation']) for doc in docs for r in store.lines(doc))
    assert len([q for q in queries if q.startswith('SELECT a.state,a.diagnostics')])==1
    before=time.perf_counter()
    for _ in range(100):pool.monitor_snapshot(30)
    mean=(time.perf_counter()-before)/100
    assert mean<.03
    evidence=Path('artifacts/kira-live-monitor');evidence.mkdir(parents=True,exist_ok=True)
    (evidence/f'load-{key_count}-{file_count}.json').write_text(json.dumps(dict(mock_only=True,
        peak_http=peak,requests=expected,mean_snapshot_seconds=mean,snapshot=snapshot),indent=2),encoding='utf-8')
    store.db.set_trace_callback(None);store.close()


def test_two_keys_same_121_docx_live_and_restart(tmp_path,monkeypatch):
    store,doc,run,jobs=fixture_docx(tmp_path)
    for key in store.kira_keys():store.set_kira_account_scope(key['id'],key['id'])
    async def handler(req):await asyncio.sleep(.004);return success(req)
    scheduler,pool=start(store,run,jobs,handler,account_limit=30)
    scheduler.join(15);snapshot=pool.monitor_snapshot(30)
    assert sorted(s['requests'] for s in snapshot['per_key'].values())==[20,21]
    assert sorted(s['files'][0]['translated_lines'] for s in snapshot['per_key'].values())==[60,61]
    assert snapshot['translated_lines']==snapshot['unique_translated_lines']==121
    assert snapshot['requests']==snapshot['successful_requests']==41
    store.close();store=Store(tmp_path/'synthetic.db')
    import transcomic.security as security
    monkeypatch.setattr(security,'unprotect_key',lambda value:pytest.fail('monitor must not decrypt'))
    recovered=load_latest(store)
    assert recovered['state']=='finished' and recovered['busy']==0
    assert recovered['translated_lines']==recovered['unique_translated_lines']==121
    assert [s['files'] for s in recovered['per_key'].values()]==[s['files'] for s in snapshot['per_key'].values()]
    store.close()


@pytest.mark.parametrize('failure',['quota','rate','504','timeout','wrong_id'])
def test_failure_and_unknown_are_not_successful_lines(tmp_path,failure):
    store,docs,run,jobs=setup(tmp_path,2,1,files=4,batches=3)
    failed=[];seen=[]
    async def handler(req):
        ids=tuple(r['id'] for r in lines(req));seen.append(ids)
        await asyncio.sleep(.003)
        if req.headers['authorization'].endswith('0000-not-real') and not failed:
            failed.append(ids)
            if failure=='timeout':raise httpx.ReadTimeout('fixture',request=req)
            if failure=='504':return httpx.Response(504)
            if failure=='quota':return httpx.Response(429,json={'error':{'code':'insufficient_quota'}})
            if failure=='rate':return httpx.Response(429,headers={'retry-after':'1'},json={'error':{'code':'rate_limit'}})
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[{'id':'foreign','text':'A translated story'}]})}}]})
        return success(req)
    scheduler,pool=start(store,run,jobs,handler)
    if failure=='timeout':wait_for(lambda:scheduler._paused.is_set());scheduler.resume()
    scheduler.join(15);assert not scheduler._thread.is_alive()
    snapshot=pool.monitor_snapshot(30)
    assert len(seen)==len(set(seen))==snapshot['requests']
    files=[f for s in snapshot['per_key'].values() for f in s['files']]
    unknown=failure in ('504','timeout')
    assert sum(f['unknown_lines'] for f in files)==(len(failed[0]) if unknown else 0)
    assert sum(f['failed_lines'] for f in files)==(0 if unknown else len(failed[0]))
    assert snapshot['unknown_requests']==int(unknown) and snapshot['failed_requests']==int(not unknown)
    assert snapshot['translated_lines']==sum(bool(r['translation']) for doc in docs for r in store.lines(doc))
    assert all(f['in_flight_lines']==0 for f in files)
    store.close()


@pytest.mark.parametrize('failure_site',['write','commit'])
def test_200_commit_failure_never_increments_saved_lines(tmp_path,monkeypatch,failure_site):
    store,docs,run,jobs=setup(tmp_path,1,1,files=1)
    if failure_site=='write':
        def fail(*args):raise RuntimeError('Synthetic write failure')
        monkeypatch.setattr(store,'complete_attempt',fail)
    else:
        original=store.transaction;complete=store.complete_attempt;armed=False
        def complete_then_fail(*args):
            nonlocal armed
            complete(*args);armed=True
        @contextmanager
        def fail_commit():
            nonlocal armed
            nested=store.db.in_transaction
            with original():
                yield
                if armed and not nested:
                    armed=False
                    raise RuntimeError('Synthetic failure before outer COMMIT')
        monkeypatch.setattr(store,'transaction',fail_commit)
        monkeypatch.setattr(store,'complete_attempt',complete_then_fail)
    scheduler,pool=start(store,run,jobs,success);scheduler.join(8)
    assert not scheduler._thread.is_alive()
    snapshot=pool.monitor_snapshot(1)
    assert snapshot['translated_lines']==snapshot['unique_translated_lines']==0
    assert snapshot['failed_requests']==1 and snapshot['successful_requests']==0
    assert all(not r['translation'] for r in store.lines(docs[0]))
    assert not pool.busy[next(iter(pool.busy))]
    store.close()


def test_pause_stop_keep_actual_inflight_and_do_not_complete_queued(tmp_path):
    store,docs,run,jobs=setup(tmp_path,2,2,files=6,batches=4)
    gate=threading.Event();sent=[]
    async def handler(req):
        sent.append(tuple(r['id'] for r in lines(req)))
        while not gate.is_set():await asyncio.sleep(.002)
        return success(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        wait_for(lambda:len(sent)==4);scheduler.pause();snapshot=pool.monitor_snapshot(2)
        assert snapshot['state']=='user_paused' and snapshot['busy']==4
        assert sum(s['in_flight_lines'] for s in snapshot['per_key'].values())==12
        scheduler.stop();assert pool.monitor_snapshot(2)['busy']==4
    finally:gate.set()
    scheduler.join(10);snapshot=pool.monitor_snapshot(2)
    assert snapshot['state']=='stopped' and snapshot['requests']==4 and snapshot['translated_lines']==12
    assert snapshot['busy']==snapshot['active_files']==0
    store.close()


@pytest.mark.parametrize('resume_at',['slot_released','phase_drained'])
def test_pause_after_last_response_stays_paused_until_resume(tmp_path,resume_at):
    store,docs,run,jobs=setup(tmp_path,1,1,files=1)
    gate=threading.Event()
    async def handler(req):
        while not gate.is_set():await asyncio.sleep(.002)
        return success(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        wait_for(lambda:scheduler.active_http==1)
        scheduler.pause();gate.set();wait_for(lambda:not any(pool.busy.values()))
        if resume_at=='phase_drained':wait_for(lambda:store.job(jobs[0])['state']=='finished')
        assert scheduler._thread.is_alive() and pool.monitor_snapshot(1)['state']=='user_paused'
        scheduler.resume();scheduler.join(8)
        assert not scheduler._thread.is_alive() and store.run(run)['state']=='finished'
        assert pool.monitor_snapshot(1)['state']=='finished'
    finally:gate.set();scheduler.stop();scheduler.join(5)
    store.close()


def test_manual_edit_and_duplicate_terminal_diagnostics_do_not_change_counts(tmp_path):
    store,docs,run,jobs=setup(tmp_path,1,1,files=1)
    first=store.lines(docs[0])[0]['id']
    def handler(req):store.edit_line(first,'translation','Manual edit wins');return success(req)
    scheduler,pool=start(store,run,jobs,handler);scheduler.join(8)
    snapshot=pool.monitor_snapshot(1)
    assert snapshot['translated_lines']==snapshot['unique_translated_lines']==2
    assert store.line(first)['translation']=='Manual edit wins'
    attempt=store.attempts(store.batches(jobs[0])[0]['id'])[0]
    original=attempt['diagnostics']['monitor']
    assert original['state']=='REJECTED'
    assert not pool.monitor.complete(original)
    store.complete_attempt(attempt['id'],{'monitor':{**original,'accepted_ids':[]}})
    assert store.attempts(store.batches(jobs[0])[0]['id'])[0]['diagnostics']['monitor']==original
    store.close()


def test_normalization_rejection_is_failed_data_not_a_revision_rejection(tmp_path):
    store,docs,run,jobs=setup(tmp_path,1,1,files=1)
    def handler(req):
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[
            {'id':r['id'],'text':'...'} for r in lines(req)]})}}]})
    scheduler,pool=start(store,run,jobs,handler);scheduler.join(8)
    snapshot=pool.monitor_snapshot(1);file=next(iter(snapshot['per_key'].values()))['files'][0]
    assert snapshot['translated_lines']==snapshot['successful_requests']==0
    assert file['failed_lines']==3 and file['rejected_lines']==0
    assert snapshot['failed_requests']==1
    store.close()


@pytest.mark.parametrize('sent',[False,True])
def test_crash_recovery_classifies_prepared_and_sent_without_dispatch(tmp_path,sent):
    store,docs,run,jobs=setup(tmp_path,1,1,files=1)
    pool=KiraPoolProvider(store,'mock');key=store.kira_keys()[0]['id']
    batch=store.batches(jobs[0])[0];claimed=store.claim_batch(batch['id']);aid=store.prepare_attempt(batch['id'],1)
    r=record(aid,key,docs[0],ids=tuple(x['id'] for x in claimed));r.update(run_id=run,job_id=jobs[0],batch_id=batch['id'])
    pool.monitor.begin(run);pool.monitor.claim(r)
    if sent:pool.monitor.sent(aid)
    r=dict(pool.monitor.attempts[aid])
    with store.transaction():store.db.execute('UPDATE request_attempts SET diagnostics=? WHERE id=?',(json.dumps({'monitor':r}),aid))
    save_summary(store,pool.monitor_snapshot(1));store.close()
    store=Store(tmp_path/'state.db');recovered=load_latest(store)
    assert recovered['state']=='interrupted' and recovered['busy']==0
    assert recovered['translated_lines']==0 and recovered['requests']==int(sent)
    assert recovered['unknown_requests']==int(sent)
    assert recovered['per_key'][key]['latency_samples']==0
    assert recovered['per_key'][key]['files'][0]['unknown_lines']==(3 if sent else 0)
    store.close()


def test_recovery_recalculates_latency_from_durable_records_not_stale_summary(tmp_path):
    store,docs,run,jobs=setup(tmp_path,1,1,files=1)
    scheduler,pool=start(store,run,jobs,success);scheduler.join(8)
    actual=pool.monitor_snapshot(1);key=store.kira_keys()[0]['id']
    stale=json.loads(json.dumps(actual));stale['per_key'][key]['mean_seconds']=999
    stale['per_key'][key]['error_rate']=1
    save_summary(store,stale)
    recovered=load_latest(store)
    assert recovered['per_key'][key]['mean_seconds']==actual['per_key'][key]['mean_seconds']
    assert recovered['per_key'][key]['error_rate']==0
    store.close()


def test_intentional_retranslation_starts_separate_run(tmp_path):
    store,docs,run,jobs=setup(tmp_path,1,1,files=1)
    scheduler,pool=start(store,run,jobs,success);scheduler.join(8)
    old=pool.monitor_snapshot(1);ids=[r['id'] for r in store.lines(docs[0])]
    job=store.create_job(docs[0],'mock','vi','en',1,ids,provider='kira')
    scheduler=Scheduler(store,pool);scheduler.start(job);scheduler.join(8)
    current=pool.monitor_snapshot(1)
    assert old['run_id']==run and current['run_id']==job and run!=job
    assert current['translated_lines']==current['unique_translated_lines']==3
    assert current['requests']==1
    assert sum(s['retranslation_requests'] for s in current['per_key'].values())==1
    assert store.db.execute('SELECT COUNT(*) FROM kira_monitor_runs').fetchone()[0]==2
    store.close()


def test_duplicate_file_names_two_languages_through_real_scheduler(tmp_path):
    store=Store(tmp_path/'state.db');store.add_kira_keys('sk-locale-A sk-locale-B')
    store.set_setting('concurrency','2');docs=[]
    for folder in ('a','b'):
        docs.append(store.import_document(tmp_path/folder/'same.txt',decode_txt('Nguồn một\nNguồn hai\nNguồn ba'.encode()),'vi','en')[0])
    run,jobs=store.create_run(docs,['en','id'],provider='kira',model='mock',source_lang='vi',concurrency=2,config={'kira_multi_key':True})
    def handler(req):
        text='Kisah terjemahan berlanjut dengan tenang' if 'Indonesian' in json.loads(req.content)['messages'][0]['content'] else 'The translated story continues'
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'lines':[
            {'id':r['id'],'text':text} for r in reversed(lines(req))]})}}]})
    scheduler,pool=start(store,run,jobs,handler);scheduler.join(10)
    snapshot=pool.monitor_snapshot(2)
    files=[f for s in snapshot['per_key'].values() for f in s['files']]
    assert snapshot['state']=='finished' and snapshot['translated_lines']==12
    assert len({f['document_id'] for f in files})==4
    assert {f['target_language'] for f in files}=={'en','id'}
    assert {f['name'] for f in files}=={'same.txt'}
    assert snapshot['unique_translated_lines']==12
    store.close()


def test_fast_key_keeps_working_and_snapshot_is_detached(tmp_path):
    store,doc,run,jobs=fixture_docx(tmp_path/'long');store.set_setting('concurrency','1')
    gate=threading.Event();calls=Counter()
    async def handler(req):
        alias='slow' if req.headers['authorization'].endswith('distribution-A') else 'fast'
        calls[alias]+=1
        if alias=='slow':
            while not gate.is_set():await asyncio.sleep(.002)
        return success(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        wait_for(lambda:calls['fast']==40 and pool.monitor_snapshot(1)['translated_lines']==118)
        snapshot=pool.monitor_snapshot(1)
        assert snapshot['translated_lines']==118 and snapshot['busy']==1
        slow=next(s for s in snapshot['per_key'].values() if s['in_flight_lines'])
        assert slow['in_flight_lines']==3 and slow['files'][0]['in_flight_lines']==3
        slow['files'][0]['in_flight_lines']=999
        assert sum(s['in_flight_lines'] for s in pool.monitor_snapshot(1)['per_key'].values())==3
    finally:gate.set()
    scheduler.join(10);assert pool.monitor_snapshot(1)['translated_lines']==121
    store.close()


def test_safe_exit_cancel_preserves_unknown_attribution(tmp_path):
    store,docs,run,jobs=setup(tmp_path,2,2,files=3,batches=3)
    async def handler(req):await asyncio.sleep(30);return success(req)
    scheduler,pool=start(store,run,jobs,handler)
    wait_for(lambda:scheduler.active_http==4)
    scheduler.cancel_inflight();scheduler.join(8)
    snapshot=pool.monitor_snapshot(2)
    assert not scheduler._thread.is_alive() and snapshot['busy']==0
    assert snapshot['unknown_requests']==4 and snapshot['translated_lines']==0
    assert sum(f['unknown_lines'] for s in snapshot['per_key'].values() for f in s['files'])==12
    assert load_latest(store)['unknown_requests']==4
    store.close()


def test_deleted_contributing_key_can_be_restored_for_run_monitor_only(tmp_path):
    store,docs,run,jobs=setup(tmp_path,2,1,files=2)
    scheduler,pool=start(store,run,jobs,success);scheduler.join(8)
    old=pool.monitor_snapshot(1);key=store.kira_keys()[0]['id']
    store.change_kira_key(key,delete=True)
    from transcomic.kira_monitor_store import records_for_run
    new=KiraPoolProvider(store,'mock');new.begin_monitor(run,records_for_run(store,run))
    snapshot=new.monitor_snapshot(1)
    assert snapshot['translated_lines']==old['translated_lines']
    assert snapshot['per_key'][key]['wait_reason']=='removed'
    assert snapshot['per_key'][key]['translated_lines']==old['per_key'][key]['translated_lines']
    assert key not in new.keys  # No credential resurrected.
    store.close()


def test_optional_summary_failure_does_not_interrupt_translation(tmp_path,monkeypatch):
    import sqlite3
    import transcomic.kira_monitor_store as summaries
    store,docs,run,jobs=setup(tmp_path,1,1,files=1)
    def unavailable(*args):raise sqlite3.OperationalError('Synthetic summary write failure')
    monkeypatch.setattr(summaries,'save_summary',unavailable)
    scheduler,pool=start(store,run,jobs,success);scheduler.join(8)
    snapshot=pool.monitor_snapshot(1)
    assert snapshot['state']=='finished' and snapshot['translated_lines']==3
    assert snapshot['persistence_error']
    assert len([e for e in store.log.snapshot() if e['event']=='monitor_persistence_error'])==1
    store.close()


@pytest.mark.parametrize('summary_failure',[False,True])
def test_shutdown_fence_retires_late_callback_without_losing_attribution(tmp_path,monkeypatch,summary_failure):
    store,docs,run,jobs=setup(tmp_path,1,1,files=1)
    gate=threading.Event();entered=threading.Event()
    async def handler(req):
        entered.set()
        while not gate.is_set():await asyncio.sleep(.002)
        return success(req)
    scheduler,pool=start(store,run,jobs,handler)
    try:
        # active_http is incremented before the pool persists its sent marker.
        # Fence only after the mock transport really entered the HTTP handler;
        # otherwise this tests the legitimate cancelled-before-send branch.
        wait_for(entered.is_set)
        if summary_failure:
            import sqlite3
            import transcomic.kira_monitor_store as summaries
            def unavailable(*args):raise sqlite3.OperationalError('Synthetic summary failure')
            monkeypatch.setattr(summaries,'save_summary',unavailable)
        scheduler.fence_shutdown()
        assert pool.monitor_snapshot(1)['unknown_requests']==1
    finally:gate.set()
    scheduler.join(8)
    assert not scheduler._thread.is_alive()
    assert not any(r['translation'] for r in store.lines(docs[0]))
    recovered=load_latest(store)
    assert recovered['unknown_requests']==1 and recovered['translated_lines']==0
    assert recovered['busy']==0
    store.close()
