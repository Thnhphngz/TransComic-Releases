import hashlib
import io
import json
from pathlib import Path
import threading
import zipfile
import httpx
import pytest
from transcomic.tts.acceleration import AccelerationPacks


def fixture_pack(version=b'fake never executed'):
    entries={'python/python.exe':version,'worker/worker.py':b'verified worker fixture'};stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as archive:
        for path,data in entries.items():archive.writestr(path,data)
    data=stream.getvalue();descriptor=dict(protocol=1,url='https://github.com/Thnhphngz/TransComic-Releases/releases/download/gpu-test/pack.zip',sha256=hashlib.sha256(data).hexdigest(),size=len(data),python='python/python.exe',worker='worker/worker.py',files={p:dict(size=len(b),sha256=hashlib.sha256(b).hexdigest()) for p,b in entries.items()})
    return data,descriptor


def client(data):return httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,content=data)))


def test_verified_install_probe_before_activation_and_reuse_without_download(tmp_path):
    data,descriptor=fixture_pack();packs=AccelerationPacks(tmp_path/'AccelerationPacks',descriptor);seen=[]
    with client(data) as http:packs.install(http,threading.Event(),lambda runtime:seen.append(runtime['python'].read_bytes()))
    assert seen==[b'fake never executed'] and packs.active()['python'].exists()
    with httpx.Client(transport=httpx.MockTransport(lambda r:pytest.fail('No second download'))) as http:packs.install(http,threading.Event(),lambda r:None)


def test_failed_probe_keeps_previous_pointer_and_audio(tmp_path):
    data,descriptor=fixture_pack();root=tmp_path/'packs';root.mkdir();(root/'current.json').write_text(json.dumps(dict(active='previous')));audio=tmp_path/'audio.wav';audio.write_bytes(b'user audio fixture')
    def fail(runtime):raise RuntimeError('No CUDA driver fixture')
    with client(data) as http,pytest.raises(RuntimeError):AccelerationPacks(root,descriptor).install(http,threading.Event(),fail)
    assert json.loads((root/'current.json').read_text())['active']=='previous' and audio.read_bytes()==b'user audio fixture'


def test_added_unverified_binary_prevents_pack_activation(tmp_path):
    data,descriptor=fixture_pack();packs=AccelerationPacks(tmp_path/'packs',descriptor)
    with client(data) as http:runtime=packs.install(http,threading.Event(),lambda r:None)
    (runtime['folder']/'unverified.dll').write_bytes(b'never execute')
    with pytest.raises(ValueError,match='Unexpected installed'):packs.active()


def test_archive_checksum_cancel_and_path_traversal_rejected(tmp_path):
    data,descriptor=fixture_pack();called=[]
    with client(data+b'bad') as http,pytest.raises(ValueError):AccelerationPacks(tmp_path/'bad',descriptor).install(http,threading.Event(),lambda r:called.append(r))
    cancel=threading.Event();cancel.set()
    with client(data) as http,pytest.raises(InterruptedError):AccelerationPacks(tmp_path/'cancel',descriptor).install(http,cancel,lambda r:called.append(r))
    packs=AccelerationPacks(tmp_path/'paths',descriptor)
    for path in ('../escape.exe','C:/escape.exe','a\\b','/absolute.exe'):
        with pytest.raises(ValueError):packs.path(tmp_path,path)
    assert not called and not (tmp_path/'escape.exe').exists()


def test_explicit_rollback_only_to_trusted_verified_previous_pack(tmp_path):
    data,old=fixture_pack(b'old');new_data,new=fixture_pack(b'new');root=tmp_path/'packs'
    with client(data) as http:AccelerationPacks(root,old).install(http,threading.Event(),lambda r:None)
    packs=AccelerationPacks(root,new,previous=[old])
    with client(new_data) as http:packs.install(http,threading.Event(),lambda r:None)
    packs.rollback();assert packs.active()['python'].read_bytes()==b'old'


def test_setup_preserves_existing_gpu_and_never_calls_pip(tmp_path,monkeypatch):
    import scripts.setup_tts_runtime as setup
    from types import SimpleNamespace
    target=tmp_path/'.venv';target.mkdir();(target/'pyvenv.cfg').write_text('fixture');calls=[]
    monkeypatch.setattr(setup,'ROOT',tmp_path);monkeypatch.setattr(setup.subprocess,'run',lambda args,**kwargs:calls.append(args) or SimpleNamespace(returncode=0))
    setup.main();assert not any('pip' in item for args in calls for item in args) and (target/'.transcomic-ready').exists()


def test_actual_release_cpu_lock_still_rejects_gpu_only_environment():
    from importlib import metadata
    from scripts.release_config import static_configuration
    try:metadata.version('onnxruntime');cpu_present=True
    except metadata.PackageNotFoundError:cpu_present=False
    result=static_configuration(Path(__file__).resolve().parents[1])
    assert ('lock_missing:onnxruntime' in result['missing']) is not cpu_present
