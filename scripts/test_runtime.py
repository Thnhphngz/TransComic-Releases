"""Dedicated test data paths. Does not alter the application's production paths."""
import hashlib
import os
from pathlib import Path
import tempfile
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
SYSTEM_TEMP=Path(tempfile.gettempdir())

def outside(path):
    path=Path(os.path.abspath(path))
    local=Path(os.environ.get('LOCALAPPDATA',SYSTEM_TEMP))
    protected=[ROOT,local/'TransComic',local/'TransComicSigning',Path(ROOT.anchor)/'TransComic-SecureBackup']
    if any(path==base or path.is_relative_to(base) for base in protected):raise ValueError('Test runtime must be outside workspace and production data')
    for parent in (path,*path.parents):
        if parent.exists() or parent.is_symlink():
            info=parent.lstat()
            if parent.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('Test runtime reparse path')
    return path
def runtime_root():
    explicit=os.environ.get('TRANSCOMIC_TEST_RUNTIME')
    choices=[Path(explicit)] if explicit else ([Path(ROOT.anchor)/'TransComic-TestRuntime'] if os.name=='nt' else [])+[SYSTEM_TEMP/'TransComic-TestRuntime']
    for candidate in choices:
        try:
            path=outside(candidate);path.mkdir(parents=True,exist_ok=True)
            probe=path/('write-probe-'+uuid4().hex)
            with probe.open('xb'):pass
            probe.unlink()
            return path
        except (OSError,ValueError):
            if explicit:raise
    raise OSError('No writable external test runtime')
def session():
    project=hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    path=runtime_root()/'projects'/project/'runs'/('run-'+str(os.getpid())+'-'+uuid4().hex)
    outside(path);path.mkdir(parents=True);return path
def TemporaryDirectory(*args,**kwargs):
    if 'dir' not in kwargs:
        path=runtime_root()/'gui';path.mkdir(exist_ok=True);kwargs['dir']=path
    else:outside(kwargs['dir'])
    return tempfile.TemporaryDirectory(*args,**kwargs)
