"""Optional verified GPU worker packs, outside installer/update/model folders.

Descriptors are shipped/trusted by the app, never accepted from an untrusted
URL at runtime. No official pack descriptor is published with this hotfix.
"""
import hashlib
import json
from pathlib import Path,PurePosixPath
import stat
import re
from uuid import uuid4
import zipfile
from .output import safe_path,atomic_json


class AccelerationPacks:
    def __init__(self,root,descriptor=None,previous=()):
        self.root=Path(root);self.descriptor=descriptor;self.known={d['sha256']:d for d in [*previous,*([descriptor] if descriptor else [])]}
    def validate_descriptor(self,descriptor):
        if not re.fullmatch('[0-9a-f]{64}',descriptor['sha256']) or descriptor.get('protocol')!=1:raise ValueError('Invalid trusted GPU pack descriptor')
    def path(self,root,relative):
        item=PurePosixPath(relative)
        if not relative or '\\' in relative or ':' in relative or item.is_absolute() or '..' in item.parts:raise ValueError('Unsafe pack path')
        return safe_path(root.joinpath(*item.parts))
    def verify(self,folder,descriptor):
        self.validate_descriptor(descriptor)
        # A verified interpreter can load neighbouring DLLs/modules too. Reject
        # added files, not only modified files listed in the trusted descriptor.
        actual=set()
        for path in folder.rglob('*'):
            safe_path(path)
            if path.is_file():actual.add(path.relative_to(folder).as_posix())
        if actual!=set(descriptor['files']):raise ValueError('Unexpected installed GPU pack contents')
        for relative,record in descriptor['files'].items():
            path=self.path(folder,relative)
            if not path.is_file() or path.stat().st_size!=record['size']:raise ValueError('GPU pack file size mismatch')
            sha=hashlib.sha256()
            with path.open('rb') as source:
                for block in iter(lambda:source.read(1024**2),b''):sha.update(block)
            if sha.hexdigest()!=record['sha256']:raise ValueError('GPU pack checksum mismatch')
        python=self.path(folder,descriptor['python']);worker=self.path(folder,descriptor['worker'])
        if descriptor['python'] not in descriptor['files'] or descriptor['worker'] not in descriptor['files']:raise ValueError('Unverified worker executable')
        return dict(python=python,worker=worker,folder=folder)
    def active(self):
        if not self.descriptor:return None
        state=self.root/'current.json'
        if not state.is_file():return None
        data=json.loads(state.read_text(encoding='utf8'))
        descriptor=self.known.get(data.get('active'))
        if not descriptor:return None
        return self.verify(safe_path(self.root/data['active']),descriptor)
    def install(self,client,cancel,probe):
        descriptor=self.descriptor
        if not descriptor:raise ValueError('Chưa có GPU acceleration pack chính thức được pin')
        self.validate_descriptor(descriptor)
        if not descriptor['url'].startswith('https://github.com/Thnhphngz/TransComic-Releases/releases/download/'):raise ValueError('Untrusted GPU pack source')
        if len(descriptor['sha256'])!=64 or descriptor['size']>4*1024**3:raise ValueError('Invalid GPU pack metadata')
        self.root=safe_path(self.root);self.root.mkdir(parents=True,exist_ok=True);target=safe_path(self.root/descriptor['sha256'])
        if target.is_dir():runtime=self.verify(target,descriptor)
        else:
            archive=safe_path(self.root/(descriptor['sha256']+'.zip.part'));sha=hashlib.sha256();size=0
            with client.stream('GET',descriptor['url'],follow_redirects=True) as response:
                response.raise_for_status()
                with archive.open('wb') as output:
                    for block in response.iter_bytes():
                        if cancel.is_set():raise InterruptedError('GPU pack download cancelled; CPU unchanged')
                        size+=len(block)
                        if size>descriptor['size']:raise ValueError('GPU pack exceeds declared size')
                        sha.update(block);output.write(block)
            if size!=descriptor['size'] or sha.hexdigest()!=descriptor['sha256']:raise ValueError('GPU archive checksum mismatch')
            staging=safe_path(self.root/('staging-'+uuid4().hex));staging.mkdir()
            with zipfile.ZipFile(archive) as packed:
                files=[i for i in packed.infolist() if not i.is_dir()]
                if len(files)!=len(descriptor['files']) or len({i.filename for i in files})!=len(files):raise ValueError('Unexpected GPU pack contents')
                if sum(i.file_size for i in files)>4*1024**3:raise ValueError('GPU pack too large')
                for item in files:
                    path=self.path(staging,item.filename)
                    if item.filename not in descriptor['files'] or stat.S_ISLNK(item.external_attr>>16):raise ValueError('Untrusted GPU pack entry')
                    record=descriptor['files'][item.filename]
                    if item.file_size!=record['size']:raise ValueError('GPU pack entry size mismatch')
                    path.parent.mkdir(parents=True,exist_ok=True)
                    with packed.open(item) as source,path.open('xb') as output:
                        for block in iter(lambda:source.read(1024**2),b''):
                            if cancel.is_set():raise InterruptedError('GPU pack extraction cancelled')
                            output.write(block)
            runtime=self.verify(staging,descriptor);staging.rename(target);runtime=self.verify(target,descriptor)
        # Probe BEFORE activation. Failure leaves the previous pointer untouched.
        probe(runtime)
        current=self.root/'current.json';old=json.loads(current.read_text()) if current.exists() else {}
        atomic_json(current,dict(active=descriptor['sha256'],previous=old.get('active')));return runtime
    def rollback(self):
        current=self.root/'current.json';data=json.loads(current.read_text())
        if not data.get('previous'):raise ValueError('No previous GPU pack')
        descriptor=self.known.get(data['previous'])
        if not descriptor:raise ValueError('Previous pack is not in the trusted catalog')
        self.verify(safe_path(self.root/data['previous']),descriptor)
        atomic_json(current,dict(active=data['previous'],previous=data['active']))


def packaged_descriptor():
    source=Path(__file__).with_name('gpu-pack.json')
    return json.loads(source.read_text(encoding='utf8')) if source.is_file() else None
