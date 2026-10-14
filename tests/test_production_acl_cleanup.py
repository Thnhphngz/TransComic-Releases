import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from transcomic.update.keytools import WindowsKeyACL,_provision,_load_pair
from transcomic.update.metadata import UpdateError
from transcomic.maintenance import inventory,cleanup
from transcomic.provisioning import native_drill,interactive_provision


def test_native_acl_encrypted_recovery():
    assert native_drill()=={'native_acl':True,'encrypted_test_recovery':True,'production_created':False}


def test_native_dacl_tamper_access_denied_readonly_and_inheritance(tmp_path):
    acl=WindowsKeyACL(native=True);folder=tmp_path/'native';folder.mkdir();acl.restrict(folder)
    file=folder/'nonsecret.bin';file.write_bytes(b'fixture')
    assert not acl.verify(file)  # inherited DACL is not a protected key DACL
    acl.restrict(file);assert acl.verify(file)
    icacls=str(Path(os.environ['SystemRoot'])/'System32/icacls.exe')
    def change(*args):
        result=subprocess.run([icacls,*map(str,args)],capture_output=True,shell=False)
        assert result.returncode==0
    change(file,'/grant','*S-1-1-0:(R)')
    assert not acl.verify(file)
    acl.restrict(file);assert acl.verify(file)
    raw=subprocess.check_output(['whoami','/user','/fo','csv','/nh']).decode().strip()
    sid=list(csv.reader([raw]))[0][1]
    change(file,'/deny',f'*{sid}:(R)')
    try:
        assert not acl.verify(file)
        with pytest.raises(PermissionError):file.read_bytes()
    finally:acl.restrict(file)
    assert file.read_bytes()==b'fixture'
    readonly=folder/'readonly';readonly.mkdir();acl.restrict(readonly)
    change(readonly,'/deny',f'*{sid}:(W)')
    try:
        with pytest.raises(PermissionError):(readonly/'child').mkdir()
        assert not acl.verify(readonly)
    finally:acl.restrict(readonly)
    assert acl.verify(readonly)
    key=folder/'key';_provision(key,b'native-test-passphrase',acl,'test')
    with pytest.raises(UpdateError):_provision(key,b'native-test-passphrase',acl,'test')
    assert _load_pair(key,b'native-test-passphrase',acl,'test')[1]['purpose']=='test'


def test_native_reparse_rejected(tmp_path):
    target=tmp_path/'target';target.mkdir();link=tmp_path/'junction'
    result=subprocess.run(['cmd','/d','/c','mklink','/J',str(link),str(target)],capture_output=True,shell=False)
    assert result.returncode==0
    try:
        with pytest.raises(UpdateError):WindowsKeyACL(native=True).verify(link)
        with pytest.raises(UpdateError):WindowsKeyACL(native=True).restrict(link)
    finally:link.rmdir()  # junction node only, no recursive traversal
    assert target.exists()


def test_no_terminal_no_production_effects(monkeypatch,capsys):
    from scripts.provision_release_key import main
    monkeypatch.setattr('sys.stdin.isatty',lambda:False)
    monkeypatch.setattr('getpass.getpass',lambda *a:(_ for _ in ()).throw(AssertionError('secret prompt forbidden')))
    assert main(['--interactive'])==2
    assert 'BLOCKED' in capsys.readouterr().out


def test_native_cleanup_cli_blocks_running_pytest():
    root=Path(__file__).resolve().parents[1]
    run=subprocess.run([sys.executable,str(root/'scripts/cleanup_project.py')],capture_output=True,timeout=30,shell=False)
    assert run.returncode==2 and b'CLEANUP BLOCKED' in run.stdout


@pytest.mark.parametrize('failure',['decline','same-password','hidden-input-unavailable'])
def test_interactive_confirmation_and_password_guards(tmp_path,monkeypatch,failure):
    import getpass
    from transcomic import provisioning as module
    monkeypatch.setattr('sys.stdin.isatty',lambda:True)
    monkeypatch.setattr('sys.stdout.isatty',lambda:True)
    monkeypatch.setattr(module,'native_drill',lambda:{'native_acl':True})
    monkeypatch.setattr(module,'locations',lambda:(tmp_path/'production',tmp_path/'drill',tmp_path/'offline/backup'))
    monkeypatch.setattr('builtins.input',lambda *a:'NO' if failure=='decline' else 'CREATE PRODUCTION KEY')
    def hidden(*args):
        if failure=='decline':raise AssertionError('No secret prompt before confirmation')
        if failure=='hidden-input-unavailable':
            import warnings
            warnings.warn('hidden input unavailable',getpass.GetPassWarning)
        return 'same-strong-test-password'
    monkeypatch.setattr(getpass,'getpass',hidden)
    monkeypatch.setattr(module,'_provision',lambda *a:(_ for _ in ()).throw(AssertionError('No key creation permitted')))
    with pytest.raises((UpdateError,getpass.GetPassWarning)):module.interactive_provision()
    assert list(tmp_path.iterdir())==[]


def project(tmp_path):
    root=tmp_path/'source';root.mkdir()
    for name in ('transcomic','tests','docs','scripts','installer','artifacts','build','dist'):(root/name).mkdir()
    cache=root/'transcomic/__pycache__';cache.mkdir();(cache/'module.pyc').write_bytes(b'generated cache')
    for name in ('book.docx','user.sqlite3','ddd'):(root/name).write_bytes(b'keep')
    (root/'artifacts/ledger.json').write_bytes(b'keep ledger')
    data=root/'.pytest_old';data.mkdir();(data/'database.db').write_bytes(b'keep unknown test data')
    return root


def test_cleanup_preserves_data_tracked_evidence_and_repeat(tmp_path):
    root=project(tmp_path);tracked={'tests/test.py'}
    plan=inventory(root,tracked,set())
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file() and p.suffix!='.pyc'}
    result=cleanup(root,plan,tmp_path/'quarantine',processes=[],tracked=tracked)
    assert result['deleted']==['transcomic/__pycache__']
    assert (Path(result['quarantine'])/'transcomic/__pycache__/module.pyc').read_bytes()==b'generated cache'
    assert before=={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert cleanup(root,inventory(root,tracked,set()),tmp_path/'quarantine',processes=[],tracked=tracked)['deleted']==[]
    assert all((root/p).is_dir() for p in ('transcomic','tests','docs','scripts','installer','artifacts','build','dist'))


@pytest.mark.parametrize('condition',['tracked','active','journal','traversal','changed','reparse'])
def test_cleanup_blocks_unsafe(tmp_path,condition):
    root=project(tmp_path);tracked=set();cache=root/'transcomic/__pycache__'
    plan=inventory(root,tracked,set());link=None
    if condition=='tracked':tracked.add('transcomic/__pycache__/module.pyc')
    if condition=='journal':
        folder=root/'.release-state';folder.mkdir();(folder/'journal.json').write_text(json.dumps({'state':'FAILED'}))
    if condition=='traversal':next(c for c in plan['candidates'] if c['safe'])['path']='../outside'
    if condition=='changed':(cache/'user.docx').write_bytes(b'new data')
    if condition=='reparse':
        link=cache/'junction';target=tmp_path/'external';target.mkdir()
        assert subprocess.run(['cmd','/d','/c','mklink','/J',str(link),str(target)],capture_output=True).returncode==0
    try:
        with pytest.raises(UpdateError):cleanup(root,plan,tmp_path/'quarantine',processes=[123] if condition=='active' else [],tracked=tracked)
        assert (cache/'module.pyc').exists() and (root/'book.docx').exists()
    finally:
        if link is not None:link.rmdir()
