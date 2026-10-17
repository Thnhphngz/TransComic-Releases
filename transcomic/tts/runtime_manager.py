"""Probe the same killable engine used by jobs; no dependency installation."""
from .engine import providers
from .runtime import diagnostics,friendly


class RuntimeManager:
    def __init__(self,models,factory=None,packs=None,prefer_cpu=False):
        from .process_engine import ProcessEngine
        self.models=models;self.factory=factory or ProcessEngine;self.packs=packs;self.prefer_cpu=prefer_cpu

    def prepare(self,variant='standard',voice='af_heart',speed=1,language='en-us'):
        data=diagnostics();data.update(model_ready=self.models.ready(variant),download_bytes=self.models.size(variant),backend=None,fallback_reason='')
        if not data['model_ready']:return data
        available=providers();external=None
        if ('CUDAExecutionProvider' not in available or not data['compatible']) and self.packs:
            try:external=self.packs.active()
            except (OSError,ValueError) as exc:data['fallback_reason']='GPU pack không hợp lệ. '+friendly(exc)
        if not data['compatible'] and not external:return data
        backends=['CPUExecutionProvider'] if self.prefer_cpu else ['CUDAExecutionProvider','CPUExecutionProvider'] if 'CUDAExecutionProvider' in available or (external and external.get('backend','CUDAExecutionProvider')=='CUDAExecutionProvider') else ['CPUExecutionProvider']
        if backends==['CPUExecutionProvider']:data['fallback_reason']='CUDA không có trong runtime hiện tại; sử dụng CPU.'
        for backend in backends:
            engine=None
            try:
                if external and backend==external.get('backend','CUDAExecutionProvider'):
                    if external.get('protocol')==2:
                        from .managed_engine import ManagedEngine
                        engine=ManagedEngine(self.models,dict(variant=variant),external)
                    else:
                        from .pack_engine import PackEngine
                        engine=PackEngine(self.models,dict(variant=variant),external)
                else:engine=self.factory(self.models,variant,backend)
                data['probe_seconds']=engine.probe(voice,speed,language);data['engine_process']=engine.runtime_info;data['backend']=backend;data['compatible']=True
                return data
            except Exception as exc:
                if backend=='CPUExecutionProvider':raise
                data['fallback_reason']='Không thể khởi tạo GPU, đã chuyển sang CPU. '+friendly(exc)
                data['gpu_traceback']=getattr(exc,'technical_traceback',str(exc))
            finally:
                if engine:engine.close()
        return data
