"""Rolling admission contract: isolated SQLite, synthetic media, mock HTTP."""
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import threading
import time

import httpx
import pytest

from test_automation import setup,add_group,FakeEngine
from test_deepseek_admission import configure
from test_kira_auto_recovery import request_lines,response
from transcomic.automation.adapters import Translation
from transcomic.deepseek import DeepSeekProvider
from transcomic.deepseek_rolling import RollingAdmission,ROLLING,COHORT,admission_policy,validate_checkpoint
from transcomic.kira_admission import CohortAdmission


def write_evidence(name,data):
    if target:=os.environ.get('ROLLING_EVIDENCE'):
        path=Path(target);path.mkdir(parents=True,exist_ok=True)
        (path/name).write_text(json.dumps(data,indent=2),encoding='utf8')


def test_hundred_files_2000_lines_exact_rolling_sequence_and_immediate_tts(setup,tmp_path):
    repo,wid,services,c=setup;cfg=configure(repo,wid);cfg.update(capcut_mode='split',part_count=4,project_name='Rolling');repo.configure(wid,cfg)
    gids=[add_group(repo,wid,tmp_path/str(i),f'{i:03}',20)[0] for i in range(100)]
    docs=[repo.group(g)['document_id'] for g in gids];rows=[repo.store.lines(d) for d in docs]
    owners={r['id']:i for i,units in enumerate(rows) for r in units}
    sources=[repo.store.document(d)['source_instance'] for d in docs]
    source_index={source:i for i,source in enumerate(sources)}
    finals={units[-1]['id'] for units in rows};seen=Counter();started=set();final_started=set()
    permit=[threading.Event() for _ in docs];all_release=threading.Event();voice=threading.Event()
    FakeEngine.entered=voice;FakeEngine.release=threading.Event();FakeEngine.release.set()
    trace=[];active=Counter();peak_files=0;peak_http=0;emit=repo.store.log.emit
    def record(event,**kw):
        if event in ('source_completed','source_admitted','source_job_loaded','cohort_unlocked'):
            trace.append(dict(event=event,time=time.time(),monotonic=time.monotonic(),**kw))
        return emit(event,**kw)
    repo.store.log.emit=record
    async def handler(req):
        nonlocal peak_files,peak_http
        units=request_lines(req);n=owners[units[0]['id']];started.add(n);seen.update(r['id'] for r in units)
        assert len(units)<=5
        active[n]+=1;peak_files=max(peak_files,len(active));peak_http=max(peak_http,sum(active.values()))
        trace.append(dict(event='http',index=n+1,time=time.time(),source_instance=sources[n],
                          job_id=next(j['id'] for j in repo.store.jobs() if j['document_id']==docs[n])))
        try:
            if any(r['id'] in finals for r in units):
                final_started.add(n)
                while not all_release.is_set() and not permit[n].is_set():await asyncio.sleep(.003)
            return response(req)
        finally:
            active[n]-=1
            if not active[n]:del active[n]
    services.translation=Translation(repo,lambda st,j:DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler),batch_size=5),network_probe=lambda _:True)
    def wait(condition,seconds=15):
        until=time.monotonic()+seconds
        while not condition() and time.monotonic()<until:time.sleep(.01)
        assert condition(),repo.events(wid)[:3]
    assert c.validate(wid)['passed'];c.start(wid)
    try:
        wait(lambda:len(final_started)==10)
        assert started==set(range(10))
        sequence=[]
        for finished,opened in ((2,10),(6,11),(0,12),(11,13)):
            permit[finished].set();wait(lambda:opened in started)
            certified=[i for i,d in enumerate(docs) if all(r['state']=='done' for r in repo.store.lines(d))]
            assert set(certified)=={i for i in (2,6,0,11) if permit[i].is_set()}
            assert started==set(range(opened+1))
            assert len(services.translation.scheduler.admission.active)<=10
            sequence.append(dict(completed=finished+1,opened=opened+1,time=time.time(),
                                 completed_source=sources[finished],opened_source=sources[opened],
                                 completed_job=next(j['id'] for j in repo.store.jobs() if j['document_id']==docs[finished]),
                                 opened_job=next(j['id'] for j in repo.store.jobs() if j['document_id']==docs[opened])))
            if finished==2:
                assert voice.wait(5),'File 3 must reach TTS while the other nine files are blocked'
                assert not all_release.is_set() and len(certified)==1
        all_release.set();c.join(180)
        assert not c.busy and repo.workset(wid)['state']=='completed',repo.events(wid)[:5]
        gate=services.translation.scheduler.admission
        assert gate.complete==set(sources) and peak_files<=10 and peak_http<=30
        assert len(seen)==2000 and set(seen.values())=={1}
        assert len(FakeEngine.calls)==2000 and len(repo.store.jobs())==100
        assert len([a for a in repo.artifacts(wid) if a['kind']=='capcut' and a['state']=='complete'])==4
        completed=[e for e in trace if e['event']=='source_completed'];assert len(completed)==100
        assert all(e['job_id'] and e['source_instance'] in source_index for e in completed)
        admitted=[e for e in trace if e['event']=='source_admitted']
        assert len(admitted)==100 and all(e['job_id'] for e in admitted)
        assert not any(e['event']=='cohort_unlocked' for e in trace)
        jobs=[dict(index=i+1,source_instance=sources[i],job_id=next(j['id'] for j in repo.store.jobs() if j['document_id']==d)) for i,d in enumerate(docs)]
        assert all(json.loads(j['config'])['deepseek_admission_policy']==ROLLING for j in repo.store.jobs())
        write_evidence('rolling-100files-2000lines.json',dict(status='PASS',sequence=sequence,events=trace,jobs=jobs,
                        peak_active_http_files=peak_files,peak_http_requests=peak_http,accepted_rows=2000,tts_calls=len(FakeEngine.calls),
                        requests=sum(seen.values())//5,completed=100,duplicate_accepted_rows=0,capcut_parts=4))
    finally:all_release.set();c.stop();c.join(10)


def test_rolling_releases_one_slot_while_kira_keeps_nine_of_ten_barrier():
    order=list(map(str,range(100)));rolling=RollingAdmission(order);kira=CohortAdmission(order)
    ready=set(order)
    assert rolling.refresh(set(),ready,set())==kira.refresh(set(),ready,set())==order[:10]
    assert '10' in rolling.refresh({'2'},ready,set(order[:10])-{'2'})
    assert '10' not in kira.refresh({'2'},ready,set(order[:10])-{'2'})
    assert '10' in kira.refresh(set(order[:9]),ready,{'9'})
    write_evidence('kira-cohort-comparison.json',dict(status='PASS',rolling_after_one=rolling.snapshot(),
                   kira_after_nine=kira.snapshot(),kira_after_one_admits_eleven=False))


def test_rolling_cooldown_is_bounded_and_restores_old_files_first():
    order=list(map(str,range(100)));gate=RollingAdmission(order);gate.refresh([],order,[])
    gate.refresh([],order[10:],[])
    assert gate.parked==set(order[:10]) and gate.active==set(order[10:20])
    gate.refresh([],order[20:],[])
    assert len(gate.opened)==20 and len(gate.active)==10 and len(gate.parked)==10
    gate.refresh([],order,[])
    assert gate.active==set(order[:10]) and gate.parked==set(order[10:20])
    state=json.loads(json.dumps(gate.snapshot()));validate_checkpoint(order,state,ROLLING)
    resumed=RollingAdmission(order,state);resumed.refresh([],order,[])
    assert resumed.snapshot()==state


@pytest.mark.parametrize('revoked',[1,100])
def test_restart_rechecks_saved_completion_and_readmits_changed_revisions(revoked):
    order=list(map(str,range(100)))
    state=dict(version=1,admission_policy=ROLLING,order=order,opened=order,active=[],parked=[],complete=order)
    validate_checkpoint(order,state,ROLLING);gate=RollingAdmission(order,state)
    certified=set(order[revoked:]);gate.refresh(certified,order,[])
    assert gate.active==set(order[:min(revoked,10)])
    assert gate.complete==certified and gate.opened==certified|gate.active
    assert not gate.parked


@pytest.mark.parametrize('policy',[None,COHORT,ROLLING])
def test_frozen_policy_and_checkpoint_validation(policy):
    expected=COHORT if policy is None else policy;assert admission_policy(policy)==expected
    gate=RollingAdmission(['a','b']) if expected==ROLLING else CohortAdmission(['a','b'])
    gate.refresh([],['a','b'],[]);saved=gate.snapshot()
    validate_checkpoint(['a','b'],saved,expected)
    with pytest.raises(ValueError):validate_checkpoint(['b','a'],saved,expected)
    with pytest.raises(ValueError):validate_checkpoint(['a','b'],saved,COHORT if expected==ROLLING else ROLLING)
    saved['active'].append('outside');
    with pytest.raises(ValueError):validate_checkpoint(['a','b'],saved,expected)


@pytest.mark.parametrize('invalid',[{},dict(version=2,mode='rolling'),dict(version=1,mode='unbounded')])
def test_unknown_policy_fails_closed(invalid):
    with pytest.raises(ValueError):admission_policy(invalid)


@pytest.mark.parametrize('conflict',['policy','order','mixed_jobs'])
def test_conflicting_durable_policy_refuses_admission_before_enqueue(setup,tmp_path,conflict):
    from types import SimpleNamespace
    from transcomic.deepseek_admission import DeepSeekAdmission
    from transcomic.deepseek import MODEL
    repo,wid,services,c=setup;cfg=configure(repo,wid)
    docs=[repo.group(add_group(repo,wid,tmp_path/str(i),f'{i:03}',3)[0])['document_id'] for i in range(2)]
    order=[repo.store.document(d)['source_instance'] for d in docs];jobs={}
    for i,doc in enumerate(docs):
        policy=COHORT if conflict=='mixed_jobs' and i==1 else ROLLING
        jid=repo.store.create_job(doc,MODEL,'vi','en',30,provider='deepseek',
                  config=dict(automation_owner=wid,deepseek_admission_policy=policy),allow_shared_document=True)
        jobs[jid]=repo.store.job(jid)
    gate=CohortAdmission(order) if conflict=='policy' else RollingAdmission(list(reversed(order)) if conflict=='order' else order)
    gate.refresh([],order,[]);cp=repo.workset(wid)['checkpoint'];cp['deepseek_admissions']={'1':gate.snapshot()}
    repo.execute('UPDATE automation_worksets SET checkpoint=? WHERE id=?',(json.dumps(cp),wid))
    scheduler=SimpleNamespace(store=repo.store,source_order=order,admission_key='1',loader_complete=set())
    with pytest.raises(ValueError):DeepSeekAdmission(scheduler,jobs,lambda _:pytest.fail('Admission must not enqueue a conflicting job'))
    assert repo.rows('SELECT COUNT(*) n FROM request_attempts')[0]['n']==0
    assert {j['id']:j['config'] for j in repo.store.jobs()}=={j:v['config'] for j,v in jobs.items()}


def test_creation_marker_is_scoped_and_does_not_backfill_existing_worksets(setup):
    repo,wid,services,c=setup
    assert repo.workset(wid)['checkpoint']['deepseek_admission_policy']==ROLLING
    repo.execute("UPDATE automation_worksets SET checkpoint='{}' WHERE id=?",(wid,))
    configure(repo,wid)
    assert 'deepseek_admission_policy' not in repo.workset(wid)['checkpoint']
    assert admission_policy(repo.workset(wid)['checkpoint'].get('deepseek_admission_policy'))==COHORT
    new=repo.create('New DeepSeek',repo.workset(wid)['config'])
    assert repo.workset(new)['checkpoint']['deepseek_admission_policy']==ROLLING


def test_completed_workset_rechecks_changed_source_without_replaying_other_rows(setup,tmp_path):
    repo,wid,services,c=setup;configure(repo,wid)
    groups=[add_group(repo,wid,tmp_path/str(i),f'{i:03}',9) for i in range(12)]
    seen=Counter()
    def handler(req):
        seen.update(r['id'] for r in request_lines(req));return response(req)
    services.translation=Translation(repo,lambda st,j:DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler),batch_size=5),network_probe=lambda _:True)
    assert c.validate(wid)['passed'];c.start(wid);c.join(25)
    try:
        assert not c.busy and repo.workset(wid)['state']=='completed'
        jobs={j['id'] for j in repo.store.jobs()};before=Counter(seen);voices=len(FakeEngine.calls)
        doc=repo.group(groups[0][0])['document_id'];changed=repo.store.lines(doc)[1]['id']
        affected=next(b['payload'] for j in repo.store.jobs() if j['document_id']==doc for b in repo.store.batches(j['id'])
                      if any(r['id']==changed for r in b['payload']))
        path=groups[0][1];lines=path.read_text(encoding='utf8').splitlines();lines[1]='Văn bản nguồn đã thay đổi trong cùng bố cục';path.write_text('\n'.join(lines),encoding='utf8')
        assert c.validate(wid)['passed'];c.start(wid);c.join(25)
        assert not c.busy and repo.workset(wid)['state']=='completed',repo.events(wid)[:3]
        # Preserve the existing source-revision rule: the affected saved batch
        # is invalidated together; all still-valid batches must remain untouched.
        assert seen-before==Counter(r['id'] for r in affected)
        assert jobs<{j['id'] for j in repo.store.jobs()} and len(repo.store.jobs())==13
        assert len(FakeEngine.calls)==voices,'Same mock translated text must reuse verified WAVs'
        write_evidence('changed-source-recovery.json',dict(status='PASS',original_job_ids=list(jobs),changed_line_id=changed,
                        invalidated_batch_ids=[r['id'] for r in affected],additional_row_sends=sum((seen-before).values()),new_jobs=1,resynthesized_wavs=0))
    finally:c.stop();c.join(8)


@pytest.mark.parametrize('legacy',[False,True])
def test_stop_close_reopen_resume_keeps_jobs_attempts_and_committed_rows(setup,tmp_path,legacy):
    from types import SimpleNamespace
    from transcomic.storage import Store
    from transcomic.automation.repository import Repository
    from transcomic.automation.controller import Controller
    from transcomic.automation.adapters import Kokoro,Capcut
    repo,wid,services,c=setup;configure(repo,wid)
    if legacy:repo.execute("UPDATE automation_worksets SET checkpoint='{}' WHERE id=?",(wid,))
    expected=COHORT if legacy else ROLLING
    docs=[repo.group(add_group(repo,wid,tmp_path/str(i),f'{i:03}',10)[0])['document_id'] for i in range(12)]
    first=repo.store.lines(docs[0])[0]['id'];saved=threading.Event();release=threading.Event();seen=Counter();emit=repo.store.log.emit
    def log(event,**kw):
        if event=='saved' and first in kw.get('accepted_ids',()):saved.set()
        return emit(event,**kw)
    repo.store.log.emit=log
    async def handler(req):
        ids=[r['id'] for r in request_lines(req)];seen.update(ids)
        while first not in ids and not release.is_set():await asyncio.sleep(.003)
        return response(req)
    def make(st,j):return DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler),batch_size=5)
    services.translation=Translation(repo,make,network_probe=lambda _:True)
    assert c.validate(wid)['passed'];c.start(wid)
    reopened=None;resumed=None
    try:
        assert saved.wait(10);c.pause();assert c.paused.is_set()
        c.stop();release.set();c.join(12);assert not c.busy
        original=repo.store;accepted={r['id']:dict(r) for d in docs for r in original.lines(d) if r['state']=='done'}
        jobs={j['id']:j['config'] for j in original.jobs()};attempts={r[0] for r in original.db.execute('SELECT id FROM request_attempts')}
        checkpoint=repo.workset(wid)['checkpoint'];original.close()
        reopened=Store(original.path);newrepo=Repository(reopened);newrepo.tts_store=services.tts_store;services.tts_store.automation=newrepo
        newservices=SimpleNamespace(tts_store=services.tts_store,translation=Translation(newrepo,make,network_probe=lambda _:True),
                    kokoro=Kokoro(newrepo,services.tts_store,None,engine_factory=FakeEngine),capcut=Capcut(newrepo,services.tts_store),preflight=lambda _:None)
        resumed=Controller(newrepo,newservices)
        assert newrepo.workset(wid)['checkpoint']==checkpoint
        assert resumed.validate(wid)['passed'];resumed.start(wid);resumed.join(40)
        assert not resumed.busy and newrepo.workset(wid)['state']=='completed',newrepo.events(wid)[:3]
        assert len(reopened.jobs())==12 and all(reopened.job(j)['config']==cfg for j,cfg in jobs.items())
        assert attempts<={r[0] for r in reopened.db.execute('SELECT id FROM request_attempts')}
        assert all(reopened.line(rid)==row for rid,row in accepted.items())
        assert max(seen.values())==1 and len(FakeEngine.calls)==120
        assert newrepo.workset(wid)['checkpoint']['deepseek_admissions']['1']['admission_policy']==expected
        write_evidence(f'close-reopen-{expected["mode"]}.json',dict(status='PASS',policy=expected,preserved_job_ids=list(jobs),preserved_attempt_ids=list(attempts),
                         accepted_rows_preserved=len(accepted),completed_files=12,tts_calls=120,duplicate_row_sends=0))
    finally:
        release.set();c.stop();c.join(8)
        if resumed:resumed.stop();resumed.join(8)
        if reopened:reopened.close()


@pytest.mark.parametrize('failure',[429,503,504,'timeout','schema','wrong_language'])
def test_rolling_recovery_does_not_replay_committed_rows(setup,tmp_path,failure):
    repo,wid,services,c=setup;configure(repo,wid)
    docs=[repo.group(add_group(repo,wid,tmp_path/str(i),f'{i:03}',3)[0])['document_id'] for i in range(12)]
    failed={r['id'] for r in repo.store.lines(docs[2])};seen=Counter();times=[]
    def handler(req):
        units=request_lines(req);ids=[r['id'] for r in units];seen.update(ids)
        if ids[0] in failed:
            times.append(time.monotonic())
            if seen[ids[0]]==1:
                if failure=='timeout':raise httpx.ReadTimeout('Synthetic timeout',request=req)
                if failure=='schema':return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':'not json'}}]})
                if failure=='wrong_language':
                    data=response(req).json();data['choices'][0]['message']['content']=json.dumps({'lines':[{'id':r['id'],'text':'Tôi đã nói với cô ấy rằng chúng tôi không thể quay trở về trong đêm này'} for r in units]})
                    return httpx.Response(200,json=data)
                return httpx.Response(failure,headers={'Retry-After':'.15'})
        return response(req)
    services.translation=Translation(repo,lambda st,j:DeepSeekProvider('synthetic',transport=httpx.MockTransport(handler),batch_size=5),network_probe=lambda _:True)
    assert c.validate(wid)['passed'];c.start(wid);c.join(25)
    try:
        assert not c.busy and repo.workset(wid)['state']=='completed',repo.events(wid)[:3]
        assert all(seen[r['id']]==(2 if r['id'] in failed else 1) for d in docs for r in repo.store.lines(d))
        assert repo.store.db.execute('SELECT COUNT(*) FROM api_text_versions WHERE accepted=1').fetchone()[0]==36
        assert len(FakeEngine.calls)==36 and len(repo.store.jobs())==12
        if isinstance(failure,int):assert times[1]-times[0]>=.14
        write_evidence(f'recovery-{failure}.json',dict(status='PASS',failure=failure,failed_file_attempts=len(times),
                       retry_interval=times[1]-times[0],accepted_rows=36,tts_calls=36,files=12,duplicate_commits=0))
    finally:c.stop();c.join(8)
