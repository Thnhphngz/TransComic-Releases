"""Offline release gates and staging inventory; no EXE/compiler execution."""
import importlib.util
import json
from pathlib import Path
import tomllib
import pytest
from scripts.rc_release_audit import records,validate,gate,cache_check


def test_shipped_95_artifacts_have_pins_and_exclusive_ort():
    lock,rows=records();validate(rows)
    assert len(rows)==95 and lock['platform']=='win_amd64'


@pytest.mark.parametrize('status',['FAIL','PARTIAL','NOT_RUN','BLOCKED'])
def test_unresolved_license_never_authorizes_build(status):
    assert gate(dict(packaging='PASS',license=status))=='BLOCKED — DO NOT RELEASE'
    assert gate(dict(packaging='PASS',license='PASS'))=='PASS'
    assert gate({})!='PASS'


def test_cache_partial_and_wrong_hash_not_accepted(tmp_path):
    _,rows=records();record=next(r for r in rows if r['category']=='runtime')
    (tmp_path/(record['sha256']+'.download.part')).write_bytes(b'incomplete')
    assert cache_check(record,[tmp_path],[])['status']=='NOT_CACHED'
    (tmp_path/record['sha256']).write_bytes(b'bad')
    assert cache_check(record,[tmp_path],[])['status']=='NOT_CACHED'


@pytest.mark.parametrize('bad',['architecture','checksum','credential_url'])
def test_manifest_bad_platform_checksum_or_secret_url_rejected(bad):
    _,rows=records();row=next(r for r in rows if r['name']=='onnxruntime')
    if bad=='architecture':row['url']=row['url'].replace('win_amd64','manylinux_2_17_x86_64')
    elif bad=='checksum':row['sha256']='fabricated'
    else:row['url']='https://example:secret@files.pythonhosted.org/pack.whl'
    with pytest.raises(ValueError):validate(rows)


def test_staged_tts_hook_catalog_worker_sources_and_notices_exist(tmp_path,monkeypatch):
    import scripts.build_local as build
    # Exercise staging and the actual resource hook with a CPU profile stub.
    # CPU dependencies are never installed over the working GPU environment.
    monkeypatch.setattr(build,'static_configuration',lambda root:dict(missing=[],qt_windows_plugin=True))
    from uuid import uuid4
    output=build.ROOT/'artifacts/rc-audit'/('staging-test-'+uuid4().hex)
    stage,report=build.prepare(build.ROOT,output)
    path=stage/'scripts/tts_packaging.py';assert path.is_file()
    spec=importlib.util.spec_from_file_location('staged_tts_packaging',path);hook=importlib.util.module_from_spec(spec);spec.loader.exec_module(hook)
    monkeypatch.setattr(hook,'audit',lambda:dict(ready=True,runtimes=[('onnxruntime','1.24.4')]))
    import PyInstaller.utils.hooks as hooks
    monkeypatch.setattr(hooks,'collect_all',lambda package:([],[],[]));monkeypatch.setattr(hooks,'copy_metadata',lambda package:[])
    datas,_,hidden=hook.resources()
    assert all(Path(source).is_file() for source,_ in datas)
    assert 'PySide6.QtMultimedia' in hidden
    assert any(dest=='transcomic/tts/worker_source' for _,dest in datas)
    assert json.loads((stage/'transcomic/tts/setup-catalog.json').read_text())==json.loads((build.ROOT/'transcomic/tts/setup-catalog.json').read_text())
    assert 'setup-catalog.json' in tomllib.loads((stage/'pyproject.toml').read_text())['tool']['setuptools']['package-data']['transcomic.tts']
    assert not report['install_allowed'] and not report['remote_release_allowed'] and not report['version_overlay']
    assert not any(n.endswith(('.db','.sqlite3','.key','.pfx','.docx','.wav','.mp3')) or n.startswith(('tests/','artifacts/')) for n in report['hashes'])
