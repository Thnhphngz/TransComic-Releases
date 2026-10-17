"""Versioned, cancellable asset installation independent of application updates."""
import hashlib
import json
import os
from pathlib import Path
import threading
from .catalog import ASSETS, MODELS, REPOSITORY, REVISION


class Cancelled(Exception): pass


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


class ModelManager:
    def __init__(self, directory):
        self.root=Path(directory)/REVISION
        self.lock=threading.RLock();self._verified={}

    def path(self,name):return self.root/Path(name)

    def safe(self,path):
        # Import at call time to keep the catalog/engine imports lightweight.
        from .output import safe_path
        return safe_path(path)

    def valid(self,name):
        path=self.path(name)
        try:
            self.safe(path);stat=path.stat();stamp=(stat.st_size,stat.st_mtime_ns)
            if path.is_symlink() or stat.st_size!=ASSETS[name]['size']:return False
            if self._verified.get(name)==stamp:return True
            if digest(path)!=ASSETS[name]['sha256']:return False
            self._verified[name]=stamp;return True
        except (OSError,ValueError):return False

    def required(self,variant='standard'):
        return [MODELS[variant]]+[n for n in ASSETS if n.startswith('voices/')]

    def size(self,variant='standard'):return sum(ASSETS[n]['size'] for n in self.required(variant) if not self.valid(n))

    def ready(self,variant='standard'):return all(self.valid(n) for n in self.required(variant))

    def install(self,variant='standard',cancel=None,progress=lambda *args:None,client=None):
        import httpx
        cancel=cancel or threading.Event()
        with self.lock:
            names=self.required(variant);total=sum(ASSETS[n]['size'] for n in names);done=0
            own=client is None;client=client or httpx.Client(follow_redirects=True,timeout=60,trust_env=False)
            try:
                for name in names:
                    if cancel.is_set():raise Cancelled('Đã hủy tải; file hợp lệ được giữ, file dở không được dùng.')
                    if self.valid(name):done+=ASSETS[name]['size'];progress(done,total,name);continue
                    path=self.safe(self.path(name));path.parent.mkdir(parents=True,exist_ok=True)
                    # No executable URLs/configuration from a server. Both revision
                    # and LFS hash are shipped in the reviewed application catalog.
                    from .download import fetch
                    record=dict(ASSETS[name],url=f'https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}')
                    try:fetch(client,record,path,cancel,lambda a,b:progress(done+a,total,name))
                    except InterruptedError as exc:raise Cancelled(str(exc)) from exc
                    self._verified.pop(name,None);done+=ASSETS[name]['size']
            finally:
                if own:client.close()
        return self.root

    def voices_pack(self):
        import numpy as np
        names=[n for n in ASSETS if n.startswith('voices/')]
        if not all(self.valid(n) for n in names):raise ValueError('Voice assets chưa được xác minh đầy đủ')
        pack=self.safe(self.root/'verified-voices.npz');metadata=self.safe(self.root/'verified-voices.json')
        if pack.exists() and metadata.exists():
            try:
                if json.loads(metadata.read_text(encoding='utf8'))['sha256']==digest(pack):return pack
            except (OSError,ValueError,KeyError):pass
        arrays={Path(n).stem:np.fromfile(self.path(n),dtype=np.float32).reshape(-1,1,256) for n in names}
        part=pack.with_suffix('.part')
        with part.open('wb') as stream:np.savez(stream,**arrays)
        os.replace(part,pack)
        metadata.write_text(json.dumps({'revision':REVISION,'sha256':digest(pack),'voices':sorted(arrays)}),encoding='utf8')
        return pack

    def remove(self):
        """Remove only catalog assets and derived pack; never recurse into audio."""
        with self.lock:
            for name in [*ASSETS,'verified-voices.npz','verified-voices.json']:
                path=self.safe(self.path(name))
                if path.is_file() and not path.is_symlink():path.unlink()
            self._verified.clear()
