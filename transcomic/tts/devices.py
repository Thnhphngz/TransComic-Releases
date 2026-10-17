"""Backend plans require a successful synthesis probe; Auto never assumes hybrid."""
from concurrent.futures import ThreadPoolExecutor
import time
from .engine import KokoroEngine,gpu_provider,memory_available
from .catalog import LANGUAGES

CPU='CPUExecutionProvider'


def backend_plan(mode):
    if mode=='CPU':return [CPU]
    gpu=gpu_provider()
    if mode=='Auto':return [gpu] if gpu else [CPU]
    if not gpu:raise RuntimeError('Không có GPU execution provider. Chọn CPU để tiếp tục.')
    if mode=='GPU':return [gpu]
    if mode=='Hybrid':
        if memory_available()<4*1024**3:raise MemoryError('Hybrid cần ít nhất 4 GiB RAM còn trống. Chọn CPU/GPU đơn.')
        return [CPU,gpu]
    raise ValueError('Chế độ thiết bị không hợp lệ')


def benchmark(manager,variant='standard',device_id=-1):
    """Explicit, fixed fixture benchmark. Never run automatically on app startup."""
    import psutil
    result={};fixture=[LANGUAGES['en-us'][2]]*4;process=psutil.Process()
    for mode in ('CPU','GPU','Hybrid'):
        start=time.perf_counter();before=process.memory_info().rss;peak=before
        try:
            backends=backend_plan(mode);engines=[KokoroEngine(manager,variant,b,device_id) for b in backends]
            for engine in engines:engine.probe('af_heart',1,'en-us')
            loaded=time.perf_counter();peak=max(peak,process.memory_info().rss)
            def work(pair):
                engine,texts=pair
                return sum(len(block)/24000 for text in texts for block in engine.synthesize(text,'af_heart',1,'en-us'))
            with ThreadPoolExecutor(len(engines)) as pool:
                duration=sum(pool.map(work,[(e,fixture[i::len(engines)]) for i,e in enumerate(engines)]))
            elapsed=time.perf_counter()-loaded;peak=max(peak,process.memory_info().rss)
            result[mode]=dict(providers=backends,seconds=elapsed,load_probe_seconds=loaded-start,audio_seconds=duration,
                              throughput=duration/elapsed,rss_bytes=peak,rss_delta_bytes=peak-before,error=None)
            del engines
        except Exception as exc:result[mode]=dict(error=f'{type(exc).__name__}: {exc}',seconds=time.perf_counter()-start)
    # Conservative Auto remains single backend until repeated, stable benchmark
    # and adapter-specific acceleration are established. Explicit hybrid works.
    return result
