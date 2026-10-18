"""Six-asset verification remains strict and downloads each immutable asset."""
import hashlib,json,shutil,io,zipfile
import pytest
from scripts import release_120 as r
from scripts.first_internal_release import FirstReleaseCommands
from transcomic.release_adapters import Asset
from transcomic.update.internal import manifest
from transcomic.update.metadata import canonical,asset_url,release_url,UpdateError


@pytest.fixture
def publication(tmp_path,monkeypatch):
    monkeypatch.setattr(r,'ROOT',tmp_path);monkeypatch.setattr(r,'OUT',tmp_path);monkeypatch.setattr(r,'FOLDER',tmp_path)
    payload={name:b'fixture '+name.encode() for name in r.NAMES}
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as packed:packed.writestr('ThirdParty/manifest.json','{}')
    payload[r.EXTRAS[0]]=stream.getvalue()
    installer=payload[r.SCOPE.names[0]]
    payload['transcomic-update.json']=canonical(manifest('1.2.0',r.SCOPE.names[0],len(installer),hashlib.sha256(installer).hexdigest(),'2026-10-19T00:00:00Z'))
    payload['SHA256SUMS.txt']=''.join(hashlib.sha256(payload[n]).hexdigest()+'  '+n+'\n' for n in r.SCOPE.names[:2]).encode()
    for name,data in payload.items():(tmp_path/name).write_bytes(data)
    assets=[r.inspect_scoped_asset(r.SCOPE,n,tmp_path/n,tmp_path) for n in r.NAMES]
    commands=FirstReleaseCommands(shutil.which('gh'),'a'*40,'a'*40,'b'*64,'<!-- transcomic-build-id: '+'b'*64+' -->',assets,scope=r.SCOPE)
    publisher=r.SixAssetPublisher(commands);monkeypatch.setattr(publisher,'check_tag',lambda *args:True)
    remote={'id':123,'body':commands.notes,'url':'https://api.github.com/repos/Thnhphngz/TransComic-Releases/releases/123','target_commitish':'a'*40,'tag_name':'v1.2.0','draft':True,'prerelease':False,'html_url':release_url('v1.2.0'),
            'assets':[{'id':i+1,'name':a.name,'state':'uploaded','size':a.size,'digest':'sha256:'+a.sha256,'browser_download_url':asset_url('v1.2.0',a.name)} for i,a in enumerate(assets)]}
    calls=[]
    def download(commands,argv,*args):
        i=int(argv[2].rsplit('/',1)[1]);calls.append(i);return payload[assets[i-1].name]
    monkeypatch.setattr(r,'execute',download)
    return publisher,assets,remote,calls


def test_six_assets_downloaded_hashed_then_metadata_rechecked(publication):
    publisher,assets,remote,calls=publication
    assert publisher.verify('1.2.0',remote,assets)
    assert len(calls)==6
    remote.update(draft=False,published_at='2026-10-19T00:00:00Z')
    assert publisher.verify('1.2.0',remote,assets,published=True)
    assert len(calls)==6


@pytest.mark.parametrize('problem',['missing','digest','size','extra','duplicate'])
def test_bad_remote_asset_inventory_never_verifies(publication,problem):
    publisher,assets,remote,calls=publication
    if problem=='missing':remote['assets'].pop()
    elif problem=='digest':remote['assets'][0]['digest']='sha256:'+'0'*64
    elif problem=='size':remote['assets'][0]['size']+=1
    elif problem=='duplicate':remote['assets'].append(dict(remote['assets'][0],id=99))
    else:remote['assets'].append(dict(remote['assets'][0],name='unreviewed.bin',id=99))
    with pytest.raises(UpdateError):publisher.verify('1.2.0',remote,assets)


@pytest.mark.parametrize('name,member',[
    ('private.zip','ThirdParty/manifest.json'),
    ('TransComic-1.2.0-ThirdParty-Sources.zip','ThirdParty/../private.txt'),
    ('TransComic-1.2.0-ThirdParty-Sources.zip','private.txt'),
])
def test_source_asset_guard_rejects_unreviewed_archives(tmp_path,name,member):
    path=tmp_path/name
    with zipfile.ZipFile(path,'w') as packed:packed.writestr(member,'{}')
    with pytest.raises(UpdateError):r.inspect_scoped_asset(r.SCOPE,name,path,tmp_path)
