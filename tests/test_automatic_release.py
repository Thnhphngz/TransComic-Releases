"""Isolated Git and fake GitHub: never publish, install or call translation APIs."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from scripts import automatic_release as auto
from scripts import release_package as package
from scripts import release_source as source
from transcomic.release_pipeline import FakeReleaseOperations,ReleaseCoordinator
from transcomic.release_journal import ReleaseJournal,ReleaseState
from transcomic.update.internal import manifest,candidate,verify_checksums
from transcomic.update.metadata import canonical,asset_url,release_url,UpdateError

def git(root,*args):return source.git(root,*args).decode().strip()

class FakeRuntime(auto.Runtime):
    def __init__(self,root,version):
        super().__init__(root);self.latest=version;self.events=[];self.fail=None;self.ops=FakeReleaseOperations();self.ops.policy='internal';self.public_ok=True
    def inventory(self):
        return {'latest':{'tag_name':'v'+self.latest},'tags':['v'+self.latest],
            'releases':[{'tag_name':'v'+self.latest}],'distribution_commit':'b'*40}
    def verify_previous(self,r):
        self.events.append('verify_previous')
        return {'tag':'v'+r['version'],'build_id':r['build_id'],'assets_verified':True,'published':True,'draft':False}
    def prepare(self,r,work):
        for phase in ('test','build','package','GUI','baseline','privacy'):
            self.events.append(phase)
            if self.fail==phase:raise UpdateError('FAKE_'+phase+'_FAILURE')
        folder=self.root/'releases'/r['version'];folder.mkdir(parents=True)
        name=package.names(r['version'])[0];data=b'nonexecutable fixture'
        (folder/name).write_bytes(data)
        raw=canonical(manifest(r['version'],name,len(data),hashlib.sha256(data).hexdigest(),r['created_at']))
        (folder/'transcomic-update.json').write_bytes(raw)
        (folder/'SHA256SUMS.txt').write_bytes((hashlib.sha256(data).hexdigest()+'  '+name+'\n'+hashlib.sha256(raw).hexdigest()+'  transcomic-update.json\n').encode('ascii'))
        (work/'full.xml').write_text('<testsuites><testsuite tests="1" failures="0" errors="0"/></testsuites>')
    def verify_local(self,r,work):
        self.events.append('verify_local')
        folder=self.root/'releases'/r['version'];names=package.names(r['version'])
        if self.fail=='sha':(folder/names[0]).write_bytes(b'corrupt')
        raw=(folder/names[1]).read_bytes()
        envelope=json.loads(raw)
        if self.fail=='manifest':envelope['payload']['app_id']='other'
        fixture={'tag_name':'v'+r['version'],'draft':False,'prerelease':False,'html_url':release_url('v'+r['version']),
            'published_at':'fixture','assets':[{'name':n,'size':(folder/n).stat().st_size,'state':'uploaded','browser_download_url':asset_url('v'+r['version'],n)} for n in names]}
        item=candidate(fixture,envelope);verify_checksums((folder/names[2]).read_bytes(),item,raw)
        if package.sha(folder/names[0])!=item.sha256:raise UpdateError('SHA_MISMATCH')
    def publish(self,r,work,journal):
        self.events.append('publish')
        if self.fail=='upload_unknown':
            r.update(state=ReleaseState.UNKNOWN_REMOTE_OUTCOME,last_completed=ReleaseState.DRAFT_CREATED)
            with journal.exclusive():journal.save(r)
            raise UpdateError('UPLOAD_OUTCOME_UNKNOWN')
        result=ReleaseCoordinator(journal)._execute(self.ops,current=r['previous_published_version'],choice=r['version'],build_id=r['build_id'],distribution_commit=r['distribution_commit'])
        self.latest=r['version'];return result
    def verify_public(self,r,work):
        self.events.append('verify_public')
        if not self.public_ok:raise UpdateError('LATEST_NOT_VERIFIED')

@pytest.fixture
def project(tmp_path):
    root=tmp_path/'project with spaces';root.mkdir();(root/'transcomic').mkdir()
    (root/'.gitignore').write_text('artifacts/\nreleases/\n.release-state/\n')
    (root/'transcomic/version.py').write_text('VERSION = "1.0.0"\n')
    (root/'transcomic/app.py').write_text('x = 1\n')
    git(root,'init');git(root,'config','user.name','Isolated Release Test');git(root,'config','user.email','fixture@example.invalid')
    git(root,'add','--','.gitignore','transcomic/version.py','transcomic/app.py');git(root,'commit','-m','baseline')
    runtime=FakeRuntime(root,'1.0.0');system=auto.AutomaticSystem(runtime)
    record={'schema':1,'version':'1.0.0','state':'PUBLISHED','last_completed':'PUBLISHED','build_id':'old','origin_id':'old',
            'source_commit':git(root,'rev-parse','HEAD'),'distribution_commit':'b'*40,'distribution_policy':'internal'}
    with system.journal.exclusive():system.journal.save(record)
    return root,runtime,system

def change(root):(root/'transcomic/app.py').write_text('x = 2\n')

def test_check_changes_neither_source_version_nor_journal(project):
    root,runtime,system=project;change(root)
    before={p:p.read_bytes() for p in (root/'transcomic/version.py',root/'transcomic/app.py',system.journal.path)}
    plan=system.run('check');assert plan['version']=='1.0.1'
    assert all(p.read_bytes()==raw for p,raw in before.items());assert 'publish' not in runtime.events

def test_default_runs_all_phases_then_reports_success(project,capsys):
    root,runtime,system=project;change(root);record=system.run('auto')
    assert record['version']=='1.0.1' and record['post_publication_verified'] is True
    assert runtime.events[-2:]==['publish','verify_public']
    assert set(('test','build','package','GUI','baseline','privacy')).issubset(runtime.events)
    assert 'RELEASE PUBLISHED AND VERIFIED' in capsys.readouterr().out
    assert not git(root,'status','--porcelain')

def test_build_only_and_then_auto_reuses_reserved_version(project):
    root,runtime,system=project;change(root)
    record=system.run('build-only');assert record['version']=='1.0.1' and 'publish' not in runtime.events
    assert system.run('auto')['version']=='1.0.1';assert runtime.events.count('build')==1

def test_no_changes_no_bump_no_commit_no_new_release(project,capsys):
    root,runtime,system=project;head=git(root,'rev-parse','HEAD');raw=system.journal.path.read_bytes()
    system.run('auto');assert git(root,'rev-parse','HEAD')==head and raw==system.journal.path.read_bytes()
    assert 'NO RELEASEABLE CHANGES' in capsys.readouterr().out and 'publish' not in runtime.events

def test_second_run_after_success_has_no_releaseable_changes(project):
    root,runtime,system=project;change(root);system.run('auto');head=git(root,'rev-parse','HEAD')
    system.run('auto');assert runtime.events.count('publish')==1 and git(root,'rev-parse','HEAD')==head

@pytest.mark.parametrize('old,new',[('1.0.9','1.1.0'),('1.9.9','2.0.0')])
def test_rollover_uses_existing_policy(project,old,new):
    root,runtime,system=project;auto.set_version(root,'1.0.0',old);git(root,'add','--','transcomic/version.py');git(root,'commit','-m','fixture version')
    r=system.journal.load();r.update(version=old,source_commit=git(root,'rev-parse','HEAD'));system.save(r);runtime.latest=old
    change(root);assert system.run('check')['version']==new

@pytest.mark.parametrize('failure',['test','build','baseline','sha','manifest'])
def test_local_failure_never_publishes(project,failure):
    root,runtime,system=project;change(root);runtime.fail=failure
    with pytest.raises(UpdateError):system.run('auto')
    assert 'publish' not in runtime.events and system.journal.load()['version']=='1.0.1'

def test_secret_and_unclassified_file_stop_before_commit(project):
    root,runtime,system=project;head=git(root,'rev-parse','HEAD')
    (root/'transcomic/app.py').write_text('value = '+repr('sk-'+'A'*30)+'\n')
    with pytest.raises(UpdateError,match='SECRET'):system.run('auto')
    (root/'transcomic/app.py').write_text('safe = True\n');(root/'personal.txt').write_text('personal')
    with pytest.raises(UpdateError,match='UNCLASSIFIED'):system.run('auto')
    assert git(root,'rev-parse','HEAD')==head

def test_existing_unjournaled_release_is_not_overwritten(project):
    root,runtime,system=project;change(root);original=runtime.inventory
    runtime.inventory=lambda:dict(original(),tags=['v1.0.0','v1.0.1'])
    with pytest.raises(UpdateError,match='ALREADY_EXISTS'):system.run('auto')
    assert 'publish' not in runtime.events

def test_unknown_remote_keeps_version_and_blocks_source_change(project):
    root,runtime,system=project;change(root);runtime.fail='upload_unknown'
    with pytest.raises(UpdateError,match='OUTCOME_UNKNOWN'):system.run('auto')
    r=system.journal.load();assert r['version']=='1.0.1' and r['state']=='UNKNOWN_REMOTE_OUTCOME'
    (root/'transcomic/app.py').write_text('x = 3\n')
    with pytest.raises(UpdateError,match='SOURCE_CHANGED'):system.run('auto')
    assert runtime.events.count('publish')==1

def test_fixing_local_failure_reuses_version_and_preserves_failed_candidate(project):
    root,runtime,system=project;change(root);runtime.fail='sha'
    with pytest.raises(UpdateError):system.run('auto')
    failed=root/'releases/1.0.1'/package.names('1.0.1')[0];assert failed.read_bytes()==b'corrupt'
    (root/'transcomic/app.py').write_text('x = 3\n');runtime.fail=None
    assert system.run('auto')['version']=='1.0.1'
    archived=list((root/'artifacts/automatic-release/1.0.1').glob('old-*'))
    assert len(archived)==1 and (archived[0]/failed.name).read_bytes()==b'corrupt'

def test_timeout_persists_intent_before_write_and_rejects_blind_repeat(tmp_path,monkeypatch):
    from scripts import first_internal_release as first
    monkeypatch.setattr(first,'ROOT',tmp_path);monkeypatch.setattr(first,'_AUTOMATIC_SCOPES',{})
    monkeypatch.setattr(first,'source_identity',lambda:SimpleNamespace(commit='a'*40))
    monkeypatch.setattr(first,'require_current_tests',lambda scope:None)
    scope=first.automatic_scope('1.0.1');scope.out.mkdir(parents=True)
    c=first.FirstReleaseCommands(tmp_path/'gh.exe','a'*40,'b'*40,'c'*64,'notes',[],scope=scope)
    calls=[]
    def uncertain(*args,**kwargs):
        calls.append(args);assert package.load(scope.out/'remote-intent.json')['outcome']=='PENDING'
        raise subprocess.TimeoutExpired('gh',1)
    monkeypatch.setattr(first.subprocess,'run',uncertain)
    argv=[c.gh,'api','repos/'+auto.REPO+'/git/refs','--method','POST','-F','ref=refs/tags/v1.0.1','-F','sha='+'b'*40]
    with pytest.raises(UpdateError,match='OUTCOME_UNKNOWN'):c(argv,tmp_path)
    with pytest.raises(UpdateError,match='UNRESOLVED'):c(argv,tmp_path)
    assert len(calls)==1

def test_public_verify_failure_never_prints_success_and_resumes_same_version(project,capsys):
    root,runtime,system=project;change(root);runtime.public_ok=False
    with pytest.raises(UpdateError,match='LATEST_NOT_VERIFIED'):system.run('auto')
    assert 'RELEASE PUBLISHED AND VERIFIED' not in capsys.readouterr().out
    assert system.journal.load()['post_publication_verified'] is False
    runtime.public_ok=True;assert system.run('auto')['version']=='1.0.1'

def test_two_processes_cannot_own_release_lock(project):
    root,_,_=project
    with auto.process_lock(root):
        code='import sys;from pathlib import Path;from scripts.automatic_release import process_lock;\nwith process_lock(Path(sys.argv[1])):print("UNSAFE")'
        result=subprocess.run([sys.executable,'-c',code,str(root)],cwd=auto.ROOT,capture_output=True,timeout=30)
        assert result.returncode!=0 and b'UNSAFE' not in result.stdout and b'ALREADY_ACTIVE' in result.stderr
    with auto.process_lock(root):pass

def test_user_data_and_old_builds_are_preserved(project):
    root,runtime,system=project
    protected=[]
    for name in ('releases/1.0.0/old.exe','artifacts/two-laptop-update-test/old.log','.release-state/SecureBackup/key.backup'):
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'protected');protected.append(p)
    change(root);system.run('auto');assert all(p.read_bytes()==b'protected' for p in protected)
    assert (root/'.release-state/history/v1.0.0.json').exists()

def test_installer_identity_gate_is_real():
    iss=(auto.ROOT/'installer/TransComic.iss').read_text(encoding='utf8');package.verify_identity(iss)
    for old,new in (('CB58C770','00000000'),('PrivilegesRequired=lowest','PrivilegesRequired=admin'),('{localappdata}\\Programs','{app}\\Programs')):
        with pytest.raises(UpdateError):package.verify_identity(iss.replace(old,new))

@pytest.mark.parametrize('args',[['--chec'],['--build'],['--publish'],['--check','--build-only'],['--version','1.0.1']])
def test_unknown_or_abbreviated_cli_cannot_activate_release(monkeypatch,args):
    monkeypatch.setattr(auto,'Runtime',lambda:pytest.fail('No runtime before argument validation'))
    with pytest.raises(SystemExit) as error:auto.main(args)
    assert error.value.code==2

def test_cli_default_selects_auto_without_implicit_check(monkeypatch):
    modes=[];monkeypatch.setattr(auto,'Runtime',lambda:object());monkeypatch.setattr(auto,'AutomaticSystem',lambda r:SimpleNamespace(run=lambda mode:modes.append(mode)))
    assert auto.main([])==0 and modes==['auto']

def test_unresolved_upload_intent_is_read_only_and_never_retried(tmp_path):
    scope=SimpleNamespace(out=tmp_path);auto.write(tmp_path/'remote-intent.json',{'endpoint':'https://uploads.github.com/repos/'+auto.REPO+'/releases/7/assets?name=x.exe','build_id':'id','outcome':'PENDING'})
    publisher=SimpleNamespace(read=lambda v:{'id':7,'assets':[]},commands=SimpleNamespace(assets={}))
    with pytest.raises(UpdateError,match='OUTCOME_UNKNOWN'):auto.Runtime().reconcile_intent({'version':'1.0.1','build_id':'id'},scope,publisher)
    assert package.load(tmp_path/'remote-intent.json')['outcome']=='PENDING'

def bat_fixture(root):
    import shutil
    shutil.copyfile(auto.ROOT/'release_transcomic.bat',root/'release_transcomic.bat')
    (root/'scripts').mkdir(exist_ok=True)
    driver=('import sys,json,time,os\nsys.stdout.reconfigure(encoding="utf8",errors="replace")\nfrom pathlib import Path\n'
        f'sys.path.insert(0,{str(auto.ROOT)!r});sys.path.insert(0,{str(auto.ROOT/"tests")!r})\n'
        'from scripts.automatic_release import AutomaticSystem\nfrom test_automatic_release import FakeRuntime\n'
        'root=Path(__file__).resolve().parents[1]\nr=json.loads((root/".release-state/journal.json").read_text())\n'
        'runtime=FakeRuntime(root,r["version"] if r["state"]=="PUBLISHED" else r["previous_published_version"])\n'
        'original=runtime.prepare\n'
        'def prepare(record,work):\n'
        '    if os.environ.get("FIXTURE_HOLD_RELEASE")=="1":\n'
        '        (root/".release-state/started").write_text("ready");time.sleep(3)\n'
        '    return original(record,work)\n'
        'runtime.prepare=prepare\n'
        'try:\n'
        '    AutomaticSystem(runtime).run("check" if "--check" in sys.argv else "build-only" if "--build-only" in sys.argv else "auto")\n'
        'except Exception as exc:\n'
        '    print(str(exc));sys.exit(2)\n')
    (root/'scripts/automatic_release.py').write_text(driver,encoding='utf8')
    git(root,'add','--','scripts/automatic_release.py','release_transcomic.bat');git(root,'commit','-m','BAT fake GitHub fixture')
    return root/'release_transcomic.bat'

@pytest.mark.skipif(os.name!='nt',reason='Windows BAT integration')
def test_actual_bat_check_build_only_and_default_with_fake_github(project):
    root,runtime,system=project;bat=bat_fixture(root);change(root)
    before=system.journal.path.read_bytes();head=git(root,'rev-parse','HEAD')
    for args in (['--check'],['--build-only'],[]):
        result=subprocess.run(['cmd','/c',str(bat),*args],cwd=root.parent,capture_output=True,timeout=90)
        assert result.returncode==0,result.stdout.decode('utf8',errors='replace')
        if args==['--check']:assert system.journal.path.read_bytes()==before and git(root,'rev-parse','HEAD')==head
        elif args:assert b'NO GITHUB WRITES' in result.stdout and system.journal.load()['state']!='PUBLISHED'
        else:assert b'RELEASE PUBLISHED AND VERIFIED' in result.stdout and system.journal.load()['post_publication_verified']

@pytest.mark.skipif(os.name!='nt',reason='Windows concurrent BAT integration')
def test_two_actual_bats_only_one_can_release(project):
    import time
    root,runtime,system=project;bat=bat_fixture(root);change(root)
    first=subprocess.Popen(['cmd','/c',str(bat)],cwd=root.parent,env=dict(os.environ,FIXTURE_HOLD_RELEASE='1'),stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=0x08000000)
    try:
        deadline=time.monotonic()+20
        while not (root/'.release-state/started').exists() and first.poll() is None and time.monotonic()<deadline:time.sleep(0.05)
        assert (root/'.release-state/started').exists()
        second=subprocess.run(['cmd','/c',str(bat)],cwd=root.parent,capture_output=True,timeout=30)
        assert second.returncode==2 and b'ALREADY_ACTIVE' in second.stdout
        first.communicate(timeout=30);assert first.returncode==0
    finally:
        if first.poll() is None:first.kill();first.communicate()

def test_real_scoped_publisher_resumes_uncertain_upload_without_duplicate(project,monkeypatch):
    """Real command policy/coordinator/publisher against a fake gh REST server."""
    from scripts import first_internal_release as first
    root,runtime,system=project;change(root);record=system.run('build-only')
    work=root/record['work'];folder=root/'releases'/record['version']
    monkeypatch.setattr(first,'ROOT',root);monkeypatch.setattr(first,'_AUTOMATIC_SCOPES',{})
    monkeypatch.setattr(first,'require_current_tests',lambda scope:None)  # Fixture test evidence, never a CLI switch.
    scope=first.automatic_scope(record['version']);scope.out.mkdir(parents=True,exist_ok=True)
    (scope.out/'release-notes.md').write_text('Vietnamese notes fixture',encoding='utf8')
    runtime.tools={'gh':{'path':str(root/'gh.exe')}}
    original_verify=runtime.verify_local
    def verified(r,w):
        original_verify(r,w)
        return [package.Asset.inspect(n,folder/n,root) for n in package.names(r['version'])]
    runtime.verify_local=verified
    original_run=subprocess.run;state={'tag':False,'release':None,'uploads':{},'uncertain':True,'publish_count':0}
    prefix='repos/'+auto.REPO
    def respond(argv,**kwargs):
        if argv[0]!=str(root/'gh.exe'):return original_run(argv,**kwargs)
        endpoint=argv[2];method=argv[argv.index('--method')+1] if '--method' in argv else 'GET'
        value=None;code=0
        if endpoint==prefix+'/releases?per_page=100':value=[] if state['release'] is None else [state['release']]
        elif endpoint==prefix+'/git/ref/tags/v1.0.1':
            if not state['tag']:return subprocess.CompletedProcess(argv,1,b'HTTP/2.0 404 Not Found\r\n\r\n{}',b'')
            value={'object':{'sha':'b'*40,'type':'commit'}}
        elif endpoint==prefix+'/git/refs' and method=='POST':
            assert not state['tag'];state['tag']=True;value={'ref':'refs/tags/v1.0.1','object':{'sha':'b'*40,'type':'commit'}}
        elif endpoint==prefix+'/releases' and method=='POST':
            assert state['release'] is None
            request=json.loads(Path(argv[argv.index('--input')+1]).read_text())
            value=dict(request,id=7,url='https://api.github.com/'+prefix+'/releases/7',
                html_url='https://github.com/'+auto.REPO+'/releases/tag/untagged-fixture',assets=[])
            state['release']=value
        elif endpoint.startswith('https://uploads.github.com/'+prefix+'/releases/7/assets?name='):
            name=endpoint.rsplit('=',1)[-1];assert name not in state['uploads'],'Duplicate upload!'
            raw=Path(argv[argv.index('--input')+1]).read_bytes();state['uploads'][name]=raw
            value={'name':name,'id':80+len(state['uploads']),'size':len(raw),'state':'uploaded','digest':'sha256:'+hashlib.sha256(raw).hexdigest(),
                'browser_download_url':'https://github.com/'+auto.REPO+'/releases/download/untagged-fixture/'+name}
            state['release']['assets'].append(value)
            if state['uncertain']:
                state['uncertain']=False;raise subprocess.TimeoutExpired('gh',1)
        elif endpoint.startswith(prefix+'/releases/assets/'):
            asset=next(a for a in state['release']['assets'] if str(a['id'])==endpoint.rsplit('/',1)[-1])
            return subprocess.CompletedProcess(argv,0,state['uploads'][asset['name']],b'')
        elif endpoint==prefix+'/releases/7':
            if method=='PATCH':
                state['publish_count']+=1;state['release'].update(draft=False,html_url=release_url('v1.0.1'),published_at='2026-10-15T00:00:00Z')
                for a in state['release']['assets']:a['browser_download_url']=asset_url('v1.0.1',a['name'])
            value=state['release']
        else:pytest.fail('Unapproved fake endpoint: '+endpoint)
        raw=json.dumps(value).encode()
        if '--include' in argv:raw=b'HTTP/2.0 200 OK\r\n\r\n'+raw
        return subprocess.CompletedProcess(argv,code,raw,b'')
    monkeypatch.setattr(first.subprocess,'run',respond)
    with pytest.raises(UpdateError,match='OUTCOME_UNKNOWN'):auto.Runtime.publish(runtime,record,work,system.journal)
    assert len(state['uploads'])==1 and system.journal.load()['state']=='UNKNOWN_REMOTE_OUTCOME'
    published=auto.Runtime.publish(runtime,system.journal.load(),work,system.journal)
    assert published['state']=='PUBLISHED' and len(state['uploads'])==3 and state['publish_count']==1
    receipts=package.load(scope.out/'mutation-receipts.json');assert len(receipts)==6  # tag/draft/3 assets/publish
    assert all(v['confirmed'] is True for v in receipts.values())
    notes=(scope.out/'release-notes.md').read_text().rstrip()+'\n\n<!-- transcomic-build-id: '+record['build_id']+' -->\n'
    commands=first.FirstReleaseCommands(root/'gh.exe',record['source_commit'],'b'*40,record['build_id'],notes,verified(record,work),scope=scope)
    commands.release_id=7;installer=package.names(record['version'])[0]
    argv=[commands.gh,'api','https://uploads.github.com/'+prefix+'/releases/7/assets?name='+installer,'--method','POST','-H','Content-Type: application/octet-stream','--input',str(folder/installer)]
    with pytest.raises(UpdateError,match='RECEIPT_PRESENT'):commands(argv,root)
    assert len(state['uploads'])==3

def test_readonly_previous_release_does_not_overwrite_historical_evidence(tmp_path,monkeypatch):
    from scripts import first_internal_release as first
    monkeypatch.setattr(first,'ROOT',tmp_path);monkeypatch.setattr(first,'_AUTOMATIC_SCOPES',{})
    scope=first.automatic_scope('1.0.1');notes='<!-- transcomic-build-id: '+'c'*64+' -->'
    c=first.FirstReleaseCommands(tmp_path/'gh.exe','a'*40,'b'*40,'c'*64,notes,[],scope=scope,read_only=True)
    publisher=first.FirstReleasePublisher(c)
    release={'id':7,'tag_name':'v1.0.1','draft':False,'prerelease':False,'body':notes,'assets':[],
        'html_url':release_url('v1.0.1'),'url':'https://api.github.com/repos/'+auto.REPO+'/releases/7','target_commitish':'b'*40}
    monkeypatch.setattr(publisher,'api',lambda endpoint:json.dumps([release]).encode())
    assert publisher.read('1.0.1')['id']==7 and not scope.out.exists()
