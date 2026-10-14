from update_versions import CURRENT, NEXT
import base64
import copy
import hashlib
import json
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path
import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from transcomic.update.metadata import *
from transcomic.update.service import UpdateService, LATEST_URL, Cancelled, DAY
from transcomic.update.install import *
from scripts import release_transcomic as release_script

def fixture_release(data=b'fixture data, not an executable',version=NEXT,signed=True):
    key=Ed25519PrivateKey.generate();keys={'ephemeral-test':key.public_key().public_bytes_raw()}
    tag='v'+version;name=f'TransComic-Setup-{version}-windows-x64.testdata'
    p={'app_id':APP_ID,'version':version,'channel':'stable','os':'windows','architecture':'x64',
       'installer_filename':name,'installer_size':len(data),'sha256':hashlib.sha256(data).hexdigest(),
       'release_tag':tag,'release_url':release_url(tag),'minimum_updater_version':'0.1.0','minimum_windows':'10','published_at':'2026-10-14T00:00:00Z'}
    s={'algorithm':'ed25519','key_id':'ephemeral-test','value':base64.b64encode(key.sign(canonical(p))).decode()} if signed else {}
    envelope={'payload':p,'signature':s};manifest=json.dumps(envelope).encode()
    def asset(n,size):return {'name':n,'size':size,'state':'uploaded','browser_download_url':asset_url(tag,n)}
    release={'tag_name':tag,'draft':False,'prerelease':False,'published_at':p['published_at'],'html_url':release_url(tag),
             'body':'Fixture changelog','assets':[asset(MANIFEST_NAME,len(manifest)),asset(name,len(data))]}
    return release,envelope,manifest,keys,data

@pytest.mark.parametrize('a,b',[('1.9.0','1.10.0'),('1.0.0-alpha','1.0.0-alpha.1'),('1.0.0-alpha.1','1.0.0-beta'),('1.0.0-rc.1','1.0.0'),('1.0.0-9','1.0.0-10')])
def test_semver_order(a,b):assert SemVer.parse(a)<SemVer.parse(b)
@pytest.mark.parametrize('value',['01.0.0','1.0','1.0.0-01','../1.0.0','v1.0.0','1.0.0;echo'])
def test_invalid_semver(value):
    with pytest.raises(UpdateError):SemVer.parse(value)
def test_semver_build_and_bumps():
    assert SemVer.parse('1.0.0+a')==SemVer.parse('1.0.0+b')
    assert [bumped('0.1.0',x) for x in ('patch','minor','major','1.2.3')]==['0.1.1','0.2.0','1.0.0','1.2.3']
    with pytest.raises(UpdateError):bumped('1.0.0','1.0.0')

@pytest.mark.parametrize('field,value',[('os','linux'),('architecture','arm64'),('channel','beta'),('installer_filename','../evil.exe'),('installer_filename','evil.exe.txt'),('installer_size',0),('installer_size',True),('sha256','bad'),('release_tag','v0.3.0'),('release_url','https://evil.test'),('version','0.3.0'),('minimum_updater_version','99.0.0'),('published_at','wrong')])
def test_manifest_mismatch_rejected(field,value):
    r,e,_,keys,_=fixture_release();e['payload'][field]=value
    with pytest.raises(UpdateError):candidate(r,e,keys,True)
@pytest.mark.parametrize('change',['draft','prerelease','duplicate','missing','foreign','version','publish'])
def test_invalid_release(change):
    r,e,_,keys,_=fixture_release()
    if change in ('draft','prerelease'):r[change]=True
    if change=='duplicate':r['assets'].append(r['assets'][0])
    if change=='missing':r['assets']=[]
    if change=='foreign':r['assets'][1]['browser_download_url']='https://github.com/evil/repo/releases/download/v0.2.0/evil.exe'
    if change=='version':r['tag_name']='v0.2.0-rc.1'
    if change=='publish':r['published_at']=None
    with pytest.raises(UpdateError):candidate(r,e,keys,True)
def test_signature_and_duplicate_json():
    r,e,_,keys,_=fixture_release()
    assert candidate(r,e,keys,True).signature_status=='VERIFIED_ED25519'
    assert candidate(r,e,{},True).signature_status==NOT_READY
    e['signature']['value']=base64.b64encode(b'x'*64).decode()
    with pytest.raises(UpdateError):candidate(r,e,keys,True)
    with pytest.raises(UpdateError):strict_json(b'{"version":1,"version":2}')

def make_service(tmp_path, data=b'fixture', version=NEXT, status=200, handler=None):
    r,e,m,keys,data=fixture_release(data,version)
    calls=[]
    def send(req):
        calls.append(str(req.url))
        if handler:return handler(req,r,m,data)
        if str(req.url)==LATEST_URL:return httpx.Response(status,json=r,headers={'etag':'"fixture"'})
        return httpx.Response(200,content=m if req.url.path.endswith(MANIFEST_NAME) else data)
    client=httpx.Client(transport=httpx.MockTransport(send))
    return UpdateService(tmp_path/'Updates',client,keys=keys,testing=True),calls,(r,e,m,keys,data)

@pytest.mark.parametrize('version,state',[('0.0.9','UP_TO_DATE'),(CURRENT,'UP_TO_DATE'),(NEXT,'UPDATE_AVAILABLE')])
def test_check_versions(tmp_path,version,state):
    service,calls,_=make_service(tmp_path,version=version)
    assert service.check().state==state and len(calls)==2
@pytest.mark.parametrize('status,state',[(404,'NO_RELEASE'),(403,'RATE_LIMITED'),(429,'RATE_LIMITED'),(500,'ERROR')])
def test_check_http_and_24_hour_cache(tmp_path,status,state):
    service,calls,_=make_service(tmp_path,status=status)
    assert service.check().state==state
    assert service.check().cached and len(calls)==1
def test_cache_304_and_manual_check(tmp_path):
    service,calls,_=make_service(tmp_path);now=[100000.]
    service.clock=lambda:now[0]
    assert service.check().state=='UPDATE_AVAILABLE'
    assert service.check().cached and len(calls)==2
    now[0]+=DAY;assert service.due()
    def send(req):
        assert req.headers['if-none-match']=='"fixture"'
        return httpx.Response(304)
    service.client=httpx.Client(transport=httpx.MockTransport(send))
    assert service.check().state=='UPDATE_AVAILABLE'
    now[0]+=5;assert service.check(True).cached
@pytest.mark.parametrize('kind',['timeout','json','304','redirect'])
def test_check_failure_redacts(tmp_path,kind):
    def send(req,*_):
        if kind=='timeout':raise httpx.ReadTimeout('secret=gho_TEST_TOKEN',request=req)
        if kind=='json':return httpx.Response(200,content=b'not-json secret')
        return httpx.Response(304 if kind=='304' else 302,headers={'location':'https://evil.test'})
    service,_,_=make_service(tmp_path,handler=send)
    result=service.check()
    assert result.state=='ERROR' and 'secret' not in result.message and 'gho_' not in service.cache_path.read_text()

def test_download_progress_repeat_and_part_cleanup(tmp_path):
    service,calls,f=make_service(tmp_path,b'fixture'*30000)
    item=service.check().candidate;progress=[]
    path=service.download(item,progress.append)
    assert path.suffix=='.testdata' and path.read_bytes()==f[-1]
    assert progress[-1].downloaded==item.size and progress[-1].bytes_per_second>0
    count=len(calls);assert service.download(item)==path and len(calls)==count
    assert not list(service.directory.glob('*.part'))
@pytest.mark.parametrize('kind',['cancel','timeout','404','403','429','redirect','hash','size','oversize'])
def test_download_failures(tmp_path,kind):
    service,_,f=make_service(tmp_path,b'data'*40000);item=service.check().candidate
    def send(req):
        if kind=='timeout':raise httpx.ReadTimeout('token secret',request=req)
        if kind in ('404','403','429'):return httpx.Response(int(kind))
        if kind=='redirect':return httpx.Response(302,headers={'location':'https://evil.test/evil'})
        if kind=='oversize':return httpx.Response(200,headers={'content-length':str(MAX_DOWNLOAD+1)})
        return httpx.Response(200,content=b'x'*item.size if kind=='hash' else b'short' if kind=='size' else f[-1])
    service.client=httpx.Client(transport=httpx.MockTransport(send));cancel=threading.Event()
    with pytest.raises(UpdateError):service.download(item,lambda p:cancel.set() if kind=='cancel' else None,cancel)
    assert not list(service.directory.glob('*.part')) and not (service.directory/item.filename).exists()
def test_unsigned_and_tampered_candidate_never_download(tmp_path):
    service,calls,_=make_service(tmp_path);item=service.check().candidate
    count=len(calls)
    with pytest.raises(UpdateError):service.download(replace(item,filename='../evil'))
    service.keys={}
    with pytest.raises(UpdateError):service.download(item)
    assert len(calls)==count
@pytest.mark.parametrize('url',['http://github.com/a','https://evil.test/a','https://user:pass@github.com/a','https://github.com:444/a','https://github.com/evil/repo/releases/download/v1/a'])
def test_url_allowlist(url):
    with pytest.raises(UpdateError):valid_network_url(url)
def test_directory_lock_and_double_download(tmp_path):
    with pytest.raises(UpdateError):UpdateService(Path.cwd()/'Updates')
    service,_,_=make_service(tmp_path);item=service.check().candidate
    service._download_lock.acquire()
    with pytest.raises(UpdateError):service.download(item)
    service._download_lock.release()

@pytest.mark.parametrize('field',['translating','paused','inflight','transaction','editing','app_closed','process_exited','safe_exit_verified'])
def test_install_waits_for_every_safety_condition(tmp_path,field):
    path=tmp_path/'fake.testdata';path.write_bytes(b'data')
    flags={'app_closed':True,'process_exited':True,'safe_exit_verified':True}
    flags[field]=field not in flags
    machine=InstallMachine();adapter=FakeInstaller()
    assert machine.simulate(path,SafetySnapshot(**flags),adapter,lambda p:None)['blocked_by']
    assert adapter.calls==0 and machine.state==State.WAITING_FOR_SAFE_EXIT
@pytest.mark.parametrize('success',[True,False])
def test_mock_installer_only(tmp_path,success):
    path=tmp_path/'fake.testdata';path.write_bytes(b'data');adapter=FakeInstaller(success)
    machine=InstallMachine()
    result=machine.simulate(path,SafetySnapshot(app_closed=True,process_exited=True,safe_exit_verified=True),adapter,lambda p:None)
    assert result['simulated'] and adapter.calls==1
    assert machine.state==(State.COMPLETED if success else State.INSTALL_FAILED)
    with pytest.raises(UpdateError):machine.install(path,force=True)
    assert machine.simulate(path,SafetySnapshot(),adapter,lambda p:None,cancelled=True)['success'] is False
    with pytest.raises(UpdateError):machine.simulate(path,SafetySnapshot(),object(),lambda p:None)

def fake_commands(args):
    if args[:3]==['gh','auth','status']:return True,'token must not be logged'
    if args[:3]==['gh','repo','view']:return True,json.dumps({'nameWithOwner':RELEASE_REPOSITORY,'visibility':'PUBLIC'})
    if 'rev-parse' in args:return True,'a'*40
    if 'status' in args:return True,''
    return True,'[]'
@pytest.mark.parametrize('missing',['git','gh','ISCC','PyInstaller',None])
def test_preflight_even_full_environment_stays_locked(missing):
    report=release_script.preflight(commands=fake_commands,which=lambda n:None if n==missing else n,find_spec=lambda n:None if n==missing else object())
    assert report['production_locked'] and not report['version_modified'] and report['repository']==RELEASE_REPOSITORY
    assert report['phases']['publish']=='LOCKED' and report['current_version']==CURRENT
    with pytest.raises(RuntimeError):release_script.production_action('publish')
def test_readonly_commands_and_auth_redaction():
    calls=[]
    def run(args,**kw):
        calls.append(args);assert kw['shell'] is False
        return subprocess.CompletedProcess(args,0,'gho_'+'x'*30,'')
    runner=release_script.ReadOnlyCommands(run)
    assert runner(['gh','auth','status'])==(True,'')
    with pytest.raises(RuntimeError):runner(['git','push'])
    with pytest.raises(RuntimeError):runner(['gh','release','create','v1','--repo',RELEASE_REPOSITORY])
    assert len(calls)==1
@pytest.mark.parametrize('bad',['duplicate','assets','tests','commit','older'])
def test_release_gates(bad):
    new='0.2.0';tags=['v0.2.0'] if bad=='duplicate' else []
    assets={f'TransComic-Setup-{new}-windows-x64.exe',MANIFEST_NAME,'SHA256SUMS.txt'}
    with pytest.raises(UpdateError):release_script.verify_release_plan('0.3.0' if bad=='older' else '0.1.0',new,tags,bad!='tests',[] if bad=='assets' else assets,'main' if bad=='commit' else 'a'*40)
def test_static_build_locks_and_no_version_duplicate():
    root=release_script.ROOT
    spec=(root/'TransComic.spec').read_text();iss=(root/'installer/TransComic.iss').read_text()
    assert 'raise RuntimeError' in spec and '#error Stage A locked' in iss
    assert 'generated-version.iss' in iss and 'MyAppVersion "0.1.0"' not in iss
    assert '[UninstallDelete]' not in iss and 'CloseApplications=no' in iss
    assert 'datas=[]' not in spec and '*.svg' in spec

def test_bat_from_other_directory_with_space_and_no_activation(tmp_path):
    # Real BAT parsing from a directory with spaces; help never starts a release.
    root=release_script.ROOT;before=(root/'transcomic/version.py').read_bytes()
    work=tmp_path/'directory with spaces';work.mkdir()
    result=subprocess.run(['cmd','/c',str(root/'release_transcomic.bat'),'--help'],cwd=work,capture_output=True,timeout=90)
    assert result.returncode==0 and b'--build-only' in result.stdout and b'--check' in result.stdout
    assert result.stderr==b'', 'BAT must execute without cmd parsing errors'
    assert (root/'transcomic/version.py').read_bytes()==before
    result=subprocess.run([__import__('sys').executable,str(root/'scripts/release_transcomic.py'),'--publish'],cwd=work,capture_output=True)
    assert result.returncode==2

def test_wal_backup_keeps_committed_history_and_ciphertext(tmp_path):
    import sqlite3
    from transcomic.update.backup import consistent_backup
    source=tmp_path/'user.db';db=sqlite3.connect(source)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE data (id INTEGER PRIMARY KEY, history TEXT, dpapi BLOB)')
    ciphertext=b'opaque protected blob fixture'
    db.execute('INSERT INTO data VALUES (1,?,?)',('retained history',ciphertext));db.commit()
    db.execute('INSERT INTO data VALUES (2,?,?)',('uncommitted',ciphertext))
    target=consistent_backup(source,tmp_path/'backup.db')
    copied=sqlite3.connect(target)
    assert copied.execute('SELECT * FROM data').fetchall()==[(1,'retained history',ciphertext)]
    copied.close();db.rollback()
    assert db.execute('SELECT count(*) FROM data').fetchone()[0]==1;db.close()
    with pytest.raises(UpdateError):consistent_backup(source,source)
    with pytest.raises(UpdateError):consistent_backup(source,target)
    assert not list(tmp_path.glob('*.backup-part'))
