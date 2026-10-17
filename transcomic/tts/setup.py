"""One user action: assets, isolated runtime if needed, real inference/codecs."""
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import httpx
from .download import check_cancel,SetupCancelled
from .managed_runtime import ManagedRuntimes,nvidia_device
from .runtime import diagnostics
from .output import atomic_json


class RuntimeRegistry(ManagedRuntimes):
    def __init__(self,root,legacy=None):super().__init__(root);self.legacy=legacy;self.descriptor=legacy.descriptor if legacy else None
    def active(self):return super().active() or (self.legacy.active() if self.legacy else None)


def fingerprint(packs):
    data=diagnostics()
    return hashlib.sha256(json.dumps([packs.identity,nvidia_device(),data['runtimes'],data['providers']],sort_keys=True).encode()).hexdigest()


def prefer_cpu(directory,packs):
    path=Path(directory)/'setup-state.json'
    try:
        data=json.loads(path.read_text());return data.get('backend')=='CPUExecutionProvider' and data.get('gpu_failed') and data.get('fingerprint')==fingerprint(packs)
    except (OSError,ValueError):return False


class SetupFlow:
    def __init__(self,directory,models,packs,log=None):self.directory=Path(directory);self.models=models;self.packs=packs;self.log=log
    def probe(self,config,cancel,runtime=None,backend='CPUExecutionProvider'):
        from .process_engine import ProcessEngine
        from .managed_engine import ManagedEngine
        from .audio import encode
        engine=ManagedEngine(self.models,config,runtime) if runtime else ProcessEngine(self.models,config['variant'],backend,config.get('device_id',-1));done=threading.Event()
        def watch():
            while not done.wait(.1):
                if cancel.is_set():engine.cancel();return
        watcher=threading.Thread(target=watch,daemon=True);watcher.start()
        try:
            duration=engine.probe(config['voice'],config['speed'],config['language']);check_cancel(cancel)
            blocks=list(engine.synthesize('A new beginning.',config['voice'],config['speed'],config['language']));check_cancel(cancel)
            checks=self.directory/'Checks';checks.mkdir(parents=True,exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='probe-',dir=checks) as folder:
                codecs={fmt:encode(Path(folder)/('probe.'+fmt),iter(blocks),fmt) for fmt in ('wav','mp3')}
            return dict(compatible=True,model_ready=True,download_bytes=0,backend=backend,probe_seconds=duration,engine_process=engine.runtime_info,codecs=codecs,fallback_reason='')
        finally:done.set();engine.close();watcher.join(.5)
    def run(self,config,cancel,progress=lambda *args:None,client=None):
        check_cancel(cancel);progress(0,0,'Đang kiểm tra thiết bị')
        own=client is None;client=client or httpx.Client(timeout=httpx.Timeout(90,connect=15),trust_env=False)
        try:
            self.models.install(config['variant'],cancel,lambda a,b,c:progress(a,b,'Đang tải mô hình giọng đọc'),client)
            check_cancel(cancel);progress(0,0,'Đang kiểm tra dữ liệu')
            data=diagnostics();hardware=nvidia_device();gpu=bool(hardware and hardware['compatible']);local_gpu=data['compatible'] and 'CUDAExecutionProvider' in data['providers'];result=None;failure=''
            if gpu or local_gpu:
                try:
                    if local_gpu:progress(0,0,'Đang khởi tạo Kokoro');result=self.probe(config,cancel,backend='CUDAExecutionProvider')
                    else:
                        def probe(runtime):
                            nonlocal result
                            progress(0,0,'Đang kiểm tra tạo audio');result=self.probe(config,cancel,runtime,'CUDAExecutionProvider')
                        self.packs.install('CUDAExecutionProvider',client,cancel,probe,progress)
                except Exception as exc:
                    check_cancel(cancel)
                    if self.log:self.log.exception('Automatic CUDA setup failed; retain CPU path')
                    failure='GPU chưa sử dụng được; Kokoro vẫn hoạt động bằng CPU.'
            if result is None:
                progress(0,0,'Đang khởi tạo Kokoro')
                if data['compatible']:result=self.probe(config,cancel,backend='CPUExecutionProvider')
                else:
                    def probe_cpu(runtime):
                        nonlocal result
                        progress(0,0,'Đang kiểm tra tạo audio');result=self.probe(config,cancel,runtime,'CPUExecutionProvider')
                    self.packs.install('CPUExecutionProvider',client,cancel,probe_cpu,progress)
            check_cancel(cancel);result['fallback_reason']=failure;result['runtimes']=data['runtimes'];result['providers']=data['providers']
            atomic_json(self.directory/'setup-state.json',dict(backend=result['backend'],gpu_failed=bool(failure),fingerprint=fingerprint(self.packs),verified_at=time.time(),codecs=result['codecs']))
            progress(1,1,'Kokoro — Sẵn sàng');return result
        except Exception:
            check_cancel(cancel);raise
        finally:
            if own:client.close()
