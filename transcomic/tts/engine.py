"""Lazy Kokoro adapter and bounded backend selection; no Qt or translation API."""
import importlib.util
import threading
from .catalog import LANGUAGES, MODELS, voice_names

PHONEME_LOCK=threading.RLock()


def providers():
    try:
        import onnxruntime as rt
        return rt.get_available_providers()
    except ImportError:return []


def language_available(language):
    if language=='ja':return all(importlib.util.find_spec(n) is not None for n in ('misaki','jaconv','fugashi','unidic_lite'))
    if language=='cmn':return importlib.util.find_spec('misaki') is not None and importlib.util.find_spec('jieba') is not None
    return language in LANGUAGES


def memory_available():
    try:
        import psutil
        return psutil.virtual_memory().available
    except ImportError:return 0


def gpu_provider():
    available=providers()
    return next((name for name in ('CUDAExecutionProvider','DmlExecutionProvider') if name in available),None)


def chunks(text,limit=800):
    """Partition source characters exactly once, including whitespace."""
    while len(text)>limit:
        cut=max(text.rfind(' ',0,limit+1),text.rfind('\n',0,limit+1))
        if cut<limit//3:cut=limit
        else:cut+=1
        yield text[:cut];text=text[cut:]
    if text:yield text


class KokoroEngine:
    sample_rate=24000
    def __init__(self,manager,variant='standard',backend='CPUExecutionProvider',device_id=-1):
        import onnxruntime as rt
        from kokoro_onnx import Kokoro
        if not manager.ready(variant):raise ValueError('Chưa cài model/voice đã xác minh')
        if backend not in providers():raise ValueError('Execution provider không có trong runtime: '+backend)
        options=rt.SessionOptions();options.intra_op_num_threads=2;options.inter_op_num_threads=1
        options.log_severity_level=3
        self._profile=None;self.gpu_verified=False
        if backend!='CPUExecutionProvider':
            import tempfile
            from pathlib import Path
            from .adapters import preferred_device
            # CUDA ordinals enumerate NVIDIA devices, not DXGI's Intel/NVIDIA
            # adapter order. Do not pass a DXGI index into the CUDA provider.
            if device_id<0:device_id=preferred_device() if backend=='DmlExecutionProvider' else 0
            self._dll_directories=[]
            if backend=='CUDAExecutionProvider' and hasattr(rt,'preload_dlls'):
                import os
                # cuDNN loads engine sublibraries lazily. Loading cudnn64_9.dll
                # alone does not put its sibling DLLs on Windows' search path.
                roots=[]
                for name in ('nvidia.cudnn','nvidia.cublas','nvidia.cuda_runtime','nvidia.cufft','nvidia.curand','nvidia.cuda_nvrtc','nvidia.nvjitlink'):
                    try:spec=importlib.util.find_spec(name)
                    except ModuleNotFoundError:spec=None
                    if spec:
                        for root in spec.submodule_search_locations or []:
                            for child in ('bin','lib'):
                                directory=Path(root)/child
                                if directory.is_dir():roots.append(str(directory))
                if os.name=='nt':
                    for directory in roots:self._dll_directories.append(os.add_dll_directory(directory))
                    current=os.environ.get('PATH','').split(os.pathsep)
                    os.environ['PATH']=os.pathsep.join([p for p in roots if p not in current]+current)
                rt.preload_dlls(directory='')
            self._profile=tempfile.TemporaryDirectory(prefix='transcomic-tts-probe-',ignore_cleanup_errors=True)
            options.enable_profiling=True;options.profile_file_prefix=str(Path(self._profile.name)/'probe')
        if backend=='DmlExecutionProvider':
            options.enable_mem_pattern=False;options.execution_mode=rt.ExecutionMode.ORT_SEQUENTIAL
        provider_options={'device_id':device_id}
        if backend=='CUDAExecutionProvider':
            provider_options.update(gpu_mem_limit=2*1024**3,cudnn_conv_algo_search='DEFAULT',cudnn_conv_use_max_workspace='1',cudnn_conv1d_pad_to_nc1d='1',use_tf32='0')
        session=rt.InferenceSession(str(manager.path(MODELS[variant])),sess_options=options,
            providers=[(backend,provider_options)] if backend!='CPUExecutionProvider' else [backend])
        if session.get_providers()[0]!=backend:
            if self._profile:session.end_profiling();self._profile.cleanup();self._profile=None
            raise RuntimeError('GPU khởi tạo thất bại; runtime đã fallback. Chưa xác nhận GPU hoạt động.')
        if backend!='CPUExecutionProvider':session.disable_fallback()
        self.backend=backend;self.model=Kokoro.from_session(session,str(manager.voices_pack()))
        if self.model._input_dtypes.get('speed').kind not in 'fc':raise ValueError('Model không hỗ trợ speed liên tục 0.5–2.0')
        self._g2p={}
        self.inference_observer=None
        original_run=getattr(session,'run',None)
        def observed_run(*args,**kwargs):
            callback=self.inference_observer
            if callback:callback('start',threading.get_ident())
            try:return original_run(*args,**kwargs)
            finally:
                if callback:callback('end',threading.get_ident())
        if original_run:session.run=observed_run

    def synthesize(self,text,voice,speed,language):
        if not text.strip() or not .5<=speed<=2 or voice not in voice_names(language):raise ValueError('Văn bản/giọng/speed không hợp lệ')
        if not language_available(language):raise ValueError('Phonemizer cho ngôn ngữ này chưa sẵn sàng')
        for piece in chunks(text):
            if not piece.strip():continue
            if language in ('ja','cmn'):
                with PHONEME_LOCK:
                    if language not in self._g2p:
                        if language=='ja':
                            from .japanese import JAG2P
                            self._g2p[language]=JAG2P()
                        else:
                            from misaki.zh import ZHG2P
                            self._g2p[language]=ZHG2P()
                    phonemes=self._g2p[language](piece)
                    if isinstance(phonemes,tuple):phonemes=phonemes[0]
                audio,rate=self.model.create(phonemes,voice,speed,lang=language,is_phonemes=True)
            else:
                # Kokoro's espeak tokenizer has its own process-global lock.
                audio,rate=self.model.create(piece,voice,speed,lang=language)
            if rate!=self.sample_rate:raise ValueError('Sample rate engine không đúng manifest')
            yield audio

    def probe(self,voice,speed,language):
        import numpy as np
        profiled=self._profile is not None
        try:
            audio=next(self.synthesize(LANGUAGES[language][2],voice,speed,language))
            if len(audio)==0 or not np.isfinite(audio).all() or np.max(np.abs(audio))<1e-5:
                raise RuntimeError('Backend không tạo được audio hợp lệ')
        finally:
            if self._profile:
                import json
                from pathlib import Path
                profile=self.model.sess.end_profiling()
                events=json.loads(Path(profile).read_text(encoding='utf8'))
                self.gpu_verified=any(e.get('args',{}).get('provider')==self.backend for e in events)
                self.gpu_node_count=sum(e.get('args',{}).get('provider')==self.backend for e in events)
                self._profile.cleanup();self._profile=None
        if profiled and not self.gpu_verified:raise RuntimeError('Probe có audio nhưng không xác minh được node chạy GPU. Chọn CPU.')
        return len(audio)/self.sample_rate
