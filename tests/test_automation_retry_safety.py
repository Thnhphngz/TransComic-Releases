"""Admission, account limits and persisted retry intent across app objects."""
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import httpx
import pytest
from transcomic.automation.adapters import Translation,Kokoro,Capcut
from transcomic.automation.controller import Controller
from transcomic.automation.repository import Repository
from transcomic.storage import Store
from transcomic.tts.storage import TtsStore
from transcomic.kira_pool import KiraPoolProvider
from transcomic.documents import decode_txt
from test_automation import setup,add_group,run,FakeEngine
from test_automation_retranslation import until,block_other
from test_kira_auto_recovery import response,request_lines


@pytest.mark.parametrize('status',[429,504])
@pytest.mark.parametrize('switch',[False,True])
def test_requested_retry_uses_live_keys_and_obeys_retry_after(setup,tmp_path,status,switch):
    repo,id,s,c=setup;gid,_,_=add_group(repo,id,tmp_path/'g',count=1);other,_,_=add_group(repo,id,tmp_path/'other',count=1)
    target=repo.store.lines(repo.group(gid)['document_id'])[0]['id'];repo.store.edit_line(target,'translation','The translated story continues')
    release=threading.Event();block_other(s,other,release);calls=[]
    def http(req):
        payload=request_lines(req)
        if payload[0]['id']==target:
            calls.append((time.monotonic(),req.headers['authorization']))
            if len(calls)==1:return httpx.Response(status,headers={'Retry-After':'.12'})
        return response(req)
    s.translation=Translation(repo,lambda store,job:KiraPoolProvider(store,'mock',transport=httpx.MockTransport(http),rpm=100000,tpm=100000000),network_probe=lambda _:True);s.translation.backoff=lambda _:0
    try:
        assert c.validate(id)['passed'];c.start(id)
        until(lambda:s.translation.scheduler and s.translation.scheduler._thread and not s.translation.scheduler._thread.is_alive())
        if switch:
            old=repo.store.kira_keys()[0]['id'];repo.store.kira_key_status(old,'QUOTA_EXHAUSTED',reason='Synthetic verified quota')
            with pytest.raises(ValueError,match='API key'):c.enqueue_retry([target])
            assert c.retry_requests(id)==[]
            repo.store.add_kira_keys('synthetic-replacement-key')
        assert c.enqueue_retry([target])==1
        until(lambda:len(calls)==2,timeout=8);release.set();c.join(10)
        assert not c.busy and repo.workset(id)['state']=='completed',repo.events(id)[:3]
        assert calls[1][0]-calls[0][0]>=.11
        if switch:assert all(key=='Bearer synthetic-replacement-key' for _,key in calls)
        else:assert calls[0][1]==calls[1][1]
        assert len(c.retry_requests(id))==1
    finally:release.set()


def test_external_document_is_rejected_without_changing_owner_or_queue(setup,tmp_path):
    repo,id,s,c=setup;other,_,_=add_group(repo,id,tmp_path/'other',count=1)
    external=repo.store.import_document(tmp_path/'external.txt',decode_txt(b'External synthetic source'),'vi','en')[0]
    line=repo.store.lines(external)[0]['id'];release=threading.Event();block_other(s,other,release)
    try:
        assert c.validate(id)['passed'];c.start(id)
        with pytest.raises(ValueError,match='không thuộc'):c.enqueue_retry([line])
        with pytest.raises(ValueError,match='Automation'):repo.store.create_job(external,'mock','vi','en',1,[line])
        assert c.retry_requests(id)==[] and repo.active()==id
    finally:release.set();c.join(10)


@pytest.mark.parametrize('manual_completed',[False,True])
def test_new_connections_recover_pending_request_and_preserve_newer_manual_result(setup,tmp_path,manual_completed):
    repo,id,s,c=setup;gid,_,_=add_group(repo,id,tmp_path/'g',count=1);run(c,id)
    doc=repo.group(gid)['document_id'];row=repo.store.lines(doc)[0]
    # This is the exact durable intent written by enqueue_retry before dispatch.
    request=dict(id='synthetic-crash-intent',line_ids=[row['id']],state='pending',started=False,revisions={row['id']:row['translation_revision']})
    c.checkpoint(id,translation_retries=[request]);repo.state(id,'interrupted')
    if manual_completed:repo.store.edit_line(row['id'],'translation','The newer manual correction must be preserved')
    fresh_store=Store(repo.store.path);fresh_tts=TtsStore(s.tts_store.path);reopened=None
    try:
        fresh=Repository(fresh_store);fresh.tts_store=fresh_tts;fresh_tts.automation=fresh;calls=[]
        def http(req):calls.extend(r['id'] for r in request_lines(req));return response(req)
        services=SimpleNamespace(tts_store=fresh_tts,translation=Translation(fresh,lambda store,job:KiraPoolProvider(store,'mock',transport=httpx.MockTransport(http),rpm=100000,tpm=100000000),network_probe=lambda _:True),kokoro=Kokoro(fresh,fresh_tts,None,engine_factory=FakeEngine),capcut=Capcut(fresh,fresh_tts),preflight=lambda _:None)
        reopened=Controller(fresh,services);services.translation.backoff=lambda _:0
        assert reopened.retry_requests(id)==[request] and not reopened.busy
        run(reopened,id)
        assert fresh.workset(id)['state']=='completed',fresh.events(id)[:3]
        assert reopened.retry_requests(id)[0]['state']=='done'
        if manual_completed:
            assert calls==[] and fresh_store.line(row['id'])['translation']=='The newer manual correction must be preserved'
        else:assert calls==[row['id']]
    finally:
        if reopened:reopened.stop();reopened.join(10)
        fresh_tts.close();fresh_store.close()


@pytest.mark.parametrize('failure',[504,'schema'])
def test_explicit_retry_cycle_remains_bounded_at_five_actual_requests(setup,tmp_path,failure):
    from transcomic.providers import KiraProvider
    repo,id,s,c=setup;gid,_,_=add_group(repo,id,tmp_path/'g',count=1);other,_,_=add_group(repo,id,tmp_path/'other',count=1)
    line=repo.store.lines(repo.group(gid)['document_id'])[0]['id'];repo.store.edit_line(line,'translation','The translated story continues')
    release=threading.Event();block_other(s,other,release);calls=[]
    def http(req):
        if request_lines(req)[0]['id']==line:
            calls.append(1)
            return httpx.Response(504) if failure==504 else response(req,[])
        return response(req)
    s.translation=Translation(repo,lambda store,job:KiraProvider('synthetic','mock',transport=httpx.MockTransport(http)),network_probe=lambda _:True);s.translation.backoff=lambda _:0
    try:
        assert c.validate(id)['passed'];c.start(id)
        until(lambda:s.translation.scheduler and s.translation.scheduler._thread and not s.translation.scheduler._thread.is_alive())
        assert c.enqueue_retry([line])==1
        until(lambda:c.retry_requests(id)[0]['state']=='done');release.set();c.join(10)
        assert not c.busy and len(calls)==5
        assert repo.workset(id)['state']=='needs_attention'
        assert repo.store.line(line)['translation']=='The translated story continues'
        mapping=repo.field(gid,'batch_jobs',{})
        assert len(mapping)==1 and next(iter(mapping)).startswith('retry:')
        assert sum(len(repo.store.attempts(b)) for b in repo.batch_ids(next(iter(mapping.values()))))==5
    finally:release.set()


def test_retry_adapter_exception_preserves_durable_request_for_resume(setup,tmp_path,monkeypatch):
    repo,id,s,c=setup;gid,_,_=add_group(repo,id,tmp_path/'g',count=1);other,_,_=add_group(repo,id,tmp_path/'other',count=1)
    line=repo.store.lines(repo.group(gid)['document_id'])[0]['id'];repo.store.edit_line(line,'translation','The translated story continues')
    release=threading.Event();block_other(s,other,release)
    try:
        assert c.validate(id)['passed'];c.start(id)
        until(lambda:s.translation.scheduler and s.translation.scheduler._thread and not s.translation.scheduler._thread.is_alive())
        original=s.translation.run
        def failed(*args,**kwargs):raise OSError('Synthetic local adapter failure')
        monkeypatch.setattr(s.translation,'run',failed)
        assert c.enqueue_retry([line])==1
        until(lambda:c.retry_requests(id)[0]['started']);release.set();c.join(10)
        assert not c.busy and c.retry_requests(id)[0]['state']=='pending'
        monkeypatch.setattr(s.translation,'run',original);run(c,id)
        assert repo.workset(id)['state']=='completed' and c.retry_requests(id)[0]['state']=='done'
    finally:release.set()
