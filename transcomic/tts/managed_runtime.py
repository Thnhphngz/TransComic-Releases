"""Self-contained pinned CPython runtime in app data; no pip/system Python.

The app ships the lock and worker sources. Only reviewed upstream archives are
downloaded; activation follows integrity checks AND a real inference probe.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import platform
import shutil
import stat
import tarfile
import zipfile
from uuid import uuid4
from .download import fetch,check_cancel,verified
from .output import safe_path,atomic_json
from .models import digest

WORKER_FILES=('engine.py','models.py','catalog.py','adapters.py','japanese.py','output.py','audio.py','managed_worker.py')


def nvidia_device():
    """CUDA Driver API, not a dependency on nvidia-smi being in PATH."""
    if os.name!='nt' or platform.machine().lower() not in ('amd64','x86_64'):return None
    try:
        driver=ctypes.WinDLL('nvcuda.dll');version=ctypes.c_int();count=ctypes.c_int()
        if driver.cuInit(0) or driver.cuDriverGetVersion(ctypes.byref(version)) or driver.cuDeviceGetCount(ctypes.byref(count)) or count.value<1:return None
        major=ctypes.c_int();minor=ctypes.c_int()
        if driver.cuDeviceGetAttribute(ctypes.byref(major),75,0) or driver.cuDeviceGetAttribute(ctypes.byref(minor),76,0):return None
        return dict(driver_api=version.value,compute=[major.value,minor.value],compatible=version.value>=12000 and major.value>=5)
    except (OSError,AttributeError):return None


def catalog():return json.loads(Path(__file__).with_name('setup-catalog.json').read_text(encoding='utf8'))


def runtime_path(path):
    """Use long Win32 paths without depending on a machine-wide registry flag."""
    value=os.path.abspath(path)
    if os.name=='nt' and not value.startswith('\\\\?\\'):
        value='\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value
    return Path(value)


def member_path(root,name,check_parents=True):
    path=PurePosixPath(name)
    if not name or '\\' in name or ':' in name or path.is_absolute() or '..' in path.parts or any(p.rstrip(' .')!=p or p.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))} for p in path.parts):raise ValueError('Unsafe runtime archive path')
    target=root.joinpath(*path.parts)
    return safe_path(target) if check_parents else target


def unpack(archive,record,root,cancel):
    root=safe_path(runtime_path(root));root.mkdir(parents=True,exist_ok=True)
    checked={root}
    def destination(name):
        target=member_path(root,name,False)
        if target.parent not in checked:
            safe_path(target.parent);target.parent.mkdir(parents=True,exist_ok=True);checked.add(target.parent)
        return target
    if record['kind']=='sdist':
        with tarfile.open(archive,'r:gz') as packed:
            total=0;count=0
            for item in packed:
                count+=1;total+=item.size
                if count>40000 or total>5*1024**3:raise ValueError('Runtime source archive expansion exceeds limit')
                check_cancel(cancel);member_path(root,item.name,False)
                if not item.isfile():
                    if item.isdir():continue
                    raise ValueError('Links/devices are not allowed in runtime archives')
                parts=PurePosixPath(item.name).parts
                if len(parts)<2:continue
                name='/'.join(parts[1:]);package=record['package']
                if name.split('/')[0]!=package and not Path(name).name.upper().startswith(('LICENSE','COPYING','NOTICE')):continue
                if item.size>512*1024**2:raise ValueError('Oversized package member')
                target=destination(name if name.startswith(package+'/') else '_notices/'+record['name']+'/'+name)
                with packed.extractfile(item) as source,target.open('xb') as out:shutil.copyfileobj(source,out,1024**2)
    else:
        with zipfile.ZipFile(archive) as packed:
            items=packed.infolist();names=set();total=sum(i.file_size for i in items)
            if total>5*1024**3 or len(items)>40000:raise ValueError('Runtime archive expansion exceeds limit')
            if shutil.disk_usage(root).free<total+64*1024**2:raise OSError(28,'Không đủ dung lượng để chuẩn bị Kokoro')
            for item in items:
                check_cancel(cancel);member_path(root,item.filename,False)
                if item.is_dir():continue
                if stat.S_ISLNK(item.external_attr>>16):raise ValueError('Archive symlink rejected')
                name=item.filename
                if '.data/' in name:
                    _,kind,name=name.split('/',2)
                    if kind not in ('purelib','platlib'):continue
                if name.casefold() in names:raise ValueError('Duplicate runtime archive member')
                names.add(name.casefold());target=destination(name)
                if target.exists():
                    with packed.open(item) as source:expected=hashlib.file_digest(source,'sha256').hexdigest()
                    if target.stat().st_size==item.file_size and digest(target)==expected:continue
                    raise ValueError('Runtime package collision: '+name)
                with packed.open(item) as source,target.open('xb') as out:shutil.copyfileobj(source,out,1024**2)


class ManagedRuntimes:
    def __init__(self,root,lock=None):
        self.root=runtime_path(root);self.lock=lock if lock is not None else catalog();self.source=Path(__file__).parent/'worker_source'
        if not self.source.is_dir():self.source=Path(__file__).parent
        self.identity=hashlib.sha256(json.dumps(self.lock,sort_keys=True).encode()+b''.join((self.source/n).read_bytes() for n in WORKER_FILES)).hexdigest()
        self.descriptor=None  # compatible with the legacy optional-pack UI
        self._expected={}
    def records(self,backend):return [self.lock['python']]+[r for r in self.lock['artifacts'] if r['group'] in ('base','cuda' if backend=='CUDAExecutionProvider' else 'cpu')]
    def expected(self,backend):
        records=self.records(backend);paths=[safe_path(self.root/'Downloads'/r['sha256']) for r in records]
        stamp=tuple((p.stat().st_size,p.stat().st_mtime_ns) for p in paths)
        if backend in self._expected and self._expected[backend][0]==stamp:return self._expected[backend][1]
        result={}
        for record,path in zip(records,paths):
            if not verified(path,record):raise ValueError('Pinned runtime archive unavailable or corrupt')
            prefix='python/' if record['kind']=='python' else 'python/Lib/site-packages/'
            if record['kind']=='sdist':
                with tarfile.open(path,'r:gz') as packed:
                    for item in packed:
                        if not item.isfile():continue
                        parts=PurePosixPath(item.name).parts
                        if len(parts)<2:continue
                        name='/'.join(parts[1:]);package=record['package']
                        if name.split('/')[0]!=package:
                            if not Path(name).name.upper().startswith(('LICENSE','COPYING','NOTICE')):continue
                            name='_notices/'+record['name']+'/'+name
                        with packed.extractfile(item) as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
                        result[prefix+name]=dict(size=item.size,sha256=sha)
            else:
                with zipfile.ZipFile(path) as packed:
                    for item in packed.infolist():
                        if item.is_dir():continue
                        name=item.filename
                        if '.data/' in name:
                            _,kind,name=name.split('/',2)
                            if kind not in ('purelib','platlib'):continue
                        with packed.open(item) as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
                        result[prefix+name]=dict(size=item.file_size,sha256=sha)
        def add(name,data):result[name]=dict(size=len(data),sha256=hashlib.sha256(data).hexdigest())
        add('python/python313._pth',b'python313.zip\n.\nLib/site-packages\n../worker\n')
        add('worker/transcomic/__init__.py',b'');add('worker/transcomic/tts/__init__.py',b'')
        for name in WORKER_FILES:add('worker/managed_worker.py' if name=='managed_worker.py' else 'worker/transcomic/tts/'+name,(self.source/name).read_bytes())
        self._expected[backend]=(stamp,result);return result
    def runtime(self,folder,backend):return dict(folder=folder,python=folder/'python/python.exe',worker=folder/'worker/managed_worker.py',backend=backend,protocol=2)
    def verify(self,folder,backend):
        folder=runtime_path(folder)
        safe_path(folder);record=json.loads((folder/'installed.json').read_text(encoding='utf8'))
        if record['identity']!=self.identity or record['backend']!=backend:raise ValueError('Runtime catalog/source changed')
        if record['files']!=self.expected(backend):raise ValueError('Installed manifest does not match pinned archives/source')
        actual={}
        for directory,dirs,files in os.walk(folder,followlinks=False):
            for name in [*dirs,*files]:
                path=Path(directory)/name;info=path.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('Runtime reparse point rejected')
                if name in files:actual[path.relative_to(folder).as_posix()]=info
        if set(actual)!=set(record['files'])|{'installed.json'}:raise ValueError('Unlisted runtime files')
        for name,info in record['files'].items():
            path=member_path(folder,name,False)
            if actual[name].st_size!=info['size'] or digest(path)!=info['sha256']:raise ValueError('Installed runtime integrity failure')
        return self.runtime(folder,backend)
    def active(self):
        state=safe_path(self.root/'current.json')
        if not state.is_file():return None
        value=json.loads(state.read_text(encoding='utf8'));name=value['active']
        if name not in (self.identity+'-cpu',self.identity+'-cuda'):return None
        return self.verify(self.root/name,value['backend'])
    def install(self,backend,client,cancel,probe,progress=lambda *args:None):
        check_cancel(cancel)
        if os.name!='nt' or platform.machine().lower() not in ('amd64','x86_64'):raise RuntimeError('Runtime này cần Windows x64')
        root=safe_path(self.root);root.mkdir(parents=True,exist_ok=True);name=self.identity+('-cuda' if backend=='CUDAExecutionProvider' else '-cpu');target=safe_path(root/name)
        runtime=None
        if target.is_dir():
            try:runtime=self.verify(target,backend)
            except (OSError,ValueError,KeyError):pass  # repair via a fresh staging tree
        if runtime:probe(runtime)
        else:
            records=self.records(backend)
            total=sum(r['size'] for r in records);done=0;download=root/'Downloads';download.mkdir(exist_ok=True)
            staging=safe_path(root/('staging-'+uuid4().hex));staging.mkdir();(staging/'.setup-owned').write_text('tts-setup')
            try:
                for record in records:
                    check_cancel(cancel);path=fetch(client,record,download/record['sha256'],cancel,lambda a,b:progress(done+a,total,'Đang chuẩn bị tăng tốc GPU' if backend=='CUDAExecutionProvider' else 'Đang chuẩn bị Kokoro'))
                    unpack(path,record,staging/('python' if record['kind']=='python' else 'python/Lib/site-packages'),cancel);done+=record['size']
                package=staging/'worker/transcomic/tts';package.mkdir(parents=True)
                (package.parent/'__init__.py').write_text('');(package/'__init__.py').write_text('')
                for file in WORKER_FILES:
                    shutil.copyfile(self.source/file,staging/'worker/managed_worker.py' if file=='managed_worker.py' else package/file)
                (staging/'python/python313._pth').write_bytes(b'python313.zip\n.\nLib/site-packages\n../worker\n')
                (staging/'.setup-owned').unlink()
                files={p.relative_to(staging).as_posix():dict(size=p.stat().st_size,sha256=digest(p)) for p in staging.rglob('*') if p.is_file()}
                atomic_json(staging/'installed.json',dict(identity=self.identity,backend=backend,files=files))
                runtime=self.verify(staging,backend);check_cancel(cancel);probe(runtime);check_cancel(cancel)
                quarantine=None
                if target.exists():quarantine=safe_path(root/('quarantine-'+uuid4().hex));target.rename(quarantine)
                try:staging.rename(target)
                except BaseException:
                    if quarantine and not target.exists():quarantine.rename(target)
                    raise
                runtime=self.runtime(target,backend)
            except BaseException:
                # Only the random staging directory allocated in this call.
                if staging.parent.resolve()==root.resolve() and staging.name.startswith('staging-') and staging.exists():shutil.rmtree(safe_path(staging))
                raise
        check_cancel(cancel);old=json.loads((root/'current.json').read_text()) if (root/'current.json').exists() else {}
        atomic_json(root/'current.json',dict(active=name,backend=backend,previous=old.get('active')));return runtime
    def rollback(self):
        path=safe_path(self.root/'current.json');state=json.loads(path.read_text());previous=state.get('previous')
        if previous not in (self.identity+'-cpu',self.identity+'-cuda'):raise ValueError('No trusted previous runtime')
        backend='CUDAExecutionProvider' if previous.endswith('-cuda') else 'CPUExecutionProvider';self.verify(self.root/previous,backend)
        atomic_json(path,dict(active=previous,backend=backend,previous=state['active']))
