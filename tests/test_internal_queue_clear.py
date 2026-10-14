import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import threading
import httpx
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication,QDialog
from transcomic.storage import Store
from transcomic.documents import decode_txt
from transcomic.ui.main import MainWindow
from transcomic.ui.queue_clear import ClearDialog
from transcomic.update.internal import InternalUpdateService,candidate,manifest,INTERNAL_VERIFIED
from transcomic.update.metadata import UpdateError,asset_url,release_url,canonical,candidate as signed_candidate
from transcomic.update.service import LATEST_URL,Cancelled
from transcomic.update.windows_helper import (FakeWindowsRuntime,ProductionUpdateHelper,InstallPlan,AppProcessIdentity,load_install_plan)
from transcomic.update.install import SafetySnapshot


def populated(tmp_path,count=3):
    (tmp_path/'source.txt').write_bytes(b'hello\nworld')
    (tmp_path/'export.txt').write_bytes(b'previous export')
    store=Store(tmp_path/'test.sqlite3');doc=store.import_document(tmp_path/'source.txt',decode_txt(b'hello\nworld'),'Tiếng Việt','Tiếng Anh')[0]
    store.edit_line(store.lines(doc)[0]['id'],'translation','saved translation')
    store.set_setting('theme','dark');store.db.execute("INSERT INTO secrets VALUES ('kira',?)",(b'opaque DPAPI fixture',))
    for n in range(count):
        job=store.create_job(doc,'test','Tiếng Việt','Tiếng Anh',1,allow_shared_document=True)
        store.job_state(job,('completed','error','paused','stopped')[n%4])
        for batch in store.batches(job):
            for attempt in (1,2):
                attempt_id=f'{batch["id"]}-{attempt}'
                store.db.execute("INSERT INTO request_attempts(id,original_batch_id,attempt_number,state,created_at) VALUES (?,?,?,'finished','fixture')",(attempt_id,batch['id'],attempt))
                store.db.execute('INSERT INTO api_text_versions VALUES (?,?,?,?,?,?,?)',(attempt_id,store.lines(doc)[0]['id'],'raw','processed','fixture','[]',0))
    return store,doc


@pytest.mark.parametrize('count',[0,1,4,30])
def test_clear_graph_preserves_documents_settings_secrets_reopen(tmp_path,count):
    store,doc=populated(tmp_path,count);before=store.lines(doc);document=store.document(doc)
    entries={e['entry_id'] for e in store.history()}
    assert store.clear_queue_history(entries,lambda:True)==len(entries)
    assert store.history()==[] and store.jobs()==[]
    for table in ('batches','request_attempts','api_text_versions','translation_runs'):assert store.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==0
    assert store.lines(doc)==before and store.document(doc)==document and store.setting('theme')=='dark'
    assert (tmp_path/'source.txt').read_bytes()==b'hello\nworld' and (tmp_path/'export.txt').read_bytes()==b'previous export'
    assert store.db.execute('SELECT encrypted FROM secrets').fetchone()[0]==b'opaque DPAPI fixture'
    assert not store.db.execute('PRAGMA foreign_key_check').fetchall()
    store.close();store=Store(tmp_path/'test.sqlite3');assert store.history()==[] and store.lines(doc)==before;store.close()


def test_truly_empty_queue_does_not_delete(tmp_path):
    store=Store(tmp_path/'empty.sqlite3');calls=[]
    store.db.set_trace_callback(calls.append)
    assert store.clear_queue_history(set(),lambda:True)==0
    assert not any('DELETE' in sql.upper() for sql in calls);store.close()


def test_clear_only_target_run_metadata(tmp_path):
    store,doc=populated(tmp_path,1)
    store.db.execute("INSERT INTO translation_runs(id,config) VALUES ('unrelated','{}'),('target','{}')")
    store.db.execute("UPDATE jobs SET run_id='target'")
    store.clear_queue_history({e['entry_id'] for e in store.history()},lambda:True)
    assert [r[0] for r in store.db.execute('SELECT id FROM translation_runs')]==['unrelated']
    store.close()


@pytest.mark.parametrize('busy',['running','pausing','stopping','inflight','transaction','callback','changed'])
def test_clear_rechecks_and_keeps_data(tmp_path,busy):
    store,doc=populated(tmp_path);entries={e['entry_id'] for e in store.history()};job=store.jobs()[0]
    if busy in ('running','pausing','stopping'):store.job_state(job['id'],busy)
    if busy=='inflight':store.db.execute("UPDATE batches SET state='inflight' WHERE job_id=?",(job['id'],))
    if busy=='transaction':store.db.execute('BEGIN IMMEDIATE')
    if busy=='changed':entries.add('unexpected')
    with pytest.raises(ValueError):store.clear_queue_history(entries,lambda:busy!='callback')
    if store.db.in_transaction:store.db.execute('ROLLBACK')
    assert len(store.jobs())==3 and store.lines(doc)[0]['translation']=='saved translation';store.close()


def test_clear_rollback_sqlite_failure(tmp_path):
    store,doc=populated(tmp_path);entries={e['entry_id'] for e in store.history()}
    store.db.execute("CREATE TRIGGER fail_queue_delete BEFORE DELETE ON jobs BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
    import sqlite3
    with pytest.raises(sqlite3.DatabaseError):store.clear_queue_history(entries,lambda:True)
    assert len(store.jobs())==3 and store.batches(store.jobs()[0]['id']) and store.history()
    assert not store.db.in_transaction;store.close()


def test_clear_dialog_and_ui_cancel_confirm_double_click(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([]);store,doc=populated(tmp_path)
    window=MainWindow(store);window.show();window.open_document(doc);window.pages.setCurrentIndex(1);window.refresh();app.processEvents()
    assert window.clear_all_jobs_button.isEnabled()
    dialog=ClearDialog(window,3);assert dialog.windowTitle()=='Xóa toàn bộ lượt dịch?'
    assert any(b.text()=='Hủy' and b.isDefault() for b in dialog.findChildren(__import__('PySide6.QtWidgets',fromlist=['QPushButton']).QPushButton))
    dialog.close()
    monkeypatch.setattr(window,'confirm_clear_all',lambda n:False);window.clear_all_queue();assert len(store.jobs())==3
    calls=[];monkeypatch.setattr(window,'confirm_clear_all',lambda n:calls.append(n) or True)
    window.clear_all_queue();window.clear_all_queue()
    for _ in range(100):
        QTest.qWait(20)
        if not window.queue_clear_busy:break
    assert calls==[3] and store.history()==[] and window.job_list.count()==0
    assert not window.clear_all_jobs_button.isEnabled() and store.lines(doc)[0]['translation']=='saved translation'
    window._exit_authorized=True;window.close();QTest.qWait(50)


@pytest.mark.parametrize('busy',['thread','inflight','background','confirmation-race'])
def test_ui_blocks_worker_and_confirmation_race(tmp_path,monkeypatch,busy):
    app=QApplication.instance() or QApplication([]);store,doc=populated(tmp_path)
    w=MainWindow(store);w.show();w.refresh()
    thread=SimpleNamespace(is_alive=lambda:True)
    if busy=='thread':w.scheduler=SimpleNamespace(_thread=thread,active=0,job_id=store.jobs()[0]['id'])
    if busy=='inflight':w.scheduler=SimpleNamespace(_thread=None,active=1,job_id=store.jobs()[0]['id'])
    if busy=='background':w.background_threads=[thread]
    def confirm(n):
        if busy=='confirmation-race':w.scheduler=SimpleNamespace(_thread=thread,active=0,job_id=store.jobs()[0]['id'])
        return True
    monkeypatch.setattr(w,'confirm_clear_all',confirm);w.clear_all_queue();assert len(store.jobs())==3
    w.scheduler=None;w.background_threads=[];w._exit_authorized=True;w.close();QTest.qWait(50)


def fixture(version='0.2.0'):
    data=b'not executable internal fixture';name=f'TransComic-Setup-{version}-windows-x64.testdata';tag='v'+version
    envelope=manifest(version,f'TransComic-Setup-{version}-windows-x64.exe',len(data),hashlib.sha256(data).hexdigest(),'2026-10-14T00:00:00Z')
    envelope['payload']['installer_filename']=name
    raw=canonical(envelope)
    sums=(hashlib.sha256(data).hexdigest()+'  '+name+'\n'+hashlib.sha256(raw).hexdigest()+'  transcomic-update.json\n').encode()
    contents={name:data,'transcomic-update.json':raw,'SHA256SUMS.txt':sums}
    release={'tag_name':tag,'draft':False,'prerelease':False,'html_url':release_url(tag),'published_at':'2026-10-14T00:00:00Z','body':'Internal notes',
             'assets':[{'name':n,'size':len(b),'state':'uploaded','browser_download_url':asset_url(tag,n)} for n,b in contents.items()]}
    return release,envelope,contents


def service(tmp_path,release,contents,respond=None):
    def transport(req):
        if respond is not None:return respond(req)
        return httpx.Response(200,json=release) if str(req.url)==LATEST_URL else httpx.Response(200,content=contents[req.url.path.rsplit('/',1)[-1]])
    return InternalUpdateService(tmp_path/'updates',httpx.Client(transport=httpx.MockTransport(transport)),testing=True)


@pytest.mark.parametrize('version,state',[('0.2.0','UPDATE_AVAILABLE'),('0.1.0','UP_TO_DATE')])
def test_internal_check_download_without_signing_key(tmp_path,version,state):
    release,envelope,contents=fixture(version);client=service(tmp_path,release,contents)
    result=client.check(True);assert result.state==state and result.candidate.signature_status==INTERNAL_VERIFIED
    path=client.download(result.candidate);assert path.read_bytes()==contents[path.name]
    client.verify_file(path,result.candidate)
    with pytest.raises(UpdateError):signed_candidate(release,envelope,testing=True)
    assert not __import__('transcomic.update.metadata',fromlist=['PRODUCTION_KEYS']).PRODUCTION_KEYS


@pytest.mark.parametrize('bad',['draft','prerelease','policy','signed','arch','filename','size','hash','redirect','checksum','version'])
def test_internal_invalid_metadata_and_tamper(tmp_path,bad):
    release,envelope,contents=fixture();p=envelope['payload']
    if bad in ('draft','prerelease'):release[bad]=True
    if bad=='policy':p['channel']='stable'
    if bad=='signed':envelope['signature']={}
    if bad=='arch':p['architecture']='arm64'
    if bad=='filename':p['installer_filename']='../evil.exe'
    if bad=='size':p['installer_size']+=1
    if bad=='hash':p['sha256']='bad'
    if bad=='redirect':release['assets'][0]['browser_download_url']='https://evil.example/file'
    if bad=='version':release['tag_name']='v01.2.0'
    if bad=='checksum':contents['SHA256SUMS.txt']=b'bad'
    else:
        contents['transcomic-update.json']=canonical(envelope)
        for a in release['assets']:
            if a['name']=='transcomic-update.json':a['size']=len(contents[a['name']])
    assert service(tmp_path,release,contents).check(True).state=='ERROR'


@pytest.mark.parametrize('kind',['no-release','timeout','network'])
def test_internal_network(tmp_path,kind):
    def respond(req):
        if kind=='timeout':raise httpx.ReadTimeout('fixture')
        if kind=='network':raise httpx.ConnectError('fixture')
        return httpx.Response(404)
    client=service(tmp_path,{}, {},respond)
    assert client.check(True).state==('NO_RELEASE' if kind=='no-release' else 'ERROR')


def test_internal_download_hash_size_cancel_and_redirect(tmp_path):
    release,envelope,contents=fixture();client=service(tmp_path,release,contents);item=client.check(True).candidate
    cancel=threading.Event();cancel.set()
    with pytest.raises(Cancelled):client.download(item,cancel=cancel)
    contents[item.filename]=b'bad'
    with pytest.raises(UpdateError):client.download(item)
    assert not list(client.directory.glob('*.part'))
    client.client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(302,headers={'location':'https://evil.example/payload'})))
    with pytest.raises(UpdateError):client.download(item)


@pytest.mark.parametrize('bad',['success','install-failure','busy','version','tamper','plan'])
def test_internal_existing_helper_algorithm_mock(tmp_path,bad):
    release,envelope,contents=fixture();client=service(tmp_path,release,contents);item=client.check(True).candidate;path=client.download(item)
    installation=tmp_path/'app';installation.mkdir();runtime=FakeWindowsRuntime();process=AppProcessIdentity(123,456,str(installation/'TransComic.exe'))
    runtime.version=item.version
    runtime.identity=process
    runtime.fail='installer' if bad=='install-failure' else None
    if bad=='version':runtime.version='0.1.0'
    if bad=='tamper':path.write_bytes(b'x'*item.size)
    plan=InstallPlan(item.version,path,item.size,item.sha256,release,envelope,process)
    helper=ProductionUpdateHelper(client.directory,installation,runtime,policy='internal')
    snapshot=SafetySnapshot(app_closed=True,process_exited=True,safe_exit_verified=True,translating=bad=='busy')
    if bad=='plan':
        raw=canonical({'release':release,'manifest':envelope,'pid':123,'creation_time':456,'restart':True,'safe_exit_verified':True,'policy':'internal'})
        with pytest.raises(UpdateError):load_install_plan(raw,client.directory,installation,testing=True,policy='internal')
    elif bad=='success':assert helper.run(plan,snapshot,threading.Event())['simulated']
    else:
        with pytest.raises(UpdateError):helper.run(plan,snapshot,threading.Event())


def test_internal_publisher_verifies_complete_unsigned_inventory(tmp_path):
    from transcomic.release_adapters import GitHubPublisher,FakeCommands,CommandResult,Asset
    release,envelope,contents=fixture('0.1.1')
    release['id']=1
    old=envelope['payload']['installer_filename'];new=old.replace('.testdata','.exe')
    envelope['payload']['installer_filename']=new
    contents[new]=contents.pop(old);contents['transcomic-update.json']=canonical(envelope)
    contents['SHA256SUMS.txt']=''.join(hashlib.sha256(contents[n]).hexdigest()+'  '+n+'\n' for n in (new,'transcomic-update.json')).encode()
    assets=[]
    for n,data in contents.items():
        path=tmp_path/(str(len(assets))+'.testdata');path.write_bytes(data);assets.append(Asset.inspect(n,path,tmp_path))
    release['assets']=[{'id':i+10,'name':a.name,'size':a.size,'state':'uploaded','digest':'sha256:'+a.sha256,'browser_download_url':asset_url('v0.1.1',a.name)} for i,a in enumerate(assets)]
    remote=dict(release,draft=True,published_at=None)
    responses=[CommandResult(stdout=json.dumps(remote).encode()),*[CommandResult(stdout=contents[a.name]) for a in assets],CommandResult(stdout=b'{}'),CommandResult(stdout=json.dumps(release).encode()),*[CommandResult(stdout=contents[a.name]) for a in assets]]
    commands=FakeCommands(responses);publisher=GitHubPublisher('C:/fake/gh.exe',tmp_path,commands,policy='internal')
    assert publisher.publish('0.1.1',assets)['draft'] is False
    assert len([c for c in commands.calls if 'PATCH' in c['argv']])==1
    with pytest.raises(UpdateError):GitHubPublisher('C:/fake/gh.exe',tmp_path,FakeCommands(),policy='signed-stable').verify('0.1.1',remote,assets)
    with pytest.raises(UpdateError):GitHubPublisher('C:/fake/gh.exe',tmp_path,policy='internal').read('0.1.1')


def test_internal_tag_preparation_mock_and_wrong_existing_commit(tmp_path):
    from transcomic.release_adapters import GitHubPublisher,FakeCommands,CommandResult
    ref={'object':{'type':'commit','sha':'b'*40}}
    commands=FakeCommands([CommandResult(1,b'HTTP/2.0 404 Not Found\r\n\r\n{}'),CommandResult(stdout=b'{}'),CommandResult(stdout=json.dumps(ref).encode())])
    publisher=GitHubPublisher('C:/fake/gh.exe',tmp_path,commands,policy='internal')
    publisher.prepare_internal_tag('1.1.0','b'*40)
    assert sum('POST' in c['argv'] for c in commands.calls)==1
    assert all('private' not in ' '.join(c['argv']) for c in commands.calls)
    publisher.commands=FakeCommands([CommandResult(stdout=json.dumps(ref).encode()),CommandResult(stdout=json.dumps(ref).encode())])
    with pytest.raises(UpdateError):publisher.prepare_internal_tag('1.1.0','c'*40)
    assert not any('POST' in c['argv'] for c in publisher.commands.calls)


def test_internal_mutated_verified_item_rejected(tmp_path):
    release,envelope,contents=fixture();client=service(tmp_path,release,contents);item=client.check(True).candidate
    item.payload['sha256']='f'*64
    with pytest.raises(UpdateError):client.download(item)


def test_unfinished_attempt_blocks_clear(tmp_path):
    store,doc=populated(tmp_path,1)
    store.db.execute("UPDATE request_attempts SET state='prepared'")
    with pytest.raises(ValueError):store.clear_queue_history({e['entry_id'] for e in store.history()},lambda:True)
    assert store.jobs();store.close()


def test_internal_publish_response_loss_preserves_reservation(tmp_path):
    from transcomic.release_pipeline import ReleaseCoordinator,FakeReleaseOperations
    from transcomic.release_journal import ReleaseJournal
    journal=ReleaseJournal(tmp_path/'journal.json');coordinator=ReleaseCoordinator(journal)
    operations=FakeReleaseOperations();operations.policy='internal';operations.unknown_publish=True
    with pytest.raises(UpdateError):coordinator.simulate(operations,current='1.0.8',build_id='intent')
    assert journal.load()['version']=='1.0.9' and journal.load()['distribution_policy']=='internal'
    assert coordinator.simulate(operations,current='1.0.8',build_id='intent')['version']=='1.0.9'
    assert operations.calls.count('publish')==1
    other=FakeReleaseOperations();other.policy='signed-stable'
    with pytest.raises(UpdateError,match='policy changed'):coordinator.simulate(other,current='1.0.8',build_id='intent')


def test_internal_release_manifest_phase_needs_no_key_or_certificate(tmp_path):
    from transcomic.release_pipeline import ProductionReleaseOperations
    from transcomic.release_journal import ReleaseState
    from transcomic.release_provenance import SourceIdentity
    source=SourceIdentity(str(tmp_path),'a'*40,'main',False,(),None,None,True)
    builder=SimpleNamespace(output=tmp_path,build_provenance={})
    publisher=SimpleNamespace(policy='internal')
    ops=ProductionReleaseOperations(builder,None,publisher,None,lambda:(_ for _ in ()).throw(AssertionError('No password')),None,source,{},policy='internal')
    ops.installer=tmp_path/'fixture.testdata';ops.installer.write_bytes(b'fixture nonexecutable')
    record={'version':'0.1.1'};ops.perform(ReleaseState.SIGNED,record)
    envelope=json.loads((tmp_path/'transcomic-update.json').read_bytes())
    assert set(envelope)=={'payload'} and envelope['payload']['channel']=='internal'
    assert len(ops.assets)==3 and not any('source_repository' in json.dumps(envelope) for _ in [0])
