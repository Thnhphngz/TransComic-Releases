"""No real HTTP, user data or runtime installation in offline regressions."""
import hashlib
import io
import json
from pathlib import Path
import threading
import zipfile
import httpx
import pytest
from transcomic.tts.download import fetch,SetupCancelled
from transcomic.tts.managed_runtime import unpack,member_path,catalog,ManagedRuntimes


def asset(data):return dict(url='https://files.pythonhosted.org/pinned.whl',size=len(data),sha256=hashlib.sha256(data).hexdigest())


def test_resume_after_interruption_and_restart_uses_range_and_does_not_redownload(tmp_path):
    data=b'abcdefghij';target=tmp_path/'asset';part=target.with_name('asset.download.part');part.write_bytes(data[:4]);seen=[]
    def respond(r):
        seen.append(r.headers.get('Range'));return httpx.Response(206,headers={'Content-Range':'bytes 4-9/10'},content=data[4:])
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:fetch(client,asset(data),target)
    assert seen==['bytes=4-'] and target.read_bytes()==data and not part.exists()
    with httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('verified asset must be reused'))) as client:fetch(client,asset(data),target)


@pytest.mark.parametrize('status',[200,503,404])
def test_server_without_resume_and_bounded_server_errors(tmp_path,status):
    data=b'fixture';part=tmp_path/'file.download.part';part.write_bytes(b'fi');calls=[]
    def response(r):calls.append(r);return httpx.Response(status,content=data)
    with httpx.Client(transport=httpx.MockTransport(response)) as client:
        if status==200:assert fetch(client,asset(data),tmp_path/'file').read_bytes()==data
        else:
            with pytest.raises(httpx.HTTPStatusError):fetch(client,asset(data),tmp_path/'file')
            assert len(calls)==(3 if status==503 else 1)


@pytest.mark.parametrize('failure',['hash','range','timeout','cancel','disk','permission'])
def test_failed_download_never_changes_installed_asset(tmp_path,monkeypatch,failure):
    import transcomic.tts.download as module
    target=tmp_path/'asset';target.write_bytes(b'previous verified runtime fixture');before=target.read_bytes();cancel=threading.Event()
    def response(r):
        if failure=='timeout':raise httpx.ReadTimeout('fixture timeout')
        return httpx.Response(206,headers={'Content-Range':'bytes 9-9/10'},content=b'x') if failure=='range' else httpx.Response(200,content=b'incorrect')
    if failure=='cancel':cancel.set()
    if failure=='disk':monkeypatch.setattr(module.shutil,'disk_usage',lambda p:type('Disk',(),{'free':0})())
    if failure=='permission':
        original=Path.open
        def denied(path,*a,**k):
            if path.name.endswith('.download.part'):raise PermissionError('fixture denied')
            return original(path,*a,**k)
        monkeypatch.setattr(Path,'open',denied)
    with httpx.Client(transport=httpx.MockTransport(response)) as client,pytest.raises((ValueError,httpx.TransportError,SetupCancelled,OSError)):fetch(client,asset(b'expected!'),target,cancel)
    assert target.read_bytes()==before


@pytest.mark.parametrize('name',['../escape','/absolute','C:/bad','a\\b','x/CON.dll','x/trailing.'])
def test_archive_paths_are_windows_safe(tmp_path,name):
    with pytest.raises(ValueError):member_path(tmp_path,name)


def test_zip_traversal_and_bomb_bound_and_cancel(tmp_path):
    archive=tmp_path/'pack'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('../escape.dll',b'bad')
    with pytest.raises(ValueError):unpack(archive,dict(kind='wheel'),tmp_path/'stage',threading.Event())
    assert not (tmp_path/'escape.dll').exists()
    with zipfile.ZipFile(archive,'w') as z:z.writestr('safe.dll',b'valid')
    cancel=threading.Event();cancel.set()
    with pytest.raises(SetupCancelled):unpack(archive,dict(kind='wheel'),tmp_path/'stage',cancel)


def test_catalog_has_exclusive_ort_profiles_pinned_artifacts_and_no_runtime_pip():
    lock=catalog();assert lock['platform']=='win_amd64';names={r['name']:r for r in lock['artifacts']}
    assert names['onnxruntime']['group']=='cpu' and names['onnxruntime-gpu']['group']=='cuda'
    assert names['nvidia-cudnn-cu12']['version']=='9.27.0.42'
    for r in [lock['python'],*lock['artifacts']]:assert r['size']>0 and len(r['sha256'])==64 and r['url'].startswith('https://') and r['license']
    assert lock['python']['version']=='3.13.14'


def test_forged_installed_manifest_cannot_authorize_modified_binary(tmp_path,monkeypatch):
    packs=ManagedRuntimes(tmp_path);folder=tmp_path/'fixture';folder.mkdir();path=folder/'python.exe';path.write_bytes(b'original')
    expected={'python.exe':dict(size=8,sha256=hashlib.sha256(b'original').hexdigest())}
    monkeypatch.setattr(packs,'expected',lambda backend:expected)
    path.write_bytes(b'tampered');forged={'python.exe':dict(size=8,sha256=hashlib.sha256(b'tampered').hexdigest())}
    (folder/'installed.json').write_text(json.dumps(dict(identity=packs.identity,backend='CPUExecutionProvider',files=forged)))
    with pytest.raises(ValueError,match='pinned archives'):packs.verify(folder,'CPUExecutionProvider')


def test_one_click_pipeline_awaits_probe_and_falls_back_cpu_without_prompt(tmp_path,monkeypatch):
    import transcomic.tts.setup as module
    events=[]
    class Models:
        def install(self,*a):events.append('model+voices')
    packs=type('Packs',(),{'identity':'fixture'})()
    monkeypatch.setattr(module,'diagnostics',lambda:dict(compatible=True,providers=['CUDAExecutionProvider','CPUExecutionProvider'],runtimes=[['onnxruntime-gpu','1.24.4']]))
    monkeypatch.setattr(module,'nvidia_device',lambda:dict(compatible=True))
    flow=module.SetupFlow(tmp_path,Models(),packs)
    def probe(config,cancel,runtime=None,backend=None):
        events.append(backend)
        if backend=='CUDAExecutionProvider':raise RuntimeError('fixture GPU failure')
        return dict(backend=backend,codecs={'wav':True,'mp3':True})
    monkeypatch.setattr(flow,'probe',probe)
    stages=[]
    with httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('no network'))) as client:result=flow.run(dict(variant='standard'),threading.Event(),lambda a,b,s:stages.append(s),client)
    assert events==['model+voices','CUDAExecutionProvider','CPUExecutionProvider'] and result['backend']=='CPUExecutionProvider'
    assert stages[-1]=='Kokoro — Sẵn sàng' and module.prefer_cpu(tmp_path,packs)
    monkeypatch.setattr(module,'nvidia_device',lambda:dict(compatible=True,driver_api=13000));assert not module.prefer_cpu(tmp_path,packs)


def test_cancel_does_not_mark_ready_or_overwrite_previous_state(tmp_path,monkeypatch):
    import transcomic.tts.setup as module
    path=tmp_path/'setup-state.json';path.write_text('previous');cancel=threading.Event()
    class Models:
        def install(self,*a):cancel.set()
    stages=[];flow=module.SetupFlow(tmp_path,Models(),None)
    with httpx.Client() as client,pytest.raises(SetupCancelled):flow.run(dict(variant='standard'),cancel,lambda a,b,s:stages.append(s),client)
    assert path.read_text()=='previous' and 'Kokoro — Sẵn sàng' not in stages


def test_managed_atomic_probe_failure_cancel_rollback_and_repair_preserve_previous(tmp_path):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:archive.writestr('python.exe',b'fake never executed')
    payload=stream.getvalue();record=dict(asset(payload),kind='python',name='python',group='base')
    packs=ManagedRuntimes(tmp_path/'Runtime',dict(python=record,artifacts=[]));audio=tmp_path/'audio.wav';audio.write_bytes(b'keep user fixture')
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=payload))) as client:
        current=packs.install('CPUExecutionProvider',client,threading.Event(),lambda r:None);pointer=(packs.root/'current.json').read_bytes()
        def fail(r):raise RuntimeError('injected probe failure, binary never executed')
        with pytest.raises(RuntimeError):packs.install('CUDAExecutionProvider',client,threading.Event(),fail)
        assert (packs.root/'current.json').read_bytes()==pointer and packs.active()['backend']=='CPUExecutionProvider'
        cancel=threading.Event();cancel.set()
        with pytest.raises(SetupCancelled):packs.install('CUDAExecutionProvider',client,cancel,lambda r:pytest.fail('cancelled before probe'))
        packs.install('CUDAExecutionProvider',client,threading.Event(),lambda r:None);packs.rollback();assert packs.active()['backend']=='CPUExecutionProvider'
        current['python'].write_bytes(b'corrupt')
        with pytest.raises(ValueError):packs.active()
        packs.install('CPUExecutionProvider',client,threading.Event(),lambda r:None);assert packs.active()['python'].read_bytes()==b'fake never executed'
        assert audio.read_bytes()==b'keep user fixture' and list(packs.root.glob('quarantine-*')) and not list(packs.root.glob('staging-*'))


def test_promoted_runtime_restart_verifies_windows_paths_longer_than_260(tmp_path):
    # Promotion replaces short staging-* with the full content hash. The leaf
    # must remain verifiable after restart, without LongPathsEnabled changes.
    leaf='Lib/site-packages/'+('nested/'*15)+'RuntimeOptimizationRecordContainerEntry.py'
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        archive.writestr('python.exe',b'fixture never executed');archive.writestr(leaf,b'verified long path')
    payload=stream.getvalue();record=dict(asset(payload),kind='python',name='python',group='base');lock=dict(python=record,artifacts=[])
    packs=ManagedRuntimes(tmp_path/'Runtime',lock)
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=payload))) as client:
        runtime=packs.install('CPUExecutionProvider',client,threading.Event(),lambda r:None)
    long_file=runtime['folder']/'python'/leaf
    assert len(str(long_file))>260 and long_file.read_bytes()==b'verified long path'
    assert ManagedRuntimes(tmp_path/'Runtime',lock).active()['python'].read_bytes()==b'fixture never executed'
