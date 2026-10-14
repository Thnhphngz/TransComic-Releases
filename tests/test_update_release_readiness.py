from update_versions import CURRENT, NEXT
"""Verified app/helper handoff, interrupted install recovery and staging overlay."""
from dataclasses import replace
import json
from pathlib import Path
import threading
import pytest
from test_internal_queue_clear import fixture,service
from transcomic.update.metadata import UpdateError,canonical
from transcomic.update.install import SafetySnapshot
from transcomic.update.windows_helper import (AppProcessIdentity,FakeWindowsRuntime,ProductionUpdateHelper,
                                             prepare_install_plan,HandoffSafety)

def prepared(tmp_path,version=NEXT):
    release,envelope,contents=fixture(version);client=service(tmp_path/'updates',release,contents)
    item=client.check(True).candidate;path=client.download(item)
    installation=tmp_path/'installed';installation.mkdir()
    process=AppProcessIdentity(42,123,str(installation/'TransComic.exe'))
    snapshot=SafetySnapshot(app_closed=True,process_exited=True,safe_exit_verified=True)
    return client,item,path,installation,process,snapshot

@pytest.mark.parametrize('fault',['none','busy','logger','candidate','tamper','identity','same','older'])
def test_handoff_binding_and_safe_exit(tmp_path,fault):
    args=list(prepared(tmp_path,CURRENT if fault=='same' else '0.0.9' if fault=='older' else NEXT))
    handoff=None
    if fault=='busy':args[-1]=replace(args[-1],inflight=True)
    if fault=='logger':handoff=HandoffSafety(logger_flushing=True)
    if fault=='candidate':args[1]=replace(args[1],changelog='changed')
    if fault=='tamper':args[2].write_bytes(b'tamper')
    if fault=='identity':args[4]=replace(args[4],image=str(tmp_path/'wrong.exe'))
    if fault!='none':
        with pytest.raises(UpdateError):prepare_install_plan(*args,handoff=handoff)
    else:
        raw,plan=prepare_install_plan(*args)
        value=json.loads(raw)
        assert set(value)=={'release','manifest','pid','creation_time','restart','safe_exit_verified'}
        runtime=FakeWindowsRuntime();runtime.identity=args[4]
        result=ProductionUpdateHelper(args[0].directory,args[3],runtime,policy='internal').run(plan,args[-1],threading.Event())
        assert result['simulated'] and not result['actual_install'] and runtime.calls==['open','wait','close','install','version','restart']

@pytest.mark.parametrize('fault',['timeout','version','restart'])
def test_helper_uncertain_outcome_blocks_blind_replay(tmp_path,fault):
    args=prepared(tmp_path);raw,plan=prepare_install_plan(*args)
    runtime=FakeWindowsRuntime();runtime.identity=args[4];runtime.fail=fault
    helper=ProductionUpdateHelper(args[0].directory,args[3],runtime,policy='internal')
    with pytest.raises(UpdateError):helper.run(plan,args[-1],threading.Event())
    receipt=json.loads((helper.updates/('install-'+NEXT+'.json')).read_text())
    assert receipt['state']==('INSTALLED_RESTART_PENDING' if fault=='restart' else 'INSTALL_OUTCOME_UNKNOWN')
    calls=list(runtime.calls);runtime.fail=None
    with pytest.raises(UpdateError,match='MANUAL_RECONCILIATION'):helper.run(plan,args[-1],threading.Event())
    assert runtime.calls==calls

def test_staging_version_overlay_does_not_mutate_source(tmp_path):
    from scripts.build_local import ROOT,prepare
    original=(ROOT/'transcomic/version.py').read_bytes()
    # Existing build entry requires outputs inside the actual workspace.
    from uuid import uuid4
    output=ROOT/'artifacts/release-preparation'/('overlay-test-'+uuid4().hex)
    stage,report=prepare(ROOT,output,NEXT)
    assert report['source_version']==CURRENT and report['version']==NEXT
    assert report['version_overlay'] and not report['remote_release_allowed'] and not report['install_allowed']
    assert (ROOT/'transcomic/version.py').read_bytes()==original
    assert ('VERSION = '+repr(NEXT)) in (stage/'transcomic/version.py').read_text()
    assert json.loads((stage/'.build-local.json').read_text())['permission']=='BUILD_LOCAL'

def test_helper_rejects_downgrade_before_process_open(tmp_path):
    args=prepared(tmp_path,CURRENT);client,item,path,installation,process,snapshot=args
    from transcomic.update.windows_helper import InstallPlan
    plan=InstallPlan(item.version,path,item.size,item.sha256,client._cache()['release'],client._cache()['envelope'],process)
    runtime=FakeWindowsRuntime();runtime.identity=process
    with pytest.raises(UpdateError,match='NOT_NEWER'):
        ProductionUpdateHelper(client.directory,installation,runtime,policy='internal').run(plan,snapshot,threading.Event())
    assert not runtime.calls

def test_download_rejects_changed_directory_junction_before_writing(tmp_path):
    import subprocess
    args=prepared(tmp_path);client,item,path,installation,process,snapshot=args
    # Remove only our generated fixture/cache, then replace empty fixture directory by a junction.
    for file in client.directory.iterdir():file.unlink()
    client.directory.rmdir()
    target=tmp_path/'external';target.mkdir();sentinel=target/'keep.txt';sentinel.write_bytes(b'keep')
    result=subprocess.run(['cmd','/c','mklink','/J',str(client.directory),str(target)],capture_output=True)
    assert result.returncode==0
    with pytest.raises(UpdateError,match='Reparse'):client.download(item)
    assert list(target.iterdir())==[sentinel] and sentinel.read_bytes()==b'keep'

@pytest.mark.parametrize('exited',[True,False])
def test_plan_prepared_before_os_exit_helper_proves_exit_before_install(tmp_path,exited):
    args=list(prepared(tmp_path));args[-1]=replace(args[-1],process_exited=False)
    raw,plan=prepare_install_plan(*args)
    runtime=FakeWindowsRuntime();runtime.identity=args[4];runtime.process_exited=exited
    helper=ProductionUpdateHelper(args[0].directory,args[3],runtime,policy='internal')
    if exited:
        assert helper.run(plan,args[-1],threading.Event())['simulated']
        assert runtime.calls.index('wait')<runtime.calls.index('install')
    else:
        with pytest.raises(UpdateError,match='PROCESS_EXIT_TIMEOUT'):helper.run(plan,args[-1],threading.Event())
        assert 'install' not in runtime.calls and 'restart' not in runtime.calls
