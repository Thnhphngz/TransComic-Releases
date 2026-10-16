"""Synthetic DOCX and MockTransport only; never inspect the user's credentials/data."""
import asyncio
import json
import os
import threading
import time
from collections import Counter
from pathlib import Path

import httpx
import pytest
from docx import Document

from transcomic.docx_document import import_docx
from transcomic.documents import ImportedText, TextLine
from transcomic.kira_pool import KiraPoolProvider
from transcomic.storage import Store
from transcomic.translation import Scheduler
from transcomic.providers import BatchResult
from test_kira_multikey import lines, success, wait_for


def fixture_docx(tmp_path):
    store = Store(tmp_path / 'synthetic.db')
    store.add_kira_keys('fixture-distribution-A fixture-distribution-B')
    store.set_setting('concurrency', '30')
    path = tmp_path / 'synthetic-121.docx'
    word = Document()
    for i in range(121):
        word.add_paragraph(f'Nguồn tổng hợp để kiểm thử dòng {i + 1}')
    word.save(path)
    imported = import_docx(path)
    data = ImportedText(tuple(TextLine(u.text, '') for u in imported.units), 'docx', imported.raw)
    doc = store.import_document(path, data, 'vi', 'en', document_format='docx',
                                locators=[u.locator for u in imported.units])[0]
    run, jobs = store.create_run([doc], ['en'], provider='kira', model='mock',
        source_lang='vi', concurrency=30, config={'kira_multi_key': True})
    assert len(store.lines(doc)) == 121
    assert len(store.batches(jobs[0])) == 41
    return store, doc, run, jobs


@pytest.mark.parametrize('independent', [False, True])
@pytest.mark.parametrize('latency', ['immediate', 'overlapping'])
def test_exact_121_accounts(tmp_path, latency, independent):
    store, doc, run, jobs = fixture_docx(tmp_path)
    ids = [k['id'] for k in store.kira_keys()]
    if independent:
        for key_id in ids: store.set_kira_account_scope(key_id, key_id)
    aliases = {ids[0]: 'Key 1', ids[1]: 'Key 2'}
    auth_alias = {'Bearer fixture-distribution-A': 'Key 1',
                  'Bearer fixture-distribution-B': 'Key 2'}
    counts = Counter(); busy = Counter(); peaks = Counter(); seen = []; peak_total = 0
    gate = threading.Event()

    async def handler(req):
        nonlocal peak_total
        alias = auth_alias[req.headers['authorization']]
        batch = tuple(r['id'] for r in lines(req))
        assert 1 <= len(batch) <= 3
        assert batch not in seen
        seen.append(batch); counts[alias] += 1; busy[alias] += 1
        peaks[alias] = max(peaks[alias], busy[alias]); peak_total = max(peak_total, sum(busy.values()))
        if latency == 'overlapping':
            while not gate.is_set():
                await asyncio.sleep(.002)
        busy[alias] -= 1
        return success(req)

    pool = KiraPoolProvider(store, 'mock', transport=httpx.MockTransport(handler))
    scheduler = Scheduler(store, pool)
    scheduler.start_many(jobs, run)
    if latency == 'overlapping':
        try:
            wait_for(lambda: sum(busy.values()) == (41 if independent else 30))
            assert sorted(counts.values()) == ([20, 21] if independent else [15, 15])
            if not independent:
                wait_for(lambda: all(v['wait_reasons'].get('account_slots_full',0) for v in pool.stats.values()))
        finally:
            gate.set()
    scheduler.join(20)
    assert not scheduler._thread.is_alive()
    assert store.run(run)['state'] == 'finished'
    assert sorted(counts.values()) == [20, 21]
    assert sum(counts.values()) == len(set(seen)) == 41
    snapshot=pool.snapshot(30)
    assert snapshot['maximum']==(60 if independent else 30)
    assert snapshot['accounts']==(2 if independent else 1)
    assert sum(v['successful_requests'] for v in pool.stats.values())==41
    assert sum(v['batches'] for v in pool.stats.values())==41
    assert sum(v['translated_lines'] for v in pool.stats.values())==121
    assert sum(v['errors'] for v in pool.stats.values())==0
    assert all(v['wait_reason']=='no_pending_work' for v in snapshot['per_key'].values())
    summary=[e for e in store.log.snapshot() if e['event']=='kira_distribution']
    assert len(summary)==1
    for secret in ('fixture-distribution-A','fixture-distribution-B'):
        assert secret not in json.dumps(summary) and secret not in json.dumps(snapshot)
    assert all(r['translation'] for r in store.lines(doc))
    assert all(len(store.attempts(b['id'])) == 1 for b in store.batches(jobs[0]))
    out = Path('artifacts/kira-distribution-121'); out.mkdir(parents=True, exist_ok=True)
    phase = os.environ.get('TRANSCOMIC_DISTRIBUTION_PHASE', 'after')
    grouping='independent' if independent else 'shared'
    (out / f'{phase}-{grouping}-{latency}.json').write_text(json.dumps({
        'mock_only': True, 'source': 'generated DOCX, 121 lines',
        'requests': dict(counts), 'peak_http_by_key': dict(peaks), 'peak_http_total': peak_total,
        'configured_per_key': 30, 'account_limit': pool.account_limit, 'rpm': pool.rpm, 'tpm': pool.tpm,
        'unique_batches': len(set(seen)), 'translated_lines': 121, 'effective_capacity':snapshot['maximum'],
        'per_key': {aliases[k]: v for k, v in pool.snapshot(30)['per_key'].items()},
    }, indent=2), encoding='utf-8')
    store.close()


def test_fair_rotation_survives_refresh_and_release_with_one_shared_slot(tmp_path):
    store,_,_,_=fixture_docx(tmp_path)
    ids=[k['id'] for k in store.kira_keys()]
    pool=KiraPoolProvider(store,'mock',account_limit=1)
    selected=[]
    for _ in range(20):
        pool.refresh()
        key,_=pool.reserve(30,1);selected.append(key)
        pool.release(key,BatchResult({}))
    assert selected==ids*10
    store.close()


def test_fast_ready_key_uses_unsent_batches_while_other_key_is_slow(tmp_path):
    store,_,run,jobs=fixture_docx(tmp_path)
    store.set_setting('concurrency','1')
    gate=threading.Event();counts=Counter();seen=[]
    async def handler(req):
        alias='Key 1' if req.headers['authorization'].endswith('distribution-A') else 'Key 2'
        batch=tuple(r['id'] for r in lines(req));assert batch not in seen
        seen.append(batch);counts[alias]+=1
        if alias=='Key 1':
            while not gate.is_set():await asyncio.sleep(.002)
        return success(req)
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler))
    scheduler=Scheduler(store,pool);scheduler.start_many(jobs,run)
    try:
        wait_for(lambda:counts['Key 2']==40)
        assert counts['Key 1']==1 and scheduler._thread.is_alive()
    finally:gate.set()
    scheduler.join(10)
    assert store.run(run)['state']=='finished' and len(set(seen))==41
    assert all(v['peak']==1 for v in pool.stats.values())
    store.close()


def test_partial_and_manual_edit_stats_only_count_accepted_lines(tmp_path):
    store,doc,run,jobs=fixture_docx(tmp_path)
    first=store.lines(doc)[0]['id']
    def handler(req):
        if first in {r['id'] for r in lines(req)}:
            store.edit_line(first,'translation','Manual edit wins')
        return success(req)
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler))
    scheduler=Scheduler(store,pool);scheduler.start_many(jobs,run);scheduler.join(20)
    assert not scheduler._thread.is_alive()
    assert store.line(first)['translation']=='Manual edit wins'
    assert sum(v['successful_requests'] for v in pool.stats.values())==41
    assert sum(v['batches'] for v in pool.stats.values())==40
    assert sum(v['translated_lines'] for v in pool.stats.values())==120
    store.close()


@pytest.mark.parametrize('limit,reason', [('concurrency','account_slots_full'),
    ('rpm','account_rpm'), ('tpm','account_tpm')])
def test_blocked_account_does_not_block_independent_ready_key(tmp_path, limit, reason):
    store, _, _, _ = fixture_docx(tmp_path)
    a,b=[k['id'] for k in store.kira_keys()]
    for key in (a,b):store.set_kira_account_scope(key,key)
    pool=KiraPoolProvider(store,'mock',account_limit=1 if limit=='concurrency' else 30,
        rpm=1 if limit=='rpm' else 60,tpm=100 if limit=='tpm' else 1000000)
    lease=pool.reserve(30,60);assert lease[0]==a
    if limit!='concurrency':pool.release(a)
    while pool._order[0]!=a:pool._order.rotate(-1)
    next_lease=pool.reserve(30,60)
    assert next_lease[0]==b
    assert pool.stats[a]['wait_reasons'][reason]==1
    assert pool.snapshot(30)['per_key'][a]['wait_reason']==reason
    pool.release(b)
    if limit=='concurrency':pool.release(a)
    store.close()


def test_smaller_unsent_batch_can_use_remaining_tpm_after_large_batch_blocked(tmp_path):
    store,_,_,_=fixture_docx(tmp_path)
    pool=KiraPoolProvider(store,'mock',tpm=100)
    key,_=pool.reserve(30,60);pool.release(key)
    assert pool.reserve(30,60) is None
    # Both READY keys share the account, but a smaller candidate still fits.
    lease=pool.reserve(30,20)
    assert lease is not None
    pool.release(lease[0]);store.close()


def test_scoped_budget_and_cooldown_persist_without_cross_account_pause(tmp_path):
    store, _, _, _ = fixture_docx(tmp_path)
    a,b=[k['id'] for k in store.kira_keys()]
    for key in (a,b):store.set_kira_account_scope(key,key)
    pool=KiraPoolProvider(store,'mock',rpm=1)
    assert pool.reserve(30,10)[0]==a
    pool.release(a,BatchResult({},'rate',diagnostics={'failure_kind':'rate_limit','retry_after_seconds':60}))
    store.close();store=Store(tmp_path/'synthetic.db')
    pool=KiraPoolProvider(store,'mock',rpm=1)
    assert pool.snapshot(30)['per_key'][a]['wait_reason']=='account_cooldown'
    assert pool.reserve(30,10)[0]==b
    pool.release(b);store.close();store=Store(tmp_path/'synthetic.db')
    pool=KiraPoolProvider(store,'mock',rpm=1)
    assert pool.reserve(30,10) is None
    assert pool.snapshot(30)['per_key'][b]['wait_reason']=='account_rpm'
    store.close()


def test_regrouping_does_not_reset_known_account_cooldown(tmp_path):
    store,_,_,_=fixture_docx(tmp_path)
    a,b=[k['id'] for k in store.kira_keys()]
    for key in (a,b):store.set_kira_account_scope(key,key)
    pool=KiraPoolProvider(store,'mock')
    key,_=pool.reserve(30,10);assert key==a
    pool.release(a,BatchResult({},'rate',diagnostics={'failure_kind':'rate_limit','retry_after_seconds':60}))
    store.set_kira_account_scope(a,b)
    pool=KiraPoolProvider(store,'mock')
    assert pool.reserve(30,10) is None
    assert pool.snapshot(30)['per_key'][b]['wait_reason']=='account_cooldown'
    store.close()


def test_account_assignment_frozen_until_new_provider_and_same_account_shares(tmp_path):
    store, _, _, _ = fixture_docx(tmp_path)
    a,b=[k['id'] for k in store.kira_keys()]
    pool=KiraPoolProvider(store,'mock',account_limit=1)
    assert pool.reserve(30,10)[0]==a
    store.set_kira_account_scope(b,b);pool.refresh()
    assert pool.scopes[b]=='shared' and pool.reserve(30,10) is None
    pool.release(a)
    new=KiraPoolProvider(store,'mock',account_limit=1)
    assert new.availability(30)[1]==2 and new.scopes[b]==b
    store.set_kira_account_scope(a,a);store.set_kira_account_scope(b,a)
    new=KiraPoolProvider(store,'mock',rpm=1)
    # The reservation made before regrouping still consumes this account budget.
    assert new.reserve(30,10) is None
    assert new.snapshot(30)['per_key'][b]['wait_reason']=='account_rpm'
    store.close()


def test_old_budget_migration_preserves_rows_and_ciphertext(tmp_path):
    import sqlite3
    store, _, _, _ = fixture_docx(tmp_path)
    with store.lock:blobs=[tuple(r) for r in store.db.execute('SELECT id,encrypted FROM kira_keys')]
    store.close()
    db=sqlite3.connect(tmp_path/'synthetic.db')
    db.execute('DROP TABLE kira_reservations')
    db.execute('CREATE TABLE kira_reservations(id TEXT PRIMARY KEY,created_at REAL NOT NULL,tokens INTEGER NOT NULL)')
    db.execute('INSERT INTO kira_reservations VALUES (?,?,?)',('prior-reservation',time.time(),99))
    db.commit();db.close()
    for _ in range(2):
        store=Store(tmp_path/'synthetic.db')
        with store.lock:
            row=store.db.execute('SELECT * FROM kira_reservations').fetchone()
            assert row['id']=='prior-reservation' and row['tokens']==99 and row['account_scope']=='shared'
            assert [tuple(r) for r in store.db.execute('SELECT id,encrypted FROM kira_keys')]==blobs
        assert KiraPoolProvider(store,'mock',rpm=1).reserve(30,1) is None
        for key in store.kira_keys():store.set_kira_account_scope(key['id'],key['id'])
        # Old reservations had no key ownership: regrouping cannot discard them.
        assert KiraPoolProvider(store,'mock',rpm=1).reserve(30,1) is None
        store.close()


@pytest.mark.parametrize('failure',['504','timeout'])
def test_121_unknown_batches_never_resent_on_other_key_or_resume(tmp_path,failure):
    store,doc,run,jobs=fixture_docx(tmp_path)
    store.set_setting('concurrency','1')
    for key in store.kira_keys():store.set_kira_account_scope(key['id'],key['id'])
    seen=[];failed=[]
    async def handler(req):
        batch=tuple(r['id'] for r in lines(req));seen.append(batch)
        await asyncio.sleep(.005)
        if req.headers['authorization'].endswith('distribution-A') and not failed:
            failed.append(batch)
            if failure=='timeout':raise httpx.ReadTimeout('Synthetic timeout',request=req)
            return httpx.Response(504)
        return success(req)
    pool=KiraPoolProvider(store,'mock',transport=httpx.MockTransport(handler))
    scheduler=Scheduler(store,pool);scheduler.start_many(jobs,run)
    if failure=='timeout':
        wait_for(lambda:scheduler._paused.is_set())
        prior=len(seen);time.sleep(.05);assert len(seen)==prior
        scheduler.resume()
    scheduler.join(20)
    assert not scheduler._thread.is_alive()
    assert len(seen)==41 and len(set(seen))==41 and seen.count(failed[0])==1
    assert scheduler.retry_count==0 and store.run(run)['state']=='needs_intervention'
    assert sum(v['errors'] for v in pool.stats.values())==1
    assert sum(v['successful_requests'] for v in pool.stats.values())==40
    assert sum(v['batches'] for v in pool.stats.values())==40
    assert sum(v['translated_lines'] for v in pool.stats.values())==118
    assert not any(pool.busy.values())
    assert all(len(store.attempts(b['id']))==1 for b in store.batches(jobs[0]))
    assert sum(b['state']=='unknown' for b in store.batches(jobs[0]))==1
    report={'mock_only':True,'failure':failure,'requests':len(seen),'unique_batches':len(set(seen)),
        'retry_count':scheduler.retry_count,'unknown_batches':1,'translated_lines':118,
        'per_key':{'Key '+str(i+1):pool.snapshot(30)['per_key'][k['id']] for i,k in enumerate(store.kira_keys())}}
    Path(f'artifacts/kira-distribution-121/{failure}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    store.close()
