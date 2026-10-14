"""Execute updater code extracted from the actual 0.1.1 EXE; never execute PE."""
import argparse,hashlib,importlib.abc,importlib.util,json,marshal,sys,threading
from pathlib import Path
from tempfile import TemporaryDirectory
from PyInstaller.archive.readers import CArchiveReader
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(allow_abbrev=False)
p.add_argument('--baseline',type=Path,required=True);p.add_argument('--current',required=True);p.add_argument('--version',required=True);p.add_argument('--assets',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--remote',action='store_true')
args=p.parse_args();EXE=args.baseline.resolve();OUT=args.output.resolve();OUT.mkdir(parents=True,exist_ok=True);tag='v'+args.version
archive=CArchiveReader(str(EXE)).open_embedded_archive('PYZ.pyz')
assert not any(n=='transcomic' or n.startswith('transcomic.') for n in sys.modules)
loaded={}
class FrozenBaseline(importlib.abc.MetaPathFinder,importlib.abc.Loader):
    def find_spec(self,name,path=None,target=None):
        if name=='transcomic' or name.startswith('transcomic.'):
            if name not in archive.toc:raise ImportError('Module absent from baseline EXE: '+name)
            return importlib.util.spec_from_loader(name,self,is_package=archive.toc[name][0]==1)
    def create_module(self,spec):return None
    def exec_module(self,module):
        code=archive.extract(module.__name__)
        loaded[module.__name__]=hashlib.sha256(marshal.dumps(code)).hexdigest()
        module.__file__=str(OUT/'frozen-baseline'/Path(*module.__name__.split('.')).with_suffix('.py'))
        exec(code,module.__dict__)
sys.meta_path.insert(0,FrozenBaseline())
from transcomic.version import VERSION,RELEASE_REPOSITORY
from transcomic.update.internal import InternalUpdateService
from transcomic.update.metadata import asset_url,release_url
from transcomic.update.windows_helper import (prepare_install_plan,AppProcessIdentity,ProductionUpdateHelper)
from transcomic.update.install import SafetySnapshot
from transcomic.update.windows_helper import INSTALL_APP_ID
from transcomic.version import APP_ID
assert INSTALL_APP_ID=='{CB58C770-47B7-42DC-A2CA-409DDF456487}' and APP_ID=='TransComic.Desktop'
import httpx
assert VERSION==args.current and RELEASE_REPOSITORY=='Thnhphngz/TransComic-Releases'
base=args.assets.resolve()
files={n:base/n for n in ('TransComic-Setup-'+args.version+'-windows-x64.exe','transcomic-update.json','SHA256SUMS.txt')}
real=args.remote
requests=[]
fixture={'tag_name':tag,'draft':False,'prerelease':False,'html_url':release_url(tag),
    'published_at':'OFFLINE_VALIDATION_ONLY','body':'Protocol fixture; not native update evidence',
    'assets':[{'name':n,'size':p.stat().st_size,'state':'uploaded','browser_download_url':asset_url(tag,n)} for n,p in files.items()]}
def response(request):
    url=str(request.url);requests.append(url)
    if url in ('https://api.github.com/repos/'+RELEASE_REPOSITORY+'/releases/latest',
                'https://api.github.com/repos/'+RELEASE_REPOSITORY+'/releases/tags/'+tag):
        return httpx.Response(200,json=fixture)
    for n,p in files.items():
        if url==asset_url(tag,n):return httpx.Response(200,content=p.read_bytes())
    raise AssertionError('Unexpected network target')
with TemporaryDirectory(prefix='TransComic-baseline-release-probe-') as tmp:
    updates=Path(tmp)/'Updates';installation=Path(tmp)/'Programs/TransComic'
    client=None if real else httpx.Client(transport=httpx.MockTransport(response))
    service=InternalUpdateService(directory=updates,client=client)
    result=service.check(manual=True)
    assert result.state=='UPDATE_AVAILABLE',result.message
    item=result.candidate
    assert item.version==args.version and item.signature_status=='VERIFIED_INTERNAL_HTTPS_SHA256'
    assert item.sha256==hashlib.sha256(files[item.filename].read_bytes()).hexdigest()
    assert item.size==files[item.filename].stat().st_size
    downloaded=service.download(item)
    assert downloaded.stat().st_size==files[item.filename].stat().st_size
    service.confirm_install(item)
    process=AppProcessIdentity(88,123456,str(installation/'TransComic.exe'))
    raw,plan=prepare_install_plan(service,item,downloaded,installation,process,
        SafetySnapshot(app_closed=True,safe_exit_verified=True))
    # FakeWindowsRuntime intentionally requires .testdata. This probe verifies
    # canonical .exe plans with production validation only, never helper.run.
    helper=ProductionUpdateHelper(updates,installation,policy='internal')
    validated_path,validated_item=helper.validate(plan)
    assert validated_path==downloaded and validated_item==item
    if client:client.close()
    proof={'passed':True,'baseline_version':VERSION,'baseline_exe_sha256':hashlib.sha256(EXE.read_bytes()).hexdigest(),
        'mode':'anonymous_real_GitHub_download_no_execution' if real else 'offline_production_protocol_fixture_no_execution',
        'modules_executed_from_packaged_PYZ':loaded,'candidate_version':item.version,'installer_size':item.size,
        'installer_sha256':item.sha256,'manifest_signature_status':item.signature_status,
        'check_download_confirm_prepare_plan':True,'native_installer_executions':0,'native_handoff_executions':0,
        'translation_api_requests':0,'user_data_accessed':False,'mock_request_urls':requests}
(OUT/('baseline-remote.json' if real else 'baseline-offline.json')).write_text(json.dumps(proof,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in proof.items() if k!='modules_executed_from_packaged_PYZ'}))
