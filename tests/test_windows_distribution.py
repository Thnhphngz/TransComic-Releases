"""Offline distribution media integrity and frozen-process boundaries."""
import hashlib
import json
from pathlib import Path
import pytest
from scripts.distribution_kit import REQUIRED,verify_kit


def media(tmp_path):
    content=b'fixture source';(tmp_path/'source.tar').write_bytes(content)
    record=dict(schema=1,components=sorted(REQUIRED),files={'source.tar':dict(bytes=len(content),sha256=hashlib.sha256(content).hexdigest())})
    (tmp_path/'manifest.json').write_text(json.dumps(record))
    return record


def test_corresponding_source_media_checks_actual_bytes(tmp_path):
    media(tmp_path);assert verify_kit(tmp_path)['files']==1
    (tmp_path/'source.tar').write_bytes(b'corrupt source')
    with pytest.raises(ValueError,match='hash mismatch'):verify_kit(tmp_path)


@pytest.mark.parametrize('case',['missing_component','unlisted_file','traversal','missing_file'])
def test_source_media_rejects_incomplete_or_unsafe_contents(tmp_path,case):
    record=media(tmp_path)
    if case=='missing_component':record['components'].remove('ffmpeg')
    elif case=='unlisted_file':(tmp_path/'unexpected.txt').write_text('unreviewed')
    elif case=='traversal':record['files']['../outside']=record['files'].pop('source.tar')
    else:(tmp_path/'source.tar').unlink()
    (tmp_path/'manifest.json').write_text(json.dumps(record))
    with pytest.raises((ValueError,OSError)):verify_kit(tmp_path)


def test_build_refuses_missing_source_media_before_invoking_tools(tmp_path,monkeypatch):
    import scripts.build_local as build
    monkeypatch.delenv('TRANSCOMIC_DISTRIBUTION_KIT',raising=False)
    def unexpected():raise AssertionError('No build tool may run')
    monkeypatch.setattr(build,'discover',unexpected)
    target=tmp_path/'never-built'
    assert build.main(['--output',str(target)])==2
    assert not target.exists()


def test_frozen_resource_hook_keeps_inference_outside_gui(monkeypatch):
    from scripts import tts_packaging as hook
    import PyInstaller.utils.hooks as hooks
    calls=[]
    monkeypatch.setattr(hook,'audit',lambda:dict(ready=True,runtimes=[('onnxruntime','1.24.4')]))
    monkeypatch.setattr(hooks,'collect_all',lambda package:(calls.append(package) or [],[],[]))
    monkeypatch.setattr(hooks,'copy_metadata',lambda package:[])
    data,_,hidden=hook.resources()
    assert {'numpy','soundfile','lameenc','psutil'}<=set(calls)
    assert not {'phonemizer','espeakng_loader','kokoro_onnx','onnxruntime','nvidia'}&set(calls)
    assert {'phonemizer','espeakng_loader','kokoro_onnx','onnxruntime','nvidia'}<=set(hook.FROZEN_EXCLUDES)
    assert 'PySide6.QtMultimedia' in hidden
    from transcomic.tts.managed_runtime import WORKER_FILES
    assert {Path(src).name for src,dest in data if dest.endswith('worker_source')}==set(WORKER_FILES)


def test_distribution_harness_rejects_normal_source_profile(monkeypatch):
    from transcomic.distribution_smoke import main
    monkeypatch.delenv('LOCALAPPDATA',raising=False)
    assert main()==2


def test_worker_bootstrap_native_paths_and_isolation_flags(tmp_path):
    import os,subprocess,sys
    from transcomic.tts.managed_engine import worker_command
    script=tmp_path/'entry.py'
    # The real Python process executes the same fixed bootstrap; dependencies
    # in this test are inert package fixtures rather than inference binaries.
    (tmp_path/'espeakng_loader.py').write_text("def get_data_path(): return __file__.replace('espeakng_loader.py','data')")
    (tmp_path/'unidic_lite.py').write_text("DICDIR=__file__.replace('unidic_lite.py','dictionary')")
    package=tmp_path/'phonemizer/backend/espeak';package.mkdir(parents=True)
    for folder in (package,package.parent,package.parent.parent):(folder/'__init__.py').write_text('')
    (package/'api.py').write_text('class EspeakAPI:\n def __init__(self,library,data_path):self.path=data_path\n')
    script.write_text('import json,sys,os\nfrom phonemizer.backend.espeak.api import EspeakAPI\n'
                     'data=os.path.abspath("x"*max(10,245-len(os.getcwd()))+"/data")\n'
                     'native=EspeakAPI("inert",data).path\n'
                     'print(json.dumps(dict(isolated=sys.flags.isolated,no_bytecode=sys.dont_write_bytecode,paths=sys.path,native_data=native,absolute_length=len(data))))')
    command=worker_command(dict(python=sys.executable,worker=script))
    # -I excludes the test fixture directory; use its own explicit runtime-like
    # path entry before running the production bootstrap in the child process.
    command[4]='import sys;sys.path.insert(0,'+repr(str(tmp_path))+');'+command[4]
    result=subprocess.run(command,cwd=tmp_path,capture_output=True,text=True,check=True)
    report=json.loads(result.stdout)
    assert report['isolated']==1 and report['no_bytecode']
    if os.name=='nt':
        assert all(p.startswith('\\\\?\\') for p in report['paths'])
        assert report['absolute_length']>230 and not os.path.isabs(report['native_data'])
        assert len(report['native_data'])<230
    assert not list(tmp_path.glob('__pycache__/*'))


def test_kit_rejects_stale_corresponding_worker_source(tmp_path):
    import ast
    from transcomic.tts.managed_runtime import WORKER_FILES
    repo=Path(__file__).resolve().parents[1];source=tmp_path/'source';kit=tmp_path/'kit';kit.mkdir()
    names=[*WORKER_FILES,'setup-catalog.json','calibration.json']
    for name in names:
        target=source/'transcomic/tts'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((repo/'transcomic/tts'/name).read_bytes())
        target=kit/'worker'/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((repo/'transcomic/tts'/name).read_bytes())
    text=(repo/'transcomic/tts/managed_engine.py').read_text(encoding='utf8')
    (source/'transcomic/tts/managed_engine.py').write_text(text,encoding='utf8')
    tree=ast.parse(text);bootstrap=next(n.value.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='WORKER_BOOTSTRAP' for t in n.targets))
    (kit/'worker/windows_bootstrap.py').write_bytes(bootstrap.encode('utf8'))
    lock=b'fixture lock';(source/'requirements-release.lock').write_bytes(lock)
    files={p.relative_to(kit).as_posix():dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in kit.rglob('*') if p.is_file()}
    (kit/'manifest.json').write_text(json.dumps(dict(schema=1,components=sorted(REQUIRED),files=files,release_lock_sha256=hashlib.sha256(lock).hexdigest())))
    assert verify_kit(kit,source)['files']==11
    (source/'transcomic/tts/engine.py').write_text('changed source')
    with pytest.raises(ValueError,match='Worker corresponding source is stale'):verify_kit(kit,source)


def test_auto_workers_use_verified_sidecar_metadata_without_gui_ort(monkeypatch):
    import builtins
    import onnxruntime as rt
    from transcomic.tts import concurrency
    monkeypatch.setattr(concurrency,'gpu_identity',lambda:'test-hardware')
    config=dict(variant='standard',revision='test',language='en-us',voice='af_heart',format='wav')
    native_key=concurrency.fingerprint(config)
    actual_import=builtins.__import__
    def absent(name,*args,**kwargs):
        if name=='onnxruntime':raise ModuleNotFoundError('GUI intentionally excludes inference')
        return actual_import(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',absent)
    child=dict(runtime=rt.__version__,providers=rt.get_available_providers())
    assert concurrency.fingerprint({**config,'_managed_engine':child})==native_key
    class NoCalibration:
        def one(self,*args):return None
    assert concurrency.selected(NoCalibration(),config)==1


def test_installer_preserves_user_data_and_replaceable_libraries():
    root=Path(__file__).resolve().parents[1]
    iss=(root/'installer/TransComic.iss').read_text(encoding='utf8')
    spec=(root/'TransComic.spec').read_text()
    assert 'recursesubdirs createallsubdirs' in iss
    assert '[UninstallDelete]' not in iss and 'CloseApplications=no' in iss
    assert 'exclude_binaries=True' in spec and 'COLLECT(exe, a.binaries, a.datas' in spec
    assert 'a.binaries=filter_native(a.binaries)' in spec


@pytest.mark.parametrize('name',['Qt6VirtualKeyboard.dll','qtvirtualkeyboardplugin.dll','Qt6Pdf.dll','Qt6Charts.dll','onnxruntime_providers_cuda.dll'])
def test_actual_payload_rejects_unreviewed_autocollected_native_modules(tmp_path,name):
    from scripts.tts_packaging import audit_payload
    (tmp_path/name).write_bytes(b'never executed fixture')
    with pytest.raises(ValueError,match='UNREVIEWED_NATIVE_PAYLOAD'):audit_payload(tmp_path)


def test_virtual_keyboard_is_filtered_without_removing_native_windows_input():
    from scripts.tts_packaging import filter_native
    entries=[('PySide6/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll','source','BINARY'),
             ('PySide6/Qt6VirtualKeyboard.dll','source','BINARY'),
             ('PySide6/plugins/platforms/qwindows.dll','source','BINARY')]
    assert filter_native(entries)==entries[-1:]


def test_frozen_worker_receives_private_application_dll_directories(tmp_path,monkeypatch):
    import sys
    from transcomic.tts.managed_engine import worker_command
    internal=tmp_path/'_internal';(internal/'PySide6').mkdir(parents=True)
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(sys,'_MEIPASS',str(internal),raising=False)
    monkeypatch.setenv('PATH','unchanged-user-path')
    import os
    command=worker_command(dict(python='python.exe',worker='worker.py'))
    assert command[1:4]==['-I','-B','-c']
    assert command[5:]==['worker.py',str(internal),str(internal/'PySide6')]
    assert os.environ['PATH']=='unchanged-user-path'


def test_source_worker_does_not_borrow_an_unrelated_frozen_directory(tmp_path,monkeypatch):
    import sys
    from transcomic.tts.managed_engine import worker_command
    monkeypatch.delattr(sys,'frozen',raising=False)
    monkeypatch.setattr(sys,'_MEIPASS',str(tmp_path),raising=False)
    assert worker_command(dict(python='python.exe',worker='worker.py'))[5:]==['worker.py']
