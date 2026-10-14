import os
from pathlib import Path
import pytest
from scripts import test_runtime as runtime

def test_configured_cache_and_tmp_are_external_and_unique(pytestconfig,tmp_path):
    run=pytestconfig._transcomic_test_runtime
    assert not run.is_relative_to(runtime.ROOT)
    assert pytestconfig.cache._cachedir==run/'cache'
    assert tmp_path.is_relative_to(run/'tmp')
    other=runtime.session()
    assert other!=run and other.is_dir()

def test_runtime_rejects_workspace_and_production(monkeypatch):
    with pytest.raises(ValueError):runtime.outside(runtime.ROOT/'generated')
    production=Path(os.environ['LOCALAPPDATA'])/'TransComic'
    with pytest.raises(ValueError):runtime.outside(production/'test-data')

def test_gui_temp_uses_external_runtime():
    with runtime.TemporaryDirectory() as path:
        directory=Path(path)
        assert directory.is_relative_to(runtime.runtime_root()/'gui') and not directory.is_relative_to(runtime.ROOT)
