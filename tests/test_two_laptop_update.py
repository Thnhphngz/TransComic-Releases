"""Native code preparation: local IPC/exit gates mocked, never run an installer."""
from dataclasses import replace
import json
import sys
import threading
from types import SimpleNamespace
import httpx
import pytest
from qt_wait import wait_until
from transcomic.update.metadata import UpdateError
from transcomic.update.install import SafetySnapshot
from transcomic.update.windows_helper import HandoffSession,WindowsRuntime,NativeHelperSession
from transcomic.update.windows_channel import channel_name,WindowsChannel


class Channel:
    def __init__(self,reply=b'COMMIT_ACK'):
        self.sent=[];self.closed=False;self.reply=reply
    def send(self,raw,*args,**kwargs):self.sent.append(raw)
    def receive(self,*args,**kwargs):return self.reply
    def close(self):self.closed=True


@pytest.mark.parametrize('field',['translating','paused','inflight','transaction','editing','app_closed','safe_exit_verified','logger'])
def test_commit_never_authorizes_busy_or_unflushed_exit(field):
    channel=Channel();session=HandoffSession(channel,None,None)
    snapshot=SafetySnapshot(app_closed=True,safe_exit_verified=True)
    if field!='logger':snapshot=replace(snapshot,**{field:field not in ('app_closed','safe_exit_verified')})
    with pytest.raises(UpdateError):session.commit(snapshot,field!='logger')
    assert channel.sent==[] and not session.committed
    session.abort();assert channel.closed


def test_commit_is_one_use_and_requires_no_os_exit_claim():
    channel=Channel();session=HandoffSession(channel,None,None)
    session.commit(SafetySnapshot(app_closed=True,process_exited=False,safe_exit_verified=True),True)
    assert channel.sent==[b'COMMIT_SAFE_EXIT'] and channel.closed and session.committed
    with pytest.raises(UpdateError):session.commit(SafetySnapshot(app_closed=True,safe_exit_verified=True),True)


def test_native_context_cannot_be_forged_by_a_json_boolean_or_environment(monkeypatch,tmp_path):
    from transcomic.update.windows_helper import ProductionUpdateHelper,HelperHandoff
    monkeypatch.setenv('ENABLE_UNSAFE_UPDATE','1')
    monkeypatch.setenv('TRANSCOMIC_UPDATE_PRODUCTION','1')
    calls=[]
    monkeypatch.setattr('subprocess.Popen',lambda *a,**kw:calls.append(a))
    with pytest.raises(UpdateError):NativeHelperSession(None,None,None,None,None,None)
    with pytest.raises(UpdateError):WindowsRuntime().install(tmp_path/'arbitrary.exe',tmp_path,10)
    with pytest.raises(UpdateError):HelperHandoff(tmp_path/'updates',tmp_path/'app',None,policy='internal').launch(b'{}')
    assert calls==[] and not (tmp_path/'updates').exists()


@pytest.mark.parametrize('name',['x','../arbitrary.exe','https://example.com/installer','A'*64,'0'*65])
def test_only_local_random_channel_names(name):
    with pytest.raises(UpdateError):channel_name(name)
    assert channel_name('a'*64).startswith('\\\\.\\pipe\\TransComic-Update-')


def test_entry_rejects_arbitrary_plan_files_and_probe_has_no_install(monkeypatch,capsys,tmp_path):
    from scripts import update_helper
    calls=[]
    monkeypatch.setattr(update_helper,'require_packaged_windows',lambda:None)
    monkeypatch.setattr(update_helper.ProductionUpdateHelper,'run',lambda *a,**k:calls.append(a))
    with pytest.raises(SystemExit) as error:update_helper.main(['--plan',str(tmp_path/'arbitrary.json')])
    assert error.value.code==2
    assert update_helper.main(['--self-check'])==0
    assert json.loads(capsys.readouterr().out)['installer_executed'] is False
    assert calls==[]


def test_duplicate_helpers_cannot_execute_same_installer_concurrently(tmp_path):
    from test_release_stage_b2_1 import helper_plan
    helper,plan,snapshot,runtime=helper_plan(tmp_path)
    entered=threading.Event();release=threading.Event();errors=[]
    original=runtime.install
    def install(*args):
        entered.set();assert release.wait(3)
        return original(*args)
    runtime.install=install
    def run():
        try:helper.run(plan,snapshot,threading.Event())
        except BaseException as error:errors.append(error)
    worker=threading.Thread(target=run);worker.start()
    try:
        assert entered.wait(1)
        with pytest.raises(UpdateError,match='INSTALL_BUSY_OR_RECOVERY_REQUIRED'):
            helper.run(plan,snapshot,threading.Event())
    finally:release.set();worker.join(3)
    assert not worker.is_alive() and not errors and runtime.calls.count('install')==1


def installed_fixture(tmp_path):
    from test_internal_queue_clear import fixture
    from transcomic.update.internal import InternalUpdateService,manifest
    from transcomic.update.metadata import canonical
    import hashlib
    release,envelope,contents=fixture()
    old=envelope['payload']['installer_filename'];name=old.replace('.testdata','.exe')
    data=contents[old];raw=canonical(manifest('0.2.0',name,len(data),hashlib.sha256(data).hexdigest(),'2026-10-15T00:00:00Z'))
    contents={name:data,'transcomic-update.json':raw,'SHA256SUMS.txt':(hashlib.sha256(data).hexdigest()+'  '+name+'\n'+hashlib.sha256(raw).hexdigest()+'  transcomic-update.json\n').encode()}
    for asset in release['assets']:
        if asset['name']==old:asset['name']=name;asset['browser_download_url']=asset['browser_download_url'].replace(old,name)
        asset['size']=len(contents[asset['name']])
    def respond(req):
        return httpx.Response(200,json=release) if req.url.path.endswith('/latest') or '/releases/tags/' in req.url.path else httpx.Response(200,content=contents[req.url.path.rsplit('/',1)[-1]])
    return InternalUpdateService(tmp_path/'updates',httpx.Client(transport=httpx.MockTransport(respond)))


@pytest.mark.parametrize('late_busy',[False,True,'slow_close'])
def test_ui_handoff_commit_occurs_only_after_data_close(tmp_path,monkeypatch,late_busy):
    from test_first_local_build import window
    import transcomic.update.windows_helper as native
    app,w=window(tmp_path)
    panel=w.update_panel;panel.service=installed_fixture(tmp_path)
    panel.item=panel.service.check(True).candidate
    assert panel.item is not None
    panel.downloaded_path=panel.service.download(panel.item)
    installation=tmp_path/'app';identity=native.AppProcessIdentity(321,456,str(installation/'TransComic.exe'))
    monkeypatch.setattr(native,'registered_installation',lambda:installation)
    monkeypatch.setattr(native,'current_process_identity',lambda:identity)
    channel=Channel();launches=[]
    if late_busy=='slow_close':
        import transcomic.ui.main as main_module
        clock=[0.0];original_close=w.store.close
        monkeypatch.setattr(main_module,'time',SimpleNamespace(monotonic=lambda:clock[0]))
        def slow_close():
            original_close();clock[0]=1.0
        w.store.close=slow_close
    def launch(self,raw,cancel):
        plan=native.load_install_plan(raw,panel.service.directory,installation,policy='internal')
        launches.append(plan)
        if late_busy is True:w.store.db.execute('BEGIN')
        return HandoffSession(channel,None,plan)
    monkeypatch.setattr(native.HelperHandoff,'launch',launch)
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    try:
        panel.begin_native_install()
        assert wait_until(lambda:not panel.busy and not panel.handoff_pending,3000)
        assert len(launches)==1
        if late_busy is True:
            assert not w._closed and channel.sent==[] and channel.closed
            w.store.db.rollback()
        elif late_busy=='slow_close':
            assert w._closed and channel.sent==[] and channel.closed
        else:
            assert w._closed and w.store.log.closed and not w.store.log.thread.is_alive()
            assert channel.sent==[b'COMMIT_SAFE_EXIT'] and channel.closed
    finally:
        if not w._closed:w._exit_authorized=True;w.close()


def test_fresh_https_confirmation_rejects_locally_poisoned_cache(tmp_path):
    from transcomic.update.internal import candidate
    service=installed_fixture(tmp_path)
    good=service.check(True).candidate
    assert service.confirm_install(good)==good
    cache=service._cache();cache['envelope']['payload']['sha256']='0'*64
    service._save(cache)
    forged=candidate(cache['release'],cache['envelope'])
    with pytest.raises(UpdateError,match='INSTALL_RELEASE_CHANGED'):
        service.confirm_install(forged)


@pytest.mark.parametrize('status',[403,429,404,'offline'])
def test_install_never_falls_back_to_cached_permission(tmp_path,status):
    service=installed_fixture(tmp_path);good=service.check(True).candidate
    def respond(req):
        if status=='offline':raise httpx.ConnectError('fixture offline')
        return httpx.Response(status)
    service.client=httpx.Client(transport=httpx.MockTransport(respond))
    with pytest.raises((UpdateError,httpx.HTTPError)):service.confirm_install(good)


@pytest.mark.parametrize('reply',[b'',b'COMPLETED',b'{"safe_exit_verified":true}'])
def test_native_ready_requires_a_separate_commit(reply,tmp_path):
    import transcomic.update.windows_helper as native
    channel=Channel(reply)
    session=native.NativeHelperSession(native._NATIVE_SESSION_SEAL,channel,None,tmp_path,tmp_path,object())
    with pytest.raises(UpdateError,match='SAFE_EXIT_COMMIT_REQUIRED'):session.ready_and_wait(threading.Event())
    assert channel.sent==[b'READY'] and not session.committed and not session.exited


def test_stale_exclusive_install_lock_requires_recovery(tmp_path):
    from test_release_stage_b2_1 import helper_plan
    helper,plan,snapshot,runtime=helper_plan(tmp_path)
    (helper.updates/('install-'+plan.version+'.lock')).write_text('previous process')
    with pytest.raises(UpdateError,match='INSTALL_BUSY_OR_RECOVERY_REQUIRED'):
        helper.run(plan,snapshot,threading.Event())
    assert runtime.calls==[]


def test_packaging_keeps_same_appid_mutex_and_user_data_outside_programs():
    from pathlib import Path
    from transcomic.update.windows_helper import INSTALL_APP_ID,APPLICATION_MUTEX
    source=(Path(__file__).resolve().parents[1]/'installer/TransComic.iss').read_text(encoding='utf8')
    assert 'AppId={'+INSTALL_APP_ID in source
    assert 'AppMutex='+APPLICATION_MUTEX in source
    assert 'PrivilegesRequired=lowest' in source and 'UsePreviousAppDir=yes' in source
    assert 'ArchitecturesInstallIn64BitMode=x64compatible' in source
    assert '[UninstallDelete]' not in source and '[Dirs]' not in source


def test_startup_ack_is_atomic_fixed_location_and_not_overwritten(tmp_path,monkeypatch):
    import transcomic.update.windows_helper as native
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    installation=tmp_path/'Programs/TransComic'
    identity=native.AppProcessIdentity(123,456,str(installation/'TransComic.exe'))
    monkeypatch.setattr(native,'require_packaged_windows',lambda:None)
    monkeypatch.setattr(native,'registered_installation',lambda:installation)
    monkeypatch.setattr(native,'current_process_identity',lambda:identity)
    token='a'*64
    native.acknowledge_restart(['--update-startup-token='+token])
    path=tmp_path/'TransComic/Updates'/('startup-'+token+'.json')
    assert json.loads(path.read_bytes())=={'version':'0.1.0','pid':123,'creation_time':456,'image':identity.image}
    assert not list(path.parent.glob('*.tmp'))
    with pytest.raises(UpdateError,match='STARTUP_RECEIPT_ALREADY_EXISTS'):
        native.acknowledge_restart(['--update-startup-token='+token])
    with pytest.raises(UpdateError):native.acknowledge_restart(['--update-startup-token=../outside'])


@pytest.mark.parametrize('mode',['ok','version','identity','parent','no-ack'])
def test_restart_requires_live_verified_app_startup_ack(tmp_path,monkeypatch,mode):
    import transcomic.update.windows_helper as native
    updates=tmp_path/'updates';updates.mkdir();installation=tmp_path/'installed';installation.mkdir()
    app=installation/'TransComic.exe';plan=SimpleNamespace(version='0.1.1')
    channel=Channel();session=native.NativeHelperSession(native._NATIVE_SESSION_SEAL,channel,plan,updates,installation,None)
    session.committed=True;session.exited=True
    runtime=native.WindowsRuntime();runtime._native_session=session;runtime._plan=plan
    monkeypatch.setattr(native,'require_packaged_windows',lambda:None)
    monkeypatch.setattr(native,'registered_installation',lambda version=None:installation)
    def identify(pid):return native.AppProcessIdentity(pid,100 if pid==999 else 101,str(app))
    monkeypatch.setattr(native,'process_identity',identify)
    monkeypatch.setattr(native,'parent_process_id',lambda pid:998 if mode=='parent' else 999)
    calls=[]
    def spawn(argv,**kwargs):
        calls.append((argv,kwargs));token=argv[1].split('=',1)[1]
        if mode!='no-ack':
            (updates/('startup-'+token+'.json')).write_text(json.dumps({'version':'0.1.0' if mode=='version' else '0.1.1',
                'pid':1000,'creation_time':99 if mode=='identity' else 101,'image':str(app)}))
        return SimpleNamespace(pid=999,poll=lambda:None)
    monkeypatch.setattr('subprocess.Popen',spawn)
    if mode=='no-ack':
        values=iter([0,31]);monkeypatch.setattr(native,'time',SimpleNamespace(monotonic=lambda:next(values),sleep=lambda delay:None))
    if mode=='ok':assert runtime.restart(app)==1000
    else:
        with pytest.raises(UpdateError):runtime.restart(app)
    assert len(calls)==1 and calls[0][0][0]==str(app)
    assert calls[0][1]['env']['PYINSTALLER_RESET_ENVIRONMENT']=='1'


def test_dll_search_restored_when_external_launch_fails(monkeypatch):
    import transcomic.update.windows_helper as native
    changes=[]
    def directory(size,buffer):
        if buffer is not None:buffer.value='frozen-private-folder'
        return len('frozen-private-folder')
    def set_directory(value):changes.append(value);return True
    kernel=SimpleNamespace(GetDllDirectoryW=directory,SetDllDirectoryW=set_directory)
    monkeypatch.setattr(native.ctypes,'WinDLL',lambda *args,**kwargs:kernel)
    with pytest.raises(RuntimeError):
        with native.system_dll_search():raise RuntimeError('mock external launch failure')
    assert changes==[None,'frozen-private-folder']


def test_channel_cancellation_drains_overlapped_io_without_killing_process(monkeypatch):
    import transcomic.update.windows_channel as ipc
    operation=SimpleNamespace(event=7,cancel=lambda:None,GetOverlappedResult=lambda wait:(0,0))
    seen=[]
    operation.cancel=lambda:seen.append('cancel_io')
    operation.GetOverlappedResult=lambda wait:(seen.append(('drain',wait)) or (0,995))
    monkeypatch.setitem(sys.modules,'_winapi',SimpleNamespace(WaitForMultipleObjects=lambda *args:258))
    cancel=threading.Event();cancel.set()
    with pytest.raises(UpdateError,match='UPDATE_CANCELLED'):
        WindowsChannel(7,True)._wait(operation,cancel,1)
    assert seen==['cancel_io',('drain',True)]


def test_native_unknown_retains_startup_lock_without_executing_installer(tmp_path):
    from transcomic.update.windows_helper import ProductionUpdateHelper
    updates=tmp_path/'updates';updates.mkdir()
    helper=ProductionUpdateHelper(updates,tmp_path/'app',policy='internal')
    plan=SimpleNamespace(version='0.1.1')
    lock=updates/'install-0.1.1.lock';lock.write_bytes(b'')
    receipt=updates/'install-0.1.1.json';receipt.write_text(json.dumps({'state':'INSTALL_OUTCOME_UNKNOWN'}))
    helper.release_lock(lock,plan);assert lock.exists()
    receipt.write_text(json.dumps({'state':'COMPLETED'}))
    helper.release_lock(lock,plan);assert not lock.exists()


def test_cancel_after_download_completion_does_not_start_native_handoff(tmp_path,monkeypatch):
    from test_first_local_build import window
    from transcomic.update.install import State
    app,w=window(tmp_path);panel=w.update_panel;calls=[]
    monkeypatch.setattr(panel,'begin_native_install',lambda:calls.append('handoff'))
    panel.cancel_event.set()
    panel.receive({'kind':'downloaded','path':str(tmp_path/'verified.exe')})
    assert panel.machine.state==State.CANCELLED and calls==[]
    w._exit_authorized=True;w.close()


def test_connected_pipe_result_is_collected_to_completion(monkeypatch):
    observed=[]
    operation=SimpleNamespace(event=7,GetOverlappedResult=lambda wait:(observed.append(wait) or (0,0)))
    monkeypatch.setitem(sys.modules,'_winapi',SimpleNamespace(WaitForMultipleObjects=lambda *args:0))
    assert WindowsChannel(7,True)._wait(operation,threading.Event(),1)==(0,0)
    assert observed==[True]
